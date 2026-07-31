"""Confirmation-text variants, and the Telnyx call that sends it.

The guarantee that the facts come from the record lives in `tests/test_confirmation.py`.
"""

from __future__ import annotations

import logging
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


async def test_send_is_skipped_without_touching_the_network_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offline suite must not reach Telnyx to discover it has no credentials."""

    def explode(**_: Any) -> Any:
        raise AssertionError("send_sms opened a network client while unconfigured")

    monkeypatch.setattr(sms.httpx, "AsyncClient", explode)
    with pytest.raises(sms.SmsSkipped, match="TELNYX_API_KEY"):
        await sms.send_sms(REAL_NUMBER, "hello")


async def test_the_fictional_range_is_refused_before_the_network(
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telnyx would happily deliver to it, so this guard can never be delegated."""

    def explode(**_: Any) -> Any:
        raise AssertionError("send_sms tried to text the reserved fictional range")

    monkeypatch.setattr(sms.httpx, "AsyncClient", explode)
    with pytest.raises(sms.SmsSkipped, match="reserved for fiction"):
        await sms.send_sms(CALLER, "hello")


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


async def test_the_dialled_number_is_what_the_text_comes_from(
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller should see the business they rang, not some unrelated number."""
    sent: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        sent["body"] = httpx.Response(200, content=request.content).json()
        return httpx.Response(200, json={"data": {"id": "msg_456"}})

    _use_transport(monkeypatch, httpx.MockTransport(handle))

    await sms.send_sms(REAL_NUMBER, "hello", "+16042969870")
    assert sent["body"]["from"] == "+16042969870"


async def test_the_configured_number_is_the_fallback(
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing was dialled — the console and the REPL land here."""
    sent: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        sent["body"] = httpx.Response(200, content=request.content).json()
        return httpx.Response(200, json={"data": {"id": "msg_789"}})

    _use_transport(monkeypatch, httpx.MockTransport(handle))

    await sms.send_sms(REAL_NUMBER, "hello", None)
    assert sent["body"]["from"] == "+16045550000"


def test_a_dialled_number_is_enough_without_the_configured_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "telnyx_api_key", "KEY")
    monkeypatch.setattr(settings, "telnyx_from_number", "")
    assert not sms.can_send(REAL_NUMBER)
    assert sms.can_send(REAL_NUMBER, "+16042969870")


def test_every_skip_says_why() -> None:
    """The reason is the whole point: a text that silently never arrives is invisible."""
    assert "TELNYX_API_KEY" in (sms.skip_reason(REAL_NUMBER) or "")


def test_skip_reason_names_the_missing_from_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telnyx_api_key", "KEY")
    monkeypatch.setattr(settings, "telnyx_from_number", "")
    assert "TELNYX_FROM_NUMBER" in (sms.skip_reason(REAL_NUMBER) or "")


def test_skip_reason_is_none_when_it_can_go(telnyx_configured: Any) -> None:
    assert sms.skip_reason(REAL_NUMBER) is None


async def test_a_skipped_text_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="receptionist.services.sms"):
        with pytest.raises(sms.SmsSkipped):
            await sms.send_sms(REAL_NUMBER, "hello")
    assert "TELNYX_API_KEY" in caplog.text


async def test_a_sent_text_is_logged_without_its_body(
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The body carries a signed link, so it must never reach a log."""
    _use_transport(
        monkeypatch, httpx.MockTransport(lambda _: httpx.Response(200, json={"data": {"id": "m1"}}))
    )
    with caplog.at_level(logging.INFO, logger="receptionist.services.sms"):
        await sms.send_sms(REAL_NUMBER, "secret-link-token")
    assert "m1" in caplog.text
    assert "secret-link-token" not in caplog.text


async def test_a_rejection_is_logged_as_an_error(
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    rejection = {"errors": [{"code": "40300", "title": "Forbidden", "detail": "no profile"}]}
    _use_transport(monkeypatch, httpx.MockTransport(lambda _: httpx.Response(403, json=rejection)))
    with caplog.at_level(logging.ERROR, logger="receptionist.services.sms"):
        with pytest.raises(sms.SmsError):
            await sms.send_sms(REAL_NUMBER, "hello")
    assert "40300" in caplog.text


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


async def test_a_caller_who_never_spoke_is_marked_abandoned(tmp_path: Path) -> None:
    store = CallStore(tmp_path / "calls.db")
    record = CallRecord(profile_id="hvac", caller_number=CALLER)

    assert await finish_call(get_profile("hvac"), record, store=store) == ""
    assert record.outcome is Outcome.ABANDONED


async def test_a_caller_who_only_asked_a_question_was_answered_not_abandoned(
    tmp_path: Path,
) -> None:
    """No tool sets an outcome for a plain question, since the facts are in the prompt.
    Reporting that call as abandoned would misrepresent it to the business owner."""
    store = CallStore(tmp_path / "calls.db")
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.said("agent", "Thanks for calling.")
    record.said("caller", "what are your hours?")
    record.said("agent", "Monday to Saturday, 8 to 6.")

    text = await finish_call(get_profile("hvac"), record, store=store)

    assert record.outcome is Outcome.ANSWERED
    # Nothing to confirm, so nobody gets a text for asking the opening hours.
    assert text == ""


def _use_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """Make the one AsyncClient that send_sms opens use a stub transport."""
    original = httpx.AsyncClient

    def build(**kwargs: Any) -> httpx.AsyncClient:
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(sms.httpx, "AsyncClient", build)
