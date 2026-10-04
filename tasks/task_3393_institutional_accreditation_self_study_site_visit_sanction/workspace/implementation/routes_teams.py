"""Review teams, assignments, site visit scheduling and reports (§3.5-§3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import constants as C
from auth import authenticate, check_liaison_chain, institution_of_team, require_role
from calculations import recommended_action
from db import STORE, _parse_iso_datetime, fmt_dt
from errors import (ERR_CYCLE_PREREQUISITE_NOT_MET, ERR_INVALID_STATE,
                    ERR_REVIEW_CYCLE_NOT_FOUND, ERR_REVIEW_TEAM_NOT_FOUND,
                    ERR_REVIEWER_NOT_ASSIGNED, ERR_REVIEWER_CAPACITY_EXCEEDED,
                    ERR_REVIEWER_WINDOW_CONFLICT, ERR_STALE_VERSION,
                    ERR_TEAM_ASSIGNMENT_NOT_FOUND, ERR_TEAM_INCOMPLETE,
                    ERR_VALIDATION, raise_err)
from helpers import (fetch_or_404, get_body, new_entity, paginate,
                     req_enum, req_int, req_list, req_string,
                     reviewer_assignment_count, serialize, touch)
from response import success_list, success_object
from selector import (eligible_candidates, make_assignment, pick_chair,
                      pick_members, replacement_candidate)

bp = Blueprint("teams", __name__)


def _ser_team(team):
    return serialize(team)


@bp.post("/accreditation/review-cycles/<cycle_id>/review-teams")
def assemble_team(cycle_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    body = get_body()
    modality = req_enum(body, "visit_modality", C.VISIT_MODALITIES)
    expected = req_int(body, "expected_review_cycle_version")
    if expected != cycle["version"]:
        raise_err(ERR_STALE_VERSION, "expected_review_cycle_version does not match current version")
    for t in STORE.review_teams.values():
        if t["review_cycle_id"] == cycle_id and t["status"] != "DISBANDED":
            raise_err(ERR_INVALID_STATE, "A cycle may hold at most one non-DISBANDED team")
    candidates = eligible_candidates(cycle)
    chair = pick_chair(candidates)
    members = pick_members(candidates, chair)
    team = new_entity({
        "review_cycle_id": cycle_id,
        "visit_modality": modality,
        "status": "PROPOSED",
        "chair_reviewer_id": chair["id"],
        "visit_start_at": None,
        "visit_end_at": None,
        "_visit_start_dt": None,
        "_visit_end_dt": None,
        "criterion_ratings": [],
        "report_recommendation": None,
        "report_summary": None,
        "recommended_action_computed": None,
        "report_filed_at": None,
    })
    STORE.review_teams[team["id"]] = team
    make_assignment(team, chair, "CHAIR")
    for m in members:
        make_assignment(team, m, "MEMBER")
    touch(cycle)  # team assembly advances the cycle version (§2.7)
    return success_object(_ser_team(team), code=201)


@bp.get("/accreditation/review-cycles/<cycle_id>/review-teams")
def list_teams(cycle_id):
    actor = authenticate()
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, cycle["institution_id"])
    items = [t for t in STORE.review_teams.values() if t["review_cycle_id"] == cycle_id]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.get("/accreditation/review-teams/<team_id>")
def get_team(team_id):
    actor = authenticate()
    team = fetch_or_404(STORE.review_teams, team_id, ERR_REVIEW_TEAM_NOT_FOUND)
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, institution_of_team(team))
    return success_object(_ser_team(team))


@bp.get("/accreditation/review-teams/<team_id>/assignments")
def list_team_assignments(team_id):
    actor = authenticate()
    team = fetch_or_404(STORE.review_teams, team_id, ERR_REVIEW_TEAM_NOT_FOUND)
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, institution_of_team(team))
    items = [a for a in STORE.team_assignments.values() if a["review_team_id"] == team_id]
    reviewer_id = request.args.get("reviewer_id")
    if reviewer_id is not None:
        items = [a for a in items if a["reviewer_id"] == reviewer_id]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.post("/accreditation/team-assignments/<assignment_id>/respond")
def respond_assignment(assignment_id):
    actor = authenticate()
    require_role(actor, ["PeerReviewer"])
    assignment = fetch_or_404(STORE.team_assignments, assignment_id, ERR_TEAM_ASSIGNMENT_NOT_FOUND)
    body = get_body()
    response = req_enum(body, "response", C.ASSIGNMENT_RESPONSES)
    if assignment["response"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "This assignment has already been answered")
    if assignment["reviewer_id"] != actor.user_id:
        raise_err(ERR_REVIEWER_NOT_ASSIGNED, "A reviewer may answer only their own assignment")
    reviewer = STORE.reviewers.get(assignment["reviewer_id"])
    team = STORE.review_teams.get(assignment["review_team_id"])
    if response == "ACCEPT":
        # Capacity: count already includes this PENDING assignment (§3.5).
        if reviewer_assignment_count(actor.user_id) > C.MAX_CONCURRENT_ASSIGNMENTS:
            raise_err(ERR_REVIEWER_CAPACITY_EXCEEDED,
                      "Acceptance would push the reviewer past 3 concurrent assignments")
        assignment["response"] = "ACCEPTED"
        touch(assignment)
        return success_object(serialize(assignment))
    # DECLINE: close the assignment and offer the seat to a replacement.
    assignment["response"] = "DECLINED"
    assignment["status"] = "CLOSED"
    touch(assignment)
    if reviewer is not None:
        touch(reviewer)  # load bookkeeping (reviewer_load_conservation)
    if team is not None and team["status"] != "DISBANDED":
        replacement = replacement_candidate(team, assignment["role_on_team"])
        if replacement is not None:
            new_a = make_assignment(team, replacement, assignment["role_on_team"])
            if assignment["role_on_team"] == "CHAIR":
                team["chair_reviewer_id"] = replacement["id"]
                touch(team)
    return success_object(serialize(assignment))


@bp.post("/accreditation/review-teams/<team_id>/confirm")
def confirm_team(team_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    team = fetch_or_404(STORE.review_teams, team_id, ERR_REVIEW_TEAM_NOT_FOUND)
    if team["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "Only a PROPOSED team can be confirmed")
    for a in STORE.team_assignments.values():
        if a["review_team_id"] != team_id or a["status"] != "ACTIVE":
            continue
        if a["response"] != "ACCEPTED" or a["conflict_status"] == "CONFLICTED":
            raise_err(ERR_TEAM_INCOMPLETE,
                      "Every ACTIVE assignment must be ACCEPTED and conflict-cleared")
    team["status"] = "CONFIRMED"
    touch(team)
    return success_object(_ser_team(team))


def _buffer_for(modality):
    return timedelta(days=C.ONSITE_BUFFER_DAYS) if modality == "ON_SITE" else timedelta(days=C.VIRTUAL_BUFFER_DAYS)


def _accepted_members(team_id):
    return [a for a in STORE.team_assignments.values()
            if a["review_team_id"] == team_id and a["status"] == "ACTIVE"
            and a["response"] == "ACCEPTED"]


@bp.post("/accreditation/review-teams/<team_id>/schedule-visit")
def schedule_visit(team_id):
    actor = authenticate()
    require_role(actor, ["PeerReviewer"])
    team = fetch_or_404(STORE.review_teams, team_id, ERR_REVIEW_TEAM_NOT_FOUND)
    body = get_body()
    start_raw = req_string(body, "visit_start_at")
    end_raw = req_string(body, "visit_end_at")
    start_dt = _parse_iso_datetime(start_raw)
    end_dt = _parse_iso_datetime(end_raw)
    if start_dt is None or end_dt is None:
        raise_err(ERR_VALIDATION, "visit_start_at and visit_end_at must be ISO 8601 datetimes")
    # State gates (priority 4) before reviewer binding (priority 24).
    if team["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Only a CONFIRMED team can schedule its visit")
    cycle = STORE.review_cycles.get(team["review_cycle_id"])
    if cycle is None or cycle["status"] != "EVALUATION_ACTIVE":
        raise_err(ERR_INVALID_STATE, "The cycle must be EVALUATION_ACTIVE")
    locked = any(a["review_cycle_id"] == cycle["id"] and a["status"] == "REVIEW_LOCKED"
                 for a in STORE.assurance_arguments.values())
    if not locked:
        raise_err(ERR_CYCLE_PREREQUISITE_NOT_MET, "The assurance argument must be REVIEW_LOCKED")
    # Window conflict (priority 19), half-open buffered intervals.
    buf = _buffer_for(team["visit_modality"])
    new_lo, new_hi = start_dt - buf, end_dt + buf
    member_ids = {a["reviewer_id"] for a in _accepted_members(team_id)}
    for other in STORE.review_teams.values():
        if other["id"] == team_id or other["_visit_start_dt"] is None:
            continue
        if other["status"] not in ("VISIT_SCHEDULED", "REPORT_FILED"):
            continue
        other_members = {a["reviewer_id"] for a in _accepted_members(other["id"])}
        if not (member_ids & other_members):
            continue
        obuf = _buffer_for(other["visit_modality"])
        o_lo, o_hi = other["_visit_start_dt"] - obuf, other["_visit_end_dt"] + obuf
        if new_lo < o_hi and o_lo < new_hi:
            raise_err(ERR_REVIEWER_WINDOW_CONFLICT,
                      "An accepted member holds an overlapping effective visit window")
    # Chair binding (priority 24).
    if actor.user_id != team["chair_reviewer_id"]:
        raise_err(ERR_REVIEWER_NOT_ASSIGNED, "Only the team's chair may schedule the visit")
    team["visit_start_at"] = start_raw
    team["visit_end_at"] = end_raw
    team["_visit_start_dt"] = start_dt
    team["_visit_end_dt"] = end_dt
    team["status"] = "VISIT_SCHEDULED"
    touch(team)
    return success_object(_ser_team(team))


@bp.post("/accreditation/review-teams/<team_id>/file-report")
def file_report(team_id):
    actor = authenticate()
    require_role(actor, ["PeerReviewer"])
    team = fetch_or_404(STORE.review_teams, team_id, ERR_REVIEW_TEAM_NOT_FOUND)
    body = get_body()
    ratings = req_list(body, "criterion_ratings")
    seen = set()
    for entry in ratings:
        if not isinstance(entry, dict):
            raise_err(ERR_VALIDATION, "Each criterion rating must be an object")
        code = req_enum(entry, "criterion_code", C.CRITERION_CODES)
        req_enum(entry, "rating", C.CRITERION_RATING_VALUES)
        if code in seen:
            raise_err(ERR_VALIDATION, "Each criterion must be rated exactly once")
        seen.add(code)
    if seen != set(C.CRITERION_CODES):
        raise_err(ERR_VALIDATION, "criterion_ratings must cover all five criteria")
    recommendation = req_enum(body, "report_recommendation", C.REPORT_RECOMMENDATIONS)
    summary = req_string(body, "report_summary")
    if team["status"] != "VISIT_SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a VISIT_SCHEDULED team can file its report")
    if team["_visit_end_dt"] is None or STORE.now() < team["_visit_end_dt"]:
        raise_err(ERR_INVALID_STATE, "The report may be filed only once the visit has ended")
    if actor.user_id != team["chair_reviewer_id"]:
        raise_err(ERR_REVIEWER_NOT_ASSIGNED, "Only the team's chair may file the report")
    cycle = STORE.review_cycles.get(team["review_cycle_id"])
    inst = STORE.institutions.get(cycle["institution_id"]) if cycle else None
    team["criterion_ratings"] = [{"criterion_code": e["criterion_code"], "rating": e["rating"]}
                                 for e in ratings]
    team["report_recommendation"] = recommendation
    team["report_summary"] = summary
    team["recommended_action_computed"] = recommended_action(
        team["criterion_ratings"], inst["sanction_status"],
        cycle["federal_compliance_status"], inst["latest_cfi_band"], cycle["cycle_type"])
    team["report_filed_at"] = STORE.now_iso()
    team["status"] = "REPORT_FILED"
    touch(team)
    return success_object(_ser_team(team))


@bp.post("/accreditation/review-teams/<team_id>/cancel-visit")
def cancel_visit(team_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    team = fetch_or_404(STORE.review_teams, team_id, ERR_REVIEW_TEAM_NOT_FOUND)
    if team["status"] != "VISIT_SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a VISIT_SCHEDULED team can cancel its visit")
    team["status"] = "CONFIRMED"
    team["visit_start_at"] = None
    team["visit_end_at"] = None
    team["_visit_start_dt"] = None
    team["_visit_end_dt"] = None
    touch(team)
    return success_object(_ser_team(team))
