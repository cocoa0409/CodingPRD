"""Submission, review, disputes and the bonus window."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    create_submission_payload,
    create_rejection_payload,
    create_dispute_payload,
    create_bonus_payload,
    create_resolution_payload,
    make_requester_headers,
    make_worker_headers,
    get_hit,
    get_assignment,
    get_worker,
    list_assignment_reviews,
    submit_assignment,
    approve_assignment,
    reject_assignment,
    dispute_assignment,
    admin_resolve,
    pay_bonus,
    setup_review_probe,
    setup_submitted_assignment,
    setup_rejected_assignment,
    setup_disputed_assignment,
    setup_half_window_probe,
    setup_upturned_dispute,
    setup_submitted_assignment_with_budget,
    setup_requester_and_hit,
    setup_worker,
    accept_task,
    set_clock,
    advance_clock,
    CLOCK_EPOCH,
    iso_at,
    iso_out,
)


# ═════════════════════════════════════════════════════════════════════════════
# Submission
# ═════════════════════════════════════════════════════════════════════════════

def test_submission_opens_the_seventy_two_hour_review_window(api, admin_headers):
    """PRD §3.4: "On success the platform stamps `submitted_at` with the current
    logical instant and sets `review_expires_at` to that instant plus 72 hours —
    `REVIEW_WINDOW_HOURS`"
    PRD §2.5: "Both timestamps are ISO 8601 UTC strings with exactly three
    fractional digits"

    Design: Corner/entities/review_rows_are_append_only_and_carry_the_requester_actor
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_review_probe(
        decision=None, submit_at_minutes=40, title="Submit Probe",
    )
    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["submitted_at"] == iso_out(minutes=40)
    assert stored["review_expires_at"] == iso_out(minutes=40, hours=72)


def test_submission_with_a_stale_assignment_version_is_refused(api, admin_headers):
    """PRD §2.7: "submitting an assignment requires `expected_assignment_version`
    to equal the assignment's current `version`"
    PRD §2.7: "If that value does not equal the task's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_hit_version_sweep_is_rejected_with_stale_version
    """
    set_clock(CLOCK_EPOCH)
    requester, hit = setup_requester_and_hit(
        reward_cents=100, max_assignments=1, assignment_duration_minutes=60,
        time_limit_minutes=300, name="Acme Stale Submit",
    )
    worker = setup_worker()
    assignment = accept_task(hit["id"], worker["id"])
    submit_assignment(assignment, worker["id"])

    res = api.submit_assignment(
        assignment["id"],
        create_submission_payload(assignment["version"] - 1),
        make_worker_headers(worker["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)


# ═════════════════════════════════════════════════════════════════════════════
# The half-window approval gate
# ═════════════════════════════════════════════════════════════════════════════

def test_approval_before_the_half_window_is_refused(api, admin_headers):
    """PRD §3.4: "an assignment is only approvable once the elapsed time since
    acceptance has reached at least half of the task's
    `assignment_duration_minutes`"
    PRD §3.4: "approval attempted before it turns true is refused with
    `ERR_REVIEW_TOO_EARLY` (HTTP 409)."

    Design: Corner/calculations/assignment_half_window_boundary_is_inclusive
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_half_window_probe(
        assignment_duration_minutes=60, submit_at_minutes=29,
    )

    res = api.approve_assignment(assignment["id"], make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_REVIEW_TOO_EARLY, 409)


def test_approval_at_exactly_the_half_window_is_allowed(api, admin_headers):
    """PRD §3.4: "the comparison is at least, so an assignment that has elapsed
    exactly half the window is already approvable — a strict reading would
    wrongly reject the boundary case."
    PRD §3.4: "The flag that carries this verdict is `eligible_for_approval`"

    Design: Corner/calculations/assignment_half_window_boundary_is_inclusive
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_half_window_probe(
        assignment_duration_minutes=60, submit_at_minutes=29,
    )
    advance_clock(iso_at(minutes=30))

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["eligible_for_approval"] is True

    res = api.approve_assignment(assignment["id"], make_requester_headers(requester["id"]))
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"


# ═════════════════════════════════════════════════════════════════════════════
# Terminal-state lockdown on the review loop
# ═════════════════════════════════════════════════════════════════════════════

def test_submitting_again_after_approval_is_refused(api, admin_headers):
    """PRD §3.4: "Approval is the requester's acceptance of submitted work, and it
    moves the assignment from `SUBMITTED` to `APPROVED`, a terminal state."
    PRD §2.10: "4. **State** (`ERR_INVALID_STATE`, HTTP 409) — the target resource
    sits in a state from which the requested transition is declared."

    APPROVED is terminal, so the repeat submission never fires. The exact error
    identifier is not pinned: the presented version is also stale by then, and
    the PRD's ladder orders optimistic concurrency (step 8) below state (step
    4) without stating which wins when both are violated — a PRD-faithful
    implementation may answer with either. The test therefore pins that the
    submission is refused AND that the terminal row is untouched, which both
    readers agree on.

    Design: Corner/state_machines/assignment_submit_after_approval_returns_invalid_state
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_submitted_assignment(
        title="Invalid Probe", deposit_cents=1_000,
    )
    approve_assignment(assignment["id"], requester["id"])

    res = api.submit_assignment(
        assignment["id"],
        create_submission_payload(assignment["version"]),
        make_worker_headers(worker["id"]),
    )
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_STALE_VERSION]
    )

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "APPROVED"
    assert get_worker(worker["id"])["approved_count"] == 1


def test_rejection_after_approval_is_refused_and_appends_no_review(api, admin_headers):
    """PRD §3.4: "Mirroring approval's structural gate, an assignment that already
    carries an approval cannot then be rejected — `ERR_INVALID_STATE`."

    Design: Corner/state_machines/assignment_reject_after_approval_returns_invalid_state
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_submitted_assignment(
        title="Terminal Probe", deposit_cents=1_000,
    )
    approve_assignment(assignment["id"], requester["id"])

    res = api.reject_assignment(
        assignment["id"], create_rejection_payload(reason="changed my mind"),
        make_requester_headers(requester["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    reviews = list_assignment_reviews(assignment["id"], as_requester_id=requester["id"])
    assert len(reviews) == 1, "the terminal state must lock the review loop closed"
    worker_profile = get_worker(worker["id"])
    assert worker_profile["approved_count"] == 1
    assert worker_profile["rejected_count"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Rejection requires a reason
# ═════════════════════════════════════════════════════════════════════════════

def test_rejection_without_a_reason_is_refused_before_anything_is_written(api, admin_headers):
    """PRD §3.4: "The rejection body must carry a non-empty `reason`; an empty or
    missing one is refused with `ERR_REJECTION_REASON_REQUIRED` (HTTP 400)."

    Design: Corner/validations/reject_without_reason_returns_rejection_reason_required
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_submitted_assignment(
        title="Reason Probe", deposit_cents=1_000,
    )

    res = api.reject_assignment(
        assignment["id"], create_rejection_payload(reason=""),
        make_requester_headers(requester["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REJECTION_REASON_REQUIRED, 400)

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "SUBMITTED"
    assert get_worker(worker["id"])["rejected_count"] == 0
    assert list_assignment_reviews(assignment["id"], as_requester_id=requester["id"]) == []


def test_approving_appends_one_requester_attributed_review(api, admin_headers):
    """PRD §3.4: "it appends a `Review` row of `kind` `APPROVAL` attributed to the
    acting `actor_requester_id` with an `actor_role` of `REQUESTER`."
    PRD §3.9: "a `bonus_cents` amount that is zero for everything except a bonus"

    Design: Corner/entities/review_rows_are_append_only_and_carry_the_requester_actor
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_review_probe(
        decision="APPROVE", title="Review Probe", deposit_cents=1_000,
    )

    reviews = list_assignment_reviews(assignment["id"], as_requester_id=requester["id"])
    assert len(reviews) == 1
    review = reviews[0]
    assert review["kind"] == "APPROVAL"
    assert review["actor_role"] == "REQUESTER"
    assert review["actor_requester_id"] == requester["id"]
    assert review["bonus_cents"] == 0
    assert review["abuse_points"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Disputes and administrative resolution
# ═════════════════════════════════════════════════════════════════════════════

def test_a_dispute_does_not_undo_the_rejection_damage(api, admin_headers):
    """PRD §3.5: "The originating rejection review is not withdrawn, and the
    worker's `rejected_count` stays exactly as the rejection left it — a dispute
    opens an appeal, it does not undo the damage while the appeal is pending."

    Design: Difficulty/non_linear_state_machine/assignment_reject_dispute_resolve_branch_and_rejoin
    """
    requester, hit, worker, assignment = setup_rejected_assignment(
        title="Dispute Damage Probe", deposit_cents=1_000,
    )
    assert get_worker(worker["id"])["rejected_count"] == 1

    # The rejection is at most a few minutes old and DISPUTE_WINDOW_HOURS spans
    # hours, so the appeal is comfortably inside the window. The clock is not
    # rewound here: containing the rejection (and thus the rolling-window
    # population it feeds) inside the window the requester's rate is measured
    # over is a precondition of the surrounding narrative.
    disputed = dispute_assignment(assignment["id"], worker["id"])
    assert disputed["status"] == "DISPUTED"
    assert get_worker(worker["id"])["rejected_count"] == 1


def test_an_uphold_resolution_returns_the_assignment_to_rejected(api, admin_headers):
    """PRD §3.5: "A decision to uphold leaves the rejection standing. The worker's
    `rejected_count` is unchanged, the assignment returns to `REJECTED` as a
    terminal state, and no further dispute of that assignment is ever permitted"

    Design: Difficulty/non_linear_state_machine/assignment_reject_dispute_resolve_branch_and_rejoin
    """
    requester, hit, worker, assignment = setup_disputed_assignment(
        title="Uphold Probe", deposit_cents=1_000,
    )

    resolved = admin_resolve(assignment["id"], "UPHOLD", reason="review confirmed")
    assert resolved["status"] == "REJECTED"
    assert get_worker(worker["id"])["rejected_count"] == 1


def test_a_second_dispute_of_the_same_assignment_is_refused(api, admin_headers):
    """PRD §3.5: "the assignment may be disputed only once in its entire life, a
    second attempt failing with `ERR_DISPUTE_ALREADY_USED` (HTTP 409)."
    PRD §3.5: "no further dispute of that assignment is ever permitted — a
    subsequent attempt fails with `ERR_DISPUTE_ALREADY_USED`"

    Design: Corner/errors/disputed_assignment_cannot_be_disputed_twice
    """
    requester, hit, worker, assignment = setup_disputed_assignment(
        title="OneDispute Probe", deposit_cents=1_000,
    )
    admin_resolve(assignment["id"], "UPHOLD", reason="confirmed")

    res = api.dispute_assignment(
        assignment["id"], create_dispute_payload(reason="trying again"),
        make_worker_headers(worker["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DISPUTE_ALREADY_USED, 409)

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "REJECTED"
    assert get_worker(worker["id"])["rejected_count"] == 1


def test_admin_resolve_rejects_a_decision_other_than_approve_or_uphold(api, admin_headers):
    """PRD §3.5: "Two outcomes are possible, and each is declared only for its own
    decision value; any other `decision` supplied against a disputed assignment is
    refused with `ERR_INVALID_STATE`."
    PRD §3.5: "There is no third outcome and no partial relief."

    Design: Corner/endpoints/settlement_of_conditional_action_requires_the_branch_decision
    """
    requester, hit, worker, assignment = setup_disputed_assignment(
        title="Resolve Probe", deposit_cents=1_000,
    )

    res = api.admin_resolve(
        assignment["id"], create_resolution_payload(decision="PARTIAL"),
        admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "DISPUTED"


# ═════════════════════════════════════════════════════════════════════════════
# Bonus: the two accepted states and the budget ceiling
# ═════════════════════════════════════════════════════════════════════════════

def test_bonus_credits_the_net_amount_and_extends_the_worker_earning(api, admin_headers):
    """PRD §3.4: "A bonus payment adds `bonus_cents` to the assignment's
    cumulative `bonus_cents`, appends a `Review` row of `kind` `BONUS` (the only
    review kind whose `bonus_cents` field is non-zero), and adds the same amount
    to the task's `spent_bonus_cents`."
    PRD §3.6: "the platform's commission is that gross multiplied by a 10 percent
    rate, rounded half-up to a whole cent. The worker's net for that assignment is
    the gross minus the commission"

    A 100c reward plus a 50c bonus grosses 150c; the 10% commission is 15c and the
    net is 135c, replacing the 90c the reward alone earned.

    Design: Corner/endpoints/bonus_endpoint_credits_net_bonus_and_extends_the_worker_earning
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_submitted_assignment_with_budget(
        bonus_budget_cents=200, reward_cents=100, approve=True,
        title="Bonus Probe", deposit_cents=2_000,
    )

    res = api.pay_bonus(
        assignment["id"], create_bonus_payload(bonus_cents=50),
        make_requester_headers(requester["id"]),
    )
    bonused = validate_success(res, 200)
    assert bonused["bonus_cents"] == 50

    assert get_hit(hit["id"], as_requester_id=requester["id"])["spent_bonus_cents"] == 50
    assert get_worker(worker["id"])["total_earned_cents"] == 135

    reviews = list_assignment_reviews(assignment["id"], as_requester_id=requester["id"])
    assert len(reviews) == 2
    bonus_rows = [row for row in reviews if row["kind"] == "BONUS"]
    assert len(bonus_rows) == 1
    assert reviews[-1]["kind"] == "BONUS", (
        "the ledger reads back in append order, so the bonus follows the approval"
    )
    assert reviews[-1]["bonus_cents"] == 50


def test_bonus_above_the_task_budget_is_refused_without_writing_anything(api, admin_headers):
    """PRD §3.4: "the task's `bonus_budget_cents` is a hard ceiling on the sum of
    all bonuses across the task, and a payment that would push the task's
    `spent_bonus_cents` above that ceiling is refused with
    `ERR_BONUS_BUDGET_EXCEEDED` (HTTP 409)"

    Design: Corner/errors/reward_amount_above_the_bonus_budget_is_rejected_on_bonus
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_submitted_assignment_with_budget(
        bonus_budget_cents=50, reward_cents=100, approve=True,
        title="BBudget Probe", deposit_cents=2_000,
    )

    res = api.pay_bonus(
        assignment["id"], create_bonus_payload(bonus_cents=60),
        make_requester_headers(requester["id"]),
    )
    validate_error(res, ApiErrorId.ERR_BONUS_BUDGET_EXCEEDED, 409)

    assert get_hit(hit["id"], as_requester_id=requester["id"])["spent_bonus_cents"] == 0
    assert get_assignment(assignment["id"], as_worker_id=worker["id"])["bonus_cents"] == 0
    assert len(list_assignment_reviews(assignment["id"], as_requester_id=requester["id"])) == 1


def test_bonus_credits_the_worker_earning_by_the_net_bonus(api, admin_headers):
    """PRD §3.4: "the worker's `total_earned_cents` and `withdrawable_cents` rise
    by the net after the per-assignment commission of §3.6."
    PRD §3.6: "the platform's commission is that gross multiplied by a 10 percent
    rate, rounded half-up to a whole cent. The worker's net for that assignment is
    the gross minus the commission"

    Design: Corner/endpoints/bonus_endpoint_credits_net_bonus_and_extends_the_worker_earning
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_submitted_assignment_with_budget(
        bonus_budget_cents=200, reward_cents=100, approve=True,
        title="Bonus Round Probe", deposit_cents=2_000,
    )
    pay_bonus(assignment["id"], requester["id"], 50)

    # 150c gross -> 15c commission (round_half_up(15.0)) -> 135c net.
    assert get_worker(worker["id"])["total_earned_cents"] == 135
    assert get_worker(worker["id"])["withdrawable_cents"] == 135


def test_a_bonus_review_records_the_amount_on_the_ledger(api, admin_headers):
    """PRD §3.9: "an `abuse_points` contribution as described in §3.7, and a
    `reason` string that is required non-empty whenever the `kind` is `REJECTION`"
    PRD §3.4: "appends a `Review` row of `kind` `BONUS` (the only review kind
    whose `bonus_cents` field is non-zero)"

    Design: Difficulty/combinatorial_formula/worker_earning_nested_rounding_per_assignment_then_sum
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_submitted_assignment_with_budget(
        bonus_budget_cents=200, reward_cents=100, approve=True,
        title="Bonus Ledger Probe", deposit_cents=2_000,
    )
    pay_bonus(assignment["id"], requester["id"], 50)

    reviews = list_assignment_reviews(assignment["id"], as_requester_id=requester["id"])
    assert len(reviews) == 2
    bonus_rows = [row for row in reviews if row["kind"] == "BONUS"]
    assert len(bonus_rows) == 1
    assert bonus_rows[0]["bonus_cents"] == 50
    assert bonus_rows[0]["abuse_points"] == 0
    assert get_hit(hit["id"], as_requester_id=requester["id"])["spent_bonus_cents"] == 50