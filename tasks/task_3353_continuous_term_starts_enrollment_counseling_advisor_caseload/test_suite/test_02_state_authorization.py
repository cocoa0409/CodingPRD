"""State authorization half-open windows and admission decision gates."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_program, authorize_state, create_term,
    open_term, create_applicant, create_submitted_application,
    assert_state_authorization, assert_application,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestAuthorizationWindowOverlap:
    def test_overlapping_window_rejected(self):
        """PRD §3.2: "Two rows for the same `program_id` and `state_code` may
        not have overlapping windows — an overlapping append is rejected with
        `ERR_AUTHORIZATION_WINDOW_OVERLAP` — but adjacency is explicitly
        permitted, so a new row whose `effective_from` equals an existing
        row's `effective_to` is accepted, allowing a program's status in a
        state to change over time without gaps or collisions."

        Design: Difficulty/resource_temporal_overlap/state_authorization_half_open_window_overlap
        """
        program = create_program()
        authorize_state(program["id"], state_code="CO",
                        effective_from="2026-01-01", effective_to="2026-06-01")
        resp = api_client.create_state_authorization(
            program["id"],
            {"state_code": "CO", "authorization_status": "RESTRICTED",
             "effective_from": "2026-03-01", "disclosure_text": "d"},
            TEST_USERS["compliance_headers"])
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_OVERLAP)

    def test_adjacent_window_accepted(self):
        """PRD §3.2: "Two rows for the same `program_id` and `state_code` may
        not have overlapping windows — an overlapping append is rejected with
        `ERR_AUTHORIZATION_WINDOW_OVERLAP` — but adjacency is explicitly
        permitted, so a new row whose `effective_from` equals an existing
        row's `effective_to` is accepted, allowing a program's status in a
        state to change over time without gaps or collisions."

        Design: Difficulty/resource_temporal_overlap/state_authorization_half_open_window_overlap
        """
        program = create_program()
        authorize_state(program["id"], state_code="CO",
                        effective_from="2026-01-01", effective_to="2026-06-01")
        resp = api_client.create_state_authorization(
            program["id"],
            {"state_code": "CO", "authorization_status": "RESTRICTED",
             "effective_from": "2026-06-01", "disclosure_text": "d"},
            TEST_USERS["compliance_headers"])
        data = validate_success(resp, expected_status=201)
        assert_state_authorization(data)
        assert data["effective_from"] == "2026-06-01"
        assert data["authorization_status"] == "RESTRICTED"


class TestDecisionRequiresStateAuthorization:
    def _open_term_with_program(self, program):
        term = create_term()
        open_term(term["id"])
        return term

    def test_decision_prohibited_state_rejected(self):
        """PRD §3.4: "An `ADMIT` passes through two compliance gates,
        evaluated in order: first the current state authorization for the
        program and the applicant's `state_code` must be `AUTHORIZED` or
        `RESTRICTED` — a missing row, a `PENDING` row, or a `PROHIBITED` row
        is rejected with `ERR_STATE_NOT_AUTHORIZED` — and second, when the
        current row is `RESTRICTED`, the application's
        `disclosure_acknowledged` must be true, otherwise the decision is
        rejected with `ERR_DISCLOSURE_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/application_decision_requires_state_authorization
        """
        program = create_program()
        authorize_state(program["id"], state_code="NM", status="PROHIBITED")
        term = self._open_term_with_program(program)
        applicant = create_applicant(state_code="NM", full_name="NM Prospect")
        application = create_submitted_application(
            applicant["id"], term["id"], program["id"])
        resp = api_client.decide_application(
            application["id"], {"decision": "ADMIT"}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_STATE_NOT_AUTHORIZED)
        after = get_success_data(
            api_client.get_application(application["id"], REGISTRAR))
        assert_application(after)
        assert after["status"] == "SUBMITTED", (
            f"rejected decision must not mutate the application; "
            f"got {after['status']}")

    def test_decision_restricted_without_disclosure_rejected(self):
        """PRD §3.4: "An `ADMIT` passes through two compliance gates,
        evaluated in order: first the current state authorization for the
        program and the applicant's `state_code` must be `AUTHORIZED` or
        `RESTRICTED` — a missing row, a `PENDING` row, or a `PROHIBITED` row
        is rejected with `ERR_STATE_NOT_AUTHORIZED` — and second, when the
        current row is `RESTRICTED`, the application's
        `disclosure_acknowledged` must be true, otherwise the decision is
        rejected with `ERR_DISCLOSURE_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/application_decision_requires_state_authorization
        """
        program = create_program()
        authorize_state(program["id"], state_code="UT", status="RESTRICTED",
                        disclosure_text="UT disclosure")
        term = self._open_term_with_program(program)
        applicant = create_applicant(state_code="UT", full_name="UT Prospect")
        application = create_submitted_application(
            applicant["id"], term["id"], program["id"])
        assert application["disclosure_acknowledged"] is False
        resp = api_client.decide_application(
            application["id"], {"decision": "ADMIT"}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_REQUIRED)
