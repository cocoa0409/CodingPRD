"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CapacityCommitStatus,
    JobMaterialStatus,
    JobRunStatus,
    MaintenanceOrderStatus,
    MoldOwnership,
    MoldServiceState,
    MoldStatus,
    PPAPStatus,
    PressQualificationStatus,
    PressStatus,
    QuoteStatus,
    ResinLotStatus,
    ToolTransferStatus,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict):
    """Every resource carries a UUID id, ISO 8601 stamps and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no type prefix: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 when the resource is created"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 16
    assert isinstance(data["credit_hold"], bool)


def assert_press(data: dict):
    assert_common_fields(data)
    assert isinstance(data["press_code"], str) and data["press_code"]
    assert isinstance(data["tonnage"], int) and data["tonnage"] >= 1
    assert isinstance(data["shot_size_grams_max"], int) and data["shot_size_grams_max"] >= 1
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 1
    assert data["status"] in _values(PressStatus), f"unexpected press status {data['status']!r}"
    assert isinstance(data["committed_minutes_scheduled"], int)
    assert data["committed_minutes_scheduled"] >= 0, "the press minute ledger never goes negative"


def assert_mold(data: dict):
    assert_common_fields(data)
    assert isinstance(data["mold_code"], str) and data["mold_code"]
    assert is_valid_uuid(data["customer_id"])
    assert data["cavity_count"] >= 1
    assert data["shot_weight_grams"] >= 1
    assert data["required_min_tonnage"] >= 1
    assert data["required_max_tonnage"] >= data["required_min_tonnage"]
    assert data["pm_interval_shots"] >= 1
    assert data["tooling_cost_cents"] >= 0
    assert data["ownership"] in _values(MoldOwnership)
    assert data["status"] in _values(MoldStatus), f"unexpected mold status {data['status']!r}"
    assert data["service_state"] in _values(MoldServiceState)
    assert data["total_shot_count"] >= 0 and data["shots_since_pm"] >= 0
    assert data["shots_since_pm"] <= data["total_shot_count"], (
        "shots_since_pm counts a suffix of the same non-reversed reports as total_shot_count"
    )


def assert_press_qualification(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["mold_id"]) and is_valid_uuid(data["press_id"])
    assert data["status"] in _values(PressQualificationStatus)
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_quote(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"]) and is_valid_uuid(data["mold_id"])
    assert data["part_weight_grams"] >= 1
    assert data["cycle_time_sec"] >= 1
    assert data["cavitation"] >= 1
    assert isinstance(data["resin_grade"], str) and data["resin_grade"]
    assert data["resin_price_cents_per_kg"] >= 1
    assert data["annual_volume"] >= 1
    assert data["status"] in _values(QuoteStatus)


def assert_ppap_submission(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["mold_id"]) and is_valid_uuid(data["quote_id"])
    assert 1 <= data["level"] <= 5
    assert 0 <= data["max_regrind_bp"] <= 10000
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert data["status"] in _values(PPAPStatus)


def assert_resin_lot(data: dict):
    assert_common_fields(data)
    assert isinstance(data["resin_grade"], str) and data["resin_grade"]
    assert isinstance(data["supplier_lot_code"], str) and data["supplier_lot_code"]
    assert data["qty_kg_received"] >= 1
    assert 0 <= data["moisture_bp"] <= 10000
    assert isinstance(data["qty_grams_remaining"], int)
    assert data["status"] in _values(ResinLotStatus)
    assert_resin_lot_invariants(data)


def assert_production_job(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["quote_id"]) and is_valid_uuid(data["mold_id"])
    assert is_valid_uuid(data["press_id"])
    assert data["planned_qty"] >= 1
    assert data["run_status"] in _values(JobRunStatus)
    assert data["material_status"] in _values(JobMaterialStatus)
    assert_job_rollup_invariants(data)


def assert_production_report(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["job_id"])
    assert data["shots"] >= 1
    assert 0 <= data["short_shot_shots"] <= data["shots"]
    assert data["good_parts"] >= 0 and data["scrap_parts"] >= 0
    assert data["virgin_grams"] >= 0 and data["regrind_grams"] >= 0
    assert data["run_minutes"] >= 1
    assert isinstance(data["is_reversed"], bool)


def assert_maintenance_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["mold_id"])
    assert data["kind"] in ("PM", "REPAIR")
    assert data["status"] in _values(MaintenanceOrderStatus)
    assert isinstance(data["shots_reset"], bool)
    assert data["window_start"] < data["window_end"], "window start must be strictly before its end"


def assert_tool_transfer(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["mold_id"]) and is_valid_uuid(data["to_customer_id"])
    assert data["from_ownership"] in _values(MoldOwnership)
    assert data["settlement_cents"] >= 0
    assert data["status"] in _values(ToolTransferStatus)


def assert_capacity_commit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"]) and is_valid_uuid(data["press_id"])
    assert data["committed_minutes"] >= 1
    assert data["shortfall_policy"] in ("STRICT", "GOODWILL")
    assert data["status"] in _values(CapacityCommitStatus)
    assert data["consumed_minutes"] >= 0
    assert data["shortfall_minutes"] >= 0
    assert data["shortfall_fee_cents"] >= 0
    assert data["utilization_bp"] >= 0


# ------------------------------------------------------ domain invariants ----

def assert_resin_lot_invariants(lot: dict):
    """The lot balance is a conserved quantity in whole grams."""
    assert isinstance(lot["qty_grams_remaining"], int), "mass is integer grams"
    assert lot["qty_grams_remaining"] >= 0, "a lot balance never goes negative"
    assert lot["qty_grams_remaining"] <= lot["qty_kg_received"] * 1000, (
        "the balance can never exceed the received mass"
    )


def assert_job_rollup_invariants(job: dict):
    """Rollups that must hold after any posting and after any reversal."""
    assert job["parts_molded_total"] == job["good_parts_total"] + job["scrap_parts_total"], (
        "parts conserve at every line, so parts_molded_total == good_parts_total + scrap_parts_total"
    )
    assert job["job_total_cost_cents"] == job["job_direct_cost_cents"] + job["job_overhead_cents"], (
        "job_total_cost_cents is job_direct_cost_cents plus job_overhead_cents"
    )
    if job["parts_molded_total"] == 0:
        assert job["first_pass_yield_bp"] == 10000, (
            "first_pass_yield_bp stands at 10000 basis points while parts_molded_total is zero"
        )
    if job["total_shots"] == 0:
        assert job.get("actual_cycle_time_sec") is None, (
            "actual_cycle_time_sec is unset whenever total_shots is zero"
        )
    for field in (
        "total_shots",
        "parts_molded_total",
        "good_parts_total",
        "scrap_parts_total",
        "short_shot_shots_total",
        "total_run_minutes",
        "cumulative_regrind_bp",
        "job_direct_cost_cents",
        "job_overhead_cents",
        "job_total_cost_cents",
    ):
        assert isinstance(job[field], int), f"{field} must be an integer"
        assert job[field] >= 0, f"{field} must not be negative"


def assert_integer_money(value, label="value"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be integer cents, got {value!r}"
    )


def assert_mass_conserved(lot: dict, expected_remaining: int):
    assert lot["qty_grams_remaining"] == expected_remaining, (
        f"Expected qty_grams_remaining {expected_remaining}, got {lot['qty_grams_remaining']}"
    )
    assert_resin_lot_invariants(lot)
