"""Catalog (Course) and section (Offering) endpoints, including the census
fork and its four-hop cancellation cascade."""
from flask import Blueprint, request

import calc
import domain
from core import (DB, D, base_record, body, as_str, as_int, as_decimal, as_enum,
                  as_dt, as_id, authenticate, envelope_object, fail, get_course,
                  get_learner, get_offering, now, own, paginate, qfilter, touch)

bp = Blueprint("catalog", __name__)

ALL_AUTH = ("ProgramAdmin", "Registrar", "Learner", "Instructor", "CorporateSponsor")
DELIVERY_MODES = ("IN_PERSON", "ONLINE_SYNC", "ONLINE_ASYNC")
SCHEDULING_MODES = ("TERM", "ROLLING")


def _creates_cycle(new_course_id, prerequisite_id):
    seen = set()
    cursor = prerequisite_id
    while cursor is not None:
        if cursor == new_course_id or cursor in seen:
            return True
        seen.add(cursor)
        parent = DB.courses.get(cursor)
        if parent is None:
            return False
        cursor = parent["prerequisite_course_id"]
    return False


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

@bp.post("/courses")
def create_course():
    authenticate(("ProgramAdmin",))
    payload = body()
    course_code = as_str(payload, "course_code", min_len=1, max_len=32)
    title = as_str(payload, "title")
    ceu_units = as_decimal(payload, "ceu_units", gt=0, lte=10.0, max_places=1)
    contact_hours = as_decimal(payload, "contact_hours", gt=0)
    list_price_cents = as_int(payload, "list_price_cents", minimum=0)
    delivery_mode = as_enum(payload, "delivery_mode", DELIVERY_MODES)
    cpl_credit_units = as_decimal(payload, "cpl_credit_units", gt=0, max_places=1)
    prerequisite_course_id = as_id(payload, "prerequisite_course_id", required=False)

    for existing in DB.courses.values():
        if existing["course_code"] == course_code:
            fail("ERR_INVALID_REQUEST", "course_code must be unique")

    if prerequisite_course_id is not None:
        get_course(prerequisite_course_id)

    rec = base_record()
    if prerequisite_course_id is not None and _creates_cycle(rec["id"], prerequisite_course_id):
        fail("ERR_INVALID_REQUEST", "prerequisite_course_id would form a cycle")

    rec.update({
        "course_code": course_code,
        "title": title,
        "ceu_units": ceu_units,
        "contact_hours": contact_hours,
        "list_price_cents": list_price_cents,
        "delivery_mode": delivery_mode,
        "prerequisite_course_id": prerequisite_course_id,
        "cpl_credit_units": cpl_credit_units,
        "status": "ACTIVE",
        "active_offering_count": 0,
    })
    DB.courses[rec["id"]] = rec
    return envelope_object(domain.ser_course(rec)), 201


@bp.get("/courses")
def list_courses():
    authenticate(ALL_AUTH)
    rows = list(DB.courses.values())
    rows = qfilter(rows, "status")
    rows = qfilter(rows, "prerequisite_course_id")
    rows = qfilter(rows, "delivery_mode")
    return paginate(rows, domain.ser_course), 200


@bp.get("/courses/<cid>")
def read_course(cid):
    authenticate(ALL_AUTH)
    return envelope_object(domain.ser_course(get_course(cid))), 200


@bp.post("/courses/<cid>/retire")
def retire_course(cid):
    authenticate(("ProgramAdmin",))
    course = get_course(cid)
    if course["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Course is not ACTIVE")
    if course["active_offering_count"] != 0:
        fail("ERR_INVALID_STATE", "Course still has live offerings")
    course["status"] = "RETIRED"
    touch(course)
    return envelope_object(domain.ser_course(course)), 200


# ---------------------------------------------------------------------------
# Offerings
# ---------------------------------------------------------------------------

@bp.post("/offerings")
def create_offering():
    authenticate(("ProgramAdmin",))
    payload = body()
    course_id = as_id(payload, "course_id")
    scheduling_mode = as_enum(payload, "scheduling_mode", SCHEDULING_MODES)
    term_code = as_str(payload, "term_code", required=False, allow_null=True)
    if scheduling_mode == "TERM" and term_code is None:
        fail("ERR_INVALID_REQUEST", "term_code is required for a TERM offering")
    if scheduling_mode == "ROLLING" and term_code is not None:
        fail("ERR_INVALID_REQUEST", "term_code must be omitted for a ROLLING offering")
    start_date = as_dt(payload, "start_date")
    end_date = as_dt(payload, "end_date")
    census_at = as_dt(payload, "census_at")
    session_count = as_int(payload, "session_count", minimum=1)
    min_enrollment = as_int(payload, "min_enrollment", minimum=1)
    max_enrollment = as_int(payload, "max_enrollment", minimum=0)
    tuition_cents = as_int(payload, "tuition_cents", minimum=0)
    if not end_date > start_date:
        fail("ERR_INVALID_REQUEST", "end_date must be strictly after start_date")
    if census_at > start_date:
        fail("ERR_INVALID_REQUEST", "census_at must be no later than start_date")
    if max_enrollment < min_enrollment:
        fail("ERR_INVALID_REQUEST", "max_enrollment must be >= min_enrollment")

    course = get_course(course_id)
    if course["status"] != "ACTIVE":
        fail("ERR_COURSE_RETIRED", "Course is RETIRED")

    rec = base_record()
    rec.update({
        "course_id": course_id,
        "scheduling_mode": scheduling_mode,
        "term_code": term_code,
        "start_date": start_date,
        "end_date": end_date,
        "census_at": census_at,
        "session_count": session_count,
        "min_enrollment": min_enrollment,
        "max_enrollment": max_enrollment,
        "tuition_cents": tuition_cents,
        "status": "DRAFT",
        "cancellation_reason": None,
        "confirmed_enrollment_count": 0,
        "paid_enrollment_count": 0,
        "waitlist_count": 0,
        "net_program_revenue_cents": 0,
    })
    DB.offerings[rec["id"]] = rec
    course["active_offering_count"] += 1
    touch(course)
    return envelope_object(domain.ser_offering(rec)), 201


@bp.get("/offerings")
def list_offerings():
    authenticate(ALL_AUTH)
    rows = list(DB.offerings.values())
    rows = qfilter(rows, "course_id")
    rows = qfilter(rows, "term_code")
    rows = qfilter(rows, "status")
    rows = qfilter(rows, "scheduling_mode")
    return paginate(rows, domain.ser_offering), 200


@bp.get("/offerings/<oid>")
def read_offering(oid):
    authenticate(ALL_AUTH)
    return envelope_object(domain.ser_offering(get_offering(oid))), 200


@bp.post("/offerings/<oid>/open")
def open_offering(oid):
    authenticate(("ProgramAdmin",))
    offering = get_offering(oid)
    if offering["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Offering is not DRAFT")
    course = DB.courses[offering["course_id"]]
    if course["status"] != "ACTIVE":
        fail("ERR_COURSE_RETIRED", "Backing course is RETIRED")
    staffed = [c for c in domain.contracts_of_offering(oid)
               if c["status"] in ("SIGNED", "ACTIVE")]
    if not staffed:
        fail("ERR_INVALID_STATE", "No SIGNED or ACTIVE instructor contract on this offering")
    if not now() < offering["start_date"]:
        fail("ERR_INVALID_STATE", "The logical clock has already reached start_date")
    offering["status"] = "OPEN"
    touch(offering)
    return envelope_object(domain.ser_offering(offering)), 200


def _census_lock(offering):
    headcount = offering["paid_enrollment_count"]
    for contract in domain.contracts_of_offering(offering["id"]):
        if contract["status"] in ("OFFERED", "SIGNED", "ACTIVE"):
            contract["census_headcount"] = headcount
            touch(contract)
    for reg in domain.regs_of_offering(offering["id"]):
        if reg["payment_status"] == "VOUCHER_COMMITTED":
            reg["payment_status"] = "PAID"
            touch(reg)
            if reg["voucher_id"] is not None:
                voucher = DB.vouchers[reg["voucher_id"]]
                domain.voucher_consume(voucher, reg["total_due_cents"])
    offering["status"] = "CENSUS_LOCKED"
    domain.recompute_offering_revenue(offering)
    touch(offering)


def _census_cancel(offering):
    # HOP 1
    offering["status"] = "CANCELLED"
    offering["cancellation_reason"] = "MIN_ENROLLMENT_NOT_MET"
    # HOP 2 / 3 / 4
    for reg in domain.regs_of_offering(offering["id"]):
        if reg["enrollment_status"] not in ("PENDING", "ENROLLED", "WAITLISTED"):
            continue
        previous_enrollment = reg["enrollment_status"]
        previous_payment = reg["payment_status"]
        reg["enrollment_status"] = "WITHDRAWN"
        if previous_payment in ("PAID", "VOUCHER_COMMITTED", "PARTIALLY_REFUNDED"):
            reg["payment_status"] = "REFUNDED"
            reg["amount_refunded_cents"] = reg["amount_paid_cents"]
        touch(reg)
        if previous_enrollment == "ENROLLED":
            offering["confirmed_enrollment_count"] -= 1
            offering["paid_enrollment_count"] -= 1
        elif previous_enrollment == "WAITLISTED":
            offering["waitlist_count"] -= 1
        if reg["voucher_id"] is not None and previous_payment in (
                "PAID", "VOUCHER_COMMITTED", "PARTIALLY_REFUNDED"):
            voucher = DB.vouchers[reg["voucher_id"]]
            domain.voucher_release(voucher, reg["total_due_cents"])
    # FAN-OUT over teaching staff
    for contract in domain.contracts_of_offering(offering["id"]):
        if contract["status"] not in ("OFFERED", "SIGNED", "ACTIVE"):
            continue
        instructor = DB.instructors[contract["instructor_id"]]
        was_counted = contract["status"] in ("SIGNED", "ACTIVE")
        contract["kill_fee_cents"] = calc.instructor_kill_fee(contract, instructor)
        contract["status"] = "TERMINATED_NO_FAULT"
        touch(contract)
        if was_counted:
            domain.recompute_active_contract_count(instructor)
            touch(instructor)
    domain.recompute_offering_revenue(offering)
    touch(offering)


@bp.post("/offerings/<oid>/census")
def census_offering(oid):
    authenticate(("ProgramAdmin",))
    offering = get_offering(oid)
    if offering["status"] not in ("OPEN", "WAITLIST_ONLY"):
        fail("ERR_INVALID_STATE", "Offering is not OPEN or WAITLIST_ONLY")
    if now() < offering["census_at"]:
        fail("ERR_CENSUS_TOO_EARLY", "The logical clock has not reached census_at")
    if offering["paid_enrollment_count"] >= offering["min_enrollment"]:
        _census_lock(offering)
    else:
        _census_cancel(offering)
    course = DB.courses[offering["course_id"]]
    domain.recompute_active_offering_count(course)
    return envelope_object(domain.ser_offering(offering)), 200


@bp.post("/offerings/<oid>/complete")
def complete_offering(oid):
    authenticate(("ProgramAdmin",))
    offering = get_offering(oid)
    if offering["status"] != "CENSUS_LOCKED":
        fail("ERR_INVALID_STATE", "Offering is not CENSUS_LOCKED")
    if now() < offering["end_date"]:
        fail("ERR_OFFERING_NOT_ENDED", "The logical clock has not reached end_date")
    for reg in domain.regs_of_offering(oid):
        if reg["enrollment_status"] == "ENROLLED":
            reg["enrollment_status"] = "NO_SHOW"
            touch(reg)
        elif reg["enrollment_status"] in ("PENDING", "WAITLISTED"):
            if reg["enrollment_status"] == "WAITLISTED":
                offering["waitlist_count"] -= 1
            reg["enrollment_status"] = "WITHDRAWN"
            reg["payment_status"] = "REFUNDED"
            reg["amount_refunded_cents"] = reg["amount_paid_cents"]
            touch(reg)
    offering["status"] = "COMPLETED"
    domain.recompute_offering_revenue(offering)
    touch(offering)
    course = DB.courses[offering["course_id"]]
    domain.recompute_active_offering_count(course)
    return envelope_object(domain.ser_offering(offering)), 200


# ---------------------------------------------------------------------------
# Registration creation (offering-scoped)
# ---------------------------------------------------------------------------

def prerequisite_satisfied(learner_id, prerequisite_course_id):
    for record in DB.completion_records.values():
        if record["learner_id"] != learner_id or record["status"] != "ISSUED":
            continue
        reg = DB.registrations.get(record["registration_id"])
        if reg is None:
            continue
        off = DB.offerings.get(reg["offering_id"])
        if off is not None and off["course_id"] == prerequisite_course_id:
            return True
    for petition in DB.cpl_petitions.values():
        if (petition["learner_id"] == learner_id
                and petition["status"] == "APPROVED"
                and petition["target_course_id"] == prerequisite_course_id):
            return True
    return False


def _windows_overlap_closed(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.post("/offerings/<oid>/registrations")
def create_registration(oid):
    actor = authenticate(("Learner", "Registrar"))
    payload = body()
    learner_id = as_id(payload, "learner_id")
    expected_offering_version = as_int(payload, "expected_offering_version")

    offering = get_offering(oid)
    learner = get_learner(learner_id)

    if actor.role == "Learner":
        own(actor.user_id == learner_id)

    if expected_offering_version != offering["version"]:
        fail("ERR_STALE_VERSION", "expected_offering_version does not match")

    if offering["status"] not in ("OPEN", "WAITLIST_ONLY"):
        fail("ERR_OFFERING_NOT_OPEN", "Offering is not OPEN or WAITLIST_ONLY")

    course = DB.courses[offering["course_id"]]
    prerequisite_course_id = course["prerequisite_course_id"]
    if prerequisite_course_id is not None:
        if not prerequisite_satisfied(learner_id, prerequisite_course_id):
            fail("ERR_PREREQUISITE_NOT_MET", "Prerequisite course not satisfied")

    load = D(course["ceu_units"])
    for reg in domain.regs_of_learner(learner_id):
        if reg["enrollment_status"] not in ("PENDING", "ENROLLED", "WAITLISTED"):
            continue
        other = DB.offerings.get(reg["offering_id"])
        if other is None:
            continue
        if _windows_overlap_closed(other["start_date"], other["end_date"],
                                   offering["start_date"], offering["end_date"]):
            load += D(DB.courses[other["course_id"]]["ceu_units"])
    if load > calc.MAX_CONCURRENT_CEU:
        fail("ERR_LEARNER_LOAD_EXCEEDED", "Concurrent CEU load exceeded")

    for reg in domain.regs_of_learner(learner_id):
        if (reg["offering_id"] == oid
                and reg["enrollment_status"] in ("PENDING", "ENROLLED",
                                                 "WAITLISTED", "COMPLETED")):
            fail("ERR_DUPLICATE_REGISTRATION", "Learner is already registered")

    if (offering["status"] == "WAITLIST_ONLY"
            and offering["waitlist_count"] >= calc.WAITLIST_CAP):
        fail("ERR_OFFERING_FULL", "Waitlist is full")

    rec = domain.create_registration(offering, learner)
    touch(offering)
    return envelope_object(domain.ser_registration(rec)), 201
