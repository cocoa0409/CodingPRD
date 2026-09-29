"""Two multi-level cascades out of a single request: the acceptance cascade whose
step four re-suspends what step two just promoted, and the termination cascade that
reaches the vendor's paperwork and then settles the rights position."""

from test_helpers.assertions import (
    assert_fields_equal,
    assert_ledger,
    assert_ratio_equals,
)
from test_helpers.fixtures import (
    create_engagement,
    payment_of_milestone,
    read_agreement,
    read_milestone,
    record_accepted_review,
    setup_aurora_drift,
    submit_build,
    submit_invoice,
)
from prd_bench_local_runner.testing import validate_success

ALPHA_PASSING = {
    "feature_completeness_pct": 75.00,
    "crash_free_sessions_pct": 96.00,
    "content_completeness_pct": 60.00,
    "known_blocker_count": 5,
}


def _accepted_alpha_with_downstream_engagements(api):
    """Engagements sit on the two not-yet-started milestones when M1 is accepted."""
    scenario = setup_aurora_drift(api)
    reg = scenario.reg
    e2 = create_engagement(
        reg, scenario.m2["id"], "NET-CORAL", 600000, "2026-09-01", "2026-10-31"
    )
    e3 = create_engagement(
        reg, scenario.m3["id"], "CERT-LUMEN", 400000, "2026-11-05", "2026-12-20"
    )
    assert e2["status"] == "PROPOSED" and e3["status"] == "PROPOSED"

    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING)
    record_accepted_review(reg, build["id"])
    return scenario, e2, e3


def test_acceptance_mints_the_payment_and_starts_the_dependent_milestone(api):
    """PRD §3.5: "Step one creates exactly one milestone payment in
    `PENDING_AUTHORIZATION` whose `scheduled_amount_cents` is the milestone's
    `funded_amount_cents` plus its `uplift_cents` frozen at the instant of
    acceptance. Step two, because this milestone became `ACCEPTED`, promotes every
    milestone whose `depends_on_milestone_id` points at it and whose `status` is still
    `DEFINED` from `DEFINED → IN_DEVELOPMENT`".

    Design: Difficulty/transitive_cascade/acceptance_cascade_unlocks_dependent_milestone_then_restricted_posture_resuspends_its_engagement
    """
    scenario, _e2, _e3 = _accepted_alpha_with_downstream_engagements(api)
    reg = scenario.reg

    m1 = read_milestone(reg, scenario.m1["id"])
    assert_fields_equal(
        m1, {"status": "ACCEPTED", "accepted_at": "2026-08-01T00:00:00.000Z"}, "M1"
    )

    payment = payment_of_milestone(reg, scenario.m1["id"])
    assert_fields_equal(
        payment,
        {"status": "PENDING_AUTHORIZATION", "scheduled_amount_cents": 3600000},
        "payment",
    )

    assert read_milestone(reg, scenario.m2["id"])["status"] == "IN_DEVELOPMENT"
    assert read_milestone(reg, scenario.m3["id"])["status"] == "DEFINED"


def test_the_restricted_posture_suspends_the_engagement_step_two_promoted(api):
    """PRD §3.5: "Step four, and only when the posture has become `RESTRICTED`, moves
    every contractor engagement of this agreement whose `status` is `PROPOSED` or
    `ACTIVE` and whose milestone's `status` is `DEFINED` or `IN_DEVELOPMENT` to
    `SUSPENDED`" and "step two runs before step four, so an engagement that step two
    has just promoted to `ACTIVE` can legitimately be suspended again by step four
    inside the same request."

    Design: Difficulty/transitive_cascade/acceptance_cascade_unlocks_dependent_milestone_then_restricted_posture_resuspends_its_engagement
    """
    scenario, e2, e3 = _accepted_alpha_with_downstream_engagements(api)
    reg = scenario.reg

    agreement = read_agreement(reg, scenario.agreement_id)
    assert agreement["accepted_value_cents"] == 3600000
    assert agreement["funding_posture"] == "RESTRICTED"

    assert validate_success(api.get_engagement(e2["id"], reg.dev))["status"] == "SUSPENDED"
    assert validate_success(api.get_engagement(e3["id"], reg.dev))["status"] == "SUSPENDED"


def test_the_acceptance_leaves_the_agreement_active_with_the_pool_committed(api):
    """PRD §3.5: "Step five, evaluated last of all after the funding ledger has been
    recomputed, tests the agreement for completion, as described in §3.9." No `GOLD`
    milestone has been accepted, so the deal stays live.

    Design: Difficulty/transitive_cascade/acceptance_cascade_unlocks_dependent_milestone_then_restricted_posture_resuspends_its_engagement
    """
    scenario, _e2, _e3 = _accepted_alpha_with_downstream_engagements(api)

    agreement = read_agreement(scenario.reg, scenario.agreement_id)
    assert agreement["status"] == "ACTIVE"
    assert_ledger(agreement, committed_cents=12000000, available_funding_cents=0)


def _terminated_after_one_acceptance(api):
    """M1 accepted with its payment left unauthorized, a live engagement on M2 and one
    unpaid vendor invoice, then the whole deal is torn up."""
    scenario = setup_aurora_drift(api)
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING)
    record_accepted_review(reg, build["id"])

    engagement = create_engagement(
        reg, scenario.m2["id"], "NET-CORAL", 600000, "2026-09-01", "2026-10-31"
    )
    assert engagement["status"] == "ACTIVE"
    invoice = submit_invoice(reg, engagement["id"], "CORAL-001", 200000, "2026-09-30")
    assert invoice["status"] == "SUBMITTED"
    payment = payment_of_milestone(reg, scenario.m1["id"])

    terminated = validate_success(
        api.terminate_agreement(
            scenario.agreement_id, reg.finance,
            {"reason": "Publisher exits the genre; project cancelled"},
        )
    )
    return scenario, terminated, engagement, invoice, payment


def test_termination_cancels_the_unfinished_milestones_and_freezes_the_posture(api):
    """PRD §3.9: termination "sets `status` to `TERMINATED`, forces `funding_posture`
    to `FROZEN` and stamps `terminated_at` from the logical clock ... Step one cancels
    unfinished work: every milestone whose `status` is `DEFINED`, `IN_DEVELOPMENT`,
    `UNDER_REVIEW` or `CURE_PENDING` moves to `CANCELLED`".

    Design: Difficulty/transitive_cascade/termination_cascade_cancels_milestones_withholds_payment_and_voids_contractor_invoice
    """
    scenario, terminated, _engagement, _invoice, _payment = _terminated_after_one_acceptance(api)
    reg = scenario.reg

    assert_fields_equal(
        terminated,
        {"status": "TERMINATED", "funding_posture": "FROZEN",
         "terminated_at": "2026-08-01T00:00:00.000Z"},
        "agreement",
    )
    assert read_milestone(reg, scenario.m2["id"])["status"] == "CANCELLED"
    assert read_milestone(reg, scenario.m3["id"])["status"] == "CANCELLED"
    assert read_milestone(reg, scenario.m1["id"])["status"] == "ACCEPTED"


def test_termination_withholds_the_payment_and_voids_the_vendor_invoice(api):
    """PRD §3.9: "Step two stops the money and the vendors: every milestone payment of
    the agreement whose `status` is `PENDING_AUTHORIZATION` or `HELD_PENDING_CURE`
    moves to `WITHHELD` ... and every contractor engagement of a now-cancelled
    milestone whose `status` is `PROPOSED`, `ACTIVE` or `SUSPENDED` moves to
    `TERMINATED_EARLY`. Step three, because those engagements were terminated early,
    moves each of their invoices still in `SUBMITTED` to `VOIDED`."

    Design: Difficulty/transitive_cascade/termination_cascade_cancels_milestones_withholds_payment_and_voids_contractor_invoice
    """
    scenario, _terminated, engagement, invoice, payment = _terminated_after_one_acceptance(api)
    reg = scenario.reg

    assert validate_success(api.get_payment(payment["id"], reg.finance))["status"] == "WITHHELD"
    assert validate_success(
        api.get_engagement(engagement["id"], reg.dev)
    )["status"] == "TERMINATED_EARLY"
    assert validate_success(api.get_invoice(invoice["id"], reg.dev))["status"] == "VOIDED"

    agreement = read_agreement(reg, scenario.agreement_id)
    assert_ledger(
        agreement, withheld_payment_cents=3600000, advance_disbursed_cents=0
    )


def test_the_reversion_ratio_keeps_the_cancelled_milestones_in_its_denominator(api):
    """PRD §3.9: "`accepted_milestone_ratio` is the count of the agreement's
    milestones whose `status` is `ACCEPTED` divided by the count of *all* milestones
    ever created for the agreement — every status, `CANCELLED` and `BREACHED`
    included — rounded half up to four decimal places" and "A ratio strictly below
    0.5000 sets `ip_reversion_state` to `REVERTED_TO_DEVELOPER` and
    `sequel_rights_holder` to `DEVELOPER`".

    Design: Difficulty/transitive_cascade/termination_cascade_cancels_milestones_withholds_payment_and_voids_contractor_invoice
    """
    scenario, _terminated, _engagement, _invoice, _payment = _terminated_after_one_acceptance(api)

    agreement = read_agreement(scenario.reg, scenario.agreement_id)
    assert_ratio_equals(agreement["accepted_milestone_ratio"], 0.3333, "ratio")
    assert_fields_equal(
        agreement,
        {"ip_reversion_state": "REVERTED_TO_DEVELOPER", "sequel_rights_holder": "DEVELOPER"},
        "agreement",
    )
    assert_ledger(agreement, committed_cents=3600000, available_funding_cents=8400000)
