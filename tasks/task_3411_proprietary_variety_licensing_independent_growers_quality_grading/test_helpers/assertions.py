"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

BERRY_TYPES = ["STRAWBERRY", "RASPBERRY", "BLACKBERRY", "BLUEBERRY"]
GRADES = ["PREMIUM", "STANDARD", "PROCESS", "JUICE", "REJECT"]


def _common(data):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _opt_ts(data, field):
    v = data.get(field)
    assert v is None or is_iso8601_timestamp(v), f"{field} must be ISO 8601 or null"


def _opt_int(data, field):
    v = data.get(field)
    assert v is None or (isinstance(v, int) and not isinstance(v, bool)), field


def _opt_num(data, field):
    v = data.get(field)
    assert v is None or isinstance(v, (int, float)) and not isinstance(v, bool), field


def _opt_str(data, field):
    v = data.get(field)
    assert v is None or isinstance(v, str), field


def assert_variety(data: dict):
    _common(data)
    assert isinstance(data["variety_code"], str) and data["variety_code"]
    assert data["berry_type"] in BERRY_TYPES
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["DEVELOPMENT", "RELEASED", "RECALLED"]
    _opt_ts(data, "released_at")
    _opt_ts(data, "recalled_at")


def assert_grower(data: dict):
    _common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "EXITED"]
    _opt_ts(data, "suspended_at")
    _opt_ts(data, "exited_at")


def assert_agreement(data: dict):
    _common(data)
    for f in ("grower_id", "variety_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be valid UUID"
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["max_planting_units"], int) and data["max_planting_units"] > 0
    assert isinstance(data["units_planted"], int) and data["units_planted"] >= 0
    assert data["units_planted"] <= data["max_planting_units"]
    assert isinstance(data["cultural_practice_codes"], list) and data["cultural_practice_codes"]
    assert data["exclusive_marketing"] is True
    _opt_ts(data, "effective_from")
    _opt_ts(data, "effective_to")
    assert data["status"] in ["PENDING_REVIEW", "ACTIVE", "REJECTED",
                              "SUSPENDED", "TERMINATED"]
    _opt_ts(data, "decided_at")
    _opt_str(data, "reject_reason")


def assert_plant_lot(data: dict):
    _common(data)
    assert isinstance(data["nursery_code"], str) and data["nursery_code"]
    for f in ("agreement_id", "variety_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be valid UUID"
    assert isinstance(data["quantity_plants"], int) and data["quantity_plants"] > 0
    _opt_ts(data, "shipped_at")
    assert isinstance(data["season_year"], int)
    for f in ("plants_reserved", "plants_planted", "plants_destroyed",
              "plants_available"):
        assert isinstance(data.get(f), int) and data[f] >= 0, f
    assert isinstance(data["royalty_provisional_cents"], int)
    _opt_int(data, "royalty_final_cents")
    _opt_int(data, "royalty_adjustment_cents")
    _opt_ts(data, "depleted_at")
    assert data["status"] in ["SHIPPED", "PLANTED", "DEPLETED", "RECALLED"]


def assert_planting(data: dict):
    _common(data)
    for f in ("agreement_id", "plant_lot_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be valid UUID"
    assert isinstance(data["planned_plants"], int) and data["planned_plants"] > 0
    _opt_int(data, "plants_planted_actual")
    _opt_ts(data, "planted_on")
    assert isinstance(data["region_code"], str) and data["region_code"]
    _opt_ts(data, "expected_first_harvest")
    _opt_num(data, "expected_yield_kg")
    v = data.get("harvest_window_id")
    assert v is None or is_valid_uuid(v), "harvest_window_id UUID or null"
    assert data["status"] in ["PLANNED", "PLANTED", "HARVESTING",
                              "COMPLETED", "CANCELLED", "RECALLED"]
    _opt_ts(data, "completed_at")
    _opt_ts(data, "recalled_at")
    _opt_int(data, "recall_compensation_cents")


def assert_harvest_window(data: dict):
    _common(data)
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert is_valid_uuid(data.get("variety_id", "")), "variety_id must be valid UUID"
    _opt_ts(data, "week_start")
    _opt_ts(data, "week_end")
    assert isinstance(data["target_volume_kg"], int) and data["target_volume_kg"] > 0
    assert isinstance(data["booked_volume_kg"], (int, float))
    assert data["booked_volume_kg"] >= 0


def assert_harvest_lot(data: dict):
    _common(data)
    assert is_valid_uuid(data.get("planting_id", "")), "planting_id must be valid UUID"
    _opt_ts(data, "harvested_at")
    assert isinstance(data["gross_weight_kg"], (int, float)) and data["gross_weight_kg"] > 0
    assert isinstance(data["tare_weight_kg"], (int, float)) and data["tare_weight_kg"] >= 0
    assert isinstance(data["net_kg"], (int, float))
    _opt_ts(data, "received_at")
    _opt_num(data, "pulp_temp_c_at_receipt")
    _opt_str(data, "received_by_user_id")
    _opt_num(data, "precool_hours")
    v = data.get("cold_chain_compliant")
    assert v is None or isinstance(v, bool)
    assert data["lot_status"] in ["IN_TRANSIT", "RECEIVED", "GRADED",
                                  "SETTLED", "REJECTED"]
    assert data["grade_status"] in ["UNGRADED", "SUBMITTED", "CERTIFIED", "DISPUTED"]
    _opt_num(data, "flavor_brix")
    _opt_int(data, "firmness_g")
    _opt_int(data, "appearance_score")
    _opt_num(data, "defect_pct")
    v = data.get("grade")
    assert v is None or v in GRADES
    v = data.get("pack_designation")
    assert v is None or v in GRADES
    _opt_str(data, "submitted_by_user_id")
    _opt_str(data, "certified_by_user_id")
    _opt_ts(data, "grade_submitted_at")
    _opt_str(data, "grade_dispute_reason")
    assert isinstance(data.get("grade_version"), int) and data["grade_version"] >= 0
    v = data.get("pool_period_id")
    assert v is None or is_valid_uuid(v), "pool_period_id UUID or null"
    _opt_int(data, "lot_gross_provisional_cents")
    _opt_int(data, "lot_gross_final_cents")


def assert_pool_period(data: dict):
    _common(data)
    assert data["berry_type"] in BERRY_TYPES
    _opt_ts(data, "week_start")
    _opt_ts(data, "week_end")
    assert isinstance(data["is_shoulder_week"], bool)
    assert data["status"] in ["OPEN", "CLOSED", "SETTLED", "PAID"]
    _opt_int(data, "estimated_price_cents_per_kg")
    _opt_int(data, "actual_price_cents_per_kg")
    _opt_num(data, "total_net_kg")
    _opt_num(data, "total_weighted_kg")
    for f in ("gross_pool_revenue_cents", "marketing_fee_cents",
              "net_pool_revenue_cents", "pool_distributable_cents"):
        _opt_int(data, f)
    _opt_num(data, "provisional_pool_rate")
    _opt_num(data, "final_pool_rate")
    _opt_ts(data, "closed_at")
    _opt_ts(data, "settled_at")


def assert_settlement_statement(data: dict):
    _common(data)
    for f in ("pool_period_id", "grower_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be valid UUID"
    assert data["status"] in ["PROVISIONAL", "ISSUED", "DISPUTED", "FINAL", "PAID"]
    for f in ("provisional_net_cents", "gross_cents", "royalty_offset_cents",
              "cold_chain_deduction_cents", "recall_credit_cents", "net_cents"):
        _opt_int(data, f)
    _opt_ts(data, "issued_at")
    _opt_ts(data, "dispute_deadline")
    _opt_str(data, "dispute_reason")
    assert isinstance(data.get("dispute_count"), int) and data["dispute_count"] >= 0
    v = data.get("resolution")
    assert v is None or v in ["UPHOLD", "ADJUST"]
    assert isinstance(data.get("adjustment_total_cents"), int)
    _opt_ts(data, "paid_at")


def assert_recall_order(data: dict):
    _common(data)
    assert is_valid_uuid(data.get("variety_id", "")), "variety_id must be valid UUID"
    assert isinstance(data["reason"], str) and data["reason"]
    _opt_ts(data, "destroy_before")
    assert isinstance(data["compensation_per_plant_cents"], int)
    assert data["compensation_per_plant_cents"] >= 0
    assert data["status"] in ["ISSUED", "COMPLETE"]
    assert isinstance(data.get("plantings_recalled_count"), int)
    assert isinstance(data.get("total_compensation_cents"), int)
    _opt_ts(data, "enforced_at")


def assert_plant_lot_conservation(lot: dict):
    """Plant counters conserve quantity_plants at every step (PRD §3.4)."""
    total = (lot["plants_reserved"] + lot["plants_planted"]
             + lot["plants_destroyed"] + lot["plants_available"])
    assert total == lot["quantity_plants"], (
        f"lot counters sum {total} != quantity_plants {lot['quantity_plants']}")


def assert_pool_zero_sum(pool: dict, included_lots: list):
    """Sum of final lot grosses equals pool_distributable_cents exactly."""
    total = sum(l["lot_gross_final_cents"] for l in included_lots)
    assert total == pool["pool_distributable_cents"], (
        f"lot grosses sum {total} != distributable {pool['pool_distributable_cents']}")
