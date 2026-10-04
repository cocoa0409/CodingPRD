"""Breadth tests over the calculation surface: eligibility floor division,
attribution and credit-tier constants, the tiered clock-increment boundary,
and the assignment-ranking tie-break."""
from test_helpers import (
    UPFRONT_10M_UNITS,
    assert_eligibility_from_held,
    create_open_auction,
    create_qualified_applicant,
    eligibility_units_for,
    expected_attributable_revenue_cents,
    expected_credit_pct,
    expected_next_price_cents,
    get_applicant,
    get_price_entry,
    get_round,
    list_licenses,
    make_bidder_headers,
    open_next_round,
    register_applicant,
    run_round,
    setup_clock_active_auction,
    setup_closed_auction_with_licenses,
    validate_success,
)


def test_upfront_payment_eligibility_floor_discards_remainder(api, auction_admin_headers):
    """PRD §3.2: "Each payment increases `upfront_paid_cents` and
    `upfront_held_cents` by the amount paid and immediately recomputes
    `eligibility_units` as the held balance divided by 2500, rounded down to
    a whole unit — one eligibility unit of bidding power per 2500 cents
    held."

    Design: Corner/calculations/eligibility_floor_division_discards_remainder
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    r = register_applicant(
        ctx["auction"]["id"],
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )

    # 31,250,001,250 / 2500 = 12,500,000.5: the floor discards the odd 1,250
    # cents — they remain held but buy no unit.
    amount = 31_250_001_250
    resp = api.add_upfront_payment(r["id"], amount, make_bidder_headers(r["id"]))
    data = validate_success(resp, 200)
    assert data["eligibility_units"] == 12_500_000
    assert data["upfront_held_cents"] == amount
    assert eligibility_units_for(amount) == 12_500_000  # the PRD floor rule

    r_after = get_applicant(r["id"])
    assert r_after["eligibility_units"] == 12_500_000
    assert_eligibility_from_held(r_after)


def test_attribution_stake_exactly_25_is_not_attributable(api, auction_admin_headers):
    """PRD §3.3: "The `attributable_revenue_cents` is the applicant's
    `own_annual_revenue_cents` plus the `holder_annual_revenue_cents` of
    every ownership interest whose `stake_pct` is strictly greater than 25 —
    a holder with exactly 25 percent is not attributable."
    PRD §3.3: "A small-business claimant receives 35 percent when its
    attributable revenue is at most 400000000 cents, otherwise 25 percent
    when at most 2000000000 cents, otherwise 15 percent when at most
    5500000000 cents, and 0 above the largest tier; tier boundaries are
    inclusive, so revenue exactly at a boundary qualifies for that
    boundary's percentage."

    Design: Corner/calculations/attribution_stake_exactly_25_is_not_attributable
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction_id = ctx["auction"]["id"]

    # 25.00 is NOT strictly greater than 25: the 900,000,000-cent holder is
    # not attributed, leaving the applicant in the 35% tier.
    l25_interests = [
        {"holder_name": "HoldCo", "stake_pct": 25.00, "holder_annual_revenue_cents": 900_000_000},
        {"holder_name": "Rest", "stake_pct": 75, "holder_annual_revenue_cents": 0},
    ]
    l25 = create_qualified_applicant(
        auction_id,
        UPFRONT_10M_UNITS,
        legal_name="L25",
        claims_small_business=True,
        ownership_interests=l25_interests,
    )

    # 25.01 > 25: the full holder revenue attributes, pushing the applicant
    # to the 25% tier (at most 2,000,000,000).
    l2501_interests = [
        {"holder_name": "HoldCo", "stake_pct": 25.01, "holder_annual_revenue_cents": 900_000_000},
        {"holder_name": "Rest", "stake_pct": 74.99, "holder_annual_revenue_cents": 0},
    ]
    l2501 = create_qualified_applicant(
        auction_id,
        UPFRONT_10M_UNITS,
        legal_name="L2501",
        claims_small_business=True,
        ownership_interests=l2501_interests,
    )

    l25_after = get_applicant(l25["id"])
    assert l25_after["status"] == "QUALIFIED"
    assert l25_after["attributable_revenue_cents"] == 0
    assert l25_after["credit_pct"] == 35
    assert l25_after["attributable_revenue_cents"] == expected_attributable_revenue_cents(
        0, l25_interests
    )

    l2501_after = get_applicant(l2501["id"])
    assert l2501_after["status"] == "QUALIFIED"
    assert l2501_after["attributable_revenue_cents"] == 900_000_000
    assert l2501_after["credit_pct"] == 25
    assert l2501_after["credit_pct"] == expected_credit_pct(True, False, 900_000_000, 0)


def test_rural_population_cap_exact_boundary(api, auction_admin_headers):
    """PRD §3.3: "A rural claimant instead receives 15 percent when its
    `service_population` is at most 250000, and 0 above that cap."

    Design: Corner/calculations/rural_population_cap_exact_boundary
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction_id = ctx["auction"]["id"]

    # The cap is inclusive: exactly 250,000 earns the 15% rural credit.
    r_in = create_qualified_applicant(
        auction_id,
        UPFRONT_10M_UNITS,
        legal_name="R In",
        claims_rural_credit=True,
        service_population=250_000,
    )
    # One resident over the cap earns nothing — but still qualifies.
    r_out = create_qualified_applicant(
        auction_id,
        UPFRONT_10M_UNITS,
        legal_name="R Out",
        claims_rural_credit=True,
        service_population=250_001,
    )

    r_in_after = get_applicant(r_in["id"])
    assert r_in_after["status"] == "QUALIFIED"
    assert r_in_after["credit_pct"] == 15

    r_out_after = get_applicant(r_out["id"])
    assert r_out_after["status"] == "QUALIFIED"
    assert r_out_after["credit_pct"] == 0


def test_increment_ratio_exactly_one_point_five_hits_top_tier(api, auction_admin_headers):
    """PRD §3.5: "the product takes a 15 percent increment when twice the
    demand is at least three times the supply; failing that, a 10 percent
    increment when five times the demand is at least six times the supply;
    failing that, a 5 percent increment when the demand is at least the
    supply."
    PRD §3.5: "Boundaries are inclusive on the lower side — demand of exactly
    three-halves of supply earns 15 percent, exactly six-fifths earns 10
    percent, and demand exactly equal to supply earns 5 percent."
    PRD §3.5: "The new posted price is the product's last price increased by
    the selected percentage and rounded half up to a whole cent, applied once
    per product per round."

    Design: Corner/calculations/increment_ratio_exactly_one_point_five_hits_top_tier
    """
    # CATEGORY_C @ PEA003: units 5 * 2,000,000 = 10,000,000; opening price
    # 10,000,000 * 100 = 1,000,000,000. Three bidders, 50,000,000 units each.
    ctx = setup_clock_active_auction(
        area_codes=("PEA003",),
        block_categories=("CATEGORY_C",),
        bidder_specs=[
            {"legal_name": "T1", "upfront_cents": 125_000_000_000},
            {"legal_name": "T2", "upfront_cents": 125_000_000_000},
            {"legal_name": "T3", "upfront_cents": 125_000_000_000},
        ],
    )
    round1 = ctx["round"]
    assert get_price_entry(round1, "PEA003", "CATEGORY_C")["price_cents"] == 1_000_000_000

    t1, t2, t3 = (a["id"] for a in ctx["applicants"])
    # Demand 6 vs supply 4: 2*6 >= 3*4 with equality, so the inclusive
    # three-halves boundary selects the +15% tier.
    run_round(
        ctx["auction"]["id"],
        [
            (t1, "PEA003", "CATEGORY_C", 2),
            (t2, "PEA003", "CATEGORY_C", 2),
            (t3, "PEA003", "CATEGORY_C", 2),
        ],
    )

    round2 = open_next_round(ctx["auction"]["id"])
    price = get_price_entry(get_round(round2["id"]), "PEA003", "CATEGORY_C")["price_cents"]
    assert price == 1_150_000_000  # 1,000,000,000 * 115 / 100 exactly
    assert price == expected_next_price_cents(1_000_000_000, 6, 4)


def test_assignment_tie_break_by_created_at(api, auction_admin_headers):
    """PRD §3.6: "Within each product, the winners' assignment bids are
    ranked by `amount_cents` descending, with ties broken by the assignment
    bid's `created_at` ascending — never by id."
    PRD §3.6: "Walking that ranking, each winner's won quantity takes the
    next consecutive `frequency_block_index` values, starting at 0, within
    the product."

    Design: Corner/calculations/assignment_tie_break_by_created_at
    """
    # CATEGORY_A @ PEA002 has supply 2; R and W1 win one unit each and file
    # identical 5,000,000 assignment bids — R's first, W1's second — so only
    # filing order separates them.
    ctx = setup_closed_auction_with_licenses(
        bids=[(0, "PEA002", "CATEGORY_A", 1), (1, "PEA002", "CATEGORY_A", 1)],
        assignment_amounts={
            (0, "PEA002", "CATEGORY_A"): 5_000_000,
            (1, "PEA002", "CATEGORY_A"): 5_000_000,
        },
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {
                "legal_name": "Rural Wireless Co",
                "claims_rural_credit": True,
                "service_population": 200_000,
                "upfront_cents": 12_500_000_000,
            },
            {"legal_name": "Winner One LLC", "upfront_cents": 12_500_000_000},
        ],
    )
    r_id = ctx["applicants"][0]["id"]
    w1_id = ctx["applicants"][1]["id"]

    r_licenses = list_licenses(holder_applicant_id=r_id)
    w1_licenses = list_licenses(holder_applicant_id=w1_id)
    assert len(r_licenses) == 1
    assert len(w1_licenses) == 1
    assert r_licenses[0]["assignment_bid_cents"] == 5_000_000
    assert w1_licenses[0]["assignment_bid_cents"] == 5_000_000
    # The earlier-filed bid takes frequency_block_index 0.
    assert r_licenses[0]["frequency_block_index"] == 0
    assert w1_licenses[0]["frequency_block_index"] == 1
