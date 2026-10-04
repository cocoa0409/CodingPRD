"""Entity assertions and domain invariant checkers (field rules from PRD §2–§3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

PLAN_STATUSES = [
    "DRAFT", "OPEN_FOR_COMMENT", "UNDER_REVIEW", "APPROVED",
    "APPROVED_WITH_CONDITIONS", "REJECTED", "SUPERSEDED",
]
RESOURCE_STATUSES = ["ACTIVE", "DECIDED", "RETIRED", "MOTHBALLED"]
RESOURCE_TYPES = [
    "COAL", "GAS_CC", "GAS_CT", "NUCLEAR", "HYDRO",
    "SOLAR", "WIND", "STORAGE", "DEMAND_RESPONSE",
]
FUEL_TYPES = ["COAL", "NATURAL_GAS", "URANIUM", "WATER", "SUN", "WIND", "NONE"]
SCENARIO_TAGS = ["BASE", "HIGH_ELECTRIFICATION", "LOW_GROWTH"]
PORTFOLIO_STATUSES = ["DRAFT", "FROZEN"]
ANALYSIS_STATUSES = ["DRAFT", "FINAL"]
RECOMMENDATIONS = ["RETIRE", "KEEP"]
COMMENT_STATUSES = ["RECEIVED", "ACKNOWLEDGED"]
TESTIMONY_STATUSES = ["FILED", "WITHDRAWN"]
COMMITMENT_STATUSES = ["ISSUED", "AWARDED", "CANCELLED"]
CONDITION_STATUSES = ["OPEN", "DISCHARGED"]
PARTY_TYPES = ["CONSUMER_ADVOCATE", "INDUSTRIAL_GROUP", "ENVIRONMENTAL_ORG", "MUNICIPALITY"]
SENSITIVITY_DIMENSIONS = ["FUEL_PRICE", "POLICY", "TECHNOLOGY_COST"]


def _assert_id_and_created_at(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"


def _assert_mutable_common(data: dict, label: str):
    _assert_id_and_created_at(data, label)
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{label}.version must be a positive int"


def assert_plan(data: dict):
    _assert_mutable_common(data, "ResourcePlan")
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert isinstance(data["cycle_year"], int)
    assert isinstance(data["planning_horizon_years"], int) and data["planning_horizon_years"] >= 10
    assert data["status"] in PLAN_STATUSES
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_forecast(data: dict):
    _assert_mutable_common(data, "LoadForecast")
    assert data["scenario_tag"] in SCENARIO_TAGS
    assert isinstance(data["forecast_year"], int)
    for field in ("residential_mw", "commercial_mw", "industrial_mw", "electrification_mw"):
        assert data[field] >= 0, f"LoadForecast.{field} must be >= 0"
    assert isinstance(data["total_peak_mw"], (int, float))
    assert isinstance(data["effective_load_mw"], (int, float))
    assert isinstance(data["locked"], bool)


def assert_resource(data: dict):
    _assert_mutable_common(data, "Resource")
    assert isinstance(data["unit_name"], str) and data["unit_name"]
    assert data["resource_type"] in RESOURCE_TYPES
    assert data["fuel_type"] in FUEL_TYPES
    assert data["nameplate_mw"] > 0
    assert isinstance(data["in_service_year"], int)
    assert data["status"] in RESOURCE_STATUSES


def assert_portfolio(data: dict):
    _assert_mutable_common(data, "ResourcePortfolio")
    assert isinstance(data["portfolio_name"], str) and data["portfolio_name"]
    assert isinstance(data["preferred_flag"], bool)
    assert data["status"] in PORTFOLIO_STATUSES


def assert_candidate(data: dict):
    _assert_mutable_common(data, "ResourceCandidate")
    assert isinstance(data["candidate_name"], str) and data["candidate_name"]
    assert data["resource_type"] in RESOURCE_TYPES
    assert data["fuel_type"] in FUEL_TYPES
    assert data["nameplate_mw"] > 0
    assert isinstance(data["online_year"], int) and data["online_year"] >= 2026
    assert data["capex_usd_per_kw"] > 0
    assert data["fixed_om_usd_per_kw_year"] >= 0
    assert isinstance(data["build_lead_years"], int) and data["build_lead_years"] >= 1
    assert isinstance(data["global_sequence_index"], int) and data["global_sequence_index"] >= 1


def assert_position(data: dict):
    """Append-only junction (PRD §2.5): only id + created_at, never version/updated_at."""
    _assert_id_and_created_at(data, "Position")
    assert "version" not in data, "Position must not carry version"
    assert "updated_at" not in data, "Position must not carry updated_at"
    assert data["committed_mw"] > 0
    assert isinstance(data["selected"], bool)


def assert_snapshot(data: dict):
    """Computed immutable artifact (PRD §2.5): only id + created_at."""
    _assert_id_and_created_at(data, "ReliabilitySnapshot")
    assert "version" not in data, "ReliabilitySnapshot must not carry version"
    assert "updated_at" not in data, "ReliabilitySnapshot must not carry updated_at"
    assert isinstance(data["forecast_year"], int)
    assert data["scenario_tag"] in SCENARIO_TAGS
    assert data["fuel_price_usd_per_mmbtu"] > 0
    assert isinstance(data["accredited_supply_mw"], (int, float))
    assert isinstance(data["load_mw"], (int, float))
    assert isinstance(data["capacity_margin_mw"], (int, float))
    assert isinstance(data["meets_requirement"], bool)


def assert_retirement_analysis(data: dict):
    _assert_mutable_common(data, "RetirementAnalysis")
    assert data["status"] in ANALYSIS_STATUSES
    assert data["recommendation"] in RECOMMENDATIONS
    for field in (
        "compliance_cost_usd", "replacement_cost_usd",
        "fixed_om_avoided_usd", "net_retirement_benefit_usd",
    ):
        assert isinstance(data[field], (int, float)), f"RetirementAnalysis.{field} must be numeric"


def assert_comment(data: dict):
    _assert_mutable_common(data, "PublicComment")
    assert isinstance(data["commenter_name"], str) and data["commenter_name"]
    assert isinstance(data["commenter_email"], str) and data["commenter_email"]
    assert isinstance(data["body"], str) and data["body"]
    assert data["status"] in COMMENT_STATUSES


def assert_intervenor(data: dict):
    _assert_mutable_common(data, "Intervenor")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["party_type"] in PARTY_TYPES
    assert isinstance(data["standing_approved"], bool)


def assert_testimony(data: dict):
    _assert_mutable_common(data, "IntervenorTestimony")
    assert isinstance(data["topic"], str)
    assert isinstance(data["body"], str) and data["body"]
    assert isinstance(data["volume_no"], int) and data["volume_no"] >= 1
    assert data["status"] in TESTIMONY_STATUSES


def assert_sensitivity(data: dict):
    _assert_mutable_common(data, "SensitivityAnalysis")
    assert data["dimension"] in SENSITIVITY_DIMENSIONS
    assert -0.50 <= data["delta_pct"] <= 0.50
    assert isinstance(data["base_score_usd"], (int, float))
    assert isinstance(data["adjusted_score_usd"], (int, float))
    assert isinstance(data["robust_flag"], bool)


def assert_commitment(data: dict):
    _assert_mutable_common(data, "ProcurementCommitment")
    assert data["committed_mw"] > 0
    assert data["solicitation_type"] in ["RFP", "SELF_BUILD"]
    assert data["status"] in COMMITMENT_STATUSES


def assert_condition(data: dict):
    _assert_mutable_common(data, "PlanCondition")
    assert isinstance(data["description"], str)
    assert data["required_procurement_mw"] >= 0
    assert data["status"] in CONDITION_STATUSES


def assert_deviation_report(data: dict):
    """Immutable filing (PRD §2.5): only id + created_at."""
    _assert_id_and_created_at(data, "PlanDeviationReport")
    assert "version" not in data, "PlanDeviationReport must not carry version"
    assert "updated_at" not in data, "PlanDeviationReport must not carry updated_at"
    assert isinstance(data["report_year"], int)
    assert data["actual_load_mw"] >= 0
    assert isinstance(data["baseline_load_mw"], (int, float))
    assert isinstance(data["load_deviation_pct"], (int, float))
    assert isinstance(data["committed_procurement_mw"], (int, float))
    assert isinstance(data["required_procurement_mw"], (int, float))
    assert isinstance(data["procurement_deviation_mw"], (int, float))
    assert isinstance(data["material_breach"], bool)


def assert_snapshot_invariants(data: dict):
    """Domain invariants on a reliability snapshot (PRD §3.5)."""
    # meets_requirement is exactly the sign of capacity_margin_mw (zero passes).
    assert data["meets_requirement"] == (data["capacity_margin_mw"] >= 0), (
        "meets_requirement must equal (capacity_margin_mw >= 0)"
    )
