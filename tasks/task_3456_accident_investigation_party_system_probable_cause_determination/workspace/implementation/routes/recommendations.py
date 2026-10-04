"""Safety recommendations with response tracking (PRD 3.7).

POST /safety-recommendations                     IIC
GET  /safety-recommendations                     all roles
GET  /safety-recommendations/{id}                all roles
POST /safety-recommendations/{id}/responses      AddresseeContact
POST /safety-recommendations/{id}/classify       ManagingDirector
POST /safety-recommendations/{id}/close          ManagingDirector
"""

from flask import Blueprint, request

import clock
import db
import domain
from auth import get_context, require_iic, require_roles
from constants import (
    CLASSIFICATIONS,
    CLOSE_OUTCOMES,
    RECOMMENDATION_RESPONSIBLE_STATUSES,
    ROLES,
    UNACCEPTABLE_STREAK_CLOSE_MIN,
)
from envelope import ok_list, ok_object, paginate, parse_pagination
from errors import api_error
from serializers import recommendation_public
from validate import get_body, req_enum, req_str

bp = Blueprint("recommendations", __name__)


@bp.route("/safety-recommendations", methods=["POST"])
def create_recommendation():
    user_id, role = get_context()
    require_roles(role, ("IIC",))
    body = get_body()
    investigation_id = req_str(body, "investigation_id")
    addressee_org_id = req_str(body, "addressee_org_id")
    recommendation_text = req_str(body, "recommendation_text")
    investigation = domain.get_investigation(investigation_id)
    require_iic(user_id, investigation)
    organization = domain.get_organization(addressee_org_id)

    if investigation["phase"] not in ("ANALYSIS", "BOARD_REVIEW"):
        raise api_error(
            "ERR_INVESTIGATION_PHASE_INVALID",
            "safety recommendations may only be issued during ANALYSIS or "
            "BOARD_REVIEW",
        )

    recommendation = db.add(
        "safety_recommendations",
        {
            "investigation_id": investigation["id"],
            "addressee_org_id": organization["id"],
            "recommendation_text": recommendation_text,
            "status": "OPEN_AWAITING_RESPONSE",
            "issued_at": clock.get_clock(),
            "response_log": [],
            "unacceptable_streak": 0,
        },
    )
    return ok_object(recommendation_public(recommendation), status=201)


@bp.route("/safety-recommendations", methods=["GET"])
def list_recommendations():
    _user_id, role = get_context()
    require_roles(role, ROLES)
    limit, offset = parse_pagination(request.args)
    items = db.all_of("safety_recommendations")
    investigation_id = request.args.get("investigation_id")
    if investigation_id is not None:
        items = [
            r for r in items if r["investigation_id"] == investigation_id
        ]
    addressee_org_id = request.args.get("addressee_org_id")
    if addressee_org_id is not None:
        items = [
            r for r in items if r["addressee_org_id"] == addressee_org_id
        ]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list(
        [recommendation_public(r) for r in page], limit, offset, total
    )


@bp.route("/safety-recommendations/<recommendation_id>", methods=["GET"])
def get_recommendation(recommendation_id):
    _user_id, role = get_context()
    require_roles(role, ROLES)
    recommendation = domain.get_recommendation(recommendation_id)
    return ok_object(recommendation_public(recommendation), status=200)


@bp.route("/safety-recommendations/<recommendation_id>/responses",
          methods=["POST"])
def submit_response(recommendation_id):
    user_id, role = get_context()
    require_roles(role, ("AddresseeContact",))
    recommendation = domain.get_recommendation(recommendation_id)
    if user_id != recommendation["addressee_org_id"]:
        raise api_error(
            "ERR_NOT_ADDRESSEE",
            "only the addressed organization may respond to this "
            "recommendation",
        )
    body = get_body()
    response_text = req_str(body, "response_text")

    if recommendation["status"] not in RECOMMENDATION_RESPONSIBLE_STATUSES:
        raise api_error(
            "ERR_RECOMMENDATION_STATE_INVALID",
            "responses are accepted only while OPEN_AWAITING_RESPONSE, "
            "OPEN_ACCEPTABLE, or OPEN_UNACCEPTABLE",
        )

    recommendation["response_log"].append(
        {
            "response_id": db.new_id(),
            "response_text": response_text,
            "responded_at": clock.get_clock(),
            "classification_pending": True,
            "classification": None,
            "classified_at": None,
        }
    )
    recommendation["status"] = "OPEN_UNCLASSIFIED"
    db.touch(recommendation)
    return ok_object(recommendation_public(recommendation), status=201)


@bp.route("/safety-recommendations/<recommendation_id>/classify",
          methods=["POST"])
def classify_response(recommendation_id):
    _user_id, role = get_context()
    require_roles(role, ("ManagingDirector",))
    recommendation = domain.get_recommendation(recommendation_id)
    body = get_body()
    classification = req_enum(body, "classification", CLASSIFICATIONS)

    if recommendation["status"] != "OPEN_UNCLASSIFIED":
        raise api_error(
            "ERR_RECOMMENDATION_STATE_INVALID",
            "classification requires status OPEN_UNCLASSIFIED",
        )

    pending = None
    for entry in recommendation["response_log"]:
        if entry["classification_pending"]:
            pending = entry
            break
    if pending is None:
        raise api_error(
            "ERR_RECOMMENDATION_STATE_INVALID",
            "no response is awaiting classification",
        )

    pending["classification"] = classification
    pending["classification_pending"] = False
    pending["classified_at"] = clock.get_clock()

    if classification == "ACCEPTABLE":
        recommendation["status"] = "OPEN_ACCEPTABLE"
        recommendation["unacceptable_streak"] = 0
    else:
        recommendation["status"] = "OPEN_UNACCEPTABLE"
        streak = 0
        for entry in reversed(recommendation["response_log"]):
            if entry["classification"] == "UNACCEPTABLE":
                streak += 1
            elif entry["classification"] is not None:
                break
        recommendation["unacceptable_streak"] = streak

    db.touch(recommendation)
    return ok_object(recommendation_public(recommendation), status=200)


@bp.route("/safety-recommendations/<recommendation_id>/close",
          methods=["POST"])
def close_recommendation(recommendation_id):
    _user_id, role = get_context()
    require_roles(role, ("ManagingDirector",))
    recommendation = domain.get_recommendation(recommendation_id)
    body = get_body()
    outcome = req_enum(body, "outcome", CLOSE_OUTCOMES)

    status = recommendation["status"]
    if outcome in ("CLOSED_ACCEPTABLE", "CLOSED_EXCEEDS"):
        if status != "OPEN_ACCEPTABLE":
            raise api_error(
                "ERR_RECOMMENDATION_STATE_INVALID",
                "%s requires status OPEN_ACCEPTABLE" % outcome,
            )
    elif outcome == "CLOSED_UNACCEPTABLE":
        if status != "OPEN_UNACCEPTABLE":
            raise api_error(
                "ERR_RECOMMENDATION_STATE_INVALID",
                "CLOSED_UNACCEPTABLE requires status OPEN_UNACCEPTABLE",
            )
        if recommendation["unacceptable_streak"] < UNACCEPTABLE_STREAK_CLOSE_MIN:
            raise api_error(
                "ERR_UNACCEPTABLE_STREAK_INSUFFICIENT",
                "CLOSED_UNACCEPTABLE requires an unacceptable_streak of at "
                "least %d" % UNACCEPTABLE_STREAK_CLOSE_MIN,
            )

    recommendation["status"] = outcome
    db.touch(recommendation)
    return ok_object(recommendation_public(recommendation), status=200)
