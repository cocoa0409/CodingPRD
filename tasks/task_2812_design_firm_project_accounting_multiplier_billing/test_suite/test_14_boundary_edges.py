"""
Inclusive and exclusive edges in unbilled aging, write-off routing and earned value.

The practice's books read the same age number twice with deliberately different
semantics: the aging report reserves its write-off-eligible column for charges
strictly more than 90 days old, while write-off routing escalates to a Controller
at 90 days or more, so a charge exactly 90 days old is not eligible by the report
yet already demands controller authority. The money threshold is inclusive in the
same way, at exactly 5000.00. One level down, a phase's cost-to-cost completion
has three edges of its own — a zero budget, a budget the actual cost has exactly
consumed, and a budget it has overrun — and the project-level work-in-progress
gate compares strictly, so a position exactly at the alert threshold stays open.

Every figure below is the one the ledger must show at that edge, to the cent.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import ERR_APPROVAL_LEVEL_INSUFFICIENT
from test_helpers.assertions import (
    assert_aging_report,
    assert_billing_posture,
    assert_earned_value_report,
    assert_money,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_ratio,
    assert_write_off_routing,
)
from test_helpers.constants import (
    APPROVER_CONTROLLER,
    APPROVER_PROJECT_MANAGER,
    CLOCK_2026_06_01,
    METHOD_EFFORT_BASED,
    POSTURE_OPEN,
    ROLE_CODE_PRINCIPAL,
    TIME_ENTRY_APPROVED,
    TIME_ENTRY_WRITTEN_OFF,
    WRITE_OFF_APPROVED,
    WRITE_OFF_CONTROLLER_AGING_DAYS,
    WRITE_OFF_CONTROLLER_AMOUNT,
    WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
    WRITE_OFF_PENDING_PM_APPROVAL,
)
from test_helpers.fixtures import (
    activate_project,
    add_approved_time_entry,
    add_lump_sum_phase,
    approve_time_entry,
    approve_write_off,
    build_active_project,
    create_private_client,
    create_project,
    prepare_labor_write_off,
    project_version,
    publish_labor_rate,
    read_aging,
    read_earned_value,
    read_phase,
    read_project,
    read_time_entry,
    read_write_off,
    set_clock,
    set_multiplier,
    submit_time_entry,
)
from test_helpers.test_users import CONTROLLER, PROJECT_MANAGER
from test_helpers.types import ProjectContext


def _stand_up_three_unbilled_charges_across_the_ninety_day_edge(api):
    """
    A project holding 8281.25 of unbilled approved labour in three charges chosen
    so that each edge is exercised once: 156.25 dated exactly 90 days before the
    clock, 5000.00 exactly on the escalation amount and 21 days old, and 3125.00
    below both thresholds at 20 days old. The 2.5000 multiplier keeps every
    billable amount on an exact cent, and the alert threshold is left at its
    50000.00 default so the position stays comfortably open.
    """
    ctx = build_active_project(
        api,
        clock=CLOCK_2026_06_01,
        multiplier=2.5000,
        project_overrides={"name": "Riverside Library", "target_multiplier": 2.5000},
    )
    publish_labor_rate(api, ROLE_CODE_PRINCIPAL, 100.00, "2026-01-01")
    stale = add_approved_time_entry(api, ctx, hours=1.00, work_date="2026-03-03")
    principal = add_approved_time_entry(
        api, ctx, hours=20.00, work_date="2026-05-11", role_code=ROLE_CODE_PRINCIPAL
    )
    recent = add_approved_time_entry(api, ctx, hours=20.00, work_date="2026-05-12")
    return ctx, stale["id"], principal["id"], recent["id"]


def test_a_charge_exactly_ninety_days_old_stays_out_of_the_write_off_eligible_column(api):
    """
    The aging report's own edges: 21 and 20 days old fall in the first bucket for
    8125.00 together, and the charge dated exactly 90 days before the clock lands
    in the 61-to-90 bucket for 156.25 rather than the over-90 bucket. Nothing is
    write-off eligible, because eligibility is exactly the over-90 bucket and that
    bucket needs 91 days. The four buckets add to 8281.25, which is the project's
    own unbilled position.

    PRD §3.8: "`bucket_0_30` holds the value of charges aged 30 days or fewer, `bucket_31_60` those aged 31 through 60 days inclusive, `bucket_61_90` those aged 61 through 90 days inclusive, and `bucket_over_90` those aged 91 days or more."
    PRD §3.8: "`total_unbilled` is the sum of the four buckets and must equal the project's `unbilled_wip`. `write_off_eligible_amount` is exactly `bucket_over_90`."
    PRD §3.8: "The report's `as_of_date` is the calendar date of the logical clock."
    PRD §3.1: "Its `locked_through_date` is `null`, its `overhead_adjustment_required` flag is false, and its `certified_multiplier_ceiling` is `null` unless a certification is already in force for a public-agency client."

    Design: Difficulty/boundary_precision_check/write_off_routing_inclusive_thresholds_vs_exclusive_aging_bucket
    """
    ctx, stale_id, principal_id, recent_id = (
        _stand_up_three_unbilled_charges_across_the_ninety_day_edge(api)
    )

    assert_money(read_time_entry(api, stale_id)["billable_amount"], 156.25,
                 "time_entry.billable_amount")
    assert_money(read_time_entry(api, principal_id)["billable_amount"], 5000.00,
                 "time_entry.billable_amount")
    assert_money(read_time_entry(api, recent_id)["billable_amount"], 3125.00,
                 "time_entry.billable_amount")

    report = read_aging(api, ctx.project_id)
    assert report["project_id"] == ctx.project_id, (
        f"wip_aging.project_id: expected {ctx.project_id}, got {report['project_id']}"
    )
    assert report["as_of_date"] == "2026-06-01", (
        f"wip_aging.as_of_date: expected 2026-06-01, got {report['as_of_date']}"
    )
    assert_aging_report(
        report,
        bucket_0_30=8125.00,
        bucket_31_60=0.00,
        bucket_61_90=156.25,
        bucket_over_90=0.00,
        total_unbilled=8281.25,
        write_off_eligible_amount=0.00,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(project, unbilled_wip=8281.25, total_charge_value=8281.25)
    assert_billing_posture(project, POSTURE_OPEN)
    assert project["overhead_adjustment_required"] is False, (
        "project.overhead_adjustment_required must still be False before any "
        f"controller-level approval, got {project['overhead_adjustment_required']}"
    )


def test_the_charge_exactly_ninety_days_old_still_escalates_to_the_controller(api):
    """
    The other half of the asymmetry, on the same 90-day-old charge. Writing off its
    156.25 escalates to controller authority purely on age — the amount is nowhere
    near the 5000.00 escalation figure — even though the aging report refuses to
    count that charge as write-off eligible at all. The frozen age is the greatest
    age among the allocated charges, which here is the single charge at 90 days.

    PRD §3.8: "Note the deliberate asymmetry between the report and the approval routing that follows: the over-90 bucket is strictly more than 90 days old, while write-off routing escalates to a `Controller` at 90 days or more. A charge exactly 90 days old therefore still sits in `bucket_61_90` and is not counted as write-off eligible, yet a write-off touching it already demands `Controller` authority."
    PRD §3.8: "`required_approver` is set to `CONTROLLER` when the `amount` is at or above 5000.00 or the `aging_days` is at or above 90 — both thresholds inclusive, so an amount of exactly 5000.00 and an age of exactly 90 days each escalate — and to `PROJECT_MANAGER` otherwise."
    PRD §3.8: "The write-off's initial `status` is `PENDING_CONTROLLER_APPROVAL` when `required_approver` is `CONTROLLER` and `PENDING_PM_APPROVAL` when it is `PROJECT_MANAGER`."
    PRD §3.8: "`aging_days` is frozen at the greatest age in whole days among those allocated entries, measured from each entry's `work_date` against the logical clock."

    Design: Difficulty/boundary_precision_check/write_off_routing_inclusive_thresholds_vs_exclusive_aging_bucket
    """
    ctx, stale_id, _principal_id, _recent_id = (
        _stand_up_three_unbilled_charges_across_the_ninety_day_edge(api)
    )

    write_off = prepare_labor_write_off(
        api, ctx, 156.25, reason="Stale charge on cancelled study"
    )
    assert_money(write_off["amount"], 156.25, "write_off.amount")
    assert write_off["amount"] < WRITE_OFF_CONTROLLER_AMOUNT, (
        f"write_off.amount {write_off['amount']} must sit below the "
        f"{WRITE_OFF_CONTROLLER_AMOUNT} escalation figure so only age can escalate it"
    )
    assert_write_off_routing(
        write_off,
        required_approver=APPROVER_CONTROLLER,
        status=WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
        aging_days=WRITE_OFF_CONTROLLER_AGING_DAYS,
        allocated_time_entry_ids=[stale_id],
    )

    assert_aging_report(
        read_aging(api, ctx.project_id),
        bucket_61_90=156.25,
        bucket_over_90=0.00,
        write_off_eligible_amount=0.00,
        total_unbilled=8281.25,
    )
    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=8281.25,
        written_off_gross=0.00,
        total_charge_value=8281.25,
    )
    assert read_time_entry(api, stale_id)["status"] == TIME_ENTRY_APPROVED, (
        "the allocated charge stays APPROVED until the write-off is approved"
    )


def test_a_write_off_of_exactly_five_thousand_escalates_and_refuses_the_manager(api):
    """
    The money threshold is inclusive at its stated figure. A write-off of exactly
    5000.00 against a charge only 21 days old escalates to controller authority on
    amount alone, and the project manager who owns the project is refused when he
    tries to approve it — a refusal that leaves the write-off exactly where it was,
    still awaiting the controller who then approves it.

    PRD §3.8: "`required_approver` is set to `CONTROLLER` when the `amount` is at or above 5000.00 or the `aging_days` is at or above 90 — both thresholds inclusive, so an amount of exactly 5000.00 and an age of exactly 90 days each escalate — and to `PROJECT_MANAGER` otherwise."
    PRD §3.8: "On the controller branch, only an acting `Controller` may approve a write-off sitting in `PENDING_CONTROLLER_APPROVAL` — a `ProjectManager` attempting it is refused with `ERR_APPROVAL_LEVEL_INSUFFICIENT` — and the acting `X-User-ID` must likewise differ from `prepared_by_user_id`."

    Design: Difficulty/boundary_precision_check/write_off_routing_inclusive_thresholds_vs_exclusive_aging_bucket
    """
    ctx, stale_id, principal_id, _recent_id = (
        _stand_up_three_unbilled_charges_across_the_ninety_day_edge(api)
    )

    # The oldest charge must be cleared first: an amount is only allocatable when it
    # equals an exact prefix sum of the remaining charges in chronological order.
    stale_write_off = prepare_labor_write_off(
        api, ctx, 156.25, reason="Stale charge on cancelled study"
    )
    approve_write_off(api, stale_write_off["id"], CONTROLLER)

    write_off = prepare_labor_write_off(
        api, ctx, 5000.00, reason="Unbillable principal review time"
    )
    assert_money(write_off["amount"], WRITE_OFF_CONTROLLER_AMOUNT, "write_off.amount")
    assert_write_off_routing(
        write_off,
        required_approver=APPROVER_CONTROLLER,
        status=WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
        aging_days=21,
        allocated_time_entry_ids=[principal_id],
    )

    refused = api.approve_write_off(write_off["id"], PROJECT_MANAGER)
    validate_error(refused, ERR_APPROVAL_LEVEL_INSUFFICIENT, 403)
    assert_write_off_routing(
        read_write_off(api, write_off["id"]),
        required_approver=APPROVER_CONTROLLER,
        status=WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
        aging_days=21,
        allocated_time_entry_ids=[principal_id],
    )
    assert read_time_entry(api, principal_id)["status"] == TIME_ENTRY_APPROVED, (
        "the refused approval may not move the allocated charge"
    )

    approved = get_success_data(api.approve_write_off(write_off["id"], CONTROLLER))
    assert approved["status"] == WRITE_OFF_APPROVED, (
        f"write_off.status: expected {WRITE_OFF_APPROVED}, got {approved['status']}"
    )
    assert read_time_entry(api, principal_id)["status"] == TIME_ENTRY_WRITTEN_OFF, (
        "the controller approval must move the allocated charge to WRITTEN_OFF"
    )
    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=3125.00,
        written_off_gross=5156.25,
        total_charge_value=8281.25,
    )
    assert read_time_entry(api, stale_id)["status"] == TIME_ENTRY_WRITTEN_OFF, (
        "the earlier controller-level write-off stays settled"
    )


def test_below_both_thresholds_the_write_off_routes_to_the_project_manager(api):
    """
    The third charge is under both edges — 3125.00 and 20 days old — so it routes to
    the project manager, who may approve it himself. Taking all three write-offs in
    turn also pins the allocation rule: each amount is an exact prefix of what is
    left in chronological order, so each write-off names exactly one charge. The
    unbilled position ends at 0.00 with the whole 8281.25 written off, the conserved
    total unchanged, and the overhead disclosure flag raised by the two write-offs
    that took the controller branch.

    PRD §3.8: "The candidate list is the project's time entries whose `status` is `APPROVED` and whose `billed_invoice_id` is null, ordered by `work_date` ascending and then by `created_at` ascending — never by `id`."
    PRD §3.8: "On success, `allocated_time_entry_ids` holds the ordered list of identifiers the amount was allocated to, and `aging_days` is frozen at the greatest age in whole days among those allocated entries, measured from each entry's `work_date` against the logical clock."
    PRD §3.8: "Every time entry named in `allocated_time_entry_ids` moves `APPROVED → WRITTEN_OFF`, each such entry's `version` incrementing by 1; the project's `unbilled_wip` falls by the write-off `amount` while `written_off_gross` rises by the same amount"
    PRD §3.8: "This branch, and only this branch, sets the project's `overhead_adjustment_required` flag to true, because a write-off approved at controller level must be disclosed in the firm's next overhead certification."

    Design: Difficulty/boundary_precision_check/write_off_routing_inclusive_thresholds_vs_exclusive_aging_bucket
    """
    ctx, stale_id, principal_id, recent_id = (
        _stand_up_three_unbilled_charges_across_the_ninety_day_edge(api)
    )

    stale_write_off = prepare_labor_write_off(
        api, ctx, 156.25, reason="Stale charge on cancelled study"
    )
    assert_write_off_routing(
        stale_write_off, allocated_time_entry_ids=[stale_id], aging_days=90
    )
    approve_write_off(api, stale_write_off["id"], CONTROLLER)

    principal_write_off = prepare_labor_write_off(
        api, ctx, 5000.00, reason="Unbillable principal review time"
    )
    assert_write_off_routing(
        principal_write_off, allocated_time_entry_ids=[principal_id], aging_days=21
    )
    approve_write_off(api, principal_write_off["id"], CONTROLLER)

    recent_write_off = prepare_labor_write_off(
        api, ctx, 3125.00, reason="Scope creep absorbed by the firm"
    )
    assert_money(recent_write_off["amount"], 3125.00, "write_off.amount")
    assert_write_off_routing(
        recent_write_off,
        required_approver=APPROVER_PROJECT_MANAGER,
        status=WRITE_OFF_PENDING_PM_APPROVAL,
        aging_days=20,
        allocated_time_entry_ids=[recent_id],
    )

    settled = approve_write_off(api, recent_write_off["id"], PROJECT_MANAGER)
    assert settled["status"] == WRITE_OFF_APPROVED, (
        f"write_off.status: expected {WRITE_OFF_APPROVED}, got {settled['status']}"
    )

    for entry_id in (stale_id, principal_id, recent_id):
        entry = read_time_entry(api, entry_id)
        assert entry["status"] == TIME_ENTRY_WRITTEN_OFF, (
            f"time_entry.status: expected {TIME_ENTRY_WRITTEN_OFF}, got {entry['status']}"
        )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=8281.25,
        total_charge_value=8281.25,
    )
    assert project["overhead_adjustment_required"] is True, (
        "project.overhead_adjustment_required must be True once a write-off has "
        "been approved at controller level, got "
        f"{project['overhead_adjustment_required']}"
    )
    assert_aging_report(
        read_aging(api, ctx.project_id),
        bucket_0_30=0.00,
        bucket_31_60=0.00,
        bucket_61_90=0.00,
        bucket_over_90=0.00,
        total_unbilled=0.00,
        write_off_eligible_amount=0.00,
    )


def _stand_up_three_phases_with_contrasting_labour_budgets(api):
    """
    One project, three root phases that differ only in the denominator of their
    cost-to-cost completion, and one identical 7.35 h charge waiting on each: at
    62.50 an hour every charge freezes a raw cost of 459.38 and, under the 3.0500
    multiplier, a billable amount of 1401.11. The 01-SD phase budgets 0.00 of
    labour, 02-DD budgets exactly the 459.38 the charge will consume, and 03-CD
    budgets 229.69, half of it. The alert threshold is set to exactly the 4203.33
    the three charges will together leave unbilled.
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    publish_labor_rate(api)
    project = create_project(
        api, client["id"], name="Harbor Museum Fitout", wip_alert_threshold=4203.33
    )
    zero_budget = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="01-SD",
        lump_sum_fee=100000.00,
        budget_labor_cost=0.00,
    )
    exact_budget = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="02-DD",
        lump_sum_fee=120000.00,
        budget_labor_cost=459.38,
    )
    overrun_budget = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="03-CD",
        lump_sum_fee=80000.00,
        budget_labor_cost=229.69,
    )
    set_multiplier(api, project["id"], multiplier=3.0500, effective_from="2026-01-01")
    activate_project(api, project["id"])

    ctx = ProjectContext(
        client_id=client["id"],
        project_id=project["id"],
        version=project_version(api, project["id"]),
        phase_ids=[zero_budget["id"], exact_budget["id"], overrun_budget["id"]],
    )
    entry_ids = [
        submit_time_entry(
            api, ctx, hours=7.35, work_date="2026-05-11", phase_id=phase_id
        )["id"]
        for phase_id in ctx.phase_ids
    ]
    return ctx, entry_ids


def test_a_phase_budgeting_no_labour_reports_zero_completion_rather_than_failing(api):
    """
    A denominator of exactly 0.00 is a guarded case, not an error and not a
    complete phase: the charge still raises the phase's actual labour cost to
    459.38, but its cost-to-cost completion reads 0.0000 and it recognises nothing
    of its 100000.00 fee. The project-level ratio is guarded the same way: before
    any charge is approved the raw labour cost is 0.00, and the net multiplier
    reports 0.0000 rather than being undefined.

    PRD §3.6: "From it, `effort_based_percent_complete` is `actual_labor_cost_to_date` divided by `budget_labor_cost`, rounded half up to 4 decimal places and then capped at 1.0000 by taking the lesser of the two; when `budget_labor_cost` is exactly 0.00 the figure is 0.0000 rather than undefined."
    PRD §3.6: "`effort_based_earned_value` is then the `phase_fee` multiplied by `effort_based_percent_complete`, rounded half up to 2 decimal places."
    PRD §2.10: "When `raw_labor_cost_to_date` is exactly 0.00, `net_multiplier_achieved` reports 0.0000 rather than being undefined."

    Design: Difficulty/boundary_precision_check/earned_value_denominator_and_posture_comparison_edges
    """
    ctx, entry_ids = _stand_up_three_phases_with_contrasting_labour_budgets(api)

    before = read_project(api, ctx.project_id)
    assert_project_ledger(
        before,
        raw_labor_cost_to_date=0.00,
        unbilled_wip=0.00,
        total_charge_value=0.00,
        earned_revenue_to_date=0.00,
        net_multiplier_achieved=0.0000,
    )
    assert_billing_posture(before, POSTURE_OPEN)

    approved = approve_time_entry(api, entry_ids[0])
    assert approved["status"] == TIME_ENTRY_APPROVED, (
        f"time_entry.status: expected {TIME_ENTRY_APPROVED}, got {approved['status']}"
    )
    assert_money(approved["raw_cost"], 459.38, "time_entry.raw_cost")
    assert_ratio(approved["applied_multiplier"], 3.0500, "time_entry.applied_multiplier")
    assert_money(approved["billable_amount"], 1401.11, "time_entry.billable_amount")

    assert_phase_earned_value(
        read_phase(api, ctx.phase_ids[0]),
        phase_fee=100000.00,
        actual_labor_cost_to_date=459.38,
        effort_based_percent_complete=0.0000,
        effort_based_earned_value=0.00,
        recognized_earned_value=0.00,
    )
    assert_project_ledger(
        read_project(api, ctx.project_id),
        raw_labor_cost_to_date=459.38,
        unbilled_wip=1401.11,
        total_charge_value=1401.11,
        earned_revenue_to_date=0.00,
        net_multiplier_achieved=3.0500,
    )


def test_actual_cost_exactly_consuming_the_budget_lands_on_full_completion(api):
    """
    The 1.0000 edge reached from below. The 02-DD phase budgets exactly the 459.38
    of labour cost the charge freezes, so its cost-to-cost completion is exactly
    1.0000 and it recognises its whole 120000.00 fee while its status is still only
    IN_PROGRESS — the full fee here is the arithmetic, not the completion event.

    PRD §3.6: "From it, `effort_based_percent_complete` is `actual_labor_cost_to_date` divided by `budget_labor_cost`, rounded half up to 4 decimal places and then capped at 1.0000 by taking the lesser of the two; when `budget_labor_cost` is exactly 0.00 the figure is 0.0000 rather than undefined."
    PRD §3.6: "`recognized_earned_value` — the single figure that rolls up into the project — is chosen in this order: it is the full `phase_fee` whenever the phase's `status` is `COMPLETE`; otherwise it is `effort_based_earned_value` when the project's `percent_complete_method` is `EFFORT_BASED`; otherwise it is `assessed_earned_value`."

    Design: Difficulty/boundary_precision_check/earned_value_denominator_and_posture_comparison_edges
    """
    ctx, entry_ids = _stand_up_three_phases_with_contrasting_labour_budgets(api)

    approve_time_entry(api, entry_ids[1])

    phase = read_phase(api, ctx.phase_ids[1])
    assert_money(phase["budget_labor_cost"], 459.38, "phase.budget_labor_cost")
    assert_phase_earned_value(
        phase,
        phase_fee=120000.00,
        actual_labor_cost_to_date=459.38,
        effort_based_percent_complete=1.0000,
        effort_based_earned_value=120000.00,
        assessed_percent_complete=0.0000,
        assessed_earned_value=0.00,
        recognized_earned_value=120000.00,
    )
    assert_project_ledger(
        read_project(api, ctx.project_id),
        raw_labor_cost_to_date=459.38,
        unbilled_wip=1401.11,
        total_charge_value=1401.11,
        earned_revenue_to_date=120000.00,
    )


def test_actual_cost_overrunning_the_budget_clamps_completion_at_one(api):
    """
    The same edge crossed from above. The 03-CD phase budgets 229.69 against the
    459.38 the charge freezes — a raw ratio of exactly 2.0000 — and the cap takes
    the lesser of the two, so completion reads 1.0000 and the phase recognises
    80000.00 rather than the 160000.00 the uncapped ratio would claim. The
    side-by-side computed read tells the same story and names the route it took.

    PRD §3.6: "From it, `effort_based_percent_complete` is `actual_labor_cost_to_date` divided by `budget_labor_cost`, rounded half up to 4 decimal places and then capped at 1.0000 by taking the lesser of the two; when `budget_labor_cost` is exactly 0.00 the figure is 0.0000 rather than undefined."
    PRD §3.6: "A computed read exposes both routes side by side for exactly this reason, returning `phase_id`, `phase_fee`, `budget_labor_cost`, `actual_labor_cost_to_date`, `effort_based_percent_complete`, `effort_based_earned_value`, `assessed_percent_complete`, `assessed_earned_value`, `selected_method` and `recognized_earned_value`."

    Design: Difficulty/boundary_precision_check/earned_value_denominator_and_posture_comparison_edges
    """
    ctx, entry_ids = _stand_up_three_phases_with_contrasting_labour_budgets(api)

    approve_time_entry(api, entry_ids[2])

    phase = read_phase(api, ctx.phase_ids[2])
    assert_money(phase["budget_labor_cost"], 229.69, "phase.budget_labor_cost")
    assert_phase_earned_value(
        phase,
        phase_fee=80000.00,
        actual_labor_cost_to_date=459.38,
        effort_based_percent_complete=1.0000,
        effort_based_earned_value=80000.00,
        recognized_earned_value=80000.00,
    )

    report = read_earned_value(api, ctx.phase_ids[2])
    assert report["phase_id"] == ctx.phase_ids[2], (
        f"earned_value.phase_id: expected {ctx.phase_ids[2]}, got {report['phase_id']}"
    )
    assert_money(report["budget_labor_cost"], 229.69, "earned_value.budget_labor_cost")
    assert_earned_value_report(
        report,
        phase_fee=80000.00,
        actual_labor_cost_to_date=459.38,
        effort_based_percent_complete=1.0000,
        effort_based_earned_value=80000.00,
        assessed_percent_complete=0.0000,
        assessed_earned_value=0.00,
        recognized_earned_value=80000.00,
        selected_method=METHOD_EFFORT_BASED,
    )


def test_unbilled_work_exactly_at_the_alert_threshold_leaves_the_project_open(api):
    """
    With all three charges approved the project's position is exactly its own alert
    threshold — 4203.33 against 4203.33 — and the comparison is strict, so the
    project stays open rather than moving into review. The rest of the rollup pins
    the three phases together: 1378.14 of raw labour cost, a net multiplier back at
    the 3.0500 that priced every charge, and 200000.00 of earned revenue summed over
    the leaf phases, the zero-budget phase contributing nothing at all.

    PRD §2.11: "Otherwise, if `unbilled_wip` is strictly greater than the project's `wip_alert_threshold`, the posture is `REVIEW_REQUIRED`. The comparison is strict: `unbilled_wip` exactly equal to `wip_alert_threshold` leaves the posture `OPEN`."
    PRD §2.10: "`earned_revenue_to_date` is the sum of `recognized_earned_value` over the project's **leaf** phases only; a non-leaf phase contributes nothing, because its fee is already represented by its children."
    PRD §2.10: "`net_multiplier_achieved` is the project's billable labour value divided by its raw labour cost: the sum of `billable_amount` over time entries whose `status` is `APPROVED`, `BILLED` or `WRITTEN_OFF`, divided by `raw_labor_cost_to_date`, rounded half up to 4 decimal places."

    Design: Difficulty/boundary_precision_check/earned_value_denominator_and_posture_comparison_edges
    """
    ctx, entry_ids = _stand_up_three_phases_with_contrasting_labour_budgets(api)

    for entry_id in entry_ids:
        approve_time_entry(api, entry_id)

    assert_phase_earned_value(
        read_phase(api, ctx.phase_ids[0]),
        effort_based_percent_complete=0.0000,
        recognized_earned_value=0.00,
    )
    assert_phase_earned_value(
        read_phase(api, ctx.phase_ids[1]),
        effort_based_percent_complete=1.0000,
        recognized_earned_value=120000.00,
    )
    assert_phase_earned_value(
        read_phase(api, ctx.phase_ids[2]),
        effort_based_percent_complete=1.0000,
        recognized_earned_value=80000.00,
    )

    project = read_project(api, ctx.project_id)
    assert_money(project["wip_alert_threshold"], 4203.33, "project.wip_alert_threshold")
    assert_project_ledger(
        project,
        raw_labor_cost_to_date=1378.14,
        unbilled_wip=4203.33,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=4203.33,
        earned_revenue_to_date=200000.00,
        net_multiplier_achieved=3.0500,
    )
    assert_billing_posture(project, POSTURE_OPEN)
