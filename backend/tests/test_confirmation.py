"""The text the caller gets after hanging up.

Every word of it is built from the record. A wrong time in a message going out under the
business's name is the one error that costs someone a morning, so nothing in the text is
narrated — and since nothing is narrated, there is no model call left on this path to go
wrong or to slow the text down.
"""

from __future__ import annotations

from receptionist.core.models import CallRecord
from receptionist.worker.lifecycle import finish_call
from receptionist.worker.messaging.compose import compose_sms
from receptionist.worker.profiles import get_profile
from tests.support.fakes import FakeCallStore


def test_the_facts_in_the_text_come_from_the_record(booked_record: CallRecord) -> None:
    text = compose_sms(get_profile("hvac"), booked_record)

    assert "Helpdesk Heating and Cooling" in text
    assert "Booked: Furnace repair" in text
    assert "Wed Jul 29, 10:00 AM" in text
    assert "12 Oak St, Burnaby" in text
    assert str(booked_record.id) in text


def test_the_text_says_each_thing_once(booked_record: CallRecord) -> None:
    """The business used to be named twice — once by the model, once by the facts — and
    the address twice in two different formats. That duplication is what retired the
    written opening, so it is worth a test rather than a comment."""
    text = compose_sms(get_profile("hvac"), booked_record)

    assert text.count("Helpdesk Heating and Cooling") == 1
    assert text.count("12 Oak St, Burnaby") == 1


def test_an_ordinary_booking_fits_in_two_segments(booked_record: CallRecord) -> None:
    """160 characters a segment, and the link alone is a third of one. Two is the floor
    while call ids are UUIDs; three was what the written opening cost."""
    text = compose_sms(get_profile("hvac"), booked_record)

    assert len(text) <= 320


async def test_finishing_a_call_saves_it_and_records_whether_the_caller_was_told(
    booked_record: CallRecord,
) -> None:
    """The saved record is the only evidence the call happened, and the only thing the
    link in the text can resolve to, so sending has to be recorded on it either way."""
    store = FakeCallStore()

    text = await finish_call(get_profile("hvac"), booked_record, store=store)

    assert "Booked: Furnace repair" in text
    assert booked_record.ended_at is not None
    # No Telnyx credentials in the test environment, so the send is skipped, not silent.
    assert [e.type for e in booked_record.events] == ["booking_created", "sms_skipped"]

    saved = await store.get(booked_record.id)
    assert saved is not None
    # Saved AFTER the send was recorded, not before — the whole reason `finish_call`
    # orders it that way is so the stored call says whether the caller was told.
    assert [e.type for e in saved.events] == ["booking_created", "sms_skipped"]
