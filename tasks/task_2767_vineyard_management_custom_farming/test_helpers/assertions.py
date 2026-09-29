"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant

MONEY = dict(abs=0.01)
WATER = dict(abs=0.0005)


def assert_money(actual, expected, label=""):
    """Two-decimal comparison for currency, tonnage and acreage (PRD §2.7)."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"Expected {label or 'amount'} {expected}, got {actual}"
    )


def assert_water(actual, expected, label=""):
    """Three-decimal comparison for acre-inch figures (PRD §2.7)."""
    assert actual == pytest.approx(expected, abs=0.0005), (
        f"Expected {label or 'water depth'} {expected}, got {actual}"
    )


def assert_instant(actual, expected, label=""):
    """Compare two ISO 8601 UTC instants irrespective of sub-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label or 'instant'} {expected}, got {actual}"
    )


def assert_common_fields(data: dict):
    """id / created_at / updated_at / version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer of at least 1, got {data.get('version')!r}"
    )


def assert_event_record_fields(data: dict):
    """PRD §2.4: an immutable event record carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "an event record must not carry updated_at"
    assert "version" not in data, "an event record must not carry version"


# ─── Per-entity assertions ────────────────────────────

def assert_vineyard(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["owner_legal_name"], str) and 1 <= len(data["owner_legal_name"]) <= 160
    assert isinstance(data["ava_region"], str) and 1 <= len(data["ava_region"]) <= 80
    assert data["client_contact_email"].count("@") == 1
    assert isinstance(data["block_count"], int) and data["block_count"] >= 0
    assert data["managed_acres"] >= 0
    assert_cost_precision(data["managed_acres"])


def assert_block(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["vineyard_id"])
    assert isinstance(data["block_code"], str) and 1 <= len(data["block_code"]) <= 24
    assert data["variety"] in (
        "CABERNET_SAUVIGNON", "CHARDONNAY", "PINOT_NOIR", "ZINFANDEL", "SYRAH")
    assert data["rootstock"] in (
        "ROOTSTOCK_1103P", "ROOTSTOCK_110R", "ROOTSTOCK_SO4", "RIPARIA_GLOIRE", "ST_GEORGE")
    assert data["trellis_system"] in (
        "VSP", "SPRAWL", "QUADRILATERAL_CORDON", "HEAD_TRAINED", "GDC")
    assert data["farming_status"] in ("ESTABLISHING", "BEARING", "REMOVED")
    assert data["compliance_posture"] in ("CLEAR", "REENTRY_RESTRICTED", "PHI_RESTRICTED")
    assert data["harvest_posture"] in ("NOT_ESTIMATED", "OPEN", "COMPLETE")
    assert isinstance(data["vines_per_acre"], int), "vines_per_acre must be an integer"
    assert isinstance(data["vine_count"], int), "vine_count must be an integer"
    assert 1900 <= data["planting_year"] <= 2100
    for key in ("vine_spacing_ft", "row_spacing_ft", "acres"):
        assert data[key] > 0, f"{key} must be strictly greater than zero"


def assert_contract(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["vineyard_id"])
    assert data["contract_status"] in ("DRAFT", "ACTIVE", "CLOSED")
    assert data["per_acre_annual_fee"] >= 0
    assert 0 <= data["cost_pass_through_pct"] <= 1
    assert data["quality_incentive_per_ton"] >= 0
    assert data["quality_brix_threshold"] > 0
    assert data["period_overhead_pool"] >= 0
    assert data["period_start"] <= data["period_end"]
    assert isinstance(data["enrolled_block_count"], int)
    assert isinstance(data["settled_period_count"], int)
    for key in ("total_contracted_acres", "accrued_quality_incentive",
                "projected_total_billable"):
        assert_cost_precision(data[key])


def assert_farming_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["block_id"])
    assert 2000 <= data["plan_year"] <= 2100
    assert data["plan_status"] in ("DRAFT", "SUBMITTED", "APPROVED")
    assert data["quality_target"] in ("PREMIUM", "STANDARD", "BULK")
    assert data["budget_posture"] in ("WITHIN_BUDGET", "AT_RISK", "EXHAUSTED")
    assert isinstance(data["revision_count"], int) and 0 <= data["revision_count"] <= 2
    for key in ("total_budget", "committed_cost", "remaining_budget"):
        assert_cost_precision(data[key])


def assert_crew(data: dict):
    assert_common_fields(data)
    assert isinstance(data["crew_name"], str) and 1 <= len(data["crew_name"]) <= 80
    assert data["pay_structure"] in ("PIECE_RATE", "HOURLY")
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert data["base_hourly_rate"] >= 0
    assert data["piece_rate_per_vine"] >= 0
    assert data["vines_per_hour_standard"] > 0
    assert isinstance(data["task_capabilities"], list) and data["task_capabilities"]
    assert len(set(data["task_capabilities"])) == len(data["task_capabilities"])
    for task in data["task_capabilities"]:
        assert task in ("PRUNING", "SUCKERING", "LEAFING", "HARVEST")
    assert isinstance(data["pest_certified"], bool)
    assert data["crew_status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["scheduled_work_order_count"], int)


def assert_work_order(data: dict):
    assert_common_fields(data)
    for key in ("block_id", "farming_plan_id", "crew_id"):
        assert is_valid_uuid(data[key])
    assert data["task_type"] in ("PRUNING", "SUCKERING", "LEAFING", "HARVEST")
    assert data["execution_status"] in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["payroll_status"] in ("NOT_PAYABLE", "PENDING", "APPROVED", "PAID")
    assert data["scheduled_start"] < data["scheduled_end"]
    assert data["planned_vines"] >= 0
    assert data["planned_hours"] > 0
    assert_cost_precision(data["estimated_labor_cost"])
    if data.get("actual_labor_cost") is not None:
        assert_cost_precision(data["actual_labor_cost"])
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in (
            "WEATHER", "CLIENT_REQUEST", "CREW_UNAVAILABLE", "REENTRY_RESTRICTION")


def assert_irrigation_event(data: dict):
    assert_common_fields(data)
    for key in ("block_id", "farming_plan_id"):
        assert is_valid_uuid(data[key])
    assert data["irrigation_status"] in ("SCHEDULED", "APPLIED")
    assert data["scheduled_start"] < data["scheduled_end"]
    assert 0 <= data["soil_moisture_pct"] <= 100
    assert 0 <= data["field_capacity_pct"] <= 100
    assert data["crop_coefficient"] > 0
    assert data["root_zone_depth_in"] > 0
    for key in ("deficit_factor", "et_demand_inches", "target_inches",
                "soil_shortfall_inches", "refill_inches",
                "gross_requirement_inches", "seasonal_allowance_inches",
                "recommended_inches"):
        assert data[key] >= 0, f"{key} must never be negative"
    assert data["recommended_inches"] <= 1.500 + 1e-9, (
        "recommended_inches must never exceed the 1.500-inch per-set ceiling"
    )


def assert_spray_record(data: dict):
    assert_common_fields(data)
    for key in ("block_id", "farming_plan_id", "pest_observation_id"):
        assert is_valid_uuid(data[key])
    assert data["spray_status"] in ("RECOMMENDED", "APPLIED", "VERIFIED")
    assert isinstance(data["product_name"], str) and 1 <= len(data["product_name"]) <= 120
    assert isinstance(data["active_ingredient"], str)
    assert isinstance(data["rei_hours"], int) and data["rei_hours"] >= 0
    assert isinstance(data["phi_days"], int) and data["phi_days"] >= 0
    assert data["rate_per_acre"] > 0
    assert_cost_precision(data["material_cost"])
    assert isinstance(data["recommended_by_user_id"], str)


def assert_pest_observation(data: dict):
    assert_event_record_fields(data)
    assert is_valid_uuid(data["block_id"])
    assert data["pest_code"] in (
        "POWDERY_MILDEW", "VINE_MEALYBUG", "BOTRYTIS", "LEAFHOPPER")
    assert 0 <= data["incidence_pct"] <= 100
    assert isinstance(data["severity_index"], int) and 0 <= data["severity_index"] <= 5
    assert is_iso8601_timestamp(data["observed_at"])
    assert isinstance(data["scout_user_id"], str)
    assert isinstance(data["exceeds_threshold"], bool)
    assert data["exceeds_threshold"] == (
        data["incidence_pct"] >= data["action_threshold_pct"]
    ), "exceeds_threshold must be true exactly when incidence reaches the threshold"


def assert_yield_estimate(data: dict):
    assert_event_record_fields(data)
    assert is_valid_uuid(data["block_id"])
    assert data["method"] in ("CLUSTER_COUNT", "BERRY_SAMPLE")
    assert isinstance(data["vine_count_at_estimate"], int)
    assert data["avg_clusters_per_vine"] >= 0
    assert_cost_precision(data["estimated_tons"])
    assert_cost_precision(data["estimated_tons_per_acre"])
    if data["method"] == "CLUSTER_COUNT":
        assert data["avg_cluster_weight_lb"] is not None
    else:
        for key in ("berries_per_cluster", "avg_berry_weight_g", "days_to_harvest"):
            assert data[key] is not None


def assert_delivery_window(data: dict):
    assert_common_fields(data)
    assert isinstance(data["winery_name"], str) and 1 <= len(data["winery_name"]) <= 120
    assert data["window_start"] < data["window_end"]
    assert data["capacity_tons"] > 0
    assert data["window_posture"] in ("OPEN", "NEARLY_FULL", "FULL")
    for key in ("committed_tons", "remaining_tons", "capacity_tons"):
        assert_cost_precision(data[key])
    assert_window_tonnage_invariant(data)


def assert_harvest_load(data: dict):
    assert_common_fields(data)
    for key in ("block_id", "crew_id", "delivery_window_id"):
        assert is_valid_uuid(data[key])
    assert data["load_status"] in ("PLANNED", "IN_TRANSIT", "RECEIVED", "REJECTED")
    assert data["estimated_tons"] > 0
    assert_cost_precision(data["estimated_tons"])
    if data.get("net_tons") is not None:
        assert_cost_precision(data["net_tons"])
    if data.get("quality_incentive_amount") is not None:
        assert_cost_precision(data["quality_incentive_amount"])
    if data.get("rejection_reason") is not None:
        assert data["rejection_reason"] in (
            "MOG_EXCESS", "LOW_BRIX", "ROT_DAMAGE", "LATE_ARRIVAL")


def assert_settlement_statement(data: dict):
    assert is_valid_uuid(data["contract_id"])
    assert data["settlement_mode"] in ("PROVISIONAL", "FINAL")
    assert data["contract_status"] in ("DRAFT", "ACTIVE", "CLOSED")
    for key in ("direct_cost_total", "management_fee_base", "pass_through",
                "tier_basis", "volume_discount", "quality_incentive",
                "total_billable"):
        assert_cost_precision(data[key])
    assert data["volume_discount_pct"] in (0.00, 0.03, 0.05), (
        f"volume_discount_pct must be one of 0.00 / 0.03 / 0.05, got "
        f"{data['volume_discount_pct']}"
    )


# ─── Domain invariant checkers ────────────────────────

def assert_plan_ledger(plan: dict, committed_cost: float, remaining_budget: float,
                       budget_posture: str = None):
    """PRD §3.3: remaining_budget is total_budget less committed_cost."""
    assert_money(plan["committed_cost"], committed_cost, "committed_cost")
    assert_money(plan["remaining_budget"], remaining_budget, "remaining_budget")
    if budget_posture is not None:
        assert plan["budget_posture"] == budget_posture, (
            f"Expected budget_posture {budget_posture}, got {plan['budget_posture']}"
        )
    assert_money(
        plan["committed_cost"] + plan["remaining_budget"], plan["total_budget"],
        "committed_cost + remaining_budget",
    )


def assert_window_tonnage_invariant(window: dict):
    """PRD §3.8: committed_tons plus remaining_tons equals capacity_tons."""
    assert_money(
        window["committed_tons"] + window["remaining_tons"], window["capacity_tons"],
        "committed_tons + remaining_tons",
    )


def assert_block_harvest_ledger(block: dict, governing: float, committed: float,
                                received: float, remaining: float,
                                harvest_posture: str = None):
    """PRD §3.7: the block's three-line harvest ledger and its posture."""
    assert_money(block["governing_estimate_tons"], governing, "governing_estimate_tons")
    assert_money(block["committed_harvest_tons"], committed, "committed_harvest_tons")
    assert_money(block["received_tons"], received, "received_tons")
    assert_money(block["remaining_estimated_tons"], remaining, "remaining_estimated_tons")
    if harvest_posture is not None:
        assert block["harvest_posture"] == harvest_posture, (
            f"Expected harvest_posture {harvest_posture}, got {block['harvest_posture']}"
        )


def assert_version(data: dict, expected: int, label="resource"):
    assert data["version"] == expected, (
        f"Expected {label} version {expected}, got {data['version']}"
    )
