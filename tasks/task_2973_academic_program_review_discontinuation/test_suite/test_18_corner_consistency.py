"""Read-after-write consistency: every derived figure and every cascade hop is
visible in the response that caused it and in the very next read."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import *  # noqa: F401,F403
from test_helpers.test_users import (
    make_hr_partner_headers,
    make_provost_ratifier_headers,
    make_review_coordinator_headers,
)


def test_every_derived_effect_is_visible_in_the_response_that_caused_it(api):
    """Nothing in this API lags behind the write that caused it.

    §2.7 recomputes every derived figure from scratch inside the write that can
    change its inputs, so the snapshot append returns its own per-term
    diagnostic, the third append leaves the program already banded, and the
    appointment create returns a row the staffing waterfall has already placed at
    reduction position 1. Each following read agrees with the write response, and
    reads never mutate.

    Note on the arithmetic: §3.2 nulls `composite_score` and bands
    INSUFFICIENT_DATA only for a program with **no** observations at all, and
    §3.1 makes the rolling window "every observation it has" when there are fewer
    than three. One observation therefore yields a real score: a flat window
    gives enrollment 50.00, completion 33.3333..., demand 42 and efficiency
    75.00, whose weighted sum 49.2333... is ceilinged by the small-program rule
    (30 heads) to 39.99, which bands NONVIABLE.

    Design: Corner/consistency_model/every_derived_effect_is_visible_in_the_response_that_caused_it
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
    assertions.assert_program_registration_defaults(program)

    # --- the first append computes its diagnostic in the same request ------
    first_snapshot = validate_success(
        api.create_metric_snapshot(
            program_id,
            factories.metric_snapshot_payload(
                term_code="2024FA",
                term_index=1,
                enrollment_headcount=30,
                credit_hours=300,
                direct_cost_cents=12000000,
                completions_count=4,
                market_demand_index=42,
            ),
            make_review_coordinator_headers(),
        ),
        201,
    )
    assert first_snapshot["cost_per_credit_hour_cents"] == 40000, (
        "12000000 / 300, computed inside the create"
    )

    after_first = validate_success(
        api.get_program(program_id, make_review_coordinator_headers())
    )
    assert after_first["snapshot_count"] == 1
    assertions.assert_viability(after_first, 40000, 40000, 39.99, "NONVIABLE")

    # --- terms 2 and 3 ----------------------------------------------------
    fixtures.append_snapshots(
        api,
        program_id,
        [
            {
                "term_code": "2025SP",
                "term_index": 2,
                "enrollment_headcount": 24,
                "credit_hours": 240,
                "direct_cost_cents": 11000000,
                "completions_count": 3,
                "market_demand_index": 40,
            },
            {
                "term_code": "2025FA",
                "term_index": 3,
                "enrollment_headcount": 20,
                "credit_hours": 200,
                "direct_cost_cents": 11000000,
                "completions_count": 2,
                "market_demand_index": 42,
            },
        ],
    )

    after_third = validate_success(
        api.get_program(program_id, make_review_coordinator_headers())
    )
    assert after_third["snapshot_count"] == 3
    assertions.assert_viability(
        after_third,
        constants.FIXTURE_A_ROLLING_CPH_CENTS,
        constants.FIXTURE_A_LATEST_CPH_CENTS,
        constants.FIXTURE_A_COMPOSITE_UNDERGRADUATE,
        constants.FIXTURE_A_BAND,
    )
    version_after_third = after_third["version"]

    # --- the appointment create runs the whole waterfall inside itself -----
    created_appointment = validate_success(
        api.create_faculty_appointment(
            program_id,
            factories.faculty_appointment_payload(
                faculty_number="F-ADJ-1",
                tenure_status="ADJUNCT",
                fte=0.25,
                annual_salary_cents=4000000,
            ),
            make_hr_partner_headers(),
        ),
        201,
    )
    assert created_appointment["state"] == "ASSIGNED"
    assert created_appointment["notice_pay_cents"] == 82192, (
        "round_half_up(4000000 x 0.25 x 30 / 365)"
    )
    assert created_appointment["reduction_sequence_position"] == 1, (
        "the waterfall ran inside the create, so the row is already queued"
    )

    rows, appointment_meta = validate_paginated(
        api.list_faculty_appointments(program_id, make_hr_partner_headers())
    )
    assert appointment_meta["total_count"] == 1
    assert rows[0] == created_appointment, (
        "the list channel agrees with the create response field for field"
    )

    after_appointment = validate_success(
        api.get_program(program_id, make_hr_partner_headers())
    )
    assertions.assert_waterfall(
        after_appointment,
        baseline=0.25,
        active=0.25,
        assigned_pool=0.25,
        retained=0.00,
        reducible=0.25,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=82192,
        deferred=0.00,
    )
    assert after_appointment["version"] == version_after_third + 1, (
        "§2.4: creating an appointment bumps AcademicProgram.version by exactly 1"
    )

    snapshots, snapshot_meta = validate_paginated(
        api.list_metric_snapshots(program_id, make_review_coordinator_headers())
    )
    assert snapshot_meta["total_count"] == 3, "reads never mutate"
    assert len(snapshots) == 3


def test_a_cascade_is_visible_on_the_parent_in_the_very_next_read(api):
    """The ratification cascade crosses four aggregates and lags on none of them.

    One write on a DecisionRecord moves the ReviewCycle, the AcademicProgram, that
    program's catalog axis and a pair of AgencyNotification rows that did not
    exist a moment earlier — and §3.6's hops are all readable on the very next
    request, including the `compliance_posture` derived over rows the cascade
    itself minted. No effect is deferred to the compliance sweep: the notices
    already carry their §3.7 deadlines.

    Note on the catalog axis: §3.6 hop 3 moves it LISTED -> MARKETING_SUPPRESSED
    at ratification; MARKETING_SUPPRESSED -> ADMISSIONS_CLOSED is an effectuation
    cascade (§2.6, §3.8) and has not fired yet at this point.

    Design: Corner/consistency_model/a_cascade_is_visible_on_the_parent_in_the_very_next_read
    """
    ctx = fixtures.carry_cycle_to_response_submitted(api)
    fixtures.set_clock(api, fixtures.CLOCK_AT_RATIFICATION)
    decision = fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    assert decision["state"] == "PROPOSED"

    # --- the one write that fires the whole cascade ------------------------
    ratified = validate_success(
        api.transition_decision_record(
            decision["id"],
            factories.ratify_payload(ratification_note="Board ratified."),
            make_provost_ratifier_headers(),
        )
    )
    assert ratified["state"] == "RATIFIED"
    assertions.assert_instant_equals(
        ratified["ratified_at"], fixtures.CLOCK_AT_RATIFICATION, "ratified_at"
    )
    assert ratified["notification_count"] == 2, (
        "the minted children are already counted in the response that minted them"
    )
    assert ratified["unacknowledged_notification_count"] == 2

    # --- the cycle --------------------------------------------------------
    cycle = validate_success(
        api.get_review_cycle(ctx.cycle_id, make_provost_ratifier_headers())
    )
    assert cycle["state"] == "DECIDED"
    assertions.assert_instant_equals(
        cycle["decided_at"], ratified["ratified_at"], "cycle.decided_at"
    )
    assert cycle["compliance_posture"] == "NOTICES_PENDING"

    # --- the program, on both axes ----------------------------------------
    program = validate_success(
        api.get_program(ctx.program_id, make_provost_ratifier_headers())
    )
    assertions.assert_axes(
        program,
        lifecycle_state="TEACH_OUT_PENDING",
        catalog_status="MARKETING_SUPPRESSED",
    )
    assert program["catalog_status_pre_decision"] == "LISTED", (
        "the cascade recorded the pre-decision catalog value so a rescission can "
        "restore it"
    )

    # --- the notifications the cascade minted -----------------------------
    notices, notice_meta = validate_paginated(
        api.list_agency_notifications(decision["id"], make_provost_ratifier_headers())
    )
    assert notice_meta["total_count"] == 2
    accreditor = next(n for n in notices if n["agency_type"] == "ACCREDITOR")
    state_agency = next(n for n in notices if n["agency_type"] == "STATE_AGENCY")
    assert accreditor["agency_code"] == constants.AUTO_MINTED_ACCREDITOR_CODE
    assert accreditor["status"] == "PENDING"
    assert accreditor["origin"] == "AUTO_MINTED"
    assertions.assert_instant_equals(
        accreditor["due_at"],
        assertions.add_days(ratified["ratified_at"], 30),
        "ACCREDITOR.due_at",
    )
    assertions.assert_instant_equals(
        accreditor["due_at"], "2026-10-15T10:00:00Z", "ACCREDITOR.due_at"
    )
    assert state_agency["agency_code"] == constants.AUTO_MINTED_STATE_AGENCY_CODE
    assert state_agency["status"] == "PENDING"
    assert state_agency["origin"] == "AUTO_MINTED"
    assertions.assert_instant_equals(
        state_agency["due_at"],
        assertions.add_days(ratified["ratified_at"], 45),
        "STATE_AGENCY.due_at",
    )
    assertions.assert_instant_equals(
        state_agency["due_at"], "2026-10-30T10:00:00Z", "STATE_AGENCY.due_at"
    )

    # --- nothing was completed lazily between the two requests ------------
    reread = validate_success(
        api.get_decision_record(decision["id"], make_provost_ratifier_headers())
    )
    assert reread == ratified, (
        "the decision read agrees with the RATIFY response field for field"
    )
