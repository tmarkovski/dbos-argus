"""Best-effort decoding of DBOS-stored output/error payloads into JSON.

DBOS stores workflow/step outputs in the `output` and `error` text columns
as base64-encoded serialized bytes. The `serialization` column tags the
format — `"py_pickle"` (default) or `"json"` (app-configured).

This module exposes `decode_dbos_value(raw, serialization)` which returns a
pretty-printed JSON string of the decoded value when possible, or `None`
when decoding isn't safe / possible.

Security: pickle payloads run through a *restricted* unpickler. Builtin
primitives, containers, and standard exception types are constructed
normally (see `_SAFE_BUILTINS`). Anything else — Pydantic models,
dataclasses, plain Python objects, even `os.system` — is replaced with an
inert `_OpaqueObject` proxy whose only behavior is to capture the pickle
state for the JSON encoder. We never import the user's module or invoke
the user's `__init__`, so a malicious pickle stream still can't execute
code; the JSON output for unknown classes is `{"__class__": "...", ...
fields}` with the dotted qualified name plus whatever fields BUILD
applied. This makes step outputs from real DBOS apps (which routinely
return Pydantic models or dataclasses) readable in Argus instead of
falling back to the raw base64 blob.
"""

from __future__ import annotations

import base64
import copyreg
import io
import json
import pickle
from typing import Any

# Allowlist of classes/functions the unpickler is allowed to actually invoke.
# Anything outside this set is replaced with an inert opaque proxy — see
# `_SafeUnpickler.find_class`.
_SAFE_BUILTINS: dict[str, set[str]] = {
    "builtins": {
        # Primitives & containers.
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "NoneType",
        "range",
        "set",
        "slice",
        "str",
        "tuple",
        # Standard exception types — their constructors just store *args,
        # which is safe to run. Letting them through means pickled error
        # payloads (DBOS's default for workflow/step failures) decode to a
        # human-readable `{type, message}` shape instead of being rejected.
        "ArithmeticError",
        "AssertionError",
        "AttributeError",
        "BaseException",
        "BufferError",
        "EOFError",
        "Exception",
        "FileExistsError",
        "FileNotFoundError",
        "IndexError",
        "InterruptedError",
        "IOError",
        "IsADirectoryError",
        "KeyError",
        "LookupError",
        "MemoryError",
        "NameError",
        "NotADirectoryError",
        "NotImplementedError",
        "OSError",
        "OverflowError",
        "PermissionError",
        "RecursionError",
        "RuntimeError",
        "StopAsyncIteration",
        "StopIteration",
        "SyntaxError",
        "SystemError",
        "TimeoutError",
        "TypeError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "UnicodeError",
        "UnicodeTranslateError",
        "ValueError",
        "ZeroDivisionError",
    },
    # `_reconstructor(cls, base, state)` is the standard helper the pickle
    # protocol generates for default object reductions. It calls
    # `base.__new__(cls)` (or `base(state)` if state is given). With our
    # opaque proxy in place of unknown `cls`, this resolves to
    # `object.__new__(opaque_proxy)` — no user code runs.
    "copyreg": {"_reconstructor"},
    # Stdlib value types whose constructors are pure data — no I/O, no
    # imports, no ambient state. Allowing them means real DBOS step
    # outputs (which routinely embed datetimes, decimals, UUIDs) decode
    # to the native Python value and our JSON encoder renders them as
    # ISO strings / decimal strings rather than as opaque dicts.
    "datetime": {"datetime", "date", "time", "timedelta", "timezone"},
    "decimal": {"Decimal"},
    "uuid": {"UUID"},
}


class _OpaqueObject:
    """Stand-in for unpickled instances whose class isn't on the safe list.

    Pickle reaches this class through several paths and we accept all of
    them without invoking user code:
      * REDUCE: `cls(*args)` — `__new__` captures positional args.
      * NEWOBJ / NEWOBJ_EX: `cls.__new__(cls, *args, **kwargs)` — same.
      * `copyreg._reconstructor`: `object.__new__(cls)` — empty args.
      * BUILD: applies state via `__setstate__`.

    We never import the user's module or call its `__init__` — the class
    is fabricated locally by `_make_opaque_class`, not resolved from the
    user's package. `__init__` is a no-op so pickle's REDUCE path doesn't
    crash on classes whose constructor would otherwise reject extra args.
    """

    __argus_qualname__: str  # set per subclass by `_make_opaque_class`

    def __new__(cls, *args: Any, **kwargs: Any) -> _OpaqueObject:
        instance = object.__new__(cls)
        if args or kwargs:
            object.__setattr__(instance, "__argus_args__", (list(args), kwargs))
        return instance

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # __new__ already captured anything we want; this no-op exists
        # because `object.__init__` rejects extra args on subclasses.
        pass

    def __setstate__(self, state: Any) -> None:
        object.__setattr__(self, "__argus_state__", state)


_OPAQUE_CACHE: dict[tuple[str, str], type] = {}


def _make_opaque_class(module: str, name: str) -> type:
    key = (module, name)
    cached = _OPAQUE_CACHE.get(key)
    if cached is not None:
        return cached
    cls = type(
        f"_Opaque__{module.replace('.', '_')}__{name}",
        (_OpaqueObject,),
        {"__argus_qualname__": f"{module}.{name}"},
    )
    _OPAQUE_CACHE[key] = cls
    return cls


class _SafeUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        allowed = _SAFE_BUILTINS.get(module, set())
        if name in allowed:
            if module == "copyreg":
                return getattr(copyreg, name)
            return super().find_class(module, name)
        return _make_opaque_class(module, name)


def _opaque_to_dict(value: _OpaqueObject) -> Any:
    qualname = type(value).__argus_qualname__
    state = getattr(value, "__argus_state__", None)
    args = getattr(value, "__argus_args__", None)
    # Pydantic v2 BUILD state shape:
    #   {"__dict__": {...real fields...},
    #    "__pydantic_extra__": ..., "__pydantic_fields_set__": ...,
    #    "__pydantic_private__": ...}
    # Surface just the fields — the surrounding metadata is implementation
    # detail and not useful in the UI.
    if isinstance(state, dict) and "__dict__" in state and "__pydantic_fields_set__" in state:
        fields = state.get("__dict__") or {}
        return {"__class__": qualname, **fields}
    if isinstance(state, dict):
        # Plain object / dataclass: state IS __dict__.
        return {"__class__": qualname, **state}
    if state is not None:
        return {"__class__": qualname, "__state__": state}
    if args is not None:
        # REDUCE-path classes (often __reduce__-only types like Enums).
        positional, keyword = args
        out: dict[str, Any] = {"__class__": qualname}
        if positional:
            out["__args__"] = positional
        if keyword:
            out["__kwargs__"] = keyword
        return out
    return {"__class__": qualname}


def _json_default(value: Any) -> Any:
    # Best-effort JSON fallback for otherwise non-encodable scalars that may
    # sneak out of safe unpickling (bytes, frozensets, exceptions, etc.).
    if isinstance(value, _OpaqueObject):
        return _opaque_to_dict(value)
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)}
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(value).decode("ascii")
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=lambda x: repr(x))
    # Stdlib value types we explicitly allowlist for unpickling — render
    # them as strings the UI can read directly.
    import datetime as _dt
    import decimal as _dec
    import uuid as _uuid

    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    if isinstance(value, _dt.tzinfo):
        return str(value)
    if isinstance(value, _dec.Decimal):
        return str(value)
    if isinstance(value, _uuid.UUID):
        return str(value)
    return repr(value)


def _pretty(value: Any) -> str | None:
    try:
        return json.dumps(value, indent=2, default=_json_default, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _try_json(raw: str) -> str | None:
    # JSON values may be stored either as a raw JSON string or as base64-
    # wrapped UTF-8 JSON bytes. Try direct first, then base64.
    try:
        return _pretty(json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        decoded = base64.b64decode(raw, validate=True)
        return _pretty(json.loads(decoded))
    except Exception:
        return None


def _try_safe_pickle(raw: str) -> str | None:
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception:
        return None
    try:
        value = _SafeUnpickler(io.BytesIO(data)).load()
    except Exception:
        return None
    return _pretty(value)


def decode_dbos_value(raw: str | None, serialization: str | None) -> str | None:
    """Decode a DBOS output/error payload into a pretty-printed JSON string.

    Returns None when the payload can't be decoded safely — callers should
    fall back to showing the raw on-disk value.
    """
    if raw is None:
        return None
    tag = (serialization or "").lower()
    if "json" in tag:
        return _try_json(raw)
    if "pickle" in tag or tag == "":
        return _try_safe_pickle(raw)
    return None
