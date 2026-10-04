"""Entity assertions and domain invariant checkers (PRD §2.5, §3).

Field presence follows the PRD: primary resources carry id, created_at,
updated_at, version; PriceObservation and InterruptEvent are append-only
and carry only id and created_at (both updated_at and version absent).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_smelter(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["region_code"] in ("NA_NORTHWEST", "NA_MIDWEST", "EU_NORDIC", "AU_EAST")
    assert data["rated_capacity_tpd"] > 0
    assert data["labor_headcount"] >= 0
    assert data["operating_posture"] in (
        "FULL_OPERATION", "PARTIAL_CURTAILMENT", "FULL_CURTAILMENT", "SHUTDOWN",
    )
    assert "open_hedged_tonnes" in data
    assert "curtailed_capacity_tpd" in data
    assert "hedge_coverage_ratio" in data


def assert_potline(data: dict):
    _assert_common(data)
    assert isinstance(data["smelter_id"], str)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["capacity_tpd"] > 0
    assert data["amperage_ka"] > 0
    assert data["operating_status"] in (
        "OPERATING", "CURTAILED", "IDLE", "RESTARTING", "SHUTDOWN",
    )
    assert "curtailment_depth_pct" in data
    assert "curtailed_since" in data
    assert "last_full_shutdown_at" in data
    assert "active_decision_id" in data
    assert data["restart_cost_class"] in ("HOT", "WARM", "COLD")


def assert_power_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["smelter_id"], str)
    assert isinstance(data["supplier_name"], str)
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data["components"], list) and len(data["components"]) >= 1
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED")
    assert "interruptible_hours_used" in data
    assert "forward_cost_per_mwh" in data
    assert "settled_cost_per_mwh" in data
    assert "month_to_date_settlement_usd" in data
    assert "take_or_pay_exposed" in data


def assert_price_observation(data: dict):
    """Append-only record: id + created_at only; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"
    assert data["instrument"] in (
        "POWER_SPOT", "ALUMINUM_LME", "REGIONAL_PREMIUM", "ALUMINA_INDEX",
    )
    assert data["price_usd"] > 0


def assert_interrupt_event(data: dict):
    """Append-only record: id + created_at only; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"
    assert data["mw_reduced"] > 0
    assert data["hours"] > 0


def assert_hedge_position(data: dict):
    _assert_common(data)
    assert isinstance(data["smelter_id"], str)
    assert data["instrument"] in ("LME_SWAP", "PREMIUM_SWAP")
    assert data["volume_tonnes"] > 0
    assert data["strike_price_usd"] > 0
    assert isinstance(data["delivery_month"], str) and len(data["delivery_month"]) == 7
    assert data["status"] in ("OPEN", "CLOSED", "EXPIRED")
    assert "closed_price_usd" in data
    assert "realized_pnl_usd" in data


def assert_alumina_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["smelter_id"], str)
    assert isinstance(data["refinery_name"], str)
    assert data["pricing_model"] in ("COST_PLUS", "MARKET_LINKED")
    assert data["monthly_volume_tonnes"] > 0
    assert "current_transfer_price" in data


def assert_curtailment_decision(data: dict):
    _assert_common(data)
    assert isinstance(data["potline_id"], str)
    assert data["trigger_type"] in (
        "POWER_PRICE", "METAL_PRICE", "GRID_EMERGENCY", "MAINTENANCE",
    )
    assert 0 < data["depth_pct"] <= 100
    assert data["status"] in (
        "ECONOMIC_REVIEW", "LABOR_REVIEW", "APPROVED", "REJECTED",
        "EXECUTED", "REVERSED", "SUPERSEDED",
    )
    assert isinstance(data["proposed_by_user_id"], str)
    assert "economic_reviewed_by_user_id" in data
    assert "approved_by_user_id" in data
    assert "approved_at" in data
    assert "executed_at" in data
    assert isinstance(data["economics_snapshot"], dict)


def assert_restart_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["potline_id"], str)
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED")
    assert data["restart_cost_class"] in ("HOT", "WARM", "COLD")
    assert "estimated_cost_usd" in data
    assert "actual_cost_usd" in data


def assert_environmental_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["smelter_id"], str)
    assert data["permit_type"] in ("EMISSIONS", "SPL_DISPOSAL")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_to", ""))


def assert_labor_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["smelter_id"], str)
    assert isinstance(data["union_name"], str)
    assert data["notice_period_days"] >= 0
    assert data["severance_weeks_per_year"] >= 0
    assert data["status"] in ("ACTIVE", "EXPIRED")


def assert_production_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["smelter_id"], str)
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    forms = [a["product_form"] for a in data["allocations"]]
    assert sorted(forms) == ["BILLET", "SLAB", "VALUE_ADDED"]
    assert data["status"] in ("PUBLISHED", "SUPERSEDED")
    assert "total_tonnes" in data
    assert "total_margin_usd" in data
