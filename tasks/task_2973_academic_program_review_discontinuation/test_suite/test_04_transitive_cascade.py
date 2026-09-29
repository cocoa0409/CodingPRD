"""SCAFFOLD §1.8 rule_id transitive_cascade: one request, a chain of causally dependent hops."""

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
    make_program_chair_headers,
    make_provost_proposer_headers,
    make_provost_ratifier_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)

RATIFICATION_INSTANT = "2026-09-15T10:00:00Z"


def test_ratify_four_hop_cascade_cycle_program_catalog_notifications(api):
    """One RATIFY fires four hops, each existing only because the previous one did.

    §3.6's ratification cascade: hop 1 closes the parent cycle into DECIDED, hop 2
    fires because the cycle became DECIDED and moves the program onto the
    DISCONTINUATION branch's TEACH_OUT_PENDING, hop 3 fires because the program
    left UNDER_REVIEW and both snapshots the catalog axis into
    catalog_status_pre_decision and suppresses it while minting the two
    AUTO_MINTED notices with §3.7 deadlines (30 whole days for the ACCREDITOR,
    45 for the STATE_AGENCY, each an exact multiple of 24 hours off ratified_at),
    and hop 4 fires because those rows now exist and flips the cycle's
    compliance_posture to NOTICES_PENDING. Only the one RATIFY request is issued.

    Design: Difficulty/transitive_cascade/ratify_four_hop_cascade_cycle_program_catalog_notifications
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    ctx = fixtures.carry_cycle_to_response_submitted(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
        host_capacity_per_day=2,
    )
    program_id = ctx.program_id
    cycle_id = ctx.cycle_id

    # Park the clock so ratified_at and both computed deadlines are determined.
    fixtures.set_clock(api, RATIFICATION_INSTANT)
    decision = fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    assert decision["state"] == "PROPOSED"
    assertions.assert_axes(
        fixtures.read_program(api, program_id),
        lifecycle_state="UNDER_REVIEW",
        catalog_status="LISTED",
    )

    # Trigger: the single RATIFY, issued by the second provost.
    ratified = validate_success(
        api.transition_decision_record(
            decision["id"], factories.ratify_payload(), make_provost_ratifier_headers()
        ),
        200,
    )
    assert ratified["state"] == "RATIFIED"
    assert ratified["ratified_by_user_id"] == "provost-ratifier"
    assertions.assert_instant_equals(
        ratified["ratified_at"], RATIFICATION_INSTANT, "decision.ratified_at"
    )
    assertions.assert_decimal_equals(
        ratified["composite_score_at_proposal"],
        constants.FIXTURE_A_COMPOSITE_UNDERGRADUATE,
        "composite_score_at_proposal",
    )
    assert ratified["viability_band_at_proposal"] == constants.FIXTURE_A_BAND

    # Hop 1: the parent cycle closed into DECIDED.
    cycle = fixtures.read_cycle(api, cycle_id)
    assert cycle["state"] == "DECIDED"
    assertions.assert_instant_equals(
        cycle["decided_at"], RATIFICATION_INSTANT, "cycle.decided_at"
    )

    # Hop 2 and hop 3: the lifecycle branch, the catalog snapshot and the
    # suppression, on one row.
    program = fixtures.read_program(api, program_id)
    assertions.assert_axes(
        program,
        lifecycle_state="TEACH_OUT_PENDING",
        catalog_status="MARKETING_SUPPRESSED",
    )
    assert program["catalog_status_pre_decision"] == "LISTED"

    # Hop 3: exactly two auto-minted notices, each with its statutory deadline.
    notices, meta = validate_paginated(
        api.list_agency_notifications(decision["id"], coordinator)
    )
    assert meta["total_count"] == 2
    assert len(notices) == 2
    by_type = {row["agency_type"]: row for row in notices}
    assert set(by_type) == {"ACCREDITOR", "STATE_AGENCY"}
    for row in notices:
        assert row["origin"] == "AUTO_MINTED"
        assert row["status"] == "PENDING"

    accreditor = by_type["ACCREDITOR"]
    assert accreditor["agency_code"] == constants.AUTO_MINTED_ACCREDITOR_CODE
    assertions.assert_instant_equals(
        accreditor["due_at"],
        assertions.add_days(
            RATIFICATION_INSTANT, constants.NOTICE_DAYS_BY_AGENCY_TYPE["ACCREDITOR"]
        ),
        "ACCREDITOR due_at",
    )

    state_agency = by_type["STATE_AGENCY"]
    assert state_agency["agency_code"] == constants.AUTO_MINTED_STATE_AGENCY_CODE
    assertions.assert_instant_equals(
        state_agency["due_at"],
        assertions.add_days(
            RATIFICATION_INSTANT, constants.NOTICE_DAYS_BY_AGENCY_TYPE["STATE_AGENCY"]
        ),
        "STATE_AGENCY due_at",
    )

    # Hop 4: the posture flipped because those rows now exist.
    assert cycle["compliance_posture"] == "NOTICES_PENDING"
    decision_after = fixtures.read_decision(api, decision["id"])
    assert decision_after["notification_count"] == 2
    assert decision_after["unacknowledged_notification_count"] == 2


def test_last_student_completion_bubbles_up_to_program_and_faculty(api):
    """One COMPLETE on the last open student bubbles three hops upward.

    §3.10's seat release drops the student's eight seats back onto their
    guarantees, which drives §3.9's open_student_count to 0; hop 1 auto-completes
    the IN_EFFECT plan, hop 2 fires because the plan completed and moves the
    program to DISCONTINUED and then its catalog axis to CATALOG_WITHDRAWN, and
    hop 3 fires because the program became DISCONTINUED and returns the
    TEACH_OUT_RETAINED adjunct to ASSIGNED — which re-runs the whole staffing
    waterfall against a guarantee set the plan's own completion has just taken out
    of the retained count.

    Design: Difficulty/transitive_cascade/last_student_completion_bubbles_up_to_program_and_faculty
    """
    coordinator = make_review_coordinator_headers()
    registrar = make_registrar_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
        host_capacity_per_day=2,
    )
    program_id = program["id"]
    fixtures.append_snapshots(api, program_id, constants.FIXTURE_A_SNAPSHOTS)

    adjunct = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-ADJ-1",
        tenure_status="ADJUNCT",
        fte=0.25,
        annual_salary_cents=4000000,
    )

    ctx = fixtures.carry_cycle_to_response_submitted(
        api, program=fixtures.read_program(api, program_id)
    )
    fixtures.set_clock(api, RATIFICATION_INSTANT)
    fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    fixtures.ratify_decision(api, ctx)
    fixtures.acknowledge_all_notifications(api, ctx.decision["id"])

    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    plan_id = ctx.plan["id"]
    first = fixtures.add_guarantee(
        api, ctx, course_code="HIST-401", term_index=4, seats_guaranteed=6
    )
    second = fixtures.add_guarantee(
        api, ctx, course_code="HIST-402", term_index=5, seats_guaranteed=6
    )
    student = fixtures.enrol_student(
        api, ctx, student_number="S-0001", credits_remaining=24, max_credits_per_term=15
    )
    fixtures.submit_plan(api, ctx)
    fixtures.approve_plan(api, ctx)

    # Advised at 12 credits per term the conservative projection still lands on
    # term 5, so the student is not at risk and the plan stays approvable.
    advised = fixtures.record_advising(
        api, student["id"], advised_credits_per_term=12, plan_signed=True
    )
    assertions.assert_projection(
        advised,
        variant="CONSERVATIVE_ADVISED_LOAD",
        terms_remaining=2,
        completion_term_index=5,
        at_risk=False,
        required_seat_count=8,
    )
    assert advised["advising_status"] == "PLAN_SIGNED"

    retained = fixtures.transition_appointment(
        api, adjunct["id"], factories.retain_payload()
    )
    assert retained["state"] == "TEACH_OUT_RETAINED"

    fixtures.effectuate_decision(api, ctx)
    fixtures.activate_plan(api, ctx)
    assert fixtures.read_plan(api, plan_id)["state"] == "IN_EFFECT"

    # The student takes all eight of their required seats across both guarantees.
    validate_success(
        api.allocate_seats(
            first["id"], factories.seat_commit_payload(student["id"], 6), registrar
        )
    )
    validate_success(
        api.allocate_seats(
            second["id"], factories.seat_commit_payload(student["id"], 2), registrar
        )
    )
    held = fixtures.read_plan(api, plan_id)
    assertions.assert_plan_ledger(
        held, committed_seat_total=8, open_student_count=1
    )

    # Trigger: the last open student completes.
    completed = validate_success(
        api.record_student_progress(
            student["id"], factories.student_complete_payload(completion_term_index=5), registrar
        ),
        200,
    )
    assert completed["advising_status"] == "COMPLETED"
    assert completed["completion_term_index"] == 5
    assert completed["committed_seat_count"] == 0

    # The seats went back to their guarantees.
    guarantees, _meta = validate_paginated(
        api.list_course_guarantees(plan_id, coordinator)
    )
    by_course = {row["course_code"]: row for row in guarantees}
    for course_code in ("HIST-401", "HIST-402"):
        assert by_course[course_code]["seats_committed"] == 0
        assert by_course[course_code]["seats_available"] == 6

    # Hop 1: the plan auto-completed at zero open students.
    plan = fixtures.read_plan(api, plan_id)
    assert plan["state"] == "COMPLETED"
    assertions.assert_instant_equals(
        plan["completed_at"], RATIFICATION_INSTANT, "plan.completed_at"
    )
    assertions.assert_plan_ledger(plan, open_student_count=0, committed_seat_total=0)

    # Hop 2: both program axes moved because the plan completed.
    program = fixtures.read_program(api, program_id)
    assertions.assert_axes(
        program, lifecycle_state="DISCONTINUED", catalog_status="CATALOG_WITHDRAWN"
    )

    # Hop 3: the retained appointment came back and the waterfall re-ran.
    appointments = fixtures.list_appointments(api, program_id)
    assert len(appointments) == 1
    row = appointments[0]
    assert row["id"] == adjunct["id"]
    assert row["state"] == "ASSIGNED"
    assert row["reduction_sequence_position"] == 1
    assert row["notice_pay_cents"] == 82192
    assertions.assert_waterfall(
        program,
        baseline=0.25,
        assigned_pool=0.25,
        retained=0.00,
        reducible=0.25,
        liability_cents=82192,
        deferred=0.00,
    )
    assertions.assert_fte_partition(program, appointments)

    cycle = fixtures.read_cycle(api, ctx.cycle_id)
    assert cycle["state"] == "CLOSED"
    assert cycle["compliance_posture"] == "NOTICES_CLEARED"
