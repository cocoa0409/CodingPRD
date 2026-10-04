"""ReproductionRequest endpoints (PRD §3.8).

POST /records/reproduction-requests               Researcher, 201 (fee computed)
GET  /records/reproduction-requests               all roles except Anonymous
GET  /records/reproduction-requests/{id}          all roles except Anonymous
POST /records/reproduction-requests/{id}/pay      Researcher (owner)
POST /records/reproduction-requests/{id}/fulfill  ResearchRoomStaff
POST /records/reproduction-requests/{id}/cancel   Researcher (owner, QUOTED only)
"""
from flask import Blueprint, request

import calcs
import constants as C
from envelope import ok_list, ok_object
from errors import err
from helpers import (
    bump,
    get_collection,
    get_repro,
    load_researcher,
    require_active_researcher,
    touch_collection,
)
from store import DB, new_id, parse_dt, ts3
from validation import (
    body_fk,
    get_auth,
    get_body,
    list_page,
    req_bool,
    req_enum,
    req_int,
    req_str,
    require_ownership,
    require_role,
)

bp = Blueprint("repros", __name__)


@bp.post("/records/reproduction-requests")
def create_repro():
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
            "reproduction requests require restriction_posture PUBLIC",
        )
    # rung 15: shape rules
    if collection["processing_status"] not in ("DESCRIBED", "PUBLISHED"):
        raise err(
            "ERR_COLLECTION_NOT_DESCRIBED",
            "reproduction requests require processing_status DESCRIBED or "
            "PUBLISHED",
        )
    page_count = req_int(body, "page_count")
    if page_count < 1:
        raise err("ERR_INVALID_REQUEST", "page_count must be at least 1")
    req_enum(body, "format", C.REPRO_FORMATS)     # format selects no rate in v1
    rush = req_bool(body, "rush", default=False)
    # rung 17: daily committed-pages quota (inclusive 200-page boundary;
    # CANCELLED requests are excluded, so cancellation restores quota)
    today = DB.now().date()
    committed = sum(
        rp["page_count"]
        for rp in DB.repros.values()
        if rp["researcher_id"] == researcher_id
        and rp["status"] in ("QUOTED", "PAID", "FULFILLED")
        and parse_dt(rp["created_at"]).date() == today
    )
    if committed + page_count > C.REPRO_DAILY_PAGE_LIMIT:
        raise err(
            "ERR_DAILY_PAGE_LIMIT_EXCEEDED",
            "committed daily pages plus this request exceed 200",
        )
    fee = calcs.reproduction_fee_cents(page_count, researcher["affiliation"], rush)
    now = ts3(DB.now())
    repro = {
        "id": new_id(),
        "researcher_id": researcher_id,
        "collection_id": collection_id,
        "page_count": page_count,
        "format": body["format"],
        "rush": rush,
        "fee_cents": fee,
        "status": "QUOTED",
        "payment_reference": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.repros[repro["id"]] = repro
    return ok_object(repro, 201)


@bp.get("/records/reproduction-requests")
def list_repros():
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    filters = {}
    for k in ("researcher_id", "collection_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    page, total, limit, offset = list_page(DB.repros.values(), filters)
    return ok_list(page, total, limit, offset)


@bp.get("/records/reproduction-requests/<repro_id>")
def get_one_repro(repro_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    return ok_object(get_repro(repro_id))


@bp.post("/records/reproduction-requests/<repro_id>/pay")
def pay_repro(repro_id):
    uid, role = get_auth()
    require_role(role, ["Researcher"])
    rp = get_repro(repro_id)                      # rung 3
    require_ownership(uid, rp["researcher_id"])   # rung 5
    if rp["status"] != "QUOTED":                  # rung 8
        raise err("ERR_REPRO_NOT_PAYABLE", "pay requires status QUOTED")
    payment_reference = req_str(get_body(), "payment_reference")   # rung 15
    rp["status"] = "PAID"
    rp["payment_reference"] = payment_reference
    bump(rp)
    return ok_object(rp)


@bp.post("/records/reproduction-requests/<repro_id>/fulfill")
def fulfill_repro(repro_id):
    _uid, role = get_auth()
    require_role(role, ["ResearchRoomStaff"])
    rp = get_repro(repro_id)                      # rung 3
    # rung 17/8: QUOTED -> not yet paid (402); terminal states -> generic 409
    if rp["status"] == "QUOTED":
        raise err("ERR_REPRO_NOT_PAID", "fulfill requires status PAID")
    if rp["status"] != "PAID":
        raise err("ERR_INVALID_STATE", "fulfill requires status PAID")
    rp["status"] = "FULFILLED"
    bump(rp)
    collection = DB.collections[rp["collection_id"]]
    collection["repro_pages_fulfilled"] += rp["page_count"]
    touch_collection(collection)   # priority recompute if QUEUED + version bump
    return ok_object(rp)


@bp.post("/records/reproduction-requests/<repro_id>/cancel")
def cancel_repro(repro_id):
    uid, role = get_auth()
    require_role(role, ["Researcher"])
    rp = get_repro(repro_id)                      # rung 3
    require_ownership(uid, rp["researcher_id"])   # rung 5
    if rp["status"] != "QUOTED":                  # rung 8
        raise err("ERR_REPRO_NOT_CANCELLABLE", "cancel requires status QUOTED")
    rp["status"] = "CANCELLED"   # committed daily pages freed immediately
    bump(rp)
    return ok_object(rp)
