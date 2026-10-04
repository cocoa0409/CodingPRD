"""Qualification register service.

Two mechanisms live here:

* `cascade_qualifications` — the approval-rate cascade (PRD §2.9). Whenever a
  worker's approval_rate_pct is recomputed, every SYSTEM qualification type is
  re-evaluated. Reaching a type's auto_assign_threshold_pct mints or refreshes
  a CASCADE grant in ACTIVE status at the type's default_score; falling back
  below revokes it. Only CASCADE rows are ever touched: a grant earned by
  passing an exam is permanent.
* Exam attempts (PRD §3.2) — the per-worker attempt cap, the retake cooldown,
  and the EXAM grant upsert on a pass.
"""

from apptime import diff_seconds, now
from db import db, common_fields, touch
from errors import fail
from rounding import rate


def worker_approval_rate(worker_row: dict) -> int:
    approved = worker_row.get("approved_count", 0)
    rejected = worker_row.get("rejected_count", 0)
    denom = approved + rejected
    return 100 if denom == 0 else rate(approved, denom)


def recompute_worker_rate(worker_row: dict) -> int:
    """Recompute the live rate, cascade the SYSTEM grants, and bump the row.

    A recomputation rewrites a derived field, so the worker's version and
    updated_at advance with it (PRD §2.5).
    """
    live_rate = worker_approval_rate(worker_row)
    cascade_qualifications(worker_row, live_rate)
    touch(worker_row)
    return live_rate


def find_grant(worker_id: str, type_id: str, source: str):
    for row in db.worker_qualifications.values():
        if (
            row["worker_id"] == worker_id
            and row["qualification_type_id"] == type_id
            and row["source"] == source
        ):
            return row
    return None


def cascade_qualifications(worker_row: dict, live_rate: int) -> None:
    for qtype in db.qualification_types.values():
        if qtype["kind"] != "SYSTEM":
            continue
        threshold = qtype.get("auto_assign_threshold_pct", 0)
        meets = live_rate >= threshold
        grant = find_grant(worker_row["id"], qtype["id"], "CASCADE")
        if meets:
            if grant is None:
                row = common_fields()
                row.update(
                    {
                        "worker_id": worker_row["id"],
                        "qualification_type_id": qtype["id"],
                        "score": qtype.get("default_score", 0),
                        "source": "CASCADE",
                        "status": "ACTIVE",
                    }
                )
                db.worker_qualifications[row["id"]] = row
            else:
                changed = False
                if grant["status"] != "ACTIVE":
                    grant["status"] = "ACTIVE"
                    changed = True
                if grant.get("score") != qtype.get("default_score", 0):
                    grant["score"] = qtype.get("default_score", 0)
                    changed = True
                if changed:
                    touch(grant)
        else:
            if grant is not None and grant["status"] == "ACTIVE":
                grant["status"] = "REVOKED"
                touch(grant)


# --- exam attempts ---------------------------------------------------------
def attempts_for(worker_id: str, exam_id: str) -> list:
    rows = [
        a
        for a in db.exam_attempts.values()
        if a["worker_id"] == worker_id and a["exam_id"] == exam_id
    ]
    rows.sort(key=lambda a: (a.get("sequence") or 0, a.get("created_at") or ""))
    return rows


def submit_attempt(exam: dict, worker_row: dict, score: int) -> dict:
    """Record a scored attempt according to the scaffold's side effects.

    Returns the QualificationExamAttempt row. The attempt counter that enforces
    max_attempts is the count of attempt rows, not any outcome value.
    """
    attempts = attempts_for(worker_row["id"], exam["id"])

    if len(attempts) >= exam["max_attempts"]:
        fail("ERR_QUALIFICATION_EXAM_ATTEMPTS_EXCEEDED")
    cooldown_days = exam.get("retake_cooldown_days", 0)
    if attempts and cooldown_days:
        last = attempts[-1]
        elapsed_days = diff_seconds(now(), last["created_at"]) / 86400.0
        if elapsed_days < cooldown_days:
            fail("ERR_QUALIFICATION_EXAM_COOLDOWN_ACTIVE")

    row = common_fields()
    offset = len(attempts)
    row.update(
        {
            "exam_id": exam["id"],
            "worker_id": worker_row["id"],
            "sequence": offset + 1,
            "score": score,
            "outcome": "PASSED" if score >= exam["passing_score"] else "FAILED",
        }
    )
    db.exam_attempts[row["id"]] = row

    if row["outcome"] == "PASSED":
        grant = find_grant(worker_row["id"], exam["qualification_type_id"], "EXAM")
        if grant is None:
            granted = common_fields()
            granted.update(
                {
                    "worker_id": worker_row["id"],
                    "qualification_type_id": exam["qualification_type_id"],
                    "score": score,
                    "source": "EXAM",
                    "status": "ACTIVE",
                }
            )
            db.worker_qualifications[granted["id"]] = granted
        else:
            # Re-granting refreshes the score and status, never duplicates.
            if grant["score"] != score or grant["status"] != "ACTIVE":
                grant["score"] = score
                grant["status"] = "ACTIVE"
                touch(grant)
    return row


def gate_snapshot_record(hire: dict, worker_row: dict) -> None:
    """Freeze the worker's live approval rate when the HIT first reaches full cap.

    The snapshot is what drives any later appraisal of the pool (calculation:
    qualification_gate_snapshot). It is recorded once, at the instant
    accepted_count reaches max_assignments, and never overwritten.
    """
    if hire["id"] in db.hit_admission_rate:
        return
    db.hit_admission_rate[hire["id"]] = {
        "worker_id": worker_row["id"],
        "admission_rate_pct": worker_approval_rate(worker_row),
        "captured_at": now(),
    }


def holds_all_required(worker_id: str, required_ids) -> bool:
    """Snapshot predicate: live ACTIVE grants for every required type id."""
    if not required_ids:
        return True
    held = {
        row["qualification_type_id"]
        for row in db.worker_qualifications.values()
        if row["worker_id"] == worker_id and row["status"] == "ACTIVE"
    }
    return all(tid in held for tid in required_ids)