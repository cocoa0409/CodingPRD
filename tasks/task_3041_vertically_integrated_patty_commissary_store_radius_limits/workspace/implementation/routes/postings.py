"""ManagerPosting and ManagerApplication routes."""

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_APPLICATION_INVALID_STATE,
    ERR_POSTING_INVALID_STATE,
    ERR_SOD_VIOLATION,
    conflict,
    forbidden,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    paginate,
    req_string,
    touch,
)

bp = Blueprint("postings", __name__)


@bp.route("/manager-postings", methods=["POST"])
def create_posting():
    user_id, _ = require_roles("HRDirector")
    body = get_json_body()
    store_id = req_string(body, "store_id")
    # Body FK existence (tier 5).
    store = domain.get_store(store_id)
    p = base_entity()
    p.update({
        "store_id": store["id"],
        "posted_by_id": user_id,
        "status": "OPEN",
        "filled_by_associate_id": None,
    })
    db.postings[p["id"]] = p
    return success_object(domain.ser_posting(p), 201)


@bp.route("/stores/<sid>/manager-postings", methods=["GET"])
def list_store_postings(sid):
    require_roles("HRDirector", "StoreManager", "Associate")
    store = domain.get_store(sid)
    items = [p for p in db.postings.values() if p["store_id"] == store["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_posting(p) for p in page], limit, offset, total)


@bp.route("/manager-postings/<pid>", methods=["GET"])
def get_posting(pid):
    require_roles("HRDirector", "StoreManager", "Associate")
    return success_object(domain.ser_posting(domain.get_posting(pid)))


@bp.route("/manager-postings/<pid>/applications", methods=["POST"])
def apply_to_posting(pid):
    require_roles("Associate")
    # Path existence (tier 4).
    posting = domain.get_posting(pid)
    body = get_json_body()
    candidate_id = req_string(body, "candidate_associate_id")
    # Body FK existence (tier 5).
    candidate = domain.get_associate(candidate_id)
    # State (tier 8): posting must be OPEN.
    if posting["status"] != "OPEN":
        raise conflict(ERR_POSTING_INVALID_STATE, "Posting is not OPEN")
    # Internal sourcing (tier 21): active SHIFT_LEAD, not the posting store's
    # current manager.
    store = db.stores.get(posting["store_id"])
    current_manager = store.get("manager_associate_id") if store else None
    if (
        not candidate.get("active", True)
        or candidate["current_level"] != "SHIFT_LEAD"
        or candidate_id == current_manager
    ):
        raise unprocessable(ERR_SOD_VIOLATION, "Candidate is not eligible for internal manager sourcing")
    a = base_entity()
    a.update({
        "posting_id": posting["id"],
        "candidate_associate_id": candidate_id,
        "status": "PENDING",
    })
    db.applications[a["id"]] = a
    return success_object(domain.ser_application(a), 201)


@bp.route("/manager-postings/<pid>/applications", methods=["GET"])
def list_posting_applications(pid):
    require_roles("HRDirector", "Associate")
    posting = domain.get_posting(pid)
    items = [a for a in db.applications.values() if a["posting_id"] == posting["id"]]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_application(a) for a in page], limit, offset, total)


@bp.route("/manager-applications", methods=["GET"])
def list_applications():
    require_roles("HRDirector")
    items = list(db.applications.values())
    cid = request.args.get("candidate_associate_id")
    if cid is not None:
        items = [a for a in items if a["candidate_associate_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_application(a) for a in page], limit, offset, total)


@bp.route("/associates/<aid>/manager-applications", methods=["GET"])
def list_associate_applications(aid):
    require_roles("HRDirector", "Associate")
    assoc = domain.get_associate(aid)
    items = [a for a in db.applications.values() if a["candidate_associate_id"] == assoc["id"]]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_application(a) for a in page], limit, offset, total)


@bp.route("/manager-applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    user_id, _ = require_roles("Associate")
    app = domain.get_application(aid)
    # Identity (tier 3): only the candidate may withdraw.
    if user_id != app["candidate_associate_id"]:
        raise forbidden("Only the candidate may withdraw their own application")
    if app["status"] != "PENDING":
        raise conflict(ERR_APPLICATION_INVALID_STATE, "Application is not PENDING")
    app["status"] = "WITHDRAWN"
    touch(app)
    return success_object(domain.ser_application(app))


@bp.route("/manager-postings/<pid>/close", methods=["POST"])
def close_posting(pid):
    user_id, _ = require_roles("HRDirector")
    posting = domain.get_posting(pid)
    body = get_json_body()
    candidate_application_id = req_string(body, "candidate_application_id")
    # Body FK existence (tier 5).
    application = domain.get_application(candidate_application_id)
    # State (tier 8): posting OPEN.
    if posting["status"] != "OPEN":
        raise conflict(ERR_POSTING_INVALID_STATE, "Posting is not OPEN")
    # Application must be PENDING on this posting.
    if application["posting_id"] != posting["id"] or application["status"] != "PENDING":
        raise conflict(ERR_APPLICATION_INVALID_STATE, "candidate_application_id is not a PENDING application on this posting")
    # SoD (tier 21): closer != poster.
    if user_id == posting["posted_by_id"]:
        raise unprocessable(ERR_SOD_VIOLATION, "The posting creator may not close the same posting")
    candidate = domain.get_associate(application["candidate_associate_id"])
    # Close: fill, accept selected, reject other PENDING.
    posting["filled_by_associate_id"] = candidate["id"]
    posting["status"] = "CLOSED"
    touch(posting)
    for a in db.applications.values():
        if a["posting_id"] != posting["id"] or a["status"] != "PENDING":
            continue
        if a["id"] == application["id"]:
            a["status"] = "ACCEPTED"
        else:
            a["status"] = "REJECTED"
        touch(a)
    # Promote the candidate: SHIFT_LEAD -> MANAGER, wage recompute, compounding
    # promotion count, home-store move, store manager update.
    candidate["current_level"] = "MANAGER"
    candidate["hourly_wage_cents"] = calc.wage_for_level("MANAGER")
    candidate["promotion_count"] += 1
    candidate["home_store_id"] = posting["store_id"]
    touch(candidate)
    store = db.stores.get(posting["store_id"])
    if store is not None:
        store["manager_associate_id"] = candidate["id"]
    return success_object(domain.ser_posting(posting))


@bp.route("/manager-postings/<pid>/cancel", methods=["POST"])
def cancel_posting(pid):
    require_roles("HRDirector")
    posting = domain.get_posting(pid)
    if posting["status"] != "OPEN":
        raise conflict(ERR_POSTING_INVALID_STATE, "Posting is not OPEN")
    posting["status"] = "CANCELLED"
    touch(posting)
    for a in db.applications.values():
        if a["posting_id"] == posting["id"] and a["status"] == "PENDING":
            a["status"] = "REJECTED"
            touch(a)
    return success_object(domain.ser_posting(posting))
