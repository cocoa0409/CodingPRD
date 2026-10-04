"""Depth tests for combinatorial formulas: per-product tiered clock
increments, per-license rounding then summation of proceeds, and the pinned
evaluation order of the activity rule against bid validation."""
from test_helpers import (
    UPFRONT_10M_UNITS,
    UPFRONT_20M_UNITS,
    UPFRONT_40M_UNITS,
    UPFRONT_80M_UNITS,
    add_area,
    add_block,
    assert_auction,
    assert_bid,
    assert_clock_round,
    assert_license,
    assert_license_price_invariants,
    begin_quiet_period,
    close_round,
    create_auction,
    create_draft_plan,
    create_qualified_applicant,
    current_round,
    get_applicant,
    get_auction,
    get_demand_entry,
    get_price_entry,
    get_round,
    get_supply_entry,
    open_applications,
    open_next_round,
    place_bid,
    publish_plan,
    setup_clock_active_auction,
    setup_closed_auction_with_licenses,
    start_clock,
)


def test_clock_increment_tiered_per_product(api):
    """PRD §3.5: "Take the product's finalized demand — its `demand_quantity`
    in that round's `aggregate_demand` — and its supply, the block's
    `supply_per_area`. The comparisons use integer cross-multiplication so no
    floating-point division ever occurs: the product takes a 15 percent
    increment when twice the demand is at least three times the supply;
    failing that, a 10 percent increment when five times the demand is at
    least six times the supply; failing that, a 5 percent increment when the
    demand is at least the supply."
    PRD §3.5: "A product whose demand falls short of supply closes: it is
    excluded from the new round's `prices` array, is no longer biddable, and
    can never re-enter. Because the decision is computed independently per
    product, one product may jump 15 percent in the same round in which
    another closes."

    Design: Difficulty/combinatorial_formula/clock_increment_tiered_per_product
    """
    ctx = setup_clock_active_auction(
        area_codes=("PEA003",),
        block_categories=("CATEGORY_C", "CATEGORY_D"),
        bidder_specs=[
            {"legal_name": "G1 Wireless", "upfront_cents": UPFRONT_80M_UNITS},
            {"legal_name": "G2 Wireless", "upfront_cents": UPFRONT_10M_UNITS},
        ],
    )
    g1, g2 = ctx["applicants"]
    auction_id = ctx["auction"]["id"]
    r1 = ctx["round"]

    # CATEGORY_C demand 4 + 1 = 5 (ratio 1.25 -> +10% tier); CATEGORY_D
    # demand 3 < supply 4 -> closes permanently.
    place_bid(r1["id"], g1["id"], "PEA003", "CATEGORY_C", 4)
    place_bid(r1["id"], g1["id"], "PEA003", "CATEGORY_D", 3)
    place_bid(r1["id"], g2["id"], "PEA003", "CATEGORY_C", 1)
    close_round(r1["id"])

    r1_closed = get_round(r1["id"])
    assert get_demand_entry(r1_closed, "PEA003", "CATEGORY_C")["demand_quantity"] == 5
    assert get_demand_entry(r1_closed, "PEA003", "CATEGORY_D")["demand_quantity"] == 3

    r2 = open_next_round(auction_id)
    assert_clock_round(r2)
    assert r2["round_number"] == 2
    assert r2["stage"] == 1
    # Only CATEGORY_C survives: 1,000,000,000 * 110/100 = 1,100,000,000.
    assert len(r2["prices"]) == 1
    entry = get_price_entry(r2, "PEA003", "CATEGORY_C")
    assert entry["price_cents"] == 1_100_000_000
    assert all(p["category"] != "CATEGORY_D" for p in r2["prices"])

    auction = get_auction(auction_id)
    assert_auction(auction)
    assert auction["status"] == "CLOCK_ACTIVE"
    assert auction["current_round_number"] == 2


def test_settlement_round_per_license_then_sum(api):
    """PRD §3.6: "Rounding order is pinned: each license's `net_price_cents`
    is rounded to cents first, and the auction's `total_proceeds_cents` is
    then the sum of those per-license figures — summing unrounded values and
    rounding once at the end is a different, non-conformant answer."
    PRD §3.6: "Walking that ranking, each winner's won quantity takes the next
    consecutive `frequency_block_index` values, starting at 0, within the
    product."
    PRD §3.3: "A small-business claimant receives 35 percent when its
    attributable revenue is at most 400000000 cents".

    Design: Difficulty/combinatorial_formula/settlement_round_per_license_then_sum
    """
    ctx = setup_closed_auction_with_licenses(
        bids=[(0, "PEA002", "CATEGORY_A", 2)],
        assignment_amounts={(0, "PEA002", "CATEGORY_A"): 1},
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[{"legal_name": "Small Biz Co", "claims_small_business": True}],
    )
    licenses = ctx["licenses"]
    assert len(licenses) == 2
    for lic in licenses:
        assert_license(lic)
        assert_license_price_invariants(lic)
        # gross 250,000,000 + 1 cent assignment bid; 65% of 250,000,001 is
        # 162,500,000.65 -> round_half_up per license -> 162,500,001 EACH.
        assert lic["gross_final_price_cents"] == 250_000_001
        assert lic["net_price_cents"] == 162_500_001
        assert lic["credit_pct"] == 35
    # Single winner of two units takes the consecutive indices 0 and 1.
    assert sorted(lic["frequency_block_index"] for lic in licenses) == [0, 1]

    auction = get_auction(ctx["auction"]["id"])
    assert_auction(auction)
    assert auction["status"] == "CLOSED"
    # Per-license round-then-sum: 2 * 162,500,001 = 325,000,002 (sum-then-
    # round would give 325,000,001 and is non-conformant).
    assert auction["total_proceeds_cents"] == 325_000_002
    assert get_supply_entry(auction, "PEA002", "CATEGORY_A")["available"] == 0


def test_activity_eligibility_evaluation_order(api):
    """PRD §3.5: "The requirement is set by the round's `stage`: 800
    milli-units (80 percent) in stage 1 and 950 milli-units (95 percent) in
    stage 2. If the applicant's activity multiplied by 1000 is at least the
    stage requirement multiplied by the applicant's current
    `eligibility_units`, eligibility is unchanged — the boundary is inclusive.
    Otherwise `eligibility_units` is reduced to the applicant's activity
    multiplied by 1000 and divided by the stage requirement, rounded down to a
    whole unit."
    PRD §3.5: "The evaluation order is pinned to break any appearance of
    circularity: bids were validated against the eligibility in force during
    the round; activity is measured at close for that same round; and any
    reduction applies to subsequent rounds only, never retroactively."
    PRD §3.5: "Each clock round is `OPEN` or `CLOSED`, carries a 1-based
    `round_number`, and is stamped with a `stage` — 1 for every round before
    round 4, and 2 from round 4 onward."

    Design: Difficulty/combinatorial_formula/activity_eligibility_evaluation_order
    """
    # CATEGORY_C here is 9 MHz, supply 2, 10 cents/MHz-pop over the
    # 1,000,000-pop area: bidding units 9,000,000, opening price 90,000,000.
    plan = create_draft_plan()
    add_area(plan["id"], "PEA001")
    add_block(
        plan["id"], "CATEGORY_C", mhz_size=9, supply_per_area=2, price_per_mhz_pop_cents=10
    )
    publish_plan(plan["id"])
    auction = create_auction(plan["id"])
    open_applications(auction["id"])
    g = create_qualified_applicant(auction["id"], UPFRONT_20M_UNITS, legal_name="G Bidder")
    h = create_qualified_applicant(auction["id"], UPFRONT_40M_UNITS, legal_name="H Bidder")
    begin_quiet_period(auction["id"], auction["application_deadline"])
    start_clock(auction["id"])

    # Rounds 1-3 (stage 1): both bid qty 2 (18,000,000 units) every round;
    # demand 4 > supply 2 keeps the clock running. The administrator opens
    # each next round explicitly after the previous one CLOSED (§3.5).
    for round_idx in range(3):
        round_ = current_round(auction["id"])
        place_bid(round_["id"], g["id"], "PEA001", "CATEGORY_C", 2)
        place_bid(round_["id"], h["id"], "PEA001", "CATEGORY_C", 2)
        close_round(round_["id"])
        if round_idx < 2:
            open_next_round(auction["id"])

    # Stage-1 outcome: G unchanged (18M * 1000 >= 800 * 20M); H was reduced
    # once at round-1 close to floor(18M*1000/800) = 22,500,000 and then held
    # at the inclusive boundary (18M * 1000 == 800 * 22.5M).
    assert get_applicant(g["id"])["eligibility_units"] == 20_000_000
    assert get_applicant(h["id"])["eligibility_units"] == 22_500_000

    r4 = open_next_round(auction["id"])
    assert r4["stage"] == 2
    # Round-4 bids are validated against the eligibility in force DURING the
    # round (20M and 22.5M), so both 18M-unit bids are accepted.
    bid_g4 = place_bid(r4["id"], g["id"], "PEA001", "CATEGORY_C", 2)
    bid_h4 = place_bid(r4["id"], h["id"], "PEA001", "CATEGORY_C", 2)
    assert_bid(bid_g4)
    assert_bid(bid_h4)
    assert bid_g4["status"] == "SUBMITTED"
    assert bid_h4["status"] == "SUBMITTED"

    close_round(r4["id"])
    # Stage-2 (950 milli): 18M * 1000 < 950 * 20M, so both reduce to
    # floor(18,000,000 * 1000 / 950) = 18,947,368 — from round 5 onward.
    assert get_applicant(g["id"])["eligibility_units"] == 18_947_368
    assert get_applicant(h["id"])["eligibility_units"] == 18_947_368
