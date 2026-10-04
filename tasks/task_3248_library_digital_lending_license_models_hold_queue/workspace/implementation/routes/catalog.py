"""Title and license routes, plus title availability view."""
import math
from flask import Blueprint, request
from db import stores
from middleware import require_roles
from response import success, paginate
from engine import (
    new_id, touch_common, require_body, req_field, opt_field,
    get_consortium, get_library, get_title, get_license, serialize,
    effective_copies, holds_queue, license_visible_to, sync_patron_counters,
)
from errors import (
    err, ERR_NOT_FOUND, ERR_TITLE_NOT_FOUND, ERR_LIBRARY_NOT_FOUND,
    ERR_LICENSE_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_FORBIDDEN,
    ERR_LICENSE_IN_USE, ERR_PATRON_NOT_ACTIVE,
)

bp = Blueprint("catalog", __name__)

SHARING_SCOPES = ("LOCAL_ONLY", "CONSORTIUM")


@bp.post("/lending/consortiums/<cid>/titles")
def create_title(cid):
    body = require_body()
    isbn = req_field(body, "isbn", (str,))
    name = req_field(body, "name", (str,))
    author = req_field(body, "author", (str,))
    price_ocou = req_field(body, "price_ocou_cents", (int,))
    mt_price = req_field(body, "metered_time_price_cents", (int,))
    mt_days = req_field(body, "metered_time_days", (int,))
    mc_price = req_field(body, "metered_circ_price_cents", (int,))
    mc_count = req_field(body, "metered_circ_count", (int,))
    cpc_price = req_field(body, "cpc_price_per_circ_cents", (int,))
    su_price = req_field(body, "simultaneous_use_price_cents", (int,))
    su_days = req_field(body, "simultaneous_use_days", (int,))
    scope = opt_field(body, "sharing_scope", (str,), enums=SHARING_SCOPES, default="LOCAL_ONLY")
    stl = opt_field(body, "skip_the_line_enabled", (bool,), default=False)
    sua = opt_field(body, "simultaneous_use_allowed", (bool,), default=False)
    require_roles({"ConsortiumAdmin"})
    get_consortium(cid, ERR_NOT_FOUND)
    t = {
        "id": new_id(), "consortium_id": cid, "isbn": isbn, "name": name, "author": author,
        "sharing_scope": scope, "skip_the_line_enabled": stl,
        "simultaneous_use_allowed": sua,
        "price_ocou_cents": price_ocou,
        "metered_time_price_cents": mt_price, "metered_time_days": mt_days,
        "metered_circ_price_cents": mc_price, "metered_circ_count": mc_count,
        "cpc_price_per_circ_cents": cpc_price,
        "simultaneous_use_price_cents": su_price, "simultaneous_use_days": su_days,
    }
    touch_common(t, created=True)
    t["_seq"] = len(stores["titles"])
    stores["titles"][t["id"]] = t
    return success(serialize(t), 201)


@bp.get("/lending/consortiums/<cid>/titles")
def list_titles(cid):
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "Patron", "SystemAnalyst"})
    get_consortium(cid, ERR_NOT_FOUND)
    items = [t for t in stores["titles"].values() if t["consortium_id"] == cid]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    page, meta = paginate([serialize(t) for t in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/titles/<tid>")
def read_title(tid):
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "Patron", "SystemAnalyst"})
    t = get_title(tid, ERR_TITLE_NOT_FOUND)
    return success(serialize(t))


@bp.get("/lending/titles/<tid>/availability")
def title_availability(tid):
    role, uid = require_roles({"ConsortiumAdmin", "LibraryAdmin", "Patron", "SystemAnalyst"})
    t = get_title(tid, ERR_TITLE_NOT_FOUND)
    lib_id = request.args.get("library_id")
    if lib_id is None:
        if role == "Patron":
            lib_id = uid
        else:
            raise err(ERR_REFERENCE_NOT_FOUND, "library_id query parameter is required for non-patron callers")
    lib = stores["libraries"].get(lib_id)
    if lib is None:
        raise err(ERR_LIBRARY_NOT_FOUND, "library not found")
    copies_available = 0
    for lic in stores["licenses"].values():
        if lic["title_id"] != tid or lic["status"] != "ACTIVE":
            continue
        if not license_visible_to(lic, lib_id, t):
            continue
        if lic["model"] == "OCOU":
            copies_available += max(0, lic["copies_total"] - lic["copies_on_loan"] - lic["_reserved"])
    active_holds = len(holds_queue(tid))
    C = max(effective_copies(t, lib_id), 1)
    cycles = math.ceil(active_holds / C)
    opt = cycles * lib["loan_period_days"]
    pess = cycles * (lib["loan_period_days"] + lib["max_renewals"] * lib["renewal_period_days"])
    return success({
        "copies_available": copies_available,
        "active_holds": active_holds,
        "optimistic_wait_days": opt,
        "pessimistic_wait_days": pess,
    })


@bp.get("/lending/licenses")
def list_licenses():
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    items = list(stores["licenses"].values())
    for key in ("title_id", "library_id", "acquisition_order_id", "model", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [l for l in items if str(l.get(key)) == v]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, meta = paginate([serialize(l) for l in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/licenses/<lid>")
def read_license(lid):
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    lic = get_license(lid, ERR_LICENSE_NOT_FOUND)
    return success(serialize(lic))


@bp.post("/lending/licenses/<lid>/retire")
def retire_license(lid):
    role, uid = require_roles({"LibraryAdmin"})
    lic = get_license(lid, ERR_LICENSE_NOT_FOUND)
    if uid != lic["library_id"]:
        raise err(ERR_FORBIDDEN, "LibraryAdmin may only retire their own library's licenses")
    if lic["status"] != "ACTIVE":
        raise err(ERR_PATRON_NOT_ACTIVE, "license is not ACTIVE")
    for loan in stores["loans"].values():
        if loan["license_id"] == lid and loan["status"] == "ACTIVE":
            raise err(ERR_LICENSE_IN_USE, "license has ACTIVE loans")
    lic["status"] = "RETIRED"
    touch_common(lic)
    return success(serialize(lic))
