"""ContinuityPlan endpoints and the logical clock / injection endpoints (PRD §3.7, §2.10)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from errors import fail
from middleware import Body, identity, qenum, qstr, require_roles
from response import ok, paginate
from serializers import ser
from store import (
    CONTINUITY_EXTENSION_DAYS,
    CONTINUITY_GRACE_DAYS,
    CONTINUITY_REASONS,
    active_patient_count,
    all_rows,
    create_row,
    get,
    now,
    refresh_posture,
    refresh_all_postures,
    require,
    resync,
    set_derived,
    sort_asc,
    touch,
)
from util import fmt_ts, parse_ts

bp = Blueprint("continuity", __name__)

PLAN_STATUSES = {"PENDING", "ACCEPTED", "DECLINED", "ESCALATED", "COMPLETED"}


def _plan_or_404(plan_id):
    return require("continuity_plans", plan_id, "ERR_CONTINUITY_PLAN_NOT_FOUND")


def _deadline_for(clinician):
    requested = parse_ts(clinician.get("offboarding_requested_on")) if clinician else None
    base = requested if requested is not None else now()
    return fmt_ts(base + timedelta(days=CONTINUITY_GRACE_DAYS))


@bp.post("/continuity-plans")
@require_roles("OpsAdmin")
def create_plan():
    body = Body.read()
    clinician_id = body.string("clinician_id")
    patient_id = body.string("patient_id")
    reason = body.enum("reason", CONTINUITY_REASONS)
    successor_clinician_id = body.optional_string("successor_clinician_id")
    body.finish()

    clinician = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    require("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    if successor_clinician_id is not None:
        require("clinicians", successor_clinician_id, "ERR_CLINICIAN_NOT_FOUND")

    row = create_row(
        "continuity_plans",
        clinician_id=clinician["id"],
        patient_id=patient_id,
        successor_clinician_id=successor_clinician_id,
        reassignment_deadline=_deadline_for(clinician),
        status="PENDING",
        reason=reason,
    )
    return ok(ser("continuity_plans", row), 201)


@bp.get("/continuity-plans")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_plans():
    clinician_id = qstr("clinician_id")
    patient_id = qstr("patient_id")
    status = qenum("status", PLAN_STATUSES)
    out = [ser("continuity_plans", r) for r in sort_asc(all_rows("continuity_plans"))]
    if clinician_id is not None:
        out = [r for r in out if r.get("clinician_id") == clinician_id]
    if patient_id is not None:
        out = [r for r in out if r.get("patient_id") == patient_id]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/continuity-plans/<plan_id>")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def get_plan(plan_id):
    row = _plan_or_404(plan_id)
    return ok(ser("continuity_plans", row), 200)


@bp.get("/clinicians/<clinician_id>/continuity-plans")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_clinician_plans(clinician_id):
    require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    status = qenum("status", PLAN_STATUSES)
    out = [
        ser("continuity_plans", r)
        for r in sort_asc(all_rows("continuity_plans"))
        if r.get("clinician_id") == clinician_id
    ]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/patients/<patient_id>/continuity-plans")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_patient_plans(patient_id):
    require("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    status = qenum("status", PLAN_STATUSES)
    out = [
        ser("continuity_plans", r)
        for r in sort_asc(all_rows("continuity_plans"))
        if r.get("patient_id") == patient_id
    ]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.post("/continuity-plans/<plan_id>/successor")
@require_roles("OpsAdmin")
def assign_successor(plan_id):
    plan = _plan_or_404(plan_id)
    body = Body.read()
    successor_clinician_id = body.string("successor_clinician_id")
    expected = body.version("expected_plan_version")
    body.finish()
    require("clinicians", successor_clinician_id, "ERR_CLINICIAN_NOT_FOUND")

    status = plan.get("status")
    if status == "COMPLETED":
        raise fail("ERR_ALREADY_TERMINAL")
    if status == "ACCEPTED":
        raise fail("ERR_INVALID_STATE")

    deadline = parse_ts(plan.get("reassignment_deadline"))
    if status == "PENDING":
        if deadline is not None and not now() < deadline:
            raise fail("ERR_INVALID_STATE", "The reassignment deadline has passed.")
    elif status in ("DECLINED", "ESCALATED"):
        if deadline is not None and not now() < deadline + timedelta(days=CONTINUITY_EXTENSION_DAYS):
            raise fail("ERR_CONTINUITY_DEADLINE_PASSED")
    else:
        raise fail("ERR_INVALID_STATE")

    # PRD §2.7's optimistic-concurrency rejection is the last gate here: the
    # deadline branch above reports its own, more specific refusal for a plan that
    # is no longer reassignable at all.
    if int(plan.get("version") or 1) != expected:
        raise fail("ERR_STALE_VERSION")

    plan["successor_clinician_id"] = successor_clinician_id
    plan["status"] = "PENDING"
    if status == "ESCALATED":
        patient = get("patients", plan.get("patient_id"))
        if patient is not None:
            patient["swap_requested"] = False
    touch(plan)
    return ok(ser("continuity_plans", plan), 200)


@bp.post("/continuity-plans/<plan_id>/accept")
@require_roles("Clinician")
def accept_plan(plan_id):
    ident = identity()
    plan = _plan_or_404(plan_id)
    successor = get("clinicians", plan.get("successor_clinician_id"))
    if successor is None:
        raise fail("ERR_INVALID_STATE", "The plan has no proposed successor.")
    if ident["id"] != successor["id"]:
        raise fail("ERR_UNAUTHORIZED")
    if plan.get("status") != "PENDING":
        raise fail("ERR_INVALID_STATE")
    refresh_posture(successor)
    if successor.get("billing_posture") != "BILLABLE":
        raise fail("ERR_INVALID_STATE", "The successor is not BILLABLE.")
    if active_patient_count(successor) >= int(successor.get("weekly_caseload_target") or 0):
        raise fail("ERR_CASELOAD_FULL")

    patient = get("patients", plan.get("patient_id"))
    prior = get("clinicians", plan.get("clinician_id"))
    if patient is not None:
        patient["matched_clinician_id"] = successor["id"]
        patient["swap_requested"] = False
        touch(patient)
    if prior is not None and prior["id"] != successor["id"]:
        set_derived(prior, "active_patient_count", active_patient_count(prior))
        set_derived(prior, "continuity_plan_count", _plan_count(prior))
        touch(prior)
        if prior.get("status") == "OFFBOARDING" and active_patient_count(prior) == 0:
            from store import finalize_offboarding

            finalize_offboarding(prior)
    set_derived(successor, "active_patient_count", active_patient_count(successor))
    touch(successor)

    # Escalation clears the swap flag only once the reassignment is in place,
    # so re-derive it here rather than letting a clock resync resurrect it.
    if plan.get("status") == "ESCALATED" and patient is not None:
        patient["swap_requested"] = False

    plan["status"] = "ACCEPTED"
    touch(plan)
    return ok(ser("continuity_plans", plan), 200)


def _plan_count(clinician):
    return len(
        [
            p
            for p in all_rows("continuity_plans")
            if p.get("clinician_id") == clinician["id"] and p.get("status") != "COMPLETED"
        ]
    )


@bp.post("/continuity-plans/<plan_id>/decline")
@require_roles("Clinician")
def decline_plan(plan_id):
    ident = identity()
    plan = _plan_or_404(plan_id)
    successor = get("clinicians", plan.get("successor_clinician_id"))
    if successor is None:
        raise fail("ERR_INVALID_STATE", "The plan has no proposed successor.")
    if ident["id"] != successor["id"]:
        raise fail("ERR_UNAUTHORIZED")
    if plan.get("status") != "PENDING":
        raise fail("ERR_INVALID_STATE")

    plan["status"] = "DECLINED"
    touch(plan)
    return ok(ser("continuity_plans", plan), 200)


@bp.post("/continuity-plans/<plan_id>/complete")
@require_roles("OpsAdmin")
def complete_plan(plan_id):
    plan = _plan_or_404(plan_id)
    if plan.get("status") != "ACCEPTED":
        raise fail("ERR_INVALID_STATE")
    patient = get("patients", plan.get("patient_id"))
    if patient is None or patient.get("matched_clinician_id") != plan.get("successor_clinician_id"):
        raise fail("ERR_INVALID_STATE", "The patient is not matched to the successor.")

    clinician = get("clinicians", plan.get("clinician_id"))
    plan["status"] = "COMPLETED"
    touch(plan)
    if clinician is not None:
        set_derived(clinician, "continuity_plan_count", _plan_count(clinician))
        touch(clinician)
    return ok(ser("continuity_plans", plan), 200)


# ---------------------------------------------------------------- clock


@bp.post("/_clock/set_current_utc")
@require_roles("OpsAdmin")
def set_clock():
    from util import clock as clock_ref

    body = Body.read()
    current_utc = body.instant("current_utc")
    body.finish()
    clock_ref().set(current_utc)
    resync()
    refresh_all_postures()
    return ok({"current_utc": fmt_ts(current_utc)}, 200)