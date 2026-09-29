"""SCAFFOLD §1.8 rule_id cross_entity_state_dependency: a transition gated on a sibling's state."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures  # noqa: E402
from test_helpers.api_errors import *  # noqa: F401,F403,E402
from test_helpers.test_users import (  # noqa: E402
    make_hr_partner_headers,
    make_review_coordinator_headers,
)

RATIFICATION_INSTANT = "2026-09-15T10:00:00Z"
NOTICE_INSTANT = "2026-09-20T00:00:00Z"
NOTICE_ELAPSED_INSTANT = "2027-09-20T00:00:00Z"


def test_plan_activation_gated_on_decision_record_state_not_its_own(api):
    """ACTIVATE is refused for a reason that lives entirely on the decision record.

    §3.9 gates APPROVED -> IN_EFFECT on the linked decision having reached
    EFFECTUATED, so the refusal has nothing to do with the plan: its own state is
    APPROVED, its seat_shortfall is 0 and its at_risk_student_count is 0. What
    blocks it is two aggregates away — the decision cannot effectuate while
    §3.7's notices are unacknowledged. Clearing the notices, effectuating, and
    reissuing the byte-identical ACTIVATE then succeeds, and because the plan
    carries one open student the empty-cohort auto-completion of §3.9 does not
    fire, leaving the plan in IN_EFFECT.

    Design: Difficulty/cross_entity_state_dependency/plan_activation_gated_on_decision_record_state_not_its_own
    """
    coordinator = make_review_coordinator_headers()

    ctx = fixtures.setup_ratified_discontinuation(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    decision_id = ctx.decision["id"]

    # A plan may be filed while its decision is only RATIFIED.
    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    plan_id = ctx.plan["id"]
    guarantee = fixtures.add_guarantee(
        api, ctx, course_code="HIST-401", term_index=4, seats_guaranteed=6
    )
    student = fixtures.enrol_student(
        api, ctx, student_number="S-0001", credits_remaining=12, max_credits_per_term=15
    )
    fixtures.submit_plan(api, ctx)
    fixtures.approve_plan(api, ctx)

    # Nothing about the plan itself is wrong at the moment of the trigger.
    approved = fixtures.read_plan(api, plan_id)
    assert approved["state"] == "APPROVED"
    assertions.assert_plan_ledger(
        approved,
        guaranteed_seat_total=6,
        required_seat_total=4,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=1,
    )
    assert fixtures.read_decision(api, decision_id)["state"] == "RATIFIED"

    # Trigger part 1: the sibling aggregate is what refuses the request.
    refused = api.transition_teach_out_plan(
        plan_id, factories.plan_transition_payload("ACTIVATE"), coordinator
    )
    validate_error(refused, ERR_DECISION_NOT_EFFECTUATED, 409)

    after_refusal = fixtures.read_plan(api, plan_id)
    assert after_refusal["state"] == "APPROVED"
    assert after_refusal["activated_at"] is None
    assert after_refusal["seat_shortfall"] == 0
    assert after_refusal["at_risk_student_count"] == 0

    # Clear the notices two aggregates away, then effectuate.
    fixtures.acknowledge_all_notifications(api, decision_id)
    effectuated = validate_success(
        api.transition_decision_record(
            decision_id, factories.effectuate_payload(), coordinator
        ),
        200,
    )
    assert effectuated["state"] == "EFFECTUATED"
    assertions.assert_axes(
        fixtures.read_program(api, ctx.program_id),
        lifecycle_state="TEACH_OUT_ACTIVE",
        catalog_status="ADMISSIONS_CLOSED",
    )
    assert fixtures.read_cycle(api, ctx.cycle_id)["state"] == "CLOSED"

    # Trigger part 2: the identical request, now permitted.
    activated = validate_success(
        api.transition_teach_out_plan(
            plan_id, factories.plan_transition_payload("ACTIVATE"), coordinator
        ),
        200,
    )
    assert activated["state"] == "IN_EFFECT"
    assertions.assert_instant_equals(
        activated["activated_at"], RATIFICATION_INSTANT, "plan.activated_at"
    )
    assert activated["completed_at"] is None
    assertions.assert_plan_ledger(activated, open_student_count=1)

    guarantees, _meta = validate_paginated(
        api.list_course_guarantees(plan_id, coordinator)
    )
    assert len(guarantees) == 1
    assert guarantees[0]["id"] == guarantee["id"]
    assert guarantees[0]["status"] == "OFFERED"

    students, _meta = validate_paginated(
        api.list_displaced_students(plan_id, coordinator)
    )
    assert len(students) == 1
    assert students[0]["id"] == student["id"]
    assert students[0]["advising_status"] == "PENDING"


def test_tenured_separation_gated_on_teach_out_plan_state(api):
    """A tenured separation is refused by the state of a plan on another aggregate.

    §3.11 checks the tenure obligation before the notice-period clock: while any
    teach-out plan on the program is APPROVED or IN_EFFECT, a TENURED appointment
    cannot separate. The notice was issued at 2026-09-20T00:00:00Z for the full
    statutory 365 days and the clock is parked at exactly 2027-09-20T00:00:00Z,
    365 whole days later, so the notice-period comparison — which §2.5 makes
    inclusive — is satisfied. The only live fault is the plan sitting in APPROVED,
    so ERR_TENURE_OBLIGATION_ACTIVE is the answer, and an implementation that
    ordered the two checks the other way, or that treated the notice boundary as
    exclusive, would report ERR_NOTICE_PERIOD_NOT_ELAPSED instead.

    Design: Difficulty/cross_entity_state_dependency/tenured_separation_gated_on_teach_out_plan_state
    """
    hr = make_hr_partner_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    program_id = program["id"]
    fixtures.append_snapshots(api, program_id, constants.FIXTURE_A_SNAPSHOTS)

    appointment = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-TEN-1",
        tenure_status="TENURED",
        fte=1.00,
        annual_salary_cents=4000000,
    )
    appointment_id = appointment["id"]
    # 4000000 * 1.00 * 365 / 365 sits inside the 5100000 cent cap, so the walk
    # funds this appointment and it holds the minimum reduction position.
    assert appointment["notice_pay_cents"] == 4000000
    assert appointment["reduction_sequence_position"] == 1

    ctx = fixtures.carry_cycle_to_response_submitted(
        api, program=fixtures.read_program(api, program_id)
    )
    fixtures.set_clock(api, RATIFICATION_INSTANT)
    fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    fixtures.ratify_decision(api, ctx)

    # The notice is issued before any plan exists, so the statutory clock starts
    # while the tenure obligation is dormant.
    fixtures.set_clock(api, NOTICE_INSTANT)
    noticed = fixtures.transition_appointment(
        api, appointment_id, factories.issue_notice_payload(365)
    )
    assert noticed["state"] == "NOTICE_ISSUED"
    assert noticed["notice_days"] == 365
    assertions.assert_instant_equals(
        noticed["notice_issued_at"], NOTICE_INSTANT, "appointment.notice_issued_at"
    )

    # Now a plan reaches APPROVED on a different aggregate entirely.
    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    plan_id = ctx.plan["id"]
    fixtures.add_guarantee(
        api, ctx, course_code="HIST-401", term_index=4, seats_guaranteed=6
    )
    fixtures.submit_plan(api, ctx)
    fixtures.approve_plan(api, ctx)
    assert fixtures.read_plan(api, plan_id)["state"] == "APPROVED"

    # Exactly 365 whole days after the notice: the period has elapsed.
    fixtures.set_clock(api, NOTICE_ELAPSED_INSTANT)
    assertions.assert_instant_equals(
        assertions.add_days(NOTICE_INSTANT, 365),
        NOTICE_ELAPSED_INSTANT,
        "notice_issued_at plus 365 whole days",
    )

    # Trigger: the tenure obligation, not the calendar, is what refuses this.
    refused = api.transition_faculty_appointment(
        appointment_id, factories.separate_payload(), hr
    )
    error = validate_error(refused, ERR_TENURE_OBLIGATION_ACTIVE, 409)
    assert error["error_id"] != ERR_NOTICE_PERIOD_NOT_ELAPSED, (
        "the notice period elapsed exactly, and the comparison is inclusive"
    )

    appointments = fixtures.list_appointments(api, program_id)
    assert len(appointments) == 1
    row = appointments[0]
    assert row["id"] == appointment_id
    assert row["state"] == "NOTICE_ISSUED"
    assert row["notice_days"] == 365
    assertions.assert_instant_equals(
        row["notice_issued_at"], NOTICE_INSTANT, "appointment.notice_issued_at"
    )
    assert row["separated_at"] is None
    assert row["notice_pay_cents"] == 4000000

    # The blocking condition still lives on the sibling aggregate.
    assert fixtures.read_plan(api, plan_id)["state"] == "APPROVED"

    program = fixtures.read_program(api, program_id)
    assertions.assert_waterfall(
        program, active=1.00, separated=0.00, assigned_pool=0.00
    )
    assertions.assert_fte_partition(program, appointments)
