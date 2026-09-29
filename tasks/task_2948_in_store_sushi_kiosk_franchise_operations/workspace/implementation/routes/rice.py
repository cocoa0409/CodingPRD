"""Sushi rice: acidification, TTC verification and the HACCP variance -- PRD 3.5."""

from flask import Blueprint

import db
from core import (LOCK, dec, iso_instant, logical_now_iso, parse_instant,
                  whole_minutes_between)
from errors import ApiError
from middleware import (ROLE_FRANCHISE_CHEF, ROLE_FRANCHISOR_OPS,
                        ROLE_QUALITY_AUDITOR, authorize, body, current_user_id,
                        req_enum, req_instant, req_int, req_num, req_str,
                        strictly_ordered)
from response import created, ok
from routes.base import (batch_or_404, chef_or_404, fk_lookup, filters, paginate,
                         plan_or_404)
from services import calc, domain

bp = Blueprint("rice", __name__)


def _scope_batch(actor, batch):
    if not actor.is_chef:
        return
    chef = db.chefs.get(actor.user_id)
    kiosk = domain.kiosk_of_batch(batch)
    if chef is None or kiosk is None or chef["assigned_kiosk_id"] != kiosk["id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


@bp.post("/rice-batches")
def start_batch():
    actor = authorize(ROLE_FRANCHISE_CHEF)
    payload = body()
    plan = fk_lookup(payload, "production_plan_id", plan_or_404)
    mixing_chef = fk_lookup(payload, "chef_id", chef_or_404)
    if plan is not None:
        acting = db.chefs.get(actor.user_id)
        if acting is None or acting["assigned_kiosk_id"] != plan["kiosk_id"]:
            raise ApiError("ERR_OWNERSHIP_MISMATCH")

    req_str(payload, "production_plan_id")
    req_str(payload, "chef_id")
    rice_kg = req_num(payload, "rice_kg", exclusive_minimum=0)
    vinegar_liters = req_num(payload, "vinegar_liters", exclusive_minimum=0)
    hold_start_at = req_instant(payload, "hold_start_at")
    hold_end_at = req_instant(payload, "hold_end_at")
    strictly_ordered("hold_start_at", hold_start_at, "hold_end_at", hold_end_at)

    with LOCK:
        if plan["status"] != "RELEASED":
            raise ApiError("ERR_PLAN_INVALID_STATE")
        if mixing_chef["status"] != "CERTIFIED":
            raise ApiError("ERR_CHEF_NOT_CERTIFIED")

        # Half-open hold windows; touching endpoints do not overlap.
        for other in domain.batches_of_kiosk(plan["kiosk_id"]):
            if other["status"] == "REJECTED":
                continue
            other_start = parse_instant(other["hold_start_at"])
            other_end = parse_instant(other["hold_end_at"])
            if hold_start_at < other_end and other_start < hold_end_at:
                raise ApiError("ERR_ACIDIFICATION_WINDOW_OVERLAP")

        row = db.new_row(db.rice_batches, {
            "production_plan_id": plan["id"],
            "chef_id": mixing_chef["id"],
            "rice_kg": float(rice_kg),
            "vinegar_liters": float(vinegar_liters),
            "hold_start_at": iso_instant(hold_start_at),
            "hold_end_at": iso_instant(hold_end_at),
            "status": "MIXING",
            "measured_ph": None,
            "ph_measured_at": None,
            "max_temp_c": None,
            "exposure_minutes": None,
            "max_pack_yield": calc.rice_yield_ceiling(rice_kg),
            "documented_ph": None,
            "documented_hold_minutes": None,
            "corrective_narrative": None,
            "variance_submitted_by_chef_id": None,
            "variance_reviewed_by_user_id": None,
            "rejection_reason": None,
        })
    return created(db.public(row))


@bp.get("/rice-batches/<batch_id>")
def get_batch(batch_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    batch = batch_or_404(batch_id)
    _scope_batch(actor, batch)
    return ok(db.public(batch))


@bp.get("/rice-batches")
def list_batches():
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    rows = list(db.rice_batches.values())
    if actor.is_chef:
        chef = db.chefs.get(actor.user_id)
        assigned = chef["assigned_kiosk_id"] if chef else None
        rows = [b for b in rows
                if (domain.kiosk_of_batch(b) or {}).get("id") == assigned]
    rows = filters(rows, {
        "production_plan_id": "production_plan_id",
        "chef_id": "chef_id",
        "variance_submitted_by_chef_id": "variance_submitted_by_chef_id",
        "status": "status",
    })
    return paginate(rows)


@bp.post("/rice-batches/<batch_id>/acidification-reading")
def acidification_reading(batch_id):
    actor = authorize(ROLE_FRANCHISE_CHEF)
    batch = batch_or_404(batch_id)
    _scope_batch(actor, batch)
    payload = body()
    measured_ph = req_num(payload, "measured_ph")
    ph_measured_at = req_instant(payload, "ph_measured_at")
    max_temp_c = req_num(payload, "max_temp_c")
    with LOCK:
        if batch["status"] != "MIXING":
            raise ApiError("ERR_RICE_BATCH_INVALID_STATE")
        batch["measured_ph"] = float(measured_ph)
        batch["ph_measured_at"] = iso_instant(ph_measured_at)
        batch["max_temp_c"] = float(max_temp_c)
        batch["status"] = "ACIDIFYING"
        db.touch(batch)
    return ok(db.public(batch))


@bp.post("/rice-batches/<batch_id>/verify-ttc")
def verify_ttc(batch_id):
    actor = authorize(ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    batch = batch_or_404(batch_id)
    _scope_batch(actor, batch)
    with LOCK:
        if batch["status"] != "ACIDIFYING":
            raise ApiError("ERR_RICE_BATCH_INVALID_STATE")
        exposure = whole_minutes_between(parse_instant(batch["hold_start_at"]),
                                         parse_instant(batch["hold_end_at"]))
        disposition = calc.rice_acidification_disposition(
            batch["measured_ph"], exposure, batch["max_temp_c"])
        batch["exposure_minutes"] = exposure
        batch["status"] = disposition
        if disposition == "REJECTED":
            batch["rejection_reason"] = "TTC_HARD_FAIL"
        db.touch(batch)
    return ok(db.public(batch))


@bp.post("/rice-batches/<batch_id>/variance-request")
def variance_request(batch_id):
    actor = authorize(ROLE_FRANCHISE_CHEF)
    batch = batch_or_404(batch_id)
    _scope_batch(actor, batch)
    payload = body()
    documented_ph = req_num(payload, "documented_ph")
    documented_hold_minutes = req_int(payload, "documented_hold_minutes", minimum=0)
    corrective_narrative = req_str(payload, "corrective_narrative")
    with LOCK:
        if batch["status"] != "VARIANCE_REQUIRED":
            raise ApiError("ERR_RICE_BATCH_INVALID_STATE")
        filing_chef = db.chefs.get(actor.user_id)
        expiry = filing_chef["haccp_cert_expires_at"] if filing_chef else None
        if expiry is None or expiry <= logical_now_iso():
            raise ApiError("ERR_HACCP_CERT_EXPIRED")
        batch["documented_ph"] = float(documented_ph)
        batch["documented_hold_minutes"] = documented_hold_minutes
        batch["corrective_narrative"] = corrective_narrative
        batch["variance_submitted_by_chef_id"] = filing_chef["id"]
        batch["status"] = "VARIANCE_PENDING"
        db.touch(batch)
    return ok(db.public(batch))


@bp.post("/rice-batches/<batch_id>/variance-decision")
def variance_decision(batch_id):
    authorize(ROLE_QUALITY_AUDITOR)
    batch = batch_or_404(batch_id)
    payload = body()
    decision = req_enum(payload, "decision", ("APPROVE", "REJECT"))
    req_str(payload, "review_note")
    with LOCK:
        if batch["status"] != "VARIANCE_PENDING":
            raise ApiError("ERR_RICE_BATCH_INVALID_STATE")
        if decision == "APPROVE":
            if (dec(batch["documented_ph"]) > calc.PH_DOCUMENTABLE_CEILING
                    or int(batch["documented_hold_minutes"])
                    > calc.EXPOSURE_PASS_MINUTES):
                raise ApiError("ERR_VARIANCE_PH_ABOVE_CEILING")
            batch["status"] = "VARIANCE_APPROVED"
            batch["_variance_approved"] = True
        else:
            batch["status"] = "REJECTED"
            batch["rejection_reason"] = "VARIANCE_DENIED"
        batch["variance_reviewed_by_user_id"] = current_user_id()
        db.touch(batch)
        kiosk = domain.kiosk_of_batch(batch)
        if kiosk is not None:
            domain.rederive_kiosk(kiosk)
    return ok(db.public(batch))


@bp.post("/rice-batches/<batch_id>/revoke-variance")
def revoke_variance(batch_id):
    authorize(ROLE_QUALITY_AUDITOR)
    batch = batch_or_404(batch_id)
    payload = body()
    req_str(payload, "revocation_rationale")
    with LOCK:
        if batch["status"] != "CONSUMED" or batch["documented_ph"] is None:
            raise ApiError("ERR_RICE_BATCH_INVALID_STATE")
        batch["status"] = "REJECTED"
        batch["rejection_reason"] = "VARIANCE_REVOKED"
        batch["_variance_approved"] = False
        db.touch(batch)
        for lot in domain.pack_lots_of_batch(batch["id"]):
            if lot["status"] in domain.LIVE_PACK_STATES:
                domain.discard_pack_lot(lot, "VARIANCE_REJECTED")
        kiosk = domain.kiosk_of_batch(batch)
        if kiosk is not None:
            domain.rederive_kiosk(kiosk)
    return ok(db.public(batch))
