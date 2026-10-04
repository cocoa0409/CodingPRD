"""Application listing, duplicate gate, term-open gate, and decision state."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, TEST_USERS, create_program, create_term,
    open_term, create_applicant, create_submitted_application,
    make_applicant_headers, assert_application,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def test_applications_list_pagination_envelope():
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; when omitted it defaults to 10, and it is bounded below by 1
    and above by 100. The `offset` parameter sets the number of items skipped
    and defaults to 0. Unless otherwise specified, every list endpoint
    returns resources sorted by `created_at` in ascending order. List
    responses carry `limit`, `offset`, `total_count`, and `has_more` in the
    `meta` object of the envelope."
    PRD §3.4: "Applications can be listed with the optional filters
    `applicant_id`, `term_id`, `program_id`, and `status`, combined with the
    standard `limit` and `offset` pagination."

    Design: Corner/entities/applications_list_pagination_envelope
    """
    program = create_program()
    term = create_term()
    open_term(term["id"])
    for i in range(3):
        applicant = create_applicant(full_name=f"P{i+1}")
        create_submitted_application(
            applicant["id"], term["id"], program["id"])
    resp = api_client.list_applications(
        REGISTRAR, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"limit=2 must return 2 items; got {len(data)}"
    assert meta["total_count"] == 3, (
        f"3 applications exist; total_count must be 3, got "
        f"{meta['total_count']}")
    assert meta["has_more"] is True
    assert meta["limit"] == 2 and meta["offset"] == 0


def test_duplicate_active_application_rejected():
    """PRD §3.4: "First, a duplicate check: if any application already exists
    for the same `applicant_id` and `term_id` in `SUBMITTED` or `ADMITTED`
    status, the create is rejected with `ERR_DUPLICATE_APPLICATION`
    (HTTP 409)."

    Design: Corner/validations/duplicate_active_application_rejected
    """
    program = create_program()
    term = create_term()
    open_term(term["id"])
    applicant = create_applicant()
    first = create_submitted_application(
        applicant["id"], term["id"], program["id"])
    resp = api_client.create_application(
        {"applicant_id": applicant["id"], "term_id": term["id"],
         "program_id": program["id"]},
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)
    # After withdrawing the first, the identical create succeeds (the
    # WITHDRAWN application is no longer SUBMITTED or ADMITTED).
    resp = api_client.withdraw_application(
        first["id"], make_applicant_headers(applicant["id"]))
    validate_success(resp, expected_status=200)
    resp = api_client.create_application(
        {"applicant_id": applicant["id"], "term_id": term["id"],
         "program_id": program["id"]},
        make_applicant_headers(applicant["id"]))
    data = validate_success(resp, expected_status=201)
    assert_application(data)
    assert data["status"] == "SUBMITTED"


def test_application_create_before_term_open_rejected():
    """PRD §3.4: "Second, a temporal gate: the targeted term must be in
    `ENROLLMENT_OPEN`, otherwise the create is rejected with
    `ERR_TERM_NOT_OPEN`."

    Design: Corner/validations/application_create_before_term_open_rejected
    """
    program = create_program()
    term = create_term()  # stays SCHEDULED
    applicant = create_applicant()
    resp = api_client.create_application(
        {"applicant_id": applicant["id"], "term_id": term["id"],
         "program_id": program["id"]},
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_OPEN)


def test_withdraw_terminal_denied_application_invalid_state():
    """PRD §3.4: "Either the applicant owner or the assigned counselor may
    withdraw an application that is still `SUBMITTED` or `ADMITTED`".
    PRD §2.7: "State legality. The target resource must be in a state from
    which the requested transition is defined — a decision only on a
    `SUBMITTED` application, a withdrawal only on a `REGISTERED` or `ACTIVE`
    enrollment, an advance only along a declared edge; otherwise
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/withdraw_terminal_denied_application_invalid_state
    """
    program = create_program()
    term = create_term()
    open_term(term["id"])
    applicant = create_applicant()
    application = create_submitted_application(
        applicant["id"], term["id"], program["id"])
    resp = api_client.decide_application(
        application["id"], {"decision": "DENY"}, REGISTRAR)
    denied = validate_success(resp, expected_status=200)
    assert denied["status"] == "DENIED"
    resp = api_client.withdraw_application(
        application["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(
        api_client.get_application(application["id"], REGISTRAR))
    assert after["status"] == "DENIED", (
        f"DENIED is terminal; withdraw must leave it untouched, got "
        f"{after['status']}")


class TestStateErrorBeatsSafetyErrorOnDecision:
    """A WITHDRAWN application whose program+state has no authorization row:
    the state-legality check outranks the business-safety check."""

    def _setup_withdrawn_wy_application(self):
        program = create_program()  # no authorization row for WY at all
        term = create_term()
        open_term(term["id"])
        applicant = create_applicant(state_code="WY", full_name="Wy Prospect")
        application = create_submitted_application(
            applicant["id"], term["id"], program["id"])
        resp = api_client.withdraw_application(
            application["id"], make_applicant_headers(applicant["id"]))
        validate_success(resp, expected_status=200)
        return application

    def test_decision_on_withdrawn_returns_invalid_state_not_safety(self):
        """PRD §2.7: "When a request violates several rules at once, the error
        it receives is determined by a fixed priority order; the first
        matching check wins and later checks are never evaluated."
        PRD §2.7: "State legality. The target resource must be in a state
        from which the requested transition is defined — a decision only on a
        `SUBMITTED` application, a withdrawal only on a `REGISTERED` or
        `ACTIVE` enrollment, an advance only along a declared edge; otherwise
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_decision
        """
        application = self._setup_withdrawn_wy_application()
        resp = api_client.decide_application(
            application["id"], {"decision": "ADMIT"}, REGISTRAR)
        # Both state (WITHDRAWN) and safety (no WY authorization) fail; the
        # state error must win.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_decision_on_withdrawn_leaves_status_untouched(self):
        """PRD §2.7: "When a request violates several rules at once, the error
        it receives is determined by a fixed priority order; the first
        matching check wins and later checks are never evaluated."
        PRD §3.4: "Decisions are defined only on `SUBMITTED` applications;
        any other status is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_decision
        """
        application = self._setup_withdrawn_wy_application()
        resp = api_client.decide_application(
            application["id"], {"decision": "ADMIT"}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(
            api_client.get_application(application["id"], REGISTRAR))
        assert after["status"] == "WITHDRAWN", (
            f"rejected decision must leave the application WITHDRAWN; got "
            f"{after['status']}")
