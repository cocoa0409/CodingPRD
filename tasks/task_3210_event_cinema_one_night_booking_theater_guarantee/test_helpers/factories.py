"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "DISTRIBUTOR_NAME": "Kaleidoscope Concerts",
    "CONTACT_EMAIL": "prog@kaleidoscope.example",
    "SETTLEMENT_CURRENCY": "USD",
    # PRD §3.1: "every booking written under that licensor must carry a guarantee
    # at or above it". `TEST_DEFAULTS["GUARANTEE_CENTS"]` is the guarantee every
    # booking factory supplies, so the default floor must not exceed it or no
    # factory-built booking could be opened, submitted, or approved.
    "GUARANTEE_FLOOR_CENTS": 100000,
    "TICKET_PRICE_DEFAULT_CENTS": 1500,
    "CIRCUIT_NAME": "Silverline Cinemas",
    "CIRCUIT_CODE": "SILV",
    "THEATER_NAME": "Silverline Pasadena",
    "CITY": "Pasadena",
    "STATE_CODE": "CA",
    "TIMEZONE": "America/Los_Angeles",
    "SEATS_TOTAL": 200,
    "SCREEN_COUNT": 3,
    "SHOWTIME_BUFFER_MINUTES": 20,
    "TITLE_NAME": "Midnight Broadcast: Encore Anniversary",
    "AUDITORIUM": "AUD-1",
}


def create_distributor_payload(**overrides) -> dict:
    defaults = {
        "distributor_name": DEFAULTS["DISTRIBUTOR_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "settlement_currency": DEFAULTS["SETTLEMENT_CURRENCY"],
        "guarantee_floor_cents": DEFAULTS["GUARANTEE_FLOOR_CENTS"],
        "ticket_price_default_cents": DEFAULTS["TICKET_PRICE_DEFAULT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_circuit_payload(**overrides) -> dict:
    defaults = {
        "circuit_name": DEFAULTS["CIRCUIT_NAME"],
        "circuit_code": DEFAULTS["CIRCUIT_CODE"],
        "credit_rating": "B",
        "settlement_terms": "NET_30",
        "screen_pool_total": 2000,
        "on_sale_lead_days_min": 21,
    }
    defaults.update(overrides)
    return defaults


def create_theater_payload(circuit_id, **overrides) -> dict:
    defaults = {
        "circuit_id": circuit_id,
        "theater_name": DEFAULTS["THEATER_NAME"],
        "city": DEFAULTS["CITY"],
        "state_code": DEFAULTS["STATE_CODE"],
        "timezone": DEFAULTS["TIMEZONE"],
        "seats_total": DEFAULTS["SEATS_TOTAL"],
        "screen_count": DEFAULTS["SCREEN_COUNT"],
        "showtime_buffer_minutes": DEFAULTS["SHOWTIME_BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_title_payload(distributor_id, **overrides) -> dict:
    defaults = {
        "distributor_id": distributor_id,
        "title_name": DEFAULTS["TITLE_NAME"],
        "content_type": "ANNIVERSARY",
        "is_live": False,
        "duration_minutes": 120,
        "rights_start_utc": TEST_DEFAULTS["RIGHTS_START"],
        "rights_end_utc": TEST_DEFAULTS["RIGHTS_END"],
        "territory_state_codes": ["CA"],
        "max_screen_commitment": 120,
        "ticket_price_cents": TEST_DEFAULTS["TICKET_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def showtime_plan_element(index=1, date_utc=None, start_minute_utc=None,
                          auditorium=None) -> dict:
    return {
        "index": index,
        "date_utc": date_utc or TEST_DEFAULTS["SHOWTIME_DATE"],
        "start_minute_utc": (TEST_DEFAULTS["SHOWTIME_START_MINUTE"]
                             if start_minute_utc is None else start_minute_utc),
        "auditorium": auditorium or DEFAULTS["AUDITORIUM"],
    }


def create_booking_payload(title_id, circuit_id, **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "circuit_id": circuit_id,
        "showtime_count": 1,
        "showtime_plan": [showtime_plan_element()],
        "on_sale_at": TEST_DEFAULTS["ON_SALE_AT"],
        "guarantee_cents": TEST_DEFAULTS["GUARANTEE_CENTS"],
        "revenue_share_pct": TEST_DEFAULTS["REVENUE_SHARE_PCT"],
        "min_screens": 1,
        "pre_sale_threshold": 0,
    }
    defaults.update(overrides)
    return defaults


def create_booking_line_payload(theater_id, expected_booking_version, **overrides) -> dict:
    defaults = {
        "theater_id": theater_id,
        "committed_screens": 60,
        "expected_attendance": 100,
        "expected_booking_version": expected_booking_version,
    }
    defaults.update(overrides)
    return defaults


def create_content_delivery_payload(booking_id, expected_booking_version,
                                    **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "delivery_method": "FILE",
        "content_checksum": "sha256:aa11bb22",
        "scheduled_delivery_utc": "2026-11-25T00:00:00Z",
        "expected_booking_version": expected_booking_version,
    }
    defaults.update(overrides)
    return defaults


def create_encryption_key_payload(screening_id, **overrides) -> dict:
    defaults = {
        "screening_id": screening_id,
        "not_valid_before_utc": "2026-12-01T18:00:00Z",
        "not_valid_after_utc": "2026-12-01T22:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_feed_event_payload(booking_id, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "failure_type": "FEED_LOSS",
        "detected_at_utc": "2026-12-01T19:05:00Z",
        "outage_minutes": 20,
    }
    defaults.update(overrides)
    return defaults


def create_encore_window_payload(booking_id, expected_booking_version,
                                 **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "window_start_utc": "2026-12-10T00:00:00Z",
        "window_end_utc": "2026-12-20T00:00:00Z",
        "standard_ticket_price_cents": 1500,
        "encore_ticket_price_cents": 1000,
        "planned_screen_count": 25,
        "expected_booking_version": expected_booking_version,
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(booking_id, theater_id, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "theater_id": theater_id,
        "auditorium": DEFAULTS["AUDITORIUM"],
        "starts_at": "2026-12-01T19:00:00Z",
        "ends_at": "2026-12-01T21:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(booking_id, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "gross_box_office_cents": 3000000,
        "reported_line_count": 1,
        "topup_paid_cents": 0,
        "adjustment_cents": 0,
    }
    defaults.update(overrides)
    return defaults