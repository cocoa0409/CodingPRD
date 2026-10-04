"""Consortium, library, patron routes."""
from flask import Blueprint, request
from db import stores
from timeutil import fmt_ts, parse_iso
from datetime import timedelta
from middleware import require_roles
from response import success, paginate
from engine import (
    new_id, now, touch_common, require_body, req_field, opt_field,
    get_consortium, get_library, get_patron, serialize, sync_patron_counters,
)
from errors import (
    err, ERR_NOT_FOUND, ERR_LIBRARY_NOT_FOUND, ERR_PATRON_NOT_FOUND,
    ERR_RESIDENCY_VIOLATION, ERR_CARD_EXPIRED, ERR_PATRON_NOT_ACTIVE,
    ERR_STALE_LIBRARY_VERSION, ERR_INVALID_REQUEST, ERR_FORBIDDEN,
)

bp = Blueprint("core", __name__)

INVOICE_PERIODS = ("MONTHLY", "QUARTERLY")

LIBRARY_DEFAULTS = {
    "card_validity_days": 730,
    "max_concurrent_loans": 10,
    "max_concurrent_holds": 15,
    "loan_period_days": 21,
    "renewal_period_days": 21,
    "max_renewals": 2,
    "pickup_window_hours": 72,
    "skip_the_line_loan_days": 7,
    "auto_purchase_enabled": False,
    "holds_per_copy_ratio": 4,
    "wait_target_days": 28,
    "auto_purchase_max_cents": 10000,
}


@bp.post("/lending/consortiums")
def create_consortium():
    body = require_body()
    name = req_field(body, "name", (str,))
    cpc = opt_field(body, "cpc_discount_pct", (int, float), default=0.0)
    floor = opt_field(body, "host_share_floor_pct", (int, float), default=0.25)
    period = opt_field(body, "invoice_period", (str,), enums=INVOICE_PERIODS, default="MONTHLY")
    require_roles({"ConsortiumAdmin"})
    if isinstance(cpc, bool) or isinstance(floor, bool):
        raise err(ERR_INVALID_REQUEST, "pct fields must be numeric")
    c = {
        "id": new_id(),
        "name": name,
        "cpc_discount_pct": cpc,
        "host_share_floor_pct": floor,
        "invoice_period": period,
        "status": "ACTIVE",
    }
    touch_common(c, created=True)
    c["_seq"] = len(stores["consortiums"])
    stores["consortiums"][c["id"]] = c
    return success(serialize(c), 201)


@bp.get("/lending/consortiums/<cid>")
def read_consortium(cid):
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    c = get_consortium(cid, ERR_NOT_FOUND)
    return success(serialize(c))


@bp.post("/lending/consortiums/<cid>/libraries")
def create_library(cid):
    body = require_body()
    name = req_field(body, "name", (str,))
    codes = req_field(body, "residency_region_codes", (list,))
    for code in codes:
        if not isinstance(code, str):
            raise err(ERR_INVALID_REQUEST, "residency_region_codes must be strings")
    require_roles({"ConsortiumAdmin"})
    get_consortium(cid, ERR_NOT_FOUND)
    lib = {"id": new_id(), "consortium_id": cid, "name": name,
           "residency_region_codes": list(codes), "status": "ACTIVE"}
    for k, dv in LIBRARY_DEFAULTS.items():
        v = opt_field(body, k, (bool,) if isinstance(dv, bool) else (int,), default=dv)
        lib[k] = v
    touch_common(lib, created=True)
    lib["_seq"] = len(stores["libraries"])
    stores["libraries"][lib["id"]] = lib
    return success(serialize(lib), 201)


@bp.get("/lending/consortiums/<cid>/libraries")
def list_libraries(cid):
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    get_consortium(cid, ERR_NOT_FOUND)
    items = [l for l in stores["libraries"].values() if l["consortium_id"] == cid]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, meta = paginate([serialize(l) for l in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/libraries/<lid>")
def read_library(lid):
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    lib = get_library(lid, ERR_LIBRARY_NOT_FOUND)
    return success(serialize(lib))


@bp.patch("/lending/libraries/<lid>")
def patch_library(lid):
    body = require_body()
    expected = req_field(body, "expected_library_version", (int,))
    role, uid = require_roles({"LibraryAdmin"})
    lib = get_library(lid, ERR_LIBRARY_NOT_FOUND)
    if uid != lib["id"]:
        raise err(ERR_FORBIDDEN, "LibraryAdmin may only update their own library")
    if expected != lib["version"]:
        raise err(ERR_STALE_LIBRARY_VERSION, "stale library version")
    if "name" in body:
        lib["name"] = req_field(body, "name", (str,))
    if "residency_region_codes" in body:
        codes = req_field(body, "residency_region_codes", (list,))
        for code in codes:
            if not isinstance(code, str):
                raise err(ERR_INVALID_REQUEST, "residency_region_codes must be strings")
        lib["residency_region_codes"] = list(codes)
    for k, dv in LIBRARY_DEFAULTS.items():
        if k in body:
            lib[k] = req_field(body, k, (bool,) if isinstance(dv, bool) else (int,))
    touch_common(lib)
    return success(serialize(lib))


@bp.get("/lending/libraries/<lid>/patrons")
def list_patrons(lid):
    require_roles({"LibraryAdmin", "SystemAnalyst"})
    get_library(lid, ERR_LIBRARY_NOT_FOUND)
    status = request.args.get("status")
    items = [p for p in stores["patrons"].values() if p["library_id"] == lid]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, meta = paginate([serialize(p) for p in items], request.args)
    return success(page, 200, meta)


@bp.post("/lending/libraries/<lid>/patrons")
def create_patron(lid):
    body = require_body()
    card = req_field(body, "external_card_number", (str,))
    full_name = req_field(body, "full_name", (str,))
    postal = req_field(body, "postal_code", (str,))
    role, uid = require_roles({"LibraryAdmin"})
    lib = get_library(lid, ERR_LIBRARY_NOT_FOUND)
    if uid != lib["id"]:
        raise err(ERR_FORBIDDEN, "LibraryAdmin may only register patrons at their own library")
    if postal not in lib["residency_region_codes"]:
        raise err(ERR_RESIDENCY_VIOLATION, "postal_code not in residency_region_codes")
    p = {
        "id": new_id(),
        "library_id": lid,
        "external_card_number": card,
        "full_name": full_name,
        "postal_code": postal,
        "status": "ACTIVE",
        "card_expires_at": fmt_ts(now() + timedelta(days=lib["card_validity_days"])),
        "active_loan_count": 0,
        "active_hold_count": 0,
    }
    touch_common(p, created=True)
    p["_seq"] = len(stores["patrons"])
    p["_card_expires_dt"] = parse_iso(p["card_expires_at"])
    stores["patrons"][p["id"]] = p
    return success(serialize(p), 201)


@bp.get("/lending/patrons/<pid>")
def read_patron(pid):
    role, uid = require_roles({"LibraryAdmin", "Patron", "SystemAnalyst"})
    p = get_patron(pid, ERR_PATRON_NOT_FOUND)
    if role == "Patron" and uid != p["id"]:
        raise err(ERR_FORBIDDEN, "patrons may only read their own record")
    sync_patron_counters(pid)
    return success(serialize(p))


@bp.post("/lending/patrons/<pid>/suspend")
def suspend_patron(pid):
    role, uid = require_roles({"LibraryAdmin"})
    p = get_patron(pid, ERR_PATRON_NOT_FOUND)
    if uid != p["library_id"]:
        raise err(ERR_FORBIDDEN, "LibraryAdmin may only suspend their own library's patrons")
    if p["status"] != "ACTIVE":
        raise err(ERR_PATRON_NOT_ACTIVE, "patron is not ACTIVE")
    p["status"] = "SUSPENDED"
    touch_common(p)
    sync_patron_counters(pid)
    return success(serialize(p))


@bp.post("/lending/patrons/<pid>/reinstate")
def reinstate_patron(pid):
    role, uid = require_roles({"LibraryAdmin"})
    p = get_patron(pid, ERR_PATRON_NOT_FOUND)
    if uid != p["library_id"]:
        raise err(ERR_FORBIDDEN, "LibraryAdmin may only reinstate their own library's patrons")
    if p["status"] != "SUSPENDED":
        raise err(ERR_PATRON_NOT_ACTIVE, "patron is not SUSPENDED")
    if p["_card_expires_dt"] <= now():
        raise err(ERR_CARD_EXPIRED, "card validity has lapsed")
    p["status"] = "ACTIVE"
    touch_common(p)
    sync_patron_counters(pid)
    return success(serialize(p))


@bp.get("/lending/patrons/<pid>/loans")
def list_patron_loans(pid):
    role, uid = require_roles({"LibraryAdmin", "Patron", "SystemAnalyst"})
    p = get_patron(pid, ERR_PATRON_NOT_FOUND)
    if role == "Patron" and uid != p["id"]:
        raise err(ERR_FORBIDDEN, "patrons may only list their own loans")
    status = request.args.get("status")
    items = [l for l in stores["loans"].values() if l["patron_id"] == pid]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, meta = paginate([serialize(l) for l in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/patrons/<pid>/holds")
def list_patron_holds(pid):
    role, uid = require_roles({"LibraryAdmin", "Patron", "SystemAnalyst"})
    p = get_patron(pid, ERR_PATRON_NOT_FOUND)
    if role == "Patron" and uid != p["id"]:
        raise err(ERR_FORBIDDEN, "patrons may only list their own holds")
    status = request.args.get("status")
    items = [h for h in stores["holds"].values() if h["patron_id"] == pid]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    items.sort(key=lambda h: (h["created_at"], h["_seq"]))
    page, meta = paginate([serialize(h) for h in items], request.args)
    return success(page, 200, meta)
