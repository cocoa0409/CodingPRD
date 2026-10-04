"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_funder(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"], "name must be non-empty"
    assert data["funder_type"] in [
        "FEDERAL", "STATE", "COUNTY", "PRIVATE_FOUNDATION", "DIOCESAN", "PARISH",
    ]
    assert isinstance(data["allow_faith_based_activity"], bool)
    assert isinstance(data["requires_time_and_effort_documentation"], bool)
    assert 0.0 <= data["max_admin_rate_pct"] <= 0.25
    assert 1 <= data["fiscal_year_start_month"] <= 12
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"], "name must be non-empty"
    assert data["service_domain"] in ["HOUSING", "FOOD", "COUNSELING", "IMMIGRATION", "REFUGEE"]
    assert isinstance(data["faith_based_activity_offered"], bool)
    assert isinstance(data["nondiscrimination_attested"], bool)
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 0
    assert isinstance(data["enrolled_slots"], int) and data["enrolled_slots"] >= 0
    assert isinstance(data["match_eligible"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]


def assert_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["funder_id"]), "funder_id must be a UUID"
    assert is_valid_uuid(data["program_id"]), "program_id must be a UUID"
    assert isinstance(data["grant_code"], str) and data["grant_code"]
    assert isinstance(data["total_award_cents"], int) and data["total_award_cents"] >= 0
    assert isinstance(data["expended_cents"], int) and data["expended_cents"] >= 0
    assert isinstance(data["obligated_cents"], int) and data["obligated_cents"] >= 0
    assert 0.0 <= data["admin_rate_pct"] <= 0.25
    assert isinstance(data["allocation_rank"], int) and data["allocation_rank"] >= 1
    assert isinstance(data["max_in_kind_rate_cents"], int) and data["max_in_kind_rate_cents"] >= 0
    assert 0.0 <= data["matching_requirement_pct"] <= 1.0
    assert data["cost_allocation_basis"] in [
        "DIRECT_ONLY", "HEADCOUNT", "TIME_AND_EFFORT", "SQUARE_FOOTAGE",
    ]
    assert data["status"] in ["OPEN", "THROTTLED", "FROZEN"]
    assert isinstance(data["burn_ratio"], (int, float))


def assert_grant_invariants(data: dict):
    """Domain invariants that hold on any grant read."""
    assert data["burn_ratio"] >= 0.0, "burn_ratio can never be negative"
    assert data["expended_cents"] >= 0, "expended_cents can never be negative"
    assert data["obligated_cents"] >= 0, "obligated_cents can never be negative"
    if data["total_award_cents"] == 0:
        assert data["burn_ratio"] == 0.0, "a zero-award grant carries burn_ratio 0.0"
    committed = data["expended_cents"] + data["obligated_cents"]
    if data["total_award_cents"] > 0:
        expected = round(committed / data["total_award_cents"], 6)
        assert abs(data["burn_ratio"] - expected) < 1e-6, (
            f"burn_ratio {data['burn_ratio']} must equal committed/award {expected}"
        )


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["immigration_status"] in [
        "CITIZEN", "LPR", "REFUGEE", "ASYLEE", "UNDOCUMENTED", "PENDING_ASYLUM",
    ]
    assert data["confidentiality_tier"] in ["STANDARD", "PROTECTED", "SEALED"]
    assert isinstance(data["consent_scope"], list)
    assert isinstance(data["open_enrollment_count"], int) and data["open_enrollment_count"] >= 0


def assert_intake_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["presenting_needs"], list) and len(data["presenting_needs"]) >= 1
    assert isinstance(data["requested_domains"], list) and len(data["requested_domains"]) >= 1
    assert data["status"] in ["DRAFT", "SUBMITTED", "ROUTED", "RETURNED", "CLOSED"]
    assert data["routing_outcome"] in ["PENDING", "ROUTED", "NO_ELIGIBLE_PROGRAM", "WITHDRAWN"]


def assert_eligibility_screen(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["intake_assessment_id"])
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["grant_id"])
    assert isinstance(data["verified_income_cents"], int) and data["verified_income_cents"] >= 0
    assert data["determination"] in ["PENDING", "ELIGIBLE", "INELIGIBLE"]
    assert data["verification_state"] in ["UNVERIFIED", "VERIFIED", "EXPIRED"]
    assert data["denial_reason_code"] in [
        "INCOME_OVER_LIMIT", "RESIDENCY", "IMMIGRATION_STATUS",
        "PROGRAM_AT_CAPACITY", "CONFIDENTIALITY_BAR", None,
    ]


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["grant_id"])
    assert data["status"] in ["PENDING", "ACTIVE", "SUSPENDED", "EXITED", "DENIED"]
    assert data["exit_reason"] in [
        "COMPLETED", "WITHDRAWN", "TRANSFERRED", "GRANT_TERMINATED", "NONCOMPLIANCE", None,
    ]


def assert_service_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["grant_id"])
    assert data["service_code"] in [
        "HOUSING_RENT_ASSIST", "FOOD_PANTRY_BOX", "CLINICAL_COUNSELING_HOUR",
        "IMMIGRATION_LEGAL_HOUR", "REFUGEE_CASE_MGMT_HOUR",
    ]
    assert isinstance(data["authorized_units"], int) and data["authorized_units"] >= 1
    assert isinstance(data["unit_rate_cents"], int) and data["unit_rate_cents"] >= 1
    assert isinstance(data["units_delivered"], int) and data["units_delivered"] >= 0
    assert data["status"] in ["DRAFT", "ACTIVE", "EXHAUSTED", "EXPIRED", "VOIDED"]


def assert_service_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_authorization_id"])
    assert is_valid_uuid(data["grant_id"])
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["units_delivered"], int) and data["units_delivered"] >= 0
    assert data["gross_cost_cents"] == data["units_delivered"] * data["unit_rate_cents"], (
        "gross_cost_cents must equal units_delivered * unit_rate_cents"
    )
    assert data["documentation_status"] in ["INCOMPLETE", "COMPLETE"]
    assert data["status"] in ["DRAFT", "DOCUMENTED", "BILLED", "REJECTED", "VOIDED"]


def assert_cost_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_delivery_id"])
    assert is_valid_uuid(data["grant_id"])
    assert isinstance(data["allocation_rank"], int) and data["allocation_rank"] >= 1
    assert data["allocation_basis"] in ["RANKED_PRIORITY", "CHRONOLOGICAL_PERIOD"]
    assert data["status"] in ["PROVISIONAL", "COMMITTED", "REVERSED"]


def assert_in_kind_donation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["grant_id"])
    assert data["donor_type"] in ["PARISH", "VOLUNTEER", "CORPORATE"]
    assert data["valuation_method"] in [
        "IRS_STANDARD_RATE", "APPRAISAL", "ACTUAL_COST", "UNVALUED",
    ]
    assert isinstance(data["hours"], (int, float)) and data["hours"] >= 0
    assert isinstance(data["rate_cents"], int) and data["rate_cents"] >= 0
    assert isinstance(data["value_cents"], int) and data["value_cents"] >= 0
    assert isinstance(data["uncapped_value_cents"], int) and data["uncapped_value_cents"] >= 0
    assert isinstance(data["match_credit_cents"], int) and data["match_credit_cents"] >= 0
    assert data["status"] in ["ACCEPTED", "REJECTED", "VOIDED"]


def assert_outcome_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["grant_id"])
    assert data["measure_code"] in [
        "HOUSING_PLACEMENTS", "FOOD_UNITS_DISTRIBUTED", "COUNSELING_COMPLETION",
        "IMMIGRATION_CASES_CLOSED", "REFUGEE_EMPLOYMENT",
    ]
    assert isinstance(data["numerator"], int) and data["numerator"] >= 0
    assert isinstance(data["denominator"], int) and data["denominator"] >= 0
    assert data["denominator_basis"] in ["ALL_SERVED", "COMPLETED_ONLY"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED"]
    if data["rate_pct"] is not None:
        assert 0.00 <= data["rate_pct"] <= 100.00, "rate_pct is null or between 0.00 and 100.00"


def assert_delivery_totals(delivery: dict, lines: list):
    """The delivery's braided totals must be the sums of its live allocation lines."""
    live = [ln for ln in lines if ln["status"] in ("PROVISIONAL", "COMMITTED")]
    allocated = sum(ln["allocated_amount_cents"] for ln in live)
    admin = sum(ln["admin_amount_cents"] for ln in live)
    assert delivery["allocated_total_cents"] == allocated, (
        f"allocated_total_cents {delivery['allocated_total_cents']} != line sum {allocated}"
    )
    assert delivery["admin_total_cents"] == admin, (
        f"admin_total_cents {delivery['admin_total_cents']} != line sum {admin}"
    )


def assert_admin_share(delivery: dict, rate_pct: float, expected_cents: int):
    """The pinned order rounds each line's admin share first, then sums."""
    assert delivery["admin_total_cents"] == expected_cents, (
        f"admin_total_cents {delivery['admin_total_cents']} != expected {expected_cents}"
    )
