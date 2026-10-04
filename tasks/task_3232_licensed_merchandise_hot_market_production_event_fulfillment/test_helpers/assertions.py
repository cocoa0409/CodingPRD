"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_licensor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["league_code"], str) and data["league_code"]
    assert 0 <= data["royalty_rate_pct"] <= 1
    assert data["minimum_guarantee_cents"] >= 0
    assert isinstance(data["currency"], str)
    assert_licensor_invariants(data)


def assert_licensor_invariants(data: dict):
    """The ledger triple invariant: U = max(0, A - B) at every observable point."""
    a = data["accrued_royalty_cents"]
    b = data["guarantee_recovery_block_cents"]
    u = data["accrued_unsettled_cents"]
    assert u == max(0, a - b), f"ledger invariant broken: U={u}, A={a}, B={b}"


def assert_design(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["licensor_id"], str)
    assert data["approval_state"] in [
        "PENDING_LICENSOR_APPROVAL", "APPROVED", "APPROVAL_REJECTED",
    ]
    assert data["garment_sku"] in [
        "JERSEY", "TRACTOR", "DUFFEL", "CAP", "MINI", "PENNANT",
    ]
    assert data["player_code"] is None or isinstance(data["player_code"], str)
    if data["approval_state"] == "APPROVED":
        assert isinstance(data["approved_version"], int), (
            "an approved design pins approved_version"
        )
    else:
        assert data["approved_version"] is None


def assert_production_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "PARALLEL_HOLD", "COMMITTED", "PRINTING",
        "RETIRED_DESTROYED", "RETIRED_DONATED",
    ]
    assert data["trigger_type"] in [
        "CHAMPIONSHIP_WIN", "MILESTONE", "ATHLETE_TRANSACTION", "STANDARD",
    ]
    assert data["event_outcome"] in [
        "WIN_FAVORED_TEAM", "WIN_UNDERDOG_TEAM", "NO_OUTCOME",
    ]
    assert data["expected_demand_qty"] > 0
    assert data["unit_cost_cents"] > 0
    assert isinstance(data["layer_ids"], list)
    assert data["base_units_printed"] >= 0
    assert data["accessory_units_printed"] >= 0
    assert data["destroyed_units"] >= 0
    assert data["donated_units"] >= 0
    if data["status"] == "PARALLEL_HOLD":
        assert data["committed_at"] is None
    else:
        assert data["committed_at"] is not None


def assert_print_layer(data: dict):
    _assert_common_fields(data)
    assert data["print_type"] in ["BASE", "EMBROIDER", "HEAT_PRESS", "PENNANT"]
    assert data["layer_state"] in ["PENDING_PRINT", "PRINTED", "PRINT_FAILED"]
    assert data["quantity"] > 0
    assert data["printed_qty"] >= 0
    assert data["failed_qty"] >= 0
    assert data["committed_qty"] >= 0
    if data["layer_state"] == "PENDING_PRINT":
        assert data["printed_qty"] == 0 and data["committed_qty"] == 0


def assert_print_capacity(data: dict):
    _assert_common_fields(data)
    assert data["print_type"] in ["BASE", "EMBROIDER", "HEAT_PRESS"]
    assert data["capacity_qty"] > 0
    assert data["rush_sla_hours"] > 0
    assert data["reserved_qty"] >= 0
    assert data["available_qty"] == data["capacity_qty"] - data["reserved_qty"]


def assert_print_reservation(data: dict):
    _assert_common_fields(data)
    assert data["reservation_state"] == "HELD"
    assert data["quantity"] > 0
    assert isinstance(data["needed_by"], str) and data["needed_by"]


def assert_fulfillment_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "PLANNED", "PICKED", "SHIPPED", "DELIVERED", "DISTRESSED", "RETURNED",
    ]
    assert data["channel"] in ["VENUE_RETAIL", "EVENT_POPUP", "ECOM"]
    assert data["quantity"] > 0
    for field in (
        "picked_qty", "shipped_qty", "returned_qty",
        "destroyed_qty", "donated_qty",
    ):
        assert data[field] >= 0, f"{field} must be non-negative"
    assert_fulfillment_order_invariants(data)


def assert_fulfillment_order_invariants(data: dict):
    """Quantities are monotone ledgers; nothing exceeds what was requested."""
    assert data["shipped_qty"] <= data["picked_qty"], "cannot ship more than was picked"
    assert data["picked_qty"] <= data["quantity"], "cannot pick more than requested"
    assert data["realized_wholesale_cents"] >= 0
    assert data["requested_wholesale_cents"] >= 0
    if data["status"] == "DELIVERED":
        assert data["realized_wholesale_cents"] == data["requested_wholesale_cents"]
    if data["status"] == "DISTRESSED":
        assert data["realized_wholesale_cents"] == 0


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert data["carrier"] in ["RUSH_AIR", "GROUND"]
    assert data["sla_hours"] > 0
    assert data["shipment_state"] in ["IN_TRANSIT", "DELIVERED"]
    if data["shipment_state"] == "IN_TRANSIT":
        assert data["delivered_at"] is None
    else:
        assert data["delivered_at"] is not None


def assert_royalty_accrual(data: dict):
    _assert_common_fields(data)
    assert data["accrual_state"] in ["ACCRUED", "SETTLED"]
    assert data["gross_wholesale_cents"] >= 0
    assert data["accrued_cents"] >= 0
    assert isinstance(data["superseded"], bool)
    if data["superseded"]:
        assert data["accrued_cents"] == 0, "a superseded row contributes nothing"


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PENDING", "APPROVED", "REVERSED"]
    assert data["snapped_accrued_cents"] >= 0
    assert data["guarantee_shortfall_cents"] >= 0
    assert data["max_recoverable_early_cents"] >= 0
    assert data["reserved_cents"] >= 0


def assert_counterfeit_report(data: dict):
    _assert_common_fields(data)
    assert data["report_status"] in ["OPEN", "ENFORCED"]
    assert data["unit_count"] > 0
    assert data["suspect_quantity"] >= 0
    assert data["total_exposure_cents"] == (
        data["royalty_leakage_cents"] + data["penalty_cents"]
    )
    if data["report_status"] == "OPEN":
        assert data["total_exposure_cents"] == 0


def assert_royalty_rate_applied(rate_for_sku: dict, sku: str, expected_rate: float):
    assert rate_for_sku[sku] == expected_rate, (
        f"royalty rate for {sku} should be {expected_rate}"
    )