"""Dual-variant calculations: the same inputs, two deliberately different faces.

A project's cost quote has a live provisional face while editable and a frozen
pinned face after submit; a school's equity score has a banded face for
eligibility and a weighted face for ranking.
"""

from test_helpers import assert_one_dp, fixtures, validate_success


# ── Project quote: provisional face vs pinned face ─────────────────────────


def test_provisional_quote_tracks_catalog_price_edits(api):
    """A DRAFT project's provisional face is a live quote at current prices.

    PRD: "While the project is in `DRAFT` or `RETURNED`, every read recomputes `provisional_total_cents` as the sum of `quantity` times the *current* catalog `unit_price_cents` over the project's items, plus the shipping quote computed over each distinct vendor's current lines — a live quote that moves when a vendor edits a price."
    Design: Difficulty/dual_variant_calc/project_quote_provisional_moves_pinned_immune
    """
    world = fixtures.setup_draft_project(api)  # 4 x 2500c book, zone A
    project_id = world["project"]["id"]
    item_id = world["items"][0]["id"]

    before = fixtures.read_project(api, project_id)
    assert before["status"] == "DRAFT"
    assert before["provisional_total_cents"] == 10959, (
        "4 x 2500 + shipping 959 (40 oz -> tier 2 base 599, 3 lbs x 120)"
    )

    # The vendor edits the current price: the provisional face moves with it.
    validate_success(
        api.patch_catalog_item(world["vendor"]["id"], item_id, {"unit_price_cents": 3000},
                               fixtures.ADMIN_HEADERS),
        200,
    )
    after = fixtures.read_project(api, project_id)
    assert after["provisional_total_cents"] == 12959, (
        "the PATCH to 3000c moved the live quote: 4 x 3000 + 959"
    )
    assert after["status"] == "DRAFT"


def test_pinned_goal_immune_to_post_submit_price_edits(api):
    """At submit the prices are pinned; later catalog edits cannot move them.

    PRD: "On success the submit snapshots each item's current catalog price into that item's `pinned_unit_price_cents`, freezes `pinned_items_total_cents` (the sum of pinned price times quantity over the items), `pinned_shipping_total_cents` (the sum of per-vendor shipping quotes over the pinned lines), and `goal_cents` (the sum of those two frozen totals), sets `provisional_total_cents` to null permanently, increments the project's `version` by one, and moves the project to `IN_REVIEW`."
    PRD: "Later catalog price edits leave the pinned totals and the goal untouched."
    Design: Difficulty/dual_variant_calc/project_quote_provisional_moves_pinned_immune
    """
    world = fixtures.setup_draft_project(api)
    project_id = world["project"]["id"]
    item_id = world["items"][0]["id"]

    # Move the catalog price to 3000c before submit: the pin must capture 3000.
    validate_success(
        api.patch_catalog_item(world["vendor"]["id"], item_id, {"unit_price_cents": 3000},
                               fixtures.ADMIN_HEADERS),
        200,
    )
    submitted = fixtures.submit_project(api, project_id, world["teacher"])
    assert submitted["status"] == "IN_REVIEW"

    # A further price edit after submit must not move the pinned face.
    validate_success(
        api.patch_catalog_item(world["vendor"]["id"], item_id, {"unit_price_cents": 4000},
                               fixtures.ADMIN_HEADERS),
        200,
    )
    pinned = fixtures.read_project(api, project_id)
    assert pinned["status"] == "IN_REVIEW"
    assert pinned["provisional_total_cents"] is None, "provisional face is null after submit"
    assert pinned["pinned_items_total_cents"] == 12000, "4 x 3000 pinned at submit"
    assert pinned["pinned_shipping_total_cents"] == 959
    assert pinned["goal_cents"] == 12959, "goal frozen at submit even after the 4000c PATCH"

    rows = fixtures.project_items_for(api, project_id)
    assert len(rows) == 1
    assert rows[0]["pinned_unit_price_cents"] == 3000


# ── School equity scores: banded face vs weighted face ─────────────────────


def test_banded_and_weighted_scores_diverge_on_same_inputs(api):
    """One school row carries two deliberately divergent equity scores.

    PRD: "Every school carries two equity scores, computed at creation and reflected on every read, which deliberately diverge."
    PRD: "The **banded** score, `equity_score_banded`, is a step function of `poverty_pct` alone: at least 90.0 scores 100; at least 75.0 (but below 90.0) scores 80; at least 50.0 (but below 75.0) scores 50; below 50.0 scores 10."
    PRD: "The **weighted** score, `equity_score_weighted`, is seven-tenths of `poverty_pct` plus three-tenths of `ell_pct`, rounded half up to one decimal place"
    Design: Difficulty/dual_variant_calc/equity_scores_banded_vs_weighted_ranking_inversion
    """
    fixtures.set_clock(api)
    s1 = fixtures.create_school(api, name="Ridgeview Elementary", poverty_pct=80.0, ell_pct=90.0)
    s2 = fixtures.create_school(
        api, name="Cactus Middle", district="Cactus ISD", poverty_pct=92.0, ell_pct=10.0
    )

    # Same inputs, two variants, different numbers.
    assert s1["equity_score_banded"] == 80, "80.0 poverty lands in the >= 75 band"
    assert_one_dp(s1["equity_score_weighted"], 83.0, "s1 weighted")  # 0.7*80 + 0.3*90
    assert s2["equity_score_banded"] == 100, "92.0 poverty lands in the >= 90 band"
    assert_one_dp(s2["equity_score_weighted"], 67.4, "s2 weighted")  # 0.7*92 + 0.3*10

    # The reads reflect the same two faces.
    reread = fixtures.get_success_data(api.get_school(s1["id"], fixtures.ADMIN_HEADERS))
    assert reread["equity_score_banded"] == 80
    assert_one_dp(reread["equity_score_weighted"], 83.0, "s1 weighted reread")


def test_equity_allocation_follows_weighted_not_banded(api):
    """The selector ranks by the weighted score, so the lower-poverty school wins.

    PRD: "Candidates are ranked by their school's `equity_score_weighted` in descending order, with ties broken by the project's `created_at` ascending — `created_at` is the only tie-break and id is never used — and the selector picks the single best project."
    PRD: "The grant amount is the lesser of the project's remaining need (`goal_cents` minus `funded_cents`) and the fund's `remaining_cents`."
    Design: Difficulty/dual_variant_calc/equity_scores_banded_vs_weighted_ranking_inversion
    """
    fixtures.set_clock(api)
    s1 = fixtures.create_school(api, name="Ridgeview Elementary", poverty_pct=80.0, ell_pct=90.0)
    s2 = fixtures.create_school(
        api, name="Cactus Middle", district="Cactus ISD", poverty_pct=92.0, ell_pct=10.0
    )
    t1 = fixtures.create_verified_teacher(api, s1["id"], full_name="Ada Lovelace")
    t2 = fixtures.create_verified_teacher(api, s2["id"], full_name="Alan Turing")
    vendor_world = fixtures.seed_vendor_with_items(api)
    item_id = vendor_world["items"][0]["id"]

    # Both projects carry the same 10959c goal; both schools beat min_poverty 75.0.
    p1 = fixtures.create_funding_project(api, t1, [(item_id, 4)])
    p2 = fixtures.create_funding_project(
        api, t2, [(item_id, 4)], title="Reading Nook Revival", grade_band="G6_8"
    )
    assert fixtures.read_project(api, p1["id"])["goal_cents"] == 10959
    assert fixtures.read_project(api, p2["id"])["goal_cents"] == 10959

    fund = fixtures.create_equity_fund(api, budget_cents=500000)
    grant = validate_success(api.allocate_equity_fund(fund["id"], {}, fixtures.ADMIN_HEADERS), 200)

    # Weighted 83.0 (s1) beats weighted 67.4 (s2), even though banded ranks s2 first.
    assert grant["project_id"] == p1["id"], "selector followed equity_score_weighted DESC"
    assert grant["amount_cents"] == 10959, "min(remaining need 10959, fund remaining 500000)"
    assert grant["kind"] == "EQUITY_GRANT"
    assert grant["matched_cents"] == 0
    assert grant["donor_id"] is None
    assert grant["equity_fund_id"] == fund["id"]

    p1_after = fixtures.read_project(api, p1["id"])
    p2_after = fixtures.read_project(api, p2["id"])
    assert p1_after["status"] == "FUNDED", "the grant tipped p1 exactly to its goal"
    assert p2_after["status"] == "FUNDING"
    assert fixtures.read_equity_fund(api, fund["id"])["remaining_cents"] == 500000 - 10959
