"""Make-ready allocation at ground-break and the nine-step conversion settlement."""

from test_helpers import (
    assert_cents,
    assert_shares_sum_to_pool,
    canonical_instant,
    list_ledger_for_account,
    read_account,
    read_preorder,
    read_zone,
    setup_construction_ready_zone,
    setup_converted_preorder,
)

MAKE_READY_POOL_CENTS = 500000
EVENLY_DIVISIBLE_POOL_CENTS = 45600


def test_make_ready_pool_splits_by_floor_quotient_with_a_front_loaded_residue():
    """500,000 cents over three recipients pays 166,667, 166,667 and 166,666.

    PRD 3.6: "Each recipient first receives the integer quotient of the total divided by
    the count, discarding any fraction. The residue - the total minus that quotient
    multiplied by the count, a value that is at least zero and strictly less than the
    recipient count - is then distributed one extra cent at a time to the recipients at the
    front of the sorted order, so that the first *residue* recipients receive the quotient
    plus one cent and everyone after them receives the quotient exactly."

    Design: Difficulty/combinatorial_formula/make_ready_share_floor_then_remainder_order
    """
    base = setup_construction_ready_zone(
        preorder_count=3, household_count=10, pole_quote_cents=MAKE_READY_POOL_CENTS
    )

    shares = [read_preorder(p["id"])["make_ready_share_cents"] for p in base["preorders"]]

    assert shares == [166667, 166667, 166666], shares


def test_allocated_shares_sum_to_the_pool_with_zero_residue_left_over():
    """The three integer shares reconstruct the zone's make-ready cost exactly.

    PRD 3.6: "The arithmetic is integer throughout, there is no rounding mode, and the
    shares sum to the total with zero residue left over."

    Design: Difficulty/combinatorial_formula/make_ready_share_floor_then_remainder_order
    """
    base = setup_construction_ready_zone(
        preorder_count=3, household_count=10, pole_quote_cents=MAKE_READY_POOL_CENTS
    )

    zone = read_zone(base["zone"]["id"])
    assert zone["construction_status"] == "IN_CONSTRUCTION", zone["construction_status"]
    assert_cents(zone["make_ready_cost_cents"], MAKE_READY_POOL_CENTS, "make_ready_cost_cents")

    shares = [read_preorder(p["id"])["make_ready_share_cents"] for p in base["preorders"]]
    assert_shares_sum_to_pool(shares, MAKE_READY_POOL_CENTS)
    for share in shares:
        assert isinstance(share, int) and not isinstance(share, bool), share


def test_extra_cents_go_to_the_earliest_created_recipients():
    """The residue lands on the front of the created_at-ascending recipient order.

    PRD 3.6: "The recipients are the zone's preorders whose `preorder_status` is
    `QUALIFIED` at this instant - `PENDING` preorders are excluded because they never
    qualified, and `LAPSED`, `CANCELLED` and `CONVERTED` ones are excluded too - sorted by
    `created_at` ascending, with ties broken by the ascending `street_address` of the
    preorder's address as a final deterministic tie-break."

    Design: Difficulty/combinatorial_formula/make_ready_share_floor_then_remainder_order
    """
    base = setup_construction_ready_zone(
        preorder_count=3, household_count=10, pole_quote_cents=MAKE_READY_POOL_CENTS
    )

    rows = [read_preorder(p["id"]) for p in base["preorders"]]
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), stamps

    quotient = MAKE_READY_POOL_CENTS // len(rows)
    residue = MAKE_READY_POOL_CENTS - quotient * len(rows)
    assert 0 <= residue < len(rows), residue
    for position, row in enumerate(rows):
        expected = quotient + 1 if position < residue else quotient
        assert_cents(
            row["make_ready_share_cents"], expected, f"share at position {position}"
        )


def _aerial_conversion_on_an_even_pool():
    """Three recipients over a 45,600-cent pool, so each share is exactly 15,200."""
    return setup_converted_preorder(
        drop_method="AERIAL",
        preorder_index=0,
        preorder_count=3,
        household_count=10,
        pole_quote_cents=EVENLY_DIVISIBLE_POOL_CENTS,
    )


def test_discount_tier_is_chosen_from_the_pre_discount_total_not_the_install_base():
    """An install base of 9,900 lifted to 30,100 by drop and share earns the 0.05 tier.

    PRD 3.7: "Fifth, the loyalty tier is chosen from the pre-discount total - and it is
    chosen from *that* figure, not from the install base alone and not from any post-deposit
    amount. A pre-discount total of at least 50,000 cents earns a discount rate of 0.10;
    otherwise a total of at least 30,000 cents earns 0.05; otherwise the rate is 0.00."

    Design: Difficulty/combinatorial_formula/conversion_settlement_discount_tier_evaluated_pre_deposit
    """
    base = _aerial_conversion_on_an_even_pool()

    preorder = read_preorder(base["converted"]["id"])
    assert preorder["plan_tier"] == "BASIC_300", preorder["plan_tier"]
    assert preorder["drop_method"] == "AERIAL", preorder["drop_method"]
    assert_cents(preorder["make_ready_share_cents"], 15200, "make_ready_share_cents")
    assert_cents(
        preorder["conversion_pre_discount_total_cents"],
        30100,
        "conversion_pre_discount_total_cents",
    )
    assert_cents(preorder["conversion_discount_cents"], 1505, "conversion_discount_cents")


def test_deposit_is_credited_at_face_value_after_the_discount_is_taken():
    """The 1,000-cent deposit is subtracted from the net 28,595 to leave 27,595 owing.

    PRD 3.7: "Eighth, the subscriber's held deposit is credited at face value - never
    discounted, never scaled - so the amount still owing is the net total minus the
    preorder's `deposit_amount_cents`."

    Design: Difficulty/combinatorial_formula/conversion_settlement_discount_tier_evaluated_pre_deposit
    """
    base = _aerial_conversion_on_an_even_pool()

    preorder = read_preorder(base["converted"]["id"])
    net_total = (
        preorder["conversion_pre_discount_total_cents"]
        - preorder["conversion_discount_cents"]
    )
    assert_cents(net_total, 28595, "net total")
    assert_cents(preorder["deposit_amount_cents"], 1000, "deposit_amount_cents")
    assert_cents(
        preorder["conversion_total_due_cents"], 27595, "conversion_total_due_cents"
    )


def test_conversion_consumes_the_deposit_through_one_negative_ledger_entry():
    """Settlement moves the deposit HELD to APPLIED and drains the account's held balance.

    PRD 3.7: "`deposit_status` moves `HELD → APPLIED`, appending one ledger entry of
    `entry_type` `DEPOSIT_APPLIED` whose `amount_cents` is the negative of
    `deposit_amount_cents` and recomputing the account's `deposit_held_cents`; and
    `converted_at` is stamped with the logical clock."

    Design: Difficulty/combinatorial_formula/conversion_settlement_discount_tier_evaluated_pre_deposit
    """
    base = _aerial_conversion_on_an_even_pool()
    account = base["accounts"][0]

    preorder = read_preorder(base["converted"]["id"])
    assert preorder["preorder_status"] == "CONVERTED", preorder["preorder_status"]
    assert preorder["deposit_status"] == "APPLIED", preorder["deposit_status"]
    assert preorder["converted_at"] is not None
    assert_cents(read_account(account["id"])["deposit_held_cents"], 0, "deposit_held_cents")

    entries, _ = list_ledger_for_account(account["id"])
    applied = [e for e in entries if e["entry_type"] == "DEPOSIT_APPLIED"]
    assert len(applied) == 1, entries
    assert_cents(applied[0]["amount_cents"], -1000, "DEPOSIT_APPLIED amount_cents")
    assert applied[0]["preorder_id"] == preorder["id"], applied[0]["preorder_id"]
