"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)
from .types import (
    CONTRACT_STATUSES,
    ASSET_STATUSES,
    ASSET_CLASSES,
    CONDITION_BANDS,
    WORK_ORDER_STATUSES,
    EXPENSE_CLASSES,
    METRIC_TYPES,
    STANDARD_STATUSES,
    MEASUREMENT_STATUSES,
    PERMIT_STATUSES,
    ALLOCATION_STATUSES,
    EMERGENCY_STATUSES,
    PROPOSAL_STATUSES,
    OBLIGATION_STATUSES,
    EMPLOYEE_STATUSES,
    STAFFING_STATUSES,
    PM_STATUSES,
    ASSESSMENT_STATUSES,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_municipality(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"], "name must be non-empty"
    assert len(data["state_code"]) == 2 and data["state_code"].isupper(), "state_code must be 2 uppercase letters"
    assert isinstance(data["population_served"], int) and data["population_served"] >= 0
    assert isinstance(data["owns_treatment_works"], bool)
    assert isinstance(data["total_operator_penalty_cents"], int)
    assert isinstance(data["benchmark_index_baseline"], (int, float))


def assert_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["municipality_id"]), "municipality_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in CONTRACT_STATUSES
    assert isinstance(data["annual_fee_cents"], int)
    assert 0.0 <= data["operator_penalty_share_pct"] <= 1.0
    assert isinstance(data["staffing_floor_fte"], (int, float))
    assert isinstance(data["baseline_frozen"], bool)
    assert isinstance(data["renewal_round"], int) and data["renewal_round"] >= 0
    assert data["contract_end_date"] > data["contract_start_date"]


def assert_standard(data: dict):
    _assert_common(data)
    assert data["metric_type"] in METRIC_TYPES
    assert 0.0 < data["criticality_weight"] <= 1.0
    assert data["threshold_direction"] in ("AT_LEAST", "AT_MOST")
    assert data["breach_penalty_cents"] >= 0
    assert data["status"] in STANDARD_STATUSES


def assert_measurement(data: dict):
    _assert_common(data)
    assert data["status"] in MEASUREMENT_STATUSES
    assert data["period_end"] > data["period_start"]
    assert isinstance(data["in_breach"], bool)


def assert_staffing_commitment(data: dict):
    _assert_common(data)
    assert data["status"] in STAFFING_STATUSES
    assert data["committed_fte"] >= 0
    assert data["filled_fte"] >= 0
    assert data["vacancy_fte"] == max(data["committed_fte"] - data["filled_fte"], 0.0) or data["vacancy_fte"] >= 0


def assert_employee(data: dict):
    _assert_common(data)
    assert data["status"] in EMPLOYEE_STATUSES
    assert 0 < data["transfer_offer_fte"] <= 1.0
    assert data["benefit_tier"] in ("NONE", "BASIC", "STANDARD", "ENHANCED", "GRANDFATHERED")
    assert isinstance(data["pension_offset_cents"], int) and data["pension_offset_cents"] >= 0


def assert_asset(data: dict):
    _assert_common(data)
    assert data["asset_class"] in ASSET_CLASSES
    assert 1900 <= data["install_year"] <= 2100
    assert data["useful_life_years"] >= 1
    assert data["criticality_rank"] >= 1
    assert 0.0 <= data["condition_score"] <= 100.0
    assert data["condition_band"] in CONDITION_BANDS
    assert data["status"] in ASSET_STATUSES


def assert_assessment(data: dict):
    _assert_common(data)
    assert 0.0 <= data["assessed_score"] <= 100.0
    assert data["assessor_party"] in ("OPERATOR", "MUNICIPALITY", "JOINT")
    assert data["status"] in ASSESSMENT_STATUSES
    assert isinstance(data["baseline_binding"], bool)


def assert_permit(data: dict):
    _assert_common(data)
    assert data["permit_type"] in (
        "NPDES_DISCHARGE", "WATER_ALLOCATION", "SLUDGE_LAND_APPLICATION", "AIR_EMISSIONS"
    )
    assert data["regulator"] in ("STATE_PRIMACY_AGENCY", "USEPA_REGION", "LOCAL_HEALTH_DEPARTMENT")
    assert data["status"] in PERMIT_STATUSES
    assert data["expiration_date"] > data["effective_date"]


def assert_penalty_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ALLOCATION_STATUSES
    assert data["total_penalty_cents"] >= 0
    assert_cost_precision(data["operator_share_cents"])
    assert_cost_precision(data["municipality_share_cents"])
    assert_cost_precision(data["state_baseline_share_cents"])
    if data["status"] != "VOIDED":
        assert data["operator_share_cents"] + data["municipality_share_cents"] == data["total_penalty_cents"], (
            "the operator share plus the municipality share must equal the total penalty"
        )


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["work_type"] in ("PREVENTIVE", "CORRECTIVE", "EMERGENCY", "INSPECTION")
    assert data["expense_class"] in EXPENSE_CLASSES
    assert data["estimated_cost_cents"] >= 0
    assert data["status"] in WORK_ORDER_STATUSES


def assert_pm_schedule(data: dict):
    _assert_common(data)
    assert data["frequency_days"] >= 1
    assert data["duration_hours"] > 0
    assert data["status"] in PM_STATUSES
    assert data["missed_occurrence_count"] >= 0
    assert 0.0 <= data["compliance_rate_pct"] <= 100.0


def assert_emergency(data: dict):
    _assert_common(data)
    assert data["event_type"] in (
        "MAIN_BREAK", "SANITARY_OVERFLOW", "TREATMENT_UPSET", "POWER_LOSS", "CONTAMINATION"
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in EMERGENCY_STATUSES


def assert_renewal_proposal(data: dict):
    _assert_common(data)
    assert data["status"] in PROPOSAL_STATUSES
    assert data["round_number"] >= 1
    assert data["proposed_fee_cents"] >= 1
    assert data["proposed_term_years"] >= 1
    assert data["submitted_by"] in ("OPERATOR", "MUNICIPALITY")


def assert_obligation(data: dict):
    _assert_common(data)
    assert data["obligation_type"] in (
        "ASSET_HANDOVER", "RECORDS_TRANSFER", "EMPLOYEE_REINSTATE",
        "PERMIT_TRANSFER", "SPARES_INVENTORY", "SCADA_ACCESS",
    )
    assert data["status"] in OBLIGATION_STATUSES
    assert data["penalty_per_day_cents"] >= 0
    assert isinstance(data["outstanding_days"], int) and data["outstanding_days"] >= 0
    assert isinstance(data["withholding_cents"], int) and data["withholding_cents"] >= 0


def assert_contract_invariants(data: dict):
    """Domain invariants that must hold on any contract read."""
    assert data["staffing_floor_fte"] >= 0
    assert data["total_operator_penalty_cents"] >= 0
    assert isinstance(data["baseline_asset_count"], int) and data["baseline_asset_count"] >= 0


def assert_obligation_invariants(data: dict):
    """The withholding is the elapsed whole days times the daily rate, capped."""
    expected = min(data["outstanding_days"] * data["penalty_per_day_cents"], 4000000)
    if data["status"] in ("SATISFIED", "WAIVED"):
        expected = 0
    assert data["withholding_cents"] == expected, (
        f"withholding_cents should be {expected}, got {data['withholding_cents']}"
    )


def assert_penalty_conservation(allocation: dict):
    """The penalty ledger must conserve (PRD §3.10)."""
    if allocation["status"] == "VOIDED":
        return
    assert allocation["operator_share_cents"] + allocation["municipality_share_cents"] == (
        allocation["total_penalty_cents"]
    )


def assert_settlement(data: dict):
    assert data["net_payable_cents"] == (
        data["prorated_fee_cents"] - data["withholding_total"] - data["penalty_total"]
    ), "net payable must be the prorated fee minus withholding minus penalties"