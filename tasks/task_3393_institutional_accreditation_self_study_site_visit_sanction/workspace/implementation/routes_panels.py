"""Decision panels: convene, list, cast votes, close + cascade (PRD §3.7)."""
from flask import Blueprint

import constants as C
from auth import (authenticate, check_liaison_chain, require_role)
from calculations import panel_tally
from db import STORE
from errors import (ERR_ACTION_TYPE_MISMATCH, ERR_DECISION_PANEL_NOT_FOUND,
                    ERR_DUPLICATE_VOTE, ERR_FEDERAL_COMPLIANCE_DEFICIENT,
                    ERR_INVALID_STATE, ERR_PANEL_QUORUM_NOT_MET,
                    ERR_REVIEW_CYCLE_NOT_FOUND,
                    ERR_REVIEWER_CONFLICT_OF_INTEREST,
                    ERR_SEGREGATION_OF_DUTIES, ERR_UNAUTHORIZED_ROLE,
                    ERR_VALIDATION, raise_err)
from helpers import (fetch_or_404, get_body, new_entity, paginate, req_enum,
                     req_list, serialize, touch)
from response import success_list, success_object

bp = Blueprint("panels", __name__)


def _holds_assignment_on_cycle(reviewer_id, cycle_id):
    """Any TeamAssignment record on any team of the cycle (§2.10: 'any')."""
    for a in STORE.team_assignments.values():
        if a["reviewer_id"] != reviewer_id:
            continue
        team = STORE.review_teams.get(a["review_team_id"])
        if team is not None and team["review_cycle_id"] == cycle_id:
            return True
    return False


def _conflicted_with(reviewer, institution_id):
    return (reviewer["affiliation_institution_id"] is not None
            and reviewer["affiliation_institution_id"] == institution_id) \
        or institution_id in (reviewer["declared_conflict_institution_ids"] or [])


@bp.post("/accreditation/review-cycles/<cycle_id>/decision-panels")
def convene_panel(cycle_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    body = get_body()
    member_ids = req_list(body, "member_reviewer_ids")
    if len(member_ids) != C.PANEL_SIZE:
        raise_err(ERR_VALIDATION, "member_reviewer_ids must name exactly 7 reviewers")
    for mid in member_ids:
        if not isinstance(mid, str):
            raise_err(ERR_VALIDATION, "member_reviewer_ids must contain reviewer id strings")
    if len(set(member_ids)) != len(member_ids):
        raise_err(ERR_VALIDATION, "member_reviewer_ids must be distinct")
    members = []
    for mid in member_ids:
        reviewer = STORE.reviewers.get(mid)
        if reviewer is None:
            raise_err(ERR_VALIDATION, "No Reviewer with id %s" % mid)
        members.append(reviewer)
    for reviewer in members:
        if _holds_assignment_on_cycle(reviewer["id"], cycle_id):
            raise_err(ERR_SEGREGATION_OF_DUTIES,
                      "A panel member may not hold a TeamAssignment on the same cycle")
    for reviewer in members:
        if _conflicted_with(reviewer, cycle["institution_id"]):
            raise_err(ERR_REVIEWER_CONFLICT_OF_INTEREST,
                      "A panel member is conflicted against the institution under review")
    panel = new_entity({
        "review_cycle_id": cycle_id,
        "member_reviewer_ids": list(member_ids),
        "status": "CONVENED",
        "votes": [],
        "prevailing_action": None,
        "closed_at": None,
    })
    STORE.decision_panels[panel["id"]] = panel
    return success_object(serialize(panel), code=201)


@bp.get("/accreditation/review-cycles/<cycle_id>/decision-panels")
def list_panels(cycle_id):
    actor = authenticate()
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, cycle["institution_id"])
    items = [p for p in STORE.decision_panels.values() if p["review_cycle_id"] == cycle_id]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.post("/accreditation/decision-panels/<panel_id>/cast-vote")
def cast_vote(panel_id):
    actor = authenticate()
    require_role(actor, ["PeerReviewer"])
    panel = fetch_or_404(STORE.decision_panels, panel_id, ERR_DECISION_PANEL_NOT_FOUND)
    body = get_body()
    choice = req_enum(body, "choice", C.VOTE_CHOICES)
    # Panel membership is this endpoint's reviewer binding (§2.1) -> 403.
    if actor.user_id not in panel["member_reviewer_ids"]:
        raise_err(ERR_UNAUTHORIZED_ROLE, "Only a seated panel member may cast a vote")
    if panel["status"] != "CONVENED":
        raise_err(ERR_INVALID_STATE, "Votes may be cast only on a CONVENED panel")
    cycle = STORE.review_cycles.get(panel["review_cycle_id"])
    if _holds_assignment_on_cycle(actor.user_id, panel["review_cycle_id"]):
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "A panel member may not hold a TeamAssignment on the same cycle")
    reviewer = STORE.reviewers.get(actor.user_id)
    if reviewer is not None and cycle is not None \
            and _conflicted_with(reviewer, cycle["institution_id"]):
        raise_err(ERR_REVIEWER_CONFLICT_OF_INTEREST,
                  "The voter is conflicted against the institution under review")
    if any(v["reviewer_id"] == actor.user_id for v in panel["votes"]):
        raise_err(ERR_DUPLICATE_VOTE, "This reviewer has already voted on this panel")
    panel["votes"].append({
        "reviewer_id": actor.user_id,
        "choice": choice,
        "cast_at": STORE.now_iso(),
    })
    touch(panel)
    return success_object(serialize(panel), code=201)


@bp.post("/accreditation/decision-panels/<panel_id>/close")
def close_panel(panel_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    panel = fetch_or_404(STORE.decision_panels, panel_id, ERR_DECISION_PANEL_NOT_FOUND)
    if panel["status"] != "CONVENED":
        raise_err(ERR_INVALID_STATE, "Only a CONVENED panel can be closed")
    cycle = STORE.review_cycles.get(panel["review_cycle_id"])
    if cycle is None or cycle["status"] != "PANEL_REVIEW":
        raise_err(ERR_INVALID_STATE, "The cycle must be in PANEL_REVIEW to close its panel")
    # Pinned gate order (§3.7): federal compliance, then quorum, then type.
    if cycle["federal_compliance_status"] == "DEFICIENT":
        raise_err(ERR_FEDERAL_COMPLIANCE_DEFICIENT,
                  "A DEFICIENT federal-compliance finding blocks panel close")
    if len(panel["votes"]) < C.PANEL_QUORUM:
        raise_err(ERR_PANEL_QUORUM_NOT_MET, "At least 5 votes are required to close the panel")
    prevailing = panel_tally(panel["votes"])
    if cycle["cycle_type"] == "INITIAL_ACCREDITATION":
        if prevailing in ("REAFFIRM", "WITHDRAW"):
            raise_err(ERR_ACTION_TYPE_MISMATCH,
                      "REAFFIRM/WITHDRAW may not prevail on an INITIAL_ACCREDITATION cycle")
    else:
        if prevailing in ("GRANT", "DENY"):
            raise_err(ERR_ACTION_TYPE_MISMATCH,
                      "GRANT/DENY may not prevail on a REAFFIRMATION cycle")
    action_type = C.CHOICE_TO_ACTION_TYPE[prevailing]
    panel["prevailing_action"] = prevailing
    panel["status"] = "CLOSED"
    panel["closed_at"] = STORE.now_iso()
    touch(panel)
    # Cascade link 1: draft the ActionOutcome.
    outcome = new_entity({
        "review_cycle_id": cycle["id"],
        "indicator_origin_institution_id": None,
        "origin": "PANEL",
        "action_type": action_type,
        "status": "DRAFTED",
        "public_disclosure_text": None,
        "disclosed_at": None,
        "effective_at": None,
        "sanction_level": None,
        "cure_status": "NONE",
        "cure_review_opened_at": None,
        "_cure_opened_dt": None,
        "cure_threshold_snapshot": None,
        "cure_deadline_at": None,
    })
    STORE.action_outcomes[outcome["id"]] = outcome
    # Cascade link 2: cycle PANEL_REVIEW -> DECIDED.
    cycle["status"] = "DECIDED"
    cycle["decided_at"] = STORE.now_iso()
    touch(cycle)
    # Cascade link 3: disband the REPORT_FILED team, close assignments, drop loads.
    for team in STORE.review_teams.values():
        if team["review_cycle_id"] != cycle["id"] or team["status"] != "REPORT_FILED":
            continue
        team["status"] = "DISBANDED"
        touch(team)
        for a in STORE.team_assignments.values():
            if a["review_team_id"] == team["id"] and a["status"] == "ACTIVE":
                a["status"] = "CLOSED"
                touch(a)
                reviewer = STORE.reviewers.get(a["reviewer_id"])
                if reviewer is not None:
                    touch(reviewer)
    # Cascade link 4: accept the locked argument unless the action is a denial.
    if action_type != "DENIAL":
        for argument in STORE.assurance_arguments.values():
            if argument["review_cycle_id"] == cycle["id"] and argument["status"] == "REVIEW_LOCKED":
                argument["status"] = "ACCEPTED"
                touch(argument)
    return success_object(serialize(panel))
