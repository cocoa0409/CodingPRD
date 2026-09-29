"""Cross-cutting corners: optimistic concurrency meeting derived aggregates."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import *  # noqa: F401,F403
from test_helpers.test_users import (
    make_hr_partner_headers,
    make_program_chair_headers,
    make_provost_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)

SECOND_PROVOST_USER_ID = "provost-second"


def test_a_plan_author_working_from_a_pre_ratification_view_is_told_the_program_moved(api):
    """The chair's stale program version survives every other kind of mistake.

    The ratification cascade of §3.6 mutates the program twice inside one request
    — hop 2 moves ``lifecycle_state`` and hop 3 moves ``catalog_status`` — but
    §2.4 counts the request, not the hops, so the chair's pre-ratification
    ``version`` is exactly one behind. §2.8 makes ``expected_program_version``
    non-optional on plan filing and refuses a mismatch with
    ``ERR_STALE_PROGRAM_VERSION`` (412), and §2.10 places that check at 10 —
    below body-FK resolution at 8, so an unknown ``decision_id`` answers
    ``ERR_DECISION_NOT_FOUND`` (404) even when the token is also stale, and above
    the term-horizon check at 30, so a badly ordered horizon answers on the token
    rather than with ``ERR_TEACH_OUT_HORIZON_INSUFFICIENT``. Re-reading the
    program yields the token that works, and §3.9 says the accepted filing bumps
    the program once more.

    Design: Corner/cross_cutting_complexity_layers/a_plan_author_working_from_a_pre_ratification_view_is_told_the_program_moved
    """
    ctx = fixtures.carry_cycle_to_response_submitted(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    fixtures.set_clock(api, fixtures.CLOCK_AT_RATIFICATION)
    decision = fixtures.propose_decision(api, ctx, "DISCONTINUATION")

    chair = make_program_chair_headers(ctx.program_id)
    stale_version = validate_success(api.get_program(ctx.program_id, chair))["version"]

    fixtures.ratify_decision(api, ctx)

    # check 8 (body FK) outranks check 10 (OCC): the unknown decision answers
    # first even though the token is stale too.
    validate_error(
        api.create_teach_out_plan(
            ctx.program_id,
            factories.teach_out_plan_payload(
                decision_id=constants.UNKNOWN_UUID,
                expected_program_version=stale_version,
                last_admit_term_index=3,
                first_teach_out_term_index=4,
                final_award_term_index=5,
            ),
            chair,
        ),
        ERR_DECISION_NOT_FOUND,
        404,
    )
    # check 10 outranks check 30: the stale token answers before the horizon.
    validate_error(
        api.create_teach_out_plan(
            ctx.program_id,
            factories.teach_out_plan_payload(
                decision_id=decision["id"],
                expected_program_version=stale_version,
                last_admit_term_index=4,
                first_teach_out_term_index=3,
                final_award_term_index=5,
            ),
            chair,
        ),
        ERR_STALE_PROGRAM_VERSION,
        412,
    )
    # The token alone, with everything else in order.
    validate_error(
        api.create_teach_out_plan(
            ctx.program_id,
            factories.teach_out_plan_payload(
                decision_id=decision["id"],
                expected_program_version=stale_version,
                last_admit_term_index=3,
                first_teach_out_term_index=4,
                final_award_term_index=5,
            ),
            chair,
        ),
        ERR_STALE_PROGRAM_VERSION,
        412,
    )

    fresh = validate_success(api.get_program(ctx.program_id, chair))
    assert fresh["version"] == stale_version + 1, (
        "the four-hop cascade is one request and therefore one version bump"
    )
    assertions.assert_axes(fresh, "TEACH_OUT_PENDING", "MARKETING_SUPPRESSED")

    plan = validate_success(
        api.create_teach_out_plan(
            ctx.program_id,
            factories.teach_out_plan_payload(
                decision_id=decision["id"],
                expected_program_version=fresh["version"],
                last_admit_term_index=3,
                first_teach_out_term_index=4,
                final_award_term_index=5,
            ),
            chair,
        ),
        201,
    )
    assert plan["state"] == "DRAFT"
    assert plan["plan_revision_round"] == 0
    assertions.assert_plan_ledger(
        plan,
        guaranteed_seat_total=0,
        committed_seat_total=0,
        required_seat_total=0,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=0,
        substituted_guarantee_count=0,
        waived_guarantee_count=0,
    )
    assert (
        validate_success(api.get_program(ctx.program_id, chair))["version"]
        == fresh["version"] + 1
    ), "§3.9: filing the plan bumps AcademicProgram.version by 1"


def test_a_second_proposal_needs_the_version_the_first_proposal_produced(api):
    """A proposal is a mutation of the cycle, so it invalidates its own token.

    §2.8 makes ``expected_cycle_version`` non-optional on decision proposal and
    refuses a mismatch with ``ERR_STALE_CYCLE_VERSION`` (412); §3.6 says an
    accepted proposal advances the cycle and increments ``ReviewCycle.version``
    by 1. So the token that carried the first proposal is dead the instant that
    proposal is accepted, and a second provost still holding it is refused —
    §2.10 puts the OCC check at 10, above every cycle-state check at 12, so the
    token is what answers. §2.4 then supplies the negative: the refusal is not a
    mutation, so the cycle's ``version`` is unmoved, no second decision row
    exists, and the incumbent proposal is still ``PROPOSED`` rather than
    ``WITHDRAWN``.

    Design: Corner/cross_cutting_complexity_layers/a_second_proposal_needs_the_version_the_first_proposal_produced
    """
    coordinator = make_review_coordinator_headers()
    second_provost = make_provost_headers(SECOND_PROVOST_USER_ID)
    ctx = fixtures.carry_cycle_to_response_submitted(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    version_before = fixtures.read_cycle(api, ctx.cycle_id)["version"]
    fixtures.set_clock(api, fixtures.CLOCK_AT_RATIFICATION)

    first = fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    assert first["state"] == "PROPOSED"

    # The second provost is still holding the token he read before the first
    # proposal landed.
    validate_error(
        api.create_decision_record(
            ctx.cycle_id,
            factories.decision_payload(
                outcome="IMPROVEMENT_PLAN",
                expected_cycle_version=version_before,
                rationale="A second provost prefers an improvement plan.",
                improvement_target_score=55.00,
                improvement_review_term_index=6,
                improvement_milestones=["Recruit two cohorts"],
            ),
            second_provost,
        ),
        ERR_STALE_CYCLE_VERSION,
        412,
    )

    version_after = fixtures.read_cycle(api, ctx.cycle_id)["version"]
    assert version_after == version_before + 1, (
        "the accepted first proposal bumped the cycle once; the refusal bumped nothing"
    )

    rows, meta = validate_paginated(
        api.list_decision_records(coordinator, params={"cycle_id": ctx.cycle_id})
    )
    assert meta["total_count"] == 1, "the refused proposal created no decision row"
    assert rows[0]["id"] == first["id"]
    assert rows[0]["state"] == "PROPOSED", (
        "a refused proposal may not withdraw the incumbent"
    )
    assert rows[0]["outcome"] == "DISCONTINUATION"

    # The token the first proposal produced is not stale: whatever else the
    # server makes of a second proposal, it may not answer 412, which on this
    # endpoint is ERR_STALE_CYCLE_VERSION and nothing else (§5).
    retry = api.create_decision_record(
        ctx.cycle_id,
        factories.decision_payload(
            outcome="IMPROVEMENT_PLAN",
            expected_cycle_version=version_after,
            rationale="A second provost prefers an improvement plan.",
            improvement_target_score=55.00,
            improvement_review_term_index=6,
            improvement_milestones=["Recruit two cohorts"],
        ),
        second_provost,
    )
    assert retry.status_code != 412, (
        "the version the first proposal produced is the cycle's current version"
    )


def test_one_accepted_write_bumps_the_version_once_and_a_refusal_never_does(api):
    """Six requests, four accepted, and a counter that only the four may move.

    §2.4 defines ``version`` as beginning at 1 and increasing by exactly 1 on
    every mutation of the row, which makes the counter a ledger of accepted
    writes: a snapshot append, an opened cycle and a new appointment each add 1,
    and the cycle's own two-axis side effect (§3.3 moves ``lifecycle_state``
    ``ACTIVE → UNDER_REVIEW`` in the same request) is part of that one increment,
    not a second one. The refused writes are the other half of the rule — a body
    that fails §2.10's schema check at 9 (``ERR_VALIDATION``, 422) and a catalog
    edge that fails the axis check at 13 (``ERR_CATALOG_TRANSITION_INVALID``,
    409) are not mutations, so they leave ``version``, ``snapshot_count`` and
    ``faculty_fte_baseline`` exactly where the last accepted write left them.

    Design: Corner/cross_cutting_complexity_layers/one_accepted_write_bumps_the_version_once_and_a_refusal_never_does
    """
    coordinator = make_review_coordinator_headers()
    registrar = make_registrar_headers()
    hr_partner = make_hr_partner_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    program_id = program["id"]
    assert program["version"] == 1, "§2.4: version begins at 1 on creation"

    # Accepted write 1 — a metric snapshot.
    validate_success(
        api.create_metric_snapshot(
            program_id,
            factories.metric_snapshot_payload(term_code="2024FA", term_index=1),
            coordinator,
        ),
        201,
    )
    after_snapshot = fixtures.read_program(api, program_id)
    assert after_snapshot["version"] == program["version"] + 1
    assert after_snapshot["snapshot_count"] == 1

    # Refusal 1 — the same term ordinal twice (§2.10 check 15).
    validate_error(
        api.create_metric_snapshot(
            program_id,
            factories.metric_snapshot_payload(
                term_code="2024FB",
                term_index=1,
                enrollment_headcount=31,
                credit_hours=310,
                direct_cost_cents=12100000,
                market_demand_index=43,
            ),
            coordinator,
        ),
        ERR_DUPLICATE_TERM_SNAPSHOT,
        409,
    )
    assert fixtures.read_program(api, program_id)["version"] == after_snapshot["version"]

    # Accepted write 2 — opening a cycle, which also moves the lifecycle axis.
    validate_success(
        api.create_review_cycle(program_id, factories.review_cycle_payload(), coordinator),
        201,
    )
    after_cycle = fixtures.read_program(api, program_id)
    assert after_cycle["version"] == after_snapshot["version"] + 1, (
        "one request that moves an axis is still one increment"
    )
    assertions.assert_axes(after_cycle, "UNDER_REVIEW", "LISTED")

    # Accepted write 3 — an appointment, which re-derives the whole waterfall.
    validate_success(
        api.create_faculty_appointment(
            program_id,
            factories.faculty_appointment_payload(
                faculty_number="F-ADJ-1",
                tenure_status="ADJUNCT",
                fte=0.25,
                annual_salary_cents=4000000,
            ),
            hr_partner,
        ),
        201,
    )
    after_appointment = fixtures.read_program(api, program_id)
    assert after_appointment["version"] == after_cycle["version"] + 1
    assertions.assert_decimal_equals(
        after_appointment["faculty_fte_baseline"], 0.25, "program.faculty_fte_baseline"
    )

    # Refusal 2 — an out-of-range fte (§2.10 check 9).
    validate_error(
        api.create_faculty_appointment(
            program_id,
            factories.faculty_appointment_payload(
                faculty_number="F-ADJ-2",
                tenure_status="ADJUNCT",
                fte=1.50,
                annual_salary_cents=4000000,
            ),
            hr_partner,
        ),
        ERR_VALIDATION,
        422,
    )
    # Refusal 3 — a catalog edge that skips a step (§2.6 / check 13).
    validate_error(
        api.set_catalog_status(
            program_id,
            factories.catalog_status_payload(
                "CATALOG_WITHDRAWN", "Two steps at once is not an edge."
            ),
            registrar,
        ),
        ERR_CATALOG_TRANSITION_INVALID,
        409,
    )
    after_refusals = fixtures.read_program(api, program_id)
    assert after_refusals["version"] == after_appointment["version"], (
        "neither refusal may move the counter"
    )
    assert after_refusals["snapshot_count"] == 1
    assertions.assert_decimal_equals(
        after_refusals["faculty_fte_baseline"], 0.25, "program.faculty_fte_baseline"
    )

    # Accepted write 4 — the legal catalog edge, on the axis the refusal touched.
    validate_success(
        api.set_catalog_status(
            program_id,
            factories.catalog_status_payload(
                "MARKETING_SUPPRESSED", "One legal step along the catalog axis."
            ),
            registrar,
        )
    )
    final = fixtures.read_program(api, program_id)
    assert final["version"] == after_refusals["version"] + 1
    assertions.assert_axes(final, "UNDER_REVIEW", "MARKETING_SUPPRESSED")
    assert final["snapshot_count"] == 1
    assertions.assert_decimal_equals(
        final["faculty_fte_baseline"], 0.25, "program.faculty_fte_baseline"
    )


def test_derived_aggregates_track_creation_mutation_and_removal_of_their_sources(api):
    """Adding, mutating and dropping a source all re-derive inside the request.

    §3.9 defines the plan's ledger entirely by derivation:
    ``guaranteed_seat_total`` sums ``seats_guaranteed`` over guarantees in
    ``PLANNED``, ``OFFERED`` or ``SUBSTITUTED``, which is why a substitution —
    which the PRD says leaves the seat ledger untouched — keeps its seats in the
    supply while raising ``substituted_guarantee_count``, and why a waive drops
    them out again and moves the count to ``waived_guarantee_count``. §3.7 does
    the same for the compliance counters: a hand-added notice raises the
    decision's ``notification_count`` and ``unacknowledged_notification_count``
    and drives the cycle's ``compliance_posture`` *backwards* from
    ``NOTICES_CLEARED`` to ``NOTICES_PENDING``, and its ``due_at`` is anchored on
    the decision's ``ratified_at`` plus 60 whole days for a ``FEDERAL`` agency —
    which the clock, deliberately parked elsewhere, cannot explain.

    Design: Corner/cross_cutting_complexity_layers/derived_aggregates_track_creation_mutation_and_removal_of_their_sources
    """
    coordinator = make_review_coordinator_headers()
    registrar = make_registrar_headers()

    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    decision_id = ctx.decision["id"]
    fixtures.acknowledge_all_notifications(api, decision_id)

    chair = ctx.chair_headers
    plan = fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    plan_id = plan["id"]
    first_guarantee = fixtures.add_guarantee(
        api, ctx, course_code="HIST-301", term_index=4, seats_guaranteed=5
    )
    fixtures.enrol_student(api, ctx, credits_remaining=12, max_credits_per_term=15)

    # One guarantee of five seats against one student needing four.
    assertions.assert_plan_ledger(
        fixtures.read_plan(api, plan_id),
        guaranteed_seat_total=5,
        committed_seat_total=0,
        required_seat_total=4,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=1,
        substituted_guarantee_count=0,
        waived_guarantee_count=0,
    )

    # Creation of a source raises the aggregate.
    second_guarantee = validate_success(
        api.create_course_guarantee(
            plan_id,
            factories.course_guarantee_payload(
                course_code="HIST-402", term_index=5, seats_guaranteed=4
            ),
            chair,
        ),
        201,
    )
    assert second_guarantee["status"] == "PLANNED"
    assert second_guarantee["seats_available"] == 4
    assertions.assert_plan_ledger(
        fixtures.read_plan(api, plan_id),
        guaranteed_seat_total=9,
        committed_seat_total=0,
        required_seat_total=4,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=1,
        substituted_guarantee_count=0,
        waived_guarantee_count=0,
    )

    # Mutation that changes the status but not the seats.
    substituted = validate_success(
        api.allocate_seats(
            second_guarantee["id"],
            factories.seat_substitute_payload(
                substitute_course_code="HIST-405",
                substitution_justification="An equivalent capstone seminar.",
            ),
            registrar,
        )
    )
    assert substituted["status"] == "SUBSTITUTED"
    assert substituted["seats_guaranteed"] == 4
    assertions.assert_plan_ledger(
        fixtures.read_plan(api, plan_id),
        guaranteed_seat_total=9,
        committed_seat_total=0,
        required_seat_total=4,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=1,
        substituted_guarantee_count=1,
        waived_guarantee_count=0,
    )

    # Removal from the supply side: the row survives, its seats do not.
    waived = validate_success(
        api.allocate_seats(
            second_guarantee["id"],
            factories.seat_waive_payload(waived_reason_code="NO-DEMAND"),
            registrar,
        )
    )
    assert waived["status"] == "WAIVED"
    assertions.assert_plan_ledger(
        fixtures.read_plan(api, plan_id),
        guaranteed_seat_total=5,
        committed_seat_total=0,
        required_seat_total=4,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=1,
        substituted_guarantee_count=0,
        waived_guarantee_count=1,
    )

    rows, meta = validate_paginated(api.list_course_guarantees(plan_id, registrar))
    assert meta["total_count"] == 2, "a waived guarantee is dropped from the total, not deleted"
    dropped = next(row for row in rows if row["id"] == second_guarantee["id"])
    assert dropped["status"] == "WAIVED"
    assert dropped["seats_guaranteed"] == 4
    assert dropped["substitute_course_code"] == "HIST-405"
    assert dropped["waived_reason_code"] == "NO-DEMAND"
    kept = next(row for row in rows if row["id"] == first_guarantee["id"])
    assert kept["status"] == "PLANNED"

    # The compliance counters start from a cleared posture.
    assert fixtures.read_cycle(api, ctx.cycle_id)["compliance_posture"] == "NOTICES_CLEARED"
    cleared_decision = fixtures.read_decision(api, decision_id)
    assert cleared_decision["notification_count"] == 2
    assert cleared_decision["unacknowledged_notification_count"] == 0

    # Park the clock away from the anchor so only ratified_at can explain due_at.
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    manual = validate_success(
        api.create_agency_notification(
            decision_id,
            factories.agency_notification_payload(
                agency_type="FEDERAL", agency_code="USDE-TITLE4"
            ),
            coordinator,
        ),
        201,
    )
    assert manual["status"] == "PENDING"
    assert manual["origin"] == "MANUAL"
    assert manual["sent_at"] is None
    assert manual["acknowledged_at"] is None
    assert manual["transmitted_reference"] is None
    assert manual["overdue_marked_at"] is None
    assertions.assert_instant_equals(
        manual["due_at"], "2026-11-14T10:00:00Z", "notification.due_at"
    )
    assertions.assert_instant_equals(
        manual["due_at"],
        assertions.add_days(
            fixtures.CLOCK_AT_RATIFICATION,
            constants.NOTICE_DAYS_BY_AGENCY_TYPE["FEDERAL"],
        ),
        "notification.due_at",
    )

    reblocked = fixtures.read_decision(api, decision_id)
    assert reblocked["notification_count"] == 3
    assert reblocked["unacknowledged_notification_count"] == 1
    assert fixtures.read_cycle(api, ctx.cycle_id)["compliance_posture"] == "NOTICES_PENDING", (
        "a derived posture may run backwards when a new source appears"
    )

    sent = validate_success(
        api.transition_agency_notification(
            manual["id"], factories.notification_send_payload("TX-FED-1"), coordinator
        )
    )
    assert sent["status"] == "SENT"
    assert sent["transmitted_reference"] == "TX-FED-1"
    acknowledged = validate_success(
        api.transition_agency_notification(
            manual["id"], factories.notification_acknowledge_payload(), coordinator
        )
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"

    assert fixtures.read_cycle(api, ctx.cycle_id)["compliance_posture"] == "NOTICES_CLEARED"
    final_decision = fixtures.read_decision(api, decision_id)
    assert final_decision["notification_count"] == 3
    assert final_decision["unacknowledged_notification_count"] == 0
