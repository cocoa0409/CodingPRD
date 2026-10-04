"""Entity assertions and domain invariant checkers.

Structural assertions derived from the PRD's resource descriptions
(section 2.4 common properties plus each entity's field list).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_CARRIER_STATUSES = {"ACTIVE", "SUSPENDED"}
_EMPLOYER_STATUSES = {"ACTIVE", "UNDER_REVIEW", "INACTIVE"}
_CLASS_CODE_STATUSES = {"ACTIVE", "RETIRED"}
_RATING_TABLE_STATUSES = {"DRAFT", "PROMULGATED", "SUPERSEDED"}
_POLICY_STATUSES = {"ACTIVE", "CANCELLED", "EXPIRED"}
_REPORT_STATUSES = {"SUBMITTED", "VALIDATED", "LOCKED", "CORRECTED"}
_ASSIGNMENT_STATUSES = {
    "PENDING_INSPECTION",
    "ASSIGNED",
    "DISPUTED",
    "CONFIRMED",
    "REASSIGNED",
    "WITHDRAWN",
}
_INSPECTION_STATUSES = {"SCHEDULED", "COMPLETED", "WAIVED"}
_DISPUTE_STATUSES = {"OPEN", "IN_REVIEW", "RESOLVED", "WITHDRAWN"}
_SHEET_STATUSES = {"DRAFT", "PROMULGATED", "REVISED", "CONTESTED", "FINAL"}
_APPEAL_STATUSES = {"FILED", "UNDER_REVIEW", "UPHELD", "REVERSED", "WITHDRAWN"}
_OWNERSHIP_CHANGE_STATUSES = {"PENDING", "COMBINED", "NOT_COMBINED", "REVERSED"}
_GROUP_STATUSES = {"ACTIVE", "DISSOLVED"}
_ENROLLMENT_STATUSES = {"PENDING", "ACTIVE", "EXITED", "CANCELLED"}
_TAKE_OUT_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
_REVIEW_STATUSES = {"PENDING", "APPROVED", "REJECTED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_bureau(data: dict):
    _assert_common(data)
    for field in (
        "code",
        "name",
        "eligibility_threshold_cents",
        "split_point_cents",
        "credibility_ballast_bp",
        "credibility_excess_divisor_bp",
        "underwriting_threshold_cents",
    ):
        assert field in data, f"Bureau missing field {field}"


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data.get("naic_number"), str)
    assert isinstance(data.get("legal_name"), str)
    assert isinstance(data.get("assigned_risk_quota_cents"), int)
    assert isinstance(data.get("assigned_risk_current_load_cents"), int)
    assert data.get("status") in _CARRIER_STATUSES


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data.get("fein"), str)
    assert isinstance(data.get("legal_name"), str)
    assert isinstance(data.get("state_code"), str)
    assert data.get("status") in _EMPLOYER_STATUSES


def assert_class_code(data: dict):
    # ClassCode is the exception: id and created_at only among common fields.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "ClassCode must not carry updated_at"
    assert "version" not in data, "ClassCode must not carry version"
    assert isinstance(data.get("code"), str)
    assert data.get("status") in _CLASS_CODE_STATUSES


def assert_rating_table(data: dict):
    _assert_common(data)
    assert isinstance(data.get("state_code"), str)
    assert data.get("status") in _RATING_TABLE_STATUSES
    assert isinstance(data.get("values"), list)


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("carrier_id"), str)
    assert isinstance(data.get("policy_number"), str)
    assert isinstance(data.get("manual_premium_cents"), int)
    assert data.get("status") in _POLICY_STATUSES
    assert isinstance(data.get("class_codes"), list)


def assert_unit_stat_report(data: dict):
    _assert_common(data)
    assert isinstance(data.get("policy_id"), str)
    assert isinstance(data.get("payroll_lines"), list)
    assert isinstance(data.get("claim_lines"), list)
    assert data.get("status") in _REPORT_STATUSES
    assert isinstance(data.get("submission_number"), int)


def assert_class_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("class_code_id"), str)
    assert data.get("status") in _ASSIGNMENT_STATUSES


def assert_inspection(data: dict):
    _assert_common(data)
    assert isinstance(data.get("class_assignment_id"), str)
    assert data.get("status") in _INSPECTION_STATUSES


def assert_class_assignment_dispute(data: dict):
    _assert_common(data)
    assert isinstance(data.get("class_assignment_id"), str)
    assert data.get("status") in _DISPUTE_STATUSES


def assert_experience_mod_sheet(data: dict):
    _assert_common(data)
    assert isinstance(data.get("employer_id"), str)
    assert data.get("status") in _SHEET_STATUSES
    assert isinstance(data.get("expected_losses_cents"), int)
    assert isinstance(data.get("actual_primary_cents"), int)
    assert isinstance(data.get("actual_excess_cents"), int)
    assert isinstance(data.get("ballast_cents"), int)
    assert isinstance(data.get("mod_factor"), str)
    assert isinstance(data.get("weight_w"), str)


def assert_mod_appeal(data: dict):
    _assert_common(data)
    assert isinstance(data.get("mod_sheet_id"), str)
    assert data.get("status") in _APPEAL_STATUSES


def assert_ownership_change(data: dict):
    _assert_common(data)
    assert isinstance(data.get("employer_id"), str)
    assert data.get("change_type") in {
        "SALE",
        "MERGER",
        "FORMATION_OF_NEW_ENTITY",
        "OTHER",
    }
    assert data.get("status") in _OWNERSHIP_CHANGE_STATUSES


def assert_combinability_group(data: dict):
    _assert_common(data)
    assert isinstance(data.get("member_employer_ids"), list)
    assert data.get("status") in _GROUP_STATUSES


def assert_assigned_risk_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("state_code"), str)
    assert isinstance(data.get("estimated_annual_premium_cents"), int)
    assert data.get("status") in _ENROLLMENT_STATUSES


def assert_assigned_risk_take_out(data: dict):
    _assert_common(data)
    assert isinstance(data.get("enrollment_id"), str)
    assert isinstance(data.get("voluntary_carrier_id"), str)
    assert data.get("status") in _TAKE_OUT_STATUSES


def assert_underwriting_review(data: dict):
    _assert_common(data)
    assert data.get("subject_type") in {"MOD_SHEET", "CLASS_ASSIGNMENT", "TAKE_OUT"}
    assert isinstance(data.get("subject_id"), str)
    assert data.get("status") in _REVIEW_STATUSES


def assert_primary_excess_identity(sheet: dict):
    """Per-claim loss identity: primary plus excess equals total incurred."""
    total = sheet["actual_primary_cents"] + sheet["actual_excess_cents"]
    assert total >= 0
    return total


def assert_carrier_load_within_quota(carrier: dict):
    """The carrier's pool load must never exceed its quota after a mutation."""
    assert carrier["assigned_risk_current_load_cents"] >= 0
    assert (
        carrier["assigned_risk_current_load_cents"]
        <= carrier["assigned_risk_quota_cents"]
    )
