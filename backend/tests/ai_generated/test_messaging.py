"""Confirmation-text variants, and the Telnyx call that sends it.

The guarantee that the facts come from the record lives in `tests/test_confirmation.py`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from receptionist.core.models import Booking, CallRecord, Message, Outcome
from receptionist.settings import settings
from receptionist.worker.lifecycle import finish_call
from receptionist.worker.messaging import telnyx as sms
from receptionist.worker.messaging.compose import compose_sms, plain
from receptionist.worker.profiles import get_profile
from tests.support.fakes import CALLER, FakeCallStore

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


def test_a_booking_states_the_business_service_time_and_place() -> None:
    text = compose_sms(get_profile("hvac"), booked_call())

    assert "Helpdesk Heating and Cooling" in text
    assert "Booked: Furnace repair" in text
    assert "Wed Jul 29, 10:00 AM" in text
    assert "12 Oak St, Burnaby" in text
    assert "Details: http" in text


def test_the_service_is_capitalised_without_flattening_an_acronym() -> None:
    """`book`'s `service` argument is the model's wording, so its case is not ours to
    trust -- but "AC" must not become "Ac"."""
    booking = Booking(service="AC tune-up", starts_at=STARTS, ends_at=STARTS)
    assert "Booked: AC tune-up" in compose_sms(get_profile("hvac"), booked_call(booking=booking))


def test_a_single_digit_day_is_not_zero_padded() -> None:
    starts = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    booking = Booking(service="furnace repair", starts_at=starts, ends_at=starts)
    text = compose_sms(get_profile("hvac"), booked_call(booking=booking))

    assert "Thu Jul 9, 10:00 AM" in text
    assert "Jul 09" not in text


def test_a_reschedule_says_moved() -> None:
    text = compose_sms(get_profile("hvac"), booked_call(outcome=Outcome.RESCHEDULED))
    assert "Moved: Furnace repair" in text
    assert "Booked:" not in text


def test_a_cancellation_claims_no_service_or_time_it_no_longer_has() -> None:
    """`tools.cancel` clears the booking, so there is nothing left to name. Saying so
    plainly beats reading it back out of an event summary."""
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.CANCELLED
    text = compose_sms(get_profile("hvac"), record)

    assert "Cancelled: your appointment" in text
    assert "AM" not in text and "PM" not in text


def test_a_taken_message_names_who_it_is_from() -> None:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.MESSAGE_TAKEN
    record.message = Message(name="Dana", reason="boiler quote")
    text = compose_sms(get_profile("hvac"), record)

    assert "Message taken for Dana" in text
    assert "call you back" in text


def test_every_variant_has_the_same_shape() -> None:
    """A caller who has had one of these should read the next at a glance."""
    cancelled = CallRecord(profile_id="hvac", caller_number=CALLER, outcome=Outcome.CANCELLED)
    for record in (booked_call(), cancelled):
        body = compose_sms(get_profile("hvac"), record).splitlines()
        assert body[0] == "Helpdesk Heating and Cooling"
        assert body[1] == ""
        assert ":" in body[2]
        assert body[-2] == ""
        assert body[-1].startswith("Details: ")


def test_nothing_is_texted_when_the_call_produced_nothing() -> None:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.ABANDONED
    assert compose_sms(get_profile("hvac"), record) == ""


def test_the_message_stays_gsm7_so_it_costs_one_segment_per_160_chars() -> None:
    """A single em-dash or emoji drops SMS capacity from 160 characters to 70. The model
    no longer writes prose, but the service and address are still its tool arguments."""
    booking = Booking(
        service="furnace “repair”",
        starts_at=STARTS,
        ends_at=STARTS,
        details={"address": "12 Oak St — Burnaby… 🎉"},
    )
    text = compose_sms(get_profile("hvac"), booked_call(booking=booking))

    assert text.isascii()
    assert 'Booked: Furnace "repair"' in text
    assert "12 Oak St - Burnaby..." in text


def test_plain_leaves_ordinary_text_alone() -> None:
    assert plain("Booked: furnace repair at 10:00 AM") == "Booked: furnace repair at 10:00 AM"


# --- whether it gets sent -------------------------------------------------------


def can_send(to: str, from_number: str | None = None) -> bool:
    """`skip_reason` inverted, which is how the assertions below want to read."""
    return sms.skip_reason(to, from_number) is None


@pytest.fixture
def telnyx_configured() -> Any:
    before = (settings.telnyx_api_key, settings.telnyx_from_number)
    settings.telnyx_api_key, settings.telnyx_from_number = "KEY", "+16045550000"
    yield
    settings.telnyx_api_key, settings.telnyx_from_number = before


def test_nothing_is_sent_without_credentials() -> None:
    assert not can_send(REAL_NUMBER)


def test_the_reserved_fictional_range_is_never_texted(telnyx_configured: Any) -> None:
    """The suite's default caller lives here, so a test run can't text a stranger."""
    assert not can_send(CALLER)
    assert can_send(REAL_NUMBER)


@pytest.mark.parametrize("number", ["", "6045551234", "+1", "not-a-number"])
def test_only_e164_numbers_are_texted(number: str, telnyx_configured: Any) -> None:
    assert not can_send(number)


async def test_send_is_skipped_without_touching_the_network_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offline suite must not reach Telnyx to discover it has no credentials."""

    def explode(**_: Any) -> Any:
        raise AssertionError("send_sms opened a network client while unconfigured")

    monkeypatch.setattr(sms.httpx, "AsyncClient", explode)
    with pytest.raises(sms.SmsSkipped, match="from-number"):
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
    assert not can_send(REAL_NUMBER)
    assert can_send(REAL_NUMBER, "+16042969870")


def test_every_skip_says_why(telnyx_configured: Any) -> None:
    """The reason is the whole point: a text that silently never arrives is invisible.

    Credentials are no longer among these — they stop the worker at startup, which
    `tests/test_startup_config.py` covers. What is left is about the call itself.
    """
    assert "reserved for fiction" in (sms.skip_reason(CALLER) or "")
    assert "not an E.164 number" in (sms.skip_reason("") or "")


def test_skip_reason_names_the_missing_from_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telnyx_api_key", "KEY")
    monkeypatch.setattr(settings, "telnyx_from_number", "")
    assert "TELNYX_FROM_NUMBER" in (sms.skip_reason(REAL_NUMBER) or "")


def test_skip_reason_is_none_when_it_can_go(telnyx_configured: Any) -> None:
    assert sms.skip_reason(REAL_NUMBER) is None


async def test_a_skipped_text_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="receptionist.worker.messaging.telnyx"):
        with pytest.raises(sms.SmsSkipped):
            await sms.send_sms(REAL_NUMBER, "hello")
    assert "from-number" in caplog.text


async def test_a_sent_text_is_logged_without_its_body(
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The body carries a signed link, so it must never reach a log."""
    _use_transport(
        monkeypatch, httpx.MockTransport(lambda _: httpx.Response(200, json={"data": {"id": "m1"}}))
    )
    with caplog.at_level(logging.INFO, logger="receptionist.worker.messaging.telnyx"):
        await sms.send_sms(REAL_NUMBER, "secret-link-token")
    assert "m1" in caplog.text
    assert "secret-link-token" not in caplog.text


async def test_a_rejection_is_logged_as_an_error(
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    rejection = {"errors": [{"code": "40300", "title": "Forbidden", "detail": "no profile"}]}
    _use_transport(monkeypatch, httpx.MockTransport(lambda _: httpx.Response(403, json=rejection)))
    with caplog.at_level(logging.ERROR, logger="receptionist.worker.messaging.telnyx"):
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
    telnyx_configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Losing the record because the text failed would be the worse of two failures."""
    _use_transport(monkeypatch, httpx.MockTransport(lambda _: httpx.Response(500, json={})))
    store = FakeCallStore()
    record = booked_call(caller_number=REAL_NUMBER)
    record.said("caller", "my furnace quit")

    await finish_call(get_profile("hvac"), record, store=store)

    assert [e.type for e in record.events] == ["sms_failed"]
    saved = await store.get(record.id)
    assert saved is not None
    assert [e.type for e in saved.events] == ["sms_failed"]


async def test_a_caller_who_never_spoke_is_marked_abandoned() -> None:
    store = FakeCallStore()
    record = CallRecord(profile_id="hvac", caller_number=CALLER)

    assert await finish_call(get_profile("hvac"), record, store=store) == ""
    assert record.outcome is Outcome.ABANDONED


async def test_a_caller_who_only_asked_a_question_was_answered_not_abandoned() -> None:
    """No tool sets an outcome for a plain question, since the facts are in the prompt.
    Reporting that call as abandoned would misrepresent it to the business owner."""
    store = FakeCallStore()
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
