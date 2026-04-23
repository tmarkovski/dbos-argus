import base64
import json
import pickle

from dbos_argus.decoding import decode_dbos_value


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


class _DangerousObject:
    """Module-level class so pickle can serialize it — the restricted
    unpickler should still refuse to reconstruct it on load."""


def test_decode_pickle_rejects_custom_class() -> None:
    raw = base64.b64encode(pickle.dumps(_DangerousObject())).decode("ascii")
    assert decode_dbos_value(raw, "py_pickle") is None


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
