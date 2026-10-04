"""Difficulty queue A — compensating_invariant: the reverse move restores exactly."""
from test_helpers import (
    ApiErrorId,
    advance_order,
    api_client,
    book_payment,
    collect_payment,
    confirm_order,
    create_delivered_order,
    create_order,
    get_account,
    get_order,
    get_route,
    list_charges,
    order_line,
    position_for,
    reverse_payment,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_error,
    validate_success,
)


def test_cancelling_a_confirmed_order_releases_every_reserved_unit(api):
    """PRD §3.4: "Cancellation is allowed from `DRAFT` or `CONFIRMED` and releases the
    reservation: each line's `reserved_qty` is decremented by the line quantity and the route's
    `inventory_at_risk_cents` and `over_pledge_cents` are recomputed."
    PRD §3.4: "Cancellation is pure compensation —
    no account principal was written while the order was merely confirmed, so no ledger entry needs
    reversing."

    Design: Difficulty/compensating_invariant/compensating_reserved_units_return_to_zero_after_cancel
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_order(store["franchisee"], store["route"], people["technician"],
                         account, [order_line(product, 4)], mix_profile="POWER_TOOLS")

    position = position_for(store["franchisee"], store["route"]["id"], product["id"])
    assert position["reserved_qty"] == 0
    assert get_route(store["route"]["id"])["inventory_at_risk_cents"] == 0

    confirm_order(store["franchisee"], order, order["version"])
    reserved = position_for(store["franchisee"], store["route"]["id"], product["id"])
    assert reserved["reserved_qty"] == 4
    assert get_route(store["route"]["id"])["inventory_at_risk_cents"] == 48000

    cancelled = validate_success(advance_order(store["franchisee"], order,
                                               "CANCEL"))
    assert cancelled["order_status"] == "CANCELLED"

    released = position_for(store["franchisee"], store["route"]["id"], product["id"])
    assert released["reserved_qty"] == 0, "the compensating transition removed exactly 4 units"
    assert released["remaining_qty"] == released["on_hand_qty"] == 10
    final_route = get_route(store["route"]["id"])
    assert final_route["inventory_at_risk_cents"] == 0
    assert final_route["over_pledge_cents"] == 0
    assert get_account(account["id"])["principal_balance_cents"] == 0


def test_reversing_a_collected_payment_restores_the_ledger_exactly(api):
    """PRD §3.5: "A `CreditOfficer` may reverse a `COLLECTED` payment, which un-credits every finance
    charge the payment had credited, returning each charge's `collection_applied_cents` by the amount it
    received and restoring any charge whose `collection_applied_cents` returns to zero to `OPEN` status
    with its `charge_resolved_iso_week` cleared"
    PRD §3.5: "the amount applied to charges plus the amount that reduced
    principal equals the payment's `amount_cents`, with no residue."

    Design: Difficulty/compensating_invariant/compensating_payment_reversal_restores_account_ledger_exactly
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    create_delivered_order(store["franchisee"], store["route"], people["technician"],
                           account, [order_line(product, 3)],
                           mix_profile="DIAGNOSTIC_WEIGHTED")

    set_clock("2026-09-14T00:00:00Z")
    before = get_account(account["id"])
    assert before["accrued_finance_charge_cents"] == 136
    assert before["principal_balance_cents"] == 45338
    assert before["credit_available_cents"] == 4526

    payment = book_payment(store["franchisee"], account, "2026-09-14T00:00:00Z")
    collected = validate_success(collect_payment(store["franchisee"], account,
                                                 payment))
    assert collected["charge_applied_cents"] == 136

    after_collect = get_account(account["id"])
    assert after_collect["principal_balance_cents"] == 25474
    assert after_collect["credit_available_cents"] == 24526
    assert after_collect["accrued_finance_charge_cents"] == 0

    reversed_payment = validate_success(reverse_payment(account, payment))
    assert reversed_payment["payment_status"] == "REVERSED"

    restored = get_account(account["id"])
    assert restored["principal_balance_cents"] == 45338
    assert restored["accrued_finance_charge_cents"] == 136
    assert restored["credit_available_cents"] == 4526
    assert restored["current_balance_cents"] == 45474

    charges = list_charges(account["id"])
    assert charges[0]["charge_status"] == "OPEN"
    assert charges[0]["collection_applied_cents"] == 0
