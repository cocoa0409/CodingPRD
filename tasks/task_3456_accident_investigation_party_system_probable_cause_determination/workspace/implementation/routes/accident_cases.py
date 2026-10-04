"""Accident cases and their embedded launch decisions (PRD 3.1-3.2).

POST /accident-cases                                             DutyOfficer
GET  /accident-cases                                             all roles
GET  /accident-cases/{id}                                        all roles
POST /accident-cases/{id}/launch-decisions                       ManagingDirector
POST /accident-cases/{id}/launch-decisions/{decision_id}/adopt   ManagingDirector
POST /accident-cases/{id}/launch-decisions/{decision_id}/reconsider
                                                                 ManagingDirector
"""

from flask import Blueprint, request

import clock
import db
import domain
from auth import get_context, require_roles
from constants import (
    CASE_CATEGORIES,
    FULL_LAUNCH_THRESHOLD,
    LAUNCH_MODES,
    LIMITED_LAUNCH_THRESHOLD,
    ROLES,
)
from envelope import ok_list, ok_object, paginate, parse_pagination
from errors import api_error
from scoring import compute_launch_scores
from serializers import case_public
from validate import (
    get_body,
    opt_bool,
    opt_int,
    opt_str,
    req_bool,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("accident_cases", __name__)


def _recompute_case_scores(case):
    statutory, risk_adjusted, suggested = compute_launch_scores(
        case["fatalities_count"],
        case["injuries_count"],
        case["damage_estimate_cents"],
        case["is_public_transport"],
        case["category"],
    )
    case["statutory_score"] = statutory
    case["risk_adjusted_score"] = risk_adjusted
    case["suggested_mode"] = suggested


def _read_severity_overrides(body):
    """Optional severity overrides carried by propose/reconsider payloads."""
    overrides = {}
    fatalities = opt_int(body, "fatalities_count", minimum=0)
    if fatalities is not None:
        overrides["fatalities_count"] = fatalities
    injuries = opt_int(body, "injuries_count", minimum=0)
    if injuries is not None:
        overrides["injuries_count"] = injuries
    damage = opt_int(body, "damage_estimate_cents", minimum=0)
    if damage is not None:
        overrides["damage_estimate_cents"] = damage
    is_public = opt_bool(body, "is_public_transport")
    if is_public is not None:
        overrides["is_public_transport"] = is_public
    return overrides


@bp.route("/accident-cases", methods=["POST"])
def create_case():
    _user_id, role = get_context()
    require_roles(role, ("DutyOfficer",))
    body = get_body()
    report_number = req_str(body, "report_number")
    category = req_enum(body, "category", CASE_CATEGORIES)
    occurred_at = req_str(body, "occurred_at")
    if clock.parse_iso(occurred_at) is None:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "field 'occurred_at' must be an ISO 8601 UTC timestamp",
        )
    location_state = req_str(body, "location_state")
    fatalities_count = req_int(body, "fatalities_count", minimum=0)
    injuries_count = req_int(body, "injuries_count", minimum=0)
    damage_estimate_cents = req_int(body, "damage_estimate_cents", minimum=0)
    is_public_transport = req_bool(body, "is_public_transport")

    for existing in db.store["accident_cases"].values():
        if existing["report_number"] == report_number:
            raise api_error(
                "ERR_DUPLICATE_REPORT_NUMBER",
                "an accident case with report_number %s already exists"
                % report_number,
            )

    statutory, risk_adjusted, suggested = compute_launch_scores(
        fatalities_count,
        injuries_count,
        damage_estimate_cents,
        is_public_transport,
        category,
    )
    case = db.add(
        "accident_cases",
        {
            "report_number": report_number,
            "category": category,
            "occurred_at": occurred_at,
            "location_state": location_state,
            "fatalities_count": fatalities_count,
            "injuries_count": injuries_count,
            "damage_estimate_cents": damage_estimate_cents,
            "is_public_transport": is_public_transport,
            "statutory_score": statutory,
            "risk_adjusted_score": risk_adjusted,
            "suggested_mode": suggested,
            "status": "SCREENING",
            "launch_decisions": [],
        },
    )
    return ok_object(case_public(case), status=201)


@bp.route("/accident-cases", methods=["GET"])
def list_cases():
    _user_id, role = get_context()
    require_roles(role, ROLES)
    limit, offset = parse_pagination(request.args)
    items = db.all_of("accident_cases")
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    category = request.args.get("category")
    if category is not None:
        items = [c for c in items if c["category"] == category]
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([case_public(c) for c in page], limit, offset, total)


@bp.route("/accident-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    _user_id, role = get_context()
    require_roles(role, ROLES)
    case = domain.get_case(case_id)
    return ok_object(case_public(case), status=200)


@bp.route("/accident-cases/<case_id>/launch-decisions", methods=["POST"])
def propose_decision(case_id):
    user_id, role = get_context()
    require_roles(role, ("ManagingDirector",))
    case = domain.get_case(case_id)
    body = get_body()
    mode = req_enum(body, "mode", LAUNCH_MODES)
    expected_version = req_int(body, "expected_accident_case_version")
    rationale = opt_str(body, "rationale")
    overrides = _read_severity_overrides(body)

    if case["status"] != "SCREENING":
        raise api_error(
            "ERR_CASE_NOT_SCREENING",
            "launch decisions may only be proposed while the case is SCREENING",
        )
    if expected_version != case["version"]:
        raise api_error(
            "ERR_STALE_VERSION",
            "expected_accident_case_version does not match the accident case's "
            "current version",
        )

    if overrides:
        case.update(overrides)
        _recompute_case_scores(case)

    for existing in case["launch_decisions"]:
        if existing["status"] == "PROPOSED":
            existing["status"] = "SUPERSEDED"

    decision = {
        "decision_id": db.new_id(),
        "mode": mode,
        "status": "PROPOSED",
        "proposed_by_user_id": user_id,
        "proposed_at": clock.get_clock(),
        "adopted_at": None,
        "snapshot_statutory_score": case["statutory_score"],
        "snapshot_risk_adjusted_score": case["risk_adjusted_score"],
        "rationale": rationale,
    }
    case["launch_decisions"].append(decision)
    db.touch(case)
    return ok_object(case_public(case), status=201)


@bp.route(
    "/accident-cases/<case_id>/launch-decisions/<decision_id>/adopt",
    methods=["POST"],
)
def adopt_decision(case_id, decision_id):
    user_id, role = get_context()
    require_roles(role, ("ManagingDirector",))
    case = domain.get_case(case_id)
    decision = domain.find_decision(case, decision_id)

    if case["status"] != "SCREENING":
        raise api_error(
            "ERR_CASE_NOT_SCREENING",
            "only a decision on a SCREENING case may be adopted",
        )
    if decision["status"] != "PROPOSED":
        raise api_error(
            "ERR_DECISION_STATE_INVALID",
            "only a PROPOSED launch decision may be adopted",
        )
    if (
        decision["mode"] == "FULL_GO_TEAM"
        and case["statutory_score"] < FULL_LAUNCH_THRESHOLD
    ):
        raise api_error(
            "ERR_LAUNCH_THRESHOLD_NOT_MET",
            "adopting FULL_GO_TEAM requires statutory_score >= %d"
            % FULL_LAUNCH_THRESHOLD,
        )
    if (
        decision["mode"] == "LIMITED"
        and case["statutory_score"] < LIMITED_LAUNCH_THRESHOLD
    ):
        raise api_error(
            "ERR_LAUNCH_THRESHOLD_NOT_MET",
            "adopting LIMITED requires statutory_score >= %d"
            % LIMITED_LAUNCH_THRESHOLD,
        )
    if decision["proposed_by_user_id"] == user_id:
        raise api_error(
            "ERR_SOD_PROPOSER_CANNOT_ADOPT",
            "the ManagingDirector who proposed a launch decision may not "
            "adopt it",
        )

    body = get_body()
    iic_user_id = body.get("iic_user_id")
    if decision["mode"] == "FULL_GO_TEAM":
        if not isinstance(iic_user_id, str) or iic_user_id == "":
            raise api_error(
                "ERR_INVALID_REQUEST",
                "iic_user_id is required when adopting a FULL_GO_TEAM decision",
            )
    elif iic_user_id is not None:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "iic_user_id must be absent unless adopting a FULL_GO_TEAM decision",
        )

    decision["status"] = "ADOPTED"
    decision["adopted_at"] = clock.get_clock()
    if decision["mode"] == "FULL_GO_TEAM":
        case["status"] = "LAUNCHED"
        db.add(
            "investigations",
            {
                "accident_case_id": case["id"],
                "iic_user_id": iic_user_id,
                "phase": "GO_TEAM_ASSEMBLED",
                "docket_status": "SEALED",
                "docket_completeness_pct": 0,
            },
        )
    elif decision["mode"] == "LIMITED":
        case["status"] = "LIMITED_TRACK"
    else:
        case["status"] = "DECLINED"
    db.touch(case)
    return ok_object(case_public(case), status=200)


@bp.route(
    "/accident-cases/<case_id>/launch-decisions/<decision_id>/reconsider",
    methods=["POST"],
)
def reconsider_decision(case_id, decision_id):
    _user_id, role = get_context()
    require_roles(role, ("ManagingDirector",))
    case = domain.get_case(case_id)
    decision = domain.find_decision(case, decision_id)

    if case["status"] in ("LAUNCHED", "CLOSED_ADOPTED"):
        raise api_error(
            "ERR_CASE_ALREADY_LAUNCHED",
            "reconsideration is blocked once the case is LAUNCHED or "
            "CLOSED_ADOPTED",
        )
    if decision["status"] != "ADOPTED":
        raise api_error(
            "ERR_DECISION_STATE_INVALID",
            "only an ADOPTED launch decision may be reconsidered",
        )

    body = get_body()
    rationale = opt_str(body, "rationale")
    overrides = _read_severity_overrides(body)
    if overrides:
        case.update(overrides)
    _recompute_case_scores(case)

    decision["status"] = "PROPOSED"
    decision["adopted_at"] = None
    if rationale is not None:
        decision["rationale"] = rationale
    decision["snapshot_statutory_score"] = case["statutory_score"]
    decision["snapshot_risk_adjusted_score"] = case["risk_adjusted_score"]
    case["status"] = "SCREENING"
    db.touch(case)
    return ok_object(case_public(case), status=200)
