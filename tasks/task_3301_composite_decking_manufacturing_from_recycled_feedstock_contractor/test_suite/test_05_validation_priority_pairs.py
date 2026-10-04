"""Priority-pair validation conflicts: the earlier check in the PRD's fixed
validation cascade determines the reported error."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_active_formulation,
    make_dealer,
    create_feedstock_lot_payload,
    make_order,
    make_plant,
    make_price_book,
    make_product_line,
    make_supplier,
    set_clock,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

QE = TEST_USERS["quality_engineer_headers"]
DSR = TEST_USERS["dealer_sales_rep_headers"]


def test_state_error_wins_over_lab_limits_on_release(api):
    """PRD §2.5: "Fifth, the target resource must be in a state that permits
    the requested transition, otherwise the request fails with
    `ERR_INVALID_STATE`. Only after these generic gates do business-specific
    checks run — feedstock lab limits, capacity, resin sufficiency,
    formulation balance, dealer credit, finished-goods availability, temporal
    windows, idempotence guards, product-line sellability, certification
    gates, ownership, and lab verdict gates"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_lot_release
    """
    set_clock("2026-03-01T00:00:00Z")
    make_plant()
    supplier = make_supplier()
    payload = create_feedstock_lot_payload(
        supplier_id=supplier["id"], material="PCR_FILM", weight_lbs=100,
        received_date="2026-03-01", moisture_pct=1.0, contamination_ppm=3000,
        melt_flow_index=0.7,
    )
    lot = get_success_data(api.create_feedstock_lot(payload, QE))
    get_success_data(api.reject_feedstock_lot(lot["id"], QE))
    # The lot is REJECTED (state gate) AND breaches the contamination cap
    # (business-safety gate): the state gate runs first.
    resp = api.release_feedstock_lot(lot["id"], {"release_disposition": "PRODUCTION"}, QE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_lab_limit_error_when_state_gate_passes(api):
    """PRD §3.2: "`PCR_FILM`: `contamination_ppm` must be at most 2000, and
    `melt_flow_index` must lie in the inclusive range 0.3 to 1.2."
    PRD §3.2: "a breach of any applicable limit is rejected with
    `ERR_LOT_LIMIT_EXCEEDED` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_lot_release
    """
    set_clock("2026-03-01T00:00:00Z")
    make_plant()
    supplier = make_supplier()
    payload = create_feedstock_lot_payload(
        supplier_id=supplier["id"], material="PCR_FILM", weight_lbs=100,
        received_date="2026-03-01", moisture_pct=1.0, contamination_ppm=3000,
        melt_flow_index=0.7,
    )
    lot = get_success_data(api.create_feedstock_lot(payload, QE))
    # QUARANTINE lot breaching the contamination cap: only the business-safety
    # gate can fail here, so the lab-limit error surfaces.
    resp = api.release_feedstock_lot(lot["id"], {"release_disposition": "PRODUCTION"}, QE)
    validate_error(resp, ApiErrorId.ERR_LOT_LIMIT_EXCEEDED)
    lot_after = get_success_data(api.get_feedstock_lot(lot["id"], QE))
    assert lot_after["status"] == "QUARANTINE"


def test_credit_error_wins_over_fg_shortfall_on_confirm(api):
    """PRD §3.6: "Confirmation, performed by a `DealerSalesRep`, runs three
    gates in this order. First, the dealer must be `ACTIVE"
    PRD §3.6: "Second, credit headroom: the dealer's `outstanding_cents` plus
    the projected invoice for this order must be strictly less than
    `credit_limit_cents` — equality with the limit is a rejection, not an
    acceptance — with breaches reported as `ERR_CREDIT_LIMIT` (HTTP 409).
    The projection uses the provisional invoicing variant"
    PRD §3.6: "Third, finished-goods availability: the line's `fg_store` minus
    the sum of footage over confirmed-but-unshipped orders for that line must
    be at least the order's `lf`"

    Design: Difficulty/priority_pair_validation_conflict/constraint_vs_referential_on_order_confirm
    """
    set_clock("2026-03-01T00:00:00Z")
    make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"])
    make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer(credit_limit_cents=50000)
    # fg_store nets to 0 AND projected invoice 200*500=100000 >= 50000 limit:
    # the credit gate (second) runs before the finished-goods gate (third).
    order = make_order(dealer["id"], line["id"], 200, "2026-03-02")
    resp = api.confirm_shipment_order(order["id"], DSR)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT)
    order_after = get_success_data(api.get_shipment_order(order["id"], DSR))
    assert order_after["status"] == "REQUESTED"


def test_fg_shortfall_error_when_credit_gate_passes(api):
    """PRD §3.6: "Third, finished-goods availability: the line's `fg_store`
    minus the sum of footage over confirmed-but-unshipped orders for that line
    must be at least the order's `lf`; the boundary is inclusive, so a net
    position exactly equal to the order size is confirmable, and anything
    short is rejected with `ERR_FG_SHORTFALL` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/constraint_vs_referential_on_order_confirm
    """
    set_clock("2026-03-01T00:00:00Z")
    make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"])
    make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer(credit_limit_cents=100000000)
    # Credit passes; fg_store is 0 against a 200-lf order.
    order = make_order(dealer["id"], line["id"], 200, "2026-03-02")
    resp = api.confirm_shipment_order(order["id"], DSR)
    validate_error(resp, ApiErrorId.ERR_FG_SHORTFALL)
    order_after = get_success_data(api.get_shipment_order(order["id"], DSR))
    assert order_after["status"] == "REQUESTED"
