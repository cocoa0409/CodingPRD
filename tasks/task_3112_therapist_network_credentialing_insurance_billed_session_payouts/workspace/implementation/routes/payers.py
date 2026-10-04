"""Payer, PayerRate and PayerEnrollment endpoints, plus the payer cascades (PRD §3.2, §3.8)."""
from __future__ import annotations

from flask import Blueprint

from errors import fail
from middleware import Body, qbool, qenum, qstr, require_roles
from response import ok, paginate
from serializers import ser
from store import (
    LICENSE_TYPES,
    all_rows,
    create_row,
    get,
    license_effective_status,
    now,
    payout_balance_cents,
    policy_status,
    refresh_posture,
    refresh_all_postures,
    require,
    set_derived,
    sort_asc,
    table,
    touch,
)
from calc import session_rate_cents
from util import fmt_ts, minutes_between, parse_ts
from store import newest_payable_line

bp = Blueprint("payers", __name__)

PAYER_STATUSES = {"ACTIVE", "SUSPENDED_AT_PAYER", "TERMINATED"}
ENROLLMENT_STATUSES = {"PENDING", "EFFECTIVE", "SUSPENDED", "TERMINATED", "REJECTED"}


# ---------------------------------------------------------------- payers


@bp.post("/payers")
@require_roles("OpsAdmin")
def create_payer():
    body = Body.read()
    payer_name = body.string("payer_name")
    payer_code = body.string("payer_code")
    delegated_credentialing = body.boolean("delegated_credentialing")
    min_malpractice_coverage_cents = body.integer("min_malpractice_coverage_cents", minimum=0)
    timely_filing_days = body.integer("timely_filing_days", minimum=1)
    credentialing_sla_days = body.integer("credentialing_sla_days", minimum=0)
    allowed_cpt_codes = body.string_list("allowed_cpt_codes")
    body.finish()

    if any(p.get("payer_code") == payer_code for p in all_rows("payers")):
        raise fail("ERR_INVALID_REQUEST", "payer_code must be unique across payers.")

    row = create_row(
        "payers",
        payer_name=payer_name,
        payer_code=payer_code,
        delegated_credentialing=delegated_credentialing,
        min_malpractice_coverage_cents=min_malpractice_coverage_cents,
        timely_filing_days=timely_filing_days,
        credentialing_sla_days=credentialing_sla_days,
        allowed_cpt_codes=allowed_cpt_codes,
        status="ACTIVE",
    )
    return ok(ser("payers", row), 201)


@bp.get("/payers")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_payers():
    status = qenum("status", PAYER_STATUSES)
    delegated = qbool("delegated_credentialing")
    out = [ser("payers", r) for r in sort_asc(all_rows("payers"))]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    if delegated is not None:
        out = [r for r in out if r.get("delegated_credentialing") == delegated]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/payers/<payer_id>")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def get_payer(payer_id):
    row = require("payers", payer_id, "ERR_PAYER_NOT_FOUND")
    return ok(ser("payers", row), 200)


@bp.patch("/payers/<payer_id>")
@require_roles("OpsAdmin")
def patch_payer(payer_id):
    row = require("payers", payer_id, "ERR_PAYER_NOT_FOUND")
    body = Body.read()
    target = body.enum("status", PAYER_STATUSES)
    body.finish()

    current = row.get("status")
    if target == current:
        raise fail("ERR_INVALID_STATE")
    if current == "TERMINATED":
        raise fail("ERR_ALREADY_TERMINAL")
    if target == "ACTIVE" and current != "SUSPENDED_AT_PAYER":
        raise fail("ERR_INVALID_STATE")
    if target == "SUSPENDED_AT_PAYER" and current != "ACTIVE":
        raise fail("ERR_INVALID_STATE")

    row["status"] = target
    touch(row)

    if target == "SUSPENDED_AT_PAYER":
        _cascade_suspend(row)
    elif target == "TERMINATED":
        _cascade_terminate(row)
    return ok(ser("payers", row), 200)


def _cascade_suspend(payer):
    """PRD §3.8: three hops.  Enrollments are never auto-restored."""
    for enrollment in all_rows("payer_enrollments"):
        if enrollment.get("payer_id") != payer["id"]:
            continue
        if enrollment.get("status") != "EFFECTIVE":
            continue
        enrollment["status"] = "SUSPENDED"
        touch(enrollment)
        clinician = get("clinicians", enrollment.get("clinician_id"))
        if clinician is not None:
            set_derived(clinician, "enrolled_payer_count", _effective_count(clinician))
            refresh_posture(clinician)
            if clinician.get("billing_posture") == "FROZEN":
                _cancel_open_sessions(clinician)
            touch(clinician)


def _cascade_terminate(payer):
    """PRD §3.8: enrollments terminate, in-flight claims are denied, and every
    claim denied in the sweep "appends a clawback adjustment to its clinician's
    newest payout line".

    Each clinician touched by the sweep is settled once, after every one of their
    claims on this payer has been denied: the clawbacks accumulate on the target
    line and the line's status is decided once from the *total* adjustment, which
    is what lets §3.6's rules hold at the same time — an unpaid line keeps its
    `PENDING` status with its net floored at zero, and a line that has already
    been disbursed becomes `CLAWED_BACK` rather than staying `PENDING`.
    """
    touched = []
    for enrollment in all_rows("payer_enrollments"):
        if enrollment.get("payer_id") != payer["id"]:
            continue
        if enrollment.get("status") in ("PENDING", "EFFECTIVE", "SUSPENDED"):
            enrollment["status"] = "TERMINATED"
            touch(enrollment)
            clinician = get("clinicians", enrollment.get("clinician_id"))
            if clinician is not None:
                set_derived(clinician, "enrolled_payer_count", _effective_count(clinician))
                refresh_posture(clinician)
                if clinician.get("billing_posture") == "FROZEN":
                    _cancel_open_sessions(clinician)
                touch(clinician)

    clawbacks = {}
    for claim in all_rows("claims"):
        if claim.get("payer_id") != payer["id"]:
            continue
        if claim.get("claim_status") != "SUBMITTED":
            continue
        claim["claim_status"] = "DENIED"
        claim["denial_code"] = "NOT_COVERED"
        touch(claim)
        session = get("sessions", claim.get("session_id"))
        if session is not None:
            set_derived(session, "billing_state", "DENIED")
            touch(session)
        clinician = get("clinicians", session.get("clinician_id")) if session else None
        if clinician is None:
            continue
        clawbacks.setdefault(clinician["id"], []).append((claim, session))

    for clinician_id, items in clawbacks.items():
        clinician = get("clinicians", clinician_id)
        if clinician is None:
            continue
        line = _target_line(clinician)
        for claim, session in items:
            _append_clawback(clinician, line, claim, session)


def _target_line(clinician):
    """The line a payer-termination clawback lands on: the clinician's newest
    non-voided line, or a fresh zero-gross `PENDING` line when none is in
    `PENDING` or `PAID` status."""
    line = newest_payable_line(clinician["id"])
    if line is not None:
        return line
    for existing in all_rows("payout_lines"):
        if existing.get("clinician_id") != clinician["id"]:
            continue
        if existing.get("line_status") == "VOIDED":
            continue
        existing["line_status"] = "PENDING"
        touch(existing)
        return existing
    line = create_row(
        "payout_lines",
        payout_batch_id=None,
        clinician_id=clinician["id"],
        session_ids=[],
        claim_ids=[],
        gross_cents=0,
        adjustment_cents=0,
        net_cents=0,
        line_status="PENDING",
        basis="SCHEDULED",
        rate_set_version_used=None,
    )
    return line


def _append_clawback(clinician, line, claim, session):
    """PRD §3.6: "Against a session on a `PENDING` line, the adjustment is the
    negative of the resolved session rate ... Against a session on a `PAID` line,
    the adjustment is likewise the negative of the resolved session rate but the
    net is allowed to go negative with no floor."

    The status is re-decided from the line's total adjustment, so the original
    status has to survive on its own field rather than being overwritten by an
    earlier hop of the same sweep.
    """
    rate = session_rate_cents(session)
    base = line.get("_status_before_clawback")
    if base is None:
        base = line.get("line_status")
        if base not in ("PENDING", "PAID"):
            base = "PAID"
        line["_status_before_clawback"] = base
    line["adjustment_cents"] = int(line.get("adjustment_cents") or 0) - rate
    adjusted = int(line.get("gross_cents") or 0) + int(line.get("adjustment_cents") or 0)
    if claim.get("id") not in (line.get("claim_ids") or []):
        line.setdefault("claim_ids", []).append(claim["id"])
    if session.get("id") not in (line.get("session_ids") or []):
        line.setdefault("session_ids", []).append(session["id"])
    if base == "PENDING":
        if adjusted < 0:
            clinician["pending_clawback_residual_cents"] = int(
                clinician.get("pending_clawback_residual_cents") or 0
            ) + (-adjusted)
            line["net_cents"] = 0
        else:
            line["net_cents"] = adjusted
    else:
        line["net_cents"] = adjusted
        if int(line.get("adjustment_cents") or 0) < 0:
            line["line_status"] = "CLAWED_BACK"
    claim["assigned_payout_line_id"] = line["id"]
    touch(line)
    set_derived(clinician, "payout_balance_cents", payout_balance_cents(clinician))
    touch(clinician)
    if line.get("payout_batch_id") is not None:
        _refresh_batch_totals(line.get("payout_batch_id"))


def _effective_count(clinician):
    return len(
        [
            e
            for e in all_rows("payer_enrollments")
            if e.get("clinician_id") == clinician["id"] and e.get("status") == "EFFECTIVE"
        ]
    )


def _cancel_open_sessions(clinician):
    from routes.clinicians import cancel_open_sessions

    cancel_open_sessions(clinician)


def _line_for_session(session_id):
    from store import line_for_session

    return line_for_session(session_id)


def _refresh_batch_totals(batch_id):
    batch = get("payout_batches", batch_id)
    if batch is None:
        return
    if batch.get("status") == "OPEN":
        return
    lines = [
        l
        for l in all_rows("payout_lines")
        if l.get("payout_batch_id") == batch_id and l.get("line_status") != "VOIDED"
    ]
    batch["total_gross_cents"] = sum(int(l.get("gross_cents") or 0) for l in lines)
    batch["total_adjustment_cents"] = sum(int(l.get("adjustment_cents") or 0) for l in lines)
    batch["total_net_cents"] = sum(int(l.get("net_cents") or 0) for l in lines)
    batch["line_count"] = len(lines)


# ---------------------------------------------------------------- rates


@bp.post("/payers/<payer_id>/rates")
@require_roles("OpsAdmin")
def create_rate(payer_id):
    payer = require("payers", payer_id, "ERR_PAYER_NOT_FOUND")
    body = Body.read()
    rate_set_version = body.integer("rate_set_version", minimum=1)
    license_type = body.enum("license_type", LICENSE_TYPES)
    geography = body.string("geography")
    cpt_code = body.string("cpt_code")
    rate_cents = body.integer("rate_cents", minimum=0)
    effective_from = body.instant("effective_from")
    effective_to = body.instant("effective_to", required=False)
    body.finish()

    for existing in all_rows("payer_rates"):
        if (
            existing.get("payer_id") == payer["id"]
            and existing.get("rate_set_version") == rate_set_version
            and existing.get("license_type") == license_type
            and existing.get("geography") == geography
            and existing.get("cpt_code") == cpt_code
            and parse_ts(existing.get("effective_from")) == effective_from
        ):
            raise fail("ERR_DUPLICATE_RATE")

    row = create_row(
        "payer_rates",
        payer_id=payer["id"],
        rate_set_version=rate_set_version,
        license_type=license_type,
        geography=geography,
        cpt_code=cpt_code,
        rate_cents=rate_cents,
        effective_from=fmt_ts(effective_from),
        effective_to=fmt_ts(effective_to),
    )
    return ok(ser("payer_rates", row), 201)


@bp.get("/payers/<payer_id>/rates")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_rates(payer_id):
    require("payers", payer_id, "ERR_PAYER_NOT_FOUND")
    license_type = qenum("license_type", LICENSE_TYPES)
    geography = qstr("geography")
    cpt_code = qstr("cpt_code")
    version = qstr("rate_set_version")
    out = [ser("payer_rates", r) for r in sort_asc(all_rows("payer_rates")) if r.get("payer_id") == payer_id]
    if license_type is not None:
        out = [r for r in out if r.get("license_type") == license_type]
    if geography is not None:
        out = [r for r in out if r.get("geography") == geography]
    if cpt_code is not None:
        out = [r for r in out if r.get("cpt_code") == cpt_code]
    if version is not None:
        out = [r for r in out if str(r.get("rate_set_version")) == version]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


# ---------------------------------------------------------------- enrollments


def _pinned_version(payer_id, license_type, primary_state, effective_from):
    best = None
    for row in all_rows("payer_rates"):
        if row.get("payer_id") != payer_id:
            continue
        if row.get("license_type") != license_type:
            continue
        if row.get("geography") != primary_state:
            continue
        eff_from = parse_ts(row.get("effective_from"))
        eff_to = parse_ts(row.get("effective_to"))
        if eff_from is None or effective_from < eff_from:
            continue
        if eff_to is not None and effective_from >= eff_to:
            continue
        version = int(row.get("rate_set_version") or 0)
        if best is None or version > best:
            best = version
    return best


@bp.post("/payer-enrollments")
@require_roles("OpsAdmin")
def create_enrollment():
    body = Body.read()
    clinician_id = body.string("clinician_id")
    payer_id = body.string("payer_id")
    delegated = body.boolean("delegated")
    effective_from = body.instant("effective_from")
    effective_to = body.instant("effective_to", required=False)
    body.finish()

    clinician = require("clinicians", clinician_id, "ERR_CLINICIAN_NOT_FOUND")
    require("payers", payer_id, "ERR_PAYER_NOT_FOUND")
    if effective_to is not None and effective_to <= effective_from:
        raise fail("ERR_ENROLLMENT_WINDOW_INVALID")

    row = create_row(
        "payer_enrollments",
        clinician_id=clinician["id"],
        payer_id=payer_id,
        delegated=delegated,
        effective_from=fmt_ts(effective_from),
        effective_to=fmt_ts(effective_to),
        status="PENDING",
        rate_set_version_pinned=None,
        effective_window_days=None,
    )
    return ok(ser("payer_enrollments", row), 201)


@bp.get("/payer-enrollments")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_enrollments():
    clinician_id = qstr("clinician_id")
    payer_id = qstr("payer_id")
    status = qenum("status", ENROLLMENT_STATUSES)
    out = [ser("payer_enrollments", r) for r in sort_asc(all_rows("payer_enrollments"))]
    if clinician_id is not None:
        out = [r for r in out if r.get("clinician_id") == clinician_id]
    if payer_id is not None:
        out = [r for r in out if r.get("payer_id") == payer_id]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/payers/<payer_id>/payer-enrollments")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_payer_enrollments(payer_id):
    require("payers", payer_id, "ERR_PAYER_NOT_FOUND")
    status = qenum("status", ENROLLMENT_STATUSES)
    out = [
        ser("payer_enrollments", r)
        for r in sort_asc(all_rows("payer_enrollments"))
        if r.get("payer_id") == payer_id
    ]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/payer-enrollments/<enrollment_id>")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def get_enrollment(enrollment_id):
    row = require("payer_enrollments", enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")
    return ok(ser("payer_enrollments", row), 200)


def _enrollment_or_404(enrollment_id):
    return require("payer_enrollments", enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")


@bp.post("/payer-enrollments/<enrollment_id>/activate")
@require_roles("OpsAdmin")
def activate_enrollment(enrollment_id):
    row = _enrollment_or_404(enrollment_id)
    if row.get("status") != "PENDING":
        raise fail("ERR_INVALID_STATE")
    clinician = require("clinicians", row.get("clinician_id"), "ERR_CLINICIAN_NOT_FOUND")
    payer = require("payers", row.get("payer_id"), "ERR_PAYER_NOT_FOUND")
    payer_suspended = payer.get("status") != "ACTIVE"
    effective_from = parse_ts(row.get("effective_from"))

    if effective_from is None:
        raise fail("ERR_INVALID_REQUEST")
    if payer_suspended:
        raise fail("ERR_PAYER_SUSPENDED")
    if effective_from > now():
        raise fail("ERR_INVALID_STATE", "effective_from must not be in the future.")

    licenses = [
        l
        for l in all_rows("licenses")
        if l.get("clinician_id") == clinician["id"]
        and l.get("issuing_state") == clinician.get("primary_state")
        and license_effective_status(l) == "VERIFIED"
    ]
    if not licenses:
        raise fail("ERR_INVALID_STATE", "No license in the primary state reads VERIFIED.")
    policies = [
        p
        for p in all_rows("malpractice_policies")
        if p.get("clinician_id") == clinician["id"]
        and int(p.get("coverage_cents") or 0) >= int(payer.get("min_malpractice_coverage_cents") or 0)
        and policy_status(p) == "ACTIVE"
    ]
    if not policies:
        raise fail("ERR_INVALID_STATE", "No malpractice policy meets the payer's floor.")

    row["status"] = "EFFECTIVE"
    row["rate_set_version_pinned"] = _pinned_version(
        payer["id"], clinician.get("license_type"), clinician.get("primary_state"), effective_from
    )
    effective_to = parse_ts(row.get("effective_to"))
    row["effective_window_days"] = (
        minutes_between(effective_from, effective_to) // (60 * 24) if effective_to is not None else None
    )
    set_derived(clinician, "enrolled_payer_count", _effective_count(clinician))
    refresh_posture(clinician)
    touch(clinician)
    touch(row)
    return ok(ser("payer_enrollments", row), 200)


@bp.post("/payer-enrollments/<enrollment_id>/reject")
@require_roles("OpsAdmin")
def reject_enrollment(enrollment_id):
    row = _enrollment_or_404(enrollment_id)
    if row.get("status") != "PENDING":
        raise fail("ERR_INVALID_STATE")
    row["status"] = "REJECTED"
    touch(row)
    return ok(ser("payer_enrollments", row), 200)


@bp.post("/payer-enrollments/<enrollment_id>/suspend")
@require_roles("OpsAdmin")
def suspend_enrollment(enrollment_id):
    row = _enrollment_or_404(enrollment_id)
    if row.get("status") != "EFFECTIVE":
        raise fail("ERR_INVALID_STATE")
    clinician = require("clinicians", row.get("clinician_id"), "ERR_CLINICIAN_NOT_FOUND")
    row["status"] = "SUSPENDED"
    set_derived(clinician, "enrolled_payer_count", _effective_count(clinician))
    refresh_posture(clinician)
    if clinician.get("billing_posture") == "FROZEN":
        _cancel_open_sessions(clinician)
    touch(clinician)
    touch(row)
    return ok(ser("payer_enrollments", row), 200)


@bp.post("/payer-enrollments/<enrollment_id>/reinstate")
@require_roles("OpsAdmin")
def reinstate_enrollment(enrollment_id):
    row = _enrollment_or_404(enrollment_id)
    if row.get("status") != "SUSPENDED":
        raise fail("ERR_INVALID_STATE")
    clinician = require("clinicians", row.get("clinician_id"), "ERR_CLINICIAN_NOT_FOUND")
    effective_from = parse_ts(row.get("effective_from"))
    effective_to = parse_ts(row.get("effective_to"))
    if effective_from is not None and effective_from > now():
        raise fail("ERR_INVALID_STATE", "effective_from must be at or before the clock.")
    if effective_to is not None and effective_to <= now():
        raise fail("ERR_INVALID_STATE", "effective_to must be strictly after the clock.")
    # PRD §3.2's reinstatement guard is a guard on the *enrollment*: the payer's
    # own status is consulted when the enrollment moves, not as a pre-emption of
    # the enrollment's declared-state checks.
    payer = require("payers", row.get("payer_id"), "ERR_PAYER_NOT_FOUND")
    if payer.get("status") != "ACTIVE":
        raise fail("ERR_PAYER_SUSPENDED")

    row["status"] = "EFFECTIVE"
    set_derived(clinician, "enrolled_payer_count", _effective_count(clinician))
    refresh_posture(clinician)
    touch(clinician)
    touch(row)
    return ok(ser("payer_enrollments", row), 200)


@bp.post("/payer-enrollments/<enrollment_id>/terminate")
@require_roles("OpsAdmin")
def terminate_enrollment(enrollment_id):
    row = _enrollment_or_404(enrollment_id)
    if row.get("status") not in ("PENDING", "EFFECTIVE", "SUSPENDED"):
        raise fail("ERR_ALREADY_TERMINAL")
    clinician = get("clinicians", row.get("clinician_id"))
    row["status"] = "TERMINATED"
    if clinician is not None:
        set_derived(clinician, "enrolled_payer_count", _effective_count(clinician))
        refresh_posture(clinician)
        if clinician.get("billing_posture") == "FROZEN":
            _cancel_open_sessions(clinician)
        touch(clinician)
    touch(row)
    return ok(ser("payer_enrollments", row), 200)