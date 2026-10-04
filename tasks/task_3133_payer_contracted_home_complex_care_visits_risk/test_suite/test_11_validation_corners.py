"""Corner-queue tests: validation ladder and error discipline."""
import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    CONTRACT_ADMIN,
    COORDINATOR,
    NON_EXISTENT_UUID,
    SPECIALIST,
    activate_care_team_for,
    activate_enrollment,
    advance_clock,
    api_client,
    build_user_headers,
    create_capitated_contract_payload,
    create_care_program_payload,
    create_clinician,
    create_member,
    create_member_payload,
    create_member_with_enrollment,
    create_pcp,
    create_program,
    create_scheduled_visit,
    create_settlement,
    create_triggered_episode,
    dispatch_episode,
    drive_enrollment_to_consented,
    drive_enrollment_to_outreach,
    finalize_settlement,
    get_success_data,
    make_clinician_headers,
    set_clock,
    setup_active_enrollment,
    setup_basic_reference,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestAuthAndExistence:
    def test_missing_user_context_header_rejected(self, api):
        """PRD section 2.1: "Every request carries two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` names the operational capacity in which they act. If either header is missing or empty, the server rejects the call with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_context_header_rejected
        """
        resp = api.list_care_programs(headers={"Content-Type": "application/json"})
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )

    def test_invalid_role_for_endpoint_rejected(self, api):
        """PRD section 2.1: "Beyond authentication, each endpoint permits a fixed set of roles; a call made under a role not on that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/validations/invalid_role_for_endpoint_rejected
        """
        resp = api.create_care_program(create_care_program_payload(), ANALYST)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_nonexistent_program_id_returns_404(self, api):
        """PRD section 2.6: "3. Path-template identifiers resolve to existing resources, validated left-to-right along the URL — failure is the resource-specific not-found error (e.g., `ERR_MEMBER_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_EPISODE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_PCP_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CARE_TEAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_MEASUREMENT_NOT_FOUND`), or the generic `ERR_NOT_FOUND` when no resource-specific code applies."

        Design: Corner/validations/nonexistent_program_id_returns_404
        """
        resp = api.get_care_program(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND, expected_status=404)

    def test_body_fk_nonexistent_returns_404(self, api):
        """PRD section 2.6: "4. Body-supplied foreign keys resolve — a payload that names a `payer_contract_id`, `pcp_provider_id`, `member_id`, `enrollment_id`, `primary_np_id`, `social_worker_id`, or `behavioral_clinician_id` that does not exist yields the corresponding `ERR_{REFERENCED}_NOT_FOUND`."

        Design: Corner/validations/body_fk_nonexistent_returns_404
        """
        program = create_program()
        pcp = create_pcp(program["id"])
        resp = api.create_member(
            create_member_payload(program["id"], NON_EXISTENT_UUID, pcp["id"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND, expected_status=404)


class TestEnrollmentStateViolations:
    def test_enrollment_not_identified_for_begin_outreach(self, api):
        """PRD section 3.3: "The same begin-outreach action is also the re-engagement path from `DECLINED` back to `OUTREACH`; the two paths are distinguished by their starting state, with a call against an `IDENTIFIED` enrollment carrying the precondition that the status really is `IDENTIFIED` (else `ERR_ENROLLMENT_NOT_IDENTIFIED`) and a call against a `DECLINED` enrollment requiring the status really be `DECLINED` (else `ERR_ENROLLMENT_NOT_DECLINED`)."

        Design: Corner/validations/enrollment_not_identified_for_begin_outreach
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_outreach(enrollment["id"])
        resp = api.begin_outreach(enrollment["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_IDENTIFIED, expected_status=409)

    def test_enrollment_not_in_outreach_for_record_attempt(self, api):
        """PRD section 3.3: "Calling record-attempt from any status other than `OUTREACH` is rejected with `ERR_ENROLLMENT_NOT_IN_OUTREACH`."

        Design: Corner/validations/enrollment_not_in_outreach_for_record_attempt
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        resp = api.record_attempt(enrollment["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_IN_OUTREACH, expected_status=409)

    def test_enrollment_not_consented_for_activate(self, api):
        """PRD section 3.5: "Activation requires the enrollment to be in `CONSENTED` (else `ERR_ENROLLMENT_NOT_CONSENTED`) and the associated care team to be `ACTIVE` (else `ERR_CARE_TEAM_NOT_ACTIVE`)."

        Design: Corner/validations/enrollment_not_consented_for_activate
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_outreach(enrollment["id"])
        resp = api.activate_enrollment(enrollment["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_CONSENTED, expected_status=409)

    def test_enrollment_not_active_for_disenroll(self, api):
        """PRD section 3.3: "Calling disenroll from any other status is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`."

        Design: Corner/validations/enrollment_not_active_for_disenroll
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        resp = api.disenroll(
            enrollment["id"], {"disenrollment_reason": "MEMBER_REQUEST"}, SPECIALIST
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE, expected_status=409)

    def test_enrollment_superseded_rejected_on_transition(self, api):
        """PRD section 3.3: "Both paths require `is_current` to be `true` — operating on a superseded enrollment is rejected with `ERR_ENROLLMENT_SUPERSEDED` — and both reset `outreach_attempts` to 1, initializing the counter on first outreach and resetting it on re-engagement."

        Design: Corner/validations/enrollment_superseded_rejected_on_transition
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        member, enrollment1 = create_member_with_enrollment(program, contract, pcp)
        current = get_success_data(api.get_member(member["id"], SPECIALIST))
        get_success_data(api.create_enrollment(
            member["id"],
            {"outreach_channel": "MAIL", "expected_member_version": current["version"]},
            SPECIALIST,
        ))
        resp = api.begin_outreach(enrollment1["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_SUPERSEDED, expected_status=409)


class TestCareTeamAndOwnershipViolations:
    def test_care_team_not_active_for_visit_creation(self, api):
        """PRD section 3.4: "While a team is `SUSPENDED`, any new visit creation against the parent enrollment is rejected with `ERR_CARE_TEAM_NOT_ACTIVE`."

        Design: Corner/validations/care_team_not_active_for_visit_creation
        """
        ctx = setup_active_enrollment()
        get_success_data(api.suspend_care_team(ctx["enrollment"]["id"], COORDINATOR))
        resp = api.create_visit(
            {
                "enrollment_id": ctx["enrollment"]["id"],
                "visit_type": "ROUTINE_FOLLOWUP",
                "scheduled_start": "2026-09-02T09:00:00Z",
                "scheduled_end": "2026-09-02T10:00:00Z",
            },
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_CARE_TEAM_NOT_ACTIVE, expected_status=409)

    def test_not_assigned_clinician_depart_rejected(self, api):
        """PRD section 2.1: "A clinician who attempts a clinician-driven transition on a visit or episode they are not assigned to is rejected with `ERR_NOT_ASSIGNED_CLINICIAN` (HTTP 403)."

        Design: Corner/validations/not_assigned_clinician_depart_rejected
        """
        ctx = setup_active_enrollment()
        np2 = create_clinician(ctx["program"]["id"], full_name="Nick NP")
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        resp = api.depart_visit(visit["id"], make_clinician_headers(np2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_CLINICIAN, expected_status=403)


class TestTemporalAndOccViolations:
    def test_visit_time_overlap_same_clinician_rejected(self, api):
        """PRD section 2.10: "The check runs against every other visit currently in `SCHEDULED`, `EN_ROUTE`, or `IN_PROGRESS` status assigned to the same clinician, and a violation is reported as `ERR_VISIT_TIME_OVERLAP` (HTTP 409)."

        Design: Corner/validations/visit_time_overlap_same_clinician_rejected
        """
        ctx = setup_active_enrollment()
        create_scheduled_visit(
            ctx["enrollment"]["id"],
            start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z",
        )
        resp = api.create_visit(
            {
                "enrollment_id": ctx["enrollment"]["id"],
                "visit_type": "ROUTINE_FOLLOWUP",
                "scheduled_start": "2026-09-02T09:30:00Z",
                "scheduled_end": "2026-09-02T10:30:00Z",
            },
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_TIME_OVERLAP, expected_status=409)

    def test_visit_window_not_past_for_mark_no_show(self, api):
        """PRD section 3.5: "The assigned clinician may mark a `SCHEDULED` visit as `NO_SHOW` once the visit's window has passed: the current logical clock must be at or past `scheduled_end`, and calling before that moment is rejected with `ERR_VISIT_WINDOW_NOT_PAST`."

        Design: Corner/validations/visit_window_not_past_for_mark_no_show
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        set_clock("2026-09-02T09:00:00Z")
        resp = api.mark_no_show(visit["id"], make_clinician_headers(visit["clinician_id"]))
        validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_NOT_PAST, expected_status=409)

    def test_stale_version_on_enrollment_create(self, api):
        """PRD section 2.5: "A request to create a new enrollment for a member must carry `expected_member_version` holding the `Member.version` value the caller most recently observed for that member. If another writer has advanced the member's version since that observation — most commonly because another enrollment creation legitimately superseded the prior `is_current` enrollment — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_version_on_enrollment_create
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        member, _enrollment = create_member_with_enrollment(program, contract, pcp)
        resp = api.create_enrollment(
            member["id"],
            {"outreach_channel": "MAIL", "expected_member_version": member["version"]},
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_contract_expired_finalize_rejected(self, api):
        """PRD section 3.7: "Finalizing the settlement — a coordinator-independent administrator action — requires the settlement to be `PROVISIONAL` (else `ERR_SETTLEMENT_NOT_PROVISIONAL`) and the contract to be on or before its `contract_expiration_date` (else `ERR_CONTRACT_EXPIRED`)."

        Design: Corner/validations/contract_expired_finalize_rejected
        """
        program = create_program()
        resp = api.create_payer_contract(
            create_capitated_contract_payload(
                program["id"], contract_expiration_date="2026-06-30T23:59:59Z"
            ),
            CONTRACT_ADMIN,
        )
        contract = get_success_data(resp)
        settle = create_settlement(contract["id"])
        set_clock("2026-07-01T00:00:00Z")
        resp = api.finalize_settlement(contract["id"], settle["id"], CONTRACT_ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_EXPIRED, expected_status=409)

    def test_payment_model_mismatch_capitated_missing_pmpm(self, api):
        """PRD section 2.8: "A `CAPITATED` contract must supply `pmpm_rate_cents` (the per-member-per-month capitation rate in integer cents); a `SHARED_SAVINGS` contract must supply both `shared_savings_baseline_pmpm_cents` (the baseline medical cost per member per month against which savings are computed) and `shared_savings_split_pct` (the provider's share of any pooled savings, expressed as a number between 0 and 1). Mixing models — omitting the rate the chosen model requires — is rejected at creation with `ERR_PAYMENT_MODEL_MISMATCH` (HTTP 400)."

        Design: Corner/validations/payment_model_mismatch_capitated_missing_pmpm
        """
        program = create_program()
        payload = create_capitated_contract_payload(program["id"])
        del payload["pmpm_rate_cents"]
        resp = api.create_payer_contract(payload, CONTRACT_ADMIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_MODEL_MISMATCH, expected_status=400)


class TestPriorityOrdering:
    def test_auth_beats_state(self, api):
        """PRD section 2.6: "1. Presence and well-formedness of `X-User-ID` and `X-User-Role` — failure is `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD section 2.6: "The ladder matters: a caller cannot infer the state of a later check from the absence of an earlier error. A stale-version enrollment create against a member that does not exist reports `ERR_MEMBER_NOT_FOUND`, not `ERR_STALE_VERSION`."

        Design: Corner/validations/priority_ordering_auth_beats_state
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        # record-attempt from IDENTIFIED would fail state validation, but the
        # missing user-context header (rung 1) must be reported first.
        resp = api.record_attempt(
            enrollment["id"], headers={"Content-Type": "application/json"}
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )

    def test_existence_beats_state(self, api):
        """PRD section 2.6: "The ladder matters: a caller cannot infer the state of a later check from the absence of an earlier error. A stale-version enrollment create against a member that does not exist reports `ERR_MEMBER_NOT_FOUND`, not `ERR_STALE_VERSION`."

        Design: Corner/validations/priority_ordering_existence_beats_state
        """
        resp = api.record_attempt(NON_EXISTENT_UUID, SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND, expected_status=404)
