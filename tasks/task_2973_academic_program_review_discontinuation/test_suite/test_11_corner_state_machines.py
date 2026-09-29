"""Corner coverage for the declared state machines: initial states, cascades,
invalid transitions, idempotency replays, compensation and the two independent
program axes.
"""

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
    make_provost_ratifier_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)


def test_review_cycle_and_self_study_start_in_declared_initial_states(api):
    """Opening a cycle mints it in SELF_STUDY_OPEN, its self-study in DRAFT, and
    moves only the program's lifecycle axis.

    §3.3 fixes the cycle's initial field set, the self-study's initial field set
    and the derived ``missing_section_codes``; §2.6 keeps the catalog axis at
    LISTED while the lifecycle axis advances ACTIVE -> UNDER_REVIEW.

    Design: Corner/state_machines/review_cycle_and_self_study_start_in_declared_initial_states
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    assertions.assert_program_registration_defaults(program)
    assert program["version"] == 1

    cycle = validate_success(
        api.create_review_cycle(
            program["id"],
            factories.review_cycle_payload(
                cycle_year=2026,
                self_study_due_at="2026-09-01T00:00:00Z",
                required_section_codes=["S1", "S2"],
            ),
            make_review_coordinator_headers(),
        ),
        201,
    )
    assert cycle["state"] == "SELF_STUDY_OPEN"
    assert cycle["addendum_round"] == 0
    assert cycle["response_concurrence"] is None
    assert cycle["response_text"] is None
    assert cycle["disputed_finding_codes"] == []
    assert cycle["response_submitted_at"] is None
    assert cycle["decided_at"] is None
    assert cycle["compliance_posture"] == "NOT_APPLICABLE"
    assert cycle["version"] == 1
    assertions.assert_audit_quartet(cycle, "cycle")

    after_cycle = fixtures.read_program(api, program["id"])
    assertions.assert_axes(
        after_cycle, lifecycle_state="UNDER_REVIEW", catalog_status="LISTED"
    )
    assert after_cycle["version"] == 2, (
        "§3.3: opening a cycle increments AcademicProgram.version by exactly 1"
    )

    self_study = validate_success(
        api.create_self_study(
            cycle["id"],
            factories.self_study_payload(
                narrative="Draft narrative", section_codes=[]
            ),
            make_program_chair_headers(program["id"]),
        ),
        201,
    )
    assert self_study["state"] == "DRAFT"
    assert self_study["revision_round"] == 0
    assert self_study["submitted_at"] is None
    assert self_study["accepted_at"] is None
    assert self_study["revision_notes"] is None
    assert self_study["attestation_note"] is None
    assert self_study["missing_section_codes"] == ["S1", "S2"], (
        "§3.3: an empty section_codes list is legal at creation and the shortfall "
        "is derived immediately, in the cycle's declared order"
    )


def test_self_study_accept_cascades_cycle_to_self_study_accepted(api):
    """SUBMIT moves only the document; ACCEPT stamps accepted_at and cascades the
    parent cycle SELF_STUDY_OPEN -> SELF_STUDY_ACCEPTED.

    §3.3 declares the two-step ladder, so the cycle must still read
    SELF_STUDY_OPEN between the two calls.

    Design: Corner/state_machines/self_study_accept_cascades_cycle_to_self_study_accepted
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    cycle = fixtures.open_cycle(
        api,
        program["id"],
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1"],
    )
    self_study = fixtures.create_self_study(
        api, cycle["id"], program["id"],
        narrative="History self-study", section_codes=["S1"],
    )

    submitted = validate_success(
        api.transition_self_study(
            self_study["id"],
            factories.self_study_submit_payload(),
            make_program_chair_headers(program["id"]),
        )
    )
    assert submitted["state"] == "SUBMITTED"
    assertions.assert_instant_equals(
        submitted["submitted_at"],
        constants.CLOCK_STARTUP_DEFAULT,
        "self_study.submitted_at",
    )
    assert submitted["accepted_at"] is None
    assert (
        fixtures.read_cycle(api, cycle["id"])["state"] == "SELF_STUDY_OPEN"
    ), "§3.3: SUBMIT does not cascade to the cycle"

    accepted = validate_success(
        api.transition_self_study(
            self_study["id"],
            factories.self_study_accept_payload(),
            make_review_coordinator_headers(),
        )
    )
    assert accepted["state"] == "ACCEPTED"
    assertions.assert_instant_equals(
        accepted["accepted_at"],
        constants.CLOCK_STARTUP_DEFAULT,
        "self_study.accepted_at",
    )
    assert accepted["revision_round"] == 0
    assert accepted["missing_section_codes"] == []
    assert (
        fixtures.read_cycle(api, cycle["id"])["state"] == "SELF_STUDY_ACCEPTED"
    ), "§3.3: ACCEPT cascades the parent cycle"


def _program_with_scheduled_visit(api):
    """A HIST-BA program whose cycle is in VISIT_SCHEDULED, window [.., 17:00Z).

    Every hop is a §3.3 / §3.4 ladder step: the self-study is accepted while the
    clock still sits at the startup default, so its own deadline is open, and the
    visit window is the one the design index quotes.
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    cycle = fixtures.open_cycle(
        api,
        program["id"],
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1"],
    )
    self_study = fixtures.create_self_study(
        api, cycle["id"], program["id"],
        narrative="History self-study", section_codes=["S1"],
    )
    fixtures.accept_self_study(api, self_study["id"], program["id"])
    reviewer = fixtures.register_reviewer(
        api,
        full_name="Dr Alice Reyes",
        institution="Northfield University",
        specialty_code="HIST",
    )
    visit = fixtures.schedule_visit(
        api,
        cycle["id"],
        reviewer["id"],
        window_start_at="2026-08-20T09:00:00Z",
        window_end_at="2026-08-22T17:00:00Z",
    )
    return program, cycle, reviewer, visit


def test_visit_complete_before_window_end_rejected(api):
    """One second before window_end_at the completion is refused; at exactly
    window_end_at it succeeds.

    §2.5 declares the boundary inclusive ("a visit may be completed once the
    clock has reached or passed window_end_at; equality is permitted") and §2.10
    check 24 names ERR_VISIT_WINDOW_NOT_ELAPSED at 409.

    Design: Corner/state_machines/visit_complete_before_window_end_rejected
    """
    program, cycle, _reviewer, visit = _program_with_scheduled_visit(api)
    assert visit["state"] == "SCHEDULED"
    assert visit["completed_at"] is None

    fixtures.set_clock(api, "2026-08-22T16:59:59Z")
    validate_error(
        api.complete_reviewer_visit(visit["id"], make_review_coordinator_headers()),
        ERR_VISIT_WINDOW_NOT_ELAPSED,
        409,
    )

    refused = validate_success(
        api.get_reviewer_visit(visit["id"], make_review_coordinator_headers())
    )
    assert refused["state"] == "SCHEDULED"
    assert refused["completed_at"] is None
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "VISIT_SCHEDULED"

    fixtures.set_clock(api, "2026-08-22T17:00:00Z")
    completed = validate_success(
        api.complete_reviewer_visit(visit["id"], make_review_coordinator_headers())
    )
    assert completed["state"] == "COMPLETED"
    assertions.assert_instant_equals(
        completed["completed_at"], "2026-08-22T17:00:00Z", "visit.completed_at"
    )
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "VISIT_COMPLETED"
    assertions.assert_axes(
        fixtures.read_program(api, program["id"]),
        lifecycle_state="UNDER_REVIEW",
        catalog_status="LISTED",
    )


def test_visit_complete_twice_rejected(api):
    """Replaying the completion from COMPLETED is a 409 and never re-stamps
    completed_at to the newer clock value.

    §3.4: "completion attempted on a visit already COMPLETED or REPORTED is
    refused with ERR_VISIT_NOT_SCHEDULED"; §2.10 check 12 puts that state check
    ahead of the window check, and the refused write mutates nothing.

    Design: Corner/state_machines/visit_complete_twice_rejected
    """
    _program, cycle, _reviewer, visit = _program_with_scheduled_visit(api)

    fixtures.set_clock(api, "2026-08-23T00:00:00Z")
    completed = fixtures.complete_visit(api, visit["id"])
    assert completed["state"] == "COMPLETED"
    assertions.assert_instant_equals(
        completed["completed_at"], "2026-08-23T00:00:00Z", "visit.completed_at"
    )

    fixtures.set_clock(api, "2026-08-24T00:00:00Z")
    validate_error(
        api.complete_reviewer_visit(visit["id"], make_review_coordinator_headers()),
        ERR_VISIT_NOT_SCHEDULED,
        409,
    )

    replayed = validate_success(
        api.get_reviewer_visit(visit["id"], make_review_coordinator_headers())
    )
    assert replayed["state"] == "COMPLETED"
    assertions.assert_instant_equals(
        replayed["completed_at"],
        "2026-08-23T00:00:00Z",
        "visit.completed_at after the refused replay",
    )
    assert replayed["report_count"] == 0
    assert fixtures.read_cycle(api, cycle["id"])["state"] == "VISIT_COMPLETED"


def test_decision_effectuate_from_proposed_rejected(api):
    """EFFECTUATE is declared only from RATIFIED, so from PROPOSED the state error
    wins over the notice-acknowledgement and teach-out gates.

    §3.8: "Effectuation attempted from PROPOSED, or on an already-effectuated
    decision, is refused with ERR_DECISION_STATE_INVALID". §2.10 ranks that state
    check (12) above the compliance gate (31) and the teach-out gate (32), even
    though this decision holds no notification at all.

    Design: Corner/state_machines/decision_effectuate_from_proposed_rejected
    """
    ctx = fixtures.carry_cycle_to_response_submitted(api)
    fixtures.set_clock(api, fixtures.CLOCK_AT_RATIFICATION)
    decision = fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    assert decision["state"] == "PROPOSED"

    validate_error(
        api.transition_decision_record(
            decision["id"],
            factories.effectuate_payload(),
            make_review_coordinator_headers(),
        ),
        ERR_DECISION_STATE_INVALID,
        409,
    )

    refused = fixtures.read_decision(api, decision["id"])
    assert refused["state"] == "PROPOSED"
    assert refused["effectuated_at"] is None
    assert refused["notification_count"] == 0
    assert refused["unacknowledged_notification_count"] == 0
    assertions.assert_decimal_equals(
        refused["composite_score_at_proposal"],
        constants.FIXTURE_A_COMPOSITE_UNDERGRADUATE,
        "decision.composite_score_at_proposal",
    )
    assert refused["viability_band_at_proposal"] == constants.FIXTURE_A_BAND

    assert fixtures.read_cycle(api, ctx.cycle_id)["state"] == "DECISION_PROPOSED"
    assertions.assert_axes(
        fixtures.read_program(api, ctx.program_id),
        lifecycle_state="UNDER_REVIEW",
        catalog_status="LISTED",
    )


def test_notification_send_twice_rejected(api):
    """SEND runs from PENDING and OVERDUE only; a replay from SENT is a 409 that
    preserves the first transmission's audit trail.

    §3.7: "A transmit attempted from SENT, ACKNOWLEDGED or VOIDED ... is refused
    with ERR_NOTIFICATION_STATE_INVALID". The refused write leaves sent_at and
    transmitted_reference exactly as the first transmission stored them, and a
    SENT notice is still an unacknowledged one.

    Design: Corner/state_machines/notification_send_twice_rejected
    """
    ctx = fixtures.setup_ratified_discontinuation(api)
    assertions.assert_instant_equals(
        ctx.decision["ratified_at"],
        fixtures.CLOCK_AT_RATIFICATION,
        "decision.ratified_at",
    )
    accreditor = next(
        n for n in ctx.notifications if n["agency_type"] == "ACCREDITOR"
    )
    assert accreditor["status"] == "PENDING"

    sent = validate_success(
        api.transition_agency_notification(
            accreditor["id"],
            factories.notification_send_payload("ACC-TX-0001"),
            make_review_coordinator_headers(),
        )
    )
    assert sent["status"] == "SENT"
    assert sent["transmitted_reference"] == "ACC-TX-0001"

    fixtures.set_clock(api, "2026-09-16T10:00:00Z")
    validate_error(
        api.transition_agency_notification(
            accreditor["id"],
            factories.notification_send_payload("ACC-TX-0002"),
            make_review_coordinator_headers(),
        ),
        ERR_NOTIFICATION_STATE_INVALID,
        409,
    )

    replayed = next(
        n
        for n in fixtures.list_notifications(api, ctx.decision["id"])
        if n["id"] == accreditor["id"]
    )
    assert replayed["status"] == "SENT"
    assert replayed["transmitted_reference"] == "ACC-TX-0001", (
        "the refused replay must not overwrite the first transmission's reference"
    )
    assertions.assert_instant_equals(
        replayed["sent_at"], fixtures.CLOCK_AT_RATIFICATION, "notification.sent_at"
    )
    assertions.assert_instant_equals(
        replayed["due_at"],
        assertions.add_days(
            fixtures.CLOCK_AT_RATIFICATION,
            constants.NOTICE_DAYS_BY_AGENCY_TYPE["ACCREDITOR"],
        ),
        "notification.due_at",
    )
    assert replayed["origin"] == "AUTO_MINTED"
    assert replayed["overdue_marked_at"] is None
    assert replayed["acknowledged_at"] is None

    decision = fixtures.read_decision(api, ctx.decision["id"])
    assert decision["notification_count"] == 2
    assert decision["unacknowledged_notification_count"] == 2, (
        "§3.7: a SENT notice counts as unacknowledged"
    )
    assert (
        fixtures.read_cycle(api, ctx.cycle_id)["compliance_posture"]
        == "NOTICES_PENDING"
    )


def test_plan_approve_from_draft_rejected(api):
    """APPROVE is declared only from SUBMITTED, so from DRAFT the state error wins
    over the seat-shortfall and at-risk gates this plan would pass.

    §3.9: "A plan action attempted from a state where it is not declared is
    refused with ERR_PLAN_STATE_INVALID"; §2.10 ranks that check (12) above the
    seat gate (34) and the at-risk gate (35).

    Design: Corner/state_machines/plan_approve_from_draft_rejected
    """
    ctx = fixtures.setup_ratified_discontinuation(api)
    plan = fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    assert plan["state"] == "DRAFT"

    validate_error(
        api.transition_teach_out_plan(
            plan["id"],
            factories.plan_transition_payload("APPROVE"),
            make_provost_ratifier_headers(),
        ),
        ERR_PLAN_STATE_INVALID,
        409,
    )

    refused = fixtures.read_plan(api, plan["id"])
    assert refused["state"] == "DRAFT"
    assert refused["approved_at"] is None
    assert refused["plan_revision_round"] == 0
    assertions.assert_plan_ledger(
        refused,
        guaranteed_seat_total=0,
        committed_seat_total=0,
        required_seat_total=0,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=0,
    )


def test_appointment_confirm_reassignment_from_assigned_rejected(api):
    """CONFIRM_REASSIGNMENT and WITHDRAW_REASSIGNMENT are declared only from
    REASSIGNMENT_PROPOSED; from ASSIGNED both are 409s that move no FTE.

    §3.11: "An action that is not declared from the appointment's current state —
    a reassignment confirmation from ASSIGNED ... — is refused with
    ERR_APPOINTMENT_STATE_INVALID", and §2.11 keeps every bucket where it was
    because no transition happened.

    Design: Corner/state_machines/appointment_confirm_reassignment_from_assigned_rejected
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    appointment = fixtures.create_appointment(
        api,
        program["id"],
        faculty_number="F-TT-1",
        tenure_status="TENURE_TRACK",
        fte=1.00,
        annual_salary_cents=9000000,
    )
    assert appointment["state"] == "ASSIGNED"

    validate_error(
        api.transition_faculty_appointment(
            appointment["id"],
            factories.confirm_reassignment_payload(),
            make_hr_partner_headers(),
        ),
        ERR_APPOINTMENT_STATE_INVALID,
        409,
    )
    validate_error(
        api.transition_faculty_appointment(
            appointment["id"],
            factories.withdraw_reassignment_payload(),
            make_hr_partner_headers(),
        ),
        ERR_APPOINTMENT_STATE_INVALID,
        409,
    )

    rows, _meta = validate_paginated(
        api.list_faculty_appointments(program["id"], make_hr_partner_headers())
    )
    refused = next(row for row in rows if row["id"] == appointment["id"])
    assert refused["state"] == "ASSIGNED"
    assert refused["reassigned_to_department_code"] is None
    assert refused["reassignment_withdraw_count"] == 0

    after = fixtures.read_program(api, program["id"])
    assertions.assert_waterfall(
        after,
        baseline=1.00,
        active=1.00,
        reassigned=0.00,
        separated=0.00,
        assigned_pool=1.00,
    )
    assertions.assert_fte_partition(after, rows)


def test_program_lifecycle_and_catalog_axes_move_independently(api):
    """The registrar drives the catalog axis and reverses it while the lifecycle
    axis sits at ACTIVE; opening a cycle then moves the lifecycle axis alone.

    §2.6 declares the two axes independent on the same row, declares
    LISTED -> MARKETING_SUPPRESSED and its reverse edge, and states that every
    catalog edge "increments AcademicProgram.version by 1 and touches nothing
    else"; §3.3 adds the third increment when the cycle opens.

    Design: Corner/state_machines/program_lifecycle_and_catalog_axes_move_independently
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    assert program["version"] == 1
    assertions.assert_axes(program, lifecycle_state="ACTIVE", catalog_status="LISTED")

    suppressed = validate_success(
        api.set_catalog_status(
            program["id"],
            factories.catalog_status_payload(
                "MARKETING_SUPPRESSED",
                suppression_note="Pre-emptive suppression pending review.",
            ),
            make_registrar_headers(),
        )
    )
    assertions.assert_axes(
        suppressed, lifecycle_state="ACTIVE", catalog_status="MARKETING_SUPPRESSED"
    )
    assert suppressed["version"] == 2

    relisted = validate_success(
        api.set_catalog_status(
            program["id"],
            factories.catalog_status_payload("LISTED"),
            make_registrar_headers(),
        )
    )
    assertions.assert_axes(
        relisted, lifecycle_state="ACTIVE", catalog_status="LISTED"
    )
    assert relisted["version"] == 3
    assert relisted["catalog_status_pre_decision"] is None

    fixtures.open_cycle(
        api,
        program["id"],
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1"],
    )
    after_cycle = fixtures.read_program(api, program["id"])
    assertions.assert_axes(
        after_cycle, lifecycle_state="UNDER_REVIEW", catalog_status="LISTED"
    )
    assert after_cycle["version"] == 4
    assert after_cycle["catalog_status_pre_decision"] is None, (
        "§2.6: only a ratification cascade captures catalog_status_pre_decision"
    )
    assertions.assert_viability(
        after_cycle,
        rolling_cents=None,
        latest_cents=None,
        composite=None,
        band="INSUFFICIENT_DATA",
    )


def test_student_withdraw_releases_seats_and_syncs_plan_ledger(api):
    """WITHDRAW from PENDING releases the student's whole holding in one hop and
    drops them out of every plan aggregate, without auto-completing a DRAFT plan.

    §3.10: withdrawal "release[s] every seat the student holds: each affected
    guarantee's seats_committed drops by the count that student held on it, and
    the student's committed_seat_count becomes 0", and re-derives
    required_seat_total, seat_shortfall, open_student_count and
    at_risk_student_count. The auto-completion edge is declared IN_EFFECT ->
    COMPLETED only, so a DRAFT plan reaching open_student_count 0 stays DRAFT.

    Design: Corner/state_machines/student_withdraw_releases_seats_and_syncs_plan_ledger
    """
    ctx = fixtures.setup_ratified_discontinuation(api)
    plan = fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    guarantee = fixtures.add_guarantee(
        api, ctx, course_code="HIST-401", term_index=4, seats_guaranteed=3
    )
    student = fixtures.enrol_student(
        api, ctx, student_number="S-0001", credits_remaining=12, max_credits_per_term=15
    )
    validate_success(
        api.allocate_seats(
            guarantee["id"],
            factories.seat_commit_payload(student["id"], 3),
            make_registrar_headers(),
        )
    )

    guarantees, _gmeta = validate_paginated(
        api.list_course_guarantees(plan["id"], make_registrar_headers())
    )
    students, _smeta = validate_paginated(
        api.list_displaced_students(plan["id"], make_registrar_headers())
    )
    before_guarantee = next(g for g in guarantees if g["id"] == guarantee["id"])
    before_student = next(s for s in students if s["id"] == student["id"])
    assert before_guarantee["seats_committed"] == 3
    assert before_guarantee["seats_available"] == 0
    assert before_student["committed_seat_count"] == 3
    assert before_student["required_seat_count"] == 4
    assertions.assert_seat_conservation(guarantees, students)
    assertions.assert_plan_ledger(
        fixtures.read_plan(api, plan["id"]),
        guaranteed_seat_total=3,
        committed_seat_total=3,
        required_seat_total=4,
        seat_shortfall=1,
        open_student_count=1,
    )

    withdrawn = validate_success(
        api.record_student_progress(
            student["id"],
            factories.student_withdraw_payload("TRANSFERRED"),
            make_registrar_headers(),
        )
    )
    assert withdrawn["advising_status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_reason_code"] == "TRANSFERRED"
    assert withdrawn["committed_seat_count"] == 0

    guarantees, _gmeta = validate_paginated(
        api.list_course_guarantees(plan["id"], make_registrar_headers())
    )
    students, _smeta = validate_paginated(
        api.list_displaced_students(plan["id"], make_registrar_headers())
    )
    after_guarantee = next(g for g in guarantees if g["id"] == guarantee["id"])
    assert after_guarantee["seats_committed"] == 0
    assert after_guarantee["seats_available"] == 3
    assert after_guarantee["status"] == "PLANNED", (
        "§3.10: releasing a withdrawn student's seats leaves the guarantee's own "
        "status axis untouched"
    )
    assertions.assert_seat_conservation(guarantees, students)

    after_plan = fixtures.read_plan(api, plan["id"])
    assertions.assert_plan_ledger(
        after_plan,
        guaranteed_seat_total=3,
        committed_seat_total=0,
        required_seat_total=0,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=0,
    )
    assert after_plan["state"] == "DRAFT", (
        "§3.10: open_student_count reaching 0 auto-completes a plan only from "
        "IN_EFFECT"
    )
    assert after_plan["completed_at"] is None
    assertions.assert_axes(
        fixtures.read_program(api, ctx.program_id),
        lifecycle_state="TEACH_OUT_PENDING",
        catalog_status="MARKETING_SUPPRESSED",
    )


def test_rescind_compensates_every_ratification_side_effect(api):
    """RESCIND unwinds the whole ratification cascade hop for hop.

    §3.8: every notification in PENDING, SENT or OVERDUE moves to VOIDED, the
    program returns to UNDER_REVIEW with catalog_status "restored verbatim from
    catalog_status_pre_decision, which is then set back to null", every linked
    DRAFT / SUBMITTED / APPROVED plan moves to SUPERSEDED, and the cycle moves
    DECIDED -> RESPONSE_SUBMITTED clearing decided_at. §3.7 excludes VOIDED rows
    from both notification counters, which returns compliance_posture to
    NOT_APPLICABLE.

    Design: Corner/state_machines/rescind_compensates_every_ratification_side_effect
    """
    program = fixtures.create_nonviable_program(
        api, code="HIST-BA", name="History BA", degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    appointment = fixtures.create_appointment(
        api,
        program["id"],
        faculty_number="F-ADJ-1",
        tenure_status="ADJUNCT",
        fte=0.25,
        annual_salary_cents=4000000,
    )
    ctx = fixtures.carry_cycle_to_response_submitted(api, program=program)
    fixtures.set_clock(api, fixtures.CLOCK_AT_RATIFICATION)
    decision = fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    fixtures.ratify_decision(api, ctx)
    assert len(ctx.notifications) == 2
    accreditor = next(
        n for n in ctx.notifications if n["agency_type"] == "ACCREDITOR"
    )
    other = next(n for n in ctx.notifications if n["id"] != accreditor["id"])
    validate_success(
        api.transition_agency_notification(
            accreditor["id"],
            factories.notification_send_payload("ACC-TX-0001"),
            make_review_coordinator_headers(),
        )
    )
    ratified_program = fixtures.read_program(api, ctx.program_id)
    assertions.assert_axes(
        ratified_program,
        lifecycle_state="TEACH_OUT_PENDING",
        catalog_status="MARKETING_SUPPRESSED",
    )
    assert ratified_program["catalog_status_pre_decision"] == "LISTED"
    plan = fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    assert plan["state"] == "DRAFT"

    rescinded = validate_success(
        api.transition_decision_record(
            decision["id"],
            factories.rescind_payload("New enrolment data supersedes the review."),
            make_provost_ratifier_headers(),
        )
    )
    assert rescinded["state"] == "RESCINDED"
    assert rescinded["rescission_reason"] == (
        "New enrolment data supersedes the review."
    )

    notifications = fixtures.list_notifications(api, decision["id"])
    by_id = {n["id"]: n for n in notifications}
    assert by_id[accreditor["id"]]["status"] == "VOIDED"
    assert by_id[other["id"]]["status"] == "VOIDED"
    assert by_id[accreditor["id"]]["transmitted_reference"] == "ACC-TX-0001", (
        "a VOIDED notice is not deleted and keeps its transmission audit trail"
    )
    assertions.assert_instant_equals(
        by_id[accreditor["id"]]["sent_at"],
        fixtures.CLOCK_AT_RATIFICATION,
        "voided notification.sent_at",
    )

    after_decision = fixtures.read_decision(api, decision["id"])
    assert after_decision["notification_count"] == 0
    assert after_decision["unacknowledged_notification_count"] == 0

    after_cycle = fixtures.read_cycle(api, ctx.cycle_id)
    assert after_cycle["state"] == "RESPONSE_SUBMITTED"
    assert after_cycle["decided_at"] is None
    assert after_cycle["compliance_posture"] == "NOT_APPLICABLE"

    after_program = fixtures.read_program(api, ctx.program_id)
    assertions.assert_axes(
        after_program, lifecycle_state="UNDER_REVIEW", catalog_status="LISTED"
    )
    assert after_program["catalog_status_pre_decision"] is None

    assert fixtures.read_plan(api, plan["id"])["state"] == "SUPERSEDED"

    rows, _meta = validate_paginated(
        api.list_faculty_appointments(ctx.program_id, make_hr_partner_headers())
    )
    assert next(r for r in rows if r["id"] == appointment["id"])["state"] == "ASSIGNED"
    assertions.assert_waterfall(
        after_program,
        baseline=0.25,
        assigned_pool=0.25,
        retained=0.00,
        reducible=0.25,
        active=0.25,
        reassigned=0.00,
        separated=0.00,
    )


def test_retain_and_propose_reassignment_conditional_guards(api):
    """One validation row, two different causes: RETAIN without an APPROVED or
    IN_EFFECT plan, and a reassignment proposal naming the program's own
    department.

    §3.11: retention "requires a teach-out plan on the appointment's program to be
    in APPROVED or IN_EFFECT; without one it is refused with
    ERR_REASSIGNMENT_TARGET_INVALID", and a proposal's
    reassigned_to_department_code "must differ from the program's own
    department_code". §5 puts that identifier at 422. Neither refusal may shift a
    unit of FTE; the accepted proposal moves load out of assigned_pool_fte while
    §2.11 keeps it inside active_fte_total.

    Design: Corner/state_machines/retain_and_propose_reassignment_conditional_guards
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", degree_level="UNDERGRADUATE",
        department_code="HIST",
    )
    appointment = fixtures.create_appointment(
        api,
        program["id"],
        faculty_number="F-ADJ-1",
        tenure_status="ADJUNCT",
        fte=0.25,
        annual_salary_cents=4000000,
    )

    validate_error(
        api.transition_faculty_appointment(
            appointment["id"],
            factories.retain_payload(),
            make_hr_partner_headers(),
        ),
        ERR_REASSIGNMENT_TARGET_INVALID,
        422,
    )
    validate_error(
        api.transition_faculty_appointment(
            appointment["id"],
            factories.propose_reassignment_payload("HIST"),
            make_hr_partner_headers(),
        ),
        ERR_REASSIGNMENT_TARGET_INVALID,
        422,
    )

    rows, _meta = validate_paginated(
        api.list_faculty_appointments(program["id"], make_hr_partner_headers())
    )
    refused = next(row for row in rows if row["id"] == appointment["id"])
    assert refused["state"] == "ASSIGNED"
    assert refused["reassigned_to_department_code"] is None
    assertions.assert_waterfall(
        fixtures.read_program(api, program["id"]),
        baseline=0.25,
        assigned_pool=0.25,
        active=0.25,
    )

    proposed = validate_success(
        api.transition_faculty_appointment(
            appointment["id"],
            factories.propose_reassignment_payload("CLAS"),
            make_hr_partner_headers(),
        )
    )
    assert proposed["state"] == "REASSIGNMENT_PROPOSED"
    assert proposed["reassigned_to_department_code"] == "CLAS"

    after = fixtures.read_program(api, program["id"])
    assertions.assert_waterfall(
        after,
        baseline=0.25,
        assigned_pool=0.00,
        retained=0.00,
        reducible=0.00,
        active=0.25,
        reassigned=0.00,
        separated=0.00,
        liability_cents=0,
    )
