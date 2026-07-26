"""Auto repair — service bookings."""

from __future__ import annotations

from receptionist.profiles.base import Receptionist
from receptionist.profiles.fields import EMAIL, NAME, Field


class AutoReceptionist(Receptionist):
    profile_id = "auto"
    business_name = "Helpdesk Auto Services"
    greeting = "Thanks for calling Helpdesk Auto Services — how can I help?"

    def domain_prompt(self) -> str:
        return (
            "You book service appointments — oil changes, brakes, tires, check-engine "
            "diagnostics, batteries, and safety inspections."
        )

    def booking_fields(self) -> list[Field]:
        return [
            NAME,
            Field("vehicle", "vehicle year, make, and model"),
            Field("drop_off", "drop-off or wait"),
            EMAIL,
        ]

    def knowledge(self) -> str:
        return (
            "Hours: Monday to Friday, 7:30am to 5:30pm. Services: oil changes, brakes, "
            "tires, check-engine diagnostics, batteries, and safety inspections."
        )
