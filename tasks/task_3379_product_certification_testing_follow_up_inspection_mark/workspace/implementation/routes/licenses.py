"""Mark license and label batch endpoints (PRD 3.7)."""
from flask import Blueprint

import db
from constants import LABEL_TYPES, ROLE_REP
from errors import (
    ApiError, ERR_ALREADY_TERMINAL, ERR_INVALID_LABEL_QUANTITY,
    ERR_LABEL_QUOTA_EXCEEDED, ERR_LICENSE_NOT_ACTIVE, ERR_NOT_FOUND,
)
from middleware import any_authenticated, check_rep_ownership, require_roles
from response import paginated_list, success
from routes.certifications import get_certification_or_404
from services import calc
from validation import body, req_enum, req_int, req_str

bp = Blueprint("licenses", __name__)


def get_license_or_404(license_id):
    lic = db.mark_licenses.get(license_id)
    if lic is None:
        raise ApiError(ERR_NOT_FOUND, "mark license not found")
    return lic


def get_batch_or_404(batch_id):
    batch = db.label_batches.get(batch_id)
    if batch is None:
        raise ApiError(ERR_NOT_FOUND, "label batch not found")
    return batch


def _license_manufacturer_id(lic):
    return db.certifications[lic["certification_id"]]["manufacturer_id"]


@bp.post("/certifications/<certification_id>/mark-licenses")
@require_roles(ROLE_REP)
def create_mark_license(certification_id, user_id, role):
    cert = get_certification_or_404(certification_id)
    check_rep_ownership(user_id, role, cert["manufacturer_id"])
    payload = body(required=True)
    label_type = req_enum(payload, "label_type", LABEL_TYPES)
    declared_annual_volume = req_int(payload, "declared_annual_volume", minimum=0)

    factory = db.factories[cert["factory_id"]]
    quota_variant = ("PROBATION_QUOTA" if factory["conformity_regime"] == "PROBATION"
                     else "STANDARD_QUOTA")
    authorized_quantity = calc.quota_for(quota_variant, declared_annual_volume)

    lic = db.new_entity(db.mark_licenses, {
        "certification_id": certification_id,
        "label_type": label_type,
        "declared_annual_volume": declared_annual_volume,
        "quota_variant": quota_variant,
        "authorized_quantity": authorized_quantity,
        "used_quantity": 0,
        "next_serial": 1,
        "serial_prefix": "%s-%s" % (cert["listing_number"], label_type[0]),
        "status": "ACTIVE",
    })
    return success(lic, status=201)


@bp.get("/certifications/<certification_id>/mark-licenses")
@any_authenticated
def list_mark_licenses(certification_id, user_id, role):
    get_certification_or_404(certification_id)
    items = [l for l in db.sorted_items(db.mark_licenses)
             if l["certification_id"] == certification_id]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


@bp.get("/mark-licenses/<license_id>")
@any_authenticated
def get_mark_license(license_id, user_id, role):
    return success(get_license_or_404(license_id))


@bp.post("/mark-licenses/<license_id>/label-batches")
@require_roles(ROLE_REP)
def issue_label_batch(license_id, user_id, role):
    lic = get_license_or_404(license_id)
    check_rep_ownership(user_id, role, _license_manufacturer_id(lic))
    payload = body(required=True)
    quantity = req_int(payload, "quantity")

    if lic["status"] != "ACTIVE":
        raise ApiError(ERR_LICENSE_NOT_ACTIVE,
                       "license is %s; issuance requires ACTIVE" % lic["status"])
    if quantity < 1:
        raise ApiError(ERR_INVALID_LABEL_QUANTITY, "quantity must be >= 1")
    remaining = lic["authorized_quantity"] - lic["used_quantity"]
    if quantity > remaining:
        raise ApiError(ERR_LABEL_QUOTA_EXCEEDED,
                       "quantity exceeds the remaining quota")

    serial_start = lic["next_serial"]
    batch = db.new_entity(db.label_batches, {
        "license_id": license_id,
        "quantity": quantity,
        "serial_start": serial_start,
        "serial_end": serial_start + quantity - 1,
        "status": "ISSUED",
    })
    lic["next_serial"] += quantity
    lic["used_quantity"] += quantity
    if lic["used_quantity"] == lic["authorized_quantity"]:
        lic["status"] = "EXHAUSTED"
    db.mutate(lic)
    return success(batch, status=201)


@bp.get("/mark-licenses/<license_id>/label-batches")
@any_authenticated
def list_label_batches(license_id, user_id, role):
    get_license_or_404(license_id)
    items = [b for b in db.sorted_items(db.label_batches)
             if b["license_id"] == license_id]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


@bp.post("/label-batches/<batch_id>/void")
@require_roles(ROLE_REP)
def void_label_batch(batch_id, user_id, role):
    batch = get_batch_or_404(batch_id)
    lic = db.mark_licenses[batch["license_id"]]
    check_rep_ownership(user_id, role, _license_manufacturer_id(lic))
    payload = body(required=True)
    req_str(payload, "reason")

    if batch["status"] == "VOIDED":
        raise ApiError(ERR_ALREADY_TERMINAL, "label batch is already VOIDED")

    batch["status"] = "VOIDED"
    db.mutate(batch)

    lic["used_quantity"] -= batch["quantity"]  # serials are never rewound
    if lic["status"] == "EXHAUSTED":
        lic["status"] = "ACTIVE"
    db.mutate(lic)
    return success(batch)
