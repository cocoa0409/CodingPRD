"""Kiosks, their two independent state dimensions and the risk summary -- PRD 3.3."""

from flask import Blueprint

import db
from core import LOCK, dec, floor_int, logical_now_iso
from errors import ApiError
from middleware import (ROLE_FRANCHISE_CHEF, ROLE_FRANCHISOR_OPS,
                        ROLE_HOST_STORE_MANAGER, ROLE_QUALITY_AUDITOR, authorize,
                        body, own_kiosk, req_date, req_int, req_num, req_str)
from response import created, ok
from routes.base import (agreement_or_404, chef_or_404, fk_lookup, filters,
                         kiosk_or_404, paginate)
from services import calc, domain

bp = Blueprint("kiosks", __name__)


@bp.post("/kiosks")
def provision_kiosk():
    authorize(ROLE_FRANCHISOR_OPS)
    payload = body()
    agreement = fk_lookup(payload, "license_agreement_id", agreement_or_404)
    agreement_id = req_str(payload, "license_agreement_id")
    kiosk_code = req_str(payload, "kiosk_code")
    footprint = req_int(payload, "case_footprint_sqft", exclusive_minimum=0)

    with LOCK:
        for existing in db.kiosks.values():
            if (existing["license_agreement_id"] == agreement_id
                    and existing["kiosk_code"] == kiosk_code):
                raise ApiError("ERR_INVALID_REQUEST",
                               "kiosk_code must be unique within the agreement.")
        row = db.new_row(db.kiosks, {
            "license_agreement_id": agreement_id,
            "kiosk_code": kiosk_code,
            "case_footprint_sqft": footprint,
            "lead_chef_id": None,
            "operational_state": "PROVISIONING",
            "sanitation_posture": "CLEAR",
            "daily_pack_cap": 0,
            "certified_chef_count": 0,
            "risk_points": 0,
            "open_critical_finding_count": 0,
            "consecutive_clean_audits": 0,
            "commissioned_on": None,
            "suspension_reason": None,
        })
    return created(db.public(row))


@bp.get("/kiosks/<kiosk_id>")
def get_kiosk(kiosk_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    own_kiosk(actor, kiosk_id)
    kiosk = kiosk_or_404(kiosk_id)
    if actor.is_manager:
        store = domain.store_of_kiosk(kiosk)
        if store is None or store["id"] != actor.user_id:
            raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return ok(db.public(kiosk))


@bp.get("/kiosks")
def list_kiosks():
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_QUALITY_AUDITOR)
    rows = list(db.kiosks.values())
    if actor.is_manager:
        rows = [k for k in rows
                if (domain.store_of_kiosk(k) or {}).get("id") == actor.user_id]
    rows = filters(rows, {
        "license_agreement_id": "license_agreement_id",
        "lead_chef_id": "lead_chef_id",
        "operational_state": "operational_state",
        "sanitation_posture": "sanitation_posture",
    })
    return paginate(rows)


@bp.get("/kiosks/<kiosk_id>/risk-summary")
def risk_summary(kiosk_id):
    authorize(ROLE_FRANCHISOR_OPS, ROLE_QUALITY_AUDITOR)
    kiosk = kiosk_or_404(kiosk_id)
    breakdown = domain.risk_breakdown(kiosk)
    unresolved = breakdown.pop("unresolved_critical_count")
    forced = unresolved > 0
    breakdown["sanitation_posture"] = calc.posture_band(
        breakdown["risk_points"], unresolved)
    breakdown["posture_forced_by_critical"] = forced
    return ok(breakdown)


@bp.post("/kiosks/<kiosk_id>/commission")
def commission_kiosk(kiosk_id):
    authorize(ROLE_FRANCHISOR_OPS)
    kiosk = kiosk_or_404(kiosk_id)
    payload = body()
    body_chef = fk_lookup(payload, "lead_chef_id", chef_or_404)
    commissioned_on = req_date(payload, "commissioned_on")

    with LOCK:
        if kiosk["operational_state"] != "PROVISIONING":
            raise ApiError("ERR_KIOSK_INVALID_STATE")
        agreement = domain.agreement_of(kiosk)
        if agreement is None or agreement["status"] != "ACTIVE":
            raise ApiError("ERR_LICENSE_INVALID_STATE")
        store = domain.store_of_agreement(agreement)
        if store["pos_integration_status"] != "CONNECTED":
            raise ApiError("ERR_POS_NOT_CONNECTED")
        if store["space_compliance_state"] != "COMPLIANT":
            raise ApiError("ERR_SPACE_OBLIGATION_DEFICIENT")

        lead = body_chef if body_chef is not None else db.chefs.get(
            kiosk["lead_chef_id"] or "")
        if (lead is None or lead["status"] != "CERTIFIED"
                or lead["assigned_kiosk_id"] != kiosk["id"]):
            raise ApiError("ERR_CHEF_NOT_CERTIFIED")
        haccp = lead["haccp_cert_expires_at"]
        if haccp is None or haccp <= logical_now_iso():
            raise ApiError("ERR_HACCP_CERT_EXPIRED")

        kiosk["operational_state"] = "OPERATING"
        kiosk["lead_chef_id"] = lead["id"]
        kiosk["commissioned_on"] = commissioned_on
        kiosk["daily_pack_cap"] = floor_int(
            dec(store["refrigerated_case_linear_ft"]) * calc.PACKS_PER_LINEAR_FT)
        db.touch(kiosk)
        domain.refresh_certified_chef_count(kiosk)
        domain.rederive_kiosk(kiosk)
        domain.refresh_active_kiosk_count(agreement)
    return ok(db.public(kiosk))


@bp.post("/kiosks/<kiosk_id>/suspend")
def suspend_kiosk_route(kiosk_id):
    authorize(ROLE_FRANCHISOR_OPS, ROLE_QUALITY_AUDITOR)
    kiosk = kiosk_or_404(kiosk_id)
    payload = body()
    reason = req_str(payload, "suspension_reason")
    with LOCK:
        if kiosk["operational_state"] != "OPERATING":
            raise ApiError("ERR_KIOSK_INVALID_STATE")
        domain.suspend_kiosk(kiosk, reason)
    return ok(db.public(kiosk))


@bp.post("/kiosks/<kiosk_id>/reinstate")
def reinstate_kiosk(kiosk_id):
    authorize(ROLE_FRANCHISOR_OPS)
    kiosk = kiosk_or_404(kiosk_id)
    with LOCK:
        if kiosk["operational_state"] != "SUSPENDED":
            raise ApiError("ERR_KIOSK_INVALID_STATE")
        agreement = domain.agreement_of(kiosk)
        if agreement is None or agreement["status"] != "ACTIVE":
            raise ApiError("ERR_LICENSE_INVALID_STATE")
        if kiosk["sanitation_posture"] == "LOCKDOWN":
            raise ApiError("ERR_KIOSK_POSTURE_LOCKDOWN")
        if domain.kiosk_has_live_audit(kiosk["id"]):
            raise ApiError("ERR_KIOSK_INVALID_STATE")
        lead = db.chefs.get(kiosk["lead_chef_id"] or "")
        if lead is None or lead["status"] != "CERTIFIED":
            raise ApiError("ERR_CHEF_NOT_CERTIFIED")

        kiosk["operational_state"] = "OPERATING"
        kiosk["suspension_reason"] = None
        db.touch(kiosk)
        domain.refresh_certified_chef_count(kiosk)
        domain.rederive_kiosk(kiosk)
        domain.refresh_active_kiosk_count(agreement)
    return ok(db.public(kiosk))


@bp.post("/kiosks/<kiosk_id>/decommission")
def decommission_kiosk_route(kiosk_id):
    authorize(ROLE_FRANCHISOR_OPS)
    kiosk = kiosk_or_404(kiosk_id)
    payload = body()
    reason = req_str(payload, "decommission_reason")
    with LOCK:
        if kiosk["operational_state"] not in ("PROVISIONING", "OPERATING",
                                              "SUSPENDED"):
            raise ApiError("ERR_KIOSK_INVALID_STATE")
        if domain.live_packs_of_kiosk(kiosk["id"]) > 0:
            raise ApiError("ERR_KIOSK_INVALID_STATE")
        domain.decommission_kiosk(kiosk, reason)
    return ok(db.public(kiosk))
