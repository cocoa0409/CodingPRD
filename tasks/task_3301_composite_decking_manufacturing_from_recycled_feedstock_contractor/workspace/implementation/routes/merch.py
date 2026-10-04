"""Merchandising: sample kits and color chip requests."""
from flask import Blueprint, request

import db as dbmod
from errors import (raise_err, ERR_INVALID_STATE, ERR_KIT_STILL_CURRENT,
                    ERR_CHIP_STOCK_SHORT)
from middleware import require_roles
from services.lookup import get_path, get_body_ref
from util import body, ok_object, ok_list, req_int, req_str, new_resource, touch

bp = Blueprint("merch", __name__)

KIT_TYPES = ("DISPLAY_BOARD", "CHIP_SET")


# ---------- Sample kits ----------

@bp.post("/decking/sample-kits")
@require_roles("DealerSalesRep")
def create_kit():
    data = body()
    dealer = get_body_ref("dealers", data.get("dealer_id"), "dealer_id")
    line = get_body_ref("product_lines", data.get("product_line_id"), "product_line_id")
    kt = req_str(data, "kit_type")
    if kt not in KIT_TYPES:
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, f"kit_type must be one of {KIT_TYPES}")
    k = new_resource({
        "dealer_id": dealer["id"],
        "product_line_id": line["id"],
        "kit_type": kt,
        "status": "ORDERED",
    })
    dbmod.db.sample_kits[k["id"]] = k
    return ok_object(dict(k), status=201)


@bp.get("/decking/sample-kits/<kid>")
@require_roles("DealerSalesRep", "ChannelManager")
def get_kit(kid):
    return ok_object(dict(get_path("sample_kits", kid)))


@bp.get("/decking/sample-kits")
@require_roles("DealerSalesRep", "ChannelManager", "Dealer")
def list_kits():
    items = list(dbmod.db.sample_kits.values())
    for f in ("product_line_id", "dealer_id", "status"):
        v = request.args.get(f)
        if v:
            items = [k for k in items if str(k.get(f)) == v]
    return ok_list([dict(k) for k in items])


@bp.get("/decking/dealers/<did>/sample-kits")
@require_roles("DealerSalesRep", "ChannelManager", "Dealer")
def dealer_kits(did):
    get_path("dealers", did)
    items = [k for k in dbmod.db.sample_kits.values() if k["dealer_id"] == did]
    return ok_list([dict(k) for k in items])


@bp.post("/decking/sample-kits/<kid>/deliver")
@require_roles("DealerSalesRep")
def deliver_kit(kid):
    k = get_path("sample_kits", kid)
    if k["status"] != "ORDERED":
        raise_err(ERR_INVALID_STATE, f"kit is {k['status']}")
    k["status"] = "DELIVERED"
    touch(k)
    return ok_object(dict(k))


@bp.post("/decking/sample-kits/<kid>/retire")
@require_roles("DealerSalesRep")
def retire_kit(kid):
    k = get_path("sample_kits", kid)
    if k["status"] != "DELIVERED":
        raise_err(ERR_INVALID_STATE, f"kit is {k['status']}")
    line = dbmod.db.product_lines[k["product_line_id"]]
    line_not_current = line["status"] in ("DISCONTINUED", "REPAIRED_SUPPORTED", "SUNSET")
    superseded = any(
        other["id"] != k["id"] and other["product_line_id"] == k["product_line_id"]
        and other["created_at"] > k["created_at"]
        for other in dbmod.db.sample_kits.values())
    if not (line_not_current or superseded):
        raise_err(ERR_KIT_STILL_CURRENT,
                  "kit retire blocked while line is current and no superseding kit exists")
    k["status"] = "RETIRED"
    touch(k)
    return ok_object(dict(k))


# ---------- Color chip requests ----------

@bp.post("/decking/color-chip-requests")
@require_roles("Dealer", "DealerSalesRep")
def create_chip_request():
    data = body()
    dealer = get_body_ref("dealers", data.get("dealer_id"), "dealer_id")
    line = get_body_ref("product_lines", data.get("product_line_id"), "product_line_id")
    qty = req_int(data, "quantity", minimum=1)
    r = new_resource({
        "dealer_id": dealer["id"],
        "product_line_id": line["id"],
        "quantity": qty,
        "status": "REQUESTED",
        "chip_run_id": None,
    })
    dbmod.db.color_chip_requests[r["id"]] = r
    return ok_object(dict(r), status=201)


@bp.get("/decking/color-chip-requests/<rid>")
@require_roles("Dealer", "DealerSalesRep", "OpsManager")
def get_chip_request(rid):
    return ok_object(dict(get_path("color_chip_requests", rid)))


@bp.get("/decking/color-chip-requests")
@require_roles("Dealer", "DealerSalesRep", "OpsManager")
def list_chip_requests():
    items = list(dbmod.db.color_chip_requests.values())
    for f in ("product_line_id", "dealer_id", "chip_run_id", "status"):
        v = request.args.get(f)
        if v:
            items = [r for r in items if str(r.get(f)) == v]
    return ok_list([dict(r) for r in items])


@bp.get("/decking/dealers/<did>/color-chip-requests")
@require_roles("Dealer", "DealerSalesRep")
def dealer_chip_requests(did):
    get_path("dealers", did)
    items = [r for r in dbmod.db.color_chip_requests.values() if r["dealer_id"] == did]
    return ok_list([dict(r) for r in items])


@bp.post("/decking/color-chip-requests/<rid>/fulfill")
@require_roles("OpsManager")
def fulfill_chip_request(rid):
    r = get_path("color_chip_requests", rid)
    if r["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, f"chip request is {r['status']}")
    need_lf = r["quantity"] * 2
    # find completed SUPPORT_STOCK runs for the line whose support lot has enough lf
    runs = [run for run in dbmod.db.production_runs.values()
            if run["product_line_id"] == r["product_line_id"]
            and run["run_kind"] == "SUPPORT_STOCK" and run["status"] == "COMPLETED"]
    runs.sort(key=lambda run: (run["created_at"], run["id"]))
    chosen_run = None
    chosen_lot = None
    for run in runs:
        lot = dbmod.db.board_lots.get(run.get("board_lot_id") or "")
        if lot and lot["disposition"] == "AVAILABLE" and lot["lf"] >= need_lf:
            chosen_run = run
            chosen_lot = lot
            break
    if chosen_run is None:
        raise_err(ERR_CHIP_STOCK_SHORT, "chip fulfilment without sufficient support-stock production")
    chosen_lot["lf"] -= need_lf
    if chosen_lot["lf"] <= 0:
        chosen_lot["disposition"] = "SCRAPPED"
    touch(chosen_lot)
    r["chip_run_id"] = chosen_run["id"]
    r["status"] = "FULFILLED"
    touch(r)
    return ok_object(dict(r))


@bp.post("/decking/color-chip-requests/<rid>/cancel")
@require_roles("DealerSalesRep")
def cancel_chip_request(rid):
    r = get_path("color_chip_requests", rid)
    if r["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, f"chip request is {r['status']}")
    r["status"] = "CANCELLED"
    touch(r)
    return ok_object(dict(r))
