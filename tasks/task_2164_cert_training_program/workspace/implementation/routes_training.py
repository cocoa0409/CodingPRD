"""Class sessions, trainees and module completions."""
from __future__ import annotations

from flask import Blueprint

from calc import (DEMO_PASS_SCORE, FACILITY_TURNOVER_BUFFER_MINUTES,
                  MAX_DEMO_ATTEMPTS, MIN_ATTENDANCE_RATIO, cohort_trainees,
                  core_active_count, hnum, instructor_day_load,
                  readiness_components, recompute_readiness,
                  recompute_trainee_tallies)
from cascade import (after_demotion, apply_pass_ledger, cohort_missing_core_delivery,
                     demote_trainee_if_short, refresh_cohort, refresh_program,
                     refresh_session, revert_cohort_from_review, void_completion)
from errors import ApiError
from store import new_row, sorted_rows, store, touch
from util import D, add_minutes, dec_out, fmt_iso, parse_iso, round_half_up
from web import (MISSING, body, f_bool, f_dt, f_enum, f_id, f_int, f_num, f_str,
                 ok, ok_row, paginate, q_enum, q_str, require, require_any,
                 resolve)

bp = Blueprint("training", __name__)

SESSION_STATUS = ("SCHEDULED", "DELIVERED", "CANCELLED")
ENROLLMENT_STATUS = ("APPLIED", "WAITLISTED", "ENROLLED", "GRADUATED", "WITHDRAWN")
CURRENCY_STATUS = ("NOT_CREDENTIALED", "CURRENT", "LAPSING", "LAPSED", "REVOKED")
COMPLETION_STATUS = ("RECORDED", "SKILLS_PENDING", "PASSED", "FAILED", "VOIDED")


# ==========================================================================
# ClassSession
# ==========================================================================
@bp.post("/class-sessions")
def create_session():
    require("ProgramCoordinator")
    data = body()
    cohort_id = f_id(data, "cohort_id")
    module_id = f_id(data, "module_id")
    facility_id = f_id(data, "facility_id")
    instructor_id = f_id(data, "instructor_id")
    starts_raw, starts_at = f_dt(data, "starts_at")

    cohort = resolve(store.cohorts, cohort_id, "ERR_COHORT_NOT_FOUND")
    module = resolve(store.curriculum_modules, module_id, "ERR_CURRICULUM_MODULE_NOT_FOUND")
    facility = resolve(store.facilities, facility_id, "ERR_FACILITY_NOT_FOUND")
    instructor = resolve(store.instructors, instructor_id, "ERR_INSTRUCTOR_NOT_FOUND")

    contact_hours = D(module["contact_hours"])
    ends_at = add_minutes(starts_at, contact_hours * D(60))

    # 32 — instructor certification currency
    if not parse_iso(instructor["certification_expires_on"]) > ends_at:
        raise ApiError("ERR_INSTRUCTOR_CERT_EXPIRED",
                       "The instructor's certification does not outlast the class.")
    # 34 — instructor and facility activeness
    if instructor["status"] != "ACTIVE" or facility["status"] != "ACTIVE":
        raise ApiError("ERR_RESOURCE_NOT_ACTIVE",
                       "The instructor or facility is not ACTIVE.")
    # 40 — facility overlap, buffered on BOTH ends of the candidate only
    buf_start = add_minutes(starts_at, -FACILITY_TURNOVER_BUFFER_MINUTES)
    buf_end = add_minutes(ends_at, FACILITY_TURNOVER_BUFFER_MINUTES)
    for s in store.class_sessions.values():
        if s["facility_id"] != facility_id or s["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        e_start = parse_iso(s["starts_at"])
        e_end = parse_iso(s["ends_at"])
        if buf_start < e_end and e_start < buf_end:
            raise ApiError("ERR_FACILITY_DOUBLE_BOOKED",
                           "The room is occupied within the turnover buffer.")
    # 42 — instructor overlap, unbuffered; exact adjacency is legal
    for s in store.class_sessions.values():
        if s["instructor_id"] != instructor_id or s["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        e_start = parse_iso(s["starts_at"])
        e_end = parse_iso(s["ends_at"])
        if starts_at < e_end and e_start < ends_at:
            raise ApiError("ERR_INSTRUCTOR_DOUBLE_BOOKED",
                           "The instructor is already booked over this interval.")
    # 44 — cohort teaching window
    if starts_at < parse_iso(cohort["session_window_start"]) or \
            ends_at > parse_iso(cohort["session_window_end"]):
        raise ApiError("ERR_SESSION_OUTSIDE_COHORT_WINDOW",
                       "The session falls outside the cohort's teaching window.")
    # 50 — prerequisite scheduled on this cohort, ending at or before the start
    prereq_id = module.get("prerequisite_module_id")
    if prereq_id:
        ok_prereq = False
        for s in store.class_sessions.values():
            if s["cohort_id"] != cohort_id or s["module_id"] != prereq_id:
                continue
            if s["status"] not in ("SCHEDULED", "DELIVERED"):
                continue
            if parse_iso(s["ends_at"]) <= starts_at:
                ok_prereq = True
                break
        if not ok_prereq:
            raise ApiError("ERR_PREREQUISITE_NOT_SCHEDULED",
                           "The prerequisite module has no earlier session on this cohort.")
    # 64 — the room must hold the class
    from calc import recompute_cohort_seats
    recompute_cohort_seats(cohort)
    if int(facility["capacity_seats"]) < int(cohort["seats_confirmed"]):
        raise ApiError("ERR_FACILITY_CAPACITY_INSUFFICIENT",
                       "The facility cannot seat the cohort's confirmed members.")
    # 66 — aggregate instructor day load
    load = instructor_day_load(instructor_id, starts_at.date())
    cap = D(instructor["max_daily_contact_hours"])
    if round_half_up(load + contact_hours, 1) > round_half_up(cap, 1):
        raise ApiError("ERR_INSTRUCTOR_DAILY_LOAD_EXCEEDED",
                       "The instructor's daily contact-hour cap would be exceeded.")

    row = new_row(
        "ClassSession",
        cohort_id=cohort_id,
        module_id=module_id,
        facility_id=facility_id,
        instructor_id=instructor_id,
        starts_at=starts_raw,
        ends_at=fmt_iso(ends_at),
        delivered_at=None,
        recorded_completion_count=0,
        status="SCHEDULED",
    )
    store.class_sessions[row["id"]] = row
    return ok_row(row, 201)


@bp.get("/class-sessions")
def list_sessions():
    require_any()
    cohort_id = q_str("cohort_id")
    module_id = q_str("module_id")
    facility_id = q_str("facility_id")
    instructor_id = q_str("instructor_id")
    status = q_enum("status", SESSION_STATUS)
    rows = []
    for s in store.class_sessions.values():
        if cohort_id is not None and s["cohort_id"] != cohort_id:
            continue
        if module_id is not None and s["module_id"] != module_id:
            continue
        if facility_id is not None and s["facility_id"] != facility_id:
            continue
        if instructor_id is not None and s["instructor_id"] != instructor_id:
            continue
        if status is not None and s["status"] != status:
            continue
        rows.append(s)
    return paginate(rows)


@bp.get("/class-sessions/<session_id>")
def read_session(session_id):
    require_any()
    session = resolve(store.class_sessions, session_id, "ERR_CLASS_SESSION_NOT_FOUND")
    return ok_row(session)


@bp.post("/class-sessions/<session_id>/deliver")
def deliver_session(session_id):
    user_id, role = require("Instructor")
    session = resolve(store.class_sessions, session_id, "ERR_CLASS_SESSION_NOT_FOUND")
    if user_id != session["instructor_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the assigned instructor may deliver this session.")
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SCHEDULED session can be delivered.")
    cohort = store.cohorts.get(session["cohort_id"])
    if cohort is None or cohort["status"] != "IN_SESSION":
        raise ApiError("ERR_INVALID_STATE", "The owning cohort is not IN_SESSION.")
    if store.now() < parse_iso(session["starts_at"]):
        raise ApiError("ERR_INVALID_STATE",
                       "The logical clock has not reached the session start.")
    instructor = store.instructors.get(session["instructor_id"])
    if instructor is None or not parse_iso(instructor["certification_expires_on"]) > store.now():
        raise ApiError("ERR_INSTRUCTOR_CERT_EXPIRED",
                       "The instructor's certification has lapsed.")
    session["status"] = "DELIVERED"
    session["delivered_at"] = store.now_iso()
    touch(session)
    refresh_cohort(cohort)
    return ok_row(session)


@bp.post("/class-sessions/<session_id>/cancel")
def cancel_session(session_id):
    require("ProgramCoordinator")
    session = resolve(store.class_sessions, session_id, "ERR_CLASS_SESSION_NOT_FOUND")
    data = body()
    f_str(data, "reason", required=False, default=None)
    if session["status"] not in ("SCHEDULED", "DELIVERED"):
        raise ApiError("ERR_INVALID_STATE", "The session is already CANCELLED.")
    was_delivered = session["status"] == "DELIVERED"
    cohort = store.cohorts.get(session["cohort_id"])
    session["status"] = "CANCELLED"
    touch(session)
    if was_delivered:
        # Cascade chain B, links 1-5.
        demoted_any = False
        for comp in sorted_rows(list(store.module_completions.values())):
            if comp["class_session_id"] != session["id"]:
                continue
            if comp["status"] not in ("RECORDED", "SKILLS_PENDING", "PASSED", "FAILED"):
                continue
            if void_completion(comp):
                demoted_any = True
        if cohort is not None and cohort["status"] == "GRADUATION_REVIEW":
            if demoted_any or cohort_missing_core_delivery(cohort):
                revert_cohort_from_review(cohort)
    refresh_cohort(cohort)
    refresh_session(session)
    return ok_row(session)


# ==========================================================================
# Trainee
# ==========================================================================
@bp.post("/trainees")
def create_trainee():
    require("ProgramCoordinator")
    data = body()
    program_id = f_id(data, "program_id")
    cohort_id = f_id(data, "cohort_id")
    full_name = f_str(data, "full_name")
    email = f_str(data, "email")
    hold = f_bool(data, "deployment_hold", required=False, default=False)

    program = resolve(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    cohort = resolve(store.cohorts, cohort_id, "ERR_COHORT_NOT_FOUND")
    for t in store.trainees.values():
        if t["program_id"] == program_id and t["email"] == email:
            raise ApiError("ERR_DUPLICATE_SCOPED_KEY",
                           "email is already used inside this program.")
    if cohort["status"] not in ("RECRUITING", "SCHEDULED", "IN_SESSION"):
        raise ApiError("ERR_COHORT_NOT_ACCEPTING",
                       "The cohort is not accepting applicants.")
    row = new_row(
        "Trainee",
        program_id=program_id,
        cohort_id=cohort_id,
        full_name=full_name,
        email=email,
        deployment_hold=hold,
        enrollment_status="APPLIED",
        currency_status="NOT_CREDENTIALED",
        waitlist_position=None,
        earned_contact_hours=0.0,
        passed_core_count=0,
        readiness_score=0.0,
        equipment_liability_cents=0,
        last_deployed_at=None,
        last_qualifying_activity_at=None,
    )
    store.trainees[row["id"]] = row
    return ok_row(row, 201)


@bp.get("/trainees")
def list_trainees():
    require_any()
    program_id = q_str("program_id")
    cohort_id = q_str("cohort_id")
    enrollment = q_enum("enrollment_status", ENROLLMENT_STATUS)
    currency = q_enum("currency_status", CURRENCY_STATUS)
    rows = []
    for t in store.trainees.values():
        if program_id is not None and t["program_id"] != program_id:
            continue
        if cohort_id is not None and t["cohort_id"] != cohort_id:
            continue
        if enrollment is not None and t["enrollment_status"] != enrollment:
            continue
        if currency is not None and t["currency_status"] != currency:
            continue
        rows.append(t)
    return paginate(rows)


@bp.get("/trainees/<trainee_id>")
def read_trainee(trainee_id):
    require_any()
    trainee = resolve(store.trainees, trainee_id, "ERR_TRAINEE_NOT_FOUND")
    return ok_row(trainee)


def _promote_from_waitlist(cohort):
    """Waitlist promotion selector — exactly one trainee per released seat."""
    from calc import recompute_cohort_seats
    recompute_cohort_seats(cohort)
    if int(cohort["seats_confirmed"]) >= int(cohort["seat_capacity"]):
        return
    candidates = [t for t in cohort_trainees(cohort["id"])
                  if t["enrollment_status"] == "WAITLISTED"]
    if not candidates:
        return
    candidates.sort(key=lambda t: (t.get("waitlist_position") or 0,
                                   t["created_at"], t["_seq"]))
    winner = candidates[0]
    winner["enrollment_status"] = "ENROLLED"
    touch(winner)


@bp.post("/trainees/<trainee_id>/enrollment")
def trainee_enrollment(trainee_id):
    user_id, role = require("ProgramCoordinator", "Trainee")
    trainee = resolve(store.trainees, trainee_id, "ERR_TRAINEE_NOT_FOUND")
    data = body()
    action = f_enum(data, "action", ("ENROLL", "WITHDRAW", "GRADUATE"))
    if role == "Trainee":
        if user_id != trainee["id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "A trainee may act only on their own record.")
        if action != "WITHDRAW":
            raise ApiError("ERR_UNAUTHORIZED",
                           "A trainee may only take the WITHDRAW action.")
    cohort = store.cohorts.get(trainee["cohort_id"])
    program = store.programs.get(trainee["program_id"])
    current = trainee["enrollment_status"]

    if action == "ENROLL":
        if current != "APPLIED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only an APPLIED trainee can be enrolled.")
        if cohort is None or cohort["status"] not in ("RECRUITING", "SCHEDULED", "IN_SESSION"):
            raise ApiError("ERR_COHORT_NOT_ACCEPTING",
                           "The cohort is not accepting enrollments.")
        from calc import recompute_cohort_seats
        recompute_cohort_seats(cohort)
        if int(cohort["seats_confirmed"]) < int(cohort["seat_capacity"]):
            trainee["enrollment_status"] = "ENROLLED"
        else:
            trainee["enrollment_status"] = "WAITLISTED"
            trainee["waitlist_position"] = int(cohort["next_waitlist_position"])
            cohort["next_waitlist_position"] = int(cohort["next_waitlist_position"]) + 1
            touch(cohort)
        touch(trainee)
    elif action == "WITHDRAW":
        if current == "WITHDRAWN":
            raise ApiError("ERR_INVALID_STATE", "The trainee is already WITHDRAWN.")
        if current in ("ENROLLED", "GRADUATED"):
            for iss in store.equipment_issuances.values():
                if iss["trainee_id"] == trainee["id"] and iss["status"] == "ISSUED":
                    raise ApiError("ERR_EQUIPMENT_OUTSTANDING",
                                   "The trainee still holds issued equipment.")
            for r in store.roster_assignments.values():
                if r["trainee_id"] == trainee["id"] and \
                        r["status"] in ("NOTIFIED", "ACCEPTED", "DEPLOYED"):
                    raise ApiError("ERR_ROSTER_COMMITMENT_OUTSTANDING",
                                   "The trainee holds a live call-out commitment.")
        trainee["enrollment_status"] = "WITHDRAWN"
        touch(trainee)
        if current in ("ENROLLED", "GRADUATED") and cohort is not None:
            _promote_from_waitlist(cohort)
    else:  # GRADUATE
        if current != "ENROLLED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only an ENROLLED trainee can be graduated.")
        if cohort is None or cohort["status"] != "GRADUATION_REVIEW":
            raise ApiError("ERR_COHORT_NOT_IN_REVIEW",
                           "The cohort is not in GRADUATION_REVIEW.")
        recompute_trainee_tallies(trainee)
        if int(trainee["passed_core_count"]) != core_active_count():
            raise ApiError("ERR_CORE_MODULES_INCOMPLETE",
                           "The trainee has not passed every core active module.")
        for comp in store.module_completions.values():
            if comp["trainee_id"] == trainee["id"] and comp["status"] == "SKILLS_PENDING":
                raise ApiError("ERR_CORE_MODULES_INCOMPLETE",
                               "A completion is still awaiting its skills demonstration.")
        trainee["enrollment_status"] = "GRADUATED"
        recompute_readiness(trainee)
        touch(trainee)

    refresh_cohort(cohort)
    refresh_program(program)
    return ok_row(trainee)


@bp.get("/trainees/<trainee_id>/readiness")
def trainee_readiness(trainee_id):
    require_any()
    trainee = resolve(store.trainees, trainee_id, "ERR_TRAINEE_NOT_FOUND")
    parts = readiness_components(trainee)
    return ok({
        "certified_readiness_score": dec_out(parts["certified_readiness_score"], 2),
        "provisional_readiness_score": dec_out(parts["provisional_readiness_score"], 2),
        "core_hours_total": dec_out(parts["core_hours_total"], 1),
        "core_hours_earned_certified": dec_out(parts["core_hours_earned_certified"], 1),
        "core_hours_earned_provisional": dec_out(parts["core_hours_earned_provisional"], 1),
        "core_ratio_certified": dec_out(parts["core_ratio_certified"], 4),
        "core_ratio_provisional": dec_out(parts["core_ratio_provisional"], 4),
        "demo_avg_certified": dec_out(parts["demo_avg_certified"], 4),
        "demo_avg_provisional": dec_out(parts["demo_avg_provisional"], 4),
        "recency_factor": dec_out(parts["recency_factor"], 2),
        "exercise_bonus": dec_out(parts["exercise_bonus"], 1),
    })


# ==========================================================================
# ModuleCompletion
# ==========================================================================
@bp.post("/module-completions")
def create_completion():
    user_id, role = require("Instructor")
    data = body()
    trainee_id = f_id(data, "trainee_id")
    session_id = f_id(data, "class_session_id")
    minutes = f_int(data, "attendance_minutes", min_val=0)

    trainee = resolve(store.trainees, trainee_id, "ERR_TRAINEE_NOT_FOUND")
    session = resolve(store.class_sessions, session_id, "ERR_CLASS_SESSION_NOT_FOUND")

    if session["status"] != "DELIVERED":
        raise ApiError("ERR_SESSION_NOT_DELIVERED",
                       "Attendance may only be recorded against a DELIVERED session.")
    module = store.curriculum_modules.get(session["module_id"])
    if module is None:
        raise ApiError("ERR_CURRICULUM_MODULE_NOT_FOUND")

    prereq_id = module.get("prerequisite_module_id")
    if prereq_id:
        held = any(c["trainee_id"] == trainee_id and c["module_id"] == prereq_id
                   and c["status"] == "PASSED"
                   for c in store.module_completions.values())
        if not held:
            raise ApiError("ERR_PREREQUISITE_NOT_PASSED",
                           "The trainee has not passed the prerequisite module.")

    contact_minutes = D(module["contact_hours"]) * D(60)
    ratio = round_half_up(D(minutes) / contact_minutes, 4) if contact_minutes else D(0)
    if ratio < MIN_ATTENDANCE_RATIO:
        raise ApiError("ERR_ATTENDANCE_INSUFFICIENT",
                       "Attendance is below the 0.80 floor.")

    for c in store.module_completions.values():
        if c["trainee_id"] == trainee_id and c["module_id"] == module["id"] \
                and c["status"] != "VOIDED":
            raise ApiError("ERR_DUPLICATE_COMPLETION",
                           "The trainee already holds a live completion for this module.")

    passes_now = not module["requires_skills_demo"]
    row = new_row(
        "ModuleCompletion",
        trainee_id=trainee_id,
        class_session_id=session_id,
        module_id=module["id"],
        evaluator_id=None,
        attendance_minutes=minutes,
        attendance_ratio=float(ratio),
        demo_score=None,
        attempt_number=1,
        credited_contact_hours=0,
        status="PASSED" if passes_now else "SKILLS_PENDING",
    )
    store.module_completions[row["id"]] = row
    if passes_now:
        apply_pass_ledger(row, trainee, module, touch_completion=False)
    refresh_session(session)
    return ok_row(row, 201)


@bp.get("/module-completions")
def list_completions():
    require_any()
    trainee_id = q_str("trainee_id")
    module_id = q_str("module_id")
    session_id = q_str("class_session_id")
    evaluator_id = q_str("evaluator_id")
    status = q_enum("status", COMPLETION_STATUS)
    rows = []
    for c in store.module_completions.values():
        if trainee_id is not None and c["trainee_id"] != trainee_id:
            continue
        if module_id is not None and c["module_id"] != module_id:
            continue
        if session_id is not None and c["class_session_id"] != session_id:
            continue
        if evaluator_id is not None and c.get("evaluator_id") != evaluator_id:
            continue
        if status is not None and c["status"] != status:
            continue
        rows.append(c)
    return paginate(rows)


@bp.get("/module-completions/<completion_id>")
def read_completion(completion_id):
    require_any()
    comp = resolve(store.module_completions, completion_id, "ERR_MODULE_COMPLETION_NOT_FOUND")
    return ok_row(comp)


@bp.post("/module-completions/<completion_id>/skills-demo")
def skills_demo(completion_id):
    user_id, role = require("SkillsEvaluator")
    comp = resolve(store.module_completions, completion_id, "ERR_MODULE_COMPLETION_NOT_FOUND")
    data = body()
    outcome = f_enum(data, "outcome", ("PASS", "FAIL"))
    score = f_num(data, "demo_score", min_val=0, max_val=100)

    if comp["status"] not in ("SKILLS_PENDING", "FAILED"):
        raise ApiError("ERR_INVALID_STATE",
                       "The completion is not awaiting a skills demonstration.")
    session = store.class_sessions.get(comp["class_session_id"])
    if session is not None and user_id == session["instructor_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "An evaluator may not sign a demonstration for a session they taught.")
    if comp["status"] == "FAILED":
        if int(comp["attempt_number"]) >= MAX_DEMO_ATTEMPTS:
            raise ApiError("ERR_DEMO_ATTEMPTS_EXHAUSTED",
                           "The demonstration attempt allowance is exhausted.")
        # bounded retake, reopened within this same request
        comp["attempt_number"] = int(comp["attempt_number"]) + 1
        comp["evaluator_id"] = None
        comp["demo_score"] = None
        comp["status"] = "SKILLS_PENDING"

    trainee = store.trainees.get(comp["trainee_id"])
    module = store.curriculum_modules.get(comp["module_id"])
    comp["evaluator_id"] = user_id
    comp["demo_score"] = float(score)
    if outcome == "PASS" and score >= DEMO_PASS_SCORE:
        apply_pass_ledger(comp, trainee, module)
    else:
        comp["status"] = "FAILED"
        touch(comp)
    return ok_row(comp)


@bp.post("/module-completions/<completion_id>/void")
def void_completion_route(completion_id):
    require("ProgramCoordinator")
    comp = resolve(store.module_completions, completion_id, "ERR_MODULE_COMPLETION_NOT_FOUND")
    data = body()
    f_str(data, "reason", required=False, default=None)
    if comp["status"] == "VOIDED":
        raise ApiError("ERR_INVALID_STATE", "The completion is already VOIDED.")
    trainee = store.trainees.get(comp["trainee_id"])
    cohort = store.cohorts.get(trainee["cohort_id"]) if trainee else None
    if cohort is not None and cohort["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "The owning cohort is CLOSED.")
    demoted = void_completion(comp)
    if demoted and cohort is not None:
        revert_cohort_from_review(cohort)
    refresh_cohort(cohort)
    if trainee is not None:
        refresh_program(store.programs.get(trainee["program_id"]))
    return ok_row(comp)
