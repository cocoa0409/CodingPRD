"""Corner coverage — numismatic order, subscription, and invoice state
machines (PRD §3.6, §3.7): the order's parallel payment/allocation dimensions
(double pay, double cancel), enrollment gates, the dunning cycle and its
attempt-count boundary, and invoice terminal-state lockdown."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_collector_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_numismatic_order,
    assert_order_derived_status,
    assert_subscription,
    assert_subscription_invoice,
    validate_created,
)
from test_helpers.factories import (
    billing_cycle_payload,
    create_subscription_payload,
    invoice_payment_payload,
    order_payment_payload,
)
from test_helpers.fixtures import (
    create_collector,
    get_subscription,
    pay_invoice,
    place_and_pay_order,
    place_order,
    set_clock,
    setup_billed_subscription,
    setup_dunning_subscription,
    setup_on_sale_product,
    setup_subscription,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_order_double_cancel_rejected(api):
    """PRD §3.6: "A collector may cancel an order that is `ALLOCATED` or
    `WAITLISTED`; cancelling one already `RELEASED` is rejected with
    `ERR_ORDER_NOT_CANCELLABLE` (422). Cancellation flips `allocation_status`
    to `RELEASED` — and therefore the derived status to `CANCELLED` — refunds a
    `PAID` order to `REFUNDED`, and, for an order that held allocated units,
    returns its quantity to the product's `remaining_units`, reopening a
    `SOLD_OUT` product to `ON_SALE` when the count dips below the limit."

    Design: Corner/state_machines/order_double_cancel_rejected
    """
    product = setup_on_sale_product(api, product_code="DBL-1",
                                    product_family="F1", price_cents=2000,
                                    mintage_limit=100, household_order_limit=10)
    collector = create_collector(api, full_name="Cancel Twice",
                                 email="dc@example.com", household_id="HH-1")
    order = place_order(api, product["id"], collector, 1)
    assert order["allocation_status"] == "ALLOCATED"

    cancelled = validate_success(
        api.cancel_order(order["id"], make_collector_headers(collector["id"])))
    assert_numismatic_order(cancelled)
    assert_order_derived_status(cancelled)
    assert cancelled["allocation_status"] == "RELEASED"
    assert cancelled["status"] == "CANCELLED"

    # The second cancel hits a RELEASED order: rejected, no further mutation.
    resp = api.cancel_order(order["id"], make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)


def test_order_double_pay_rejected(api):
    """PRD §3.6: "Paying an order requires it to be `UNPAID` and `ALLOCATED` —
    a `WAITLISTED` or `RELEASED` order, or one whose payment was already made
    or refunded, is rejected with `ERR_ORDER_NOT_PAYABLE` (422) — and the
    tendered `amount_cents` must equal the order's `total_cents` to the cent
    (`ERR_PAYMENT_AMOUNT_MISMATCH`, 422)."

    Design: Corner/state_machines/order_double_pay_rejected
    """
    product = setup_on_sale_product(api, product_code="PAY-2",
                                    product_family="F1", price_cents=2000,
                                    mintage_limit=100, household_order_limit=10)
    collector = create_collector(api, full_name="Double Pay",
                                 email="dp@example.com", household_id="HH-1")
    order = place_and_pay_order(api, product["id"], collector, 1)
    assert order["payment_status"] == "PAID"

    # Exact amount again — the payment-state gate fires, not the amount check.
    resp = api.pay_order(order["id"], order_payment_payload(2000),
                         make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAYABLE)


def test_subscription_cancel_from_dunning_succeeds(api):
    """PRD §3.7: "On a `PENDING` invoice, `SUCCEEDED` moves it to `PAID`;
    `FAILED` moves it to `FAILED`, and that first failed attempt drops the
    subscription from `ACTIVE` into `DUNNING`."
    PRD §3.7: "Collectors may cancel an `ACTIVE` or `DUNNING` subscription at
    any time, moving it to `CANCELLED`."

    Design: Corner/state_machines/subscription_cancel_from_dunning_succeeds
    """
    _, collector, subscription, invoice = setup_dunning_subscription(api)
    assert subscription["status"] == "DUNNING"
    assert invoice["status"] == "FAILED"

    cancelled = validate_success(api.cancel_subscription(
        subscription["id"], make_collector_headers(collector["id"])))
    assert_subscription(cancelled)
    assert cancelled["status"] == "CANCELLED", (
        "a manual cancel lands in CANCELLED, not CANCELLED_NONPAYMENT")


def test_subscription_billing_before_due_date_rejected(api):
    """PRD §3.7: "The request carries `expected_subscription_version` for
    optimistic concurrency (§2.6) and is gated twice: the subscription must be
    `ACTIVE` — running a cycle against a `DUNNING`, `CANCELLED`, or
    `CANCELLED_NONPAYMENT` subscription is rejected with
    `ERR_SUBSCRIPTION_NOT_ACTIVE` (422) — and the logical clock's date must
    have reached `next_billing_date`, with an early run rejected as
    `ERR_BILLING_NOT_DUE` (422)."

    Design: Corner/state_machines/subscription_billing_before_due_date_rejected
    """
    _, _, subscription, _ = setup_billed_subscription(api)
    # One cycle ran at the 2026-09-01 clock; next_billing_date advanced a
    # month while the clock stands still, so a second cycle is not due. The
    # OCC version is fresh, so the temporal gate is what fires.
    assert subscription["cycles_billed"] == 1

    resp = api.run_billing_cycle(
        subscription["id"], billing_cycle_payload(subscription["version"]),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_BILLING_NOT_DUE)
    assert get_subscription(api, subscription["id"])["cycles_billed"] == 1


def test_subscription_duplicate_active_rejected(api):
    """PRD §3.7: "One live subscription per pairing: if the collector already
    holds an `ACTIVE` or `DUNNING` subscription for the same product,
    enrollment is rejected with `ERR_DUPLICATE_SUBSCRIPTION` (409)."
    PRD §3.7: "The platform sets the subscription's `collector_id` from the
    caller's `X-User-ID`, creates it `ACTIVE` with `cycles_billed` at zero, and
    initializes `next_billing_date` to the current logical-clock date."

    Design: Corner/state_machines/subscription_duplicate_active_rejected
    """
    product, collector, subscription = setup_subscription(api)
    assert subscription["status"] == "ACTIVE"

    # A second live subscription for the same (collector, product) pairing —
    # even at a different frequency — is rejected.
    resp = api.create_subscription(
        create_subscription_payload(product_id=product["id"], units_per_cycle=1,
                                    frequency="QUARTERLY"),
        make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBSCRIPTION)

    # After cancellation the pairing is free again and re-enrollment succeeds.
    validate_success(api.cancel_subscription(
        subscription["id"], make_collector_headers(collector["id"])))
    renewed = validate_created(api.create_subscription(
        create_subscription_payload(product_id=product["id"], units_per_cycle=1,
                                    frequency="QUARTERLY"),
        make_collector_headers(collector["id"])))
    assert_subscription(renewed)
    assert renewed["status"] == "ACTIVE"


def test_subscription_non_eligible_product_rejected(api):
    """PRD §3.7: "Enrollment requires the `product_id` to resolve
    (`ERR_UNKNOWN_PRODUCT`, 422), the product to be in `ON_SALE` — any other
    state, `SOLD_OUT` included, is rejected with `ERR_PRODUCT_NOT_ORDERABLE`
    (422) — and `subscription_eligible` to be true
    (`ERR_SUBSCRIPTION_NOT_ELIGIBLE_PRODUCT`, 422)."
    PRD §3.6: "Each product carries a unique `product_code` (a collision is
    rejected with `ERR_PRODUCT_CODE_EXISTS`, 409), an optional `program_id`
    that must resolve to a real program when supplied (`ERR_UNKNOWN_PROGRAM`,
    422) and stays null for non-commemorative products, a `product_family`
    grouping releases on the calendar, a `product_type` of `PROOF_SET`,
    `COMMEMORATIVE`, `UNCIRCULATED`, or `SUBSCRIPTION_SERIES`, a strictly
    positive `price_cents`, a strictly positive `mintage_limit` bounding
    sellable units, a strictly positive `household_order_limit` bounding
    per-household accumulation, a scheduled `release_datetime`, and a
    `subscription_eligible` flag defaulting to false when omitted."

    Design: Corner/state_machines/subscription_non_eligible_product_rejected
    """
    # A plain PROOF_SET: subscription_eligible omitted, so it defaults to false.
    product = setup_on_sale_product(api, product_code="NO-SUB",
                                    product_family="F1", price_cents=2000,
                                    mintage_limit=100, household_order_limit=10)
    assert product["subscription_eligible"] is False
    collector = create_collector(api, full_name="Wanna Sub",
                                 email="ws@example.com", household_id="HH-1")

    resp = api.create_subscription(
        create_subscription_payload(product_id=product["id"], units_per_cycle=1,
                                    frequency="MONTHLY"),
        make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ELIGIBLE_PRODUCT)


def test_invoice_third_failed_attempt_writes_off(api):
    """PRD §3.7: "Every attempt, success or failure, increments the invoice's
    `attempts` by one. On a `PENDING` invoice, `SUCCEEDED` moves it to `PAID`;
    `FAILED` moves it to `FAILED`, and that first failed attempt drops the
    subscription from `ACTIVE` into `DUNNING`. On a `FAILED` invoice the same
    two outcomes apply so long as `attempts` is still below 3: `SUCCEEDED` pays
    the invoice and lifts the subscription back to `ACTIVE`, while `FAILED`
    leaves the invoice `FAILED` — a second failure while the subscription is
    already in `DUNNING` leaves it in `DUNNING` — and when the failed attempt
    being recorded is the third, the invoice is written off to `WRITTEN_OFF`
    and the subscription moves to `CANCELLED_NONPAYMENT`."

    Design: Corner/state_machines/invoice_third_failed_attempt_writes_off
    """
    _, collector, subscription, invoice = setup_billed_subscription(api)
    assert invoice["status"] == "PENDING"
    assert invoice["attempts"] == 0

    invoice = pay_invoice(api, invoice, collector, "FAILED")
    assert_subscription_invoice(invoice)
    assert invoice["status"] == "FAILED"
    assert invoice["attempts"] == 1
    assert get_subscription(api, subscription["id"])["status"] == "DUNNING"

    invoice = pay_invoice(api, invoice, collector, "FAILED")
    assert invoice["status"] == "FAILED"
    assert invoice["attempts"] == 2
    assert get_subscription(api, subscription["id"])["status"] == "DUNNING"

    invoice = pay_invoice(api, invoice, collector, "FAILED")
    assert_subscription_invoice(invoice)
    assert invoice["status"] == "WRITTEN_OFF"
    assert invoice["attempts"] == 3
    subscription = get_subscription(api, subscription["id"])
    assert subscription["status"] == "CANCELLED_NONPAYMENT"


def test_invoice_pay_after_paid_rejected(api):
    """PRD §3.7: "Paying a `PAID` or `WRITTEN_OFF` invoice, or attempting
    payment on a `FAILED` invoice already at 3 attempts, is rejected with
    `ERR_INVOICE_NOT_PAYABLE` (422)."
    PRD §3.7: "Every attempt, success or failure, increments the invoice's
    `attempts` by one."

    Design: Corner/state_machines/invoice_pay_after_paid_rejected
    """
    _, collector, subscription, invoice = setup_billed_subscription(api)
    invoice = pay_invoice(api, invoice, collector, "SUCCEEDED")
    assert invoice["status"] == "PAID"
    assert invoice["attempts"] == 1

    resp = api.pay_invoice(invoice["id"], invoice_payment_payload("SUCCEEDED"),
                           make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)

    # The rejected attempt records nothing: still PAID with a single attempt.
    invoices, _ = validate_paginated(
        api.list_subscription_invoices(subscription["id"], ADMIN))
    assert len(invoices) == 1
    assert invoices[0]["id"] == invoice["id"]
    assert invoices[0]["status"] == "PAID"
    assert invoices[0]["attempts"] == 1


def test_billing_cycle_on_cancelled_subscription_rejected(api):
    """PRD §3.7: "The request carries `expected_subscription_version` for
    optimistic concurrency (§2.6) and is gated twice: the subscription must be
    `ACTIVE` — running a cycle against a `DUNNING`, `CANCELLED`, or
    `CANCELLED_NONPAYMENT` subscription is rejected with
    `ERR_SUBSCRIPTION_NOT_ACTIVE` (422) — and the logical clock's date must
    have reached `next_billing_date`, with an early run rejected as
    `ERR_BILLING_NOT_DUE` (422)."

    Design: Corner/state_machines/billing_cycle_on_cancelled_subscription_rejected
    """
    _, collector, subscription = setup_subscription(api)
    cancelled = validate_success(api.cancel_subscription(
        subscription["id"], make_collector_headers(collector["id"])))
    assert cancelled["status"] == "CANCELLED"

    # The OCC version is fresh from the cancel response, so the ACTIVE-state
    # gate is what fires.
    resp = api.run_billing_cycle(
        subscription["id"], billing_cycle_payload(cancelled["version"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)
