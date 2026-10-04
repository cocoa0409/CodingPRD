"""Corner-queue tests: state machine transitions (valid paths and happy flows)."""
import pytest

from test_helpers import (
    CONTRACT_ADMIN,
    ApiErrorId,
    COORDINATOR,
    SPECIALIST,
    activate_care_team_for,
    activate_enrollment,
    api_client,
    arrive_episode,
    complete_visit,
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
    get_care_team_row,
    get_success_data,
    make_clinician_headers,
    resolve_episode,
    set_clock,
    setup_active_enrollment,
    setup_basic_reference,
    upsert_and_submit_assessment,
    validate_success,
)


class TestEnrollmentTransitions:
    def test_begin_outreach_from_identified_success(self, api):
        """PRD section 3.3: "From `IDENTIFIED`, the specialist begins outreach, transitioning the enrollment to `OUTREACH`."
        PRD section 3.3: "Both paths require `is_current` to be `true` — operating on a superseded enrollment is rejected with `ERR_ENROLLMENT_SUPERSEDED` — and both reset `outreach_attempts` to 1, initializing the counter on first outreach and resetting it on re-engagement."

        Design: Corner/state_machines/enrollment_begin_outreach_from_identified_success
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        data = validate_success(api.begin_outreach(enrollment["id"], SPECIALIST))
        assert data["status"] == "OUTREACH"
        assert data["outreach_attempts"] == 1

    def test_begin_outreach_from_outreach_rejected(self, api):
        """PRD section 3.3: "The same begin-outreach action is also the re-engagement path from `DECLINED` back to `OUTREACH`; the two paths are distinguished by their starting state, with a call against an `IDENTIFIED` enrollment carrying the precondition that the status really is `IDENTIFIED` (else `ERR_ENROLLMENT_NOT_IDENTIFIED`) and a call against a `DECLINED` enrollment requiring the status really be `DECLINED` (else `ERR_ENROLLMENT_NOT_DECLINED`)."

        Design: Corner/state_machines/enrollment_begin_outreach_from_outreach_rejected
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_outreach(enrollment["id"])
        from test_helpers import validate_error
        resp = api.begin_outreach(enrollment["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_IDENTIFIED, expected_status=409)

    def test_record_consent_creates_care_team_draft(self, api):
        """PRD section 3.3: "On success the enrollment moves to `CONSENTED`, the system stamps `consent_recorded_at` with the current logical clock, and a new `CareTeam` is automatically created for this enrollment in `DRAFT` status with its `enrollment_id` and `member_id` populated and all three clinician foreign keys (`primary_np_id`, `social_worker_id`, `behavioral_clinician_id`) null."

        Design: Corner/state_machines/enrollment_record_consent_creates_care_team_draft
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_consented(enrollment["id"])
        team = get_care_team_row(enrollment["id"])
        assert team["status"] == "DRAFT"
        assert team["enrollment_id"] == enrollment["id"]

    def test_enrollment_activate_from_consented_success(self, api):
        """PRD section 3.5: "On success the enrollment moves to `ACTIVE`, becoming eligible for visit scheduling and urgent-response episodes."

        Design: Corner/state_machines/enrollment_activate_from_consented_success
        """
        ctx = setup_active_enrollment()
        assert ctx["enrollment"]["status"] == "ACTIVE"

    def test_enrollment_disenroll_from_active_success(self, api):
        """PRD section 3.7: "The enrollment's `is_current` flips to `false`."
        PRD section 3.3: "Disenrollment ends the funnel, moving the enrollment to the terminal `DISENROLLED` state."

        Design: Corner/state_machines/enrollment_disenroll_from_active_success
        """
        ctx = setup_active_enrollment()
        data = validate_success(api.disenroll(
            ctx["enrollment"]["id"], {"disenrollment_reason": "MEMBER_REQUEST"}, SPECIALIST
        ))
        assert data["status"] == "DISENROLLED"
        assert data["is_current"] is False

    def test_terminal_disenrolled_rejects_begin_outreach(self, api):
        """PRD section 3.3: "Disenrollment ends the funnel, moving the enrollment to the terminal `DISENROLLED` state."
        PRD section 3.3: "The same begin-outreach action is also the re-engagement path from `DECLINED` back to `OUTREACH`; the two paths are distinguished by their starting state, with a call against an `IDENTIFIED` enrollment carrying the precondition that the status really is `IDENTIFIED` (else `ERR_ENROLLMENT_NOT_IDENTIFIED`) and a call against a `DECLINED` enrollment requiring the status really be `DECLINED` (else `ERR_ENROLLMENT_NOT_DECLINED`)."

        Design: Corner/state_machines/enrollment_terminal_disenrolled_no_further_transitions
        """
        from test_helpers import validate_error
        ctx = setup_active_enrollment()
        validate_success(api.disenroll(
            ctx["enrollment"]["id"], {"disenrollment_reason": "MEMBER_REQUEST"}, SPECIALIST
        ))
        resp = api.begin_outreach(ctx["enrollment"]["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_IDENTIFIED, expected_status=409)


class TestCareTeamTransitions:
    def test_care_team_activate_from_draft_success(self, api):
        """PRD section 3.4: "On success the team moves to `ACTIVE`. Only then can the parent enrollment be activated (see §3.5)."

        Design: Corner/state_machines/care_team_activate_from_draft_success
        """
        program, contract, pcp, np = setup_basic_reference()
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_consented(enrollment["id"])
        team = activate_care_team_for(enrollment["id"], np["id"])
        assert team["status"] == "ACTIVE"

    def test_care_team_suspend_reinstate_cycle(self, api):
        """PRD section 3.4: "A team in `ACTIVE` may be moved to `SUSPENDED` by the coordinator (the only precondition is that the team really is `ACTIVE`, else `ERR_CARE_TEAM_NOT_ACTIVE`). While a team is `SUSPENDED`, any new visit creation against the parent enrollment is rejected with `ERR_CARE_TEAM_NOT_ACTIVE`. The coordinator may reinstate a `SUSPENDED` team back to `ACTIVE` — calling reinstate from any other status yields `ERR_CARE_TEAM_NOT_SUSPENDED`."

        Design: Corner/state_machines/care_team_suspend_reinstate_cycle
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        suspended = validate_success(api.suspend_care_team(enr_id, COORDINATOR))
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_care_team(enr_id, COORDINATOR))
        assert reinstated["status"] == "ACTIVE"


class TestVisitTransitions:
    def test_visit_depart_from_scheduled_success(self, api):
        """PRD section 3.5: "The clinician marks departure, moving the visit to `EN_ROUTE`; the call requires the visit really be `SCHEDULED` (else `ERR_VISIT_NOT_SCHEDULED`) and the caller's `X-User-ID` to equal the visit's `clinician_id` (else `ERR_NOT_ASSIGNED_CLINICIAN`)."

        Design: Corner/state_machines/visit_depart_from_scheduled_success
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        data = validate_success(api.depart_visit(
            visit["id"], make_clinician_headers(visit["clinician_id"])
        ))
        assert data["status"] == "EN_ROUTE"

    def test_visit_arrive_sets_actual_start(self, api):
        """PRD section 3.5: "Arrival transitions the visit from `EN_ROUTE` to `IN_PROGRESS` (calling arrive from any other state yields `ERR_VISIT_NOT_EN_ROUTE`) and stamps `actual_start` with the current logical clock."

        Design: Corner/state_machines/visit_arrive_from_en_route_sets_actual_start
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        headers = make_clinician_headers(visit["clinician_id"])
        validate_success(api.depart_visit(visit["id"], headers))
        set_clock("2026-09-02T09:30:00Z")
        data = validate_success(api.arrive_visit(visit["id"], headers))
        assert data["status"] == "IN_PROGRESS"
        assert data["actual_start"] is not None
        assert data["actual_start"].startswith("2026-09-02T09:30:00"), (
            f"actual_start must stamp the current logical clock, got {data['actual_start']}"
        )

    def test_visit_cancel_from_scheduled_success(self, api):
        """PRD section 3.5: "Cancellation moves the visit to `CANCELLED`, decrements the assigned clinician's `active_daily_visit_count` by 1, and increments `visits_cancelled` on the period's `PerformanceMeasurement` row (with `composite_score` recomputed)."

        Design: Corner/state_machines/visit_cancel_from_scheduled_success
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        data = validate_success(api.cancel_visit(
            visit["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
        ))
        assert data["status"] == "CANCELLED"

    def test_visit_mark_no_show_after_window_end(self, api):
        """PRD section 3.5: "The assigned clinician may mark a `SCHEDULED` visit as `NO_SHOW` once the visit's window has passed: the current logical clock must be at or past `scheduled_end`, and calling before that moment is rejected with `ERR_VISIT_WINDOW_NOT_PAST`."

        Design: Corner/state_machines/visit_mark_no_show_from_scheduled_after_window_end
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        set_clock("2026-09-02T10:00:00Z")
        data = validate_success(api.mark_no_show(
            visit["id"], make_clinician_headers(visit["clinician_id"])
        ))
        assert data["status"] == "NO_SHOW"

    def test_assessment_submit_from_draft_success(self, api):
        """PRD section 3.5: "Submitting the assessment moves it from `DRAFT` to `SUBMITTED`."

        Design: Corner/state_machines/visit_assessment_submit_from_draft_success
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(
            ctx["enrollment"]["id"], visit_type="INITIAL_ASSESSMENT"
        )
        drive_visit_to_in_progress(visit)
        assessment = upsert_and_submit_assessment(visit)
        assert assessment["status"] == "SUBMITTED"


class TestUrgentEpisodeTransitions:
    def test_dispatch_from_triggered_success(self, api):
        """PRD section 3.6: "A successful dispatch writes the chosen clinician into `dispatched_clinician_id`, moves the episode to `DISPATCHED`, and increments that clinician's `active_daily_visit_count` by 1."

        Design: Corner/state_machines/urgent_episode_dispatch_from_triggered_success
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        episode = create_triggered_episode(ctx["enrollment"]["id"])
        dispatched = dispatch_episode(episode["id"])
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["dispatched_clinician_id"] == ctx["np"]["id"]

    def test_resolve_from_on_scene_success(self, api):
        """PRD section 3.6: "On success the episode moves to `RESOLVED` and the dispatched clinician's `active_daily_visit_count` decrements by 1."

        Design: Corner/state_machines/urgent_episode_resolve_from_on_scene_success
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        episode = create_dispatched_episode(ctx["enrollment"]["id"])
        arrive_episode(episode)
        resolved = resolve_episode(episode, "AVOIDED_ED")
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_outcome"] == "AVOIDED_ED"


class TestSettlementTransitions:
    def test_finalize_from_provisional_success(self, api):
        """PRD section 3.7: "The settlement moves to `FINALIZED`."

        Design: Corner/state_machines/settlement_finalize_from_provisional_success
        """
        ctx = setup_active_enrollment()
        settle = finalize_settlement(
            ctx["contract"]["id"], create_settlement(ctx["contract"]["id"])["id"]
        )
        assert settle["status"] == "FINALIZED"

    def test_void_from_provisional_success(self, api):
        """PRD section 3.7: "A `PROVISIONAL` settlement may alternatively be voided — moving it to `VOIDED` — with the same `ERR_SETTLEMENT_NOT_PROVISIONAL` precondition as finalize. `PAID` and `VOIDED` are terminal."

        Design: Corner/state_machines/settlement_void_from_provisional_success
        """
        ctx = setup_active_enrollment()
        settle = create_settlement(ctx["contract"]["id"])
        voided = validate_success(api.void_settlement(
            ctx["contract"]["id"], settle["id"], CONTRACT_ADMIN
        ))
        assert voided["status"] == "VOIDED"

    def test_mark_paid_from_finalized_success(self, api):
        """PRD section 3.7: "A `FINALIZED` settlement may be marked paid, moving it to `PAID`; the call requires `FINALIZED` status and is otherwise rejected with `ERR_SETTLEMENT_NOT_FINALIZED`."

        Design: Corner/state_machines/settlement_mark_paid_from_finalized_success
        """
        ctx = setup_active_enrollment()
        settle = finalize_settlement(
            ctx["contract"]["id"], create_settlement(ctx["contract"]["id"])["id"]
        )
        paid = validate_success(api.mark_settlement_paid(
            ctx["contract"]["id"], settle["id"], CONTRACT_ADMIN
        ))
        assert paid["status"] == "PAID"


from test_helpers import CONTRACT_ADMIN as CONTRACT_ADMIN
