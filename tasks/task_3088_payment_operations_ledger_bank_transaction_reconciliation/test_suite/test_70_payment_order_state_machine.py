"""Queue B (corner design), section ``state_machines``.

Initial state, declared transitions, invalid transitions and terminal-state
lockdown.
"""
import pytest

from test_helpers import (
    ANALYST,
    APPROVER,
    CONTROLLER,
    INITIATOR,
    api_client,
    create_order,
    dispatched_order_scenario,
    get_success_data,
    ledger_scenario,
    list_transactions,
    validate_error,
)


def test_settle_from_pending_approval_is_not_a_declared_transition():
    """PRD §3.5: "The state gate precedes all of these: releasing an order that
    is not at `PENDING_APPROVAL` yields `ERR_INVALID_TRANSITION` with HTTP 409."
    PRD §3.5: "Settlement moves the order `IN_FLIGHT` → `SETTLED`".

    Design: Corner/state_machines/settle_from_pending_approval_is_not_a_declared_transition
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=2_000)
    assert order["status"] == "PENDING_APPROVAL"

    res = api_client.settle_payment_order(order["id"], ANALYST)
    validate_error(res, "ERR_INVALID_TRANSITION")
    assert res.status_code == 409

    after = get_success_data(api_client.get_payment_order(order["id"], ANALYST))
    assert after["status"] == "PENDING_APPROVAL"
    assert after["settlement_status"] == "UNSETTLED"


def test_settle_from_pending_approval_books_no_legs():
    """PRD §3.5: "The state gate precedes all of these: releasing an order that
    is not at `PENDING_APPROVAL` yields `ERR_INVALID_TRANSITION` with HTTP 409."

    Design: Corner/state_machines/settle_from_pending_approval_is_not_a_declared_transition
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=2_000)
    api_client.settle_payment_order(order["id"], ANALYST)

    rows = list_transactions(scenario["ledger"]["id"])
    assert rows == [], f"a refused settle must not book legs, got {len(rows)}"


def test_dispatch_from_returned_is_locked_out_by_the_terminal_state():
    """PRD §3.5: "No transition in this lifecycle is idempotent. Settling an
    order that is already `SETTLED`, returning one that is already `RETURNED`,
    dispatching one that has already been dispatched, or approving one that is no
    longer `PENDING_APPROVAL` all return `ERR_INVALID_TRANSITION` with HTTP 409."

    Design: Corner/state_machines/dispatch_from_returned_is_locked_out_by_the_terminal_state
    """
    scenario = dispatched_order_scenario(rail="ACH", direction="CREDIT", amount_cents=2_000)
    in_flight = get_success_data(
        api_client.mark_payment_order_in_flight(scenario["order"]["id"], ANALYST))
    returned = get_success_data(api_client.return_payment_order(
        in_flight["id"], {"return_reason": "R05",
                          "expected_payment_order_version": in_flight["version"]}, ANALYST))
    assert returned["status"] == "RETURNED"

    res = api_client.dispatch_payment_order(
        returned["id"], {"expected_payment_order_version": returned["version"]}, APPROVER)
    validate_error(res, "ERR_INVALID_TRANSITION")
    assert res.status_code == 409

    after = get_success_data(api_client.get_payment_order(returned["id"], ANALYST))
    assert after["status"] == "RETURNED"
    assert after["return_reason"] == "R05"


def test_the_returned_order_keeps_its_compensating_legs_intact():
    """PRD §3.5: "For every `ORIGINATING` or `FEE` leg of the order that is
    still `IN_SETTLEMENT`, a compensating `RETURN` `Transaction` is created in
    the same ledger".

    Design: Corner/state_machines/dispatch_from_returned_is_locked_out_by_the_terminal_state
    """
    scenario = dispatched_order_scenario(rail="ACH", direction="CREDIT", amount_cents=2_000)
    in_flight = get_success_data(
        api_client.mark_payment_order_in_flight(scenario["order"]["id"], ANALYST))
    returned = get_success_data(api_client.return_payment_order(
        in_flight["id"], {"return_reason": "R05",
                          "expected_payment_order_version": in_flight["version"]}, ANALYST))
    before = len(list_transactions(scenario["ledger"]["id"], entry_type="RETURN"))

    api_client.dispatch_payment_order(
        returned["id"], {"expected_payment_order_version": returned["version"]}, APPROVER)
    after = len(list_transactions(scenario["ledger"]["id"], entry_type="RETURN"))
    assert after == before, "the locked-out call must produce no side effect"


def test_payment_order_is_born_pending_approval_and_unsettled():
    """PRD §3.1: "The order is created in the `PENDING_APPROVAL` state with its
    settlement axis at `UNSETTLED`, its `initiator_user_id` taken from the
    caller's `X-User-ID`, and its `approver_user_id` left null."

    Design: Corner/state_machines/payment_order_is_born_pending_approval_and_unsettled
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=750)
    assert order["status"] == "PENDING_APPROVAL"
    assert order["settlement_status"] == "UNSETTLED"
    assert order["approver_user_id"] is None
    assert order["initiator_user_id"] == INITIATOR["X-User-ID"]


def test_nothing_is_booked_until_dispatch():
    """PRD §3.1: "An audit event recording the action `payment_order.created` is
    appended when the draft is accepted".
    PRD §2.4: "`pending_balance_cents` is the signed sum of `net_effect_cents`
    over every transaction in the ledger".

    Design: Corner/state_machines/payment_order_is_born_pending_approval_and_unsettled
    """
    scenario = ledger_scenario()
    create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=750)
    ledger = get_success_data(api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))
    assert ledger["pending_balance_cents"] == 0


def test_cancelling_an_already_cancelled_order_is_rejected():
    """PRD §3.5: "No transition in this lifecycle is idempotent."
    PRD §3.5: "A `PaymentInitiator` may cancel an order that is still at
    `PENDING_APPROVAL`, and only when the caller's `X-User-ID` equals the
    order's `initiator_user_id`".
    PRD §3.5: "Once the order is in one of its four terminal statuses the attempt
    is reported as `ERR_ALREADY_TERMINAL` with HTTP 409."

    Design: Corner/state_machines/cancelling_an_already_cancelled_order_is_rejected
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=900)
    cancelled = get_success_data(api_client.cancel_payment_order(order["id"], INITIATOR))
    assert cancelled["status"] == "CANCELLED"

    res = api_client.cancel_payment_order(order["id"], INITIATOR)
    assert res.status_code == 409
    error = res.json()["data"]["error_id"]
    assert error in ("ERR_INVALID_TRANSITION", "ERR_ALREADY_TERMINAL"), (
        f"a second cancel of a CANCELLED order must be refused, got {error}"
    )

    after = get_success_data(api_client.get_payment_order(order["id"], INITIATOR))
    assert after["status"] == "CANCELLED"


def test_the_cancel_cascade_does_not_re_fire_on_the_second_attempt():
    """PRD §3.5: "Cancellation is not a local edit: it moves the order to
    `CANCELLED`, moves the linked `Counterparty.status` to `RESTRICTED` so that
    the payee relationship is frozen pending operations review".

    Design: Corner/state_machines/cancelling_an_already_cancelled_order_is_rejected
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=900)
    api_client.cancel_payment_order(order["id"], INITIATOR)
    counterparty = get_success_data(
        api_client.get_counterparty(scenario["counterparty"]["id"], APPROVER))
    assert counterparty["status"] == "RESTRICTED"

    api_client.cancel_payment_order(order["id"], INITIATOR)
    after = get_success_data(
        api_client.get_counterparty(scenario["counterparty"]["id"], APPROVER))
    assert after["status"] == "RESTRICTED", (
        f"the cascade runs exactly once, got {after['status']}"
    )