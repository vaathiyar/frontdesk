"""profile_id -> Receptionist subclass. Adding a vertical is one line here.

In Python a class is a first-class value, so this dict *is* the factory — look up
the class by its string key, then call it to build an instance. No factory class needed.
"""

from __future__ import annotations

from receptionist.core.models import CallRecord
from receptionist.profiles.base import Receptionist
from receptionist.profiles.hvac import HvacReceptionist
from receptionist.profiles.restaurant import RestaurantReceptionist
from receptionist.services.calendar import CalendarService


class UnknownProfile(KeyError):
    """Raised for a profile_id we can't serve — fail fast rather than mis-handle a call."""


PROFILES: dict[str, type[Receptionist]] = {
    "hvac": HvacReceptionist,
    "restaurant": RestaurantReceptionist,
}


def create_profile(profile_id: str, calendar: CalendarService, record: CallRecord) -> Receptionist:
    try:
        cls = PROFILES[profile_id]
    except KeyError as exc:
        raise UnknownProfile(profile_id) from exc
    return cls(calendar, record)
