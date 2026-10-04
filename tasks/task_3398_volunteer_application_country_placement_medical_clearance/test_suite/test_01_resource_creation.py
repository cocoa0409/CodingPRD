"""Resource creation, response envelope, and field-shape validation tests."""

from datetime import datetime

from test_helpers import (
    BOGUS_UUID,
    DEFAULT_CLOCK_START,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_applicant,
    assert_assignment_opening,
    begin_review,
    create_applicant_payload,
    create_application,
    create_applicant,
    create_assignment_opening,
    create_country_program,
    create_country_program_payload,
    is_valid_uuid,
    make_applicant_headers,
    schedule_interview,
    set_clock,
    submit_application,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLACER = TEST_USERS["placement_officer_headers"]


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class TestResourceCreation:
    def test_create_applicant_persists_fields_and_defaults(self):
        """PRD §3.1: "The skills list may be empty, and an optional
        `languages` list captures free-form languages spoken, defaulting to
        empty."
        PRD §2.4: "The system does not consult the wall clock. All deadline
        reasoning runs on a logical clock that, at server startup and before
        any administrative intervention, reads exactly 2026-09-01T00:00:00Z."
        PRD §2.5: "Every persisted resource carries a system-minted `id`
        formatted as a bare UUID with no type prefix, and a `created_at`
        timestamp in ISO 8601 UTC with three fractional digits."

        Design: Corner/entities/create_applicant_persists_fields_and_defaults
        """
        set_clock(DEFAULT_CLOCK_START)
        resp = api_client.create_applicant(
            create_applicant_payload(
                full_name="Ana Ruiz",
                date_of_birth="1995-05-20T00:00:00Z",
                citizenship_country="US",
                skills=["TEACHING_ENGLISH", "MATH_SCIENCE"],
            ),
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert_applicant(data)
        assert is_valid_uuid(data["id"])
        assert data["full_name"] == "Ana Ruiz"
        assert data["skills"] == ["TEACHING_ENGLISH", "MATH_SCIENCE"]
        assert data["languages"] == [], "omitted languages must default to []"
        assert _ts(data["created_at"]) == _ts(DEFAULT_CLOCK_START), \
            "created_at must come from the logical clock, not the wall clock"

    def test_applicant_create_ignores_client_supplied_system_fields(self):
        """PRD §2.5: "Every persisted resource carries a system-minted `id`
        formatted as a bare UUID with no type prefix, and a `created_at`
        timestamp in ISO 8601 UTC with three fractional digits."

        Design: Corner/entities/applicant_create_system_fields_input_ignored
        """
        set_clock(DEFAULT_CLOCK_START)
        client_id = "11111111-1111-4111-8111-111111111111"
        resp = api_client.create_applicant(
            create_applicant_payload(id=client_id, version=99),
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert data["id"] != client_id, \
            "the id is system-minted; a client-supplied id must not be used"
        assert is_valid_uuid(data["id"])

    def test_create_opening_initializes_computed_counters(self):
        """PRD §3.1: "The opening starts `OPEN` with both seat counters at
        zero, and the openings list can be filtered by `country_program_id`,
        `status`, or `sector`."
        PRD §3.1: "optional `preferred_skills` that never gate eligibility and
        default to empty, a `seats_total` of at least 1, the planned
        `departure_date`, and the `invitation_issue_deadline` after which no
        invitations may be issued."

        Design: Corner/entities/create_opening_initializes_computed_counters
        """
        set_clock(DEFAULT_CLOCK_START)
        program = create_country_program()
        resp = api_client.create_assignment_opening(
            {
                "country_program_id": program["id"],
                "sector": "EDUCATION",
                "title": "Secondary English Teacher",
                "required_skills": ["TEACHING_ENGLISH"],
                "seats_total": 3,
                "departure_date": "2027-01-15T00:00:00Z",
                "invitation_issue_deadline": "2026-12-01T00:00:00Z",
            },
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert_assignment_opening(data)
        assert data["status"] == "OPEN"
        assert data["seats_provisional"] == 0
        assert data["seats_committed"] == 0
        assert data["preferred_skills"] == [], \
            "omitted preferred_skills must default to []"

    def test_create_application_rejects_unknown_references(self):
        """PRD §2.9: "Existence checks resolve identifiers left to right:
        path-template identifiers first, in the order they appear in the URL,
        then foreign keys supplied in the request body. Each missing resource
        has its own error: `ERR_APPLICANT_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`
        (also raised for an unknown program id inside
        `country_preference_ids`), `ERR_OPENING_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_INTERVIEW_NOT_FOUND`,
        `ERR_INVITATION_NOT_FOUND`, `ERR_MEDICAL_CLEARANCE_NOT_FOUND`,
        `ERR_LEGAL_CLEARANCE_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`,
        `ERR_ENROLLMENT_NOT_FOUND`, `ERR_SERVICE_NOT_FOUND`, and
        `ERR_PLACEMENT_NOT_FOUND`."
        PRD §2.1: "Creating an application likewise requires `X-User-ID` to
        equal the payload's `applicant_id`."

        Design: Corner/entities/create_application_rejects_unknown_references
        """
        set_clock(DEFAULT_CLOCK_START)
        ana = create_applicant()
        # Bogus applicant_id (ownership satisfied by matching X-User-ID).
        resp1 = api_client.create_application(
            {"applicant_id": BOGUS_UUID, "sector_preferences": ["EDUCATION"]},
            make_applicant_headers(BOGUS_UUID),
        )
        validate_error(resp1, ApiErrorId.ERR_APPLICANT_NOT_FOUND)
        # Bogus entry inside country_preference_ids.
        resp2 = api_client.create_application(
            {"applicant_id": ana["id"], "sector_preferences": ["EDUCATION"],
             "country_preference_ids": [BOGUS_UUID]},
            make_applicant_headers(ana["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_PROGRAM_NOT_FOUND)
        # Bogus country_program_id on opening creation.
        resp3 = api_client.create_assignment_opening(
            {
                "country_program_id": BOGUS_UUID,
                "sector": "EDUCATION",
                "title": "X",
                "required_skills": [],
                "seats_total": 1,
                "departure_date": "2027-01-15T00:00:00Z",
                "invitation_issue_deadline": "2026-12-01T00:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp3, ApiErrorId.ERR_PROGRAM_NOT_FOUND)


class TestEnvelopeAndAuth:
    def test_response_envelope_object_and_error_shape(self):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/response_envelope_object_and_error_shape
        """
        set_clock(DEFAULT_CLOCK_START)
        resp = api_client.create_country_program(
            create_country_program_payload(), ADMIN)
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        program = validate_success(resp, 201)

        err_resp = api_client.get_country_program(BOGUS_UUID, ADMIN)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_PROGRAM_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip()
        validate_error(err_resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND, 404)
        assert program["id"] != BOGUS_UUID

    def test_missing_authentication_headers_unauthenticated(self):
        """PRD §2.1: "A request with either header missing or malformed, or
        whose role is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_authentication_headers_unauthenticated
        """
        resp = api_client.create_country_program(
            create_country_program_payload(), {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_field_shape_validation_errors(self):
        """PRD §2.9: "Field-shape validation runs last and covers missing
        required fields, unknown enum members, out-of-range numbers, and a
        window whose end is not strictly after its start, all reported as
        `ERR_VALIDATION` (HTTP 400)."
        PRD §3.3: "the officer records four dimension scores,
        `motivation_score`, `adaptability_score`, `skill_competency_score`,
        and `cross_cultural_score`, each between 1.0 and 5.0 or the request
        fails with `ERR_VALIDATION`."

        Design: Corner/validations/field_shape_validation_errors
        """
        set_clock(DEFAULT_CLOCK_START)
        program = create_country_program()
        ana = create_applicant()
        app = create_application(ana["id"])
        submit_application(app["id"], ana["id"])
        begin_review(app["id"])
        interview = schedule_interview(app["id"])

        # 1. Missing required field (name) on program creation.
        bad_program = create_country_program_payload()
        bad_program.pop("name")
        validate_error(
            api_client.create_country_program(bad_program, ADMIN),
            ApiErrorId.ERR_VALIDATION, 400)
        # 2. Unknown sector enum member on opening creation.
        validate_error(
            api_client.create_assignment_opening(
                {
                    "country_program_id": program["id"],
                    "sector": "COOKING",
                    "title": "Bad sector",
                    "required_skills": [],
                    "seats_total": 1,
                    "departure_date": "2027-01-15T00:00:00Z",
                    "invitation_issue_deadline": "2026-12-01T00:00:00Z",
                },
                ADMIN),
            ApiErrorId.ERR_VALIDATION, 400)
        # 3. seats_total below 1.
        validate_error(
            api_client.create_assignment_opening(
                {
                    "country_program_id": program["id"],
                    "sector": "EDUCATION",
                    "title": "Zero seats",
                    "required_skills": [],
                    "seats_total": 0,
                    "departure_date": "2027-01-15T00:00:00Z",
                    "invitation_issue_deadline": "2026-12-01T00:00:00Z",
                },
                ADMIN),
            ApiErrorId.ERR_VALIDATION, 400)
        # 4. Cohort end not strictly after start.
        validate_error(
            api_client.create_training_cohort(
                {
                    "country_program_id": program["id"],
                    "name": "Inverted",
                    "start_date": "2027-03-31T00:00:00Z",
                    "end_date": "2027-01-01T00:00:00Z",
                    "capacity": 5,
                },
                ADMIN),
            ApiErrorId.ERR_VALIDATION, 400)
        # 5. Interview score outside [1.0, 5.0]; interview stays SCHEDULED.
        validate_error(
            api_client.complete_interview(
                interview["id"],
                {"motivation_score": 6.0, "adaptability_score": 3.0,
                 "skill_competency_score": 3.0, "cross_cultural_score": 3.0},
                PLACER),
            ApiErrorId.ERR_VALIDATION, 400)
        interviews = validate_success(
            api_client.list_interviews(app["id"], PLACER), 200)
        assert interviews[0]["status"] == "SCHEDULED"


class TestProgramStatusGate:
    def test_program_suspended_blocks_opening_creation(self):
        """PRD §3.1: "Suspension blocks the creation of new assignment
        openings while leaving every existing opening and invitation
        untouched; closure ends the program outright."
        PRD §3.1: "Against an `OPEN` program — and only an `OPEN` one, or the
        attempt fails with `ERR_OPENING_NOT_OPEN` — a `SystemAdmin` publishes
        an assignment opening: the hosting `country_program_id`, a `sector`
        from `EDUCATION`, `HEALTH`, `AGRICULTURE`, `ENVIRONMENT`, `YOUTH`, or
        `COMMUNITY_DEVELOPMENT`, a `title`, the `required_skills` an invitee
        must fully hold (itself possibly empty), optional `preferred_skills`
        that never gate eligibility and default to empty, a `seats_total` of
        at least 1, the planned `departure_date`, and the
        `invitation_issue_deadline` after which no invitations may be
        issued."

        Design: Corner/validations/program_suspended_blocks_opening_creation
        """
        set_clock(DEFAULT_CLOCK_START)
        program = create_country_program()
        validate_success(
            api_client.update_country_program(
                program["id"], {"status": "SUSPENDED"}, ADMIN), 200)
        validate_error(
            api_client.create_assignment_opening(
                {
                    "country_program_id": program["id"],
                    "sector": "EDUCATION",
                    "title": "X",
                    "required_skills": [],
                    "seats_total": 1,
                    "departure_date": "2027-01-15T00:00:00Z",
                    "invitation_issue_deadline": "2026-12-01T00:00:00Z",
                },
                ADMIN),
            ApiErrorId.ERR_OPENING_NOT_OPEN, 409)
        validate_success(
            api_client.update_country_program(
                program["id"], {"status": "OPEN"}, ADMIN), 200)
        opening = create_assignment_opening(program["id"])
        assert opening["status"] == "OPEN"
