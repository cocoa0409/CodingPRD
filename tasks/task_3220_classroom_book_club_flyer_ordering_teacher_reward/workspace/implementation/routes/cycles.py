"""Flyer cycle and offering endpoints."""

from flask import Blueprint

import db
from errors import raise_err
from middleware import require_roles
from response import object_response, list_response, paginate
from services import (
    new_record, touch, serialize_cycle, serialize_offering, parse_month,
    school_posture, cycle_offering_count, title_license_status,
    CLUB_PRICE_FACTOR_NUM, CLUB_PRICE_FACTOR_DEN, GRADE_BANDS,
)
from routes.common import get_body, path_get, ref_get, req_field, req_enum

bp = Blueprint("cycles", __name__)


@bp.post("/club/flyer-cycles")
@require_roles("ClubAdmin")
def create_cycle():
    body = get_body()
    school_id = req_field(body, "school_id")
    ref_get(db.schools, school_id, "School")
    month = req_field(body, "month")
    parse_month(month)
    grade_band = req_enum(body, "grade_band", GRADE_BANDS)
    cycle = new_record({
        "school_id": school_id,
        "month": month,
        "grade_band": grade_band,
        "status": "DRAFT",
    })
    db.flyer_cycles[cycle["id"]] = cycle
    return object_response(serialize_cycle(cycle), 201)


@bp.get("/club/flyer-cycles/<cid>")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Parent")
def get_cycle(cid):
    return object_response(serialize_cycle(path_get(db.flyer_cycles, cid, "FlyerCycle")))


@bp.post("/club/flyer-cycles/<cid>/offerings")
@require_roles("ClubAdmin")
def add_offering(cid):
    cycle = path_get(db.flyer_cycles, cid, "FlyerCycle")
    body = get_body()
    title_id = req_field(body, "title_id")
    title = ref_get(db.titles, title_id, "Title")
    if cycle["status"] != "DRAFT":
        if cycle["status"] == "CLOSED":
            raise_err("ERR_ALREADY_TERMINAL", "Cycle is CLOSED")
        raise_err("ERR_INVALID_STATE", "Offerings may be added only to a DRAFT cycle")
    if title_license_status(title) != "ACTIVE":
        raise_err("ERR_LICENSE_SUSPENDED", "Title license is SUSPENDED")
    if title["grade_band"] != cycle["grade_band"]:
        raise_err("ERR_GRADE_BAND_MISMATCH", "Title grade band does not match the cycle's band")
    if title["format"] not in ("PAPERBACK", "CLUB_PAPERBACK"):
        raise_err("ERR_FORMAT_NOT_ALLOWED", "Only PAPERBACK or CLUB_PAPERBACK titles may be offered")
    if title["format"] == "CLUB_PAPERBACK":
        price = title["base_price_cents"] * CLUB_PRICE_FACTOR_NUM // CLUB_PRICE_FACTOR_DEN
    else:
        price = title["base_price_cents"]
    offering = new_record({
        "cycle_id": cid,
        "title_id": title_id,
        "flyer_price_cents": price,
    })
    db.offerings[offering["id"]] = offering
    return object_response(serialize_offering(offering), 201)


@bp.get("/club/flyer-cycles/<cid>/offerings")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Parent")
def list_offerings(cid):
    path_get(db.flyer_cycles, cid, "FlyerCycle")
    items = sorted((o for o in db.offerings.values() if o["cycle_id"] == cid),
                   key=lambda o: (o["created_at"], o["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_offering(o) for o in page], total, limit, offset))


@bp.get("/club/offerings/<oid>")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Parent")
def get_offering(oid):
    return object_response(serialize_offering(path_get(db.offerings, oid, "FlyerOffering")))


@bp.get("/club/offerings/<oid>/lines")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def offering_lines(oid):
    from services import serialize_line
    path_get(db.offerings, oid, "FlyerOffering")
    items = sorted((l for l in db.order_lines.values() if l["offering_id"] == oid),
                   key=lambda l: (l["created_at"], l["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_line(l) for l in page], total, limit, offset))


@bp.get("/club/flyer-cycles/<cid>/class-orders")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def cycle_orders(cid):
    from flask import request
    from services import serialize_order
    path_get(db.flyer_cycles, cid, "FlyerCycle")
    items = [o for o in db.class_orders.values() if o["cycle_id"] == cid]
    st = request.args.get("status")
    if st:
        items = [o for o in items if o["status"] == st]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_order(o) for o in page], total, limit, offset))


@bp.post("/club/flyer-cycles/<cid>/publish")
@require_roles("ClubAdmin")
def publish_cycle(cid):
    cycle = path_get(db.flyer_cycles, cid, "FlyerCycle")
    if cycle["status"] == "CLOSED":
        raise_err("ERR_ALREADY_TERMINAL", "Cycle is CLOSED")
    if cycle["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT cycle can be published")
    if school_posture(cycle["school_id"]) != "NORMAL":
        raise_err("ERR_SCHOOL_RESTRICTED", "School posture is RESTRICTED")
    for c in db.flyer_cycles.values():
        if (c["id"] != cid and c["school_id"] == cycle["school_id"]
                and c["grade_band"] == cycle["grade_band"] and c["status"] == "PUBLISHED"):
            raise_err("ERR_CYCLE_ALREADY_PUBLISHED",
                      "Another PUBLISHED cycle exists for this (school, grade_band)")
    if cycle_offering_count(cid) < 1:
        raise_err("ERR_EMPTY_CYCLE", "Publish requires at least one offering")
    cycle["status"] = "PUBLISHED"
    touch(cycle)
    # fair_overlap is derived; initialize the cached value on each offering.
    from services import offering_fair_overlap
    for o in db.offerings.values():
        if o["cycle_id"] == cid:
            o["_fair_overlap_cache"] = offering_fair_overlap(o)
    return object_response(serialize_cycle(cycle))


@bp.post("/club/flyer-cycles/<cid>/close")
@require_roles("ClubAdmin")
def close_cycle(cid):
    cycle = path_get(db.flyer_cycles, cid, "FlyerCycle")
    if cycle["status"] == "CLOSED":
        raise_err("ERR_ALREADY_TERMINAL", "Cycle is CLOSED")
    if cycle["status"] == "PUBLISHED":
        for o in db.class_orders.values():
            if o["cycle_id"] == cid and o["status"] == "OPEN":
                raise_err("ERR_INVALID_STATE",
                          "Every ClassOrder in the cycle must be out of OPEN before close")
    cycle["status"] = "CLOSED"
    touch(cycle)
    return object_response(serialize_cycle(cycle))
