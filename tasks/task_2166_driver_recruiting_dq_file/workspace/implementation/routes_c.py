"""Routes: road tests, orientation sessions and orientation enrollments."""
from datetime import timedelta

import calc
import domain
from core import (ALL_ROLES, DB, ROLE_RECRUITER, ROLE_SAFETY, actor_id,
                  all_rows, body, created, dt, fail, fk, fmt_date, fmt_instant,
                  must_get, new_row, now, ok, qs, req_enum, req_id_list,
                  req_instant, req_int, req_str, require_roles, serialize,
                  today, touch)
from routes_a import filtered, page
from routes_b import guard_application_active

VEHICLE_CLASSES = ("CLASS_A", "CLASS_B", "CLASS_C")
RT_TERMINAL = ("PASSED",)
SESSION_TERMINAL = ("COMPLETED",)
ENROLL_TERMINAL = ("ATTENDED", "ABSENT", "CANCELLED")


def examiner_conflict(examiner_user_id, start, exclude_id=None):
    """Closed 180-minute slot; touching endpoints collide."""
    end = start + timedelta(minutes=calc.ROAD_TEST_SLOT_MINUTES)
    for other in all_rows("road_tests"):
        if other["id"] == exclude_id:
            continue
        if other["status"] != "SCHEDULED":
            continue
        if other["examiner_user_id"] != examiner_user_id:
            continue
        other_start = dt(other["scheduled_at"])
        if other_start is None:
            continue
        other_end = other_start + timedelta(minutes=calc.ROAD_TEST_SLOT_MINUTES)
        if start <= other_end and other_start <= end:
            return True
    return False


def register(app):
    # -----------------------------------------------------------------
    # RoadTest
    # -----------------------------------------------------------------
    @app.post("/road-tests")
    def road_test_create():
        require_roles([ROLE_RECRUITER])
        payload = body()
        application = fk(payload, "application_id", "driver_applications")
        if application is None:
            req_str(payload, "application_id")
            fail("ERR_VALIDATION", "application_id must be a valid identifier.")
        examiner_user_id = req_str(payload, "examiner_user_id")
        scheduled_at = req_instant(payload, "scheduled_at")
        vehicle_class = req_enum(payload, "vehicle_class", VEHICLE_CLASSES)
        guard_application_active(application)
        if examiner_conflict(examiner_user_id, scheduled_at):
            fail("ERR_EXAMINER_SLOT_CONFLICT", "The examiner slot is already taken.")
        row = new_row("road_tests", {
            "application_id": application["id"],
            "examiner_user_id": examiner_user_id,
            "scheduled_at": fmt_instant(scheduled_at),
            "vehicle_class": vehicle_class,
            "status": "SCHEDULED",
            "attempt_number": 1,
            "score_pretrip": None,
            "score_skills": None,
            "score_road": None,
            "composite_score": None,
        })
        return created(serialize(row))

    @app.get("/road-tests/<road_test_id>")
    def road_test_read(road_test_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("road_tests", road_test_id)))

    @app.get("/road-tests")
    def road_test_list():
        require_roles(ALL_ROLES)
        return page(filtered("road_tests", {
            "application_id": qs("application_id"),
            "examiner_user_id": qs("examiner_user_id"),
            "status": qs("status"),
        }))

    @app.post("/road-tests/<road_test_id>/record-result")
    def road_test_record_result(road_test_id):
        require_roles([ROLE_SAFETY])
        row = must_get("road_tests", road_test_id)
        payload = body()
        outcome = req_enum(payload, "outcome", ("PASSED", "FAILED", "NO_SHOW"))
        pretrip = skills = road = None
        if outcome in ("PASSED", "FAILED"):
            pretrip = req_int(payload, "score_pretrip", minimum=0, maximum=100)
            skills = req_int(payload, "score_skills", minimum=0, maximum=100)
            road = req_int(payload, "score_road", minimum=0, maximum=100)
        if row["status"] in RT_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Road test is already terminal.")
        if row["status"] != "SCHEDULED":
            fail("ERR_INVALID_STATE", "Road test is not SCHEDULED.")
        composite = None
        if outcome in ("PASSED", "FAILED"):
            composite = calc.road_test_composite_score(pretrip, skills, road)
        if outcome == "PASSED" and not calc.road_test_passes(composite, road):
            fail("ERR_INVALID_STATE",
                 "The recorded scores do not satisfy the pass thresholds.")
        application = domain.application_of(row["application_id"])
        recruiter_user_id = application.get("recruiter_user_id") if application else None
        if recruiter_user_id is not None and row["examiner_user_id"] == recruiter_user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The examiner may not be the submitting recruiter.")
        if actor_id() != row["examiner_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "Only the assigned examiner may record this result.")
        if outcome == "PASSED":
            if application is not None and domain.clearinghouse_blocked(application):
                fail("ERR_CLEARINGHOUSE_PROHIBITED",
                     "The Clearinghouse picture is unresolved or prohibited.")
            if application is not None and not domain.has_negative_pre_employment(application):
                fail("ERR_DRUG_TEST_NOT_NEGATIVE",
                     "No verified-negative pre-employment specimen exists.")
        row["score_pretrip"] = pretrip
        row["score_skills"] = skills
        row["score_road"] = road
        row["composite_score"] = float(composite) if composite is not None else None
        if outcome == "NO_SHOW":
            row["status"] = "NO_SHOW"
            touch(row)
        elif outcome == "FAILED":
            row["status"] = "FAILED"
            touch(row)
        else:
            row["status"] = "PASSED"
            touch(row)
            if application is not None:
                if application["qualification_status"] == "IN_PROGRESS":
                    application["qualification_status"] = "ROAD_TEST_PASSED"
                    touch(application)
                dq_file = domain.file_of_application(application)
                if dq_file is not None:
                    domain.set_document(dq_file, "ROAD_TEST_CERT", "PRESENT",
                                        effective_on=fmt_date(today()),
                                        source_ref=row["id"])
                    domain.recompute_file(dq_file, force_touch=True)
        return ok(serialize(row))

    @app.post("/road-tests/<road_test_id>/reschedule")
    def road_test_reschedule(road_test_id):
        require_roles([ROLE_RECRUITER])
        row = must_get("road_tests", road_test_id)
        payload = body()
        scheduled_at = req_instant(payload, "scheduled_at")
        examiner_user_id = req_str(payload, "examiner_user_id")
        if row["status"] in RT_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Road test is already terminal.")
        if row["status"] not in ("FAILED", "NO_SHOW"):
            fail("ERR_INVALID_STATE", "Road test cannot be rescheduled from here.")
        if examiner_conflict(examiner_user_id, scheduled_at, exclude_id=row["id"]):
            fail("ERR_EXAMINER_SLOT_CONFLICT", "The examiner slot is already taken.")
        if row["attempt_number"] >= calc.MAX_ROAD_TEST_ATTEMPTS:
            fail("ERR_ROAD_TEST_ATTEMPTS_EXHAUSTED",
                 "The road test attempt budget is exhausted.")
        row["scheduled_at"] = fmt_instant(scheduled_at)
        row["examiner_user_id"] = examiner_user_id
        row["attempt_number"] += 1
        row["score_pretrip"] = None
        row["score_skills"] = None
        row["score_road"] = None
        row["composite_score"] = None
        row["status"] = "SCHEDULED"
        touch(row)
        return ok(serialize(row))

    # -----------------------------------------------------------------
    # OrientationSession
    # -----------------------------------------------------------------
    @app.post("/orientation-sessions")
    def session_create():
        require_roles([ROLE_RECRUITER])
        payload = body()
        carrier = fk(payload, "carrier_id", "carriers")
        if carrier is None:
            req_str(payload, "carrier_id")
            fail("ERR_VALIDATION", "carrier_id must be a valid identifier.")
        starts_at = req_instant(payload, "starts_at")
        ends_at = req_instant(payload, "ends_at")
        capacity = req_int(payload, "capacity", minimum=1)
        location_code = req_str(payload, "location_code")
        if not ends_at > starts_at:
            fail("ERR_VALIDATION", "ends_at must be strictly after starts_at.")
        row = new_row("orientation_sessions", {
            "carrier_id": carrier["id"],
            "starts_at": fmt_instant(starts_at),
            "ends_at": fmt_instant(ends_at),
            "capacity": capacity,
            "location_code": location_code,
            "enrolled_count": 0,
            "status": "PLANNED",
        })
        return created(serialize(row))

    @app.get("/orientation-sessions/<session_id>")
    def session_read(session_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("orientation_sessions", session_id)))

    @app.get("/orientation-sessions")
    def session_list():
        require_roles(ALL_ROLES)
        return page(filtered("orientation_sessions", {
            "carrier_id": qs("carrier_id"),
            "status": qs("status"),
        }))

    @app.post("/orientation-sessions/<session_id>/open")
    def session_open(session_id):
        require_roles([ROLE_RECRUITER])
        row = must_get("orientation_sessions", session_id)
        if row["status"] in SESSION_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Session is already completed.")
        if row["status"] != "PLANNED":
            fail("ERR_INVALID_STATE", "Session is not PLANNED.")
        starts_at = dt(row["starts_at"])
        if not now() < starts_at:
            fail("ERR_INVALID_STATE", "The session has already started.")
        row["status"] = "OPEN"
        touch(row)
        return ok(serialize(row))

    @app.post("/orientation-sessions/<session_id>/complete")
    def session_complete(session_id):
        require_roles([ROLE_RECRUITER])
        session = must_get("orientation_sessions", session_id)
        payload = body()
        attended_ids = req_id_list(payload, "attended_enrollment_ids")
        attended = [must_get("orientation_enrollments", eid) for eid in attended_ids]
        if session["status"] in SESSION_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Session is already completed.")
        if session["status"] != "OPEN":
            fail("ERR_INVALID_STATE", "Session is not OPEN.")
        ends_at = dt(session["ends_at"])
        if now() < ends_at:
            fail("ERR_INVALID_STATE", "The session has not ended yet.")
        for enrollment in attended:
            if enrollment["session_id"] != session["id"]:
                fail("ERR_INVALID_STATE",
                     "An attended enrollment does not belong to this session.")
            if enrollment["status"] != "RESERVED":
                fail("ERR_INVALID_STATE",
                     "An attended enrollment is not RESERVED.")
        attended_set = {e["id"] for e in attended}
        for enrollment in calc.rows_where("orientation_enrollments",
                                          session_id=session["id"]):
            if enrollment["status"] != "RESERVED":
                continue
            if enrollment["id"] in attended_set:
                enrollment["status"] = "ATTENDED"
                touch(enrollment)
                application = domain.application_of(enrollment["application_id"])
                if (application is not None
                        and application["qualification_status"] == "ROAD_TEST_PASSED"):
                    application["qualification_status"] = "ORIENTATION_COMPLETE"
                    touch(application)
                    domain.evaluate_qualified_join(application)
            else:
                enrollment["status"] = "ABSENT"
                touch(enrollment)
        session["status"] = "COMPLETED"
        domain.recompute_session_count(session)
        touch(session)
        return ok(serialize(session))

    # -----------------------------------------------------------------
    # OrientationEnrollment
    # -----------------------------------------------------------------
    @app.post("/orientation-enrollments")
    def enrollment_create():
        require_roles([ROLE_RECRUITER])
        payload = body()
        session = fk(payload, "session_id", "orientation_sessions")
        application = fk(payload, "application_id", "driver_applications")
        if session is None:
            req_str(payload, "session_id")
            fail("ERR_VALIDATION", "session_id must be a valid identifier.")
        if application is None:
            req_str(payload, "application_id")
            fail("ERR_VALIDATION", "application_id must be a valid identifier.")
        expected = req_int(payload, "expected_session_version")
        if expected != session["version"]:
            fail("ERR_STALE_VERSION", "expected_session_version does not match.")
        if session["status"] in SESSION_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Session is already completed.")
        if session["status"] != "OPEN":
            fail("ERR_INVALID_STATE", "Session is not OPEN.")
        guard_application_active(application)
        if application["qualification_status"] != "ROAD_TEST_PASSED":
            fail("ERR_APPLICATION_NOT_QUALIFIED",
                 "The application has not reached ROAD_TEST_PASSED.")
        if domain.clearinghouse_blocked(application):
            fail("ERR_CLEARINGHOUSE_PROHIBITED",
                 "The Clearinghouse picture is unresolved or prohibited.")
        applicant = domain.applicant_of_application(application)
        carrier = domain.carrier_of_application(application)
        band = calc.cdl_downgrade_risk(applicant, carrier)["cdl_downgrade_risk"]
        if band == "DOWNGRADED":
            fail("ERR_MEDICAL_CERT_INVALID", "The applicant's CDL is downgraded.")
        starts_at = dt(session["starts_at"])
        ends_at = dt(session["ends_at"])
        buffer_span = timedelta(hours=calc.ORIENTATION_BUFFER_HOURS)
        lo = starts_at - buffer_span
        hi = ends_at + buffer_span
        for other in calc.rows_where("orientation_enrollments",
                                     application_id=application["id"]):
            if other["status"] not in ("RESERVED", "ATTENDED"):
                continue
            other_session = DB["orientation_sessions"].get(other["session_id"])
            if other_session is None:
                continue
            o_start = dt(other_session["starts_at"])
            o_end = dt(other_session["ends_at"])
            if lo < o_end and o_start < hi:
                fail("ERR_ORIENTATION_OVERLAP",
                     "The application already occupies an overlapping session.")
        if session["enrolled_count"] >= session["capacity"]:
            fail("ERR_SESSION_AT_CAPACITY", "The session is full.")
        row = new_row("orientation_enrollments", {
            "session_id": session["id"],
            "application_id": application["id"],
            "status": "RESERVED",
        })
        domain.recompute_session_count(session)
        touch(session)
        return created(serialize(row))

    @app.get("/orientation-enrollments/<enrollment_id>")
    def enrollment_read(enrollment_id):
        require_roles(ALL_ROLES)
        return ok(serialize(must_get("orientation_enrollments", enrollment_id)))

    @app.get("/orientation-enrollments")
    def enrollment_list():
        require_roles(ALL_ROLES)
        return page(filtered("orientation_enrollments", {
            "session_id": qs("session_id"),
            "application_id": qs("application_id"),
            "status": qs("status"),
        }))

    @app.post("/orientation-enrollments/<enrollment_id>/cancel")
    def enrollment_cancel(enrollment_id):
        require_roles([ROLE_RECRUITER])
        row = must_get("orientation_enrollments", enrollment_id)
        payload = body()
        req_str(payload, "reason")
        if row["status"] in ENROLL_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Enrollment is already terminal.")
        if row["status"] != "RESERVED":
            fail("ERR_INVALID_STATE", "Enrollment is not RESERVED.")
        domain.cancel_enrollment(row)
        return ok(serialize(row))
