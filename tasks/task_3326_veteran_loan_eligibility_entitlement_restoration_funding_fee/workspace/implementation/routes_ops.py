"""Routes: appraisers, appraisals, repairs, occupancy, deployments,
assumptions, refinances, restorations, audit events, logical clock."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

import common
from common import envelope_ok, paginate, append_audit, stamp_new, touch, new_id, parse_iso
from db import STORE
import errors as E
import middleware as mw
import services as svc
import validate as V

bp = Blueprint("ops", __name__)


def appraiser_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "name": a["name"],
        "region": a["region"],
        "max_open_assignments": a["max_open_assignments"],
        "open_assignment_count": a["open_assignment_count"],
        "active": a["active"],
    }


def appraisal_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "loan_id": a["loan_id"],
        "appraiser_id": a["appraiser_id"],
        "status": a["status"],
        "appraised_value_cents": a["appraised_value_cents"],
        "report_round": a["report_round"],
    }


def repair_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "appraisal_id": r["appraisal_id"],
        "description": r["description"],
        "required_for_clearance": r["required_for_clearance"],
        "status": r["status"],
    }


def cert_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "loan_id": c["loan_id"],
        "certification_date": c["certification_date"],
        "move_in_deadline": c["move_in_deadline"],
        "status": c["status"],
        "exception_type": c["exception_type"],
    }


def deployment_view(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "veteran_id": d["veteran_id"],
        "deployment_start": d["deployment_start"],
        "deployment_end": d["deployment_end"],
        "orders_reference": d["orders_reference"],
    }


def assumption_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "loan_id": a["loan_id"],
        "buyer_name": a["buyer_name"],
        "buyer_is_veteran": a["buyer_is_veteran"],
        "buyer_veteran_id": a["buyer_veteran_id"],
        "substitute_entitlement": a["substitute_entitlement"],
        "release_of_liability": a["release_of_liability"],
        "status": a["status"],
    }


def refi_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "loan_id": r["loan_id"],
        "refinance_type": r["refinance_type"],
        "new_rate_percent": float(r["new_rate_percent"]),
        "new_rate_type": r["new_rate_type"],
        "flat_costs_cents": r["flat_costs_cents"],
        "seasoning_days": r["seasoning_days"],
        "ntb_rate_satisfied": r["ntb_rate_satisfied"],
        "recoupment_months": r["recoupment_months"],
        "ntb_satisfied": r["ntb_satisfied"],
        "status": r["status"],
    }


def restoration_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "veteran_id": r["veteran_id"],
        "loan_id": r["loan_id"],
        "restoration_type": r["restoration_type"],
        "restored_amount_cents": r["restored_amount_cents"],
        "status": r["status"],
    }


def audit_view(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "entity_type": e["entity_type"],
        "entity_id": e["entity_id"],
        "action": e["action"],
        "actor_role": e["actor_role"],
        "actor_user_id": e["actor_user_id"],
        "detail": e["detail"],
    }


# ---------------------------------------------------------------------------
# Appraisers
# ---------------------------------------------------------------------------

@bp.post("/va-loans/appraisers")
def create_appraiser():
    ctx = mw.actor()
    mw.require_roles(ctx, {"ProgramAdmin"})
    data = V.body_json()
    name = V.as_str(data, "name")
    region = V.as_enum(data, "region", svc.REGIONS)
    max_open_assignments = V.as_int(data, "max_open_assignments", required=False, default=3)
    active = V.as_bool(data, "active", required=False, default=True)
    aid = new_id()
    appraiser = stamp_new({
        "id": aid,
        "name": name,
        "region": region,
        "max_open_assignments": max_open_assignments,
        "open_assignment_count": 0,
        "active": active,
    })
    STORE.appraisers[aid] = appraiser
    append_audit("Appraiser", aid, "create", ctx["role"], ctx["user_id"], "appraiser registered")
    return envelope_ok(appraiser_view(appraiser), "object", 201)


# ---------------------------------------------------------------------------
# Appraisals
# ---------------------------------------------------------------------------

@bp.get("/va-loans/appraisal-requests")
def list_appraisals():
    ctx = mw.actor()
    mw.require_roles(ctx, {"Appraiser", "LoanOfficer", "ProgramAdmin"})
    items = list(STORE.appraisals.values())
    appraiser_id = request.args.get("appraiser_id")
    loan_id = request.args.get("loan_id")
    status = request.args.get("status")
    if appraiser_id:
        items = [a for a in items if a.get("appraiser_id") == appraiser_id]
    if loan_id:
        items = [a for a in items if a["loan_id"] == loan_id]
    if status:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([appraisal_view(a) for a in page], "array", 200, pagination)


@bp.post("/va-loans/loans/<lid>/appraisal-requests")
def create_appraisal(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    mw.get_loan_or_404(lid)
    aid = new_id()
    appraisal = stamp_new({
        "id": aid,
        "loan_id": lid,
        "appraiser_id": None,
        "status": "REQUESTED",
        "appraised_value_cents": None,
        "report_round": 0,
    })
    STORE.appraisals[aid] = appraisal
    svc.try_assign_appraisal(appraisal)
    append_audit("Appraisal", aid, "create", ctx["role"], ctx["user_id"], "appraisal ordered")
    return envelope_ok(appraisal_view(appraisal), "object", 201)


@bp.get("/va-loans/loans/<lid>/appraisal-requests")
def list_loan_appraisals(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Appraiser", "ProgramAdmin"})
    loan = mw.get_loan_or_404(lid)
    mw.check_veteran_subtree(ctx, loan["veteran_id"])
    items = [a for a in STORE.appraisals.values() if a["loan_id"] == lid]
    items.sort(key=lambda a: a["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([appraisal_view(a) for a in page], "array", 200, pagination)


@bp.get("/va-loans/appraisal-requests/<aid>")
def get_appraisal(aid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Appraiser", "ProgramAdmin"})
    appraisal = mw.get_appraisal_or_404(aid)
    loan = STORE.loans.get(appraisal["loan_id"])
    if loan is not None:
        mw.check_veteran_subtree(ctx, loan["veteran_id"])
    return envelope_ok(appraisal_view(appraisal), "object", 200)


@bp.post("/va-loans/appraisal-requests/<aid>/submit-report")
def submit_report(aid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Appraiser"})
    appraisal = mw.get_appraisal_or_404(aid)
    data = V.body_json()
    outcome = V.as_enum(data, "outcome", {"VALUE_ISSUED", "REPAIRS_REQUIRED"})
    appraised_value_cents = V.as_int(data, "appraised_value_cents", required=False)
    repairs = V.as_list(data, "repairs", required=False, default=None)

    if appraisal["status"] not in ("ASSIGNED", "REPAIRS_REQUIRED"):
        raise E.appraisal_not_assigned()
    if ctx["user_id"] != appraisal.get("appraiser_id"):
        raise E.appraisal_not_assigned()

    if outcome == "VALUE_ISSUED":
        if appraised_value_cents is None:
            raise E.validation("appraised_value_cents is required for VALUE_ISSUED")
        if svc.appraisal_has_clearance_blockers(aid):
            raise E.repairs_outstanding()
        appraisal["status"] = "VALUE_ISSUED"
        appraisal["appraised_value_cents"] = appraised_value_cents
        appraisal["report_round"] += 1
        touch(appraisal)
        appraiser = STORE.appraisers.get(appraisal.get("appraiser_id") or "")
        if appraiser is not None:
            appraiser["open_assignment_count"] = max(0, appraiser["open_assignment_count"] - 1)
            touch(appraiser)
            svc.promote_queue_for_appraiser(appraiser)
    else:  # REPAIRS_REQUIRED
        if not repairs:
            raise E.validation("repairs array must be non-empty for REPAIRS_REQUIRED")
        for entry in repairs:
            if not isinstance(entry, dict):
                raise E.validation("repairs entries must be objects")
            description = entry.get("description")
            if not isinstance(description, str):
                raise E.validation("repairs entries require a description string")
            rfc = entry.get("required_for_clearance", True)
            if not isinstance(rfc, bool):
                raise E.validation("required_for_clearance must be a boolean")
            rid = new_id()
            repair = stamp_new({
                "id": rid,
                "appraisal_id": aid,
                "description": description,
                "required_for_clearance": rfc,
                "status": "OPEN",
            })
            STORE.repair_requirements[rid] = repair
        appraisal["status"] = "REPAIRS_REQUIRED"
        appraisal["report_round"] += 1
        touch(appraisal)

    append_audit("Appraisal", aid, "submit_report", ctx["role"], ctx["user_id"],
                 f"report submitted with outcome {outcome}")
    return envelope_ok(appraisal_view(appraisal), "object", 200)


# ---------------------------------------------------------------------------
# Repair requirements
# ---------------------------------------------------------------------------

@bp.get("/va-loans/appraisal-requests/<aid>/repair-requirements")
def list_repairs(aid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Appraiser", "ProgramAdmin"})
    appraisal = mw.get_appraisal_or_404(aid)
    loan = STORE.loans.get(appraisal["loan_id"])
    if loan is not None:
        mw.check_veteran_subtree(ctx, loan["veteran_id"])
    items = [r for r in STORE.repair_requirements.values() if r["appraisal_id"] == aid]
    items.sort(key=lambda r: r["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([repair_view(r) for r in page], "array", 200, pagination)


@bp.post("/va-loans/repair-requirements/<rid>/complete")
def complete_repair(rid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    repair = mw.get_repair_or_404(rid)
    if repair["status"] != "OPEN":
        raise E.invalid_state()
    appraisal = STORE.appraisals.get(repair["appraisal_id"])
    if appraisal is None or appraisal["status"] != "REPAIRS_REQUIRED":
        raise E.invalid_state()
    repair["status"] = "COMPLETED"
    touch(repair)
    append_audit("RepairRequirement", rid, "complete", ctx["role"], ctx["user_id"], "repair completed")
    return envelope_ok(repair_view(repair), "object", 200)


@bp.post("/va-loans/repair-requirements/<rid>/verify")
def verify_repair(rid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Appraiser"})
    repair = mw.get_repair_or_404(rid)
    if repair["status"] != "COMPLETED":
        raise E.invalid_state()
    appraisal = STORE.appraisals.get(repair["appraisal_id"])
    if appraisal is None or ctx["user_id"] != appraisal.get("appraiser_id"):
        raise E.appraisal_not_assigned("only the assigned appraiser may verify this repair")
    repair["status"] = "VERIFIED"
    touch(repair)
    append_audit("RepairRequirement", rid, "verify", ctx["role"], ctx["user_id"], "repair verified")
    return envelope_ok(repair_view(repair), "object", 200)


@bp.post("/va-loans/repair-requirements/<rid>/waive")
def waive_repair(rid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"ProgramAdmin"})
    repair = mw.get_repair_or_404(rid)
    if repair["status"] != "OPEN":
        raise E.invalid_state()
    repair["status"] = "WAIVED"
    touch(repair)
    append_audit("RepairRequirement", rid, "waive_repair", ctx["role"], ctx["user_id"], "repair waived")
    return envelope_ok(repair_view(repair), "object", 200)


# ---------------------------------------------------------------------------
# Occupancy certificates
# ---------------------------------------------------------------------------

@bp.get("/va-loans/loans/<lid>/occupancy-certificates")
def list_occupancy_certificates(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "ProgramAdmin"})
    loan = mw.get_loan_or_404(lid)
    mw.check_veteran_subtree(ctx, loan["veteran_id"])
    items = [c for c in STORE.occupancy_certificates.values() if c["loan_id"] == lid]
    items.sort(key=lambda c: c["created_at"])
    return envelope_ok([cert_view(c) for c in items], "array", 200)


@bp.post("/va-loans/occupancy-certificates/<cid>/verify-occupancy")
def verify_occupancy(cid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    cert = mw.get_occupancy_cert_or_404(cid)
    data = V.body_json()
    move_in_date = V.as_str(data, "move_in_date")
    try:
        move_in_dt = parse_iso(move_in_date)
        deadline_dt = parse_iso(cert["move_in_deadline"])
    except Exception:
        raise E.validation("move_in_date must be an ISO date")
    if cert["status"] != "CERTIFIED":
        raise E.invalid_state()

    if move_in_dt <= deadline_dt:
        cert["status"] = "SATISFIED"
    else:
        loan = STORE.loans.get(cert["loan_id"])
        veteran_id = loan["veteran_id"] if loan else None
        covered = False
        for d in STORE.deployment_exceptions.values():
            if d["veteran_id"] != veteran_id:
                continue
            if parse_iso(d["deployment_start"]) <= deadline_dt < parse_iso(d["deployment_end"]):
                covered = True
                break
        if covered:
            cert["status"] = "EXCEPTED"
            cert["exception_type"] = "DEPLOYMENT"
        else:
            cert["status"] = "VIOLATED"
            append_audit("OccupancyCertificate", cid, "occupancy_violation", ctx["role"],
                         ctx["user_id"], "occupancy deadline violated")
    touch(cert)
    return envelope_ok(cert_view(cert), "object", 200)


# ---------------------------------------------------------------------------
# Deployment exceptions
# ---------------------------------------------------------------------------

@bp.post("/va-loans/veterans/<vid>/deployment-exceptions")
def create_deployment_exception(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer"})
    mw.check_veteran_subtree(ctx, vid)
    mw.get_veteran_or_404(vid)
    data = V.body_json()
    deployment_start = V.as_str(data, "deployment_start")
    deployment_end = V.as_str(data, "deployment_end")
    orders_reference = V.as_str(data, "orders_reference")
    try:
        start_dt = parse_iso(deployment_start)
        end_dt = parse_iso(deployment_end)
    except Exception:
        raise E.validation("deployment_start and deployment_end must be ISO dates")

    # Half-open overlap rejection: [start, end). end == other start is allowed.
    for d in STORE.deployment_exceptions.values():
        if d["veteran_id"] != vid:
            continue
        ex_start = parse_iso(d["deployment_start"])
        ex_end = parse_iso(d["deployment_end"])
        if start_dt < ex_end and ex_start < end_dt:
            raise E.deployment_window_overlap()

    did = new_id()
    dep = stamp_new({
        "id": did,
        "veteran_id": vid,
        "deployment_start": deployment_start,
        "deployment_end": deployment_end,
        "orders_reference": orders_reference,
    })
    STORE.deployment_exceptions[did] = dep
    append_audit("DeploymentException", did, "create", ctx["role"], ctx["user_id"], "deployment window recorded")
    return envelope_ok(deployment_view(dep), "object", 201)


@bp.get("/va-loans/veterans/<vid>/deployment-exceptions")
def list_deployment_exceptions(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "ProgramAdmin"})
    mw.check_veteran_subtree(ctx, vid)
    mw.get_veteran_or_404(vid)
    items = [d for d in STORE.deployment_exceptions.values() if d["veteran_id"] == vid]
    items.sort(key=lambda d: d["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([deployment_view(d) for d in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Assumption requests
# ---------------------------------------------------------------------------

@bp.post("/va-loans/loans/<lid>/assumption-requests")
def create_assumption(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    mw.get_loan_or_404(lid)
    data = V.body_json()
    buyer_name = V.as_str(data, "buyer_name")
    buyer_is_veteran = V.as_bool(data, "buyer_is_veteran")
    substitute_entitlement = V.as_bool(data, "substitute_entitlement")
    release_of_liability = V.as_bool(data, "release_of_liability")
    if buyer_is_veteran:
        buyer_veteran_id = V.as_str(data, "buyer_veteran_id")
        if buyer_veteran_id not in STORE.veterans:
            raise E.service_period_mismatch("buyer_veteran_id does not resolve")
    else:
        buyer_veteran_id = V.opt_field(data, "buyer_veteran_id", None)

    aid = new_id()
    assumption = stamp_new({
        "id": aid,
        "loan_id": lid,
        "buyer_name": buyer_name,
        "buyer_is_veteran": buyer_is_veteran,
        "buyer_veteran_id": buyer_veteran_id,
        "substitute_entitlement": substitute_entitlement,
        "release_of_liability": release_of_liability,
        "status": "SUBMITTED",
    })
    STORE.assumption_requests[aid] = assumption
    append_audit("AssumptionRequest", aid, "create", ctx["role"], ctx["user_id"], "assumption request submitted")
    return envelope_ok(assumption_view(assumption), "object", 201)


@bp.get("/va-loans/loans/<lid>/assumption-requests")
def list_loan_assumptions(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Underwriter", "ProgramAdmin"})
    loan = mw.get_loan_or_404(lid)
    mw.check_veteran_subtree(ctx, loan["veteran_id"])
    items = [a for a in STORE.assumption_requests.values() if a["loan_id"] == lid]
    items.sort(key=lambda a: a["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([assumption_view(a) for a in page], "array", 200, pagination)


@bp.get("/va-loans/veterans/<vid>/assumption-requests")
def list_veteran_assumptions(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Underwriter", "ProgramAdmin"})
    mw.check_veteran_subtree(ctx, vid)
    mw.get_veteran_or_404(vid)
    items = [a for a in STORE.assumption_requests.values() if a.get("buyer_veteran_id") == vid]
    items.sort(key=lambda a: a["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([assumption_view(a) for a in page], "array", 200, pagination)


@bp.post("/va-loans/assumption-requests/<aid>/approve")
def approve_assumption(aid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Underwriter"})
    assumption = mw.get_assumption_or_404(aid)
    if assumption["status"] != "SUBMITTED":
        raise E.invalid_state()
    loan = STORE.loans.get(assumption["loan_id"])
    if loan is None:
        raise E.not_found("ERR_LOAN_NOT_FOUND", "loan id does not resolve")
    if loan["closing_status"] != "CLOSED":
        raise E.assumption_ineligible("loan must be CLOSED (not PAID_IN_FULL) for assumption")

    if assumption["substitute_entitlement"]:
        if not assumption["buyer_is_veteran"] or not assumption.get("buyer_veteran_id"):
            raise E.assumption_ineligible("substitution requires a veteran buyer")
        buyer_veteran = STORE.veterans.get(assumption["buyer_veteran_id"])
        if buyer_veteran is None:
            raise E.assumption_ineligible("buyer_veteran_id does not resolve")
        buyer_acct = svc.recompute_entitlement_account(assumption["buyer_veteran_id"])
        if buyer_acct is None or buyer_acct["remaining_with_bonus_cents"] < loan["entitlement_charged_cents"]:
            raise E.assumption_ineligible("buyer entitlement insufficient for substitution")

    assumption["status"] = "APPROVED"
    touch(assumption)

    if assumption["substitute_entitlement"]:
        amount = loan["entitlement_charged_cents"]
        buyer_acct = svc.get_account_for_veteran(assumption["buyer_veteran_id"])
        seller_acct = svc.get_account_for_veteran(loan["veteran_id"])
        if buyer_acct is not None:
            buyer_acct["total_charged_cents"] += amount
            svc.recompute_entitlement_account(assumption["buyer_veteran_id"])
            touch(buyer_acct)
        if seller_acct is not None:
            seller_acct["total_restored_cents"] += amount
            svc.recompute_entitlement_account(loan["veteran_id"])
            touch(seller_acct)
        svc.refresh_restoration_flags(assumption["buyer_veteran_id"])
        svc.refresh_restoration_flags(loan["veteran_id"])
        buyer = STORE.veterans.get(assumption["buyer_veteran_id"])
        if buyer is not None:
            svc.recompute_veteran_totals(buyer)
            touch(buyer)
        seller = STORE.veterans.get(loan["veteran_id"])
        if seller is not None:
            svc.recompute_veteran_totals(seller)
            touch(seller)

    append_audit("AssumptionRequest", aid, "approve_assumption", ctx["role"], ctx["user_id"],
                 "assumption approved")
    return envelope_ok(assumption_view(assumption), "object", 200)


# ---------------------------------------------------------------------------
# Refinance requests
# ---------------------------------------------------------------------------

@bp.post("/va-loans/loans/<lid>/refinance-requests")
def create_refinance(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    loan = mw.get_loan_or_404(lid)
    data = V.body_json()
    refinance_type = V.as_enum(data, "refinance_type", svc.REFI_TYPES)
    new_rate_percent = V.as_number(data, "new_rate_percent")
    new_rate_type = V.as_enum(data, "new_rate_type", svc.RATE_TYPES)
    flat_costs_cents = V.as_int(data, "flat_costs_cents")
    expected_loan_version = V.as_int(data, "expected_loan_version")

    if expected_loan_version != loan["version"]:
        raise E.stale_version()

    # Supersede any prior SUBMITTED request on this loan.
    for r in STORE.refinance_requests.values():
        if r["loan_id"] == lid and r["status"] == "SUBMITTED":
            r["status"] = "SUPERSEDED"
            touch(r)

    rid = new_id()
    refi = stamp_new({
        "id": rid,
        "loan_id": lid,
        "refinance_type": refinance_type,
        "new_rate_percent": new_rate_percent,
        "new_rate_type": new_rate_type,
        "flat_costs_cents": flat_costs_cents,
        "seasoning_days": None,
        "ntb_rate_satisfied": None,
        "recoupment_months": None,
        "ntb_satisfied": None,
        "status": "SUBMITTED",
    })
    STORE.refinance_requests[rid] = refi
    touch(loan)
    append_audit("RefinanceRequest", rid, "create", ctx["role"], ctx["user_id"], "refinance request created")
    return envelope_ok(refi_view(refi), "object", 201)


@bp.get("/va-loans/loans/<lid>/refinance-requests")
def list_refinances(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "Underwriter", "ProgramAdmin"})
    loan = mw.get_loan_or_404(lid)
    mw.check_veteran_subtree(ctx, loan["veteran_id"])
    items = [r for r in STORE.refinance_requests.values() if r["loan_id"] == lid]
    items.sort(key=lambda r: r["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([refi_view(r) for r in page], "array", 200, pagination)


@bp.post("/va-loans/refinance-requests/<rid>/evaluate")
def evaluate_refinance(rid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Underwriter"})
    refi = mw.get_refinance_or_404(rid)
    if refi["status"] != "SUBMITTED":
        raise E.invalid_state()
    loan = STORE.loans.get(refi["loan_id"])
    if loan is None:
        raise E.not_found("ERR_LOAN_NOT_FOUND", "loan id does not resolve")
    if loan["closing_date"] is None or loan["first_payment_due_date"] is None:
        raise E.invalid_state("loan must be closed before refinance evaluation")

    clock = common.clock_now()
    closing_dt = parse_iso(loan["closing_date"])
    first_payment_dt = parse_iso(loan["first_payment_due_date"])
    seasoning_days = min((clock - closing_dt).days, (clock - first_payment_dt).days)
    refi["seasoning_days"] = seasoning_days
    if seasoning_days < 210:
        touch(refi)
        raise E.seasoning_not_met()

    # NTB computation in pinned order.
    veteran = STORE.veterans.get(loan["veteran_id"], {})
    new_base_cents = loan["loan_amount_cents"]
    fee_cents = svc.compute_refinance_fee_cents(
        refi["refinance_type"], new_base_cents, veteran, loan["loan_use"],
        loan["down_payment_cents"], loan["purchase_price_cents"])
    allowable_costs_cents = fee_cents + refi["flat_costs_cents"]
    new_principal_cents = new_base_cents + allowable_costs_cents
    old_payment_cents = svc.amortize_payment_cents(new_base_cents, loan["interest_rate_percent"], 360)
    new_payment_cents = svc.amortize_payment_cents(new_principal_cents, refi["new_rate_percent"], 360)
    monthly_savings_cents = old_payment_cents - new_payment_cents
    if monthly_savings_cents > 0:
        recoupment_months = -(-allowable_costs_cents // monthly_savings_cents)  # ceil division
    else:
        recoupment_months = 999999
    ntb_rate_satisfied = svc.rate_leg_satisfied(
        loan["rate_type"], refi["new_rate_type"], loan["interest_rate_percent"], refi["new_rate_percent"])
    if refi["refinance_type"] == "IRRRL":
        ntb_satisfied = ntb_rate_satisfied and recoupment_months <= 36
    else:
        ntb_satisfied = ntb_rate_satisfied

    refi["ntb_rate_satisfied"] = ntb_rate_satisfied
    refi["recoupment_months"] = recoupment_months
    refi["ntb_satisfied"] = ntb_satisfied
    refi["status"] = "APPROVED" if ntb_satisfied else "REJECTED"
    touch(refi)
    append_audit("RefinanceRequest", rid, "evaluate_refinance", ctx["role"], ctx["user_id"],
                 f"refinance evaluated: {refi['status']}")
    return envelope_ok(refi_view(refi), "object", 200)


# ---------------------------------------------------------------------------
# Entitlement restoration requests
# ---------------------------------------------------------------------------

@bp.post("/va-loans/veterans/<vid>/entitlement-restoration-requests")
def create_restoration(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"LoanOfficer"})
    mw.get_veteran_or_404(vid)
    data = V.body_json()
    loan_id = V.as_str(data, "loan_id")
    restoration_type = V.as_enum(data, "restoration_type", svc.RESTORATION_TYPES)
    loan = STORE.loans.get(loan_id)
    if loan is None:
        raise E.not_found("ERR_LOAN_NOT_FOUND", "loan id does not resolve")

    rid = new_id()
    rest = stamp_new({
        "id": rid,
        "veteran_id": vid,
        "loan_id": loan_id,
        "restoration_type": restoration_type,
        "restored_amount_cents": 0,
        "status": "SUBMITTED",
    })
    STORE.restoration_requests[rid] = rest
    append_audit("EntitlementRestorationRequest", rid, "create", ctx["role"], ctx["user_id"],
                 "restoration request filed")
    return envelope_ok(restoration_view(rest), "object", 201)


@bp.get("/va-loans/veterans/<vid>/entitlement-restoration-requests")
def list_veteran_restorations(vid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "ProgramAdmin"})
    mw.check_veteran_subtree(ctx, vid)
    mw.get_veteran_or_404(vid)
    items = [r for r in STORE.restoration_requests.values() if r["veteran_id"] == vid]
    items.sort(key=lambda r: r["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([restoration_view(r) for r in page], "array", 200, pagination)


@bp.get("/va-loans/loans/<lid>/entitlement-restoration-requests")
def list_loan_restorations(lid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"Veteran", "LoanOfficer", "ProgramAdmin"})
    loan = mw.get_loan_or_404(lid)
    mw.check_veteran_subtree(ctx, loan["veteran_id"])
    items = [r for r in STORE.restoration_requests.values() if r["loan_id"] == lid]
    items.sort(key=lambda r: r["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([restoration_view(r) for r in page], "array", 200, pagination)


@bp.post("/va-loans/entitlement-restoration-requests/<rid>/grant")
def grant_restoration(rid):
    ctx = mw.actor()
    mw.require_roles(ctx, {"ProgramAdmin"})
    rest = mw.get_restoration_or_404(rid)
    if rest["status"] != "SUBMITTED":
        raise E.invalid_state()
    loan = STORE.loans.get(rest["loan_id"])
    if loan is None:
        raise E.not_found("ERR_LOAN_NOT_FOUND", "loan id does not resolve")
    if loan["closing_status"] != "PAID_IN_FULL":
        raise E.loan_not_paid_off()
    if rest["restoration_type"] == "SALE_PAYOFF" and loan["payoff_type"] != "SALE":
        raise E.invalid_state("SALE_PAYOFF requires payoff_type SALE")
    if rest["restoration_type"] == "REFINANCE_PAYOFF" and loan["payoff_type"] != "REFINANCE_PAYOFF":
        raise E.invalid_state("REFINANCE_PAYOFF requires payoff_type REFINANCE_PAYOFF")
    if rest["restoration_type"] == "ONE_TIME_RESTORATION":
        for other in STORE.restoration_requests.values():
            if (other["veteran_id"] == rest["veteran_id"]
                    and other["restoration_type"] == "ONE_TIME_RESTORATION"
                    and other["status"] == "GRANTED"):
                raise E.invalid_state("one-time restoration already used")

    amount = loan["entitlement_charged_cents"]
    rest["restored_amount_cents"] = amount
    rest["status"] = "GRANTED"
    touch(rest)

    acct = svc.get_account_for_veteran(rest["veteran_id"])
    if acct is not None:
        acct["total_restored_cents"] += amount
        svc.recompute_entitlement_account(rest["veteran_id"])
        touch(acct)
    svc.refresh_restoration_flags(rest["veteran_id"])
    veteran = STORE.veterans.get(rest["veteran_id"])
    if veteran is not None:
        svc.recompute_veteran_totals(veteran)
        touch(veteran)

    append_audit("EntitlementRestorationRequest", rid, "grant_restoration", ctx["role"],
                 ctx["user_id"], "restoration granted")
    return envelope_ok(restoration_view(rest), "object", 200)


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

@bp.get("/va-loans/audit-events")
def list_audit_events():
    ctx = mw.actor()
    mw.require_roles(ctx, {"ProgramAdmin"})
    items = list(STORE.audit_events.values())
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    action = request.args.get("action")
    if entity_type:
        items = [e for e in items if e["entity_type"] == entity_type]
    if entity_id:
        items = [e for e in items if e["entity_id"] == entity_id]
    if action:
        items = [e for e in items if e["action"] == action]
    items.sort(key=lambda e: e["created_at"])
    page, pagination = paginate(items, request.args)
    return envelope_ok([audit_view(e) for e in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/va-loans/_clock/set_current_utc")
def set_clock():
    ctx = mw.actor()
    mw.require_roles(ctx, {"ProgramAdmin"})
    data = V.body_json()
    to_iso8601 = V.as_str(data, "to_iso8601")
    try:
        parse_iso(to_iso8601)
    except Exception:
        raise E.validation("to_iso8601 must be an ISO 8601 timestamp")
    common.set_clock(to_iso8601)
    return envelope_ok({"current_utc": to_iso8601}, "object", 200)
