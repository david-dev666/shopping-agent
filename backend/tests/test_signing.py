import hashlib

from app.adapters.signing import md5_sign


def test_sign_is_order_independent() -> None:
    assert md5_sign("s", {"b": "2", "a": "1"}) == md5_sign("s", {"a": "1", "b": "2"})


def test_sign_known_value() -> None:
    # secret="s", params {"a":"1","b":"2"} -> plain "sa1b2s"
    expected = hashlib.md5(b"sa1b2s").hexdigest().upper()
    assert md5_sign("s", {"a": "1", "b": "2"}) == expected
