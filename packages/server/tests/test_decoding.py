import base64
import json
import pickle
from dataclasses import dataclass

from dbos_argus.decoding import decode_dbos_value
from pydantic import BaseModel


def _b64_pickle(value: object) -> str:
    return base64.b64encode(pickle.dumps(value)).decode("ascii")


def test_decode_pickle_none() -> None:
    # This is the real payload DBOS writes for log_greeting / audit returns.
    assert decode_dbos_value("gAROLg==", "py_pickle") == "null"


def test_decode_pickle_str() -> None:
    raw = _b64_pickle("(parent) got: ok")
    assert decode_dbos_value(raw, "py_pickle") == '"(parent) got: ok"'


def test_decode_pickle_int_and_bool() -> None:
    assert decode_dbos_value(_b64_pickle(42), "py_pickle") == "42"
    assert decode_dbos_value(_b64_pickle(True), "py_pickle") == "true"


def test_decode_pickle_containers() -> None:
    raw = _b64_pickle({"a": [1, 2, 3], "b": (4, 5)})
    decoded = decode_dbos_value(raw, "py_pickle")
    assert decoded is not None
    # tuples become lists through JSON round-trip, which is fine for display.
    assert json.loads(decoded) == {"a": [1, 2, 3], "b": [4, 5]}


class _Plain:
    """Module-level class so pickle can serialize it. The unpickler doesn't
    know about it, so it should be surfaced as an opaque dict — not by
    importing this class or invoking its constructor."""

    def __init__(self, x: int = 0, y: str = "") -> None:
        self.x = x
        self.y = y


class _PydInner(BaseModel):
    label: str
    n: int


class _PydOuter(BaseModel):
    name: str
    items: list[_PydInner]


@dataclass
class _Point:
    x: int
    y: int


def test_decode_pickle_unknown_class_renders_as_opaque_dict() -> None:
    raw = base64.b64encode(pickle.dumps(_Plain(x=7, y="hi"))).decode("ascii")
    decoded = decode_dbos_value(raw, "py_pickle")
    assert decoded is not None
    parsed = json.loads(decoded)
    assert parsed["__class__"].endswith("._Plain")
    assert parsed["x"] == 7
    assert parsed["y"] == "hi"


def test_decode_pickle_pydantic_basemodel() -> None:
    obj = _PydOuter(
        name="hello",
        items=[_PydInner(label="a", n=1), _PydInner(label="b", n=2)],
    )
    raw = base64.b64encode(pickle.dumps(obj)).decode("ascii")
    decoded = decode_dbos_value(raw, "py_pickle")
    assert decoded is not None
    parsed = json.loads(decoded)
    assert parsed["__class__"].endswith("._PydOuter")
    assert parsed["name"] == "hello"
    assert parsed["items"][0]["__class__"].endswith("._PydInner")
    assert parsed["items"][0]["label"] == "a"
    assert parsed["items"][0]["n"] == 1
    assert parsed["items"][1]["label"] == "b"
    # Pydantic envelope keys should be stripped — they're noise to a viewer.
    assert "__pydantic_fields_set__" not in parsed
    assert "__pydantic_extra__" not in parsed


def test_decode_pickle_dataclass() -> None:
    raw = base64.b64encode(pickle.dumps(_Point(3, 4))).decode("ascii")
    decoded = decode_dbos_value(raw, "py_pickle")
    assert decoded is not None
    parsed = json.loads(decoded)
    assert parsed == {"__class__": parsed["__class__"], "x": 3, "y": 4}
    assert parsed["__class__"].endswith("._Point")


def test_decode_pickle_does_not_invoke_dangerous_globals() -> None:
    # Build a pickle stream by hand that resolves `os.system` and tries to
    # call it with "echo pwn". The opaque-proxy path must intercept the
    # GLOBAL lookup (returning an inert proxy class) so REDUCE produces
    # another proxy instead of executing the system call.
    payload = (
        b"\x80\x04"  # PROTO 4
        b"\x8c\x02os"  # SHORT_BINUNICODE 'os'
        b"\x8c\x06system"  # SHORT_BINUNICODE 'system'
        b"\x93"  # STACK_GLOBAL
        b"\x8c\x08echo pwn"  # SHORT_BINUNICODE 'echo pwn'
        b"\x85"  # TUPLE1
        b"R"  # REDUCE
        b"."  # STOP
    )
    raw = base64.b64encode(payload).decode("ascii")
    decoded = decode_dbos_value(raw, "py_pickle")
    # Whether this decodes to a proxy dict or fails entirely is fine — the
    # important guarantee is that calling os.system did NOT happen, which
    # would otherwise have side-effected the shell. The proxy class's
    # __init__ accepts and discards the args.
    if decoded is not None:
        parsed = json.loads(decoded)
        assert parsed.get("__class__") == "os.system" or "echo pwn" not in decoded


def test_decode_json_raw_string() -> None:
    decoded = decode_dbos_value('{"a":1}', "json")
    assert decoded is not None
    assert json.loads(decoded) == {"a": 1}


def test_decode_json_base64_wrapped() -> None:
    raw = base64.b64encode(b'{"a":1}').decode("ascii")
    decoded = decode_dbos_value(raw, "json")
    assert decoded is not None
    assert json.loads(decoded) == {"a": 1}


def test_decode_none_returns_none() -> None:
    assert decode_dbos_value(None, "py_pickle") is None
    assert decode_dbos_value(None, "json") is None


def test_decode_garbage_returns_none() -> None:
    assert decode_dbos_value("not-base64!!", "py_pickle") is None
    assert decode_dbos_value("not-json", "json") is None


def test_decode_pickled_exception() -> None:
    raw = _b64_pickle(ValueError("simulated transient failure for 'argus'"))
    decoded = decode_dbos_value(raw, "py_pickle")
    assert decoded is not None
    parsed = json.loads(decoded)
    assert parsed == {
        "type": "ValueError",
        "message": "simulated transient failure for 'argus'",
    }
