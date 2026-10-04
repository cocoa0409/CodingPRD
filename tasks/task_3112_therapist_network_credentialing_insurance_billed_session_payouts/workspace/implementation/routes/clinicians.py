"""Clinician, License and MalpracticePolicy endpoints (PRD §3.1)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from calc import resolve_rate
from errors import fail
from middleware import Body, require_roles, qstr, qenum
from response import ok, paginate
from serializers import ser
from store import (
    CONTINUITY_GRACE_DAYS,
    LICENSE_TYPES,
    active_patient_count,
    all_rows,
    billing_posture,
    create_row,
    finalize_offboarding,
    get,
    license_effective_status,
    now,
    open_slot_count,
    policy_status,
    refresh_posture,
    reify,
    require,
    set_derived,
    sort_asc,
    table,
    touch,
)
from util import fmt_ts, parse_ts

bp = Blueprint("clinicians", __name__)

CLINICIAN_STATUS_FILTERS = {
    "ONBOARDING",
    "CREDENTIALING",
    "ACTIVE",
    "SUSPENDED",
    "OFFBOARDING",
    "OFFBOARDED",
}
POSTURES = {"BILLABLE", "GATED", "FROZEN"}


def _cancels_open_sessions(clinician):
    for session in all_rows("sessions"):
        if session.get("clinician_id") != clinician["id"]:
            continue
        if session.get("status") in ("REQUESTED", "SCHEDULED"):
            session["status"] = "CANCELLED"
            set_derived(session, "slot_consumed", False)
            touch(session)
    set_derived(clinician, "open_slot_count", open_slot_count(clinician))


def cancel_open_sessions(clinician):
    _cancels_open_sessions(clinician)


# ---------------------------------------------------------------- collection


@bp.post("/clinicians")
@require_roles("OpsAdmin")
def create_clinician():
    body = Body.read()
    full_name = body.string("full_name")
    license_type = body.enum("license_type", LICENSE_TYPES)
    primary_state = body.string("primary_state")
    specialty_tags = body.string_list("specialty_tags")
    weekly_caseload_target = body.integer("weekly_caseload_target", minimum=1)
    availability_blocks = body.blocks("availability_blocks", required=False)
    body.finish()

    row = create_row(
        "clinicians",
        full_name=full_name,
        license_type=license_type,
        primary_state=primary_state,
        specialty_tags=specialty_tags,
        weekly_caseload_target=weekly_caseload_target,
        availability_blocks=availability_blocks,
        onboarded_at=fmt_ts(now()),
        status="ONBOARDING",
        billing_posture="GATED",
        active_patient_count=0,
        enrolled_payer_count=0,
        payout_balance_cents=0,
        offboarding_requested_on=None,
        continuity_plan_count=0,
        cash_basis_opt_in=False,
        pending_clawback_residual_cents=0,
    )
    set_derived(row, "open_slot_count", open_slot_count(row))
    refresh_posture(row)
    return ok(ser("clinicians", row), 201)


@bp.get("/clinicians")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_clinicians():
    status = qenum("status", CLINICIAN_STATUS_FILTERS)
    posture = qenum("billing_posture", POSTURES)
    primary_state = qstr("primary_state")
    license_type = qenum("license_type", LICENSE_TYPES)

    items = sort_asc(all_rows("clinicians"))
    out = [ser("clinicians", row) for row in items]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    if posture is not None:
        out = [r for r in out if r.get("billing_posture") == posture]
    if primary_state is not None:
        out = [r for r in out if r.get("primary_state") == primary_state]
    if license_type is not None:
        out = [r for r in out if r.get("license_type") == license_type]

    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/clinicians/<clinician_id>")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician", "Patient")
def get_clinician(clinician_id):
    row = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    return ok(ser("clinicians", row), 200)


@bp.put("/clinicians/<clinician_id>")
@require_roles("OpsAdmin")
def update_clinician(clinician_id):
    row = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    body = Body.read()
    if body.has("weekly_caseload_target"):
        row["weekly_caseload_target"] = body.integer("weekly_caseload_target", minimum=1)
    if body.has("availability_blocks"):
        row["availability_blocks"] = body.blocks("availability_blocks")
    if body.has("specialty_tags"):
        row["specialty_tags"] = body.string_list("specialty_tags")
    if body.has("primary_state"):
        row["primary_state"] = body.string("primary_state")
    body.optional_version("expected_clinician_version")
    body.finish()

    set_derived(row, "open_slot_count", open_slot_count(row))
    set_derived(row, "active_patient_count", active_patient_count(row))
    refresh_posture(row)
    touch(row)
    return ok(ser("clinicians", row), 200)


# ---------------------------------------------------------------- lifecycle


@bp.post("/clinicians/<clinician_id>/submit-credentials")
@require_roles("ComplianceOfficer")
def submit_credentials(clinician_id):
    row = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    if row.get("status") not in ("ONBOARDING", "CREDENTIALING"):
        raise fail("ERR_INVALID_STATE")
    has_license = any(l.get("clinician_id") == row["id"] for l in all_rows("licenses"))
    if not has_license:
        raise fail("ERR_INVALID_STATE", "A license must be on file before credentialing.")
    has_policy = any(p.get("clinician_id") == row["id"] for p in all_rows("malpractice_policies"))
    if not has_policy:
        raise fail("ERR_INVALID_STATE", "A malpractice policy must be on file before credentialing.")

    row["status"] = "CREDENTIALING"
    refresh_posture(row)
    touch(row)
    return ok(ser("clinicians", row), 200)


@bp.post("/clinicians/<clinician_id>/suspend")
@require_roles("OpsAdmin")
def suspend_clinician(clinician_id):
    row = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    if row.get("status") != "ACTIVE":
        raise fail("ERR_INVALID_STATE")
    row["status"] = "SUSPENDED"
    set_derived(row, "billing_posture", "FROZEN")
    _cancels_open_sessions(row)
    touch(row)
    return ok(ser("clinicians", row), 200)


@bp.post("/clinicians/<clinician_id>/reinstate")
@require_roles("OpsAdmin")
def reinstate_clinician(clinician_id):
    row = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    if row.get("status") != "SUSPENDED":
        raise fail("ERR_INVALID_STATE")
    licenses = [l for l in all_rows("licenses") if l.get("clinician_id") == row["id"]]
    if not any(license_effective_status(l) == "VERIFIED" for l in licenses):
        raise fail("ERR_INVALID_STATE", "No license reads VERIFIED.")
    if int(row.get("enrolled_payer_count") or 0) < 1:
        raise fail("ERR_INVALID_STATE", "At least one EFFECTIVE enrollment is required.")

    row["status"] = "ACTIVE"
    refresh_posture(row)
    touch(row)
    return ok(ser("clinicians", row), 200)


@bp.post("/clinicians/<clinician_id>/request-offboarding")
@require_roles("OpsAdmin")
def request_offboarding(clinician_id):
    row = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    if row.get("status") != "ACTIVE":
        raise fail("ERR_INVALID_STATE")
    if open_slot_count(row) != 0:
        raise fail("ERR_INVALID_STATE", "Offboarding requires no open availability.")
    patients = [p for p in all_rows("patients") if p.get("matched_clinician_id") == row["id"]]
    if len(patients) < 1:
        raise fail("ERR_INVALID_STATE", "Offboarding requires at least one active patient.")

    row["status"] = "OFFBOARDING"
    row["offboarding_requested_on"] = fmt_ts(now())
    set_derived(row, "billing_posture", "GATED")
    deadline = fmt_ts(now() + timedelta(days=CONTINUITY_GRACE_DAYS))
    for patient in patients:
        create_row(
            "continuity_plans",
            clinician_id=row["id"],
            patient_id=patient["id"],
            successor_clinician_id=None,
            reassignment_deadline=deadline,
            status="PENDING",
            reason="OFFBOARDING",
        )
    set_derived(row, "continuity_plan_count", _plan_count(row))
    touch(row)
    return ok(ser("clinicians", row), 200)


def _plan_count(clinician):
    return len(
        [
            p
            for p in all_rows("continuity_plans")
            if p.get("clinician_id") == clinician["id"] and p.get("status") != "COMPLETED"
        ]
    )


@bp.post("/clinicians/<clinician_id>/cancel-offboarding")
@require_roles("OpsAdmin")
def cancel_offboarding(clinician_id):
    row = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    if row.get("status") != "OFFBOARDING":
        raise fail("ERR_INVALID_STATE")
    plans = [p for p in all_rows("continuity_plans") if p.get("clinician_id") == row["id"]]
    if not all(p.get("status") in ("PENDING", "COMPLETED") for p in plans):
        raise fail("ERR_INVALID_STATE")

    row["status"] = "ACTIVE"
    row["offboarding_requested_on"] = None
    set_derived(row, "continuity_plan_count", _plan_count(row))
    refresh_posture(row)
    touch(row)
    return ok(ser("clinicians", row), 200)


@bp.post("/clinicians/<clinician_id>/complete-offboarding")
@require_roles("OpsAdmin")
def complete_offboarding(clinician_id):
    row = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    if row.get("status") != "OFFBOARDING":
        raise fail("ERR_INVALID_STATE")
    if active_patient_count(row) != 0:
        raise fail("ERR_INVALID_STATE", "Every matched patient must have been reassigned.")

    finalize_offboarding(row)
    return ok(ser("clinicians", row), 200)


# ---------------------------------------------------------------- licenses


def _license_or_404(clinician_id, license_id):
    require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    row = get("licenses", license_id)
    if row is None or row.get("clinician_id") != clinician_id:
        raise fail("ERR_LICENSE_NOT_FOUND")
    return row


@bp.post("/clinicians/<clinician_id>/licenses")
@require_roles("OpsAdmin")
def create_license(clinician_id):
    clinician = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    body = Body.read()
    license_number = body.string("license_number")
    license_type = body.enum("license_type", LICENSE_TYPES)
    issuing_state = body.string("issuing_state")
    expires_on = body.instant("expires_on")
    telehealth_eligible = body.boolean("telehealth_eligible")
    body.finish()

    row = create_row(
        "licenses",
        clinician_id=clinician["id"],
        license_number=license_number,
        license_type=license_type,
        issuing_state=issuing_state,
        expires_on=fmt_ts(expires_on),
        telehealth_eligible=telehealth_eligible,
        verification_status="UNVERIFIED",
        verified_at=None,
        verified_by_user_id=None,
        verification_attempts=0,
        verify_attempt_failed=False,
        reset_since_failure=False,
    )
    refresh_posture(clinician)
    touch(clinician)
    return ok(ser("licenses", row), 201)


@bp.get("/clinicians/<clinician_id>/licenses")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_licenses(clinician_id):
    require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    license_type = qenum("license_type", LICENSE_TYPES)
    issuing_state = qstr("issuing_state")
    verification_status = qenum(
        "verification_status", {"UNVERIFIED", "VERIFIED", "EXPIRED", "FAILED"}
    )
    out = [ser("licenses", r) for r in sort_asc(all_rows("licenses")) if r.get("clinician_id") == clinician_id]
    if license_type is not None:
        out = [r for r in out if r.get("license_type") == license_type]
    if issuing_state is not None:
        out = [r for r in out if r.get("issuing_state") == issuing_state]
    if verification_status is not None:
        out = [r for r in out if r.get("verification_status") == verification_status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.post("/clinicians/<clinician_id>/licenses/<license_id>/verify")
@require_roles("ComplianceOfficer")
def verify_license(clinician_id, license_id):
    ident = _identity()
    row = _license_or_404(clinician_id, license_id)
    clinician = get("clinicians", clinician_id)
    expires_on = parse_ts(row.get("expires_on"))

    row["verification_attempts"] = int(row.get("verification_attempts") or 0) + 1
    if expires_on is not None and expires_on > now():
        row["verification_status"] = "VERIFIED"
        row["verified_at"] = fmt_ts(now())
        row["verified_by_user_id"] = ident
        row["verify_attempt_failed"] = False
        row["reset_since_failure"] = False
    else:
        row["verification_status"] = "FAILED"
        row["verified_at"] = None
        row["verify_attempt_failed"] = True
        row["reset_since_failure"] = False
    refresh_posture(clinician)
    touch(clinician)
    touch(row)
    return ok(ser("licenses", row), 200)


@bp.post("/clinicians/<clinician_id>/licenses/<license_id>/reverify")
@require_roles("ComplianceOfficer")
def reverify_license(clinician_id, license_id):
    ident = _identity()
    row = _license_or_404(clinician_id, license_id)
    body = Body.read()
    replacement = body.instant("replacement_expires_on")
    body.finish()
    if replacement <= now():
        raise fail("ERR_INVALID_REQUEST", "replacement_expires_on must be strictly after the clock.")
    clinician = get("clinicians", clinician_id)

    row["expires_on"] = fmt_ts(replacement)
    row["verification_status"] = "VERIFIED"
    row["verified_at"] = fmt_ts(now())
    row["verified_by_user_id"] = ident
    row["verification_attempts"] = int(row.get("verification_attempts") or 0) + 1
    row["verify_attempt_failed"] = False
    row["reset_since_failure"] = False
    refresh_posture(clinician)
    touch(clinician)
    touch(row)
    return ok(ser("licenses", row), 200)


@bp.post("/clinicians/<clinician_id>/licenses/<license_id>/reset-verification")
@require_roles("ComplianceOfficer")
def reset_verification(clinician_id, license_id):
    row = _license_or_404(clinician_id, license_id)
    clinician = get("clinicians", clinician_id)
    row["verification_status"] = "UNVERIFIED"
    row["verified_at"] = None
    row["verify_attempt_failed"] = False
    row["reset_since_failure"] = True
    refresh_posture(clinician)
    touch(clinician)
    touch(row)
    return ok(ser("licenses", row), 200)


# ---------------------------------------------------------------- malpractice


@bp.post("/clinicians/<clinician_id>/malpractice-policies")
@require_roles("OpsAdmin")
def create_policy(clinician_id):
    clinician = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    body = Body.read()
    carrier_name = body.string("carrier_name")
    coverage_cents = body.integer("coverage_cents", minimum=0)
    effective_on = body.instant("effective_on")
    expires_on = body.instant("expires_on")
    tail_coverage = body.boolean("tail_coverage")
    body.finish()

    row = create_row(
        "malpractice_policies",
        clinician_id=clinician["id"],
        carrier_name=carrier_name,
        coverage_cents=coverage_cents,
        effective_on=fmt_ts(effective_on),
        expires_on=fmt_ts(expires_on),
        tail_coverage=tail_coverage,
        _effective_on_dt=effective_on,
        _expires_on_dt=expires_on,
    )
    set_derived(row, "policy_status", policy_status(row))
    refresh_posture(clinician)
    touch(clinician)
    return ok(ser("malpractice_policies", row), 201)


@bp.get("/clinicians/<clinician_id>/malpractice-policies")
@require_roles("OpsAdmin", "ComplianceOfficer")
def list_policies(clinician_id):
    require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    status = qenum("policy_status", {"PENDING", "ACTIVE", "LAPSED"})
    out = [
        ser("malpractice_policies", r)
        for r in sort_asc(all_rows("malpractice_policies"))
        if r.get("clinician_id") == clinician_id
    ]
    if status is not None:
        out = [r for r in out if r.get("policy_status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


def _identity():
    from middleware import identity

    return identity()["id"]