from __future__ import annotations

from uuid import uuid4

from receptionist.core.links import sign, verify


def test_sign_is_deterministic() -> None:
    call_id = uuid4()
    assert sign(call_id, "s") == sign(call_id, "s")


def test_verify_accepts_matching_token() -> None:
    call_id = uuid4()
    assert verify(call_id, sign(call_id, "s"), "s")


def test_verify_rejects_wrong_token() -> None:
    call_id = uuid4()
    assert not verify(call_id, "not-the-token", "s")


def test_verify_rejects_token_for_a_different_id() -> None:
    a, b = uuid4(), uuid4()
    assert not verify(b, sign(a, "s"), "s")


def test_share_path_is_signed() -> None:
    from receptionist.core.models import CallRecord

    rec = CallRecord(profile_id="hvac", caller_number="+1-555-0100")
    path = rec.share_path()
    assert path.startswith(f"/c/{rec.id}?t=")
    token = path.split("t=", 1)[1]
    assert verify(rec.id, token)
