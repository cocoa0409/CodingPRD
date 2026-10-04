"""PatientClient, BenefitVerification and match endpoints (PRD §3.3, §3.7)."""
from __future__ import annotations

from flask import Blueprint

from calc import provisional_quote, session_rate_cents
from errors import fail
from middleware import Body, qenum, qstr, require_roles
from response import ok, paginate
from serializers import ser
from store import (
    active_patient_count,
    all_rows,
    benefit_status,
    create_row,
    get,
    license_effective_status,
    newest_line,
    now,
    refresh_posture,
    require,
    set_derived,
    sort_asc,
    touch,
)
from util import fmt_ts

bp = Blueprint("patients", __name__)


def benefit_status_of(patient):
    return benefit_status(patient)


@bp.post("/patients")
@require_roles("OpsAdmin")
def create_patient():
    body = Body.read()
    full_name = body.string("full_name")
    member_id = body.string("member_id")
    payer_id = body.string("payer_id")
    plan_code = body.string("plan_code")
    state_code = body.string("state_code")
    deductible_cents = body.integer("deductible_cents", minimum=0)
    coinsurance_rate = body.number("coinsurance_rate", minimum=0.0, maximum=1.0)
    oop_max_cents = body.integer("oop_max_cents", minimum=0)
    body.finish()

    require("payers", payer_id, "ERR_PAYER_NOT_FOUND")
    for existing in all_rows("patients"):
        if existing.get("payer_id") == payer_id and existing.get("member_id") == member_id:
            raise fail("ERR_INVALID_REQUEST", "member_id must be unique within the payer.")

    row = create_row(
        "patients",
        full_name=full_name,
        member_id=member_id,
        payer_id=payer_id,
        plan_code=plan_code,
        state_code=state_code,
        deductible_cents=deductible_cents,
        coinsurance_rate=coinsurance_rate,
        oop_max_cents=oop_max_cents,
        oop_met_cents=0,
        benefit_status="UNVERIFIED",
        matched_clinician_id=None,
        swap_requested=False,
        visit_count_year=0,
    )
    return ok(ser("patients", row), 201)


@bp.get("/patients")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_patients():
    payer_id = qstr("payer_id")
    state_code = qstr("state_code")
    status = qenum("benefit_status", {"UNVERIFIED", "VERIFIED", "STALE"})
    matched = qstr("matched_clinician_id")
    out = [ser("patients", r) for r in sort_asc(all_rows("patients"))]
    if payer_id is not None:
        out = [r for r in out if r.get("payer_id") == payer_id]
    if state_code is not None:
        out = [r for r in out if r.get("state_code") == state_code]
    if status is not None:
        out = [r for r in out if r.get("benefit_status") == status]
    if matched is not None:
        out = [r for r in out if r.get("matched_clinician_id") == matched]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)


@bp.get("/patients/<patient_id>")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician", "Patient")
def get_patient(patient_id):
    row = require("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    return ok(ser("patients", row), 200)


# ---------------------------------------------------------------- match


@bp.post("/patients/<patient_id>/match")
@require_roles("OpsAdmin")
def match_patient(patient_id):
    patient = require("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    body = Body.read()
    requested_tags = body.string_list("specialty_tags")
    body.finish()

    eligible = []
    for clinician in all_rows("clinicians"):
        if clinician.get("status") != "ACTIVE":
            continue
        if clinician.get("billing_posture") != "BILLABLE":
            continue
        enrollments = [
            e
            for e in all_rows("payer_enrollments")
            if e.get("clinician_id") == clinician["id"] and e.get("status") == "EFFECTIVE"
        ]
        if patient.get("payer_id") not in [e.get("payer_id") for e in enrollments]:
            continue
        shared = set(clinician.get("specialty_tags") or []) & set(requested_tags)
        if not shared:
            continue
        geography_ok = clinician.get("primary_state") == patient.get("state_code")
        if not geography_ok:
            geography_ok = any(
                l.get("issuing_state") == patient.get("state_code") and l.get("telehealth_eligible")
                for l in all_rows("licenses")
                if l.get("clinician_id") == clinician["id"]
            )
        if not geography_ok:
            continue
        if active_patient_count(clinician) >= int(clinician.get("weekly_caseload_target") or 0):
            continue
        eligible.append((clinician, len(shared)))

    if not eligible:
        raise fail("ERR_NO_ELIGIBLE_CLINICIAN")

    ranked = sorted(
        eligible,
        key=lambda pair: (
            -pair[1],
            active_patient_count(pair[0]),
            pair[0].get("created_at") or "",
        ),
    )
    if len(ranked) > 1:
        first = (
            ranked[0][1],
            active_patient_count(ranked[0][0]),
            ranked[0][0].get("created_at") or "",
        )
        second = (
            ranked[1][1],
            active_patient_count(ranked[1][0]),
            ranked[1][0].get("created_at") or "",
        )
        if first == second:
            raise fail("ERR_MATCH_TIE_UNRESOLVABLE")

    chosen = ranked[0][0]
    previous = get("clinicians", patient.get("matched_clinician_id"))
    if previous is not None and previous["id"] != chosen["id"]:
        set_derived(previous, "active_patient_count", active_patient_count(previous))
        touch(previous)
    patient["matched_clinician_id"] = chosen["id"]
    set_derived(chosen, "active_patient_count", active_patient_count(chosen))
    touch(chosen)
    touch(patient)
    return ok(ser("patients", patient), 200)


# ---------------------------------------------------------------- verification


@bp.post("/patients/<patient_id>/verification")
@require_roles("OpsAdmin")
def create_verification(patient_id):
    patient = require("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    body = Body.read()
    deductible_remaining_cents = body.integer("deductible_remaining_cents", minimum=0)
    coinsurance_rate = body.number("coinsurance_rate", minimum=0.0, maximum=1.0)
    copay_cents = body.integer("copay_cents", minimum=0)
    oop_remaining_cents = body.integer("oop_remaining_cents", minimum=0)
    body.finish()

    _eligibility_gate(patient)

    row = create_row(
        "benefit_verifications",
        patient_id=patient["id"],
        payer_id=patient.get("payer_id"),
        deductible_remaining_cents=deductible_remaining_cents,
        coinsurance_rate=coinsurance_rate,
        copay_cents=copay_cents,
        oop_remaining_cents=oop_remaining_cents,
        status="VERIFIED",
        verified_at=fmt_ts(now()),
    )
    set_derived(row, "quoted_cost_share_cents", provisional_quote(row, 0))
    patient["benefit_status"] = benefit_status(patient)
    touch(patient)
    return ok(ser("benefit_verifications", row), 201)


def _eligibility_gate(patient):
    """The verified payer must be on the network and ACTIVE (PRD §2.9 referential gate)."""
    payer = get("payers", patient.get("payer_id"))
    if payer is None:
        raise fail("ERR_PAYER_NOT_FOUND")
    if payer.get("status") != "ACTIVE":
        raise fail("ERR_SERVICE_NOT_ENROLLED")


@bp.get("/patients/<patient_id>/verification")
@require_roles("OpsAdmin", "ComplianceOfficer", "Clinician")
def list_verifications(patient_id):
    require("patients", patient_id, "ERR_PATIENT_NOT_FOUND")
    status = qenum("status", {"VERIFIED", "STALE", "FAILED"})
    out = [
        ser("benefit_verifications", r)
        for r in sort_asc(all_rows("benefit_verifications"))
        if r.get("patient_id") == patient_id
    ]
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    window, meta = paginate(out, qstr("limit"), qstr("offset"))
    return ok(window, 200, meta)