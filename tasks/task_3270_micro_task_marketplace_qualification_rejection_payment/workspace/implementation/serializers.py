"""Resource serialisation.

Each serializer emits exactly the field set the scaffold's §1.1 entity table
declares, in that order. Derived figures (`approval_rate_pct`,
`total_earned_cents`, `withdrawable_cents`, `eligible_for_approval`,
`lifetime_rejection_rate_pct`) are computed at render time so a response can
never disagree with the rows it is derived from.
"""

import math
from decimal import Decimal

from config import (
    ABUSE_FLAG_THRESHOLD_PCT,
    DISPUTE_WINDOW_HOURS,
    FRAUD_REVIEW_THRESHOLD_PCT,
    REVIEW_WINDOW_DAYS,
    WORKER_COMMISSION_RATE,
)
from db import db
from rounding import rate, round_half_up
from services.common import elapsed_minutes_since, is_terminal_assignment


def _int(value, default=0):
    return default if value is None else value


# --- Requester -------------------------------------------------------------
def requester(row: dict) -> dict:
    approved = _int(row.get("approved_count"))
    rejected = _int(row.get("rejected_count"))
    denom = approved + rejected
    lifetime = 100 if denom == 0 else rate(rejected, denom)
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "name": row["name"],
        "prepaid_balance_cents": _int(row.get("prepaid_balance_cents")),
        "escrowed_cents": _int(row.get("escrowed_cents")),
        "lifetime_spent_cents": _int(row.get("lifetime_spent_cents")),
        "approved_count": approved,
        "rejected_count": rejected,
        "lifetime_rejection_rate_pct": lifetime,
        "abuse_score": _int(row.get("abuse_score")),
        "task_abuse_flag": bool(row.get("task_abuse_flag", False)),
        "suspension_reason": row.get("suspension_reason"),
        "status": row["status"],
    }


# --- Worker ----------------------------------------------------------------
def worker(row: dict) -> dict:
    approved = _int(row.get("approved_count"))
    rejected = _int(row.get("rejected_count"))
    denom = approved + rejected
    approval_rate = 100 if denom == 0 else rate(approved, denom)
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "display_name": row["display_name"],
        "country": row["country"],
        "approval_rate_pct": approval_rate,
        "approved_count": approved,
        "rejected_count": rejected,
        "returned_count": _int(row.get("returned_count")),
        "expired_count": _int(row.get("expired_count")),
        "total_earned_cents": total_earned_cents(row["id"]),
        "withdrawable_cents": withdrawable_cents(row["id"]),
        "identity_verified": bool(row.get("identity_verified", False)),
        "status": row["status"],
    }


def total_earned_cents(worker_id: str) -> int:
    """Sum of per-assignment nets over this worker's APPROVED assignments.

    Per-assignment rounding, then sum (never sum-then-round); each net is
    floored at zero (calculation: worker_net_earning).
    """
    total = 0
    approved = [
        a
        for a in db.assignments.values()
        if a["worker_id"] == worker_id and a["status"] == "APPROVED"
    ]
    approved.sort(key=lambda a: (a.get("approved_at") or "", a.get("sequence") or 0))
    for a in approved:
        hire = db.hits.get(a["hit_id"], {})
        gross = _int(hire.get("reward_cents")) + _int(a.get("bonus_cents"))
        commission = round_half_up(Decimal(gross) * Decimal(WORKER_COMMISSION_RATE))
        net = gross - commission
        total += net if net > 0 else 0
    return total


def reserved_payout_cents(worker_id: str) -> int:
    """Sum of payout requests in PAID or HELD_FOR_VETTING (reserved funds)."""
    return sum(
        _int(p.get("amount_cents"))
        for p in db.payouts.values()
        if p["worker_id"] == worker_id and p["status"] in {"PAID", "HELD_FOR_VETTING"}
    )


def withdrawable_cents(worker_id: str) -> int:
    return total_earned_cents(worker_id) - reserved_payout_cents(worker_id)


# --- WorkerQualification ---------------------------------------------------
def worker_qualification(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "worker_id": row["worker_id"],
        "qualification_type_id": row["qualification_type_id"],
        "score": _int(row.get("score")),
        "source": row["source"],
        "status": row["status"],
    }


# --- QualificationType -----------------------------------------------------
def qualification_type(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "name": row["name"],
        "kind": row["kind"],
        "exam_available": bool(row.get("exam_available", False)),
        "auto_assign_threshold_pct": _int(row.get("auto_assign_threshold_pct")),
        "default_score": _int(row.get("default_score")),
    }


# --- QualificationExam -----------------------------------------------------
def qualification_exam(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "qualification_type_id": row["qualification_type_id"],
        "passing_score": _int(row.get("passing_score")),
        "max_attempts": _int(row.get("max_attempts"), 3),
        "retake_cooldown_days": _int(row.get("retake_cooldown_days")),
    }


# --- QualificationExamAttempt ---------------------------------------------
def exam_attempt(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "exam_id": row["exam_id"],
        "sequence": _int(row.get("sequence")),
        "score": _int(row.get("score")),
        "outcome": row["outcome"],
    }


# --- HIT -------------------------------------------------------------------
def hit(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "requester_id": row["requester_id"],
        "title": row["title"],
        "reward_cents": _int(row.get("reward_cents")),
        "required_qualification_ids": list(row.get("required_qualification_ids") or []),
        "max_assignments": _int(row.get("max_assignments")),
        "assignment_duration_minutes": _int(row.get("assignment_duration_minutes")),
        "time_limit_minutes": _int(row.get("time_limit_minutes")),
        "bonus_budget_cents": _int(row.get("bonus_budget_cents")),
        "funds_required_cents": _int(row.get("funds_required_cents")),
        "escrowed_cents": _int(row.get("escrowed_cents")),
        "accepted_count": _int(row.get("accepted_count")),
        "assignment_count": _int(row.get("assignment_count")),
        "committed_assignments": _int(row.get("committed_assignments")),
        "spent_rewards_cents": _int(row.get("spent_rewards_cents")),
        "spent_bonus_cents": _int(row.get("spent_bonus_cents")),
        "status": row["status"],
    }


def hit_provisional_spent(hit_row: dict) -> int:
    """Requester-facing projection: adds SUBMITTED rewards, deadline_at ASC."""
    rows = [
        a
        for a in db.assignments.values()
        if a["hit_id"] == hit_row["id"] and a["status"] in {"APPROVED", "SUBMITTED"}
    ]
    rows.sort(key=lambda a: (a.get("deadline_at") or "", a.get("sequence") or 0))
    return sum(_int(hit_row.get("reward_cents")) for _ in rows)


# --- Assignment ------------------------------------------------------------
def assignment(row: dict) -> dict:
    hire = db.hits.get(row["hit_id"], {})
    duration = _int(hire.get("assignment_duration_minutes"))
    elapsed = elapsed_minutes_since(row["accepted_at"])
    eligible = elapsed >= math.floor(duration / 2)
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "hit_id": row["hit_id"],
        "worker_id": row["worker_id"],
        "sequence": _int(row.get("sequence")),
        "deadline_at": row.get("deadline_at"),
        "review_expires_at": row.get("review_expires_at"),
        "submitted_at": row.get("submitted_at"),
        "approved_at": row.get("approved_at"),
        "bonus_cents": _int(row.get("bonus_cents")),
        "eligible_for_approval": bool(eligible),
        "approval_rate_effect_applied": bool(row.get("approval_rate_effect_applied", False)),
        "committed": bool(row.get("committed", False)),
        "rejection_reason": row.get("rejection_reason"),
        "dispute_reason": row.get("dispute_reason"),
        "status": row["status"],
        "assignment_expired": bool(row.get("assignment_expired", False)),
    }


# --- RequesterDeposit ------------------------------------------------------
def deposit(row: dict) -> dict:
    requester_row = db.requesters.get(row["requester_id"], {})
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "requester_id": row["requester_id"],
        "amount_cents": _int(row.get("amount_cents")),
        "status": row["status"],
        # Informational only: mirrors the requester's pool, never consulted by
        # any conservation check (PRD §2.8).
        "escrowed_cents": _int(requester_row.get("escrowed_cents")),
        "refunded_cents": _int(row.get("refunded_cents")),
    }


# --- PayoutRequest ---------------------------------------------------------
def payout(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "worker_id": row["worker_id"],
        "payment_method": row["payment_method"],
        "amount_cents": _int(row.get("amount_cents")),
        "hold_until_at": row.get("hold_until_at"),
        "identity_verified_at": row.get("identity_verified_at"),
        "status": row["status"],
        "rejection_reason": row.get("rejection_reason"),
    }


# --- Review (no updated_at / version: append-only audit row) ---------------
def review(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "assignment_id": row["assignment_id"],
        "actor_requester_id": row["actor_requester_id"],
        "actor_role": row["actor_role"],
        "kind": row["kind"],
        "bonus_cents": _int(row.get("bonus_cents")),
        "abuse_points": _int(row.get("abuse_points")),
        "reason": row.get("reason"),
    }


# Re-exported so route modules can reference the pinned thresholds in one place.
__all__ = [
    "requester",
    "worker",
    "worker_qualification",
    "qualification_type",
    "qualification_exam",
    "exam_attempt",
    "hit",
    "assignment",
    "deposit",
    "payout",
    "review",
    "total_earned_cents",
    "withdrawable_cents",
    "hit_provisional_spent",
    "REVIEW_WINDOW_DAYS",
    "ABUSE_FLAG_THRESHOLD_PCT",
    "FRAUD_REVIEW_THRESHOLD_PCT",
    "DISPUTE_WINDOW_HOURS",
]