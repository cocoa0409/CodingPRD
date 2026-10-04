"""Transitive cascades: fraud confirmation unwinds a whole pipeline, and the
expiration sweep runs its two donation phases across two runs."""

from test_helpers import (
    ADMIN_HEADERS,
    assert_cents,
    assert_instant,
    fixtures,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.constants import CHOICE_DEADLINE, FUNDING_DEADLINE


# ── Fraud confirmation: a four-deep clawback cascade ───────────────────────


def _funded_world_with_matched_donation(api):
    """FUNDED project (goal 10959): a 5000c donation matched 1:1 by an ACTIVE
    TX campaign, then a 959c plain donation; the single PO shipped and was
    diversion-reported, leaving an OPEN fraud case."""
    world = fixtures.setup_funding_project(api)
    campaign = fixtures.create_match_campaign(api, match_ratio=1.0, budget_cents=100000)
    donor = fixtures.create_donor(api)
    d1 = fixtures.donate(api, world["project"]["id"], donor, 5000, campaign["id"])
    d2 = fixtures.donate(api, world["project"]["id"], donor, 959)
    world.update(campaign=campaign, donor=donor, donations=[d1, d2])
    world["project"] = fixtures.read_project(api, world["project"]["id"])
    assert world["project"]["status"] == "FUNDED"

    po = fixtures.purchase_orders_for(api, world["project"]["id"])[0]
    fixtures.ship_purchase_order(api, po)
    fixtures.report_diversion(api, po["id"])
    world["po"] = po
    world["fraud_case"] = fixtures.fraud_cases_for_teacher(api, world["teacher"]["id"])[0]
    return world


def test_fraud_confirmation_suspends_cancels_and_refunds(api):
    """CONFIRMED fires the cascade: teacher, then pipeline, then donations.

    PRD: "`CONFIRMED` moves it to `CONFIRMED` and fires the full clawback cascade, in this fixed order:"
    PRD: "1. The teacher transitions to `SUSPENDED`."
    PRD: "2. Every project of that teacher in `DRAFT`, `IN_REVIEW`, `VETTING`, `RETURNED`, `FUNDING`, or `FUNDED` transitions to `CANCELLED`, processed in project `created_at` ascending order."
    PRD: "3. For each project cancelled out of `FUNDING` or `FUNDED`, every donation in `CAPTURED` or `CHOICE_PENDING` transitions to `REFUNDED` with `refund_reason` set to `FRAUD_CLAWBACK`: the donor's `lifetime_refunded_cents` increases by `amount_cents`, and the project's `funded_cents` decreases by `amount_cents` plus `matched_cents`."
    Design: Difficulty/transitive_cascade/fraud_confirm_cascade_suspends_and_claws_back
    """
    world = _funded_world_with_matched_donation(api)
    case = world["fraud_case"]
    assert case["status"] == "OPEN"

    resolved = validate_success(
        api.resolve_fraud_case(case["id"], f.fraud_resolve_payload("CONFIRMED"), ADMIN_HEADERS),
        200,
    )
    assert resolved["status"] == "CONFIRMED"

    # Link 1: the teacher is suspended.
    teacher = fixtures.read_teacher(api, world["teacher"]["id"])
    assert teacher["employment_status"] == "SUSPENDED"

    # Link 2: the FUNDED project is cancelled.
    project = fixtures.read_project(api, world["project"]["id"])
    assert project["status"] == "CANCELLED"
    assert_cents(project["funded_cents"], 0, "funded_cents after clawback")

    # Link 3: both donations refund with the fraud reason.
    for donation, _amount in zip(world["donations"], (5000, 959)):
        after = fixtures.read_donation(api, donation["id"])
        assert after["status"] == "REFUNDED"
        assert after["refund_reason"] == "FRAUD_CLAWBACK"

    donor = fixtures.read_donor(api, world["donor"]["id"])
    assert_cents(donor["lifetime_refunded_cents"], 5959, "lifetime_refunded_cents")
    assert_cents(donor["lifetime_donated_cents"], 5959, "lifetime_donated_cents")


def test_fraud_confirmation_claws_the_match_back_and_keeps_the_evidence(api):
    """The match returns to the campaign; the reported PO stays as evidence.

    PRD: "4. Each refunded donation's `matched_cents` returns to its match campaign — `matched_so_far_cents` decreases and `remaining_budget_cents` increases by the same amount — and an `EXHAUSTED` campaign whose window is still open flips back to `ACTIVE`."
    PRD: "5. Each purchase order of those projects in `ISSUED` or `SHIPPED` transitions to `CANCELLED`; orders already `DELIVERED` or `DIVERSION_REPORTED` are left untouched as the evidence trail."
    Design: Difficulty/transitive_cascade/fraud_confirm_cascade_suspends_and_claws_back
    """
    world = _funded_world_with_matched_donation(api)
    campaign_id = world["campaign"]["id"]

    before = fixtures.read_match_campaign(api, campaign_id)
    assert_cents(before["matched_so_far_cents"], 5000, "matched_so_far before")
    assert_cents(before["remaining_budget_cents"], 95000, "remaining before")

    validate_success(
        api.resolve_fraud_case(
            world["fraud_case"]["id"], f.fraud_resolve_payload("CONFIRMED"), ADMIN_HEADERS
        ),
        200,
    )

    # Link 4: the 5000c match is clawed back into the campaign budget.
    after = fixtures.read_match_campaign(api, campaign_id)
    assert_cents(after["matched_so_far_cents"], 0, "matched_so_far after")
    assert_cents(after["remaining_budget_cents"], 100000, "remaining after")
    assert after["status"] == "ACTIVE"

    # The evidence PO is DIVERSION_REPORTED and must not be cancelled.
    po = fixtures.read_purchase_order(api, world["po"]["id"])
    assert po["status"] == "DIVERSION_REPORTED"


# ── Expiration sweep: two phases across two runs ───────────────────────────


def _funding_world_with_donation(api):
    world = fixtures.setup_funding_project(api)
    donor = fixtures.create_donor(api)
    donation = fixtures.donate(api, world["project"]["id"], donor, 5000)
    world.update(donor=donor, donation=donation)
    return world


def test_sweep_expires_at_deadline_and_opens_the_choice_window(api):
    """Phase 1: a project whose deadline equals now expires; its donations go
    CHOICE_PENDING with a fourteen-day choice window.

    PRD: "Every project in `FUNDING` whose `funding_deadline` is at or before now transitions to `EXPIRED` — the boundary is inclusive, so a project whose deadline equals now expires in this run."
    PRD: "Each `CAPTURED` donation on each expired project moves to `CHOICE_PENDING` with `choice_deadline` set to the sweep timestamp plus 14 days"
    PRD: "The sweep response summarizes the run with five lists: `expired_project_ids`, `choice_pending_donation_ids`, `auto_refunded_donation_ids`, `closed_match_campaign_ids`, and `closed_equity_fund_ids`."
    Design: Difficulty/transitive_cascade/expiration_sweep_two_phase_cascade
    """
    world = _funding_world_with_donation(api)
    project_id = world["project"]["id"]
    donation_id = world["donation"]["id"]

    # The clock lands exactly on the funding deadline: the boundary is inclusive.
    fixtures.set_clock(api, FUNDING_DEADLINE)
    summary = fixtures.run_sweep(api)

    assert project_id in summary["expired_project_ids"]
    assert donation_id in summary["choice_pending_donation_ids"]
    assert summary["auto_refunded_donation_ids"] == []

    project = fixtures.read_project(api, project_id)
    assert project["status"] == "EXPIRED"

    donation = fixtures.read_donation(api, donation_id)
    assert donation["status"] == "CHOICE_PENDING"
    assert_instant(donation["choice_deadline"], CHOICE_DEADLINE, "choice_deadline")
    # A CHOICE_PENDING donation still counts toward funded_cents.
    assert_cents(project["funded_cents"], 5000, "funded_cents while choice pending")


def test_second_sweep_auto_refunds_at_the_choice_deadline(api):
    """Phase 2: a donation whose choice_deadline equals now auto-refunds.

    PRD: "Every donation still in `CHOICE_PENDING` whose `choice_deadline` is at or before now — equality auto-refunds — transitions to `REFUNDED` with `refund_reason` set to `EXPIRED_AUTO`, processed in `choice_deadline` ascending order, ties broken by `created_at` ascending."
    Design: Difficulty/transitive_cascade/expiration_sweep_two_phase_cascade
    """
    world = _funding_world_with_donation(api)
    project_id = world["project"]["id"]
    donation_id = world["donation"]["id"]

    fixtures.set_clock(api, FUNDING_DEADLINE)
    fixtures.run_sweep(api)

    # Advance to the exact choice deadline and sweep again: equality refunds.
    fixtures.set_clock(api, CHOICE_DEADLINE)
    summary = fixtures.run_sweep(api)

    assert donation_id in summary["auto_refunded_donation_ids"]

    donation = fixtures.read_donation(api, donation_id)
    assert donation["status"] == "REFUNDED"
    assert donation["refund_reason"] == "EXPIRED_AUTO"

    donor = fixtures.read_donor(api, world["donor"]["id"])
    assert_cents(donor["lifetime_refunded_cents"], 5000, "lifetime_refunded_cents")

    project = fixtures.read_project(api, project_id)
    assert project["status"] == "EXPIRED"
    assert_cents(project["funded_cents"], 0, "funded_cents after auto-refund")
