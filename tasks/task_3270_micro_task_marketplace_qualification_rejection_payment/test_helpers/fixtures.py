"""
Composite setup helpers — multi-step prerequisites built from PRD endpoints only.

Every helper drives the real API through ``api_client``; nothing is stubbed and
no state is carried between tests (the runner restarts the server before each
test, so each fixture builds its world from an empty database). Setup calls use
``get_success_data`` so a broken precondition surfaces as a clear "Setup failed"
message rather than a confusing assertion failure.

Identity threading: whenever a fixture creates an entity-backed principal it
builds that principal's headers from the real entity id via
``make_requester_headers`` / ``make_worker_headers`` — never from the shared
``TEST_USERS`` constants, which carry ids no ownership check would accept.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_EPOCH,
    CONCURRENCY_PROBE_LIMIT,
    TEST_DEFAULTS,
)
from .test_users import TEST_USERS, make_requester_headers, make_worker_headers


# ─── Clock helpers ───────────────────────────────────────────────────────────
_EPOCH = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso_at(minutes: int = 0, hours: int = 0, days: int = 0) -> str:
    """Absolute logical-clock instant, offset from the fixed startup epoch."""
    dt = _EPOCH + timedelta(minutes=minutes, hours=hours, days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_out(minutes: int = 0, hours: int = 0, days: int = 0) -> str:
    """The same instant in the response format the platform emits.

    Timestamps carried in resource bodies are ISO 8601 UTC strings with exactly
    three fractional digits, so output comparisons must use this form rather than
    the bare ``iso_at`` used to drive the clock.
    """
    dt = _EPOCH + timedelta(minutes=minutes, hours=hours, days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def set_clock(instant: str = CLOCK_EPOCH):
    """Set the logical clock to an absolute instant (no sweeps run)."""
    res = api_client.set_current_utc(
        {"current_utc": instant}, TEST_USERS["admin_headers"]
    )
    assert res.status_code == 200, f"Setup failed: set clock -> {res.status_code} {res.text}"
    return res


def advance_clock(instant: str):
    """Advance the logical clock and run every automatic sweep due by ``instant``."""
    res = api_client.advance_to({"target_utc": instant}, TEST_USERS["admin_headers"])
    assert res.status_code == 200, f"Setup failed: advance clock -> {res.status_code} {res.text}"
    return res


# ─── Principal registration and funding ──────────────────────────────────────

def register_requester(name: str = None, **overrides) -> dict:
    """Register a requester account and return its profile."""
    payload = {"name": name or TEST_DEFAULTS["REQUESTER_NAME"]}
    payload.update(overrides)
    res = api_client.create_requester(payload, TEST_USERS["anonymous_headers"])
    return get_success_data(res)


def register_worker(display_name: str = None, country: str = "US", **overrides) -> dict:
    """Register a worker account and return its profile."""
    payload = {
        "display_name": display_name or TEST_DEFAULTS["WORKER_NAME"],
        "country": country,
    }
    payload.update(overrides)
    res = api_client.create_worker(payload, TEST_USERS["anonymous_headers"])
    return get_success_data(res)


def create_deposit(requester_id: str, amount_cents: int) -> dict:
    """Mint a PENDING deposit for the requester."""
    res = api_client.create_deposit(
        requester_id, {"amount_cents": amount_cents}, make_requester_headers(requester_id)
    )
    return get_success_data(res)


def settle_deposit(deposit_id: str, outcome: str = "SUCCEEDED") -> dict:
    """Settle a deposit as SUCCEEDED (credits the balance) or FAILED (no credit)."""
    res = api_client.settle_deposit(
        deposit_id, {"outcome": outcome}, TEST_USERS["admin_headers"]
    )
    return get_success_data(res)


def fund_requester(requester: dict, amount_cents: int) -> dict:
    """Deposit and settle ``amount_cents`` for a requester, then re-read it."""
    dep = create_deposit(requester["id"], amount_cents)
    settle_deposit(dep["id"], "SUCCEEDED")
    return get_requester(requester["id"])


def get_requester(requester_id: str) -> dict:
    res = api_client.get_requester(requester_id, make_requester_headers(requester_id))
    return get_success_data(res)


def get_worker(worker_id: str) -> dict:
    res = api_client.get_worker(worker_id, make_worker_headers(worker_id))
    return get_success_data(res)


def get_hit(hit_id: str, as_requester_id: str = None) -> dict:
    """Read a task. Ownership is not required for GET, but the requester view is used."""
    headers = (
        make_requester_headers(as_requester_id)
        if as_requester_id
        else TEST_USERS["admin_headers"]
    )
    res = api_client.get_hit(hit_id, headers)
    return get_success_data(res)


def get_assignment(assignment_id: str, as_worker_id: str = None) -> dict:
    headers = (
        make_worker_headers(as_worker_id)
        if as_worker_id
        else TEST_USERS["admin_headers"]
    )
    res = api_client.get_assignment(assignment_id, headers)
    return get_success_data(res)


def get_payout(payout_id: str, as_worker_id: str = None) -> dict:
    headers = (
        make_worker_headers(as_worker_id)
        if as_worker_id
        else TEST_USERS["admin_headers"]
    )
    res = api_client.get_payout(payout_id, headers)
    return get_success_data(res)


# ─── Qualification catalogue ─────────────────────────────────────────────────

def create_qualification_type(name="Test Qualification", kind="SYSTEM",
                              auto_assign_threshold_pct=80, **overrides) -> dict:
    payload = {
        "name": name,
        "kind": kind,
        "auto_assign_threshold_pct": auto_assign_threshold_pct,
    }
    payload.update(overrides)
    res = api_client.create_qualification_type(payload, TEST_USERS["admin_headers"])
    return get_success_data(res)


def create_exam(qualification_type_id: str, passing_score: int = 80, **overrides) -> dict:
    payload = {"passing_score": passing_score}
    payload.update(overrides)
    res = api_client.create_exam(
        qualification_type_id, payload, TEST_USERS["admin_headers"]
    )
    return get_success_data(res)


def submit_exam_attempt(exam_id: str, worker_id: str, score: int) -> dict:
    res = api_client.submit_exam_attempt(
        exam_id, {"score": score}, make_worker_headers(worker_id)
    )
    return get_success_data(res)


def list_worker_qualifications(worker_id: str) -> list:
    """All qualification grants held by ``worker_id`` (filtered server-side)."""
    res = api_client.list_worker_qualifications(
        make_worker_headers(worker_id), params={"worker_id": worker_id}
    )
    body = res.json()
    return body.get("data", [])


def list_assignment_reviews(assignment_id: str, as_requester_id: str = None) -> list:
    """All reviews appended against ``assignment_id``."""
    headers = (
        make_requester_headers(as_requester_id)
        if as_requester_id
        else TEST_USERS["admin_headers"]
    )
    res = api_client.list_assignment_reviews(assignment_id, headers)
    return res.json().get("data", [])


def list_requester_hits(requester_id: str, params: dict = None) -> list:
    res = api_client.list_requester_hits(
        requester_id, make_requester_headers(requester_id), params=params
    )
    return res.json().get("data", [])


def list_worker_payouts(worker_id: str) -> list:
    """All payout requests raised by ``worker_id``."""
    res = api_client.list_payouts(worker_id, make_worker_headers(worker_id))
    return res.json().get("data", [])


def list_hits(params: dict = None, as_requester_id: str = None) -> list:
    headers = (
        make_requester_headers(as_requester_id)
        if as_requester_id
        else TEST_USERS["admin_headers"]
    )
    res = api_client.list_hits(headers, params=params)
    return res.json().get("data", [])


# ─── Task lifecycle ──────────────────────────────────────────────────────────

def create_task(requester_id: str, **overrides) -> dict:
    """Create a task in DRAFT. ``funds_required_cents`` is computed by the server."""
    payload = {
        "requester_id": requester_id,
        "title": overrides.pop("title", "Test Task"),
        "reward_cents": overrides.pop("reward_cents", TEST_DEFAULTS["REWARD_CENTS"]),
        "max_assignments": overrides.pop("max_assignments", TEST_DEFAULTS["MAX_ASSIGNMENTS"]),
        "assignment_duration_minutes": overrides.pop(
            "assignment_duration_minutes", TEST_DEFAULTS["ASSIGNMENT_DURATION_MINUTES"]
        ),
        "time_limit_minutes": overrides.pop(
            "time_limit_minutes", TEST_DEFAULTS["TIME_LIMIT_MINUTES"]
        ),
    }
    payload.update(overrides)
    res = api_client.create_hit(payload, make_requester_headers(requester_id))
    return get_success_data(res)


def publish_task(hit_id: str, requester_id: str) -> dict:
    res = api_client.publish_hit(hit_id, make_requester_headers(requester_id))
    return get_success_data(res)


def create_published_task(requester_id: str, **overrides) -> dict:
    """Create a task and publish it. Assumes the requester is already funded."""
    hit = create_task(requester_id, **overrides)
    return publish_task(hit["id"], requester_id)


def accept_task(hit_id: str, worker_id: str) -> dict:
    """Accept a task slot; mints an ACCEPTED assignment and consumes a pool slot."""
    res = api_client.accept_hit(
        hit_id, {"worker_id": worker_id}, make_worker_headers(worker_id)
    )
    return get_success_data(res)


def submit_assignment(assignment: dict, worker_id: str) -> dict:
    """Submit an accepted assignment using its current version."""
    res = api_client.submit_assignment(
        assignment["id"],
        {"expected_assignment_version": assignment["version"]},
        make_worker_headers(worker_id),
    )
    return get_success_data(res)


def approve_assignment(assignment_id: str, requester_id: str) -> dict:
    res = api_client.approve_assignment(assignment_id, make_requester_headers(requester_id))
    return get_success_data(res)


def reject_assignment(assignment_id: str, requester_id: str,
                      reason: str = "work did not meet the instructions") -> dict:
    res = api_client.reject_assignment(
        assignment_id, {"reason": reason}, make_requester_headers(requester_id)
    )
    return get_success_data(res)


def dispute_assignment(assignment_id: str, worker_id: str,
                       reason: str = "the work followed the checklist") -> dict:
    res = api_client.dispute_assignment(
        assignment_id, {"reason": reason}, make_worker_headers(worker_id)
    )
    return get_success_data(res)


def admin_resolve(assignment_id: str, decision: str, reason: str = "reviewed") -> dict:
    res = api_client.admin_resolve(
        assignment_id, {"decision": decision, "reason": reason}, TEST_USERS["admin_headers"]
    )
    return get_success_data(res)


def pay_bonus(assignment_id: str, requester_id: str, bonus_cents: int) -> dict:
    res = api_client.pay_bonus(
        assignment_id, {"bonus_cents": bonus_cents}, make_requester_headers(requester_id)
    )
    return get_success_data(res)


def return_assignment(assignment_id: str, worker_id: str) -> dict:
    res = api_client.return_assignment(assignment_id, make_worker_headers(worker_id))
    return get_success_data(res)


def verify_worker_identity(worker_id: str, outcome: str = "VERIFIED") -> dict:
    res = api_client.submit_identity_verification(
        worker_id, {"outcome": outcome}, TEST_USERS["admin_headers"]
    )
    return get_success_data(res)


def suspend_worker(worker_id: str) -> dict:
    res = api_client.suspend_worker(worker_id, TEST_USERS["admin_headers"])
    return get_success_data(res)


def request_payout(worker_id: str, amount_cents: int,
                   payment_method: str = "BANK_TRANSFER") -> dict:
    res = api_client.create_payout(
        worker_id,
        {"payment_method": payment_method, "amount_cents": amount_cents},
        make_worker_headers(worker_id),
    )
    return get_success_data(res)


# ═════════════════════════════════════════════════════════════════════════════
# Tier 1 — State progression
# ═════════════════════════════════════════════════════════════════════════════

def setup_requester(name: str = None, deposit_cents: int = None) -> dict:
    """A registered requester, optionally funded. Returns the (re-read) profile."""
    requester = register_requester(name or TEST_DEFAULTS["REQUESTER_NAME"])
    if deposit_cents:
        requester = fund_requester(requester, deposit_cents)
    return requester


def setup_worker(country: str = "US", display_name: str = None) -> dict:
    """A registered worker in ``country``."""
    return register_worker(display_name or TEST_DEFAULTS["WORKER_NAME"], country=country)


def accept_and_submit(hit: dict, worker: dict, submit_at_minutes: int = 40,
                      slot_index: int = 0) -> dict:
    """Accept a slot for ``worker``, move the clock, submit. Returns the assignment.

    ``slot_index`` shifts both instants forward for each successive slot a
    fixture fills, so a multi-slot fixture never has to move the logical clock
    backwards. Because the clock is shared and frozen between calls, every slot
    in a run would otherwise be accepted at the same instant — and approval is
    only legal once half of ``assignment_duration_minutes`` has elapsed since
    acceptance (PRD §3.4), so the submission instant is driven a full
    ``submit_at_minutes`` past that slot's own acceptance instant.
    """
    accept_at = slot_index * submit_at_minutes
    set_clock(iso_at(minutes=accept_at))
    assignment = accept_task(hit["id"], worker["id"])
    set_clock(iso_at(minutes=accept_at + submit_at_minutes))
    return submit_assignment(assignment, worker["id"])


def run_approval_chain(requester: dict, hit: dict, worker: dict,
                       submit_at_minutes: int = 40, approve: bool = True,
                       bonus_cents: int = None, slot_index: int = 0) -> dict:
    """accept -> submit -> (approve) -> (bonus) on an already-published task."""
    submitted = accept_and_submit(
        hit, worker, submit_at_minutes, slot_index=slot_index
    )
    if not approve:
        return submitted
    approved = approve_assignment(submitted["id"], requester["id"])
    if bonus_cents is not None:
        approved = pay_bonus(submitted["id"], requester["id"], bonus_cents)
    return approved


# ═════════════════════════════════════════════════════════════════════════════
# Tier 2 — Entity hierarchy
# ═════════════════════════════════════════════════════════════════════════════

def setup_requester_and_hit(reward_cents: int = 100, max_assignments: int = 1,
                            assignment_duration_minutes: int = 60,
                            time_limit_minutes: int = 300,
                            deposit_cents: int = None, publish: bool = True,
                            name: str = None, **hit_overrides) -> tuple:
    """Funded requester + one task (published by default). Returns (requester, hit).

    ``funds_required_cents`` for the default 100c x 1 shape is 125.
    """
    if deposit_cents is None:
        deposit_cents = TEST_DEFAULTS["DEPOSIT_CENTS"]
    requester = setup_requester(name=name, deposit_cents=deposit_cents)
    hit = create_task(
        requester["id"],
        reward_cents=reward_cents,
        max_assignments=max_assignments,
        assignment_duration_minutes=assignment_duration_minutes,
        time_limit_minutes=time_limit_minutes,
        **hit_overrides,
    )
    if publish:
        hit = publish_task(hit["id"], requester["id"])
    return requester, hit


# ═════════════════════════════════════════════════════════════════════════════
# Tier 3 — Full lifecycle shortcuts
# ═════════════════════════════════════════════════════════════════════════════

def setup_approved_assignment(reward_cents: int = 100, max_assignments: int = 1,
                              assignment_duration_minutes: int = 60,
                              time_limit_minutes: int = 300,
                              deposit_cents: int = None, country: str = "US",
                              submit_at_minutes: int = 40, approve: bool = True,
                              bonus_cents: int = None, **hit_overrides) -> tuple:
    """Full happy path on one task.

    funded requester -> published task -> worker accepts -> clock +40m ->
    submits -> approved (and optionally bonused).
    Returns (requester, hit, worker, assignment).
    """
    requester, hit = setup_requester_and_hit(
        reward_cents=reward_cents,
        max_assignments=max_assignments,
        assignment_duration_minutes=assignment_duration_minutes,
        time_limit_minutes=time_limit_minutes,
        deposit_cents=deposit_cents,
        **hit_overrides,
    )
    worker = setup_worker(country=country)
    assignment = run_approval_chain(
        requester, hit, worker,
        submit_at_minutes=submit_at_minutes, approve=approve, bonus_cents=bonus_cents,
    )
    return requester, hit, worker, assignment


def setup_submitted_assignment(**overrides) -> tuple:
    """Same as setup_approved_assignment but stops at SUBMITTED."""
    overrides["approve"] = False
    return setup_approved_assignment(**overrides)


def setup_rejected_assignment(reject_reason: str = "work did not meet the instructions",
                              reject_at_minutes: int = 45,
                              **overrides) -> tuple:
    """accept -> submit -> reject. Returns (requester, hit, worker, assignment).

    The rejection lands a few minutes after the submission, which keeps it
    inside the task's time limit (PRD §3.3: the expiry predicate refuses any
    write at or after acceptance + `time_limit_minutes`) while leaving it inside
    DISPUTE_WINDOW_HOURS, so an appeal raised afterwards is still in window.
    """
    requester, hit, worker, assignment = setup_approved_assignment(
        approve=False, **overrides
    )
    set_clock(iso_at(minutes=reject_at_minutes))
    rejected = reject_assignment(assignment["id"], requester["id"], reason=reject_reason)
    return requester, hit, worker, rejected


def setup_disputed_assignment(dispute_at_minutes: int = 5,
                              dispute_reason: str = "the work followed the checklist",
                              **overrides) -> tuple:
    """accept -> submit -> reject -> dispute. Returns (requester, hit, worker, assignment)."""
    requester, hit, worker, assignment = setup_rejected_assignment(**overrides)
    set_clock(iso_at(minutes=dispute_at_minutes))
    disputed = dispute_assignment(assignment["id"], worker["id"], reason=dispute_reason)
    return requester, hit, worker, disputed


def setup_upturned_dispute(**overrides) -> tuple:
    """Dispute then resolve APPROVE. Returns (requester, hit, worker, assignment)."""
    requester, hit, worker, assignment = setup_disputed_assignment(**overrides)
    resolved = admin_resolve(assignment["id"], "APPROVE", reason="overturned")
    return requester, hit, worker, resolved


# ═════════════════════════════════════════════════════════════════════════════
# Tier 4 — Accumulation / threshold targeting
# ═════════════════════════════════════════════════════════════════════════════

def setup_worker_earnings(num_tasks: int = 2, reward_cents: int = 100,
                          country: str = "US", deposit_cents: int = None,
                          name: str = None) -> tuple:
    """A worker holding ``num_tasks`` approved assignments on separate tasks.

    The deposits reach the balance before any task is drafted, so a low-priced
    task still clears its own funds requirement. Each 100c reward contributes
    90c net. Returns (requester, worker, [assignments], total_earned_cents).
    """
    requester = setup_requester(name=name, deposit_cents=deposit_cents or 5_000)
    worker = setup_worker(country=country)
    assignments = []
    for index in range(num_tasks):
        hit = create_published_task(
            requester["id"],
            title=f"Earning Task {index + 1}",
            reward_cents=reward_cents,
            max_assignments=1,
            assignment_duration_minutes=60,
            time_limit_minutes=300,
        )
        assignments.append(run_approval_chain(requester, hit, worker, slot_index=index))
    earned = sum(
        a["bonus_cents"] + reward_cents
        - round((a["bonus_cents"] + reward_cents) * 0.10)
        for a in assignments
    )
    return requester, worker, assignments, earned


def setup_nickel_worker(count: int = 2, deposit_cents: int = 2_000,
                        country: str = "US", filler_cents: int = 120) -> tuple:
    """A worker with ``count`` approved 5c assignments.

    Each 5c gross yields a 1c commission, so each net is 4c; ``count`` of them
    sum to ``4 * count``, the figure the nested-rounding rule pins (PRD §3.6).
    A payout request must still clear the worker's country floor (PRD §3.6), so
    ``filler_cents`` extra is earned on a separate 1-slot task. Returns
    (requester, worker, [assignments]) where the list holds only the nickel
    assignments.
    """
    requester = setup_requester(name="Nickel Requester", deposit_cents=deposit_cents)
    worker = setup_worker(country=country, display_name="Nickel Worker")
    assignments = []
    for index in range(count):
        hit = create_published_task(
            requester["id"],
            title=f"Nickel {index + 1}",
            reward_cents=5,
            max_assignments=1,
            assignment_duration_minutes=60,
            time_limit_minutes=300,
        )
        assignments.append(run_approval_chain(requester, hit, worker, slot_index=index))
    if filler_cents:
        filler = create_published_task(
            requester["id"],
            title="Nickel Filler",
            reward_cents=filler_cents,
            max_assignments=1,
            assignment_duration_minutes=60,
            time_limit_minutes=300,
        )
        run_approval_chain(requester, filler, worker, slot_index=count)
    return requester, worker, assignments


def setup_requester_with_reviews(num_rejections: int = 2, num_approvals: int = 1,
                                 reward_cents: int = 100, deposit_cents: int = 5_000,
                                 advance_minutes: int = 40,
                                 name: str = None) -> tuple:
    """A requester whose tasks have accrued rejections and approvals.

    One task carries one slot per review; each worker is distinct. Returns
    (requester, [hits], [workers], [assignments]).
    """
    slots = num_rejections + num_approvals
    requester = setup_requester(name=name or "Review Requester", deposit_cents=deposit_cents)
    workers, assignments, hits = [], [], []
    for index in range(slots):
        hit = create_published_task(
            requester["id"],
            title=f"Review Task {index + 1}",
            reward_cents=reward_cents,
            max_assignments=1,
            assignment_duration_minutes=60,
            time_limit_minutes=300,
        )
        worker = setup_worker(display_name=f"Review Worker {index + 1}")
        assignment = accept_and_submit(hit, worker, advance_minutes, slot_index=index)
        if index < num_rejections:
            assignment = reject_assignment(assignment["id"], requester["id"])
        else:
            assignment = approve_assignment(assignment["id"], requester["id"])
        hits.append(hit)
        workers.append(worker)
        assignments.append(assignment)
    return requester, hits, workers, assignments


# ═════════════════════════════════════════════════════════════════════════════
# Tier 5 — Terminal / finalization targeting
# ═════════════════════════════════════════════════════════════════════════════


def setup_task_with_live_accepted_assignment(time_limit_minutes: int = 600,
                                             **overrides) -> tuple:
    """A task holding one live ACCEPTED assignment (worker has not submitted).

    Returns (requester, hit, worker, assignment). The task sits DISPATCHED with
    no advance needed: the fixture starts by moving the clock back to the
    startup epoch, because earlier clock moves inside the same test are packed
    into the instant the caller later drives to.
    """
    set_clock(CLOCK_EPOCH)
    requester, hit = setup_requester_and_hit(
        max_assignments=overrides.pop("max_assignments", 1),
        time_limit_minutes=time_limit_minutes,
        **overrides,
    )
    worker = setup_worker()
    assignment = accept_task(hit["id"], worker["id"])
    return requester, hit, worker, assignment


def server_concurrency_cap() -> int:
    """Discover the platform's per-worker concurrency cap by probing it.

    The PRD names ``MAX_CONCURRENT_ASSIGNMENTS`` but never pins a number, so a
    fixture that hard-codes a slot count would assert a constant the spec does
    not determine. Instead a scratch worker is handed 1-slot tasks until the
    platform refuses with ``ERR_CONCURRENCY_LIMIT_EXCEEDED`` — that refusal is
    itself the PRD rule "the per-worker concurrency cap is not exceeded"
    (§2.10 step 6) — and the number of assignments accepted before the refusal
    is the cap. The probe worker is discarded, so the probe leaves no rows on
    the worker any caller actually uses. Returns the cap.
    """
    requester = setup_requester(name="Ceiling Probe Requester", deposit_cents=20_000)
    probe_worker = setup_worker(display_name="Ceiling Probe Worker")
    accepted = 0
    for index in range(CONCURRENCY_PROBE_LIMIT):
        hit = create_published_task(
            requester["id"], title=f"Ceiling {index + 1}", reward_cents=100,
            max_assignments=1, assignment_duration_minutes=1,
            time_limit_minutes=1,
        )
        res = api_client.accept_hit(
            hit["id"], {"worker_id": probe_worker["id"]},
            make_worker_headers(probe_worker["id"]),
        )
        if res.status_code == 201:
            accepted += 1
            continue
        body = res.json().get("data") or {}
        assert body.get("error_id") == "ERR_CONCURRENCY_LIMIT_EXCEEDED", (
            f"Setup failed: expected the concurrency refusal, got "
            f"{res.status_code} {res.text}"
        )
        break
    else:  # pragma: no cover - a cap above the probe bound is not expected
        raise AssertionError(
            "Setup failed: no concurrency refusal within the probe bound"
        )
    assert accepted >= 1, "Setup failed: the platform admitted no assignment at all"
    return accepted


def setup_worker_at_concurrency_cap(deadline_minutes_first: int = 30,
                                    deadline_minutes_second: int = 600,
                                    **overrides) -> tuple:
    """A worker at the platform's real concurrency cap, holding one provably
    expirable assignment at the earliest deadline.

    The cap is discovered from the server rather than assumed (see
    ``server_concurrency_cap``). The victim carries the earliest deadline, a
    hold window that has already elapsed, and therefore the earliest deadline
    of the live set. Returns (requester, [hits], [assignments], worker).
    """
    cap = server_concurrency_cap()
    requester = setup_requester(name="Cap Requester", deposit_cents=20_000)
    worker = setup_worker(display_name="Cap Worker")

    # The victim is the earliest-deadline row, so it is the one the selector
    # must sacrifice. Its hold is still open at the assertion instant, so the
    # clock advance the acceptance test performs cannot collect it first.
    victim_hit = create_published_task(
        requester["id"], title="Cap A", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=deadline_minutes_first,
        time_limit_minutes=100_000,
    )
    victim = accept_task(victim_hit["id"], worker["id"])

    hits, assignments = [victim_hit], [victim]
    for index in range(cap - 1):
        hit = create_published_task(
            requester["id"], title=f"Cap B{index + 1}", reward_cents=100,
            max_assignments=1, assignment_duration_minutes=deadline_minutes_second,
            time_limit_minutes=100_000,
        )
        hits.append(hit)
        assignments.append(accept_task(hit["id"], worker["id"]))
    return requester, hits, assignments, worker


def setup_worker_all_live_submitted(num_live: int = 2, extra_hit: bool = True) -> tuple:
    """A worker whose live assignments are SUBMITTED and who sits AT the cap.

    The cap is discovered from the server (see ``server_concurrency_cap``), and
    every admitted slot is then filled with a SUBMITTED row, so the candidate
    set — ACCEPTED rows only (PRD §3.3) — is provably empty. The submitted rows
    carry a review window long enough that no sweep resolves one of them behind
    the test's back, which would quietly restore a free slot. Returns
    (requester, [hits], [assignments], worker, extra_hit_id).
    """
    cap = server_concurrency_cap()
    requester = setup_requester(name="Empty Requester", deposit_cents=20_000)
    worker = setup_worker(display_name="Empty Worker")
    num_live = max(num_live, cap)
    hits, assignments = [], []
    for index in range(num_live):
        hit = create_published_task(
            requester["id"], title=f"Empty {index + 1}", reward_cents=100,
            max_assignments=1, assignment_duration_minutes=100_000,
            time_limit_minutes=100_000,
        )
        assignment = accept_task(hit["id"], worker["id"])
        assignments.append(submit_assignment(assignment, worker["id"]))
        hits.append(hit)
    extra = None
    if extra_hit:
        extra = create_published_task(
            requester["id"], title="Empty Extra", reward_cents=100, max_assignments=1,
            assignment_duration_minutes=60, time_limit_minutes=300,
        )
    return requester, hits, assignments, worker, (extra["id"] if extra else None)


def setup_qualification_gate_scenario(threshold_pct: int = 80,
                                      default_score: int = 70) -> tuple:
    """A system qualification type plus one gated and one ungated task.

    Returns (qualification_type, requester, ungated_hit, gated_hit).
    """
    qualification_type = create_qualification_type(
        name="AccuracyGate", kind="SYSTEM",
        auto_assign_threshold_pct=threshold_pct, default_score=default_score,
    )
    requester = setup_requester(name="Gate Requester", deposit_cents=5_000)
    ungated = create_published_task(
        requester["id"], title="Gate A", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=300,
    )
    gated = create_published_task(
        requester["id"], title="Gate B", reward_cents=100, max_assignments=1,
        assignment_duration_minutes=60, time_limit_minutes=300,
        required_qualification_ids=[qualification_type["id"]],
    )
    return qualification_type, requester, ungated, gated


def setup_submitted_assignment_with_budget(bonus_budget_cents: int = 200,
                                           reward_cents: int = 100,
                                           approve: bool = True, **overrides) -> tuple:
    """A submitted (or approved) assignment on a task carrying a bonus budget."""
    return setup_approved_assignment(
        reward_cents=reward_cents, bonus_budget_cents=bonus_budget_cents,
        approve=approve, **overrides,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Scenario probes — named after the workflow shapes individual tests target
# ═════════════════════════════════════════════════════════════════════════════

def setup_review_probe(decision: str = "APPROVE", reward_cents: int = 100,
                       title: str = "Review Probe", deposit_cents: int = None,
                       submit_at_minutes: int = 40, country: str = "US",
                       max_assignments: int = 1, **hit_overrides) -> tuple:
    """One task whose single assignment is accepted, submitted and reviewed.

    ``decision`` is "APPROVE", "REJECT", or None to leave the assignment SUBMITTED.
    Returns (requester, hit, worker, assignment).
    """
    requester, hit = setup_requester_and_hit(
        reward_cents=reward_cents, max_assignments=max_assignments,
        title=title, deposit_cents=deposit_cents, **hit_overrides,
    )
    worker = setup_worker(country=country)
    assignment = accept_and_submit(hit, worker, submit_at_minutes)
    if decision == "APPROVE":
        assignment = approve_assignment(assignment["id"], requester["id"])
    elif decision == "REJECT":
        assignment = reject_assignment(assignment["id"], requester["id"])
    return requester, hit, worker, assignment


def setup_review_probe_multi_slot(decisions, reward_cents: int = 100,
                                  title: str = "Multi Probe", deposit_cents: int = None,
                                  submit_at_minutes: int = 40,
                                  **hit_overrides) -> tuple:
    """An n-slot task with one distinct worker per slot, each reviewed per ``decisions``.

    ``decisions`` is a sequence of "APPROVE" / "REJECT" / None. Each slot is
    accepted and submitted ``submit_at_minutes`` after the previous slot's
    submission, so every slot's own half-window has elapsed by the time it is
    reviewed (PRD §3.4). Returns (requester, hit, [workers], [assignments]).
    """
    slots = len(decisions)
    requester, hit = setup_requester_and_hit(
        reward_cents=reward_cents, max_assignments=slots,
        title=title, deposit_cents=deposit_cents, **hit_overrides,
    )
    workers, assignments = [], []
    for index, decision in enumerate(decisions):
        worker = setup_worker(display_name=f"{title} W{index + 1}")
        assignment = accept_and_submit(
            hit, worker, submit_at_minutes=submit_at_minutes, slot_index=index
        )
        if decision == "APPROVE":
            assignment = approve_assignment(assignment["id"], requester["id"])
        elif decision == "REJECT":
            assignment = reject_assignment(assignment["id"], requester["id"])
        workers.append(worker)
        assignments.append(assignment)
    return requester, hit, workers, assignments


def setup_requester_with_old_rejection_and_recent_approval() -> dict:
    """A requester holding one rejection outside the review window and one approval inside.

    A 2-slot task: W1 submits and is rejected at T0+40m. The clock then jumps 40
    days, putting that rejection outside the rolling window, and only afterwards
    does W2 accept the second slot, submit and get approved — so the approval is
    the only review inside the window and the window is genuinely non-empty.
    Lifetime counters read 1/1 (50%) while the windowed rate is 0.
    Returns the requester's fresh profile.
    """
    requester = setup_requester(name="Acme Surveys", deposit_cents=2_000)
    hit = create_published_task(
        requester["id"], title="Rate Probe", reward_cents=100, max_assignments=2,
        assignment_duration_minutes=60, time_limit_minutes=120,
    )
    first = setup_worker(display_name="W1 Old Rejection")
    assignment_one = accept_and_submit(hit, first, submit_at_minutes=40)
    reject_assignment(assignment_one["id"], requester["id"], reason="answers copied verbatim")

    set_clock(iso_at(days=40))
    second = setup_worker(display_name="W2 Recent Approval")
    assignment_two = accept_task(hit["id"], second["id"])
    set_clock(iso_at(minutes=40, days=40))
    assignment_two = submit_assignment(assignment_two, second["id"])
    approve_assignment(assignment_two["id"], requester["id"])
    return get_requester(requester["id"])


def setup_half_window_probe(assignment_duration_minutes: int = 60,
                            submit_at_minutes: int = 29) -> tuple:
    """One 1-slot task accepted at T0 and submitted before the half-window.

    Returns (requester, hit, worker, assignment) with the clock at
    ``submit_at_minutes`` past the acceptance instant.
    """
    requester, hit = setup_requester_and_hit(
        reward_cents=100, max_assignments=1,
        assignment_duration_minutes=assignment_duration_minutes,
        time_limit_minutes=300,
    )
    worker = setup_worker()
    assignment = accept_task(hit["id"], worker["id"])
    set_clock(iso_at(minutes=submit_at_minutes))
    assignment = submit_assignment(assignment, worker["id"])
    return requester, hit, worker, assignment


def setup_flagged_requester_probe() -> tuple:
    """A requester whose 2-slot task has one rejection and one recent approval.

    The windowed rejection rate is 50 — at or above the flag threshold but below
    the fraud threshold — and abuse-review has been run, flagging the requester
    while leaving it ACTIVE. Returns (requester, hit, workers, assignments).
    """
    requester, hit = setup_requester_and_hit(
        reward_cents=100, max_assignments=2, assignment_duration_minutes=60,
        time_limit_minutes=300, deposit_cents=2_000, name="Acme Flag",
    )
    workers, assignments = [], []
    for index, decision in enumerate(("REJECT", "APPROVE")):
        worker = setup_worker(display_name=f"Flag Worker {index + 1}")
        assignment = accept_and_submit(hit, worker, slot_index=index)
        if decision == "REJECT":
            assignment = reject_assignment(assignment["id"], requester["id"])
        else:
            assignment = approve_assignment(assignment["id"], requester["id"])
        workers.append(worker)
        assignments.append(assignment)
    api_client.run_abuse_review(requester["id"], TEST_USERS["admin_headers"])
    return get_requester(requester["id"]), hit, workers, assignments


def setup_worker_earnings_ready_for_payout(count: int = 2, country: str = "US",
                                           name: str = None,
                                           decide_at_minutes: int = 80,
                                           deposit_cents: int = 20_000,
                                           filler_cents: int = 720,
                                           payout_room_cents: int = 1_000) -> tuple:
    """A worker holding ``count`` approved 100c assignments plus one filler slot.

    The schedule keeps the logical clock monotone while dating every approval
    from a single instant, so a withdrawal raised straight afterwards has its
    vetting hold stamped from that instant and a three-day advance settles it.
    Each slot is accepted on its own staggered instant (all at least half of
    ``assignment_duration_minutes`` before ``decide_at_minutes``), every slot is
    then submitted at ``decide_at_minutes``, and every approval lands there too.
    The filler slot exists so a withdrawal can clear the country floor, whose
    minimum is above the reached amount only for the 1-slots-per-100c shape.
    Returns (requester, worker, [assignments]) for the ``count`` named slots.
    """
    requester = setup_requester(
        name=name or "Payout Schedule Requester", deposit_cents=deposit_cents
    )
    worker = setup_worker(country=country, display_name="Payout Schedule Worker")

    # Spread the acceptances across the minutes before the decision instant so
    # the LAST accepted slot has still cleared half its window at decision time.
    slots = [(f"Payout Slot {index + 1}", 100) for index in range(count)]
    if filler_cents:
        slots.append(("Payout Filler", filler_cents))
    if payout_room_cents:
        slots.append(("Payout Room", payout_room_cents))

    # Spread the acceptances across the minutes before the decision instant so
    # the last-accepted slot has still cleared half of its 60-minute window.
    room = max(0, decide_at_minutes - 30)
    stagger = room // max(1, len(slots) - 1) if len(slots) > 1 else 0

    # Accept every slot first (staggered so the last one still clears half its
    # window at the decision instant), then submit and approve them all at that
    # instant. Clustering the approvals on one instant matters twice: it is the
    # instant the caller's payout request is stamped from, and it keeps every
    # sketch inside the rolling 30-day review window the abuse machinery reads.
    assignments = []
    for slot_index, (title, reward) in enumerate(slots):
        set_clock(iso_at(minutes=slot_index * stagger))
        hit = create_published_task(
            requester["id"], title=title, reward_cents=reward,
            max_assignments=1, assignment_duration_minutes=60, time_limit_minutes=600,
        )
        assignments.append(accept_task(hit["id"], worker["id"]))

    set_clock(iso_at(minutes=decide_at_minutes))
    assignments = [submit_assignment(a, worker["id"]) for a in assignments]
    assignments = [
        approve_assignment(a["id"], requester["id"]) for a in assignments
    ]
    named = assignments[:count]
    return requester, worker, named


def setup_mixed_reward_worker() -> tuple:
    """A worker with two approved 100c tasks and two approved 5c tasks.

    Under the pinned per-assignment order the balance is 90 + 90 + 4 + 4 == 188;
    rounding the 210c gross once would instead yield 189. Returns
    (requester, worker, [assignments]).
    """
    requester = setup_requester(name="Mixed Reward Requester", deposit_cents=5_000)
    worker = setup_worker(display_name="Mixed Reward Worker")
    assignments = []
    for index, reward in enumerate((100, 100, 5, 5)):
        hit = create_published_task(
            requester["id"], title=f"Mixed {index + 1}", reward_cents=reward,
            max_assignments=1, assignment_duration_minutes=60, time_limit_minutes=300,
        )
        assignments.append(run_approval_chain(requester, hit, worker, slot_index=index))
    return requester, worker, assignments


def setup_suspended_worker_probe() -> tuple:
    """A worker suspended while holding one live ACCEPTED assignment.

    Returns (requester, hit, worker, assignment).
    """
    requester, hit = setup_requester_and_hit(
        reward_cents=100, max_assignments=1, assignment_duration_minutes=60,
        time_limit_minutes=300, name="Acme XA",
    )
    worker = setup_worker(display_name="W1 Suspended")
    assignment = accept_task(hit["id"], worker["id"])
    suspend_worker(worker["id"])
    return requester, hit, worker, assignment


def seed_review_history(requester: dict, decisions) -> None:
    """Accrue APPROVAL / REJECTION reviews for ``requester`` without editing any
    task's live state.

    Each decision uses its own single-slot task, submitted and then reviewed, and
    every task is left COMPLETED and terminal — so no task is still in DRAFT,
    PUBLISHED or DISPATCHED and the suspension cascade has nothing to cancel,
    which is exactly what the transparency tests need (they observe the flagging
    or suspension alone). Each slot is accepted a full ``half-window`` before it
    is submitted, so approval is legal (PRD §3.4).

    ``decisions`` is a sequence of "APPROVE" / "REJECT".
    """
    worker = setup_worker(display_name="Seed Worker")
    for index, decision in enumerate(decisions):
        accept_at = index * 40
        set_clock(iso_at(minutes=accept_at))
        hit = create_published_task(
            requester["id"], title=f"Seed {index + 1}", reward_cents=100,
            max_assignments=1, assignment_duration_minutes=60,
            time_limit_minutes=10_000,
        )
        assignment = accept_task(hit["id"], worker["id"])
        set_clock(iso_at(minutes=accept_at + 40))
        assignment = submit_assignment(assignment, worker["id"])
        if decision == "APPROVE":
            approve_assignment(assignment["id"], requester["id"])
        elif decision == "REJECT":
            reject_assignment(assignment["id"], requester["id"])


def setup_suspension_probe(num_slots: int = 3, all_submitted: bool = True) -> tuple:
    """A requester with ``num_slots`` distinct rejections and no live assignments left.

    The clock stays inside every time limit, so nothing expires for reasons other
    than the suspension cascade. Returns (requester, hit, [workers], [assignments]).
    """
    decisions = ["REJECT"] * num_slots
    requester, hit, workers, assignments = setup_review_probe_multi_slot(
        decisions, reward_cents=100, deposit_cents=2_000,
        title="Suspension Probe", assignment_duration_minutes=60,
        time_limit_minutes=300,
    )
    return requester, hit, workers, assignments


def setup_three_review_risk_probe() -> dict:
    """A requester whose 3-slot task took three rejections from three workers.

    The windowed rejection rate is 100 and three distinct workers were rejected,
    so the weighted risk sum exceeds the ceiling. Returns the requester's profile
    after abuse-review has run.
    """
    requester, hit, workers, assignments = setup_review_probe_multi_slot(
        ["REJECT", "REJECT", "REJECT"], reward_cents=100, deposit_cents=2_000,
        title="Risk Probe", assignment_duration_minutes=60, time_limit_minutes=300,
    )
    api_client.run_abuse_review(requester["id"], TEST_USERS["admin_headers"])
    return get_requester(requester["id"])


def setup_exam_probe(passing_score: int = 80, kind: str = "REQUESTER",
                     auto_assign_threshold_pct: int = 90, **exam_overrides) -> tuple:
    """A qualification type carrying an exam, plus a worker ready to attempt it.

    Returns (qualification_type, exam, worker).
    """
    qualification_type = create_qualification_type(
        name="Accuracy", kind=kind,
        auto_assign_threshold_pct=auto_assign_threshold_pct, exam_available=True,
    )
    exam = create_exam(qualification_type["id"], passing_score=passing_score, **exam_overrides)
    worker = setup_worker(display_name="W1 Exam")
    return qualification_type, exam, worker