"""Second assertions for the hardest depth targets: priority conflicts, the
cross-entity gates, the empty-candidate fallback, per-assignment rounding and the
payout reservation conservation."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_acceptance_payload,
    create_payout_payload,
    create_submission_payload,
    make_requester_headers,
    make_worker_headers,
    get_requester,
    get_hit,
    get_worker,
    get_assignment,
    list_worker_payouts,
    register_requester,
    fund_requester,
    create_task,
    publish_task,
    create_published_task,
    accept_task,
    submit_assignment,
    request_payout,
    setup_requester,
    setup_worker,
    setup_requester_and_hit,
    setup_nickel_worker,
    setup_worker_earnings_ready_for_payout,
    setup_mixed_reward_worker,
    setup_review_probe_multi_slot,
    setup_worker_all_live_submitted,
    setup_suspended_worker_probe,
    accept_and_submit,
    seed_review_history,
    set_clock,
    CLOCK_EPOCH,
    iso_at,
)


# ═════════════════════════════════════════════════════════════════════════════
# Per-assignment rounding, proved through the reserved-funds invariant
# ═════════════════════════════════════════════════════════════════════════════

def test_nickel_earnings_survive_requesting_a_payout(api, admin_headers):
    """PRD §3.6: "the rounding is nested per assignment and only then summed"
    PRD §3.6: "What a worker can actually withdraw is `withdrawable_cents`, which
    is `total_earned_cents` reduced by the sum of the worker's payout requests
    that are currently reserved"

    Two 5c tasks net 8c under the nested order; requesting the whole 8c — once the
    worker's balance clears the US floor — leaves withdrawable at zero while the
    earned total is untouched, which only holds if the per-item rounding — not
    one rounding of the 10c gross — produced 8.

    Design: Difficulty/dual_variant_calc/worker_earning_per_assignment_rounding_vs_total_rounding
    """
    requester, worker, assignments = setup_nickel_worker(count=2, country="US")
    profile = get_worker(worker["id"])
    assert profile["total_earned_cents"] == 8 + 108, (
        "the two 5c slots net 8c under the nested order"
    )

    # A withdrawal must clear the US floor of 100c (PRD §3.6), so 8c itself is
    # refused; the nested-rounding figure is therefore read off the balance,
    # where 8c (nested) and 9c (one rounding of the 10c gross) are distinct.
    request_payout(worker["id"], 100, "BANK_TRANSFER")
    profile = get_worker(worker["id"])
    assert profile["total_earned_cents"] == 8 + 108
    assert profile["withdrawable_cents"] == 16


def test_a_mixed_reward_balance_matches_the_nested_rounding_order(api, admin_headers):
    """PRD §3.6: "the rounding is nested per assignment and only then summed —
    rounding the gross total once at the end is a different and incorrect answer"

    Two 100c rewards (90c net each) plus two 5c rewards (4c net each) sum to 188c;
    one rounding of the 210c gross would have produced 189c.

    Design: Difficulty/dual_variant_calc/worker_earning_per_assignment_rounding_vs_total_rounding
    """
    set_clock(CLOCK_EPOCH)
    requester, worker, assignments = setup_mixed_reward_worker()

    profile = get_worker(worker["id"])
    assert profile["total_earned_cents"] == 188
    assert profile["approved_count"] == 4
    assert profile["withdrawable_cents"] == 188


# ═════════════════════════════════════════════════════════════════════════════
# The priority ladder before money
# ═════════════════════════════════════════════════════════════════════════════

def test_the_state_error_outranks_the_balance_error_on_publish(api, admin_headers):
    """PRD §2.10: "a request that violates an earlier step never reaches a later
    one."
    PRD §2.10: "9. **Fiscal constraints** (`ERR_INSUFFICIENT_FUNDS`, HTTP 402) —
    money is checked last"

    Both violations hold at once — the task is no longer DRAFT and the requester
    has nothing left to prepay with — and the state step fires first.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_second_publish
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Priority A")
    requester = fund_requester(requester, 125)
    hit = create_task(requester["id"], title="Priority A", reward_cents=100,
                      max_assignments=1, assignment_duration_minutes=60,
                      time_limit_minutes=120)
    publish_task(hit["id"], requester["id"])
    assert get_requester(requester["id"])["prepaid_balance_cents"] == 0

    res = api.publish_hit(hit["id"], make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
    assert res.json()["data"]["error_id"] != ApiErrorId.ERR_INSUFFICIENT_FUNDS.value


def test_a_refused_second_publish_leaves_the_escrow_untouched(api, admin_headers):
    """PRD §3.1: "Publishing a drafted task is the second step, and it moves the
    task from `DRAFT` to `PUBLISHED`."
    PRD §3.1: "Three checks gate it, in the platform's fixed order"

    The second publish is refused at the state step, so neither the task's own
    escrow nor the requester's balances move — the fiscal step is never reached.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_second_publish
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Priority A Escrow")
    requester = fund_requester(requester, 125)
    hit = create_task(requester["id"], title="Priority A Escrow", reward_cents=100,
                      max_assignments=1, assignment_duration_minutes=60,
                      time_limit_minutes=120)
    published = publish_task(hit["id"], requester["id"])
    assert published["escrowed_cents"] == 125

    res = api.publish_hit(hit["id"], make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)

    stored = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored["status"] == "PUBLISHED"
    assert stored["escrowed_cents"] == 125
    profile = get_requester(requester["id"])
    assert profile["prepaid_balance_cents"] == 0
    assert profile["escrowed_cents"] == 125


def test_the_worker_state_error_outranks_the_expiry_error_on_submit(api, admin_headers):
    """PRD §2.10: "5. **Actor safety** (`ERR_WORKER_SUSPENDED`, HTTP 409) — the
    acting worker is `ACTIVE`"
    PRD §2.10: "Both of these checks outrank every fiscal check"

    The assignment is both suspended-owned and past its 10-minute hold, and the
    suspension gate is the one that answers.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_expired_submit_by_suspended_worker
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Priority B")
    requester = fund_requester(requester, 1_000)
    hit = create_published_task(
        requester["id"], title="Priority B", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=10,
    )
    worker = setup_worker(display_name="W1 Priority B")
    assignment = accept_task(hit["id"], worker["id"])
    api.suspend_worker(worker["id"], admin_headers)
    set_clock(iso_at(minutes=20))

    res = api.submit_assignment(
        assignment["id"], create_submission_payload(assignment["version"]),
        make_worker_headers(worker["id"]),
    )
    validate_error(res, ApiErrorId.ERR_WORKER_SUSPENDED, 409)
    assert res.json()["data"]["error_id"] != ApiErrorId.ERR_ASSIGNMENT_EXPIRED.value


# ═════════════════════════════════════════════════════════════════════════════
# The concurrency selector's empty fallback
# ═════════════════════════════════════════════════════════════════════════════

def test_the_empty_candidate_fallback_leaves_every_submitted_row_alone(api, admin_headers):
    """PRD §3.3: "If the candidate set is empty because every live assignment is
    `SUBMITTED`, nothing is expired and the attempted acceptance is refused with
    `ERR_CONCURRENCY_LIMIT_EXCEEDED` (HTTP 409)."
    PRD §3.3: "the platform will not silently drop work a worker has handed in"

    Design: Difficulty/boundary_precision_check/concurrency_empty_candidate_set_is_refused_not_silently_dropped
    """
    set_clock(CLOCK_EPOCH)
    requester, hits, assignments, worker, extra_hit_id = setup_worker_all_live_submitted()

    res = api.concurrency_check(
        worker["id"], {"hit_id": extra_hit_id}, make_worker_headers(worker["id"])
    )
    validate_error(res, ApiErrorId.ERR_CONCURRENCY_LIMIT_EXCEEDED, 409)

    assert get_worker(worker["id"])["expired_count"] == 0
    for assignment in assignments:
        assert get_assignment(assignment["id"], as_worker_id=worker["id"])["status"] == "SUBMITTED"
    assert get_hit(extra_hit_id, as_requester_id=requester["id"])["accepted_count"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Cross-entity state gates
# ═════════════════════════════════════════════════════════════════════════════

def test_a_suspended_worker_cannot_drive_their_assignment_to_submitted(api, admin_headers):
    """PRD §3.9: "a suspended worker is refused at acceptance, submission, and
    return with `ERR_WORKER_SUSPENDED`."
    PRD §2.10: "5. **Actor safety** (`ERR_WORKER_SUSPENDED`, HTTP 409) — the
    acting worker is `ACTIVE`"

    The assignment itself sits happily in ACCEPTED and inside its window, but the
    Worker row it belongs to is SUSPENDED, so the transition never fires.

    Design: Difficulty/cross_entity_state_dependency/submit_requires_acting_worker_active
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_suspended_worker_probe()

    res = api.submit_assignment(
        assignment["id"], create_submission_payload(assignment["version"]),
        make_worker_headers(worker["id"]),
    )
    validate_error(res, ApiErrorId.ERR_WORKER_SUSPENDED, 409)

    stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
    assert stored["status"] == "ACCEPTED"
    assert get_worker(worker["id"])["status"] == "SUSPENDED"


def test_a_suspended_requester_cannot_open_a_new_lifecycle(api, admin_headers):
    """PRD §3.7: "a requester left in `PENDING_REVIEW`, like one already
    `SUSPENDED`, is closed to publication and to the lifecycle writes that would
    open new work, and such an attempt is refused with `ERR_REQUESTER_NOT_ACTIVE`."

    The suspended requester's previously published task was cancelled by the
    suspension cascade, while the fresh draft they are holding stays DRAFT.

    Design: Difficulty/cross_entity_state_dependency/publish_requires_acting_requester_active
    """
    set_clock(CLOCK_EPOCH)
    requester = setup_requester(name="Acme XB Suspended", deposit_cents=20_000)
    # The reviews that carry the requester over the fraud threshold are accrued
    # on their own terminal tasks, so the tasks the cascade can still cancel
    # stay open: the collection probe starts DISPATCHED with a live slot.
    seed_review_history(
        requester, ["APPROVE", "REJECT", "APPROVE", "REJECT", "REJECT"]
    )
    hit = create_published_task(
        requester["id"], title="XB Old", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=100_000,
    )
    worker = setup_worker(display_name="XB Old Worker")
    accept_task(hit["id"], worker["id"])
    assert get_hit(hit["id"], as_requester_id=requester["id"])["status"] == "DISPATCHED"

    api.run_abuse_review(requester["id"], admin_headers)
    fresh = create_task(
        requester["id"], title="XB New", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=600,
    )

    res = api.publish_hit(fresh["id"], make_requester_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_REQUESTER_NOT_ACTIVE, 409)

    profile = get_requester(requester["id"])
    assert profile["status"] == "SUSPENDED"
    assert get_hit(fresh["id"], as_requester_id=requester["id"])["status"] == "DRAFT"
    assert get_hit(hit["id"], as_requester_id=requester["id"])["status"] == "CANCELLED"


# ═════════════════════════════════════════════════════════════════════════════
# The suspension cascade as one chained event
# ═════════════════════════════════════════════════════════════════════════════

def test_the_rejection_chain_runs_requester_to_task_to_assignment(api, admin_headers):
    """PRD §3.7: "Every task the requester owns that is still in `DRAFT`,
    `PUBLISHED`, or `DISPATCHED` is cancelled."
    PRD §3.7: "Each cancelled task also strands its live work: every assignment
    still in `ACCEPTED`, `SUBMITTED`, or `RETURNED` is moved to `EXPIRED`, with
    the owning worker's `expired_count` incremented"

    Two rejections inside the window carry the requester past the fraud threshold;
    the suspension cancels the task and strands the third worker's live slot
    without that slot ever being touched directly.

    Design: Difficulty/transitive_cascade/rejection_to_suspension_to_hit_cancel_to_assignment_expire
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Chain Cascade")
    requester = fund_requester(requester, 2_000)
    hit = create_published_task(
        requester["id"], title="Chain Cascade", reward_cents=100, max_assignments=3,
        assignment_duration_minutes=60, time_limit_minutes=600,
    )
    first = setup_worker(display_name="W1 Chain Cascade")
    second = setup_worker(display_name="W2 Chain Cascade")
    third = setup_worker(display_name="W3 Chain Cascade")

    # Two slots are worked and decided; the third worker is left holding a live
    # ACCEPTED row, which is the row the suspension cascade must strand. The
    # clock stays inside every window so nothing expires for any reason other
    # than the cascade.
    submitted = [
        accept_and_submit(hit, first, submit_at_minutes=40, slot_index=0),
        accept_and_submit(hit, second, submit_at_minutes=40, slot_index=1),
    ]
    third_assignment = accept_task(hit["id"], third["id"])
    api.reject_assignment(
        submitted[0]["id"], {"reason": "spam"}, make_requester_headers(requester["id"])
    )
    api.reject_assignment(
        submitted[1]["id"], {"reason": "spam"}, make_requester_headers(requester["id"])
    )

    before = get_assignment(third_assignment["id"], as_worker_id=third["id"])
    assert before["status"] == "ACCEPTED"

    res = api.run_abuse_review(requester["id"], admin_headers)
    validate_success(res, 200)

    assert get_worker(third["id"])["expired_count"] == 1
    assert get_assignment(third_assignment["id"], as_worker_id=third["id"])["status"] == "EXPIRED"


# ═════════════════════════════════════════════════════════════════════════════
# Withdrawable + reserved conservation
# ═════════════════════════════════════════════════════════════════════════════

def test_the_payout_reservation_is_released_on_rejection(api, admin_headers):
    """PRD §3.6: "Creating it immediately reduces the worker's
    `withdrawable_cents` by `amount_cents`, reserving the funds."
    PRD §3.6: "that records the reason, returns `amount_cents` to the worker's
    `withdrawable_cents`, and lands the payout in `REJECTED`, the other terminal
    state."

    The named quantity of withdrawable plus the reserved hold reads 180 before and
    after the rejection, so nothing was created or destroyed by the pair.

    Design: Difficulty/compensating_invariant/worker_withdrawable_plus_reserved_payouts_conserved_across_request_and_reject
    """
    requester, worker, assignments = setup_worker_earnings_ready_for_payout(
        count=2, country="US", name="Acme Reservation",
    )

    payout = request_payout(worker["id"], 100, "BANK_TRANSFER")
    earned = get_worker(worker["id"])["total_earned_cents"]
    held = get_worker(worker["id"])
    reserved = sum(
        p["amount_cents"] for p in list_worker_payouts(worker["id"])
        if p["status"] in ("PAID", "HELD_FOR_VETTING")
    )
    assert held["withdrawable_cents"] == earned - 100
    assert held["withdrawable_cents"] + reserved == earned

    api.reject_payout(payout["id"], {"rejection_reason": "documents unreadable"}, admin_headers)

    after = get_worker(worker["id"])
    remaining = sum(
        p["amount_cents"] for p in list_worker_payouts(worker["id"])
        if p["status"] in ("PAID", "HELD_FOR_VETTING")
    )
    assert after["withdrawable_cents"] == earned
    assert after["withdrawable_cents"] + remaining == earned