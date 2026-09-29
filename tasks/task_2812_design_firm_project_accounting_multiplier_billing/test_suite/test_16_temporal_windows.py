"""
Effective-date windows and the two opposite interval conventions.

Published labour cost rate windows are half-open, so two windows that share a
calendar boundary are adjacent and the shared date belongs to the later of them.
Consultant commitment windows are closed, so two that merely touch on one date
overlap and their commitments are summed against the phase's consultant budget.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CONSULTANT_BUDGET_OVERCOMMIT,
    ERR_RATE_PERIOD_OVERLAP,
)
from test_helpers.assertions import (
    assert_billing_posture,
    assert_money,
    assert_null,
    assert_pagination_meta,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_subcontract_rollup,
    assert_time_entry_frozen,
)
from test_helpers.constants import (
    CLOCK_2026_06_01,
    PHASE_IN_PROGRESS,
    POSTURE_OPEN,
    ROLE_CODE_DESIGNER,
    ROLE_CODE_PROJECT_ARCHITECT,
    SUBCONTRACT_DRAFT,
    SUBCONTRACT_EXECUTED,
    TIME_ENTRY_APPROVED,
)
from test_helpers.factories import labor_rate_payload
from test_helpers.fixtures import (
    approve_time_entry,
    build_active_project,
    draft_subcontract,
    publish_labor_rate,
    read_phase,
    read_project,
    read_subcontract,
    set_clock,
    submit_time_entry,
)
from test_helpers.test_users import CONTROLLER


def _publish_adjacent_windows(api):
    """
    Two windows for one labour grade that share the boundary 2026-04-01: 45.00
    over [2026-01-01, 2026-04-01) and 48.00 from 2026-04-01 with no end date.
    """
    set_clock(api, CLOCK_2026_06_01)
    early = publish_labor_rate(
        api,
        role_code=ROLE_CODE_DESIGNER,
        raw_cost_rate=45.00,
        effective_from="2026-01-01",
        effective_to="2026-04-01",
    )
    late = publish_labor_rate(
        api,
        role_code=ROLE_CODE_DESIGNER,
        raw_cost_rate=48.00,
        effective_from="2026-04-01",
    )
    return early, late


def _project_straddling_the_boundary(api):
    """
    An ACTIVE project on a multiplier of 3.0500 carrying two 8.00 hour timesheet
    lines of that labour grade, one dated the day before the rate boundary and one
    dated on it.
    """
    early, late = _publish_adjacent_windows(api)
    ctx = build_active_project(
        api,
        clock=None,
        publish_rate=False,
        project_overrides={"name": "Riverside Library"},
    )
    before = submit_time_entry(
        api, ctx, hours=8.00, work_date="2026-03-31", role_code=ROLE_CODE_DESIGNER
    )
    on_boundary = submit_time_entry(
        api, ctx, hours=8.00, work_date="2026-04-01", role_code=ROLE_CODE_DESIGNER
    )
    return ctx, early, late, before, on_boundary


def _phase_with_four_drafted_commitments(api):
    """
    An ACTIVE project whose leaf phase has a consultant budget of exactly
    100000.00 and four drafted subcontracts: 60000.00 over 2026-04-01 to
    2026-06-30, 40000.00 over 2026-06-30 to 2026-09-30, 1.00 over 2026-06-30 to
    2026-07-01 and 50000.00 over 2026-07-01 to 2026-08-01.
    """
    ctx = build_active_project(
        api,
        project_overrides={"name": "Lakeshore Pavilion"},
        phase_overrides={"consultant_budget": 100000.00},
    )
    first = draft_subcontract(
        api,
        ctx,
        consultant_name="Halcyon MEP",
        committed_amount=60000.00,
        commitment_start="2026-04-01",
        commitment_end="2026-06-30",
    )
    second = draft_subcontract(
        api,
        ctx,
        consultant_name="Cedar Structural",
        committed_amount=40000.00,
        commitment_start="2026-06-30",
        commitment_end="2026-09-30",
    )
    touching = draft_subcontract(
        api,
        ctx,
        consultant_name="Verdant Landscape",
        committed_amount=1.00,
        commitment_start="2026-06-30",
        commitment_end="2026-07-01",
    )
    later = draft_subcontract(
        api,
        ctx,
        consultant_name="Aster Acoustics",
        committed_amount=50000.00,
        commitment_start="2026-07-01",
        commitment_end="2026-08-01",
    )
    return ctx, first, second, touching, later


def test_touching_labour_rate_windows_are_adjacent_and_the_boundary_date_belongs_to_the_later_one(
    api,
):
    """
    Two published cost rate windows for one labour grade that share the date
    2026-04-01 coexist, and resolving the grade on that shared date returns the
    later window's 48.00 while the day before still resolves 45.00.

    PRD §3.2: "The interval is **half-open**: a rate covers a date when its `effective_from` is on or before that date and either its `effective_to` is absent or the date is strictly earlier than its `effective_to`."
    PRD §3.2: "Because of that, two windows for the same `role_code` that merely touch — where the earlier window's `effective_to` equals the later window's `effective_from` — are adjacent, leave neither gap nor overlap, and are entirely legal."
    PRD §2.9: "`role_code` and `effective_on` on labour rates, where `effective_on` resolves the window covering a given date"

    Design: Difficulty/resource_temporal_overlap/labor_rate_half_open_window_adjacency_versus_overlap
    """
    early, late = _publish_adjacent_windows(api)

    assert_money(early["raw_cost_rate"], 45.00, "earlier window raw_cost_rate")
    assert early["effective_from"] == "2026-01-01"
    assert early["effective_to"] == "2026-04-01"
    assert_money(late["raw_cost_rate"], 48.00, "later window raw_cost_rate")
    assert late["effective_from"] == "2026-04-01"
    assert_null(late["effective_to"], "later window effective_to")

    rows, meta = validate_paginated(
        api.list_labor_rates(CONTROLLER, {"role_code": ROLE_CODE_DESIGNER})
    )
    assert_pagination_meta(meta, total_count=2, has_more=False)
    assert {row["id"] for row in rows} == {early["id"], late["id"]}

    day_before, before_meta = validate_paginated(
        api.list_labor_rates(
            CONTROLLER,
            {"role_code": ROLE_CODE_DESIGNER, "effective_on": "2026-03-31"},
        )
    )
    assert_pagination_meta(before_meta, total_count=1, has_more=False)
    assert day_before[0]["id"] == early["id"]
    assert_money(day_before[0]["raw_cost_rate"], 45.00, "rate covering 2026-03-31")

    boundary_day, boundary_meta = validate_paginated(
        api.list_labor_rates(
            CONTROLLER,
            {"role_code": ROLE_CODE_DESIGNER, "effective_on": "2026-04-01"},
        )
    )
    assert_pagination_meta(boundary_meta, total_count=1, has_more=False)
    assert boundary_day[0]["id"] == late["id"]
    assert_money(boundary_day[0]["raw_cost_rate"], 48.00, "rate covering 2026-04-01")


def test_a_rate_window_straddling_the_boundary_is_refused_while_another_grade_may_hold_it(api):
    """
    A third window for the same labour grade running 2026-03-01 to 2026-05-01
    genuinely overlaps both incumbents and is refused, as is an open-ended window
    opening on 2026-09-01 inside the incumbent's open tail; the identical
    2026-03-01 to 2026-05-01 window for a different labour grade is accepted,
    because overlap is judged per grade.

    PRD §3.2: "Two windows for the same `role_code` that genuinely overlap are refused outright with `ERR_RATE_PERIOD_OVERLAP` (HTTP 409), and it is this rejection that guarantees at most one rate can ever cover a given role and date."

    Design: Difficulty/resource_temporal_overlap/labor_rate_half_open_window_adjacency_versus_overlap
    """
    early, late = _publish_adjacent_windows(api)

    validate_error(
        api.create_labor_rate(
            labor_rate_payload(
                ROLE_CODE_DESIGNER,
                raw_cost_rate=50.00,
                effective_from="2026-03-01",
                effective_to="2026-05-01",
            ),
            CONTROLLER,
        ),
        ERR_RATE_PERIOD_OVERLAP,
        409,
    )

    validate_error(
        api.create_labor_rate(
            labor_rate_payload(
                ROLE_CODE_DESIGNER,
                raw_cost_rate=52.00,
                effective_from="2026-09-01",
            ),
            CONTROLLER,
        ),
        ERR_RATE_PERIOD_OVERLAP,
        409,
    )

    other_grade = validate_success(
        api.create_labor_rate(
            labor_rate_payload(
                ROLE_CODE_PROJECT_ARCHITECT,
                raw_cost_rate=62.50,
                effective_from="2026-03-01",
                effective_to="2026-05-01",
            ),
            CONTROLLER,
        ),
        201,
    )
    assert other_grade["role_code"] == ROLE_CODE_PROJECT_ARCHITECT
    assert_money(other_grade["raw_cost_rate"], 62.50, "other grade raw_cost_rate")

    surviving, meta = validate_paginated(
        api.list_labor_rates(CONTROLLER, {"role_code": ROLE_CODE_DESIGNER})
    )
    assert_pagination_meta(meta, total_count=2, has_more=False)
    assert {row["id"] for row in surviving} == {early["id"], late["id"]}


def test_charges_either_side_of_the_boundary_freeze_the_two_adjacent_cost_rates(api):
    """
    Two identical 8.00 hour lines of the same labour grade, one worked on
    2026-03-31 and one on 2026-04-01, freeze different money because each resolves
    the window covering its own work date: 360.00 raw against 45.00 and 384.00 raw
    against 48.00, both billed at the project's multiplier of 3.0500.

    PRD §3.3: "Rate resolution considers every published labour rate for that `role_code` regardless of the order in which the rows were created, and multiplier resolution considers every multiplier of the project in `ACTIVE` or `SUPERSEDED` status; in both cases a row covers the date when its `effective_from` is on or before the `work_date` and either it has no `effective_to` or the `work_date` is strictly earlier than that `effective_to`."
    PRD §3.3: "First, `raw_cost` is the `hours` multiplied by the resolved `raw_cost_rate`, rounded half up to 2 decimal places."
    PRD §3.3: "Third, `billable_amount` is the already-rounded `raw_cost` multiplied by `applied_multiplier`, rounded half up to 2 decimal places."

    Design: Difficulty/resource_temporal_overlap/labor_rate_half_open_window_adjacency_versus_overlap
    """
    ctx, early, late, before, on_boundary = _project_straddling_the_boundary(api)

    approved_before = approve_time_entry(api, before["id"])
    assert approved_before["status"] == TIME_ENTRY_APPROVED
    assert_time_entry_frozen(
        approved_before, raw_cost=360.00, applied_multiplier=3.0500, billable_amount=1098.00
    )

    approved_on_boundary = approve_time_entry(api, on_boundary["id"])
    assert approved_on_boundary["status"] == TIME_ENTRY_APPROVED
    assert_time_entry_frozen(
        approved_on_boundary,
        raw_cost=384.00,
        applied_multiplier=3.0500,
        billable_amount=1171.20,
    )

    phase = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(phase, actual_labor_cost_to_date=744.00)

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=2269.20,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=2269.20,
        raw_labor_cost_to_date=744.00,
        net_multiplier_achieved=3.0500,
    )
    assert_billing_posture(project, POSTURE_OPEN)


def test_touching_commitment_windows_together_may_fill_the_consultant_budget_exactly(api):
    """
    A 60000.00 commitment running 2026-04-01 to 2026-06-30 and a 40000.00
    commitment running 2026-06-30 to 2026-09-30 touch on 2026-06-30, so the second
    execution is measured against an aggregate exposure of exactly 100000.00 — the
    phase's whole consultant budget — and is admitted.

    PRD §3.5: "That exposure is computed over the **closed-inclusive** commitment windows of the phase's other `EXECUTED` subcontracts: a peer subcontract counts when it sits on the same phase, is not the candidate itself, has `status` `EXECUTED`, and its `commitment_start` is on or before the candidate's `commitment_end` while its `commitment_end` is on or after the candidate's `commitment_start`."
    PRD §3.5: "The exposure is the sum of the `committed_amount` of every such peer plus the candidate's own `committed_amount`, and it may not exceed the phase's `consultant_budget`; the cap comparison is strict, so an exposure exactly equal to `consultant_budget` is permitted while anything above it is refused with `ERR_CONSULTANT_BUDGET_OVERCOMMIT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/consultant_commitment_closed_window_aggregate_capacity
    """
    ctx, first, second, _touching, _later = _phase_with_four_drafted_commitments(api)

    executed_first = validate_success(api.execute_subcontract(first["id"], CONTROLLER), 200)
    assert_subcontract_rollup(
        executed_first,
        approved_to_date=0.00,
        released_to_date=0.00,
        committed_remaining=60000.00,
        status=SUBCONTRACT_EXECUTED,
    )
    assert executed_first["version"] == 2

    executed_second = validate_success(api.execute_subcontract(second["id"], CONTROLLER), 200)
    assert_subcontract_rollup(
        executed_second,
        approved_to_date=0.00,
        released_to_date=0.00,
        committed_remaining=40000.00,
        status=SUBCONTRACT_EXECUTED,
    )
    assert executed_second["version"] == 2

    phase = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(phase, consultant_committed_open=100000.00)
    assert_money(phase["consultant_budget"], 100000.00, "phase.consultant_budget")
    assert phase["status"] == PHASE_IN_PROGRESS

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=0.00,
    )
    assert_billing_posture(project, POSTURE_OPEN)


def test_a_one_dollar_commitment_touching_both_incumbents_is_refused_and_consumes_nothing(api):
    """
    With both incumbents executed and the consultant budget exactly full, a
    commitment of 1.00 running 2026-06-30 to 2026-07-01 touches the earlier window
    on its first day and lies inside the later window, so its aggregate exposure of
    100001.00 exceeds the budget and execution is refused; the subcontract stays in
    DRAFT and the phase's committed capacity is untouched.

    PRD §3.5: "Two windows that merely touch at a single date therefore **do** overlap."
    PRD §3.5: "The exposure is the sum of the `committed_amount` of every such peer plus the candidate's own `committed_amount`, and it may not exceed the phase's `consultant_budget`; the cap comparison is strict, so an exposure exactly equal to `consultant_budget` is permitted while anything above it is refused with `ERR_CONSULTANT_BUDGET_OVERCOMMIT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/consultant_commitment_closed_window_aggregate_capacity
    """
    ctx, first, second, touching, _later = _phase_with_four_drafted_commitments(api)
    validate_success(api.execute_subcontract(first["id"], CONTROLLER), 200)
    validate_success(api.execute_subcontract(second["id"], CONTROLLER), 200)

    phase_before = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(phase_before, consultant_committed_open=100000.00)

    validate_error(
        api.execute_subcontract(touching["id"], CONTROLLER),
        ERR_CONSULTANT_BUDGET_OVERCOMMIT,
        409,
    )

    refused = read_subcontract(api, touching["id"])
    assert_subcontract_rollup(
        refused,
        approved_to_date=0.00,
        released_to_date=0.00,
        committed_remaining=1.00,
        status=SUBCONTRACT_DRAFT,
    )
    assert refused["version"] == 1

    phase_after = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(phase_after, consultant_committed_open=100000.00)
    assert phase_after["version"] == phase_before["version"]


def test_a_later_window_overlapping_only_one_incumbent_executes_past_the_lifetime_budget(api):
    """
    A 50000.00 commitment running 2026-07-01 to 2026-08-01 starts after the earlier
    incumbent's window has closed, so only the 40000.00 incumbent is a peer and the
    exposure is 90000.00, which fits. Execution therefore succeeds and carries the
    phase's committed capacity to 150000.00, half again its consultant budget,
    because only overlapping exposure is capped.

    PRD §3.5: "Pairwise overlap between two individual subcontracts is perfectly legal — only the aggregate is capped."
    PRD §3.5: "Execution raises the phase's `consultant_committed_open` by the `committed_amount`, moves a phase still in `PLANNED` to `IN_PROGRESS`, and increments both the subcontract's `version` and the phase's `version` by 1."

    Design: Difficulty/resource_temporal_overlap/consultant_commitment_closed_window_aggregate_capacity
    """
    ctx, first, second, _touching, later = _phase_with_four_drafted_commitments(api)
    validate_success(api.execute_subcontract(first["id"], CONTROLLER), 200)
    validate_success(api.execute_subcontract(second["id"], CONTROLLER), 200)

    executed_later = validate_success(api.execute_subcontract(later["id"], CONTROLLER), 200)
    assert_subcontract_rollup(
        executed_later,
        approved_to_date=0.00,
        released_to_date=0.00,
        committed_remaining=50000.00,
        status=SUBCONTRACT_EXECUTED,
    )
    assert executed_later["version"] == 2
    assert executed_later["commitment_start"] == "2026-07-01"
    assert executed_later["commitment_end"] == "2026-08-01"

    phase = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(phase, consultant_committed_open=150000.00)
    assert_money(phase["consultant_budget"], 100000.00, "phase.consultant_budget")

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=0.00,
    )
    assert_billing_posture(project, POSTURE_OPEN)
