"""Distributor and Territory endpoints (PRD SS3.1)."""
from flask import Blueprint, request

import store
from domain import cancel_open_visits, cancel_order, lazy_territory, touch
from errors import fail
from serializers import ser_distributor, ser_territory
from store import db
from util import (ALL_ROLES, auth, body, list_response, new_id, ok, opt_enum,
                  opt_int, req_int, req_str, sort_std)

bp = Blueprint("network", __name__)

DISTRIBUTOR_TIERS = {"STANDARD", "PREFERRED", "ELITE"}


def _get_distributor(did):
    d = db["distributors"].get(did)
    if d is None:
        fail("ERR_NOT_FOUND", 404, "distributor not found")
    return d


def _get_territory(tid):
    t = db["territories"].get(tid)
    if t is None:
        fail("ERR_NOT_FOUND", 404, "territory not found")
    return t


# ---------------------------------------------------------------------------
# distributors
# ---------------------------------------------------------------------------

@bp.post("/api/distributors")
def create_distributor():
    auth("BrandAdmin")
    b = body()
    code = req_str(b, "code")
    name = req_str(b, "name")
    tier = opt_enum(b, "service_level_tier", DISTRIBUTOR_TIERS, "STANDARD")
    for d in db["distributors"].values():
        if d["code"] == code:
            fail("ERR_DUPLICATE_CODE", 409, "distributor code already in use")
    now = store.now()
    d = {
        "id": new_id(), "_seq": store.next_seq(), "code": code, "name": name,
        "status": "PROSPECT", "service_level_tier": tier,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["distributors"][d["id"]] = d
    return ok(ser_distributor(d), 201)


@bp.get("/api/distributors")
def list_distributors():
    auth(*ALL_ROLES)
    items = sort_std(db["distributors"].values())
    status = request.args.get("status")
    tier = request.args.get("service_level_tier")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if tier is not None:
        items = [d for d in items if d["service_level_tier"] == tier]
    return list_response([ser_distributor(d) for d in items])


@bp.get("/api/distributors/<did>")
def get_distributor(did):
    auth(*ALL_ROLES)
    return ok(ser_distributor(_get_distributor(did)))


@bp.post("/api/distributors/<did>/suspend")
def suspend_distributor(did):
    auth("BrandAdmin")
    d = _get_distributor(did)
    if d["status"] == "TERMINATED":
        fail("ERR_ALREADY_TERMINAL", 409, "distributor is terminated")
    if d["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409, "distributor is not ACTIVE")
    d["status"] = "SUSPENDED"
    touch(d)
    # cascade: cancel this distributor's SCHEDULED / REWORK service visits
    cancel_open_visits(d["id"])
    return ok(ser_distributor(d))


@bp.post("/api/distributors/<did>/reinstate")
def reinstate_distributor(did):
    auth("BrandAdmin")
    d = _get_distributor(did)
    if d["status"] == "TERMINATED":
        fail("ERR_ALREADY_TERMINAL", 409, "distributor is terminated")
    if d["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", 409, "distributor is not SUSPENDED")
    d["status"] = "ACTIVE"
    touch(d)
    return ok(ser_distributor(d))


@bp.post("/api/distributors/<did>/terminate")
def terminate_distributor(did):
    auth("BrandAdmin")
    d = _get_distributor(did)
    if d["status"] == "TERMINATED":
        fail("ERR_ALREADY_TERMINAL", 409, "distributor is terminated")
    if d["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", 409, "only ACTIVE or SUSPENDED distributors can be terminated")
    from_suspended = d["status"] == "SUSPENDED"
    now = store.now()
    # revoke every territory currently GRANTED to this distributor
    for t in db["territories"].values():
        lazy_territory(t)
        if t["status"] == "GRANTED" and t["granted_distributor_id"] == d["id"]:
            t["status"] = "REVOKED"
            t["granted_distributor_id"] = None
            t["revoked_at"] = now
            touch(t)
    # cancel every open order, releasing allocated lot units (FEFO-reverse)
    for o in db["orders"].values():
        if (o["distributor_id"] == d["id"]
                and o["allocation_status"] in ("PENDING", "ALLOCATED", "PARTIAL", "SHORTED")
                and o["fulfillment_status"] == "UNSHIPPED"):
            cancel_order(o)
    # termination from SUSPENDED additionally cancels open service visits
    if from_suspended:
        cancel_open_visits(d["id"])
    d["status"] = "TERMINATED"
    touch(d)
    return ok(ser_distributor(d))


# ---------------------------------------------------------------------------
# territories
# ---------------------------------------------------------------------------

@bp.post("/api/territories")
def create_territory():
    auth("BrandAdmin")
    b = body()
    code = req_str(b, "code")
    name = req_str(b, "name")
    region = req_str(b, "region")
    min_visits = opt_int(b, "min_weekly_visits_per_account", 1)
    for t in db["territories"].values():
        if t["code"] == code:
            fail("ERR_DUPLICATE_CODE", 409, "territory code already in use")
    now = store.now()
    t = {
        "id": new_id(), "_seq": store.next_seq(), "code": code, "name": name,
        "region": region, "status": "OPEN", "granted_distributor_id": None,
        "granted_at": None, "revoked_at": None,
        "min_weekly_visits_per_account": min_visits,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["territories"][t["id"]] = t
    return ok(ser_territory(t), 201)


@bp.get("/api/territories")
def list_territories():
    auth(*ALL_ROLES)
    items = sort_std(db["territories"].values())
    for t in items:
        lazy_territory(t)
    status = request.args.get("status")
    granted = request.args.get("granted_distributor_id")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if granted is not None:
        items = [t for t in items if t["granted_distributor_id"] == granted]
    return list_response([ser_territory(t) for t in items])


@bp.get("/api/territories/<tid>")
def get_territory(tid):
    auth(*ALL_ROLES)
    return ok(ser_territory(_get_territory(tid)))


@bp.post("/api/territories/<tid>/grant")
def grant_territory(tid):
    auth("BrandAdmin")
    b = body()
    distributor_id = req_str(b, "distributor_id")
    expected = req_int(b, "expected_territory_version")
    t = _get_territory(tid)
    lazy_territory(t)
    dist = db["distributors"].get(distributor_id)
    if dist is None:
        fail("ERR_NOT_FOUND", 404, "distributor not found")
    # state legality: effectively OPEN (post-cooling-off) or GRANTED (supersede)
    if t["status"] not in ("OPEN", "GRANTED"):
        fail("ERR_INVALID_STATE", 409, "territory is not open for grant")
    # optimistic concurrency (PRD SS2.6)
    if expected != t["version"]:
        fail("ERR_STALE_VERSION", 412,
             "expected_territory_version does not match the territory's current version")
    now = store.now()
    t["status"] = "GRANTED"
    t["granted_distributor_id"] = distributor_id
    t["granted_at"] = now
    t["revoked_at"] = None
    touch(t)
    # a first grant flips a PROSPECT distributor to ACTIVE
    if dist["status"] == "PROSPECT":
        dist["status"] = "ACTIVE"
        touch(dist)
    return ok(ser_territory(t))


@bp.post("/api/territories/<tid>/revoke")
def revoke_territory(tid):
    auth("BrandAdmin")
    t = _get_territory(tid)
    lazy_territory(t)
    if t["status"] != "GRANTED":
        fail("ERR_INVALID_STATE", 409, "territory is not GRANTED")
    t["status"] = "REVOKED"
    t["granted_distributor_id"] = None
    t["revoked_at"] = store.now()
    touch(t)
    return ok(ser_territory(t))
