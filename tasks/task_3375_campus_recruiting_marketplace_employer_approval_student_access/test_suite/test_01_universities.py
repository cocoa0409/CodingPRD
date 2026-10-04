"""University onboarding, lifecycle terminal lockdown, and mutation semantics."""
from test_helpers import (
    ApiErrorId,
    assert_university,
    create_student,
    create_university,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PA


class TestUniversityCreation:
    def test_create_applies_defaults_and_onboarding_state(self, api, platform_admin_headers):
        """PRD §3.1: "The cap is a non-negative integer defaulting to 10 when omitted; it
        bounds how many outreach messages any single employer may send to students of
        this university per logical day (§3.8). A freshly onboarded university lands in
        `ONBOARDING`."
        PRD §2.4: "`version` (integer): starts at 1 at creation and increments by 1 on
        every mutation of the resource"
        PRD §3.1: "Two counters live on the university as computed readouts of these
        workflows: `enrolled_student_count`, the number of its students currently in
        `ENROLLED` status, and `approved_employer_count`, the number of its employer
        approvals currently in `APPROVED` status (§3.3 maintains the latter)."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/entities/university_create_applies_defaults_and_onboarding_state
        """
        set_clock()
        response = api.create_university(
            {"name": "State University", "primary_domain": "stateu.edu"},
            platform_admin_headers,
        )
        university = validate_success(response, 201)
        assert_university(university)
        assert university["status"] == "ONBOARDING"
        assert university["version"] == 1
        assert university["employer_daily_message_cap"] == 10, (
            f"omitted cap must default to 10, got {university['employer_daily_message_cap']}"
        )
        assert university["enrolled_student_count"] == 0
        assert university["approved_employer_count"] == 0
        body = response.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestUniversityLifecycle:
    def test_offboarded_is_terminal(self, api):
        """PRD §3.1: "and either `ACTIVE` or `SUSPENDED` can be offboarded to
        `OFFBOARDED`, which is terminal."
        PRD §3.1: "a request naming any other source-target pair — including anything
        out of `OFFBOARDED` — is rejected with `ERR_INVALID_UNIVERSITY_TRANSITION`
        (HTTP 409)."

        Design: Corner/state_machines/university_offboarded_is_terminal
        """
        set_clock()
        university = create_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        activated = get_success_data(
            api.transition_university(university["id"], {"to": "ACTIVE"}, PA)
        )
        assert activated["status"] == "ACTIVE"
        offboarded = validate_success(
            api.transition_university(university["id"], {"to": "OFFBOARDED"}, PA), 200
        )
        assert offboarded["status"] == "OFFBOARDED"
        response = api.transition_university(university["id"], {"to": "ACTIVE"}, PA)
        validate_error(response, ApiErrorId.ERR_INVALID_UNIVERSITY_TRANSITION, 409)
        assert response.json()["data"]["error_id"] != "ERR_UNIVERSITY_NOT_ACTIVE"
        # The stored status never moved: the failed response leaves OFFBOARDED in place.
        assert offboarded["status"] == "OFFBOARDED"

    def test_mutation_response_reflects_new_state_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."
        PRD §3.1: "and the university must be in `ONBOARDING` or `ACTIVE`; provisioning
        into any other status fails with `ERR_UNIVERSITY_NOT_PROVISIONABLE` (HTTP 409)."

        Design: Corner/consistency_model/mutation_responses_reflect_new_state_immediately
        """
        set_clock()
        university = create_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        assert university["version"] == 1
        activated = validate_success(
            api.transition_university(university["id"], {"to": "ACTIVE"}, PA), 200
        )
        # The transition response itself carries the new state — no follow-up read.
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2
        # A dependent write against the new state succeeds immediately.
        student = create_student(
            university["id"], email="sam@stateu.edu", full_name="Sam Lee",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        assert student["university_id"] == university["id"]
        assert student["status"] == "ENROLLED"
