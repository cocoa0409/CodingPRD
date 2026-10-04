# Product families routes (PRD 3.3; scaffold Tables 2/5).
from datetime import timedelta

from flask import Blueprint, request

import authz
import calc
import clock
import constants
import envelope
import errors
import serialize
import state
import validate
from dealers import _new_entity

bp = Blueprint("families", __name__)


@bp.post("/product-families")
def create_family():
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    body = validate.body_json(request)
    family_code = validate.req_str(body, "family_code")
    name = validate.req_str(body, "name")
    category = validate.req_enum(body, "category", constants.FAMILY_CATEGORIES)
    base = validate.req_int(body, "base_lead_time_days")
    if not (1 <= base <= 365):
        errors.validation("base_lead_time_days must be in 1..365")
    for fam in state.families.values():
        if fam["family_code"] == family_code:
            errors.validation("family_code must be unique across product families")
        if fam["category"] == category:
            errors.validation("at most one family row per category")
    family = _new_entity({
        "family_code": family_code,
        "name": name,
        "category": category,
        "base_lead_time_days": base,
        "lifecycle_status": "CURRENT",
        "last_order_date": None,
        "discontinued_at": None,
        "parts_support_until": None,
    })
    state.families[family["id"]] = family
    return envelope.success_object(serialize.family(family), status=201)


@bp.patch("/product-families/<familyId>")
def update_family(familyId):
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    family = state.families.get(familyId)
    if family is None:
        errors.not_found("ERR_PRODUCT_FAMILY_NOT_FOUND",
                         "No product family with the given id")
    body = validate.body_json(request)
    # Step 5: lifecycle_status required and a valid enum member.
    target = validate.req_enum(body, "lifecycle_status", constants.LIFECYCLE_STATUSES)
    today = clock.today()
    # Step 6: field-level date windows for the requested target state.
    last_order_date = None
    parts_support_until = None
    if target == "SUNSETTING":
        raw = body.get("last_order_date")
        if raw is None:
            errors.date_window("SUNSETTING requires last_order_date")
        try:
            last_order_date = validate.parse_iso_date(raw, "last_order_date")
        except Exception:
            errors.date_window("SUNSETTING requires a valid last_order_date")
        if last_order_date < today:
            errors.date_window("last_order_date must be at or after the clock date")
    elif target == "DISCONTINUED":
        raw = body.get("parts_support_until")
        if raw is None:
            errors.date_window("DISCONTINUED requires parts_support_until")
        try:
            parts_support_until = validate.parse_iso_date(raw, "parts_support_until")
        except Exception:
            errors.date_window("DISCONTINUED requires a valid parts_support_until")
        if parts_support_until < today + timedelta(days=constants.MIN_PARTS_SUPPORT_DAYS):
            errors.date_window(
                "parts_support_until must be at least 2557 days after the clock date")
    # Step 9: lifecycle is forward-only, one step at a time (PRD 3.3).
    allowed = {"CURRENT": "SUNSETTING", "SUNSETTING": "DISCONTINUED"}
    if allowed.get(family["lifecycle_status"]) != target:
        errors.err("ERR_INVALID_LIFECYCLE_TRANSITION", 409,
                   "Lifecycle must step CURRENT -> SUNSETTING -> DISCONTINUED")
    family["lifecycle_status"] = target
    if target == "SUNSETTING":
        family["last_order_date"] = last_order_date.isoformat()
    elif target == "DISCONTINUED":
        family["discontinued_at"] = today.isoformat()
        family["parts_support_until"] = parts_support_until.isoformat()
    state.touch(family)
    return envelope.success_object(serialize.family(family))
