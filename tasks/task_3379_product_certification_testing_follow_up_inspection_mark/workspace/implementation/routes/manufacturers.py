"""Manufacturer and factory endpoints."""
from flask import Blueprint

import db
from constants import REVENUE_TIERS, ROLE_ADMIN, ROLE_COMPLIANCE
from errors import ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND
from middleware import any_authenticated, require_roles
from response import paginated_list, success
from validation import body, req_enum, req_str

bp = Blueprint("manufacturers", __name__)


def get_manufacturer_or_404(manufacturer_id):
    manufacturer = db.manufacturers.get(manufacturer_id)
    if manufacturer is None:
        raise ApiError(ERR_NOT_FOUND, "manufacturer not found")
    return manufacturer


def get_factory_or_404(factory_id):
    factory = db.factories.get(factory_id)
    if factory is None:
        raise ApiError(ERR_NOT_FOUND, "factory not found")
    return factory


@bp.post("/manufacturers")
@require_roles(ROLE_ADMIN)
def create_manufacturer(user_id, role):
    payload = body(required=True)
    manufacturer = db.new_entity(db.manufacturers, {
        "legal_name": req_str(payload, "legal_name"),
        "home_jurisdiction_code": req_str(payload, "home_jurisdiction_code"),
        "annual_revenue_tier": req_enum(payload, "annual_revenue_tier", REVENUE_TIERS),
        "status": "ACTIVE",
        "suspension_reason": None,
    })
    return success(manufacturer, status=201)


@bp.get("/manufacturers/<manufacturer_id>")
@any_authenticated
def get_manufacturer(manufacturer_id, user_id, role):
    return success(get_manufacturer_or_404(manufacturer_id))


@bp.post("/manufacturers/<manufacturer_id>/suspend")
@require_roles(ROLE_COMPLIANCE)
def suspend_manufacturer(manufacturer_id, user_id, role):
    manufacturer = get_manufacturer_or_404(manufacturer_id)
    payload = body(required=True)
    reason = req_str(payload, "reason")
    if manufacturer["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "manufacturer is not ACTIVE")
    manufacturer["status"] = "SUSPENDED"
    manufacturer["suspension_reason"] = reason
    db.mutate(manufacturer)
    return success(manufacturer)


@bp.post("/manufacturers/<manufacturer_id>/factories")
@require_roles(ROLE_ADMIN)
def create_factory(manufacturer_id, user_id, role):
    get_manufacturer_or_404(manufacturer_id)
    payload = body(required=True)
    factory = db.new_entity(db.factories, {
        "manufacturer_id": manufacturer_id,
        "site_code": req_str(payload, "site_code"),
        "country_code": req_str(payload, "country_code"),
        "jurisdiction_code": req_str(payload, "jurisdiction_code"),
        "conformity_regime": "STANDARD",
        "conformity_score": 100.0,
        "open_critical_findings": 0,
        "last_inspection_completed_on": None,
        "next_inspection_due_on": None,
    })
    return success(factory, status=201)


@bp.get("/manufacturers/<manufacturer_id>/factories")
@any_authenticated
def list_factories(manufacturer_id, user_id, role):
    get_manufacturer_or_404(manufacturer_id)
    items = [f for f in db.sorted_items(db.factories)
             if f["manufacturer_id"] == manufacturer_id]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


@bp.get("/factories/<factory_id>")
@any_authenticated
def get_factory(factory_id, user_id, role):
    return success(get_factory_or_404(factory_id))
