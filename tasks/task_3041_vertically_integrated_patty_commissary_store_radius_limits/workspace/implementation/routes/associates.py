"""Associate routes: hire, list, get, patch, promote."""

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_PROMOTION_INELIGIBLE,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    opt_bool,
    paginate,
    parse_datetime,
    req_field,
    req_string,
    touch,
)

bp = Blueprint("associates", __name__)


@bp.route("/associates", methods=["POST"])
def hire_associate():
    require_roles("HRDirector")
    body = get_json_body()
    full_name = req_string(body, "full_name")
    hired_date = parse_datetime(req_field(body, "hired_date"), "hired_date")
    home_store_id = req_string(body, "home_store_id")
    active = opt_bool(body, "active", True)
    # Body FK existence (tier 5).
    store = domain.get_store(home_store_id)
    a = base_entity()
    a.update({
        "full_name": full_name,
        "hired_date": hired_date,
        "home_store_id": store["id"],
        "current_level": "LEVEL_1",
        "hourly_wage_cents": calc.wage_for_level("LEVEL_1"),
        "promotion_count": 0,
        "active": active,
    })
    db.associates[a["id"]] = a
    return success_object(domain.ser_associate(a), 201)


@bp.route("/associates", methods=["GET"])
def list_associates():
    require_roles("HRDirector", "StoreManager")
    items = list(db.associates.values())
    hs = request.args.get("home_store_id")
    if hs is not None:
        items = [a for a in items if a["home_store_id"] == hs]
    cl = request.args.get("current_level")
    if cl is not None:
        items = [a for a in items if a["current_level"] == cl]
    act = request.args.get("active")
    if act is not None:
        want = act.lower() == "true"
        items = [a for a in items if a["active"] == want]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_associate(a) for a in page], limit, offset, total)


@bp.route("/associates/<aid>", methods=["GET"])
def get_associate(aid):
    require_roles("HRDirector", "StoreManager", "Associate")
    return success_object(domain.ser_associate(domain.get_associate(aid)))


@bp.route("/associates/<aid>/manager-postings-filled", methods=["GET"])
def manager_postings_filled(aid):
    require_roles("HRDirector")
    assoc = domain.get_associate(aid)
    items = [p for p in db.postings.values() if p.get("filled_by_associate_id") == assoc["id"]]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_posting(p) for p in page], limit, offset, total)


@bp.route("/associates/<aid>", methods=["PATCH"])
def patch_associate(aid):
    require_roles("HRDirector")
    assoc = domain.get_associate(aid)
    body = get_json_body()
    updates = {}
    if "active" in body and body["active"] is not None:
        if not isinstance(body["active"], bool):
            raise invalid_request("active must be a boolean")
        updates["active"] = body["active"]
    if "home_store_id" in body and body["home_store_id"] is not None:
        if not isinstance(body["home_store_id"], str):
            raise invalid_request("home_store_id must be a string")
        domain.get_store(body["home_store_id"])
        updates["home_store_id"] = body["home_store_id"]
    for k, v in updates.items():
        assoc[k] = v
    touch(assoc)
    return success_object(domain.ser_associate(assoc))


@bp.route("/associates/<aid>/promote", methods=["POST"])
def promote_associate(aid):
    require_roles("HRDirector")
    assoc = domain.get_associate(aid)
    # Promotion gates (tier 20), boundary-inclusive as pinned.
    clock = db.clock_now()
    tenure_days = (clock.date() - assoc["hired_date"].date()).days
    if tenure_days < calc.TENURE_MIN_DAYS:
        raise unprocessable(ERR_PROMOTION_INELIGIBLE, "Tenure below %d days" % calc.TENURE_MIN_DAYS)
    future_shifts = sum(
        1 for s in db.shifts.values()
        if s["associate_id"] == assoc["id"]
        and s["status"] == "SCHEDULED"
    )
    if future_shifts < calc.SHIFT_MIN_ACTIVE:
        raise unprocessable(ERR_PROMOTION_INELIGIBLE, "Fewer than %d active future shifts" % calc.SHIFT_MIN_ACTIVE)
    if assoc["promotion_count"] >= calc.MAX_PROMOTIONS:
        raise unprocessable(ERR_PROMOTION_INELIGIBLE, "Promotion count at maximum")
    if assoc["current_level"] == "MANAGER":
        raise unprocessable(ERR_PROMOTION_INELIGIBLE, "MANAGER is terminal")
    if assoc["current_level"] == "SHIFT_LEAD":
        # MANAGER is never reachable via /promote — only via posting close.
        # Promoting a SHIFT_LEAD is a no-op success.
        return success_object(domain.ser_associate(assoc))
    idx = calc.LADDER_ORDER.index(assoc["current_level"])
    new_level = calc.LADDER_ORDER[idx + 1]
    assoc["current_level"] = new_level
    assoc["hourly_wage_cents"] = calc.wage_for_level(new_level)
    assoc["promotion_count"] += 1
    touch(assoc)
    return success_object(domain.ser_associate(assoc))
