"""Research access requests (PRD 3.8): scholar creation over a closed visit
interval, and registrar decision with object-state and overlap gates."""

from flask import Blueprint

import calc
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("research_access_requests", __name__)

RESEARCH_READ_ROLES = ["PlatformAdmin", "Registrar", "Scholar"]


@bp.post("/campus/research-access-requests")
def create_request():
    uid, role = auth()
    require_role(role, ["Scholar"])
    b = util.body()
    # (4) body FK existence
    object_id = b.get("object_id")
    obj = None
    if object_id is not None:
        obj = get_or_404("collection_objects", object_id, "CollectionObject")
    # (9) request shape
    if object_id is None:
        fail("ERR_INVALID_REQUEST", "Missing required field: object_id")
    scholar_name = util.req_str(b, "scholar_name")
    research_topic = util.req_str(b, "research_topic")
    visit_start_date = util.req_date(b, "visit_start_date")
    visit_end_date = util.req_date(b, "visit_end_date")
    # Closed interval: the end is on or after the start.
    if util.parse_date(visit_end_date) < util.parse_date(visit_start_date):
        fail("ERR_INVALID_REQUEST", "visit_end_date must be on or after visit_start_date")
    r = db.new_entity(
        {
            "object_id": obj["id"],
            "scholar_name": scholar_name,
            "research_topic": research_topic,
            "visit_start_date": visit_start_date,
            "visit_end_date": visit_end_date,
            "status": "REQUESTED",
            "created_by_user_id": uid,
        }
    )
    db.STORE["research_requests"][r["id"]] = r
    return success(serializers.research_access_request(r), 201)


@bp.get("/campus/research-access-requests")
def list_requests():
    _uid, role = auth()
    require_role(role, RESEARCH_READ_ROLES)
    limit, offset = util.pagination()
    f_object = util.request.args.get("object_id")
    rows = []
    for r in db.all_sorted("research_requests"):
        if f_object is not None and r["object_id"] != f_object:
            continue
        rows.append(r)
    page = rows[offset : offset + limit]
    return listing([serializers.research_access_request(r) for r in page], limit, offset, len(rows))


@bp.get("/campus/research-access-requests/<rid>")
def get_request(rid):
    _uid, role = auth()
    require_role(role, RESEARCH_READ_ROLES)
    r = get_or_404("research_requests", rid, "ResearchAccessRequest")
    return success(serializers.research_access_request(r))


@bp.post("/campus/research-access-requests/<rid>/decide")
def decide_request(rid):
    _uid, role = auth()
    require_role(role, ["Registrar"])
    r = get_or_404("research_requests", rid, "ResearchAccessRequest")
    if r["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Only a REQUESTED research access request can be decided")
    b = util.body()
    outcome = util.req_enum(b, "outcome", ("APPROVED", "DENIED"))
    if outcome == "APPROVED":
        # (18) approval gates, in PRD 3.8 order
        obj = db.STORE["collection_objects"].get(r["object_id"])
        if obj is None or obj["status"] != "IN_COLLECTION":
            fail("ERR_OBJECT_NOT_IN_COLLECTION", "The object is not IN_COLLECTION")
        v_start = util.parse_date(r["visit_start_date"])
        v_end = util.parse_date(r["visit_end_date"])
        # Visit-visit overlap: CLOSED intervals; a shared boundary day conflicts.
        for o in db.STORE["research_requests"].values():
            if o["id"] == r["id"] or o["object_id"] != r["object_id"]:
                continue
            if o["status"] != "APPROVED":
                continue
            if calc.closed_overlap(
                v_start,
                v_end,
                util.parse_date(o["visit_start_date"]),
                util.parse_date(o["visit_end_date"]),
            ):
                fail(
                    "ERR_RESEARCH_VISIT_CONFLICT",
                    "The visit interval overlaps another approved research visit",
                )
        # Visit-loan overlap against AGREED/ACTIVE loan windows.
        for l in db.STORE["loan_agreements"].values():
            if l["object_id"] != r["object_id"] or l["status"] not in ("AGREED", "ACTIVE"):
                continue
            if calc.visit_loan_conflict(
                v_start,
                v_end,
                util.parse_date(l["loan_start_date"]),
                util.parse_date(l["loan_end_date"]),
            ):
                fail(
                    "ERR_OBJECT_RESERVED_FOR_LOAN",
                    "The visit interval overlaps an agreed or active loan window",
                )
    r["status"] = outcome
    db.touch(r)
    return success(serializers.research_access_request(r))
