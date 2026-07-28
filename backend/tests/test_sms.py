"""The confirmation text: what it says, and whether it gets sent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from receptionist.finish import finish_call
from receptionist.models import Booking, CallRecord, Message, Outcome
from receptionist.profiles import get_profile
from receptionist.services import sms
from receptionist.services.summary import compose_sms, confirmation, plain
from receptionist.settings import settings
from receptionist.store import CallStore
from tests.fakes import CALLER, ScriptedModel, says

REAL_NUMBER = "+16045551234"
STARTS = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)


def booked_call(**overrides: Any) -> CallRecord:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.BOOKED
    record.booking = Booking(
        service="furnace repair",
        starts_at=STARTS,
        ends_at=STARTS + timedelta(hours=1),
        calendar_event_id="evt_1",
        details={"name": "Sam Lee", "address": "12 Oak St, Burnaby", "issue": "no heat"},
    )
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


# --- what it says ---------------------------------------------------------------


def test_confirmation_states_the_business_service_and_time() -> None:
    text = confirmation(get_profile("hvac"), booked_call())

    assert "Helpdesk Heating and Cooling" in text
    assert "Booked: furnace repair" in text
    assert "10:00 AM" in text
    assert "12 Oak St, Burnaby" in text
    assert "Details + add to calendar:" in text


def test_confirmation_says_moved_for_a_reschedule() -> None:
    text = confirmation(get_profile("hvac"), booked_call(outcome=Outcome.RESCHEDULED))
    assert "Moved: furnace repair" in text
    assert "Booked:" not in text


def test_confirmation_covers_a_cancellation() -> None:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.CANCELLED
    assert "cancelled" in confirmation(get_profile("hvac"), record)


def test_confirmation_covers_a_taken_message() -> None:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.MESSAGE_TAKEN
    record.message = Message(name="Dana", reason="boiler quote")
    text = confirmation(get_profile("hvac"), record)

    assert "call you back" in text
    assert "Call details:" in text


def test_nothing_is_texted_when_the_call_produced_nothing() -> None:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.ABANDONED
    assert confirmation(get_profile("hvac"), record) == ""


async def test_the_model_writes_the_opening_and_code_writes_the_facts() -> None:
    record = booked_call()
    record.said("caller", "my furnace quit")
    model = ScriptedModel(replies=[says("Hi Sam, sorry about the furnace trouble.")])

    text = await compose_sms(get_profile("hvac"), record, model)

    assert text.startswith("Hi Sam, sorry about the furnace trouble.")
    assert "Booked: furnace repair" in text


async def test_a_failed_model_call_still_sends_the_facts() -> None:
    class Broken(ScriptedModel):
        def _generate(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("gemini is down")

    record = booked_call()
    record.said("caller", "my furnace quit")

    text = await compose_sms(get_profile("hvac"), record, Broken())

    assert "Booked: furnace repair" in text
    assert "10:00 AM" in text


async def test_an_abandoned_call_is_never_texted() -> None:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.ABANDONED
    record.said("caller", "never mind")
    assert await compose_sms(get_profile("hvac"), record, ScriptedModel()) == ""


async def test_the_message_stays_gsm7_so_it_costs_one_segment_per_160_chars() -> None:
    """A single em-dash or emoji drops SMS capacity from 160 characters to 70."""
    record = booked_call()
    record.said("caller", "my furnace quit")
    model = ScriptedModel(replies=[says("Hi Sam — you’re all set… 🎉 “great”")])

    text = await compose_sms(get_profile("hvac"), record, model)

    assert text.isascii()
    assert "—" not in text and "🎉" not in text
    assert "Hi Sam - you're all set..." in text


def test_plain_leaves_ordinary_text_alone() -> None:
    assert plain("Booked: furnace repair at 10:00 AM") == "Booked: furnace repair at 10:00 AM"


# --- whether it gets sent -------------------------------------------------------


@pytest.fixture
def telnyx_configured() -> Any:
    before = (settings.telnyx_api_key, settings.telnyx_from_number)
    settings.telnyx_api_key, settings.telnyx_from_number = "KEY", "+16045550000"
    yield
    settings.telnyx_api_key, settings.telnyx_from_number = before


def test_nothing_is_sent_without_credentials() -> None:
    assert not sms.can_send(REAL_NUMBER)


def test_the_reserved_fictional_range_is_never_texted(telnyx_configured: Any) -> None:
    """The dev REPL's default caller lives here, so a local run can't text a stranger."""
    assert not sms.can_send(CALLER)
    assert sms.can_send(REAL_NUMBER)


@pytest.mark.parametrize("number", ["", "6045551234", "+1", "not-a-number"])
def test_only_e164_numbers_are_texted(number: str, telnyx_configured: Any) -> None:
    assert not sms.can_send(number)


async def test_send_is_skipped_rather_than_failing_when_unconfigured() -> None:
    assert await sms.send_sms(REAL_NUMBER, "hello") is None


async def test_a_sent_message_posts_to_telnyx_and_returns_its_id(
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        sent["url"] = str(request.url)
        sent["auth"] = request.headers["Authorization"]
        sent["body"] = httpx.Response(200, content=request.content).json()
        return httpx.Response(200, json={"data": {"id": "msg_123"}})

    _use_transport(monkeypatch, httpx.MockTransport(handle))

    assert await sms.send_sms(REAL_NUMBER, "Booked: furnace repair") == "msg_123"
    assert sent["url"] == sms.TELNYX_MESSAGES
    assert sent["auth"] == "Bearer KEY"
    assert sent["body"] == {
        "from": "+16045550000",
        "to": REAL_NUMBER,
        "text": "Booked: furnace repair",
    }


async def test_a_telnyx_rejection_surfaces_its_reason(
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejection = {
        "errors": [
            {
                "code": "40300",
                "title": "Forbidden",
                "detail": "The from number is not assigned to a messaging profile.",
            }
        ]
    }
    _use_transport(monkeypatch, httpx.MockTransport(lambda _: httpx.Response(403, json=rejection)))

    with pytest.raises(sms.SmsError, match="40300"):
        await sms.send_sms(REAL_NUMBER, "hello")


# --- finishing the call ---------------------------------------------------------


async def test_finishing_saves_the_call_and_notes_the_text_was_not_sent(
    tmp_path: Path,
) -> None:
    store = CallStore(tmp_path / "calls.db")
    record = booked_call()
    record.said("caller", "my furnace quit")

    text = await finish_call(
        get_profile("hvac"), record, store=store, model=ScriptedModel(replies=[says("All set.")])
    )

    assert "Booked: furnace repair" in text
    assert record.ended_at is not None
    assert [e.type for e in record.events] == ["sms_skipped"]
    assert await store.get(record.id) is not None


async def test_a_failed_text_still_saves_the_call(
    tmp_path: Path, telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Losing the record because the text failed would be the worse of two failures."""
    _use_transport(monkeypatch, httpx.MockTransport(lambda _: httpx.Response(500, json={})))
    store = CallStore(tmp_path / "calls.db")
    record = booked_call(caller_number=REAL_NUMBER)
    record.said("caller", "my furnace quit")

    await finish_call(
        get_profile("hvac"), record, store=store, model=ScriptedModel(replies=[says("All set.")])
    )

    assert [e.type for e in record.events] == ["sms_failed"]
    saved = await store.get(record.id)
    assert saved is not None
    assert [e.type for e in saved.events] == ["sms_failed"]


async def test_an_unanswered_call_is_marked_abandoned(tmp_path: Path) -> None:
    store = CallStore(tmp_path / "calls.db")
    record = CallRecord(profile_id="hvac", caller_number=CALLER)

    assert await finish_call(get_profile("hvac"), record, store=store) == ""
    assert record.outcome is Outcome.ABANDONED


def _use_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """Make the one AsyncClient that send_sms opens use a stub transport."""
    original = httpx.AsyncClient

    def build(**kwargs: Any) -> httpx.AsyncClient:
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(sms.httpx, "AsyncClient", build)
