"""Emergency response: the evacuation edge with its two guarded preconditions and
its two cascades, the containment that reopens the reservoir without restoring the
schedule, the closure that makes the event terminal, the remediation sign-off that
an active response blocks, and the advance endpoint whose inputs depend on the
`to_status` it is given."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_EVACUATION_RADIUS_INVALID,
    ERR_INVALID_EMERGENCY_STATE,
    ERR_REMEDIATION_ESCALATED,
)
from test_helpers.assertions import (
    assert_error_envelope,
    assert_field_derived_block,
    assert_instant_equals,
    assert_ledger_entry,
    assert_money,
    assert_ok,
    assert_utilization,
    assert_volume,
)
from test_helpers.constants import (
    BAND_MID,
    CLOCK_EPOCH,
    DIRECTION_INJECTION,
    EMERGENCY_CLOSED,
    EMERGENCY_CONTAINED,
    EMERGENCY_EVACUATION_ORDERED,
    EMERGENCY_RESPONDING,
    EVENT_TYPE_LEAK,
    INTEGRITY_MIT_FAILED,
    INTEGRITY_REMEDIATED,
    LEDGER_CURTAILMENT_CREDIT,
    NOMINATION_CURTAILED,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    REMEDIATION_COMPLETED,
    REMEDIATION_ESCALATED,
    REMEDIATION_OPEN,
    RUN_CANCELLED,
    SEVERITY_CRITICAL,
    SEVERITY_MINOR,
    SEVERITY_SERIOUS,
    SHUT_IN_REASON_MIT_FAILURE,
    UNIT_OUT_OF_SERVICE,
)
from test_helpers.fixtures import (
    advance_emergency,
    book_run,
    confirmed_nomination,
    create_field,
    create_unit,
    create_well,
    fail_mit_on_well,
    open_emergency,
    read_event,
    read_field,
    read_nomination,
    read_contract,
    read_program,
    read_unit,
    read_well,
    remediate_well,
)
from test_helpers.test_users import (
    ENGINEER_B_ID,
    FIELD_OPERATOR,
    INTEGRITY_ENGINEER_B,
    SCHEDULING_COORDINATOR,
)


def _advance(api, event_id, to_status, responder_notes=None, evacuation_radius_m=None):
    """Raw advance so the caller can assert on a refusal as well as a success."""
    return api.advance_emergency_event(
        event_id,
        F.advance_payload(to_status, responder_notes, evacuation_radius_m),
        FIELD_OPERATOR,
    )


def _complete_remediation(api, program_id, notes="Casing repair verified"):
    """Raw completion by the independent engineer, eng-b."""
    return api.complete_remediation_program(
        program_id, F.remediation_completion_payload(notes), INTEGRITY_ENGINEER_B
    )


class TestEvacuationOrderCascades:
    """One advance fans out across three unrelated aggregates."""

    def test_the_order_escalates_remediation_and_strands_the_station(self, api):
        """Ordering an evacuation turns the open remediation program terminally
        ESCALATED while leaving the wellbore MIT_FAILED, takes the compressor unit
        OUT_OF_SERVICE and cancels its scheduled run without burning a single
        dekatherm, so the reservoir still holds its opening 250,000 Dth even though the
        cancelled run already carried the utilization band it was stamped with at
        booking.

        PRD §3.8: "When it succeeds, the radius is stored and two cascades fire. Every
        remediation program on that reservoir's wellbores that still stands `OPEN`
        becomes `ESCALATED` and is thereby permanently unclosable, with the affected
        wellbores left at `integrity_state` `MIT_FAILED`. And every compressor unit on
        the reservoir becomes `OUT_OF_SERVICE`, with each of its `SCHEDULED` runs moving
        to `CANCELLED` without burning fuel."

        Design: Corner/state_machines/evacuation_order_escalates_remediation_and_strands_the_compressor_station
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-1")
        second_well = create_well(api, field["id"], well_name="MINI-2")
        unit = create_unit(api, field["id"], unit_code="U-1", rated_horsepower=6000, derate_factor=0.00)
        run = book_run(
            api, unit["id"],
            window_start_at="2026-08-10T00:00:00Z", window_end_at="2026-08-10T08:00:00Z",
            allocated_horsepower=3000,
        )
        failure = fail_mit_on_well(api, second_well["id"])
        event = open_emergency(api, field["id"], detected_at="2026-08-02T06:00:00Z")
        advance_emergency(
            api, event["id"], EMERGENCY_RESPONDING,
            responder_notes="Crew dispatched to the wellhead",
        )

        ordered = assert_ok(
            _advance(api, event["id"], EMERGENCY_EVACUATION_ORDERED, evacuation_radius_m=1500)
        )
        assert ordered["status"] == EMERGENCY_EVACUATION_ORDERED, (
            f"status: expected EVACUATION_ORDERED, got {ordered['status']}"
        )
        assert ordered["evacuation_radius_m"] == 1500, (
            f"evacuation_radius_m: expected 1500, got {ordered['evacuation_radius_m']}"
        )
        assert ordered["contained_at"] is None and ordered["closed_at"] is None
        assert ordered["responder_notes"] == "Crew dispatched to the wellhead", (
            "An advance that supplies no notes leaves the latest narrative in place, got "
            f"{ordered['responder_notes']!r}"
        )

        program = read_program(api, failure.program["id"])
        assert program["status"] == REMEDIATION_ESCALATED, (
            f"An OPEN program must escalate, got {program['status']}"
        )
        assert program["completed_at"] is None and program["completed_by_user_id"] is None
        stranded_well = read_well(api, second_well["id"])
        assert stranded_well["integrity_state"] == INTEGRITY_MIT_FAILED, (
            f"The escalation leaves the wellbore MIT_FAILED, got {stranded_well['integrity_state']}"
        )
        assert stranded_well["shut_in_reason"] == SHUT_IN_REASON_MIT_FAILURE

        stranded_unit = read_unit(api, unit["id"])
        assert stranded_unit["status"] == UNIT_OUT_OF_SERVICE, (
            f"Every unit on the reservoir goes out of service, got {stranded_unit['status']}"
        )
        assert stranded_unit["scheduled_run_count"] == 0, (
            f"scheduled_run_count: expected 0, got {stranded_unit['scheduled_run_count']}"
        )
        assert_money(stranded_unit["lifetime_fuel_dth"], 0.00, "lifetime_fuel_dth")

        rows, meta = validate_paginated(
            api.list_unit_runs(unit["id"], FIELD_OPERATOR, {"status": RUN_CANCELLED, "limit": 100})
        )
        assert meta["total_count"] == 1, (
            f"The one scheduled run must be the one cancelled row, got {meta['total_count']}"
        )
        cancelled = rows[0]
        assert cancelled["id"] == run["id"]
        assert cancelled["status"] == RUN_CANCELLED
        assert cancelled["fuel_consumed_dth"] is None, (
            "A cancelled run burns no fuel, so its consumption stays null, got "
            f"{cancelled['fuel_consumed_dth']}"
        )
        assert_utilization(cancelled["utilization_ratio"], 0.500000)
        assert cancelled["utilization_band"] == BAND_MID, (
            f"The band stamped at booking survives cancellation, got {cancelled['utilization_band']}"
        )

        frozen = read_field(api, field["id"])
        assert_field_derived_block(
            frozen, working_gas=250000.000, inventory_pct=50.00, posture=POSTURE_FROZEN
        )
        assert_volume(frozen["fuel_gas_used_dth"], 0.000, "fuel_gas_used_dth")


class TestEvacuationOrderPreconditions:
    """One error code guards two unrelated preconditions on the same edge."""

    def test_severity_and_the_radius_band_answer_with_the_same_code(self, api):
        """A `MINOR` event with a perfectly legal 1,500 m radius fails exactly like a
        `SERIOUS` event with no radius at all, and the band is inclusive at both ends: 0
        and 8,001 metres are refused while exactly 8,000 is admitted.

        PRD §2.11 rung 16: "**Evacuation order validity.** Advancing an emergency event
        to `EVACUATION_ORDERED` requires a `severity` of `SERIOUS` or `CRITICAL` and an
        `evacuation_radius_m` of at least 1 metre and at most 8000 metres — otherwise
        `ERR_EVACUATION_RADIUS_INVALID` (422)."

        Design: Corner/state_machines/evacuation_order_needs_a_serious_event_and_a_radius_inside_the_band
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-1")
        minor = open_emergency(api, field["id"], severity=SEVERITY_MINOR)
        serious = open_emergency(api, field["id"], severity=SEVERITY_SERIOUS)
        for event in (minor, serious):
            advance_emergency(
                api, event["id"], EMERGENCY_RESPONDING, responder_notes="Crew dispatched"
            )

        assert_error_envelope(
            _advance(api, minor["id"], EMERGENCY_EVACUATION_ORDERED, evacuation_radius_m=1500),
            ERR_EVACUATION_RADIUS_INVALID,
        )
        assert_error_envelope(
            _advance(api, serious["id"], EMERGENCY_EVACUATION_ORDERED),
            ERR_EVACUATION_RADIUS_INVALID,
        )
        assert_error_envelope(
            _advance(api, serious["id"], EMERGENCY_EVACUATION_ORDERED, evacuation_radius_m=0),
            ERR_EVACUATION_RADIUS_INVALID,
        )
        assert_error_envelope(
            _advance(api, serious["id"], EMERGENCY_EVACUATION_ORDERED, evacuation_radius_m=8001),
            ERR_EVACUATION_RADIUS_INVALID,
        )

        refused = read_event(api, serious["id"])
        assert refused["status"] == EMERGENCY_RESPONDING, (
            f"Four refusals must leave the event RESPONDING, got {refused['status']}"
        )
        assert refused["evacuation_radius_m"] == 0, (
            "A refused advance stores no radius, so the opening 0 stands, got "
            f"{refused['evacuation_radius_m']}"
        )

        admitted = assert_ok(
            _advance(api, serious["id"], EMERGENCY_EVACUATION_ORDERED, evacuation_radius_m=8000)
        )
        assert admitted["status"] == EMERGENCY_EVACUATION_ORDERED
        assert admitted["evacuation_radius_m"] == 8000, (
            f"8000 sits on the inclusive ceiling, got {admitted['evacuation_radius_m']}"
        )

        untouched = read_event(api, minor["id"])
        assert untouched["status"] == EMERGENCY_RESPONDING, (
            f"A MINOR event can never justify an evacuation, got {untouched['status']}"
        )
        assert untouched["evacuation_radius_m"] == 0
        assert_field_derived_block(read_field(api, field["id"]), posture=POSTURE_FROZEN)


class TestContainmentAndClosure:
    """Containment reopens the reservoir; closure ends the event."""

    def test_containment_restores_no_schedule_and_closure_is_terminal(self, api, mini_world):
        """The RESPONDING advance freezes the reservoir and sweeps a FIRM nomination away
        exactly as it would an interruptible one; containment recomputes the posture back
        to OPEN with both rates at 150,000 but leaves the nomination CURTAILED and the
        contract's scheduled injection at zero; and once the event is CLOSED any further
        advance is refused.

        PRD §3.8: "In both cases `contained_at` is stamped from the logical clock and the
        reservoir's posture is recomputed from scratch — which is how a field leaves
        `FROZEN` once no event on it is responding or evacuating... Containment does not
        by itself restore anything that was curtailed."

        Design: Corner/state_machines/emergency_containment_reopens_the_field_and_closure_makes_the_event_terminal
        """
        nomination = confirmed_nomination(
            api, mini_world.contract_id, mini_world.shipper_id,
            gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
        )
        event = open_emergency(api, mini_world.field_id)

        advance_emergency(
            api, event["id"], EMERGENCY_RESPONDING,
            responder_notes="station isolated, gas venting stopped",
        )
        assert_field_derived_block(read_field(api, mini_world.field_id), posture=POSTURE_FROZEN)
        swept = read_nomination(api, nomination["id"])
        assert swept["status"] == NOMINATION_CURTAILED, (
            f"The frozen form of the sweep takes firm nominations too, got {swept['status']}"
        )
        assert swept["confirmed_volume_dth"] == 0
        assert swept["curtailed_volume_dth"] == 80000
        assert read_contract(api, mini_world.contract_id)["scheduled_injection_dth"] == 0

        contained = advance_emergency(api, event["id"], EMERGENCY_CONTAINED)
        assert contained["status"] == EMERGENCY_CONTAINED
        assert_instant_equals(contained["contained_at"], CLOCK_EPOCH)
        assert_field_derived_block(
            read_field(api, mini_world.field_id), posture=POSTURE_OPEN,
            injection_rate=150000, withdrawal_rate=150000,
        )
        assert read_nomination(api, nomination["id"])["status"] == NOMINATION_CURTAILED, (
            "Recomputing the posture restores nothing the sweep took"
        )

        closed = advance_emergency(api, event["id"], EMERGENCY_CLOSED)
        assert closed["status"] == EMERGENCY_CLOSED
        assert_instant_equals(closed["closed_at"], CLOCK_EPOCH)

        assert_error_envelope(
            _advance(api, event["id"], EMERGENCY_CONTAINED), ERR_INVALID_EMERGENCY_STATE
        )
        assert read_event(api, event["id"])["status"] == EMERGENCY_CLOSED, (
            "CLOSED is terminal, so the refused advance changes nothing"
        )

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                mini_world.contract_id, SCHEDULING_COORDINATOR, {"limit": 100}
            )
        )
        assert meta["total_count"] == 1, (
            f"Only the curtailment credit may exist, got {meta['total_count']}"
        )
        assert_ledger_entry(
            rows[0], entry_type=LEDGER_CURTAILMENT_CREDIT,
            volume_dth=-80000.000, amount_usd=0.00, gas_day="2026-08-20",
        )


class TestRemediationDuringAnActiveResponse:
    """The block is keyed on the event's status, not on the program's."""

    def test_completion_is_refused_only_while_the_event_is_being_worked(self, api):
        """A detected event does not block the sign-off, a responding one refuses it with
        `ERR_REMEDIATION_ESCALATED` while leaving the program OPEN -- it is not escalated,
        because only an evacuation order escalates programs -- and once the event is
        contained the identical call by the identical engineer succeeds.

        PRD §2.11 rung 32: "**Remediation blocked by emergency.** An `OPEN` remediation
        program may not be completed while an emergency event on its wellbore's field
        stands in `RESPONDING` or `EVACUATION_ORDERED` status — otherwise
        `ERR_REMEDIATION_ESCALATED` (409)."

        Design: Corner/validations/remediation_completion_blocked_while_an_emergency_is_being_worked
        """
        field = create_field(api)
        first_well = create_well(api, field["id"], well_name="MINI-1")
        create_well(api, field["id"], well_name="MINI-2")
        failure = fail_mit_on_well(api, first_well["id"])
        program_id = failure.program["id"]
        assert read_program(api, program_id)["status"] == REMEDIATION_OPEN

        event = open_emergency(
            api, field["id"], event_type=EVENT_TYPE_LEAK, severity=SEVERITY_MINOR,
            detected_at="2026-08-02T06:00:00Z",
        )
        advance_emergency(
            api, event["id"], EMERGENCY_RESPONDING,
            responder_notes="Crew dispatched to the wellhead",
        )
        assert_field_derived_block(read_field(api, field["id"]), posture=POSTURE_FROZEN)

        assert_error_envelope(_complete_remediation(api, program_id), ERR_REMEDIATION_ESCALATED)
        blocked = read_program(api, program_id)
        assert blocked["status"] == REMEDIATION_OPEN, (
            "Only an evacuation order escalates a program; a refusal leaves it OPEN, got "
            f"{blocked['status']}"
        )
        assert read_event(api, event["id"])["status"] == EMERGENCY_RESPONDING

        advance_emergency(
            api, event["id"], EMERGENCY_CONTAINED, responder_notes="Leak isolated and vented"
        )
        completed = remediate_well(api, program_id, notes="Casing repair verified")
        assert completed["status"] == REMEDIATION_COMPLETED, (
            f"The same call must now succeed, got {completed['status']}"
        )
        assert completed["completed_by_user_id"] == ENGINEER_B_ID, (
            f"completed_by_user_id: expected {ENGINEER_B_ID}, got {completed['completed_by_user_id']}"
        )

        cleared = read_well(api, first_well["id"])
        assert cleared["integrity_state"] == INTEGRITY_REMEDIATED, (
            f"integrity_state: expected REMEDIATED, got {cleared['integrity_state']}"
        )
        reopened = read_field(api, field["id"])
        assert_field_derived_block(
            reopened, working_gas=250000.000, posture=POSTURE_OPEN, wells_in_service=1
        )


class TestAdvanceInputsPerTargetStatus:
    """One action endpoint, three different input contracts."""

    def test_each_edge_requires_and_ignores_its_own_inputs(self, api):
        """Advancing to RESPONDING succeeds on notes alone and stores no radius; the same
        endpoint refuses an evacuation with no radius and then accepts one at 2,500 m; and
        a radius handed to the containment edge is simply not stored, so the evacuation's
        2,500 m survives.

        PRD §3.8: "Response then advances along a fixed plan, each step carrying the
        requested `to_status` and optionally `responder_notes` that overwrite the latest
        responder narrative."

        Design: Corner/endpoints/emergency_advance_requires_different_inputs_per_target_status
        """
        field = create_field(api)
        well = create_well(api, field["id"], well_name="MINI-1")
        event = open_emergency(
            api, field["id"], event_type=EVENT_TYPE_LEAK, severity=SEVERITY_CRITICAL,
            detected_at=CLOCK_EPOCH, well_id=well["id"],
        )

        responding = assert_ok(
            _advance(api, event["id"], EMERGENCY_RESPONDING, responder_notes="Crew dispatched")
        )
        assert responding["status"] == EMERGENCY_RESPONDING
        assert responding["responder_notes"] == "Crew dispatched", (
            f"responder_notes: expected the supplied narrative, got {responding['responder_notes']!r}"
        )
        assert responding["evacuation_radius_m"] == 0, (
            "The responding edge takes no radius, so the opening 0 stands, got "
            f"{responding['evacuation_radius_m']}"
        )

        assert_error_envelope(
            _advance(api, event["id"], EMERGENCY_EVACUATION_ORDERED),
            ERR_EVACUATION_RADIUS_INVALID,
        )
        assert read_event(api, event["id"])["status"] == EMERGENCY_RESPONDING

        ordered = assert_ok(
            _advance(api, event["id"], EMERGENCY_EVACUATION_ORDERED, evacuation_radius_m=2500)
        )
        assert ordered["status"] == EMERGENCY_EVACUATION_ORDERED
        assert ordered["evacuation_radius_m"] == 2500

        contained = assert_ok(
            _advance(
                api, event["id"], EMERGENCY_CONTAINED,
                responder_notes="Well killed and vented", evacuation_radius_m=4000,
            )
        )
        assert contained["status"] == EMERGENCY_CONTAINED
        assert_instant_equals(contained["contained_at"], CLOCK_EPOCH)
        assert contained["evacuation_radius_m"] == 2500, (
            "The radius is an evacuation-edge input only, so containment must not overwrite "
            f"it, got {contained['evacuation_radius_m']}"
        )
        assert contained["well_id"] == well["id"]
        assert contained["severity"] == SEVERITY_CRITICAL

        assert_field_derived_block(
            read_field(api, field["id"]), posture=POSTURE_OPEN, wells_in_service=1
        )
