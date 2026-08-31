"""Registration payment/attendance/completion, instructor contracting and
completion-record endpoints."""
from flask import Blueprint, request

import calc
import domain
from core import (DB, D, base_record, body, as_str, as_int, as_enum, as_id,
                  authenticate, envelope_object, fail, get_completion,
                  get_contract, get_instructor, get_offering, get_registration,
                  get_voucher, now, own, paginate, qfilter, touch)

bp = Blueprint("registrations", __name__)

PAY_METHODS = ("SELF_PAY", "VOUCHER")
SIGN_DECISIONS = ("ACCEPT", "DECLINE")
PAY_BASES = ("CENSUS_LOCKED", "FINAL_COMPLETION")


def _instructor_contract_on(offering_id, instructor_id, statuses):
    for contract in domain.contracts_of_offering(offering_id):
        if contract["instructor_id"] == instructor_id and contract["status"] in statuses:
            return contract
    return None


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

@bp.get("/registrations")
def list_registrations():
    authenticate(("ProgramAdmin", "Registrar", "Learner", "Instructor"))
    rows = list(DB.registrations.values())
    rows = qfilter(rows, "offering_id")
    rows = qfilter(rows, "learner_id")
    rows = qfilter(rows, "voucher_id")
    rows = qfilter(rows, "transferred_to_registration_id")
    rows = qfilter(rows, "enrollment_status")
    rows = qfilter(rows, "payment_status")
    return paginate(rows, domain.ser_registration), 200


@bp.get("/registrations/<rid>")
def read_registration(rid):
    authenticate(("ProgramAdmin", "Registrar", "Learner", "Instructor"))
    return envelope_object(domain.ser_registration(get_registration(rid))), 200


@bp.post("/registrations/<rid>/pay")
def pay_registration(rid):
    actor = authenticate(("Learner", "Registrar"))
    payload = body()
    method = as_enum(payload, "method", PAY_METHODS)
    voucher_id = as_id(payload, "voucher_id", required=(method == "VOUCHER"))

    reg = get_registration(rid)
    voucher = get_voucher(voucher_id) if (method == "VOUCHER" and voucher_id) else None

    if actor.role == "Learner":
        own(actor.user_id == reg["learner_id"])

    offering = DB.offerings[reg["offering_id"]]
    if offering["status"] not in ("OPEN", "WAITLIST_ONLY"):
        fail("ERR_OFFERING_NOT_OPEN", "Offering is not OPEN or WAITLIST_ONLY")

    if reg["payment_status"] != "UNPAID" or reg["enrollment_status"] != "PENDING":
        fail("ERR_INVALID_STATE", "Registration is not PENDING x UNPAID")

    if method == "VOUCHER":
        account = DB.corporate_accounts[voucher["corporate_account_id"]]
        usable = (voucher["status"] in ("ASSIGNED", "PARTIALLY_REDEEMED")
                  and voucher["assigned_learner_id"] == reg["learner_id"]
                  and now() < voucher["expires_at"]
                  and account["status"] == "ACTIVE")
        if not usable:
            fail("ERR_VOUCHER_NOT_USABLE", "Voucher is not usable")
        if voucher["remaining_cents"] < reg["total_due_cents"]:
            fail("ERR_VOUCHER_INSUFFICIENT_BALANCE", "Voucher balance is insufficient")
        reg["voucher_id"] = voucher_id
        reg["payment_status"] = "VOUCHER_COMMITTED"
        reg["amount_paid_cents"] = reg["total_due_cents"]
        touch(reg)
        domain.voucher_commit(voucher, reg["total_due_cents"])
    else:
        reg["payment_status"] = "PAID"
        reg["amount_paid_cents"] = reg["total_due_cents"]
        touch(reg)

    closed = domain.seat_resolution(reg, offering)
    domain.recompute_offering_revenue(offering)
    touch(offering)
    if closed:
        touch(offering)
    return envelope_object(domain.ser_registration(reg)), 200


@bp.post("/registrations/<rid>/attendance")
def record_attendance(rid):
    actor = authenticate(("Instructor", "Registrar"))
    payload = body()
    sessions_attended = as_int(payload, "sessions_attended", minimum=0)
    reg = get_registration(rid)
    if actor.role == "Instructor":
        own(_instructor_contract_on(reg["offering_id"], actor.user_id,
                                    ("SIGNED", "ACTIVE")) is not None)
    reg["sessions_attended"] = sessions_attended
    touch(reg)
    return envelope_object(domain.ser_registration(reg)), 200


@bp.post("/registrations/<rid>/complete")
def complete_registration(rid):
    actor = authenticate(("Instructor",))
    reg = get_registration(rid)
    own(_instructor_contract_on(reg["offering_id"], actor.user_id,
                                ("ACTIVE",)) is not None)
    offering = DB.offerings[reg["offering_id"]]
    if reg["enrollment_status"] != "ENROLLED":
        fail("ERR_INVALID_STATE", "Registration is not ENROLLED")
    if offering["status"] != "CENSUS_LOCKED":
        fail("ERR_INVALID_STATE", "Offering is not CENSUS_LOCKED")

    ratio = calc.attendance_ratio(reg)
    if ratio < calc.MIN_ATTENDANCE_RATIO:
        fail("ERR_ATTENDANCE_BELOW_THRESHOLD", "Attendance ratio is below 0.80")

    course = DB.courses[offering["course_id"]]
    ceu_awarded = calc.ceu_award(course)

    # HOP 1
    reg["enrollment_status"] = "COMPLETED"
    touch(reg)

    # HOP 2
    sequence = 1 + len([cr for cr in DB.completion_records.values()
                        if DB.registrations[cr["registration_id"]]["offering_id"]
                        == offering["id"]])
    label = offering["term_code"] if offering["term_code"] else "ROLL"
    record = base_record()
    record.update({
        "registration_id": reg["id"],
        "learner_id": reg["learner_id"],
        "ceu_awarded": ceu_awarded,
        "attendance_ratio": ratio,
        "certificate_number": "CEU-%s-%04d" % (label, sequence),
        "issued_at": now(),
        "status": "ISSUED",
    })
    DB.completion_records[record["id"]] = record

    # HOP 3
    learner = DB.learners[reg["learner_id"]]
    domain.recompute_learner_totals(learner)
    touch(learner)

    # HOP 4
    domain.marketing_segment_recompute(learner)

    domain.recompute_offering_revenue(offering)
    touch(offering)
    return envelope_object(domain.ser_completion(record)), 201


# ---------------------------------------------------------------------------
# Instructor contracts
# ---------------------------------------------------------------------------

@bp.post("/instructor-contracts")
def create_contract():
    authenticate(("ProgramAdmin",))
    payload = body()
    offering_id = as_id(payload, "offering_id")
    instructor_id = as_id(payload, "instructor_id")
    base_stipend_cents = as_int(payload, "base_stipend_cents", minimum=0)
    per_enrollment_cents = as_int(payload, "per_enrollment_cents", minimum=0)
    enrollment_cap_for_pay = as_int(payload, "enrollment_cap_for_pay", minimum=0)
    pay_basis = as_enum(payload, "pay_basis", PAY_BASES, required=False,
                        default="CENSUS_LOCKED")
    get_offering(offering_id)
    get_instructor(instructor_id)
    rec = base_record()
    rec.update({
        "offering_id": offering_id,
        "instructor_id": instructor_id,
        "base_stipend_cents": base_stipend_cents,
        "per_enrollment_cents": per_enrollment_cents,
        "enrollment_cap_for_pay": enrollment_cap_for_pay,
        "pay_basis": pay_basis,
        "status": "OFFERED",
        "census_headcount": None,
        "final_headcount": None,
        "settled_pay_cents": None,
        "kill_fee_cents": None,
    })
    DB.instructor_contracts[rec["id"]] = rec
    return envelope_object(domain.ser_contract(rec)), 201


@bp.get("/instructor-contracts")
def list_contracts():
    authenticate(("ProgramAdmin", "Registrar", "Instructor"))
    rows = list(DB.instructor_contracts.values())
    rows = qfilter(rows, "offering_id")
    rows = qfilter(rows, "instructor_id")
    rows = qfilter(rows, "status")
    return paginate(rows, domain.ser_contract), 200


@bp.get("/instructor-contracts/<cid>")
def read_contract(cid):
    authenticate(("ProgramAdmin", "Registrar", "Instructor"))
    return envelope_object(domain.ser_contract(get_contract(cid))), 200


def _windows_overlap_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/instructor-contracts/<cid>/sign")
def sign_contract(cid):
    actor = authenticate(("Instructor",))
    payload = body()
    decision = as_enum(payload, "decision", SIGN_DECISIONS)
    contract = get_contract(cid)
    own(actor.user_id == contract["instructor_id"])
    if contract["status"] != "OFFERED":
        fail("ERR_INVALID_STATE", "Contract is not OFFERED")
    offering = DB.offerings[contract["offering_id"]]
    if offering["status"] not in ("DRAFT", "OPEN", "WAITLIST_ONLY"):
        fail("ERR_INVALID_STATE", "Offering is no longer open for staffing")

    if decision == "DECLINE":
        contract["status"] = "DECLINED"
        touch(contract)
        return envelope_object(domain.ser_contract(contract)), 200

    for other in DB.instructor_contracts.values():
        if other["id"] == contract["id"]:
            continue
        if other["instructor_id"] != contract["instructor_id"]:
            continue
        if other["status"] not in ("SIGNED", "ACTIVE"):
            continue
        other_offering = DB.offerings.get(other["offering_id"])
        if other_offering is None:
            continue
        if _windows_overlap_half_open(other_offering["start_date"],
                                      other_offering["end_date"],
                                      offering["start_date"],
                                      offering["end_date"]):
            fail("ERR_INSTRUCTOR_SCHEDULE_CONFLICT",
                 "Instructor already staffs an overlapping offering")

    contract["status"] = "SIGNED"
    touch(contract)
    instructor = DB.instructors[contract["instructor_id"]]
    domain.recompute_active_contract_count(instructor)
    touch(instructor)
    return envelope_object(domain.ser_contract(contract)), 200


@bp.post("/instructor-contracts/<cid>/activate")
def activate_contract(cid):
    authenticate(("ProgramAdmin",))
    contract = get_contract(cid)
    if contract["status"] != "SIGNED":
        fail("ERR_INVALID_STATE", "Contract is not SIGNED")
    offering = DB.offerings[contract["offering_id"]]
    if offering["status"] != "CENSUS_LOCKED":
        fail("ERR_INVALID_STATE", "Offering is not CENSUS_LOCKED")
    contract["status"] = "ACTIVE"
    touch(contract)
    return envelope_object(domain.ser_contract(contract)), 200


@bp.post("/instructor-contracts/<cid>/settle")
def settle_contract(cid):
    authenticate(("ProgramAdmin",))
    contract = get_contract(cid)
    if contract["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Contract is not ACTIVE")
    offering = DB.offerings[contract["offering_id"]]
    if offering["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE", "Offering is not COMPLETED")
    instructor = DB.instructors[contract["instructor_id"]]
    contract["final_headcount"] = len(
        [r for r in domain.regs_of_offering(offering["id"])
         if r["enrollment_status"] == "COMPLETED"])
    contract["settled_pay_cents"] = calc.instructor_contract_pay(contract, instructor)
    contract["status"] = "SETTLED"
    touch(contract)
    domain.recompute_active_contract_count(instructor)
    touch(instructor)
    return envelope_object(domain.ser_contract(contract)), 200


# ---------------------------------------------------------------------------
# Completion records
# ---------------------------------------------------------------------------

@bp.get("/completion-records")
def list_completions():
    authenticate(("ProgramAdmin", "Registrar", "Learner", "Instructor"))
    rows = list(DB.completion_records.values())
    rows = qfilter(rows, "registration_id")
    rows = qfilter(rows, "learner_id")
    rows = qfilter(rows, "status")
    return paginate(rows, domain.ser_completion), 200


@bp.get("/completion-records/<crid>")
def read_completion(crid):
    authenticate(("ProgramAdmin", "Registrar", "Learner", "Instructor"))
    return envelope_object(domain.ser_completion(get_completion(crid))), 200


@bp.get("/completion-records/<crid>/citations")
def list_record_citations(crid):
    authenticate(("ProgramAdmin", "Registrar", "Learner"))
    get_completion(crid)
    rows = [c for c in DB.cpl_citations.values()
            if c["completion_record_id"] == crid]
    return paginate(rows, domain.ser_citation), 200


@bp.post("/completion-records/<crid>/revoke")
def revoke_completion(crid):
    authenticate(("Registrar",))
    record = get_completion(crid)
    if record["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "Completion record is not ISSUED")
    for citation in domain.citations_of_record(crid):
        petition = DB.cpl_petitions.get(citation["petition_id"])
        if petition is not None and petition["status"] == "APPROVED":
            fail("ERR_CITATION_NOT_ELIGIBLE",
                 "Record is cited by an APPROVED CPL petition")
    record["status"] = "REVOKED"
    touch(record)
    reg = DB.registrations.get(record["registration_id"])
    if reg is not None and reg["enrollment_status"] == "COMPLETED":
        reg["enrollment_status"] = "NO_SHOW"
        touch(reg)
    learner = DB.learners[record["learner_id"]]
    domain.recompute_learner_totals(learner)
    touch(learner)
    domain.marketing_segment_recompute(learner)
    return envelope_object(domain.ser_completion(record)), 200
