"""Corner coverage — circulating-side state machines (PRD §3.1-§3.3):
the Federal Reserve order lifecycle (SUBMITTED/SCHEDULED/FULFILLING/
SHORTFALL_RECORDED), the production-run gates (start, inspect, cancel),
and the procurement lot's single receive transition."""

from test_helpers import ApiErrorId, TEST_USERS, validate_error, validate_success
from test_helpers.assertions import (
    assert_blank_conservation,
    assert_federal_reserve_order,
    assert_production_run,
    assert_report_envelope,
)
from test_helpers.factories import inspect_payload
from test_helpers.fixtures import (
    create_completed_run,
    create_denomination,
    create_fed_order,
    create_metal_lot,
    create_run,
    create_started_run,
    inspect_run,
    receive_metal_lot,
    set_clock,
    setup_circulating_base,
    start_run,
)

LIAISON = TEST_USERS["fed_liaison_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
PROCUREMENT = TEST_USERS["procurement_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def _get_fed_order(api, order_id):
    return validate_success(api.get_fed_order(order_id, LIAISON))


def _get_run(api, run_id):
    return validate_success(api.get_production_run(run_id, PLANNER))


def test_fedorder_initial_state_then_schedule_and_fulfill_transitions(api):
    """PRD §3.1: "Newly submitted orders sit in `SUBMITTED`, and at creation
    the platform snapshots `budgeted_seigniorage_cents` as
    `quantity_ordered_pieces` multiplied by the denomination's current
    `budgeted_unit_seigniorage_cents`."
    PRD §3.1: "Creating the first production run against an order moves it
    `SUBMITTED → SCHEDULED`; the first linked run to begin striking moves it
    `SCHEDULED → FULFILLING`."

    Design: Corner/state_machines/fedorder_initial_state_then_schedule_and_fulfill_transitions
    """
    _, _, fed_order = setup_circulating_base(api, quantity_ordered_pieces=50000)
    assert fed_order["status"] == "SUBMITTED"

    run = create_run(api, fed_order["id"], planned_quantity=50000)
    assert run["status"] == "PLANNED"
    order = _get_fed_order(api, fed_order["id"])
    assert order["status"] == "SCHEDULED", (
        f"first linked run must move the order to SCHEDULED, got {order['status']}")

    run = start_run(api, run["id"])
    assert run["status"] == "STRIKING"
    order = _get_fed_order(api, fed_order["id"])
    assert_federal_reserve_order(order)
    assert order["status"] == "FULFILLING", (
        f"first striking run must move the order to FULFILLING, got {order['status']}")


def test_fedorder_cancel_from_fulfilling_rejected(api):
    """PRD §3.1: "An order in `FULFILLING`, `FULFILLED`, `SHORTFALL_RECORDED`,
    or `CANCELLED` cannot be cancelled; the attempt is rejected with
    `ERR_FEDORDER_NOT_CANCELLABLE` (422)."

    Design: Corner/state_machines/fedorder_cancel_from_fulfilling_rejected
    """
    _, _, fed_order = setup_circulating_base(api, quantity_ordered_pieces=50000)
    create_started_run(api, fed_order["id"], planned_quantity=50000)
    assert _get_fed_order(api, fed_order["id"])["status"] == "FULFILLING"

    resp = api.cancel_fed_order(fed_order["id"], LIAISON)
    validate_error(resp, ApiErrorId.ERR_FEDORDER_NOT_CANCELLABLE)
    assert _get_fed_order(api, fed_order["id"])["status"] == "FULFILLING"


def test_fedorder_shortfall_recorded_when_runs_exhausted(api):
    """PRD §3.1: "If instead every linked run of a `SCHEDULED` or `FULFILLING`
    order has reached a terminal state — `COMPLETED` or `CANCELLED`, with at
    least one linked run existing — and the fulfilled count still falls short
    of the ordered quantity, the order auto-transitions to
    `SHORTFALL_RECORDED`, again incrementing `version`."
    PRD §3.1: "As runs complete, the order's `quantity_fulfilled_pieces`
    accumulates the `produced_pieces` of its `COMPLETED` linked runs."
    PRD §2.5: "Nullable computed fields stay null until the event that fixes
    them: an order's `realized_seigniorage_cents` until the order is fulfilled,
    a lot's `realized_cost_cents` until the lot is delivered, an allocation's
    `total_price_cents` until the allocation is confirmed, and a case's
    `destroyed_by_user_ids` until destruction is certified."

    Design: Corner/state_machines/fedorder_shortfall_recorded_when_runs_exhausted
    """
    _, _, fed_order = setup_circulating_base(api, quantity_ordered_pieces=100000)
    # Two runs on the same facility but different press lines: no overlap.
    run1 = create_run(api, fed_order["id"], facility="PHILADELPHIA",
                      press_line="P1", planned_quantity=60000)
    run2 = create_run(api, fed_order["id"], facility="PHILADELPHIA",
                      press_line="P2", planned_quantity=40000)
    run1 = start_run(api, run1["id"])
    run1 = inspect_run(api, run1["id"], outcome="PASS", good_pieces=60000)
    assert run1["status"] == "COMPLETED"

    # Cancelling the last non-terminal run leaves every linked run terminal
    # with 60000 fulfilled < 100000 ordered.
    cancelled = validate_success(api.cancel_production_run(run2["id"], PLANNER))
    assert cancelled["status"] == "CANCELLED"

    order = _get_fed_order(api, fed_order["id"])
    assert_federal_reserve_order(order)
    assert order["status"] == "SHORTFALL_RECORDED"
    assert order["quantity_fulfilled_pieces"] == 60000
    assert order["realized_seigniorage_cents"] is None, (
        "realized seigniorage finalizes only at FULFILLED")


def test_run_cancel_from_striking_rejected(api):
    """PRD §3.3: "A planner may cancel a run in `PLANNED` or `REWORK`;
    cancelling one in `STRIKING`, `COMPLETED`, or `CANCELLED` is rejected with
    `ERR_RUN_NOT_CANCELLABLE` (422)."
    PRD §3.3: "A successful start debits `blank_stock_pieces` by
    `planned_quantity`, sets the run's `reserved_blanks` to `planned_quantity`,
    increments both the run's and the denomination's `version`, and — when the
    linked order is still `SCHEDULED` — moves the order to `FULFILLING`."

    Design: Corner/state_machines/run_cancel_from_striking_rejected
    """
    _, _, fed_order = setup_circulating_base(api, quantity_ordered_pieces=50000)
    run = create_started_run(api, fed_order["id"], planned_quantity=50000)
    assert run["status"] == "STRIKING"

    resp = api.cancel_production_run(run["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_CANCELLABLE)
    run = _get_run(api, run["id"])
    assert_production_run(run)
    assert run["status"] == "STRIKING"
    assert run["reserved_blanks"] == 50000


def test_run_inspect_from_planned_rejected(api):
    """PRD §3.3: "Inspection resolves a striking run inside a single
    `QualityInspector` action carrying an `outcome`; `INSPECTION` is entered
    and left within that call and is never persisted as a resting state, and
    inspecting a run that is not in `STRIKING` is rejected with
    `ERR_RUN_NOT_INSPECTABLE` (422)."

    Design: Corner/state_machines/run_inspect_from_planned_rejected
    """
    create_denomination(api)
    fed_order = create_fed_order(api, quantity_ordered_pieces=50000)
    run = create_run(api, fed_order["id"], planned_quantity=50000)
    assert run["status"] == "PLANNED"

    resp = api.inspect_production_run(
        run["id"], inspect_payload("PASS", 50000), INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_INSPECTABLE)
    assert _get_run(api, run["id"])["status"] == "PLANNED"


def test_run_start_without_blank_stock_rejected(api):
    """PRD §3.3: "The denomination's `blank_stock_pieces` must be at least the
    run's `planned_quantity` (`ERR_BLANKS_INSUFFICIENT`, 422)."

    Design: Corner/state_machines/run_start_without_blank_stock_rejected
    """
    # No lot is ever delivered, so blank stock stays 0 while the linked order
    # is SCHEDULED and the quality record is clean — the fiscal gate alone fires.
    create_denomination(api)
    fed_order = create_fed_order(api, quantity_ordered_pieces=50000)
    run = create_run(api, fed_order["id"], planned_quantity=50000)
    assert _get_fed_order(api, fed_order["id"])["status"] == "SCHEDULED"

    resp = api.start_production_run(run["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_BLANKS_INSUFFICIENT)
    assert _get_run(api, run["id"])["status"] == "PLANNED"


def test_lot_double_receive_rejected(api):
    """PRD §3.2: "Receiving moves the lot `ORDERED → DELIVERED` (receiving a
    lot not in `ORDERED` is rejected with `ERR_LOT_NOT_RECEIVABLE`, 422), fixes
    `realized_cost_cents` as `quantity_tonnes` multiplied by the locked unit
    price when one is present or by the commodity's current spot price per
    tonne at delivery time when the lot is unhedged, and credits the
    denomination's `blank_stock_pieces` by the lot's `blanks_produced`,
    incrementing the denomination's `version`."
    PRD §3.2: "The lot's `blanks_produced` is computed immediately as
    `quantity_tonnes` multiplied by the denomination's `blanks_per_tonne`, and
    the lot sits in `ORDERED`."
    PRD §2.9: "The seigniorage report carries one row per denomination with
    `budgeted_seigniorage_cents` summed over non-cancelled orders'
    creation-time snapshots, `realized_seigniorage_cents` summed over
    `FULFILLED` orders, and the reconciliation figures `blanks_on_hand_pieces`,
    `blanks_reserved_pieces`, `blanks_produced_pieces`,
    `blanks_scrapped_pieces`, and `blanks_delivered_pieces`; optional
    `fiscal_year` and `denomination_code` query parameters narrow the rows."

    Design: Corner/state_machines/lot_double_receive_rejected
    """
    set_clock(api, "2026-09-10T00:00:00Z", {"COPPER": 800000})
    create_denomination(api)
    lot = create_metal_lot(api, quantity_tonnes=1,
                           locked_unit_price_cents_per_tonne=800000,
                           vault="DENVER_VAULT",
                           planned_delivery_date="2026-09-10")
    lot = receive_metal_lot(api, lot["id"])
    assert lot["status"] == "DELIVERED"

    resp = api.receive_metal_lot(lot["id"], PROCUREMENT)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_RECEIVABLE)

    # Blank stock was credited exactly once: 1 tonne x 176000 blanks/tonne.
    resp = api.get_report("seigniorage", FINANCE,
                          params={"denomination_code": "QUARTER"})
    report = validate_success(resp)
    assert_report_envelope(report, "seigniorage")
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["blanks_on_hand_pieces"] == 176000, (
        f"stock must be credited exactly once (176000), got "
        f"{row['blanks_on_hand_pieces']}")
    assert row["blanks_delivered_pieces"] == 176000
    assert_blank_conservation(row)
