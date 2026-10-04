"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "STATION_CODE": "DFW",
    "STATION_NAME": "Dallas Fort Worth",
    "STATION_TIMEZONE": "America/Chicago",
    "STATION_MIN_REST": 10,
    "STATION_TRANSPORT_MIN": 30,
    "STATION_ROOM_COMMITMENT": 40,
    "UNION_NAME": "APA-2026",
    "UNION_MIN_REST": 10,
    "UNION_MAX_VARIANCE": 10.0,
    "VENDOR_NAME": "Test Hotel",
    "VENDOR_EMAIL": "ops@testhotel.example",
    "VENDOR_QUIET_ROOMS": 20,
    "CYCLE_TITLE": "2026 crew hotel",
    "CYCLE_DEADLINE": "2026-11-10T00:00:00Z",
    "CYCLE_TARGET_ROOMS": 5,
    "CYCLE_BUDGET_CAP": 1_000_000,
    "PROPOSAL_ROOMS": 5,
    "PROPOSAL_RATE": 9000,
    "AWARD_BLOCK": 5,
    "AWARD_START": "2026-10-01T00:00:00Z",
    "AWARD_END": "2026-10-11T00:00:00Z",
    "AWARD_LATE_CANCEL_HOURS": 24,
    "LAYOVER_CREW_COUNT": 2,
    "LAYOVER_ARRIVAL": "2026-10-02T18:00:00Z",
    "LAYOVER_DEPARTURE": "2026-10-03T09:00:00Z",
    "LAYOVER_REQUIRED_REST": 12,
    "STAY_DATE": "2026-10-02T00:00:00Z",
}


def create_station_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["STATION_CODE"],
        "name": DEFAULTS["STATION_NAME"],
        "timezone": DEFAULTS["STATION_TIMEZONE"],
        "min_rest_hours": DEFAULTS["STATION_MIN_REST"],
        "transport_time_minutes": DEFAULTS["STATION_TRANSPORT_MIN"],
        "room_availability_commitment": DEFAULTS["STATION_ROOM_COMMITMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_union_agreement_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["UNION_NAME"],
        "crew_type": "PILOT",
        "min_rest_hours": DEFAULTS["UNION_MIN_REST"],
        "quiet_room_required": False,
        "min_room_standard": "STANDARD",
        "blackout_protection_required": False,
        "max_invoice_variance_pct": DEFAULTS["UNION_MAX_VARIANCE"],
    }
    defaults.update(overrides)
    return defaults


def create_hotel_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENDOR_NAME"],
        "contact_email": DEFAULTS["VENDOR_EMAIL"],
        "security_certified": True,
        "quiet_rooms_count": DEFAULTS["VENDOR_QUIET_ROOMS"],
    }
    defaults.update(overrides)
    return defaults


def create_rfp_cycle_payload(**overrides) -> dict:
    defaults = {
        "station_id": None,
        "title": DEFAULTS["CYCLE_TITLE"],
        "response_deadline": DEFAULTS["CYCLE_DEADLINE"],
        "target_room_count": DEFAULTS["CYCLE_TARGET_ROOMS"],
        "budget_cap_cents": DEFAULTS["CYCLE_BUDGET_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(**overrides) -> dict:
    defaults = {
        "vendor_id": None,
        "offered_room_count": DEFAULTS["PROPOSAL_ROOMS"],
        "offered_rate_cents": DEFAULTS["PROPOSAL_RATE"],
        "quiet_room_commitment": DEFAULTS["PROPOSAL_ROOMS"],
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(**overrides) -> dict:
    defaults = {
        "proposal_id": None,
        "room_block_size": DEFAULTS["AWARD_BLOCK"],
        "start_date": DEFAULTS["AWARD_START"],
        "end_date": DEFAULTS["AWARD_END"],
        "late_cancel_hours": DEFAULTS["AWARD_LATE_CANCEL_HOURS"],
        "quiet_room_standard": "ENHANCED",
        "security_requirements": ["KEYCARD_FLOOR"],
        "blackout_dates": [],
        "blackout_protection": False,
        "expected_cycle_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_layover_payload(**overrides) -> dict:
    defaults = {
        "station_id": None,
        "crew_type": "PILOT",
        "crew_count": DEFAULTS["LAYOVER_CREW_COUNT"],
        "arrival_time": DEFAULTS["LAYOVER_ARRIVAL"],
        "departure_time": DEFAULTS["LAYOVER_DEPARTURE"],
        "required_rest_hours": DEFAULTS["LAYOVER_REQUIRED_REST"],
    }
    defaults.update(overrides)
    return defaults


def create_book_payload(**overrides) -> dict:
    defaults = {
        "contract_id": None,
        "stay_date": DEFAULTS["STAY_DATE"],
        "expected_layover_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_distressed_book_payload(**overrides) -> dict:
    defaults = {
        "vendor_id": None,
        "rate_cents": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_transport_trip_payload(**overrides) -> dict:
    defaults = {
        "direction": "AIRPORT_TO_HOTEL",
        "vehicle_capacity": 8,
    }
    defaults.update(overrides)
    return defaults


def create_crew_feedback_payload(**overrides) -> dict:
    defaults = {
        "contract_id": None,
        "layover_requirement_id": None,
        "crew_type": "PILOT",
        "rating": 4,
        "category": "CLEANLINESS",
        "comment": "",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {
        "contract_id": None,
        "auditor_id": "aud-1",
        "severity": "MINOR",
        "findings": "no issues found",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "contract_id": None,
        "billing_period_start": "2026-10-01T00:00:00Z",
        "billing_period_end": "2026-10-30T00:00:00Z",
        "billed_room_nights": 0,
        "billed_amount_cents": 0,
    }
    defaults.update(overrides)
    return defaults
