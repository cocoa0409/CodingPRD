"""Entity assertions and domain invariant checkers.

``assert_<entity>(data)`` validates the shape of a single resource body:
identifier and timestamp formats, the full common-field quartet where the PRD
grants it (and its deliberate absence on the append-only TestResult), and the
membership of every status field in its declared vocabulary. Value-level
checks for calculated fields live in the tests themselves, where the PRD
sentence being exercised is quoted.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ComponentLotStatus,
    DcaStatus,
    HearingStatus,
    LicenseStatus,
    PipelineStatus,
    QualifiedVariant,
    QualificationStatus,
    RaiStatus,
    SarStatus,
    SitePermitStatus,
    SubscriptionStatus,
    TestOutcome,
    TestProgramStatus,
)


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def _assert_append_only_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} is append-only and must not carry updated_at"
    assert "version" not in data, f"{entity} is append-only and must not carry version"


def _assert_two_dp(value: float, field: str) -> None:
    """EPZ radii are stored at 2 decimal places, rounded half-up."""
    assert abs(value - round(value, 2)) < 1e-9, f"{field} must be stored at 2 decimal places"


def assert_dca(data: dict) -> None:
    _assert_common_fields(data, "DesignCertification")
    assert isinstance(data["docket_number"], str) and data["docket_number"]
    assert isinstance(data["reactor_model"], str) and data["reactor_model"]
    assert isinstance(data["target_power_mwt"], int) and data["target_power_mwt"] > 0
    assert isinstance(data["plant_net_capacity_mw"], int) and data["plant_net_capacity_mw"] > 0
    assert 0 < data["source_term_fraction"] <= 1
    assert data["site_boundary_miles"] >= 0.25
    assert data["status"] in [s.value for s in DcaStatus]
    assert data["review_phase"] in (0, 1, 2, 3, 4)
    _assert_two_dp(data["epz_radius_deterministic_miles"], "epz_radius_deterministic_miles")
    _assert_two_dp(data["epz_radius_dose_based_miles"], "epz_radius_dose_based_miles")
    _assert_two_dp(data["epz_radius_selected_miles"], "epz_radius_selected_miles")
    assert data["subscribed_mw"] >= 0
    assert data["available_mw"] == data["plant_net_capacity_mw"] - data["subscribed_mw"]
    assert data["funding_gap_usd"] >= 0


def assert_sar(data: dict) -> None:
    _assert_common_fields(data, "SafetyAnalysisReport")
    assert isinstance(data["section_code"], str) and data["section_code"]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0
    assert data["status"] in [s.value for s in SarStatus]
    assert data["open_rais"] >= 0


def assert_rai(data: dict) -> None:
    _assert_common_fields(data, "RAI")
    assert isinstance(data["dca_id"], str) and data["dca_id"]
    assert isinstance(data["sar_section_code"], str) and data["sar_section_code"]
    assert isinstance(data["question_text"], str) and data["question_text"]
    assert is_iso8601_timestamp(data["due_date"])
    assert data["status"] in [s.value for s in RaiStatus]
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]
    assert isinstance(data["late_response"], bool)


def assert_test_program(data: dict) -> None:
    _assert_common_fields(data, "TestProgram")
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["required_tests"], int) and data["required_tests"] > 0
    assert data["completed_tests"] >= 0
    assert data["status"] in [s.value for s in TestProgramStatus]


def assert_test_result(data: dict) -> None:
    _assert_append_only_fields(data, "TestResult")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert data["outcome"] in [s.value for s in TestOutcome]
    assert is_iso8601_timestamp(data["run_at"])


def assert_vendor(data: dict) -> None:
    _assert_common_fields(data, "Vendor")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capability_scope"], str) and data["capability_scope"]
    assert isinstance(data["qualified"], bool)
    assert isinstance(data["has_active_qualification"], bool)


def assert_vendor_qualification(data: dict) -> None:
    _assert_common_fields(data, "VendorQualification")
    assert isinstance(data["vendor_id"], str) and data["vendor_id"]
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert is_iso8601_timestamp(data["audit_date"])
    assert isinstance(data["defects_found"], int) and data["defects_found"] >= 0
    assert data["qualified_variant"] in [s.value for s in QualifiedVariant]
    assert data["status"] in [s.value for s in QualificationStatus]


def assert_component_lot(data: dict) -> None:
    _assert_common_fields(data, "ComponentLot")
    assert isinstance(data["vendor_id"], str) and data["vendor_id"]
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["component_type"], str) and data["component_type"]
    assert isinstance(data["nuclear_grade"], bool)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in [s.value for s in ComponentLotStatus]


def assert_site_permit(data: dict) -> None:
    _assert_common_fields(data, "SitePermit")
    assert data["permit_type"] in ("ESP", "COL")
    assert isinstance(data["dca_id"], str) and data["dca_id"]
    assert isinstance(data["site_name"], str) and data["site_name"]
    _assert_two_dp(data["epz_radius_miles"], "epz_radius_miles")
    assert data["status"] in [s.value for s in SitePermitStatus]


def assert_public_hearing(data: dict) -> None:
    _assert_common_fields(data, "PublicHearing")
    assert isinstance(data["permit_id"], str) and data["permit_id"]
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data["location"], str) and data["location"]
    assert data["status"] in [s.value for s in HearingStatus]


def assert_subscription(data: dict) -> None:
    _assert_common_fields(data, "SubscriptionCommitment")
    assert isinstance(data["dca_id"], str) and data["dca_id"]
    assert isinstance(data["utility_id"], str) and data["utility_id"]
    assert isinstance(data["committed_mw"], int) and data["committed_mw"] >= 1
    assert data["price_per_mwh_usd"] > 0
    assert data["status"] in [s.value for s in SubscriptionStatus]
    for field in (
        "cost_share_total_usd",
        "allocated_overrun_usd",
        "withdrawal_reserve_usd",
        "offload_penalty_usd",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"SubscriptionCommitment.{field} must be a non-negative integer dollar amount"
        )


def assert_cost_share_agreement(data: dict) -> None:
    _assert_common_fields(data, "CostShareAgreement")
    assert isinstance(data["dca_id"], str) and data["dca_id"]
    assert isinstance(data["total_cost_usd"], int) and data["total_cost_usd"] > 0
    assert isinstance(data["gov_contribution_usd"], int)
    assert 0 <= data["gov_contribution_usd"] < data["total_cost_usd"]
    assert data["participant_share_usd"] == data["total_cost_usd"] - data["gov_contribution_usd"]
    assert data["allocated_to_participants_usd"] >= 0


def assert_workforce_pipeline(data: dict) -> None:
    _assert_common_fields(data, "WorkforcePipeline")
    assert isinstance(data["cohort_code"], str) and data["cohort_code"]
    assert isinstance(data["required_operators"], int) and data["required_operators"] > 0
    assert data["graduates"] >= 0
    assert data["status"] in [s.value for s in PipelineStatus]


def assert_operator_license(data: dict) -> None:
    _assert_common_fields(data, "OperatorLicense")
    assert isinstance(data["pipeline_id"], str) and data["pipeline_id"]
    assert isinstance(data["candidate_name"], str) and data["candidate_name"]
    assert data["license_status"] in [s.value for s in LicenseStatus]
