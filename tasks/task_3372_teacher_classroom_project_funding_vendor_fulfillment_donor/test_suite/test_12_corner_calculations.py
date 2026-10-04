"""Calculation corners: the match budget cap with EXHAUSTED round-trip, the
shipping fee cap on a heavy fragile order, and immediate read-after-write
consistency of the funding totals."""

from test_helpers import (
    assert_campaign_budget_invariant,
    assert_cents,
    fixtures,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.constants import FUNDING_DEADLINE


def test_match_budget_cap_exhausts_campaign_then_clawback_restores(api):
    """The match caps at the campaign's remaining budget; the expiry clawback
    restores exactly those cents and reopens the campaign.

    PRD: "The match itself is computed per donation: the raw match is `amount_cents` multiplied by the campaign's `match_ratio`, rounded half up to whole cents, and `matched_cents` is the lesser of that rounded amount and the campaign's `remaining_budget_cents`. The campaign's `matched_so_far_cents` grows by `matched_cents` and its `remaining_budget_cents` shrinks by the same amount; when the remaining budget reaches exactly 0, the campaign flips from `ACTIVE` to `EXHAUSTED`."
    PRD: "At the same moment each such donation's `matched_cents` is clawed back to its match campaign: the campaign's `matched_so_far_cents` decreases and its `remaining_budget_cents` increases by the same amount, and an `EXHAUSTED` campaign whose window is still open flips back to `ACTIVE`."
    Design: Corner/calculations/match_budget_cap_exhausts_campaign_then_clawback_restores
    """
    world = fixtures.setup_funding_project(api)
    campaign = fixtures.create_match_campaign(
        api, sponsor_name="TinyCap Partners", match_ratio=1.0, budget_cents=300
    )
    donor = fixtures.create_donor(api)

    donation = fixtures.donate(api, world["project"]["id"], donor, 500, campaign["id"])
    assert_cents(donation["matched_cents"], 300, "min(round_half_up(500 x 1.0), remaining 300)")

    capped = fixtures.read_match_campaign(api, campaign["id"])
    assert_cents(capped["matched_so_far_cents"], 300, "matched_so_far")
    assert_cents(capped["remaining_budget_cents"], 0, "remaining hits zero")
    assert capped["status"] == "EXHAUSTED"
    assert_campaign_budget_invariant(capped)

    project = fixtures.read_project(api, world["project"]["id"])
    assert_cents(project["funded_cents"], 800, "500 principal + 300 capped match")

    # Expiry claws the match back; the window still covers now, so the
    # exhausted campaign flips back to ACTIVE.
    fixtures.set_clock(api, FUNDING_DEADLINE)
    fixtures.run_sweep(api)

    restored = fixtures.read_match_campaign(api, campaign["id"])
    assert_cents(restored["matched_so_far_cents"], 0, "clawed back")
    assert_cents(restored["remaining_budget_cents"], 300, "restored")
    assert restored["status"] == "ACTIVE"
    assert_campaign_budget_invariant(restored)


def test_shipping_fee_cap_binds_on_a_heavy_fragile_order(api):
    """99 units of a 200-oz zone-C fragile item produce a raw fee far above
    the cap; the issued PO reports exactly the capped 4999 cents.

    PRD: "The raw fee is the tier base plus the billable pounds times the zone rate, plus a flat 350 cents if any line is fragile. The final fee clamps the raw fee: never below 199 cents and never above 4999 cents."
    Design: Corner/calculations/shipping_fee_cap_binds_on_heavy_fragile_order
    """
    world = fixtures.setup_funded_project(api, item_specs=[(f.centrifuge_item_spec(), 99)])
    project = world["project"]

    # 99 x 800 = 79200 items; raw fee 899 + ceil(19800/16)=1238 lbs x 260 + 350
    # = 323129, clamped to the 4999 cap. Goal 79200 + 4999 = 84199.
    assert project["status"] == "FUNDED"
    assert_cents(project["goal_cents"], 84199, "goal_cents")

    pos = world["purchase_orders"]
    assert len(pos) == 1
    assert_cents(pos[0]["line_total_cents"], 79200, "po line_total_cents")
    assert_cents(pos[0]["shipping_fee_cents"], 4999, "the cap, not the raw 323129")


def test_funded_total_is_visible_immediately_after_the_donation(api):
    """The write response and the very next reads agree: no reconciliation lag.

    PRD: "Two ledger-style invariants hold at all times, and every workflow in §3 preserves them."
    PRD: "A successful donation starts in status `CAPTURED` with `kind` set to `DONOR`, `donor_id` set to the acting donor, `matched_cents` at 0 unless a match applies, `equity_fund_id` null, and `refund_reason` null; the donor's `lifetime_donated_cents` grows by `amount_cents`, and the project's `funded_cents` grows by `amount_cents` plus `matched_cents`."
    Design: Corner/consistency_model/funded_total_visible_immediately_after_donation
    """
    world = fixtures.setup_funding_project(api)
    donor = fixtures.create_donor(api)

    donation = fixtures.donate(api, world["project"]["id"], donor, 9000)
    assert donation["status"] == "CAPTURED", "the write response reports the capture"

    project = fixtures.read_project(api, world["project"]["id"])
    assert_cents(project["funded_cents"], 9000, "funded_cents on the immediately following read")

    reread = fixtures.read_donation(api, donation["id"])
    assert reread["status"] == "CAPTURED"

    donor_after = fixtures.read_donor(api, donor["id"])
    assert_cents(donor_after["lifetime_donated_cents"], 9000, "lifetime_donated_cents")
