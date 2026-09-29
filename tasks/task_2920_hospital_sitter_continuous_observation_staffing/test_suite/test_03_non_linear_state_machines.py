"""
Two state machines that are not simple ladders: an observation order that cycles
back through ACTIVE and can be escalated again, and a sitter assignment whose two
state dimensions advance independently on the same row.
"""

from test_helpers import ObservationApiClient, get_success_data, instant, validate_success
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_row_count,
    rows_where,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    COMPLETION_HANDOFF_COMPLETE,
    DOC_HANDOFF_DRAFTED,
    DOC_HANDOFF_SIGNED,
    DOC_PENDING,
    HANDOFF_DRAFTED,
    EVENT_CLOSED,
    HANDOFF_SIGNED,
    INTERVENTION_BED_ALARM,
    INTERVENTION_DISTRACTION,
    INTERVENTION_FAMILY_PRESENCE,
    INTERVENTION_VERBAL_REDIRECTION,
    KIND_AGGRESSION,
    MODALITY_ONE_TO_ONE_SITTER,
    ORDER_ACTIVE,
    ORDER_ESCALATED,
    POOL_INTERNAL_FLOAT,
    RESOLUTION_CONTINUE_OBSERVATION,
    RISK_FALL,
    WATCH_COMPLETED,
    WATCH_ON_WATCH,
    WATCH_SCHEDULED,
)
from test_helpers.factories import (
    close_event_payload,
    completion_payload,
    escalate_response_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    make_assignment,
    make_handoff,
    make_order,
    make_patient,
    make_safety_event,
    make_staff,
    make_unit,
    order_safety_events,
    read_assignment,
    read_handoff,
    read_order,
    start_watch_at,
)
from test_helpers.test_users import OFFICER_1, OFFICER_2, make_sitter_headers


def _unit_e_order(api: ObservationApiClient) -> dict:
    """UNIT-E: a FALL order whose admission baseline is 1.5 on a 24-hour cadence."""
    unit = make_unit(
        api,
        unit_code="UNIT-E",
        name="Acute Unit E",
        budget_cents=100000,
        video_monitoring_enabled=False,
    )
    patient = make_patient(api, unit["id"], mrn="MRN-5001", full_name="Pat Six", age_years=60)
    staff = make_staff(
        api,
        unit["id"],
        full_name="Sitter Six",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Agitated with fall risk",
    )
    return {"unit": unit, "staff": staff, "order": order}


def _report_escalate_close(
    api: ObservationApiClient, world: dict, narrative: str, actions: list
) -> dict:
    """One full escalation loop: report an AGGRESSION, respond to it, then close it."""
    event = make_safety_event(
        api, world["order"]["id"], KIND_AGGRESSION, world["staff"]["id"], narrative=narrative
    )
    escalated_order = read_order(api, world["order"]["id"])
    get_success_data(
        api.escalate_response(event["id"], escalate_response_payload(actions), OFFICER_1)
    )
    get_success_data(
        api.close_safety_event(
            event["id"], close_event_payload(RESOLUTION_CONTINUE_OBSERVATION), OFFICER_2
        )
    )
    return {"event": event, "order_while_escalated": escalated_order}


class TestOrderCyclesActiveEscalatedActiveTwice:
    """The order status returns to where it started, but the loop is not idempotent."""

    def test_the_order_re_enters_escalated_after_having_returned_to_active(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.8: "An `ELOPEMENT_ATTEMPT` or an `AGGRESSION` report drives the order
        `ACTIVE → ESCALATED`, or `REASSESSMENT_DUE → ESCALATED` when the order was
        already overdue"

        The first report escalates, the first close returns the order to ACTIVE
        because "the last open event is what un-escalates the order", and a second
        report escalates the very same order again.

        Design: Difficulty/non_linear_state_machine/observation_order_cycles_active_escalated_active_twice
        """
        world = _unit_e_order(api)
        assert world["order"]["status"] == ORDER_ACTIVE

        first = _report_escalate_close(
            api, world, "Struck at staff during repositioning", [INTERVENTION_VERBAL_REDIRECTION]
        )
        assert first["order_while_escalated"]["status"] == ORDER_ESCALATED
        after_first_close = read_order(api, world["order"]["id"])
        assert_fields(
            after_first_close,
            label="order after the first close",
            status=ORDER_ACTIVE,
            elopement_risk_score=2.5,
            reassessment_interval_hours=24,
        )

        second = _report_escalate_close(
            api,
            world,
            "Second aggression episode during hygiene care",
            [INTERVENTION_DISTRACTION, INTERVENTION_FAMILY_PRESENCE],
        )
        assert second["order_while_escalated"]["status"] == ORDER_ESCALATED, (
            "the cycle must re-enter ESCALATED from ACTIVE"
        )
        assert read_order(api, world["order"]["id"])["status"] == ORDER_ACTIVE

    def test_each_completed_loop_raises_the_rolling_score_and_tightens_the_cadence(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.3: "Because the event component can only add points, identical order
        data always produces a score at least as high under this reading as under the
        admission baseline, and strictly higher whenever any safety event exists on
        the order."

        Two closed loops leave two windowed AGGRESSION events on the order, so the
        score climbs 1.5 -> 2.5 -> 3.5 and the cadence tightens from 24 to 12 hours
        even though the status ended where it began. Neither loop is a reassessment,
        so `reassessment_count` stays 0.

        Design: Difficulty/non_linear_state_machine/observation_order_cycles_active_escalated_active_twice
        """
        world = _unit_e_order(api)
        assert_fields(world["order"], label="order at creation", elopement_risk_score=1.5)

        _report_escalate_close(
            api, world, "Struck at staff during repositioning", [INTERVENTION_VERBAL_REDIRECTION]
        )
        _report_escalate_close(
            api,
            world,
            "Second aggression episode during hygiene care",
            [INTERVENTION_DISTRACTION, INTERVENTION_FAMILY_PRESENCE],
        )

        order = read_order(api, world["order"]["id"])
        assert_fields(
            order,
            label="order after both loops",
            status=ORDER_ACTIVE,
            elopement_risk_score=3.5,
            reassessment_interval_hours=12,
            reassessment_count=0,
        )
        assert_instant(order["last_reassessed_at"], CLOCK_START, "order.last_reassessed_at")
        assert_instant(
            order["next_reassessment_due_at"],
            instant(CLOCK_START, hours=12),
            "order.next_reassessment_due_at",
        )

        events = order_safety_events(api, world["order"]["id"])
        assert_row_count(events, 2, "safety events on the order")
        assert_row_count(
            rows_where(events, status=EVENT_CLOSED, resolution=RESOLUTION_CONTINUE_OBSERVATION),
            2,
            "CLOSED events resolved CONTINUE_OBSERVATION",
        )


def _unit_f_two_shifts(api: ObservationApiClient) -> dict:
    """
    UNIT-F: one order covered by two back-to-back watches, the outgoing one already
    on watch and already carrying drafted handoff documentation.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-F",
        name="Stepdown Unit F",
        budget_cents=200000,
        video_monitoring_enabled=False,
    )
    patient = make_patient(api, unit["id"], mrn="MRN-6001", full_name="Pat Seven", age_years=60)
    outgoing_staff = make_staff(
        api,
        unit["id"],
        full_name="Sitter Out",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    incoming_staff = make_staff(
        api,
        unit["id"],
        full_name="Sitter In",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Continuous fall precautions across two shifts",
    )
    outgoing = make_assignment(
        api,
        order["id"],
        outgoing_staff["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=16),
        expected_order_version=order["version"],
    )
    incoming = make_assignment(
        api,
        order["id"],
        incoming_staff["id"],
        instant(CLOCK_START, hours=16),
        instant(CLOCK_START, hours=24),
    )
    start_watch_at(api, outgoing["id"], outgoing_staff["id"], instant(CLOCK_START, hours=8))
    handoff = make_handoff(
        api,
        outgoing["id"],
        incoming["id"],
        outgoing_staff["id"],
        behavior_summary="Calm, redirectable, no attempts to rise unassisted",
        interventions_used=[INTERVENTION_VERBAL_REDIRECTION, INTERVENTION_BED_ALARM],
    )
    return {
        "unit": unit,
        "outgoing_staff": outgoing_staff,
        "incoming_staff": incoming_staff,
        "order": order,
        "outgoing": outgoing,
        "incoming": incoming,
        "handoff": handoff,
    }


class TestDocumentationDimensionMovesWhileWatchStatusIsFrozen:
    """One row, two independent state dimensions, advanced by different calls."""

    def test_drafting_and_countersigning_move_only_the_documentation_dimension(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.5: "A sitter assignment carries **two independent state dimensions on the
        same row**, and understanding that they are independent is essential."

        Drafting takes the outgoing watch PENDING -> HANDOFF_DRAFTED and the
        countersign takes it HANDOFF_DRAFTED -> HANDOFF_SIGNED, while `watch_status`
        sits at ON_WATCH across both calls, because neither the draft nor the
        countersign is allowed to disturb the watch dimension.

        Design: Difficulty/non_linear_state_machine/sitter_assignment_documentation_dimension_moves_while_watch_status_frozen
        """
        world = _unit_f_two_shifts(api)
        after_draft = read_assignment(api, world["outgoing"]["id"])
        assert_fields(
            after_draft,
            label="outgoing watch after the draft",
            watch_status=WATCH_ON_WATCH,
            documentation_status=DOC_HANDOFF_DRAFTED,
        )
        assert world["handoff"]["documentation_state"] == HANDOFF_DRAFTED

        validate_success(
            api.countersign_handoff(
                world["handoff"]["id"], make_sitter_headers(world["incoming_staff"]["id"])
            )
        )
        after_countersign = read_assignment(api, world["outgoing"]["id"])
        assert_fields(
            after_countersign,
            label="outgoing watch after the countersign",
            watch_status=WATCH_ON_WATCH,
            documentation_status=DOC_HANDOFF_SIGNED,
        )

        handoff = read_handoff(api, world["handoff"]["id"])
        assert_fields(
            handoff,
            label="handoff record",
            documentation_state=HANDOFF_SIGNED,
            countersigned_by_staff_id=world["incoming_staff"]["id"],
        )
        assert_instant(
            handoff["countersigned_at"],
            instant(CLOCK_START, hours=8),
            "handoff.countersigned_at",
        )

    def test_completing_the_watch_moves_only_the_watch_dimension(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.6: "In every case the waiver applies only if `documentation_status` was
        still `PENDING` at the moment the watch ended; a dimension already sitting in
        `HANDOFF_DRAFTED` or `HANDOFF_SIGNED` is left exactly as it is, and the
        assignment's `version` advances by 1 for the waiver."

        The completion advances `watch_status` to COMPLETED and leaves the signed
        paperwork exactly where the countersign left it, and the successor watch that
        the paperwork points at is not advanced by any of this.

        Design: Difficulty/non_linear_state_machine/sitter_assignment_documentation_dimension_moves_while_watch_status_frozen
        """
        world = _unit_f_two_shifts(api)
        validate_success(
            api.countersign_handoff(
                world["handoff"]["id"], make_sitter_headers(world["incoming_staff"]["id"])
            )
        )
        advance_clock(api, instant(CLOCK_START, hours=16))
        completed = validate_success(
            api.complete_watch(
                world["outgoing"]["id"],
                completion_payload(COMPLETION_HANDOFF_COMPLETE),
                make_sitter_headers(world["outgoing_staff"]["id"]),
            )
        )
        assert_fields(
            completed,
            label="completed outgoing watch",
            watch_status=WATCH_COMPLETED,
            documentation_status=DOC_HANDOFF_SIGNED,
            completion_reason=COMPLETION_HANDOFF_COMPLETE,
            final_cost_cents=16000,
            watch_segment_count=1,
            watched_minutes=480,
        )
        assert read_order(api, world["order"]["id"])["coverage_gap_flag"] is False, (
            "HANDOFF_COMPLETE is not the branch that flags an uncovered gap"
        )

        incoming = read_assignment(api, world["incoming"]["id"])
        assert_fields(
            incoming,
            label="incoming watch",
            watch_status=WATCH_SCHEDULED,
            documentation_status=DOC_PENDING,
        )
