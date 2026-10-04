"""Per-entity response assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ANCILLARY_SHARE_PCT,
    LIVE_BIRTH_WEIGHT_BPS,
    MATURITY_BONUS_BPS,
    MATURITY_CAP,
    MULTIPLE_BIRTH_PENALTY_BPS,
)


def assert_common_fields(data: dict):
    """Every top-level resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_employer_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["employer_name"], str) and data["employer_name"]
    assert isinstance(data["plan_year"], int)
    assert data["funding_type"] in ("SELF_FUNDED", "FULLY_INSURED")
    assert data["allocation_method"] in ("SEQUENTIAL_BUNDLE", "CONCURRENT_BUNDLE")
    assert isinstance(data["enrollment_limit"], int)
    assert data["account_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["active_member_count"], int) and data["active_member_count"] >= 0
    assert isinstance(data["entitlement_count"], int) and data["entitlement_count"] >= 0


def assert_bundle_entitlement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["employer_account_id"]), "employer_account_id must be a UUID"
    assert data["bundle_type"] in (
        "DIAGNOSTIC_IUI", "IVF_RETRIEVAL_TRANSFER", "PRESERVATION",
        "DONOR_EGG", "DONOR_SPERM", "SURROGACY", "MEDICATION",
    )
    for counter in ("lifetime_max_cycles", "max_cycles_per_year", "max_transfers_per_cycle",
                    "cycles_consumed", "cycles_committed", "cycles_remaining",
                    "pharmacy_pool_cents", "pharmacy_consumed_cents", "pharmacy_remaining_cents"):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    assert data["cycles_remaining"] >= 0, "cycles_remaining is floored at zero"
    assert data["pharmacy_remaining_cents"] >= 0, "pharmacy_remaining_cents is floored at zero"
    assert data["cycles_consumed"] <= data["lifetime_max_cycles"]
    assert isinstance(data["copay_max"], bool)
    assert data["bundle_status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXHAUSTED")


def assert_bundle_invariants(data: dict):
    """Ledger invariants that hold after any operation on the entitlement."""
    assert data["cycles_remaining"] >= 0
    assert data["cycles_consumed"] >= 0
    assert data["pharmacy_consumed_cents"] >= 0
    assert data["pharmacy_remaining_cents"] >= 0
    assert data["pharmacy_consumed_cents"] + data["pharmacy_remaining_cents"] <= data["pharmacy_pool_cents"]


def assert_care_advocate(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["states_licensed"], list)
    assert isinstance(data["specializations"], list)
    assert isinstance(data["caseload_limit"], int)
    assert is_iso8601_timestamp(data["credentials_expire_on"])
    assert isinstance(data["current_caseload"], int) and data["current_caseload"] >= 0
    assert isinstance(data["assignments_completed"], int) and data["assignments_completed"] >= 0
    assert data["advocate_status"] in ("ACTIVE", "AT_CAPACITY", "INACTIVE")


def assert_member(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["employer_account_id"])
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["state_code"], str)
    assert data["required_track"] in (
        "STANDARD_IVF", "DIAGNOSTIC_IUI", "PRESERVATION",
        "DONOR_EGG", "DONOR_SPERM", "SURROGACY",
    )
    assert data["member_status"] in ("INTAKE", "CARE_ACTIVE", "CARE_COMPLETE")
    assert data["pathway_selected"] in (
        "NONE", "PRESERVATION", "DONOR_EGG", "DONOR_SPERM", "SURROGACY",
    )
    assert data["care_advocate_id"] is None or is_valid_uuid(data["care_advocate_id"])
    assert data["clinic_id"] is None or is_valid_uuid(data["clinic_id"])
    assert isinstance(data["completed_cycles"], int) and data["completed_cycles"] >= 0
    assert isinstance(data["live_births_recorded"], int) and data["live_births_recorded"] >= 0
    if data["member_status"] == "INTAKE":
        assert data["intake_completed_at"] is None, "intake_completed_at is null while INTAKE"


def assert_clinic(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10 and data["npi"].isdigit()
    assert isinstance(data["state_code"], str)
    assert data["network_tier"] in ("PREFERRED", "STANDARD", "OUT_OF_NETWORK")
    for field in ("min_live_birth_rate_bps", "max_multiple_birth_rate_bps",
                  "required_quality_report_count", "maturity_report_threshold",
                  "live_birth_rate_bps", "multiple_birth_rate_bps",
                  "composite_quality_bps", "cycles_reported"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["live_birth_rate_bps"] >= 0
    assert data["multiple_birth_rate_bps"] >= 0
    assert data["cycles_reported"] >= 0
    assert data["clinic_status"] in (
        "IN_REVIEW", "CONTRACTED", "PROBATION", "SUSPENDED", "TERMINATED",
    )


def assert_clinic_quality_invariants(data: dict):
    """The published rate readings are ten-thousandths, so they cannot exceed 10000."""
    assert 0 <= data["live_birth_rate_bps"] <= 10000
    assert 0 <= data["multiple_birth_rate_bps"] <= 10000
    if data["cycles_reported"] == 0:
        assert data["live_birth_rate_bps"] == 0
        assert data["multiple_birth_rate_bps"] == 0
        assert data["composite_quality_bps"] == 0


def assert_clinic_contract(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["clinic_id"])
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["effective_from"] < data["effective_to"], "the coverage interval is half-open"
    assert isinstance(data["bundle_rates"], dict)
    assert data["contracting_status"] in ("IN_REVIEW", "ACTIVE", "FROZEN", "TERMINATED")
    if data["contracting_status"] == "FROZEN":
        assert isinstance(data["frozen_reason"], str) and data["frozen_reason"]
    else:
        assert data["frozen_reason"] is None, "frozen_reason is populated only while FROZEN"


def assert_treatment_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["care_advocate_id"])
    assert is_valid_uuid(data["bundle_entitlement_id"])
    assert data["clinic_id"] is None or is_valid_uuid(data["clinic_id"])
    assert data["pathway_type"] in (
        "STANDARD_IVF", "DIAGNOSTIC_IUI", "PRESERVATION",
        "DONOR_EGG", "DONOR_SPERM", "SURROGACY",
    )
    assert data["plan_status"] in (
        "PLAN_DRAFT", "CLINIC_SELECTED", "AUTHORIZATION_PENDING",
        "IN_PROGRESS", "PLANNING_REVISION", "COMPLETED", "ABANDONED",
    )
    assert isinstance(data["planned_cycles"], int)
    assert isinstance(data["selected_bundle_price_cents"], int)
    assert isinstance(data["cycles_completed"], int) and data["cycles_completed"] >= 0


def assert_preauthorization(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["treatment_plan_id"])
    assert isinstance(data["cycle_sequence_index"], int) and data["cycle_sequence_index"] >= 1
    assert data["review_status"] in (
        "SUBMITTED", "CLINICAL_REVIEW", "APPROVED", "DENIED", "EXPIRED",
    )
    assert data["consumption_status"] in ("UNCONSUMED", "PARTIALLY_CONSUMED", "EXHAUSTED")
    assert isinstance(data["approved_cycles"], int)
    assert isinstance(data["consumed_cycles"], int) and data["consumed_cycles"] >= 0
    assert isinstance(data["bundle_price_snapshot_cents"], int)
    assert isinstance(data["member_cost_share_pct"], int)
    assert 0 <= data["member_cost_share_pct"] <= 100


def assert_treatment_cycle(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["treatment_plan_id"])
    assert is_valid_uuid(data["preauthorization_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert data["cycle_status"] in (
        "SCHEDULED", "STIMULATION", "RETRIEVAL", "FERTILIZATION",
        "TRANSFER", "OUTCOME_PENDING", "OUTCOME_RECORDED", "CANCELLED",
    )
    assert data["consumption_marker"] in ("UNCONSUMED", "CONSUMED")
    assert isinstance(data["embryos_transferred"], int)
    if data["cycle_status"] == "OUTCOME_RECORDED":
        assert data["consumption_marker"] == "CONSUMED", "a recorded cycle consumes its slot"
    if data["cycle_status"] == "CANCELLED":
        assert data["consumption_marker"] == "UNCONSUMED", "a cancelled cycle releases its slot"


def assert_medication_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["preauthorization_id"])
    assert isinstance(data["medication_code"], str) and data["medication_code"]
    assert isinstance(data["specialty_drug"], bool)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["days_supply"], int)
    assert isinstance(data["acquisition_cost_cents"], int)
    assert data["pharmacy_status"] in (
        "PRESCRIBED", "DISPENSING", "DISPENSED", "SHIPPED", "DELIVERED", "CANCELLED",
    )
    assert isinstance(data["plan_paid_cents"], int)
    assert isinstance(data["member_cost_cents"], int)
    assert data["plan_paid_cents"] >= 0
    assert data["member_cost_cents"] >= 0
    assert data["plan_paid_cents"] + data["member_cost_cents"] == data["acquisition_cost_cents"]


def assert_pathway_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["pathway_type"] in ("PRESERVATION", "DONOR_EGG", "DONOR_SPERM", "SURROGACY")
    assert data["pathway_status"] in (
        "DRAFT", "CLINICAL_REVIEW", "APPROVED", "DENIED",
        "ACTIVE", "COMPLETED", "WITHDRAWN",
    )
    assert isinstance(data["consent_signed"], bool)
    assert isinstance(data["coverage_pct"], int)
    assert 0 <= data["coverage_pct"] <= 100
    assert isinstance(data["pathway_cost_cents"], int)


def assert_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["preauthorization_id"])
    assert data["service_category"] in (
        "CLINIC_BUNDLE", "MEDICATION", "LAB", "STORAGE", "DONOR_MATERIAL", "SURROGACY_FEE",
    )
    assert data["claim_status"] in (
        "RECEIVED", "PENDED", "ADJUDICATED", "DENIED", "APPEALED", "PAID", "REVERSED",
    )
    for field in ("billed_cents", "allowed_cents", "member_cost_share_cents",
                  "plan_paid_cents", "member_accumulator_before_cents",
                  "member_accumulator_after_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["plan_paid_cents"] >= 0, "plan_paid_cents is never negative"
    assert data["member_cost_share_cents"] >= 0


def assert_claim_invariants(data: dict):
    """plan_paid_cents is the allowance less the member share and never negative."""
    assert data["plan_paid_cents"] >= 0
    if data["claim_status"] in ("ADJUDICATED", "PAID"):
        assert data["member_cost_share_cents"] + data["plan_paid_cents"] == data["allowed_cents"]
    if data["claim_status"] in ("DENIED", "REVERSED"):
        assert data["plan_paid_cents"] == 0
        assert data["member_cost_share_cents"] == 0


def assert_outcome_record(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["clinic_id"])
    assert is_valid_uuid(data["treatment_cycle_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["live_birth"], bool)
    assert isinstance(data["births_count"], int) and data["births_count"] >= 0
    assert isinstance(data["multiple_birth"], bool)
    assert isinstance(data["gestational_weeks"], int)
    assert is_iso8601_timestamp(data["outcome_recorded_on"])
    assert data["outcome_status"] in ("RECORDED", "AMENDED", "VOIDED")
    if data["outcome_status"] == "AMENDED":
        assert isinstance(data["amendment_reason"], str) and data["amendment_reason"]
    if data["outcome_status"] == "VOIDED":
        assert isinstance(data["void_reason"], str) and data["void_reason"]


def assert_surrender_route(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["pathway_type"] in ("PRESERVATION", "DONOR_EGG", "DONOR_SPERM", "SURROGACY")
    assert data["carrier_kind"] in ("MEMBER", "GESTATIONAL_CARRIER", "CUSTODIAN")
    assert is_iso8601_timestamp(data["route_from"])
    assert is_iso8601_timestamp(data["route_to"])
    assert data["route_from"] < data["route_to"], "the occupancy window is end-exclusive"
    assert data["route_status"] in ("SUBMITTED", "ROUTED", "RETIRED", "WITHDRAWN")
    assert isinstance(data["surrender_cost_cents"], int)


# --- Composite / calculation assertions -----------------------------------------

def assert_quality_composite(data: dict):
    """composite_quality_bps is a weighted reading over the same workset."""
    expected = round(
        LIVE_BIRTH_WEIGHT_BPS * min(data["live_birth_rate_bps"], 10000)
        - MULTIPLE_BIRTH_PENALTY_BPS * data["multiple_birth_rate_bps"]
        + MATURITY_BONUS_BPS * min(data["cycles_reported"], MATURITY_CAP)
    )
    assert data["composite_quality_bps"] == expected, (
        f"composite_quality_bps {data['composite_quality_bps']} != derived {expected}"
    )


def assert_ancillary_slice(allowed_cents: int, ceiling_cents: int, service_category: str,
                           billed_cents: int):
    """An ancillary allowance is the smaller of the bill and the category's own slice."""
    pct = ANCILLARY_SHARE_PCT[service_category]
    slice_cents = (ceiling_cents * pct + 50) // 100
    assert allowed_cents == min(billed_cents, slice_cents), (
        f"{service_category} allowance {allowed_cents} != min({billed_cents}, {slice_cents})"
    )


def assert_accumulator_advanced(claim_before: dict, claim_after: dict):
    """member_accumulator_after_cents is the before value plus the member's share."""
    assert claim_after["member_accumulator_after_cents"] == (
        claim_after["member_accumulator_before_cents"] + claim_after["member_cost_share_cents"]
    ), "the member accumulator must advance by exactly the member share"


def assert_pharmacy_pool_conserved(bundle: dict):
    """pharmacy_consumed_cents + pharmacy_remaining_cents == pharmacy_pool_cents."""
    assert bundle["pharmacy_consumed_cents"] + bundle["pharmacy_remaining_cents"] == (
        bundle["pharmacy_pool_cents"]
    ), "the specialty-pharmacy pool is conserved across every draw and release"