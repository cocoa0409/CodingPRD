"""Salvage lots (channel-priced) and disposal tickets (diversion cascade)."""
from decimal import Decimal

from flask import Blueprint, request

import errors
from clock import now
from db import store
from envelope import success
from serializers import ser_lot, ser_ticket
from services import (
    CHANNEL_CATEGORIES,
    D,
    MIN_BALE_LBS,
    disposal_cost,
    new_entity,
    new_light_entity,
    org_of_item,
    recompute_diversion,
    recompute_margin_health,
    salvage_revenue,
    touch,
)
from validate import auth, field, get_body, paginate, require_role, sort_created

bp = Blueprint("salvage", __name__)

CHANNELS = {"TEXTILE_BALE", "EWASTE", "OUTLET_BIN"}
MATERIALS = {"MIXED_UNSALABLE", "HAZARD", "FURNITURE"}


def _get_org(oid):
    org = store.member_orgs.get(oid)
    if org is None:
        errors.not_found("MemberOrg not found")
    return org


def _lot_totals(lot_id):
    members = [it for it in store.donated_items.values()
               if it["salvage_lot_id"] == lot_id]
    total = sum((D(it["weight_lbs"]) for it in members), Decimal("0"))
    return total, len(members)


@bp.post("/donated-goods/salvage-lots")
def create_lot():
    body = get_body()
    member_org_id = field(body, "member_org_id", "str", required=True)
    channel = field(body, "channel", "str", required=True, enum=CHANNELS)
    item_ids = field(body, "item_ids", "list", required=True)
    for iid in item_ids:
        if not isinstance(iid, str):
            errors.invalid_request("item_ids must be a list of strings")
    uid, role = auth()
    require_role(role, {"MemberAdmin"})
    if uid != member_org_id:
        errors.ownership_mismatch()
    org = _get_org(member_org_id)
    items = _resolve_items(item_ids)  # existence (priority 5), before gates
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if not org["diversion_compliant"]:
        errors.diversion_breach()
    _check_items_against(org["id"], channel, items)
    with store.lock:
        lot = new_entity()
        lot.update({
            "member_org_id": member_org_id,
            "channel": channel,
            "status": "OPEN",
            "total_weight_lbs": Decimal("0"),
            "item_count": 0,
            "sale_revenue_cents": None,
            "sold_at": None,
        })
        store.salvage_lots[lot["id"]] = lot
        for item in items:
            item["salvage_lot_id"] = lot["id"]
            touch(item)
        lot["total_weight_lbs"], lot["item_count"] = _lot_totals(lot["id"])
    return success(ser_lot(lot), 201)


def _resolve_items(item_ids):
    items = []
    for iid in item_ids:
        item = store.donated_items.get(iid)
        if item is None:
            errors.not_found("DonatedItem not found")
        items.append(item)
    return items


def _check_items_against(org_id, channel, items):
    for item in items:
        item_org = org_of_item(item)
        if (item["status"] != "SALVAGED" or item["salvage_lot_id"] is not None
                or item_org["id"] != org_id):
            errors.item_already_in_lot()
        if item["category"] not in CHANNEL_CATEGORIES[channel]:
            errors.item_channel_mismatch()


@bp.get("/donated-goods/member-orgs/<oid>/salvage-lots")
def list_lots(oid):
    auth()
    _get_org(oid)
    items = [l for l in store.salvage_lots.values() if l["member_org_id"] == oid]
    channel = request.args.get("channel")
    status = request.args.get("status")
    if channel is not None:
        items = [l for l in items if l["channel"] == channel]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_lot(l) for l in page], 200,
                   response_type="array", pagination=meta)


def _get_lot(lid):
    lot = store.salvage_lots.get(lid)
    if lot is None:
        errors.not_found("SalvageLot not found")
    return lot


def _owning_admin(uid, lot):
    if uid != lot["member_org_id"]:
        errors.ownership_mismatch()


@bp.post("/donated-goods/salvage-lots/<lid>/add-items")
def add_items(lid):
    body = get_body()
    item_ids = field(body, "item_ids", "list", required=True)
    for iid in item_ids:
        if not isinstance(iid, str):
            errors.invalid_request("item_ids must be a list of strings")
    uid, role = auth()
    require_role(role, {"MemberAdmin"})
    lot = _get_lot(lid)
    _owning_admin(uid, lot)
    items = _resolve_items(item_ids)
    org = _get_org(lot["member_org_id"])
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if lot["status"] != "OPEN":
        errors.invalid_state("Only an OPEN lot accepts more items")
    _check_items_against(org["id"], lot["channel"], items)
    with store.lock:
        for item in items:
            item["salvage_lot_id"] = lot["id"]
            touch(item)
        lot["total_weight_lbs"], lot["item_count"] = _lot_totals(lot["id"])
        touch(lot)
    return success(ser_lot(lot), 200)


@bp.post("/donated-goods/salvage-lots/<lid>/sell")
def sell_lot(lid):
    get_body()
    uid, role = auth()
    require_role(role, {"MemberAdmin"})
    lot = _get_lot(lid)
    _owning_admin(uid, lot)
    org = _get_org(lot["member_org_id"])
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if lot["status"] != "OPEN":
        errors.invalid_state("Only an OPEN lot can be sold")
    if (lot["channel"] == "TEXTILE_BALE"
            and lot["total_weight_lbs"] < D(MIN_BALE_LBS)):
        errors.bale_underweight()
    with store.lock:
        revenue = salvage_revenue(lot)
        lot["sale_revenue_cents"] = revenue
        lot["status"] = "SOLD"
        lot["sold_at"] = now()
        touch(lot)
        # Cascade: diverted weight -> diversion rate -> compliance; and the
        # salvage revenue joins the retail margin pool -> margin health.
        org["total_diverted_lbs"] += lot["total_weight_lbs"]
        recompute_diversion(org)
        org["retail_margin_pool_cents"] += revenue
        recompute_margin_health(org)
        touch(org)
    return success(ser_lot(lot), 200)


# ---------------------------------------------------------------------------
# Disposal tickets
# ---------------------------------------------------------------------------

@bp.post("/donated-goods/disposal-tickets")
def create_ticket():
    body = get_body()
    member_org_id = field(body, "member_org_id", "str", required=True)
    material = field(body, "material", "str", required=True, enum=MATERIALS)
    weight = field(body, "weight_lbs", "number", required=True, minval=0)
    uid, role = auth()
    require_role(role, {"MemberAdmin"})
    if uid != member_org_id:
        errors.ownership_mismatch()
    org = _get_org(member_org_id)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    with store.lock:
        ticket = new_light_entity()
        ticket.update({
            "member_org_id": member_org_id,
            "material": material,
            "weight_lbs": weight,
            "cost_cents": disposal_cost(material, weight),
        })
        store.disposal_tickets[ticket["id"]] = ticket
        # Depth-3 cascade: disposed weight -> rate -> compliance gate.
        org["total_disposed_lbs"] += D(weight)
        recompute_diversion(org)
        touch(org)
    return success(ser_ticket(ticket), 201)


@bp.get("/donated-goods/member-orgs/<oid>/disposal-tickets")
def list_tickets(oid):
    auth()
    _get_org(oid)
    items = [t for t in store.disposal_tickets.values()
             if t["member_org_id"] == oid]
    material = request.args.get("material")
    if material is not None:
        items = [t for t in items if t["material"] == material]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_ticket(t) for t in page], 200,
                   response_type="array", pagination=meta)
