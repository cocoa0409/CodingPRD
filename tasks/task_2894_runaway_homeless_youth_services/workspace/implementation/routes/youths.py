"""Street outreach, intake, screenings, enrollments and youth-scoped listings."""

from flask import Blueprint

import authz
import calc
import cascade
import envelope
import find
import serial
import shape
import store

bp = Blueprint("youths", __name__)

YOUTH_STATUSES = (
    "PROSPECT",
    "ENGAGED",
    "SHELTERED",
    "TLP_ENROLLED",
    "REUNIFIED_PENDING",
    "REUNIFIED",
    "EXITED",
)
TIERS = ("LOW", "ELEVATED", "CRITICAL")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
SCREENING_STATUSES = ("SUBMITTED", "ESCALATED", "CLEARED")
CASE_STATUSES = (
    "OPENED",
    "MEDIATION_SCHEDULED",
    "MEDIATION_HELD",
    "HOME_ASSESSMENT",
    "APPROVED",
    "DECLINED",
    "AFTERCARE",
    "CLOSED",
    "SUPERSEDED",
)
ENROLLMENT_TYPES = ("PUBLIC_K12", "GED_PROGRAM", "POSTSECONDARY", "VOCATIONAL")
ENROLLMENT_STATUSES = ("IMMEDIATE_ENROLLMENT", "VERIFIED")
VOTE_STATUSES = ("COUNTED", "RETRACTED")


@bp.post("/ryhs/youths")
def intake_youth():
    user_id, _role = authz.require(authz.OUTREACH_WORKER)
    body = shape.body()
    first = shape.need_str(body, "legal_first_name", 1, 80)
    last = shape.need_str(body, "legal_last_name", 1, 80)
    dob = shape.need_date(body, "date_of_birth")
    # PRD 3.1: "When unaccompanied is omitted it defaults to true".
    unaccompanied = shape.opt_bool(body, "unaccompanied", True)

    record = {
        "legal_first_name": first,
        "legal_last_name": last,
        "date_of_birth": dob,
        "unaccompanied": unaccompanied,
        "status": "PROSPECT",
        "risk_posture": "OPEN",
        "trafficking_risk_score": 0,
        "trafficking_risk_tier": "LOW",
        "engagement_contact_count": 0,
        "basic_needs_provision_count": 0,
        "cumulative_shelter_nights": 0,
        "lifetime_savings_deposited_cents": 0,
        "governance_vote_eligible": False,
        "intake_worker_user_id": user_id,
    }
    store.stamp_new(record)
    store.youths[record["id"]] = record
    return envelope.created(serial.youth(record))


@bp.get("/ryhs/youths")
def list_youths():
    authz.require(*authz.STAFF_READ_ALL)
    status = envelope.enum_filter("status", YOUTH_STATUSES)
    tier = envelope.enum_filter("trafficking_risk_tier", TIERS)
    posture = envelope.enum_filter("risk_posture", POSTURES)
    rows = list(store.youths.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if tier is not None:
        rows = [r for r in rows if r["trafficking_risk_tier"] == tier]
    if posture is not None:
        rows = [r for r in rows if r["risk_posture"] == posture]
    return envelope.listing(store.ordered(rows), serial.youth)


@bp.get("/ryhs/youths/<youth_id>")
def read_youth(youth_id):
    user_id, role = authz.require(*(authz.STAFF_READ_ALL + (authz.YOUTH_MEMBER,)))
    # Ladder 3 outranks path resolution: a YouthMember may read only its own record.
    authz.own_youth(user_id, role, youth_id)
    return envelope.ok(serial.youth(find.youth(youth_id)))


@bp.post("/ryhs/youths/<youth_id>/outreach-contacts")
def log_outreach(youth_id):
    user_id, _role = authz.require(authz.OUTREACH_WORKER)
    youth = find.youth(youth_id)
    body = shape.body()
    stage = shape.need_enum(body, "engagement_stage", calc.ENGAGEMENT_STAGES)
    basic_needs = shape.need_code_array(body, "basic_needs_provided", calc.BASIC_NEEDS_CODES)
    indicators = shape.need_code_array(body, "indicator_flags", calc.INDICATOR_CODES)

    record = {
        "youth_id": youth["id"],
        "contacted_at": store.now(),
        "engagement_stage": stage,
        "basic_needs_provided": basic_needs,
        "indicator_flags": indicators,
        "worker_user_id": user_id,
    }
    # PRD 2.4: an OutreachContact is an immutable event record with no version.
    store.stamp_new(record, versioned=False)
    store.outreach_contacts[record["id"]] = record

    # PRD 3.1: a first encounter moves the youth PROSPECT -> ENGAGED; every later
    # encounter is a legitimate self-loop.
    if youth["status"] == "PROSPECT":
        youth["status"] = "ENGAGED"
    youth["engagement_contact_count"] += 1
    youth["basic_needs_provision_count"] += len(basic_needs)
    cascade.apply_trafficking_history(youth)
    cascade.apply_youth_derived(youth)
    # "the youth's version increments by one"
    store.touch(youth)
    return envelope.created(serial.outreach_contact(record))


@bp.get("/ryhs/youths/<youth_id>/outreach-contacts")
def list_outreach(youth_id):
    authz.require(*authz.STAFF_READ_ALL)
    youth = find.youth(youth_id)
    rows = [c for c in store.outreach_contacts.values() if c["youth_id"] == youth["id"]]
    return envelope.listing(store.ordered(rows), serial.outreach_contact)


@bp.post("/ryhs/youths/<youth_id>/safety-screenings")
def submit_screening(youth_id):
    user_id, _role = authz.require(authz.OUTREACH_WORKER, authz.SHELTER_CASE_MANAGER)
    youth = find.youth(youth_id)
    body = shape.body()
    codes = shape.need_code_array(body, "indicator_codes", calc.INDICATOR_CODES)

    score = calc.screening_score(codes)
    record = {
        "youth_id": youth["id"],
        "screened_at": store.now(),
        "indicator_codes": codes,
        "score": score,
        "tier": calc.tier_for(score),
        "status": "SUBMITTED",
        "specialized_response_code": "NONE",
        "screener_user_id": user_id,
        "disposition_user_id": None,
    }
    store.stamp_new(record)
    store.safety_screenings[record["id"]] = record
    # PRD 3.2: "the youth's risk_posture is recomputed on submission, but only a
    # disposition can drive it to FROZEN."
    cascade.refresh_youth(youth)
    return envelope.created(serial.screening(record))


@bp.get("/ryhs/youths/<youth_id>/safety-screenings")
def list_screenings(youth_id):
    authz.require(*authz.STAFF_READ_ALL)
    youth = find.youth(youth_id)
    status = envelope.enum_filter("status", SCREENING_STATUSES)
    rows = [s for s in store.safety_screenings.values() if s["youth_id"] == youth["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.listing(store.ordered(rows), serial.screening)


@bp.get("/ryhs/youths/<youth_id>/reunification-cases")
def list_youth_cases(youth_id):
    authz.require(
        authz.PROGRAM_ADMIN, authz.SHELTER_CASE_MANAGER, authz.REUNIFICATION_SPECIALIST
    )
    youth = find.youth(youth_id)
    status = envelope.enum_filter("status", CASE_STATUSES)
    rows = [c for c in store.reunification_cases.values() if c["youth_id"] == youth["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.listing(store.ordered(rows), serial.case)


@bp.post("/ryhs/youths/<youth_id>/education-enrollments")
def enroll(youth_id):
    user_id, _role = authz.require(authz.SHELTER_CASE_MANAGER, authz.TLP_COORDINATOR)
    youth = find.youth(youth_id)
    body = shape.body()
    school_name = shape.need_str(body, "school_name", 1, 120)
    enrollment_type = shape.need_enum(body, "enrollment_type", ENROLLMENT_TYPES)

    record = {
        "youth_id": youth["id"],
        "school_name": school_name,
        "enrollment_type": enrollment_type,
        "status": "IMMEDIATE_ENROLLMENT",
        # PRD 3.9: records_waived is the youth's unaccompanied value at enrollment time.
        "records_waived": youth["unaccompanied"],
        "enrolled_at": store.now(),
        "verified_at": None,
        "liaison_user_id": user_id,
    }
    store.stamp_new(record)
    store.education_enrollments[record["id"]] = record
    # "This operation is deliberately exempt from every gate in the system."
    return envelope.created(serial.enrollment(record))


@bp.get("/ryhs/youths/<youth_id>/education-enrollments")
def list_enrollments(youth_id):
    authz.require(
        authz.PROGRAM_ADMIN,
        authz.SHELTER_CASE_MANAGER,
        authz.TLP_COORDINATOR,
        authz.OUTREACH_WORKER,
    )
    youth = find.youth(youth_id)
    status = envelope.enum_filter("status", ENROLLMENT_STATUSES)
    rows = [e for e in store.education_enrollments.values() if e["youth_id"] == youth["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.listing(store.ordered(rows), serial.enrollment)


@bp.get("/ryhs/youths/<youth_id>/governance-votes")
def list_youth_votes(youth_id):
    user_id, role = authz.require(
        authz.PROGRAM_ADMIN,
        authz.SHELTER_CASE_MANAGER,
        authz.TLP_COORDINATOR,
        authz.YOUTH_MEMBER,
    )
    # Ladder 3: "may list only its own governance votes".
    authz.own_youth(user_id, role, youth_id)
    youth = find.youth(youth_id)
    status = envelope.enum_filter("status", VOTE_STATUSES)
    rows = [v for v in store.governance_votes.values() if v["youth_id"] == youth["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.listing(store.ordered(rows), serial.vote)
