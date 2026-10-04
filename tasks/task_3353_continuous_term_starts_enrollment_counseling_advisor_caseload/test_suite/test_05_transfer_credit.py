"""Transfer credit evaluation degree-path computation and lifecycle."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_program, create_term, open_term,
    create_applicant, create_submitted_application, admit_application,
    create_tce_payload, create_enrollment_payload, create_advisor,
    setup_open_term_scenario, setup_registered_enrollment, assert_tce,
    assert_enrollment,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def test_tce_computed_degree_path_fields():
    """PRD §3.5: "Completion is the moment the degree path is computed, in a
    pinned order: first the program's `total_credits_required` is read
    through the evaluation's application; then the transfer cap is computed
    as three quarters of that total, rounded down to a whole credit; then
    `capped_credits` is set to the smaller of `accepted_credits` and that
    cap; and finally `remaining_credits` is set to `total_credits_required`
    minus `capped_credits` minus `in_progress_credits`, floored at zero so it
    can never go negative."

    Design: Corner/entities/tce_computed_degree_path_fields
    """
    program = create_program(total_credits=120)
    term = create_term()
    open_term(term["id"])
    applicant = create_applicant()
    application = create_submitted_application(
        applicant["id"], term["id"], program["id"])
    resp = api_client.create_tce(
        application["id"],
        create_tce_payload(accepted_credits=100, in_progress_credits=6),
        REGISTRAR)
    tce = get_success_data(resp)
    get_success_data(api_client.advance_tce(tce["id"], "IN_REVIEW", REGISTRAR))
    resp = api_client.advance_tce(tce["id"], "COMPLETED", REGISTRAR)
    data = validate_success(resp, expected_status=200)
    assert_tce(data)
    # cap = floor(120 * 3/4) = 90; capped = min(100, 90) = 90.
    assert data["capped_credits"] == 90, (
        f"capped_credits must be min(100, floor(120*3/4)) = 90; got "
        f"{data['capped_credits']}")
    # remaining = 120 - 90 - 6 = 24.
    assert data["remaining_credits"] == 24, (
        f"remaining_credits must be 120 - 90 - 6 = 24; got "
        f"{data['remaining_credits']}")


def test_tce_draft_to_completed_skip_rejected():
    """PRD §3.5: "From `DRAFT`, an advance by a `RegistrarAdmin` naming a
    `to_state` moves the evaluation `DRAFT` → `IN_REVIEW`, and a further
    advance moves it `IN_REVIEW` → `COMPLETED`."
    PRD §2.7: "State legality. The target resource must be in a state from
    which the requested transition is defined — a decision only on a
    `SUBMITTED` application, a withdrawal only on a `REGISTERED` or `ACTIVE`
    enrollment, an advance only along a declared edge; otherwise
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/tce_draft_to_completed_skip_rejected
    """
    ctx = setup_open_term_scenario()
    applicant = create_applicant()
    application = create_submitted_application(
        applicant["id"], ctx["term"]["id"], ctx["program"]["id"])
    resp = api_client.create_tce(
        application["id"],
        create_tce_payload(accepted_credits=5, in_progress_credits=0),
        REGISTRAR)
    tce = get_success_data(resp)
    assert tce["status"] == "DRAFT"
    resp = api_client.advance_tce(tce["id"], "COMPLETED", REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTceReEvaluationCycle:
    def test_completed_reopens_to_in_review_pre_enrollment(self):
        """PRD §3.5: "A completed evaluation may be returned to `IN_REVIEW`
        for a re-evaluation cycle — but only while no enrollment derived from
        the same application exists in `REGISTERED`, `ACTIVE`, or `DEFERRED`;
        once such an enrollment exists the degree path is locked and the
        attempt is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/tce_completed_reopens_to_in_review_cycle
        """
        program = create_program(total_credits=120)
        term = create_term()
        open_term(term["id"])
        applicant = create_applicant()
        application = create_submitted_application(
            applicant["id"], term["id"], program["id"])
        resp = api_client.create_tce(
            application["id"],
            create_tce_payload(accepted_credits=100, in_progress_credits=6),
            REGISTRAR)
        tce = get_success_data(resp)
        get_success_data(api_client.advance_tce(
            tce["id"], "IN_REVIEW", REGISTRAR))
        get_success_data(api_client.advance_tce(
            tce["id"], "COMPLETED", REGISTRAR))
        # Cycle back while no enrollment exists: legal.
        resp = api_client.advance_tce(tce["id"], "IN_REVIEW", REGISTRAR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "IN_REVIEW", (
            f"COMPLETED -> IN_REVIEW must be legal pre-enrollment; got "
            f"{data['status']}")
        # And forward again; completion recomputes the degree path.
        resp = api_client.advance_tce(tce["id"], "COMPLETED", REGISTRAR)
        data = validate_success(resp, expected_status=200)
        assert data["capped_credits"] == 90
        assert data["remaining_credits"] == 24

    def test_completed_reopen_rejected_once_enrolled(self):
        """PRD §3.5: "A completed evaluation may be returned to `IN_REVIEW`
        for a re-evaluation cycle — but only while no enrollment derived from
        the same application exists in `REGISTERED`, `ACTIVE`, or `DEFERRED`;
        once such an enrollment exists the degree path is locked and the
        attempt is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/tce_completed_reopens_to_in_review_cycle
        """
        ctx = setup_registered_enrollment(
            accepted_credits=100, in_progress_credits=6)
        assert ctx["enrollment"]["status"] == "REGISTERED"
        resp = api_client.advance_tce(ctx["tce"]["id"], "IN_REVIEW", REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEnrollmentRequiresCompletedTce:
    def _setup_admitted_with_tce_in_review(self):
        ctx = setup_open_term_scenario()
        advisor = create_advisor()
        applicant = create_applicant()
        application = create_submitted_application(
            applicant["id"], ctx["term"]["id"], ctx["program"]["id"])
        application = admit_application(application["id"])
        resp = api_client.create_tce(
            application["id"],
            create_tce_payload(accepted_credits=10, in_progress_credits=0),
            REGISTRAR)
        tce = get_success_data(resp)
        get_success_data(api_client.advance_tce(
            tce["id"], "IN_REVIEW", REGISTRAR))
        ctx.update({"advisor": advisor, "applicant": applicant,
                    "application": application, "tce": tce})
        return ctx

    def test_enroll_with_in_review_tce_rejected(self):
        """PRD §3.6: "The most recent non-`VOID` transfer credit evaluation
        for the application must be `COMPLETED` — the degree path must be
        finalized before enrollment — otherwise `ERR_EVALUATION_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_completed_tce
        """
        ctx = self._setup_admitted_with_tce_in_review()
        resp = api_client.create_enrollment(
            create_enrollment_payload(
                ctx["application"]["id"], ctx["advisor"]["id"],
                ctx["application"]["version"]),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_EVALUATION_INCOMPLETE)

    def test_enroll_after_tce_completed_succeeds(self):
        """PRD §3.6: "The most recent non-`VOID` transfer credit evaluation
        for the application must be `COMPLETED` — the degree path must be
        finalized before enrollment — otherwise `ERR_EVALUATION_INCOMPLETE`."
        PRD §3.6: "The application moves `ADMITTED` → `CONVERTED` (terminal)
        and its `version` increments; the applicant moves `ADMITTED` →
        `ENROLLED` and its `version` increments; and the new **Enrollment**
        is created in `REGISTERED` status".

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_completed_tce
        """
        ctx = self._setup_admitted_with_tce_in_review()
        get_success_data(api_client.advance_tce(
            ctx["tce"]["id"], "COMPLETED", REGISTRAR))
        resp = api_client.create_enrollment(
            create_enrollment_payload(
                ctx["application"]["id"], ctx["advisor"]["id"],
                ctx["application"]["version"]),
            REGISTRAR)
        data = validate_success(resp, expected_status=201)
        assert_enrollment(data)
        assert data["status"] == "REGISTERED"
        application = get_success_data(
            api_client.get_application(ctx["application"]["id"], REGISTRAR))
        assert application["status"] == "CONVERTED", (
            f"successful conversion must move the application to CONVERTED; "
            f"got {application['status']}")
