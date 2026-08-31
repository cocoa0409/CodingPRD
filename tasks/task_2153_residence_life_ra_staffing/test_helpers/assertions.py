"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, entity_label: str = "resource"):
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}"
    )


def assert_building(data: dict):
    assert_common_fields(data, "Building")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert data["campus_zone"] in ("NORTH", "SOUTH", "WEST")
    assert isinstance(data["break_housing_enabled"], bool)
    assert data["posture"] in ("OPEN", "RESTRICTED", "EMERGENCY_CLOSED")
    assert isinstance(data["bed_capacity"], int) and data["bed_capacity"] >= 0
    assert isinstance(data["assigned_bed_count"], int) and data["assigned_bed_count"] >= 0


def assert_floor(data: dict):
    assert_common_fields(data, "Floor")
    assert isinstance(data["building_id"], str)
    assert 1 <= data["floor_number"] <= 30
    assert 1 <= data["required_programs_per_term"] <= 12
    assert data["programming_compliance_status"] in ("PENDING", "COMPLIANT", "DEFICIENT")
    assert data["coverage_status"] in ("NORMAL", "CRITICAL")
    assert isinstance(data["programming_frozen"], bool)
    assert_floor_budget_partition(data)


def assert_floor_budget_partition(floor: dict):
    """The three buckets always partition the same total (PRD §3.8)."""
    budget = floor["programming_budget_cents"]
    encumbered = floor["programming_encumbered_cents"]
    spent = floor["programming_spent_cents"]
    available = floor["programming_available_cents"]
    assert available == budget - encumbered - spent, (
        "programming_available_cents must equal budget less encumbered less spent; "
        f"got {available} from {budget}/{encumbered}/{spent}"
    )
    for key in (
        "programming_budget_cents",
        "programming_encumbered_cents",
        "programming_spent_cents",
    ):
        assert floor[key] >= 0, f"{key} must never go negative, got {floor[key]}"


def assert_floor_coverage(floor: dict):
    """coverage_status is CRITICAL exactly when uncovered_shift_count >= 2."""
    expected = "CRITICAL" if floor["uncovered_shift_count"] >= 2 else "NORMAL"
    assert floor["coverage_status"] == expected, (
        f"Expected coverage_status {expected} for uncovered_shift_count "
        f"{floor['uncovered_shift_count']}, got {floor['coverage_status']}"
    )


def assert_room(data: dict):
    assert_common_fields(data, "Room")
    assert isinstance(data["floor_id"], str)
    assert isinstance(data["room_number"], str)
    assert 1 <= data["bed_capacity"] <= 4
    assert 1950 <= data["last_renovation_year"] <= 2100
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "OFFLINE", "CONSOLIDATED")
    assert 0 <= data["occupied_beds"] <= data["bed_capacity"], (
        f"occupied_beds {data['occupied_beds']} must stay within bed_capacity "
        f"{data['bed_capacity']}"
    )
    assert 0 <= data["condition_score"] <= 100
    assert data["break_hold_count"] >= 0


def assert_student(data: dict):
    assert_common_fields(data, "Student")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["class_year"] in ("FIRST_YEAR", "SOPHOMORE", "JUNIOR", "SENIOR")
    assert data["housing_status"] in ("UNASSIGNED", "ASSIGNED", "RELOCATION_PENDING")
    assert data["conduct_standing"] in ("GOOD", "PROBATION", "SUSPENDED")
    assert isinstance(data["conduct_points"], int) and data["conduct_points"] >= 0
    assert isinstance(data["judicial_hold"], bool)
    assert isinstance(data["break_housing_eligible"], bool)
    assert data["damage_balance_cents"] >= 0


def assert_conduct_standing_derived(student: dict):
    """conduct_standing is re-derived from conduct_points (PRD §3.5)."""
    points = student["conduct_points"]
    expected = "SUSPENDED" if points >= 20 else "PROBATION" if points >= 12 else "GOOD"
    assert student["conduct_standing"] == expected, (
        f"Expected conduct_standing {expected} for conduct_points {points}, "
        f"got {student['conduct_standing']}"
    )


def assert_application(data: dict):
    assert_common_fields(data, "RAApplication")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "REVISION_REQUESTED",
        "OFFERED",
        "ACCEPTED",
        "DECLINED",
        "REJECTED",
    )
    assert isinstance(data["revision_count"], int) and 0 <= data["revision_count"] <= 2


def assert_ra(data: dict):
    assert_common_fields(data, "RA")
    assert data["employment_status"] in (
        "PROVISIONAL",
        "ACTIVE",
        "SUSPENDED",
        "SEPARATED",
    )
    assert data["certification_status"] in (
        "UNCERTIFIED",
        "IN_TRAINING",
        "CERTIFIED",
        "LAPSED",
    )
    assert isinstance(data["completed_module_codes"], list)
    assert len(set(data["completed_module_codes"])) == len(
        data["completed_module_codes"]
    ), "completed_module_codes must hold distinct codes"
    assert data["training_credits_earned"] >= 0
    assert data["duty_points_balance"] >= 0
    assert data["missed_shift_count"] >= 0


def assert_duty_shift(data: dict):
    assert_common_fields(data, "DutyShift")
    assert data["shift_type"] in ("WEEKDAY", "WEEKEND", "BREAK")
    assert data["status"] in (
        "OPEN",
        "ASSIGNED",
        "SWAP_PENDING",
        "CHECKED_IN",
        "COMPLETED",
        "MISSED",
        "VOID",
    )
    expected_points = {"WEEKDAY": 1, "WEEKEND": 3, "BREAK": 5}[data["shift_type"]]
    assert data["points_value"] == expected_points, (
        f"points_value for a {data['shift_type']} block must be {expected_points}, "
        f"got {data['points_value']}"
    )
    assert isinstance(data["filled_by_selector"], bool)


def assert_incident_report(data: dict):
    assert_common_fields(data, "IncidentReport")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "RETURNED_FOR_DETAIL",
        "ROUTED_TO_CONDUCT",
        "CLOSED_NO_ACTION",
        "CLOSED_ADJUDICATED",
    )
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE")
    assert data["policy_code"] in ("ALCOHOL", "NOISE", "GUEST", "DAMAGE", "SAFETY")
    assert isinstance(data["return_count"], int) and 0 <= data["return_count"] <= 2


def assert_conduct_case(data: dict):
    assert_common_fields(data, "ConductCase")
    assert data["status"] in ("OPEN", "HEARING_SCHEDULED", "SANCTIONED", "DISMISSED")
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE")
    assert data["outcome"] in (None, "SANCTION", "DISMISS")


def assert_room_inspection(data: dict):
    assert_common_fields(data, "RoomInspection")
    assert data["inspection_type"] in ("CHECK_IN", "CHECK_OUT", "HEALTH_SAFETY")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "SUPERSEDED", "CANCELLED")
    assert isinstance(data["damage_lines"], list)


def assert_damage_charge(data: dict):
    assert_common_fields(data, "DamageCharge")
    assert data["status"] in (
        "PENDING",
        "BILLED",
        "APPEALED",
        "SETTLED",
        "WAIVED",
        "VOID",
    )
    assert isinstance(data["provisional_subtotal_cents"], int)
    assert data["provisional_subtotal_cents"] >= 0
    assert data["appeal_outcome"] in (None, "ADJUSTED", "UPHELD")


def assert_settlement_arithmetic(charge: dict):
    """final_amount_cents is the fee-inclusive total less relief (PRD §3.6)."""
    gross = charge["assessed_subtotal_cents"]
    fee = charge["admin_fee_cents"]
    relief = charge["hardship_relief_cents"]
    final = charge["final_amount_cents"]
    assert None not in (gross, fee, relief, final), (
        "a billed charge must expose assessed_subtotal_cents, admin_fee_cents, "
        "hardship_relief_cents and final_amount_cents"
    )
    assert final == max(0, gross + fee - relief), (
        f"final_amount_cents must be {max(0, gross + fee - relief)} from gross {gross}, "
        f"fee {fee} and relief {relief}; got {final}"
    )
    for key in ("assessed_subtotal_cents", "admin_fee_cents", "hardship_relief_cents"):
        assert isinstance(charge[key], int), f"{key} must be an integer count of cents"


def assert_room_change_case(data: dict):
    assert_common_fields(data, "RoomChangeCase")
    assert data["origin"] in (
        "SELF_REQUEST",
        "ROOMMATE_CONFLICT",
        "EMERGENCY_RELOCATION",
    )
    assert data["mediation_status"] in (
        "NOT_REQUIRED",
        "INTAKE",
        "SESSION_SCHEDULED",
        "AGREEMENT_REACHED",
        "IMPASSE",
    )
    assert data["placement_status"] in (
        "NONE",
        "REQUESTED",
        "APPROVED",
        "COMPLETED",
        "DENIED",
        "CANCELLED",
        "REVERTED",
    )
    assert isinstance(data["mediation_round"], int) and 0 <= data["mediation_round"] <= 3


def assert_program_event(data: dict):
    assert_common_fields(data, "ProgramEvent")
    assert data["category"] in ("SOCIAL", "EDUCATIONAL", "WELLNESS")
    assert data["status"] in (
        "PROPOSED",
        "APPROVED",
        "HELD",
        "REIMBURSED",
        "DENIED",
        "CANCELLED",
    )
    assert 0 <= data["requested_amount_cents"] <= 500_000
    assert data["encumbered_amount_cents"] >= 0


def assert_break_housing_request(data: dict):
    assert_common_fields(data, "BreakHousingRequest")
    assert data["break_code"] in ("THANKSGIVING", "WINTER", "SPRING")
    assert data["status"] in (
        "REQUESTED",
        "APPROVED",
        "CHECKED_IN",
        "DENIED",
        "REVOKED",
        "CLOSED",
    )
    assert data["revocation_cause"] in (None, "EMERGENCY_CLOSURE", "CONDUCT_INELIGIBLE")


def assert_timestamp_equals(actual: str, expected_instant: str, label: str = "timestamp"):
    """Compare a returned instant to an expected UTC instant, tolerating the
    trailing-Z / fractional-digit spellings a faithful server may emit."""
    assert actual is not None, f"{label} must not be null"
    normalised_actual = _normalise_instant(actual)
    normalised_expected = _normalise_instant(expected_instant)
    assert normalised_actual == normalised_expected, (
        f"Expected {label} {expected_instant}, got {actual}"
    )


def _normalise_instant(value: str) -> str:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text:
        text = text.split("+")[0]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return text
