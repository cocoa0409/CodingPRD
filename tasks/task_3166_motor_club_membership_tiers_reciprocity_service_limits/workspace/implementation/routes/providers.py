"""Service providers and truck part stock."""

from flask import Blueprint, request

from db import DB, new_id, stamp_new, touch
from errors import (
    not_found, invalid_request, business, ERR_CLUB_SUSPENDED, ERR_PROVIDER_BUSY,
)
from middleware import require_auth
from response import ok_obj
from routes._common import list_response
from services.calculations import NON_TERMINAL_DISPATCH_STATES
from services.serialize import public
from services.validate import (
    body_json, req_string, req_list, req_number, req_int, opt_enum,
)

bp = Blueprint("providers", __name__)

PROVIDER_READ = {"ClubAdmin", "Dispatcher", "ProviderOps"}
STOCK_RW = {"ClubAdmin", "ProviderOps"}
SERVICE_TYPES = {"TOW", "BATTERY", "LOCKOUT", "TIRE", "FUEL", "WINCH"}
PART_KINDS = {"BATTERY", "TIRE", "FUEL_CAN", "LOCKSMITH_KIT"}


def _get_provider(providerId):
    p = DB.providers.get(providerId)
    if p is None:
        raise not_found("provider not found")
    return p


def _get_stock(stockId):
    s = DB.truck_part_stock.get(stockId)
    if s is None:
        raise not_found("truck part stock not found")
    return s


# -------------------------------------------------------------- providers ---

@bp.post("/motor-club/providers")
def create_provider():
    require_auth({"ClubAdmin"})
    data = body_json()
    servicing_club_id = req_string(data, "servicing_club_id")
    name = req_string(data, "name")
    kind = data.get("provider_kind")
    if kind not in {"OWNED", "CONTRACTED"}:
        raise invalid_request("provider_kind must be OWNED or CONTRACTED")
    capabilities = req_list(data, "capabilities", item_type=str)
    for c in capabilities:
        if c not in SERVICE_TYPES:
            raise invalid_request("capabilities contains an unknown service type")
    home_base_state_code = req_string(data, "home_base_state_code")
    sla = req_number(data, "sla_multiplier", min_value=0.5, max_value=3.0)
    shift_start = req_int(data, "shift_start_minute", min_value=0, max_value=1439)
    shift_end = req_int(data, "shift_end_minute", min_value=0, max_value=1439)
    max_conc = req_int(data, "max_concurrent_dispatches", min_value=1)
    club = DB.clubs.get(servicing_club_id)
    if club is None:
        raise not_found("servicing club not found")
    provider = {
        "id": new_id(),
        "servicing_club_id": servicing_club_id,
        "name": name,
        "provider_kind": kind,
        "capabilities": capabilities,
        "home_base_state_code": home_base_state_code,
        "sla_multiplier": sla,
        "shift_start_minute": shift_start,
        "shift_end_minute": shift_end,
        "max_concurrent_dispatches": max_conc,
        "status": "ACTIVE",
    }
    stamp_new(provider)
    DB.providers[provider["id"]] = provider
    return ok_obj(public(provider), 201)


@bp.get("/motor-club/providers")
def list_providers():
    require_auth(PROVIDER_READ)
    sc = request.args.get("servicing_club_id")
    status = request.args.get("status")

    def filt(p):
        if sc is not None and p["servicing_club_id"] != sc:
            return False
        if status is not None and p["status"] != status:
            return False
        return True

    return list_response(list(DB.providers.values()), filt)


@bp.get("/motor-club/providers/<providerId>")
def get_provider(providerId):
    require_auth(PROVIDER_READ)
    return ok_obj(public(_get_provider(providerId)))


@bp.put("/motor-club/providers/<providerId>")
def update_provider(providerId):
    require_auth({"ClubAdmin"})
    p = _get_provider(providerId)
    data = body_json()
    if "name" in data and data["name"] is not None:
        if not isinstance(data["name"], str) or not data["name"]:
            raise invalid_request("name must be a non-empty string")
        p["name"] = data["name"]
    if "capabilities" in data and data["capabilities"] is not None:
        v = data["capabilities"]
        if not isinstance(v, list) or any(c not in SERVICE_TYPES for c in v):
            raise invalid_request("capabilities must be an array of service types")
        p["capabilities"] = v
    if "sla_multiplier" in data and data["sla_multiplier"] is not None:
        v = data["sla_multiplier"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0.5 or v > 3.0:
            raise invalid_request("sla_multiplier must be between 0.5 and 3.0")
        p["sla_multiplier"] = v
    for f in ("shift_start_minute", "shift_end_minute"):
        if f in data and data[f] is not None:
            v = data[f]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 1439:
                raise invalid_request(f"{f} must be between 0 and 1439")
            p[f] = v
    if "max_concurrent_dispatches" in data and data["max_concurrent_dispatches"] is not None:
        v = data["max_concurrent_dispatches"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise invalid_request("max_concurrent_dispatches must be an integer >= 1")
        p["max_concurrent_dispatches"] = v
    if "status" in data and data["status"] is not None:
        v = data["status"]
        if v not in {"ACTIVE", "SUSPENDED"}:
            raise invalid_request("status must be ACTIVE or SUSPENDED")
        if v == "SUSPENDED" and p["status"] == "ACTIVE":
            for d in DB.dispatches.values():
                if d["provider_id"] == p["id"] and d["status"] in NON_TERMINAL_DISPATCH_STATES:
                    raise business(ERR_PROVIDER_BUSY,
                                   "provider has non-terminal dispatches")
        if v == "ACTIVE" and p["status"] == "SUSPENDED":
            club = DB.clubs.get(p["servicing_club_id"])
            if club is None or club["status"] != "ACTIVE":
                raise business(ERR_CLUB_SUSPENDED,
                               "provider's servicing club is not ACTIVE")
        p["status"] = v
    touch(p)
    return ok_obj(public(p))


# ------------------------------------------------------------ part stock ---

@bp.get("/motor-club/providers/<pid>/truckPartStocks")
def list_stock_of_provider(pid):
    require_auth(STOCK_RW)
    _get_provider(pid)
    rows = [s for s in DB.truck_part_stock.values() if s["provider_id"] == pid]
    return list_response(rows)


@bp.post("/motor-club/providers/<providerId>/part-stock")
def create_part_stock(providerId):
    require_auth(STOCK_RW)
    _get_provider(providerId)
    data = body_json()
    part_sku = req_string(data, "part_sku")
    part_kind = data.get("part_kind")
    if part_kind not in PART_KINDS:
        raise invalid_request("part_kind must be BATTERY, TIRE, FUEL_CAN or LOCKSMITH_KIT")
    qty = req_int(data, "quantity_on_hand", min_value=0)
    reorder = data.get("reorder_level", 0)
    if isinstance(reorder, bool) or not isinstance(reorder, int) or reorder < 0:
        raise invalid_request("reorder_level must be an integer >= 0")
    for s in DB.truck_part_stock.values():
        if s["provider_id"] == providerId and s["part_sku"] == part_sku:
            raise invalid_request("part_sku must be unique per provider")
    stock = {
        "id": new_id(),
        "provider_id": providerId,
        "part_sku": part_sku,
        "part_kind": part_kind,
        "quantity_on_hand": qty,
        "reorder_level": reorder,
    }
    stamp_new(stock)
    DB.truck_part_stock[stock["id"]] = stock
    return ok_obj(public(stock), 201)


@bp.post("/motor-club/part-stock/<stockId>/restock")
def restock(stockId):
    require_auth(STOCK_RW)
    s = _get_stock(stockId)
    data = body_json()
    add = data.get("add_quantity")
    if isinstance(add, bool) or not isinstance(add, int) or add < 1:
        raise invalid_request("add_quantity must be an integer >= 1")
    s["quantity_on_hand"] += add
    touch(s)
    return ok_obj(public(s))


@bp.get("/motor-club/truck-part-stock")
def list_stock_flat():
    require_auth(STOCK_RW)
    provider_id = request.args.get("provider_id")
    part_kind = request.args.get("part_kind")

    def filt(s):
        if provider_id is not None and s["provider_id"] != provider_id:
            return False
        if part_kind is not None and s["part_kind"] != part_kind:
            return False
        return True

    return list_response(list(DB.truck_part_stock.values()), filt)
