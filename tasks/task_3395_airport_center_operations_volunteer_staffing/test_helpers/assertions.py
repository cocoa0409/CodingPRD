"""Entity assertions and domain invariant checkers.

Each assert_{entity} checks the common properties plus the entity's
declared fields. Status membership is checked against the PRD's declared
value sets. Optional/nullable fields are checked for type only when
present and non-null.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus, AssignmentStatus, BookingStatus, CenterPosture,
    CheckInStatus, DonationCategory, EventKind, EventStatus, GrantStatus,
    GuestCategory, GuestEligibility, LotStatus, ScreeningStatus, ShiftRole,
    ShiftStatus, VolunteerStatus, ServiceType,
)

_DATE_FIELDS = (
    "start_date", "end_date", "expiry_date", "spend_by_date",
    "verification_expires_on",
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def _assert_date(value, field):
    assert isinstance(value, str) and len(value) == 10, (
        f"{field} must be a YYYY-MM-DD date string, got {value!r}"
    )


def assert_center(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["airport_code"], str) and data["airport_code"]
    assert isinstance(data["occupancy_cap"], int) and data["occupancy_cap"] >= 1
    assert isinstance(data["required_daily_confirmed_assignments"], int)
    assert data["required_daily_confirmed_assignments"] >= 1
    assert data["posture"] in [p.value for p in CenterPosture]
    assert isinstance(data["current_occupancy"], int) and data["current_occupancy"] >= 0
    assert isinstance(data["coverage_ratio"], (int, float))
    assert data["coverage_ratio"] >= 0
    assert data.get("active_agreement_id") is None or isinstance(
        data["active_agreement_id"], str
    )
    assert isinstance(data["expense_ledger"], list)
    assert isinstance(data["ops_run_count"], int) and data["ops_run_count"] >= 0


def assert_site_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be a UUID"
    assert isinstance(data["facility_space_sqft"], int) and data["facility_space_sqft"] > 0
    assert isinstance(data["utilities_included"], bool)
    assert isinstance(data["access_terms"], str)
    assert isinstance(data["security_level"], int) and 1 <= data["security_level"] <= 5
    _assert_date(data["start_date"], "start_date")
    _assert_date(data["end_date"], "end_date")
    assert data["status"] in [s.value for s in AgreementStatus]


def assert_volunteer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert is_valid_uuid(data.get("home_center_id", "")), "home_center_id must be a UUID"
    assert data["status"] in [s.value for s in VolunteerStatus]
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert isinstance(data["total_hours"], (int, float)) and data["total_hours"] >= 0


def assert_screening(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("volunteer_id", "")), "volunteer_id must be a UUID"
    assert data["status"] in [s.value for s in ScreeningStatus]
    assert data.get("claimed_by_user_id") is None or isinstance(
        data["claimed_by_user_id"], str
    )
    assert data.get("decided_by_user_id") is None or isinstance(
        data["decided_by_user_id"], str
    )
    expires = data.get("expires_at")
    assert expires is None or is_iso8601_timestamp(expires), (
        f"expires_at must be null or ISO 8601, got {expires!r}"
    )


def assert_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert data["role_required"] in [r.value for r in ShiftRole]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert data["status"] in [s.value for s in ShiftStatus]


def assert_shift_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shift_id", "")), "shift_id must be a UUID"
    assert is_valid_uuid(data.get("volunteer_id", "")), "volunteer_id must be a UUID"
    assert data["status"] in [s.value for s in AssignmentStatus]
    hours = data.get("actual_hours")
    assert hours is None or (isinstance(hours, (int, float)) and hours > 0), (
        f"actual_hours must be null until COMPLETED, got {hours!r}"
    )


def assert_guest(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["category"] in [c.value for c in GuestCategory]
    _assert_date(data["verification_expires_on"], "verification_expires_on")
    assert data["eligibility_status"] in [s.value for s in GuestEligibility]


def assert_check_in(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be a UUID"
    assert is_valid_uuid(data.get("guest_id", "")), "guest_id must be a UUID"
    assert is_iso8601_timestamp(data.get("checked_in_at", "")), (
        "checked_in_at must be ISO 8601"
    )
    out = data.get("checked_out_at")
    assert out is None or is_iso8601_timestamp(out), (
        f"checked_out_at must be null or ISO 8601, got {out!r}"
    )
    assert data["status"] in [s.value for s in CheckInStatus]


def assert_service_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be a UUID"
    assert is_valid_uuid(data.get("guest_id", "")), "guest_id must be a UUID"
    assert data["service_type"] in [t.value for t in ServiceType]
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert data["status"] in [s.value for s in BookingStatus]


def assert_donation_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be a UUID"
    assert isinstance(data["item_name"], str) and data["item_name"]
    assert data["category"] in [c.value for c in DonationCategory]
    assert isinstance(data["received_qty"], int) and data["received_qty"] > 0
    assert isinstance(data["remaining_qty"], int) and data["remaining_qty"] >= 0
    assert data["remaining_qty"] <= data["received_qty"]
    _assert_date(data["expiry_date"], "expiry_date")
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 0
    assert isinstance(data["partner_match_cents"], int) and data["partner_match_cents"] >= 0
    assert data["status"] in [s.value for s in LotStatus]


def assert_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be a UUID"
    assert data["kind"] in [k.value for k in EventKind]
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert data["status"] in [s.value for s in EventStatus]
    assert isinstance(data["min_volunteers"], int) and data["min_volunteers"] >= 0
    assert isinstance(data["required_security_level"], int)
    assert 1 <= data["required_security_level"] <= 5
    assert isinstance(data["talent_agreement_signed"], bool)
    assert isinstance(data["event_budget_cents"], int) and data["event_budget_cents"] >= 0


def assert_funding_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be a UUID"
    assert isinstance(data["donor_name"], str) and data["donor_name"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0
    assert isinstance(data["remaining_cents"], int)
    assert data["remaining_cents"] == data["amount_cents"] - data["spent_cents"], (
        "remaining_cents must equal amount_cents - spent_cents"
    )
    _assert_date(data["spend_by_date"], "spend_by_date")
    assert data["status"] in [s.value for s in GrantStatus]


def assert_expense_result(data: dict):
    assert isinstance(data["posted_cents"], int) and data["posted_cents"] > 0
    assert isinstance(data["debits"], list)
    for debit in data["debits"]:
        assert isinstance(debit, dict), f"each debit is an object, got {debit!r}"


def assert_cost_report(data: dict):
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be a UUID"
    assert data["posture"] in [p.value for p in CenterPosture]
    assert isinstance(data["current_occupancy"], int) and data["current_occupancy"] >= 0
    assert isinstance(data["coverage_ratio"], (int, float))
    assert isinstance(data["month_expenses_cents"], int)
    assert isinstance(data["month_visits"], int) and data["month_visits"] >= 0
    actual = data.get("cost_per_visit_actual_cents")
    loaded = data.get("cost_per_visit_loaded_cents")
    if data["month_visits"] == 0:
        assert actual is None, "with zero visits, actual cost per visit is null"
        assert loaded is None, "with zero visits, loaded cost per visit is null"
    else:
        assert isinstance(actual, int) and actual >= 0
        assert isinstance(loaded, int) and loaded >= actual
    assert isinstance(data["donation_value_total_cents"], int)
    assert isinstance(data["partner_match_total_cents"], int)


def assert_shift_capacity_invariant(shift: dict):
    """confirmed_count never exceeds capacity; FILLED exactly at capacity."""
    assert 0 <= shift["confirmed_count"] <= shift["capacity"]
    if shift["confirmed_count"] == shift["capacity"]:
        assert shift["status"] == "FILLED"
    else:
        assert shift["status"] == "OPEN"


def assert_center_occupancy_invariant(center: dict):
    """Occupancy stays within the cap."""
    assert 0 <= center["current_occupancy"] <= center["occupancy_cap"]
