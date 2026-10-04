"""Pull-date cascade (quarantine -> cancel -> restore), unit conservation
across create-then-cancel, and the manual quarantine/release cycle with its
post-pull permanence.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_AT_PULL,
    InventoryLotStatus,
    ProgramAdvanceTarget,
    SeasonalProgramStatus,
    ShipmentStatus,
    WarehousePosture,
    TEST_USERS,
    advance_program_to,
    api_client,
    create_shipment_payload,
    get_inventory_lot,
    get_lot_for_run,
    get_program,
    get_shipment,
    get_warehouse,
    set_clock,
    setup_allocated_program,
    setup_disposition_program,
    setup_on_shelf_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["category_manager_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


# ---------------------------------------------------------------------------
# Depth-3 pull cascade
# ---------------------------------------------------------------------------

def _setup_on_shelf_with_planned_shipment():
    """ON_SHELF world: 100 produced, GOLD 60 ALLOCATED, one 30-unit PLANNED
    shipment (never delivered) — the lot sits at 70."""
    world = setup_on_shelf_program(
        commitment_specs=[{"tier": "GOLD", "units": 60, "use_default_retailer": True}],
        produced_units=100,
        shipment_specs=[{"units": 30, "deliver": False}],
    )
    return world


def test_pull_quarantines_lots_and_cancels_planned_shipments(api):
    """PRD §3.9: "First, every `AVAILABLE` `InventoryLot` whose product is a
    `SEASONAL` product of this program becomes `QUARANTINED`; everyday lots
    and other programs' lots are untouched. Second, every `PLANNED` shipment
    whose commitment belongs to this program becomes `CANCELLED`, because a
    shipment of quarantined stock cannot ship."

    Design: Difficulty/transitive_cascade/program_pull_quarantines_lots_cancels_shipments_restores_units
    """
    world = _setup_on_shelf_with_planned_shipment()
    lot_before = get_lot_for_run(world["run"]["id"])
    assert lot_before["units_on_hand"] == 70  # 100 produced - 30 drawn
    assert world["program"]["shipped_units_total"] == 30

    set_clock(CLOCK_AT_PULL)
    advance_program_to(world["program"]["id"], ProgramAdvanceTarget.DISPOSITION.value)

    lot = get_inventory_lot(lot_before["id"])
    assert lot["status"] == InventoryLotStatus.QUARANTINED.value
    assert lot["units_on_hand"] == 100, "LINK 3 restores the drawn 30"
    shipment = get_shipment(world["shipments"][0]["id"])
    assert shipment["status"] == ShipmentStatus.CANCELLED.value

    program = get_program(world["program"]["id"])
    assert program["status"] == SeasonalProgramStatus.DISPOSITION.value
    assert program["shipped_units_total"] == 0, (
        "CANCELLED shipments leave the shipped set"
    )


def test_pull_restores_cancelled_units_to_source_lot_and_recomputes(api):
    """PRD §3.9: "Third, each cancelled shipment's units are restored to the
    exact lots they were drawn from — each source lot's `units_on_hand` grows
    back by the units it contributed, in the reverse of the original draw
    order. The cascade then recomputes `in_use_units`, `quarantined_units`,
    and posture for the affected warehouses, recomputes the program's
    `shipped_units_total`".

    Design: Difficulty/transitive_cascade/program_pull_quarantines_lots_cancels_shipments_restores_units
    """
    world = _setup_on_shelf_with_planned_shipment()
    lot_before = get_lot_for_run(world["run"]["id"])

    set_clock(CLOCK_AT_PULL)
    advance_program_to(world["program"]["id"], ProgramAdvanceTarget.DISPOSITION.value)

    # Per-source-lot restore: units return to the lot they were drawn from.
    lot = get_inventory_lot(lot_before["id"])
    assert lot["units_on_hand"] == 100
    warehouse = get_warehouse(world["warehouse"]["id"])
    assert warehouse["in_use_units"] == 100
    assert warehouse["quarantined_units"] == 100
    assert warehouse["posture"] == WarehousePosture.OPEN.value


# ---------------------------------------------------------------------------
# Conservation across create-then-pull-cancel
# ---------------------------------------------------------------------------

def _setup_on_shelf_with_delivered_and_planned():
    """ON_SHELF world: 100 produced, GOLD 60 ALLOCATED, shipment1 20 DELIVERED
    and shipment2 30 still PLANNED — the lot sits at 50."""
    return setup_on_shelf_program(
        commitment_specs=[{"tier": "GOLD", "units": 60, "use_default_retailer": True}],
        produced_units=100,
        shipment_specs=[
            {"units": 20, "deliver": True},
            {"units": 30, "deliver": False},
        ],
    )


def test_pull_cancels_only_planned_shipments_delivered_untouched(api):
    """PRD §3.9: "Second, every `PLANNED` shipment whose commitment belongs to
    this program becomes `CANCELLED`, because a shipment of quarantined stock
    cannot ship." (DELIVERED shipments are not PLANNED and are untouched.)

    Design: Difficulty/compensating_invariant/shipment_create_then_pull_cancel_restores_lot_units_unchanged
    """
    world = _setup_on_shelf_with_delivered_and_planned()
    lot_before = get_lot_for_run(world["run"]["id"])
    assert lot_before["units_on_hand"] == 50  # 100 - 20 delivered - 30 planned

    set_clock(CLOCK_AT_PULL)
    advance_program_to(world["program"]["id"], ProgramAdvanceTarget.DISPOSITION.value)

    sh1 = get_shipment(world["shipments"][0]["id"])
    sh2 = get_shipment(world["shipments"][1]["id"])
    assert sh1["status"] == ShipmentStatus.DELIVERED.value
    assert sh2["status"] == ShipmentStatus.CANCELLED.value
    # The CANCELLED 30 restore; the DELIVERED 20 do not.
    assert get_inventory_lot(lot_before["id"])["units_on_hand"] == 80


def test_pull_conserves_produced_units_invariant(api):
    """PRD §3.9: "each cancelled shipment's units are restored to the exact
    lots they were drawn from — each source lot's `units_on_hand` grows back
    by the units it contributed". PRD §3.6: "each creation recomputes the
    program's `shipped_units_total` — the sum of `units` over shipments in
    `PLANNED` or `DELIVERED` status for the program's commitments".

    Design: Difficulty/compensating_invariant/shipment_create_then_pull_cancel_restores_lot_units_unchanged
    """
    world = _setup_on_shelf_with_delivered_and_planned()
    lot_before = get_lot_for_run(world["run"]["id"])

    set_clock(CLOCK_AT_PULL)
    advance_program_to(world["program"]["id"], ProgramAdvanceTarget.DISPOSITION.value)

    lot = get_inventory_lot(lot_before["id"])
    program = get_program(world["program"]["id"])
    # Conservation: on_hand + delivered + disposed == produced.
    assert lot["units_on_hand"] == 80
    assert program["shipped_units_total"] == 20
    assert program["disposed_units_total"] == 0
    assert lot["units_on_hand"] + 20 + program["disposed_units_total"] == (
        program["produced_units_total"] == 100 and 100
    )


# ---------------------------------------------------------------------------
# Manual quarantine/release cycle (pre-pull)
# ---------------------------------------------------------------------------

def test_quarantined_lot_excluded_from_fefo_draw(api):
    """PRD §3.6: "the draw walks the warehouse's `AVAILABLE` lots of the
    shipment's product in `created_at` ascending order ... If the warehouse's
    available stock of the product falls short of the request, the create is
    rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 409)." PRD §3.9: "A
    `CategoryManager` may place a manual QA hold on any `AVAILABLE` lot,
    moving it to `QUARANTINED`".

    Design: Difficulty/non_linear_state_machine/inventory_lot_quarantine_release_cycle
    """
    world = setup_allocated_program(
        commitment_specs=[{"tier": "GOLD", "units": 100, "use_default_retailer": True}],
        produced_units=100,
    )
    lot = world["lot"]
    set_clock("2027-08-01T00:00:00Z")  # mid ship window

    quarantined = validate_success(
        api_client.quarantine_inventory_lot(lot["id"], CM), 200,
    )
    assert quarantined["status"] == InventoryLotStatus.QUARANTINED.value
    warehouse = get_warehouse(world["warehouse"]["id"])
    assert warehouse["quarantined_units"] == 100

    # QUARANTINED lots are not AVAILABLE: the FEFO pool is empty.
    blocked = api_client.create_shipment(
        create_shipment_payload(
            commitment_id=world["commitment"]["id"],
            warehouse_id=world["warehouse"]["id"], units=1,
            ship_on="2027-08-02T00:00:00Z",
        ),
        LOGISTICS,
    )
    validate_error(blocked, ApiErrorId.ERR_INSUFFICIENT_STOCK)


def test_release_quarantine_returns_lot_to_pool(api):
    """PRD §3.9: "may later release a `QUARANTINED` lot back to `AVAILABLE` —
    but only pre-pull: both operations require the program of the lot's
    product to be outside `DISPOSITION`, `CLOSED`, and `CANCELLED`".

    Design: Difficulty/non_linear_state_machine/inventory_lot_quarantine_release_cycle
    """
    world = setup_allocated_program(
        commitment_specs=[{"tier": "GOLD", "units": 100, "use_default_retailer": True}],
        produced_units=100,
    )
    lot = world["lot"]
    set_clock("2027-08-01T00:00:00Z")
    validate_success(api_client.quarantine_inventory_lot(lot["id"], CM), 200)

    released = validate_success(
        api_client.release_inventory_lot_quarantine(lot["id"], CM), 200,
    )
    assert released["status"] == InventoryLotStatus.AVAILABLE.value
    assert get_warehouse(world["warehouse"]["id"])["quarantined_units"] == 0

    shipped = api_client.create_shipment(
        create_shipment_payload(
            commitment_id=world["commitment"]["id"],
            warehouse_id=world["warehouse"]["id"], units=1,
            ship_on="2027-08-02T00:00:00Z",
        ),
        LOGISTICS,
    )
    data = validate_success(shipped, 201)
    assert data["status"] == ShipmentStatus.PLANNED.value
    assert get_inventory_lot(lot["id"])["units_on_hand"] == 99


# ---------------------------------------------------------------------------
# Post-pull quarantine is permanent
# ---------------------------------------------------------------------------

def test_lot_release_after_program_pull_returns_invalid_state(api):
    """PRD §3.9: "both operations require the program of the lot's product to
    be outside `DISPOSITION`, `CLOSED`, and `CANCELLED`, and a violation is
    rejected with `ERR_INVALID_STATE`. Post-pull quarantine is permanent; the
    only way out for a quarantined lot then is disposition."

    Design: Corner/state_machines/lot_release_after_program_pull_returns_invalid_state
    """
    world = setup_disposition_program(produced_units=10)
    lot = world["lot"]
    assert lot["status"] == InventoryLotStatus.QUARANTINED.value

    resp = api_client.release_inventory_lot_quarantine(lot["id"], CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_inventory_lot(lot["id"])
    assert after["status"] == InventoryLotStatus.QUARANTINED.value
    assert after["units_on_hand"] == 10
