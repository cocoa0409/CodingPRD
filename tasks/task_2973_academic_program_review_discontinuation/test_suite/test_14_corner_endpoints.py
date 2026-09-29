"""Endpoint-shape corners: action returns, bulk sweeps, partial updates, computed reads and cross-reference links."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import *  # noqa: F401,F403
from test_helpers.test_users import (
    make_external_reviewer_headers,
    make_hr_partner_headers,
    make_program_chair_headers,
    make_provost_proposer_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)

# §3.7's sweep is run from an instant well past the two accreditor deadlines but
# short of the federal one, so the sweep's three-way selectivity is observable.
SWEEP_CLOCK = "2026-11-01T00:00:00Z"


def test_catalog_status_action_returns_the_whole_program_and_moves_one_axis(api):
    """The catalog action returns the whole program row and moves only one axis.

    §2.2 makes every successful response return the affected resource, §2.6 keeps
    the two program axes independent, §3.11's hop 3 is the only writer of
    catalog_status_pre_decision, and check 13 refuses a repeat of the same target
    because the catalog machine declares no self-loop.

    Design: Corner/endpoints/catalog_status_action_returns_the_whole_program_and_moves_one_axis
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api,
        code="GEOG-BA",
        name="Geography BA",
        degree_level="UNDERGRADUATE",
        department_code="GEOG",
    )
    v0 = program["version"]
    registrar = make_registrar_headers()

    moved = validate_success(
        api.set_catalog_status(
            program["id"],
            factories.catalog_status_payload(
                "MARKETING_SUPPRESSED",
                suppression_note="Marketing paused pending the departmental review.",
            ),
            registrar,
        )
    )

    # A full AcademicProgram row came back, not a bare acknowledgement.
    assert moved["id"] == program["id"]
    assert moved["code"] == "GEOG-BA"
    assert moved["name"] == "Geography BA"
    assert moved["degree_level"] == "UNDERGRADUATE"
    assert moved["department_code"] == "GEOG"
    for field in (
        "lifecycle_state",
        "catalog_status",
        "catalog_status_pre_decision",
        "snapshot_count",
        "composite_score",
        "viability_band",
        "cost_per_credit_hour_rolling_cents",
        "cost_per_credit_hour_latest_cents",
        "faculty_fte_baseline",
        "active_fte_total",
        "assigned_pool_fte",
        "retained_teach_out_fte",
        "reducible_fte",
        "deferred_fte",
        "severance_budget_cap_cents",
        "staffing_liability_cents",
        "version",
    ):
        assert field in moved, f"the action response must carry {field}"
    assertions.assert_audit_quartet(moved, "program")

    # Exactly one axis moved.
    assertions.assert_axes(
        moved, lifecycle_state="ACTIVE", catalog_status="MARKETING_SUPPRESSED"
    )
    assert moved["catalog_status_pre_decision"] is None, (
        "the manual registrar action does not stash a restore point"
    )
    assertions.assert_version_is(moved, v0 + 1, "program")
    assertions.assert_instant_equals(
        moved["updated_at"], constants.CLOCK_STARTUP_DEFAULT, "program.updated_at"
    )

    # The derived viability block is the empty-data case, and it rode along.
    assert moved["snapshot_count"] == 0
    assertions.assert_viability(moved, None, None, None, "INSUFFICIENT_DATA")

    repeat = api.set_catalog_status(
        program["id"],
        factories.catalog_status_payload("MARKETING_SUPPRESSED"),
        registrar,
    )
    validate_error(repeat, ERR_CATALOG_TRANSITION_INVALID, 409)

    after = fixtures.read_program(api, program["id"])
    assertions.assert_axes(
        after, lifecycle_state="ACTIVE", catalog_status="MARKETING_SUPPRESSED"
    )
    assertions.assert_version_is(after, v0 + 1, "program after the refusal")


def test_one_compliance_sweep_marks_every_due_pending_notice_at_once(api):
    """One unparameterised sweep marks every eligible notice and nothing else.

    §3.7 makes the sweep selective on three axes at once — only PENDING rows, only
    strictly past-due ones — and reports swept_at, marked_overdue_count and
    marked_overdue_notification_ids. It moves neither the decision's counters nor
    the cycle's compliance posture, so a second run at the same clock is a no-op.

    Design: Corner/endpoints/one_compliance_sweep_marks_every_due_pending_notice_at_once
    """
    coordinator = make_review_coordinator_headers()
    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    decision_id = ctx.decision["id"]
    assertions.assert_instant_equals(
        ctx.decision["ratified_at"], fixtures.CLOCK_AT_RATIFICATION, "ratified_at"
    )

    accreditor_due = assertions.add_days(fixtures.CLOCK_AT_RATIFICATION, 30)
    state_due = assertions.add_days(fixtures.CLOCK_AT_RATIFICATION, 45)
    federal_due = assertions.add_days(fixtures.CLOCK_AT_RATIFICATION, 60)

    auto_accreditor, _meta = validate_paginated(
        api.list_agency_notifications(
            decision_id,
            coordinator,
            params={"agency_type": "ACCREDITOR", "limit": 10, "offset": 0},
        )
    )
    n_acc_id = auto_accreditor[0]["id"]
    auto_state, _meta = validate_paginated(
        api.list_agency_notifications(
            decision_id,
            coordinator,
            params={"agency_type": "STATE_AGENCY", "limit": 10, "offset": 0},
        )
    )
    n_state_id = auto_state[0]["id"]

    n_manual = validate_success(
        api.create_agency_notification(
            decision_id,
            factories.agency_notification_payload(
                agency_type="ACCREDITOR", agency_code="SPECIALTY-ACC"
            ),
            coordinator,
        ),
        201,
    )
    n_sent = validate_success(
        api.create_agency_notification(
            decision_id,
            factories.agency_notification_payload(
                agency_type="STATE_AGENCY", agency_code="STATE-CHE-2"
            ),
            coordinator,
        ),
        201,
    )
    n_fed = validate_success(
        api.create_agency_notification(
            decision_id,
            factories.agency_notification_payload(
                agency_type="FEDERAL", agency_code="US-DOE"
            ),
            coordinator,
        ),
        201,
    )

    fixtures.acknowledge_notification(api, n_acc_id)
    validate_success(
        api.transition_agency_notification(
            n_sent["id"],
            factories.notification_send_payload("STA-TX-0002"),
            coordinator,
        )
    )
    fixtures.set_clock(api, SWEEP_CLOCK)

    before = fixtures.read_decision(api, decision_id)
    assert before["notification_count"] == 5
    assert before["unacknowledged_notification_count"] == 4

    first_sweep = validate_success(api.run_compliance_sweep(coordinator))
    assertions.assert_instant_equals(first_sweep["swept_at"], SWEEP_CLOCK, "swept_at")
    assert first_sweep["marked_overdue_count"] == 2
    assert set(first_sweep["marked_overdue_notification_ids"]) == {
        n_state_id,
        n_manual["id"],
    }

    rows, meta = validate_paginated(
        api.list_agency_notifications(
            decision_id, coordinator, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 5
    by_id = {row["id"]: row for row in rows}

    manual = by_id[n_manual["id"]]
    assert manual["status"] == "OVERDUE"
    assertions.assert_instant_equals(
        manual["overdue_marked_at"], SWEEP_CLOCK, "manual.overdue_marked_at"
    )
    assertions.assert_instant_equals(
        manual["due_at"], accreditor_due, "manual.due_at"
    )

    auto_state_row = by_id[n_state_id]
    assert auto_state_row["status"] == "OVERDUE"
    assertions.assert_instant_equals(
        auto_state_row["due_at"], state_due, "auto state notice due_at"
    )

    sent_row = by_id[n_sent["id"]]
    assert sent_row["status"] == "SENT", "the sweep only reaches PENDING rows"
    assert sent_row["overdue_marked_at"] is None
    assertions.assert_instant_equals(
        sent_row["due_at"], state_due, "sent notice due_at"
    )

    acknowledged_row = by_id[n_acc_id]
    assert acknowledged_row["status"] == "ACKNOWLEDGED"
    assert acknowledged_row["overdue_marked_at"] is None

    federal_row = by_id[n_fed["id"]]
    assert federal_row["status"] == "PENDING", "not yet due"
    assert federal_row["overdue_marked_at"] is None
    assertions.assert_instant_equals(
        federal_row["due_at"], federal_due, "federal notice due_at"
    )

    second_sweep = validate_success(api.run_compliance_sweep(coordinator))
    assert second_sweep["marked_overdue_count"] == 0
    assert second_sweep["marked_overdue_notification_ids"] == []

    after = fixtures.read_decision(api, decision_id)
    assert after["notification_count"] == 5
    assert after["unacknowledged_notification_count"] == 4
    assert after["state"] == "RATIFIED", "a sweep never advances a decision"

    cycle = fixtures.read_cycle(api, ctx.cycle_id)
    assert cycle["compliance_posture"] == "NOTICES_PENDING"


def test_self_study_patch_writes_only_the_fields_it_was_given(api):
    """A partial self-study update leaves every unmentioned field byte-identical.

    §3.3 lets the chair edit the narrative, the section coverage and the
    attestation, and every edit rewrites missing_section_codes against the cycle's
    requirement list and bumps the version by 1. A PATCH naming one field reaches
    no other input field and no system-owned field at all.

    Design: Corner/endpoints/self_study_patch_writes_only_the_fields_it_was_given
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="PHIL-BA", name="Philosophy BA", department_code="PHIL"
    )
    cycle = fixtures.open_cycle(api, program["id"], required_section_codes=["S1", "S2"])
    self_study = fixtures.create_self_study(
        api,
        cycle["id"],
        program["id"],
        narrative="Original philosophy narrative.",
        section_codes=["S1"],
    )
    chair = make_program_chair_headers(program["id"])
    base_version = self_study["version"]

    first = validate_success(
        api.patch_self_study(
            self_study["id"],
            factories.self_study_patch_payload(
                attestation_note="Attested by the chair."
            ),
            chair,
        )
    )
    assert first["attestation_note"] == "Attested by the chair."
    assert first["narrative"] == "Original philosophy narrative."
    assert first["section_codes"] == ["S1"]
    assert first["missing_section_codes"] == ["S2"]
    assert first["state"] == "DRAFT", "a PATCH reaches no system-owned field"
    assert first["revision_round"] == 0
    assert first["submitted_at"] is None
    assert first["accepted_at"] is None
    assertions.assert_version_is(first, base_version + 1, "self-study")

    second = validate_success(
        api.patch_self_study(
            self_study["id"],
            factories.self_study_patch_payload(section_codes=["S1", "S2"]),
            chair,
        )
    )
    assert second["section_codes"] == ["S1", "S2"]
    assert second["missing_section_codes"] == []
    assert second["attestation_note"] == "Attested by the chair.", (
        "an omitted field is not cleared to null"
    )
    assert second["narrative"] == "Original philosophy narrative."
    assert second["state"] == "DRAFT"
    assert second["revision_round"] == 0
    assertions.assert_version_is(second, base_version + 2, "self-study")

    rows, meta = validate_paginated(
        api.list_self_studies(
            cycle["id"], make_review_coordinator_headers(), params={"state": "DRAFT"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0] == second, "the PATCH result is what was persisted"


def test_teach_out_plan_read_projects_the_whole_seat_and_risk_ledger(api):
    """The plan read derives nine counters nobody posted, and reading never mutates.

    §3.9 derives the plan's seat and student aggregates from its stored children —
    guaranteed and committed seat totals over the guarantees, required seats and
    risk counts over the students, seats_available per guarantee — and §3.10
    derives each student's projection from its own advising status.

    Design: Corner/endpoints/teach_out_plan_read_projects_the_whole_seat_and_risk_ledger
    """
    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    fixtures.add_guarantee(
        api, ctx, course_code="HIST-401", term_index=4, seats_guaranteed=5
    )
    fixtures.add_guarantee(
        api, ctx, course_code="HIST-402", term_index=5, seats_guaranteed=4
    )
    student = fixtures.enrol_student(
        api, ctx, student_number="S-1001", credits_remaining=24, max_credits_per_term=15
    )
    plan_id = ctx.plan["id"]
    registrar = make_registrar_headers()

    first = validate_success(
        api.get_teach_out_plan(plan_id, make_provost_proposer_headers())
    )
    assertions.assert_plan_ledger(
        first,
        guaranteed_seat_total=9,
        committed_seat_total=0,
        required_seat_total=8,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=1,
        substituted_guarantee_count=0,
        waived_guarantee_count=0,
    )
    assert first["state"] == "DRAFT"
    assert first["plan_revision_round"] == 0
    assert first["approved_at"] is None
    assert first["activated_at"] is None
    assert first["completed_at"] is None

    second = validate_success(api.get_teach_out_plan(plan_id, registrar))
    assert second == first, "reads never mutate and the ledger does not drift per read"

    guarantees, g_meta = validate_paginated(
        api.list_course_guarantees(plan_id, registrar, params={"limit": 10, "offset": 0})
    )
    assert g_meta["total_count"] == 2
    by_course = {row["course_code"]: row for row in guarantees}
    assert by_course["HIST-401"]["seats_guaranteed"] == 5
    assert by_course["HIST-401"]["seats_committed"] == 0
    assert by_course["HIST-401"]["seats_available"] == 5
    assert by_course["HIST-401"]["status"] == "PLANNED"
    assert by_course["HIST-402"]["seats_guaranteed"] == 4
    assert by_course["HIST-402"]["seats_committed"] == 0
    assert by_course["HIST-402"]["seats_available"] == 4
    assert by_course["HIST-402"]["status"] == "PLANNED"

    students, s_meta = validate_paginated(
        api.list_displaced_students(
            plan_id, registrar, params={"at_risk": "false", "limit": 10, "offset": 0}
        )
    )
    assert s_meta["total_count"] == 1
    row = students[0]
    assert row["id"] == student["id"]
    assert row["student_number"] == "S-1001"
    assert row["advising_status"] == "PENDING"
    assertions.assert_projection(
        row,
        "OPTIMISTIC_FULL_LOAD",
        2,
        5,
        False,
        required_seat_count=8,
    )
    assert row["committed_seat_count"] == 0
    assertions.assert_seat_conservation(guarantees, students)


def test_a_consolidation_decision_is_reachable_from_both_program_links(api):
    """A consolidation is reachable from the receiving program, never in reverse.

    §2.3 declares `receiving_program_id` a decision-record filter and
    `consolidated_into_program_id` a program filter — §2.3 calls the latter the
    reverse-reachability channel for the self-referential consolidation link —
    and §3.8's consolidation branch is what writes that link at effectuation.
    Both channels are directional: the reviewed program is the subject of the
    decision and never its receiver.

    Design: Corner/endpoints/a_consolidation_decision_is_reachable_from_both_program_links
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    big = fixtures.create_continue_eligible_program(
        api, code="BIG-BA", name="Big Program BA", department_code="BIG"
    )
    big_id = big["id"]
    assertions.assert_axes(big, lifecycle_state="ACTIVE", catalog_status="LISTED")
    assert big["viability_band"] == "CONTINUE_ELIGIBLE"

    ctx = fixtures.carry_cycle_to_response_submitted(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    hist_id = ctx.program_id
    fixtures.set_clock(api, fixtures.CLOCK_AT_RATIFICATION)
    fixtures.propose_decision(api, ctx, "CONSOLIDATION", receiving_program_id=big_id)
    fixtures.ratify_decision(api, ctx)
    decision_id = ctx.decision["id"]
    fixtures.acknowledge_all_notifications(api, decision_id)
    effectuated = fixtures.effectuate_decision(api, ctx)
    assert effectuated["state"] == "EFFECTUATED"

    hr = make_hr_partner_headers()
    registrar = make_registrar_headers()

    # 1. The decision is reachable from the RECEIVING program, which is not its
    #    parent anywhere in the hierarchy.
    by_receiver, meta = validate_paginated(
        api.list_decision_records(
            hr, params={"receiving_program_id": big_id, "limit": 10, "offset": 0}
        )
    )
    assertions.assert_pagination_meta(meta, 10, 0, 1, False)
    assert by_receiver[0]["id"] == decision_id

    # 2. The reviewed program is the subject, never the receiver.
    reversed_rows, reversed_meta = validate_paginated(
        api.list_decision_records(
            hr, params={"receiving_program_id": hist_id, "limit": 10, "offset": 0}
        )
    )
    assert reversed_meta["total_count"] == 0
    assert reversed_rows == []

    # 3. The additive cycle_id + outcome pair finds the same row.
    by_cycle, cycle_meta = validate_paginated(
        api.list_decision_records(
            registrar,
            params={
                "cycle_id": ctx.cycle_id,
                "outcome": "CONSOLIDATION",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert cycle_meta["total_count"] == 1
    assert by_cycle[0]["id"] == decision_id
    assert by_cycle[0]["state"] == "EFFECTUATED"
    assert by_cycle[0]["outcome"] == "CONSOLIDATION"
    assert by_cycle[0]["receiving_program_id"] == big_id

    # 4. The program-side link written by the effectuation.
    folded, folded_meta = validate_paginated(
        api.list_programs(
            registrar,
            params={"consolidated_into_program_id": big_id, "limit": 10, "offset": 0},
        )
    )
    assertions.assert_pagination_meta(folded_meta, 10, 0, 1, False)
    assert folded[0]["id"] == hist_id
    assert folded[0]["code"] == "HIST-BA"
    assertions.assert_axes(
        folded[0], lifecycle_state="CONSOLIDATED", catalog_status="ADMISSIONS_CLOSED"
    )
    assert folded[0]["consolidated_into_program_id"] == big_id

    # 5. BIG-BA absorbed a program; it was not absorbed.
    absorbed, absorbed_meta = validate_paginated(
        api.list_programs(
            registrar,
            params={"consolidated_into_program_id": hist_id, "limit": 10, "offset": 0},
        )
    )
    assert absorbed_meta["total_count"] == 0
    assert absorbed == []

    big_after = fixtures.read_program(api, big_id)
    assertions.assert_axes(
        big_after, lifecycle_state="ACTIVE", catalog_status="LISTED"
    )
    assert big_after["viability_band"] == "CONTINUE_ELIGIBLE"
    assert big_after["consolidated_into_program_id"] is None


def test_a_new_plan_may_supersede_a_draft_but_not_an_approved_plan(api):
    """The same create call is allowed against a DRAFT plan and refused against an APPROVED one.

    §3.9 supersedes any DRAFT or SUBMITTED plan on the program when a new plan is
    filed, but check 46 refuses the write outright once a plan on the program is
    APPROVED or IN_EFFECT (`ERR_TEACH_OUT_IN_EFFECT`, 409). Every accepted create
    also bumps `AcademicProgram.version`, so the second author must re-read it.

    Design: Corner/endpoints/a_new_plan_may_supersede_a_draft_but_not_an_approved_plan
    """
    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    chair = ctx.chair_headers
    decision_id = ctx.decision["id"]

    prog_v1 = fixtures.read_program(api, ctx.program_id)["version"]
    plan1 = validate_success(
        api.create_teach_out_plan(
            ctx.program_id,
            factories.teach_out_plan_payload(
                decision_id,
                prog_v1,
                last_admit_term_index=3,
                first_teach_out_term_index=4,
                final_award_term_index=5,
            ),
            chair,
        ),
        201,
    )
    assert plan1["state"] == "DRAFT"

    prog_v2 = fixtures.read_program(api, ctx.program_id)["version"]
    assert prog_v2 == prog_v1 + 1, (
        "filing the first plan bumped the program's version, so the same "
        "expected_program_version cannot be replayed"
    )

    plan2 = validate_success(
        api.create_teach_out_plan(
            ctx.program_id,
            factories.teach_out_plan_payload(
                decision_id,
                prog_v2,
                last_admit_term_index=3,
                first_teach_out_term_index=4,
                final_award_term_index=6,
            ),
            chair,
        ),
        201,
    )
    assert plan2["state"] == "DRAFT"
    assert plan2["final_award_term_index"] == 6
    assert plan2["id"] != plan1["id"]
    assert fixtures.read_plan(api, plan1["id"])["state"] == "SUPERSEDED", (
        "a DRAFT plan is replaceable"
    )

    ctx.plan = plan2
    submitted = fixtures.submit_plan(api, ctx)
    assert submitted["state"] == "SUBMITTED"
    approved = fixtures.approve_plan(api, ctx)
    assert approved["state"] == "APPROVED"
    assert approved["seat_shortfall"] == 0
    assert approved["at_risk_student_count"] == 0

    prog_v3 = fixtures.read_program(api, ctx.program_id)["version"]
    refused = api.create_teach_out_plan(
        ctx.program_id,
        factories.teach_out_plan_payload(
            decision_id,
            prog_v3,
            last_admit_term_index=3,
            first_teach_out_term_index=4,
            final_award_term_index=7,
        ),
        chair,
    )
    validate_error(refused, ERR_TEACH_OUT_IN_EFFECT, 409)

    rows, meta = validate_paginated(
        api.list_teach_out_plans(
            chair, params={"program_id": ctx.program_id, "limit": 10, "offset": 0}
        )
    )
    assertions.assert_pagination_meta(meta, 10, 0, 2, False)
    assert sorted(row["state"] for row in rows) == ["APPROVED", "SUPERSEDED"]
    assert fixtures.read_program(api, ctx.program_id)["version"] == prog_v3, (
        "the refused write bumped nothing"
    )
    assert fixtures.read_plan(api, plan2["id"])["final_award_term_index"] == 6, (
        "the refused write did not partially apply its 7"
    )


def test_the_visit_and_cycle_list_channels_carry_the_derived_span_and_report_count(api):
    """The visit channels derive an inclusive day span and a child-derived report count.

    §3.4 cuts `span_start_date` and `span_end_date` as the UTC calendar dates of
    the half-open window's two instants, so a window ending at 17:00 UTC still
    claims the whole of its own day, and a window inside one UTC day spans exactly
    that day. `report_count` is derived from the visit's child reports. §2.3
    declares the visit filters `cycle_id`, `reviewer_id` and `state` and the cycle
    filters `state` and `cycle_year`, and makes every supplied filter narrowing —
    they compose as AND, and `total_count` counts the filtered set rather than the
    returned page.

    Design: Corner/endpoints/the_visit_and_cycle_list_channels_carry_the_derived_span_and_report_count
    """
    completion_clock = "2026-08-23T00:00:00Z"
    coordinator = make_review_coordinator_headers()

    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_nonviable_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    program_id = program["id"]
    chair = make_program_chair_headers(program_id)
    cycle = fixtures.open_cycle(api, program_id)
    self_study = fixtures.create_self_study(api, cycle["id"], program_id)
    fixtures.accept_self_study(api, self_study["id"], program_id)

    r1 = fixtures.register_reviewer(
        api,
        full_name="Dr Nala Osei",
        institution="Westmoor University",
        specialty_code="HIST",
    )
    r2 = fixtures.register_reviewer(
        api,
        full_name="Dr Piotr Aldana",
        institution="Calder College",
        specialty_code="HIST",
    )
    v1 = fixtures.schedule_visit(
        api,
        cycle["id"],
        r1["id"],
        fixtures.VISIT_WINDOW_START,
        fixtures.VISIT_WINDOW_END,
    )
    v2 = fixtures.schedule_visit(
        api, cycle["id"], r2["id"], "2026-08-25T08:00:00Z", "2026-08-25T18:00:00Z"
    )

    fixtures.set_clock(api, completion_clock)
    fixtures.complete_visit(api, v1["id"])
    fixtures.file_report(
        api,
        v1["id"],
        r1["id"],
        recommendation="IMPROVE",
        finding_codes=["F-ENROLL"],
        narrative="Recoverable with recruitment.",
    )

    # The three-inclusive-day span, cut from instants that are not midnight.
    v1_read = validate_success(api.get_reviewer_visit(v1["id"], coordinator))
    assert v1_read["state"] == "REPORTED"
    assertions.assert_iso_date(v1_read["span_start_date"], "v1.span_start_date")
    assertions.assert_iso_date(v1_read["span_end_date"], "v1.span_end_date")
    assert v1_read["span_start_date"] == "2026-08-20"
    assert v1_read["span_end_date"] == "2026-08-22", (
        "a window ending at 17:00 UTC still claims the whole 22nd"
    )
    assertions.assert_instant_equals(
        v1_read["completed_at"], completion_clock, "v1.completed_at"
    )
    assert v1_read["report_count"] == 1
    assert v1_read["reviewer_id"] == r1["id"]

    # A window inside one UTC day spans exactly that day.
    v2_read = validate_success(api.get_reviewer_visit(v2["id"], chair))
    assert v2_read["state"] == "SCHEDULED"
    assert v2_read["span_start_date"] == "2026-08-25"
    assert v2_read["span_end_date"] == "2026-08-25"
    assert v2_read["completed_at"] is None
    assert v2_read["report_count"] == 0

    by_cycle, cycle_meta = validate_paginated(
        api.list_reviewer_visits(
            coordinator, params={"cycle_id": cycle["id"], "limit": 10, "offset": 0}
        )
    )
    assertions.assert_pagination_meta(cycle_meta, 10, 0, 2, False)
    assert {row["reviewer_id"] for row in by_cycle} == {r1["id"], r2["id"]}

    by_reviewer, reviewer_meta = validate_paginated(
        api.list_reviewer_visits(
            coordinator, params={"reviewer_id": r2["id"], "limit": 10, "offset": 0}
        )
    )
    assert reviewer_meta["total_count"] == 1
    assert [row["id"] for row in by_reviewer] == [v2["id"]]

    scheduled, scheduled_meta = validate_paginated(
        api.list_reviewer_visits(
            coordinator, params={"state": "SCHEDULED", "limit": 10, "offset": 0}
        )
    )
    assert scheduled_meta["total_count"] == 1
    assert [row["id"] for row in scheduled] == [v2["id"]]

    completed, completed_meta = validate_paginated(
        api.list_reviewer_visits(
            coordinator, params={"state": "COMPLETED", "limit": 10, "offset": 0}
        )
    )
    assert completed_meta["total_count"] == 0, (
        "v1 left COMPLETED for REPORTED when the report was filed"
    )
    assert completed == []

    reported, reported_meta = validate_paginated(
        api.list_reviewer_visits(
            coordinator, params={"state": "REPORTED", "limit": 10, "offset": 0}
        )
    )
    assert reported_meta["total_count"] == 1
    assert [row["id"] for row in reported] == [v1["id"]]

    # Filters compose as AND: a row matching two of three is excluded.
    anded, anded_meta = validate_paginated(
        api.list_reviewer_visits(
            coordinator,
            params={
                "cycle_id": cycle["id"],
                "reviewer_id": r1["id"],
                "state": "SCHEDULED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert anded == []
    assertions.assert_pagination_meta(anded_meta, 10, 0, 0, False)

    page, page_meta = validate_paginated(
        api.list_reviewer_visits(
            make_external_reviewer_headers(r1["id"]),
            params={"cycle_id": cycle["id"], "limit": 1, "offset": 1},
        )
    )
    assert len(page) == 1
    # total_count counts the filtered set, not the returned page.
    assertions.assert_pagination_meta(page_meta, 1, 1, 2, False)

    # The cycle list channel is the reverse-reachability path for
    # ReviewCycle.program_id. §3.4 keeps the cycle in VISIT_SCHEDULED while a
    # second visit is outstanding and §3.5 declares the report cascade only out of
    # VISIT_COMPLETED, so the PRD does not uniquely derive which state this cycle
    # now sits in; the filter is therefore exercised against the state the cycle
    # itself reports.
    cycles, cycles_meta = validate_paginated(
        api.list_review_cycles(
            program_id, make_provost_proposer_headers(), params={"limit": 10, "offset": 0}
        )
    )
    assertions.assert_pagination_meta(cycles_meta, 10, 0, 1, False)
    current_state = cycles[0]["state"]
    assert cycles[0]["id"] == cycle["id"]
    assert cycles[0]["addendum_round"] == 0
    assert cycles[0]["compliance_posture"] == "NOT_APPLICABLE"

    this_year, this_year_meta = validate_paginated(
        api.list_review_cycles(
            program_id,
            make_provost_proposer_headers(),
            params={"cycle_year": 2026, "limit": 10, "offset": 0},
        )
    )
    assert this_year_meta["total_count"] == 1
    assert this_year[0]["id"] == cycle["id"]

    last_year, last_year_meta = validate_paginated(
        api.list_review_cycles(
            program_id,
            make_provost_proposer_headers(),
            params={"cycle_year": 2025, "limit": 10, "offset": 0},
        )
    )
    assert last_year == []
    assert last_year_meta["total_count"] == 0

    stale, stale_meta = validate_paginated(
        api.list_review_cycles(
            program_id, chair, params={"state": "SELF_STUDY_OPEN", "limit": 10, "offset": 0}
        )
    )
    assert stale == [], "the filter reads the cycle's current state, not its created state"
    assert stale_meta["total_count"] == 0

    live, live_meta = validate_paginated(
        api.list_review_cycles(
            program_id, chair, params={"state": current_state, "limit": 10, "offset": 0}
        )
    )
    assert live_meta["total_count"] == 1
    assert live[0]["id"] == cycle["id"]
