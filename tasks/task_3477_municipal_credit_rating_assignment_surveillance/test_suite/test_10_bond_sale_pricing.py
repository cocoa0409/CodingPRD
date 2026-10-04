"""Borrowing cost at sale.

Covers the PROVISIONAL/FINAL pricing-variant divergence on identical inputs,
the pinned per-year-then-multiply rounding order, and the computed read-back
of a stored bond sale (PRD sections 2.8 and 3.7).
"""

from test_helpers import (
    ADMIN_HEADERS,
    BB_SCORES,
    create_bond_sale,
    make_underwriter_headers,
    setup_published_rating,
    validate_paginated,
    validate_success,
)


def test_bond_sale_provisional_vs_final_spread(api):
    """PRD section 3.7: "`PROVISIONAL` prices off the indicative notch on the
    scorecard of the rating's engagement — the pre-committee estimate — and is
    available whether the rating is `ASSIGNED` or `PUBLISHED`. `FINAL` prices
    off the rating's current published notch, reflecting every
    post-publication action, and requires the rating to be `PUBLISHED`;
    otherwise it fails with `ERR_RATING_STATE_INVALID`."
    PRD section 3.7: "The effective yield is a benchmark of 300 basis points
    plus a spread keyed by the pricing notch: 25 basis points for `AAA`, 45
    for `AA`, 90 for `A`, 150 for `BBB`, 325 for `BB`, 600 for `B`, and 900
    for `CCC`; the resulting yield is stored as `effective_yield_bps`."

    Design: Difficulty/dual_variant_calc/bond_sale_provisional_vs_final_spread
    """
    # Indicative A on the scorecard; committee median BBB (one notch away,
    # inside the band) publishes at notch BBB.
    ctx = setup_published_rating(
        api, votes=[("voter-1", "BBB"), ("voter-2", "BBB"), ("voter-3", "A")]
    )
    rating = ctx["rating"]
    issuer = ctx["issuer"]
    assert rating["notch"] == "BBB"
    assert ctx["scorecard"]["indicative_notch"] == "A"

    provisional = create_bond_sale(
        api, issuer, rating, pricing_mode="PROVISIONAL"
    )
    assert provisional["effective_yield_bps"] == 390, "300 + 90 (notch A)"
    assert provisional["annual_interest_cents"] == 3900000
    assert provisional["total_interest_cents"] == 19500000

    final = create_bond_sale(api, issuer, rating, pricing_mode="FINAL")
    assert final["effective_yield_bps"] == 450, "300 + 150 (notch BBB)"
    assert final["annual_interest_cents"] == 4500000
    assert final["total_interest_cents"] == 22500000
    assert (
        final["total_interest_cents"] - provisional["total_interest_cents"]
        == 3000000
    ), "identical sale inputs diverge by exactly the spread difference"


def test_borrowing_cost_per_year_rounding_pinned(api):
    """PRD section 3.7: "The rounding order is pinned: each year's interest is
    rounded to whole cents first, and only then is that rounded annual figure
    multiplied by `maturity_years` to give `total_interest_cents`. The
    alternative order — multiplying the exact annual figure by the years and
    rounding once at the end — is forbidden: a par of 1000000008 cents at a
    yield of 625 basis points over 3 years produces a `total_interest_cents`
    of 187500003, not 187500002."

    Design: Difficulty/combinatorial_formula/borrowing_cost_per_year_rounding_pinned
    """
    # Scores (3,3,3,3,3,2) -> weighted 2.8500 -> indicative BB; the committee
    # confirms BB, so the published notch prices at 625 bps (300 + 325).
    ctx = setup_published_rating(
        api,
        scores=BB_SCORES,
        votes=[("voter-1", "BB"), ("voter-2", "BB"), ("voter-3", "BB")],
    )
    sale = create_bond_sale(
        api,
        ctx["issuer"],
        ctx["rating"],
        par_amount_cents=1000000008,
        maturity_years=3,
        pricing_mode="FINAL",
    )
    assert sale["effective_yield_bps"] == 625
    # round_half_up(1000000008 * 625 / 10000) == round_half_up(62500000.5).
    assert sale["annual_interest_cents"] == 62500001, (
        "each year's interest is rounded half-up to whole cents first"
    )
    assert sale["total_interest_cents"] == 187500003, (
        "3 * 62500001; the forbidden sum-then-round order yields 187500002"
    )


def test_bond_sale_get_returns_computed_pricing(api):
    """PRD section 3.7: "The effective yield is a benchmark of 300 basis
    points plus a spread keyed by the pricing notch" and "Annual interest is
    the par amount multiplied by the effective yield in basis points and
    divided by 10000, rounded half-up to whole cents and stored as
    `annual_interest_cents`."
    PRD section 2.2: "operations that create or modify a resource will return
    the created or updated resource object in the data field."

    Design: Corner/endpoints/bond_sale_get_returns_computed_pricing
    """
    ctx = setup_published_rating(api)  # published notch A
    sale = create_bond_sale(api, ctx["issuer"], ctx["rating"])  # FINAL default

    fetched = validate_success(
        api.get_bond_sale(
            sale["id"], headers=make_underwriter_headers("uw-unaffiliated")
        ),
        200,
    )
    assert fetched["effective_yield_bps"] == 390
    assert fetched["annual_interest_cents"] == 3900000
    assert fetched["total_interest_cents"] == 19500000

    listed, meta = validate_paginated(
        api.list_bond_sales(
            headers=ADMIN_HEADERS, params={"rating_id": ctx["rating"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == sale["id"]
