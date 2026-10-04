"""Resource temporal overlap: line-slot same-day exclusion and ship-week
window membership."""
from test_helpers import (
    ApiErrorId,
    confirm_order,
    create_run,
    get_success_data,
    make_active_formulation,
    make_completed_run,
    make_dealer,
    make_order,
    make_plant,
    make_price_book,
    make_product_line,
    make_supplier,
    set_clock,
    ship_order,
    stock_resin,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
DSR = TEST_USERS["dealer_sales_rep_headers"]


def test_line_slot_same_day_exclusion(api):
    """PRD §3.4: "Scheduling assigns the run a `line_slot`: the lowest free
    extrusion-line index for that plant and production date. The slot is
    unique per plant per `production_date`."
    PRD §3.4: "`NULL_SLOT` runs carry `line_slot` equal to null"

    Design: Difficulty/resource_temporal_overlap/line_slot_same_day_exclusion
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(daily_capacity_lf=10000, lines=1)
    form = make_active_formulation()
    line = make_product_line(form["id"])

    # A NULL_SLOT run holds no extrusion slot: line_slot is null.
    run0 = create_run(plant["id"], line["id"], 100, "2026-03-02", run_kind="NULL_SLOT")
    assert run0["line_slot"] is None

    run1 = create_run(plant["id"], line["id"], 100, "2026-03-02")
    assert run1["line_slot"] == 1

    plant_now = get_success_data(api.get_plant(plant["id"], OPS))
    resp_same_day = api.create_production_run(plant["id"], {
        "product_line_id": line["id"], "planned_lf": 100,
        "production_date": "2026-03-02",
        "expected_plant_version": plant_now["version"],
    }, OPS)
    validate_error(resp_same_day, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    run2 = create_run(plant["id"], line["id"], 100, "2026-03-03")
    assert run2["line_slot"] == 1
    # Identical color/profile/emboss/capped -> 15-minute base changeover only.
    assert run2["changeover_minutes"] == 15


def test_line_slot_lowest_free_index_assigned(api):
    """PRD §3.4: "Scheduling assigns the run a `line_slot`: the lowest free
    extrusion-line index for that plant and production date."

    Design: Difficulty/resource_temporal_overlap/line_slot_same_day_exclusion
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(daily_capacity_lf=10000, lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"])
    run1 = create_run(plant["id"], line["id"], 100, "2026-03-02")
    run2 = create_run(plant["id"], line["id"], 100, "2026-03-02")
    assert run1["line_slot"] == 1
    assert run2["line_slot"] == 2


def _ship_window_setup(api):
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"])
    make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer()
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=3000)
    make_completed_run(plant["id"], line["id"], 2000, "2026-03-01")
    return plant, line, dealer


def test_ship_week_window_membership(api):
    """PRD §3.6: "Shipping, performed by a `DealerSalesRep`, requires the
    logical clock date to fall within the confirmed ship week — the seven days
    from `ship_week_start` through six days after it, inclusive — and
    otherwise fails with `ERR_OUTSIDE_SHIP_WEEK` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/ship_week_window_membership
    """
    plant, line, dealer = _ship_window_setup(api)
    order_a = make_order(dealer["id"], line["id"], 100, "2026-03-02")
    confirm_order(order_a["id"])
    order_b = make_order(dealer["id"], line["id"], 100, "2026-03-02")
    confirm_order(order_b["id"])
    order_c = make_order(dealer["id"], line["id"], 100, "2026-03-02")
    confirm_order(order_c["id"])

    # One day before the Monday: outside.
    set_clock("2026-03-01T00:00:00Z")
    resp_a = api.ship_shipment_order(order_a["id"], DSR)
    validate_error(resp_a, ApiErrorId.ERR_OUTSIDE_SHIP_WEEK)

    # Window start and window end (inclusive): both succeed.
    set_clock("2026-03-02T00:00:00Z")
    shipped_b = ship_order(order_b["id"])
    assert shipped_b["actual_ship_date"] == "2026-03-02"
    set_clock("2026-03-08T00:00:00Z")
    shipped_c = ship_order(order_c["id"])
    assert shipped_c["actual_ship_date"] == "2026-03-08"


def test_ship_after_window_end_fails(api):
    """PRD §3.6: "the seven days from `ship_week_start` through six days after
    it, inclusive — and otherwise fails with `ERR_OUTSIDE_SHIP_WEEK`"

    Design: Difficulty/resource_temporal_overlap/ship_week_window_membership
    """
    plant, line, dealer = _ship_window_setup(api)
    order = make_order(dealer["id"], line["id"], 100, "2026-03-02")
    confirm_order(order["id"])
    set_clock("2026-03-09T00:00:00Z")
    resp = api.ship_shipment_order(order["id"], DSR)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_SHIP_WEEK)
    order_after = get_success_data(api.get_shipment_order(order["id"], DSR))
    assert order_after["status"] == "CONFIRMED"
