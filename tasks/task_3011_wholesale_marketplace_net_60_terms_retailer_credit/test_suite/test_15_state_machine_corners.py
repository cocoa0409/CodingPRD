"""Queue B (Corner/state_machines): verification precondition, terminal invoice
lockdown, brand reinstatement, account close precondition, repeat cancel, and
flag dismissal."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    active_brand,
    confirm_flag,
    get_credit_account,
    make_retailer_headers,
    order_invoice,
    order_line,
    pay_invoice,
    place_order,
    raise_flag,
    raise_return_abuse_flags,
    read_brand,
    read_invoice,
    read_order,
    read_retailer,
    register_retailer,
    review_document,
    set_clock,
    ship_order,
    standard_market,
    validate_error,
    validate_success,
    verified_retailer_with_account,
)


def test_verify_rejected_when_documents_unconfirmed(api):
    """PRD §3.1: "Only when the overall verification is requested with an
    approving `decision` does the full check fire: the retailer must still be
    `PENDING`, and both `storefront_proof_status` and `resale_cert_status` must
    be `CONFIRMED`; an approval attempted while either document is unconfirmed
    is rejected with `ERR_VERIFICATION_INCOMPLETE` (HTTP 422)."

    Design: Corner/state_machines/verify_rejected_when_documents_unconfirmed
    """
    retailer = register_retailer(api)
    # Only the storefront proof is confirmed; the resale cert stays PENDING.
    review_document(api, retailer["id"], "STOREFRONT_PROOF", "CONFIRM")

    response = api.verify_retailer(retailer["id"], {"decision": "APPROVE"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_VERIFICATION_INCOMPLETE, 422)
    assert read_retailer(api, retailer["id"])["verification_status"] == "PENDING"


def test_terminal_invoice_rejects_payment(api):
    """PRD §3.9: "When the balance reaches zero the invoice flips to `PAID` —
    from `OPEN` or, if payment arrived late, from `OVERDUE`; the lateness of
    the settling payment is what the underwriting calculation of §3.3 later
    reads off `paid_at` versus `due_date`."
    PRD §3.9: "The retailer pays down an invoice by recording a payment as the
    `Retailer` role, supplying an `amount_cents`."

    Design: Corner/state_machines/terminal_invoice_rejects_payment
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 10000, 1)])
    ship_order(api, order["id"], brand["id"])
    invoice = order_invoice(api, order["id"])
    pay_invoice(api, invoice["id"], retailer["id"], 10000)
    assert read_invoice(api, invoice["id"])["status"] == "PAID"

    response = api.record_payment(invoice["id"], {"amount_cents": 1},
                                  make_retailer_headers(retailer["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert read_invoice(api, invoice["id"])["paid_amount_cents"] == 10000


def test_brand_reinstate_cycle(api):
    """PRD §3.2: "A brand that has been suspended through the return-abuse
    mechanism described in §3.7 sits in `SUSPENDED` until a `PlatformAdmin`
    reinstates it, returning it to `ACTIVE`; suspension is reversible precisely
    because remediation may follow."
    PRD §3.7: "the brand's `abuse_flags` increments by one and its
    `payout_balance_cents` is debited a flat 5,000 cents per assessment (a
    debit that may push the balance negative); when `abuse_flags` reaches 5, an
    `ACTIVE` brand auto-transitions to `SUSPENDED` and stays there until
    reinstated per §3.2."

    Design: Corner/state_machines/brand_reinstate_cycle
    """
    retailer, _, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "BRICK_AND_MORTAR"}
    )
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 1)])
    raise_return_abuse_flags(api, retailer["id"], order["id"], count=5)
    assert read_brand(api, brand["id"])["onboarding_status"] == "SUSPENDED"

    reinstated = validate_success(api.reinstate_brand(brand["id"], ADMIN))
    assert reinstated["onboarding_status"] == "ACTIVE"
    refreshed = read_brand(api, brand["id"])
    assert refreshed["abuse_flags"] == 5
    assert refreshed["payout_balance_cents"] == -25000


def test_credit_account_close_blocked_by_overdue_invoice(api):
    """PRD §3.3: "An account that will never be rehabilitated may instead be
    closed — but only from `FROZEN`, and only when no invoice belonging to any
    of this retailer's orders is currently `OVERDUE`; the `CLOSED` state is
    terminal."

    Design: Corner/state_machines/credit_account_close_blocked_by_overdue_invoice
    """
    retailer, account = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 10000, 1)])
    ship_order(api, order["id"], brand["id"])
    invoice = order_invoice(api, order["id"])

    flag = raise_flag(api, retailer["id"], "CONSUMER_RESELLER")
    confirm_flag(api, flag["id"])

    # Age the invoice past its due date so it is OVERDUE at close time.
    set_clock(api, "2026-11-05T00:00:00Z")
    assert read_invoice(api, invoice["id"])["status"] == "OVERDUE"

    response = api.close_credit_account(account["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_credit_account(api, account["id"])["status"] == "FROZEN"


def test_repeat_cancel_rejected_invalid_state(api):
    """PRD §3.4: "A retailer may cancel its own order while it is still
    `PLACED`, moving it `PLACED → CANCELLED`; cancellation after shipment is
    not possible through the retailer path."

    Design: Corner/state_machines/repeat_cancel_rejected_invalid_state
    """
    retailer, _, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "ONLINE"}
    )
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 1)])
    validate_success(api.cancel_order(order["id"], make_retailer_headers(retailer["id"])))

    response = api.cancel_order(order["id"], make_retailer_headers(retailer["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert read_order(api, order["id"])["status"] == "CANCELLED"


def test_fraud_flag_dismiss_fires_no_cascade(api):
    """PRD §3.7: "Dismissal moves the flag `OPEN → DISMISSED` with no further
    effect."

    Design: Corner/state_machines/fraud_flag_dismiss_fires_no_cascade
    """
    retailer, account, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "BRICK_AND_MORTAR"}
    )
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 1)])
    flag = raise_flag(api, retailer["id"], "STRAW_STOREFRONT", order["id"])

    dismissed = validate_success(api.dismiss_fraud_flag(flag["id"], ADMIN))
    assert dismissed["status"] == "DISMISSED"
    assert read_retailer(api, retailer["id"])["verification_status"] == "VERIFIED"
    assert get_credit_account(api, account["id"])["status"] == "ACTIVE"
    assert read_order(api, order["id"])["status"] == "PLACED"
