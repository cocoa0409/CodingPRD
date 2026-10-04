"""Analyst endpoints (PRD 3.2)."""

from flask import Blueprint, request

from db import db, serialize
from errors import bad_request
from middleware import authenticate, body, enum, optional_str, require_str
from response import ok, ok_list
from routes._common import page_of, require_analyst

bp = Blueprint("analysts", __name__)

PRACTICE_AREAS = ("CIO_TECH", "DATA_ANALYTICS", "SECURITY", "ERP_FINANCE")
SENIORITIES = ("ASSOCIATE", "SENIOR", "VP", "DISTINGUISHED")
ANALYST_STATUSES = ("ACTIVE", "ON_LEAVE", "EMERITUS")


@bp.post("/research/analysts")
def create_analyst():
    authenticate(["PlatformAdmin"])
    data = body()
    full_name = require_str(data, "full_name")
    practice_area = enum(require_str(data, "practice_area"), PRACTICE_AREAS, "practice_area")
    topic_routes = data.get("topic_routes")
    if not isinstance(topic_routes, list) or not all(isinstance(t, str) for t in topic_routes):
        raise bad_request("topic_routes must be an array of strings.")
    seniority = enum(require_str(data, "seniority"), SENIORITIES, "seniority")
    status = enum(optional_str(data, "status", "ACTIVE") or "ACTIVE", ANALYST_STATUSES, "status")

    analyst_obj = db.create(
        full_name=full_name,
        practice_area=practice_area,
        topic_routes=list(topic_routes),
        seniority=seniority,
        status=status,
        open_inquiry_count=0,
        integrity_flag="CLEAR",
        conflicted_vendor_ids=[],
        inquiries_completed_total=0,
    )
    db.analysts[analyst_obj["id"]] = analyst_obj
    return ok(serialize(analyst_obj), 201)


@bp.get("/research/analysts/<analyst_id>")
def read_analyst(analyst_id):
    authenticate([
        "PlatformAdmin",
        "ResearchDirector",
        "ComplianceOfficer",
        "Analyst",
        "SeatHolder",
    ])
    return ok(serialize(require_analyst(analyst_id)), 200)


@bp.get("/research/analysts")
def list_analysts():
    authenticate([
        "PlatformAdmin",
        "ResearchDirector",
        "ComplianceOfficer",
        "SeatHolder",
        "Analyst",
    ])
    items = list(db.analysts.values())
    practice_area = request.args.get("practice_area")
    topic_route = request.args.get("topic_route")
    status = request.args.get("status")
    if practice_area:
        items = [a for a in items if a.get("practice_area") == practice_area]
    if topic_route:
        items = [a for a in items if topic_route in (a.get("topic_routes") or [])]
    if status:
        items = [a for a in items if a.get("status") == status]
    page, limit, offset, total = page_of(items)
    return ok_list(page, limit, offset, total)
