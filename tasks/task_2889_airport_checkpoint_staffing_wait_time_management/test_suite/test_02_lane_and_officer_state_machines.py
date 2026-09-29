"""Lane, officer, plan and referral state machines.

Covers PRD sections 2.9, 3.1, 3.6, 3.7, 3.4 and 3.9: the initial states, the
edges that are legal, the edges that must be refused once a row is terminal, and
the conserved floor-space counters that a refused edge must leave alone.
"""

from test_helpers import (
    ADMIN_HEADERS,
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_instant,
    assert_lane_snapshot,
    assert_officer_ledger,
    assert_position_ledger,
    assert_posture,
    assert_referral_counters,
    assert_secondary_slots,
    factories as f,
    make_supervisory_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CLOCK_0800, Scenario


class TestLaneLifecycle:
    """PRD 3.1, 3.6 and 2.9 - the lane axis and the floor-space ledger."""

    def test_new_lane_is_closed_and_out_of_service_until_every_type_is_present(
        self, base: Scenario
    ):
        """equipment_state is derived, so a partly equipped lane is still out of service.

        Design: Corner/state_machines/lane_starts_closed_with_equipment_state_out_of_service
        """
        lane = base.create_lane(position_index=1)
        assert_lane_snapshot(lane, "CLOSED", "OUT_OF_SERVICE", paused_reason_code=None)
        assert lane["opened_at_utc"] is None

        wtmd = base.install_unit(lane["id"], "WTMD")
        assert wtmd["state"] == "SERVICEABLE"
        assert wtmd["last_state_note"] is None
        partial = validate_success(base.api.get_lane(lane["id"], MANAGER_HEADERS))
        assert_lane_snapshot(partial, "CLOSED", "OUT_OF_SERVICE")

        base.install_unit(lane["id"], "AT_XRAY")
        base.install_unit(lane["id"], "ADVANCED_IMAGING")
        equipped = validate_success(base.api.get_lane(lane["id"], MANAGER_HEADERS))
        assert_lane_snapshot(equipped, "CLOSED", "SERVICEABLE", paused_reason_code=None)
        assert equipped["opened_at_utc"] is None

        checkpoint = validate_success(
            base.api.get_checkpoint(base.checkpoint_id, MANAGER_HEADERS)
        )
        assert_position_ledger(checkpoint, [])

    def test_second_open_is_refused_and_leaves_the_position_ledger_alone(
        self, closed_lane_floor: Scenario
    ):
        """Opening is not idempotent: a repeat would double-charge the floor.

        Design: Corner/state_machines/second_open_on_an_already_open_lane_returns_invalid_state_transition
        """
        opened = closed_lane_floor.open_lane()
        assert_lane_snapshot(opened, "OPEN", "SERVICEABLE", paused_reason_code=None)
        assert_instant(opened["opened_at_utc"], CLOCK_0800, "opened_at_utc")

        after_open = validate_success(
            closed_lane_floor.api.get_checkpoint(
                closed_lane_floor.checkpoint_id, MANAGER_HEADERS
            )
        )
        assert_position_ledger(after_open, [1])

        validate_error(
            closed_lane_floor.api.open_lane(closed_lane_floor.lane_id, MANAGER_HEADERS),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        after_repeat = validate_success(
            closed_lane_floor.api.get_checkpoint(
                closed_lane_floor.checkpoint_id, MANAGER_HEADERS
            )
        )
        assert_position_ledger(after_repeat, [1])

    def test_decommissioned_lane_is_terminal_and_releases_its_position_index(
        self, closed_lane_floor: Scenario
    ):
        """A decommissioned lane accepts no edge and frees its index for reuse.

        Design: Corner/state_machines/lane_decommissioned_is_terminal_and_frees_its_position_index
        """
        decommissioned = validate_success(
            closed_lane_floor.api.stand_down_lane(
                closed_lane_floor.lane_id,
                f.stand_down_payload("DECOMMISSIONED"),
                MANAGER_HEADERS,
            )
        )
        assert decommissioned["lane_state"] == "DECOMMISSIONED"

        validate_error(
            closed_lane_floor.api.open_lane(closed_lane_floor.lane_id, MANAGER_HEADERS),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        reused = closed_lane_floor.create_lane(
            position_index=1, lane_type="EXPEDITED", secondary_positions=0
        )
        assert reused["position_index"] == 1
        assert reused["id"] != closed_lane_floor.lane_id

        checkpoint = validate_success(
            closed_lane_floor.api.get_checkpoint(
                closed_lane_floor.checkpoint_id, MANAGER_HEADERS
            )
        )
        assert checkpoint["total_lane_positions"] == 6
        assert checkpoint["available_lane_positions"] == 6


class TestOfficerDutyAxis:
    """PRD 3.7 - the caller-driven duty edges and the terminal state."""

    def test_duty_status_round_trip_bumps_version_and_leaves_the_ledger_alone(
        self, scenario: Scenario
    ):
        """Each accepted duty edge increments version; neither moves committed minutes.

        Design: Corner/state_machines/officer_duty_status_valid_transition_off_duty_to_on_duty
        """
        scenario.set_clock(CLOCK_0800)
        officer = scenario.create_officer(badge_number="B-1001")
        assert officer["version"] == 1

        on_duty = validate_success(
            scenario.api.set_officer_duty_status(
                officer["id"], f.duty_status_payload("ON_DUTY"), MANAGER_HEADERS
            )
        )
        assert on_duty["duty_status"] == "ON_DUTY"
        assert on_duty["version"] == 2
        assert_officer_ledger(on_duty, committed_duty_minutes=0)

        off_duty = validate_success(
            scenario.api.set_officer_duty_status(
                officer["id"], f.duty_status_payload("OFF_DUTY"), MANAGER_HEADERS
            )
        )
        assert off_duty["duty_status"] == "OFF_DUTY"
        assert off_duty["version"] == 3
        assert_officer_ledger(off_duty, committed_duty_minutes=0)

    def test_separated_officer_rejects_every_further_duty_edge(self, scenario: Scenario):
        """SEPARATED has no outbound edge, and re-asserting it is an error too.

        Design: Corner/state_machines/officer_separated_is_terminal_and_rejects_further_duty_status
        """
        scenario.set_clock(CLOCK_0800)
        officer = scenario.create_officer(badge_number="B-1001")
        separated = validate_success(
            scenario.api.set_officer_duty_status(
                officer["id"], f.duty_status_payload("SEPARATED"), MANAGER_HEADERS
            )
        )
        assert separated["duty_status"] == "SEPARATED"
        version_after_separation = separated["version"]

        validate_error(
            scenario.api.set_officer_duty_status(
                officer["id"], f.duty_status_payload("ON_DUTY"), MANAGER_HEADERS
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )
        validate_error(
            scenario.api.set_officer_duty_status(
                officer["id"], f.duty_status_payload("SEPARATED"), MANAGER_HEADERS
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        unchanged = validate_success(scenario.api.get_officer(officer["id"], ADMIN_HEADERS))
        assert unchanged["duty_status"] == "SEPARATED"
        assert unchanged["version"] == version_after_separation


class TestStaffingPlanTerminalState:
    """PRD 3.4 - CLOSED settles the labour and then refuses everything."""

    def test_closed_plan_refuses_every_lifecycle_action_but_stays_readable(
        self, activated_plan: Scenario
    ):
        """Closing cancels the scheduled work; the priced record survives untouched.

        Design: Corner/state_machines/staffing_plan_closed_is_terminal_and_rejects_every_lifecycle_action
        """
        closed = activated_plan.close_plan()
        assert closed["state"] == "CLOSED"
        assert_instant(closed["closed_at_utc"], CLOCK_0800, "closed_at_utc")

        validate_error(
            activated_plan.api.staffing_plan_lifecycle(
                activated_plan.plan_id, f.plan_lifecycle_payload("ACTIVATE"), MANAGER_HEADERS
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )
        validate_error(
            activated_plan.api.revise_staffing_plan(
                activated_plan.plan_id, PLANNER_HEADERS
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )
        validate_error(
            activated_plan.api.submit_staffing_plan(
                activated_plan.plan_id, PLANNER_HEADERS
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        still_readable = validate_success(
            activated_plan.api.get_staffing_plan(activated_plan.plan_id, MANAGER_HEADERS)
        )
        assert still_readable["state"] == "CLOSED"
        assert still_readable["total_cost_cents"] == 3180
        assert still_readable["revision_number"] == 1

        settled = validate_success(
            activated_plan.api.get_lane_assignment(
                activated_plan.assignment_id, MANAGER_HEADERS
            )
        )
        assert settled["assignment_state"] == "CANCELLED"


class TestBreakAxis:
    """PRD 3.7 - the break axis becomes due by elapsed position time, not by asking."""

    def test_break_start_before_the_hour_elapses_is_refused_then_allowed_at_the_hour(
        self, checked_in_assignment: Scenario
    ):
        """One minute short of the hour the break is not due; at the hour it is.

        Design: Corner/state_machines/break_start_before_the_on_position_run_elapses_returns_break_not_due
        """
        assert_instant(
            checked_in_assignment.assignment["break_baseline_utc"],
            CLOCK_0800,
            "break_baseline_utc",
        )
        assert checked_in_assignment.assignment["break_state"] == "NOT_DUE"

        checked_in_assignment.set_clock("2026-09-10T08:59:00Z")
        validate_error(
            checked_in_assignment.api.assignment_break(
                checked_in_assignment.assignment_id,
                f.break_action_payload("START"),
                checked_in_assignment.officer_headers,
            ),
            ApiErrorId.BREAK_NOT_DUE,
            409,
        )
        not_yet = validate_success(
            checked_in_assignment.api.get_lane_assignment(
                checked_in_assignment.assignment_id, MANAGER_HEADERS
            )
        )
        assert not_yet["break_state"] == "NOT_DUE"
        assert not_yet["assignment_state"] == "CHECKED_IN"

        checked_in_assignment.set_clock("2026-09-10T09:00:00Z")
        on_break = validate_success(
            checked_in_assignment.api.assignment_break(
                checked_in_assignment.assignment_id,
                f.break_action_payload("START"),
                checked_in_assignment.officer_headers,
            )
        )
        assert on_break["break_state"] == "ON_BREAK"
        assert on_break["assignment_state"] == "CHECKED_IN"
        assert_instant(
            on_break["break_started_at_utc"], "2026-09-10T09:00:00Z", "break_started_at_utc"
        )

        officer = validate_success(
            checked_in_assignment.api.get_officer(
                checked_in_assignment.officer_id, MANAGER_HEADERS
            )
        )
        assert officer["duty_status"] == "ON_BREAK"


class TestReferralTerminalState:
    """PRD 3.9 - a withdrawn referral releases its slot and accepts no more edges."""

    def test_begin_after_withdrawal_is_an_illegal_transition(
        self, supervised_floor: Scenario
    ):
        """WITHDRAWN is terminal, and it moves no counter but the slot count.

        Design: Corner/state_machines/referral_begin_from_a_resolved_state_is_an_invalid_transition
        """
        referral = supervised_floor.raise_referral()
        assert referral["state"] == "RAISED"
        assert referral["secondary_slot_held"] is True
        held = validate_success(
            supervised_floor.api.get_checkpoint(
                supervised_floor.checkpoint_id, MANAGER_HEADERS
            )
        )
        assert_secondary_slots(held, 1)

        # Segregation of duties: the officer who resolves must not be the one who
        # raised the referral, so a second SUPERVISOR-certified officer withdraws it.
        other_supervisor = supervised_floor.create_officer(
            badge_number="B-2003",
            full_name="Nia Sup",
            certifications=["STANDARD_LANE", "SUPERVISOR"],
        )
        other_headers = make_supervisory_officer_headers(other_supervisor["id"])

        withdrawn = validate_success(
            supervised_floor.api.resolve_screening_referral(
                referral["id"], f.referral_resolution_payload("WITHDRAWN"), other_headers
            )
        )
        assert withdrawn["state"] == "WITHDRAWN"
        assert withdrawn["secondary_slot_held"] is False
        assert_instant(withdrawn["resolved_at_utc"], CLOCK_0800, "resolved_at_utc")

        validate_error(
            supervised_floor.api.begin_screening_referral(
                referral["id"],
                f.referral_begin_payload(other_supervisor["id"]),
                other_headers,
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )
        validate_error(
            supervised_floor.api.resolve_screening_referral(
                referral["id"], f.referral_resolution_payload("WITHDRAWN"), other_headers
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        released = validate_success(
            supervised_floor.api.get_checkpoint(
                supervised_floor.checkpoint_id, MANAGER_HEADERS
            )
        )
        assert_secondary_slots(released, 0)
        assert_referral_counters(
            released,
            cleared_referral_count=0,
            leo_referral_count=0,
            denied_entry_count=0,
            diverted_pax_total=0,
        )


class TestCheckpointSuspensionCascade:
    """PRD 2.10 and 3.6 - the flag overrides the counters and pushes down the tree."""

    def test_suspension_pauses_open_lanes_and_flips_their_checked_in_crew(
        self, checked_in_assignment: Scenario
    ):
        """Only the OPEN lane is pushed; the closed one and the break axis stand still.

        Design: Corner/state_machines/checkpoint_suspension_cascades_down_to_open_lanes_and_assignments
        """
        second_lane = checked_in_assignment.create_lane(
            position_index=2, lane_type="EXPEDITED", secondary_positions=0
        )

        suspended = validate_success(
            checked_in_assignment.api.update_checkpoint(
                checked_in_assignment.checkpoint_id,
                f.checkpoint_patch_payload(suspended=True),
                MANAGER_HEADERS,
            )
        )
        assert suspended["suspended"] is True
        assert_posture(suspended, "SUSPENDED")
        assert_position_ledger(suspended, [])

        paused = validate_success(
            checked_in_assignment.api.get_lane(
                checked_in_assignment.lane_id, MANAGER_HEADERS
            )
        )
        assert_lane_snapshot(paused, "PAUSED", "SERVICEABLE", paused_reason_code="SECURITY_INCIDENT")

        untouched = validate_success(
            checked_in_assignment.api.get_lane(second_lane["id"], MANAGER_HEADERS)
        )
        assert_lane_snapshot(untouched, "CLOSED", "OUT_OF_SERVICE", paused_reason_code=None)

        assignment = validate_success(
            checked_in_assignment.api.get_lane_assignment(
                checked_in_assignment.assignment_id, MANAGER_HEADERS
            )
        )
        assert assignment["assignment_state"] == "REASSIGN_PENDING"
        assert assignment["break_state"] == "NOT_DUE"
        assert assignment["break_minutes_taken"] == 0

        officer = validate_success(
            checked_in_assignment.api.get_officer(
                checked_in_assignment.officer_id, MANAGER_HEADERS
            )
        )
        assert_officer_ledger(officer, committed_duty_minutes=30, duty_status="ON_DUTY")


class TestEscalationTicketBranches:
    """PRD 3.8 - the two resolution branches move different checkpoint counters."""

    def test_lane_opened_resolution_leaves_the_diversion_counter_alone(
        self, supervised_floor: Scenario
    ):
        """The second consecutive breach raises the ticket; LANE_OPENED diverts nobody.

        Design: Corner/state_machines/escalation_resolution_branches_move_different_checkpoint_counters
        """
        first = supervised_floor.post_observation(
            headers=supervised_floor.supervisor_headers,
            lane_type="STANDARD",
            sampled_wait_seconds=1200,
        )
        assert first["published_wait_minutes_snapshot"] == 20
        assert first["breached_threshold"] is True
        after_first = validate_paginated(
            supervised_floor.api.list_escalation_tickets(
                MANAGER_HEADERS, {"checkpoint_id": supervised_floor.checkpoint_id}
            )
        )[0]
        assert after_first == [], "a single breaching publication raises nothing"

        supervised_floor.post_observation(
            headers=supervised_floor.supervisor_headers,
            lane_type="STANDARD",
            sampled_wait_seconds=1200,
        )
        tickets, _ = validate_paginated(
            supervised_floor.api.list_escalation_tickets(
                MANAGER_HEADERS, {"checkpoint_id": supervised_floor.checkpoint_id}
            )
        )
        assert len(tickets) == 1
        ticket = tickets[0]
        assert ticket["state"] == "RAISED"
        assert ticket["trigger_reason"] == "WAIT_THRESHOLD_BREACH"
        assert ticket["lane_type_scope"] == "STANDARD"
        assert ticket["published_wait_minutes_at_raise"] == 20

        acknowledged = validate_success(
            supervised_floor.api.acknowledge_escalation_ticket(
                ticket["id"], supervised_floor.supervisor_headers
            )
        )
        assert acknowledged["state"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_by_officer_id"] == supervised_floor.supervisor_id
        still_open = validate_success(
            supervised_floor.api.get_checkpoint(
                supervised_floor.checkpoint_id, MANAGER_HEADERS
            )
        )
        assert_posture(still_open, "ELEVATED")

        resolved = validate_success(
            supervised_floor.api.resolve_escalation_ticket(
                ticket["id"],
                f.ticket_resolution_payload(
                    "LANE_OPENED", resolved_lane_id=supervised_floor.lane_id
                ),
                supervised_floor.supervisor_headers,
            )
        )
        assert resolved["state"] == "RESOLVED_LANE_OPENED"
        assert resolved["resolved_lane_id"] == supervised_floor.lane_id
        assert resolved["diverted_pax_count"] is None
        assert_instant(resolved["resolved_at_utc"], CLOCK_0800, "resolved_at_utc")

        checkpoint = validate_success(
            supervised_floor.api.get_checkpoint(
                supervised_floor.checkpoint_id, MANAGER_HEADERS
            )
        )
        assert_posture(checkpoint, "NORMAL")
        assert_referral_counters(checkpoint, diverted_pax_total=0)

    def test_a_non_breaching_publication_expires_the_raised_ticket(
        self, raised_ticket: Scenario
    ):
        """Expiry is automatic and reaches only a RAISED ticket.

        Design: Corner/state_machines/raised_ticket_auto_expires_when_the_next_publication_drops_below_threshold
        """
        ticket = raised_ticket.extras["ticket"]
        assert ticket["state"] == "RAISED"

        raised_ticket.set_clock("2026-09-10T08:30:00Z")
        calm = raised_ticket.post_observation(
            headers=raised_ticket.supervisor_headers,
            lane_type="STANDARD",
            sampled_wait_seconds=300,
        )
        assert calm["published_wait_minutes_snapshot"] == 5
        assert calm["breached_threshold"] is False

        expired = validate_success(
            raised_ticket.api.get_escalation_ticket(ticket["id"], MANAGER_HEADERS)
        )
        assert expired["state"] == "EXPIRED"
        assert_instant(expired["resolved_at_utc"], "2026-09-10T08:30:00Z", "resolved_at_utc")

        tickets, _ = validate_paginated(
            raised_ticket.api.list_escalation_tickets(
                MANAGER_HEADERS, {"checkpoint_id": raised_ticket.checkpoint_id}
            )
        )
        assert len(tickets) == 1, "expiry must not create a second ticket"

        checkpoint = validate_success(
            raised_ticket.api.get_checkpoint(raised_ticket.checkpoint_id, MANAGER_HEADERS)
        )
        assert checkpoint["consecutive_breach_count_standard"] == 0
        assert_posture(checkpoint, "NORMAL")
