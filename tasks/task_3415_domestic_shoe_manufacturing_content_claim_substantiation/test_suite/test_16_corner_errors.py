"""Corner coverage: error catalogue probes not owned by difficulty instances
(material shortage pairing, workforce shortfall, clock monotonicity)."""
from test_helpers import (
    ApiErrorId, bom_line, get_lot, get_run, lock_allocation, make_allocation,
    make_component, make_factory, make_lot, make_model, make_run,
    reserve_run, set_clock, standard_kit, validate_error, validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]
PLANNER = TEST_USERS["planner"]


def test_err_material_shortage_vs_domestic_shortage():
    """PRD §3.5: "Material allocation is first-in-first-out per
    bill-of-materials line, taken in BOM array order."
    PRD §3.5: "If eligible stock cannot cover a line, the entire reservation
    aborts with no partial consumption: a shortfall on a `DOMESTIC_REQUIRED`
    line is rejected with `ERR_DOMESTIC_MATERIAL_SHORTAGE` (HTTP 409) and a
    shortfall on any other line with `ERR_MATERIAL_SHORTAGE` (HTTP 409)."

    Design: Corner/errors/err_material_shortage_vs_domestic_shortage
    """
    set_clock()
    factory = make_factory()
    c_t = make_component()
    c_u = make_component("Full-grain leather upper", "UPPER")
    lot_t = make_lot(c_t["id"], quantity_received=5, unit_cost_cents=100)
    lot_u = make_lot(c_u["id"], supplier_name="Incheon Leather",
                     quantity_received=10, unit_cost_cents=900, is_domestic=False)
    model = make_model(bom_lines=[
        bom_line(c_t["id"], planned_unit_cost_cents=100, planned_is_domestic=False),
        bom_line(c_u["id"], sourcing_requirement="DOMESTIC_REQUIRED",
                 planned_unit_cost_cents=900, planned_is_domestic=True),
    ], style_code="MSHORT")
    allocation = make_allocation(factory["id"], "2026-W36", 100)
    run = make_run(model["id"], factory["id"], planned_units=10)
    lock_allocation(allocation["id"])

    # Line 1 (thread, IMPORT_ALLOWED, needs 10, only 5 on hand) fails first.
    resp = api.reserve_materials(run["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_MATERIAL_SHORTAGE)
    # Atomic abort: no lot touched, run still PLANNED.
    assert get_lot(lot_t["id"])["quantity_remaining"] == 5
    assert get_lot(lot_u["id"])["quantity_remaining"] == 10
    after = get_run(run["id"])
    assert after["status"] == "PLANNED" and after["consumed_lots"] == []


def test_domestic_material_shortage_only_imported_stock():
    """PRD §3.5: "The eligible lots are those whose `component_id` matches the
    line's component and whose `quantity_remaining` is greater than zero — and
    for a `DOMESTIC_REQUIRED` line, only lots with `is_domestic` true are
    eligible at all."
    PRD §3.5: "a shortfall on a `DOMESTIC_REQUIRED` line is rejected with
    `ERR_DOMESTIC_MATERIAL_SHORTAGE` (HTTP 409)"

    Design: Corner/errors/domestic_material_shortage_only_imported_stock
    """
    set_clock()
    factory = make_factory()
    c_u = make_component("Full-grain leather upper", "UPPER")
    lot = make_lot(c_u["id"], supplier_name="Incheon Leather",
                   quantity_received=100, unit_cost_cents=900, is_domestic=False)
    model = make_model(bom_lines=[
        bom_line(c_u["id"], sourcing_requirement="DOMESTIC_REQUIRED",
                 planned_unit_cost_cents=900, planned_is_domestic=True),
    ], style_code="MDOMREQ")
    allocation = make_allocation(factory["id"], "2026-W36", 100)
    run = make_run(model["id"], factory["id"], planned_units=10)
    lock_allocation(allocation["id"])

    # 100 imported units do not count toward a DOMESTIC_REQUIRED line.
    resp = api.reserve_materials(run["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_DOMESTIC_MATERIAL_SHORTAGE)
    assert get_lot(lot["id"])["quantity_remaining"] == 100
    after = get_run(run["id"])
    assert after["status"] == "PLANNED" and after["consumed_lots"] == []


def test_workforce_shortfall_blocks_run_start():
    """PRD §3.5: "For each of the three operations, the plant must field at
    least the per-run requirement of `ACTIVE` workers holding a certification
    for that operation with `cert_status` `CERTIFIED` — 2 for `STITCHING`, 1
    for `LASTING`, and 1 for `ASSEMBLY` — and a shortfall in any operation
    rejects the start with `ERR_WORKFORCE_SHORTFALL` (HTTP 422)."

    Design: Corner/errors/workforce_shortfall_blocks_run_start
    """
    kit = standard_kit()
    lock_allocation(kit["allocation"]["id"])
    kit["run"] = reserve_run(kit["run"]["id"])
    # No workers at all at the factory.
    resp = api.start_run(kit["run"]["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_WORKFORCE_SHORTFALL)
    # The run stays MATERIAL_RESERVED with its lots still consumed.
    assert get_run(kit["run"]["id"])["status"] == "MATERIAL_RESERVED"
    assert get_lot(kit["lot"]["id"])["quantity_remaining"] == 990


def test_clock_regression_is_rejected():
    """PRD §2.4: "A `PlatformAdmin`-only clock-advance capability moves the
    clock forward to a supplied `to_iso8601` instant and returns the resulting
    `current_utc`; attempting to move the clock backwards is rejected with
    `ERR_CLOCK_REGRESSION` (HTTP 400)."

    Design: Corner/errors/clock_regression_is_rejected
    """
    set_clock()
    set_clock("2026-09-05T00:00:00Z")
    resp = api.set_clock({"to_iso8601": "2026-09-04T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
    # Re-setting the current timestamp exactly is not a regression.
    ok = validate_success(api.set_clock({"to_iso8601": "2026-09-05T00:00:00Z"}, ADMIN))
    assert ok["current_utc"].startswith("2026-09-05T00:00:00")
