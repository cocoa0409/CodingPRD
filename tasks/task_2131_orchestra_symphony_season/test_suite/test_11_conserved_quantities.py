"""Seats and money as conserved quantities, before and after every compensating action."""

from test_helpers import (
    ARTISTIC_ADMIN,
    assert_patron_cash_identity,
    assert_seat_conservation,
    build_on_sale_world,
    create_patron,
    hold_tickets,
    inventory_for,
    pay_tickets,
    read_concert,
    read_patron,
    read_season,
    read_ticket_order,
    run_ops,
    validate_success,
)


def _thirty_seat_hold():
    world = build_on_sale_world()
    buyer = create_patron(full_name="Noel Vance", email="noel-hold30@patron.test")
    order = hold_tickets(world.concert["id"], buyer["id"], world.section["id"],
                         seat_count=30)
    return world, buyer, order


def _paid_pair_of_seats():
    world = build_on_sale_world()
    buyer = create_patron(full_name="Noel Vance", email="noel-cash@patron.test")
    order = hold_tickets(world.concert["id"], buyer["id"], world.section["id"],
                         seat_count=2)
    paid = pay_tickets(order["id"], use_credit=False)
    return world, buyer, paid


# --------------------------------------------------------------------------
# Seats
# --------------------------------------------------------------------------
def test_a_hold_dies_at_the_checkpoint_that_reaches_its_stamp(api):
    """PRD 2.13: "When a hold is created the system stamps it with
    `hold_expires_at_ops_run`, computed as the season's `ops_run_index` at that
    instant plus 2 — in other words, a hold survives the next checkpoint and dies
    at the one after it."
    PRD 2.13: "A held order becomes expired at the first checkpoint whose new epoch
    value has reached or passed that stamp."

    Design: Difficulty/compensating_invariant/seat_conservation_across_hold_and_ops_expiry
    """
    world, _, order = _thirty_seat_hold()
    assert order["hold_expires_at_ops_run"] == 2

    season = run_ops(world.season["id"])
    assert season["ops_run_index"] == 1
    assert read_ticket_order(order["id"])["status"] == "HELD", (
        "a hold survives the first checkpoint after it was taken"
    )

    season = run_ops(world.season["id"])
    assert season["ops_run_index"] == 2

    expired = read_ticket_order(order["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["amount_paid_cents"] == 0
    assert read_season(world.season["id"])["status"] == "SINGLE_ON_SALE", (
        "the checkpoint never changes the season's own status"
    )


def test_seats_are_conserved_across_the_hold_and_its_expiry(api):
    """PRD 2.9: "The conserved quantity that follows is simple and absolute: for
    every inventory element, `capacity` always equals `available_count` plus
    `held_count` plus `sold_count`. This identity must hold before and after every
    forward action — creating a package, holding a ticket, paying either — and
    again after every compensating action — a hold expiring, a payment being
    refunded, a package lapsing."
    PRD 2.9: "A concert additionally publishes two roll-ups: `seats_held_count` is
    the sum of `held_count` over all its inventory elements and `seats_sold_count`
    is the sum of `sold_count` over all of them."

    Design: Difficulty/compensating_invariant/seat_conservation_across_hold_and_ops_expiry
    """
    world, _, order = _thirty_seat_hold()

    during = read_concert(world.concert["id"])
    assert_seat_conservation(during)
    element = inventory_for(during, world.section["id"])
    assert (element["available_count"], element["held_count"], element["sold_count"]) == (
        70, 30, 0,
    )
    assert during["seats_held_count"] == 30

    run_ops(world.season["id"])
    run_ops(world.season["id"])

    after = read_concert(world.concert["id"])
    assert_seat_conservation(after)
    element = inventory_for(after, world.section["id"])
    assert (element["available_count"], element["held_count"], element["sold_count"]) == (
        100, 0, 0,
    )
    assert element["fill_bp"] == 0
    assert after["seats_held_count"] == 0
    assert read_ticket_order(order["id"])["status"] == "EXPIRED"


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------
def test_cancellation_refund_credits_the_patron_without_zeroing_the_order(api):
    """PRD 3.9: "Hop two, caused by hop one: each order entering `REFUNDED` adds its
    `amount_paid_cents` to its patron's `credit_balance_cents` — the order's own
    `amount_paid_cents` is deliberately left untouched, so the audit trail
    survives — and each order entering `EXPIRED` or `REFUNDED` releases its seats
    on the concert's inventory, an expiring hold coming off `held_count` and a
    refunded order coming off `sold_count`."
    PRD 2.10: "`amount_paid_cents` on a refunded order is left exactly as it was —
    the refund is recorded by the status change and the credit grant, not by
    zeroing the order."

    Design: Difficulty/compensating_invariant/patron_cash_conservation_across_payment_and_refund
    """
    world, buyer, paid = _paid_pair_of_seats()
    assert paid["quoted_unit_price_cents"] == 8100
    assert paid["amount_paid_cents"] == 16200
    assert paid["credit_applied_cents"] == 0

    validate_success(
        api.cancel_concert(world.concert["id"], "orchestra strike", ARTISTIC_ADMIN)
    )

    refunded = read_ticket_order(paid["id"])
    assert refunded["status"] == "REFUNDED"
    assert refunded["amount_paid_cents"] == 16200
    assert refunded["credit_applied_cents"] == 0
    assert read_patron(buyer["id"])["credit_balance_cents"] == 16200


def test_patron_cash_identity_survives_the_refund_with_zero_drift(api):
    """PRD 2.10: "The identity the system guarantees is this: for every patron,
    `lifetime_cash_in_cents` equals `credit_balance_cents`, plus the total
    `amount_paid_cents` across that patron's ticket orders in `PAID` status, plus
    the total `price_cents` across that patron's subscription packages in `ACTIVE`
    or `EXPIRED` status."
    PRD 2.10: "A refund moves an order out of `PAID` and adds exactly its
    `amount_paid_cents` to `credit_balance_cents`, so the two sides of the identity
    move by the same amount in opposite directions and the equality survives with
    zero drift."

    Design: Difficulty/compensating_invariant/patron_cash_conservation_across_payment_and_refund
    """
    world, buyer, paid = _paid_pair_of_seats()

    before = read_patron(buyer["id"])
    assert before["lifetime_cash_in_cents"] == 16200
    assert before["credit_balance_cents"] == 0
    assert_patron_cash_identity(before, [paid], [])

    validate_success(
        api.cancel_concert(world.concert["id"], "orchestra strike", ARTISTIC_ADMIN)
    )

    after = read_patron(buyer["id"])
    assert after["lifetime_cash_in_cents"] == 16200, "the conserved total never moves"
    assert after["credit_balance_cents"] == 16200
    assert_patron_cash_identity(after, [], [])

    concert = read_concert(world.concert["id"])
    assert_seat_conservation(concert)
    element = inventory_for(concert, world.section["id"])
    assert element["sold_count"] == 0
    assert element["available_count"] == 100
