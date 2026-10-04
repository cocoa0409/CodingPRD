"""Orphan policy reassignment (PRD §3.8; scaffold §1.2 OrphanPolicyAssignment)."""

from db import db, ts
from errors import (
    err,
    ERR_ORPHAN_ASSIGNMENT_NOT_FOUND,
    ERR_POLICY_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_NO_ELIGIBLE_ADVISOR,
)
from services import derived


def get(assignment_id):
    row = db.orphans.get(assignment_id)
    if row is None:
        raise err(ERR_ORPHAN_ASSIGNMENT_NOT_FOUND,
                  "no orphan policy assignment with id %s" % assignment_id)
    return row


def _eligible_pool(assignment, policy):
    """PRD §3.8 filter: same district office as the policy's writing office,
    contract_status IN {VALIDATING, VALIDATED}, validation_posture IN
    {VALIDATING, VALIDATED}, appointment_status APPROVED, and id != from_advisor_id."""
    from_advisor = db.advisors.get(assignment["from_advisor_id"])
    office_id = from_advisor["district_office_id"] if from_advisor else None

    pool = []
    for advisor in db.advisors.values():
        if office_id is not None and advisor["district_office_id"] != office_id:
            continue
        if advisor["contract_status"] not in ("VALIDATING", "VALIDATED"):
            continue
        if advisor["validation_posture"] not in ("VALIDATING", "VALIDATED"):
            continue
        if advisor["appointment_status"] != "APPROVED":
            continue
        if advisor["id"] == assignment["from_advisor_id"]:
            continue
        pool.append(advisor)
    # Ranked by team_production_cents ASC, ties by created_at ASC, then id ASC.
    pool.sort(key=lambda a: (a.get("team_production_cents", 0),
                             a.get("created_at") or "",
                             a.get("id") or ""))
    return pool


def assign(assignment):
    if assignment["status"] == "ASSIGNED":
        raise err(ERR_ALREADY_TERMINAL, "the assignment is already ASSIGNED")
    if assignment["status"] == "REJECTED":
        raise err(ERR_INVALID_STATE,
                  "a rejected assignment must be reopened before assignment")
    policy = db.policies.get(assignment["policy_id"])
    if policy is None:
        raise err(ERR_POLICY_NOT_FOUND, "the assignment's policy no longer exists")
    if not policy["orphaned"]:
        raise err(ERR_INVALID_STATE, "the policy is not orphaned")

    pool = _eligible_pool(assignment, policy)
    if not pool:
        # Empty-pool rejection: the assignment resolves to REJECTED with
        # NO_ELIGIBLE_ADVISOR and the policy stays orphaned; the same condition
        # is also reported as the ERR_NO_ELIGIBLE_ADVISOR error (PRD §3.8).
        assignment["status"] = "REJECTED"
        assignment["rejection_reason"] = "NO_ELIGIBLE_ADVISOR"
        db.touch(assignment)
        raise err(ERR_NO_ELIGIBLE_ADVISOR,
                  "the selector resolved an empty eligible advisor pool")

    chosen = pool[0]
    assignment["to_advisor_id"] = chosen["id"]
    assignment["status"] = "ASSIGNED"
    assignment["assigned_at"] = ts(db.now())
    db.touch(assignment)

    policy["writing_advisor_id"] = chosen["id"]
    policy["orphaned"] = False
    db.touch(policy)

    derived.recompute_team_production(chosen["id"])
    derived.cascade_rollups()
    return assignment


def reopen(assignment):
    if assignment["status"] != "REJECTED":
        raise err(ERR_INVALID_STATE, "only a rejected assignment may be reopened")
    policy = db.policies.get(assignment["policy_id"])
    if policy is None:
        raise err(ERR_POLICY_NOT_FOUND, "the assignment's policy no longer exists")
    if not policy["orphaned"]:
        raise err(ERR_INVALID_STATE, "the policy is not orphaned")
    assignment["status"] = "PENDING"
    assignment["rejection_reason"] = None
    db.touch(assignment)
    return assignment