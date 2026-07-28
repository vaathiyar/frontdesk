"""The registry. Adding a vertical is one import and one entry."""

from __future__ import annotations

from receptionist.profiles.hvac import HVAC
from receptionist.profiles.profile import Profile
from receptionist.profiles.restaurant import RESTAURANT

PROFILES: dict[str, Profile] = {
    HVAC.id: HVAC,
    RESTAURANT.id: RESTAURANT,
}


class UnknownProfile(KeyError):
    """A profile we cannot serve — fail fast rather than mishandle a call."""


def get_profile(profile_id: str) -> Profile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise UnknownProfile(profile_id) from exc


__all__ = ["PROFILES", "Profile", "UnknownProfile", "get_profile"]
