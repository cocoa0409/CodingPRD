"""Chefs, training, certifications and placement -- PRD 3.2."""

from flask import Blueprint

import db
from core import LOCK, add_days, dec, iso_instant, logical_now, parse_instant
from errors import ApiError
from middleware import (ROLE_FRANCHISE_CHEF, ROLE_FRANCHISOR_OPS,
                        ROLE_HOST_STORE_MANAGER, ROLE_QUALITY_AUDITOR, authorize,
                        body, req_bool, req_enum, req_instant, req_int, req_num,
                        req_str)
from response import created, ok
from routes.base import (certification_or_404, chef_or_404, fk_lookup, filters,
                         kiosk_or_404, paginate)
from services import calc, domain

bp = Blueprint("chefs", __name__)


@bp.post("/chefs")
def register_chef():
    authorize(ROLE_FRANCHISOR_OPS)
    payload = body()
    full_name = req_str(payload, "full_name")
    with LOCK:
        row = db.new_row(db.chefs, {
            "full_name": full_name,
            "assigned_kiosk_id": None,
            "status": "CANDIDATE",
            "training_hours_logged": 0,
            "food_handler_cert_expires_at": None,
            "haccp_cert_expires_at": None,
            "valid_cert_count": 0,
        })
    return created(db.public(row))


@bp.get("/chefs/<chef_id>")
def get_chef(chef_id):
    authorize(ROLE_FRANCHISOR_OPS, ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR,
              ROLE_HOST_STORE_MANAGER)
    return ok(db.public(chef_or_404(chef_id)))


@bp.get("/chefs")
def list_chefs():
    authorize(ROLE_FRANCHISOR_OPS, ROLE_QUALITY_AUDITOR, ROLE_HOST_STORE_MANAGER)
    rows = filters(list(db.chefs.values()), {
        "assigned_kiosk_id": "assigned_kiosk_id",
        "status": "status",
    })
    return paginate(rows)


@bp.post("/chefs/<chef_id>/training")
def log_training(chef_id):
    authorize(ROLE_FRANCHISOR_OPS)
    chef = chef_or_404(chef_id)
    payload = body()
    hours = req_num(payload, "hours", exclusive_minimum=0)
    req_str(payload, "curriculum_code")
    with LOCK:
        if chef["status"] not in ("CANDIDATE", "TRAINEE"):
            raise ApiError("ERR_CHEF_INVALID_STATE")
        total = dec(chef["training_hours_logged"]) + hours
        chef["training_hours_logged"] = float(total)
        db.touch(chef)
        # PRD 3.2 defines the status as a function of the hours and the two
        # mandatory certifications: "A chef whose `training_hours_logged` is at
        # least 24 hours **and** who holds a valid `FOOD_HANDLER` certification
        # ... **and** a valid `HACCP_RICE_ACIDIFICATION` certification ... becomes
        # `CERTIFIED`; exactly 24 hours is enough. A chef with any training hours
        # at all but not both mandatory certifications is `TRAINEE`." Logging hours
        # moves the first of those inputs, so the readiness rule is re-applied --
        # which yields the `TRAINEE -> TRAINEE` self-loop for every chef who does
        # not yet hold both certifications.
        domain.refresh_chef(chef)
    return ok(db.public(chef))


@bp.post("/chefs/<chef_id>/certifications")
def issue_certification(chef_id):
    authorize(ROLE_QUALITY_AUDITOR)
    chef = chef_or_404(chef_id)
    payload = body()
    cert_type = req_enum(payload, "cert_type", calc.CERT_TYPES)
    exam_score = req_num(payload, "exam_score", minimum=0, maximum=100)
    issued_at = req_instant(payload, "issued_at")
    valid_days = req_int(payload, "valid_days", exclusive_minimum=0)

    with LOCK:
        row = db.new_row(db.certifications, {
            "chef_id": chef["id"],
            "cert_type": cert_type,
            "exam_score": float(exam_score),
            "issued_at": iso_instant(issued_at),
            "valid_days": valid_days,
            "expires_at": iso_instant(add_days(issued_at, valid_days)),
            "status": "VALID",
            "revocation_reason": None,
        })
        domain.refresh_chef(chef)
    return created(db.public(row))


@bp.get("/chefs/<chef_id>/certifications")
def list_certifications(chef_id):
    authorize(ROLE_FRANCHISOR_OPS, ROLE_QUALITY_AUDITOR, ROLE_FRANCHISE_CHEF)
    chef = chef_or_404(chef_id)
    rows = [c for c in db.certifications.values() if c["chef_id"] == chef["id"]]
    rows = filters(rows, {"cert_type": "cert_type", "status": "status"})
    return paginate(rows)


@bp.post("/chefs/<chef_id>/certifications/<certification_id>/revoke")
def revoke_certification(chef_id, certification_id):
    authorize(ROLE_QUALITY_AUDITOR)
    chef = chef_or_404(chef_id)
    cert = certification_or_404(certification_id)
    if cert["chef_id"] != chef["id"]:
        raise ApiError("ERR_CHEF_RECORD_NOT_FOUND")
    payload = body()
    reason = req_str(payload, "revocation_reason")
    with LOCK:
        if cert["status"] != "VALID":
            raise ApiError("ERR_CERTIFICATION_INVALID_STATE")
        cert["status"] = "REVOKED"
        cert["revocation_reason"] = reason
        db.touch(cert)
        domain.refresh_chef(chef)
    return ok(db.public(cert))


@bp.post("/chefs/<chef_id>/placement")
def place_chef(chef_id):
    authorize(ROLE_FRANCHISOR_OPS)
    chef = chef_or_404(chef_id)
    payload = body()
    # PRD 3.2: "it sets the chef's `assigned_kiosk_id` to the supplied kiosk".
    # `assigned_kiosk_id` is the name the PRD spells for that kiosk reference;
    # `kiosk_id` is accepted as an equivalent spelling of the same reference.
    field = "assigned_kiosk_id" if "assigned_kiosk_id" in payload else "kiosk_id"
    kiosk = fk_lookup(payload, field, kiosk_or_404)
    kiosk_id = req_str(payload, field)
    as_lead_chef = req_bool(payload, "as_lead_chef", optional=True, default=False)

    with LOCK:
        if chef["status"] == "CANDIDATE":
            raise ApiError("ERR_CHEF_INVALID_STATE")
        chef["assigned_kiosk_id"] = kiosk_id
        db.touch(chef)
        if as_lead_chef:
            db.apply_changes(kiosk, {"lead_chef_id": chef["id"]})
        domain.refresh_certified_chef_count(kiosk)
    return ok(db.public(chef))
