"""SCAFFOLD §1.8 rule_id compensating_invariant: a write, its compensating edge, one conserved sum."""

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
    make_registrar_headers,
    make_review_coordinator_headers,
)


def _ledger(api, plan_id, coordinator):
    """Read the plan and both sides of its seat ledger in one go."""
    plan = fixtures.read_plan(api, plan_id)
    guarantees, _meta = validate_paginated(
        api.list_course_guarantees(plan_id, coordinator)
    )
    students, _meta = validate_paginated(
        api.list_displaced_students(plan_id, coordinator)
    )
    assertions.assert_seat_conservation(guarantees, students)
    return plan, guarantees, students


def test_seat_commit_release_conserves_the_two_sided_ledger(api):
    """A refused commit moves neither side; a release compensates the first commit exactly.

    §2.11 conserves one quantity across two aggregates: the committed seats on
    non-waived guarantees always equal the seats held by students who have not
    withdrawn. §3.9's capacity check is on the resulting aggregate, so 4 seats and
    3 seats each sit well inside a guarantee of 6 while their sum of 7 does not —
    a per-request bound check would let the second commit through. The refusal is
    the classic place a partial write leaks, so both sides are re-read after it.
    Releasing 2 seats then compensates, and the identical commit that was just
    refused succeeds. The conserved sum holds at all four observation points, and
    seat movement leaves the plan's other aggregates alone.

    Design: Difficulty/compensating_invariant/seat_commit_release_conserves_the_two_sided_ledger
    """
    coordinator = make_review_coordinator_headers()
    registrar = make_registrar_headers()

    ctx = fixtures.setup_ratified_discontinuation(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    # Seat allocation is not gated on the plan's state, so the ledger is
    # exercised while the plan is still DRAFT.
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
    guarantee_id = guarantee["id"]
    first_student = fixtures.enrol_student(
        api, ctx, student_number="S-0001", credits_remaining=12, max_credits_per_term=15
    )
    second_student = fixtures.enrol_student(
        api, ctx, student_number="S-0002", credits_remaining=9, max_credits_per_term=15
    )
    assert first_student["required_seat_count"] == 4
    assert second_student["required_seat_count"] == 3

    validate_success(
        api.allocate_seats(
            guarantee_id,
            factories.seat_commit_payload(first_student["id"], 4),
            registrar,
        )
    )

    def by_id(students):
        return {row["id"]: row for row in students}

    # Observation 1: the two sides agree at 4.
    plan, guarantees, students = _ledger(api, plan_id, coordinator)
    assert guarantees[0]["seats_committed"] == 4
    assert guarantees[0]["seats_available"] == 2
    assert by_id(students)[first_student["id"]]["committed_seat_count"] == 4
    assert by_id(students)[second_student["id"]]["committed_seat_count"] == 0
    assertions.assert_plan_ledger(
        plan,
        guaranteed_seat_total=6,
        committed_seat_total=4,
        required_seat_total=7,
        seat_shortfall=1,
        open_student_count=2,
        at_risk_student_count=0,
    )
    assert plan["state"] == "DRAFT"

    # Trigger part 1: only the aggregate breaches the guarantee.
    refused = api.allocate_seats(
        guarantee_id, factories.seat_commit_payload(second_student["id"], 3), registrar
    )
    validate_error(refused, ERR_SEAT_CAPACITY_EXCEEDED, 409)

    # Observation 2: nothing moved on either side.
    plan, guarantees, students = _ledger(api, plan_id, coordinator)
    assert guarantees[0]["seats_committed"] == 4
    assert guarantees[0]["seats_available"] == 2
    assert by_id(students)[first_student["id"]]["committed_seat_count"] == 4
    assert by_id(students)[second_student["id"]]["committed_seat_count"] == 0
    assertions.assert_plan_ledger(plan, committed_seat_total=4)

    # Trigger part 2: the compensating edge.
    released = validate_success(
        api.allocate_seats(
            guarantee_id,
            factories.seat_release_payload(first_student["id"], 2),
            registrar,
        ),
        200,
    )
    assert released["seats_committed"] == 2
    assert released["seats_available"] == 4

    # Observation 3: both sides still agree, now at 2.
    plan, guarantees, students = _ledger(api, plan_id, coordinator)
    assert guarantees[0]["seats_committed"] == 2
    assert by_id(students)[first_student["id"]]["committed_seat_count"] == 2
    assertions.assert_plan_ledger(plan, committed_seat_total=2)

    # Trigger part 3: the identical commit that was refused a moment ago.
    committed = validate_success(
        api.allocate_seats(
            guarantee_id,
            factories.seat_commit_payload(second_student["id"], 3),
            registrar,
        ),
        200,
    )
    assert committed["seats_committed"] == 5
    assert committed["seats_available"] == 1

    # Observation 4: 2 + 3 on the demand side, 5 on the supply side.
    plan, guarantees, students = _ledger(api, plan_id, coordinator)
    assert guarantees[0]["seats_committed"] == 5
    assert guarantees[0]["status"] == "PLANNED"
    assert by_id(students)[first_student["id"]]["committed_seat_count"] == 2
    assert by_id(students)[second_student["id"]]["committed_seat_count"] == 3
    assertions.assert_plan_ledger(
        plan,
        guaranteed_seat_total=6,
        committed_seat_total=5,
        required_seat_total=7,
        seat_shortfall=1,
        open_student_count=2,
        at_risk_student_count=0,
    )
    assert plan["state"] == "DRAFT"


def test_propose_then_withdraw_reassignment_conserves_fte_and_waterfall(api):
    """WITHDRAW_REASSIGNMENT restores every waterfall output the proposal disturbed.

    §3.11 pulls a proposed appointment's load out of assigned_pool_fte while
    leaving active_fte_total alone, so the additive identity active + reassigned +
    separated == faculty_fte_baseline holds throughout. The withdraw is the
    compensating edge, and the invariant is two-layered: the identity must hold at
    every point, and the full waterfall must be re-derived back to identical
    outputs — the same liability of 1857534 cents, the same deferred_fte of 1.00,
    and consecutive reduction positions 1 and 2 with no gap left by the row that
    temporarily vacated position 2. Only reassignment_withdraw_count, an audit
    counter, is permitted to differ afterwards.

    Design: Difficulty/compensating_invariant/propose_then_withdraw_reassignment_conserves_fte_and_waterfall
    """
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

    adjunct = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-ADJ-1",
        tenure_status="ADJUNCT",
        fte=0.25,
        annual_salary_cents=4000000,
    )
    non_tenure_track = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-NTT-1",
        tenure_status="NON_TENURE_TRACK",
        fte=1.00,
        annual_salary_cents=7200000,
    )
    tenured = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-TEN-1",
        tenure_status="TENURED",
        fte=1.00,
        annual_salary_cents=12000000,
    )

    def positions():
        rows = fixtures.list_appointments(api, program_id)
        assert len(rows) == 3
        return {row["id"]: row for row in rows}, rows

    # No course guarantees at all, so retained_teach_out_fte is 0.00 and the whole
    # baseline is reducible.
    before = fixtures.read_program(api, program_id)
    assertions.assert_waterfall(
        before,
        baseline=2.25,
        active=2.25,
        assigned_pool=2.25,
        retained=0.00,
        reducible=2.25,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=1857534,
        deferred=1.00,
        reassigned=0.00,
        separated=0.00,
    )
    rows_by_id, rows = positions()
    assertions.assert_fte_partition(before, rows)
    assert rows_by_id[adjunct["id"]]["reduction_sequence_position"] == 1
    assert rows_by_id[adjunct["id"]]["notice_pay_cents"] == 82192
    assert rows_by_id[non_tenure_track["id"]]["reduction_sequence_position"] == 2
    assert rows_by_id[non_tenure_track["id"]]["notice_pay_cents"] == 1775342
    assert rows_by_id[tenured["id"]]["reduction_sequence_position"] is None
    assert rows_by_id[tenured["id"]]["notice_pay_cents"] == 12000000

    # Trigger part 1: the proposal takes the middle row out of the pool.
    proposed = fixtures.transition_appointment(
        api,
        non_tenure_track["id"],
        factories.propose_reassignment_payload("CLAS"),
    )
    assert proposed["state"] == "REASSIGNMENT_PROPOSED"
    assert proposed["reassigned_to_department_code"] == "CLAS"

    mid = fixtures.read_program(api, program_id)
    assertions.assert_waterfall(
        mid,
        baseline=2.25,
        active=2.25,
        assigned_pool=1.25,
        retained=0.00,
        reducible=1.25,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=82192,
        deferred=1.00,
        reassigned=0.00,
        separated=0.00,
    )
    rows_by_id, rows = positions()
    assertions.assert_fte_partition(mid, rows)
    assert rows_by_id[adjunct["id"]]["reduction_sequence_position"] == 1
    assert rows_by_id[non_tenure_track["id"]]["reduction_sequence_position"] is None
    assert rows_by_id[tenured["id"]]["reduction_sequence_position"] is None, (
        "82192 + 12000000 still breaches the 5100000 cent cap"
    )

    # Trigger part 2: the compensating edge.
    withdrawn = fixtures.transition_appointment(
        api, non_tenure_track["id"], factories.withdraw_reassignment_payload()
    )
    assert withdrawn["state"] == "ASSIGNED"
    assert withdrawn["reassigned_to_department_code"] is None
    assert withdrawn["reassignment_withdraw_count"] == 1

    after = fixtures.read_program(api, program_id)
    assertions.assert_waterfall(
        after,
        baseline=2.25,
        active=2.25,
        assigned_pool=2.25,
        retained=0.00,
        reducible=2.25,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=1857534,
        deferred=1.00,
        reassigned=0.00,
        separated=0.00,
    )
    rows_by_id, rows = positions()
    assertions.assert_fte_partition(after, rows)

    # The numbering is consecutive from 1 again, with no gap at position 2.
    assert rows_by_id[adjunct["id"]]["reduction_sequence_position"] == 1
    assert rows_by_id[non_tenure_track["id"]]["reduction_sequence_position"] == 2
    assert rows_by_id[tenured["id"]]["reduction_sequence_position"] is None

    # Notice pay is a function of the appointment's own fields, so neither edge
    # touched it, and only the compensated row's audit counter moved.
    assert rows_by_id[adjunct["id"]]["notice_pay_cents"] == 82192
    assert rows_by_id[non_tenure_track["id"]]["notice_pay_cents"] == 1775342
    assert rows_by_id[tenured["id"]]["notice_pay_cents"] == 12000000
    assert rows_by_id[adjunct["id"]]["reassignment_withdraw_count"] == 0
    assert rows_by_id[non_tenure_track["id"]]["reassignment_withdraw_count"] == 1
    assert rows_by_id[tenured["id"]]["reassignment_withdraw_count"] == 0

    # The waterfall outputs are byte-identical across the compensated pair.
    for field in (
        "faculty_fte_baseline",
        "active_fte_total",
        "assigned_pool_fte",
        "retained_teach_out_fte",
        "reducible_fte",
        "severance_budget_cap_cents",
        "staffing_liability_cents",
        "deferred_fte",
        "reassigned_fte_total",
        "separated_fte_total",
    ):
        assert after[field] == before[field], (
            f"{field} was not restored by the compensating edge: "
            f"{before[field]} -> {after[field]}"
        )
