"""Candidate registration: declared fields and system defaults on creation,
read-back of stored fields, unknown-id 404s, system-field rejection, and the
email uniqueness rule."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_candidate,
    create_candidate,
    create_candidate_payload,
    set_logical_clock,
    validate_error,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"


class TestCandidateRegistration:
    def test_candidate_create_returns_declared_fields_and_defaults(self, api, program_admin_headers):
        """PRD §3.1: "A freshly registered candidate has `charter_awarded` false,
        `conduct_revoked` false, no suspension, `highest_level_passed_code` equal
        to `null`, and an empty append-only `conduct_statements` collection."
        PRD §3.7: "The candidate's derived `conduct_standing` reads `REVOKED`
        whenever `conduct_revoked` is set, else `SUSPENDED` while
        `suspended_until` lies in the future relative to the logical clock, else
        `GOOD_STANDING`."

        Design: Corner/entities/c_candidate_create_returns_declared_fields_and_defaults
        """
        set_logical_clock(CLOCK)
        payload = create_candidate_payload()
        resp = api.create_candidate(payload, program_admin_headers)
        data = validate_success(resp, 201)
        assert_candidate(data)
        assert resp.json()["response_type"] == "object"
        meta = resp.json()["meta"]
        assert meta.get("api_request_id") and meta.get("api_request_timestamp")
        assert data["email"] == payload["email"]
        assert data["gov_id_number"] == payload["gov_id_number"]
        assert data["version"] == 1
        assert data["charter_awarded"] is False
        assert data["highest_level_passed_code"] is None
        assert data["conduct_standing"] == "GOOD_STANDING"

    def test_candidate_get_round_trips_stored_fields(self, api, experience_reviewer_headers):
        """PRD §3.1: "Reading a candidate record exposes their conduct standing,
        progression marker and charter flag to every role."

        Design: Corner/entities/c_candidate_get_round_trips_stored_fields
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        resp = api.get_candidate(candidate["id"], experience_reviewer_headers)
        data = validate_success(resp, 200)
        assert_candidate(data)
        assert data["full_name"] == "A Candidate"
        assert data["date_of_birth"] == "1995-04-12"
        assert data["suspended_until"] is None
        assert data["conduct_revoked"] is False

    def test_candidate_get_unknown_id_returns_not_found(self, api, program_admin_headers):
        """PRD §2.6: "Each identifier embedded in the URL path is resolved in
        left-to-right order, and the first one that does not exist fails the
        request with its own entity-specific error: `ERR_CANDIDATE_NOT_FOUND`,
        `ERR_ENROLLMENT_NOT_FOUND`, `ERR_EXAM_LEVEL_NOT_FOUND`,
        `ERR_EXAM_WINDOW_NOT_FOUND`, `ERR_TEST_CENTER_NOT_FOUND`,
        `ERR_APPOINTMENT_NOT_FOUND`, `ERR_ATTEMPT_NOT_FOUND`,
        `ERR_SUBMISSION_NOT_FOUND`, `ERR_REFERENCE_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_SOCIETY_NOT_FOUND` or
        `ERR_MEMBERSHIP_NOT_FOUND`."

        Design: Corner/entities/c_candidate_get_unknown_id_returns_not_found
        """
        set_logical_clock(CLOCK)
        resp = api.get_candidate(NON_EXISTENT_UUID, program_admin_headers)
        error = validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_FOUND)
        assert resp.status_code == 404
        assert resp.json()["response_type"] == "error"
        assert error.get("message")

    def test_candidate_create_with_system_fields_rejected(self, api, program_admin_headers):
        """PRD §2.6: "Required fields must be present, types must be correct,
        enum values must belong to their declared sets, numeric ranges must
        hold, payload fields unknown to the endpoint are rejected outright,
        pathway-conditional fields must accompany their pathway, a reschedule
        must carry at least one change field, and an adjudication with a
        sanctioning outcome must name a sanction type."

        Design: Corner/entities/c_candidate_create_with_system_fields_rejected
        """
        set_logical_clock(CLOCK)
        payload = create_candidate_payload(
            id="11111111-1111-4111-8111-111111111111",
            version=1,
            email="rigged@example.com",
            full_name="Rigged Candidate",
            date_of_birth="1990-01-01",
            gov_id_number="GOV-R-9",
        )
        resp = api.create_candidate(payload, program_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_duplicate_candidate_email_rejected(self, api, program_admin_headers):
        """PRD §3.1: "Email addresses are unique across the program; a duplicate
        registration is rejected with `ERR_DUPLICATE_CANDIDATE_EMAIL`."

        Design: Corner/errors/c_duplicate_candidate_email_rejected
        """
        set_logical_clock(CLOCK)
        create_candidate()
        resp = api.create_candidate(
            create_candidate_payload(
                email="a.cand@example.com",
                full_name="Duplicate A",
                date_of_birth="1991-01-01",
                gov_id_number="GOV-D-9",
            ),
            program_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CANDIDATE_EMAIL)
        assert resp.status_code == 409
