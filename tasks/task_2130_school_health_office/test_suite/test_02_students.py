"""Enrolling a child: the two risk-score variants, alert flags, amendment cascades
and the optimistic-concurrency guard on the student row."""

import pytest

from test_helpers import *  # noqa: F401,F403


def _observed_risk_scenario():
    """A child whose declared profile scores 15 and whose encounter history scores 26."""
    school = create_school(name="Risk Ridge Elementary", building_code="RSK18")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    create_coverage(nurse["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    student = create_student(school["id"], full_name="Dev Patel", grade_level=6,
                             date_of_birth="2014-06-05T00:00:00Z", allergy_severity="MILD",
                             chronic_condition_codes=["T1DM"], immunization_status="COMPLIANT")
    create_lot(school["id"], medication_code="EPINEPHRINE", lot_number="EPI-RSK-1",
               is_stock_protocol=True, initial_quantity=10)
    set_clock(MONDAY_0900)
    visit = open_visit(student["id"], school["id"], nurse["id"],
                       complaint_code="ILLNESS", acuity="URGENT")
    assess_visit(visit["id"], nurse["id"], "Wheeze on exertion, guardian contacted")
    record = prepare_stock_dose(visit["id"], "EPINEPHRINE", nurse["id"], units=1)
    record_outcome(record["id"], "ADMINISTERED", nurse["id"])
    dispose_visit(visit["id"], nurse["id"], "SEND_HOME", guardian_notified=True)
    set_clock("2026-08-03T09:30:00Z")
    return school, nurse, student, visit


def test_intake_and_observed_risk_scores_are_stored_side_by_side(api, admin_headers):
    """PRD §3.2: "It awards 0 points for an `allergy_severity` of `NONE`, 5 for `MILD`, 15 for
    `MODERATE` and 40 for `ANAPHYLAXIS`; it adds 10 points for each entry in
    `chronic_condition_codes`; and it adds 0 points for a `COMPLIANT` immunisation status, 5 for
    `PROVISIONAL`, 5 for `EXEMPT` and 20 for `NONCOMPLIANT`."
    PRD §3.2: "The score awards 6 points for each qualifying encounter, a further 12 points for
    each encounter in the send-home-or-transport subset, and 8 points for each emergency-stock
    administration; the total is capped at 100 and stored as `observed_risk_score`."

    Design: Difficulty/dual_variant_calc/student_risk_intake_vs_observed_diverge
    """
    _, nurse, student, visit = _observed_risk_scenario()
    close_visit(visit["id"], nurse["id"])

    data = validate_success(api.get_student(student["id"], admin_headers))
    assert_student(data)
    assert data["intake_risk_score"] == 15, "MILD allergy 5 + one chronic condition 10"
    assert data["observed_risk_score"] == 26, "6 for the encounter + 12 for the send-home + 8 for the stock dose"
    assert data["intake_risk_score"] != data["observed_risk_score"]


def test_the_larger_risk_variant_drives_the_effective_score_and_tier(api, admin_headers):
    """PRD §3.2: "Both scores are stored side by side. `effective_risk_score` is the larger of the
    two, and `risk_tier` reads that effective score: below 25 is `ROUTINE`, from 25 up to but not
    including 60 is `ELEVATED`, and 60 or above is `CRITICAL`."
    PRD §3.6: "On closure `closed_at` is stamped with the clock, `status` becomes `CLOSED`,
    `minutes_in_office` is set to the whole minutes between `arrival_at` and `closed_at` with any
    fraction discarded, and the student's observed score, effective score and tier are recomputed."

    Design: Difficulty/dual_variant_calc/student_risk_intake_vs_observed_diverge
    """
    _, nurse, student, visit = _observed_risk_scenario()

    closed = close_visit(visit["id"], nurse["id"])
    assert closed["status"] == "CLOSED"
    assert closed["minutes_in_office"] == 30

    data = validate_success(api.get_student(student["id"], admin_headers))
    assert data["effective_risk_score"] == 26
    assert data["risk_tier"] == "ELEVATED", "the observed variant lifts the child out of ROUTINE"


def test_student_list_paginates_with_total_count_and_has_more(api, admin_headers):
    """PRD §2.3: "`limit` defaults to 10, may be no smaller than 1 and no larger than 100."
    PRD §2.3: "Results are ordered by `created_at` ascending unless a subsection below states
    otherwise, and the `meta` object of a list response carries `limit`, `offset`, `total_count`
    (the number of rows matching the filter before the page window is applied) and `has_more`
    (true when rows remain beyond the current window)."

    Design: Corner/entities/student_list_pagination_reports_total_count_and_has_more
    """
    school = create_school(name="Rivera Elementary", building_code="RIV21")
    for name, grade, dob in [("Page One", 1, "2019-01-01T00:00:00Z"),
                             ("Page Two", 2, "2018-01-01T00:00:00Z"),
                             ("Page Three", 3, "2017-01-01T00:00:00Z")]:
        create_student(school["id"], full_name=name, grade_level=grade, date_of_birth=dob)

    first, meta = validate_paginated(api.list_students(
        admin_headers, {"school_id": school["id"], "limit": 2, "offset": 0}))
    assert len(first) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    second, meta2 = validate_paginated(api.list_students(
        admin_headers, {"school_id": school["id"], "limit": 2, "offset": 2}))
    assert len(second) == 1
    assert meta2["total_count"] == 3
    assert meta2["offset"] == 2
    assert meta2["has_more"] is False


def test_alert_flags_are_computed_at_enrolment_and_sorted_ascending(api, admin_headers):
    """PRD §3.2: "**Alert flags**, stored as `alert_flags`, are a computed list of strings held in
    ascending sorted order and recomputed on every profile, plan and authorisation mutation."
    PRD §3.2: "`ALLERGY_ANAPHYLAXIS` is present when `allergy_severity` is `ANAPHYLAXIS`."
    PRD §3.2: "`IMMUNIZATION_HOLD` is present when `immunization_status` is `NONCOMPLIANT`."
    PRD §3.2: "`NO_ACTIVE_PLAN` is present whenever the student has no plan currently in force —
    it is always present at enrolment."

    Design: Corner/entities/student_alert_flags_computed_and_sorted_ascending_on_creation
    """
    school = create_school(name="Whitman Elementary", building_code="WHT26")

    resp = api.create_student(
        {"school_id": school["id"], "full_name": "Wes Tobin", "grade_level": 9,
         "date_of_birth": "2011-05-05T00:00:00Z", "allergy_severity": "ANAPHYLAXIS",
         "chronic_condition_codes": [], "immunization_status": "NONCOMPLIANT"},
        admin_headers)
    data = validate_success(resp, 201)
    assert_student(data)

    assert data["enrollment_status"] == "ENROLLED"
    assert data["intake_risk_score"] == 60, "ANAPHYLAXIS 40 + NONCOMPLIANT 20"
    assert data["observed_risk_score"] == 0
    assert data["effective_risk_score"] == 60
    assert data["risk_tier"] == "CRITICAL"
    assert data["alert_flags"] == ["ALLERGY_ANAPHYLAXIS", "IMMUNIZATION_HOLD", "NO_ACTIVE_PLAN"]
    assert data.get("active_action_plan_id") is None
    assert data["self_carry_authorized"] is False

    building = validate_success(api.get_school(school["id"], admin_headers))
    assert building["eligible_stock_student_count"] == 1
    assert building["required_stock_units"] == 1


def test_enrolment_rejects_an_allergy_severity_outside_the_declared_enum(api, admin_headers):
    """PRD §3.2: "Enrolment is performed by a district administrator or a school nurse and records
    the child's building via `school_id`, a `full_name`, a `grade_level` between 0 and 12
    inclusive, a `date_of_birth`, the highest documented `allergy_severity` of `NONE`, `MILD`,
    `MODERATE` or `ANAPHYLAXIS`, a list of `chronic_condition_codes` drawn from `ASTHMA`, `T1DM`,
    `SEIZURE`, `CARDIAC` and `MENTAL_HEALTH` (which may be empty), an `immunization_status` of
    `COMPLIANT`, `PROVISIONAL`, `EXEMPT` or `NONCOMPLIANT`, and an optional `privacy_hold` flag
    defaulting to false."
    PRD §2.7: "Then every supplied field satisfies its declared type, enum membership and numeric
    range — including `limit` within 1 to 100 and `offset` at least 0 on list endpoints — else
    `ERR_INVALID_FIELD_VALUE` (position 6, HTTP 422)."

    Design: Corner/entities/student_create_invalid_enum_allergy_severity_rejected
    """
    school = create_school(name="Yates Elementary", building_code="YAT27")

    resp = api.create_student(
        {"school_id": school["id"], "full_name": "Yara Cole", "grade_level": 4,
         "date_of_birth": "2016-07-07T00:00:00Z", "allergy_severity": "SEVERE",
         "chronic_condition_codes": [], "immunization_status": "COMPLIANT"},
        admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_FIELD_VALUE.value, 422)

    building = validate_success(api.get_school(school["id"], admin_headers))
    assert building["enrolled_student_count"] == 0


def test_intake_risk_score_is_clamped_at_one_hundred(api, admin_headers):
    """PRD §3.2: "Those three contributions are summed and the total is capped at 100, giving
    `intake_risk_score`."

    Design: Corner/calculations/intake_risk_score_clamped_at_one_hundred
    """
    school = create_school(name="Talbot Elementary", building_code="TAL48")

    resp = api.create_student(
        {"school_id": school["id"], "full_name": "Tao Villar", "grade_level": 10,
         "date_of_birth": "2010-01-20T00:00:00Z", "allergy_severity": "ANAPHYLAXIS",
         "chronic_condition_codes": ["ASTHMA", "T1DM", "SEIZURE", "CARDIAC", "MENTAL_HEALTH"],
         "immunization_status": "NONCOMPLIANT"},
        admin_headers)
    data = validate_success(resp, 201)

    assert data["intake_risk_score"] == 100, "40 + 50 + 20 sums to 110 and clamps to 100"
    assert data["observed_risk_score"] == 0
    assert data["effective_risk_score"] == 100
    assert data["risk_tier"] == "CRITICAL"

    building = validate_success(api.get_school(school["id"], admin_headers))
    assert building["eligible_stock_student_count"] == 1
    assert building["required_stock_units"] == 1


def test_withdrawing_a_student_declines_their_scheduled_screenings(api, admin_headers):
    """PRD §3.2: "One amendment carries a further consequence: when `enrollment_status` moves out
    of `ENROLLED`, every screening for that student sitting in `SCHEDULED` or `RESCREEN_DUE` is
    moved to `DECLINED`."
    PRD §3.3: "Step one counts the eligible population: `eligible_stock_student_count` is the
    number of `ENROLLED` students at the building whose `allergy_severity` is `ANAPHYLAXIS` or
    whose `chronic_condition_codes` include `ASTHMA`, with a student meeting both criteria counted
    once."

    Design: Corner/state_machines/student_withdrawal_cascades_scheduled_screenings_to_declined
    """
    school = create_school(name="Holmes Elementary", building_code="HLM36")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    create_coverage(nurse["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    student = create_student(school["id"], full_name="Hugo Salt", grade_level=4,
                             date_of_birth="2016-10-10T00:00:00Z", allergy_severity="ANAPHYLAXIS")
    vision = create_screening(student["id"], school["id"], nurse["id"],
                              screening_type="VISION", scheduled_for="2026-08-10T10:00:00Z")
    hearing = create_screening(student["id"], school["id"], nurse["id"],
                               screening_type="HEARING", scheduled_for="2026-08-11T10:00:00Z")

    patched = validate_success(api.patch_student(
        student["id"], {"enrollment_status": "WITHDRAWN"}, admin_headers))
    assert patched["enrollment_status"] == "WITHDRAWN"

    assert validate_success(api.get_screening(vision["id"], admin_headers))["status"] == "DECLINED"
    assert validate_success(api.get_screening(hearing["id"], admin_headers))["status"] == "DECLINED"

    building = validate_success(api.get_school(school["id"], admin_headers))
    assert building["enrolled_student_count"] == 0
    assert building["eligible_stock_student_count"] == 0
    assert building["required_stock_units"] == 0
    assert building["contracted_weekly_minutes"] == 480, "staffing is untouched by the withdrawal"
    assert building["delivered_weekly_minutes"] == pytest.approx(480.0, abs=0.01)
    assert building["delivered_students_per_nurse_fte"] == pytest.approx(0.0, abs=0.001)
    assert building["coverage_posture"] == "LIMITED"


def test_a_withdrawn_student_cannot_be_booked_for_a_screening(api, admin_headers):
    """PRD §3.2: "Records themselves survive withdrawal — a disclosure request may be opened for a
    student in any enrolment state — but clinical activity does not: creating an action plan, a
    medication order, an encounter or a screening for a student who is not `ENROLLED`, and likewise
    submitting a plan or recording guardian consent on a medication order for such a student, is
    refused with `ERR_STUDENT_NOT_ENROLLED` (HTTP 409) at ladder position 17."

    Design: Corner/validations/withdrawn_student_blocks_new_screening
    """
    school = create_school(name="Arbor Elementary", building_code="ARB55")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    withdrawn = create_student(school["id"], full_name="Abe Ferris", grade_level=3,
                               date_of_birth="2017-01-31T00:00:00Z")
    enrolled = create_student(school["id"], full_name="Ada Ferris", grade_level=3,
                              date_of_birth="2017-01-31T00:00:00Z")
    amend_student(withdrawn["id"], {"enrollment_status": "WITHDRAWN"})

    refused = api.create_screening(
        {"student_id": withdrawn["id"], "school_id": school["id"],
         "screening_type": "HEARING", "scheduled_for": "2026-08-10T10:00:00Z"},
        make_nurse_headers(nurse["id"]))
    validate_error(refused, ApiErrorId.ERR_STUDENT_NOT_ENROLLED.value, 409)

    accepted = api.create_screening(
        {"student_id": enrolled["id"], "school_id": school["id"],
         "screening_type": "HEARING", "scheduled_for": "2026-08-10T10:00:00Z"},
        make_nurse_headers(nurse["id"]))
    booked = validate_success(accepted, 201)
    assert booked["status"] == "SCHEDULED"
    assert booked["cycle_number"] == 1
    assert booked.get("outcome") is None

    _, meta = validate_paginated(api.list_screenings(admin_headers, {"student_id": withdrawn["id"]}))
    assert meta["total_count"] == 0
    assert validate_success(api.get_school(school["id"], admin_headers))["enrolled_student_count"] == 1


def test_stale_student_version_rejects_an_action_plan_draft(api, admin_headers):
    """PRD §2.6: "A `POST /health-office/action-plans` request must carry
    `expected_student_version`, holding the client's last observed `version` of the target
    `Student`. If the student's current `version` differs, the create is rejected with
    `ERR_STALE_STUDENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_student_version_rejects_action_plan_create
    """
    school = create_school(name="Jetty Elementary", building_code="JTY70")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student = create_student(school["id"], full_name="Jae Kwon", grade_level=4,
                             date_of_birth="2016-04-14T00:00:00Z", allergy_severity="MILD",
                             chronic_condition_codes=["ASTHMA"])
    stale_version = student["version"]
    patched = amend_student(student["id"], {"immunization_status": "PROVISIONAL"})

    nurse_headers = make_nurse_headers(nurse["id"])
    body = {"student_id": student["id"], "condition_code": "ASTHMA", "severity_score": 3,
            "requires_stock_epinephrine": False, "self_carry_requested": False,
            "effective_from": "2026-08-01T00:00:00Z", "expected_student_version": stale_version}
    refused = api.create_action_plan(body, nurse_headers)
    validate_error(refused, ApiErrorId.ERR_STALE_STUDENT_VERSION.value, 412)

    _, meta = validate_paginated(api.list_action_plans(admin_headers, {"student_id": student["id"]}))
    assert meta["total_count"] == 0
    fresh = validate_success(api.get_student(student["id"], admin_headers))
    assert fresh["version"] == patched["version"], "the refused create does not bump the student"

    body["expected_student_version"] = fresh["version"]
    accepted = validate_success(api.create_action_plan(body, nurse_headers), 201)
    assert accepted["status"] == "DRAFT"
    after = validate_success(api.get_student(student["id"], admin_headers))
    assert after["version"] == fresh["version"] + 1


def test_action_plan_for_an_unknown_student_is_a_not_found_before_the_version_check(api, admin_headers):
    """PRD §2.7: "Every referenced row exists. References are validated left to right: path
    parameters first, in URL order, then body foreign keys in the order they appear in the
    endpoint's input list. Any miss is `ERR_RESOURCE_NOT_FOUND`."
    PRD §2.7: "**Optimistic concurrency (positions 14 to 16).** `expected_student_version` on
    action-plan creation (position 14), `expected_authorization_version` on dose preparation
    (position 15), `expected_lot_version` on an inventory action (position 16)."

    Design: Corner/entities/action_plan_create_with_unknown_student_id_returns_not_found
    """
    school = create_school(name="Zane Elementary", building_code="ZAN28")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student = create_student(school["id"], full_name="Zoe Hart", grade_level=5,
                             date_of_birth="2015-08-08T00:00:00Z")

    resp = api.create_action_plan(
        {"student_id": NON_EXISTENT_UUID, "condition_code": "ASTHMA", "severity_score": 2,
         "requires_stock_epinephrine": False, "self_carry_requested": False,
         "effective_from": "2026-08-01T00:00:00Z",
         "expected_student_version": student["version"]},
        make_nurse_headers(nurse["id"]))
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

    _, meta = validate_paginated(api.list_action_plans(admin_headers, {"student_id": student["id"]}))
    assert meta["total_count"] == 0
    assert validate_success(api.get_student(student["id"], admin_headers))["version"] == student["version"]
