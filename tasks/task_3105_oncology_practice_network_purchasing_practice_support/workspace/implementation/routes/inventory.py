"""Inventory lots, quarantine, release, expiry and the consumption reads."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers
from services import shortage as shortage_service
from services.helpers import as_dt
from utils import utc_now_dt

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "NetworkAnalyst",
    "PlatformAdmin",
]


@route("GET", "/networks/inventory-lots", roles=READ_ROLES)
def list_lots(ctx):
    rows = filtered(
        db.all_records("inventory_lots"),
        ctx,
        {
            "practice_id": "practice_id",
            "drug_product_id": "drug_product_id",
            "purchase_order_id": "purchase_order_id",
            "status": "status",
        },
    )
    return paginate(ctx, rows)


@route("GET", "/networks/inventory-lots/{lotId}", roles=READ_ROLES)
def get_lot(ctx):
    return serial(helpers.lot_or_404(ctx.path_id("lotId")))


@route("GET", "/networks/inventory-lots/{lotId}/consumptions", roles=READ_ROLES)
def lot_consumptions(ctx):
    lot = helpers.lot_or_404(ctx.path_id("lotId"))
    return paginate(ctx, db.where("lot_consumptions", inventory_lot_id=lot["id"]))


@route("GET", "/networks/lot-consumptions", roles=READ_ROLES)
def list_consumptions(ctx):
    rows = filtered(
        db.all_records("lot_consumptions"),
        ctx,
        {"treatment_id": "treatment_id", "inventory_lot_id": "inventory_lot_id"},
    )
    return paginate(ctx, rows)


@route("GET", "/networks/lot-consumptions/{consumptionId}", roles=READ_ROLES)
def get_consumption(ctx):
    rec = db.get("lot_consumptions", ctx.path_id("consumptionId"))
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return serial(rec)


@route("POST", "/networks/inventory-lots/{lotId}/quarantine", roles=["PracticeAdmin"], write=True)
def quarantine_lot(ctx):
    lot = helpers.lot_or_404(ctx.path_id("lotId"))
    helpers.may_edit_practice(ctx.principal, lot.get("practice_id"))
    if lot["status"] != "AVAILABLE":
        raise ApiError("ERR_LOT_NOT_AVAILABLE")
    shortage = shortage_service.live_shortage_for_product(lot["drug_product_id"])
    if shortage is not None and shortage["status"] == "ACTIVE":
        raise ApiError("ERR_LOT_QUARANTINE_BLOCKED_BY_SHORTAGE")
    lot["status"] = "QUARANTINED"
    db.touch(lot)
    return serial(lot)


@route("POST", "/networks/inventory-lots/{lotId}/release", roles=["PracticeAdmin"], write=True)
def release_lot(ctx):
    lot = helpers.lot_or_404(ctx.path_id("lotId"))
    helpers.may_edit_practice(ctx.principal, lot.get("practice_id"))
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_LOT_NOT_QUARANTINED")
    from utils import parse_iso

    expires = parse_iso(lot.get("expires_at"))
    if expires is not None and expires <= utc_now_dt():
        raise ApiError("ERR_LOT_EXPIRED")
    lot["status"] = "AVAILABLE"
    db.touch(lot)
    return serial(lot)


@route(
    "POST",
    "/networks/inventory-lots/{lotId}/read-expiry",
    roles=["PracticeAdmin", "NetworkAdmin"],
    write=True,
)
def read_expiry(ctx):
    lot = helpers.lot_or_404(ctx.path_id("lotId"))
    helpers.may_edit_practice(ctx.principal, lot.get("practice_id"))
    as_of = as_dt(ctx.body, "as_of", default=None) or utc_now_dt()
    from utils import parse_iso

    expires = parse_iso(lot.get("expires_at"))
    if expires is not None and expires <= as_of:
        lot["status"] = "EXPIRED"
        db.touch(lot)
    return serial(lot)