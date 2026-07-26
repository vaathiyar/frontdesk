"""HVAC — the hero profile."""

from __future__ import annotations

from receptionist.profiles.base import Receptionist
from receptionist.profiles.fields import EMAIL, NAME, Field


class HvacReceptionist(Receptionist):
    profile_id = "hvac"
    business_name = "Helpdesk Heating and Cooling"
    greeting = "Thanks for calling Helpdesk Heating and Cooling — how can I help?"

    def domain_prompt(self) -> str:
        return (
            "You book service visits — furnace and AC repair, maintenance, and tune-ups. "
            "The service area is Burnaby, New Westminster, and Coquitlam; if a caller is "
            "outside it, take a message. There's a $119 service call fee, waived if the "
            "repair proceeds; install quotes are free."
        )

    def booking_fields(self) -> list[Field]:
        return [
            NAME,
            Field("address", "service address", confirm=True),
            Field("issue", "issue description"),
            EMAIL,
        ]

    def knowledge(self) -> str:
        return (
            "Hours: Monday to Saturday, 8am to 6pm. Service area: Burnaby, "
            "New Westminster, Coquitlam. Service call fee: $119, waived if the repair "
            "proceeds. Install quotes are free."
        )
