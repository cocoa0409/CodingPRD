"""Difficulty rule non_linear_state_machine (PRD §3.3, §3.6, §3.7): state
machines with cycles or parallel dimensions — the ProductionRun rework loop
that consumes a fresh blank reservation, the NumismaticOrder's two independent
dimensions (payment x allocation), and the Subscription dunning cycle driven
by invoice retry."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_collector_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_blank_conservation,
    assert_order_derived_status,
    assert_report_envelope,
    subscription_invoice_amount_cents,
)
from test_helpers.factories import order_payment_payload
from test_helpers.fixtures import (
    create_collector,
    create_run,
    get_order,
    get_subscription,
    inspect_run,
    pay_invoice,
    pay_order,
    place_order,
    setup_billed_subscription,
    setup_circulating_base,
    setup_on_sale_product,
    start_run,
)

FINANCE = TEST_USERS["finance_officer_headers"]


def test_production_run_rework_cycle_consumes_fresh_blanks(api):
    """PRD §3.3: "On `outcome=FAIL` the entire reservation is lost:
    `scrapped_pieces` grows by the reserved count, `reserved_blanks` zeroes out,
    `rework_count` increments by one, and the run returns to `REWORK`, from
    which a planner may start it again with a fresh reservation once stock and
    quality gates permit."
    PRD §3.3: "A reworked start consumes a fresh, full reservation from stock;
    pieces already scrapped stay scrapped."
    PRD §2.9: "Blank stock is reconciled as an invariant on every
    blank-affecting transition — lot receipt, run start, inspection resolution,
    and run cancellation."

    Design: Difficulty/non_linear_state_machine/production_run_rework_cycle_consumes_fresh_blanks
    """
    # QUARTER with 1760000 blanks delivered (10t lot); FY2026 order 100000.
    denomination, lot, fed_order = setup_circulating_base(
        api, quantity_ordered_pieces=100000)
    run = create_run(
        api, fed_order["id"], facility="DENVER", press_line="P7",
        planned_start="2026-10-06T08:00:00Z", planned_end="2026-10-06T12:00:00Z",
        planned_quantity=100000)
    start_run(api, run["id"])

    # STRIKING -> INSPECTION -> REWORK: all 100000 reserved pieces scrapped.
    run = inspect_run(api, run["id"], outcome="FAIL")
    assert run["status"] == "REWORK"
    assert run["rework_count"] == 1
    assert run["scrapped_pieces"] == 100000
    assert run["reserved_blanks"] == 0

    # REWORK -> STRIKING -> INSPECTION -> COMPLETED with a fresh reservation.
    start_run(api, run["id"])
    run = inspect_run(api, run["id"], outcome="PASS", good_pieces=99500)
    assert run["status"] == "COMPLETED"
    assert run["rework_count"] == 1
    assert run["produced_pieces"] == 99500
    assert run["scrapped_pieces"] == 100500  # 100000 + 500 across both strikes

    resp = api.get_report("seigniorage", FINANCE,
                          params={"denomination_code": "QUARTER"})
    report = validate_success(resp)
    assert_report_envelope(report, "seigniorage")
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    # 1760000 delivered - 200000 drawn across both strikes.
    assert row["blanks_on_hand_pieces"] == 1560000
    assert row["blanks_produced_pieces"] == 99500
    assert row["blanks_scrapped_pieces"] == 100500
    assert_blank_conservation(row)


def test_order_payment_and_allocation_dimensions_evolve_independently(api):
    """PRD §3.6: "Paying an order requires it to be `UNPAID` and `ALLOCATED` — a
    `WAITLISTED` or `RELEASED` order, or one whose payment was already made or
    refunded, is rejected with `ERR_ORDER_NOT_PAYABLE` (422) — and the tendered
    `amount_cents` must equal the order's `total_cents` to the cent
    (`ERR_PAYMENT_AMOUNT_MISMATCH`, 422)."
    PRD §3.6: "An order's `status` is never stored directly. It is derived from
    the two parallel dimensions the order actually carries: `CANCELLED` exactly
    when `allocation_status` is `RELEASED`; `COMPLETED` exactly when
    `payment_status` is `PAID` and `allocation_status` is `ALLOCATED`; and
    `ACTIVE` in every other combination."
    PRD §3.6: "Released units immediately trigger waitlist promotion: the
    platform scans the product's `WAITLISTED` orders oldest first by
    `created_at`, ties broken by server receipt order, under strict
    head-of-line blocking — the earliest waiting order is promoted to
    `ALLOCATED` if its `quantity` fits the remaining units, growing
    `allocated_units` and possibly closing the product at `SOLD_OUT` again, and
    the scan repeats with the new earliest; the moment the earliest waiting
    order does not fit, promotion stops and no later order is considered, even
    one that would fit."

    Design: Difficulty/non_linear_state_machine/order_payment_and_allocation_dimensions_evolve_independently
    """
    product = setup_on_sale_product(
        api, product_code="DIMS-1", product_family="DFAM", price_cents=2000,
        mintage_limit=10, household_order_limit=10)
    c1 = create_collector(api, full_name="Collector A", email="ca@example.com",
                          household_id="HH-A")
    c2 = create_collector(api, full_name="Collector B", email="cb@example.com",
                          household_id="HH-B")
    o1 = place_order(api, product["id"], c1, 2)
    assert o1["allocation_status"] == "ALLOCATED"
    o2 = place_order(api, product["id"], c2, 9)
    assert o2["allocation_status"] == "WAITLISTED"  # 2 + 9 > 10
    assert o2["payment_status"] == "UNPAID"

    # The WAITLISTED order is not payable even with the exact amount (18000).
    resp = api.pay_order(o2["id"], order_payment_payload(18000),
                         make_collector_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAYABLE)
    o2_mid = get_order(api, o2["id"])
    assert o2_mid["payment_status"] == "UNPAID"
    assert o2_mid["allocation_status"] == "WAITLISTED"
    assert o2_mid["status"] == "ACTIVE"

    o1 = pay_order(api, o1, c1)
    assert o1["payment_status"] == "PAID"
    assert o1["allocation_status"] == "ALLOCATED"
    assert o1["status"] == "COMPLETED"

    resp = api.cancel_order(o1["id"], make_collector_headers(c1["id"]))
    o1 = validate_success(resp)
    assert o1["payment_status"] == "REFUNDED"
    assert o1["allocation_status"] == "RELEASED"
    assert o1["status"] == "CANCELLED"

    # The released units promote o2 on the allocation dimension only; its
    # payment dimension stays UNPAID — the two evolve independently.
    o2_final = get_order(api, o2["id"])
    assert o2_final["allocation_status"] == "ALLOCATED"
    assert o2_final["payment_status"] == "UNPAID"
    assert o2_final["status"] == "ACTIVE"
    assert_order_derived_status(o2_final)


def test_subscription_dunning_cycle_recovers_to_active(api):
    """PRD §3.7: "Every attempt, success or failure, increments the invoice's
    `attempts` by one."
    PRD §3.7: "On a `PENDING` invoice, `SUCCEEDED` moves it to `PAID`; `FAILED`
    moves it to `FAILED`, and that first failed attempt drops the subscription
    from `ACTIVE` into `DUNNING`."
    PRD §3.7: "On a `FAILED` invoice the same two outcomes apply so long as
    `attempts` is still below 3: `SUCCEEDED` pays the invoice and lifts the
    subscription back to `ACTIVE`, while `FAILED` leaves the invoice `FAILED` —
    a second failure while the subscription is already in `DUNNING` leaves it in
    `DUNNING` — and when the failed attempt being recorded is the third, the
    invoice is written off to `WRITTEN_OFF` and the subscription moves to
    `CANCELLED_NONPAYMENT`."

    Design: Difficulty/non_linear_state_machine/subscription_dunning_cycle_recovers_to_active
    """
    product, collector, subscription, invoice = setup_billed_subscription(
        api, units_per_cycle=2, frequency="MONTHLY", price_cents=9995)
    assert invoice["amount_cents"] == subscription_invoice_amount_cents(9995, 2)
    assert invoice["status"] == "PENDING"
    assert invoice["attempts"] == 0

    # PENDING -> FAILED (attempt 1): the subscription drops into DUNNING.
    invoice = pay_invoice(api, invoice, collector, outcome="FAILED")
    assert invoice["status"] == "FAILED"
    assert invoice["attempts"] == 1
    subscription = get_subscription(api, subscription["id"])
    assert subscription["status"] == "DUNNING"

    # FAILED -> PAID (attempt 2): the subscription returns to ACTIVE.
    invoice = pay_invoice(api, invoice, collector, outcome="SUCCEEDED")
    assert invoice["status"] == "PAID"
    assert invoice["attempts"] == 2
    subscription = get_subscription(api, subscription["id"])
    assert subscription["status"] == "ACTIVE"
