"""Entity assertions, envelope helpers and domain invariant checkers."""
from typing import List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import parse_instant


# --------------------------------------------------------------------------
# Envelope / list-shape helpers
# --------------------------------------------------------------------------
def validate_list(response) -> tuple:
    """Validate a paginated list response and return (rows, meta).

    Every list endpoint in this API reports `limit`, `offset`, `total_count`
    and `has_more` in `meta` (PRD §2.3).
    """
    rows, meta = validate_paginated(response)
    assert isinstance(rows, list), f"list data must be an array, got {type(rows)}"
    return rows, meta


def validate_unpaginated_list(response, expected_status: int = 200) -> list:
    """Validate a list response declared as a bare array with no page window.

    Provided for endpoints whose response the PRD declares as a plain array;
    it asserts only the envelope and that `data` is a list.
    """
    assert response.status_code == expected_status, (
        f"Expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "meta" in body and "data" in body, "missing envelope keys"
    assert body.get("response_type") == "array", (
        f"expected response_type 'array', got {body.get('response_type')!r}"
    )
    assert isinstance(body["data"], list), "data must be an array"
    return body["data"]


def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int, has_more: bool):
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_created_at_ascending(rows: List[dict]):
    """List results are always ordered by `created_at` ascending (PRD §2.3)."""
    stamps = [parse_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), "rows must be ordered by created_at ascending"


# --------------------------------------------------------------------------
# Instant / precision helpers
# --------------------------------------------------------------------------
def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant"):
    """Compare two ISO 8601 UTC instants regardless of fractional-digit spelling."""
    if expected is None:
        assert actual is None, f"{label} must be null, got {actual!r}"
        return
    assert actual is not None, f"{label} must be present, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_three_fraction_digit_instant(value: str, label: str = "timestamp"):
    """PRD §2.4: instants are ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value)}"
    assert value.endswith("Z"), f"{label} must be a UTC instant ending in Z: {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"{label} must carry exactly three fractional digits: {value!r}"
    )
    assert value[20:23].isdigit(), f"{label} fractional part must be digits: {value!r}"


def assert_cents(value, label: str = "amount"):
    """Money is a whole number of cents expressed as a JSON integer (PRD §2.7)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r} ({type(value)})"
    )


def assert_two_decimal_places(value, label: str = "score"):
    """Disease activity scores carry exactly two decimal places (PRD §2.7)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_one_decimal_place(value, label: str = "percentage"):
    """Quality-report percentages carry exactly one decimal place (PRD §2.7)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 1) == float(value), (
        f"{label} must carry at most one decimal place, got {value!r}"
    )


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def _assert_append_only_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_patient(data: dict):
    _assert_common_fields(data, "Patient")
    mrn = data["mrn"]
    assert isinstance(mrn, str) and 6 <= len(mrn) <= 12, "mrn must be 6 to 12 characters"
    assert all(c.isupper() or c.isdigit() for c in mrn), "mrn must be uppercase A-Z and digits 0-9"
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) == 10
    assert data["diagnosis_code"] in ("RA_SEROPOSITIVE", "RA_SERONEGATIVE", "PSA", "AXSPA")
    assert isinstance(data["registry_consent"], bool)
    assert data["tb_screen_status"] in (
        "MISSING", "EXPIRED", "INDETERMINATE", "POSITIVE_UNTREATED",
        "CLEARED", "CLEARED_AFTER_TREATMENT",
    )
    assert data["hbv_screen_status"] in (
        "INCOMPLETE", "ACTIVE_INFECTION", "OCCULT_RISK", "CLEARED",
    )
    assert data["target_status"] in ("AT_TARGET", "NOT_AT_TARGET", "UNASSESSED")
    assert isinstance(data["administered_dose_total"], int) and data["administered_dose_total"] >= 0
    assert isinstance(data["active_episode_count"], int) and data["active_episode_count"] >= 0


def assert_clinician(data: dict):
    _assert_common_fields(data, "Clinician")
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10 and data["npi"].isdigit()
    assert data["role_type"] in ("RHEUMATOLOGIST", "NURSE")
    assert isinstance(data["can_attest_formulary_exception"], bool)


def assert_drug(data: dict):
    _assert_common_fields(data, "Drug")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert data["molecule_class"] in ("TNFI", "IL6", "JAKI", "CD20", "CTLA4")
    assert data["route"] in ("IV", "SC")
    assert 1 <= data["formulary_tier"] <= 5
    assert_cents(data["acquisition_cost_cents"], "acquisition_cost_cents")
    assert data["acquisition_cost_cents"] > 0
    assert 0 <= data["admin_time_minutes"] <= 600
    assert data["monitoring_panel_type"] in ("CBC", "CMP", "LFT")
    assert 1 <= data["monitoring_panel_interval_days"] <= 730
    assert isinstance(data["tb_screen_required"], bool)
    assert isinstance(data["hbv_screen_required"], bool)
    assert isinstance(data["is_biosimilar"], bool)
    assert isinstance(data["step_therapy_required_classes"], list)


def assert_payer_plan(data: dict):
    _assert_common_fields(data, "PayerPlan")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert isinstance(data["pharmacy_benefit_enabled"], bool)
    assert isinstance(data["medical_benefit_enabled"], bool)
    assert data["site_of_care_policy"] in ("SITE_NEUTRAL", "PREFER_AMBULATORY", "HOME_REQUIRED")
    assert 0.0 <= float(data["coinsurance_pct"]) <= 1.0
    assert_cents(data["deductible_remaining_cents"], "deductible_remaining_cents")
    assert_cents(data["medical_facility_fee_cents"], "medical_facility_fee_cents")
    assert float(data["hospital_outpatient_multiplier"]) >= 1.0
    assert 0 <= data["appeal_rounds_allowed"] <= 3
    assert 1 <= data["auth_validity_days"] <= 730
    assert isinstance(data["step_therapy_classes_required"], list)


def assert_infusion_chair(data: dict):
    _assert_common_fields(data, "InfusionChair")
    assert isinstance(data["label"], str) and 1 <= len(data["label"]) <= 40
    assert data["site_type"] in ("HOSPITAL_OUTPATIENT", "AMBULATORY_INFUSION_CENTER")
    assert 0 <= data["turnover_buffer_minutes"] <= 240
    assert data["status"] in ("OPEN", "CLOSED")


def assert_visit(data: dict):
    _assert_common_fields(data, "Visit")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["clinician_id"])
    assert is_iso8601_timestamp(data["visit_datetime"])
    assert is_iso8601_timestamp(data["visit_end_datetime"])
    assert data["visit_type"] in ("NEW", "FOLLOW_UP", "URGENT")
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "SCORED")


def assert_screening_record(data: dict):
    _assert_append_only_fields(data, "ScreeningRecord")
    assert is_valid_uuid(data["patient_id"])
    assert data["screen_type"] in (
        "TB_IGRA", "TB_TST", "TB_LTBI_TREATMENT_COMPLETE",
        "HBV_SURFACE_AG", "HBV_CORE_AB", "HCV_AB",
    )
    assert data["result"] in ("NEGATIVE", "POSITIVE", "INDETERMINATE", "COMPLETED")
    assert is_iso8601_timestamp(data["collected_at"])
    assert is_iso8601_timestamp(data["resulted_at"])
    assert parse_instant(data["collected_at"]) <= parse_instant(data["resulted_at"]), (
        "collected_at must be no later than resulted_at"
    )
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_therapy_episode(data: dict):
    _assert_common_fields(data, "TherapyEpisode")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["drug_id"])
    assert is_valid_uuid(data["payer_plan_id"])
    assert is_iso8601_timestamp(data["therapy_start_at"])
    assert isinstance(data["line_of_therapy"], int) and 1 <= data["line_of_therapy"] <= 6
    assert data["therapy_state"] in ("PLANNED", "ACTIVE", "HELD", "DISCONTINUED")
    assert data["funding_state"] in ("UNFUNDED", "PENDING_AUTH", "AUTHORIZED", "LAPSED")
    assert data["benefit_channel"] in ("PHARMACY", "MEDICAL")
    assert data["site_of_care"] in (
        "SELF_ADMIN", "AMBULATORY_INFUSION_CENTER", "HOSPITAL_OUTPATIENT", "HOME_INFUSION",
    )
    assert data["routing_frozen"] is True, "routing_frozen is set at creation and never revisited"
    assert data["self_injection_training_status"] in ("PENDING", "NOT_REQUIRED", "PASSED", "FAILED")
    assert isinstance(data["self_injection_training_attempts"], int)
    assert isinstance(data["hold_count"], int) and data["hold_count"] >= 0
    assert isinstance(data["doses_administered"], int) and data["doses_administered"] >= 0
    assert data["monitoring_status"] in ("CURRENT", "OVERDUE")


def assert_authorization(data: dict):
    _assert_common_fields(data, "Authorization")
    assert is_valid_uuid(data["episode_id"])
    assert isinstance(data["requested_units"], int) and 1 <= data["requested_units"] <= 24
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "DENIED", "EXPIRED")
    assert isinstance(data["appeal_round"], int) and data["appeal_round"] >= 0
    assert isinstance(data["units_reserved"], int) and data["units_reserved"] >= 0
    assert isinstance(data["units_consumed"], int) and data["units_consumed"] >= 0
    assert isinstance(data["unmet_step_therapy_classes"], list)
    assert data["benefit_channel"] in ("PHARMACY", "MEDICAL")


def assert_monitoring_lab(data: dict):
    _assert_append_only_fields(data, "MonitoringLab")
    assert is_valid_uuid(data["episode_id"])
    assert data["panel_type"] in ("CBC", "CMP", "LFT")
    assert is_iso8601_timestamp(data["collected_at"])
    assert data["alt_grade"] in (0, 1, 2, 3, 4)
    assert data["anc_grade"] in (0, 1, 2, 3, 4)
    assert data["abnormal_grade"] == max(data["alt_grade"], data["anc_grade"]), (
        "abnormal_grade is whichever component grade is higher"
    )
    assert isinstance(data["triggers_hold"], bool)
    assert data["triggers_hold"] is (data["abnormal_grade"] >= 3), (
        "triggers_hold is true exactly when abnormal_grade is at least 3"
    )
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_infusion_appointment(data: dict):
    _assert_common_fields(data, "InfusionAppointment")
    assert is_valid_uuid(data["episode_id"])
    assert is_valid_uuid(data["chair_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["dose_sequence"], int) and data["dose_sequence"] >= 1
    assert data["status"] in ("SCHEDULED", "ADMINISTERED", "CANCELLED")
    assert_cents(data["dose_cost_share_cents"], "dose_cost_share_cents")
    assert_cents(data["assistance_applied_cents"], "assistance_applied_cents")
    assert_cents(data["patient_out_of_pocket_cents"], "patient_out_of_pocket_cents")
    assert (
        data["patient_out_of_pocket_cents"]
        == data["dose_cost_share_cents"] - data["assistance_applied_cents"]
    ), "patient_out_of_pocket_cents is the gross share less assistance_applied_cents"


def assert_assistance_enrollment(data: dict):
    _assert_common_fields(data, "AssistanceEnrollment")
    assert is_valid_uuid(data["episode_id"])
    assert data["program_type"] in (
        "MANUFACTURER_COPAY_CARD", "FOUNDATION_GRANT", "PATIENT_ASSISTANCE_PROGRAM",
    )
    assert_cents(data["annual_benefit_cents"], "annual_benefit_cents")
    assert data["annual_benefit_cents"] > 0
    assert_cents(data["benefit_used_cents"], "benefit_used_cents")
    assert_cents(data["benefit_reserved_cents"], "benefit_reserved_cents")
    assert_cents(data["benefit_remaining_cents"], "benefit_remaining_cents")
    assert data["status"] in ("SUBMITTED", "ACTIVE", "EXHAUSTED", "REAUTH_PENDING", "TERMINATED")
    assert is_iso8601_timestamp(data["coverage_start"])
    assert is_iso8601_timestamp(data["coverage_end"])
    assert is_iso8601_timestamp(data["reauth_due_at"])
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]


# --------------------------------------------------------------------------
# Conserved-quantity invariants (PRD §2.8)
# --------------------------------------------------------------------------
def assert_unit_ledger_conserved(auth: dict):
    """`approved_units` == `units_consumed` + `units_reserved` + `units_remaining`."""
    if auth.get("approved_units") is None:
        return
    total = auth["units_consumed"] + auth["units_reserved"] + auth["units_remaining"]
    assert auth["approved_units"] == total, (
        "unit ledger broken: approved_units "
        f"{auth['approved_units']} != consumed {auth['units_consumed']} + reserved "
        f"{auth['units_reserved']} + remaining {auth['units_remaining']}"
    )


def assert_unit_ledger(auth: dict, reserved: int, consumed: int, remaining: int):
    assert auth["units_reserved"] == reserved, (
        f"expected units_reserved {reserved}, got {auth['units_reserved']}"
    )
    assert auth["units_consumed"] == consumed, (
        f"expected units_consumed {consumed}, got {auth['units_consumed']}"
    )
    assert auth["units_remaining"] == remaining, (
        f"expected units_remaining {remaining}, got {auth['units_remaining']}"
    )
    assert_unit_ledger_conserved(auth)


def assert_money_ledger_conserved(enrollment: dict):
    """`annual_benefit_cents` == used + reserved + remaining."""
    total = (
        enrollment["benefit_used_cents"]
        + enrollment["benefit_reserved_cents"]
        + enrollment["benefit_remaining_cents"]
    )
    assert enrollment["annual_benefit_cents"] == total, (
        "money ledger broken: annual_benefit_cents "
        f"{enrollment['annual_benefit_cents']} != used {enrollment['benefit_used_cents']} + "
        f"reserved {enrollment['benefit_reserved_cents']} + remaining "
        f"{enrollment['benefit_remaining_cents']}"
    )


def assert_money_ledger(enrollment: dict, used: int, reserved: int, remaining: int):
    assert enrollment["benefit_used_cents"] == used, (
        f"expected benefit_used_cents {used}, got {enrollment['benefit_used_cents']}"
    )
    assert enrollment["benefit_reserved_cents"] == reserved, (
        f"expected benefit_reserved_cents {reserved}, got {enrollment['benefit_reserved_cents']}"
    )
    assert enrollment["benefit_remaining_cents"] == remaining, (
        f"expected benefit_remaining_cents {remaining}, got {enrollment['benefit_remaining_cents']}"
    )
    assert_money_ledger_conserved(enrollment)


def assert_cost_share_estimate(
    estimate: dict,
    allowed_per_dose_cents: int,
    facility_per_dose_cents: int,
    per_dose_share_cents: List[int],
):
    """The estimate reports the whole waterfall picture (PRD §3.7)."""
    assert estimate["allowed_per_dose_cents"] == allowed_per_dose_cents
    assert estimate["facility_per_dose_cents"] == facility_per_dose_cents
    assert estimate["per_dose_share_cents"] == per_dose_share_cents, (
        f"expected per_dose_share_cents {per_dose_share_cents}, "
        f"got {estimate['per_dose_share_cents']}"
    )
    assert estimate["total_member_share_cents"] == sum(per_dose_share_cents)
    assert (
        estimate["deductible_applied_cents"]
        + estimate["coinsurance_cents"]
        + estimate["facility_cents"]
        == estimate["total_member_share_cents"]
    ), "the three component sums must add up to total_member_share_cents"
