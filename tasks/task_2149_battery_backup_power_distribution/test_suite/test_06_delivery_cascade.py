"""Delivery: the five-hop cascade and the two independent order dimensions."""
import pytest

from test_helpers import (
    TEST_USERS, setup_account_in_credit_hold, read_order, read_order_line,
    read_account, read_lot, read_shipment,
)

OPERATOR = TEST_USERS["warehouse_operator_headers"]


def test_delivered_order_advances_both_of_its_state_dimensions():
    """PRD §3.5: "**Hop two** drives the order's `fulfillment_status` from
    `SHIPPED` to `DELIVERED`, and that transition carries four effects of its
    own: the order's `credit_status` moves from `CLEARED` to `CLOSED`; every
    line is stamped with a `core_due_by` equal to the calendar date of the
    delivery instant plus 45 days, the window inside which promised cores must
    come back; every line's allocated lot has **both** its `quantity_reserved`
    and its `quantity_on_hand` decremented by that line's `allocated_quantity`,
    because the units have now physically left the building; and any service
    contract attached to that order standing in `ATTACHED` moves to `ACTIVE`, at
    which point coverage begins."
    PRD §3.3: "Both status fields are independent dimensions on the same row and
    they advance on different triggers"

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_advance_independently
    """
    env = setup_account_in_credit_hold()

    assert env["order_a"]["total_cents"] == 87331
    assert env["order_a"]["credit_status"] == "CLEARED", \
        "Order A cleared credit on its own submission"

    order_b = read_order(env["order_b"]["id"])
    assert order_b["fulfillment_status"] == "DELIVERED"
    assert order_b["credit_status"] == "CLOSED"
    assert order_b["total_cents"] == 444375, \
        f"Expected the certified total 444375, got {order_b['total_cents']}"


def test_sibling_order_moves_only_on_the_credit_dimension():
    """PRD §3.5: "**Hop five** reacts to that status change: every order
    belonging to that account whose `fulfillment_status` is `SUBMITTED` or
    `ALLOCATED` and whose `credit_status` is `CLEARED` moves its `credit_status`
    to `HELD`, which blocks those orders from being allocated until the hold is
    lifted."
    PRD §3.5: "**Hop four** reacts to that increase: if the account's
    core-deposit liability now stands at or above 500000 cents — five thousand
    dollars of outstanding core obligation — and the account's `status` is
    `ACTIVE`, the account moves to `CREDIT_HOLD`."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_advance_independently
    """
    env = setup_account_in_credit_hold()

    order_a = read_order(env["order_a"]["id"])
    assert order_a["fulfillment_status"] == "SUBMITTED", \
        "The hold never touches the fulfilment dimension"
    assert order_a["credit_status"] == "HELD"

    account = read_account(env["account"]["id"])
    assert account["status"] == "CREDIT_HOLD"
    assert account["core_deposit_balance_cents"] == 600000, \
        f"Expected 600000 of core liability, got {account['core_deposit_balance_cents']}"


def test_delivery_stamps_the_core_window_and_depletes_the_allocated_lot():
    """PRD §3.5: "**Hop one** writes the shipment's `delivered_at` from the
    logical clock and moves it `DISPATCHED → DELIVERED`."
    PRD §3.5: "every line is stamped with a `core_due_by` equal to the calendar
    date of the delivery instant plus 45 days, the window inside which promised
    cores must come back; every line's allocated lot has **both** its
    `quantity_reserved` and its `quantity_on_hand` decremented by that line's
    `allocated_quantity`, because the units have now physically left the
    building"

    Design: Difficulty/transitive_cascade/delivery_cascade_five_hops_to_sibling_order_credit_hold
    """
    env = setup_account_in_credit_hold()

    assert read_shipment(env["shipment_b"]["id"])["status"] == "DELIVERED"
    assert read_order(env["order_b"]["id"])["fulfillment_status"] == "DELIVERED"

    line = read_order_line(env["line_b"]["id"])
    assert str(line["core_due_by"]).startswith("2026-09-19"), \
        f"Delivery on 2026-08-05 plus 45 days is 2026-09-19, got {line['core_due_by']}"

    lot = read_lot(env["lot"]["id"])
    assert lot["quantity_on_hand"] == 38, \
        f"12 of 50 units have left the building, got {lot['quantity_on_hand']}"
    assert lot["quantity_reserved"] == 0


def test_delivery_books_the_core_liability_and_holds_the_account():
    """PRD §3.5: "**Hop three** books the core liability: the account's
    `core_deposit_balance_cents` increases by the sum over the order's lines of
    `core_expected_count` multiplied by that line's model `core_deposit_cents`."
    PRD §3.5: "Orders that have already reached `SHIPPED` or `DELIVERED` are not
    touched, and neither are orders whose credit dimension has already closed."

    Design: Difficulty/transitive_cascade/delivery_cascade_five_hops_to_sibling_order_credit_hold
    """
    env = setup_account_in_credit_hold()

    account = read_account(env["account"]["id"])
    assert account["core_deposit_balance_cents"] == 600000, \
        f"12 promised cores at 50000 cents book 600000, got {account['core_deposit_balance_cents']}"
    assert account["status"] == "CREDIT_HOLD"

    order_a = read_order(env["order_a"]["id"])
    assert order_a["credit_status"] == "HELD"
    assert order_a["fulfillment_status"] == "SUBMITTED"

    order_b = read_order(env["order_b"]["id"])
    assert order_b["credit_status"] == "CLOSED", \
        "The delivered order's own credit dimension closed rather than being held"
