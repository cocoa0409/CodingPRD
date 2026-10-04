"""Assignment lifecycle service.

Covers acceptance, the concurrency selector, return, submission, review
(approve / reject / bonus), dispute, administrative resolution, and the two
expiry sweeps (time-limit collection and review-window auto-approval).
"""

from apptime import now, shift
from config import (
    DISPUTE_WINDOW_HOURS,
    MAX_CONCURRENT_ASSIGNMENTS,
    REVIEW_WINDOW_HOURS,
)
from db import db, common_fields, touch
from errors import fail
from services import hit_service
from services.common import (
    assignment_expired_now,
    dispute_deadline,
    elapsed_minutes_since,
    is_terminal_assignment,
    review_expires_at,
)
from services.qualification_service import (
    gate_snapshot_record,
    holds_all_required,
    recompute_worker_rate,
)
from services.requester_service import append_review

LIVE_STATES = {"ACCEPTED", "SUBMITTED"}
TERMINAL_STATES = {"APPROVED", "REJECTED", "RETURNED", "EXPIRED"}


# --- clock-relative predicates --------------------------------------------
def eligible_for_approval(assignment: dict) -> bool:
    """elapsed_minutes >= floor(duration/2), measured in whole minutes.

    The boundary is >= : exactly half the window is already approvable.
    """
    hire = db.hits.get(assignment["hit_id"], {})
    duration = hire.get("assignment_duration_minutes", 0)
    half_window = duration // 2
    return elapsed_minutes_since(assignment["accepted_at"]) >= half_window


def worker_live_count(worker_id: str) -> int:
    """Assignments occupying the worker's concurrency budget.

    Terminal states (including RETURNED and EXPIRED) release their slot, so
    only ACCEPTED and SUBMITTED assignments count against the cap.
    """
    return sum(
        1
        for a in db.assignments.values()
        if a["worker_id"] == worker_id and a["status"] in LIVE_STATES
    )


# --- expiry ---------------------------------------------------------------
def expire_assignment(assignment: dict, hit_row: dict, worker_row: dict,
                      bump_hit: bool = True) -> None:
    """Collect an overdue ACCEPTED assignment into EXPIRED.

    The pool never refills: accepted_count is deliberately left untouched.
    """
    assignment["committed"] = False
    assignment["assignment_expired"] = True
    assignment["status"] = "EXPIRED"
    touch(assignment)
    if worker_row is not None:
        worker_row["expired_count"] = worker_row.get("expired_count", 0) + 1
        touch(worker_row)
    hit_service.recompute_hit_counts(hit_row)
    if bump_hit:
        touch(hit_row)


def write_path_expiry_guard(assignment: dict) -> None:
    """Collect an assignment whose window has elapsed, without reporting it.

    The submission path layers its own ERR_ASSIGNMENT_EXPIRED refusal on top;
    the return path declares only the state error.
    """
    if assignment["status"] != "ACCEPTED":
        return
    if not assignment_expired_now(assignment):
        return
    hit_row = db.hits.get(assignment["hit_id"])
    worker_row = db.workers.get(assignment["worker_id"])
    if hit_row is None:
        return
    expire_assignment(assignment, hit_row, worker_row)


def write_path_expiry_guard_or_fail(assignment: dict) -> None:
    """The submission guard: expiry wins over any operation on a stale window.

    A worker submitting against an assignment whose window has already elapsed
    finds it collected first and the operation refused with
    ERR_ASSIGNMENT_EXPIRED (PRD §3.4).
    """
    if assignment["status"] != "ACCEPTED":
        return
    if not assignment_expired_now(assignment):
        return
    write_path_expiry_guard(assignment)
    fail("ERR_ASSIGNMENT_EXPIRED")


def overdue_by_limit(assignment: dict, hit_row: dict) -> bool:
    if assignment["status"] != "ACCEPTED":
        return False
    return assignment_expired_now(assignment)


# --- concurrency selector --------------------------------------------------
def selector_candidates(worker_id: str) -> list:
    """(a) status == ACCEPTED only; (b) deadline_at ASC; (c) sequence ASC.

    The selector never consults Assignment.id or Worker.id.
    """
    rows = [
        a
        for a in db.assignments.values()
        if a["worker_id"] == worker_id and a["status"] == "ACCEPTED"
    ]
    rows.sort(key=lambda a: (a.get("deadline_at") or "", a.get("sequence") or 0))
    return rows


# --- acceptance -----------------------------------------------------------
def mint_assignment(hit_row: dict, worker_row: dict) -> dict:
    """Mint an ACCEPTED assignment and consume a pool slot."""
    accepted_at = now()
    seq = db.worker_assign_seq.get(worker_row["id"], 0) + 1
    db.worker_assign_seq[worker_row["id"]] = seq

    row = common_fields()
    row.update(
        {
            "hit_id": hit_row["id"],
            "worker_id": worker_row["id"],
            "sequence": seq,
            "accepted_at": accepted_at,
            "deadline_at": shift(
                accepted_at, minutes=hit_row["assignment_duration_minutes"]
            ),
            "review_expires_at": None,
            "submitted_at": None,
            "approved_at": None,
            "bonus_cents": 0,
            "eligible_for_approval": False,
            "approval_rate_effect_applied": False,
            "committed": True,
            "rejection_reason": None,
            "dispute_reason": None,
            "status": "ACCEPTED",
            "assignment_expired": False,
        }
    )
    db.assignments[row["id"]] = row
    # Snapshot the gate: captured once, at acceptance, and frozen for life.
    db.assignment_gate_snapshot[row["id"]] = holds_all_required(
        worker_row["id"], hit_row.get("required_qualification_ids") or []
    )

    hit_service.recompute_hit_counts(hit_row)
    if hit_row["status"] == "PUBLISHED":
        hit_row["status"] = "DISPATCHED"
    touch(hit_row)

    if hit_row["accepted_count"] == hit_row["max_assignments"]:
        gate_snapshot_record(hit_row, worker_row)
    return row


def accept(hit_row: dict, worker_row: dict) -> dict:
    """Acceptance gates, in the platform's fixed order (PRD §3.3)."""
    # Step 4 - state: acceptance is declared only from PUBLISHED / DISPATCHED.
    if hit_row["status"] not in {"PUBLISHED", "DISPATCHED"}:
        fail("ERR_INVALID_STATE")
    # Step 5 - actor safety.
    if worker_row["status"] != "ACTIVE":
        fail("ERR_WORKER_SUSPENDED")
    # Step 6 - business constraints, in the order the PRD lists them.
    if not holds_all_required(
        worker_row["id"], hit_row.get("required_qualification_ids") or []
    ):
        fail("ERR_QUALIFICATION_REQUIRED")
    if hit_row["accepted_count"] >= hit_row["max_assignments"]:
        fail("ERR_HIT_MAX_ASSIGNMENTS_REACHED")
    if worker_live_count(worker_row["id"]) >= MAX_CONCURRENT_ASSIGNMENTS:
        fail("ERR_CONCURRENCY_LIMIT_EXCEEDED")
    return mint_assignment(hit_row, worker_row)


def concurrency_check(hit_row: dict, worker_row: dict) -> dict:
    """Free a slot by the selector, or mint one when a slot is already free."""
    if hit_row["status"] not in {"PUBLISHED", "DISPATCHED"}:
        fail("ERR_INVALID_STATE")
    if worker_row["status"] != "ACTIVE":
        fail("ERR_WORKER_SUSPENDED")
    if hit_row["accepted_count"] >= hit_row["max_assignments"]:
        fail("ERR_HIT_MAX_ASSIGNMENTS_REACHED")
    if not holds_all_required(
        worker_row["id"], hit_row.get("required_qualification_ids") or []
    ):
        fail("ERR_QUALIFICATION_REQUIRED")

    if worker_live_count(worker_row["id"]) < MAX_CONCURRENT_ASSIGNMENTS:
        return mint_assignment(hit_row, worker_row)

    candidates = selector_candidates(worker_row["id"])
    if not candidates:
        # Every live assignment is SUBMITTED: nothing may be silently dropped.
        fail("ERR_CONCURRENCY_LIMIT_EXCEEDED")
    chosen = candidates[0]
    chosen_hit = db.hits.get(chosen["hit_id"])
    expire_assignment(chosen, chosen_hit, worker_row)
    return mint_assignment(hit_row, worker_row)


# --- return ---------------------------------------------------------------
def return_assignment(assignment: dict, worker_row: dict) -> dict:
    """Hand an ACCEPTED assignment back before its time limit.

    Refused when the assignment is the worker's last live assignment against a
    task they have already worked (ERR_ALREADY_COMPLETED_HIT) - the duplicate
    guard that stops a worker cycling slots on a task they have already had
    decided.
    """
    hit_row = db.hits[assignment["hit_id"]]
    if assignment["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE")
    if worker_row["status"] != "ACTIVE":
        fail("ERR_WORKER_SUSPENDED")
    # Returning is gated on the window (PRD §3.3: allowed only while the clock
    # is still strictly before acceptance + time_limit_minutes); a row past it
    # is collected, and the return's own refusal is the state error.
    write_path_expiry_guard(assignment)
    if assignment["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE")

    if _is_last_live_on_worked_hit(assignment, worker_row):
        fail("ERR_ALREADY_COMPLETED_HIT")

    assignment["committed"] = False
    assignment["status"] = "RETURNED"
    touch(assignment)
    worker_row["returned_count"] = worker_row.get("returned_count", 0) + 1
    touch(worker_row)
    # The pool does NOT refill: accepted_count is derived from the row count,
    # which is unchanged, so the ceiling is not lifted.
    hit_service.recompute_hit_counts(hit_row)
    touch(hit_row)
    return assignment


def _is_last_live_on_worked_hit(assignment: dict, worker_row: dict) -> bool:
    """TRUE when this is the worker's only live assignment on a HIT they have
    already had decided (an APPROVED or REJECTED assignment on the same HIT)."""
    same_hit = [
        a
        for a in db.assignments.values()
        if a["worker_id"] == worker_row["id"] and a["hit_id"] == assignment["hit_id"]
    ]
    live = [a for a in same_hit if a["status"] in {"ACCEPTED", "SUBMITTED"}]
    already_worked = any(a["status"] in {"APPROVED", "REJECTED", "DISPUTED"} for a in same_hit)
    return len(live) == 1 and already_worked


# --- submission -----------------------------------------------------------
def submit(assignment: dict, worker_row: dict, expected_version) -> dict:
    """Advance ACCEPTED -> SUBMITTED."""
    # Optimistic concurrency (PRD §2.10 step 8) outranks the state check: the
    # submission body's only required field is the last-observed version, so a
    # stale presentation is refused as such even when the assignment is no
    # longer in a state that declares the transition.
    check_assignment_version(assignment, expected_version)
    if assignment["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE")
    if worker_row["status"] != "ACTIVE":
        fail("ERR_WORKER_SUSPENDED")
    # Temporal window: expiry wins over an otherwise-valid submission.
    write_path_expiry_guard_or_fail(assignment)

    submitted_at = now()
    assignment["submitted_at"] = submitted_at
    assignment["review_expires_at"] = shift(submitted_at, hours=REVIEW_WINDOW_HOURS)
    assignment["status"] = "SUBMITTED"
    touch(assignment)
    return assignment


def check_assignment_version(assignment: dict, expected) -> None:
    """OCC guard on assignment submission (SCAFFOLD §1.2.1-adjacent, PRD §2.7)."""
    if expected is None:
        fail("ERR_INVALID_REQUEST", "Field 'expected_assignment_version' is required.")
    if int(expected) != assignment["version"]:
        fail("ERR_STALE_VERSION")


# --- approval -------------------------------------------------------------
def approve(assignment: dict, requester_row: dict, actor_id: str,
            actor_role: str = "REQUESTER") -> dict:
    """Advance SUBMITTED -> APPROVED and credit the worker."""
    if assignment["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    # Structural gate: an assignment carrying a rejection cannot be approved.
    if has_review_kind(assignment["id"], "REJECTION"):
        fail("ERR_INVALID_STATE")
    if not eligible_for_approval(assignment):
        fail("ERR_REVIEW_TOO_EARLY")

    hit_row = db.hits[assignment["hit_id"]]
    worker_row = db.workers[assignment["worker_id"]]
    approved_at = now()

    assignment["approved_at"] = approved_at
    assignment["approval_rate_effect_applied"] = True
    # Approval finalises the slot: the reward is now spent rather than held,
    # so the committed flag clears and committed_assignments falls toward zero.
    assignment["committed"] = False
    assignment["status"] = "APPROVED"
    touch(assignment)

    worker_row["approved_count"] = worker_row.get("approved_count", 0) + 1
    append_review(
        assignment=assignment,
        actor_id=actor_id,
        actor_role=actor_role,
        kind="APPROVAL",
    )
    recompute_worker_rate(worker_row)

    hit_service.recompute_hit_spent_rewards(hit_row)
    # The approval finalised the slot, so the counters are re-derived BEFORE
    # the completion gate reads them (PRD §3.8 gates on accepted_count /
    # every-assignment-terminal / committed_assignments == 0).
    hit_service.recompute_hit_counts(hit_row)
    touch(hit_row)
    hit_service.complete_hit(hit_row)
    return assignment


def has_review_kind(assignment_id: str, kind: str) -> bool:
    return any(
        r["assignment_id"] == assignment_id and r["kind"] == kind
        for r in db.reviews.values()
    )


# --- rejection ------------------------------------------------------------
def reject(assignment: dict, requester_row: dict, actor_id: str, reason) -> dict:
    """Advance SUBMITTED -> REJECTED."""
    if assignment["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    if reason is None or not str(reason).strip():
        fail("ERR_REJECTION_REASON_REQUIRED")
    # Structural gate: an assignment carrying an approval cannot be rejected.
    if has_review_kind(assignment["id"], "APPROVAL"):
        fail("ERR_INVALID_STATE")

    hit_row = db.hits[assignment["hit_id"]]
    worker_row = db.workers[assignment["worker_id"]]

    assignment["rejection_reason"] = str(reason)
    assignment["rejected_at"] = now()
    assignment["committed"] = False
    assignment["approval_rate_effect_applied"] = True
    assignment["status"] = "REJECTED"
    touch(assignment)

    worker_row["rejected_count"] = worker_row.get("rejected_count", 0) + 1
    append_review(
        assignment=assignment,
        actor_id=actor_id,
        actor_role="REQUESTER",
        kind="REJECTION",
        reason=str(reason),
    )
    recompute_worker_rate(worker_row)

    hit_service.recompute_hit_counts(hit_row)
    touch(hit_row)
    hit_service.complete_hit(hit_row)
    return assignment


# --- bonus ----------------------------------------------------------------
def bonus(assignment: dict, requester_row: dict, actor_id: str, bonus_cents: int) -> dict:
    """Pay a discretionary bonus on an APPROVED or SUBMITTED assignment."""
    if assignment["status"] not in {"APPROVED", "SUBMITTED"}:
        fail("ERR_INVALID_STATE")
    hit_row = db.hits[assignment["hit_id"]]
    # Fiscal check, evaluated last: the task's bonus budget is a hard ceiling.
    if hit_row["spent_bonus_cents"] + bonus_cents > hit_row["bonus_budget_cents"]:
        fail("ERR_BONUS_BUDGET_EXCEEDED")

    assignment["bonus_cents"] = assignment.get("bonus_cents", 0) + bonus_cents
    touch(assignment)
    append_review(
        assignment=assignment,
        actor_id=actor_id,
        actor_role="REQUESTER",
        kind="BONUS",
        bonus_cents=bonus_cents,
    )
    hit_service.recompute_hit_spent_bonus(hit_row)
    touch(hit_row)
    return assignment


# --- dispute --------------------------------------------------------------
def dispute(assignment: dict, worker_row: dict, reason) -> dict:
    """Advance REJECTED -> DISPUTED. The damage is NOT undone here."""
    if assignment["status"] != "REJECTED":
        fail("ERR_INVALID_STATE")
    if assignment.get("dispute_used"):
        fail("ERR_DISPUTE_ALREADY_USED")
    rejected_at = assignment.get("rejected_at") or assignment["updated_at"]
    if now() > dispute_deadline(rejected_at):
        fail("ERR_DISPUTE_WINDOW_CLOSED")

    assignment["dispute_reason"] = None if reason is None else str(reason)
    assignment["dispute_used"] = True
    assignment["disputed_at"] = now()
    assignment["status"] = "DISPUTED"
    touch(assignment)
    return assignment


# --- administrative resolution --------------------------------------------
def admin_resolve(assignment: dict, decision: str, reason=None,
                  admin_id: str = "platform_admin") -> dict:
    """Resolve a DISPUTED assignment by APPROVE or UPHOLD."""
    if assignment["status"] != "DISPUTED":
        fail("ERR_INVALID_STATE")
    if decision == "APPROVE":
        return _resolve_approve(assignment, admin_id)
    if decision == "UPHOLD":
        return _resolve_uphold(assignment)
    fail("ERR_INVALID_STATE")


def _resolve_approve(assignment: dict, admin_id: str) -> dict:
    """The only path in the system that reverses approval-rate damage."""
    hit_row = db.hits[assignment["hit_id"]]
    worker_row = db.workers[assignment["worker_id"]]

    assignment["approved_at"] = now()
    assignment["status"] = "APPROVED"
    assignment["committed"] = False
    touch(assignment)

    worker_row["rejected_count"] = max(0, worker_row.get("rejected_count", 0) - 1)
    worker_row["approved_count"] = worker_row.get("approved_count", 0) + 1
    append_review(
        assignment=assignment,
        actor_id=admin_id,
        actor_role="PLATFORM_ADMIN",
        kind="APPROVAL",
    )
    recompute_worker_rate(worker_row)

    hit_service.recompute_hit_spent_rewards(hit_row)
    hit_service.recompute_hit_counts(hit_row)
    touch(hit_row)
    hit_service.complete_hit(hit_row)
    return assignment


def _resolve_uphold(assignment: dict) -> dict:
    """The rejection stands; no further dispute is permitted."""
    assignment["status"] = "REJECTED"
    assignment["dispute_used"] = True
    touch(assignment)
    hit_row = db.hits[assignment["hit_id"]]
    hit_service.complete_hit(hit_row)
    return assignment


# --- explicit HIT expiration sweep ----------------------------------------
def sweep_hit_expired(hit_row: dict, expected_version) -> dict:
    """POST /mkt/hits/{hit_id}/sweep-expired.

    The sweep is not a passive read: even when its target is genuinely expired
    and correct to collect, the version guard applies first, and the HIT's
    version advances by exactly one.
    """
    if hit_row["status"] not in {"PUBLISHED", "DISPATCHED"}:
        fail("ERR_INVALID_STATE")
    check_hit_version(hit_row, expected_version)

    overdue = [
        a
        for a in db.assignments.values()
        if a["hit_id"] == hit_row["id"] and overdue_by_limit(a, hit_row)
    ]
    if not overdue:
        fail("ERR_ASSIGNMENT_NOT_EXPIRED")

    for assignment in overdue:
        worker_row = db.workers.get(assignment["worker_id"])
        expire_assignment(assignment, hit_row, worker_row, bump_hit=False)
    touch(hit_row)
    hit_service.complete_hit(hit_row)
    return hit_row


def check_hit_version(hit_row: dict, expected) -> None:
    """OCC guard on HIT cancellation and the HIT expiration sweep."""
    if expected is None:
        fail("ERR_INVALID_REQUEST", "Field 'expected_hit_version' is required.")
    if int(expected) != hit_row["version"]:
        fail("ERR_STALE_VERSION")


# --- automatic sweeps ------------------------------------------------------
def sweep_assignments_due() -> None:
    """Collect every ACCEPTED assignment past accepted_at + time_limit_minutes."""
    for assignment in list(db.assignments.values()):
        if assignment["status"] != "ACCEPTED":
            continue
        hit_row = db.hits.get(assignment["hit_id"])
        if hit_row is None:
            continue
        if assignment_expired_now(assignment):
            worker_row = db.workers.get(assignment["worker_id"])
            expire_assignment(assignment, hit_row, worker_row, bump_hit=False)


def auto_approve_due() -> None:
    """Auto-approve SUBMITTED assignments whose review window has lapsed.

    The mirror image of the manual approval: it ignores the
    eligible_for_approval gate, stamps approved_at with the expiry instant
    rather than the current one, reaches the same cascades, and is a no-op for
    any assignment an explicit review has already resolved.
    """
    for assignment in list(db.assignments.values()):
        if assignment["status"] != "SUBMITTED":
            continue
        expires = assignment.get("review_expires_at")
        if not expires or now() < expires:
            continue
        hit_row = db.hits.get(assignment["hit_id"])
        worker_row = db.workers.get(assignment["worker_id"])
        if hit_row is None or worker_row is None:
            continue

        assignment["approved_at"] = expires
        assignment["approval_rate_effect_applied"] = True
        assignment["committed"] = False
        assignment["status"] = "APPROVED"
        touch(assignment)

        worker_row["approved_count"] = worker_row.get("approved_count", 0) + 1
        append_review(
            assignment=assignment,
            actor_id=hit_row["requester_id"],
            actor_role="REQUESTER",
            kind="APPROVAL",
        )
        recompute_worker_rate(worker_row)
        hit_service.recompute_hit_spent_rewards(hit_row)
        hit_service.recompute_hit_counts(hit_row)
        touch(hit_row)
        hit_service.complete_hit(hit_row)