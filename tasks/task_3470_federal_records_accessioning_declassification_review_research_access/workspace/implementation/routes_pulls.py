"""PullRequest endpoints (PRD §3.7) — the densest gate cascade in the system.

POST /records/pull-requests               Researcher, 201
GET  /records/pull-requests               all roles except Anonymous
GET  /records/pull-requests/{id}          all roles except Anonymous
POST /records/pull-requests/{id}/fulfill  ResearchRoomStaff
POST /records/pull-requests/{id}/return   ResearchRoomStaff (late return cascades)
"""
from datetime import timedelta

from flask import Blueprint, request

import calcs
import constants as C
from envelope import ok_list, ok_object
from errors import err
from helpers import (
    bump,
    get_collection,
    get_pull,
    load_researcher,
    require_active_researcher,
    suspend_researcher,
    touch_collection,
)
from store import DB, new_id, parse_dt, ts3, tsc
from validation import (
    body_fk,
    get_auth,
    get_body,
    list_page,
    req_dt,
    req_int,
    require_ownership,
    require_role,
)

bp = Blueprint("pulls", __name__)


def _covered_days(visit_dt):
    """A pull occupies one reading-room seat on the UTC day of its visit and
    the following UTC day (exactly two days)."""
    d0 = visit_dt.date()
    return (d0, d0 + timedelta(days=1))


@bp.post("/records/pull-requests")
def create_pull():
    uid, role = get_auth()                        # rung 1
    require_role(role, ["Researcher"])            # rung 2
    body = get_body()
    # rung 4: body FK existence in declared input order
    researcher_id = body_fk(body, "researcher_id")
    researcher = load_researcher(researcher_id)   # 404 + lazy expiry
    collection_id = body_fk(body, "collection_id")
    collection = get_collection(collection_id)
    require_ownership(uid, researcher_id)         # rung 5
    require_active_researcher(researcher)         # rung 9
    # rung 10: records must be open
    if collection["restriction_posture"] != "PUBLIC":
        raise err(
            "ERR_COLLECTION_RESTRICTED",
            "pull requests require restriction_posture PUBLIC",
        )
    # rung 13: visit window [clock, clock + 30 days], inclusive both ends
    visit_dt = req_dt(body, "visit_date")
    now_dt = DB.now()
    if visit_dt < now_dt or visit_dt > calcs.add_days(now_dt, C.VISIT_WINDOW_DAYS):
        raise err(
            "ERR_VISIT_DATE_OUT_OF_WINDOW",
            "visit_date must fall within [clock, clock + 30 days]",
        )
    # rung 15: collection must be described
    if collection["processing_status"] not in ("DESCRIBED", "PUBLISHED"):
        raise err(
            "ERR_COLLECTION_NOT_DESCRIBED",
            "pull requests require processing_status DESCRIBED or PUBLISHED",
        )
    # rung 16: reservation rules, fixed sub-order -------------------------
    unit_start = req_int(body, "unit_start")
    unit_end = req_int(body, "unit_end")
    # (1) unit range inside [1, units_total]
    if (
        unit_start < 1
        or unit_end > collection["units_total"]
        or unit_start > unit_end
    ):
        raise err(
            "ERR_UNIT_RANGE_INVALID",
            "unit range must satisfy 1 <= unit_start <= unit_end <= units_total",
        )
    # (2) span limit
    if unit_end - unit_start + 1 > C.MAX_PULL_UNITS_PER_REQUEST:
        raise err(
            "ERR_UNIT_SPAN_LIMIT_EXCEEDED",
            "a pull may reserve at most 24 units",
        )
    # (3) unit-reservation overlap on the same collection
    new_start = visit_dt
    new_end = calcs.add_days(visit_dt, C.PULL_OCCUPATION_DAYS)
    for p in DB.pulls.values():
        if p["collection_id"] != collection["id"]:
            continue
        if p["status"] not in ("REQUESTED", "PULLED"):
            continue
        ranges_share = p["unit_start"] <= unit_end and unit_start <= p["unit_end"]
        if not ranges_share:
            continue
        p_start = parse_dt(p["visit_date"])
        p_end = calcs.add_days(p_start, C.PULL_OCCUPATION_DAYS)
        # half-open windows share an instant iff each starts before the other ends
        if new_start < p_end and p_start < new_end:
            raise err(
                "ERR_UNIT_RESERVATION_CONFLICT",
                "unit range overlaps another active pull on this collection",
            )
    # (4) reading-room per-day seat capacity (aggregate, all collections)
    for day in _covered_days(visit_dt):
        occupants = 0
        for p in DB.pulls.values():
            if p["status"] not in ("REQUESTED", "PULLED"):
                continue
            if day in _covered_days(parse_dt(p["visit_date"])):
                occupants += 1
        if occupants + 1 > C.READING_ROOM_DAILY_SEATS:
            raise err(
                "ERR_READING_ROOM_CAPACITY",
                "reading-room seat capacity reached on a day of the visit window",
            )
    # (5) researcher's own active-pull limit (< 3; a 3rd succeeds)
    active = sum(
        1
        for p in DB.pulls.values()
        if p["researcher_id"] == researcher_id
        and p["status"] in ("REQUESTED", "PULLED")
    )
    if active >= C.MAX_ACTIVE_PULLS_PER_RESEARCHER:
        raise err(
            "ERR_ACTIVE_PULL_LIMIT_EXCEEDED",
            "researcher already holds 3 active pulls",
        )
    now = ts3(now_dt)
    pull = {
        "id": new_id(),
        "researcher_id": researcher_id,
        "collection_id": collection_id,
        "unit_start": unit_start,
        "unit_end": unit_end,
        "visit_date": tsc(visit_dt),
        "status": "REQUESTED",
        "due_back_at": tsc(visit_dt + timedelta(hours=24)),
        "returned_at": None,
        "late_return": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.pulls[pull["id"]] = pull
    return ok_object(pull, 201)


@bp.get("/records/pull-requests")
def list_pulls():
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    filters = {}
    for k in ("researcher_id", "collection_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    page, total, limit, offset = list_page(DB.pulls.values(), filters)
    return ok_list(page, total, limit, offset)


@bp.get("/records/pull-requests/<pull_id>")
def get_one_pull(pull_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    return ok_object(get_pull(pull_id))


@bp.post("/records/pull-requests/<pull_id>/fulfill")
def fulfill_pull(pull_id):
    _uid, role = get_auth()
    require_role(role, ["ResearchRoomStaff"])
    p = get_pull(pull_id)                         # rung 3
    if p["status"] != "REQUESTED":                # rung 8
        raise err("ERR_PULL_NOT_FULFILLABLE", "fulfill requires status REQUESTED")
    p["status"] = "PULLED"
    bump(p)
    collection = DB.collections[p["collection_id"]]
    collection["pull_count_total"] += 1
    touch_collection(collection)   # priority recompute if QUEUED + version bump
    return ok_object(p)


@bp.post("/records/pull-requests/<pull_id>/return")
def return_pull(pull_id):
    _uid, role = get_auth()
    require_role(role, ["ResearchRoomStaff"])
    p = get_pull(pull_id)                         # rung 3
    if p["status"] != "PULLED":                   # rung 8
        raise err("ERR_PULL_NOT_RETURNABLE", "return requires status PULLED")
    now_dt = DB.now()
    p["status"] = "RETURNED"
    p["returned_at"] = tsc(now_dt)
    # strictly greater: a return at exactly due_back_at is on time
    p["late_return"] = now_dt > parse_dt(p["due_back_at"])
    bump(p)
    if p["late_return"]:
        researcher = load_researcher(p["researcher_id"])
        suspend_researcher(researcher)
    return ok_object(p)
