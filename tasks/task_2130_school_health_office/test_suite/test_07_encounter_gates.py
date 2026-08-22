"""The gates around an office encounter: building posture, cot capacity, nurse
coverage, disposition preconditions, closure and the reopen window."""

import pytest

from test_helpers import *  # noqa: F401,F403


def _uncovered_building():
    school = create_school(name="Jackson Elementary", building_code="JAC11")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student = create_student(school["id"], full_name="Noor Rahim", grade_level=2,
                             date_of_birth="2018-06-30T00:00:00Z")
    return school, nurse, student


def test_an_uncovered_building_refuses_a_new_encounter(api, admin_headers):
    """PRD §3.6: "The building's `coverage_posture` must be `FULL` or `LIMITED`; a building at
    `UNCOVERED` refuses new encounters with `ERR_SCHOOL_COVERAGE_UNAVAILABLE` at ladder position
    18."
    PRD §3.1: "When the relevant minute total is zero, the corresponding ratio is null rather than
    any numeric value."

    Design: Difficulty/cross_entity_state_dependency/visit_creation_gated_by_school_coverage_posture
    """
    school, nurse, student = _uncovered_building()
    before = validate_success(api.get_school(school["id"], admin_headers))
    assert before["delivered_weekly_minutes"] == pytest.approx(0.0, abs=0.01)
    assert before["delivered_students_per_nurse_fte"] is None
    assert before["coverage_posture"] == "UNCOVERED"

    resp = api.create_health_visit(
        {"student_id": student["id"], "school_id": school["id"], "nurse_id": nurse["id"],
         "complaint_code": "ILLNESS", "acuity": "ROUTINE"}, make_nurse_headers(nurse["id"]))
    validate_error(resp, ApiErrorId.ERR_SCHOOL_COVERAGE_UNAVAILABLE.value, 409)

    assert validate_success(api.get_school(school["id"], admin_headers))["occupied_cot_count"] == 0


def test_one_coverage_block_lifts_the_posture_and_admits_the_same_request(api, admin_headers):
    """PRD §3.1: "Reading only `delivered_students_per_nurse_fte`, a base posture is determined: a
    ratio at or below 750.00 is `FULL`; a ratio strictly above 750.00 and at or below 1500.00 is
    `LIMITED`; a ratio strictly above 1500.00, or a null ratio, is `UNCOVERED`."
    PRD §3.6: "The building's `coverage_posture` must be `FULL` or `LIMITED`; a building at
    `UNCOVERED` refuses new encounters with `ERR_SCHOOL_COVERAGE_UNAVAILABLE` at ladder position
    18."

    Design: Difficulty/cross_entity_state_dependency/visit_creation_gated_by_school_coverage_posture
    """
    school, nurse, student = _uncovered_building()
    api.create_health_visit(
        {"student_id": student["id"], "school_id": school["id"], "nurse_id": nurse["id"],
         "complaint_code": "ILLNESS", "acuity": "ROUTINE"}, make_nurse_headers(nurse["id"]))

    create_coverage(nurse["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    lifted = validate_success(api.get_school(school["id"], admin_headers))
    assert lifted["delivered_weekly_minutes"] == pytest.approx(480.0, abs=0.01)
    assert lifted["delivered_students_per_nurse_fte"] == pytest.approx(4.38, abs=0.001)
    assert lifted["coverage_posture"] == "LIMITED"

    resp = api.create_health_visit(
        {"student_id": student["id"], "school_id": school["id"], "nurse_id": nurse["id"],
         "complaint_code": "ILLNESS", "acuity": "ROUTINE"}, make_nurse_headers(nurse["id"]))
    visit = validate_success(resp, 201)
    assert visit["status"] == "OPEN"
    assert visit["triage_score"] == 26, "10 base + 8 complaint + 0 uplift + 8 coverage penalty"
    assert validate_success(api.get_school(school["id"], admin_headers))["occupied_cot_count"] == 1


def _noncompliant_illness_encounter():
    return setup_visit_in_assessment(
        school_overrides={"name": "Kennedy Elementary", "building_code": "KEN12"},
        student_overrides={"full_name": "Omar Silva", "grade_level": 5,
                           "date_of_birth": "2015-04-04T00:00:00Z",
                           "immunization_status": "NONCOMPLIANT"},
        visit_overrides={"complaint_code": "ILLNESS", "acuity": "ROUTINE"})


def test_a_noncompliant_child_with_illness_cannot_be_returned_to_class(api, admin_headers):
    """PRD §3.6: "It is barred in exactly one case — a student whose `immunization_status` is
    `NONCOMPLIANT` presenting with a `complaint_code` of `ILLNESS` may not be returned to class,
    and the attempt is refused with `ERR_IMMUNIZATION_HOLD` (HTTP 409) at ladder position 26."
    PRD §3.2: "`IMMUNIZATION_HOLD` is present when `immunization_status` is `NONCOMPLIANT`."

    Design: Difficulty/cross_entity_state_dependency/return_to_class_gated_by_student_immunization_status
    """
    ctx = _noncompliant_illness_encounter()
    student = validate_success(api.get_student(ctx["student"]["id"], admin_headers))
    assert student["intake_risk_score"] == 20
    assert "IMMUNIZATION_HOLD" in student["alert_flags"]

    resp = api.dispose_health_visit(ctx["visit"]["id"], {"disposition": "RETURN_TO_CLASS"},
                                    make_nurse_headers(ctx["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_IMMUNIZATION_HOLD.value, 409)

    visit = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert visit["status"] == "IN_ASSESSMENT"
    assert visit.get("disposition") is None
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 1


def test_correcting_the_immunization_record_admits_the_same_disposition(api, admin_headers):
    """PRD §3.2: "An amendment re-runs the intake score, re-tiers the effective score, recomputes
    the alert flags, and then re-runs the enrolled count, the stock requirement, the protocol
    status, both coverage-ratio variants and the posture for the building."
    PRD §3.6: "It is barred in exactly one case — a student whose `immunization_status` is
    `NONCOMPLIANT` presenting with a `complaint_code` of `ILLNESS` may not be returned to class,
    and the attempt is refused with `ERR_IMMUNIZATION_HOLD` (HTTP 409) at ladder position 26."

    Design: Difficulty/cross_entity_state_dependency/return_to_class_gated_by_student_immunization_status
    """
    ctx = _noncompliant_illness_encounter()
    api.dispose_health_visit(ctx["visit"]["id"], {"disposition": "RETURN_TO_CLASS"},
                             make_nurse_headers(ctx["nurse"]["id"]))

    amended = validate_success(api.patch_student(
        ctx["student"]["id"], {"immunization_status": "COMPLIANT"},
        make_nurse_headers(ctx["nurse"]["id"])))
    assert amended["immunization_status"] == "COMPLIANT"
    assert amended["intake_risk_score"] == 0
    assert "IMMUNIZATION_HOLD" not in amended["alert_flags"]

    resp = api.dispose_health_visit(ctx["visit"]["id"], {"disposition": "RETURN_TO_CLASS"},
                                    make_nurse_headers(ctx["nurse"]["id"]))
    data = validate_success(resp, 200)
    assert data["disposition"] == "RETURN_TO_CLASS"
    assert data["status"] == "DISPOSITIONED"
    assert data["guardian_notified"] is False
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 0


def _two_occupied_cots():
    base = setup_school_with_coverage(
        school_overrides={"name": "Newton Elementary", "building_code": "NEW15", "cot_capacity": 2})
    students = []
    for name, grade, dob in [("Pia Wren", 1, "2019-01-11T00:00:00Z"),
                             ("Quin Baird", 2, "2018-08-23T00:00:00Z"),
                             ("Remy Kaur", 3, "2017-10-06T00:00:00Z")]:
        students.append(create_student(base["school"]["id"], full_name=name,
                                       grade_level=grade, date_of_birth=dob))
    set_clock(MONDAY_0900)
    base["students"] = students
    base["visit_one"] = open_visit(students[0]["id"], base["school"]["id"], base["nurse"]["id"],
                                   complaint_code="ILLNESS")
    base["visit_two"] = open_visit(students[1]["id"], base["school"]["id"], base["nurse"]["id"],
                                   complaint_code="INJURY")
    return base


def test_cot_capacity_tolerates_concurrent_occupancy_up_to_the_ceiling(api, admin_headers):
    """PRD §3.6: "Unlike the pairwise coverage rule, overlap here is tolerated up to a ceiling
    rather than forbidden between pairs: the number of encounters at the building whose occupancy
    interval contains the new arrival instant — in practice, those with `status` of `OPEN`,
    `IN_ASSESSMENT` or `REOPENED`, which is exactly what `occupied_cot_count` reports — must be
    strictly less than the building's `cot_capacity`."
    PRD §3.6: "Reaching the ceiling is refused with `ERR_OFFICE_CAPACITY_EXCEEDED` (HTTP 409), and
    the same ceiling is re-checked when an encounter is reopened."

    Design: Difficulty/resource_temporal_overlap/school_cot_capacity_closed_interval_aggregate_tolerates_two
    """
    ctx = _two_occupied_cots()
    building = validate_success(api.get_school(ctx["school"]["id"], admin_headers))
    assert building["occupied_cot_count"] == 2, "two simultaneous occupancies are legal"
    assert building["delivered_students_per_nurse_fte"] == pytest.approx(13.13, abs=0.001)
    assert building["coverage_posture"] == "LIMITED"

    resp = api.create_health_visit(
        {"student_id": ctx["students"][2]["id"], "school_id": ctx["school"]["id"],
         "nurse_id": ctx["nurse"]["id"], "complaint_code": "ILLNESS", "acuity": "ROUTINE"},
        make_nurse_headers(ctx["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFICE_CAPACITY_EXCEEDED.value, 409)

    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 2


def test_disposing_an_encounter_frees_a_cot_for_the_waiting_arrival(api, admin_headers):
    """PRD §3.6: "Each disposition requires the encounter to be `IN_ASSESSMENT` and moves it to
    `DISPOSITIONED`, and every branch decrements the building's `occupied_cot_count` by one — but
    there the similarity ends, and the request carries a `disposition` plus, for one branch,
    `guardian_notified`."
    PRD §3.6: "Reaching the ceiling is refused with `ERR_OFFICE_CAPACITY_EXCEEDED` (HTTP 409), and
    the same ceiling is re-checked when an encounter is reopened."

    Design: Difficulty/resource_temporal_overlap/school_cot_capacity_closed_interval_aggregate_tolerates_two
    """
    ctx = _two_occupied_cots()
    nurse_id = ctx["nurse"]["id"]
    api.create_health_visit(
        {"student_id": ctx["students"][2]["id"], "school_id": ctx["school"]["id"],
         "nurse_id": nurse_id, "complaint_code": "ILLNESS", "acuity": "ROUTINE"},
        make_nurse_headers(nurse_id))

    assess_visit(ctx["visit_one"]["id"], nurse_id, "Sore throat, no fever")
    dispose_visit(ctx["visit_one"]["id"], nurse_id, "RETURN_TO_CLASS")
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 1

    resp = api.create_health_visit(
        {"student_id": ctx["students"][2]["id"], "school_id": ctx["school"]["id"],
         "nurse_id": nurse_id, "complaint_code": "ILLNESS", "acuity": "ROUTINE"},
        make_nurse_headers(nurse_id))
    admitted = validate_success(resp, 201)
    assert admitted["status"] == "OPEN"
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 2


def test_closing_an_encounter_that_was_never_dispositioned_is_refused(api, admin_headers):
    """PRD §3.6: "**Closure.** A `DISPOSITIONED` encounter is closed once nothing is still reserved
    against it: `pending_administration_count`, which counts the encounter's administration records
    in `PREPARED` status, must be exactly 0, or the close is refused with
    `ERR_PENDING_ADMINISTRATION` (HTTP 409) at ladder position 43."
    PRD §2.7: "The visit check guards assess, dispose, close and reopen, and it also guards both
    dose-preparation endpoints, because preparing a dose requires the encounter to be
    `IN_ASSESSMENT` or `DISPOSITIONED`."

    Design: Corner/state_machines/health_visit_close_from_open_rejected
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Fox Run Elementary", "building_code": "FOX34"},
        student_overrides={"full_name": "Finn Ober", "grade_level": 3,
                           "date_of_birth": "2017-03-22T00:00:00Z"})
    set_clock(MONDAY_0900)
    visit = open_visit(base["student"]["id"], base["school"]["id"], base["nurse"]["id"],
                       complaint_code="ILLNESS")

    resp = api.close_health_visit(visit["id"], make_nurse_headers(base["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VISIT_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_health_visit(visit["id"], admin_headers))
    assert unchanged["status"] == "OPEN"
    assert unchanged.get("closed_at") is None
    assert unchanged.get("minutes_in_office") is None
    assert validate_success(api.get_school(base["school"]["id"], admin_headers))["occupied_cot_count"] == 1


def test_a_full_office_at_an_uncovered_building_reports_the_coverage_failure(api, admin_headers):
    """PRD §2.7: "A full office at an `UNCOVERED` building returns
    `ERR_SCHOOL_COVERAGE_UNAVAILABLE`, not `ERR_OFFICE_CAPACITY_EXCEEDED`."
    PRD §3.6: "Only then does the cot check at position 34 apply."

    Design: Corner/validations/conflict_c_school_coverage_outranks_office_capacity
    """
    base = setup_school_with_coverage(
        school_overrides={"name": "Voltaire Elementary", "building_code": "VLT50", "cot_capacity": 2})
    students = [create_student(base["school"]["id"], full_name=name, grade_level=grade,
                               date_of_birth=dob)
                for name, grade, dob in [("Vera Lund", 2, "2018-02-02T00:00:00Z"),
                                         ("Vik Rao", 3, "2017-03-03T00:00:00Z"),
                                         ("Vida Chan", 4, "2016-04-04T00:00:00Z")]]
    set_clock(MONDAY_0900)
    open_visit(students[0]["id"], base["school"]["id"], base["nurse"]["id"], complaint_code="ILLNESS")
    open_visit(students[1]["id"], base["school"]["id"], base["nurse"]["id"], complaint_code="INJURY")
    ended = end_coverage(base["coverage"]["id"], "2026-07-15T00:00:00Z")
    assert ended["status"] == "ENDED"

    before = validate_success(api.get_school(base["school"]["id"], admin_headers))
    assert before["delivered_weekly_minutes"] == pytest.approx(0.0, abs=0.01)
    assert before["coverage_posture"] == "UNCOVERED"
    assert before["occupied_cot_count"] == 2
    assert before["cot_capacity"] == 2

    resp = api.create_health_visit(
        {"student_id": students[2]["id"], "school_id": base["school"]["id"],
         "nurse_id": base["nurse"]["id"], "complaint_code": "ILLNESS", "acuity": "ROUTINE"},
        make_nurse_headers(base["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SCHOOL_COVERAGE_UNAVAILABLE.value, 409)

    assert validate_success(api.get_school(base["school"]["id"], admin_headers))["occupied_cot_count"] == 2


def test_assessing_off_the_nurses_covered_weekday_is_refused(api, admin_headers):
    """PRD §3.6: "It additionally requires the acting nurse to be physically on coverage at that
    moment: a coverage block must exist for that nurse at that building whose `status` is `ACTIVE`,
    whose `weekday` matches the weekday of the logical clock, and whose minute range contains the
    clock's minute-of-day, counting from `start_minute` inclusive to `end_minute` exclusive.
    Failing that, the step is refused with `ERR_NURSE_NOT_ON_COVERAGE` (HTTP 409) at ladder
    position 19."

    Design: Corner/errors/error_nurse_not_on_coverage_when_the_block_is_on_another_weekday
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Ridgeway Elementary", "building_code": "RDG82"},
        coverage_overrides={"weekday": "TUE"},
        student_overrides={"full_name": "Rex Halloran", "grade_level": 4,
                           "date_of_birth": "2016-12-24T00:00:00Z"})
    block = validate_success(api.get_coverage_assignment(base["coverage"]["id"], admin_headers))
    assert block["status"] == "ACTIVE"
    assert block["weekday"] == "TUE"
    set_clock(MONDAY_0900)
    visit = open_visit(base["student"]["id"], base["school"]["id"], base["nurse"]["id"],
                       complaint_code="ILLNESS")
    assert validate_success(api.get_school(base["school"]["id"], admin_headers))["coverage_posture"] == "LIMITED"

    resp = api.assess_health_visit(visit["id"], {"assessment_note": "Monday assessment attempt"},
                                   make_nurse_headers(base["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NURSE_NOT_ON_COVERAGE.value, 409)

    unchanged = validate_success(api.get_health_visit(visit["id"], admin_headers))
    assert unchanged["status"] == "OPEN"
    assert unchanged.get("assessment_note") is None


def test_sending_a_child_home_requires_the_guardian_notification_flag(api, admin_headers):
    """PRD §3.6: "**`SEND_HOME`** requires the request body to carry `guardian_notified` as true;
    without it the disposition is refused with `ERR_GUARDIAN_NOTIFICATION_REQUIRED` (HTTP 409) at
    position 27."

    Design: Corner/errors/error_guardian_notification_required_on_send_home
    """
    ctx = setup_visit_in_assessment(
        school_overrides={"name": "Summit Elementary", "building_code": "SMT83"},
        student_overrides={"full_name": "Sol Bergeron", "grade_level": 2,
                           "date_of_birth": "2018-10-30T00:00:00Z"},
        visit_overrides={"complaint_code": "ILLNESS"})
    nurse_headers = make_nurse_headers(ctx["nurse"]["id"])

    refused = api.dispose_health_visit(ctx["visit"]["id"], {"disposition": "SEND_HOME"}, nurse_headers)
    validate_error(refused, ApiErrorId.ERR_GUARDIAN_NOTIFICATION_REQUIRED.value, 409)

    held = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert held["status"] == "IN_ASSESSMENT"
    assert held.get("disposition") is None
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 1

    accepted = validate_success(api.dispose_health_visit(
        ctx["visit"]["id"], {"disposition": "SEND_HOME", "guardian_notified": True}, nurse_headers))
    assert accepted["disposition"] == "SEND_HOME"
    assert accepted["guardian_notified"] is True
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 0


def test_a_reopen_at_exactly_the_deadline_is_refused(api, admin_headers):
    """PRD §3.6: "Only a school nurse may reopen, and only within 120 minutes of closure: a reopen
    at or after that deadline is refused with `ERR_REOPEN_WINDOW_CLOSED` (HTTP 409) at ladder
    position 36."

    Design: Corner/errors/error_reopen_window_closed_at_exactly_120_minutes
    """
    ctx = setup_closed_visit(
        school_overrides={"name": "Tidewater Elementary", "building_code": "TDW84"},
        student_overrides={"full_name": "Tam Oyelaran", "grade_level": 3,
                           "date_of_birth": "2017-04-04T00:00:00Z"},
        visit_overrides={"complaint_code": "INJURY"})
    assert ctx["visit"]["closed_at"].startswith("2026-08-03T09:30:00")

    set_clock("2026-08-03T11:30:00Z")
    resp = api.reopen_health_visit(ctx["visit"]["id"], make_nurse_headers(ctx["nurse"]["id"]),
                                   {"reason_code": "Late return"})
    validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_CLOSED.value, 409)

    unchanged = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert unchanged["status"] == "CLOSED"
    assert unchanged["reopen_count"] == 0
    assert unchanged["minutes_in_office"] == 30
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 0


def test_a_second_reopen_is_refused_even_inside_the_window(api, admin_headers):
    """PRD §3.6: "`reopen_count` must still be below 1, so a second reopen is refused with
    `ERR_REOPEN_LIMIT_REACHED` (HTTP 409) at position 45, and a cot must be free under the capacity
    rule."

    Design: Corner/errors/error_reopen_limit_reached_on_the_second_reopen
    """
    ctx = setup_closed_visit(
        school_overrides={"name": "Union Elementary", "building_code": "UNI85"},
        student_overrides={"full_name": "Uzo Kimani", "grade_level": 5,
                           "date_of_birth": "2015-07-17T00:00:00Z"},
        visit_overrides={"complaint_code": "INJURY"})
    nurse_id = ctx["nurse"]["id"]

    reopened = reopen_visit(ctx["visit"]["id"], nurse_id, "Pain returned")
    assert reopened["reopen_count"] == 1
    assess_visit(ctx["visit"]["id"], nurse_id, "Swelling now visible")
    dispose_visit(ctx["visit"]["id"], nurse_id, "RETURN_TO_CLASS")
    set_clock("2026-08-03T09:40:00Z")
    closed_again = close_visit(ctx["visit"]["id"], nurse_id)
    assert closed_again["closed_at"].startswith("2026-08-03T09:40:00")

    resp = api.reopen_health_visit(ctx["visit"]["id"], make_nurse_headers(nurse_id),
                                   {"reason_code": "Third look"})
    validate_error(resp, ApiErrorId.ERR_REOPEN_LIMIT_REACHED.value, 409)

    unchanged = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert unchanged["reopen_count"] == 1
    assert unchanged["status"] == "CLOSED"
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 0


def test_a_still_reserved_dose_blocks_the_close_until_its_outcome_is_recorded(api, admin_headers):
    """PRD §3.6: "**Closure.** A `DISPOSITIONED` encounter is closed once nothing is still reserved
    against it: `pending_administration_count`, which counts the encounter's administration records
    in `PREPARED` status, must be exactly 0, or the close is refused with
    `ERR_PENDING_ADMINISTRATION` (HTTP 409) at ladder position 43."
    PRD §3.7: "An `outcome` of `ADMINISTERED` stamps `administered_at` with the clock and moves
    `units` from `quantity_reserved` to `quantity_administered`; a lot whose `quantity_on_hand` now
    stands at 0 moves `AVAILABLE` → `DEPLETED`; the encounter's `pending_administration_count` is
    decremented by one; the order's `doses_administered_today` and `last_administered_at` are
    recomputed; the student's `observed_risk_score`, `effective_risk_score` and `risk_tier` are
    recomputed; and the lot's days of supply, the building's two days-of-supply figures, protocol
    status and posture are recomputed."

    Design: Corner/errors/error_pending_administration_blocks_visit_close
    """
    ctx = setup_dose_prepared(
        units=1,
        school_overrides={"name": "Vista Elementary", "building_code": "VST86"},
        student_overrides={"full_name": "Vera Ilunga", "grade_level": 6,
                           "date_of_birth": "2014-07-27T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-VST-1",
                       "initial_quantity": 5})
    nurse_id = ctx["nurse"]["id"]
    dispose_visit(ctx["visit"]["id"], nurse_id, "RETURN_TO_CLASS")

    blocked = api.close_health_visit(ctx["visit"]["id"], make_nurse_headers(nurse_id))
    validate_error(blocked, ApiErrorId.ERR_PENDING_ADMINISTRATION.value, 409)
    held = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert held["status"] == "DISPOSITIONED"
    assert held.get("closed_at") is None
    assert held["pending_administration_count"] == 1

    given = record_outcome(ctx["record"]["id"], "ADMINISTERED", nurse_id)
    assert given["status"] == "ADMINISTERED"
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 0
    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_administered"] == 1
    assert lot["quantity_reserved"] == 0

    closed = validate_success(api.close_health_visit(ctx["visit"]["id"], make_nurse_headers(nurse_id)))
    assert closed["status"] == "CLOSED"
    assert closed["minutes_in_office"] == 0
