"""Component catalog, warranty registrations, registration components."""
from flask import Blueprint

from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_CERTIFICATION_NOT_ACTIVE,
    ERR_MISSING_REQUIRED_COMPONENT, ERR_DUPLICATE_COMPONENT_TYPE,
    ERR_CATALOG_ITEM_NOT_FOUND, ERR_OWNERSHIP_MISMATCH, not_found,
)
from middleware import require_roles
from response import success, list_response
from services.helpers import (
    body_json, require_fields, require_string, require_enum, require_nonneg_int,
    parse_date, stamp_common, touch, clock_date,
)
from services.cascades import lazy_expire_certifications

bp = Blueprint("registrations", __name__)

COMPONENT_TYPES = ("SHINGLE", "UNDERLAYMENT", "STARTER", "RIDGE_CAP", "VENTILATION", "OTHER")
MANUFACTURERS = ("GAF", "OTHER")
REQUIRED_TYPES = ("SHINGLE", "UNDERLAYMENT", "STARTER", "RIDGE_CAP")


@bp.post("/program/component-catalog-items")
def create_catalog_item():
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["sku", "component_type", "manufacturer"])
    sku = require_string(data, "sku")
    component_type = require_enum(data, "component_type", COMPONENT_TYPES)
    manufacturer = require_enum(data, "manufacturer", MANUFACTURERS)
    with db.lock:
        if sku in db.catalog_by_sku:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Duplicate sku: {sku}")
        item = stamp_common({
            "sku": sku,
            "component_type": component_type,
            "manufacturer": manufacturer,
        })
        db.catalog_items[item["id"]] = item
        db.catalog_by_sku[sku] = item
    return success(item, status=201)


def _get_cert(cid):
    lazy_expire_certifications(db)
    cert = db.certifications.get(cid)
    if cert is None:
        raise not_found("Certification")
    return cert


def _get_registration(rid):
    reg = db.registrations.get(rid)
    if reg is None:
        raise not_found("WarrantyRegistration")
    return reg


@bp.post("/program/warranty-registrations")
def create_registration():
    user_id, role = require_roles("Contractor")
    data = body_json()
    require_fields(data, ["certification_id", "homeowner_name",
                          "property_postal_code", "install_date"])
    certification_id = require_string(data, "certification_id")
    homeowner_name = require_string(data, "homeowner_name")
    postal = require_string(data, "property_postal_code")
    install_date = require_string(data, "install_date")
    install_d = parse_date(install_date)
    with db.lock:
        cert = _get_cert(certification_id)
        if cert["contractor_id"] != user_id:
            raise ApiError(ERR_OWNERSHIP_MISMATCH, 403,
                           "Certification does not belong to caller")
        today = clock_date(db)
        if install_d > today:
            raise ApiError(ERR_INVALID_REQUEST, 400, "install_date is in the future")
        from datetime import date
        if cert["status"] != "ACTIVE" or install_d > date.fromisoformat(cert["valid_until"]):
            raise ApiError(ERR_CERTIFICATION_NOT_ACTIVE, 409,
                           "Certification not ACTIVE or install_date outside validity")
        reg = stamp_common({
            "certification_id": certification_id,
            "homeowner_name": homeowner_name,
            "property_postal_code": postal,
            "install_date": install_date,
            "activated_at": None,
            "coverage_tier": None,
            "coverage_class": "DRAFT",
            "status": "DRAFT",
        })
        db.registrations[reg["id"]] = reg
    return success(reg, status=201)


@bp.get("/program/warranty-registrations/<rid>")
def get_registration(rid):
    require_roles("ProgramAdmin", "Contractor", "Claimant")
    with db.lock:
        reg = _get_registration(rid)
    return success(reg)


@bp.post("/program/warranty-registrations/<rid>/activate")
def activate_registration(rid):
    require_roles("ProgramAdmin")
    with db.lock:
        reg = _get_registration(rid)
        if reg["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409, "Registration is not DRAFT")
        cert = _get_cert(reg["certification_id"])
        today = clock_date(db)
        from datetime import date
        install_d = date.fromisoformat(reg["install_date"])
        if cert["status"] != "ACTIVE" or install_d > date.fromisoformat(cert["valid_until"]):
            raise ApiError(ERR_CERTIFICATION_NOT_ACTIVE, 409,
                           "Certification not ACTIVE or install_date outside validity")
        if install_d > today:
            raise ApiError(ERR_INVALID_REQUEST, 400, "install_date is in the future")
        lines = [c for c in db.components.values() if c["registration_id"] == reg["id"]]
        counts = {}
        for line in lines:
            counts[line["component_type"]] = counts.get(line["component_type"], 0) + 1
        for rt in REQUIRED_TYPES:
            if counts.get(rt, 0) != 1:
                raise ApiError(ERR_MISSING_REQUIRED_COMPONENT, 422,
                               f"Required component type {rt} must be present exactly once")
        qualifying = all(
            line["manufacturer"] == "GAF"
            for line in lines if line["component_type"] in REQUIRED_TYPES
        )
        from services.helpers import parse_clock, format_clock
        reg["activated_at"] = db.clock
        reg["coverage_tier"] = cert["tier"]
        reg["coverage_class"] = "QUALIFYING_SYSTEM" if qualifying else "MIXED_MANUFACTURER"
        reg["status"] = "ACTIVE"
        touch(reg)
    return success(reg)


@bp.get("/program/warranty-registrations/<rid>/components")
def list_registration_components(rid):
    require_roles("ProgramAdmin", "Contractor")
    with db.lock:
        reg = _get_registration(rid)
        rows = sorted(
            (c for c in db.components.values() if c["registration_id"] == reg["id"]),
            key=lambda x: x["created_at"],
        )
    return list_response(rows, len(rows), len(rows), 0)


@bp.get("/program/warranty-registrations/<rid>/claims")
def list_registration_claims(rid):
    require_roles("ProgramAdmin", "Contractor", "Claimant")
    with db.lock:
        reg = _get_registration(rid)
        rows = sorted(
            (c for c in db.claims.values() if c["registration_id"] == reg["id"]),
            key=lambda x: x["created_at"],
        )
    return list_response(rows, len(rows), len(rows), 0)


@bp.post("/program/registration-components")
def create_component():
    user_id, role = require_roles("Contractor")
    data = body_json()
    require_fields(data, ["registration_id", "catalog_sku", "material_cost_cents"])
    registration_id = require_string(data, "registration_id")
    catalog_sku = require_string(data, "catalog_sku")
    material_cost = require_nonneg_int(data, "material_cost_cents")
    with db.lock:
        reg = _get_registration(registration_id)
        cert = db.certifications.get(reg["certification_id"])
        if cert is None or cert["contractor_id"] != user_id:
            raise ApiError(ERR_OWNERSHIP_MISMATCH, 403,
                           "Registration does not belong to caller")
        if reg["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409, "Registration is not DRAFT")
        item = db.catalog_by_sku.get(catalog_sku)
        if item is None:
            raise ApiError(ERR_CATALOG_ITEM_NOT_FOUND, 404, "Catalog item not found")
        for existing in db.components.values():
            if (existing["registration_id"] == reg["id"]
                    and existing["component_type"] == item["component_type"]):
                raise ApiError(ERR_DUPLICATE_COMPONENT_TYPE, 409,
                               "Duplicate component_type on registration")
        comp = stamp_common({
            "registration_id": reg["id"],
            "catalog_sku": catalog_sku,
            "component_type": item["component_type"],
            "manufacturer": item["manufacturer"],
            "material_cost_cents": material_cost,
        })
        db.components[comp["id"]] = comp
    return success(comp, status=201)
