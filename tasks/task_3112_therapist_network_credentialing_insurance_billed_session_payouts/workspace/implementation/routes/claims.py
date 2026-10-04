"""Claim submission, adjudication and recovery (PRD §3.5)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from calc import claim_amounts, final_adjudicated, session_rate_cents
from errors import fail
from middleware import Body, qenum, qstr, require_roles
from response import ok, paginate
from serializers import ser
from store import (
    DENIAL_CODES,
    all_rows,
    benefit_status,
    create_row,
    enrollment_covers,
    get,
    newest_line,
    newest_payable_line,
    newest_verified_snapshot,
    notes_for,
    now,
    refresh_posture,
    require,
    set_derived,
    sort_asc,
    touch,
)
from util import fmt_ts, parse_ts

bp = Blueprint("claims", __name__)

CLAIM_STATUSES = {"DRAFT", "SUBMITTED", "PAID", "DENIED", "REPROCESSING", "WRITTEN_OFF"}


def _claim_or_404(claim_id):
    return require("claims", claim_id, "ERR_CLAIM_NOT_FOUND")


@bp.post("/claims")
@require_roles("OpsAdmin")
def create_claim():
    body = Body.read()
    session_id = body.string("session_id")
    body.finish()

    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    if session.get("status") != "COMPLETED":
        raise fail("ERR_INVALID_STATE")
    # PRD §2.9: "a resource that is not in a state from which the requested
    # transition is declared is rejected with `ERR_INVALID_STATE`".  Submitting a
    # claim is declared from a COMPLETED session whose billing axis is still
    # UNBILLED — §3.5 advances the axis to `CLAIM_SUBMITTED` and records
    # `claim_id` on success — so a second submission against the same session has
    # no declared transition and must not mint a duplicate claim.
    if session.get("billing_state") != "UNBILLED" or session.get("claim_id") is not None:
        raise fail("ERR_INVALID_STATE")

    clinician = require("clinicians", session.get("clinician_id"), "ERR_CLINICIAN_NOT_FOUND")
    patient = require("patients", session.get("patient_id"), "ERR_PATIENT_NOT_FOUND")

    refresh_posture(clinician)
    if clinician.get("billing_posture") != "BILLABLE":
        raise fail("ERR_CLINICIAN_NOT_BILLABLE")

    notes = notes_for(session["id"])
    signed = [n for n in notes if n.get("status") == "SIGNED"]
    if notes:
        newest = notes[-1]
        if newest.get("status") != "SIGNED":
            if signed:
                raise fail("ERR_NOTE_SUPERSEDED")
            raise fail("ERR_DOCUMENTATION_MISSING")
    if len(signed) != 1:
        raise fail("ERR_DOCUMENTATION_MISSING")

    _eligibility(clinician, patient, session)

    snapshot = newest_verified_snapshot(patient["id"])
    if snapshot is None or benefit_status(patient) != "VERIFIED":
        raise fail("ERR_BENEFIT_UNVERIFIED")

    amounts = claim_amounts(patient, snapshot, session)

    claim = create_row(
        "claims",
        session_id=session["id"],
        patient_id=patient["id"],
        payer_id=patient.get("payer_id"),
        clinician_id=clinician["id"],
        submitted_on=fmt_ts(now()),
        billed_cents=amounts["billed_cents"],
        allowed_cents=amounts["allowed_cents"],
        patient_resp_cents=0,
        payer_paid_cents=0,
        _pending_patient_resp_cents=amounts["patient_resp_cents"],
        _pending_payer_paid_cents=amounts["payer_paid_cents"],
        claim_status="DRAFT",
        denial_code=None,
        recovery_deadline=None,
        resubmission_count=0,
        assigned_payout_line_id=None,
    )
    claim["claim_status"] = "SUBMITTED"

    session["billing_state"] = "CLAIM_SUBMITTED"
    session["claim_id"] = claim["id"]
    _bump(session)
    return ok(ser("claims", claim), 201)


def _eligibility(clinician, patient, session):
    payer = get("payers", patient.get("payer_id"))
    if payer is None:
        raise fail("ERR_PAYER_NOT_FOUND")
    if payer.get("status") != "ACTIVE":
        raise fail("ERR_SERVICE_NOT_ENROLLED")
    if session.get("cpt_code") not in (payer.get("allowed_cpt_codes") or []):
        raise fail("ERR_SERVICE_NOT_ENROLLED")
    start = session.get("_start_dt")
    _, verdict = enrollment_covers(clinician["id"], payer["id"], start)
    if verdict == "outside":
        raise fail("ERR_OUTSIDE_ENROLLMENT_WINDOW")
    if verdict == "none":
        raise fail("ERR_SERVICE_NOT_ENROLLED")


def _bump(row, derived=None):
    if derived:
        for key, value in derived.items():
            row[key] = value
    row["version"] = int(row.get("version") or 1) + 1
    row["updated_at"] = fmt_ts(now())


@bp.get("/claims")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_claims():
    session_id = qstr("session_id")
    status = qenum("claim_status", CLAIM_STATUSES)
    payer_id = qstr("payer_id")
    out = [ser("claims", r) for r in sort_asc(all_rows("claims"))]
    if session_id is not None:
        out = [r for r in out if r.get("session_id") == session_id]
    if status is not None:
        out = [r for r in out if r.get("claim_status") == status]
    if payer_id is not None:
        out = [r for r in out if r.get("payer_id") == payer_id]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/claims/<claim_id>")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def get_claim(claim_id):
    row = _claim_or_404(claim_id)
    return ok(ser("claims", row), 200)


@bp.get("/claims/<claim_id>/payout-line")
@require_roles("OpsAdmin", "Clinician", "ComplianceOfficer")
def claim_payout_lines(claim_id):
    claim = _claim_or_404(claim_id)
    session_id = claim.get("session_id")
    out = [
        ser("payout_lines", line)
        for line in sort_asc(all_rows("payout_lines"))
        if session_id in (line.get("session_ids") or [])
    ]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


# ---------------------------------------------------------------- adjudicate


def adjudicate(claim, outcome, denial_code):
    session = require("sessions", claim.get("session_id"), "ERR_SESSION_NOT_FOUND")
    clinician = get("clinicians", claim.get("clinician_id"))
    patient = get("patients", claim.get("patient_id"))
    status = claim.get("claim_status")

    if outcome == "PAID":
        if status not in ("SUBMITTED",):
            raise fail("ERR_INVALID_STATE")
        if int(claim.get("allowed_cents") or 0) < 0:
            raise fail("ERR_INVALID_STATE")
        claim["claim_status"] = "PAID"
        claim["patient_resp_cents"] = int(claim.get("_pending_patient_resp_cents") or 0)
        claim["payer_paid_cents"] = int(claim.get("_pending_payer_paid_cents") or 0)
        if session is not None:
            session["billing_state"] = "PAYER_PAID"
            _bump(session)
        if patient is not None:
            cap = int(patient.get("oop_max_cents") or 0)
            patient["oop_met_cents"] = min(
                int(patient.get("oop_met_cents") or 0) + int(claim.get("patient_resp_cents") or 0), cap
            )
            _bump(patient)
        touch(claim)
        _commit_earning(claim, clinician)
        return

    if outcome != "DENIED":
        raise fail("ERR_INVALID_REQUEST", "outcome must be PAID or DENIED.")
    if not denial_code:
        raise fail("ERR_INVALID_REQUEST", "denial_code is required when the outcome is DENIED.")
    if denial_code not in DENIAL_CODES:
        raise fail("ERR_INVALID_REQUEST", "denial_code is not a declared value.")
    if status not in ("SUBMITTED", "PAID"):
        raise fail("ERR_INVALID_STATE")

    was_paid = status == "PAID"
    claim["claim_status"] = "DENIED"
    claim["denial_code"] = denial_code
    _set_recovery_deadline(claim)
    if session is not None:
        session["billing_state"] = "DENIED"
        _bump(session)
    if was_paid:
        if clinician is not None:
            set_derived(clinician, "payout_balance_cents", _balance(clinician))
        _clawback(claim, session, clinician)
    touch(claim)


def _set_recovery_deadline(claim):
    payer = get("payers", claim.get("payer_id"))
    submitted = parse_ts(claim.get("submitted_on"))
    if payer is None or submitted is None:
        claim["recovery_deadline"] = None
        return
    claim["recovery_deadline"] = fmt_ts(submitted + timedelta(days=int(payer.get("timely_filing_days") or 0)))


def _balance(clinician):
    from store import payout_balance_cents

    return payout_balance_cents(clinician)


def _commit_earning(claim, clinician):
    """PRD §3.6: the earning lands on the clinician's newest PENDING/PAID line."""
    if clinician is None:
        return
    session = get("sessions", claim.get("session_id"))
    if session is None:
        return
    line = newest_payable_line(clinician["id"])
    if line is None:
        return
    if session["id"] in (line.get("session_ids") or []):
        claim["assigned_payout_line_id"] = line["id"]
        return
    line.setdefault("session_ids", []).append(session["id"])
    line.setdefault("claim_ids", []).append(claim["id"])
    line["gross_cents"] = int(line.get("gross_cents") or 0) + session_rate_cents(session)
    line["net_cents"] = int(line.get("gross_cents") or 0) + int(line.get("adjustment_cents") or 0)
    claim["assigned_payout_line_id"] = line["id"]
    touch(line)
    set_derived(clinician, "payout_balance_cents", _balance(clinician))
    touch(clinician)


def _clawback(claim, session, clinician):
    """PRD §3.6 'Clawbacks and residuals'."""
    if session is None or clinician is None:
        return
    from store import line_for_session

    line = line_for_session(session["id"])
    if line is None:
        return
    rate = session_rate_cents(session)
    line["adjustment_cents"] = int(line.get("adjustment_cents") or 0) - rate
    gross = int(line.get("gross_cents") or 0)
    adjusted = gross + int(line.get("adjustment_cents") or 0)
    if line.get("line_status") == "PENDING":
        if adjusted < 0:
            clinician["pending_clawback_residual_cents"] = int(
                clinician.get("pending_clawback_residual_cents") or 0
            ) + (-adjusted)
            line["net_cents"] = 0
        else:
            line["net_cents"] = adjusted
    else:
        line["net_cents"] = adjusted
        if line.get("line_status") == "PAID" and int(line.get("adjustment_cents") or 0) < 0:
            line["line_status"] = "CLAWED_BACK"
    claim["assigned_payout_line_id"] = line["id"]
    touch(line)
    set_derived(clinician, "payout_balance_cents", _balance(clinician))
    touch(clinician)


@bp.post("/claims/<claim_id>/adjudicate")
@require_roles("OpsAdmin")
def adjudicate_claim(claim_id):
    claim = _claim_or_404(claim_id)
    body = Body.read()
    outcome = body.enum("outcome", {"PAID", "DENIED"})
    denial_code = body.optional_string("denial_code")
    body.finish()
    adjudicate(claim, outcome, denial_code)
    return ok(ser("claims", claim), 200)


@bp.post("/_inject/claim-outcome")
@require_roles("OpsAdmin")
def inject_claim_outcome():
    body = Body.read()
    claim_id = body.string("claim_id")
    claim = require("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    outcome = body.enum("outcome", {"PAID", "DENIED"})
    denial_code = body.optional_string("denial_code")
    body.finish()
    adjudicate(claim, outcome, denial_code)
    return ok(ser("claims", claim), 201)


@bp.post("/claims/<claim_id>/resubmit")
@require_roles("OpsAdmin")
def resubmit_claim(claim_id):
    claim = _claim_or_404(claim_id)
    if claim.get("claim_status") != "DENIED":
        raise fail("ERR_INVALID_STATE")
    session = get("sessions", claim.get("session_id"))
    clinician = get("clinicians", claim.get("clinician_id"))
    if clinician is not None:
        refresh_posture(clinician)
        if clinician.get("billing_posture") != "BILLABLE":
            raise fail("ERR_CLINICIAN_NOT_BILLABLE")

    recovery = parse_ts(claim.get("recovery_deadline"))
    if recovery is not None and not now() < recovery:
        raise fail("ERR_TIMELY_FILING_EXPIRED")
    if int(claim.get("resubmission_count") or 0) > 1:
        raise fail("ERR_RESUBMISSION_LIMIT_REACHED")

    claim["resubmission_count"] = int(claim.get("resubmission_count") or 0) + 1
    claim["claim_status"] = "REPROCESSING"
    claim["denial_code"] = None
    if session is not None:
        session["billing_state"] = "CLAIM_SUBMITTED"
        _bump(session)
    touch(claim)
    return ok(ser("claims", claim), 200)


@bp.post("/claims/<claim_id>/decide-reprocessing")
@require_roles("OpsAdmin")
def decide_reprocessing(claim_id):
    claim = _claim_or_404(claim_id)
    if claim.get("claim_status") != "REPROCESSING":
        raise fail("ERR_INVALID_STATE")
    body = Body.read()
    outcome = body.enum("outcome", {"ACCEPTED", "REJECTED"})
    body.finish()

    session = get("sessions", claim.get("session_id"))
    if outcome == "ACCEPTED":
        claim["claim_status"] = "SUBMITTED"
        claim["submitted_on"] = fmt_ts(now())
        if session is not None:
            session["billing_state"] = "CLAIM_SUBMITTED"
            _bump(session)
    else:
        claim["claim_status"] = "DENIED"
        claim["denial_code"] = "DUPLICATE"
        _set_recovery_deadline(claim)
        if session is not None:
            session["billing_state"] = "DENIED"
            _bump(session)
    touch(claim)
    return ok(ser("claims", claim), 200)


@bp.post("/claims/<claim_id>/write-off")
@require_roles("OpsAdmin")
def write_off_claim(claim_id):
    claim = _claim_or_404(claim_id)
    if claim.get("claim_status") not in ("SUBMITTED", "DENIED"):
        raise fail("ERR_INVALID_STATE")
    recovery = parse_ts(claim.get("recovery_deadline"))
    at_deadline = recovery is not None and now() >= recovery
    limit_reached = int(claim.get("resubmission_count") or 0) == 2
    if not at_deadline and not limit_reached:
        raise fail("ERR_WRITE_OFF_NOT_ALLOWED")

    session = get("sessions", claim.get("session_id"))
    clinician = get("clinicians", claim.get("clinician_id"))
    claim["claim_status"] = "WRITTEN_OFF"
    if session is not None:
        session["billing_state"] = "WRITTEN_OFF"
        _bump(session)
    _clawback(claim, session, clinician)
    touch(claim)
    return ok(ser("claims", claim), 200)