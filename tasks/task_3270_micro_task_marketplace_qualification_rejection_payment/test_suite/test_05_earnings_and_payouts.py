"""Worker earnings, the qualification cascade, and withdrawals."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_hit_payload,
    create_acceptance_payload,
    create_payout_payload,
    create_verify_payout_payload,
    create_dispute_payload,
    create_resolution_payload,
    create_exam_attempt_payload,
    make_requester_headers,
    make_worker_headers,
    get_worker,
    get_requester,
    get_hit,
    get_assignment,
    get_payout,
    list_worker_qualifications,
    list_worker_payouts,
    list_assignment_reviews,
    register_requester,
    fund_requester,
    create_qualification_type,
    create_exam,
    create_task,
    publish_task,
    create_published_task,
    submit_exam_attempt,
    accept_task,
    submit_assignment,
    return_assignment,
    approve_assignment,
    reject_assignment,
    dispute_assignment,
    admin_resolve,
    request_payout,
    verify_worker_identity,
    setup_requester,
    setup_worker,
    setup_requester_and_hit,
    setup_nickel_worker,
    setup_worker_earnings,
    setup_worker_earnings_ready_for_payout,
    setup_review_probe,
    setup_review_probe_multi_slot,
    setup_qualification_gate_scenario,
    setup_exam_probe,
    accept_and_submit,
    set_clock,
    advance_clock,
    CLOCK_EPOCH,
    iso_at,
    PAYOUT_MIN_US_CENTS,
    PAYOUT_MIN_BR_CENTS,
    PAYOUT_MIN_IN_PH_CENTS,
    HOLD_DAYS,
    WORKER_COMMISSION_RATE,
)


# ═════════════════════════════════════════════════════════════════════════════
# Per-assignment rounding, then sum
# ═════════════════════════════════════════════════════════════════════════════

def test_two_five_cent_rewards_credit_eight_cents(api, admin_headers):
    """PRD §3.6: "Two details of this arithmetic are load-bearing. First, the
    rounding is nested per assignment and only then summed — rounding the gross
    total once at the end is a different and incorrect answer; four assignments
    each grossing 5 cents, for example, each yield a 1-cent commission under
    half-up rounding and therefore a 4-cent net"
    PRD §3.6: "The worker's net for that assignment is the gross minus the
    commission, and the worker's `total_earned_cents` is the sum of those per-
    assignment nets."

    Two separate 5c tasks each net 4c, so the per-item block earns 8c — not the 9c
    a single rounding of the 10c gross would produce. The worker's balance also
    carries the filler slot the fixture adds so a payout can clear the US
    floor; the nickel block's contribution is read from its own rows.

    Design: Difficulty/dual_variant_calc/worker_earning_per_assignment_rounding_vs_total_rounding
    """
    set_clock(CLOCK_EPOCH)
    requester, worker, assignments = setup_nickel_worker(count=2)

    profile = get_worker(worker["id"])
    assert profile["approved_count"] == 3
    # Two 5c slots net 4c each (nested per-assignment rounding), and the
    # 120c filler slot nets 108c — 8 + 108.
    assert profile["total_earned_cents"] == 8 + 108, (
        "two 5c slots net 8c under the nested order"
    )


def test_three_five_cent_rewards_credit_twelve_cents(api, admin_headers):
    """PRD §3.6: "the gross earning is the task's `reward_cents` plus the
    assignment's `bonus_cents`, and the platform's commission is that gross
    multiplied by a 10 percent rate, rounded half-up to a whole cent."
    PRD §3.6: "The worker's net for that assignment is the gross minus the
    commission, and the worker's `total_earned_cents` is the sum of those per-
    assignment nets."

    Each 5c item rounds to a 1c commission and a 4c net; three of them sum to
    12c, where one rounding of the 15c total would have given 13c.

    Design: Difficulty/combinatorial_formula/worker_earning_nested_rounding_per_assignment_then_sum
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Triple", deposit_cents=2_000)
    worker = setup_worker(display_name="W1 Triple")
    hit = create_published_task(
        requester["id"], title="Triple Nickel", reward_cents=5, max_assignments=3,
        assignment_duration_minutes=60, time_limit_minutes=120,
    )
    for index in range(3):
        assignment = accept_and_submit(
            hit, worker, submit_at_minutes=40, slot_index=index
        )
        approve_assignment(assignment["id"], requester["id"])

    profile = get_worker(worker["id"])
    assert profile["total_earned_cents"] == 12
    assert profile["withdrawable_cents"] == 12


def test_a_hundred_cent_reward_nets_ninety_cents(api, admin_headers):
    """PRD §3.6: "the gross earning is the
    task's `reward_cents` plus the assignment's `bonus_cents`, and the platform's
    commission is that gross multiplied by a 10 percent rate, rounded half-up to
    a whole cent."

    Design: Difficulty/boundary_precision_check/payout_country_threshold_exact_minimum_passes
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_review_probe(
        decision="APPROVE", reward_cents=100, title="Single Earning",
        deposit_cents=1_000,
    )
    assert get_worker(worker["id"])["total_earned_cents"] == 90


def test_unreviewed_and_non_approved_assignments_contribute_nothing(api, admin_headers):
    """PRD §3.6: "Only assignments in `APPROVED` contribute anything at all —
    assignments that are `REJECTED`, `SUBMITTED`, `ACCEPTED`, `RETURNED`, or
    `EXPIRED` contribute zero."

    Three assignments on the same task end respectively SUBMITTED, REJECTED and
    RETURNED, and none of them moves the worker's earning off zero.

    Design: Difficulty/combinatorial_formula/worker_earning_nested_rounding_per_assignment_then_sum
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme Zero Earning", deposit_cents=2_000)
    hit = create_published_task(
        requester["id"], title="Zero Earning", reward_cents=100, max_assignments=3,
        assignment_duration_minutes=60, time_limit_minutes=300,
    )
    workers = [setup_worker(display_name=f"Zero Earning Worker {i + 1}") for i in range(3)]

    submitted = accept_task(hit["id"], workers[0]["id"])
    submit_assignment(submitted, workers[0]["id"])

    rejected = accept_task(hit["id"], workers[1]["id"])
    rejected = submit_assignment(rejected, workers[1]["id"])
    reject_assignment(rejected["id"], requester["id"])

    returned = accept_task(hit["id"], workers[2]["id"])
    return_assignment(returned["id"], workers[2]["id"])

    for worker in workers:
        profile = get_worker(worker["id"])
        assert profile["total_earned_cents"] == 0
        assert profile["withdrawable_cents"] == 0


def test_approval_completes_the_task_and_closes_its_escrow(api, admin_headers):
    """PRD §3.8: "When they do hold, the task moves to `COMPLETED` and the ledger
    is closed out: the amount released at completion is the task's held
    `escrowed_cents` minus its `spent_rewards_cents` and minus its
    `spent_bonus_cents`, the task's `escrowed_cents` drops to zero"
    PRD §3.4: "if the task's `accepted_count` has reached `max_assignments`, every
    one of its assignments is terminal, and its `committed_assignments` has fallen
    to zero, the task bubbles up to `COMPLETED` by the gate in §3.8."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_apply_the_full_approval_chain
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_review_probe(
        decision="APPROVE", reward_cents=100, title="CascadeChain Probe",
        deposit_cents=2_000,
    )

    stored_assignment = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored_assignment["status"] == "APPROVED"
    assert stored_assignment["approved_at"] is not None

    stored_hit = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored_hit["spent_rewards_cents"] == 100
    assert stored_hit["status"] == "COMPLETED"
    assert stored_hit["escrowed_cents"] == 0

    profile = get_worker(worker["id"])
    assert profile["approved_count"] == 1
    assert profile["approval_rate_pct"] == 100
    assert profile["total_earned_cents"] == 90

    assert get_requester(requester["id"])["lifetime_spent_cents"] == 100


def test_spent_rewards_counts_only_approved_assignments(api, admin_headers):
    """PRD §3.8: "The persisted `spent_rewards_cents` is the sum of `reward_cents`
    over assignments in `APPROVED` status"
    PRD §3.8: "Assignments still sitting in `SUBMITTED` — work that has been handed
    in but not yet reviewed — contribute nothing to it"

    With one approved and one still-SUBMITTED slot on the same 100c task, the
    persisted figure reads 100 rather than 200.

    Design: Corner/calculations/hit_spent_final_variant_excludes_submitted_assignments
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, workers, assignments = setup_review_probe_multi_slot(
        ["APPROVE", "SUBMITTED"], reward_cents=100, deposit_cents=2_000,
        title="Spent Probe", assignment_duration_minutes=60, time_limit_minutes=300,
    )
    stored = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored["spent_rewards_cents"] == 100
    assert get_assignment(
        assignments[1]["id"], as_worker_id=workers[1]["id"]
    )["status"] == "SUBMITTED"


def test_task_summary_reconciles_the_outcome_mix(api, admin_headers):
    """PRD §3.8: "Completion of a task is gated by three simultaneous conditions.
    The task's `accepted_count` must have reached its `max_assignments`, every one
    of its assignments must be in a terminal state, and its
    `committed_assignments` must have fallen to zero."
    PRD §2.8: "it is the sum, across all of the requester's tasks, of their
    `spent_rewards_cents` and their `spent_bonus_cents`"

    Design: Corner/endpoints/records_summary_returns_requester_spend_totals
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignments = setup_review_probe_multi_slot(
        ["APPROVE", "REJECT"], reward_cents=100, deposit_cents=2_000,
        title="Summary Probe", assignment_duration_minutes=60, time_limit_minutes=300,
    )
    stored = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored["spent_rewards_cents"] == 100
    assert stored["spent_bonus_cents"] == 0
    assert stored["accepted_count"] == 2
    assert stored["committed_assignments"] == 0
    assert stored["status"] == "COMPLETED"
    assert stored["escrowed_cents"] == 0
    assert get_requester(requester["id"])["lifetime_spent_cents"] == 100


# ═════════════════════════════════════════════════════════════════════════════
# The approval-rate cascade into system qualifications
# ═════════════════════════════════════════════════════════════════════════════

def test_an_approval_mints_the_system_qualification_grant(api, admin_headers):
    """PRD §2.9: "Reaching a type's `auto_assign_threshold_pct` mints or refreshes
    a `CASCADE` grant in `ACTIVE` status scored at the type's `default_score`."
    PRD §2.9: "Whenever a worker's `approval_rate_pct` is recomputed — on an
    approval, on a rejection, or on an administrative resolution — the platform
    re-evaluates every `SYSTEM` qualification against the worker's rate."

    One approval lifts the rate to 100, past the type's 80 threshold, so the
    grant is minted at the declared default score of 70.

    Design: Difficulty/transitive_cascade/approval_to_worker_rate_to_system_qualification_grant
    """
    set_clock(CLOCK_EPOCH)
    qualification_type = create_qualification_type(
        name="AccuracyGate", kind="SYSTEM", auto_assign_threshold_pct=80,
        default_score=70,
    )
    requester = setup_requester(name="Acme Gate", deposit_cents=2_000)
    hit = create_published_task(
        requester["id"], title="Gate A", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=120,
    )
    worker = setup_worker(display_name="W1 Gate")
    assignment = accept_task(hit["id"], worker["id"])
    set_clock(iso_at(minutes=40))
    assignment = submit_assignment(assignment, worker["id"])
    approve_assignment(assignment["id"], requester["id"])

    grants = list_worker_qualifications(worker["id"])
    assert len(grants) == 1
    assert grants[0]["qualification_type_id"] == qualification_type["id"]
    assert grants[0]["source"] == "CASCADE"
    assert grants[0]["score"] == 70
    assert grants[0]["status"] == "ACTIVE"


def test_the_cascade_opens_a_gated_task_only_after_the_grant_lands(api, admin_headers):
    """PRD §2.9: "Reaching a type's `auto_assign_threshold_pct` mints or refreshes
    a `CASCADE` grant in `ACTIVE` status scored at the type's `default_score`."
    PRD §3.3: "A second snapshot is captured at full capacity"

    The worker who earned the grant is now admitted to the qualification-gated
    task, while the worker whose rate cascade never ran holds no grant at all.

    Design: Difficulty/transitive_cascade/approval_to_worker_rate_to_system_qualification_grant
    """
    set_clock(CLOCK_EPOCH)
    qualification_type, requester, ungated, gated = setup_qualification_gate_scenario(
        threshold_pct=80, default_score=70,
    )
    first = setup_worker(display_name="W1 Gate Grant")
    second = setup_worker(display_name="W2 Gate Grant")

    assignment = accept_task(ungated["id"], first["id"])
    set_clock(iso_at(minutes=40))
    assignment = submit_assignment(assignment, first["id"])
    approve_assignment(assignment["id"], requester["id"])

    granted = api.accept_hit(
        gated["id"], create_acceptance_payload(first["id"]),
        make_worker_headers(first["id"]),
    )
    validate_success(granted, 201)

    refused = api.accept_hit(
        gated["id"], create_acceptance_payload(second["id"]),
        make_worker_headers(second["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_QUALIFICATION_REQUIRED, 409)
    assert list_worker_qualifications(second["id"]) == []


def test_an_approving_overturn_restores_the_cascade_grant(api, admin_headers):
    """PRD §3.5: "This is the only path in the entire system that reverses
    approval-rate damage: it decrements the worker's `rejected_count` by one and
    increments their `approved_count` by one, recomputes `approval_rate_pct`, and
    lets that recomputation cascade into the system-qualification grants"
    PRD §2.9: "Falling back below the threshold revokes the `CASCADE` grants for
    types no longer met."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_reset_by_admin_overturn_revokes_cascade_grant
    """
    set_clock(CLOCK_EPOCH)
    qualification_type = create_qualification_type(
        name="RateGate", kind="SYSTEM", auto_assign_threshold_pct=100,
        default_score=60,
    )
    requester = setup_requester(name="Acme RateThresh", deposit_cents=2_000)
    worker = setup_worker(display_name="W1 RateThresh")
    hits = []
    for title in ("RateThresh A", "RateThresh B"):
        hits.append(create_published_task(
            requester["id"], title=title, reward_cents=100, max_assignments=1,
            assignment_duration_minutes=60, time_limit_minutes=300,
        ))

    assignments = []
    for index, hit in enumerate(hits):
        assignment = accept_and_submit(hit, worker, submit_at_minutes=40,
                                       slot_index=index)
        assignments.append(assignment)
    first, second = assignments
    approve_assignment(first["id"], requester["id"])
    reject_assignment(second["id"], requester["id"], reason="incomplete")

    # The appeal follows the rejection within the same logical instant, which is
    # far inside DISPUTE_WINDOW_HOURS.
    dispute_assignment(second["id"], worker["id"], reason="I was complete")
    admin_resolve(second["id"], "APPROVE", reason="overturned")

    profile = get_worker(worker["id"])
    assert profile["rejected_count"] == 0
    assert profile["approved_count"] == 2
    assert profile["approval_rate_pct"] == 100

    grants = list_worker_qualifications(worker["id"])
    gate_grants = [
        g for g in grants if g["qualification_type_id"] == qualification_type["id"]
    ]
    assert len(gate_grants) == 1
    assert gate_grants[0]["status"] == "ACTIVE"
    assert gate_grants[0]["source"] == "CASCADE"


def test_a_passing_attempt_grants_the_qualification_at_the_attempt_score(api, admin_headers):
    """PRD §3.2: "On a pass, a `WorkerQualification` is granted with `source` of
    `EXAM`, `status` of `ACTIVE`, and `score` equal to the passing attempt's score"
    PRD §3.2: "An attempt passes when its `score` is greater than or equal to the
    exam's `passing_score`."

    Design: Corner/validations/duplicate_qualification_exam_attempt_is_applied
    """
    set_clock(CLOCK_EPOCH)
    qualification_type, exam, worker = setup_exam_probe(passing_score=80)

    res = api.submit_exam_attempt(
        exam["id"], create_exam_attempt_payload(score=90),
        make_worker_headers(worker["id"]),
    )
    attempt = validate_success(res, 201)
    assert attempt["outcome"] == "PASSED"
    assert attempt["sequence"] == 1

    grants = list_worker_qualifications(worker["id"])
    assert len(grants) == 1
    assert grants[0]["source"] == "EXAM"
    assert grants[0]["status"] == "ACTIVE"
    assert grants[0]["score"] == 90


# ═════════════════════════════════════════════════════════════════════════════
# Payout floors
# ═════════════════════════════════════════════════════════════════════════════

def test_payout_below_the_country_floor_is_refused(api, admin_headers):
    """PRD §3.6: "a worker registered in `US` needs at least 100 cents; a worker
    in `IN` or `PH` needs at least 500; a worker in `BR` needs at least 1000"
    PRD §3.6: "an amount below it is refused with `ERR_PAYOUT_THRESHOLD_NOT_MET`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/payout_country_threshold_exact_minimum_passes
    """
    set_clock(CLOCK_EPOCH)
    requester, worker, assignments, earned = setup_worker_earnings(
        num_tasks=2, reward_cents=100, country="US", name="Acme Bound",
    )
    assert earned == 180

    res = api.create_payout(
        worker["id"], create_payout_payload(payment_method="BANK_TRANSFER", amount_cents=99),
        make_worker_headers(worker["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PAYOUT_THRESHOLD_NOT_MET, 409)


def test_payout_at_exactly_the_country_floor_is_accepted(api, admin_headers):
    """PRD §3.6: "The comparison is at-least, so an amount exactly equal to the
    minimum is payable"
    PRD §3.6: "Every payout request is minted in `HELD_FOR_VETTING` — there is no
    way to create one already paid"

    A US worker requesting exactly 100c clears the floor, and the request reserves
    the amount out of the withdrawable balance at creation time.

    Design: Difficulty/boundary_precision_check/payout_country_threshold_exact_minimum_passes
    """
    set_clock(CLOCK_EPOCH)
    requester, worker, assignments, earned = setup_worker_earnings(
        num_tasks=2, reward_cents=100, country="US", name="Acme Bound Ok",
    )
    verify_worker_identity(worker["id"], "VERIFIED")

    res = api.create_payout(
        worker["id"], create_payout_payload(payment_method="BANK_TRANSFER", amount_cents=100),
        make_worker_headers(worker["id"]),
    )
    payout = validate_success(res, 201)
    assert payout["amount_cents"] == 100
    assert payout["status"] == "HELD_FOR_VETTING"

    profile = get_worker(worker["id"])
    assert profile["withdrawable_cents"] == profile["total_earned_cents"] - 100, (
        "the reserved amount leaves the withdrawable balance immediately"
    )


def test_the_same_amount_is_payable_for_a_us_worker_but_not_a_br_worker(api, admin_headers):
    """PRD §3.6: "These floors are genuinely per-country: an identical 500-cent
    request succeeds for a `US` worker and fails for a `BR` worker."
    PRD §3.6: "a worker in `BR` needs at least 1000"

    Each worker clears their own balance by approving three of their own 100c
    tasks (270c earned apiece); the identical 500c request then splits on the
    country floor alone.

    Design: Difficulty/boundary_precision_check/payout_country_threshold_exact_minimum_passes
    """
    set_clock(CLOCK_EPOCH)
    _requester, us_worker, _assignments, _earned = setup_worker_earnings(
        num_tasks=3, reward_cents=100, country="US", name="Acme Per Country US",
    )
    _br_requester, br_worker, _br_assignments, _br_earned = setup_worker_earnings(
        num_tasks=3, reward_cents=100, country="BR", name="Acme Per Country BR",
    )
    assert get_worker(us_worker["id"])["total_earned_cents"] == 270
    assert get_worker(br_worker["id"])["total_earned_cents"] == 270

    allowed = api.create_payout(
        us_worker["id"], create_payout_payload(payment_method="BANK_TRANSFER", amount_cents=500),
        make_worker_headers(us_worker["id"]),
    )
    validate_success(allowed, 201)

    refused = api.create_payout(
        br_worker["id"], create_payout_payload(payment_method="BANK_TRANSFER", amount_cents=500),
        make_worker_headers(br_worker["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_PAYOUT_THRESHOLD_NOT_MET, 409)


# ═════════════════════════════════════════════════════════════════════════════
# The vetting hold and the reserved-funds conservation
# ═════════════════════════════════════════════════════════════════════════════

def test_verify_before_the_hold_window_elapses_is_refused(api, admin_headers):
    """PRD §3.6: "the logical clock must be at or past the payout's
    `hold_until_at`, or the release fails with `ERR_VETTING_HOLD_ACTIVE`
    (HTTP 409)."
    PRD §3.6: "its `hold_until_at` is stamped three days (`HOLD_DAYS`) after its
    creation"

    Design: Corner/state_machines/payout_verify_before_hold_window_returns_vetting_hold_active
    """
    requester, worker, assignments = setup_worker_earnings_ready_for_payout(
        count=2, country="US", name="Acme Vetting",
    )
    payout = request_payout(worker["id"], 100, "BANK_TRANSFER")
    verify_worker_identity(worker["id"], "VERIFIED")

    res = api.verify_payout(
        payout["id"], create_verify_payout_payload(payout["version"]), admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_VETTING_HOLD_ACTIVE, 409)

    stored = get_payout(payout["id"], as_worker_id=worker["id"])
    assert stored["status"] == "HELD_FOR_VETTING"


def test_rejecting_a_payout_releases_the_reserved_funds(api, admin_headers):
    """PRD §3.6: "A payout may instead be rejected by a `PlatformAdmin` supplying
    a `rejection_reason`; that records the reason, returns `amount_cents` to the
    worker's `withdrawable_cents`, and lands the payout in `REJECTED`, the other
    terminal state."

    The fixture leaves 900c of earned room on the worker's balance; the
    reservation of 100c drops withdrawable from 1000 to 900, and rejecting the
    payout restores it to 1000 while the earned total never moves.

    Design: Difficulty/compensating_invariant/worker_withdrawable_plus_reserved_payouts_conserved_across_request_and_reject
    """
    requester, worker, assignments = setup_worker_earnings_ready_for_payout(
        count=2, country="US", name="Acme Payout Conserve",
    )
    payout = request_payout(worker["id"], 100, "BANK_TRANSFER")
    verify_worker_identity(worker["id"], "VERIFIED")

    earned_before = get_worker(worker["id"])["total_earned_cents"]
    held = get_worker(worker["id"])
    assert held["withdrawable_cents"] == earned_before - 100

    res = api.reject_payout(
        payout["id"], {"rejection_reason": "documents unreadable"}, admin_headers,
    )
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"

    released = get_worker(worker["id"])
    assert released["withdrawable_cents"] == earned_before
    assert released["total_earned_cents"] == earned_before


def test_a_completed_payout_keeps_its_reservation(api, admin_headers):
    """PRD §3.6: "`withdrawable_cents`, which is `total_earned_cents` reduced by
    the sum of the worker's payout requests that are currently reserved — that is,
    every one whose status is `PAID` or `HELD_FOR_VETTING`."

    Design: Difficulty/compensating_invariant/worker_withdrawable_plus_reserved_payouts_conserved_across_request_and_reject
    """
    requester, worker, assignments = setup_worker_earnings_ready_for_payout(
        count=2, country="US", name="Acme Payout Reserved",
    )
    request_payout(worker["id"], 100, "BANK_TRANSFER")

    profile = get_worker(worker["id"])
    reserved = sum(
        row["amount_cents"] for row in list_worker_payouts(worker["id"])
        if row["status"] in ("PAID", "HELD_FOR_VETTING")
    )
    assert reserved == 100
    assert profile["withdrawable_cents"] + reserved == profile["total_earned_cents"]


def test_releasing_a_held_payout_after_the_hold_stamps_the_verification(api, admin_headers):
    """PRD §3.6: "A successful release stamps `identity_verified_at` with the
    current logical instant, advances the payout to `PAID` as a terminal state,
    and increments the payout's `version`."
    PRD §3.6: "The worker's `identity_verified` must already be true"

    Design: Corner/state_machines/payout_verify_before_hold_window_returns_vetting_hold_active
    """
    requester, worker, assignments = setup_worker_earnings_ready_for_payout(
        count=2, country="US", name="Acme Release",
    )
    payout = request_payout(worker["id"], 100, "BANK_TRANSFER")
    verify_worker_identity(worker["id"], "VERIFIED")

    # The hold runs HOLD_DAYS from the payout's own creation instant, so the
    # clock is moved to that instant. It is SET rather than advanced: PRD §2.11
    # states that setting the clock "moves it without running sweeps for the
    # interval skipped", and the automatic payout settlement is one of those
    # sweeps — advancing here would let the clock settle the payout itself and
    # the manual release this test exercises would never run.
    set_clock(payout["hold_until_at"])
    res = api.verify_payout(
        payout["id"], create_verify_payout_payload(payout["version"]), admin_headers,
    )
    released = validate_success(res, 200)
    assert released["status"] == "PAID"
    assert released["identity_verified_at"] is not None

    profile = get_worker(worker["id"])
    assert profile["withdrawable_cents"] == profile["total_earned_cents"] - 100, (
        "a PAID payout keeps holding its reservation"
    )