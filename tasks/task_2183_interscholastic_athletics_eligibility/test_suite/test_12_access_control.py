"""Authentication, the endpoint role lists, ownership, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_school_payload,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_registrar_cannot_run_an_eligibility_evaluation(api):
    """PRD §2.1: "If the headers are well formed but the named role is not
    authorized for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §2.1: "**`Registrar`** is the school records officer, who posts
    grading-period academic records and nothing else."
    PRD §3.4: "An `EligibilityReviewer` rules on a case by running an evaluation,
    and the ruling is the output of a five-rung ladder with strict precedence."

    Design: Corner/rbac/registrar_cannot_evaluate_an_eligibility_case
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        student_overrides={"full_name": "Ivo Marek", "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        documents=(),
    )

    response = api.evaluate_case(ctx["case"]["id"],
                                 fx.make_registrar_headers(ctx["school"]["id"]))

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    case = fx.read_case(ctx["case"]["id"])
    assert case["status"] == "INTAKE"
    assert case["evaluation_count"] == 0


def test_athletic_director_cannot_post_the_grading_period_record(api):
    """PRD §3.3: "Those four academic figures reach the athlete only through the
    `Registrar`, who posts the grading-period record for a student of their own
    school."
    PRD §2.1: "If the headers are well formed but the named role is not authorized
    for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/athletic_director_cannot_post_an_academic_record
    """
    school = fx.create_school(name="North High")
    student = fx.create_student(school["id"], full_name="Jun Park",
                                birth_date="2009-05-14", grade_level=11)

    response = api.post_academic_record(
        student["id"],
        {"gpa_prior_period": 4.000, "gpa_current_period": 4.000,
         "credits_prior_period": 3, "credits_current_period": 3},
        fx.make_director_headers(school["id"]),
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    stored = fx.read_student(student["id"])
    assert stored["academic_record_submitted_at"] is None
    assert stored["gpa_prior_period"] is None


def test_a_director_cannot_pay_another_schools_case(api):
    """PRD §2.1: "For the two entity-backed families, the ownership comparison is
    resolved per resource, and a mismatch is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "A `SchoolAthleticDirector` or `Registrar` must present the governing
    school's identifier: `home_school_id` for contest writes, `requesting_school_id`
    for transport writes, the owning `school_id` of the `Student` for student and
    eligibility writes, and the `school_id` on the credential for credential
    creation."

    Design: Corner/rbac/director_cannot_pay_the_fee_on_another_schools_case
    """
    school_a = fx.create_school(name="North High", fee_cap_cents=20000)
    school_b = fx.create_school(name="South High", region_code="R-SOUTH",
                                fee_cap_cents=20000)
    season = fx.create_season(sport_tier="TIER_A")
    student = fx.create_student(school_a["id"], full_name="Kai Duarte",
                                birth_date="2009-05-14", grade_level=10)
    case = fx.create_case(school_a["id"], student["id"], season["id"])

    response = api.create_fee_payment(
        case["id"], {"amount_cents": 12345}, fx.make_director_headers(school_b["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert fx.read_case(case["id"])["fee_paid_cents"] == 0
    assert fx.read_school(school_a["id"])["fee_collected_cents"] == 0
    assert fx.read_school(school_b["id"])["fee_collected_cents"] == 0


def test_an_official_cannot_answer_another_officials_offer(api):
    """PRD §2.1: "An `Official` must present the `official_id` recorded on the
    assignment being answered."
    PRD §3.7: "The official themselves answers, and only they may: the acting
    `X-User-ID` must equal the assignment's `official_id`."

    Design: Corner/rbac/official_cannot_respond_to_another_officials_offer
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z", season_overrides={"required_officials": 2}
    )
    offered_to = fx.create_official(full_name="Ola Nkemdi", certification_level="LEVEL_2")
    bystander = fx.create_official(full_name="Pia Sandoval",
                                   certification_level="LEVEL_1",
                                   home_region_code="R-SOUTH")
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")
    assignment = fx.offer_official(contest["id"], offered_to["id"])

    response = api.respond_to_assignment(
        assignment["id"], {"response": "ACCEPT"},
        fx.make_official_headers(bystander["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    stored = fx.read_assignment(assignment["id"])
    assert stored["status"] == "OFFERED"
    assert stored["stipend_cents"] is None
    assert fx.read_contest(contest["id"])["accepted_official_count"] == 0


def test_a_reviewer_cannot_rule_on_the_record_they_filed(api):
    """PRD §3.4: "Three conditions guard it in every case: the governing season must
    stand at `PRACTICE_OPEN` or `REGULAR_SEASON` or the answer is
    `ERR_SEASON_NOT_OPEN`; the acting reviewer's `X-User-ID` must differ from the
    athlete's `academic_record_submitted_by` or the answer is
    `ERR_SEGREGATION_OF_DUTIES`; and `academic_record_submitted_at` must not be null
    or the answer is `ERR_ACADEMIC_RECORD_MISSING`."
    PRD §2.6: "The acting `X-User-ID` differs from the principal recorded on the
    record being adjudicated — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/rbac/reviewer_cannot_evaluate_a_case_whose_academic_record_they_posted
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        student_overrides={"full_name": "Lev Antonov", "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
    )
    filer_headers = build_user_headers(ctx["school"]["id"], "EligibilityReviewer")

    blocked = api.evaluate_case(ctx["case"]["id"], filer_headers)

    validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    held = fx.read_case(ctx["case"]["id"])
    assert held["status"] == "INTAKE"
    assert held["evaluation_count"] == 0

    ruled = validate_success(api.evaluate_case(ctx["case"]["id"], fx.REVIEWER), 200)

    assert ruled["status"] == "PROVISIONAL_ELIGIBLE"
    assert ruled["evaluation_count"] == 1


def test_a_medical_officer_cannot_clear_the_report_they_filed(api, medical_headers,
                                                              medical_alt_headers):
    """PRD §3.6: "Closing a report requires a `disposition` and permits a
    `clearance_note`, and it is barred to the officer who filed it: an acting
    `X-User-ID` equal to the report's `reported_by_user_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES`, on both dispositions."

    Design: Corner/rbac/medical_officer_cannot_clear_an_injury_report_they_filed
    """
    set_clock("2026-09-10T09:00:00Z")
    school = fx.create_school(name="North High")
    student = fx.create_student(school["id"], full_name="Mira Vogel",
                                birth_date="2009-05-14", grade_level=11)
    report = fx.file_injury(student["id"], injury_type="FRACTURE")

    blocked = api.clear_injury_report(report["id"], {"disposition": "SEASON_ENDED"},
                                      medical_headers)

    validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert fx.read_injury(report["id"])["status"] == "REPORTED"

    cleared = validate_success(
        api.clear_injury_report(
            report["id"],
            {"disposition": "SEASON_ENDED", "clearance_note": "second opinion"},
            medical_alt_headers,
        ),
        200,
    )

    assert cleared["status"] == "SEASON_ENDED"
    assert cleared["reported_by_user_id"] == "med-001"
    assert cleared["cleared_by_user_id"] == "med-002"


def test_a_request_without_the_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the service carries two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the capacity in which
    that principal acts."
    PRD §2.1: "If either header is absent, or if `X-User-Role` does not name one of
    the seven roles declared below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_without_the_role_header_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00Z")

    response = api.create_school(
        create_school_payload(name="Ghost High", classification="C3A",
                              region_code="R-NORTH"),
        {"Content-Type": "application/json"},
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert response.json()["response_type"] == "error"
