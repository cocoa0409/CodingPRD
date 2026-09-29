"""
Derived reads of the architecture practice project accounting API.

The firm's profitability panel is not a stored report. Retrieving a project
recomputes its whole ledger position, retrieving a phase re-evaluates its
earned-value figures, and the two computed reads — the phase earned-value
payload and the project work-in-progress aging payload — are assembled from the
live charge population every time they are asked for. These tests drive the
charges through the PRD's own endpoints and then read the panel back, checking
that a blended achieved multiplier, both competing percent-complete variants,
the aging buckets and the consultant payable's link to its project are all
current on the very first request that follows the write.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_aging_report,
    assert_computed_report,
    assert_earned_value_report,
    assert_invoice_money,
    assert_money,
    assert_payable_axes,
    assert_payable_markup,
    assert_project_ledger,
    assert_ratio,
    assert_swept_counts,
    assert_time_entry_frozen,
)
from test_helpers.constants import (
    CLOCK_2026_06_01,
    METHOD_EFFORT_BASED,
    PAYABLE_APPROVED,
    PAYABLE_BILLED_TO_CLIENT,
    PAYABLE_RECEIVED,
    PAYABLE_UNBILLED,
    PAYMENT_WITHHELD,
    TIME_ENTRY_APPROVED,
    TIME_ENTRY_BILLED,
)
from test_helpers.fixtures import (
    add_approved_time_entry,
    add_executed_subcontract,
    build_active_project,
    enter_payable,
    prepare_invoice,
    read_aging,
    read_earned_value,
    read_phase,
    read_project,
    read_time_entry,
    refresh_version,
    set_multiplier,
    submit_time_entry,
)
from test_helpers.test_users import ACCOUNTANT, CONTROLLER, PROJECT_MANAGER

# The two multiplier windows the profitability read blends: 2.5000 governs work
# up to 2026-05-01 and 3.0500 governs work from that date on.
EARLY_MULTIPLIER = 2.5000
LATE_MULTIPLIER = 3.0500
BOUNDARY_DATE = "2026-05-01"
WORK_DATE_BEFORE_BOUNDARY = "2026-04-15"
WORK_DATE_AFTER_BOUNDARY = "2026-05-15"


def _project_with_two_multiplier_windows(api):
    """
    An ACTIVE time-and-materials project whose incumbent 2.5000 multiplier has
    been superseded by 3.0500 from 2026-05-01, carrying one approved 8.00 h line
    on each side of that boundary.
    """
    ctx = build_active_project(
        api,
        clock=CLOCK_2026_06_01,
        multiplier=EARLY_MULTIPLIER,
        multiplier_effective_from="2026-01-01",
    )
    set_multiplier(
        api, ctx.project_id, multiplier=LATE_MULTIPLIER, effective_from=BOUNDARY_DATE
    )
    early_entry = add_approved_time_entry(
        api, ctx, hours=8.00, work_date=WORK_DATE_BEFORE_BOUNDARY
    )
    late_entry = add_approved_time_entry(
        api, ctx, hours=8.00, work_date=WORK_DATE_AFTER_BOUNDARY
    )
    refresh_version(api, ctx)
    return ctx, early_entry, late_entry


def test_project_read_blends_two_multiplier_windows_into_the_achieved_multiplier(api):
    """
    Retrieving the project recomputes the whole profitability panel, and with one
    8.00 h line billed at 2.5000 and another at 3.0500 the achieved multiplier is
    a blend of 2.7750 — neither window's own factor and below the 3.0000 target.

    PRD §3.2: "A `SUPERSEDED` multiplier is not dead history: it still governs every work date that falls inside its now-truncated interval, so both `ACTIVE` and `SUPERSEDED` rows participate in multiplier resolution."
    PRD §2.10: "`net_multiplier_achieved` is the project's billable labour value divided by its raw labour cost: the sum of `billable_amount` over time entries whose `status` is `APPROVED`, `BILLED` or `WRITTEN_OFF`, divided by `raw_labor_cost_to_date`, rounded half up to 4 decimal places."

    Design: Corner/endpoints/profitability_and_earned_value_are_computed_reads
    """
    ctx, early_entry, late_entry = _project_with_two_multiplier_windows(api)

    # The truncated 2.5000 window still governs the 2026-04-15 work date.
    assert_time_entry_frozen(early_entry, 500.00, EARLY_MULTIPLIER, 1250.00)
    assert_time_entry_frozen(late_entry, 500.00, LATE_MULTIPLIER, 1525.00)

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        raw_labor_cost_to_date=1000.00,
        unbilled_wip=2775.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=2775.00,
        earned_revenue_to_date=3340.00,
        net_multiplier_achieved=2.7750,
    )
    assert_ratio(project["target_multiplier"], 3.0000, "project.target_multiplier")
    assert project["overhead_adjustment_required"] is False, (
        "no controller-level write-off has been approved, so the overhead "
        f"adjustment flag must still be false: {project['overhead_adjustment_required']!r}"
    )


def test_earned_value_read_reports_both_percent_complete_variants_side_by_side(api):
    """
    The phase earned-value read exposes the cost-to-cost route and the assessed
    route together even though only the project's declared method is recognised,
    and it is a computed payload rather than a persisted row.

    PRD §3.6: "A computed read exposes both routes side by side for exactly this reason, returning `phase_id`, `phase_fee`, `budget_labor_cost`, `actual_labor_cost_to_date`, `effort_based_percent_complete`, `effort_based_earned_value`, `assessed_percent_complete`, `assessed_earned_value`, `selected_method` and `recognized_earned_value`."
    PRD §3.6: "That payload is a computed report, not a persisted entity, and it therefore carries none of the common resource properties of §2.4."

    Design: Corner/endpoints/profitability_and_earned_value_are_computed_reads
    """
    ctx, _early_entry, _late_entry = _project_with_two_multiplier_windows(api)

    report = read_earned_value(api, ctx.phase_id)

    assert report["phase_id"] == ctx.phase_id
    assert_money(report["budget_labor_cost"], 60000.00, "earned_value.budget_labor_cost")
    assert_earned_value_report(
        report,
        phase_fee=200000.00,
        actual_labor_cost_to_date=1000.00,
        effort_based_percent_complete=0.0167,
        effort_based_earned_value=3340.00,
        assessed_percent_complete=0.0000,
        assessed_earned_value=0.00,
        selected_method=METHOD_EFFORT_BASED,
        recognized_earned_value=3340.00,
    )
    assert_computed_report(report)


def test_wip_aging_read_buckets_each_window_by_age_against_the_logical_clock(api):
    """
    With the logical clock at 2026-06-01 the 2026-05-15 line is 17 days old and
    the 2026-04-15 line is 47 days old, so the aging read splits 1525.00 into the
    youngest bucket and 1250.00 into the next one, with nothing write-off eligible.

    PRD §3.8: "`bucket_0_30` holds the value of charges aged 30 days or fewer, `bucket_31_60` those aged 31 through 60 days inclusive, `bucket_61_90` those aged 61 through 90 days inclusive, and `bucket_over_90` those aged 91 days or more."
    PRD §3.8: "`total_unbilled` is the sum of the four buckets and must equal the project's `unbilled_wip`."

    Design: Corner/endpoints/profitability_and_earned_value_are_computed_reads
    """
    ctx, _early_entry, _late_entry = _project_with_two_multiplier_windows(api)

    report = read_aging(api, ctx.project_id)

    assert report["project_id"] == ctx.project_id
    assert report["as_of_date"] == "2026-06-01", (
        f"as_of_date must be the calendar date of the logical clock: {report['as_of_date']!r}"
    )
    assert_aging_report(
        report,
        bucket_0_30=1525.00,
        bucket_31_60=1250.00,
        bucket_61_90=0.00,
        bucket_over_90=0.00,
        total_unbilled=2775.00,
        write_off_eligible_amount=0.00,
    )
    assert_computed_report(report)

    project = read_project(api, ctx.project_id)
    assert_money(
        report["total_unbilled"],
        project["unbilled_wip"],
        "wip_aging.total_unbilled against project.unbilled_wip",
    )


def _project_with_executed_subcontract_and_labor(api):
    """
    An ACTIVE time-and-materials project with one executed 20000.00 consultant
    subcontract on a phase carrying a 100000.00 consultant budget, plus one
    approved 4.00 h line worth 762.50 of billable labour.
    """
    ctx = build_active_project(
        api,
        clock=CLOCK_2026_06_01,
        multiplier=LATE_MULTIPLIER,
        phase_overrides={"consultant_budget": 100000.00},
    )
    subcontract = add_executed_subcontract(
        api,
        ctx,
        committed_amount=20000.00,
        commitment_start="2026-01-01",
        commitment_end="2026-12-31",
    )
    entry = add_approved_time_entry(api, ctx, hours=4.00, work_date="2026-05-11")
    refresh_version(api, ctx)
    return ctx, subcontract, entry


def test_payable_entry_naming_an_unresolvable_subcontract_creates_nothing(api):
    """
    A consultant payable reaches its project only through `subcontract_id`, and
    that identifier arrives in the creation payload, so an identifier that does
    not resolve is a body foreign-key fault and no payable row is written.

    PRD §2.9: "When `client_id`, `project_id`, `phase_id`, `parent_phase_id`, `subcontract_id` or `invoice_id` appears in a creation payload and does not resolve — or when a referenced `phase_id` resolves but belongs to a project other than the referenced `project_id` — the request is rejected with `ERR_INVALID_REFERENCE` (HTTP 422)."
    PRD §2.9: "This applies to project creation, phase creation, time entry creation, expense creation, subcontract creation, consultant payable creation and write-off creation."

    Design: Corner/endpoints/payables_link_to_the_project_only_through_the_subcontract
    """
    ctx, subcontract, _entry = _project_with_executed_subcontract_and_labor(api)

    response = api.create_consultant_invoice(
        f.consultant_invoice_payload(
            NON_EXISTENT_UUID,
            amount=5000.00,
            invoice_date="2026-05-20",
            backup_attached=True,
        ),
        ACCOUNTANT,
    )
    validate_error(response, err.ERR_INVALID_REFERENCE, 422)

    rows, meta = validate_paginated(
        api.list_consultant_invoices(CONTROLLER, {"subcontract_id": subcontract["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused entry must not have written a payable row: {rows}"
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(project, unbilled_wip=762.50, total_charge_value=762.50)


def test_approving_the_payable_reaches_the_project_through_its_subcontract(api):
    """
    A payable is entered against the subcontract alone, lands on all three status
    axes at their opening values, and once approved its marked-up 22000.00 joins
    the 762.50 of labour in the owning project's work in progress.

    PRD §3.5: "A payable carries **three independent status axes**: `approval_status`, which begins at `RECEIVED`; `payment_status`, which begins at `WITHHELD`; and `billing_status`, which begins at `UNBILLED`."
    PRD §3.5: "A base markup fraction of 0.1000 applies as standard; once `approved_cost_to_date` reaches 250000.00 the base drops to 0.0600, and the threshold is inclusive, so cumulative approved consultant cost of exactly 250000.00 already selects the lower tier."
    PRD §3.5: "The project's `unbilled_wip` rises by the payable's `billable_amount`, which re-runs `billing_posture`."

    Design: Corner/endpoints/payables_link_to_the_project_only_through_the_subcontract
    """
    ctx, subcontract, _entry = _project_with_executed_subcontract_and_labor(api)

    created = get_success_data(
        api.create_consultant_invoice(
            f.consultant_invoice_payload(
                subcontract["id"],
                amount=20000.00,
                invoice_date="2026-05-20",
                backup_attached=True,
            ),
            ACCOUNTANT,
        ),
        201,
    )
    assert created["subcontract_id"] == subcontract["id"]
    assert_payable_axes(created, PAYABLE_RECEIVED, PAYMENT_WITHHELD, PAYABLE_UNBILLED)
    assert_payable_markup(created, 0.0000, 0.00, 0.00)

    approved = validate_success(
        api.approve_consultant_invoice(created["id"], CONTROLLER)
    )
    assert_payable_axes(approved, PAYABLE_APPROVED, PAYMENT_WITHHELD, PAYABLE_UNBILLED)
    assert_payable_markup(approved, 0.1000, 2000.00, 22000.00)

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=22762.50,
        billed_open=0.00,
        total_charge_value=22762.50,
    )

    rows, meta = validate_paginated(
        api.list_consultant_invoices(CONTROLLER, {"subcontract_id": subcontract["id"]})
    )
    assert meta["total_count"] == 1, f"expected exactly one payable, got {meta}"
    assert rows[0]["id"] == created["id"]


def test_swept_populations_are_discoverable_only_through_the_invoice_link_filters(api):
    """
    The invoice row itself lists no members. Learning that it swept the 22000.00
    payable and the 762.50 labour line means filtering the payable list by
    `client_invoice_id` and the time entry list by `billed_invoice_id`.

    PRD §2.9: "Filtering time entries by `billed_invoice_id` is the only way to learn which entries an invoice swept; filtering consultant payables by `client_invoice_id` is the only way to learn which payables it swept."
    PRD §3.7: "Third, `retainage_amount` is keyed on the **post-discount** base and never on `gross_billed` itself: it is `gross_billed` less `discount_amount`, multiplied by the client's `retainage_pct`, rounded half up to 2 decimal places. Fourth, `net_due` is `gross_billed` less `discount_amount` less `retainage_amount`."

    Design: Corner/endpoints/payables_link_to_the_project_only_through_the_subcontract
    """
    ctx, subcontract, entry = _project_with_executed_subcontract_and_labor(api)
    payable = enter_payable(
        api, subcontract["id"], amount=20000.00, invoice_date="2026-05-20"
    )
    validate_success(api.approve_consultant_invoice(payable["id"], CONTROLLER))

    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")

    assert_invoice_money(
        invoice,
        labor_billed=762.50,
        expense_billed=0.00,
        consultant_billed=22000.00,
        gross_billed=22762.50,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=1138.13,
        net_due=21624.37,
    )
    assert_swept_counts(
        invoice,
        swept_labor_count=1,
        swept_expense_count=0,
        swept_consultant_count=1,
        backup_missing_count=0,
    )

    swept_payables, payable_meta = validate_paginated(
        api.list_consultant_invoices(CONTROLLER, {"client_invoice_id": invoice["id"]})
    )
    assert payable_meta["total_count"] == 1, (
        f"exactly the one payable must be reachable through the invoice link: {payable_meta}"
    )
    assert swept_payables[0]["id"] == payable["id"]
    assert swept_payables[0]["billing_status"] == PAYABLE_BILLED_TO_CLIENT
    assert swept_payables[0]["client_invoice_id"] == invoice["id"]

    swept_entries, entry_meta = validate_paginated(
        api.list_time_entries(CONTROLLER, {"billed_invoice_id": invoice["id"]})
    )
    assert entry_meta["total_count"] == 1, (
        f"exactly the one labour line must be reachable through the invoice link: {entry_meta}"
    )
    assert swept_entries[0]["id"] == entry["id"]
    assert swept_entries[0]["status"] == TIME_ENTRY_BILLED


def _project_with_one_submitted_line(api):
    """
    An ACTIVE time-and-materials project at multiplier 3.0500 carrying a single
    4.00 h line dated 2026-05-11 that is still awaiting approval.
    """
    ctx = build_active_project(api, clock=CLOCK_2026_06_01, multiplier=LATE_MULTIPLIER)
    entry = submit_time_entry(api, ctx, hours=4.00, work_date="2026-05-11")
    return ctx, entry


def test_one_approval_is_current_in_every_derived_read_that_follows_it(api):
    """
    Approving one 4.00 h line freezes 250.00 of raw cost and 762.50 of billable
    value, and the phase accumulator, both computed reads and the project ledger
    all carry that value on the first request after the approval, with no refresh
    call in between.

    PRD §3.3: "Approval sets `approved_by_user_id` from the request header and then propagates in four hops, each of which must be visible in the same response cycle."
    PRD §2.10: "Retrieving a single phase re-evaluates that phase's earned-value figures before returning them, and retrieving a single consultant subcontract re-evaluates its commitment rollup — `approved_to_date`, `released_to_date` and `committed_remaining` — before returning it."
    PRD §3.3: "A `SUBMITTED` line contributes to no project rollup and appears in no aging bucket."
    PRD §3.6: "From it, `effort_based_percent_complete` is `actual_labor_cost_to_date` divided by `budget_labor_cost`, rounded half up to 4 decimal places and then capped at 1.0000 by taking the lesser of the two; when `budget_labor_cost` is exactly 0.00 the figure is 0.0000 rather than undefined."

    Design: Corner/consistency_model/every_derived_read_is_current_in_the_very_next_request
    """
    ctx, entry = _project_with_one_submitted_line(api)

    before = read_earned_value(api, ctx.phase_id)
    assert_earned_value_report(
        before,
        effort_based_percent_complete=0.0000,
        effort_based_earned_value=0.00,
        recognized_earned_value=0.00,
        actual_labor_cost_to_date=0.00,
    )

    approved = validate_success(api.approve_time_entry(entry["id"], PROJECT_MANAGER))
    assert approved["status"] == TIME_ENTRY_APPROVED
    assert_time_entry_frozen(approved, 250.00, LATE_MULTIPLIER, 762.50)

    # First read of each derived surface after the approval, in one pass.
    assert_time_entry_frozen(
        read_time_entry(api, entry["id"]), 250.00, LATE_MULTIPLIER, 762.50
    )
    assert_money(
        read_phase(api, ctx.phase_id)["actual_labor_cost_to_date"],
        250.00,
        "phase.actual_labor_cost_to_date",
    )
    assert_earned_value_report(
        read_earned_value(api, ctx.phase_id),
        effort_based_percent_complete=0.0042,
        effort_based_earned_value=840.00,
        recognized_earned_value=840.00,
        actual_labor_cost_to_date=250.00,
        selected_method=METHOD_EFFORT_BASED,
    )
    assert_project_ledger(
        read_project(api, ctx.project_id),
        raw_labor_cost_to_date=250.00,
        unbilled_wip=762.50,
        total_charge_value=762.50,
        earned_revenue_to_date=840.00,
        net_multiplier_achieved=3.0500,
    )
    assert_aging_report(
        read_aging(api, ctx.project_id),
        bucket_0_30=762.50,
        bucket_31_60=0.00,
        total_unbilled=762.50,
        write_off_eligible_amount=0.00,
    )


def test_a_refused_repeat_approval_leaves_every_derived_read_untouched(api):
    """
    The mirror case of immediate consistency: a second approval of the same line
    is illegal for the state that line now sits in, and the refusal must not
    double-post the 762.50 — the project ledger, its version and the aging report
    are identical either side of the 409.

    PRD §2.8: "Declared-transition legality for the target row's current state — `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.3: "Four conditions guard the transition beyond the line simply being `SUBMITTED`: the acting `X-User-ID` must differ from the line's `submitted_by_user_id`, the owning project's `status` must be `ACTIVE`, a labour rate window must cover the pair of `role_code` and `work_date`, and a billing multiplier window on the project must cover the `work_date`."
    PRD §2.10: "The identity must hold after every request and after every hop of every cascade."

    Design: Corner/consistency_model/every_derived_read_is_current_in_the_very_next_request
    """
    ctx, entry = _project_with_one_submitted_line(api)
    validate_success(api.approve_time_entry(entry["id"], PROJECT_MANAGER))

    project_before = read_project(api, ctx.project_id)
    aging_before = read_aging(api, ctx.project_id)

    validate_error(
        api.approve_time_entry(entry["id"], PROJECT_MANAGER),
        err.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    project_after = read_project(api, ctx.project_id)
    aging_after = read_aging(api, ctx.project_id)

    assert_project_ledger(
        project_after,
        raw_labor_cost_to_date=250.00,
        unbilled_wip=762.50,
        total_charge_value=762.50,
    )
    assert project_after["version"] == project_before["version"], (
        "a refused approval must not mutate the project: version moved from "
        f"{project_before['version']} to {project_after['version']}"
    )
    for field in ("unbilled_wip", "billed_open", "total_charge_value", "earned_revenue_to_date"):
        assert_money(project_after[field], project_before[field], f"project.{field}")
    for bucket in ("bucket_0_30", "bucket_31_60", "bucket_61_90", "bucket_over_90", "total_unbilled"):
        assert_money(aging_after[bucket], aging_before[bucket], f"wip_aging.{bucket}")

    assert read_time_entry(api, entry["id"])["status"] == TIME_ENTRY_APPROVED
