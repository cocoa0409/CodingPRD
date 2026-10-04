"""Personnel competency, method validations, and readiness posture."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_approved_method_validation,
    create_competency_assessment_payload,
    create_qualified_personnel,
    get_success_data,
    make_director_headers,
    setup_lab_with_active_enrollment,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


def test_competency_composite_round_then_sum_ordering(api):
    """PRD §2.10: "A competency `composite_score` is expressed with exactly two
    decimal places, rounded half-up, and — critically — each per-element weight
    contributing to it is itself rounded half-up to four decimal places
    *before* the weights are summed. This round-then-sum order is pinned;
    summing raw ratios and rounding only at the end can differ in the second
    decimal place and is not an acceptable implementation."
    PRD §3.5: "The assessment `passed` when the `composite_score` is at least
    85.0 and every element score is at least 70."
    PRD §3.5: "Its `valid_until` is exactly 365 days after `assessed_at`,
    treated as a closed interval end."

    Design: Difficulty/combinatorial_formula/competency_composite_round_then_sum_ordering
    """
    ctx = setup_lab_with_active_enrollment(discipline="HEMATOLOGY",
                                           checklist_code="HEM")
    pers = create_qualified_personnel(ctx["enrollment"]["id"], ctx["lab"]["id"],
                                      person_name="Sam Slide")
    payload = create_competency_assessment_payload(
        personnel_id=pers["id"], assessed_at="2026-09-05T00:00:00Z",
        element_scores=[88, 88, 88, 88, 88, 83])
    resp = api.create_competency_assessment(
        payload, make_director_headers(ctx["lab"]["id"]))
    data = validate_success(resp, expected_status=201)
    # Round-then-sum: 6 * round_half_up(88/600, 4) etc. yields 87.18, not 87.17.
    assert data["composite_score"] == 87.18
    assert data["passed"] is True
    assert data["valid_until"] == "2027-09-05T00:00:00Z"
    pers_after = get_success_data(api.get_personnel_record(pers["id"], OFFICER))
    assert pers_after["qualification_status"] == "QUALIFIED"
    assert pers_after["consecutive_failed_assessments"] == 0


def test_competency_composite_element_floor_fails_despite_high_average(api):
    """PRD §3.5: "The assessment `passed` when the `composite_score` is at
    least 85.0 and every element score is at least 70."

    Design: Difficulty/combinatorial_formula/competency_composite_round_then_sum_ordering
    """
    ctx = setup_lab_with_active_enrollment(discipline="HEMATOLOGY",
                                           checklist_code="HEM")
    pers = create_qualified_personnel(ctx["enrollment"]["id"], ctx["lab"]["id"])
    payload = create_competency_assessment_payload(
        personnel_id=pers["id"], assessed_at="2026-09-05T00:00:00Z",
        element_scores=[100, 100, 100, 100, 100, 69])
    resp = api.create_competency_assessment(
        payload, make_director_headers(ctx["lab"]["id"]))
    data = validate_success(resp, expected_status=201)
    # Composite is well above 85 but one element is below the 70 floor.
    assert data["passed"] is False


def test_personnel_competency_review_qualification_cycle_and_disqualification(api):
    """PRD §3.5: "A passing assessment moves the person to `QUALIFIED`
    (including recovery from `COMPETENCY_REVIEW`) and resets
    `consecutive_failed_assessments` to zero. A failing assessment increments
    `consecutive_failed_assessments`; when the count is below two the person
    moves from `QUALIFIED` to `COMPETENCY_REVIEW`, and when the count reaches
    two the person moves to `DISQUALIFIED` — from either `QUALIFIED` or
    `COMPETENCY_REVIEW`."

    Design: Difficulty/non_linear_state_machine/personnel_competency_review_qualification_cycle_and_disqualification
    """
    ctx = setup_lab_with_active_enrollment(discipline="IMMUNOLOGY",
                                           checklist_code="IMM")
    lab_id = ctx["lab"]["id"]
    pers = create_qualified_personnel(ctx["enrollment"]["id"], lab_id,
                                      person_name="Tina Titer")
    director = make_director_headers(lab_id)

    def assess(assessed_at, scores):
        return get_success_data(api.create_competency_assessment(
            create_competency_assessment_payload(
                personnel_id=pers["id"], assessed_at=assessed_at,
                element_scores=scores),
            director))

    # A1 fails on the element floor: streak 1, COMPETENCY_REVIEW.
    assess("2026-09-02T00:00:00Z", [90, 90, 90, 90, 90, 60])
    p1 = get_success_data(api.get_personnel_record(pers["id"], OFFICER))
    assert p1["qualification_status"] == "COMPETENCY_REVIEW"
    assert p1["consecutive_failed_assessments"] == 1

    # A2 passes: back to QUALIFIED, streak reset.
    assess("2026-09-03T00:00:00Z", [90, 90, 90, 90, 90, 90])
    p2 = get_success_data(api.get_personnel_record(pers["id"], OFFICER))
    assert p2["qualification_status"] == "QUALIFIED"
    assert p2["consecutive_failed_assessments"] == 0

    # A3 fails: COMPETENCY_REVIEW, streak 1.
    assess("2026-09-04T00:00:00Z", [50, 50, 50, 50, 50, 50])
    p3 = get_success_data(api.get_personnel_record(pers["id"], OFFICER))
    assert p3["qualification_status"] == "COMPETENCY_REVIEW"
    assert p3["consecutive_failed_assessments"] == 1

    # A4 fails: streak reaches 2 -> DISQUALIFIED.
    assess("2026-09-05T00:00:00Z", [50, 50, 50, 50, 50, 50])
    p4 = get_success_data(api.get_personnel_record(pers["id"], OFFICER))
    assert p4["qualification_status"] == "DISQUALIFIED"
    assert p4["consecutive_failed_assessments"] == 2


def test_personnel_verify_then_single_failed_assessment_moves_to_review(api):
    """PRD §3.5: "A failing assessment increments
    `consecutive_failed_assessments`; when the count is below two the person
    moves from `QUALIFIED` to `COMPETENCY_REVIEW`"
    PRD §3.5: "An `AccreditationOfficer` verifies the record, moving it from
    `PROVISIONAL` to `QUALIFIED` (from any other state the verification fails
    with `ERR_INVALID_STATE`). `DISQUALIFIED` is terminal."

    Design: Difficulty/non_linear_state_machine/personnel_competency_review_qualification_cycle_and_disqualification
    """
    ctx = setup_lab_with_active_enrollment(discipline="IMMUNOLOGY",
                                           checklist_code="IMM")
    lab_id = ctx["lab"]["id"]
    pers = create_qualified_personnel(ctx["enrollment"]["id"], lab_id)
    assert pers["qualification_status"] == "QUALIFIED"

    get_success_data(api.create_competency_assessment(
        create_competency_assessment_payload(
            personnel_id=pers["id"], assessed_at="2026-09-02T00:00:00Z",
            element_scores=[90, 90, 90, 90, 90, 60]),
        make_director_headers(lab_id)))
    p = get_success_data(api.get_personnel_record(pers["id"], OFFICER))
    assert p["qualification_status"] == "COMPETENCY_REVIEW"
    assert p["consecutive_failed_assessments"] == 1

    # Verification from COMPETENCY_REVIEW is not admitted.
    resp = api.verify_qualification(pers["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_method_validation_approval_thresholds(api):
    """PRD §3.5: "Approval requires the record to be `SUBMITTED` (else
    `ERR_INVALID_STATE`), the parent enrollment to be `ACTIVE` (else
    `ERR_ENROLLMENT_INACTIVE`), and the study to meet both thresholds:
    `correlation_r_squared` at least 0.95 and `precision_cv_pct` at most 10.0,
    failing which the request is rejected with
    `ERR_VALIDATION_STUDY_INADEQUATE`."

    Design: Corner/calculations/method_validation_approval_thresholds
    """
    ctx = setup_lab_with_active_enrollment()
    lab_id = ctx["lab"]["id"]
    enr_id = ctx["enrollment"]["id"]
    director = make_director_headers(lab_id)

    def make_mv(name, r2, cv):
        mv = get_success_data(api.create_method_validation(
            {"enrollment_id": enr_id, "method_name": name,
             "instrument_name": "I", "correlation_r_squared": r2,
             "precision_cv_pct": cv}, director))
        get_success_data(api.submit_method_validation(mv["id"], director))
        return mv

    mv_ok = make_mv("MV_OK", 0.95, 10.0)
    mv_lo = make_mv("MV_LO", 0.949, 5.0)
    mv_hi = make_mv("MV_HI", 0.99, 10.01)

    ok = get_success_data(api.approve_method_validation(mv_ok["id"], OFFICER))
    assert ok["status"] == "APPROVED"

    resp_lo = api.approve_method_validation(mv_lo["id"], OFFICER)
    validate_error(resp_lo, ApiErrorId.ERR_VALIDATION_STUDY_INADEQUATE.value, 409)
    assert get_success_data(
        api.get_method_validation(mv_lo["id"], OFFICER))["status"] == "SUBMITTED"

    resp_hi = api.approve_method_validation(mv_hi["id"], OFFICER)
    validate_error(resp_hi, ApiErrorId.ERR_VALIDATION_STUDY_INADEQUATE.value, 409)
    assert get_success_data(
        api.get_method_validation(mv_hi["id"], OFFICER))["status"] == "SUBMITTED"
