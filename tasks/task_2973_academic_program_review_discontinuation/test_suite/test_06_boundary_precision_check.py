"""SCAFFOLD §1.8 rule_id boundary_precision_check: the exact value on an inclusive edge."""

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
    make_provost_proposer_headers,
    make_review_coordinator_headers,
)

RATIFICATION_INSTANT = "2026-09-15T10:00:00Z"


def test_composite_40_00_blocks_discontinuation_39_99_permits_it(api):
    """A composite of exactly 40.00 sits inside IMPROVEMENT_ELIGIBLE; 39.99 does not.

    §3.2 bands off the *rounded* score with inclusive lower bounds, so 40.00 is
    IMPROVEMENT_ELIGIBLE and only a score strictly below 40.00 is NONVIABLE.
    §3.6 then permits DISCONTINUATION only from NONVIABLE. Three flat snapshots
    (125 heads, 400 credit hours, 20000000 cents, 7 completions, demand 35) put
    the program exactly on the edge: enrollment 50, completion 14.0, demand 35,
    efficiency exactly 60 because the rolling cost lands exactly on the 50000
    cent benchmark, weighting to 40.00 on the nose. The proposal is refused.
    Appending one term whose direct cost rises by 50400 cents nudges the rolling
    quotient to 50042, the efficiency factor just under 60, and the composite to
    39.98993 -> 39.99, one hundredth below the edge, and the byte-identical
    proposal is then accepted.

    Design: Difficulty/boundary_precision_check/composite_40_00_blocks_discontinuation_39_99_permits_it
    """
    coordinator = make_review_coordinator_headers()
    proposer = make_provost_proposer_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = fixtures.create_program(
        api,
        code="CHEM-BS",
        name="Chemistry BS",
        degree_level="UNDERGRADUATE",
        department_code="CHEM",
    )
    program_id = program["id"]
    fixtures.append_snapshots(api, program_id, constants.FIXTURE_BOUNDARY_SNAPSHOTS)

    program = fixtures.read_program(api, program_id)
    assertions.assert_viability(
        program,
        rolling_cents=constants.FIXTURE_BOUNDARY_ROLLING_CPH_CENTS,
        latest_cents=constants.FIXTURE_BOUNDARY_ROLLING_CPH_CENTS,
        composite=constants.FIXTURE_BOUNDARY_COMPOSITE,
        band=constants.FIXTURE_BOUNDARY_BAND,
    )
    assertions.assert_two_decimal_places(program["composite_score"], "composite_score")

    ctx = fixtures.carry_cycle_to_response_submitted(api, program=program)
    cycle_id = ctx.cycle_id
    cycle_version = fixtures.read_cycle(api, cycle_id)["version"]

    payload = factories.decision_payload(
        outcome="DISCONTINUATION",
        expected_cycle_version=cycle_version,
        rationale="Sustained cost pressure and thin completions",
        effective_term_index=4,
    )

    # Trigger part 1: the score is on the inclusive edge, so the band still
    # shields the program from a wind-down outcome.
    refused = api.create_decision_record(cycle_id, payload, proposer)
    validate_error(refused, ERR_OUTCOME_NOT_SUPPORTED_BY_VIABILITY, 422)

    cycle = fixtures.read_cycle(api, cycle_id)
    assert cycle["state"] == "RESPONSE_SUBMITTED"
    assert cycle["version"] == cycle_version, (
        "a refused proposal must not advance the cycle's optimistic token"
    )
    _rows, meta = validate_paginated(api.list_decision_records(coordinator))
    assert meta["total_count"] == 0

    # One more term, 50400 cents dearer, drags the rolling quotient off the
    # benchmark and the composite one hundredth below the band edge.
    fixtures.append_snapshots(
        api, program_id, [constants.FIXTURE_BOUNDARY_FOURTH_SNAPSHOT]
    )
    program = fixtures.read_program(api, program_id)
    assert program["snapshot_count"] == 4
    assertions.assert_viability(
        program,
        rolling_cents=constants.FIXTURE_BOUNDARY_ROLLING_CPH_AFTER_FOURTH,
        latest_cents=constants.FIXTURE_BOUNDARY_LATEST_CPH_AFTER_FOURTH,
        composite=constants.FIXTURE_BOUNDARY_COMPOSITE_AFTER_FOURTH,
        band=constants.FIXTURE_BOUNDARY_BAND_AFTER_FOURTH,
    )

    # Trigger part 2: the same request, now one hundredth on the other side.
    accepted = validate_success(
        api.create_decision_record(cycle_id, payload, proposer), 201
    )
    assert accepted["state"] == "PROPOSED"
    assert accepted["outcome"] == "DISCONTINUATION"
    assertions.assert_decimal_equals(
        accepted["composite_score_at_proposal"],
        constants.FIXTURE_BOUNDARY_COMPOSITE_AFTER_FOURTH,
        "composite_score_at_proposal",
    )
    assert (
        accepted["viability_band_at_proposal"]
        == constants.FIXTURE_BOUNDARY_BAND_AFTER_FOURTH
    )
    assert fixtures.read_cycle(api, cycle_id)["state"] == "DECISION_PROPOSED"


def test_empty_cohort_activation_auto_completes_at_zero_open_students(api):
    """Activation with zero open students lands on COMPLETED, not IN_EFFECT.

    §3.9 makes ACTIVATE a single request with three effects in order: the plan
    moves APPROVED -> IN_EFFECT and activated_at is stamped, every PLANNED
    guarantee whose term_index is at or below first_teach_out_term_index moves to
    OFFERED, and then — because open_student_count is 0 at the zero boundary —
    the plan auto-transitions IN_EFFECT -> COMPLETED inside the same request and
    runs §3.10's completion cascade. Both instants are stamped from the one
    clock reading, the guarantee is OFFERED rather than left PLANNED, and the
    program ends DISCONTINUED with a withdrawn catalog. A plan that stops at
    IN_EFFECT because it only tests for open students on a student write would
    leave every one of those downstream facts wrong.

    Design: Difficulty/boundary_precision_check/empty_cohort_activation_auto_completes_at_zero_open_students
    """
    coordinator = make_review_coordinator_headers()

    ctx = fixtures.setup_ratified_discontinuation(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    fixtures.acknowledge_all_notifications(api, ctx.decision["id"])

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
    assert guarantee["status"] == "PLANNED"
    assert guarantee["seats_available"] == 6

    # No students are ever enrolled: this is the empty cohort.
    fixtures.submit_plan(api, ctx)
    fixtures.approve_plan(api, ctx)
    fixtures.effectuate_decision(api, ctx)

    approved = fixtures.read_plan(api, plan_id)
    assert approved["state"] == "APPROVED"
    assertions.assert_plan_ledger(
        approved,
        guaranteed_seat_total=6,
        required_seat_total=0,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=0,
    )
    assert approved["activated_at"] is None
    assert approved["completed_at"] is None

    # Trigger: one ACTIVATE, at the zero-open-student boundary.
    activated = validate_success(
        api.transition_teach_out_plan(
            plan_id, factories.plan_transition_payload("ACTIVATE"), coordinator
        ),
        200,
    )
    assert activated["state"] == "COMPLETED", (
        "an empty cohort auto-completes inside the activation request"
    )
    assertions.assert_instant_equals(
        activated["activated_at"], RATIFICATION_INSTANT, "plan.activated_at"
    )
    assertions.assert_instant_equals(
        activated["completed_at"], RATIFICATION_INSTANT, "plan.completed_at"
    )
    assertions.assert_plan_ledger(
        activated,
        open_student_count=0,
        required_seat_total=0,
        seat_shortfall=0,
        at_risk_student_count=0,
    )

    # The guarantee cascade ran before the auto-completion, not instead of it.
    guarantees, _meta = validate_paginated(
        api.list_course_guarantees(plan_id, coordinator)
    )
    assert len(guarantees) == 1
    assert guarantees[0]["id"] == guarantee["id"]
    assert guarantees[0]["status"] == "OFFERED"
    assert guarantees[0]["seats_committed"] == 0

    # §3.10's hop 2: both program axes moved because the plan completed.
    program = fixtures.read_program(api, ctx.program_id)
    assertions.assert_axes(
        program, lifecycle_state="DISCONTINUED", catalog_status="CATALOG_WITHDRAWN"
    )
    # No appointments were ever recorded, so the waterfall reports nothing owed.
    assertions.assert_decimal_equals(program["deferred_fte"], 0.00, "deferred_fte")
    assert program["staffing_liability_cents"] == 0

    cycle = fixtures.read_cycle(api, ctx.cycle_id)
    assert cycle["state"] == "CLOSED"
    assert cycle["compliance_posture"] == "NOTICES_CLEARED"
