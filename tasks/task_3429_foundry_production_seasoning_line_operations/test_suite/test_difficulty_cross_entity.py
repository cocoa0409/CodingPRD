"""Difficulty queue: cross-entity state dependencies — the AIR_EMISSIONS permit
gating melt creation for an unrelated order, and product discontinuation gating
allocation confirmation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    charge_melt,
    create_allocation,
    create_melt_batch_payload,
    create_order,
    create_permit,
    discontinue_product,
    get_allocation,
    get_inventory_record,
    get_melt,
    get_order,
    record_chemistry,
    record_reading,
    release_order,
    setup_charging_melt,
    setup_inventory_with_stock,
    validate_error,
    validate_paginated,
)

_FM = TEST_USERS["foundry_manager_headers"]
_OP = TEST_USERS["melt_operator_headers"]
_RP = TEST_USERS["retail_planner_headers"]


def _air_breach_with_second_order():
    """O1's melt is held by an AIR breach; O2 (same product) is fresh and OPEN."""
    ctx = setup_charging_melt()
    permit = create_permit("AIR_EMISSIONS", limit_value=100.0)
    b1_id = ctx["melt"]["id"]
    charge_melt(b1_id)
    record_chemistry(b1_id)  # CHEMISTRY_CHECK when the breach lands
    record_reading(permit["id"], 120.0)
    record_reading(permit["id"], 130.0)
    o2 = release_order(create_order(ctx["product"]["id"],
                                    planned_quantity=5, scheduled_week=41)["id"])
    return ctx, permit["id"], b1_id, o2


def test_melt_create_blocked_during_air_breach_for_open_order(api):
    """PRD §3.3: "if the `AIR_EMISSIONS` permit exists and is in `BREACH`, the
    create is rejected with `ERR_EMISSIONS_PERMIT_BREACH` (HTTP 409)."
    The rejection is the direct permit dependency: O2's own posture is OPEN (it
    has no melts), so the posture gate cannot be what fires.

    Design: Difficulty/cross_entity_state_dependency/melt_create_blocked_during_air_breach
    """
    ctx, _, b1_id, o2 = _air_breach_with_second_order()
    payload = create_melt_batch_payload(
        o2["id"], o2["version"], furnace_id="FURNACE_B",
        planned_tap_start="2026-09-04T10:00:00Z",
        planned_tap_end="2026-09-04T12:00:00Z")
    resp = api.create_melt_batch(payload, _OP)
    validate_error(resp, ApiErrorId.ERR_EMISSIONS_PERMIT_BREACH)
    assert get_order(o2["id"])["posture"] == "OPEN"
    assert get_order(ctx["order"]["id"])["posture"] == "FROZEN"
    assert get_melt(b1_id)["state"] == "HELD"


def test_rejected_melt_create_persists_nothing_for_second_order(api):
    """PRD §3.3: "A `MeltOperator` creates a melt batch against a production order
    that is in `MOLDING` or `POURING` with a `posture` other than `FROZEN`"
    The breached permit stops the create before any batch exists: the order's melt
    list stays empty.

    Design: Difficulty/cross_entity_state_dependency/melt_create_blocked_during_air_breach
    """
    ctx, _, _, o2 = _air_breach_with_second_order()
    payload = create_melt_batch_payload(
        o2["id"], o2["version"], furnace_id="FURNACE_B",
        planned_tap_start="2026-09-04T10:00:00Z",
        planned_tap_end="2026-09-04T12:00:00Z")
    resp = api.create_melt_batch(payload, _OP)
    validate_error(resp, ApiErrorId.ERR_EMISSIONS_PERMIT_BREACH)
    _, meta = validate_paginated(api.list_melt_batches(
        _FM, params={"production_order_id": o2["id"]}))
    assert meta["total_count"] == 0


def _proposed_allocation_then_discontinue():
    """10 units in stock; a PROPOSED allocation of 4; then the product is
    discontinued."""
    ctx = setup_inventory_with_stock(num_units=10)
    record = ctx["inventory_record"]
    allocation = create_allocation(record["id"], allocated_qty=4)
    discontinue_product(ctx["product"]["id"])
    return ctx, record, allocation


def test_allocation_confirm_blocked_when_product_discontinued(api):
    """PRD §3.8: "Confirmation moves an allocation from `PROPOSED` to `CONFIRMED`
    and re-verifies the world at confirm time: the product must still be `ACTIVE`,
    else `ERR_PRODUCT_DISCONTINUED`"
    The allocation is in a valid from-state and inventory is available; the
    discontinued product alone blocks the confirm.

    Design: Difficulty/cross_entity_state_dependency/allocation_confirm_blocked_when_product_discontinued
    """
    _, _, allocation = _proposed_allocation_then_discontinue()
    resp = api.confirm_retail_allocation(allocation["id"], _RP)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED)
    assert get_allocation(allocation["id"])["status"] == "PROPOSED"


def test_failed_confirm_releases_no_reservation(api):
    """PRD §3.8: "Cancellation releases the reservation, subtracting
    `allocated_qty` from `reserved_units` and incrementing the inventory record's
    `version`."
    A rejected confirm is not a cancel: the reservation of 4 units stays in place.

    Design: Difficulty/cross_entity_state_dependency/allocation_confirm_blocked_when_product_discontinued
    """
    _, record, allocation = _proposed_allocation_then_discontinue()
    resp = api.confirm_retail_allocation(allocation["id"], _RP)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED)
    after = get_inventory_record(record["id"])
    assert after["reserved_units"] == 4
    assert after["on_hand_units"] == 10
