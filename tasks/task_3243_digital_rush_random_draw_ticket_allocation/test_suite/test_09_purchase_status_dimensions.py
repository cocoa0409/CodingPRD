"""The three independent status dimensions on a purchase."""
import pytest

from test_helpers import validate_success
from test_helpers import constants as C
from test_helpers import fixtures as X


def _settle_and_read(api, purchase):
    return X.settle_purchase(purchase)


def test_settlement_moves_payment_without_moving_logistics(api):
    """PRD §3.9: "A `FinancialOps` operator moves a pending order to
    `AUTHORIZED` and then on to `SETTLED`, and the move out of `PENDING` requires
    that the order's `payment_status` is still `PENDING`, that its
    `logistics_status` is `AWAITING_HANDOFF` or `REVOKED`, and that the purchase's
    seat holds are still `HELD` at the moment of authorisation."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    production, performance, allocation, patron, purchase = \
        X.setup_parallel_dimension_purchase()

    settled = _settle_and_read(api, purchase)

    assert settled["payment_status"] == "SETTLED", (
        f"settlement must move the payment dimension, got {settled['payment_status']}"
    )
    assert settled["logistics_status"] == "AWAITING_HANDOFF", (
        "the fulfilment dimension must not move with payment, got "
        f"{settled['logistics_status']}"
    )


def test_delivery_moves_logistics_without_moving_payment(api):
    """PRD §3.10: "The push moves the `logistics_status` dimension from
    `AWAITING_HANDOFF` to `DELIVERED`, leaves the `handoff_status` at
    `NOT_REQUIRED` because a push market never requires verification, and
    advances the purchase's `version` by one. Nothing about the payment or
    handoff dimensions changes."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    production, performance, allocation, patron, purchase = \
        X.setup_parallel_dimension_purchase()
    settled = X.settle_purchase(purchase)

    delivered = X.deliver_purchase(settled)

    assert delivered["logistics_status"] == "DELIVERED", (
        f"the delivery must move the fulfilment dimension, got {delivered['logistics_status']}"
    )
    assert delivered["payment_status"] == "SETTLED", (
        "the payment dimension must be untouched by the delivery, got "
        f"{delivered['payment_status']}"
    )


def test_settling_the_refund_moves_payment_but_not_logistics(api):
    """PRD §3.9: "Settlement does four things at once: the request moves to
    `SETTLED`; the purchase's `refunded_cents` increases by the request's
    `refunded_amount_cents` and the purchase's `payment_status` moves to
    `REFUNDED`."
    PRD §3.5: "the `handoff_status` dimension starts at whatever the
    performance's market dictates rather than at a fixed value — `NOT_REQUIRED`
    when the market pushes to phones."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    production, performance, allocation, patron, purchase = \
        X.setup_parallel_dimension_purchase()
    settled = X.settle_purchase(purchase)
    delivered = X.deliver_purchase(settled)
    refund = X.open_refund(delivered, patron)
    X.approve_refund(refund, delivered)
    settling = X.get_purchase(purchase["id"])

    X.settle_refund(refund, settling)
    final = X.get_purchase(purchase["id"])

    assert final["payment_status"] == "REFUNDED", (
        f"the refund settlement moves payment to REFUNDED, got {final['payment_status']}"
    )
    assert final["logistics_status"] == "DELIVERED", (
        "the fulfilment dimension is unchanged by the refund, got "
        f"{final['logistics_status']}"
    )
    assert final["handoff_status"] == "NOT_REQUIRED", (
        "a push market never requires verification, got "
        f"{final['handoff_status']}"
    )


def test_the_three_dimensions_advance_on_separate_triggers(api):
    """PRD §3.9 / §3.10: "Note the coupling between the two dimensions: a
    successful handoff sets both the identity dimension to `VERIFIED` and the
    fulfilment dimension to `COLLECTED` in one act, which is the only place in
    the domain where those two dimensions move together."
    PRD §3.5: "The `payment_status` dimension starts at `PENDING`, the
    `logistics_status` dimension starts at `AWAITING_HANDOFF`."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    production, performance, allocation, patron, purchase = \
        X.setup_parallel_dimension_purchase()

    assert purchase["payment_status"] == "PENDING"
    assert purchase["logistics_status"] == "AWAITING_HANDOFF"
    assert purchase["handoff_status"] == "NOT_REQUIRED"

    settled = X.settle_purchase(purchase)
    assert settled["payment_status"] == "SETTLED"
    assert settled["logistics_status"] == "AWAITING_HANDOFF"
    assert settled["handoff_status"] == "NOT_REQUIRED"

    delivered = X.deliver_purchase(settled)
    assert delivered["payment_status"] == "SETTLED"
    assert delivered["logistics_status"] == "DELIVERED"
    assert delivered["version"] > settled["version"], \
        "each act on a purchase advances its version"


def test_a_handoff_couples_identity_and_fulfilment_dimensions(api):
    """PRD §3.10: "the purchase's `handoff_status` moves to `VERIFIED`, its
    `handoff_verified_at` is stamped with the instant of acceptance, its
    `logistics_status` moves to `COLLECTED`, the desk's `handoffs_today`
    increments by one, and both the purchase's and the desk's `version` advance
    by one."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    purchase, desk_code, patron = X.setup_concierge_purchase(quantity=2)

    assert purchase["handoff_status"] == "PENDING_CONCIERGE", \
        "a concierge market routes the purchase to a desk"
    assert purchase["handoff_token"], "a concierge purchase carries a token"

    verified = X.create_handoff(purchase, desk_code, purchase["handoff_token"])

    assert verified["handoff_status"] == "VERIFIED"
    assert verified["logistics_status"] == "COLLECTED"
    assert verified["handoff_verified_at"] is not None, \
        "the acceptance instant is stamped on the purchase"
    assert verified["payment_status"] == "SETTLED", \
        "the payment dimension is untouched by the handoff"