"""VendorRebate routes, including the two distinct retraction paths."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware
import schemas
import services
import timeutil
from errors import fail
from response import ok
from routes.common import SHARED, list_records

bp = Blueprint("rebates", __name__)


@bp.post("/rebates")
@middleware.auth(("FranchisorAdmin",))
def create_rebate():
    payload = middleware.body(
        required=("store_id", "vendor_name", "vendor_code", "recommended_vendor",
                  "rebate_cents", "period_start", "period_end"),
    )
    store = services.require_store(payload["store_id"])
    vendor_name = middleware.string_value(payload["vendor_name"], "vendor_name")
    vendor_code = middleware.string_value(payload["vendor_code"], "vendor_code")
    if not isinstance(payload["recommended_vendor"], bool):
        fail("ERR_INVALID_REQUEST")
    rebate_cents = middleware.non_negative_int(payload["rebate_cents"], "rebate_cents")
    period_start = timeutil.required_utc(payload["period_start"])
    period_end = timeutil.required_utc(payload["period_end"])
    if period_end <= period_start:
        fail("ERR_INVALID_REQUEST")

    for existing in db.all_of("rebates"):
        if (existing["store_id"] == store["id"]
                and existing["vendor_code"] == vendor_code
                and existing["period_start"] == period_start):
            fail("ERR_VENDOR_REBATE_DUPLICATE")

    record = db.insert("rebates", {
        "store_id": store["id"],
        "vendor_name": vendor_name,
        "vendor_code": vendor_code,
        "recommended_vendor": payload["recommended_vendor"],
        "rebate_cents": rebate_cents,
        "period_start": period_start,
        "period_end": period_end,
        "flowthrough_cents": Decimal("0.00"),
        "status": "POSTED",
        "covering_settlement_id": None,
    })
    return ok(schemas.dump("rebates", record), 201)


@bp.get("/rebates")
@middleware.auth(SHARED)
def list_rebates():
    return list_records("rebates", ("store_id", "status", "recommended_vendor"))


@bp.get("/rebates/<rebate_id>")
@middleware.auth(SHARED)
def get_rebate(rebate_id):
    rebate = services.require("rebates", rebate_id)
    return ok(schemas.dump("rebates", rebate))


@bp.post("/rebates/<rebate_id>/retract")
@middleware.auth(("FranchisorAdmin",))
def retract_rebate(rebate_id):
    rebate = services.require("rebates", rebate_id)
    if rebate["status"] == "POSTED":
        if db.clock() < rebate["period_end"]:
            fail("ERR_REBATE_RETRACTION_WINDOW_CLOSED")
        rebate["status"] = "RETRACTED"
        rebate["flowthrough_cents"] = Decimal("0.00")
        db.touch(rebate)
        return ok(schemas.dump("rebates", rebate))

    if rebate["status"] == "APPLIED":
        settlement = db.get("settlements", rebate.get("covering_settlement_id"))
        if settlement is None:
            fail("ERR_RESOURCE_NOT_FOUND")
        if settlement["status"] == "FINALIZED":
            fail("ERR_SETTLEMENT_ALREADY_FINALIZED")
        rebate["status"] = "RETRACTED"
        rebate["flowthrough_cents"] = Decimal("0.00")
        db.touch(rebate)
        # Unwind the settlement's money in the pinned order.
        services.recalculate_settlement_money(settlement)
        return ok(schemas.dump("rebates", rebate))

    fail("ERR_INVALID_STATE")