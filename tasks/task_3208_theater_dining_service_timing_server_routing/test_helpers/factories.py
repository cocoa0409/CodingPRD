"""Payload factories — one per entity, client-supplied input fields only.

Fields the PRD declares as server-derived (status, computed instants, money
totals, id_check_status, version) are deliberately absent: a caller never
supplies them.
"""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "AUDITORIUM_NAME": "Theater 1",
    "SEAT_CAPACITY": TEST_DEFAULTS["SEAT_CAPACITY"],
    "SCREEN_LEAD_TIME_MINUTES": TEST_DEFAULTS["SCREEN_LEAD_TIME_MINUTES"],
    "KITCHEN_POINT_RATE": TEST_DEFAULTS["KITCHEN_POINT_RATE"],
    "ALCOVE_POINT_RATE": TEST_DEFAULTS["ALCOVE_POINT_RATE"],
    "SHOWTIME_TITLE": "Test Feature",
    "START_AT_UTC": "2026-09-01T20:00:00Z",
    "RUNTIME_MINUTES": TEST_DEFAULTS["RUNTIME_MINUTES"],
    "THEME_NAME": "Test Theme Night",
    "MENU_CATALOG_NAME": "Test Item",
    "MENU_PRICE_CENTS": 1000,
    "MENU_PREP_MINUTES": 1,
    "SERVER_DISPLAY_NAME": "Test Server",
    "THEME_PRICE_CENTS": 1100,
    "SEAT_NUMBER": 1,
    "REFUND_CENTS": 100,
}


def create_auditorium_payload(**overrides) -> dict:
    fields = {
        "name": DEFAULTS["AUDITORIUM_NAME"],
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
        "screen_lead_time_minutes": DEFAULTS["SCREEN_LEAD_TIME_MINUTES"],
        "kitchen_point_rate": DEFAULTS["KITCHEN_POINT_RATE"],
        "alcove_point_rate": DEFAULTS["ALCOVE_POINT_RATE"],
    }
    fields.update(overrides)
    return fields


def create_menu_item_payload(**overrides) -> dict:
    fields = {
        "catalog_name": DEFAULTS["MENU_CATALOG_NAME"],
        "channel": "ENTREE",
        "price_cents": DEFAULTS["MENU_PRICE_CENTS"],
        "prep_minutes": DEFAULTS["MENU_PREP_MINUTES"],
        "is_alcoholic": False,
    }
    fields.update(overrides)
    return fields


def create_showtime_payload(auditorium_id: str, **overrides) -> dict:
    fields = {
        "auditorium_id": auditorium_id,
        "title": DEFAULTS["SHOWTIME_TITLE"],
        "start_at_utc": DEFAULTS["START_AT_UTC"],
        "runtime_minutes": DEFAULTS["RUNTIME_MINUTES"],
        "content_type": "STANDARD",
    }
    fields.update(overrides)
    return fields


def create_server_payload(auditorium_id: str, **overrides) -> dict:
    fields = {
        "display_name": DEFAULTS["SERVER_DISPLAY_NAME"],
        "home_auditorium_id": auditorium_id,
    }
    fields.update(overrides)
    return fields


def create_programming_event_payload(auditorium_id: str, **overrides) -> dict:
    fields = {
        "auditorium_id": auditorium_id,
        "theme_name": DEFAULTS["THEME_NAME"],
        "requires_themed_menu": True,
    }
    fields.update(overrides)
    return fields


def create_themed_menu_item_payload(menu_item_id: str, **overrides) -> dict:
    fields = {
        "menu_item_id": menu_item_id,
        "theme_price_cents": DEFAULTS["THEME_PRICE_CENTS"],
        "is_signature": False,
    }
    fields.update(overrides)
    return fields


def create_section_assignment_payload(showtime_id: str, server_id: str, **overrides) -> dict:
    fields = {
        "showtime_id": showtime_id,
        "server_id": server_id,
        "section_label": "LEFT",
    }
    fields.update(overrides)
    return fields


def create_order_slip_payload(showtime_id: str, section_assignment_id: str,
                              expected_showtime_version, **overrides) -> dict:
    fields = {
        "showtime_id": showtime_id,
        "section_assignment_id": section_assignment_id,
        "seat_number": DEFAULTS["SEAT_NUMBER"],
        "lines": [{"menu_item_id": "", "quantity": 1}],
        "expected_showtime_version": expected_showtime_version,
    }
    fields.update(overrides)
    return fields


def create_disturbance_event_payload(order_slip_id: str, **overrides) -> dict:
    fields = {
        "order_slip_id": order_slip_id,
        "kind": "NO_TALKING",
    }
    fields.update(overrides)
    return fields


def order_line(menu_item_id: str, quantity: int = 1) -> dict:
    """A single entry of an order slip's `lines` array."""
    return {"menu_item_id": menu_item_id, "quantity": quantity}