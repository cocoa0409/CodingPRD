"""Warranty claim filing, adjudication and the diagnostic loop.

Claim status is a branching machine: DIAGNOSED forks to APPROVED / DENIED,
APPROVED forks to DISPATCHED (RMA) or CLOSED (write-off), and CLOSED / DENIED
loop back through REOPENED (PRD 3.6).
"""

import db
import shapes
from approval import as_enum, as_int, as_nonempty_str_optional, as_str, body
from auth import (
    ROLE_INSTALLER,
    ROLE_MONITORING,
    ROLE_PLATFORM_ADMIN,
    acting_installer_id,
    get_claim,
    get_unit,
    require,
)
from errors import fail
from respond import ok, ok_list, paginate
from services import common
from services import orders as order_service
from views import units as unit_view

CLAIM_KINDS = ("DEFECT", "UNDERPERFORMANCE", "NO_POWER", "COMMUNICATION")


def create_claim():
    """File a claim.  The OCC guard is checked alongside the four gates."""
    data = body()
    unit_id = as_str(data, "unit_id")
    installer_id = as_str(data, "installer_id")
    claim_kind = as_enum(data, "claim_kind", CLAIM_KINDS)
    remote_diagnostic_ref = as_str(data, "remote_diagnostic_ref")
    expected_unit_version = as_int(data, "expected_unit_version")

    unit = db.DB.units.get(unit_id)
    if unit is None:
        fail("ERR_RESOURCE_NOT_FOUND", "unit %s does not exist" % unit_id)
    installer = db.DB.installers.get(installer_id)
    if installer is None:
        fail("ERR_RESOURCE_NOT_FOUND", "installer %s does not exist" % installer_id)

    # The version guard is the fiscal-tier check, so it is evaluated after the
    # business-tier gates: ownership, certification, safety and referential
    # rules all pre-empt it (PRD 2.5 ordering).
    unit_view.claim_filing_gates(unit, installer)

    if expected_unit_version != int(unit.get("version", 0)):
        fail("ERR_STALE_UNIT_VERSION")

    claim = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "updated_at": common.now_iso(),
        "version": 1,
        "unit_id": unit_id,
        "installer_id": installer_id,
        "claim_kind": claim_kind,
        "remote_diagnostic_ref": remote_diagnostic_ref,
        "status": "DRAFT",
        "installer_level_at_claim": None,
        "system_age_months_at_claim": None,
        "diagnostic_source": "REMOTE",
        "labor_eligible": False,
        "approved_labor_hours": None,
        "denial_reason": None,
        "reopen_count": 0,
        "diagnostic_evidence_ref": None,
    }
    db.DB.claims[claim["id"]] = claim

    # A successful unit-scoped write bumps the unit's version by one.
    common.set_many(unit, {"version": int(unit.get("version", 0)) + 1})
    common.recompute_installer(installer)
    return ok(shapes.warranty_claim(claim), 201)


def list_claims():
    from flask import request

    installer_id = request.args.get("installer_id")
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")

    rows = list(db.DB.claims.values())
    if installer_id:
        rows = [c for c in rows if c.get("installer_id") == installer_id]
    if unit_id:
        rows = [c for c in rows if c.get("unit_id") == unit_id]
    if status:
        rows = [c for c in rows if c.get("status") == status]
    rows = db.by_created_at(rows)
    window, meta = paginate(rows, request.args)
    return ok_list([shapes.warranty_claim(c) for c in window], pagination=meta)


def read_claim(claim_id):
    claim = get_claim(claim_id)
    return ok(shapes.warranty_claim(claim))


def submit_claim(claim_id):
    claim = get_claim(claim_id)
    if claim.get("status") != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT claim can be submitted")

    acting = acting_installer_id()
    if acting != claim.get("installer_id"):
        fail("ERR_NOT_CLAIM_OWNER")

    installer = db.DB.installers.get(claim.get("installer_id"))
    if installer is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    common.require_active_certification(installer)

    unit = get_unit(claim["unit_id"])
    common.recompute_unit(unit)
    if not unit.get("rma_eligible"):
        fail("ERR_INVALID_STATE", "the unit is not rma_eligible")
    if not (claim.get("remote_diagnostic_ref") or "").strip():
        fail("ERR_INVALID_REQUEST_BODY", "remote_diagnostic_ref must be non-empty")

    system = db.DB.systems.get(unit.get("system_id"))
    values = {
        "status": "SUBMITTED",
        "installer_level_at_claim": installer.get("certification_level"),
    }
    if system is not None:
        values["system_age_months_at_claim"] = common.system_age_months(system, common.now())
    common.set_many(claim, values)
    common.recompute_installer(installer)
    return ok(shapes.warranty_claim(claim))


def diagnose_claim(claim_id):
    data = body()
    diagnostic_evidence_ref = as_nonempty_str_optional(data, "diagnostic_evidence_ref")
    claim = get_claim(claim_id)

    if claim.get("status") not in ("SUBMITTED", "REOPENED"):
        fail("ERR_INVALID_STATE", "only a SUBMITTED or REOPENED claim can be diagnosed")

    unit = get_unit(claim["unit_id"])
    streak = int(unit.get("underperformance_streak_hours", 0))
    if streak <= 0 and unit.get("monitored_status") != "FAILED":
        fail("ERR_INVALID_STATE",
             "the unit shows no underperformance streak and has not failed")

    values = {"status": "DIAGNOSED", "diagnostic_source": "REMOTE_VERIFIED"}
    if diagnostic_evidence_ref is not None:
        values["diagnostic_evidence_ref"] = diagnostic_evidence_ref
    common.set_many(claim, values)
    return ok(shapes.warranty_claim(claim))


def approve_claim(claim_id):
    claim = get_claim(claim_id)
    if claim.get("status") != "DIAGNOSED":
        fail("ERR_INVALID_STATE", "only a DIAGNOSED claim can be approved")

    unit = get_unit(claim["unit_id"])
    common.recompute_unit(unit)
    if unit.get("monitored_status") != "FAILED":
        fail("ERR_UNIT_NOT_FAILED")

    system = db.DB.systems.get(unit.get("system_id"))
    if system is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    common.recompute_system(system)
    if system.get("warranty_status") not in ("ACTIVE", "TRANSFERRED"):
        fail("ERR_INVALID_STATE", "the system's warranty_status does not admit approval")
    if common.dec(system.get("replacement_ratio")) >= common.MAX_REPLACEMENT_RATIO:
        fail("ERR_INVALID_STATE", "the system's replacement_ratio is at the maximum")

    installer = db.DB.installers.get(claim.get("installer_id"))
    level = installer.get("certification_level") if installer else None
    age_months = common.system_age_months(system, common.now())
    level_factor = common.LEVEL_FACTOR.get(level, common.dec(0))

    labor_eligible = bool(age_months <= common.LABOR_EXTENDED_MONTHS and level_factor > 0)
    approved_labor_hours = float(common.LEVEL_CAP_HOURS.get(level, common.dec(0)))

    common.set_many(claim, {
        "status": "APPROVED",
        "labor_eligible": labor_eligible,
        "approved_labor_hours": approved_labor_hours,
    })
    if installer is not None:
        common.recompute_installer(installer)
    return ok(shapes.warranty_claim(claim))


def deny_claim(claim_id):
    data = body()
    denial_reason = as_nonempty_str_optional(data, "denial_reason")
    if denial_reason is None:
        fail("ERR_INVALID_REQUEST_BODY", "missing required field `denial_reason`")

    claim = get_claim(claim_id)
    if claim.get("status") != "DIAGNOSED":
        fail("ERR_INVALID_STATE", "only a DIAGNOSED claim can be denied")

    common.set_many(claim, {"status": "DENIED", "denial_reason": denial_reason})

    for reimbursement in db.reimbursements_of_claim(claim["id"]):
        if reimbursement.get("status") == "PENDING":
            common.set_many(reimbursement, {
                "status": "REJECTED",
                "rejection_reason": "claim denied",
            })
    installer = db.DB.installers.get(claim.get("installer_id"))
    if installer is not None:
        common.recompute_installer(installer)
    return ok(shapes.warranty_claim(claim))


def dispatch_claim(claim_id):
    claim = get_claim(claim_id)
    if claim.get("status") != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED claim can be dispatched")

    unit = get_unit(claim["unit_id"])
    common.recompute_unit(unit)
    if not unit.get("rma_eligible"):
        fail("ERR_INVALID_STATE", "the unit is not rma_eligible")

    lot = db.DB.production_lots.get(unit.get("production_lot_id"))
    model, compatibility_class = order_service.resolve_replacement_model(unit, lot)

    order_service.require_chargeable(unit["id"], claim["id"], None)

    order = order_service.new_order(
        unit, model, compatibility_class, "DISPATCHED",
        claim_id=claim["id"], dispatched_at=common.now_iso())

    common.set_many(claim, {"status": "DISPATCHED"})
    for reimbursement in db.reimbursements_of_claim(claim["id"]):
        if reimbursement.get("status") == "PENDING":
            common.set_many(reimbursement, {"status": "APPROVED"})
    installer = db.DB.installers.get(claim.get("installer_id"))
    if installer is not None:
        common.recompute_installer(installer)
    common.recompute_unit(unit)
    return ok(shapes.replacement_order(order))


def close_unreplaced(claim_id):
    claim = get_claim(claim_id)
    if claim.get("status") != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED claim can be closed unreplaced")
    if db.orders_of_claim(claim["id"]):
        fail("ERR_INVALID_STATE", "a replacement order already references this claim")
    common.set_many(claim, {"status": "CLOSED"})
    return ok(shapes.warranty_claim(claim))


def reopen_claim(claim_id):
    claim = get_claim(claim_id)
    status = claim.get("status")
    if status not in ("CLOSED", "DENIED"):
        fail("ERR_INVALID_STATE", "only a CLOSED or DENIED claim can be reopened")

    values = {"reopen_count": int(claim.get("reopen_count", 0)) + 1}

    if status == "CLOSED":
        unit = get_unit(claim["unit_id"])
        if unit.get("monitored_status") not in ("FAILED", "OFFLINE"):
            fail("ERR_INVALID_STATE",
                 "a closed claim can only be reopened while the unit is FAILED or OFFLINE")
    else:
        values["denial_reason"] = None

    values["status"] = "REOPENED"
    common.set_many(claim, values)
    return ok(shapes.warranty_claim(claim))


def register(app):
    app.add_url_rule("/warranty/claims", "create_claim",
                     require(ROLE_INSTALLER)(create_claim), methods=["POST"])
    app.add_url_rule("/warranty/claims", "list_claims",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_MONITORING)(list_claims),
                     methods=["GET"])
    app.add_url_rule("/warranty/claims/<claim_id>", "read_claim",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_MONITORING)(read_claim),
                     methods=["GET"])
    app.add_url_rule("/warranty/claims/<claim_id>/submit", "submit_claim",
                     require(ROLE_INSTALLER)(submit_claim), methods=["POST"])
    app.add_url_rule("/warranty/claims/<claim_id>/diagnose", "diagnose_claim",
                     require(ROLE_MONITORING)(diagnose_claim), methods=["POST"])
    app.add_url_rule("/warranty/claims/<claim_id>/approve", "approve_claim",
                     require(ROLE_PLATFORM_ADMIN)(approve_claim), methods=["POST"])
    app.add_url_rule("/warranty/claims/<claim_id>/deny", "deny_claim",
                     require(ROLE_PLATFORM_ADMIN)(deny_claim), methods=["POST"])
    app.add_url_rule("/warranty/claims/<claim_id>/dispatch", "dispatch_claim",
                     require(ROLE_PLATFORM_ADMIN)(dispatch_claim), methods=["POST"])
    app.add_url_rule("/warranty/claims/<claim_id>/close-unreplaced", "close_unreplaced",
                     require(ROLE_PLATFORM_ADMIN)(close_unreplaced), methods=["POST"])
    app.add_url_rule("/warranty/claims/<claim_id>/reopen", "reopen_claim",
                     require(ROLE_PLATFORM_ADMIN)(reopen_claim), methods=["POST"])