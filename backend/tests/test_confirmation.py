"""The text the caller gets after hanging up.

The model writes the warm opening; code writes the facts. A wrong time in a message
going out under the business's name is the one error that costs someone a morning.
"""

from __future__ import annotations

from typing import Any

from receptionist.core.models import CallRecord
from receptionist.worker.lifecycle import finish_call
from receptionist.worker.messaging.compose import compose_sms
from receptionist.worker.profiles import get_profile
from tests.support.fakes import FakeCallStore, ScriptedModel, says


async def test_the_facts_in_the_text_come_from_the_record_not_the_model(
    booked_record: CallRecord,
) -> None:
    model = ScriptedModel(replies=[says("Hi Sam, sorry about the furnace trouble.")])

    text = await compose_sms(get_profile("hvac"), booked_record, model)

    assert text.startswith("Hi Sam, sorry about the furnace trouble.")
    assert "Helpdesk Heating and Cooling" in text
    assert "Booked: furnace repair" in text
    assert "Wed Jul 29 at 10:00 AM" in text
    assert "12 Oak St, Burnaby" in text
    assert str(booked_record.id) in text


async def test_the_facts_still_go_out_when_the_model_call_fails(
    booked_record: CallRecord,
) -> None:
    class Broken(ScriptedModel):
        def _generate(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("gemini is down")

    text = await compose_sms(get_profile("hvac"), booked_record, Broken())

    assert "Booked: furnace repair" in text
    assert "Wed Jul 29 at 10:00 AM" in text


async def test_finishing_a_call_saves_it_and_records_whether_the_caller_was_told(
    booked_record: CallRecord,
) -> None:
    """The saved record is the only evidence the call happened, and the only thing the
    link in the text can resolve to, so sending has to be recorded on it either way."""
    store = FakeCallStore()
    model = ScriptedModel(replies=[says("All set.")])

    text = await finish_call(get_profile("hvac"), booked_record, store=store, model=model)

    assert "Booked: furnace repair" in text
    assert booked_record.ended_at is not None
    # No Telnyx credentials in the test environment, so the send is skipped, not silent.
    assert [e.type for e in booked_record.events] == ["booking_created", "sms_skipped"]

    saved = await store.get(booked_record.id)
    assert saved is not None
    # Saved AFTER the send was recorded, not before — the whole reason `finish_call`
    # orders it that way is so the stored call says whether the caller was told.
    assert [e.type for e in saved.events] == ["booking_created", "sms_skipped"]
