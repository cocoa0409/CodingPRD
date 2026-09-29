"""The side effects of a rejection, the states children are born into, and the two
endgames: automatic completion on the gold milestone and the conditional termination
cascade."""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_budget_summary,
    assert_fields_equal,
    assert_ledger,
    assert_payment_components,
    assert_pct_equals,
    assert_ratio_equals,
)
from test_helpers.constants import ALPHA_PASSING_METRICS
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_2,
    create_engagement,
    payment_of_milestone,
    read_milestone,
    record_accepted_review,
    setup_single_alpha,
    setup_single_gold,
    setup_twinpeak,
    submit_build,
    submit_invoice,
)
from prd_bench_local_runner.testing import validate_paginated, validate_success

GOLD_EXACT_METRICS = {
    "feature_completeness_pct": 100.00,
    "crash_free_sessions_pct": 99.50,
    "content_completeness_pct": 100.00,
    "known_blocker_count": 0,
}


def test_a_rejection_returns_the_milestone_and_supersedes_the_reviewed_build(api):
    """PRD §3.5: "A **rejection** sends the milestone back to the studio. It moves the
    milestone `UNDER_REVIEW → IN_DEVELOPMENT`, clears `open_condition_indexes` to an empty
    array and `cure_deadline_at` to null, and moves the reviewed build `PASSED →
    SUPERSEDED` so that it can never be reviewed again. Like a conditional verdict, a
    rejection creates no payment and moves no money." PRD §3.2 gives `cure_count` a birth
    value of 0 and only a conditional verdict increments it.

    Design: Corner/state_machines/corner_rejected_review_side_effects_return_the_milestone_and_supersede_the_build
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_2,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 4, ALPHA_PASSING_METRICS)

    review = validate_success(
        api.create_review(f.rejected_review_payload(build["id"], end_hour=12), reg.reviewer),
        201,
    )
    assert_fields_equal(review, {"verdict": "REJECTED", "cure_deadline_at": None}, "review")

    milestone = read_milestone(reg, scenario.m1["id"])
    assert_fields_equal(
        milestone,
        {"status": "IN_DEVELOPMENT", "open_condition_indexes": [],
         "cure_deadline_at": None, "cure_count": 0, "latest_build_number": 4},
        "milestone",
    )
    assert validate_success(api.get_build(build["id"], reg.dev))["gate_state"] == "SUPERSEDED"

    rows, meta = validate_paginated(
        api.list_payments(reg.finance, {"milestone_id": scenario.m1["id"]})
    )
    assert rows == [] and meta["total_count"] == 0
    agreement = scenario.read_agreement()
    assert agreement["status"] == "ACTIVE"
    assert_ledger(agreement, accepted_value_cents=0)


def test_an_engagement_is_born_active_only_when_its_milestone_is_already_open(api):
    """PRD §3.8: "A new engagement is born `PROPOSED` when its milestone is still
    `DEFINED`, and born `ACTIVE` when the milestone has already reached
    `IN_DEVELOPMENT`, `UNDER_REVIEW` or `CURE_PENDING` — in the latter case the engagement
    never uses the `PROPOSED → ACTIVE` promotion at all." The server "initialises
    `approved_invoice_total_cents` to 0".

    Design: Corner/state_machines/corner_engagement_and_invoice_start_in_their_declared_initial_states
    """
    scenario = setup_twinpeak(api)
    reg = scenario.reg
    assert read_milestone(reg, scenario.m1["id"])["status"] == "IN_DEVELOPMENT"
    assert read_milestone(reg, scenario.m2["id"])["status"] == "DEFINED"

    future = create_engagement(reg, scenario.m2["id"], "AUDIO-LARK", 300000,
                               "2026-09-01", "2026-10-15", "Adaptive music")
    now = create_engagement(reg, scenario.m1["id"], "ART-QUILL", 400000,
                            "2026-08-05", "2026-09-05", "Concept art")
    assert future["status"] == "PROPOSED"
    assert_fields_equal(now, {"status": "ACTIVE", "approved_invoice_total_cents": 0},
                        "engagement")

    invoice = submit_invoice(reg, now["id"], "QUILL-001", 150000)
    assert_fields_equal(
        invoice,
        {"status": "SUBMITTED", "decided_at": None, "rejection_reason": None},
        "invoice",
    )

    assert_budget_summary(
        validate_success(api.get_budget_summary(scenario.m1["id"], reg.dev)),
        scenario.m1["id"], budget=800000, committed_basis=400000, incurred_basis=0,
        available_committed=400000, overrun=0,
    )


def test_accepting_the_gold_milestone_completes_the_agreement_by_itself(api):
    """PRD §3.9: "The agreement then moves `ACTIVE → COMPLETED`,
    `post_launch_support_state` becomes `ACTIVE`, which is what unlocks live-operations
    funding, and the same rights settlement above writes `ip_reversion_state` and
    `sequel_rights_holder`. Payments already sitting in `PENDING_AUTHORIZATION` stay
    authorizable across this transition." A ratio "of 0.8000 or more sets
    `ip_reversion_state` to `RETAINED_BY_PUBLISHER` and `sequel_rights_holder` to
    `PUBLISHER`."

    Design: Corner/state_machines/corner_gold_acceptance_bubbles_the_agreement_up_to_completed
    """
    scenario = setup_single_gold(api, title="Sunset Cut", advance_total_cents=3000000,
                                live_ops_quarterly_funding_cents=400000)
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 1, GOLD_EXACT_METRICS)
    assert build["gate_state"] == "PASSED"
    assert_pct_equals(build["readiness_score"], 99.83, "readiness_score")

    record_accepted_review(reg, build["id"], end_hour=15)

    assert_fields_equal(
        read_milestone(reg, scenario.m1["id"]),
        {"status": "ACCEPTED", "accepted_at": "2026-08-01T00:00:00.000Z"},
        "milestone",
    )
    agreement = scenario.read_agreement()
    assert_fields_equal(
        agreement,
        {"status": "COMPLETED", "post_launch_support_state": "ACTIVE",
         "ip_reversion_state": "RETAINED_BY_PUBLISHER",
         "sequel_rights_holder": "PUBLISHER"},
        "agreement",
    )
    assert_ratio_equals(agreement["accepted_milestone_ratio"], 1.0000,
                        "accepted_milestone_ratio")

    payment = payment_of_milestone(reg, scenario.m1["id"])
    authorized = validate_success(
        api.authorize_payment(payment["id"], reg.finance, {"memo": "Gold payment"})
    )
    assert authorized["status"] == "AUTHORIZED"
    assert_payment_components(authorized, scheduled=3000000, overrun=0, gross=3000000,
                              holdback_bps=500, holdback=150000, net=2850000)


def test_termination_spares_the_accepted_milestone_and_scores_shared_rights(api):
    """PRD §3.9: "Step one cancels unfinished work: every milestone whose `status` is
    `DEFINED`, `IN_DEVELOPMENT`, `UNDER_REVIEW` or `CURE_PENDING` moves to `CANCELLED`."
    And: "A ratio of at least 0.5000 but strictly below 0.8000 sets `ip_reversion_state`
    to `PARTIAL_REVERSION` and `sequel_rights_holder` to `SHARED` — the band is inclusive
    at its lower edge, so a ratio of exactly 0.5000 yields shared rights rather than full
    reversion."

    Design: Corner/state_machines/corner_termination_only_cancels_non_terminal_milestones_and_scores_partial_reversion
    """
    scenario = setup_twinpeak(api)
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING_METRICS)
    record_accepted_review(reg, build["id"], end_hour=12)
    payment = payment_of_milestone(reg, scenario.m1["id"])
    assert read_milestone(reg, scenario.m2["id"])["status"] == "IN_DEVELOPMENT"

    terminated = validate_success(
        api.terminate_agreement(scenario.agreement_id, reg.finance,
                                {"reason": "Publisher exits the genre"})
    )
    assert_fields_equal(
        terminated,
        {"status": "TERMINATED", "funding_posture": "FROZEN",
         "terminated_at": "2026-08-01T00:00:00.000Z",
         "ip_reversion_state": "PARTIAL_REVERSION", "sequel_rights_holder": "SHARED"},
        "agreement",
    )
    assert_ratio_equals(terminated["accepted_milestone_ratio"], 0.5000,
                        "accepted_milestone_ratio")
    assert_ledger(terminated, committed_cents=3600000, available_funding_cents=2400000,
                  funding_pool_cents=6000000, withheld_payment_cents=3600000)

    assert read_milestone(reg, scenario.m1["id"])["status"] == "ACCEPTED"
    assert read_milestone(reg, scenario.m2["id"])["status"] == "CANCELLED"
    assert validate_success(
        api.get_payment(payment["id"], reg.finance)
    )["status"] == "WITHHELD"
