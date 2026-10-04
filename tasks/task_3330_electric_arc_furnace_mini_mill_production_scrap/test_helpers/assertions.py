"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_lean_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_mill(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["division"] in ("CONSTRUCTION", "AUTOMOTIVE", "ENERGY")
    assert data["furnace_capacity_tons"] > 0
    assert data["caster_rate_tph"] > 0
    assert data["posture"] in ("NORMAL", "INTERRUPTED")


def assert_surcharge_index(data: dict):
    _assert_lean_fields(data)
    assert data["grade_category"] in ("SHREDDED", "BUSHLING", "HMS", "DRI", "PIG_IRON")
    assert isinstance(data["effective_month"], str) and len(data["effective_month"]) == 7
    assert isinstance(data["price_per_ton_cents"], int) and data["price_per_ton_cents"] >= 0
    assert data["status"] in ("PUBLISHED", "SUPERSEDED")


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert data["grade_category"] in ("SHREDDED", "BUSHLING", "HMS", "DRI", "PIG_IRON")
    assert data["contract_type"] in ("FIXED", "INDEXED")
    assert data["committed_tons"] > 0
    assert data["status"] in ("OPEN", "CLOSED", "DEFAULTED")


def assert_scrap_lot(data: dict):
    _assert_lean_fields(data)
    assert isinstance(data["received_on"], str) and len(data["received_on"]) == 10
    assert data["tons_received"] > 0
    assert 0.0 <= data["moisture_pct"] <= 0.30
    assert 0.0 <= data["cu_pct"] <= 0.005
    assert 0.0 <= data["mn_pct"] <= 0.02
    assert data["status"] in ("RECEIVED", "PARTIALLY_CONSUMED", "CONSUMED")


def assert_grade(data: dict):
    _assert_lean_fields(data)
    assert isinstance(data["grade_code"], str) and data["grade_code"]
    assert data["product_form"] in ("BILLET", "BLOOM", "SLAB")
    assert data["grade_group"] in ("GROUP_A", "GROUP_B")
    assert data["certification_class"] in ("STANDARD", "CERTIFIED")
    assert data["cu_max_pct"] > 0
    assert data["mn_min_pct"] >= 0
    assert data["mn_max_pct"] >= data["mn_min_pct"]


def assert_heat(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["heat_number"], str) and data["heat_number"]
    assert data["target_tap_weight_tons"] > 0
    assert is_iso8601_timestamp(data["planned_tap_at"])
    assert data["status"] in ("PLANNED", "CHARGED", "MELTDOWN_LOCKED", "TAPPED", "CAST", "ABORTED")


def assert_charge_line(data: dict):
    _assert_lean_fields(data)
    assert is_valid_uuid(data["scrap_lot_id"])
    assert data["tons"] > 0
    assert isinstance(data["line_cost_cents"], int)


def assert_meltdown_sheet(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert 0.0 <= data["cu_pct"] <= 0.02
    assert 0.0 <= data["mn_pct"] <= 0.05
    assert isinstance(data["chem_ok"], bool)
    assert data["status"] in ("RECORDED", "REVISED", "CONFIRMED", "REJECTED")


def assert_campaign(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["product_family"] in ("REBAR", "BEAM", "PLATE", "WIRE_ROD")
    assert data["grade_group"] in ("GROUP_A", "GROUP_B")
    assert is_iso8601_timestamp(data["planned_start"])
    assert is_iso8601_timestamp(data["planned_end"])
    assert data["roll_change_budget"] >= 0
    assert data["status"] in ("OPEN", "COMMITTED", "CLOSED", "CANCELLED")


def assert_campaign_line(data: dict):
    _assert_lean_fields(data)
    assert is_valid_uuid(data["heat_id"])


def assert_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["market"] in ("CONSTRUCTION", "AUTOMOTIVE", "ENERGY")
    assert data["pricing_mode"] in ("CONTRACT", "SPOT")
    assert data["credit_status"] in ("GOOD", "WATCH", "BLOCKED")
    assert data["allocation_priority"] in ("STANDARD", "STRATEGIC")


def assert_order(data: dict):
    _assert_common_fields(data)
    assert data["product_family"] in ("REBAR", "BEAM", "PLATE", "WIRE_ROD")
    assert data["tons"] > 0
    assert isinstance(data["fulfillment_month"], str) and len(data["fulfillment_month"]) == 7
    assert data["base_price_cents_per_ton"] > 0
    assert data["status"] in ("QUOTED", "CONFIRMED", "ALLOCATED", "INVOICED", "CANCELLED")


def assert_mtr(data: dict):
    _assert_lean_fields(data)
    assert isinstance(data["report_no"], str) and data["report_no"].startswith("MTR-")
    assert isinstance(data["chemistry_snapshot"], dict)
    assert isinstance(data["energy_certified"], bool)


def assert_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and data["label"]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["curtailment_credit_cents"] >= 0
    assert data["status"] in ("SCHEDULED", "HONORED", "LAPSED")


def assert_energy_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["grid_operator"], str) and data["grid_operator"]
    assert is_iso8601_timestamp(data["called_at"])
    assert is_iso8601_timestamp(data["released_at"])
    assert data["status"] in ("DECLARED", "ACTIVE", "RELEASED", "EXPIRED")


def assert_waiver(data: dict):
    _assert_lean_fields(data)
    assert data["scope"] in ("HEAT", "EVENT")
    assert is_valid_uuid(data["scope_id"])
    assert isinstance(data["granted_by"], str) and data["granted_by"]
    assert isinstance(data["reason"], str)


def assert_energy_interval(data: dict):
    _assert_lean_fields(data)
    assert is_iso8601_timestamp(data["interval_start"])
    assert is_iso8601_timestamp(data["interval_end"])
    assert data["kwh"] > 0
    assert data["posture_at_interval"] in ("NORMAL", "INTERRUPTED")


def assert_scorecard(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert data["headcount"] > 0
    for field in ("revenue_cents", "material_cost_cents", "energy_cost_cents",
                  "curtailment_credits_cents"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["status"] in ("OPEN", "CLOSED", "DISTRIBUTED")


def assert_scorecard_profit_invariants(data: dict):
    """Domain invariants on a CLOSED (or later) scorecard (PRD §3.11)."""
    assert data["profit_cents"] == (
        data["revenue_cents"] - data["material_cost_cents"] - data["energy_cost_cents"]
    )
    assert data["profit_pool_cents"] >= 0
    if data["profit_pool_cents"] == 0:
        assert data["distribution_per_employee_cents"] == 0
        assert data["remainder_cents"] == 0
    else:
        per = data["distribution_per_employee_cents"]
        assert per == data["profit_pool_cents"] // data["headcount"]
        assert data["remainder_cents"] == data["profit_pool_cents"] - per * data["headcount"]
