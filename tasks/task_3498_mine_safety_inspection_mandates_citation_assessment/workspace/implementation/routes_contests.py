"""Contest filing and commission adjudication endpoints (PRD section 3.6)."""
from datetime import timedelta

from flask import Blueprint, g, request

import clock
import services_penalty
import store
from constants import (
    BUSINESS_READ_ROLES,
    CONTEST_OUTCOMES,
    CONTEST_WINDOW_DAYS,
    ROLE_COMMISSION_JUDGE,
    ROLE_OPERATOR_REP,
)
from envelope import list_response, ok_object
from errors import (
    ApiError,
    ERR_CITATION_NOT_CONTESTABLE,
    ERR_CONTEST_DECISION_INVALID,
    ERR_CONTEST_WINDOW_LAPSED,
    ERR_INVALID_STATE,
    ERR_OPERATOR_MISMATCH,
    ERR_STALE_VERSION,
)
from serialize import contest as ser_contest
from validate import ensure_empty_body, get_or_404, parse_body, require_roles

bp = Blueprint("contests", __name__, url_prefix="/msha")


@bp.route("/contests", methods=["POST"])
def create_contest():
    require_roles(ROLE_OPERATOR_REP)
    body = parse_body({
        "citation_id": ("str", True),
        "expected_citation_version": ("int", True),
        "grounds": ("str", True),
    })
    citation = get_or_404(store.citations, body["citation_id"], "citation")
    # Tier 5 OCC precedes ownership (6), contestability (7), and window (11).
    if body["expected_citation_version"] != citation["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_citation_version does not match the citation's current version",
        )
    mine = store.mines.get(citation["mine_id"])
    if mine is None or g.uid != mine["operator_id"]:
        raise ApiError(
            ERR_OPERATOR_MISMATCH,
            "X-User-ID must be the operator of the cited mine",
        )
    if citation["contest_status"] != "UNCONTESTED":
        raise ApiError(
            ERR_CITATION_NOT_CONTESTABLE,
            "the citation's contest axis must be UNCONTESTED",
        )
    if clock.now() > citation["issued_at"] + timedelta(days=CONTEST_WINDOW_DAYS):
        raise ApiError(
            ERR_CONTEST_WINDOW_LAPSED,
            "contests must be filed within 30 days of issuance (inclusive)",
        )
    contest = store.new_entity(store.contests, {
        "citation_id": citation["id"],
        "filed_by_operator_id": g.uid,
        "grounds": body["grounds"],
        "filed_at": clock.now(),
        "status": "FILED",
        "outcome": None,
        "modified_penalty_cents": None,
        "decided_at": None,
    })
    citation["contest_status"] = "CONTESTED"
    store.touch(citation)
    assessment = services_penalty.assessment_for(citation["id"])
    if assessment is not None and assessment["status"] == "PROPOSED":
        assessment["status"] = "CONTESTED"
        store.touch(assessment)
    return ok_object(ser_contest(contest), 201)


@bp.route("/contests/<contestId>", methods=["GET"])
def get_contest(contestId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_contest(get_or_404(store.contests, contestId, "contest")))


@bp.route("/contests", methods=["GET"])
def list_contests():
    require_roles(*BUSINESS_READ_ROLES)
    items = list(store.contests.values())
    for param in ("citation_id", "filed_by_operator_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c.get(param) is not None and c[param] == value]
    return list_response(items, ser_contest)


@bp.route("/contests/<contestId>/docket", methods=["POST"])
def docket_contest(contestId):
    require_roles(ROLE_COMMISSION_JUDGE)
    ensure_empty_body()
    contest = get_or_404(store.contests, contestId, "contest")
    if contest["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, "docketing requires FILED status")
    contest["status"] = "DOCKETED"
    store.touch(contest)
    return ok_object(ser_contest(contest))


@bp.route("/contests/<contestId>/decide", methods=["POST"])
def decide_contest(contestId):
    require_roles(ROLE_COMMISSION_JUDGE)
    body = parse_body({
        "outcome": ("enum", True, CONTEST_OUTCOMES),
        "modified_penalty_cents": ("int", False),
    })
    contest = get_or_404(store.contests, contestId, "contest")
    if contest["status"] != "DOCKETED":
        raise ApiError(ERR_INVALID_STATE, "deciding requires DOCKETED status")
    outcome = body["outcome"]
    modified = body["modified_penalty_cents"]
    # Tier 12 fiscal decision payload.
    if outcome == "MODIFIED":
        if modified is None or modified < 0:
            raise ApiError(
                ERR_CONTEST_DECISION_INVALID,
                "modified_penalty_cents is required and must be >= 0 for MODIFIED",
            )
    elif modified is not None:
        raise ApiError(
            ERR_CONTEST_DECISION_INVALID,
            "modified_penalty_cents must not be supplied for a non-MODIFIED outcome",
        )
    contest["status"] = "DECIDED"
    contest["outcome"] = outcome
    contest["decided_at"] = clock.now()
    if outcome == "MODIFIED":
        contest["modified_penalty_cents"] = modified
    store.touch(contest)
    citation = store.citations.get(contest["citation_id"])
    citation["contest_status"] = outcome
    store.touch(citation)
    assessment = services_penalty.assessment_for(citation["id"])
    if outcome == "AFFIRMED":
        services_penalty.apply_final_variant(assessment, citation)
    elif outcome == "MODIFIED":
        services_penalty.apply_modified_outcome(assessment, citation, modified)
    else:
        services_penalty.apply_vacated_outcome(assessment)
    store.touch(assessment)
    return ok_object(ser_contest(contest))


@bp.route("/contests/<contestId>/withdraw", methods=["POST"])
def withdraw_contest(contestId):
    require_roles(ROLE_OPERATOR_REP)
    ensure_empty_body()
    contest = get_or_404(store.contests, contestId, "contest")
    if g.uid != contest["filed_by_operator_id"]:
        raise ApiError(ERR_OPERATOR_MISMATCH, "only the filing operator may withdraw this contest")
    if contest["status"] not in ("FILED", "DOCKETED"):
        raise ApiError(ERR_INVALID_STATE, "withdrawal requires FILED or DOCKETED status")
    contest["status"] = "WITHDRAWN"
    store.touch(contest)
    citation = store.citations.get(contest["citation_id"])
    if citation is not None and citation["contest_status"] == "CONTESTED":
        citation["contest_status"] = "UNCONTESTED"
        store.touch(citation)
    assessment = services_penalty.assessment_for(contest["citation_id"])
    if assessment is not None and assessment["status"] == "CONTESTED":
        assessment["status"] = "PROPOSED"
        store.touch(assessment)
    return ok_object(ser_contest(contest))
