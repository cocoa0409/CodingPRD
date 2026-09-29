"""Merchant partners (PRD 3.1, 3.8)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import response
import support
import validate
from errors import ApiError

bp = Blueprint("merchants", __name__)


@bp.post("/perks/merchants")
def create_merchant():
    auth.require(auth.PARTNER_MANAGER)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "legal_name", "type": "str", "required": True,
         "min_len": 1, "max_len": 200},
        {"name": "contact_email", "type": "str", "required": True, "contains": "@"},
        {"name": "primary_category", "type": "enum", "required": True,
         "values": validate.CATEGORIES},
        {"name": "region_codes", "type": "enum_list", "required": True,
         "values": validate.REGIONS, "min_len": 1, "unique": True},
    ])
    row = db.insert(db.merchants, {
        "legal_name": data["legal_name"],
        "contact_email": data["contact_email"],
        "primary_category": data["primary_category"],
        "region_codes": data["region_codes"],
        "status": "PROSPECT",
        "fault_event_count": 0,
        "suspended_at": None,
        "last_fault_at": None,
        "terminated_reason": None,
    })
    return response.created(derive.merchant_json(row))


@bp.get("/perks/merchants/<row_id>")
def get_merchant(row_id):
    principal = auth.require(auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN, auth.MERCHANT)
    if principal.is_merchant and row_id != principal.user_id:
        auth.deny_scope()
    row = support.fetch("merchants", row_id)
    return response.ok(derive.merchant_json(row))


@bp.get("/perks/merchants")
def list_merchants():
    auth.require(auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN)
    status = support.arg("status")
    category = support.arg("primary_category")
    region = support.arg("region_code")
    rows = []
    for row in db.merchants.values():
        if not support.matches(row, "status", status):
            continue
        if not support.matches(row, "primary_category", category):
            continue
        # region_code matches on MEMBERSHIP of region_codes, not on equality.
        if region is not None and region not in row["region_codes"]:
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.merchant_json)


@bp.patch("/perks/merchants/<row_id>")
def update_merchant(row_id):
    auth.require(auth.PARTNER_MANAGER)
    row = support.fetch("merchants", row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "contact_email", "type": "str", "contains": "@"},
        {"name": "region_codes", "type": "enum_list",
         "values": validate.REGIONS, "min_len": 1, "unique": True},
    ])
    if data["contact_email"] is not None:
        row["contact_email"] = data["contact_email"]
    if data["region_codes"] is not None:
        # Shrinking the footprint never retro-invalidates agreements or offers.
        row["region_codes"] = data["region_codes"]
    db.touch(row)
    return response.ok(derive.merchant_json(row))


@bp.post("/perks/merchants/<row_id>/reinstate")
def reinstate_merchant(row_id):
    auth.require(auth.PLATFORM_ADMIN)
    row = support.fetch("merchants", row_id)
    if row["status"] != "SUSPENDED":
        raise ApiError("ERR_MERCHANT_INVALID_STATE",
                       "Only a SUSPENDED partner can be reinstated.")
    if derive.merchant_failure_score(row["id"]) >= calc.MERCHANT_SUSPEND_SCORE:
        raise ApiError("ERR_MERCHANT_SCORE_NOT_DECAYED",
                       "The fulfilment failure score has not decayed below 40.")
    row["status"] = "ACTIVE"
    row["suspended_at"] = None
    db.touch(row)
    return response.ok(derive.merchant_json(row))


@bp.post("/perks/merchants/<row_id>/terminate")
def terminate_merchant(row_id):
    auth.require(auth.PLATFORM_ADMIN)
    row = support.fetch("merchants", row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "terminated_reason", "type": "str", "required": True},
    ])
    if row["status"] == "TERMINATED":
        raise ApiError("ERR_MERCHANT_INVALID_STATE",
                       "The partner is already TERMINATED.")
    cascade.terminate_merchant(row, data["terminated_reason"])
    return response.ok(derive.merchant_json(row))
