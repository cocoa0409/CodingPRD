"""Family reunification: cases, mediation, assessment, decision, aftercare (PRD 3.6)."""

from flask import Blueprint

import authz
import calc
import cascade
import envelope
import find
import serial
import shape
import store
from errors import fail

bp = Blueprint("reunification", __name__)

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
OUTCOMES = ("PROGRESS", "IMPASSE", "GUARDIAN_NO_SHOW", "AGREEMENT")
ASSESSMENT_RESULTS = ("SAFE", "CONDITIONAL", "UNSAFE")
DECISIONS = ("APPROVE", "DECLINE")
HOME_ASSESSMENT_OUTCOMES = ("PROGRESS", "AGREEMENT")


def case_sessions(case_id):
    return store.ordered(
        [s for s in store.mediation_sessions.values() if s["case_id"] == case_id]
    )


def latest_held_session(case_id):
    """The most recently held session of a case, by held_at then creation order."""
    held = [s for s in case_sessions(case_id) if s["held_at"] is not None]
    if not held:
        return None
    return sorted(held, key=lambda s: (s["held_at"], s["_seq"]))[-1]


# --------------------------------------------------------------- case lifecycle
@bp.post("/ryhs/reunification-cases")
def open_case():
    user_id, _role = authz.require(authz.REUNIFICATION_SPECIALIST)
    body = shape.body()
    # Ladder 5 - body foreign keys, in the endpoint's declared input order.
    youth = shape.fk_lookup(body, "youth_id", store.youths, "ERR_YOUTH_NOT_FOUND")
    # Ladder 6, in the endpoint's declared input order.
    if youth is None:
        shape.need_str(body, "youth_id", 1, 10000)
    label = shape.need_str(body, "guardian_household_label", 1, 120)
    expected = shape.need_int(body, "expected_youth_version")

    # Ladder 7 - optimistic concurrency on the youth (PRD 2.9).
    if expected != youth["version"]:
        fail("ERR_STALE_YOUTH_VERSION")
    # Ladder 20.
    if youth["risk_posture"] == "FROZEN":
        fail("ERR_YOUTH_POSTURE_FROZEN")

    # "Opening a case also supersedes history" - the earlier cases move first.
    cascade.supersede_cases(youth)

    clock = store.now()
    case = store.stamp_new(
        {
            "youth_id": youth["id"],
            "guardian_household_label": label,
            "status": "OPENED",
            "opened_at": clock,
            "mediation_round": 0,
            "max_mediation_rounds": calc.MAX_MEDIATION_ROUNDS,
            "safety_assessment_result": None,
            "aftercare_plan_due_at": None,
            "aftercare_contacts_completed": 0,
            "decision_user_id": None,
            "closed_at": None,
            "opening_user_id": user_id,
        }
    )
    store.reunification_cases[case["id"]] = case

    # "Opening a case always increments the youth's version by one."
    cascade.apply_youth_derived(youth)
    store.touch(youth)
    return envelope.created(serial.case(case))


@bp.get("/ryhs/reunification-cases/<case_id>")
def read_case(case_id):
    authz.require(authz.PROGRAM_ADMIN, authz.SHELTER_CASE_MANAGER, authz.REUNIFICATION_SPECIALIST)
    case = find.case(case_id)
    return envelope.ok(serial.case(case))


# ------------------------------------------------------------ mediation session
@bp.post("/ryhs/reunification-cases/<case_id>/mediation-sessions")
def schedule_session(case_id):
    user_id, _role = authz.require(authz.REUNIFICATION_SPECIALIST)
    case = find.case(case_id)
    body = shape.body()
    start_at = shape.need_instant(body, "scheduled_start_at")
    end_at = shape.need_instant(body, "scheduled_end_at")

    # Ladder 14.
    if case["status"] not in ("OPENED", "MEDIATION_HELD"):
        fail("ERR_CASE_INVALID_STATE")

    # Ladder 28 - CLOSED interval semantics: touching endpoints DO collide.
    for other in case_sessions(case["id"]):
        if start_at <= other["scheduled_end_at"] and other["scheduled_start_at"] <= end_at:
            fail("ERR_MEDIATION_SESSION_OVERLAP")

    # Ladder 29 - the 72h cooldown measured from the latest held_at.
    latest = latest_held_session(case["id"])
    if latest is not None:
        if start_at < latest["held_at"] + store.hours(calc.MEDIATION_COOLDOWN_HOURS):
            fail("ERR_MEDIATION_COOLDOWN_ACTIVE")

    # Ladder 32 - both instants in the future and correctly ordered.
    clock = store.now()
    if not (end_at > start_at and start_at > clock):
        fail("ERR_INVALID_INTERVAL")

    # Ladder 36 - the round ceiling.
    if case["mediation_round"] >= case["max_mediation_rounds"]:
        fail("ERR_MEDIATION_ROUNDS_EXHAUSTED")

    session = store.stamp_new(
        {
            "case_id": case["id"],
            "scheduled_start_at": start_at,
            "scheduled_end_at": end_at,
            "round_number": case["mediation_round"] + 1,
            "outcome": None,
            "held_at": None,
            "scheduler_user_id": user_id,
            "recorded_by_user_id": None,
        }
    )
    store.mediation_sessions[session["id"]] = session

    case["status"] = "MEDIATION_SCHEDULED"
    store.touch(case)
    return envelope.created(serial.session(session))


@bp.get("/ryhs/reunification-cases/<case_id>/mediation-sessions")
def list_sessions(case_id):
    authz.require(authz.PROGRAM_ADMIN, authz.SHELTER_CASE_MANAGER, authz.REUNIFICATION_SPECIALIST)
    case = find.case(case_id)
    envelope.page_args()
    return envelope.listing(case_sessions(case["id"]), serial.session)


@bp.post("/ryhs/mediation-sessions/<session_id>/record-outcome")
def record_outcome(session_id):
    user_id, _role = authz.require(authz.REUNIFICATION_SPECIALIST)
    session = find.session(session_id)
    body = shape.body()
    outcome = shape.need_enum(body, "outcome", OUTCOMES)

    case = store.reunification_cases.get(session["case_id"])
    # Ladder 15 - one recording per session, and never on a dead case.
    if session["outcome"] is not None:
        fail("ERR_SESSION_ALREADY_RECORDED")
    if case is not None and case["status"] in ("SUPERSEDED", "CLOSED"):
        fail("ERR_SESSION_ALREADY_RECORDED")

    session["outcome"] = outcome
    session["held_at"] = store.now()
    session["recorded_by_user_id"] = user_id
    store.touch(session)

    if case is not None:
        case["mediation_round"] += 1
        case["status"] = "MEDIATION_HELD"
        store.touch(case)
    return envelope.ok(serial.session(session))


# ------------------------------------------------------------- home assessment
@bp.post("/ryhs/reunification-cases/<case_id>/home-assessment")
def home_assessment(case_id):
    authz.require(authz.REUNIFICATION_SPECIALIST)
    case = find.case(case_id)
    body = shape.body()
    result = shape.need_enum(body, "safety_assessment_result", ASSESSMENT_RESULTS)

    # Ladder 14 - the case must stand MEDIATION_HELD and the latest held session
    # must have ended in PROGRESS or AGREEMENT.
    if case["status"] != "MEDIATION_HELD":
        fail("ERR_CASE_INVALID_STATE")
    latest = latest_held_session(case["id"])
    if latest is None or latest["outcome"] not in HOME_ASSESSMENT_OUTCOMES:
        fail("ERR_CASE_INVALID_STATE")

    case["safety_assessment_result"] = result
    case["status"] = "HOME_ASSESSMENT"
    store.touch(case)
    return envelope.ok(serial.case(case))


# -------------------------------------------------------------------- decision
APPROVABLE_ASSESSMENTS = ("SAFE", "CONDITIONAL")
NOTIFICATION_RESOLVED_ENOUGH = (
    "ATTEMPTED",
    "CONTACTED",
    "WAIVED",
    "LAW_ENFORCEMENT_REPORTED",
)


@bp.post("/ryhs/reunification-cases/<case_id>/decision")
def decide(case_id):
    user_id, _role = authz.require(authz.REUNIFICATION_SPECIALIST)
    case = find.case(case_id)
    body = shape.body()
    decision = shape.need_enum(body, "decision", DECISIONS)

    # Ladder 14.
    if case["status"] != "HOME_ASSESSMENT":
        fail("ERR_CASE_INVALID_STATE")
    if decision == "APPROVE" and case["safety_assessment_result"] not in APPROVABLE_ASSESSMENTS:
        # "an unsafe home can never be approved"
        fail("ERR_CASE_INVALID_STATE")

    youth = store.youths.get(case["youth_id"])
    if decision == "APPROVE":
        # Ladder 20.
        if youth is not None and youth["risk_posture"] == "FROZEN":
            fail("ERR_YOUTH_POSTURE_FROZEN")
        # Ladder 23 - no live parental-notification obligation may remain open.
        for admission in store.ordered(
            [a for a in store.admissions.values() if a["youth_id"] == case["youth_id"]]
        ):
            if admission["status"] not in ("ACTIVE", "EXTENDED"):
                continue
            for notification in cascade.admission_notifications(admission["id"]):
                if notification["status"] not in NOTIFICATION_RESOLVED_ENOUGH:
                    fail("ERR_NOTIFICATION_UNRESOLVED")

    # Ladder 24 - whoever ran the mediation may not sign off on its result.
    latest = latest_held_session(case["id"])
    if latest is not None and latest["recorded_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVE":
        cascade.approve_case(case, youth, user_id)
    else:
        # "DECLINE fires no cascade at all, and the asymmetry is intentional."
        case["status"] = "DECLINED"
        case["decision_user_id"] = user_id
        store.touch(case)
    return envelope.ok(serial.case(case))


# ------------------------------------------------------------------- aftercare
@bp.post("/ryhs/reunification-cases/<case_id>/aftercare-contacts")
def log_aftercare_contact(case_id):
    authz.require(authz.REUNIFICATION_SPECIALIST)
    case = find.case(case_id)
    body = shape.body()
    shape.opt_str(body, "contact_note", 0, 100000)

    # Ladder 14.
    if case["status"] not in ("APPROVED", "AFTERCARE"):
        fail("ERR_CASE_INVALID_STATE")

    clock = store.now()
    # Ladder 47 - only the FIRST contact is bound by the 72h plan window.
    if case["aftercare_contacts_completed"] == 0:
        due_at = case["aftercare_plan_due_at"]
        if due_at is not None and clock > due_at:
            fail("ERR_AFTERCARE_WINDOW_MISSED")

    case["aftercare_contacts_completed"] += 1
    if case["aftercare_contacts_completed"] >= calc.AFTERCARE_CONTACTS_REQUIRED:
        case["status"] = "CLOSED"
        case["closed_at"] = clock
    else:
        case["status"] = "AFTERCARE"
    store.touch(case)
    return envelope.ok(serial.case(case))
