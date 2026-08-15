"""Entity assertions and domain invariant helpers.

Field coverage follows the resource narratives of PRD §2 and §3; every
resource carries the four common properties of PRD §2.5 (`id`, `created_at`,
`updated_at`, `version`).
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating fractional-digit and offset
    spelling variants (PRD §2.4: datetimes are ISO 8601 UTC)."""
    assert isinstance(value, str), f"expected an ISO instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str):
    """Two ISO 8601 spellings denote the same instant."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["program_year"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["supply_budget_cents"], int) and data["supply_budget_cents"] >= 0
    assert data["child_staff_ratio"] >= 1
    assert data["waitlist_offer_ttl_hours"] >= 1
    assert data["status"] in [
        "DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED",
        "IN_SESSION", "COMPLETED", "ARCHIVED",
    ]
    assert isinstance(data["current_day_index"], int)
    assert isinstance(data["enrolled_total"], int)
    assert isinstance(data["waitlist_total"], int)


def assert_classroom(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["age_min"], int) and data["age_min"] >= 0
    assert isinstance(data["age_max"], int) and data["age_max"] >= data["age_min"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] in ["SETUP", "ACCEPTING", "FULL", "CLOSED"]
    for counter in ("enrolled_count", "offered_count", "waitlist_count",
                    "open_seats", "required_adults", "confirmed_adult_count"):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    assert data["staffing_status"] in ["ADEQUATE", "UNSTAFFED", "UNDERSTAFFED"]


def assert_family(data: dict):
    _assert_common(data)
    assert isinstance(data["household_name"], str) and data["household_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["preferred_contact"] in ["EMAIL", "PHONE", "TEXT"]
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_child(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("family_id", ""))
    assert isinstance(data["first_name"], str) and data["first_name"]
    assert isinstance(data["last_name"], str) and data["last_name"]
    assert isinstance(data["birth_date"], str)
    assert data["grade_completed"] in [
        "PRE_K", "KINDERGARTEN", "GRADE_1", "GRADE_2", "GRADE_3",
        "GRADE_4", "GRADE_5", "GRADE_6",
    ]
    assert isinstance(data["has_special_needs"], bool)


def assert_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert is_valid_uuid(data.get("classroom_id", ""))
    assert data["status"] in [
        "ENROLLED", "WAITLISTED", "OFFERED", "CANCELLED", "DECLINED", "EXPIRED",
    ]
    assert isinstance(data["age_at_registration"], int)
    pos = data.get("waitlist_position")
    if data["status"] == "WAITLISTED":
        assert isinstance(pos, int) and pos >= 1, (
            "waitlist_position must be a 1-based rank while WAITLISTED"
        )
    else:
        assert pos is None, "waitlist_position is null unless WAITLISTED"


def assert_volunteer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["birth_date"], str)
    assert isinstance(data["is_minor"], bool)
    assert data["status"] in ["APPLIED", "SCREENING", "CLEARED", "REJECTED"]


def assert_screening_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["check_type"] in ["BACKGROUND", "REFERENCE", "SAFE_MINISTRY_TRAINING"]
    assert data["status"] in ["SUBMITTED", "CLEARED", "REJECTED", "INFO_REQUESTED"]
    assert isinstance(data["resubmission_count"], int) and data["resubmission_count"] >= 0


def assert_role_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert is_valid_uuid(data.get("classroom_id", ""))
    assert data["role"] in [
        "LEAD_TEACHER", "ASSISTANT_TEACHER", "SNACK_COORDINATOR",
        "CRAFT_LEADER", "CHECKIN_DESK",
    ]
    assert data["status"] in ["PROPOSED", "CONFIRMED", "RELEASED"]


def assert_accommodation_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert data["severity"] in [
        "FOOD_ALLERGY", "ENVIRONMENTAL_ALLERGY", "MEDICATION_ADMIN",
        "MOBILITY", "BEHAVIORAL",
    ]
    assert isinstance(data["instructions"], str)
    assert isinstance(data["requires_epinephrine"], bool)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "NEEDS_REVISION", "SUPERSEDED",
    ]


def assert_supply_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["kit_name"], str) and data["kit_name"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "CANCELLED"]
    # total is quantity * unit cost in integer cents with no rounding (§3.6)
    assert data["total_cost_cents"] == data["quantity"] * data["unit_cost_cents"]


def assert_supply_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["category"] in ["SNACK", "CRAFT"]
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["reserved_quantity"], int) and data["reserved_quantity"] >= 0
    assert isinstance(data["available_quantity"], int)
    # available == on-hand minus reserved (§3.6)
    assert data["available_quantity"] == (
        data["quantity_on_hand"] - data["reserved_quantity"]
    )


def assert_supply_distribution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supply_item_id", ""))
    assert is_valid_uuid(data.get("classroom_id", ""))
    assert is_valid_uuid(data.get("program_day_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ["PLANNED", "ISSUED", "CANCELLED"]


def assert_program_day(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["day_index"], int) and data["day_index"] >= 1
    assert isinstance(data["date"], str)
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED"]
    for counter in ("checked_in_count", "checked_out_count", "absent_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_security_tag(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert is_valid_uuid(data.get("program_day_id", ""))
    code = data["tag_code"]
    assert isinstance(code, str) and len(code) == 6 and code.isdigit(), (
        f"tag_code must be six zero-padded digits, got {code!r}"
    )
    assert data["status"] in ["ISSUED", "REDEEMED", "VOIDED"]


def assert_attendance_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert is_valid_uuid(data.get("program_day_id", ""))
    assert data["status"] in ["NOT_ARRIVED", "CHECKED_IN", "CHECKED_OUT", "ABSENT"]


def assert_family_message(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["audience"] in ["ALL_FAMILIES", "CLASSROOM", "ALLERGY_ALERT", "VOLUNTEERS"]
    assert data["status"] in ["DRAFT", "SENT", "CANCELLED"]
    assert isinstance(data["recipient_count"], int) and data["recipient_count"] >= 0


def assert_retention_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("child_id", ""))
    assert isinstance(data["attended_days"], int) and data["attended_days"] >= 0
    assert isinstance(data["attendance_rate"], (int, float))
    assert isinstance(data["family_volunteer_bonus"], bool)
    assert data["priority_tier"] in ["A", "B", "C"]
    assert data["status"] in ["LISTED", "INVITED", "RESPONDED_YES", "RESPONDED_NO"]
