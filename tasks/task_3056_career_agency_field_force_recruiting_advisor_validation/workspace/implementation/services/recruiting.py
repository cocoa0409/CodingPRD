"""Recruiting pipeline service (scaffold §1.2 RecruitingCandidate, PRD §3.1/§3.2)."""

from db import db, ts
from errors import (
    err,
    ERR_CANDIDATE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_CAMPUS_NAME_REQUIRED,
    ERR_ASSESSMENT_NOT_PASSED,
    ERR_INVALID_REQUEST,
)
from services import assessment as assessment_svc

TERMINAL_STAGES = ("CONTRACTED", "REJECTED", "OFFER_DECLINED")
LIVE_ASSESSMENT_STATUSES = ("SCHEDULED", "SCORED")


def get(candidate_id):
    row = db.candidates.get(candidate_id)
    if row is None:
        raise err(ERR_CANDIDATE_NOT_FOUND,
                  "no recruiting candidate with id %s" % candidate_id)
    return row


def set_stage(candidate, stage):
    candidate["stage"] = stage
    candidate["entered_stage_at"] = ts(db.now())
    db.touch(candidate)


def require_stage(candidate, *allowed):
    if candidate["stage"] not in allowed:
        raise err(ERR_INVALID_STATE,
                  "candidate is %s, expected one of %s"
                  % (candidate["stage"], ", ".join(allowed)))


def require_not_terminal(candidate):
    if candidate["stage"] in TERMINAL_STAGES:
        raise err(ERR_ALREADY_TERMINAL, "candidate is already in a terminal stage")


def screen(candidate):
    require_stage(candidate, "SOURCED", "REENGAGED")
    # PRD §3.1: a CAMPUS candidate's campus_name must be present, and that
    # refusal happens before the transition is attempted.
    if candidate["source_channel"] == "CAMPUS" and not candidate.get("campus_name"):
        raise err(ERR_CAMPUS_NAME_REQUIRED,
                  "a CAMPUS candidate requires campus_name before screening")
    set_stage(candidate, "SCREENED")


def schedule_assessment(candidate, assessment_version, scheduled_date):
    # The stage check is a state rule and comes first, so a recognized stage
    # outranks structural payload validity (PRD §2.10).
    require_stage(candidate, "SCREENED")
    if scheduled_date is None:
        raise err(ERR_INVALID_REQUEST, "scheduled_date is required")
    row = {
        "candidate_id": candidate["id"],
        "assessment_version": assessment_version,
        "scheduled_date": scheduled_date,
        "scored_date": None,
        "raw_score": None,
        "competency_scores": None,
        "weighted_score": None,
        "outcome": None,
        "locked_weights": None,
        "status": "SCHEDULED",
    }
    db.stamp_create(row)
    db.insert(db.assessments, row)
    set_stage(candidate, "ASSESSMENT_PENDING")
    return row


def advance_to_interview(candidate):
    require_stage(candidate, "ASSESSED")
    selected = assessment_svc.selected_assessment(candidate["id"])
    if selected is None or selected["outcome"] == "FAIL":
        raise err(ERR_ASSESSMENT_NOT_PASSED,
                  "the candidate's selected assessment is not a pass")
    set_stage(candidate, "INTERVIEW_READY")


def extend_offer(candidate):
    require_stage(candidate, "INTERVIEW_READY")
    office = db.district_offices.get(candidate["district_office_id"])
    if office is None or office["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE,
                  "the recruiting district office is not ACTIVE")
    set_stage(candidate, "OFFER_EXTENDED")


def accept_offer(candidate):
    require_stage(candidate, "OFFER_EXTENDED")
    set_stage(candidate, "OFFER_ACCEPTED")


def decline_offer(candidate):
    require_stage(candidate, "OFFER_EXTENDED")
    set_stage(candidate, "OFFER_DECLINED")


def reengage(candidate):
    require_stage(candidate, "OFFER_DECLINED", "REJECTED")
    # The terminal-stage check is folded in by the declared transition set: a
    # candidate already at a terminal stage is refused above.
    candidate["reengagement_count"] = candidate.get("reengagement_count", 0) + 1
    for row in assessment_svc.of_candidate(candidate["id"]):
        if row["status"] in LIVE_ASSESSMENT_STATUSES:
            row["status"] = "SUPERSEDED"
            db.touch(row)
    set_stage(candidate, "REENGAGED")


def reject(candidate):
    require_not_terminal(candidate)
    for row in assessment_svc.of_candidate(candidate["id"]):
        if row["status"] in LIVE_ASSESSMENT_STATUSES:
            row["status"] = "INVALIDATED"
            db.touch(row)
    set_stage(candidate, "REJECTED")


# ---------------------------------------------------------------------------
# Assessment fork (PRD §3.2)
# ---------------------------------------------------------------------------
def supersede_assessment(assessment):
    candidate = get(assessment["candidate_id"])
    require_stage(candidate, "ASSESSED")
    assessment["status"] = "SUPERSEDED"
    db.touch(assessment)
    set_stage(candidate, "ASSESSMENT_PENDING")


def invalidate_assessment(assessment):
    candidate = get(assessment["candidate_id"])
    assessment["status"] = "INVALIDATED"
    db.touch(assessment)
    set_stage(candidate, "SCREENED")


def score_assessment(assessment, raw_score, competency_scores):
    """Cross-machine (scaffold §1.2 SelectionAssessment note): the same request
    advances both the assessment and, when the candidate is still at
    ASSESSMENT_PENDING, the candidate."""
    candidate = get(assessment["candidate_id"])
    assessment_svc.score(assessment, raw_score, competency_scores)
    if candidate["stage"] == "ASSESSMENT_PENDING":
        set_stage(candidate, "ASSESSED")
    return assessment