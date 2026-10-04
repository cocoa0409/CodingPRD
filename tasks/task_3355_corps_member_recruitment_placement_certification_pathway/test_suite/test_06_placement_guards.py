"""Guards that read another entity's state, and the two interval-arithmetic rules."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    create_support_record_payload,
    err,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    COACH,
    COMPLETER,
    PLACEMENT_COORDINATOR,
    activate_district,
    create_matched_placement,
    milestones_by_type,
    record_practice_hours,
    setup_member_scenario,
    setup_two_members,
    start_milestone,
    suspend_district,
)


class TestConfirmRequiresActiveDistrict:
    """Placement confirmation reads the district agreement's state."""

    def test_confirm_is_refused_while_the_district_is_suspended(self, api):
        """PRD §3.7: "The district owning the placement's school must have an `agreement_status` of `ACTIVE`, or the request fails with `ERR_DISTRICT_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/placement_confirm_requires_active_district
        """
        scenario = setup_member_scenario()
        placement = create_matched_placement(scenario["member_id"], scenario["school"]["id"])
        suspend_district(scenario["district"]["id"])

        response = api.confirm_placement(placement["id"], PLACEMENT_COORDINATOR)
        validate_error(response, err(ApiErrorId.ERR_DISTRICT_NOT_ACTIVE), 409)

        after = validate_success(
            api.list_member_placements(scenario["member_id"], PLACEMENT_COORDINATOR)
        )[0]
        assert after["status"] == "MATCHED", (
            "the refused confirmation must leave the placement untouched"
        )
        assert after.get("confirmed_at") is None

    def test_identical_confirm_succeeds_once_the_district_is_active_again(self, api):
        """PRD §3.6: "A suspended agreement returns to `ACTIVE` only when the district's invoice total has come back within its budget — that is, when `invoice_amount_cents` is at or below `fee_budget_cents`."
        PRD §3.7: "A successful confirmation stamps `confirmed_at` with the current logical clock and moves the placement to `CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/placement_confirm_requires_active_district
        """
        scenario = setup_member_scenario()
        placement = create_matched_placement(scenario["member_id"], scenario["school"]["id"])
        district_id = scenario["district"]["id"]

        suspend_district(district_id)
        validate_error(
            api.confirm_placement(placement["id"], PLACEMENT_COORDINATOR),
            err(ApiErrorId.ERR_DISTRICT_NOT_ACTIVE),
            409,
        )

        reactivated = activate_district(district_id)
        assert reactivated["agreement_status"] == "ACTIVE"

        confirmed = validate_success(
            api.confirm_placement(placement["id"], PLACEMENT_COORDINATOR)
        )
        assert confirmed["status"] == "CONFIRMED", (
            "the gate reads the district's state, not any field of the placement"
        )
        assert confirmed.get("confirmed_at") is not None


class TestMilestoneCompleteRequiresInstituteState:
    """Milestone completion reads the owning member's institute state."""

    def test_complete_is_refused_while_the_member_is_enrolled(self, api):
        """PRD §3.5: "From `IN_PROGRESS`, completion requires only that the member's `institute_status` be `IN_TRAINING` or `COMPLETED`."
        PRD §2.10: "The sixth tier applies the state gates: a transition requested from a state that does not permit it, or with a transition precondition unmet, is `ERR_INVALID_STATE` (HTTP 409) on every transition operation in this document"

        Design: Difficulty/cross_entity_state_dependency/milestone_complete_requires_institute_state
        """
        scenario = setup_member_scenario()
        milestone_id = milestones_by_type(scenario["member_id"])["COURSEWORK"]["id"]
        start_milestone(milestone_id)

        assert scenario["member"]["institute_status"] == "ENROLLED"
        response = api.complete_certification_milestone(milestone_id, COMPLETER)
        validate_error(response, err(ApiErrorId.ERR_INVALID_STATE), 409)

        after = validate_success(
            api.get_certification_milestone(milestone_id, COMPLETER)
        )
        assert after["progress_status"] == "IN_PROGRESS"

    def test_identical_complete_succeeds_once_the_member_is_in_training(self, api):
        """PRD §3.4: "The first such record moves the member's `institute_status` from `ENROLLED` to `IN_TRAINING`"
        PRD §3.5: "Both completion edges stamp `completed_at` with the current logical clock and record the officer in `completed_by_user_id`"

        Design: Difficulty/cross_entity_state_dependency/milestone_complete_requires_institute_state
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        milestone_id = milestones_by_type(member_id)["COURSEWORK"]["id"]
        start_milestone(milestone_id)

        trained = record_practice_hours(member_id, 240)
        assert trained["institute_status"] == "IN_TRAINING"

        completed = validate_success(
            api.complete_certification_milestone(milestone_id, COMPLETER)
        )
        assert completed["progress_status"] == "COMPLETED"
        assert completed["completed_by_user_id"] == COMPLETER["X-User-ID"]


class TestCoachHalfOpenIntervals:
    """Coaching occupancy is half-open, so adjacency is permitted."""

    def test_back_to_back_coaching_sessions_both_created(self, api):
        """PRD §3.9: "Because the intervals are half-open, a session that begins at the exact instant another session ends does not conflict with it, and back-to-back coaching is therefore permitted."

        Design: Difficulty/resource_temporal_overlap/coach_half_open_adjacency_allowed
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]

        first = validate_success(
            api.create_support_record(
                create_support_record_payload(
                    member_id,
                    session_start="2026-09-10T14:00:00Z",
                    session_end="2026-09-10T15:00:00Z",
                ),
                COACH,
            ),
            201,
        )
        second = validate_success(
            api.create_support_record(
                create_support_record_payload(
                    member_id,
                    session_start="2026-09-10T15:00:00Z",
                    session_end="2026-09-10T16:00:00Z",
                    notes="back-to-back slot",
                ),
                COACH,
            ),
            201,
        )
        assert first["session_end"] == second["session_start"]
        assert_same_instant(
            second["session_start"], "2026-09-10T15:00:00Z", "session_start"
        )

    def test_overlapping_coaching_session_is_refused(self, api):
        """PRD §3.9: "No existing `COACHING` record for the same `coach_user_id` may hold a half-open interval running from its `session_start` up to but not including its `session_end` that intersects the new record's half-open interval; a conflicting booking is refused with `ERR_COACH_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/coach_half_open_adjacency_allowed
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        validate_success(
            api.create_support_record(
                create_support_record_payload(
                    member_id,
                    session_start="2026-09-10T14:00:00Z",
                    session_end="2026-09-10T15:00:00Z",
                ),
                COACH,
            ),
            201,
        )

        response = api.create_support_record(
            create_support_record_payload(
                member_id,
                session_start="2026-09-10T14:59:00Z",
                session_end="2026-09-10T15:30:00Z",
                notes="one minute early",
            ),
            COACH,
        )
        validate_error(response, err(ApiErrorId.ERR_COACH_SCHEDULE_OVERLAP), 409)

    def test_evaluations_do_not_participate_in_the_occupancy_check(self, api):
        """PRD §3.9: "The rule is deliberately scoped to `COACHING` records: evaluations do not participate in the coach's occupancy check."

        Design: Difficulty/resource_temporal_overlap/coach_half_open_adjacency_allowed
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        validate_success(
            api.create_support_record(
                create_support_record_payload(
                    member_id,
                    record_type="COACHING",
                    session_start="2026-09-10T14:00:00Z",
                    session_end="2026-09-10T15:00:00Z",
                ),
                COACH,
            ),
            201,
        )

        overlapping = validate_success(
            api.create_support_record(
                create_support_record_payload(
                    member_id,
                    record_type="EVALUATION",
                    session_start="2026-09-10T14:30:00Z",
                    session_end="2026-09-10T15:30:00Z",
                    effectiveness_score=2,
                    notes="formal evaluation inside the coaching hour",
                ),
                COACH,
            ),
            201,
        )
        assert overlapping["record_type"] == "EVALUATION"


class TestSchoolCapacityClosedIntervals:
    """School capacity uses closed term windows and an aggregate counter."""

    def test_placement_starting_on_anothers_end_date_is_refused(self, api):
        """PRD §3.7: "The overlap test uses closed intervals at both ends, so two windows that share exactly one endpoint — one ending on the day the other begins — count as overlapping, and a school's capacity is consumed for that shared day by both placements."
        PRD §3.7: "a confirmation that would reach the capacity is refused with `ERR_SCHOOL_CAPACITY_EXCEEDED` (HTTP 409)"

        Design: Difficulty/resource_temporal_overlap/school_capacity_closed_interval_adjacency_rejected
        """
        scenario = setup_two_members()
        school_id = scenario["school"]["id"]

        first = create_matched_placement(scenario["member1_id"], school_id)
        validate_success(api.confirm_placement(first["id"], PLACEMENT_COORDINATOR))

        adjacent = create_matched_placement(
            scenario["member2_id"],
            school_id,
            term_start_date="2027-05-31T00:00:00Z",
            term_end_date="2028-05-31T00:00:00Z",
        )
        response = api.confirm_placement(adjacent["id"], PLACEMENT_COORDINATOR)
        validate_error(response, err(ApiErrorId.ERR_SCHOOL_CAPACITY_EXCEEDED), 409)

        still = validate_success(
            api.get_partner_school(school_id, PLACEMENT_COORDINATOR)
        )
        assert still["classroom_capacity"] == 1

    def test_placement_starting_the_next_day_is_admitted(self, api):
        """PRD §3.7: "The number of placements already at the target school whose status is `CONFIRMED` or `ACTIVE` and whose closed term window overlaps the new placement's closed window must be strictly less than the school's `classroom_capacity`"

        Design: Difficulty/resource_temporal_overlap/school_capacity_closed_interval_adjacency_rejected
        """
        scenario = setup_two_members()
        school_id = scenario["school"]["id"]

        first = create_matched_placement(scenario["member1_id"], school_id)
        validate_success(api.confirm_placement(first["id"], PLACEMENT_COORDINATOR))

        later = create_matched_placement(
            scenario["member2_id"],
            school_id,
            term_start_date="2027-06-01T00:00:00Z",
            term_end_date="2028-05-31T00:00:00Z",
        )
        confirmed = validate_success(
            api.confirm_placement(later["id"], PLACEMENT_COORDINATOR)
        )
        assert confirmed["status"] == "CONFIRMED", (
            "one day later there is no shared endpoint, so the window does not overlap"
        )
