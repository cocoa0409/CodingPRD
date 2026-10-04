"""Queue B (Corner/validations): lead-time boundary, case-pack multiples, the
fraud hold, cumulative return-quantity integrity, overpayment, write-off
timing, and the minimum-order boundary."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    active_brand,
    approve_return,
    delivered_order,
    first_line_id,
    get_success_data,
    make_brand_headers,
    make_retailer_headers,
    order_invoice,
    order_line,
    order_payload,
    place_order,
    raise_flag,
    read_order,
    receive_return,
    request_return,
    set_clock,
    shipped_invoice_scenario,
    validate_error,
    validate_success,
    verified_retailer_with_account,
)


def test_ship_before_lead_time_rejected(api):
    """PRD §3.5: "A brand ships one of its own orders — `X-User-ID` must equal
    the order's `brand_id` — moving it `PLACED → SHIPPED`, but only when the
    brand is `ACTIVE`, the purchasing retailer is `VERIFIED`, and the logical
    clock has reached at least the order's `created_at` plus the brand's
    `lead_time_days`; shipping too early fails with `ERR_LEAD_TIME_NOT_MET`
    (HTTP 422), and shipping while the brand is not active fails with
    `ERR_BRAND_SUSPENDED` (HTTP 422)."

    Design: Corner/validations/ship_before_lead_time_rejected
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=3, payout_delay_days=7)
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 1)])

    # At 2026-09-01 (order created_at), the 3-day lead time is not yet met.
    early = api.ship_order(order["id"], make_brand_headers(brand["id"]))
    validate_error(early, ApiErrorId.ERR_LEAD_TIME_NOT_MET, 422)

    # At exactly created_at + 3 days the shipment is allowed.
    set_clock(api, "2026-09-04T00:00:00Z")
    shipped = validate_success(api.ship_order(order["id"], make_brand_headers(brand["id"])))
    assert shipped["status"] == "SHIPPED"
    invoice = order_invoice(api, order["id"])
    assert invoice["due_date"] == "2026-11-03T00:00:00Z"


def test_case_pack_multiple_enforced(api):
    """PRD §3.4: "The case-pack check requires the brand to be `ACTIVE` and
    every line's `qty` to be a positive multiple of the brand's
    `default_case_pack_size`."

    Design: Corner/validations/case_pack_multiple_enforced
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, default_case_pack_size=6, lead_time_days=0)

    bad = api.create_order(
        order_payload(retailer["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 5000, "qty": 7}]),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(bad, ApiErrorId.ERR_CASE_PACK_VIOLATION, 422)

    good = api.create_order(
        order_payload(retailer["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 5000, "qty": 6}]),
        make_retailer_headers(retailer["id"]),
    )
    order = validate_success(good, 201)
    assert order["subtotal_cents"] == 30000


def test_fraud_hold_blocks_order_and_return(api):
    """PRD §3.4: "The fraud gate requires that the acting retailer have no
    fraud flag still in `OPEN` status and that the retailer's
    `verification_status` be `VERIFIED`; a retailer under an open flag, or one
    whose verification is incomplete, rejected, or suspended, is turned away
    with `ERR_FRAUD_HOLD` (HTTP 422)."
    PRD §3.7: "A new flag is `OPEN`, and while any flag remains `OPEN` the
    fraud gate of §3.4 and §3.6 blocks the retailer from placing orders or
    requesting returns."

    Design: Corner/validations/fraud_hold_blocks_order_and_return
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)
    flag = raise_flag(api, retailer["id"], "CONSUMER_RESELLER")

    blocked = api.create_order(
        order_payload(retailer["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 5000, "qty": 1}]),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_FRAUD_HOLD, 422)

    validate_success(api.dismiss_fraud_flag(flag["id"], ADMIN))
    allowed = api.create_order(
        order_payload(retailer["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 5000, "qty": 1}]),
        make_retailer_headers(retailer["id"]),
    )
    validate_success(allowed, 201)


def test_return_qty_exceeded_rejected(api):
    """PRD §3.6: "Receipt requires the authorization to be `APPROVED`, and it
    enforces return-quantity integrity: the cumulative received quantity per
    order line — across this and every earlier received authorization — must
    never exceed that line's `net_sold_qty`; an overrun is rejected with
    `ERR_RETURN_QTY_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/return_qty_exceeded_rejected
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)
    order = delivered_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 4)])
    line_id = first_line_id(api, order["id"])

    # Two authorizations, each approved before any receipt.
    ra1 = request_return(api, retailer["id"], order["id"], line_id, 3)
    approve_return(api, ra1["id"], brand["id"])
    ra2 = request_return(api, retailer["id"], order["id"], line_id, 2)
    approve_return(api, ra2["id"], brand["id"])

    # Receiving ra1 leaves one unit sold; ra2's two units overrun it.
    receive_return(api, ra1["id"])
    response = api.receive_return_authorization(ra2["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_RETURN_QTY_EXCEEDED, 422)

    assert get_success_data(api.get_return_authorization(ra2["id"], ADMIN))["status"] == (
        "APPROVED"
    )
    assert read_order(api, order["id"])["status"] == "PARTIALLY_RETURNED"


def test_overpayment_and_writeoff_too_early(api):
    """PRD §3.9: "Payment bounds are enforced strictly: the amount must be
    positive and must not exceed the invoice's current `balance_cents`; a
    non-positive or over-large amount is rejected with `ERR_OVERPAYMENT`
    (HTTP 422)."
    PRD §3.9: "An `OVERDUE` invoice that the retailer never cures may be
    written off by a `PlatformAdmin`, but only once the logical clock has
    reached at least thirty days past the `due_date`; an earlier attempt — or
    an attempt on an invoice that is not `OVERDUE` — fails with
    `ERR_WRITE_OFF_TOO_EARLY` (HTTP 422)."

    Design: Corner/validations/overpayment_and_writeoff_too_early
    """
    (retailer, _, brand, order, invoice, _
     ) = shipped_invoice_scenario(api, unit_price_cents=10000, qty=1)

    overpay = api.record_payment(invoice["id"], {"amount_cents": 10001},
                                 make_retailer_headers(retailer["id"]))
    validate_error(overpay, ApiErrorId.ERR_OVERPAYMENT, 422)

    # due_date is 2026-10-31; due+29d is too early, due+30d succeeds.
    set_clock(api, "2026-11-29T00:00:00Z")
    early = api.write_off_invoice(invoice["id"], ADMIN)
    validate_error(early, ApiErrorId.ERR_WRITE_OFF_TOO_EARLY, 422)

    set_clock(api, "2026-11-30T00:00:00Z")
    written = validate_success(api.write_off_invoice(invoice["id"], ADMIN))
    assert written["status"] == "WRITTEN_OFF"


def test_minimum_order_value_boundary(api):
    """PRD §3.4: "The minimum-order check requires the computed
    `subtotal_cents` to be at least the brand's `min_order_value_cents`."

    Design: Corner/state_machines/error_min_order_value_on_place
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, min_order_value_cents=50000, lead_time_days=0)

    below = api.create_order(
        order_payload(retailer["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 49999, "qty": 1}]),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(below, ApiErrorId.ERR_MIN_ORDER_VALUE, 422)

    exact = api.create_order(
        order_payload(retailer["id"], brand["id"],
                      [{"sku": "S2", "unit_price_cents": 50000, "qty": 1}]),
        make_retailer_headers(retailer["id"]),
    )
    validate_success(exact, 201)
