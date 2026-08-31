"""Refund/transfer requests, the credit-for-prior-learning petition pathway
and the logical-clock test-driving surface."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
from core import (CLOCK, DB, D, base_record, body, as_decimal, as_enum, as_id,
                  as_str, authenticate, days_between, envelope_object, fail,
                  fmt_dt, get_completion, get_course, get_learner,
                  get_offering, get_petition, get_registration, get_request,
                  now, own, paginate, parse_dt, qfilter, touch)

bp = Blueprint("flow", __name__)

REQUEST_TYPES = ("REFUND", "TRANSFER")
REFUND_BASES = ("POLICY_SCHEDULE", "PRO_RATA_ATTENDANCE")
DECISIONS = ("APPROVE", "DENY")


def _transfer_target_check(source_reg, target_offering):
    if target_offering["id"] == source_reg["offering_id"]:
        fail("ERR_TRANSFER_TARGET_INCOMPATIBLE", "Target is the source offering")
    if target_offering["status"] not in ("OPEN", "WAITLIST_ONLY"):
        fail("ERR_TRANSFER_TARGET_INCOMPATIBLE", "Target offering is not open")
    target_course = DB.courses[target_offering["course_id"]]
    if target_course["status"] != "ACTIVE":
        fail("ERR_TRANSFER_TARGET_INCOMPATIBLE", "Target course is RETIRED")
    source_offering = DB.offerings[source_reg["offering_id"]]
    source_course = DB.courses[source_offering["course_id"]]
    if D(target_course["ceu_units"]) != D(source_course["ceu_units"]):
        fail("ERR_TRANSFER_TARGET_INCOMPATIBLE", "Target course CEU value differs")


# ---------------------------------------------------------------------------
# Refund / transfer requests
# ---------------------------------------------------------------------------

@bp.post("/refund-transfer-requests")
def create_request():
    actor = authenticate(("Learner", "Registrar"))
    payload = body()
    registration_id = as_id(payload, "registration_id")
    request_type = as_enum(payload, "request_type", REQUEST_TYPES)
    refund_basis = as_enum(payload, "refund_basis", REFUND_BASES, required=False,
                           default="POLICY_SCHEDULE")
    target_offering_id = as_id(payload, "target_offering_id", required=False)
    if request_type == "TRANSFER" and target_offering_id is None:
        fail("ERR_INVALID_REQUEST", "target_offering_id is required for a TRANSFER")
    if request_type == "REFUND" and target_offering_id is not None:
        fail("ERR_INVALID_REQUEST", "target_offering_id must be null for a REFUND")

    reg = get_registration(registration_id)
    target_offering = get_offering(target_offering_id) if target_offering_id else None

    if actor.role == "Learner":
        own(actor.user_id == reg["learner_id"])

    if reg["enrollment_status"] != "ENROLLED":
        fail("ERR_INVALID_STATE", "Registration is not ENROLLED")

    offering = DB.offerings[reg["offering_id"]]
    if not now() < offering["end_date"]:
        fail("ERR_REFUND_WINDOW_CLOSED", "The refund window has closed")

    if request_type == "TRANSFER":
        _transfer_target_check(reg, target_offering)

    days_before_start = days_between(offering["start_date"], now())
    if request_type == "REFUND":
        computed = calc.refund_amount(reg, offering, refund_basis)
    else:
        computed = 0

    rec = base_record()
    rec.update({
        "registration_id": registration_id,
        "target_offering_id": target_offering_id,
        "request_type": request_type,
        "refund_basis": refund_basis,
        "days_before_start": days_before_start,
        "computed_refund_cents": computed,
        "status": "SUBMITTED",
        "settled_at": None,
    })
    DB.refund_transfer_requests[rec["id"]] = rec
    return envelope_object(domain.ser_request(rec)), 201


@bp.get("/refund-transfer-requests")
def list_requests():
    authenticate(("ProgramAdmin", "Registrar", "Learner"))
    rows = list(DB.refund_transfer_requests.values())
    rows = qfilter(rows, "registration_id")
    rows = qfilter(rows, "target_offering_id")
    rows = qfilter(rows, "status")
    rows = qfilter(rows, "request_type")
    return paginate(rows, domain.ser_request), 200


@bp.get("/refund-transfer-requests/<rid>")
def read_request(rid):
    authenticate(("ProgramAdmin", "Registrar", "Learner"))
    return envelope_object(domain.ser_request(get_request(rid))), 200


@bp.post("/refund-transfer-requests/<rid>/decide")
def decide_request(rid):
    authenticate(("Registrar",))
    payload = body()
    decision = as_enum(payload, "decision", DECISIONS)
    override_basis = as_enum(payload, "refund_basis", REFUND_BASES, required=False)
    req = get_request(rid)
    if req["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Request is not SUBMITTED")
    reg = DB.registrations[req["registration_id"]]
    if reg["enrollment_status"] != "ENROLLED":
        fail("ERR_INVALID_STATE", "Source registration is no longer ENROLLED")

    if decision == "DENY":
        req["status"] = "DENIED"
        req["computed_refund_cents"] = 0
        touch(req)
        return envelope_object(domain.ser_request(req)), 200

    offering = DB.offerings[reg["offering_id"]]
    if req["request_type"] == "REFUND":
        effective_basis = override_basis or req["refund_basis"]
        req["refund_basis"] = effective_basis
        req["computed_refund_cents"] = calc.refund_amount(reg, offering, effective_basis)
        req["status"] = "REFUND_APPROVED"
        touch(req)
        return envelope_object(domain.ser_request(req)), 200

    target_offering = DB.offerings[req["target_offering_id"]]
    _transfer_target_check(reg, target_offering)
    learner = DB.learners[reg["learner_id"]]
    price = calc.registration_price_resolution(target_offering, learner)
    carried = reg["amount_paid_cents"] - calc.TRANSFER_FEE_CENTS
    if carried < price["total_due_cents"]:
        fail("ERR_TRANSFER_CREDIT_INSUFFICIENT", "Carried credit is insufficient")
    if override_basis is not None:
        req["refund_basis"] = override_basis
    req["status"] = "TRANSFER_APPROVED"
    touch(req)
    return envelope_object(domain.ser_request(req)), 200


def _release_voucher_value(reg):
    if reg["voucher_id"] is None:
        return
    voucher = DB.vouchers.get(reg["voucher_id"])
    if voucher is None:
        return
    domain.voucher_release(voucher, reg["total_due_cents"])


@bp.post("/refund-transfer-requests/<rid>/settle")
def settle_request(rid):
    authenticate(("Registrar",))
    req = get_request(rid)
    if req["status"] not in ("REFUND_APPROVED", "TRANSFER_APPROVED"):
        fail("ERR_INVALID_STATE", "Request is not approved")
    reg = DB.registrations[req["registration_id"]]
    source_offering = DB.offerings[reg["offering_id"]]

    if req["status"] == "REFUND_APPROVED":
        computed = req["computed_refund_cents"]
        previous_payment = reg["payment_status"]
        reg["enrollment_status"] = "WITHDRAWN"
        if previous_payment == "VOUCHER_COMMITTED":
            reg["payment_status"] = "REFUNDED"
            reg["amount_refunded_cents"] = reg["amount_paid_cents"]
        else:
            reg["amount_refunded_cents"] += computed
            if computed == reg["amount_paid_cents"]:
                reg["payment_status"] = "REFUNDED"
            elif 0 < computed < reg["amount_paid_cents"]:
                reg["payment_status"] = "PARTIALLY_REFUNDED"
        touch(reg)
        _release_voucher_value(reg)
        source_offering["confirmed_enrollment_count"] -= 1
        source_offering["paid_enrollment_count"] -= 1
        reverted = domain.seat_release(source_offering)
        domain.recompute_offering_revenue(source_offering)
        touch(source_offering)
        if reverted:
            touch(source_offering)
    else:
        target_offering = DB.offerings[req["target_offering_id"]]
        if target_offering["status"] not in ("OPEN", "WAITLIST_ONLY"):
            fail("ERR_INVALID_STATE", "Target offering is no longer open")
        learner = DB.learners[reg["learner_id"]]
        new_reg = domain.create_registration(target_offering, learner)
        new_reg["amount_paid_cents"] = new_reg["total_due_cents"]
        new_reg["payment_status"] = "PAID"
        closed = domain.seat_resolution(new_reg, target_offering)
        residual = (reg["amount_paid_cents"] - calc.TRANSFER_FEE_CENTS
                    - new_reg["total_due_cents"])
        reg["transferred_to_registration_id"] = new_reg["id"]
        reg["enrollment_status"] = "TRANSFERRED_OUT"
        reg["payment_status"] = "REFUNDED"
        reg["amount_refunded_cents"] += residual
        touch(reg)
        req["computed_refund_cents"] = residual
        source_offering["confirmed_enrollment_count"] -= 1
        source_offering["paid_enrollment_count"] -= 1
        reverted = domain.seat_release(source_offering)
        domain.recompute_offering_revenue(source_offering)
        touch(source_offering)
        if reverted:
            touch(source_offering)
        domain.recompute_offering_revenue(target_offering)
        touch(target_offering)
        if closed:
            touch(target_offering)

    req["settled_at"] = now()
    req["status"] = "SETTLED"
    touch(req)
    return envelope_object(domain.ser_request(req)), 200


# ---------------------------------------------------------------------------
# Credit for prior learning
# ---------------------------------------------------------------------------

@bp.post("/cpl-petitions")
def create_petition():
    actor = authenticate(("Learner", "Registrar"))
    payload = body()
    learner_id = as_id(payload, "learner_id")
    target_course_id = as_id(payload, "target_course_id")
    get_learner(learner_id)
    get_course(target_course_id)
    if actor.role == "Learner":
        own(actor.user_id == learner_id)
    rec = base_record()
    rec.update({
        "learner_id": learner_id,
        "target_course_id": target_course_id,
        "status": "DRAFT",
        "revision_round": 0,
        "assessed_by_user_id": None,
        "claimed_ceu_total": None,
        "awarded_credit_units": None,
        "decision_note": None,
    })
    DB.cpl_petitions[rec["id"]] = rec
    return envelope_object(domain.ser_petition(rec)), 201


@bp.get("/cpl-petitions")
def list_petitions():
    authenticate(("ProgramAdmin", "Registrar", "Learner"))
    rows = list(DB.cpl_petitions.values())
    rows = qfilter(rows, "learner_id")
    rows = qfilter(rows, "target_course_id")
    rows = qfilter(rows, "status")
    return paginate(rows, domain.ser_petition), 200


@bp.get("/cpl-petitions/<pid>")
def read_petition(pid):
    authenticate(("ProgramAdmin", "Registrar", "Learner"))
    return envelope_object(domain.ser_petition(get_petition(pid))), 200


@bp.get("/cpl-petitions/<pid>/citations")
def list_petition_citations(pid):
    authenticate(("ProgramAdmin", "Registrar", "Learner"))
    get_petition(pid)
    rows = [c for c in DB.cpl_citations.values() if c["petition_id"] == pid]
    return paginate(rows, domain.ser_citation), 200


@bp.post("/cpl-petitions/<pid>/citations")
def create_citation(pid):
    actor = authenticate(("Learner",))
    payload = body()
    completion_record_id = as_id(payload, "completion_record_id")
    weight = as_decimal(payload, "weight", gt=0, lte=1.0, max_places=2)
    petition = get_petition(pid)
    record = get_completion(completion_record_id)
    own(actor.user_id == petition["learner_id"])
    if petition["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail("ERR_INVALID_STATE", "Petition is not DRAFT or REVISION_REQUESTED")
    if record["status"] != "ISSUED" or record["learner_id"] != petition["learner_id"]:
        fail("ERR_CITATION_NOT_ELIGIBLE", "Cited completion record is not eligible")
    rec = base_record(versioned=False)
    rec.update({
        "petition_id": pid,
        "completion_record_id": completion_record_id,
        "weight": weight,
    })
    DB.cpl_citations[rec["id"]] = rec
    touch(petition)
    return envelope_object(domain.ser_citation(rec)), 201


@bp.post("/cpl-petitions/<pid>/submit")
def submit_petition(pid):
    actor = authenticate(("Learner",))
    petition = get_petition(pid)
    own(actor.user_id == petition["learner_id"])
    if petition["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail("ERR_INVALID_STATE", "Petition is not DRAFT or REVISION_REQUESTED")
    citations = domain.citations_of_petition(pid)
    if not citations:
        fail("ERR_INVALID_STATE", "Petition carries no citations")
    target_course = DB.courses[petition["target_course_id"]]
    if target_course["status"] != "ACTIVE":
        fail("ERR_COURSE_RETIRED", "Target course is RETIRED")
    for citation in citations:
        record = DB.completion_records.get(citation["completion_record_id"])
        if (record is None or record["status"] != "ISSUED"
                or record["learner_id"] != petition["learner_id"]):
            fail("ERR_CITATION_NOT_ELIGIBLE", "A cited completion record is not eligible")
    for other in DB.cpl_petitions.values():
        if (other["id"] != pid
                and other["learner_id"] == petition["learner_id"]
                and other["target_course_id"] == petition["target_course_id"]
                and other["status"] == "APPROVED"):
            fail("ERR_CPL_DUPLICATE_AWARD", "An APPROVED petition already exists")
    petition["status"] = "SUBMITTED"
    touch(petition)
    return envelope_object(domain.ser_petition(petition)), 200


@bp.post("/cpl-petitions/<pid>/review")
def review_petition(pid):
    actor = authenticate(("ProgramAdmin",))
    petition = get_petition(pid)
    if petition["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Petition is not SUBMITTED")
    petition["assessed_by_user_id"] = actor.user_id
    petition["status"] = "UNDER_REVIEW"
    touch(petition)
    return envelope_object(domain.ser_petition(petition)), 200


@bp.post("/cpl-petitions/<pid>/request-revision")
def request_revision(pid):
    actor = authenticate(("ProgramAdmin",))
    payload = body()
    decision_note = as_str(payload, "decision_note", required=False, allow_null=True)
    petition = get_petition(pid)
    if petition["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Petition is not UNDER_REVIEW")
    if petition["revision_round"] >= calc.MAX_CPL_REVISION_ROUNDS:
        fail("ERR_CPL_REVISION_LIMIT", "Revision budget is exhausted")
    petition["revision_round"] += 1
    petition["assessed_by_user_id"] = actor.user_id
    petition["status"] = "REVISION_REQUESTED"
    if decision_note is not None:
        petition["decision_note"] = decision_note
    touch(petition)
    return envelope_object(domain.ser_petition(petition)), 200


@bp.post("/cpl-petitions/<pid>/decide")
def decide_petition(pid):
    actor = authenticate(("ProgramAdmin",))
    payload = body()
    decision = as_enum(payload, "decision", DECISIONS)
    decision_note = as_str(payload, "decision_note", required=False, allow_null=True)
    petition = get_petition(pid)
    if petition["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Petition is not UNDER_REVIEW")
    if actor.user_id == petition["assessed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The assessor may not decide the petition")
    target_course = DB.courses[petition["target_course_id"]]
    claimed, awarded = calc.cpl_credit_conversion(
        petition, domain.citations_of_petition(pid), DB.completion_records,
        target_course)
    if decision == "APPROVE" and awarded <= 0:
        fail("ERR_CPL_AWARD_ZERO", "The conversion floors to zero credit units")
    petition["claimed_ceu_total"] = claimed
    petition["awarded_credit_units"] = awarded
    petition["decision_note"] = decision_note
    petition["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    touch(petition)
    return envelope_object(domain.ser_petition(petition)), 200


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("ProgramAdmin",))
    payload = body()
    value = payload.get("to_iso8601")
    if value is None:
        fail("ERR_INVALID_REQUEST", "Field 'to_iso8601' is required")
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO 8601 instant")
    CLOCK.set(parsed)
    return envelope_object({"current_utc": fmt_dt(parsed)}), 200
