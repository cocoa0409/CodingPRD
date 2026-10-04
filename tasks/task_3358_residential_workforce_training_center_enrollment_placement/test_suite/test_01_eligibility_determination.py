"""Eligibility determination: thresholds, review cycle, segregation, intake RBAC."""
from test_helpers import (
    ADVISOR,
    ApiErrorId,
    COUNSELOR,
    REVIEWER,
    api_client,
    create_applicant,
    create_application_payload,
    get_applicant,
    make_eligible_applicant,
    make_reviewer_headers,
    open_application,
    transition_application,
    validate_error,
    validate_success,
)


class TestIncomeBoundary:
    def test_income_exactly_at_limit_is_eligible(self):
        """PRD section 3.1: "INCOME_EXCEEDS_LIMIT when annual_income_cents is
        strictly greater than the computed limit (income exactly equal to the
        limit passes)".

        Design: Difficulty/boundary_precision_check/income_exactly_at_limit_is_eligible
        """
        applicant = create_applicant(full_name="Edge A", date_of_birth="2002-09-01")
        case = open_application(applicant, household_size=1,
                                annual_income_cents=1500000)
        transition_application(case["id"], "begin_review")
        determined = transition_application(case["id"], "determine")
        assert determined["status"] == "ELIGIBLE", (
            f"income == limit must pass, got {determined['status']}"
        )
        assert determined["determination_reasons"] == []

    def test_income_one_cent_over_limit_is_ineligible(self):
        """PRD section 3.1: "INCOME_EXCEEDS_LIMIT when annual_income_cents is
        strictly greater than the computed limit (income exactly equal to the
        limit passes)".

        Design: Difficulty/boundary_precision_check/income_exactly_at_limit_is_eligible
        """
        applicant = create_applicant(full_name="Edge B", date_of_birth="2002-09-01")
        case = open_application(applicant, household_size=1,
                                annual_income_cents=1500001)
        transition_application(case["id"], "begin_review")
        determined = transition_application(case["id"], "determine")
        assert determined["status"] == "INELIGIBLE"
        assert determined["determination_reasons"] == ["INCOME_EXCEEDS_LIMIT"]


class TestReviewAppealCycle:
    def test_info_request_cycle_and_first_determination(self):
        """PRD section 3.1: "The request-info/provide-info cycle may repeat
        without bound."

        Design: Difficulty/non_linear_state_machine/application_review_appeal_cycle
        """
        applicant = create_applicant(full_name="Cycle Stu")
        case = open_application(applicant, household_size=1,
                                annual_income_cents=1500001)
        transition_application(case["id"], "begin_review")
        info = transition_application(case["id"], "request_info",
                                      info_request_note="verify income docs")
        assert info["status"] == "INFO_REQUESTED"
        back = transition_application(case["id"], "provide_info",
                                      reviewer_id="counselor-1", role="counselor")
        assert back["status"] == "UNDER_REVIEW"
        determined = transition_application(case["id"], "determine")
        assert determined["status"] == "INELIGIBLE"
        assert determined["determination_reasons"] == ["INCOME_EXCEEDS_LIMIT"]

    def test_appeal_reopens_case_and_redetermines_on_new_snapshot(self):
        """PRD section 3.1: "An INELIGIBLE case is likewise reopened by the
        counselor's appeal action, which returns it to UNDER_REVIEW with the
        same overwrite semantics for the three snapshot fields, after which
        determination runs again on the updated snapshot."

        Design: Difficulty/non_linear_state_machine/application_review_appeal_cycle
        """
        applicant = create_applicant(full_name="Cycle Stu")
        case = open_application(applicant, household_size=1,
                                annual_income_cents=1500001)
        transition_application(case["id"], "begin_review")
        transition_application(case["id"], "determine")
        appealed = transition_application(case["id"], "appeal",
                                          reviewer_id="counselor-1",
                                          role="counselor",
                                          annual_income_cents=1200000)
        assert appealed["status"] == "UNDER_REVIEW"
        redetermined = transition_application(case["id"], "determine")
        assert redetermined["status"] == "ELIGIBLE"
        assert redetermined["determination_reasons"] == []


class TestAgeBoundary:
    def test_dob_exactly_24_passes(self):
        """PRD section 3.1: "AGE_OUT_OF_RANGE when the applicant is younger than
        16 or older than 24 (both bounds inclusive, so exactly 16 and exactly 24
        pass)".

        Design: Corner/calculations/age_boundary_pair_24_ok_25_fails
        """
        applicant = create_applicant(full_name="Age24",
                                     date_of_birth="2002-09-01")
        case = open_application(applicant)
        transition_application(case["id"], "begin_review")
        determined = transition_application(case["id"], "determine")
        assert determined["status"] == "ELIGIBLE"
        assert determined["determination_reasons"] == []

    def test_dob_exactly_25_fails_with_age_reason(self):
        """PRD section 3.1: "AGE_OUT_OF_RANGE when the applicant is younger than
        16 or older than 24 (both bounds inclusive, so exactly 16 and exactly 24
        pass)".

        Design: Corner/calculations/age_boundary_pair_24_ok_25_fails
        """
        applicant = create_applicant(full_name="Age25",
                                     date_of_birth="2001-09-01")
        case = open_application(applicant)
        transition_application(case["id"], "begin_review")
        determined = transition_application(case["id"], "determine")
        assert determined["status"] == "INELIGIBLE"
        assert determined["determination_reasons"] == ["AGE_OUT_OF_RANGE"]


class TestIncomeScaling:
    def test_household_size_3_lifts_limit_to_2500000(self):
        """PRD section 3.1: "The income limit in cents is a 1500000-cent base
        plus 500000 cents for each household member beyond the first."

        Design: Corner/calculations/income_limit_scales_with_household_size
        """
        applicant = create_applicant(full_name="HH3")
        case = open_application(applicant, household_size=3,
                                annual_income_cents=2000000,
                                barrier_flags=["SINGLE_PARENT"])
        transition_application(case["id"], "begin_review")
        determined = transition_application(case["id"], "determine")
        assert determined["status"] == "ELIGIBLE"
        assert determined["determination_reasons"] == []


class TestInvalidTransitions:
    def test_determine_before_review_rejected(self):
        """PRD section 2.7: "If the target is not terminal but the requested
        action is undefined from its current state, the request fails with
        ERR_INVALID_STATE".

        Design: Corner/state_machines/determine_before_review_rejected
        """
        applicant = create_applicant(full_name="Skip Stu")
        case = open_application(applicant)
        resp = api_client.transition_application(
            case["id"], {"action": "determine"}, REVIEWER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows = validate_success(api_client.list_applications(applicant["id"], REVIEWER))
        assert rows[0]["status"] == "SUBMITTED"

    def test_appeal_on_terminal_eligible_rejected(self):
        """PRD section 3.1: "ELIGIBLE is terminal — a further case action on it
        fails with ERR_ALREADY_TERMINAL".

        Design: Corner/state_machines/appeal_on_terminal_eligible_rejected
        """
        applicant, case = make_eligible_applicant(full_name="Term Stu")
        resp = api_client.transition_application(
            case["id"], {"action": "appeal", "annual_income_cents": 100},
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        rows = validate_success(api_client.list_applications(applicant["id"], REVIEWER))
        assert rows[0]["status"] == "ELIGIBLE"


class TestSegregationOfDuties:
    def test_intake_counselor_cannot_begin_review(self):
        """PRD section 2.1: "The review actions — beginning review, requesting
        information, and issuing a determination — are rejected with
        ERR_SEGREGATION_OF_DUTIES (HTTP 403) when the acting X-User-ID equals
        the application's stored intake_counselor_id."

        Design: Corner/validations/segregation_of_duties_blocks_self_review
        """
        applicant = create_applicant(full_name="Sod Stu")
        case = open_application(applicant, counselor_id="counselor-1")
        resp = api_client.transition_application(
            case["id"], {"action": "begin_review"},
            make_reviewer_headers("counselor-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_independent_reviewer_is_recorded(self):
        """PRD section 3.1: "Beginning review moves SUBMITTED to UNDER_REVIEW
        and stamps reviewer_id with the reviewer's opaque identifier".

        Design: Corner/validations/segregation_of_duties_blocks_self_review
        """
        applicant = create_applicant(full_name="Sod Stu")
        case = open_application(applicant, counselor_id="counselor-1")
        reviewed = transition_application(case["id"], "begin_review",
                                          reviewer_id="reviewer-1")
        assert reviewed["status"] == "UNDER_REVIEW"
        rows = validate_success(api_client.list_applications(applicant["id"], REVIEWER))
        assert len(rows) == 1
        assert rows[0]["reviewer_id"] == "reviewer-1"
        assert rows[0]["intake_counselor_id"] == "counselor-1"


class TestDuplicateCase:
    def test_second_open_application_rejected(self):
        """PRD section 3.1: "An applicant may hold only one open case at a
        time: while any case sits in SUBMITTED, UNDER_REVIEW, or
        INFO_REQUESTED, a further create fails with ERR_DUPLICATE_APPLICATION."

        Design: Corner/validations/duplicate_open_application_rejected
        """
        applicant = create_applicant(full_name="Dup Stu")
        open_application(applicant)
        fresh = get_applicant(applicant["id"])
        resp = api_client.create_application(
            create_application_payload(
                applicant["id"], fresh["version"], household_size=2,
                annual_income_cents=900000, barrier_flags=["HOMELESS"],
            ),
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)


class TestRequestShape:
    def test_missing_required_field_rejected(self):
        """PRD section 2.7: "A structurally malformed body — a missing required
        field, an undeclared field, an invalid enum member, or a field-domain
        violation such as an out-of-range household size, a bed label outside
        the center's valid label range, sanction points outside their allowed
        band, or out-of-range daily hours — produces ERR_INVALID_REQUEST."

        Design: Corner/validations/invalid_request_shape_violations
        """
        resp = api_client.create_applicant(
            {"full_name": "No Dob", "home_region_code": "R-NORTH",
             "desired_trade_code": "WELDING"},
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_unknown_transition_action_rejected(self):
        """PRD section 2.7: "A structurally malformed body — a missing required
        field, an undeclared field, an invalid enum member, or a field-domain
        violation such as an out-of-range household size, a bed label outside
        the center's valid label range, sanction points outside their allowed
        band, or out-of-range daily hours — produces ERR_INVALID_REQUEST."

        Design: Corner/validations/invalid_request_shape_violations
        """
        applicant = create_applicant(full_name="Shape Stu")
        case = open_application(applicant)
        resp = api_client.transition_application(
            case["id"], {"action": "fast_track"}, REVIEWER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestIntakeRbac:
    def test_reviewer_cannot_file_application(self):
        """PRD section 2.1: "A request whose role is authenticated but is not
        listed among the roles authorized for the target endpoint is rejected
        with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/reviewer_cannot_file_application
        """
        applicant = create_applicant(full_name="Rbac Stu")
        resp = api_client.create_application(
            create_application_payload(applicant["id"], applicant["version"]),
            make_reviewer_headers("reviewer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_applicant(applicant["id"])["version"] == applicant["version"], (
            "a forbidden write must not advance the applicant version"
        )

    def test_advisor_cannot_determine_application(self):
        """PRD section 2.1: "A request whose role is authenticated but is not
        listed among the roles authorized for the target endpoint is rejected
        with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/advisor_cannot_determine_application
        """
        applicant = create_applicant(full_name="Adv Stu")
        case = open_application(applicant)
        resp = api_client.transition_application(
            case["id"], {"action": "determine"}, ADVISOR
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        rows = validate_success(api_client.list_applications(applicant["id"], REVIEWER))
        assert rows[0]["status"] == "SUBMITTED"
