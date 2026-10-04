"""Tickets: issuance with compare-at substantiation, and voiding."""
import math
from flask import Blueprint, request

import errors as err
from errors import ApiError
from db import db
from middleware import require
from response import success, success_list
from services.calc import (
    get_body, validate_body, new_common, get_or_404, find_by, paginate,
    serialize, price_point, new_id, wall_now_iso,
)

bp = Blueprint("tickets", __name__)

TICKET_ROLES = ("PricingAnalyst", "PlanningLead", "StoreOpsLead", "AllocationManager")


@bp.post("/tickets")
def create_ticket():
    require(("PricingAnalyst",))
    vals = validate_body(get_body(required=True), {
        "lot_line_id": ("str", True),
        "zone_code": ("str", True),
        "substantiation_notes": ("str", False),
    })
    line = get_or_404("lot_lines", vals["lot_line_id"], "lot line not found")
    lot = db["lots"].get(line["lot_id"])
    zone = next((z for z in db["zones"].values() if z["zone_code"] == vals["zone_code"]), None)
    if lot is None or lot["status"] != "ACCEPTED" or zone is None:
        raise ApiError("ERR_TICKET_NOT_ISSUED",
                       "ticket issuance requires an ACCEPTED lot and an existing price zone")
    notes = vals.get("substantiation_notes", "")
    if not isinstance(notes, str):
        raise err.invalid_request("substantiation_notes must be a string")

    ticket_retail = price_point(line["target_retail_cents"] * 1.0)
    gate = math.ceil(ticket_retail * zone["compare_at_multiplier"])
    if line["compare_at_claim_cents"] >= gate:
        compare_at = line["compare_at_claim_cents"]
        omitted = False
    else:
        compare_at = None
        omitted = True
    vendor = db["vendors"].get(lot["vendor_id"])
    vendor_name = not (vendor and vendor["ticket_discretion_required"])

    ticket = {
        "id": new_id(),
        "created_at": wall_now_iso(),
        "lot_line_id": line["id"],
        "zone_code": vals["zone_code"],
        "ticket_retail_cents": ticket_retail,
        "compare_at_cents": compare_at,
        "compare_at_omitted": omitted,
        "vendor_name_on_ticket": vendor_name,
        "substantiation_notes": notes,
        "status": "ACTIVE",
    }
    db["tickets"][ticket["id"]] = ticket
    return success(serialize("ticket", ticket), status=201)


@bp.get("/tickets")
def list_tickets():
    require(TICKET_ROLES)
    filters = {k: request.args.get(k) for k in ("lot_line_id", "zone_code", "status")}
    page, limit, offset, total = paginate(list(db["tickets"].values()), filters)
    return success_list([serialize("ticket", t) for t in page], limit, offset, total)


@bp.get("/tickets/<tid>")
def get_ticket(tid):
    require(TICKET_ROLES)
    return success(serialize("ticket", get_or_404("tickets", tid)))


@bp.post("/tickets/<tid>/void")
def void_ticket(tid):
    require(("PricingAnalyst",))
    ticket = get_or_404("tickets", tid)
    get_body()
    if ticket["status"] != "ACTIVE":
        raise err.invalid_state("only an ACTIVE ticket can be voided")
    if any(s["ticket_id"] == tid and s["status"] in ("ON_FLOOR", "MARKED_DOWN", "CLEARANCE")
           for s in db["store_skus"].values()):
        raise ApiError("ERR_TICKET_IN_USE", "live store stock references this ticket")
    ticket["status"] = "VOIDED"
    return success(serialize("ticket", ticket))


@bp.get("/tickets/<tid>/store-skus")
def ticket_store_skus(tid):
    require(("PricingAnalyst", "StoreOpsLead", "PlanningLead"))
    get_or_404("tickets", tid)
    page, limit, offset, total = paginate(find_by("store_skus", "ticket_id", tid))
    return success_list([serialize("store_sku", s) for s in page], limit, offset, total)
