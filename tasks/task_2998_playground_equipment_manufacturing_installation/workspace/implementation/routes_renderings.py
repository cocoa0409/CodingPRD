"""Design renderings, community vote batches and review closure (PRD section 3.4)."""

from flask import Blueprint

import calc
import cascades
import validate as v
from auth import READ_ROLES, authenticate
from envelope import list_response, object_response
from errors import ApiError
from store import public, public_list, store

bp = Blueprint("renderings", __name__)

VOTE_PROJECT_STATUSES = ("RENDERED", "COMMUNITY_REVIEW")


@bp.route("/playground/renderings", methods=["GET"])
def list_renderings():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("rendering"), {
        "project_id": "project_id",
        "pinned_standard_id": "pinned_standard_id",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/renderings/<rendering_id>", methods=["GET"])
def get_rendering(rendering_id):
    authenticate(READ_ROLES)
    return object_response(public(store.require("rendering", rendering_id)))


@bp.route("/playground/renderings/<rendering_id>/community-votes", methods=["POST"])
def record_community_votes(rendering_id):
    authenticate(["ClientRepresentative"])
    rendering = store.require("rendering", rendering_id)
    body = v.raw_body()
    yes_votes = v.integer(body, "yes_votes", minimum=0)
    no_votes = v.integer(body, "no_votes", minimum=0)

    if rendering["status"] != "ISSUED":
        raise ApiError("ERR_RENDERING_NOT_ISSUED")
    project = store.require("project", rendering["project_id"])
    if project["design_status"] not in VOTE_PROJECT_STATUSES:
        raise ApiError("ERR_PROJECT_INVALID_STATE")

    rendering["yes_votes"] = rendering["yes_votes"] + yes_votes
    rendering["no_votes"] = rendering["no_votes"] + no_votes
    rendering["community_approval_pct"] = calc.community_approval_pct(
        rendering["yes_votes"], rendering["no_votes"]
    )
    store.touch(rendering)

    project["design_status"] = "COMMUNITY_REVIEW"
    store.touch(project)
    return object_response(public(rendering))


@bp.route("/playground/renderings/<rendering_id>/close-review", methods=["POST"])
def close_review(rendering_id):
    authenticate(["DesignConsultant"])
    rendering = store.require("rendering", rendering_id)

    if rendering["status"] != "ISSUED":
        raise ApiError("ERR_RENDERING_NOT_ISSUED")
    project = store.require("project", rendering["project_id"])
    if project["design_status"] != "COMMUNITY_REVIEW":
        raise ApiError("ERR_PROJECT_INVALID_STATE")

    turnout = rendering["yes_votes"] + rendering["no_votes"]
    if turnout < calc.MIN_REVIEW_VOTES:
        raise ApiError("ERR_INSUFFICIENT_COMMUNITY_INPUT")

    approved = rendering["community_approval_pct"] >= float(calc.APPROVAL_THRESHOLD_PCT)
    if approved:
        # The rendering stays ISSUED so that it can go on to back a quote.
        project["design_status"] = "DESIGN_APPROVED"
        store.touch(project)
    else:
        rendering["status"] = "WITHDRAWN"
        store.touch(rendering)
        project["design_status"] = "REVISION_REQUESTED"
        project["revision_rounds"] = project["revision_rounds"] + 1
        store.touch(project)
        cascades.expire_issued_quotes(project["id"])

    return object_response(public(project))
