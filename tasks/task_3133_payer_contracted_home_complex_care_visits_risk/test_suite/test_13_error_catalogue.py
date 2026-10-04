"""Corner-queue tests: error catalogue trigger conditions."""
import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    CONTRACT_ADMIN,
    ApiErrorId,
    COORDINATOR,
    NON_EXISTENT_UUID,
    SPECIALIST,
    advance_clock,
    api_client,
    arrive_episode,
    create_dispatched_episode,
    create_member_with_enrollment,
    create_scheduled_visit,
    create_settlement,
    create_triggered_episode,
    dispatch_episode,
    drive_enrollment_to_consented,
    drive_enrollment_to_outreach,
    drive_visit_to_in_progress,
    finalize_settlement,
    get_success_data,
    make_clinician_headers,
    setup_active_enrollment,
    setup_basic_reference,
    upsert_and_submit_assessment,
    create_assessment_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestNotFoundErrors:
    def test_error_enrollment_not_found(self, api):
        """PRD section 2.6: "3. Path-template identifiers resolve to existing resources, validated left-to-right along the URL — failure is the resource-specific not-found error (e.g., `ERR_MEMBER_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_EPISODE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_PCP_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CARE_TEAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_MEASUREMENT_NOT_FOUND`), or the generic `ERR_NOT_FOUND` when no resource-specific code applies."

        Design: Corner/errors/error_enrollment_not_found
        """
        resp = api.get_enrollment(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND, expected_status=404)

    def test_error_visit_not_found(self, api):
        """PRD section 2.6: "3. Path-template identifiers resolve to existing resources, validated left-to-right along the URL — failure is the resource-specific not-found error (e.g., `ERR_MEMBER_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_EPISODE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_PCP_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CARE_TEAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_MEASUREMENT_NOT_FOUND`), or the generic `ERR_NOT_FOUND` when no resource-specific code applies."

        Design: Corner/errors/error_visit_not_found
        """
        resp = api.get_visit(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_FOUND, expected_status=404)

    def test_error_episode_not_found(self, api):
        """PRD section 2.6: "3. Path-template identifiers resolve to existing resources, validated left-to-right along the URL — failure is the resource-specific not-found error (e.g., `ERR_MEMBER_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_EPISODE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_PCP_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CARE_TEAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_MEASUREMENT_NOT_FOUND`), or the generic `ERR_NOT_FOUND` when no resource-specific code applies."

        Design: Corner/errors/error_episode_not_found
        """
        resp = api.get_urgent_episode(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_FOUND, expected_status=404)

    def test_error_settlement_not_found(self, api):
        """PRD section 2.6: "3. Path-template identifiers resolve to existing resources, validated left-to-right along the URL — failure is the resource-specific not-found error (e.g., `ERR_MEMBER_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_EPISODE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_PCP_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CARE_TEAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_MEASUREMENT_NOT_FOUND`), or the generic `ERR_NOT_FOUND` when no resource-specific code applies."

        Design: Corner/errors/error_settlement_not_found
        """
        resp = api.get_settlement(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND, expected_status=404)

    def test_error_measurement_not_found(self, api):
        """PRD section 2.6: "3. Path-template identifiers resolve to existing resources, validated left-to-right along the URL — failure is the resource-specific not-found error (e.g., `ERR_MEMBER_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_EPISODE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_PCP_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CARE_TEAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_MEASUREMENT_NOT_FOUND`), or the generic `ERR_NOT_FOUND` when no resource-specific code applies."

        Design: Corner/errors/error_measurement_not_found
        """
        resp = api.get_performance_measurement(NON_EXISTENT_UUID, ANALYST)
        validate_error(resp, ApiErrorId.ERR_MEASUREMENT_NOT_FOUND, expected_status=404)


class TestMissingInputErrors:
    def test_error_consent_document_required(self, api):
        """PRD section 3.3: "Consent is recorded from `OUTREACH` via record-consent, which requires a `consent_document_id` reference to the signed consent document; a missing document is rejected with `ERR_CONSENT_DOCUMENT_REQUIRED`."

        Design: Corner/errors/error_consent_document_required
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_outreach(enrollment["id"])
        resp = api.record_consent(enrollment["id"], {}, SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_CONSENT_DOCUMENT_REQUIRED, expected_status=400)

    def test_error_disenrollment_reason_required(self, api):
        """PRD section 3.3: "From either `CONSENTED` or `ACTIVE`, a `disenrollment_reason` is required — one of `MEMBER_REQUEST`, `PAYER_TERMINATION`, `DECEASED`, `MOVED_OUT_OF_AREA`, or `NON_ENGAGEMENT` — and its absence is rejected with `ERR_DISENROLLMENT_REASON_REQUIRED`."

        Design: Corner/errors/error_disenrollment_reason_required
        """
        ctx = setup_active_enrollment()
        resp = api.disenroll(ctx["enrollment"]["id"], {}, SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_DISENROLLMENT_REASON_REQUIRED, expected_status=400)

    def test_error_cancellation_reason_required(self, api):
        """PRD section 3.5: "Cancelling a `SCHEDULED` visit is a coordinator action requiring a `cancellation_reason` of `MEMBER_REQUEST`, `CLINICIAN_UNAVAILABLE`, `MEMBER_NO_SHOW`, or `ENROLLMENT_ENDED`; its absence yields `ERR_CANCELLATION_REASON_REQUIRED`, and calling cancel on a visit that is not `SCHEDULED` yields `ERR_VISIT_NOT_CANCELLABLE`."

        Design: Corner/errors/error_cancellation_reason_required
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        resp = api.cancel_visit(visit["id"], {}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_CANCELLATION_REASON_REQUIRED, expected_status=400)

    def test_error_resolution_outcome_required(self, api):
        """PRD section 3.6: "Resolution requires the episode to be `ON_SCENE` (else `ERR_EPISODE_NOT_ON_SCENE`), the caller to be the dispatched clinician (else `ERR_NOT_ASSIGNED_CLINICIAN`), and a `resolved_outcome` of `AVOIDED_ED` or `REFERRED_TO_ED` (its absence is rejected with `ERR_RESOLUTION_OUTCOME_REQUIRED`)."

        Design: Corner/errors/error_resolution_outcome_required
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        episode = create_dispatched_episode(ctx["enrollment"]["id"])
        arrive_episode(episode)
        resp = api.resolve_episode(
            episode["id"], {}, make_clinician_headers(episode["dispatched_clinician_id"])
        )
        validate_error(resp, ApiErrorId.ERR_RESOLUTION_OUTCOME_REQUIRED, expected_status=400)

    def test_error_pcp_coordination_note_required(self, api):
        """PRD section 3.5: "The complete call requires the visit to be `IN_PROGRESS` (else `ERR_VISIT_NOT_IN_PROGRESS`), the caller to be the assigned clinician (else `ERR_NOT_ASSIGNED_CLINICIAN`), a `SUBMITTED` assessment to exist for the visit (else `ERR_ASSESSMENT_NOT_SUBMITTED`), and the assessment's `pcp_coordination_note` to be non-empty (else `ERR_PCP_COORDINATION_NOTE_REQUIRED`)."

        Design: Corner/errors/error_pcp_coordination_note_required
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(
            ctx["enrollment"]["id"], visit_type="INITIAL_ASSESSMENT"
        )
        drive_visit_to_in_progress(visit)
        upsert_and_submit_assessment(visit, {"pcp_coordination_note": ""})
        resp = api.complete_visit(visit["id"], make_clinician_headers(visit["clinician_id"]))
        validate_error(resp, ApiErrorId.ERR_PCP_COORDINATION_NOTE_REQUIRED, expected_status=400)

    def test_error_assessment_incomplete(self, api):
        """PRD section 3.5: "The submit requires the assessment to be `DRAFT` (else `ERR_ASSESSMENT_NOT_DRAFT`), the parent visit to be `IN_PROGRESS` (else `ERR_VISIT_NOT_IN_PROGRESS`), and all three structured objects — `medication_reconciliation`, `safety_evaluation`, and `social_needs_screening` — to be present and fully populated (else `ERR_ASSESSMENT_INCOMPLETE`)."

        Design: Corner/errors/error_assessment_incomplete
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(
            ctx["enrollment"]["id"], visit_type="INITIAL_ASSESSMENT"
        )
        drive_visit_to_in_progress(visit)
        headers = make_clinician_headers(visit["clinician_id"])
        payload = create_assessment_payload()
        del payload["social_needs_screening"]
        get_success_data(api.upsert_assessment(visit["id"], payload, headers))
        resp = api.submit_assessment(visit["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INCOMPLETE, expected_status=400)


class TestEnrollmentThresholdErrors:
    def test_error_outreach_attempts_exhausted(self, api):
        """PRD section 3.3: "An attempt that would push `outreach_attempts` past the cap is rejected with `ERR_OUTREACH_ATTEMPTS_EXHAUSTED`; an attempt that brings the counter to exactly 3 fires an automatic transition to `DECLINED` with `disenrollment_reason` set to `NON_ENGAGEMENT`, and the same `ERR_OUTREACH_ATTEMPTS_EXHAUSTED` rejection surfaces on any subsequent record-attempt call."

        Design: Corner/errors/error_outreach_attempts_exhausted
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_outreach(enrollment["id"])
        # attempts now 1; two more record-attempts bring the counter to 3.
        validate_success(api.record_attempt(enrollment["id"], SPECIALIST))
        validate_success(api.record_attempt(enrollment["id"], SPECIALIST))
        resp = api.record_attempt(enrollment["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_OUTREACH_ATTEMPTS_EXHAUSTED, expected_status=409)


class TestCareTeamStateErrors:
    def test_error_care_team_not_draft(self, api):
        """PRD section 3.4: "Activating the care team requires the team to be in `DRAFT` (else `ERR_CARE_TEAM_NOT_DRAFT`) and requires `primary_np_id` to be populated, to reference an `ACTIVE` clinician, and to reference a clinician whose `discipline` is `NP` — failure of any of these is reported as `ERR_PRIMARY_NP_INVALID`."

        Design: Corner/errors/error_care_team_not_draft
        """
        program, contract, pcp, np = setup_basic_reference()
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_consented(enrollment["id"])
        get_success_data(api.update_care_team(
            enrollment["id"], {"primary_np_id": np["id"]}, COORDINATOR
        ))
        validate_success(api.activate_care_team(enrollment["id"], COORDINATOR))
        resp = api.activate_care_team(enrollment["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_CARE_TEAM_NOT_DRAFT, expected_status=409)

    def test_error_care_team_not_suspended(self, api):
        """PRD section 3.4: "The coordinator may reinstate a `SUSPENDED` team back to `ACTIVE` — calling reinstate from any other status yields `ERR_CARE_TEAM_NOT_SUSPENDED`."

        Design: Corner/errors/error_care_team_not_suspended
        """
        ctx = setup_active_enrollment()
        resp = api.reinstate_care_team(ctx["enrollment"]["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_CARE_TEAM_NOT_SUSPENDED, expected_status=409)


class TestVisitStateErrors:
    def test_error_visit_not_scheduled_for_depart(self, api):
        """PRD section 3.5: "The clinician marks departure, moving the visit to `EN_ROUTE`; the call requires the visit really be `SCHEDULED` (else `ERR_VISIT_NOT_SCHEDULED`) and the caller's `X-User-ID` to equal the visit's `clinician_id` (else `ERR_NOT_ASSIGNED_CLINICIAN`)."

        Design: Corner/errors/error_visit_not_scheduled_for_depart
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        headers = make_clinician_headers(visit["clinician_id"])
        validate_success(api.depart_visit(visit["id"], headers))
        resp = api.depart_visit(visit["id"], headers)
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_SCHEDULED, expected_status=409)

    def test_error_visit_not_en_route_for_arrive(self, api):
        """PRD section 3.5: "Arrival transitions the visit from `EN_ROUTE` to `IN_PROGRESS` (calling arrive from any other state yields `ERR_VISIT_NOT_EN_ROUTE`) and stamps `actual_start` with the current logical clock."

        Design: Corner/errors/error_visit_not_en_route_for_arrive
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        resp = api.arrive_visit(visit["id"], make_clinician_headers(visit["clinician_id"]))
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_EN_ROUTE, expected_status=409)

    def test_error_visit_not_in_progress_for_complete(self, api):
        """PRD section 3.5: "The complete call requires the visit to be `IN_PROGRESS` (else `ERR_VISIT_NOT_IN_PROGRESS`), the caller to be the assigned clinician (else `ERR_NOT_ASSIGNED_CLINICIAN`), a `SUBMITTED` assessment to exist for the visit (else `ERR_ASSESSMENT_NOT_SUBMITTED`), and the assessment's `pcp_coordination_note` to be non-empty (else `ERR_PCP_COORDINATION_NOTE_REQUIRED`)."

        Design: Corner/errors/error_visit_not_in_progress_for_complete
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        headers = make_clinician_headers(visit["clinician_id"])
        validate_success(api.depart_visit(visit["id"], headers))
        resp = api.complete_visit(visit["id"], headers)
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_IN_PROGRESS, expected_status=409)

    def test_error_visit_not_cancellable(self, api):
        """PRD section 3.5: "Cancelling a `SCHEDULED` visit is a coordinator action requiring a `cancellation_reason` of `MEMBER_REQUEST`, `CLINICIAN_UNAVAILABLE`, `MEMBER_NO_SHOW`, or `ENROLLMENT_ENDED`; its absence yields `ERR_CANCELLATION_REASON_REQUIRED`, and calling cancel on a visit that is not `SCHEDULED` yields `ERR_VISIT_NOT_CANCELLABLE`."

        Design: Corner/errors/error_visit_not_cancellable
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        validate_success(api.depart_visit(
            visit["id"], make_clinician_headers(visit["clinician_id"])
        ))
        resp = api.cancel_visit(
            visit["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_CANCELLABLE, expected_status=409)

    def test_error_visit_not_cancelled_for_reschedule(self, api):
        """PRD section 3.5: "The reschedule requires the visit to be `CANCELLED` (else `ERR_VISIT_NOT_CANCELLED`), the visit's `reschedule_count` to be strictly less than the cap of 2 (else `ERR_MAX_RESCHEDULES_EXCEEDED`), the proposed window to clear the half-open overlap check against the clinician's other in-flight visits (else `ERR_VISIT_TIME_OVERLAP`), and the parent enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`)."

        Design: Corner/errors/error_visit_not_cancelled_for_reschedule
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        resp = api.reschedule_visit(
            visit["id"],
            {
                "scheduled_start": "2026-09-03T09:00:00Z",
                "scheduled_end": "2026-09-03T10:00:00Z",
                "expected_visit_version": visit["version"],
            },
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_CANCELLED, expected_status=409)

    def test_error_max_reschedules_exceeded(self, api):
        """PRD section 3.5: "The reschedule requires the visit to be `CANCELLED` (else `ERR_VISIT_NOT_CANCELLED`), the visit's `reschedule_count` to be strictly less than the cap of 2 (else `ERR_MAX_RESCHEDULES_EXCEEDED`), the proposed window to clear the half-open overlap check against the clinician's other in-flight visits (else `ERR_VISIT_TIME_OVERLAP`), and the parent enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`)."

        Design: Corner/errors/error_max_reschedules_exceeded
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        current = visit
        for day in ("2026-09-03", "2026-09-04"):
            cancelled = validate_success(api.cancel_visit(
                current["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
            ))
            current = validate_success(api.reschedule_visit(
                current["id"],
                {
                    "scheduled_start": f"{day}T09:00:00Z",
                    "scheduled_end": f"{day}T10:00:00Z",
                    "expected_visit_version": cancelled["version"],
                },
                COORDINATOR,
            ))
        cancelled = validate_success(api.cancel_visit(
            current["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
        ))
        resp = api.reschedule_visit(
            current["id"],
            {
                "scheduled_start": "2026-09-05T09:00:00Z",
                "scheduled_end": "2026-09-05T10:00:00Z",
                "expected_visit_version": cancelled["version"],
            },
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_MAX_RESCHEDULES_EXCEEDED, expected_status=409)


class TestAssessmentStateErrors:
    def test_error_assessment_not_draft_for_submit(self, api):
        """PRD section 3.5: "The submit requires the assessment to be `DRAFT` (else `ERR_ASSESSMENT_NOT_DRAFT`), the parent visit to be `IN_PROGRESS` (else `ERR_VISIT_NOT_IN_PROGRESS`), and all three structured objects — `medication_reconciliation`, `safety_evaluation`, and `social_needs_screening` — to be present and fully populated (else `ERR_ASSESSMENT_INCOMPLETE`)."

        Design: Corner/errors/error_assessment_not_draft_for_submit
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(
            ctx["enrollment"]["id"], visit_type="INITIAL_ASSESSMENT"
        )
        drive_visit_to_in_progress(visit)
        upsert_and_submit_assessment(visit)
        resp = api.submit_assessment(
            visit["id"], make_clinician_headers(visit["clinician_id"])
        )
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_DRAFT, expected_status=409)

    def test_error_assessment_not_submitted_for_complete(self, api):
        """PRD section 3.5: "The complete call requires the visit to be `IN_PROGRESS` (else `ERR_VISIT_NOT_IN_PROGRESS`), the caller to be the assigned clinician (else `ERR_NOT_ASSIGNED_CLINICIAN`), a `SUBMITTED` assessment to exist for the visit (else `ERR_ASSESSMENT_NOT_SUBMITTED`), and the assessment's `pcp_coordination_note` to be non-empty (else `ERR_PCP_COORDINATION_NOTE_REQUIRED`)."

        Design: Corner/errors/error_assessment_not_submitted_for_complete
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(
            ctx["enrollment"]["id"], visit_type="INITIAL_ASSESSMENT"
        )
        drive_visit_to_in_progress(visit)
        headers = make_clinician_headers(visit["clinician_id"])
        get_success_data(api.upsert_assessment(
            visit["id"], create_assessment_payload(), headers
        ))
        resp = api.complete_visit(visit["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_SUBMITTED, expected_status=409)


class TestEpisodeStateErrors:
    def test_error_episode_not_triggered_for_dispatch(self, api):
        """PRD section 3.6: "The dispatch requires the episode to be `TRIGGERED` (else `ERR_EPISODE_NOT_TRIGGERED`) and the current logical clock to be at or before `sla_deadline` (else `ERR_SLA_ALREADY_LAPSED` — dispatching after the deadline would already be a SLA miss)."

        Design: Corner/errors/error_episode_not_triggered_for_dispatch
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        episode = create_triggered_episode(ctx["enrollment"]["id"])
        dispatch_episode(episode["id"])
        resp = api.dispatch_episode(episode["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_TRIGGERED, expected_status=409)

    def test_error_episode_not_dispatched_for_arrive(self, api):
        """PRD section 3.6: "The arrive call requires the episode to be `DISPATCHED` (else `ERR_EPISODE_NOT_DISPATCHED`) and the caller's `X-User-ID` to equal `dispatched_clinician_id` (else `ERR_NOT_ASSIGNED_CLINICIAN`)."

        Design: Corner/errors/error_episode_not_dispatched_for_arrive
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        episode = create_triggered_episode(ctx["enrollment"]["id"])
        resp = api.arrive_episode(
            episode["id"], make_clinician_headers(ctx["np"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_DISPATCHED, expected_status=409)

    def test_error_episode_not_on_scene_for_resolve(self, api):
        """PRD section 3.6: "Resolution requires the episode to be `ON_SCENE` (else `ERR_EPISODE_NOT_ON_SCENE`), the caller to be the dispatched clinician (else `ERR_NOT_ASSIGNED_CLINICIAN`), and a `resolved_outcome` of `AVOIDED_ED` or `REFERRED_TO_ED` (its absence is rejected with `ERR_RESOLUTION_OUTCOME_REQUIRED`)."

        Design: Corner/errors/error_episode_not_on_scene_for_resolve
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        episode = create_dispatched_episode(ctx["enrollment"]["id"])
        resp = api.resolve_episode(
            episode["id"],
            {"resolved_outcome": "AVOIDED_ED"},
            make_clinician_headers(episode["dispatched_clinician_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_ON_SCENE, expected_status=409)

    def test_error_sla_already_lapsed(self, api):
        """PRD section 3.6: "The dispatch requires the episode to be `TRIGGERED` (else `ERR_EPISODE_NOT_TRIGGERED`) and the current logical clock to be at or before `sla_deadline` (else `ERR_SLA_ALREADY_LAPSED` — dispatching after the deadline would already be a SLA miss)."
        PRD section 3.6: "Whenever the logical clock advances past an episode's `sla_deadline` and the episode is still `TRIGGERED` or still `DISPATCHED`, the system transitions the episode to `LAPSED`, sets `sla_met` to `false`, and recomputes `composite_score` on the period's measurement row — the lapsed episode remains counted in `urgent_episodes_triggered` but never reaches `urgent_episodes_sla_met`, depressing the SLA ratio."

        Design: Corner/errors/error_sla_already_lapsed
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        episode = create_triggered_episode(ctx["enrollment"]["id"])
        advance_clock(25)
        resp = api.dispatch_episode(episode["id"], COORDINATOR)
        assert resp.status_code == 409
        # The hour-advance sweep may already have lapsed the episode; either the
        # temporal rejection or the state rejection is a faithful outcome here.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_SLA_ALREADY_LAPSED.value,
            ApiErrorId.ERR_EPISODE_NOT_TRIGGERED.value,
        ])


class TestSelectorAndSettlementStateErrors:
    def test_error_no_available_clinician(self, api):
        """PRD section 3.5: "An empty pool is rejected with `ERR_NO_AVAILABLE_CLINICIAN`."
        PRD section 2.9: "A clinician is only eligible for an assignment if their `home_zip` is in the program's `service_geography_zips` list, their `status` is `ACTIVE`, and their `active_daily_visit_count` is strictly less than `max_daily_visits`. When the eligible pool is empty, the assignment is rejected with `ERR_NO_AVAILABLE_CLINICIAN` (HTTP 409)."

        Design: Corner/errors/error_no_available_clinician
        """
        ctx = setup_active_enrollment(clinician_overrides={"max_daily_visits": 1})
        create_scheduled_visit(ctx["enrollment"]["id"])
        resp = api.create_visit(
            {
                "enrollment_id": ctx["enrollment"]["id"],
                "visit_type": "ROUTINE_FOLLOWUP",
                "scheduled_start": "2026-09-02T11:00:00Z",
                "scheduled_end": "2026-09-02T12:00:00Z",
            },
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_CLINICIAN, expected_status=409)

    def test_error_settlement_not_provisional_for_finalize(self, api):
        """PRD section 3.7: "Finalizing the settlement — a coordinator-independent administrator action — requires the settlement to be `PROVISIONAL` (else `ERR_SETTLEMENT_NOT_PROVISIONAL`) and the contract to be on or before its `contract_expiration_date` (else `ERR_CONTRACT_EXPIRED`)."

        Design: Corner/errors/error_settlement_not_provisional_for_finalize
        """
        ctx = setup_active_enrollment()
        contract_id = ctx["contract"]["id"]
        settle = finalize_settlement(contract_id, create_settlement(contract_id)["id"])
        resp = api.finalize_settlement(contract_id, settle["id"], CONTRACT_ADMIN)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_PROVISIONAL, expected_status=409)

    def test_error_settlement_not_finalized_for_mark_paid(self, api):
        """PRD section 3.7: "A `FINALIZED` settlement may be marked paid, moving it to `PAID`; the call requires `FINALIZED` status and is otherwise rejected with `ERR_SETTLEMENT_NOT_FINALIZED`."

        Design: Corner/errors/error_settlement_not_finalized_for_mark_paid
        """
        ctx = setup_active_enrollment()
        contract_id = ctx["contract"]["id"]
        settle = create_settlement(contract_id)
        resp = api.mark_settlement_paid(contract_id, settle["id"], CONTRACT_ADMIN)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FINALIZED, expected_status=409)

