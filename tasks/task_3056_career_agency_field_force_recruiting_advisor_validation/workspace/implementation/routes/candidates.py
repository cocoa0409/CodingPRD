"""RecruitingCandidate and SelectionAssessment endpoints (§1.5; PRD §3.1, §3.2)."""

from flask import Blueprint, request

from db import db, parse_dt, ts
from errors import err, ERR_INVALID_REQUEST, ERR_CANDIDATE_NOT_FOUND
from middleware import body, required, pagination, page, as_enum
from response import ok, ok_list
from routes._shared import authed
from services import assessment as assessment_svc, recruiting, serialize

bp = Blueprint("candidates", __name__)
READ = ["Any"]
SOURCE_CHANNELS = ("CAMPUS", "CAREER_CHANGER", "REFERRAL", "INTERNAL")
VERSIONS = ("V1", "V2")


def candidate_by_id(candidate_id):
    if candidate_id not in db.candidates:
        raise err(ERR_CANDIDATE_NOT_FOUND,
                  "no recruiting candidate with id %s" % candidate_id)
    return db.candidates[candidate_id]


@bp.post("/agency/recruiting-candidates")
@authed(["RecruitingOfficer"])
def create(user_id, role):
    data = body()
    # Existence first along the body's FK list (PRD §2.10), then structural
    # payload validity.
    office_id = data.get("district_office_id")
    if office_id not in db.district_offices:
        from errors import ERR_DISTRICT_OFFICE_NOT_FOUND
        raise err(ERR_DISTRICT_OFFICE_NOT_FOUND,
                  "no district office with id %s" % office_id)
    prior = data.get("prior_candidate_id")
    if prior is not None and prior not in db.candidates:
        raise err(ERR_CANDIDATE_NOT_FOUND,
                  "no recruiting candidate with id %s" % prior)
    from middleware import require_fields
    require_fields(data, ["full_name", "source_channel"])
    source_channel = as_enum(data, "source_channel", SOURCE_CHANNELS)
    row = {
        "full_name": data.get("full_name"),
        "source_channel": source_channel,
        "campus_name": data.get("campus_name"),
        "district_office_id": office_id,
        "prior_candidate_id": prior,
        "stage": "SOURCED",
        "reengagement_count": 0,
        "entered_stage_at": ts(db.now()),
        "notes": data.get("notes"),
    }
    db.stamp_create(row)
    db.insert(db.candidates, row)
    return ok(serialize.candidate(row), 201)


@bp.get("/agency/recruiting-candidates")
@authed(READ)
def list_candidates(user_id, role):
    limit, offset = pagination()
    filters = {
        "stage": request.args.get("stage"),
        "source_channel": request.args.get("source_channel"),
        "district_office_id": request.args.get("district_office_id"),
    }
    items = [c for c in db.candidates.values()
             if all(value is None or c.get(key) == value for key, value in filters.items())]
    selected = page(items, limit, offset)
    return ok_list([serialize.candidate(c) for c in selected], limit, offset, len(items))


@bp.get("/agency/recruiting-candidates/<candidate_id>")
@authed(READ)
def get_candidate(user_id, role, candidate_id):
    return ok(serialize.candidate(candidate_by_id(candidate_id)))


@bp.post("/agency/recruiting-candidates/<candidate_id>/screen")
@authed(["RecruitingOfficer"])
def screen(user_id, role, candidate_id):
    row = candidate_by_id(candidate_id)
    recruiting.screen(row)
    return ok(serialize.candidate(row))


@bp.post("/agency/recruiting-candidates/<candidate_id>/schedule-assessment")
@authed(["RecruitingOfficer"])
def schedule(user_id, role, candidate_id):
    row = candidate_by_id(candidate_id)
    data = body()
    version = as_enum(data, "assessment_version", VERSIONS)
    scheduled_date = data.get("scheduled_date")
    created = recruiting.schedule_assessment(
        row, version, parse_dt(scheduled_date) if scheduled_date is not None else None)
    return ok(serialize.assessment(created), 200)


@bp.post("/agency/recruiting-candidates/<candidate_id>/advance-to-interview")
@authed(["RecruitingOfficer"])
def advance(user_id, role, candidate_id):
    row = candidate_by_id(candidate_id)
    recruiting.advance_to_interview(row)
    return ok(serialize.candidate(row))


@bp.post("/agency/recruiting-candidates/<candidate_id>/extend-offer")
@authed(["DistrictDirector"])
def extend(user_id, role, candidate_id):
    row = candidate_by_id(candidate_id)
    recruiting.extend_offer(row)
    return ok(serialize.candidate(row))


@bp.post("/agency/recruiting-candidates/<candidate_id>/accept-offer")
@authed(["RecruitingOfficer"])
def accept(user_id, role, candidate_id):
    row = candidate_by_id(candidate_id)
    recruiting.accept_offer(row)
    return ok(serialize.candidate(row))


@bp.post("/agency/recruiting-candidates/<candidate_id>/decline-offer")
@authed(["RecruitingOfficer"])
def decline(user_id, role, candidate_id):
    row = candidate_by_id(candidate_id)
    recruiting.decline_offer(row)
    return ok(serialize.candidate(row))


@bp.post("/agency/recruiting-candidates/<candidate_id>/reengage")
@authed(["RecruitingOfficer"])
def reengage(user_id, role, candidate_id):
    row = candidate_by_id(candidate_id)
    recruiting.reengage(row)
    return ok(serialize.candidate(row))


@bp.post("/agency/recruiting-candidates/<candidate_id>/reject")
@authed(["DistrictDirector"])
def reject(user_id, role, candidate_id):
    row = candidate_by_id(candidate_id)
    recruiting.reject(row)
    return ok(serialize.candidate(row))


@bp.get("/agency/recruiting-candidates/<candidate_id>/selection-assessments")
@authed(READ)
def candidate_assessments(user_id, role, candidate_id):
    candidate_by_id(candidate_id)
    limit, offset = pagination()
    status = request.args.get("status")
    version = request.args.get("assessment_version")
    items = [a for a in db.assessments.values()
             if a["candidate_id"] == candidate_id
             and (status is None or a["status"] == status)
             and (version is None or a["assessment_version"] == version)]
    selected = page(items, limit, offset)
    return ok_list([serialize.assessment(a) for a in selected], limit, offset, len(items))


@bp.get("/agency/recruiting-candidates/<candidate_id>/reengagements")
@authed(READ)
def reengagements(user_id, role, candidate_id):
    candidate_by_id(candidate_id)
    limit, offset = pagination()
    items = [c for c in db.candidates.values() if c["prior_candidate_id"] == candidate_id]
    selected = page(items, limit, offset)
    return ok_list([serialize.candidate(c) for c in selected], limit, offset, len(items))


@bp.get("/agency/recruiting-candidates/<candidate_id>/employment-contracts")
@authed(READ)
def candidate_contracts(user_id, role, candidate_id):
    candidate_by_id(candidate_id)
    limit, offset = pagination()
    items = [c for c in db.contracts.values() if c["candidate_id"] == candidate_id]
    selected = page(items, limit, offset)
    return ok_list([serialize.contract(c) for c in selected], limit, offset, len(items))


# ---------------------------------------------------------------------------
# SelectionAssessment
# ---------------------------------------------------------------------------
@bp.get("/agency/selection-assessments/<assessment_id>")
@authed(READ)
def get_assessment(user_id, role, assessment_id):
    return ok(serialize.assessment(assessment_svc.get(assessment_id)))


@bp.post("/agency/selection-assessments/<assessment_id>/score")
@authed(["RecruitingOfficer"])
def score_assessment(user_id, role, assessment_id):
    row = assessment_svc.get(assessment_id)
    data = body()
    raw_score = data.get("raw_score")
    competency_scores = data.get("competency_scores")
    created = recruiting.score_assessment(row, raw_score, competency_scores)
    return ok(serialize.assessment(created))


@bp.post("/agency/selection-assessments/<assessment_id>/supersede")
@authed(["RecruitingOfficer"])
def supersede(user_id, role, assessment_id):
    row = assessment_svc.get(assessment_id)
    if row["status"] == "SUPERSEDED" or row["status"] == "INVALIDATED":
        from errors import ERR_ALREADY_TERMINAL
        raise err(ERR_ALREADY_TERMINAL, "the assessment is terminal")
    if row["status"] != "SCORED":
        from errors import ERR_INVALID_STATE
        raise err(ERR_INVALID_STATE, "the assessment is not SCORED")
    recruiting.supersede_assessment(row)
    return ok(serialize.assessment(row))


@bp.post("/agency/selection-assessments/<assessment_id>/invalidate")
@authed(["RecruitingOfficer"])
def invalidate(user_id, role, assessment_id):
    row = assessment_svc.get(assessment_id)
    if row["status"] in ("SUPERSEDED", "INVALIDATED"):
        from errors import ERR_ALREADY_TERMINAL
        raise err(ERR_ALREADY_TERMINAL, "the assessment is terminal")
    if row["status"] != "SCHEDULED":
        from errors import ERR_INVALID_STATE
        raise err(ERR_INVALID_STATE, "the assessment is not SCHEDULED")
    recruiting.invalidate_assessment(row)
    return ok(serialize.assessment(row))