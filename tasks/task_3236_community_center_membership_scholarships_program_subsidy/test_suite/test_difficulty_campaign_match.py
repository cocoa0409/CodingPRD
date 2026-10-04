"""Campaign attainment match: live recomputation vs frozen-at-close variant."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    assert_cents,
    assert_fraction,
)
from test_helpers import fixtures


def test_live_match_moves_with_attainment_then_freezes_at_close(api):
    """While ACTIVE the match tier recomputes on every receipt; closing pins the
    tier, and a refund after close lowers the base but not the frozen match.

    PRD §3.7: "Receipt adds the `amount_cents` to the campaign's
    `base_raised_cents`, increments the campaign's `version` by one, and
    recomputes the board match: the attainment is `base_raised_cents` divided by
    `goal_cents`, rounded to four decimal places half-up before tier comparison,
    and the `match_pct` tier is 0 when attainment is below 0.50, 0.10 when
    attainment is exactly 0.50 or above but below 1.00, and 0.25 when attainment
    is exactly 1.00 or above."
    PRD §3.7: "While the campaign is live the match tier moves both up and down
    with attainment."
    PRD §3.7: "At close, `match_pct` and `matched_raised_cents` are frozen at
    their closing values; donations refunded after the close still reduce
    `base_raised_cents`, but the frozen fields are never recomputed."

    Design: Difficulty/dual_variant_calc/campaign_live_vs_frozen_match_after_close
    """
    world = fixtures.setup_association_and_branch(api)
    campaign = fixtures.create_campaign(api, world["association"]["id"], goal_cents=100_000)
    get_success_data(api.activate_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))

    # Live variant: 60,000 of 100,000 -> attainment 0.6000 -> match 0.10.
    donation = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=60_000, designation="GENERAL"
    )
    get_success_data(api.receive_donation(donation["id"], BRANCH_DIRECTOR_HEADERS))
    live = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_fraction(live["match_pct"], 0.10, "campaign.match_pct while ACTIVE")
    assert_cents(live["matched_raised_cents"], 66_000, "campaign.matched_raised_cents while ACTIVE")
    assert_cents(live["base_raised_cents"], 60_000, "campaign.base_raised_cents while ACTIVE")

    # Close with the observed version; the tier freezes.
    get_success_data(
        api.close_campaign(
            campaign["id"], {"expected_campaign_version": live["version"]}, ASSOCIATION_ADMIN_HEADERS
        )
    )

    # Refund after close: base drops to zero, frozen fields stay put.
    get_success_data(api.refund_donation(donation["id"], ASSOCIATION_ADMIN_HEADERS))
    closed = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_cents(closed["base_raised_cents"], 0, "campaign.base_raised_cents after post-close refund")
    assert_fraction(closed["match_pct"], 0.10, "campaign.match_pct frozen at close")
    assert_cents(closed["matched_raised_cents"], 66_000, "campaign.matched_raised_cents frozen at close")


def test_match_tier_moves_down_while_active_before_the_freeze(api):
    """The live variant moves down as well as up: a refund while ACTIVE that
    drops attainment below 0.50 recomputes the match tier back to 0.

    PRD §3.7: "Refund is the compensating action, restricted to
    `AssociationAdmin`. It subtracts the amount from `base_raised_cents` and
    increments the campaign `version`; while the campaign is still `ACTIVE` the
    match tier is recomputed from the reduced attainment."
    PRD §3.7: "While the campaign is live the match tier moves both up and down
    with attainment."

    Design: Difficulty/dual_variant_calc/campaign_live_vs_frozen_match_after_close
    """
    world = fixtures.setup_association_and_branch(api)
    campaign = fixtures.create_campaign(api, world["association"]["id"], goal_cents=100_000)
    get_success_data(api.activate_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))

    first = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=30_000, designation="GENERAL"
    )
    second = fixtures.create_donation(
        api, campaign["id"], world["branch"]["id"], amount_cents=30_000, designation="GENERAL"
    )
    get_success_data(api.receive_donation(first["id"], BRANCH_DIRECTOR_HEADERS))
    get_success_data(api.receive_donation(second["id"], BRANCH_DIRECTOR_HEADERS))
    raised = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_fraction(raised["match_pct"], 0.10, "campaign.match_pct at 0.6000 attainment")

    # Refund one gift while ACTIVE: attainment falls to 0.3000 and the tier moves down.
    get_success_data(api.refund_donation(second["id"], ASSOCIATION_ADMIN_HEADERS))
    reduced = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert_cents(reduced["base_raised_cents"], 30_000, "campaign.base_raised_cents after refund")
    assert_fraction(reduced["match_pct"], 0, "campaign.match_pct recomputed down while ACTIVE")
    assert_cents(reduced["matched_raised_cents"], 30_000, "campaign.matched_raised_cents after refund")

    # Close now; the frozen values are the post-refund ones.
    get_success_data(
        api.close_campaign(
            campaign["id"], {"expected_campaign_version": reduced["version"]}, ASSOCIATION_ADMIN_HEADERS
        )
    )
    closed = get_success_data(api.get_campaign(campaign["id"], ASSOCIATION_ADMIN_HEADERS))
    assert closed["status"] == "CLOSED"
    assert_fraction(closed["match_pct"], 0, "campaign.match_pct frozen at the live value")
