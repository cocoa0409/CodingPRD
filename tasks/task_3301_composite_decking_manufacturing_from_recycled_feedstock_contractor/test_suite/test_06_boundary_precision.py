"""Boundary precision: the shortfall-penalty grace band and the inclusive
ship-week end."""
from test_helpers import (
    ApiErrorId,
    confirm_order,
    get_success_data,
    make_active_formulation,
    make_completed_run,
    make_dealer,
    make_delivered_order,
    make_order,
    make_plant,
    make_price_book,
    make_product_line,
    make_stocking_commitment,
    make_supplier,
    set_clock,
    ship_order,
    stock_resin,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

DSR = TEST_USERS["dealer_sales_rep_headers"]
CM = TEST_USERS["channel_manager_headers"]


def _base(api):
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"])
    make_price_book(base_prices={line["id"]: 500})
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=3000)
    make_completed_run(plant["id"], line["id"], 2000, "2026-03-01")
    return plant, line


def test_shortfall_grace_band_boundary_9000_included(api):
    """PRD §3.7: "a fill rate of at least 9000 basis points lands in the grace
    band and incurs a zero-cent penalty — the status is still
    `SHORTFALL_PENALIZED`, and the 9000-point boundary itself belongs to the
    grace band; a fill rate of at least 7000 but below 9000 basis points
    incurs 50 cents per unfulfilled linear foot; a fill rate below 7000 basis
    points incurs 150 cents per unfulfilled linear foot."

    Design: Difficulty/boundary_precision_check/shortfall_grace_band_boundary
    """
    plant, line = _base(api)
    dealer1 = make_dealer(name="Dealer One", territory_code="VA-N")
    dealer2 = make_dealer(name="Dealer Two", territory_code="VA-S")
    sc1 = make_stocking_commitment(dealer1["id"], "VA-N", line["id"], 1000, 2026)
    sc2 = make_stocking_commitment(dealer2["id"], "VA-S", line["id"], 1000, 2026)
    # D1 fulfills 900 (9000 bp, grace band boundary); D2 fulfills 899 (8990 bp).
    make_delivered_order(dealer1["id"], line["id"], 900, "2026-03-02", ship_date="2026-03-02")
    make_delivered_order(dealer2["id"], line["id"], 899, "2026-03-02", ship_date="2026-03-02")

    set_clock("2027-01-02T00:00:00Z")
    closed1 = get_success_data(api.close_stocking_commitment_season(sc1["id"], {}, CM))
    closed2 = get_success_data(api.close_stocking_commitment_season(sc2["id"], {}, CM))
    assert closed1["status"] == "SHORTFALL_PENALIZED"
    assert closed2["status"] == "SHORTFALL_PENALIZED"

    d1 = get_success_data(api.get_dealer(dealer1["id"], CM))
    d2 = get_success_data(api.get_dealer(dealer2["id"], CM))
    # D1: 900*500 = 450000 invoiced, penalty 0 (grace band).
    assert d1["outstanding_cents"] == 450000
    # D2: 899*500 = 449500 invoiced + 101 lf * 50 = 5050 penalty.
    assert d2["outstanding_cents"] == 449500 + 5050


def test_shortfall_mid_band_rate_applies(api):
    """PRD §3.7: "a fill rate of at least 7000 but below 9000 basis points
    incurs 50 cents per unfulfilled linear foot"

    Design: Difficulty/boundary_precision_check/shortfall_grace_band_boundary
    """
    plant, line = _base(api)
    dealer = make_dealer()
    sc = make_stocking_commitment(dealer["id"], "VA-N", line["id"], 1000, 2026)
    make_delivered_order(dealer["id"], line["id"], 800, "2026-03-02", ship_date="2026-03-02")
    set_clock("2027-01-02T00:00:00Z")
    closed = get_success_data(api.close_stocking_commitment_season(sc["id"], {}, CM))
    assert closed["status"] == "SHORTFALL_PENALIZED"
    d = get_success_data(api.get_dealer(dealer["id"], CM))
    # 800*500 = 400000 invoiced + 200 lf * 50 = 10000 penalty.
    assert d["outstanding_cents"] == 400000 + 10000


def test_exact_window_end_ship_date_inclusive(api):
    """PRD §3.6: "Shipping, performed by a `DealerSalesRep`, requires the
    logical clock date to fall within the confirmed ship week — the seven days
    from `ship_week_start` through six days after it, inclusive — and
    otherwise fails with `ERR_OUTSIDE_SHIP_WEEK` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/exact_window_end_ship_date
    """
    plant, line = _base(api)
    dealer = make_dealer()
    order_in = make_order(dealer["id"], line["id"], 200, "2026-03-02")
    confirm_order(order_in["id"])
    order_out = make_order(dealer["id"], line["id"], 200, "2026-03-02")
    confirm_order(order_out["id"])

    # 2026-03-08 is exactly 6 days after the Monday: inside the window.
    set_clock("2026-03-08T00:00:00Z")
    shipped = ship_order(order_in["id"])
    assert shipped["status"] == "SHIPPED"
    assert shipped["actual_ship_date"] == "2026-03-08"

    # 2026-03-09 is 7 days after the Monday: outside.
    set_clock("2026-03-09T00:00:00Z")
    resp = api.ship_shipment_order(order_out["id"], DSR)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_SHIP_WEEK)
    order_out_after = get_success_data(api.get_shipment_order(order_out["id"], DSR))
    assert order_out_after["status"] == "CONFIRMED"


def test_ship_week_start_day_is_inside_window(api):
    """PRD §3.6: "requires the logical clock date to fall within the confirmed
    ship week — the seven days from `ship_week_start` through six days after
    it, inclusive"

    Design: Difficulty/boundary_precision_check/exact_window_end_ship_date
    """
    plant, line = _base(api)
    dealer = make_dealer()
    order = make_order(dealer["id"], line["id"], 200, "2026-03-02")
    confirm_order(order["id"])
    set_clock("2026-03-02T00:00:00Z")
    shipped = ship_order(order["id"])
    assert shipped["status"] == "SHIPPED"
    assert shipped["actual_ship_date"] == "2026-03-02"
