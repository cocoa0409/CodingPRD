"""Stocking commitments and allocation commitments."""
from datetime import date
from flask import Blueprint, request

import db as dbmod
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_DUPLICATE_COMMITMENT)
from middleware import require_roles
from services import calcs
from services.lookup import get_path, get_body_ref
from util import body, ok_object, ok_list, req_int, req_str, new_resource, touch

bp = Blueprint("commitments", __name__)


# ---------- Stocking commitments ----------

@bp.post("/decking/stocking-commitments")
@require_roles("ChannelManager")
def create_commitment():
    data = body()
    dealer = get_body_ref("dealers", data.get("dealer_id"), "dealer_id")
    line = get_body_ref("product_lines", data.get("product_line_id"), "product_line_id")
    terr = req_str(data, "territory_code")
    committed = req_int(data, "committed_lf", minimum=1)
    year = req_int(data, "season_year")
    if terr != dealer["territory_code"]:
        raise_err(ERR_INVALID_REQUEST, "territory_code must equal the dealer's territory_code")
    for sc in dbmod.db.stocking_commitments.values():
        if sc["dealer_id"] == dealer["id"] and sc["territory_code"] == terr \
                and sc["status"] == "OPEN":
            raise_err(ERR_DUPLICATE_COMMITMENT,
                      "second OPEN stocking commitment for same (dealer, territory)")
    sc = new_resource({
        "dealer_id": dealer["id"],
        "territory_code": terr,
        "product_line_id": line["id"],
        "committed_lf": committed,
        "season_year": year,
        "fulfilled_lf": 0,
        "status": "OPEN",
    })
    dbmod.db.stocking_commitments[sc["id"]] = sc
    return ok_object(dict(sc), status=201)


@bp.get("/decking/stocking-commitments/<sid>")
@require_roles("ChannelManager", "DealerSalesRep", "Dealer")
def get_commitment(sid):
    return ok_object(dict(get_path("stocking_commitments", sid)))


@bp.get("/decking/stocking-commitments")
@require_roles("ChannelManager", "DealerSalesRep", "Dealer")
def list_commitments():
    items = list(dbmod.db.stocking_commitments.values())
    for f in ("product_line_id", "dealer_id", "status"):
        v = request.args.get(f)
        if v:
            items = [s for s in items if str(s.get(f)) == v]
    return ok_list([dict(s) for s in items])


@bp.post("/decking/stocking-commitments/<sid>/close-season")
@require_roles("ChannelManager")
def close_season(sid):
    sc = get_path("stocking_commitments", sid)
    if sc["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"commitment is {sc['status']}")
    today = dbmod.clock_date()
    earliest = date(sc["season_year"] + 1, 1, 1)
    if today < earliest:
        raise_err(ERR_INVALID_STATE, "season not yet closed")
    data = body()
    waive = data.get("waive", False)
    if not isinstance(waive, bool):
        raise_err(ERR_INVALID_REQUEST, "waive must be a boolean")
    if waive:
        sc["status"] = "WAIVED"
    else:
        if sc["fulfilled_lf"] >= sc["committed_lf"]:
            sc["status"] = "MET"
        else:
            penalty = calcs.shortfall_penalty_cents(sc)
            dealer = dbmod.db.dealers[sc["dealer_id"]]
            dealer["outstanding_cents"] += penalty
            touch(dealer)
            sc["status"] = "SHORTFALL_PENALIZED"
    touch(sc)
    return ok_object(dict(sc))


# ---------- Allocation commitments ----------

@bp.post("/decking/plants/<pid>/allocation-commitments")
@require_roles("DealerSalesRep")
def create_allocation(pid):
    plant = get_path("plants", pid)
    data = body()
    dealer = get_body_ref("dealers", data.get("dealer_id"), "dealer_id")
    line = get_body_ref("product_lines", data.get("product_line_id"), "product_line_id")
    pb = get_body_ref("price_books", data.get("price_book_id"), "price_book_id")
    reserved = req_int(data, "reserved_lf", minimum=1)
    if "expected_plant_version" not in data or data["expected_plant_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "expected_plant_version is required")
    epv = data["expected_plant_version"]
    if isinstance(epv, bool) or not isinstance(epv, int):
        raise_err(ERR_INVALID_REQUEST, "expected_plant_version must be an integer")
    if epv != plant["version"]:
        raise_err(ERR_STALE_VERSION, "expected_plant_version does not match current plant version")
    ac = new_resource({
        "plant_id": plant["id"],
        "dealer_id": dealer["id"],
        "product_line_id": line["id"],
        "reserved_lf": reserved,
        "remaining_lf": reserved,
        "price_book_id": pb["id"],
        "status": "OPEN",
    })
    dbmod.db.allocation_commitments[ac["id"]] = ac
    plant["reserved_fg_store"][line["id"]] = plant["reserved_fg_store"].get(line["id"], 0) + reserved
    touch(plant)
    return ok_object(dict(ac), status=201)


@bp.get("/decking/allocation-commitments/<aid>")
@require_roles("DealerSalesRep", "ChannelManager", "OpsManager")
def get_allocation(aid):
    return ok_object(dict(get_path("allocation_commitments", aid)))


@bp.get("/decking/plants/<pid>/allocation-commitments")
@require_roles("DealerSalesRep", "ChannelManager", "OpsManager")
def list_plant_allocations(pid):
    get_path("plants", pid)
    items = [a for a in dbmod.db.allocation_commitments.values() if a.get("plant_id") == pid]
    v = request.args.get("status")
    if v:
        items = [a for a in items if a["status"] == v]
    return ok_list([dict(a) for a in items])


@bp.get("/decking/allocation-commitments")
@require_roles("DealerSalesRep", "ChannelManager", "OpsManager")
def list_allocations():
    items = list(dbmod.db.allocation_commitments.values())
    for f in ("dealer_id", "product_line_id", "price_book_id", "status"):
        v = request.args.get(f)
        if v:
            items = [a for a in items if str(a.get(f)) == v]
    return ok_list([dict(a) for a in items])


@bp.post("/decking/allocation-commitments/<aid>/release")
@require_roles("DealerSalesRep")
def release_allocation(aid):
    ac = get_path("allocation_commitments", aid)
    if ac["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"allocation commitment is {ac['status']}")
    plant = dbmod.db.plants.get(ac.get("plant_id"))
    if plant is not None:
        line = ac["product_line_id"]
        remaining = ac.get("remaining_lf", ac["reserved_lf"])
        plant["reserved_fg_store"][line] = max(
            0, plant["reserved_fg_store"].get(line, 0) - remaining)
        ac["remaining_lf"] = 0
        touch(plant)
    ac["status"] = "RELEASED"
    touch(ac)
    return ok_object(dict(ac))
