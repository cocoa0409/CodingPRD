"""Kiosks, enrollment centers, ambassadors."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, body, require_field, pagination_params, paginate
from models import new_entity, touch
from response import success
from serializers import present, present_list
import services

bp = Blueprint("sites", __name__)


def _sorted(collection):
    return sorted(collection, key=lambda e: (e["created_at"], e["id"]))


# ---------------- kiosks ----------------

@bp.post("/kiosks")
@require_roles("OpsAdmin")
def create_kiosk():
    data = body()
    airport_id = require_field(data, "airport_id")
    code = require_field(data, "code")
    if store.airports.get(airport_id) is None:
        raise ApiError("ERR_AIRPORT_NOT_FOUND", 404, "Airport not found")
    for k in store.kiosks.values():
        if k["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "Kiosk code already in use")
    k = new_entity()
    k.update({
        "airport_id": airport_id,
        "code": code,
        "status": "PROVISIONING",
        "activated_at": None,
        "consecutive_capture_failures": 0,
    })
    store.kiosks[k["id"]] = k
    return success(present(k), status_code=201)


@bp.get("/kiosks")
@require_roles("OpsAdmin", "PartnerManager")
def list_kiosks():
    limit, offset = pagination_params()
    items = _sorted(store.kiosks.values())
    ap = request.args.get("airport_id")
    if ap is not None:
        items = [k for k in items if k["airport_id"] == ap]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/kiosks/<kid>")
@require_roles("OpsAdmin", "PartnerManager")
def get_kiosk(kid):
    k = store.kiosks.get(kid)
    if k is None:
        raise ApiError("ERR_KIOSK_NOT_FOUND", 404, "Kiosk not found")
    return success(present(k))


@bp.post("/kiosks/<kid>/activate")
@require_roles("OpsAdmin")
def activate_kiosk(kid):
    k = store.kiosks.get(kid)
    if k is None:
        raise ApiError("ERR_KIOSK_NOT_FOUND", 404, "Kiosk not found")
    if k["status"] not in ("PROVISIONING", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Kiosk cannot be activated from this state")
    ag = services.agreement_by_status(k["airport_id"], ("ACTIVE",))
    if ag is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409,
                       "Kiosk's airport has no ACTIVE agreement")
    k["status"] = "ACTIVE"
    from db import fmt_dt
    k["activated_at"] = fmt_dt(store.now())
    k["consecutive_capture_failures"] = 0
    touch(k)
    return success(present(k))


@bp.post("/kiosks/<kid>/suspend")
@require_roles("OpsAdmin")
def suspend_kiosk(kid):
    k = store.kiosks.get(kid)
    if k is None:
        raise ApiError("ERR_KIOSK_NOT_FOUND", 404, "Kiosk not found")
    if k["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Kiosk is not ACTIVE")
    k["status"] = "SUSPENDED"
    touch(k)
    return success(present(k))


@bp.post("/kiosks/<kid>/retire")
@require_roles("OpsAdmin")
def retire_kiosk(kid):
    k = store.kiosks.get(kid)
    if k is None:
        raise ApiError("ERR_KIOSK_NOT_FOUND", 404, "Kiosk not found")
    if k["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Kiosk is not ACTIVE or SUSPENDED")
    k["status"] = "RETIRED"
    touch(k)
    return success(present(k))


# ---------------- enrollment centers ----------------

@bp.post("/enrollment-centers")
@require_roles("OpsAdmin")
def create_center():
    data = body()
    airport_id = require_field(data, "airport_id")
    name = require_field(data, "name")
    capacity = require_field(data, "ambassador_capacity")
    if store.airports.get(airport_id) is None:
        raise ApiError("ERR_AIRPORT_NOT_FOUND", 404, "Airport not found")
    if not isinstance(capacity, int) or capacity < 1:
        raise ApiError("ERR_VALIDATION", 400, "ambassador_capacity must be >= 1")
    c = new_entity()
    c.update({
        "airport_id": airport_id,
        "name": name,
        "status": "ACTIVE",
        "ambassador_capacity": capacity,
    })
    store.enrollment_centers[c["id"]] = c
    return success(present(c), status_code=201)


@bp.get("/enrollment-centers")
@require_roles("OpsAdmin", "PartnerManager")
def list_centers():
    limit, offset = pagination_params()
    items = _sorted(store.enrollment_centers.values())
    ap = request.args.get("airport_id")
    if ap is not None:
        items = [c for c in items if c["airport_id"] == ap]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/enrollment-centers/<cid>")
@require_roles("OpsAdmin", "PartnerManager")
def get_center(cid):
    c = store.enrollment_centers.get(cid)
    if c is None:
        raise ApiError("ERR_ENROLLMENT_CENTER_NOT_FOUND", 404, "Enrollment center not found")
    return success(present(c))


# ---------------- ambassadors ----------------

@bp.post("/ambassadors")
@require_roles("OpsAdmin")
def create_ambassador():
    data = body()
    airport_id = require_field(data, "airport_id")
    display_name = require_field(data, "display_name")
    employee_ref = require_field(data, "employee_ref")
    if store.airports.get(airport_id) is None:
        raise ApiError("ERR_AIRPORT_NOT_FOUND", 404, "Airport not found")
    for a in store.ambassadors.values():
        if a["employee_ref"] == employee_ref:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "employee_ref already in use")
    a = new_entity()
    a.update({
        "airport_id": airport_id,
        "display_name": display_name,
        "employee_ref": employee_ref,
        "status": "ACTIVE",
    })
    store.ambassadors[a["id"]] = a
    return success(present(a), status_code=201)


@bp.get("/ambassadors")
@require_roles("OpsAdmin", "PartnerManager")
def list_ambassadors():
    limit, offset = pagination_params()
    items = _sorted(store.ambassadors.values())
    ap = request.args.get("airport_id")
    if ap is not None:
        items = [a for a in items if a["airport_id"] == ap]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/ambassadors/<aid>")
@require_roles("OpsAdmin", "PartnerManager")
def get_ambassador(aid):
    a = store.ambassadors.get(aid)
    if a is None:
        raise ApiError("ERR_AMBASSADOR_NOT_FOUND", 404, "Ambassador not found")
    return success(present(a))


@bp.post("/ambassadors/<aid>/suspend")
@require_roles("OpsAdmin")
def suspend_ambassador(aid):
    a = store.ambassadors.get(aid)
    if a is None:
        raise ApiError("ERR_AMBASSADOR_NOT_FOUND", 404, "Ambassador not found")
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Ambassador is not ACTIVE")
    a["status"] = "SUSPENDED"
    touch(a)
    return success(present(a))
