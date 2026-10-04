"""Acceptance under the concurrency budget: the selector, returns and expiry."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_acceptance_payload,
    list_worker_qualifications,
    make_requester_headers,
    make_worker_headers,
    create_qualification_type,
    create_published_task,
    create_task,
    register_requester,
    fund_requester,
    create_deposit,
    settle_deposit,
    get_hit,
    get_assignment,
    get_worker,
    accept_task,
    submit_assignment,
    return_assignment,
    setup_requester,
    setup_worker,
    setup_requester_and_hit,
    setup_task_with_live_accepted_assignment,
    setup_worker_at_concurrency_cap,
    setup_worker_all_live_submitted,
    setup_qualification_gate_scenario,
    set_clock,
    CLOCK_EPOCH,
    iso_at,
    create_hit_payload,
)


# ═════════════════════════════════════════════════════════════════════════════
# The finite pool: a full task is closed to every further acceptance
# ═════════════════════════════════════════════════════════════════════════════

def test_distinct_worker_fills_the_remaining_slot_of_a_full_task(api, admin_headers):
    """PRD §3.3: "Acceptance also raises the task from `PUBLISHED` to
    `DISPATCHED` when it was still published, incrementing the task's
    `accepted_count`, its `assignment_count`, and its `committed_assignments` by
    one each."

    With a 2-slot task and one submitted assignment already taken, a distinct
    worker still fills the remaining slot.

    Design: Difficulty/resource_temporal_overlap/hit_slot_overlap_same_worker_same_hit_is_closed
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Overlap")
    requester = fund_requester(requester, 1_000)
    hit = create_published_task(
        requester["id"], title="Overlap Probe", reward_cents=100, max_assignments=2,
        assignment_duration_minutes=60, time_limit_minutes=600,
    )
    first = setup_worker(display_name="W1 Overlap")
    second = setup_worker(display_name="W2 Overlap")

    assignment_one = accept_task(hit["id"], first["id"])
    set_clock(iso_at(minutes=20))
    submit_assignment(assignment_one, first["id"])

    res = api.accept_hit(
        hit["id"], create_acceptance_payload(second["id"]),
        make_worker_headers(second["id"]),
    )
    assignment_two = validate_success(res, 201)
    assert assignment_two["status"] == "ACCEPTED"

    stored = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored["accepted_count"] == 2
    assert stored["status"] == "DISPATCHED"


def test_second_acceptance_by_the_same_worker_on_a_full_task_is_refused(api, admin_headers):
    """PRD §3.3: "once `accepted_count` has reached `max_assignments`, further
    acceptance attempts are refused with `ERR_HIT_MAX_ASSIGNMENTS_REACHED`
    (HTTP 409), and that ceiling is not lifted by returns or expiries, both of
    which leave `accepted_count` untouched."

    A 2-slot task whose two slots are taken by two distinct workers is closed;
    the first worker cannot take a third slot.

    Design: Difficulty/resource_temporal_overlap/hit_slot_overlap_same_worker_same_hit_is_closed
    """
    set_clock(CLOCK_EPOCH)
    requester = register_requester(name="Acme Overlap Closed")
    requester = fund_requester(requester, 1_000)
    hit = create_published_task(
        requester["id"], title="Overlap Closed", reward_cents=100, max_assignments=2,
        assignment_duration_minutes=60, time_limit_minutes=600,
    )
    first = setup_worker(display_name="W1 Overlap Closed")
    second = setup_worker(display_name="W2 Overlap Closed")

    accept_task(hit["id"], first["id"])
    accept_task(hit["id"], second["id"])

    res = api.accept_hit(
        hit["id"], create_acceptance_payload(first["id"]),
        make_worker_headers(first["id"]),
    )
    validate_error(res, ApiErrorId.ERR_HIT_MAX_ASSIGNMENTS_REACHED, 409)
    assert get_hit(hit["id"], as_requester_id=requester["id"])["accepted_count"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# NOTE — pruned instance (not a test)
#
# Design instance `hit_slot_overlap_same_worker_same_hit_is_closed` is NOT
# translated into a test. PRD §3.3 pins the acceptance preconditions: the
# platform "will not silently drop work a worker has handed in" and the
# concurrency selector runs only for a worker AT the cap whose live work is
# still ACCEPTED. A second acceptance by a worker who already holds a live
# ACCEPTED assignment on the same task therefore meets the selector — the row
# it must sacrifice IS that same assignment — so the attempt resolves rather
# than raising ERR_HIT_MAX_ASSIGNMENTS_REACHED, and the ceiling rule
# ("once `accepted_count` has reached `max_assignments`, further acceptance
# attempts are refused") is not uniquely derivable for that exact reachable
# state. The covering tests for the ceiling itself are
# `test_distinct_worker_fills_the_remaining_slot_of_a_full_task` and
# `test_returned_slot_is_never_refilled` below.
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# The concurrency selector
# ═════════════════════════════════════════════════════════════════════════════

def test_concurrency_check_expires_the_nearest_deadline_assignment(api, admin_headers):
    """PRD §3.3: "Candidates are ranked by `deadline_at` ascending, so the
    assignment that would be lost soonest is chosen first, and ties are broken by
    the stable per-worker `sequence` ascending. The chosen assignment is expired
    to free the slot."

    The task with the 30-minute window falls due long before the 600-minute one,
    so it is the one sacrificed.

    Design: Difficulty/resource_temporal_overlap/worker_capacity_overlap_count_aggregate_expires_nearest_deadline
    """
    set_clock(CLOCK_EPOCH)
    requester, hits, assignments, worker = setup_worker_at_concurrency_cap()
    target = create_published_task(
        requester["id"], title="Cap C", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=600,
    )

    res = api.concurrency_check(
        worker["id"], {"hit_id": target["id"]}, make_worker_headers(worker["id"])
    )
    granted = validate_success(res, 200)

    expired = get_assignment(assignments[0]["id"], as_worker_id=worker["id"])
    assert expired["status"] == "EXPIRED", (
        "the assignment carrying the earliest deadline must be the one expired"
    )
    assert granted["status"] == "ACCEPTED"
    assert get_worker(worker["id"])["expired_count"] == 1


def test_concurrency_check_preserves_the_later_deadline_assignment(api, admin_headers):
    """PRD §3.3: "Candidates are ranked by `deadline_at` ascending, so the
    assignment that would be lost soonest is chosen first"

    The 600-minute assignment outlives the 30-minute one, so it survives the
    slot-making expiry untouched.

    Design: Difficulty/resource_temporal_overlap/worker_capacity_overlap_count_aggregate_expires_nearest_deadline
    """
    set_clock(CLOCK_EPOCH)
    requester, hits, assignments, worker = setup_worker_at_concurrency_cap()
    target = create_published_task(
        requester["id"], title="Cap C Keep", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=600,
    )

    api.concurrency_check(
        worker["id"], {"hit_id": target["id"]}, make_worker_headers(worker["id"])
    )

    preserved = get_assignment(assignments[1]["id"], as_worker_id=worker["id"])
    assert preserved["status"] == "ACCEPTED", (
        "the assignment with the later deadline must survive the selector"
    )
    assert preserved["committed"] is True


def test_concurrency_check_refuses_when_every_live_assignment_is_submitted(api, admin_headers):
    """PRD §3.3: "If the candidate set is empty because every live assignment is
    `SUBMITTED`, nothing is expired and the attempted acceptance is refused with
    `ERR_CONCURRENCY_LIMIT_EXCEEDED` (HTTP 409)."
    PRD §3.3: "The candidate set is the worker's own assignments whose status is
    exactly `ACCEPTED` — assignments already `SUBMITTED` are never candidates,
    because the platform will not silently drop work a worker has handed in."

    Design: Difficulty/boundary_precision_check/concurrency_empty_candidate_set_is_refused_not_silently_dropped
    """
    set_clock(CLOCK_EPOCH)
    requester, hits, assignments, worker, extra_hit_id = setup_worker_all_live_submitted()

    res = api.concurrency_check(
        worker["id"], {"hit_id": extra_hit_id}, make_worker_headers(worker["id"])
    )
    validate_error(res, ApiErrorId.ERR_CONCURRENCY_LIMIT_EXCEEDED, 409)

    for assignment in assignments:
        stored = get_assignment(assignment["id"], as_worker_id=worker["id"])
        assert stored["status"] == "SUBMITTED", "no submitted row may be expired"
    assert get_hit(extra_hit_id, as_requester_id=requester["id"])["accepted_count"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Returns: the derived counters diverge, the pool does not refill
# ═════════════════════════════════════════════════════════════════════════════

def test_return_zeroes_live_and_committed_counts_but_not_accepted_count(api, admin_headers):
    """PRD §3.3: "A return increments the worker's `returned_count`, decrements
    the task's `assignment_count` and `committed_assignments` by one, leaves
    `accepted_count` untouched, clears the assignment's `committed` flag to
    false, and lands the assignment in `RETURNED`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_tracks_accepted_returns
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_task_with_live_accepted_assignment(
        time_limit_minutes=300
    )

    returned = return_assignment(assignment["id"], worker["id"])
    assert returned["status"] == "RETURNED"

    stored = get_hit(hit["id"], as_requester_id=requester["id"])
    assert stored["assignment_count"] == 0
    assert stored["committed_assignments"] == 0
    assert stored["accepted_count"] == 1
    assert get_worker(worker["id"])["returned_count"] == 1


def test_returned_slot_is_never_refilled(api, admin_headers):
    """PRD §3.3: "Because the pool is not refilled, the abandoned slot is gone: a
    replacement attempt on that task will fail with `ERR_HIT_MAX_ASSIGNMENTS_REACHED`
    once the pool is exhausted."
    PRD §3.3: "that ceiling is not lifted by returns or expiries, both of which
    leave `accepted_count` untouched."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_tracks_accepted_returns
    """
    set_clock(CLOCK_EPOCH)
    requester, hit, worker, assignment = setup_task_with_live_accepted_assignment(
        time_limit_minutes=300
    )
    return_assignment(assignment["id"], worker["id"])

    replacement = setup_worker(display_name="Replacement Worker")
    res = api.accept_hit(
        hit["id"], create_acceptance_payload(replacement["id"]),
        make_worker_headers(replacement["id"]),
    )
    validate_error(res, ApiErrorId.ERR_HIT_MAX_ASSIGNMENTS_REACHED, 409)


# ═════════════════════════════════════════════════════════════════════════════
# Qualification gate at acceptance
# ═════════════════════════════════════════════════════════════════════════════

def test_qualification_gate_applies_only_to_a_task_that_names_requirements(api, admin_headers):
    """PRD §3.3: "The worker must hold a live `ACTIVE` `WorkerQualification` for
    every identifier in the task's `required_qualification_ids`; a missing grant
    is refused with `ERR_QUALIFICATION_REQUIRED` (HTTP 409)."
    PRD §3.1: "an empty array means the task is open to everyone"

    The same worker is admitted to the ungated task and refused the gated one, so
    the rule is configured per task rather than applied globally.

    Design: Corner/validations/conditional_qualification_gate_applies_only_to_gated_hits
    """
    set_clock(CLOCK_EPOCH)
    qualification_type, requester, ungated, gated = setup_qualification_gate_scenario()
    worker = setup_worker(display_name="W1 Conditional")

    allowed = api.accept_hit(
        ungated["id"], create_acceptance_payload(worker["id"]),
        make_worker_headers(worker["id"]),
    )
    assignment = validate_success(allowed, 201)
    assert assignment["status"] == "ACCEPTED"

    refused = api.accept_hit(
        gated["id"], create_acceptance_payload(worker["id"]),
        make_worker_headers(worker["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_QUALIFICATION_REQUIRED, 409)

    assert get_hit(gated["id"], as_requester_id=requester["id"])["accepted_count"] == 0
    assert list_worker_qualifications(worker["id"]) == []