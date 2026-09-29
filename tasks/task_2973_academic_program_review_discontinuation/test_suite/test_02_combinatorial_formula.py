"""SCAFFOLD §1.8 rule_id combinatorial_formula: conditional weight vectors and pinned step order."""

import os
import sys
from decimal import Decimal

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


def _by_faculty_number(rows):
    return {row["faculty_number"]: row for row in rows}


def test_viability_composite_weight_vector_switches_with_degree_level(api):
    """Byte-identical snapshot histories produce different composites per degree_level.

    §3.2 selects the four-factor weight vector from degree_level: UNDERGRADUATE
    weights 0.35/0.25/0.20/0.20 and GRADUATE weights 0.25/0.30/0.15/0.30. Two
    programs fed the same three snapshots therefore land on 29.06 and 35.01 — a
    5.95 point spread produced purely by the conditional vector, with the falling
    enrollment factor clamped up to 0 in both and the identical cost factor
    entering both sums from the same rolling quotient of 45946 cents.

    Design: Difficulty/combinatorial_formula/viability_composite_weight_vector_switches_with_degree_level
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    undergraduate = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
        host_capacity_per_day=2,
    )
    graduate = fixtures.create_program(
        api,
        code="HIST-MA",
        name="History MA",
        degree_level="GRADUATE",
        department_code="HIST",
        host_capacity_per_day=2,
    )

    # The first two terms of both windows are identical.
    fixtures.append_snapshots(
        api, undergraduate["id"], constants.FIXTURE_A_SNAPSHOTS[:2]
    )
    fixtures.append_snapshots(api, graduate["id"], constants.FIXTURE_A_SNAPSHOTS[:2])

    # Trigger: the third term lands on both, completing both windows.
    fixtures.append_snapshots(
        api, undergraduate["id"], constants.FIXTURE_A_SNAPSHOTS[2:]
    )
    fixtures.append_snapshots(api, graduate["id"], constants.FIXTURE_A_SNAPSHOTS[2:])

    undergraduate = fixtures.read_program(api, undergraduate["id"])
    graduate = fixtures.read_program(api, graduate["id"])

    assertions.assert_viability(
        undergraduate,
        rolling_cents=constants.FIXTURE_A_ROLLING_CPH_CENTS,
        latest_cents=constants.FIXTURE_A_LATEST_CPH_CENTS,
        composite=constants.FIXTURE_A_COMPOSITE_UNDERGRADUATE,
        band=constants.FIXTURE_A_BAND,
    )
    assertions.assert_viability(
        graduate,
        rolling_cents=constants.FIXTURE_A_ROLLING_CPH_CENTS,
        latest_cents=constants.FIXTURE_A_LATEST_CPH_CENTS,
        composite=constants.FIXTURE_A_COMPOSITE_GRADUATE,
        band=constants.FIXTURE_A_BAND,
    )

    # The cost factor's input is identical; only the weights differ.
    assert (
        undergraduate["cost_per_credit_hour_rolling_cents"]
        == graduate["cost_per_credit_hour_rolling_cents"]
    )
    spread = Decimal(str(graduate["composite_score"])) - Decimal(
        str(undergraduate["composite_score"])
    )
    assert spread == Decimal(str(constants.FIXTURE_A_COMPOSITE_SPREAD)), (
        f"expected a {constants.FIXTURE_A_COMPOSITE_SPREAD} point spread from the "
        f"weight vector alone, got {spread}"
    )
    assertions.assert_two_decimal_places(
        undergraduate["composite_score"], "undergraduate composite_score"
    )
    assertions.assert_two_decimal_places(
        graduate["composite_score"], "graduate composite_score"
    )


def test_staffing_waterfall_step_order_and_cap_stop(api):
    """The waterfall's four steps run in the declared order and stop at the cap.

    §3.11 runs instructional demand, then the reducible pool, then the floored 15
    percent budget cap taken off the rolling direct-cost window, then a
    whole-appointment allocation ordered by tenure tier ascending, fte descending,
    created_at ascending. Five appointments totalling 3.75 fte on a program whose
    rolling window sums to 34000000 cents give a cap of floor(0.15 * 34000000) =
    5100000. The ADJUNCT (82192), the 1.00-fte NON_TENURE_TRACK (1775342) and the
    0.50-fte NON_TENURE_TRACK (887671) take positions 1, 2 and 3 for a running
    liability of 2745205; the TENURE_TRACK holder's 4438356 would carry the total
    past the cap, so the walk stops, both protected appointments keep a null
    position and deferred_fte settles at 2.00. Computing the cap before the demand
    step, or ordering by fte before tier, changes both the positions and the
    deferred figure.

    Design: Difficulty/combinatorial_formula/staffing_waterfall_step_order_and_cap_stop
    """
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

    # Created in tier-scrambled order so the sort cannot be mistaken for
    # insertion order.
    fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-TEN-1",
        tenure_status="TENURED",
        fte=1.00,
        annual_salary_cents=12000000,
    )
    fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-TT-1",
        tenure_status="TENURE_TRACK",
        fte=1.00,
        annual_salary_cents=9000000,
    )
    fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-NTT-HALF",
        tenure_status="NON_TENURE_TRACK",
        fte=0.50,
        annual_salary_cents=7200000,
    )
    fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-NTT-FULL",
        tenure_status="NON_TENURE_TRACK",
        fte=1.00,
        annual_salary_cents=7200000,
    )

    # Trigger: the ADJUNCT lands and becomes the least protected tier.
    fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-ADJ-1",
        tenure_status="ADJUNCT",
        fte=0.25,
        annual_salary_cents=4000000,
    )

    program = fixtures.read_program(api, program_id)
    appointments = fixtures.list_appointments(api, program_id)
    assert len(appointments) == 5
    rows = _by_faculty_number(appointments)

    # Step 1 and 2: no teach-out plan means no retained fte, so the whole
    # assigned pool is reducible.
    assertions.assert_waterfall(
        program,
        baseline=3.75,
        active=3.75,
        assigned_pool=3.75,
        retained=0.00,
        reducible=3.75,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=2745205,
        deferred=2.00,
    )
    assertions.assert_fte_partition(program, appointments)

    # Step 3: notice pay is salary * fte * statutory_days / 365, half-up to cents.
    assert rows["F-ADJ-1"]["notice_pay_cents"] == 82192
    assert rows["F-NTT-FULL"]["notice_pay_cents"] == 1775342
    assert rows["F-NTT-HALF"]["notice_pay_cents"] == 887671
    assert rows["F-TT-1"]["notice_pay_cents"] == 4438356
    assert rows["F-TEN-1"]["notice_pay_cents"] == 12000000
    for faculty_number, row in rows.items():
        assertions.assert_integer_cents(
            row["notice_pay_cents"], f"{faculty_number}.notice_pay_cents"
        )

    # Step 4: tier ascending, then fte descending, then created_at ascending.
    assert rows["F-ADJ-1"]["reduction_sequence_position"] == 1
    assert rows["F-NTT-FULL"]["reduction_sequence_position"] == 2
    assert rows["F-NTT-HALF"]["reduction_sequence_position"] == 3
    assert rows["F-TT-1"]["reduction_sequence_position"] is None
    assert rows["F-TEN-1"]["reduction_sequence_position"] is None

    # The cap stop is what leaves the two most protected appointments unfunded.
    assert (
        rows["F-ADJ-1"]["notice_pay_cents"]
        + rows["F-NTT-FULL"]["notice_pay_cents"]
        + rows["F-NTT-HALF"]["notice_pay_cents"]
        <= program["severance_budget_cap_cents"]
    )
    assert (
        program["staffing_liability_cents"] + rows["F-TT-1"]["notice_pay_cents"]
        > program["severance_budget_cap_cents"]
    ), "the TENURE_TRACK holder is the appointment whose notice pay breaches the cap"
