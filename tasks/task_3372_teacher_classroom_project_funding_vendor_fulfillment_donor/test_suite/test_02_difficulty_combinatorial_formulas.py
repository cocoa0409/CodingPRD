"""Combinatorial formulas: the shipping quote's nested clamp and the match's
pinned per-donation rounding order."""

from test_helpers import (
    assert_campaign_budget_invariant,
    assert_cents,
    fixtures,
    validate_success,
)
from test_helpers import factories as f


# ── Shipping quote: tier + max-zone + fragile + clamp ──────────────────────
#
# Fixture geometry: 4 x SM-BOOK-1 (2500c, 10 oz, zone A) plus 1 x SM-LAB-1
# (800c, 200 oz, zone B, fragile) on one vendor. Total 240 oz -> tier 3 base
# 899; zone rate max(120, 180) = 180; pounds ceil(240/16) = 15; fragile +350.
# Raw fee 899 + 15*180 + 350 = 3949, inside the [199, 4999] clamp.
# Items total 4*2500 + 800 = 10800; goal 10800 + 3949 = 14749.

BOOK_LAB_SPECS = [(f.book_item_spec(), 4), (f.lab_item_spec(), 1)]


def test_shipping_quote_combines_tier_max_zone_and_fragile_at_submit(api):
    """The per-vendor shipping quote is computed over one vendor's lines.

    PRD: "The tier base depends on total ounces: at most 32 ounces the base is 299 cents; more than 32 and at most 128 ounces it is 599 cents; more than 128 ounces it is 899 cents."
    PRD: "The zone rate is the highest per-pound zone rate among the vendor's lines — 120 cents for zone `A`, 180 for `B`, 260 for `C`. Billable pounds are the total ounces divided by 16 and rounded up to a whole number. The raw fee is the tier base plus the billable pounds times the zone rate, plus a flat 350 cents if any line is fragile."
    Design: Difficulty/combinatorial_formula/po_shipping_nested_clamp_fragile_zone
    """
    world = fixtures.setup_draft_project(api, item_specs=BOOK_LAB_SPECS)
    project_id = world["project"]["id"]

    provisional = fixtures.read_project(api, project_id)
    assert provisional["provisional_total_cents"] == 14749, (
        "items 10800 + shipping 3949 at current prices"
    )

    submitted = fixtures.submit_project(api, project_id, world["teacher"])
    assert submitted["status"] == "IN_REVIEW"
    pinned = fixtures.read_project(api, project_id)
    assert pinned["pinned_items_total_cents"] == 10800, "4 x 2500 + 1 x 800 pinned"
    assert pinned["pinned_shipping_total_cents"] == 3949, (
        "tier 3 base 899 (240 oz > 128) + 15 lbs x max-zone rate 180 + fragile 350"
    )
    assert pinned["goal_cents"] == 14749


def test_issued_purchase_order_carries_the_quoted_shipping_fee(api):
    """The PO's shipping fee is the same quote computed at issuance.

    PRD: "The final fee clamps the raw fee: never below 199 cents and never above 4999 cents."
    PRD: "Each auto-issued purchase order records its `project_id` and `vendor_id`, a `line_items` snapshot array — each entry carrying `catalog_item_id`, `sku`, `quantity`, and `pinned_unit_price_cents` — sorted by the catalog item's `created_at` ascending (never by id), a `line_total_cents` equal to the sum of pinned price times quantity over those lines, and a `shipping_fee_cents` equal to the shipping quote of §3.2 computed over those lines at issuance."
    Design: Difficulty/combinatorial_formula/po_shipping_nested_clamp_fragile_zone
    """
    world = fixtures.setup_funded_project(api, item_specs=BOOK_LAB_SPECS)
    project = world["project"]
    assert project["status"] == "FUNDED"
    assert project["goal_cents"] == 14749

    pos = world["purchase_orders"]
    assert len(pos) == 1, "one vendor -> exactly one purchase order"
    po = pos[0]
    assert po["status"] == "ISSUED"
    assert po["vendor_id"] == world["vendor"]["id"]
    assert_cents(po["line_total_cents"], 10800, "po line_total_cents")
    assert_cents(po["shipping_fee_cents"], 3949, "po shipping_fee_cents")
    assert {line["quantity"] for line in po["line_items"]} == {4, 1}
    assert project["pinned_shipping_total_cents"] == 3949


# ── Match allocation: per-donation rounding before accumulation ────────────


def _funding_world_with_campaign(api):
    """FUNDING project (goal 10959) plus an ACTIVE 0.5-ratio TX campaign."""
    world = fixtures.setup_funding_project(api)
    campaign = fixtures.create_match_campaign(api, match_ratio=0.5, budget_cents=100000)
    donor = fixtures.create_donor(api)
    world.update(campaign=campaign, donor=donor)
    return world


def test_match_rounds_each_donation_before_summing(api):
    """Two 101-cent donations at ratio 0.5 match 51 + 51 = 102, never 101.

    PRD: "The rounding order is pinned: each donation's match is rounded first and only then accumulated. Summing raw matches across donations and rounding once is forbidden — two 101-cent donations at ratio 0.5 yield 51 plus 51, that is 102 matched cents, never the 101 that a single rounding of the pooled raw match would produce."
    Design: Difficulty/combinatorial_formula/match_rounded_per_donation_not_per_sum
    """
    world = _funding_world_with_campaign(api)
    campaign_id = world["campaign"]["id"]

    d1 = fixtures.donate(api, world["project"]["id"], world["donor"], 101, campaign_id)
    d2 = fixtures.donate(api, world["project"]["id"], world["donor"], 101, campaign_id)

    assert d1["matched_cents"] == 51, "round_half_up(101 x 0.5) = round_half_up(50.5) = 51"
    assert d2["matched_cents"] == 51

    campaign = fixtures.read_match_campaign(api, campaign_id)
    assert_cents(campaign["matched_so_far_cents"], 102, "matched_so_far_cents")
    assert_cents(campaign["remaining_budget_cents"], 99898, "remaining_budget_cents")
    assert_campaign_budget_invariant(campaign)


def test_per_donation_matches_accumulate_onto_project_funding(api):
    """Each donation's rounded match lands on the project's funded_cents too.

    PRD: "The match itself is computed per donation: the raw match is `amount_cents` multiplied by the campaign's `match_ratio`, rounded half up to whole cents, and `matched_cents` is the lesser of that rounded amount and the campaign's `remaining_budget_cents`."
    PRD: "Funding progress is measured by `funded_cents`, the sum of `amount_cents` plus `matched_cents` over the project's donations in `CAPTURED` or `CHOICE_PENDING` status only."
    Design: Difficulty/combinatorial_formula/match_rounded_per_donation_not_per_sum
    """
    world = _funding_world_with_campaign(api)
    campaign_id = world["campaign"]["id"]

    fixtures.donate(api, world["project"]["id"], world["donor"], 101, campaign_id)
    fixtures.donate(api, world["project"]["id"], world["donor"], 101, campaign_id)

    project = fixtures.read_project(api, world["project"]["id"])
    assert_cents(project["funded_cents"], 304, "funded_cents")  # (101 + 51) twice
    assert project["status"] == "FUNDING", "304 is far below the 10959 goal"

    campaign = fixtures.read_match_campaign(api, campaign_id)
    assert campaign["budget_cents"] == 100000
    assert campaign["matched_so_far_cents"] + campaign["remaining_budget_cents"] == 100000
