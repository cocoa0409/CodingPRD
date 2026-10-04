"""The logical clock and the automatic sweeps it drives."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    create_acceptance_payload,
    create_submission_payload,
    create_sweep_payload,
    make_requester_headers,
    make_worker_headers,
    get_hit,
    get_assignment,
    get_worker,
    get_payout,
    register_requester,
    fund_requester,
    create_task,
    publish_task,
    create_published_task,
    accept_task,
    submit_assignment,
    request_payout,
    verify_worker_identity,
    setup_requester,
    setup_worker,
    setup_requester_and_hit,
    setup_task_with_live_accepted_assignment,
    setup_review_probe,
    setup_worker_earnings,
    setup_worker_earnings_ready_for_payout,
    set_clock,
    advance_clock,
    CLOCK_EPOCH,
    iso_at,
    REVIEW_WINDOW_HOURS,
    HOLD_DAYS,
)


# ═════════════════════════════════════════════════════════════════════════════
# The stale-version guard on the sweep
# ═════════════════════════════════════════════════════════════════════════════

def test_a_sweep_carrying_a_stale_task_version_is_refused(api, admin_headers):
    """PRD §3.8: "running a task's expiration sweep does too: both demand
    `expected_hit_version` and both bump the task's `version` by one, and either
    will refuse a client whose expectation is stale with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.3: "Acceptance also raises the task from `PUBLISHED` to `DISPATCHED`"

    Acceptance advanced the task's version past the value read at creation, so
    the sweep is refused even though the sweep target is still genuinely live.

    Design: Corner/cross_cutting_complexity_layers/stale_hit_version_sweep_is_rejected_with_stale_version
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme StaleSweep")
    requester = fund_requester(requester, 1_000)
    hit = create_published_task(
        requester["id"], title="StaleSweep Probe", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=300,
    )
    stale_version = hit["version"]
    worker = setup_worker(display_name="W1 StaleSweep")
    assignment = accept_task(hit["id"], worker["id"])

    res = api.sweep_expired(
        hit["id"], create_sweep_payload(stale_version),
        make_requester_headers(requester["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "ACCEPTED"
    assert get_hit(hit["id"], as_requester_id=requester["id"])["assignment_count"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# The write-path expiry predicate
# ═════════════════════════════════════════════════════════════════════════════

def test_an_assignment_whisper_past_its_time_limit_wins_over_submission(api, admin_headers):
    """PRD §3.4: "The submission is gated on the acting worker owning the
    assignment and on the expiry predicate described above — if the logical clock
    is at or after the acceptance instant plus the task's `time_limit_minutes`,
    expiry wins and the submission is refused with `ERR_ASSIGNMENT_EXPIRED`."

    The worker accepts with a 10-minute hold, the clock moves to T0+20m, and the
    window has already elapsed.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_expired_submit_by_suspended_worker
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Expired Submit")
    requester = fund_requester(requester, 1_000)
    hit = create_published_task(
        requester["id"], title="Expired Submit", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=10,
    )
    worker = setup_worker(display_name="W1 Expired Submit")
    assignment = accept_task(hit["id"], worker["id"])

    set_clock(iso_at(minutes=20))
    res = api.submit_assignment(
        assignment["id"], create_submission_payload(assignment["version"]),
        make_worker_headers(worker["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_EXPIRED, 409)


def test_returning_an_assignment_past_its_hold_is_refused(api, admin_headers):
    """PRD §3.3: "Returning is allowed while the worker owns the assignment, while
    the current logical time is still strictly before the acceptance instant plus
    the task's `time_limit_minutes`, and while the assignment is not the worker's
    last live one against a task they have already worked"

    The worker accepted with a 10-minute hold, the clock moves to T0+20m, and the
    window has elapsed — so the return is refused. The specific `error_id` is not
    asserted: the PRD states ERR_ASSIGNMENT_EXPIRED only for the submission path
    (PRD §3.4: "if the logical clock is at or after the acceptance instant plus
    the task's `time_limit_minutes`, expiry wins and the submission is refused
    with `ERR_ASSIGNMENT_EXPIRED`"), while §3.3 renders the return's own refusal
    as the state error ("the operation refused with `ERR_ASSIGNMENT_EXPIRED`"
    appears only in the submission narrative). Both are PRD-faithful on this
    branch, so the test pins the refusal, not its identifier.

    Design: Difficulty/cross_entity_state_dependency/submit_requires_acting_worker_active
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_task_with_live_accepted_assignment(
        time_limit_minutes=10
    )
    set_clock(iso_at(minutes=20))

    res = api.return_assignment(assignment["id"], make_worker_headers(worker["id"]))
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_ASSIGNMENT_EXPIRED, ApiErrorId.ERR_INVALID_STATE]
    )
    assert res.status_code == 409

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] in ("EXPIRED", "ACCEPTED")
    assert stored["status"] != "RETURNED", (
        "a return past the hold window must never land the row in RETURNED"
    )


# ═════════════════════════════════════════════════════════════════════════════
# The automatic sweep on a clock advance
# ═════════════════════════════════════════════════════════════════════════════

def test_advancing_the_clock_collects_overdue_accepted_assignments(api, admin_headers):
    """PRD §2.11: "Those sweeps are: collecting accepted assignments whose time
    limit has elapsed into `EXPIRED`"
    PRD §3.3: "the platform expiring it sets the assignment's `assignment_expired`
    flag true, increments the worker's `expired_count`, decrements the task's
    `assignment_count` and `committed_assignments` by one, clears `committed` to
    false, and lands the assignment in `EXPIRED`."

    Design: Corner/state_machines/payout_verify_before_hold_window_returns_vetting_hold_active
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_task_with_live_accepted_assignment(
        time_limit_minutes=30
    )
    advance_clock(iso_at(minutes=45))

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "EXPIRED"
    assert stored["assignment_expired"] is True
    assert stored["committed"] is False

    stored_hit = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored_hit["assignment_count"] == 0
    assert stored_hit["committed_assignments"] == 0
    assert stored_hit["accepted_count"] == 1
    assert get_worker(worker["id"])["expired_count"] == 1


def test_a_clock_advance_auto_approves_a_lapsed_review_window(api, admin_headers):
    """PRD §2.11: "auto-approving submitted assignments whose review window has
    lapsed"
    PRD §3.9: "It deliberately ignores the `eligible_for_approval` gate, because in
    this path the clock rather than the requester is the deciding authority"
    PRD §3.9: "stamps `approved_at` with the expiry instant rather than the current one"

    The worker submits at T0+10m (well inside the half-window), so a manual
    approval would still be too early; three days later the clock's authority
    approves it anyway.

    Design: Corner/state_machines/assignment_submit_after_approval_returns_invalid_state
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_review_probe(
        decision=None, reward_cents=100, title="Auto Approve Probe",
        deposit_cents=1_000, submit_at_minutes=10,
    )
    advance_clock(iso_at(minutes=10, hours=REVIEW_WINDOW_HOURS))

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "APPROVED"
    assert get_worker(worker["id"])["approved_count"] == 1
    assert get_hit(hit["id"], as_requester_id=requester["id"])["spent_rewards_cents"] == 100


def test_a_clock_advance_settles_a_held_payout_for_a_verified_worker(api, admin_headers):
    """PRD §2.11: "settling held payouts whose vetting hold has elapsed for
    identity-verified workers"
    PRD §3.6: "The same release also happens automatically: once the logical clock
    reaches `created_at` plus `HOLD_DAYS`, a held payout whose worker is
    identity-verified is settled by the sweep without any operator action."

    Design: Corner/state_machines/payout_verify_before_hold_window_returns_vetting_hold_active
    """
    requester, worker, assignments = setup_worker_earnings_ready_for_payout(
        count=2, country="US", name="Acme Auto Payout",
    )
    payout = request_payout(worker["id"], 100, "BANK_TRANSFER")
    verify_worker_identity(worker["id"], "VERIFIED")

    # The hold runs HOLD_DAYS from the payout's own creation instant.
    advance_clock(payout["hold_until_at"])
    stored = get_payout(payout["id"], as_worker_id=worker["id"])
    assert stored["status"] == "PAID"


def test_setting_the_clock_to_an_absolute_instant_runs_no_sweeps(api, admin_headers):
    """PRD §2.11: "Setting the clock to an absolute instant moves it without
    running sweeps for the interval skipped."
    PRD §2.11: "advancing it to a later instant additionally runs every automatic
    sweep that has come due"

    The same elapsed interval that collects an overdue assignment under
    `advance_to` leaves it untouched under `set_current_utc`.

    Design: Corner/state_machines/payout_verify_before_hold_window_returns_vetting_hold_active
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_task_with_live_accepted_assignment(
        time_limit_minutes=30
    )

    set_clock(iso_at(minutes=45))
    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "ACCEPTED", (
        "moving the clock without advancing must not collect the assignment"
    )

    advance_clock(iso_at(minutes=90))
    swept = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert swept["status"] == "EXPIRED"