"""Unit tests for the shared wire protocol: encoding, decoding, validation."""
import pytest

from webway.shared import protocol as p


def test_encode_decode_round_trip():
    payload = {"type": p.C_AUTH, "username": "alice", "password": "pw"}
    assert p.decode(p.encode(payload)) == payload


def test_decode_rejects_invalid_json():
    with pytest.raises(p.ProtocolError):
        p.decode("not json")


def test_decode_rejects_missing_type():
    with pytest.raises(p.ProtocolError):
        p.decode('{"username": "alice"}')


def test_require_str_trims_and_accepts():
    assert p.require_str({"name": "  general  "}, "name", 64) == "general"


def test_require_str_rejects_empty():
    with pytest.raises(p.ProtocolError):
        p.require_str({"name": "   "}, "name", 64)


def test_require_str_rejects_oversized():
    with pytest.raises(p.ProtocolError):
        p.require_str({"name": "x" * 100}, "name", 64)


def test_require_int_rejects_bool_and_non_int():
    with pytest.raises(p.ProtocolError):
        p.require_int({"channel_id": True}, "channel_id")
    with pytest.raises(p.ProtocolError):
        p.require_int({"channel_id": "1"}, "channel_id")
    assert p.require_int({"channel_id": 3}, "channel_id") == 3
