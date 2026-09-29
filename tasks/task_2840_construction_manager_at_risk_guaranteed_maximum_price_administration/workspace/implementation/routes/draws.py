"""ContingencyDraw endpoints (PRD 3.7).  Draws are only ever cascade-minted."""
from flask import Blueprint, g

import clock
import guards
import lookups
import response as resp
import serializers
import validation as v
from db import db, sorted_rows, touch
from errors import ApiError
from money import q2
from middleware import (
    CONSTRUCTION_MANAGER,
    INDEPENDENT_AUDITOR,
    OWNER_REPRESENTATIVE,
    PROGRAM_ADMIN,
    endpoint,
)
from services import derive

bp = Blueprint("draws", __name__)

CONTINGENCY_TYPES = ("OWNER", "CONSTRUCTION")
DRAW_ORIGINS = ("CHANGE_EVENT_CLASSIFICATION", "SUBCONTRACTOR_DEFAULT_PREMIUM")
DRAW_STATUSES = ("REQUESTED", "OWNER_APPROVED", "POSTED", "VOIDED", "DENIED")
READ_ROLES = (
    CONSTRUCTION_MANAGER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
    PROGRAM_ADMIN,
)

POT_FIELD = {
    "OWNER": "owner_contingency_remaining",
    "CONSTRUCTION": "construction_contingency_remaining",
}


@bp.route("/contingency-draws/<did>/approve", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE)
def approve_draw(did):
    body = v.json_body()
    approve = v.get_bool(body, "approve", required=True)
    v.get_str(body, "approval_note", required=False, min_len=0)
    draw = lookups.draw(did)
    project = lookups.project(draw["project_id"])
    guards.require_gmp_executed(project)
    if draw["status"] != "REQUESTED":
        raise ApiError(
            "ERR_DRAW_STATE_INVALID",
            "draw status is %s; an approval decision requires REQUESTED"
            % draw["status"],
        )
    if approve:
        draw["status"] = "OWNER_APPROVED"
        draw["approved_by_user_id"] = g.user_id
    else:
        draw["status"] = "DENIED"
    touch(draw)
    return resp.ok(serializers.draw(draw))


@bp.route("/contingency-draws/<did>/post", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def post_draw(did):
    body = v.json_body()
    v.get_str(body, "post_note", required=False, min_len=0)
    draw = lookups.draw(did)
    project = lookups.project(draw["project_id"])

    if draw["status"] not in ("REQUESTED", "OWNER_APPROVED"):
        raise ApiError(
            "ERR_DRAW_STATE_INVALID",
            "draw status is %s; posting requires REQUESTED or OWNER_APPROVED"
            % draw["status"],
        )
    guards.require_not_frozen(project)
    guards.require_gmp_executed(project)

    if draw["status"] == "REQUESTED":
        if draw["requires_owner_approval"]:
            raise ApiError(
                "ERR_OWNER_APPROVAL_REQUIRED",
                "this draw requires owner approval before it can be posted",
            )
        if project["contingency_posture"] == "CONSTRAINED":
            raise ApiError(
                "ERR_OWNER_APPROVAL_REQUIRED",
                "a CONSTRAINED contingency posture requires owner approval before "
                "any draw may be posted",
            )

    pot = POT_FIELD[draw["contingency_type"]]
    if draw["amount"] > project[pot]:
        raise ApiError(
            "ERR_CONTINGENCY_INSUFFICIENT",
            "draw amount %s exceeds the remaining %s contingency %s"
            % (draw["amount"], draw["contingency_type"], project[pot]),
        )

    draw["status"] = "POSTED"
    draw["posted_at"] = clock.now()
    project[pot] = q2(project[pot] - draw["amount"])
    project["contingency_drawn_to_cost_total"] = q2(
        project["contingency_drawn_to_cost_total"] + draw["amount"]
    )
    derive.apply_posture(project)
    touch(draw)
    touch(project)
    return resp.ok(serializers.draw(draw))


@bp.route("/contingency-draws/<did>/void", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE)
def void_draw(did):
    body = v.json_body()
    void_reason = v.get_str(body, "void_reason", required=True, min_len=1, max_len=1000)
    draw = lookups.draw(did)
    project = lookups.project(draw["project_id"])
    if draw["status"] != "POSTED":
        raise ApiError(
            "ERR_DRAW_STATE_INVALID",
            "draw status is %s; voiding requires POSTED" % draw["status"],
        )
    guards.require_not_frozen(project)

    pot = POT_FIELD[draw["contingency_type"]]
    draw["status"] = "VOIDED"
    draw["voided_at"] = clock.now()
    draw["void_reason"] = void_reason
    project[pot] = q2(project[pot] + draw["amount"])
    project["contingency_drawn_to_cost_total"] = q2(
        project["contingency_drawn_to_cost_total"] - draw["amount"]
    )
    derive.apply_posture(project)
    touch(draw)
    touch(project)
    return resp.ok(serializers.draw(draw))


@bp.route("/contingency-draws", methods=["GET"])
@endpoint(*READ_ROLES)
def list_draws():
    limit, offset = v.pagination()
    project_id = v.query_filter("project_id")
    change_event_id = v.query_filter("change_event_id")
    source_subcontract_id = v.query_filter("source_subcontract_id")
    contingency_type = v.query_filter("contingency_type", CONTINGENCY_TYPES)
    origin = v.query_filter("origin", DRAW_ORIGINS)
    status = v.query_filter("status", DRAW_STATUSES)
    rows = []
    for row in db.draws.values():
        if project_id is not None and row["project_id"] != project_id:
            continue
        if change_event_id is not None and row["change_event_id"] != change_event_id:
            continue
        if source_subcontract_id is not None \
                and row["source_subcontract_id"] != source_subcontract_id:
            continue
        if contingency_type is not None \
                and row["contingency_type"] != contingency_type:
            continue
        if origin is not None and row["origin"] != origin:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing([serializers.draw(r) for r in page], limit, offset, total)


@bp.route("/contingency-draws/<did>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_draw(did):
    return resp.ok(serializers.draw(lookups.draw(did)))
