"""Compensating invariants: donor principal and match budget are conserved
across the forward action and its compensating actions."""

from test_helpers import (
    assert_campaign_budget_invariant,
    assert_cents,
    assert_donor_conservation,
    fixtures,
    validate_success,
)
from test_helpers.constants import FUNDING_DEADLINE


# ── Donor principal conservation ───────────────────────────────────────────


def _three_donation_world(api):
    """Dana's 4000 + 4000 + 2000 on one project, all CHOICE_PENDING after the
    expiry sweep; an ACTIVE TX equity fund with budget 50000."""
    world = fixtures.setup_expired_project(
        api, amounts=(4000, 4000, 2000), with_equity_fund=True
    )
    return world


def test_donor_conservation_holds_across_refund_and_reallocation(api):
    """Capture is the forward action; refund and reallocation are the two
    compensating actions, and the identity holds at every point.

    PRD: "For every donor, `lifetime_donated_cents` always equals the sum of `amount_cents` over that donor's donations currently in `CAPTURED` or `CHOICE_PENDING`, plus `lifetime_refunded_cents`, plus `lifetime_reallocated_cents`."
    Design: Difficulty/compensating_invariant/donor_conservation_across_refund_and_reallocation
    """
    world = _three_donation_world(api)
    donor = world["donor"]
    fund = world["equity_fund"]
    dn1, dn2, dn3 = world["donations"]

    validate_success(fixtures.donor_choice(api, dn1, donor, "REFUND"), 200)
    validate_success(
        fixtures.donor_choice(api, dn2, donor, "REALLOCATE", equity_fund_id=fund["id"]), 200
    )

    donor_after = fixtures.read_donor(api, donor["id"])
    assert_cents(donor_after["lifetime_donated_cents"], 10000, "lifetime never decreases")
    assert_cents(donor_after["lifetime_refunded_cents"], 4000, "refunded bucket")
    assert_cents(donor_after["lifetime_reallocated_cents"], 4000, "reallocated bucket")

    # dn3 is still CHOICE_PENDING, so 2000 remains in the active bucket.
    assert fixtures.read_donation(api, dn3["id"])["status"] == "CHOICE_PENDING"
    assert_donor_conservation(donor_after, active_amount_cents=2000)


def test_compensating_actions_move_the_project_and_fund_balances(api):
    """The same two choices move the project's funded_cents and the fund's
    remaining_cents by exactly the moved principal.

    PRD: "Choosing `REFUND` moves the donation to `REFUNDED` with `refund_reason` set to `EXPIRED_CHOICE`; the project's `funded_cents` decreases by `amount_cents` (and nothing more — the match left at expiry), and the donor's `lifetime_refunded_cents` increases by `amount_cents`."
    PRD: "On success the donation moves to `REALLOCATED` with its `equity_fund_id` set to the receiving fund, the fund's `remaining_cents` increases by `amount_cents`"
    Design: Difficulty/compensating_invariant/donor_conservation_across_refund_and_reallocation
    """
    world = _three_donation_world(api)
    donor = world["donor"]
    fund = world["equity_fund"]
    dn1, dn2, dn3 = world["donations"]

    validate_success(fixtures.donor_choice(api, dn1, donor, "REFUND"), 200)
    validate_success(
        fixtures.donor_choice(api, dn2, donor, "REALLOCATE", equity_fund_id=fund["id"]), 200
    )

    statuses = {d["id"]: d["status"] for d in fixtures.donations_for_donor(api, donor["id"])}
    assert statuses[dn1["id"]] == "REFUNDED"
    assert statuses[dn2["id"]] == "REALLOCATED"
    assert statuses[dn3["id"]] == "CHOICE_PENDING", "untouched by the other compensations"

    project = fixtures.read_project(api, world["project"]["id"])
    assert_cents(project["funded_cents"], 2000, "only dn3 still counts")
    fund_after = fixtures.read_equity_fund(api, fund["id"])
    assert_cents(fund_after["remaining_cents"], 54000, "50000 + 4000 reallocated")


# ── Match budget conservation ──────────────────────────────────────────────


def test_match_apply_conserves_the_campaign_budget(api):
    """Applying a match moves cents from remaining to matched-so-far; the sum
    is conserved.

    PRD: "The campaign's `matched_so_far_cents` grows by `matched_cents` and its `remaining_budget_cents` shrinks by the same amount"
    PRD: "For every match campaign, `budget_cents` always equals `matched_so_far_cents` plus `remaining_budget_cents`."
    Design: Difficulty/compensating_invariant/match_budget_conserved_across_apply_and_clawback
    """
    world = fixtures.setup_funding_project(api)
    campaign = fixtures.create_match_campaign(api, match_ratio=1.0, budget_cents=8000)
    donor = fixtures.create_donor(api)

    donation = fixtures.donate(api, world["project"]["id"], donor, 5000, campaign["id"])
    assert_cents(donation["matched_cents"], 5000, "ratio 1.0 on 5000c with 8000 headroom")

    after = fixtures.read_match_campaign(api, campaign["id"])
    assert_cents(after["matched_so_far_cents"], 5000, "matched_so_far after apply")
    assert_cents(after["remaining_budget_cents"], 3000, "remaining after apply")
    assert_campaign_budget_invariant(after)


def test_expiry_clawback_restores_the_campaign_budget(api):
    """The expiry clawback moves exactly the same cents back.

    PRD: "At the same moment each such donation's `matched_cents` is clawed back to its match campaign: the campaign's `matched_so_far_cents` decreases and its `remaining_budget_cents` increases by the same amount, and an `EXHAUSTED` campaign whose window is still open flips back to `ACTIVE`."
    PRD: "For every match campaign, `budget_cents` always equals `matched_so_far_cents` plus `remaining_budget_cents`."
    Design: Difficulty/compensating_invariant/match_budget_conserved_across_apply_and_clawback
    """
    world = fixtures.setup_funding_project(api)
    campaign = fixtures.create_match_campaign(api, match_ratio=1.0, budget_cents=8000)
    donor = fixtures.create_donor(api)
    donation = fixtures.donate(api, world["project"]["id"], donor, 5000, campaign["id"])

    fixtures.set_clock(api, FUNDING_DEADLINE)
    fixtures.run_sweep(api)

    after = fixtures.read_match_campaign(api, campaign["id"])
    assert_cents(after["matched_so_far_cents"], 0, "the 5000c match clawed back")
    assert_cents(after["remaining_budget_cents"], 8000, "budget restored")
    assert after["status"] == "ACTIVE", "window [2026-09-01, 2026-12-01) still covers now"
    assert_campaign_budget_invariant(after)

    donation_after = fixtures.read_donation(api, donation["id"])
    assert donation_after["status"] == "CHOICE_PENDING"
    assert_cents(donation_after["matched_cents"], 0, "the donation no longer carries the match")
