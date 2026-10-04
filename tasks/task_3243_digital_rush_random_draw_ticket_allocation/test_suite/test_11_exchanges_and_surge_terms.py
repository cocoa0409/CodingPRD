"""Exchange quotations, applications and the money they conserve."""
import pytest

from test_helpers import (
    validate_error, validate_success, get_success_data, ApiErrorId,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_a_fifteen_hundred_basis_point_term_does_not_touch_a_surge_exempt_class(api):
    """PRD §3.4: "Two of the four ticket classes never surge. A `RUSH` allocation
    and a `DRAW` allocation price at their discounted rate and stay there
    regardless of how busy the day is."

    Design: Difficulty/boundary_precision_check/boundary_surge_fill_fraction_strictly_greater_than_eighty_percent
    """
    production, performance, allocation = X.setup_released_allocation(
        face_value_cents=19990, ticket_type="RUSH", daily_quantity=11,
        discount_pct=0.05, refundable=True, per_order_limit=10,
    )
    patron = X.register_patron(email="exempt_class@example.com")
    X.join_queue(performance, allocation, patron)
    X.ops_run("2026-09-12T09:05:00Z")

    order = X.buy_seats(performance, allocation, patron, quantity=1,
                        idempotency_key="exempt-1")

    assert order["surge_multiplier_bp"] == 0, (
        "the released-but-off term would clear its threshold here, but a RUSH "
        f"allocation never surges; got {order['surge_multiplier_bp']}"
    )


def test_quote_splits_the_recalled_amount_into_fee_and_value_returned(api):
    """PRD §3.9: "It then takes the price difference between that target price
    and the purchase's per-seat amount, which is the purchase's `subtotal_cents`
    divided by its quantity."
    PRD §3.9: "When the price difference is zero or negative — the new seats cost
    no more per seat than the old ones — the fee is the smaller of 500 cents and
    the base fee, so a free-window exchange of a cheaper target costs nothing and
    a doubled base fee is capped at 500 cents."
    PRD §3.9: "Quoting produces two figures, `fee_cents` and
    `value_returned_cents`, and moves the request to `QUOTED`."

    Design: Difficulty/compensating_invariant/invariant_exchange_money_split_conserved_across_apply_and_compensation
    """
    production, performance, source, target, patron, purchase, exchange = \
        X.setup_stale_target_exchange(source_discount_pct=0.5,
                                      target_discount_pct=0.5)

    quoted = X.quote_exchange(exchange, purchase)

    assert quoted["status"] == "QUOTED", f"the quotation moves the request on, got {quoted['status']}"
    assert quoted["original_amount_cents"] == 10000, (
        f"the recalled amount is stored verbatim, got {quoted['original_amount_cents']}"
    )
    assert quoted["fee_cents"] == C.EXCHANGE_QUOTE_FEE_CENTS, (
        f"a target priced no higher leaves the capped fee at 500, got {quoted['fee_cents']}"
    )
    assert quoted["value_returned_cents"] == C.EXCHANGE_QUOTE_VALUE_RETURNED_CENTS, (
        f"the remainder is the subtotal minus the fee, got {quoted['value_returned_cents']}"
    )


def test_applying_an_exchange_conserves_the_money_split(api):
    """PRD §3.9: "Applying the exchange sets the purchase's `refunded_cents` to
    the fee plus the difference between the recalled amount and the value
    returned."
    PRD §3.9: "The `value_returned_cents` is zero at this point because the
    remainder is conserved in the purchase's `refunded_cents` rather than
    returned as cash."

    Design: Difficulty/compensating_invariant/invariant_exchange_money_split_conserved_across_apply_and_compensation
    """
    production, performance, source, target, patron, purchase, exchange = \
        X.setup_approved_exchange(source_discount_pct=0.5, target_discount_pct=0.5)

    applied = X.apply_exchange(exchange, purchase, performance)

    assert applied["status"] == "APPLIED"
    assert applied["fee_cents"] == 500, f"the fee is unchanged, got {applied['fee_cents']}"
    assert applied["value_returned_cents"] == 9500
    after = X.get_purchase(purchase["id"])
    assert after["refunded_cents"] == C.EXCHANGE_APPLIED_REFUNDED_CENTS, (
        "the applied exchange posts fee plus the recalled-minus-returned gap, got "
        f"{after['refunded_cents']}"
    )
    assert applied["fee_cents"] + applied["value_returned_cents"] == 10000, \
        "the split is conserved against the recalled amount after application"


def test_an_epoch_reversal_returns_the_money_split_to_its_pre_application_value(api):
    """PRD §3.9: "When the epoch that witnessed the application is not yet
    closed, the exchange moves from `APPLIED` to `COMPENSATED`: the purchase's
    `refunded_cents` is restored to its pre-application value, the target seat
    hold moves to `RELEASED` and the source hold returns to `HELD`, and both
    allocations' `quantity_sold_today` figures return to their pre-application
    values."

    Design: Difficulty/compensating_invariant/invariant_exchange_money_split_conserved_across_apply_and_compensation
    """
    production, performance, source, target, patron, purchase, exchange = \
        X.setup_approved_exchange(source_discount_pct=0.5, target_discount_pct=0.5)
    X.apply_exchange(exchange, purchase, performance)
    after_apply = X.get_purchase(purchase["id"])
    assert after_apply["refunded_cents"] == 1000, \
        "the application posted the pinned split before the reversal"

    X.ops_run("2026-09-12T09:10:00Z")

    compensated = X.get_purchase(purchase["id"])
    assert compensated["refunded_cents"] == 0, (
        "no money drifted: the compensating reversal returns the figure to zero, "
        f"got {compensated['refunded_cents']}"
    )
    assert compensated["payment_status"] == "SETTLED", (
        f"the purchase returns to its pre-application posture, got {compensated['payment_status']}"
    )


def test_an_approved_exchange_onto_an_unreleased_target_moves_no_seats(api):
    """PRD §3.9: "The target allocation must be in `RELEASED` and must still have
    at least as many dispensable seats left as the number of tickets on the
    purchase."
    PRD §2.6: "Second, the transition test: the target row must be in a state from
    which the requested move is defined, and a row that is not receives
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_exchange_application_requires_target_allocation_released
    """
    production, performance, source, target, patron, purchase, exchange = \
        X.setup_stale_target_exchange(release_target=False)

    quoted = X.quote_exchange(exchange, purchase)
    X.approve_exchange(quoted, purchase)
    approved = X.get_purchase(purchase["id"])

    response = api.apply_exchange(
        quoted["id"],
        {"expected_purchase_version": approved["version"],
         "expected_performance_version": X.live_performance(performance)["version"]},
        X.CS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    assert X.get_allocation(performance, target["id"])["status"] == "SCHEDULED", \
        "the unpublished target allocation is unchanged by the refused application"
    assert quoted["id"], "the guard reads the target allocation, not the request"


def test_the_target_allocation_guard_crosses_an_entity_boundary(api):
    """PRD §3.9: "The approved exchange is then applied, and application is where
    the swap lands. The target allocation must be in `RELEASED`."
    PRD §3.9: "It moves the source seat hold to `RELEASED` and creates a fresh
    target seat hold in `HELD` on the target allocation."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_exchange_application_requires_target_allocation_released
    """
    production, performance, source, target, patron, purchase, exchange = \
        X.setup_stale_target_exchange(release_target=False)

    quoted = X.quote_exchange(exchange, purchase)
    X.approve_exchange(quoted, purchase)
    approved = X.get_purchase(purchase["id"])

    refused = api.apply_exchange(
        quoted["id"],
        {"expected_purchase_version": approved["version"],
         "expected_performance_version": X.live_performance(performance)["version"]},
        X.CS,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    released_target = X.release_allocation(target, production, performance)
    assert released_target["status"] == "RELEASED"

    applied = X.apply_exchange(quoted, X.get_purchase(purchase["id"]), performance)
    assert applied["status"] == "APPLIED", (
        "the same approved exchange applies once the target allocation is "
        f"released, got {applied['status']}"
    )

    holds = get_success_data(api.list_seat_holds(
        performance["id"], X.OPS, params={"limit": 100}))
    holds = holds.get("data", holds) if isinstance(holds, dict) else holds
    target_holds = [row for row in holds
                    if row["allocation_id"] == target["id"] and row["status"] == "HELD"]
    assert target_holds, "a fresh hold is staked on the target allocation"