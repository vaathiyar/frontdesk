"""Which businesses we answer as. The registry: adding a vertical is one import, one entry.

Lives under `worker/` because a profile carries its agent's tool tuple — importing one
pulls in LangGraph — and nothing outside the worker needs it. The web service used to,
for `business_name`; that is now stamped onto `CallRecord` at call start precisely so this
package stays on one side of the seam.
"""

from __future__ import annotations

from receptionist.worker.profiles.hvac import HVAC
from receptionist.worker.profiles.profile import Profile
from receptionist.worker.profiles.restaurant import RESTAURANT

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
