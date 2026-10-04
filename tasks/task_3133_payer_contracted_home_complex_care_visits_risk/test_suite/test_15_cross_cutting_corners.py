"""Corner-queue tests: cross-cutting complexity layers (OCC, cascades, thresholds,
selector policy) and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    COORDINATOR,
    SPECIALIST,
    api_client,
    create_clinician,
    create_member_with_enrollment,
    create_scheduled_visit,
    create_triggered_episode,
    dispatch_episode,
    drive_enrollment_to_consented,
    drive_enrollment_to_outreach,
    get_care_team_row,
    get_success_data,
    setup_active_enrollment,
    setup_basic_reference,
    validate_error,
    validate_success,
)


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_enrollment_create(self, api):
        """PRD section 2.5: "A request to create a new enrollment for a member must carry `expected_member_version` holding the `Member.version` value the caller most recently observed for that member. If another writer has advanced the member's version since that observation — most commonly because another enrollment creation legitimately superseded the prior `is_current` enrollment — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_enrollment_create
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        member, _enrollment = create_member_with_enrollment(program, contract, pcp)
        resp = api.create_enrollment(
            member["id"],
            {"outreach_channel": "MAIL", "expected_member_version": member["version"]},
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_stale_version_on_visit_reschedule(self, api):
        """PRD section 2.5: "A request to reschedule a cancelled visit must carry `expected_visit_version` holding the `Visit.version` value the caller most recently observed. A mismatch against the visit's current `version` — for example, because a disenrollment cascade or a prior cancel already advanced it — is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_visit_reschedule
        """
        ctx = setup_active_enrollment()
        visit = create_scheduled_visit(ctx["enrollment"]["id"])
        stale_version = visit["version"]
        # The cancel advances the visit's version.
        validate_success(api.cancel_visit(
            visit["id"], {"cancellation_reason": "MEMBER_REQUEST"}, COORDINATOR
        ))
        resp = api.reschedule_visit(
            visit["id"],
            {
                "scheduled_start": "2026-09-03T09:00:00Z",
                "scheduled_end": "2026-09-03T10:00:00Z",
                "expected_visit_version": stale_version,
            },
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestCascadingSideEffects:
    def test_disenroll_cancels_visits_and_retires_care_team(self, api):
        """PRD section 3.7: "When an `ACTIVE` enrollment disenrolls, every `SCHEDULED` visit child of the enrollment cascades to `CANCELLED` with `cancellation_reason` set to `ENROLLMENT_ENDED`, and each cascaded cancellation decrements its assigned clinician's `active_daily_visit_count` by 1. The care team for the enrollment cascades to `RETIRED` — this is the only path by which a care team reaches `RETIRED`, and it fires whether the team was `DRAFT`, `ACTIVE`, or `SUSPENDED`."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effect_enrollment_disenroll_cancels_visits
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        v1 = create_scheduled_visit(
            enr_id, start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z"
        )
        v2 = create_scheduled_visit(
            enr_id, start="2026-09-03T09:00:00Z", end="2026-09-03T10:00:00Z"
        )
        validate_success(api.disenroll(
            enr_id, {"disenrollment_reason": "MEMBER_REQUEST"}, SPECIALIST
        ))
        for v in (v1, v2):
            after = validate_success(api.get_visit(v["id"], COORDINATOR))
            assert after["status"] == "CANCELLED"
        team = get_care_team_row(enr_id)
        assert team["status"] == "RETIRED"


class TestRateThresholds:
    def test_outreach_attempts_max_cap(self, api):
        """PRD section 3.3: "While in `OUTREACH`, the specialist records each subsequent contact by recording an attempt. This is a cyclic self-transition that leaves the enrollment in `OUTREACH` and increments `outreach_attempts` by 1. The counter caps at a maximum of 3 attempts. An attempt that would push `outreach_attempts` past the cap is rejected with `ERR_OUTREACH_ATTEMPTS_EXHAUSTED`; an attempt that brings the counter to exactly 3 fires an automatic transition to `DECLINED` with `disenrollment_reason` set to `NON_ENGAGEMENT`, and the same `ERR_OUTREACH_ATTEMPTS_EXHAUSTED` rejection surfaces on any subsequent record-attempt call."

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_outreach_attempts_max
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_outreach(enrollment["id"])
        validate_success(api.record_attempt(enrollment["id"], SPECIALIST))
        validate_success(api.record_attempt(enrollment["id"], SPECIALIST))
        resp = api.record_attempt(enrollment["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_OUTREACH_ATTEMPTS_EXHAUSTED, expected_status=409)


class TestSelectorPolicy:
    def test_routine_selector_lowest_count_wins(self, api):
        """PRD section 3.5: "Within the eligible pool the selector ranks by lowest `active_daily_visit_count` first, then by earliest clinician `created_at`; the clinician `id` is never used as a tie-break."

        Design: Corner/cross_cutting_complexity_layers/selector_policy_routine_visit_clinician_assignment
        """
        ctx = setup_active_enrollment()
        np2 = create_clinician(ctx["program"]["id"], full_name="Nick NP")
        # First visit goes to NP1 (earliest created_at at equal count 0);
        # the second must go to NP2 because NP1 now carries count 1.
        create_scheduled_visit(
            ctx["enrollment"]["id"],
            start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z",
        )
        second = create_scheduled_visit(
            ctx["enrollment"]["id"],
            start="2026-09-02T11:00:00Z", end="2026-09-02T12:00:00Z",
        )
        assert second["clinician_id"] == np2["id"]

    def test_urgent_selector_lowest_count_wins(self, api):
        """PRD section 3.6: "Ranking is by lowest `active_daily_visit_count`, then earliest clinician `created_at`; again, `id` is never a tie-break."

        Design: Corner/cross_cutting_complexity_layers/selector_policy_urgent_episode_clinician_assignment
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        np2 = create_clinician(
            ctx["program"]["id"], full_name="Nick NP", urgent_response_qualified=True
        )
        # Load NP1 with one routine visit so NP2 (count 0) wins the dispatch.
        create_scheduled_visit(
            ctx["enrollment"]["id"],
            start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z",
        )
        episode = create_triggered_episode(ctx["enrollment"]["id"])
        dispatched = dispatch_episode(episode["id"])
        assert dispatched["dispatched_clinician_id"] == np2["id"]


class TestImmediateConsistency:
    def test_enrollment_status_visible_after_transition(self, api):
        """PRD section 3.3: "From `IDENTIFIED`, the specialist begins outreach, transitioning the enrollment to `OUTREACH`."

        Design: Corner/consistency_model/immediate_consistency_enrollment_status_visible_after_transition
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        validate_success(api.begin_outreach(enrollment["id"], SPECIALIST))
        fetched = validate_success(api.get_enrollment(enrollment["id"], SPECIALIST))
        assert fetched["status"] == "OUTREACH"

    def test_visit_count_visible_after_creation(self, api):
        """PRD section 3.5: "On success the new visit lands in `SCHEDULED`, the assigned clinician's `active_daily_visit_count` increments by 1, and the visit's `member_id` is denormalized from the enrollment for direct lookup."

        Design: Corner/consistency_model/immediate_consistency_visit_count_visible_after_creation
        """
        ctx = setup_active_enrollment()
        create_scheduled_visit(ctx["enrollment"]["id"])
        clinician = validate_success(api.get_clinician(ctx["np"]["id"], COORDINATOR))
        assert clinician["active_daily_visit_count"] == 1
