"""Requester trust-and-safety service (PRD §3.7, §3.9).

Implements the rolling-window rejection rate, the weighted risk score, the
flag/fraud thresholds, the suspension cascade, reinstatement, and the
append-only review ledger.
"""

import statistics

from apptime import diff_days, now, shift
from config import (
    ABUSE_DECAY_DAYS,
    ABUSE_FLAG_THRESHOLD_PCT,
    BONUS_ABUSE_POINTS,
    FRAUD_REVIEW_THRESHOLD_PCT,
    REVIEW_WINDOW_DAYS,
    W_DISTINCT_WORKER,
    W_REJECTION,
    W_SPEED,
)
from db import db, common_fields, touch
from errors import fail
from rounding import round_half_up, rate as pct_rate

DECISION_KINDS = {"APPROVAL", "REJECTION"}


def owned_review_rows(requester_id: str) -> list:
    """Reviews whose assignment belongs to this requester's HITs."""
    rows = []
    for r in db.reviews.values():
        assignment = db.assignments.get(r["assignment_id"])
        if assignment is None:
            continue
        hire = db.hits.get(assignment["hit_id"])
        if hire is None or hire["requester_id"] != requester_id:
            continue
        rows.append(r)
    return rows


def window_decision_rows(requester_id: str) -> list:
    """Decision reviews inside the rolling window; BONUS rows excluded.

    Boundary is inclusive at the lower edge: a review created exactly
    REVIEW_WINDOW_DAYS before the clock is still inside the window.
    """
    floor = shift(now(), days=-REVIEW_WINDOW_DAYS)
    return [
        r
        for r in owned_review_rows(requester_id)
        if r["kind"] in DECISION_KINDS and (r.get("created_at") or "") >= floor
    ]


def window_rejection_rate(rows: list) -> int:
    """100 when the window is empty; else round_half_up(100*rej/total)."""
    rejected = sum(1 for r in rows if r["kind"] == "REJECTION")
    total = len(rows)
    if total == 0:
        return 100
    return pct_rate(rejected, total)


def window_rejection_population(rows: list) -> int:
    return sum(1 for r in rows if r["kind"] == "REJECTION")


def distinct_rejected_workers(rows: list) -> int:
    workers = set()
    for r in rows:
        if r["kind"] != "REJECTION":
            continue
        assignment = db.assignments.get(r["assignment_id"])
        if assignment is not None:
            workers.add(assignment["worker_id"])
    return len(workers)


def median_review_days(rows: list) -> float:
    """Median latency in days from submission to approval/rejection; 0 if empty."""
    latencies = []
    for r in rows:
        assignment = db.assignments.get(r["assignment_id"])
        if assignment is None or not assignment.get("submitted_at"):
            continue
        resolved_at = r.get("created_at")
        if r["kind"] == "APPROVAL" and assignment.get("approved_at"):
            resolved_at = assignment["approved_at"]
        latencies.append(diff_days(resolved_at, assignment["submitted_at"]))
    if not latencies:
        return 0.0
    return float(statistics.median(latencies))


def risk_score(rows: list, window_rate_pct: int) -> int:
    """Weighted risk figure, clamped to [0, 100] with the clamp applied last.

    risk = rate*W_REJECTION + distinct_workers*W_DISTINCT_WORKER
           + max(0, ABUSE_DECAY_DAYS - median_review_days) * W_SPEED
    """
    median_days = median_review_days(rows)
    speed_term = max(0.0, ABUSE_DECAY_DAYS - median_days) * float(W_SPEED)
    raw = (
        window_rate_pct * float(W_REJECTION)
        + distinct_rejected_workers(rows) * float(W_DISTINCT_WORKER)
        + speed_term
    )
    score = round_half_up(raw)
    return max(0, min(100, score))


# --- derived counters ------------------------------------------------------
def recompute_requester_counts(requester_row: dict) -> None:
    """approved_count / rejected_count are pure counts of own-HIT reviews."""
    approved = 0
    rejected = 0
    for r in owned_review_rows(requester_row["id"]):
        if r["kind"] == "APPROVAL":
            approved += 1
        elif r["kind"] == "REJECTION":
            rejected += 1
    requester_row["approved_count"] = approved
    requester_row["rejected_count"] = rejected


def lifetime_rejection_rate(requester_row: dict) -> int:
    approved = requester_row.get("approved_count", 0)
    rejected = requester_row.get("rejected_count", 0)
    denom = approved + rejected
    return 100 if denom == 0 else pct_rate(rejected, denom)


# --- review ledger ---------------------------------------------------------
def append_review(assignment: dict, actor_id: str, actor_role: str, kind: str,
                  reason=None, bonus_cents: int = 0) -> dict:
    """Append an immutable Review row (no updated_at, no version)."""
    hire = db.hits.get(assignment["hit_id"])
    requester_row = db.requesters.get(hire["requester_id"]) if hire else None
    abuse_points = 0
    if (
        kind == "REJECTION"
        and requester_row is not None
        and requester_row.get("task_abuse_flag")
    ):
        abuse_points = BONUS_ABUSE_POINTS
    row = {"id": common_fields()["id"], "created_at": now()}
    row.update(
        {
            "assignment_id": assignment["id"],
            "actor_requester_id": actor_id,
            "actor_role": actor_role,
            "kind": kind,
            "bonus_cents": bonus_cents,
            "abuse_points": abuse_points,
            "reason": reason,
        }
    )
    db.reviews[row["id"]] = row
    if requester_row is not None:
        recompute_requester_counts(requester_row)
        refresh_risk_only(requester_row)
        touch(requester_row)
    return row


def refresh_risk_only(requester_row: dict) -> None:
    """Recompute the derived abuse score without touching flag or status."""
    rows = window_decision_rows(requester_row["id"])
    requester_row["abuse_score"] = risk_score(rows, window_rejection_rate(rows))


# --- manual abuse review ---------------------------------------------------
def abuse_review(requester_row: dict) -> dict:
    """POST /mkt/requesters/{id}/abuse-review.

    Below the flag threshold there is nothing to act on and the evaluation is
    refused with ERR_REQUESTER_REVIEW_NOT_TRIGGERED. An empty rolling window is
    treated as "nothing to act on": its rate figure is the defined 100, but no
    rejection population exists to justify flagging or suspending an account.
    """
    rows = window_decision_rows(requester_row["id"])
    if window_rejection_population(rows) == 0:
        fail("ERR_REQUESTER_REVIEW_NOT_TRIGGERED")
    window_rate = window_rejection_rate(rows)
    if window_rate < ABUSE_FLAG_THRESHOLD_PCT:
        requester_row["task_abuse_flag"] = False
        touch(requester_row)
        fail("ERR_REQUESTER_REVIEW_NOT_TRIGGERED")

    requester_row["abuse_score"] = risk_score(rows, window_rate)

    if window_rate >= FRAUD_REVIEW_THRESHOLD_PCT:
        # The fraud path suspends: the published suspension stamp (ABUSE_AUTO
        # plus a score of 10) replaces the computed figure.
        return suspend(requester_row)

    requester_row["task_abuse_flag"] = True
    touch(requester_row)
    return requester_row


def suspend(requester_row: dict) -> dict:
    """Suspend the requester and cascade the cancellation of every open HIT."""
    requester_row["abuse_score"] = 10
    requester_row["suspension_reason"] = "ABUSE_AUTO"
    requester_row["status"] = "SUSPENDED"
    touch(requester_row)

    for hire in list(db.hits.values()):
        if hire["requester_id"] != requester_row["id"]:
            continue
        if hire["status"] not in {"DRAFT", "PUBLISHED", "DISPATCHED"}:
            continue
        hire["escrowed_cents"] = 0
        hire["status"] = "CANCELLED"
        touch(hire)
        for assignment in list(db.assignments.values()):
            if assignment["hit_id"] != hire["id"]:
                continue
            # A row already SUBMITTED has been handed in and carries a review
            # the ledger and the §3.5 dispute path still reference, so the
            # cancellation strands only what is still in the worker's hands.
            # The PRD renders the cascade's selectors ("every task ... still in
            # DRAFT, PUBLISHED, or DISPATCHED is cancelled", "every assignment
            # still in ACCEPTED, SUBMITTED, or RETURNED") but never its per-row
            # state write; expiring a SUBMITTED row here would erase the
            # rejection record that the threshold, the overcommit guard and the
            # risk score all read.
            if assignment["status"] not in {"ACCEPTED", "RETURNED"}:
                continue
            assignment["committed"] = False
            assignment["assignment_expired"] = True
            assignment["status"] = "EXPIRED"
            touch(assignment)
            owning_worker = db.workers.get(assignment["worker_id"])
            if owning_worker is not None:
                owning_worker["expired_count"] = owning_worker.get("expired_count", 0) + 1
                touch(owning_worker)

    from services.hit_service import resync_requester

    resync_requester(requester_row)
    touch(requester_row)
    return requester_row


def reinstate(requester_row: dict) -> dict:
    """Clear the flag, reset the score, and return the account to ACTIVE.

    HITs cancelled by the suspension are not revived: terminal states are never
    re-entered.
    """
    requester_row["task_abuse_flag"] = False
    requester_row["abuse_score"] = 0
    requester_row["suspension_reason"] = "NONE"
    requester_row["status"] = "ACTIVE"
    touch(requester_row)
    return requester_row