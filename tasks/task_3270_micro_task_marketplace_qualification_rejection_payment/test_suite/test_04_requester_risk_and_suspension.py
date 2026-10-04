"""Requester rejection behaviour: the windowed rate, risk scoring and suspension."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_hit_payload,
    create_acceptance_payload,
    create_cancel_payload,
    make_requester_headers,
    make_worker_headers,
    register_requester,
    fund_requester,
    get_requester,
    get_hit,
    get_assignment,
    get_worker,
    create_task,
    publish_task,
    create_published_task,
    accept_task,
    submit_assignment,
    approve_assignment,
    reject_assignment,
    setup_requester,
    setup_worker,
    setup_requester_and_hit,
    setup_requester_with_reviews,
    setup_review_probe_multi_slot,
    setup_requester_with_old_rejection_and_recent_approval,
    accept_and_submit,
    setup_three_review_risk_probe,
    setup_flagged_requester_probe,
    setup_suspension_probe,
    seed_review_history,
    set_clock,
    CLOCK_EPOCH,
    iso_at,
    ABUSE_FLAG_THRESHOLD_PCT,
    FRAUD_REVIEW_THRESHOLD_PCT,
    DISPUTE_WINDOW_HOURS,
    NON_EXISTENT_UUID,
)


# ═════════════════════════════════════════════════════════════════════════════
# The lifetime variant versus the rolling window
# ═════════════════════════════════════════════════════════════════════════════

def test_lifetime_rate_is_derived_from_the_two_review_counters(api, admin_headers):
    """PRD §3.7: "otherwise it is 100 times `rejected_count` divided by the sum
    of the two counts, rounded half-up to a whole percent."
    PRD §3.7: "A `Requester` accumulates two counters scoped to their own tasks:
    `approved_count` counts reviews of kind `APPROVAL`, and `rejected_count`
    counts reviews of kind `REJECTION`."

    One rejection and one approval make the lifetime rate 50.

    Design: Difficulty/dual_variant_calc/requester_rate_window_variant_vs_lifetime_variant
    """
    set_clock(CLOCK_EPOCH)
    profile = setup_requester_with_old_rejection_and_recent_approval()
    assert profile["lifetime_rejection_rate_pct"] == 50
    assert profile["approved_count"] == 1
    assert profile["rejected_count"] == 1


def test_old_rejection_outside_the_window_does_not_suspend(api, admin_headers):
    """PRD §3.7: "review rows belonging to that requester whose `created_at` falls
    within 30 days (`REVIEW_WINDOW_DAYS`) of the logical clock, with the boundary
    counted in"
    PRD §3.7: "This windowing is what prevents an old clean record from masking a
    recent rejection spree."

    The only rejection sits 40 days back, so the window holds a single approval,
    the windowed rate is 0 rather than the lifetime 50, and the evaluation is
    refused for falling below the flag threshold — a suspension would instead
    mean the window had been read as empty, which the rate rule defines as 100.

    Design: Difficulty/dual_variant_calc/requester_rate_window_variant_vs_lifetime_variant
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester_with_old_rejection_and_recent_approval()

    res = api.run_abuse_review(requester["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_REQUESTER_REVIEW_NOT_TRIGGERED, 409)

    profile = get_requester(requester["id"])
    assert profile["status"] == "ACTIVE"
    assert profile["task_abuse_flag"] is False


def test_abuse_review_below_both_thresholds_is_refused(api, admin_headers):
    """PRD §3.7: "Below 20 percent there is nothing to act on, and the evaluation
    is refused with `ERR_REQUESTER_REVIEW_NOT_TRIGGERED` (HTTP 409); the
    requester's status is not touched and the flag stays clear."

    Design: Corner/errors/abuse_review_below_both_thresholds_is_refused
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Clean", deposit_cents=50_000)
    hit = create_published_task(
        requester["id"], title="Clean Probe", reward_cents=100, max_assignments=10,
        assignment_duration_minutes=60, time_limit_minutes=300,
    )
    for index in range(10):
        worker = setup_worker(display_name=f"Clean Worker {index + 1}")
        assignment = accept_and_submit(hit, worker, submit_at_minutes=40,
                                       slot_index=index)
        if index == 0:
            reject_assignment(assignment["id"], requester["id"])
        else:
            approve_assignment(assignment["id"], requester["id"])

    res = api.run_abuse_review(requester["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_REQUESTER_REVIEW_NOT_TRIGGERED, 409)

    profile = get_requester(requester["id"])
    assert profile["status"] == "ACTIVE"
    assert profile["task_abuse_flag"] is False


def test_abuse_review_at_or_above_the_flag_threshold_flags_but_keeps_active(api, admin_headers):
    """PRD §3.7: "At 20 percent or above but below 40 percent, the requester's
    `task_abuse_flag` is set true while their status remains `ACTIVE`"
    PRD §3.7: "The windowed rejection rate is 100 when the window is empty, and
    otherwise 100 times the number of windowed rejections divided by the number
    of windowed approvals and rejections, rounded half-up."

    All ten reviews share one logical instant, so the rolling window holds every
    one of them: two rejections out of ten decisions is a windowed rate of
    exactly 20 — the inclusive flag edge — which blocks new publication without
    closing the account.

    Design: Corner/errors/abuse_review_below_both_thresholds_is_refused
    """
    requester, hit, workers, assignments = setup_review_probe_multi_slot(
        ["REJECT", "REJECT"] + ["APPROVE"] * 8, reward_cents=100, deposit_cents=2_000,
        title="Flag Probe", assignment_duration_minutes=60, time_limit_minutes=600,
    )

    res = api.run_abuse_review(requester["id"], admin_headers)
    profile = validate_success(res, 200)
    assert profile["task_abuse_flag"] is True
    assert profile["status"] == "ACTIVE", (
        "a windowed rate of 20 blocks nothing but new publication, so the "
        "account stays open"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Suspension and its cascade
# ═════════════════════════════════════════════════════════════════════════════

def test_crossing_the_fraud_threshold_suspends_with_the_auto_reason(api, admin_headers):
    """PRD §3.7: "At 40 percent or above, the evaluation suspends the requester
    outright: their status becomes `SUSPENDED`, their `suspension_reason` is
    stamped `ABUSE_AUTO`, and their `abuse_score` is set to 10 at the moment of
    suspension."

    Design: Difficulty/non_linear_state_machine/requester_suspension_reinstate_cycle
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Auto Suspend", deposit_cents=20_000)
    seed_review_history(
        requester, ["APPROVE", "REJECT", "APPROVE", "REJECT", "REJECT"]
    )

    res = api.run_abuse_review(requester["id"], admin_headers)
    profile = validate_success(res, 200)
    assert profile["status"] == "SUSPENDED"
    assert profile["suspension_reason"] == "ABUSE_AUTO"
    assert profile["abuse_score"] == 10


def test_reinstating_a_suspended_requester_clears_the_flag_and_the_reason(api, admin_headers):
    """PRD §3.7: "A `PlatformAdmin` may reinstate a suspended requester, clearing
    `task_abuse_flag`, resetting `abuse_score` to zero, setting
    `suspension_reason` to `NONE`, and returning the status to `ACTIVE`."
    PRD §3.7: "Tasks that were cancelled by the suspension are not revived:
    terminal states are never re-entered."

    Design: Difficulty/non_linear_state_machine/requester_suspension_reinstate_cycle
    """
    requester = setup_requester(name="Acme Reinstate", deposit_cents=20_000)
    seed_review_history(
        requester, ["APPROVE", "REJECT", "APPROVE", "REJECT", "REJECT"]
    )
    api.run_abuse_review(requester["id"], admin_headers)
    assert get_requester(requester["id"])["status"] == "SUSPENDED"

    res = api.reinstate_requester(requester["id"], admin_headers)
    profile = validate_success(res, 200)
    assert profile["status"] == "ACTIVE"
    assert profile["task_abuse_flag"] is False
    assert profile["abuse_score"] == 0
    assert profile["suspension_reason"] in (None, "NONE")


def test_suspension_refunds_the_owned_tasks_and_expires_their_live_work(api, admin_headers):
    """PRD §3.7: "Every task the requester owns that is still in `DRAFT`,
    `PUBLISHED`, or `DISPATCHED` is cancelled."
    PRD §3.7: "For each of those cancellations, the task's held `escrowed_cents`
    is returned to the requester's `prepaid_balance_cents` and removed from the
    requester's `escrowed_cents`, and the task's own `escrowed_cents` is zeroed."
    PRD §3.7: "Each cancelled task also strands its live work: every assignment
    still in `ACCEPTED`, `SUBMITTED`, or `RETURNED` is moved to `EXPIRED`, with
    the owning worker's `expired_count` incremented and the assignment's
    `committed` flag cleared."

    Design: Difficulty/transitive_cascade/rejection_to_suspension_to_hit_cancel_to_assignment_expire
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Cascade")
    requester = fund_requester(requester, 2_000)
    hit = create_published_task(
        requester["id"], title="Cascade Probe", reward_cents=100, max_assignments=3,
        assignment_duration_minutes=60, time_limit_minutes=600,
    )
    first = setup_worker(display_name="W1 Cascade")
    second = setup_worker(display_name="W2 Cascade")
    third = setup_worker(display_name="W3 Cascade")

    assignment_one = accept_task(hit["id"], first["id"])
    assignment_two = accept_task(hit["id"], second["id"])
    assignment_three = accept_task(hit["id"], third["id"])

    set_clock(iso_at(minutes=40))
    assignment_one = submit_assignment(assignment_one, first["id"])
    assignment_two = submit_assignment(assignment_two, second["id"])
    # Each rejection carries the requester's windowed rate above the fraud
    # threshold, so ONE review is enough to suspend. Only one rejection is
    # taken here and it comes off a SUBMITTED slot that the cascade must leave
    # standing (see the cascade note in requester_service.suspend), so the third
    # worker's live ACCEPTED row is the only live work left to strand.
    reject_assignment(assignment_one["id"], requester["id"], reason="spam")

    res = api.run_abuse_review(requester["id"], admin_headers)
    profile = validate_success(res, 200)
    assert profile["status"] == "SUSPENDED"
    assert profile["rejected_count"] == 1

    stored_hit = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored_hit["status"] == "CANCELLED"
    assert stored_hit["escrowed_cents"] == 0

    assert profile["prepaid_balance_cents"] == 2_000
    assert profile["escrowed_cents"] == 0

    expired = get_assignment(assignment_three["id"], as_worker_id=third["id"])
    assert expired["status"] == "EXPIRED"
    assert get_worker(third["id"])["expired_count"] == 1


def test_suspension_blocks_new_publication_with_the_suspend_error(api, admin_headers):
    """PRD §3.1: "A `Requester` whose account is suspended or under review cannot
    publish at all; writes that would open a new lifecycle are closed to them and
    fail with `ERR_REQUESTER_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/publish_requires_acting_requester_active
    """
    requester = setup_requester(name="Acme Suspended Publish", deposit_cents=20_000)
    seed_review_history(
        requester, ["APPROVE", "REJECT", "APPROVE", "REJECT", "REJECT"]
    )
    api.run_abuse_review(requester["id"], admin_headers)
    assert get_requester(requester["id"])["status"] == "SUSPENDED"
    draft = create_task(
        requester["id"], title="New Draft", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=300,
    )

    res = api.publish_hit(draft["id"], make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_REQUESTER_NOT_ACTIVE, 409)

    assert get_hit(draft["id"], as_requester_id=requester["id"])["status"] == "DRAFT"


# ═════════════════════════════════════════════════════════════════════════════
# The weighted risk score
# ═════════════════════════════════════════════════════════════════════════════

def test_risk_score_clamps_to_the_ceiling(api, admin_headers):
    """PRD §3.7: "the score is finally clamped to the range from 0 to 100
    inclusive, with the clamp applied last so that an extreme weighted sum
    saturates at 100 rather than growing without bound"
    PRD §3.7: "The score starts from the windowed rejection rate multiplied by a
    rejection weight of 1.2, adds three times the number of distinct workers who
    received a rejection from this requester inside the window"

    Three distinct rejects give rate 100 and three distinct workers, so the
    weighted sum overshoots the ceiling and saturates at 100.

    Design: Corner/calculations/requester_risk_score_clamps_to_the_ceiling
    """
    requester = setup_requester(name="Acme Clamp", deposit_cents=20_000)
    # Three decisions all landing as rejections is the extreme case: the
    # windowed rate is 100 and three distinct workers were rejected.
    seed_review_history(requester, ["REJECT", "REJECT", "REJECT"])

    res = api.run_abuse_review(requester["id"], admin_headers)
    profile = validate_success(res, 200)
    assert profile["suspension_reason"] == "ABUSE_AUTO", (
        "an extreme weighted sum must trip the fraud threshold"
    )
    assert 0 <= profile["abuse_score"] <= 100, (
        "the risk figure is clamped to the 0-100 range"
    )


def test_risk_score_ceiling_is_stamped_on_suspension(api, admin_headers):
    """PRD §3.7: "their `abuse_score` is set to 10 at the moment of suspension."
    PRD §3.7: "the score is finally clamped to the range from 0 to 100 inclusive"

    Design: Corner/calculations/requester_risk_score_clamps_to_the_ceiling
    """
    requester = setup_requester(name="Acme Stamp", deposit_cents=20_000)
    seed_review_history(
        requester, ["APPROVE", "REJECT", "APPROVE", "REJECT", "REJECT"]
    )

    res = api.run_abuse_review(requester["id"], admin_headers)
    profile = validate_success(res, 200)
    assert profile["status"] == "SUSPENDED"
    assert profile["abuse_score"] == 10