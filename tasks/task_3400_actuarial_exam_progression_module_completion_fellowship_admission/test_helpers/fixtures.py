"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch through PRD-declared
endpoints — the test harness restarts the server with an empty database
before every test. Setup calls use get_success_data() (lenient 2xx) so a
broken precondition surfaces as a clear "Setup failed" message.

Identity threading: the Candidate role is entity-backed, so every
ownership-gated call in these helpers uses make_candidate_headers(candidate["id"])
— never a shared fallback header.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .test_users import (
    ANONYMOUS, REGISTRAR, EXAM_COMMITTEE, ACADEMIC_REVIEWER, DISCIPLINE_BOARD,
    make_candidate_headers, make_grader_headers,
)


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def set_clock(api, iso):
    return get_success_data(api.set_clock(F.set_clock_payload(iso), REGISTRAR))


def make_candidate(api, **overrides):
    return get_success_data(api.create_candidate(F.create_candidate_payload(**overrides), ANONYMOUS))


def candidate_headers(candidate):
    return make_candidate_headers(candidate["id"])


def get_candidate(api, candidate_id):
    return get_success_data(api.get_candidate(candidate_id, REGISTRAR))


def make_syllabus(api, **overrides):
    return get_success_data(api.create_syllabus_version(F.create_syllabus_version_payload(**overrides), REGISTRAR))


def activate_syllabus(api, syllabus_id):
    return get_success_data(api.activate_syllabus_version(syllabus_id, REGISTRAR))


def make_exam(api, syllabus_version_id, **overrides):
    return get_success_data(api.create_exam(F.create_exam_payload(syllabus_version_id, **overrides), REGISTRAR))


def make_window(api, exam_id, **overrides):
    """Create a window (SCHEDULED at creation; the sweep opens it)."""
    return get_success_data(api.create_exam_window(F.create_exam_window_payload(exam_id, **overrides), REGISTRAR))


def get_window(api, window_id):
    return get_success_data(api.get_exam_window(window_id, REGISTRAR))


def register(api, window_id, candidate):
    """Candidate self-registers; REGISTERED when a seat is free else WAITLISTED."""
    return get_success_data(api.create_exam_registration(
        F.create_exam_registration_payload(window_id), candidate_headers(candidate)))


def cancel_registration(api, registration_id, headers):
    return get_success_data(api.cancel_exam_registration(registration_id, headers))


def record_score(api, registration_id, raw_score):
    return get_success_data(api.record_score(
        registration_id, F.record_score_payload(raw_score), EXAM_COMMITTEE))


def make_module(api, **overrides):
    return get_success_data(api.create_module(F.create_module_payload(**overrides), REGISTRAR))


def make_session(api, **overrides):
    return get_success_data(api.create_course_session(F.create_course_session_payload(**overrides), REGISTRAR))


def book_attendance(api, session_id, candidate):
    return get_success_data(api.create_course_attendance(
        F.create_course_attendance_payload(session_id), candidate_headers(candidate)))


def verify_attendance(api, attendance_id, outcome="ATTENDED"):
    return get_success_data(api.verify_course_attendance(
        attendance_id, F.verify_course_attendance_payload(outcome), REGISTRAR))


def file_case(api, candidate_id, **overrides):
    return get_success_data(api.create_discipline_case(
        F.create_discipline_case_payload(candidate_id, **overrides), REGISTRAR))


def sanction_case(api, case_id, **overrides):
    return get_success_data(api.sanction_discipline_case(
        case_id, F.sanction_discipline_case_payload(**overrides), DISCIPLINE_BOARD))


def make_transfer(api, candidate, source_body="IFOA", claimed_hours=10):
    return get_success_data(api.create_transfer_credit_request(
        F.create_transfer_credit_request_payload(source_body, claimed_hours), candidate_headers(candidate)))


def make_cpd(api, candidate, **overrides):
    return get_success_data(api.create_cpd_attestation(
        F.create_cpd_attestation_payload(**overrides), candidate_headers(candidate)))


def verify_cpd(api, attestation_id, verified_hours):
    return get_success_data(api.verify_cpd_attestation(
        attestation_id, F.verify_cpd_attestation_payload(verified_hours), REGISTRAR))


# ---------------------------------------------------------------------------
# Tier 1/2: active syllabus, open window, registrations
# ---------------------------------------------------------------------------
def make_active_exam(api, syllabus_code=C.STANDARD_SYLLABUS_CODE, **exam_overrides):
    """Create a syllabus version and an exam, then activate. Returns (syllabus, exam)."""
    syl = make_syllabus(api, version_code=syllabus_code)
    exam = make_exam(api, syl["id"], **exam_overrides)
    activate_syllabus(api, syl["id"])
    return syl, get_success_data(api.get_exam(exam["id"], REGISTRAR))


def setup_open_window(api, register_clock=C.CLOCK_REGISTRATION_OPEN, exam=None,
                      syllabus_code=C.STANDARD_SYLLABUS_CODE, **window_kwargs):
    """ACTIVE syllabus + exam + window, swept to REGISTRATION_OPEN.

    Returns {"syllabus": syl, "exam": exam, "window": window(refreshed)}.
    """
    if exam is None:
        syl, exam = make_active_exam(api, syllabus_code=syllabus_code)
    else:
        syl = None
    window = make_window(api, exam["id"], **window_kwargs)
    set_clock(api, register_clock)
    window = get_window(api, window["id"])
    return {"syllabus": syl, "exam": exam, "window": window}


def setup_registered(api, num_candidates=1, register_clock=C.CLOCK_REGISTRATION_OPEN, **window_kwargs):
    """Open window plus N candidates, each with one registration.

    Returns {"window", "exam", "syllabus", "candidates", "registrations"}.
    With capacity < num_candidates the overflow rows come back WAITLISTED.
    """
    ctx = setup_open_window(api, register_clock=register_clock, **window_kwargs)
    candidates, registrations = [], []
    for _ in range(num_candidates):
        cand = make_candidate(api)
        reg = register(api, ctx["window"]["id"], cand)
        candidates.append(cand)
        registrations.append(reg)
    ctx.update({"candidates": candidates, "registrations": registrations})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: scoring lifecycle (SAT -> publish) and the committee workflow
# ---------------------------------------------------------------------------
def propose_ratify_publish(api, window_id, proposed_mark=C.PASS_MARK_RATIFIED,
                           ratified_mark=C.PASS_MARK_RATIFIED):
    """Committee workflow: propose (OCC on window version) -> ratify -> publish.
    Requires the window to already be SCORING. Returns the PUBLISHED setting."""
    window = get_window(api, window_id)
    pms = get_success_data(api.create_pass_mark_setting(
        window_id,
        F.create_pass_mark_setting_payload(proposed_mark, window["version"]),
        EXAM_COMMITTEE))
    pms = get_success_data(api.ratify_pass_mark(
        pms["id"], F.ratify_pass_mark_payload(ratified_mark), EXAM_COMMITTEE))
    return get_success_data(api.publish_pass_mark(pms["id"], EXAM_COMMITTEE))


def setup_published_window(api, raw_scores=(C.RAW_SCORE_AT_MARK,), proposed_mark=C.PASS_MARK_RATIFIED,
                           ratified_mark=C.PASS_MARK_RATIFIED, scoring_clock=C.CLOCK_SCORING,
                           register_clock=C.CLOCK_REGISTRATION_OPEN, **window_kwargs):
    """Full pipeline: open window -> N registrations -> sweep to SCORING (auto-SAT)
    -> record raw scores -> propose/ratify/publish. Results are RELEASED.

    Returns {"window", "exam", "syllabus", "candidates", "registrations",
             "setting"} with registrations refreshed post-publish.
    """
    ctx = setup_registered(api, num_candidates=len(raw_scores),
                           register_clock=register_clock, **window_kwargs)
    set_clock(api, scoring_clock)
    for reg, raw in zip(ctx["registrations"], raw_scores):
        record_score(api, reg["id"], raw)
    setting = propose_ratify_publish(
        api, ctx["window"]["id"], proposed_mark=proposed_mark, ratified_mark=ratified_mark)
    ctx["setting"] = setting
    ctx["window"] = get_window(api, ctx["window"]["id"])
    ctx["registrations"] = [
        get_success_data(api.list_candidate_registrations(cand["id"], REGISTRAR))[0]
        for cand in ctx["candidates"]
    ]
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: VEE + credential chain (ASA), enrollment, modules, project
# ---------------------------------------------------------------------------
def approve_all_vee_topics(api, candidate, grade_points=C.VEE_GRADE_PASS):
    """File and APPROVE one submission per VEE topic for the candidate."""
    submissions = []
    for topic in C.VEE_TOPICS:
        sub = get_success_data(api.create_vee_submission(
            F.create_vee_submission_payload(topic=topic, grade_points=grade_points),
            candidate_headers(candidate)))
        sub = get_success_data(api.review_vee_submission(
            sub["id"], F.review_vee_submission_payload("APPROVE"), ACADEMIC_REVIEWER))
        submissions.append(sub)
    return submissions


def apply_for_credential(api, candidate, credential="ASA"):
    """Read the candidate's current version (OCC), then apply. Returns the
    application plus the refreshed candidate."""
    fresh = get_candidate(api, candidate["id"])
    app = get_success_data(api.create_credential_application(
        F.create_credential_application_payload(credential, fresh["version"]),
        candidate_headers(candidate)))
    return {"application": app, "candidate": get_candidate(api, candidate["id"])}


def setup_associate(api, candidate=None, register_clock=C.CLOCK_REGISTRATION_OPEN,
                    scoring_clock=C.CLOCK_SCORING, raw_score=C.RAW_SCORE_AT_MARK,
                    pass_mark=C.PASS_MARK_RATIFIED, window=None, **window_kwargs):
    """Drive one candidate to ASSOCIATE tier: PASS the standard prelim exam in a
    published window, approve all three VEE topics, apply for ASA.

    The ASA application happens at whatever the logical clock reads after the
    publish (for the standard chain that is 2026-10-13, i.e. admission year
    2026). Pass window/clock overrides to reproduce the 2027-admission variant.

    Returns {"candidate" (ASSOCIATE), "window", "registration", "application"}.
    """
    if candidate is None:
        candidate = make_candidate(api)
    if window is None:
        ctx = setup_open_window(api, register_clock=register_clock, **window_kwargs)
        window = ctx["window"]
    registration = register(api, window["id"], candidate)
    set_clock(api, scoring_clock)
    record_score(api, registration["id"], raw_score)
    propose_ratify_publish(api, window["id"], proposed_mark=pass_mark, ratified_mark=pass_mark)
    approve_all_vee_topics(api, candidate)
    outcome = apply_for_credential(api, candidate, "ASA")
    return {
        "candidate": outcome["candidate"],
        "window": get_window(api, window["id"]),
        "registration": registration,
        "application": outcome["application"],
    }


def setup_enrollment(api, candidate, track_code=C.TRACK_QFI, with_modules=True):
    """Enroll an ASSOCIATE/FELLOW candidate and (optionally) define the default
    three-module track: M1 (seq 1, pass 70), M2 (seq 2, pass 70), CAP (seq 3,
    capstone, pass 75). Returns {"enrollment", "modules"} with modules sorted
    by sequence_index (last is the capstone)."""
    enrollment = get_success_data(api.create_track_enrollment(
        F.create_track_enrollment_payload(track_code), candidate_headers(candidate)))
    modules = []
    if with_modules:
        prefix = f"{track_code}-M"
        modules = [
            make_module(api, module_code=f"{prefix}1", track_code=track_code, sequence_index=1,
                        title=f"{track_code} Module 1", passing_score=C.MODULE_PASSING_SCORE),
            make_module(api, module_code=f"{prefix}2", track_code=track_code, sequence_index=2,
                        title=f"{track_code} Module 2", passing_score=C.MODULE_PASSING_SCORE),
            make_module(api, module_code=f"{track_code}-CAP", track_code=track_code, sequence_index=3,
                        title=f"{track_code} Capstone", is_capstone=True,
                        passing_score=C.CAPSTONE_PASSING_SCORE),
        ]
    return {"enrollment": enrollment, "modules": modules}


def attempt_and_submit(api, candidate, enrollment, module, score=C.SUBMIT_SCORE_PASS):
    """Create an attempt and submit it. Returns the decided attempt."""
    attempt = get_success_data(api.create_module_attempt(
        F.create_module_attempt_payload(enrollment["id"], module["id"]),
        candidate_headers(candidate)))
    return get_success_data(api.submit_module_attempt(
        attempt["id"], F.submit_module_attempt_payload(score), candidate_headers(candidate)))


def get_enrollment(api, candidate):
    rows = get_success_data(api.list_candidate_track_enrollments(candidate["id"], REGISTRAR))
    return rows[0] if rows else None


def setup_capstone_eligible(api, candidate=None, track_code=C.TRACK_QFI, **associate_kwargs):
    """ASSOCIATE candidate whose enrollment has every non-capstone module PASSED
    (auto-advanced to CAPSTONE_ELIGIBLE). Returns {"candidate", "enrollment",
    "modules", "associate"}."""
    if candidate is None:
        candidate = setup_associate(api, **associate_kwargs)["candidate"]
    ctx = setup_enrollment(api, candidate, track_code=track_code)
    for module in ctx["modules"]:
        if not module["is_capstone"]:
            attempt_and_submit(api, candidate, ctx["enrollment"], module)
    return {
        "candidate": candidate,
        "enrollment": get_enrollment(api, candidate),
        "modules": ctx["modules"],
    }


def grade_project(api, project_id, score, grader_id):
    return get_success_data(api.grade_project_assessment(
        project_id, F.grade_project_payload(score), make_grader_headers(grader_id)))


def setup_project_decided(api, candidate, enrollment, scores=(C.PROJECT_SCORE_G1, C.PROJECT_SCORE_G2),
                          grader_ids=(C.GRADER_1_ID, C.GRADER_2_ID), title=C.PROJECT_TITLE):
    """Submit a project and drive it to DECIDED via the consensus path
    (|g1-g2| <= 10). Returns the DECIDED project."""
    project = get_success_data(api.create_project_assessment(
        F.create_project_assessment_payload(enrollment["id"], title=title),
        candidate_headers(candidate)))
    for gid, score in zip(grader_ids, scores):
        project = grade_project(api, project["id"], score, gid)
    return project


def setup_completed_track(api, candidate=None, track_code=C.TRACK_QFI, **associate_kwargs):
    """Enrollment driven to COMPLETED: non-capstone passes + capstone pass.
    Returns {"candidate", "enrollment", "modules", "capstone_attempt"}."""
    ctx = setup_capstone_eligible(api, candidate=candidate, track_code=track_code, **associate_kwargs)
    capstone = [m for m in ctx["modules"] if m["is_capstone"]][0]
    cap_attempt = attempt_and_submit(api, ctx["candidate"], ctx["enrollment"], capstone)
    return {
        "candidate": ctx["candidate"],
        "enrollment": get_enrollment(api, ctx["candidate"]),
        "modules": ctx["modules"],
        "capstone_attempt": cap_attempt,
    }


# ---------------------------------------------------------------------------
# Tier 3/4: professionalism course
# ---------------------------------------------------------------------------
def setup_attended(api, candidate, session_kwargs=None, held_clock=C.CLOCK_SESSION_HELD,
                   outcome="ATTENDED"):
    """Book the candidate into a session, sweep past ends_at, verify attendance.
    The caller must ensure the clock is before session.starts_at at booking.
    Returns {"session", "attendance"}."""
    session = make_session(api, **(session_kwargs or {}))
    attendance = book_attendance(api, session["id"], candidate)
    set_clock(api, held_clock)
    attendance = verify_attendance(api, attendance["id"], outcome)
    return {"session": session, "attendance": attendance}


# ---------------------------------------------------------------------------
# Tier 4: discipline cascades
# ---------------------------------------------------------------------------
def suspend_candidate(api, candidate_id, suspension_days=C.SUSPENSION_DAYS, **case_kwargs):
    """File a case and resolve it SUSPENSION. Returns the RESOLVED case."""
    case = file_case(api, candidate_id, **case_kwargs)
    return sanction_case(api, case["id"], resolution="SUSPENSION", suspension_days=suspension_days)


def expel_candidate(api, candidate_id, **case_kwargs):
    """File a case and resolve it EXPULSION. Returns the RESOLVED case."""
    case = file_case(api, candidate_id, **case_kwargs)
    return sanction_case(api, case["id"], resolution="EXPULSION")


# ---------------------------------------------------------------------------
# Tier 5: full fellowship admission (FSA happy path)
# ---------------------------------------------------------------------------
def setup_fellow(api, track_code=C.TRACK_QFI, **associate_kwargs):
    """Full chain to FELLOW: ASA -> enroll -> pass non-capstone modules ->
    CAPSTONE_ELIGIBLE -> project consensus PASS -> capstone pass -> COMPLETED
    -> professionalism ATTENDED -> FSA application APPROVED.

    Returns {"candidate" (FELLOW), "enrollment", "modules", "project",
             "session", "attendance", "application"}.
    """
    ctx = setup_capstone_eligible(api, track_code=track_code, **associate_kwargs)
    candidate, enrollment = ctx["candidate"], ctx["enrollment"]
    project = setup_project_decided(api, candidate, enrollment)
    capstone = [m for m in ctx["modules"] if m["is_capstone"]][0]
    attempt_and_submit(api, candidate, enrollment, capstone)
    enrollment = get_enrollment(api, candidate)
    attended = setup_attended(api, candidate)
    outcome = apply_for_credential(api, candidate, "FSA")
    return {
        "candidate": outcome["candidate"],
        "enrollment": get_enrollment(api, candidate),
        "modules": ctx["modules"],
        "project": project,
        "session": attended["session"],
        "attendance": attended["attendance"],
        "application": outcome["application"],
    }
