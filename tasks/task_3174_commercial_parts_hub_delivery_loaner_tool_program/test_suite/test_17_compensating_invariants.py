"""Conserved quantities: the deposit position, the core pool and the balance position."""

from test_helpers import (
    create_replenishment_satellite,
    advance_order_to_delivered,
    api_client,
    checkout_loan,
    close_loan,
    confirm_order,
    create_account,
    create_part,
    create_satellite,
    create_tool,
    forfeit_loan,
    get_success_data,
    inspect_loan,
    line_item,
    reload_account,
    reload_inventory,
    reload_order,
    reload_store,
    request_loan,
    return_desk_stop,
    return_loan,
    set_clock,
    stock,
    write_order,
)


def test_closing_a_loan_conserves_the_stores_deposit_position(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §2.11: "Whatever path is taken, the pair (`petty_cash_cents`,
    `deposit_liability_cents`) moves together so the store's conserved deposit
    position is untouched."

    Design: Difficulty/compensating_invariant/loan_close_conserves_petty_cash_minus_deposit_liability
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Cons Co Satellite")
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    tool = create_tool(tool_sku="TOOL-CONS", tool_name="Cylinder Hone",
                       deposit_amount_cents=1330, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-cons", route_code="R-CONS")

    before = reload_account(account["id"])
    position_before = before["petty_cash_cents"] - before["deposit_liability_cents"]

    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=1330)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=1330)
    return_loan(loan["id"])
    inspect_loan(loan["id"], return_condition="GOOD")
    close_loan(loan["id"])

    after = reload_account(account["id"])
    position_after = after["petty_cash_cents"] - after["deposit_liability_cents"]

    assert position_before == position_after == 0, (
        "the conserved deposit position is the same integer before checkout and after close"
    )


def test_the_held_deposit_moves_cash_and_liability_together(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §2.11: "Money taken as a deposit is parked in the account's
    `petty_cash_cents`."
    PRD §2.6: "`deposit_liability_cents` is the sum over `ToolLoan`s with
    `deposit_state` `HELD` of each loan's `deposit_amount_cents` less its
    `deposit_forfeited_cents`."

    Design: Difficulty/compensating_invariant/loan_close_conserves_petty_cash_minus_deposit_liability
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Cons Co Satellite")
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    tool = create_tool(tool_sku="TOOL-CONS2", tool_name="Cylinder Hone Two",
                       deposit_amount_cents=1330, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=1330)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=1330)

    held = reload_account(account["id"])
    assert held["petty_cash_cents"] == 1330
    assert held["deposit_liability_cents"] == 1330
    assert held["petty_cash_cents"] - held["deposit_liability_cents"] == 0, (
        "the difference is already the final conserved value while the deposit is held"
    )


def test_the_closed_loan_leaves_no_open_residue(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §3.6: "Closing refunds the unearned deposit: `deposit_state` moves to
    `REFUNDED`, the account's `petty_cash_cents` is reduced by the deposit amount
    less the forfeited amount, `credit_exposure_cents` is recomputed, and the
    loan moves to `CLOSED`."

    Design: Difficulty/compensating_invariant/loan_close_conserves_petty_cash_minus_deposit_liability
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Cons Co Satellite")
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    tool = create_tool(tool_sku="TOOL-CONS3", tool_name="Cylinder Hone Three",
                       deposit_amount_cents=1330, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-cons3", route_code="R-CONS3")
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=1330)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=1330)
    return_loan(loan["id"])
    inspect_loan(loan["id"], return_condition="GOOD")
    closed = close_loan(loan["id"])

    final = reload_account(account["id"])
    assert final["petty_cash_cents"] == 0
    assert final["deposit_liability_cents"] == 0
    assert closed["deposit_state"] == "REFUNDED"
    assert closed["deposit_forfeited_cents"] == 0
    assert closed["status"] == "CLOSED"


def test_voiding_a_confirmed_order_zeroes_the_exposure(api, sales_rep_headers):
    """PRD §3.3: "Voiding a `CONFIRMED` order does more: `reserved_unit_count` is
    reset to 0"
    PRD §3.3: "Then the order moves to `VOID` and `credit_exposure_cents` is
    recomputed."

    Design: Difficulty/compensating_invariant/order_void_and_reissue_conserves_core_and_refundable_deposit
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Inv Satellite")
    machined = create_part(sku="MACHINED-1", list_price_cents=8000,
                           core_charge_cents=3000, line_code="BRK")
    used = create_part(sku="COREUSED-1", list_price_cents=4000,
                       core_charge_cents=500, line_code="BRK")
    stock(satellite["id"], machined["id"], 10)
    stock(satellite["id"], used["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    order = write_order(account["id"], [line_item(machined["id"], 1),
                                        line_item(used["id"], 1)])
    confirmed = confirm_order(order["id"], account["id"])
    assert confirmed["core_charge_total_cents"] == 3500
    assert confirmed["refundable_deposit_cents"] == 700

    get_success_data(api_client.void_order(confirmed["id"], {}, sales_rep_headers))

    assert reload_order(confirmed["id"])["status"] == "VOID"
    assert reload_account(account["id"])["credit_exposure_cents"] == 0, (
        "the void removed the order from the provisional exposure pool"
    )


def test_a_reissued_order_restores_the_core_pool_exactly(api, sales_rep_headers):
    """PRD §3.3: "The order's `core_charge_total_cents` is the sum over lines of
    the catalogue `core_charge_cents` of the line's part multiplied by the line
    quantity."
    PRD §3.3: "the order's total core charge scaled by a deposit fraction of 0.20
    and rounded half-up to the cent once at the order level"

    Design: Difficulty/compensating_invariant/order_void_and_reissue_conserves_core_and_refundable_deposit
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Inv Satellite")
    machined = create_part(sku="MACHINED-1", list_price_cents=8000,
                           core_charge_cents=3000, line_code="BRK")
    used = create_part(sku="COREUSED-1", list_price_cents=4000,
                       core_charge_cents=500, line_code="BRK")
    stock(satellite["id"], machined["id"], 10)
    used_inv = stock(satellite["id"], used["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    order = write_order(account["id"], [line_item(machined["id"], 1),
                                        line_item(used["id"], 1)])
    confirmed = confirm_order(order["id"], account["id"])
    committed_while_live = reload_store(satellite["id"])["committed_units_today"]
    reserved_while_live = reload_inventory(used_inv["id"])["reserved_units"]

    get_success_data(api_client.void_order(confirmed["id"], {}, sales_rep_headers))

    replacement = write_order(account["id"], [line_item(machined["id"], 1),
                                              line_item(used["id"], 1)])
    reissued = confirm_order(replacement["id"], account["id"])

    assert reissued["core_charge_total_cents"] == 3500
    assert reissued["refundable_deposit_cents"] == 700
    assert reload_store(satellite["id"])["committed_units_today"] == committed_while_live, (
        "the conserved core pool has no drift"
    )
    assert reload_inventory(used_inv["id"])["reserved_units"] == reserved_while_live


def test_a_second_order_on_the_same_account_proves_the_pool_is_not_double_counted(
        api, sales_rep_headers):
    """PRD §2.6: "It is the sum, over this account's `PartOrder`s in `DRAFT`,
    `CONFIRMED`, `ALLOCATED`, `PICKING`, or `DISPATCHED`, of each order's
    `parts_subtotal_cents`"

    Design: Difficulty/compensating_invariant/order_void_and_reissue_conserves_core_and_refundable_deposit
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Inv Satellite")
    machined = create_part(sku="MACHINED-1", list_price_cents=8000,
                           core_charge_cents=3000, line_code="BRK")
    used = create_part(sku="COREUSED-1", list_price_cents=4000,
                       core_charge_cents=500, line_code="BRK")
    stock(satellite["id"], machined["id"], 10)
    used_inv = stock(satellite["id"], used["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    order = write_order(account["id"], [line_item(machined["id"], 1),
                                        line_item(used["id"], 1)])
    confirmed = confirm_order(order["id"], account["id"])
    get_success_data(api_client.void_order(confirmed["id"], {}, sales_rep_headers))
    replacement = write_order(account["id"], [line_item(machined["id"], 1),
                                              line_item(used["id"], 1)])
    confirm_order(replacement["id"], account["id"])

    live = reload_order(replacement["id"])
    assert live["status"] == "CONFIRMED"
    assert reload_inventory(used_inv["id"])["reserved_units"] == 1, (
        "exactly one live order holds the core pool"
    )
    assert reload_store(satellite["id"])["committed_units_today"] == 2


def test_forfeiting_a_held_deposit_leaves_the_total_balance_position_unchanged(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §3.6: "When the account's `receivable_balance_cents` is above zero, the
    deposit is applied against that debt: `deposit_state` moves to
    `APPLIED_TO_BALANCE` and `receivable_balance_cents` is reduced by the deposit
    amount."

    Design: Difficulty/compensating_invariant/loan_forfeit_applies_held_deposit_to_the_outstanding_invoice
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Pos Satellite")
    machined = create_part(sku="MACHINED-1", list_price_cents=7420,
                           core_charge_cents=0, line_code="BRK")
    stock(satellite["id"], machined["id"], 5)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    advance_order_to_delivered(account["id"], [line_item(machined["id"], 1)],
                               driver_id="drv-pos", route_code="R-POS")

    tool = create_tool(tool_sku="TOOL-LOST", tool_name="Vacuum Gauge",
                       deposit_amount_cents=2000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-posdesk", route_code="R-POSD")
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=2000)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=2000)

    before = reload_account(account["id"])
    assert before["petty_cash_cents"] == 2000
    assert before["receivable_balance_cents"] == 7420

    return_loan(loan["id"])
    inspect_loan(loan["id"], return_condition="LOST")
    forfeited = forfeit_loan(loan["id"])

    after = reload_account(account["id"])

    # PRD 3.6: "the deposit is applied against that debt: `deposit_state` moves to
    # `APPLIED_TO_BALANCE` and `receivable_balance_cents` is reduced by the deposit
    # amount", and PRD 2.11: "When a deposit is forfeited against a live
    # receivable the money is applied to that balance rather than returned.
    # Whatever path is taken, the pair (`petty_cash_cents`,
    # `deposit_liability_cents`) moves together so the store's conserved deposit
    # position is untouched."  The held cash pays the invoice down, so the credit
    # the shop was owed is discharged instead of refunded.
    applied_debt = before["receivable_balance_cents"] - after["receivable_balance_cents"]
    assert applied_debt == 2000, (
        "the forfeited deposit is applied against the outstanding invoice"
    )
    assert after["petty_cash_cents"] == 0, "the held deposit was fully consumed"
    assert after["receivable_balance_cents"] == 5420
    assert forfeited["deposit_state"] == "APPLIED_TO_BALANCE"
    assert forfeited["deposit_forfeited_cents"] == 2000


def test_the_intermediate_observation_sees_the_deposit_parked_in_petty_cash(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §2.11: "Money taken as a deposit is parked in the account's
    `petty_cash_cents`."

    Design: Difficulty/compensating_invariant/loan_forfeit_applies_held_deposit_to_the_outstanding_invoice
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Pos Satellite")
    machined = create_part(sku="MACHINED-1", list_price_cents=7420,
                           core_charge_cents=0, line_code="BRK")
    stock(satellite["id"], machined["id"], 5)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    advance_order_to_delivered(account["id"], [line_item(machined["id"], 1)],
                               driver_id="drv-pos2", route_code="R-POS2")

    tool = create_tool(tool_sku="TOOL-LOST2", tool_name="Vacuum Gauge Two",
                       deposit_amount_cents=2000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=2000)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=2000)

    held = reload_account(account["id"])
    assert held["petty_cash_cents"] == 2000
    assert held["receivable_balance_cents"] == 7420


def test_forfeiture_consumes_the_held_deposit_and_reduces_the_receivable(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §3.6: "When the account's `receivable_balance_cents` is above zero, the
    deposit is applied against that debt: `deposit_state` moves to
    `APPLIED_TO_BALANCE` and `receivable_balance_cents` is reduced by the deposit
    amount."
    PRD §3.6: "Forfeiture sets `deposit_forfeited_cents` to the full
    `deposit_amount_cents`"

    Design: Difficulty/compensating_invariant/loan_forfeit_applies_held_deposit_to_the_outstanding_invoice
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Pos Satellite")
    machined = create_part(sku="MACHINED-1", list_price_cents=7420,
                           core_charge_cents=0, line_code="BRK")
    stock(satellite["id"], machined["id"], 5)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    advance_order_to_delivered(account["id"], [line_item(machined["id"], 1)],
                               driver_id="drv-pos3", route_code="R-POS3")

    tool = create_tool(tool_sku="TOOL-LOST3", tool_name="Vacuum Gauge Three",
                       deposit_amount_cents=2000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-posdesk3", route_code="R-POSD3")
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=2000)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=2000)
    return_loan(loan["id"])
    inspect_loan(loan["id"], return_condition="LOST")
    forfeited = forfeit_loan(loan["id"])

    after = reload_account(account["id"])
    assert after["petty_cash_cents"] == 0, "the held deposit was fully consumed"
    assert after["receivable_balance_cents"] == 5420, (
        "7420 minus the 2000-cent deposit applied against the outstanding invoice"
    )
    assert forfeited["deposit_forfeited_cents"] == 2000, (
        "no cash and no receivable leaked out of the account"
    )