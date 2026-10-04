"""Store routes: siting, lifecycle, opening surge."""

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_DELIVERY_FREQUENCY_VIOLATION,
    ERR_RADIUS_LIMIT_EXCEEDED,
    ERR_STORE_INVALID_STATE,
    ERR_SURGE_ALREADY_ACTIVE,
    ERR_SURGE_NOT_ACTIVE,
    ERR_OPEN_SHIFTS_EXIST,
    conflict,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    check_occ,
    get_json_body,
    paginate,
    req_field,
    req_number,
    req_string,
    touch,
)
from datetime import timedelta

bp = Blueprint("stores", __name__)


def _manager_check(manager_id):
    """Tier-12 linkage: when provided, must reference a MANAGER-level associate."""
    from errors import linkage
    assoc = domain.get_associate(manager_id)
    if assoc["current_level"] != "MANAGER":
        raise linkage("manager_associate_id must reference a MANAGER associate")
    return assoc


@bp.route("/stores", methods=["POST"])
def create_store():
    require_roles("RealEstatePlanner")
    body = get_json_body()
    # Shape (tier 6) for required string/number fields.
    commissary_id = req_string(body, "commissary_id")
    name = req_string(body, "name")
    lat = req_number(body, "lat")
    lng = req_number(body, "lng")
    manager_id = body.get("manager_associate_id")
    if manager_id is not None and not isinstance(manager_id, str):
        raise invalid_request("manager_associate_id must be a string")
    # Body FK existence (tier 5).
    commissary = domain.get_commissary(commissary_id)
    if manager_id is not None:
        _manager_check(manager_id)
    # OCC (tier 7) — mandatory on store creation.
    check_occ(body, commissary, "expected_commissary_version", "Commissary")
    # Linkage (tier 12): regional entry must be open.
    from errors import linkage
    if not commissary["regional_entry_open"]:
        raise linkage("Regional entry is not open for this commissary")
    # distance_km display value is computed at creation; the radius gate itself
    # is enforced at approval time.
    raw = calc.haversine_km(commissary["lat"], commissary["lng"], lat, lng)
    s = base_entity()
    s.update({
        "commissary_id": commissary["id"],
        "name": name,
        "lat": lat,
        "lng": lng,
        "distance_km": calc.round_half_up_3(raw),
        "opening_mode": "NORMAL",
        "surge_start_date": None,
        "surge_end_date": None,
        "manager_associate_id": manager_id,
        "status": "SITE_REVIEW",
    })
    db.stores[s["id"]] = s
    # Creation mutates the commissary.
    touch(commissary)
    return success_object(domain.ser_store(s), 201)


@bp.route("/stores", methods=["GET"])
def list_stores():
    require_roles("RealEstatePlanner", "SupplyChainDirector", "CommissaryPlanner", "HRDirector")
    items = list(db.stores.values())
    cid = request.args.get("commissary_id")
    if cid is not None:
        items = [s for s in items if s["commissary_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    mid = request.args.get("manager_associate_id")
    if mid is not None:
        items = [s for s in items if s.get("manager_associate_id") == mid]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_store(s) for s in page], limit, offset, total)


@bp.route("/stores/<sid>", methods=["GET"])
def get_store(sid):
    require_roles("RealEstatePlanner", "SupplyChainDirector", "CommissaryPlanner", "StoreManager", "HRDirector")
    return success_object(domain.ser_store(domain.get_store(sid)))


@bp.route("/stores/<sid>/approve", methods=["POST"])
def approve_store(sid):
    require_roles("RealEstatePlanner")
    store = domain.get_store(sid)
    # State (tier 8).
    if store["status"] != "SITE_REVIEW":
        raise conflict(ERR_STORE_INVALID_STATE, "Store must be SITE_REVIEW to approve")
    commissary = domain.get_commissary(store["commissary_id"])
    # Radius gate (tier 13): raw haversine, strictly less than the limit.
    raw = calc.haversine_km(commissary["lat"], commissary["lng"], store["lat"], store["lng"])
    if not calc.radius_ok(raw, commissary["radius_limit_km"]):
        raise unprocessable(ERR_RADIUS_LIMIT_EXCEEDED, "Site is outside the commissary delivery radius")
    # Manager prerequisite (tier 12): must be non-null and MANAGER level.
    from errors import linkage
    manager_id = store.get("manager_associate_id")
    if manager_id is None:
        raise linkage("manager_associate_id must be set before approval")
    assoc = db.associates.get(manager_id)
    if assoc is None or assoc["current_level"] != "MANAGER":
        raise linkage("manager_associate_id must reference a MANAGER associate")
    # Delivery-day gap projection (tier 14).
    if not calc.delivery_day_gap_projection(store, commissary):
        raise unprocessable(ERR_DELIVERY_FREQUENCY_VIOLATION, "Delivery frequency projection fails")
    store["status"] = "APPROVED"
    touch(store)
    return success_object(domain.ser_store(store))


@bp.route("/stores/<sid>/open", methods=["POST"])
def open_store(sid):
    require_roles("RealEstatePlanner")
    store = domain.get_store(sid)
    if store["status"] != "APPROVED":
        raise conflict(ERR_STORE_INVALID_STATE, "Store must be APPROVED to open")
    store["status"] = "OPEN"
    touch(store)
    return success_object(domain.ser_store(store))


@bp.route("/stores/<sid>/close", methods=["POST"])
def close_store(sid):
    require_roles("RealEstatePlanner")
    store = domain.get_store(sid)
    if store["status"] != "OPEN":
        raise conflict(ERR_STORE_INVALID_STATE, "Store must be OPEN to close")
    clock = db.clock_now()
    in_progress_shifts = any(
        s["store_id"] == store["id"]
        and s["status"] == "SCHEDULED"
        and s["shift_start"] <= clock < s["shift_end"]
        for s in db.shifts.values()
    )
    if in_progress_shifts:
        raise conflict(ERR_OPEN_SHIFTS_EXIST, "Store has an in-progress SCHEDULED shift")
    domain.store_close_cascade(store)
    store["status"] = "CLOSED"
    touch(store)
    return success_object(domain.ser_store(store))


def _require_own_store_manager(user_id, store):
    """StoreManager identity: caller must be the store's manager associate."""
    if user_id != store.get("manager_associate_id"):
        from errors import forbidden
        raise forbidden("StoreManager may only manage their own store")


@bp.route("/stores/<sid>/begin-opening-surge", methods=["POST"])
def begin_surge(sid):
    user_id, _ = require_roles("StoreManager")
    store = domain.get_store(sid)
    _require_own_store_manager(user_id, store)
    if store["status"] != "OPEN":
        raise conflict(ERR_STORE_INVALID_STATE, "Store must be OPEN to begin surge")
    if store["opening_mode"] != "NORMAL":
        raise conflict(ERR_SURGE_ALREADY_ACTIVE, "Surge already active")
    start = db.clock_now()
    store["opening_mode"] = "OPENING_SURGE"
    store["surge_start_date"] = start
    store["surge_end_date"] = start + timedelta(days=calc.SURGE_WINDOW_DAYS - 1)
    touch(store)
    return success_object(domain.ser_store(store))


@bp.route("/stores/<sid>/end-opening-surge", methods=["POST"])
def end_surge(sid):
    user_id, _ = require_roles("StoreManager")
    store = domain.get_store(sid)
    _require_own_store_manager(user_id, store)
    if store["status"] != "OPEN":
        raise conflict(ERR_STORE_INVALID_STATE, "Store must be OPEN to end surge")
    if store["opening_mode"] != "OPENING_SURGE":
        raise conflict(ERR_SURGE_NOT_ACTIVE, "Surge is not active")
    store["opening_mode"] = "NORMAL"
    store["surge_start_date"] = None
    store["surge_end_date"] = None
    touch(store)
    return success_object(domain.ser_store(store))
