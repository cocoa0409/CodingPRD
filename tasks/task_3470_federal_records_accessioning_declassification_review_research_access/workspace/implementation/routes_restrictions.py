"""PresidentialRestriction endpoints (PRD §3.6).

POST /records/presidential-restrictions                 ChiefArchivist, 201
GET  /records/presidential-restrictions                 all roles except Anonymous
GET  /records/presidential-restrictions/{id}            all roles except Anonymous
POST /records/presidential-restrictions/{id}/designate  ChiefArchivist (in-state)
POST /records/presidential-restrictions/{id}/notify     ChiefArchivist
POST /records/presidential-restrictions/{id}/release    ChiefArchivist (cooling gate)
"""
from flask import Blueprint, request

import calcs
import constants as C
from envelope import ok_list, ok_object
from errors import err
from helpers import bump, get_collection, get_restriction, recompute_posture
from store import DB, new_id, parse_dt, ts3, tsc
from validation import (
    body_fk,
    get_auth,
    get_body,
    list_page,
    req_enum,
    req_str,
    require_role,
)

bp = Blueprint("restrictions", __name__)


@bp.post("/records/presidential-restrictions")
def create_restriction():
    _uid, role = get_auth()                       # rung 1
    require_role(role, ["ChiefArchivist"])        # rung 2
    body = get_body()
    collection_id = body_fk(body, "collection_id")   # rung 4
    collection = get_collection(collection_id)
    category = req_enum(body, "category", C.RESTRICTION_CATEGORIES)   # shape of the key
    # rung 12: at most one non-RELEASED restriction per (collection, category)
    if any(
        r["collection_id"] == collection["id"]
        and r["category"] == category
        and r["status"] != "RELEASED"
        for r in DB.restrictions.values()
    ):
        raise err(
            "ERR_DUPLICATE_RESTRICTION_CATEGORY",
            "a non-RELEASED restriction of this category already exists on "
            "the collection",
        )
    # rung 15: presidential restrictions attach to PRESIDENTIAL-domain records
    if collection["records_domain"] != "PRESIDENTIAL":
        raise err(
            "ERR_NOT_PRESIDENTIAL_RECORDS",
            "the target collection's records_domain is not PRESIDENTIAL",
        )
    now = ts3(DB.now())
    restriction = {
        "id": new_id(),
        "collection_id": collection_id,
        "category": category,
        "status": "IMPOSED",
        "representative_id": None,
        "notified_at": None,
        "released_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.restrictions[restriction["id"]] = restriction
    # imposing a live restriction recomputes the posture (becomes
    # PRESIDENTIAL_HOLD) and advances the collection's version
    recompute_posture(collection)
    bump(collection)
    return ok_object(restriction, 201)


@bp.get("/records/presidential-restrictions")
def list_restrictions():
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    filters = {}
    for k in ("collection_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    page, total, limit, offset = list_page(DB.restrictions.values(), filters)
    return ok_list(page, total, limit, offset)


@bp.get("/records/presidential-restrictions/<restriction_id>")
def get_one_restriction(restriction_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    return ok_object(get_restriction(restriction_id))


@bp.post("/records/presidential-restrictions/<restriction_id>/designate")
def designate_representative(restriction_id):
    _uid, role = get_auth()
    require_role(role, ["ChiefArchivist"])
    r = get_restriction(restriction_id)           # rung 3
    if r["status"] != "IMPOSED":                  # rung 8 (in-state update)
        raise err("ERR_INVALID_STATE", "designate requires status IMPOSED")
    r["representative_id"] = req_str(get_body(), "representative_id")   # rung 15
    bump(r)
    return ok_object(r)


@bp.post("/records/presidential-restrictions/<restriction_id>/notify")
def notify_restriction(restriction_id):
    _uid, role = get_auth()
    require_role(role, ["ChiefArchivist"])
    r = get_restriction(restriction_id)           # rung 3
    if r["status"] != "IMPOSED":                  # rung 8
        raise err("ERR_INVALID_STATE", "notify requires status IMPOSED")
    if not r["representative_id"]:                # rung 15
        raise err(
            "ERR_REPRESENTATIVE_REQUIRED",
            "notify requires a designated representative_id",
        )
    r["status"] = "NOTIFIED"
    r["notified_at"] = tsc(DB.now())
    bump(r)
    return ok_object(r)


@bp.post("/records/presidential-restrictions/<restriction_id>/release")
def release_restriction(restriction_id):
    _uid, role = get_auth()
    require_role(role, ["ChiefArchivist"])
    r = get_restriction(restriction_id)           # rung 3
    if r["status"] != "NOTIFIED":                 # rung 8
        raise err(
            "ERR_RESTRICTION_NOT_NOTIFIED",
            "release requires status NOTIFIED",
        )
    # rung 13: cooling period notified_at + 30 days, boundary inclusive
    if DB.now() < calcs.add_days(parse_dt(r["notified_at"]), C.NOTICE_COOLING_DAYS):
        raise err(
            "ERR_COOLING_PERIOD_ACTIVE",
            "the 30-day cooling period is still running",
        )
    r["status"] = "RELEASED"
    r["released_at"] = tsc(DB.now())
    bump(r)
    collection = DB.collections[r["collection_id"]]
    recompute_posture(collection)   # may flip to PUBLIC and close pending FOIA
    bump(collection)
    return ok_object(r)
