"""Best-effort decoding of DBOS-stored output/error payloads into JSON.

DBOS stores workflow/step outputs in the `output` and `error` text columns
as base64-encoded serialized bytes. The `serialization` column tags the
format — `"py_pickle"` (default) or `"json"` (app-configured).

This module exposes `decode_dbos_value(raw, serialization)` which returns a
pretty-printed JSON string of the decoded value when possible, or `None`
when decoding isn't safe / possible.

Security: for pickle payloads we use a *restricted* unpickler that only
allows a whitelist of builtin types. Custom classes, functions, and global
references are rejected, so a malicious pickle stream can't execute code.
The tradeoff is that any non-trivial Python object (custom classes,
exceptions, dataclasses) won't decode — callers fall back to showing the
raw base64.
"""

from __future__ import annotations

import base64
import io
import json
import pickle
from typing import Any

# Allowlist of builtin types referenced by pickle streams we'll expand. Anything
# outside this set causes the unpickler to raise, which we catch and treat as
# "undecodable".
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
}


class _SafeUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        allowed = _SAFE_BUILTINS.get(module, set())
        if name in allowed:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"disallowed class during unpickle: {module}.{name}")


def _json_default(value: Any) -> Any:
    # Best-effort JSON fallback for otherwise non-encodable scalars that may
    # sneak out of safe unpickling (bytes, frozensets, exceptions, etc.).
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)}
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(value).decode("ascii")
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=lambda x: repr(x))
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
