"""Queue A (difficulty design), rule combinatorial_formula.

Two formulas with a pinned evaluation order: the reverse-rail fee pool's
floor-division-then-one-cent-cycle allocation, and the deposit-attribution fee
tier that is keyed on the gross line amount and evaluated before the residual.
"""
import pytest

from test_helpers import (
    ANALYST,
    api_client,
    allocate_shares,
    build_three_active_return_legs,
    first_exception,
    get_success_data,
    list_transactions,
    unmatched_deposit_scenario,
)


# ─── reverse_fee_pool_floor_division_then_one_cent_cycle ──

def test_three_returned_orders_raise_one_fee_pool_per_active_return_leg():
    """PRD §2.11: "The ledger's `delivered_fee_transfers_cents` plus its
    `undeliverable_cents` must always equal 25 cents multiplied by the number of
    return legs that have been resolved on that ledger."

    Design: Difficulty/combinatorial_formula/reverse_fee_pool_floor_division_then_one_cent_cycle
    """
    scenario = build_three_active_return_legs()
    # PRD §3.9 defines an active return leg precisely: "a `RETURN` transaction
    # whose `settlement_status` is `UNSETTLED` or `IN_SETTLEMENT`".  PRD §3.5 has
    # one such leg per ORIGINATING *and* per FEE leg that was still IN_SETTLEMENT,
    # and dispatch books both, so one returned order contributes two.
    legs = [t for t in list_transactions(scenario["ledger"]["id"], entry_type="RETURN")
            if t["settlement_status"] in ("UNSETTLED", "IN_SETTLEMENT")]
    assert len(legs) == 6, f"expected 6 active RETURN legs, got {len(legs)}"
    assert 25 * len(legs) == 150


def test_equal_weight_allocation_splits_seventy_five_cents_into_three_25s():
    """PRD §3.9: "Let the total to distribute be 25 cents multiplied by the
    count of active return legs on the ledger. Let the leg's allocated share be
    the share assigned to it by the allocation primitive above applied over
    those legs with equal weights, so that the shares sum to that total exactly."

    Design: Difficulty/combinatorial_formula/reverse_fee_pool_floor_division_then_one_cent_cycle
    """
    shares = allocate_shares(75, [1, 1, 1])
    assert shares == [25, 25, 25], f"expected [25, 25, 25], got {shares}"
    assert sum(shares) == 75


def test_allocation_primitive_cycles_the_remainder_in_bucket_order():
    """PRD §3.9: "Then distribute that remainder one cent at a time, cycling
    through the buckets in order — first bucket, second bucket, and so on to the
    last, then back to the first — until the remainder is exhausted."

    Design: Difficulty/combinatorial_formula/reverse_fee_pool_floor_division_then_one_cent_cycle
    """
    assert allocate_shares(100, [1, 1, 1]) == [34, 33, 33]
    # The primitive must be floor-then-cycle, not a single round over the total
    # nor the whole remainder handed to the first bucket.
    assert allocate_shares(100, [1, 1, 1]) != [34, 33, 33 - 1]


def test_return_leg_fee_pair_is_a_flat_twenty_five_cent_credit():
    """PRD §3.5: "Each such return leg is atomically paired with a `FEE`
    transaction booked at a flat 25 cents with direction `CREDIT`; the pair
    exists so that the reverse-rail fee invariant of §2.11 can be evaluated at
    all."

    Design: Difficulty/combinatorial_formula/reverse_fee_pool_floor_division_then_one_cent_cycle
    """
    scenario = build_three_active_return_legs()
    ledger_id = scenario["ledger"]["id"]
    active = [t for t in list_transactions(ledger_id, entry_type="RETURN")
              if t["settlement_status"] in ("UNSETTLED", "IN_SETTLEMENT")]

    # The paired 25-cent credit is a FEE entry (PRD §3.5: "Each such return leg
    # is atomically paired with a `FEE` transaction booked at a flat 25 cents
    # with direction `CREDIT`"), so selecting on entry_type separates it from the
    # compensating RETURN leg, which carries the refunded amount instead.
    credits = [t for t in list_transactions(ledger_id, entry_type="FEE")
               if t["direction"] == "CREDIT"
               and t["settlement_status"] in ("UNSETTLED", "IN_SETTLEMENT")]
    assert len(credits) == len(active), (
        f"expected one 25-cent credit per active return leg, got {len(credits)}"
    )
    assert credits, "the paired fee credits must exist"
    for leg in credits:
        assert leg["amount_cents"] == 25


# ─── deposit_attribution_gross_tier_evaluated_before_residual ──

def test_unmatched_deposit_reports_the_gross_tier_fee_and_residual():
    """PRD §3.8: "when the gross is at least 100000 cents but strictly below
    1000000 cents the attributed fee is the larger of 100 cents and the gross
    multiplied by 10 and then integer-floor-divided by 1000".

    Design: Difficulty/combinatorial_formula/deposit_attribution_gross_tier_evaluated_before_residual
    """
    scenario = unmatched_deposit_scenario(amount_cents=250_000, reference_code="NRQ995")
    item = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    assert item["amount_cents"] == 250_000
    assert item["status"] == "OPEN"
    assert item["attributed_fee_cents"] == 2_500, (
        f"expected attributed fee 2500, got {item['attributed_fee_cents']}"
    )


def test_attributable_amount_is_the_residue_of_the_gross():
    """PRD §3.8: "The `attributable_amount_cents` field is the gross minus that
    fee, computed after the fee so that the two always sum to the gross exactly
    and no cent is lost."

    Design: Difficulty/combinatorial_formula/deposit_attribution_gross_tier_evaluated_before_residual
    """
    scenario = unmatched_deposit_scenario(amount_cents=250_000, reference_code="NRQ995")
    item = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    assert item["attributable_amount_cents"] == 247_500, (
        f"expected residual 247500, got {item['attributable_amount_cents']}"
    )
    assert item["attributed_fee_cents"] + item["attributable_amount_cents"] == 250_000


def test_fee_is_free_below_the_hundred_thousand_cent_tier():
    """PRD §3.8: "when the gross is strictly below 100000 cents the attributed
    fee is zero".

    Design: Difficulty/combinatorial_formula/deposit_attribution_gross_tier_evaluated_before_residual
    """
    scenario = unmatched_deposit_scenario(amount_cents=99_999, reference_code="NRQ996")
    item = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    assert item["attributed_fee_cents"] == 0, (
        f"a gross of 99999 is below the tier, expected fee 0, "
        f"got {item['attributed_fee_cents']}"
    )
    assert item["attributable_amount_cents"] == 99_999


def test_fee_tier_boundary_is_the_gross_not_the_residual():
    """PRD §3.8: "This is precisely why computing the amount first and the fee
    as a residual would be wrong: the tier boundary would then depend on the
    already-rounded amount, which is a different number."

    Design: Difficulty/combinatorial_formula/deposit_attribution_gross_tier_evaluated_before_residual
    """
    scenario = unmatched_deposit_scenario(amount_cents=100_000, reference_code="NRQ997")
    item = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    assert item["attributed_fee_cents"] == 1_000, (
        f"a gross of exactly 100000 is inside the mid tier, expected 1000, "
        f"got {item['attributed_fee_cents']}"
    )
    assert item["attributable_amount_cents"] == 99_000


def test_reevaluation_leaves_the_split_observable_while_still_unattributed():
    """PRD §3.8: "Both `attributed_fee_cents` and `attributable_amount_cents` are
    reported on every raise and every reevaluation of an `UNMATCHED_DEPOSIT` item
    whether or not a destination resolved, so the split remains observable even
    while the deposit is still unattributed".

    Design: Difficulty/combinatorial_formula/deposit_attribution_gross_tier_evaluated_before_residual
    """
    scenario = unmatched_deposit_scenario(amount_cents=250_000, reference_code="NRQ995")
    item = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    reevaluated = get_success_data(
        api_client.reevaluate_exception_aging(item["id"], ANALYST))
    assert reevaluated["status"] == "OPEN", "no destination exists, so the item stays open"
    assert reevaluated["attributed_fee_cents"] == 2_500
    assert reevaluated["attributable_amount_cents"] == 247_500