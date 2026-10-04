"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COMPANY_NAME": "Test Company",
    "COMPANY_EMAIL": "test@example.com",
    "THEATRE_NAME": "Test House",
    "THEATRE_CAPACITY": 500,
    "THEATRE_SIZE_CLASS": "SMALL",
    "THEATRE_IS_LANDMARK": False,
    "THEATRE_BASE_RENT": 500000,
    "PRODUCTION_TITLE": "Test Show",
    "REQUIRED_SIZE_CLASS": "SMALL",
    "LOADIN_HOURS": 24,
    "LOADOUT_HOURS": 24,
    "LOADIN_START": "2026-09-06T00:00:00Z",
    "RUN_END": "2026-11-01T00:00:00Z",
    "WEEKLY_RENT": 500000,
    "STOP_FLOOR": 10000,
    "STOP_WEEKS": 2,
    "PERFORMANCE_DATE": "2026-09-08T19:00:00Z",
    "TICKET_COUNT": 2,
    "FACE_VALUE": 5000,
    "WEEK_START": "2026-09-07T00:00:00Z",
}


def create_company_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["COMPANY_NAME"],
                "contact_email": DEFAULTS["COMPANY_EMAIL"]}
    defaults.update(overrides)
    return defaults


def create_theatre_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["THEATRE_NAME"],
                "capacity": DEFAULTS["THEATRE_CAPACITY"],
                "size_class": DEFAULTS["THEATRE_SIZE_CLASS"],
                "is_landmark": DEFAULTS["THEATRE_IS_LANDMARK"],
                "base_weekly_rent_cents": DEFAULTS["THEATRE_BASE_RENT"]}
    defaults.update(overrides)
    return defaults


def create_production_payload(company_id, **overrides) -> dict:
    defaults = {"company_id": company_id,
                "title": DEFAULTS["PRODUCTION_TITLE"],
                "required_size_class": DEFAULTS["REQUIRED_SIZE_CLASS"],
                "required_loadin_hours": DEFAULTS["LOADIN_HOURS"],
                "required_loadout_hours": DEFAULTS["LOADOUT_HOURS"]}
    defaults.update(overrides)
    return defaults


def create_booking_payload(production_id, theatre_id, **overrides) -> dict:
    defaults = {"production_id": production_id,
                "theatre_id": theatre_id,
                "loadin_start": DEFAULTS["LOADIN_START"],
                "run_end": DEFAULTS["RUN_END"]}
    defaults.update(overrides)
    return defaults


def create_license_agreement_payload(expected_booking_version, **overrides) -> dict:
    defaults = {"weekly_rent_cents": DEFAULTS["WEEKLY_RENT"],
                "stop_clause_weekly_floor_cents": DEFAULTS["STOP_FLOOR"],
                "stop_clause_consecutive_weeks": DEFAULTS["STOP_WEEKS"],
                "expected_booking_version": expected_booking_version}
    defaults.update(overrides)
    return defaults


def sign_license_agreement_payload(expected_booking_version, **overrides) -> dict:
    defaults = {"expected_booking_version": expected_booking_version}
    defaults.update(overrides)
    return defaults


def create_royalty_participant_payload(**overrides) -> dict:
    defaults = {"participant_name": "Participant",
                "royalty_points": 50,
                "pool_eligible": True}
    defaults.update(overrides)
    return defaults


def create_discount_code_payload(**overrides) -> dict:
    defaults = {"code": "SAVE10", "percent_off": 10}
    defaults.update(overrides)
    return defaults


def create_ticket_order_payload(**overrides) -> dict:
    defaults = {"performance_date": DEFAULTS["PERFORMANCE_DATE"],
                "ticket_count": DEFAULTS["TICKET_COUNT"],
                "is_group_sale": False,
                "face_value_cents": DEFAULTS["FACE_VALUE"]}
    defaults.update(overrides)
    return defaults


def create_weekly_gross_report_payload(**overrides) -> dict:
    defaults = {"week_start": DEFAULTS["WEEK_START"]}
    defaults.update(overrides)
    return defaults


def create_settlement_payload(**overrides) -> dict:
    defaults = {"house_expenses_cents": 100000}
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(**overrides) -> dict:
    defaults = {"crew_size": 4}
    defaults.update(overrides)
    return defaults


def create_capital_project_payload(**overrides) -> dict:
    defaults = {"description": "Maintenance",
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-20T00:00:00Z"}
    defaults.update(overrides)
    return defaults
