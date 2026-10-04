"""Book fair endpoints."""

from flask import Blueprint

import db
from errors import raise_err
from middleware import require_roles
from response import object_response, list_response, paginate
from services import (
    new_record, touch, serialize_fair, serialize_fair_title, parse_date,
    school_posture, windows_intersect, title_fair_count_used,
    recompute_fair_overlap_for_school, TITLE_FAIR_OVERLAP_LIMIT,
)
from routes.common import get_body, path_get, ref_get, req_field

bp = Blueprint("fairs", __name__)


@bp.post("/club/book-fairs")
@require_roles("SchoolAdmin", "ClubAdmin")
def create_fair():
    body = get_body()
    school_id = req_field(body, "school_id")
    ref_get(db.schools, school_id, "School")
    start_date = req_field(body, "start_date")
    end_date = req_field(body, "end_date")
    start = parse_date(start_date, "start_date")
    end = parse_date(end_date, "end_date")
    if end <= start:
        raise_err("ERR_INVALID_REQUEST", "end_date must be > start_date")
    if school_posture(school_id) != "NORMAL":
        raise_err("ERR_SCHOOL_RESTRICTED", "School posture is RESTRICTED")
    for f in db.book_fairs.values():
        if f["school_id"] != school_id or f["status"] == "CANCELLED":
            continue
        if windows_intersect(f["_start"], f["_end"], start, end):
            raise_err("ERR_FAIR_OVERLAP",
                      "BookFair window intersects another fair at the same school")
    fair = new_record({
        "school_id": school_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": "SCHEDULED",
        "_start": start,
        "_end": end,
    })
    db.book_fairs[fair["id"]] = fair
    return object_response(serialize_fair(fair), 201)


@bp.get("/club/book-fairs/<fid>")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def get_fair(fid):
    return object_response(serialize_fair(path_get(db.book_fairs, fid, "BookFair")))


@bp.get("/club/book-fairs/<fid>/titles")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def list_fair_titles(fid):
    path_get(db.book_fairs, fid, "BookFair")
    items = sorted((ft for ft in db.fair_titles.values() if ft["fair_id"] == fid),
                   key=lambda ft: (ft["created_at"], ft["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_fair_title(ft) for ft in page], total, limit, offset))


@bp.post("/club/book-fairs/<fid>/titles")
@require_roles("SchoolAdmin", "ClubAdmin")
def add_fair_title(fid):
    fair = path_get(db.book_fairs, fid, "BookFair")
    body = get_body()
    title_id = req_field(body, "title_id")
    ref_get(db.titles, title_id, "Title")
    if fair["status"] in ("COMPLETED", "CANCELLED"):
        raise_err("ERR_ALREADY_TERMINAL", "Fair is %s" % fair["status"])
    for ft in db.fair_titles.values():
        if ft["fair_id"] == fid and ft["title_id"] == title_id:
            raise_err("ERR_INVALID_REQUEST", "Title already featured at this fair")
    if title_fair_count_used(title_id) >= TITLE_FAIR_OVERLAP_LIMIT:
        raise_err("ERR_TITLE_OVERLAP_CAP",
                  "Title fair_count_used already >= %d" % TITLE_FAIR_OVERLAP_LIMIT)
    ft = new_record({"fair_id": fid, "title_id": title_id})
    db.fair_titles[ft["id"]] = ft
    touch(fair)
    recompute_fair_overlap_for_school(fair["school_id"])
    return object_response(serialize_fair_title(ft), 201)


@bp.post("/club/book-fairs/<fid>/cancel")
@require_roles("SchoolAdmin", "ClubAdmin")
def cancel_fair(fid):
    fair = path_get(db.book_fairs, fid, "BookFair")
    if fair["status"] == "COMPLETED":
        raise_err("ERR_FAIR_NOT_CANCELLABLE", "Cannot cancel a COMPLETED fair")
    if fair["status"] == "CANCELLED":
        raise_err("ERR_ALREADY_TERMINAL", "Fair is CANCELLED")
    fair["status"] = "CANCELLED"
    touch(fair)
    recompute_fair_overlap_for_school(fair["school_id"])
    return object_response(serialize_fair(fair))
