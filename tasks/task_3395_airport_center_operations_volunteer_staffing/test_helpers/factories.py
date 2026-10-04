"""Payload factories — one per entity, input fields only.

Defaults are chosen so every business timestamp is reachable from the
logical clock's default start (2026-09-01T00:00:00Z): date fields default
on/after 2026-09-01 and datetime fields default to that date or later.
Every factory accepts **overrides for the values a test needs to control.
"""

DEFAULTS = {
    "CENTER_NAME": "Liberty Center",
    "AIRPORT_CODE": "LAX",
    "OCCUPANCY_CAP": 25,
    "REQUIRED_DAILY_CONFIRMED": 2,
    "FACILITY_SPACE_SQFT": 900,
    "ACCESS_TERMS": "badge required 24x7",
    "SECURITY_LEVEL": 2,
    "AGREEMENT_START_DATE": "2026-09-01",
    "AGREEMENT_END_DATE": "2027-08-31",
    "VOLUNTEER_FULL_NAME": "Val Volunteer",
    "GUEST_FULL_NAME": "Gail Guest",
    "EMAIL_DOMAIN": "example.org",
    "VERIFICATION_EXPIRES_ON": "2027-01-01",
    "SHIFT_START_AT": "2026-09-02T08:00:00Z",
    "SHIFT_END_AT": "2026-09-02T12:00:00Z",
    "SHIFT_ROLE": "DESK",
    "SHIFT_CAPACITY": 2,
    "BOOKING_START_AT": "2026-09-01T10:00:00Z",
    "BOOKING_END_AT": "2026-09-01T11:00:00Z",
    "SERVICE_TYPE": "CONNECTIVITY",
    "ITEM_NAME": "granola bars",
    "DONATION_CATEGORY": "FOOD",
    "RECEIVED_QTY": 5,
    "LOT_EXPIRY_DATE": "2026-09-20",
    "DECLARED_VALUE_CENTS": 400,
    "EVENT_KIND": "DEPLOYMENT",
    "EVENT_NAME": "Unit Departure Support",
    "EVENT_START_AT": "2026-09-10T10:00:00Z",
    "EVENT_END_AT": "2026-09-10T12:00:00Z",
    "DONOR_NAME": "Donor",
    "GRANT_AMOUNT_CENTS": 10000,
    "SPEND_BY_DATE": "2026-12-31",
    "EXPENSE_AMOUNT_CENTS": 100,
    "EXPENSE_DESCRIPTION": "supplies restock",
}


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def create_center_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CENTER_NAME"],
        "airport_code": DEFAULTS["AIRPORT_CODE"],
        "occupancy_cap": DEFAULTS["OCCUPANCY_CAP"],
        "required_daily_confirmed_assignments": DEFAULTS[
            "REQUIRED_DAILY_CONFIRMED"
        ],
    }
    payload.update(overrides)
    return payload


def create_site_agreement_payload(**overrides) -> dict:
    payload = {
        "facility_space_sqft": DEFAULTS["FACILITY_SPACE_SQFT"],
        "utilities_included": True,
        "access_terms": DEFAULTS["ACCESS_TERMS"],
        "security_level": DEFAULTS["SECURITY_LEVEL"],
        "start_date": DEFAULTS["AGREEMENT_START_DATE"],
        "end_date": DEFAULTS["AGREEMENT_END_DATE"],
    }
    payload.update(overrides)
    return payload


def activate_agreement_payload(expected_center_version, **overrides) -> dict:
    payload = {"expected_center_version": expected_center_version}
    payload.update(overrides)
    return payload


def renew_agreement_payload(new_end_date, **overrides) -> dict:
    payload = {"new_end_date": new_end_date}
    payload.update(overrides)
    return payload


def create_volunteer_payload(home_center_id, **overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["VOLUNTEER_FULL_NAME"],
        "email": overrides.pop("email", None) or _unique_email(),
        "home_center_id": home_center_id,
    }
    payload.update(overrides)
    return payload


def create_screening_payload(expected_volunteer_version, **overrides) -> dict:
    payload = {"expected_volunteer_version": expected_volunteer_version}
    payload.update(overrides)
    return payload


def decide_screening_payload(verdict="CLEARED", **overrides) -> dict:
    payload = {"verdict": verdict}
    payload.update(overrides)
    return payload


def create_shift_payload(**overrides) -> dict:
    payload = {
        "start_at": DEFAULTS["SHIFT_START_AT"],
        "end_at": DEFAULTS["SHIFT_END_AT"],
        "role_required": DEFAULTS["SHIFT_ROLE"],
        "capacity": DEFAULTS["SHIFT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(volunteer_id, **overrides) -> dict:
    payload = {"volunteer_id": volunteer_id}
    payload.update(overrides)
    return payload


def complete_assignment_payload(actual_hours=2.0, **overrides) -> dict:
    payload = {"actual_hours": actual_hours}
    payload.update(overrides)
    return payload


def create_guest_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["GUEST_FULL_NAME"],
        "category": "ACTIVE_DUTY",
        "verification_expires_on": DEFAULTS["VERIFICATION_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def reverify_guest_payload(verification_expires_on, **overrides) -> dict:
    payload = {"verification_expires_on": verification_expires_on}
    payload.update(overrides)
    return payload


def create_check_in_payload(guest_id, **overrides) -> dict:
    payload = {"guest_id": guest_id}
    payload.update(overrides)
    return payload


def create_service_booking_payload(guest_id, **overrides) -> dict:
    payload = {
        "guest_id": guest_id,
        "service_type": DEFAULTS["SERVICE_TYPE"],
        "start_at": DEFAULTS["BOOKING_START_AT"],
        "end_at": DEFAULTS["BOOKING_END_AT"],
    }
    payload.update(overrides)
    return payload


def create_donation_lot_payload(**overrides) -> dict:
    payload = {
        "item_name": DEFAULTS["ITEM_NAME"],
        "category": DEFAULTS["DONATION_CATEGORY"],
        "received_qty": DEFAULTS["RECEIVED_QTY"],
        "expiry_date": DEFAULTS["LOT_EXPIRY_DATE"],
        "declared_value_cents": DEFAULTS["DECLARED_VALUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def consume_lot_payload(quantity=1, **overrides) -> dict:
    payload = {"quantity": quantity}
    payload.update(overrides)
    return payload


def create_event_payload(**overrides) -> dict:
    payload = {
        "kind": DEFAULTS["EVENT_KIND"],
        "name": DEFAULTS["EVENT_NAME"],
        "start_at": DEFAULTS["EVENT_START_AT"],
        "end_at": DEFAULTS["EVENT_END_AT"],
    }
    payload.update(overrides)
    return payload


def create_tour_event_payload(**overrides) -> dict:
    """Entertainment-tour event: starts in SECURITY_REVIEW; the tour gate
    fields are explicit here because tests almost always control them."""
    payload = {
        "kind": "ENTERTAINMENT_TOUR",
        "name": "Tour Stop",
        "start_at": "2026-10-01T14:00:00Z",
        "end_at": "2026-10-01T16:00:00Z",
        "min_volunteers": 0,
        "required_security_level": 1,
        "talent_agreement_signed": True,
    }
    payload.update(overrides)
    return payload


def create_funding_grant_payload(center_id, **overrides) -> dict:
    payload = {
        "center_id": center_id,
        "donor_name": DEFAULTS["DONOR_NAME"],
        "amount_cents": DEFAULTS["GRANT_AMOUNT_CENTS"],
        "spend_by_date": DEFAULTS["SPEND_BY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_expense_payload(expected_center_version, **overrides) -> dict:
    payload = {
        "amount_cents": DEFAULTS["EXPENSE_AMOUNT_CENTS"],
        "description": DEFAULTS["EXPENSE_DESCRIPTION"],
        "expected_center_version": expected_center_version,
    }
    payload.update(overrides)
    return payload


_counter = {"email": 0}


def _unique_email() -> str:
    _counter["email"] += 1
    return f"volunteer-{_counter['email']:04d}@{DEFAULTS['EMAIL_DOMAIN']}"
