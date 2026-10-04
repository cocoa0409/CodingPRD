"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS
from .types import (
    BatchStatus,
    CodePath,
    DeploymentStatus,
    InspectionDisposition,
    InspectionOutcome,
    InterruptionCause,
    InterruptionStatus,
    LearningCurveVariant,
    MixCode,
    PermitStatus,
    PlanRevisionStatus,
    PlanStatus,
    PrinterSetupStatus,
    PrintJobStatus,
    SitePosture,
    SiteStatus,
    TradeKind,
    TradeTaskStatus,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_jurisdiction(data: dict):
    _assert_common_fields(data, "Jurisdiction")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["permits_prescriptive_printed_path"], bool)
    assert isinstance(data["alternative_means_review_days"], int)
    assert data["alternative_means_review_days"] >= 1
    assert isinstance(data["weather_station_id"], str)
    assert data["status"] == "ACTIVE"


def assert_site(data: dict):
    _assert_common_fields(data, "Site")
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert isinstance(data["address"], str)
    assert data.get("community_deployment_id") is None or isinstance(
        data["community_deployment_id"], str
    )
    assert data["soil_class"] in ["A", "B", "C", "D"]
    assert data["foundation_kind"] in ["SLAB", "PIER_AND_BEAM", "FOOTING"]
    assert data["status"] in [s.value for s in SiteStatus]
    assert data["posture"] in [p.value for p in SitePosture]


def assert_community_deployment(data: dict):
    _assert_common_fields(data, "CommunityDeployment")
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert data["status"] in [s.value for s in DeploymentStatus]
    assert isinstance(data["planned_unit_count"], int) and data["planned_unit_count"] >= 2
    assert isinstance(data["completed_unit_count"], int)
    assert data.get("learning_curve_baseline_minutes") is None or isinstance(
        data["learning_curve_baseline_minutes"], int
    )
    assert data.get("learning_curve_factor") is None or isinstance(
        data["learning_curve_factor"], (int, float)
    )
    assert data["learning_curve_variant"] in [v.value for v in LearningCurveVariant]


def assert_structural_plan(data: dict):
    _assert_common_fields(data, "StructuralPlan")
    assert isinstance(data["title"], str) and data["title"]
    assert data["structural_system"] in [
        "PRINTED_WALL",
        "PRINTED_WALL_WITH_CONVENTIONAL_ROOF",
        "HYBRID",
    ]
    assert isinstance(data["wall_thickness_mm"], int) and data["wall_thickness_mm"] >= 50
    assert isinstance(data["wall_height_mm"], int) and data["wall_height_mm"] >= 2000
    assert data["plan_area_m2"] > 0
    assert data["status"] in [s.value for s in PlanStatus]


def assert_plan_revision(data: dict):
    _assert_common_fields(data, "PlanRevision")
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["engineering_notes"], str)
    assert data["required_code_path"] in [p.value for p in CodePath]
    assert data["status"] in [s.value for s in PlanRevisionStatus]


def assert_permit_application(data: dict):
    _assert_common_fields(data, "PermitApplication")
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_valid_uuid(data.get("plan_revision_id", ""))
    assert data["requested_path"] in [p.value for p in CodePath]
    assert data.get("granted_path") is None or data["granted_path"] in [
        p.value for p in CodePath
    ]
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert isinstance(data["fee_due_cents"], int) and data["fee_due_cents"] >= 0
    assert isinstance(data["fee_paid_cents"], int) and data["fee_paid_cents"] >= 0
    assert data["status"] in [s.value for s in PermitStatus]


def assert_printer_setup(data: dict):
    _assert_common_fields(data, "PrinterSetup")
    assert is_valid_uuid(data.get("site_id", ""))
    assert data["gantry_model"] in ["VULCAN_II", "VULCAN_III", "PHOENIX"]
    assert isinstance(data["rail_span_mm"], int) and data["rail_span_mm"] >= 5000
    assert data["leveling_tolerance_mm"] > 0
    assert isinstance(data["measured_level_deviation_mm"], (int, float))
    assert isinstance(data["is_within_tolerance"], bool)
    assert data["status"] in [s.value for s in PrinterSetupStatus]


def assert_material_batch(data: dict):
    _assert_common_fields(data, "MaterialBatch")
    assert is_valid_uuid(data.get("site_id", ""))
    assert data["mix_code"] in [m.value for m in MixCode]
    wc = data["water_cement_ratio"]
    assert THRESHOLDS["WC_RATIO_MIN"] <= wc <= THRESHOLDS["WC_RATIO_MAX"]
    assert isinstance(data["target_slump_mm"], int) and data["target_slump_mm"] >= 50
    assert isinstance(data["measured_slump_mm"], int)
    assert isinstance(data["slump_within_band"], bool)
    assert isinstance(data["is_pumpable"], bool)
    window = data.get("pump_window_kg_per_min")
    assert isinstance(window, list) and len(window) == 2
    assert data["status"] in [s.value for s in BatchStatus]


def assert_weather_observation(data: dict):
    _assert_common_fields(data, "WeatherObservation")
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_iso8601_timestamp(data.get("observed_at", ""))
    assert isinstance(data["air_temp_c"], (int, float))
    assert 0 <= data["relative_humidity_pct"] <= 100
    assert isinstance(data["wind_speed_mps"], (int, float))
    assert data["precipitation_mm"] >= 0
    assert isinstance(data["is_print_permissible"], bool)


def assert_print_job(data: dict):
    _assert_common_fields(data, "PrintJob")
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_valid_uuid(data.get("plan_revision_id", ""))
    assert is_valid_uuid(data.get("printer_setup_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start_at", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end_at", ""))
    assert isinstance(data["total_layers_planned"], int) and data["total_layers_planned"] >= 1
    assert isinstance(data["layers_printed"], int) and data["layers_printed"] >= 0
    assert isinstance(data["cumulative_interruption_minutes"], int)
    assert data["cumulative_interruption_minutes"] >= 0
    assert data.get("continuous_run_minutes") is None or isinstance(
        data["continuous_run_minutes"], int
    )
    assert data["status"] in [s.value for s in PrintJobStatus]


def assert_layer_inspection(data: dict):
    _assert_common_fields(data, "LayerInspection")
    assert is_valid_uuid(data.get("print_job_id", ""))
    assert isinstance(data["layer_index_start"], int) and data["layer_index_start"] >= 1
    assert isinstance(data["layer_index_end"], int)
    assert data["layer_index_end"] >= data["layer_index_start"]
    assert isinstance(data["bond_strength_mpa"], (int, float))
    assert isinstance(data["dimensional_deviation_mm"], (int, float))
    assert isinstance(data["passes_bond"], bool)
    assert isinstance(data["passes_dimensional"], bool)
    assert data["outcome"] in [o.value for o in InspectionOutcome]
    assert data["disposition"] in [d.value for d in InspectionDisposition]


def assert_trade_task(data: dict):
    _assert_common_fields(data, "ConventionalTradeTask")
    assert is_valid_uuid(data.get("site_id", ""))
    assert data["trade"] in [t.value for t in TradeKind]
    assert isinstance(data["sequence_rank"], int) and data["sequence_rank"] >= 1
    assert is_iso8601_timestamp(data.get("earliest_start_at", ""))
    assert is_iso8601_timestamp(data.get("latest_end_at", ""))
    assert is_valid_uuid(data.get("depends_on_print_job_id", ""))
    assert isinstance(data["is_startable"], bool)
    assert isinstance(data.get("start_blockers"), list)
    assert data["status"] in [s.value for s in TradeTaskStatus]


def assert_layer_inspection_outcome_invariants(data: dict):
    """The four-valued outcome must be consistent with the pass flags (PRD §3.8)."""
    pb, pd = data["passes_bond"], data["passes_dimensional"]
    expected = (
        "PASS"
        if pb and pd
        else "FAIL_BOND"
        if (not pb and pd)
        else "FAIL_DIMENSIONAL"
        if (pb and not pd)
        else "FAIL_BOTH"
    )
    assert data["outcome"] == expected, (
        f"outcome {data['outcome']} inconsistent with passes_bond={pb}, "
        f"passes_dimensional={pd}; expected {expected}"
    )


def assert_batch_pumpability_invariants(data: dict):
    """is_pumpable must agree with the slump band and pump window (PRD §3.5)."""
    within_window = (
        data["pump_window_kg_per_min"][0]
        <= data["pump_consistency_kg_per_min"]
        <= data["pump_window_kg_per_min"][1]
    )
    expected = data["slump_within_band"] and within_window
    assert data["is_pumpable"] == expected, (
        f"is_pumpable {data['is_pumpable']} inconsistent with slump band "
        f"{data['slump_within_band']} and window membership {within_window}"
    )
