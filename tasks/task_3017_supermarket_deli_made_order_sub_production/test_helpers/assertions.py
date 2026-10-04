"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Every entity declares the common field set: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_store(data: dict):
    assert_common_fields(data)
    assert isinstance(data["store_number"], str) and len(data["store_number"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["deli_case_capacity_lbs"] > 0
    assert data["hot_bar_capacity_lbs"] > 0
    assert data["sub_station_count"] >= 1
    assert data["posture"] in ["OPEN", "RESTRICTED", "HALT"]
    assert data["posture_reason"] in [
        "OK",
        "INVENTORY_TRIGGERED",
        "REVOCATION_TRIGGERED",
        "NO_ACTIVE_PRICE_FILE",
        "CERTIFICATION_TRIGGERED",
        "POSTURE_GATE_TRIGGERED",
    ]
    assert isinstance(data["case_on_hand_lbs"], (int, float))
    assert isinstance(data["ops_run_index"], int)


def assert_deli_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in [
        "HOT_BAR",
        "COLD_CUT",
        "ROTISSERIE",
        "SUB",
        "BREAD",
        "CATERING_PLATTER",
    ]
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["retail_price_per_lb_cents"], int) and data["retail_price_per_lb_cents"] >= 0
    assert isinstance(data["case_life_minutes"], int) and data["case_life_minutes"] > 0
    assert 0 <= data["markdown_window_minutes"] <= data["case_life_minutes"]
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]
    assert isinstance(data.get("allergen_flags", []), list)


def assert_production_batch(data: dict):
    assert_common_fields(data)
    assert data["production_status"] in ["PLANNED", "IN_PRODUCTION", "ON_LINE"]
    assert data["hold_status"] in ["HOLDING", "MARKED_DOWN", "DISCARDED"]
    assert isinstance(data["planned_lbs"], (int, float)) and data["planned_lbs"] > 0
    assert isinstance(data["produced_lbs"], (int, float)) and data["produced_lbs"] >= 0


def assert_slicer(data: dict):
    assert_common_fields(data)
    assert data["sanitation_status"] in ["CLEAN", "IN_USE", "NEEDS_SANITATION", "SANITIZING"]
    assert isinstance(data["cuts_since_sanitation"], int)
    assert isinstance(data["in_use_minutes"], int)
    assert isinstance(data["sanitation_cycle_limit"], int) and data["sanitation_cycle_limit"] >= 1


def assert_sanitation_cycle(data: dict):
    assert_common_fields(data)
    assert data["cycle_type"] in ["ROUTINE", "ALLERGEN_CHANGEOVER", "TIMED"]
    assert data["status"] in ["OPEN", "COMPLETE", "ABORTED"]
    assert isinstance(data["cycle_minutes"], int) and data["cycle_minutes"] >= 1
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0


def assert_sub_ticket(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "QUEUED",
        "TICKETED",
        "IN_PROGRESS",
        "COMPLETED",
        "PICKED_UP",
        "REMADE",
        "BREAD_HOLD",
        "ABANDONED",
    ]
    assert data["order_channel"] in ["IN_STORE", "DIGITAL", "PHONE"]
    assert isinstance(data["creation_sequence"], int) and data["creation_sequence"] >= 1
    assert isinstance(data["ticket_number"], int)


def assert_promotion(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "ACTIVE", "DEGRADED", "SETTLED", "CANCELLED"]
    assert 0 <= data["forecast_uplift_pct"] <= 2
    assert isinstance(data["trailing_baseline_units"], int) and data["trailing_baseline_units"] >= 0


def assert_bread_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "CONFIRMED",
        "DELIVERED",
        "SHORT",
        "RECONCILED",
    ]
    assert isinstance(data["committed_units"], int) and data["committed_units"] >= 0


def assert_price_file(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "ACTIVE", "SUPERSEDED"]
    assert isinstance(data["item_price_count"], int) and data["item_price_count"] >= 0


def assert_label(data: dict):
    assert_common_fields(data)
    assert data["subject_type"] in ["SUB_TICKET", "PRODUCTION_BATCH", "CATERING_PLATTER"]
    assert data["status"] in ["ISSUED", "VOIDED"]
    assert isinstance(data["net_weight_lbs"], (int, float)) and data["net_weight_lbs"] > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["total_price_cents"], int)


def assert_catering_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "INQUIRY",
        "CONFIRMED",
        "IN_PRODUCTION",
        "READY",
        "PICKED_UP",
        "CANCELLED",
    ]
    assert isinstance(data["platter_count"], int) and data["platter_count"] >= 1
    assert isinstance(data["headcount"], int) and data["headcount"] >= 1
    assert isinstance(data["lead_time_hours"], int) and data["lead_time_hours"] >= 0
    assert isinstance(data["quote_total_cents"], int)


def assert_associate(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert data["primary_role"] in ["DELI_CLERK", "DELI_MANAGER", "BAKERY_COORDINATOR"]
    assert isinstance(data["active_certification_count"], int)


def assert_certification(data: dict):
    assert_common_fields(data)
    assert data["cert_type"] in ["SLICER_OPERATION", "FOOD_HANDLING", "ALLERGEN_MANAGEMENT"]
    assert data["status"] in ["ACTIVE", "EXPIRED", "REVOKED", "RENEWED"]
    assert isinstance(data["issued_at"], str)
    assert isinstance(data["expires_at"], str)


def assert_waste_record(data: dict):
    assert_common_fields(data)
    assert data["reason"] in [
        "HOLD_EXPIRED",
        "TEMPERATURE_BREACH",
        "ALLERGEN_CONTAMINATION",
        "QUALITY",
        "UNCLAIMED_PLATTER",
    ]
    assert data["status"] in ["DRAFT", "MARKED_DOWN", "DISCARDED", "VERIFIED", "VOIDED"]


def assert_store_invariants(data: dict):
    """Invariants that must hold on any store read."""
    assert data["case_on_hand_lbs"] >= 0
    assert data["certified_slicer_operator_count"] >= 0
    assert data["pending_waste_verification_count"] >= 0
    assert data["verified_waste_liability_cents"] >= 0
    assert data["ops_run_index"] >= 0


def assert_posture_report(data: dict):
    assert data["posture"] in ["OPEN", "RESTRICTED", "HALT"]
    assert isinstance(data["protection_index"], int)
    assert 0 <= data["protection_index"] <= 100
    assert isinstance(data["diffusion_index"], int)
    assert data["diffusion_index"] == 100 - data["protection_index"]


def assert_batch_invariants(data: dict):
    assert data["produced_lbs"] >= 0
    assert data["discard_lbs"] >= 0
    assert data["markdown_sold_lbs"] >= 0


def assert_waste_liability_invariants(data: dict):
    assert data["discard_value_cents"] >= 0
    assert data["handling_fee_cents"] >= 0
    assert data["total_liability_cents"] == data["discard_value_cents"] + data["handling_fee_cents"]


def assert_bread_unit_conservation(data: dict):
    """reserved_units plus unreserved_required_units never exceeds committed_units."""
    assert data["reserved_units"] + data["unreserved_required_units"] <= data["committed_units"]