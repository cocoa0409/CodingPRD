"""SCAFFOLD §1.8 rule_id priority_pair_validation_conflict: §2.10 decides which of two faults surfaces."""

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
    make_provost_ratifier_headers,
    make_review_coordinator_headers,
)

RATIFICATION_INSTANT = "2026-09-15T10:00:00Z"


def test_self_study_state_check_beats_closed_deadline_window(api):
    """A late SUBMIT on an already-submitted document reports the state fault.

    §2.10 puts the entity state check at step 12 and the business-temporal window
    check at step 19. A second SUBMIT on a document already in SUBMITTED, issued
    after the cycle's self_study_due_at has passed, violates both at once, so only
    ERR_SELF_STUDY_NOT_DRAFT may surface. An implementation that evaluates the
    deadline first would answer ERR_SELF_STUDY_WINDOW_CLOSED.

    Design: Difficulty/priority_pair_validation_conflict/self_study_state_check_beats_closed_deadline_window
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    program_id = program["id"]
    chair = make_program_chair_headers(program_id)

    cycle = fixtures.open_cycle(
        api,
        program_id,
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1"],
    )
    self_study = fixtures.create_self_study(
        api,
        cycle["id"],
        program_id,
        narrative="Self-study narrative",
        section_codes=["S1"],
    )
    submitted = validate_success(
        api.transition_self_study(
            self_study["id"], factories.self_study_submit_payload(), chair
        )
    )
    assert submitted["state"] == "SUBMITTED"
    assertions.assert_instant_equals(
        submitted["submitted_at"],
        constants.CLOCK_STARTUP_DEFAULT,
        "self_study.submitted_at",
    )

    # One day past the deadline, so the window rule is violated too.
    fixtures.set_clock(api, "2026-09-02T00:00:00Z")

    # Trigger: both faults are live on this one request.
    refused = api.transition_self_study(
        self_study["id"], factories.self_study_submit_payload(), chair
    )
    error = validate_error(refused, ERR_SELF_STUDY_NOT_DRAFT, 409)
    assert error["error_id"] != ERR_SELF_STUDY_WINDOW_CLOSED, (
        "the deadline fault is real but lower priority than the state fault"
    )

    rows, _meta = validate_paginated(api.list_self_studies(cycle["id"], coordinator))
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "SUBMITTED"
    assert row["revision_round"] == 0
    assertions.assert_instant_equals(
        row["submitted_at"], constants.CLOCK_STARTUP_DEFAULT, "self_study.submitted_at"
    )
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "SELF_STUDY_OPEN"


def test_agency_compliance_check_beats_severance_budget_check(api):
    """An EFFECTUATE that breaches both the notice rule and the cap reports the notice.

    §2.10 puts the agency-compliance check at step 31 and the severance-budget
    check at step 33. At trigger time both AUTO_MINTED notices are still PENDING
    (unacknowledged_notification_count 2) and the waterfall has already stalled on
    the cap (deferred_fte 0.67 against a cap of 5100000 cents), so only
    ERR_AGENCY_NOTICE_NOT_ACKNOWLEDGED may surface. Both violations remain in place
    after the refusal, and nothing is partially effectuated.

    Design: Difficulty/priority_pair_validation_conflict/agency_compliance_check_beats_severance_budget_check
    """
    coordinator = make_review_coordinator_headers()
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
    tenure_track = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-TT-1",
        tenure_status="TENURE_TRACK",
        fte=1.00,
        annual_salary_cents=9000000,
    )
    tenured = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-TEN-1",
        tenure_status="TENURED",
        fte=1.00,
        annual_salary_cents=12000000,
    )

    ctx = fixtures.carry_cycle_to_response_submitted(
        api, program=fixtures.read_program(api, program_id)
    )
    fixtures.set_clock(api, RATIFICATION_INSTANT)
    fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    fixtures.ratify_decision(api, ctx)
    # Both notices are deliberately left in PENDING: never sent, never acknowledged.

    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    plan_id = ctx.plan["id"]
    # Eight guarantees of five seats each: 8 sections / 6 sections-per-fte gives a
    # retained figure of 1.33 after §2.7's two-decimal half-up rounding.
    for index in range(8):
        fixtures.add_guarantee(
            api,
            ctx,
            course_code=f"HIST-4{index + 1:02d}",
            term_index=4 if index < 4 else 5,
            seats_guaranteed=5,
        )
    fixtures.submit_plan(api, ctx)
    fixtures.approve_plan(api, ctx)

    # Both preconditions really are violated before the trigger runs.
    before_decision = fixtures.read_decision(api, ctx.decision["id"])
    assert before_decision["unacknowledged_notification_count"] == 2
    before_program = fixtures.read_program(api, program_id)
    assertions.assert_waterfall(
        before_program,
        baseline=3.25,
        assigned_pool=3.25,
        retained=1.33,
        reducible=1.92,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=1857534,
        deferred=0.67,
    )

    # Trigger: the two faults compete on one request.
    refused = api.transition_decision_record(
        ctx.decision["id"], factories.effectuate_payload(), coordinator
    )
    error = validate_error(refused, ERR_AGENCY_NOTICE_NOT_ACKNOWLEDGED, 409)
    assert error["error_id"] != ERR_SEVERANCE_CAP_EXCEEDED, (
        "the cap breach is real but lower priority than the compliance failure"
    )

    # Both violations survive the refusal, and nothing was partially applied.
    decision = fixtures.read_decision(api, ctx.decision["id"])
    assert decision["state"] == "RATIFIED"
    assert decision["effectuated_at"] is None
    assert decision["unacknowledged_notification_count"] == 2

    program = fixtures.read_program(api, program_id)
    assertions.assert_axes(
        program,
        lifecycle_state="TEACH_OUT_PENDING",
        catalog_status="MARKETING_SUPPRESSED",
    )
    assertions.assert_waterfall(
        program,
        retained=1.33,
        reducible=1.92,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=1857534,
        deferred=0.67,
    )

    appointments = fixtures.list_appointments(api, program_id)
    positions = {row["id"]: row["reduction_sequence_position"] for row in appointments}
    assert positions[adjunct["id"]] == 1
    assert positions[non_tenure_track["id"]] == 2
    assert positions[tenure_track["id"]] is None
    assert positions[tenured["id"]] is None

    plan = fixtures.read_plan(api, plan_id)
    assert plan["state"] == "APPROVED"
    assertions.assert_plan_ledger(plan, guaranteed_seat_total=40, seat_shortfall=0)
