"""Restaurant — reservations. Owns its own config file (the menu)."""

from __future__ import annotations

import json
from pathlib import Path

from receptionist.core.models import CallRecord
from receptionist.profiles.base import Receptionist
from receptionist.profiles.fields import EMAIL, NAME, Field
from receptionist.services.calendar import CalendarService

_MENU_PATH = Path(__file__).parent / "data" / "restaurant_menu.json"


class RestaurantReceptionist(Receptionist):
    profile_id = "restaurant"
    business_name = "Helpdesk Kitchen"
    greeting = "Thanks for calling Helpdesk Kitchen!"

    def __init__(self, calendar: CalendarService, record: CallRecord) -> None:
        super().__init__(calendar, record)
        self._menu = json.loads(_MENU_PATH.read_text())

    def domain_prompt(self) -> str:
        return (
            "You take table reservations. Treat the 'service' as the table (e.g. "
            "'table for 4'). For parties larger than 8, offer to take a message for the "
            "manager instead of booking."
        )

    def booking_fields(self) -> list[Field]:
        return [NAME, Field("party_size", "party size"), EMAIL]

    def knowledge(self) -> str:
        items = "; ".join(f"{i['name']} (${i['price']})" for i in self._menu["items"])
        return f"Hours: Tuesday to Sunday, 5pm to 10pm. Menu: {items}."
