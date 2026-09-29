"""
The pinned money arithmetic of the architecture practice project accounting API.

Covers which charges are visible to an aggregate at all, the inclusive receipt
threshold and the markup it earns at review, the volume-discount tier boundary
and the base retainage is taken on, the exact-prefix-sum allocation a labour
write-off demands, and the reconciliation a phase completion performs.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_WRITE_OFF_AMOUNT_NOT_ALLOCATABLE
from test_helpers.assertions import (
    assert_billing_posture,
    assert_expense_decision,
    assert_invoice_money,
    assert_money,
    assert_payable_axes,
    assert_payable_markup,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_swept_counts,
    assert_time_entry_carries_no_money,
    assert_write_off_routing,
)
from test_helpers.constants import (
    ALLOWABILITY_ALLOWED,
    ALLOWABILITY_DISALLOWED,
    ALLOWABILITY_PENDING_REVIEW,
    APPROVER_PROJECT_MANAGER,
    CATEGORY_ENTERTAINMENT,
    CATEGORY_PRINTING,
    DECISION_ALLOW,
    METHOD_ASSESSED,
    PAYABLE_RECEIVED,
    PAYABLE_UNBILLED,
    PAYMENT_WITHHELD,
    PHASE_COMPLETE,
    PHASE_IN_PROGRESS,
    POSTURE_OPEN,
    POSTURE_REVIEW_REQUIRED,
    PROJECT_ACTIVE,
    REASON_ALLOWED_BY_REVIEW,
    REASON_ALLOWED_BY_RULE,
    REASON_CLIENT_EXCLUDED,
    REASON_RECEIPT_MISSING,
    TIME_ENTRY_APPROVED,
    TIME_ENTRY_SUBMITTED,
    TIME_ENTRY_WRITTEN_OFF,
    WRITE_OFF_PENDING_PM_APPROVAL,
)
from test_helpers.factories import (
    assess_payload,
    expense_review_payload,
    labor_write_off_payload,
)
from test_helpers.fixtures import (
    add_approved_payable,
    add_approved_time_entry,
    add_executed_subcontract,
    add_expense,
    approve_write_off,
    build_active_project,
    enter_payable,
    prepare_invoice,
    prepare_labor_write_off,
    read_expense,
    read_invoice,
    read_payable,
    read_phase,
    read_project,
    read_time_entry,
    submit_time_entry,
)
from test_helpers.test_users import (
    ACCOUNTANT,
    CONTROLLER,
    CONTROLLER_USER_ID,
    PROJECT_MANAGER,
)


def _one_visible_charge_among_three_invisible_ones(api):
    """
    One APPROVED labour line of 7.35 h beside three populations that no aggregate
    may see: a SUBMITTED line of 10.00 h, a documented ENTERTAINMENT expense of
    200.00 that the client excludes, and a still-unapproved payable of 20000.00.
    """
    ctx = build_active_project(api, phase_overrides={"consultant_budget": 100000.00})
    approved = add_approved_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    submitted = submit_time_entry(api, ctx, hours=10.00, work_date="2026-05-12")
    excluded = add_expense(
        api,
        ctx,
        amount=200.00,
        category=CATEGORY_ENTERTAINMENT,
        incurred_on="2026-05-12",
        receipt_attached=True,
    )
    subcontract = add_executed_subcontract(api, ctx, committed_amount=20000.00)
    payable = enter_payable(
        api, subcontract["id"], amount=20000.00, invoice_date="2026-05-20"
    )
    return ctx, approved, submitted, excluded, payable


def test_excluded_charges_all_carry_zero_billable_value(api):
    """
    Each of the three invisible populations is priced at nothing: the unapproved
    line has no money at all, the excluded expense is DISALLOWED for the client's
    own reason, and the unapproved payable still has its markup triple at zero.

    PRD §3.4: "Otherwise, if the `category` appears in the client's `disallowed_categories`, the expense is `DISALLOWED` with `allowability_reason` `CLIENT_EXCLUDED`."
    PRD §3.3: "The line lands in `status` `SUBMITTED` and, crucially, carries no money yet: its `raw_cost` and `billable_amount` are both 0.00 and its `applied_multiplier` is `null`."
    PRD §3.5: "Until it is approved, its `applied_markup_pct` is 0.0000, its `markup_amount` is 0.00 and its `billable_amount` is 0.00; `approved_by_user_id`, `rejection_reason` and `client_invoice_id` are all `null`."

    Design: Corner/calculations/unapproved_and_disallowed_charges_enter_no_aggregate
    """
    ctx, approved, submitted, excluded, payable = (
        _one_visible_charge_among_three_invisible_ones(api)
    )

    held = read_time_entry(api, submitted["id"])
    assert held["status"] == TIME_ENTRY_SUBMITTED
    assert_time_entry_carries_no_money(held)

    assert_expense_decision(
        read_expense(api, excluded["id"]),
        ALLOWABILITY_DISALLOWED,
        REASON_CLIENT_EXCLUDED,
        0.00,
    )

    unapproved = read_payable(api, payable["id"])
    assert_payable_axes(unapproved, PAYABLE_RECEIVED, PAYMENT_WITHHELD, PAYABLE_UNBILLED)
    assert_payable_markup(unapproved, 0.0000, 0.00, 0.00)


def test_only_the_approved_labour_charge_reaches_the_rollups(api):
    """
    The project's work in progress and the phase's earned value are built from the
    single approved line alone: 459.38 of raw cost, 1401.11 billable and a
    cost-to-cost completion of 0.0077 that ignores the 10.00 unapproved hours.

    PRD §2.10: "`unbilled_wip` is the billable value of everything approved or allowable that no invoice has claimed: the sum of `billable_amount` over time entries with `status` `APPROVED` and no `billed_invoice_id`, plus the sum of `billable_amount` over expense items whose `allowability_status` is `ALLOWED` and whose `billing_status` is `UNBILLED`, plus the sum of `billable_amount` over consultant payables whose `approval_status` is `APPROVED` and whose `billing_status` is `UNBILLED`."
    PRD §3.6: "entries still in `SUBMITTED` are excluded, so an unapproved timesheet moves neither figure"

    Design: Corner/calculations/unapproved_and_disallowed_charges_enter_no_aggregate
    """
    ctx, approved, submitted, excluded, payable = (
        _one_visible_charge_among_three_invisible_ones(api)
    )

    assert_phase_earned_value(
        read_phase(api, ctx.phase_id),
        actual_labor_cost_to_date=459.38,
        effort_based_percent_complete=0.0077,
        effort_based_earned_value=1540.00,
        recognized_earned_value=1540.00,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=1401.11,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=1401.11,
        raw_labor_cost_to_date=459.38,
        earned_revenue_to_date=1540.00,
    )
    assert_billing_posture(project, POSTURE_OPEN)


def test_invoice_sweep_claims_the_approved_labour_and_nothing_else(api):
    """
    The sweep is the same population: labour of 1401.11, no expense value, no
    consultant value, one swept line, and the work in progress moves wholesale
    into the billed bucket with the conserved total untouched.

    PRD §3.7: "Time entries still in `SUBMITTED`, expenses in `PENDING_REVIEW` or `DISALLOWED`, and payables still `RECEIVED` or already `REJECTED` are all excluded."
    PRD §3.7: "`retainage_amount` is keyed on the **post-discount** base and never on `gross_billed` itself: it is `gross_billed` less `discount_amount`, multiplied by the client's `retainage_pct`, rounded half up to 2 decimal places."
    PRD §3.7: "the project's `unbilled_wip` falls to whatever residual remains and its `billed_open` rises by `gross_billed`"

    Design: Corner/calculations/unapproved_and_disallowed_charges_enter_no_aggregate
    """
    ctx, approved, submitted, excluded, payable = (
        _one_visible_charge_among_three_invisible_ones(api)
    )

    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    assert_invoice_money(
        invoice,
        labor_billed=1401.11,
        expense_billed=0.00,
        consultant_billed=0.00,
        gross_billed=1401.11,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=70.06,
        net_due=1331.05,
    )
    assert_swept_counts(
        invoice,
        swept_labor_count=1,
        swept_expense_count=0,
        swept_consultant_count=0,
        backup_missing_count=0,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=1401.11,
        total_charge_value=1401.11,
    )


def _three_expenses_around_the_receipt_threshold(api):
    """
    Three printing expenses against a client whose receipt threshold is 75.00 and
    whose markup is 0.1000: 75.00 undocumented, 74.99 undocumented and 75.00
    documented.
    """
    ctx = build_active_project(api)
    at_threshold = add_expense(
        api,
        ctx,
        amount=75.00,
        category=CATEGORY_PRINTING,
        incurred_on="2026-05-14",
        receipt_attached=False,
    )
    below_threshold = add_expense(
        api,
        ctx,
        amount=74.99,
        category=CATEGORY_PRINTING,
        incurred_on="2026-05-14",
        receipt_attached=False,
    )
    documented = add_expense(
        api,
        ctx,
        amount=75.00,
        category=CATEGORY_PRINTING,
        incurred_on="2026-05-14",
        receipt_attached=True,
    )
    return ctx, at_threshold, below_threshold, documented


def test_receipt_threshold_is_compared_inclusively_at_capture(api):
    """
    An amount exactly equal to the threshold already needs backup, so 75.00
    undocumented is held with no billable value while 74.99 undocumented is
    allowed outright at 82.49 and 75.00 documented at 82.50.

    PRD §3.4: "If the `amount` is at or above the client's `receipt_required_above` and `receipt_attached` is false, the expense is held with `allowability_status` `PENDING_REVIEW` and `allowability_reason` `RECEIPT_MISSING`. The threshold comparison is inclusive — an `amount` exactly equal to `receipt_required_above` already requires a receipt."
    PRD §3.4: "Otherwise the expense is `ALLOWED` with `allowability_reason` `ALLOWED_BY_RULE`."
    PRD §3.4: "On an `ALLOWED` expense it is the `amount` multiplied by one plus the client's `expense_markup_pct`, rounded half up to 2 decimal places; in every other case it stays 0.00."

    Design: Corner/calculations/receipt_threshold_is_inclusive_and_outranks_exclusions
    """
    ctx, at_threshold, below_threshold, documented = (
        _three_expenses_around_the_receipt_threshold(api)
    )

    assert_expense_decision(
        at_threshold, ALLOWABILITY_PENDING_REVIEW, REASON_RECEIPT_MISSING, 0.00
    )
    assert_expense_decision(
        below_threshold, ALLOWABILITY_ALLOWED, REASON_ALLOWED_BY_RULE, 82.49
    )
    assert_expense_decision(
        documented, ALLOWABILITY_ALLOWED, REASON_ALLOWED_BY_RULE, 82.50
    )


def test_held_expense_earns_its_markup_only_at_review(api):
    """
    The held expense is released by the controller's adjudication, which records
    the adjudicator and the justification and distinguishes the review route from
    the capture route by its reason.

    PRD §3.4: "An `ALLOW` decision on an otherwise allowable expense held only for the missing receipt sets `allowability_reason` to `ALLOWED_BY_REVIEW`, computes the marked-up `billable_amount` by the same formula as the capture path, and admits it to `unbilled_wip` in the same request."
    PRD §3.4: "A `Controller` alone adjudicates an expense held for missing backup, supplying a `decision` of either `ALLOW` or `DISALLOW` together with a `justification`, which is recorded on the expense as `review_justification`; the adjudicator's header identifier is recorded as `reviewed_by_user_id`."

    Design: Corner/calculations/receipt_threshold_is_inclusive_and_outranks_exclusions
    """
    ctx, at_threshold, below_threshold, documented = (
        _three_expenses_around_the_receipt_threshold(api)
    )
    justification = "Reprographics invoice located in the project file"

    reviewed = validate_success(
        api.review_expense(
            at_threshold["id"],
            expense_review_payload(DECISION_ALLOW, justification),
            CONTROLLER,
        )
    )

    assert_expense_decision(
        reviewed, ALLOWABILITY_ALLOWED, REASON_ALLOWED_BY_REVIEW, 82.50
    )
    assert reviewed["reviewed_by_user_id"] == CONTROLLER_USER_ID
    assert reviewed["review_justification"] == justification


def test_allowed_expenses_sum_into_work_in_progress_after_the_review(api):
    """
    Only allowable value is admitted, so once the held expense is released the
    project carries exactly the three marked-up amounts and stays well under its
    work-in-progress alert threshold.

    PRD §2.10: "`unbilled_wip` is the billable value of everything approved or allowable that no invoice has claimed: the sum of `billable_amount` over time entries with `status` `APPROVED` and no `billed_invoice_id`, plus the sum of `billable_amount` over expense items whose `allowability_status` is `ALLOWED` and whose `billing_status` is `UNBILLED`, plus the sum of `billable_amount` over consultant payables whose `approval_status` is `APPROVED` and whose `billing_status` is `UNBILLED`."
    PRD §2.11: "Otherwise the posture is `OPEN`."

    Design: Corner/calculations/receipt_threshold_is_inclusive_and_outranks_exclusions
    """
    ctx, at_threshold, below_threshold, documented = (
        _three_expenses_around_the_receipt_threshold(api)
    )
    validate_success(
        api.review_expense(
            at_threshold["id"],
            expense_review_payload(
                DECISION_ALLOW, "Reprographics invoice located in the project file"
            ),
            CONTROLLER,
        )
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=247.49,
        billed_open=0.00,
        total_charge_value=247.49,
    )
    assert_billing_posture(project, POSTURE_OPEN)


def _consultant_charge_worth_exactly_one_hundred_thousand(api):
    """
    An executed subcontract of 90909.09 whose only payable is approved at the
    standard 10% markup, which prices the work at exactly 100000.00.
    """
    ctx = build_active_project(
        api,
        project_overrides={"name": "Harborview Terminal", "contract_amount": 1200000.00},
        phase_overrides={
            "wbs_code": "03-CA",
            "lump_sum_fee": 300000.00,
            "budget_labor_cost": 80000.00,
            "consultant_budget": 100000.00,
        },
    )
    subcontract = add_executed_subcontract(api, ctx, committed_amount=90909.09)
    payable = add_approved_payable(
        api, subcontract["id"], amount=90909.09, invoice_date="2026-05-20"
    )
    return ctx, subcontract, payable


def test_first_payable_of_a_private_project_takes_the_standard_markup(api):
    """
    The approved row is excluded from its own cumulative base, so the first
    payable of the project takes the standard 10%: 9090.91 of markup on 90909.09,
    a billable 100000.00, and a work-in-progress figure that trips the alert.

    PRD §3.5: "The system first measures `approved_cost_to_date`: the sum of `amount` over every payable belonging to **this project** across all of its subcontracts whose `approval_status` is already `APPROVED`, evaluated before the current approval is applied, so the row being approved is excluded from its own cumulative base."
    PRD §3.5: "From it, `markup_amount` is the payable's `amount` multiplied by `applied_markup_pct`, rounded half up to 2 decimal places, and `billable_amount` is the `amount` plus that `markup_amount`."
    PRD §2.11: "Otherwise, if `unbilled_wip` is strictly greater than the project's `wip_alert_threshold`, the posture is `REVIEW_REQUIRED`. The comparison is strict: `unbilled_wip` exactly equal to `wip_alert_threshold` leaves the posture `OPEN`."

    Design: Corner/calculations/volume_discount_tier_one_boundary_and_its_retainage_base
    """
    ctx, subcontract, payable = _consultant_charge_worth_exactly_one_hundred_thousand(api)

    assert_payable_markup(payable, 0.1000, 9090.91, 100000.00)

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=100000.00,
        billed_open=0.00,
        total_charge_value=100000.00,
    )
    assert_billing_posture(project, POSTURE_REVIEW_REQUIRED)


def test_gross_exactly_on_the_tier_boundary_discounts_then_retains(api):
    """
    A gross of exactly 100000.00 selects the first discount tier because the tier
    comparison is inclusive, and the retainage is then taken on the post-discount
    99000.00, giving 4950.00 rather than the 5000.00 a gross-based order would.

    PRD §3.7: "First, the volume discount tier is keyed on the **pre-discount** `gross_billed`: `volume_discount_pct` is 0.0200 once `gross_billed` reaches 250000.00, otherwise 0.0100 once it reaches 100000.00, otherwise 0.0000. Both tier comparisons are inclusive."
    PRD §3.7: "Third, `retainage_amount` is keyed on the **post-discount** base and never on `gross_billed` itself: it is `gross_billed` less `discount_amount`, multiplied by the client's `retainage_pct`, rounded half up to 2 decimal places. Fourth, `net_due` is `gross_billed` less `discount_amount` less `retainage_amount`."

    Design: Corner/calculations/volume_discount_tier_one_boundary_and_its_retainage_base
    """
    ctx, subcontract, payable = _consultant_charge_worth_exactly_one_hundred_thousand(api)

    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")

    assert_invoice_money(
        invoice,
        labor_billed=0.00,
        expense_billed=0.00,
        consultant_billed=100000.00,
        gross_billed=100000.00,
        volume_discount_pct=0.0100,
        discount_amount=1000.00,
        retainage_amount=4950.00,
        net_due=94050.00,
    )
    assert_swept_counts(invoice, swept_labor_count=0, swept_consultant_count=1)


def test_invoicing_clears_the_alert_that_never_blocked_it(api):
    """
    A work-in-progress alert gates consultant commitments, never billing, so the
    invoice goes out and moving the whole position into the billed bucket is what
    returns the posture to OPEN.

    PRD §2.11: "`REVIEW_REQUIRED` blocks the execution of a consultant subcontract, refused with `ERR_PROJECT_UNDER_BILLING_REVIEW` (HTTP 409), but never blocks invoicing — invoicing is precisely the mechanism by which the excess work in progress is cleared, so blocking it would be self-defeating."
    PRD §3.7: "the project's `unbilled_wip` falls to whatever residual remains and its `billed_open` rises by `gross_billed`"

    Design: Corner/calculations/volume_discount_tier_one_boundary_and_its_retainage_base
    """
    ctx, subcontract, payable = _consultant_charge_worth_exactly_one_hundred_thousand(api)
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")

    assert_money(read_invoice(api, invoice["id"])["net_due"], 94050.00, "invoice.net_due")

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=100000.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=100000.00,
    )
    assert_billing_posture(project, POSTURE_OPEN)


def _two_unbilled_labour_charges_entered_out_of_date_order(api):
    """
    Two approved lines at a multiplier of 2.5000, created newest first: 2026-05-13
    for 2.00 h worth 312.50 and 2026-05-03 for 1.00 h worth 156.25.
    """
    ctx = build_active_project(
        api, multiplier=2.5000, project_overrides={"target_multiplier": 2.5000}
    )
    newer = add_approved_time_entry(api, ctx, hours=2.00, work_date="2026-05-13")
    older = add_approved_time_entry(api, ctx, hours=1.00, work_date="2026-05-03")
    return ctx, older, newer


def test_write_off_amount_must_equal_an_exact_prefix_of_the_dated_walk(api):
    """
    The walk runs oldest-first and stops only on an exact match, so a short
    100.00, a 156.26 one cent past the first prefix, and the 312.50 belonging to
    the second entry alone are all unallocatable.

    PRD §3.8: "The candidate list is the project's time entries whose `status` is `APPROVED` and whose `billed_invoice_id` is null, ordered by `work_date` ascending and then by `created_at` ascending — never by `id`."
    PRD §3.8: "If the running total ever passes above the `amount`, or if the list is exhausted with the running total still short of it, the preparation is refused with `ERR_WRITE_OFF_AMOUNT_NOT_ALLOCATABLE` (HTTP 422): the amount must equal an exact prefix sum of the ordered candidate list."

    Design: Corner/calculations/write_off_amount_must_equal_an_exact_prefix_sum
    """
    ctx, older, newer = _two_unbilled_labour_charges_entered_out_of_date_order(api)

    for unallocatable in (100.00, 156.26, 312.50):
        validate_error(
            api.create_write_off(
                labor_write_off_payload(
                    ctx.project_id, unallocatable, reason="Unbillable study time"
                ),
                ACCOUNTANT,
            ),
            ERR_WRITE_OFF_AMOUNT_NOT_ALLOCATABLE,
            422,
        )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project, unbilled_wip=468.75, written_off_gross=0.00, total_charge_value=468.75
    )


def test_prefix_sum_write_off_allocates_the_oldest_charge_and_routes_by_age(api):
    """
    156.25 is the first prefix, so the allocation names the older charge alone,
    freezes its age at 29 days and routes below both escalation thresholds to the
    project manager.

    PRD §3.8: "On success, `allocated_time_entry_ids` holds the ordered list of identifiers the amount was allocated to, and `aging_days` is frozen at the greatest age in whole days among those allocated entries, measured from each entry's `work_date` against the logical clock."
    PRD §3.8: "`required_approver` is set to `CONTROLLER` when the `amount` is at or above 5000.00 or the `aging_days` is at or above 90 — both thresholds inclusive, so an amount of exactly 5000.00 and an age of exactly 90 days each escalate — and to `PROJECT_MANAGER` otherwise."
    PRD §3.8: "The write-off's initial `status` is `PENDING_CONTROLLER_APPROVAL` when `required_approver` is `CONTROLLER` and `PENDING_PM_APPROVAL` when it is `PROJECT_MANAGER`."

    Design: Corner/calculations/write_off_amount_must_equal_an_exact_prefix_sum
    """
    ctx, older, newer = _two_unbilled_labour_charges_entered_out_of_date_order(api)

    write_off = prepare_labor_write_off(
        api, ctx, 156.25, reason="Unbillable study time"
    )

    assert_write_off_routing(
        write_off,
        required_approver=APPROVER_PROJECT_MANAGER,
        status=WRITE_OFF_PENDING_PM_APPROVAL,
        aging_days=29,
        allocated_time_entry_ids=[older["id"]],
    )


def test_approved_write_off_moves_only_the_allocated_charge(api):
    """
    Approval writes off the allocated charge alone: the older line goes terminal,
    the newer one stays billable, and the value moves between two buckets without
    changing the conserved total.

    PRD §3.8: "Every time entry named in `allocated_time_entry_ids` moves `APPROVED → WRITTEN_OFF`, each such entry's `version` incrementing by 1; the project's `unbilled_wip` falls by the write-off `amount` while `written_off_gross` rises by the same amount; `billing_posture` is re-run and the project's closure condition re-evaluated; and both the write-off's `version` and the project's `version` increment by 1."
    PRD §2.10: "`total_charge_value` is the sum of those four buckets — `unbilled_wip` plus `billed_open` plus `paid_gross_to_date` plus `written_off_gross` — and it is a **conserved quantity**."

    Design: Corner/calculations/write_off_amount_must_equal_an_exact_prefix_sum
    """
    ctx, older, newer = _two_unbilled_labour_charges_entered_out_of_date_order(api)
    write_off = prepare_labor_write_off(
        api, ctx, 156.25, reason="Unbillable study time"
    )

    approve_write_off(api, write_off["id"], PROJECT_MANAGER)

    assert read_time_entry(api, older["id"])["status"] == TIME_ENTRY_WRITTEN_OFF
    assert read_time_entry(api, newer["id"])["status"] == TIME_ENTRY_APPROVED

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=312.50,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=156.25,
        total_charge_value=468.75,
        raw_labor_cost_to_date=187.50,
    )


def _assessed_project_carrying_one_approved_charge(api):
    """
    A project whose completion is judged rather than measured, carrying one
    approved line of 7.35 h worth 459.38 of raw cost and 1401.11 billable.
    """
    ctx = build_active_project(
        api,
        project_overrides={
            "percent_complete_method": METHOD_ASSESSED,
            "name": "Civic Center Annex",
        },
    )
    entry = add_approved_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    return ctx, entry


def test_judged_completion_ignores_the_incurred_cost_entirely(api):
    """
    On a judged project the cost-to-cost figure is computed but not recognised, so
    459.38 of incurred cost earns 0.00 of revenue until somebody assesses the work.

    PRD §3.6: "`recognized_earned_value` — the single figure that rolls up into the project — is chosen in this order: it is the full `phase_fee` whenever the phase's `status` is `COMPLETE`; otherwise it is `effort_based_earned_value` when the project's `percent_complete_method` is `EFFORT_BASED`; otherwise it is `assessed_earned_value`."
    PRD §2.10: "`earned_revenue_to_date` is the sum of `recognized_earned_value` over the project's **leaf** phases only; a non-leaf phase contributes nothing, because its fee is already represented by its children."

    Design: Corner/calculations/completing_a_phase_reconciles_the_assessed_variant_to_full_fee
    """
    ctx, entry = _assessed_project_carrying_one_approved_charge(api)

    assert_phase_earned_value(
        read_phase(api, ctx.phase_id),
        actual_labor_cost_to_date=459.38,
        effort_based_percent_complete=0.0077,
        effort_based_earned_value=1540.00,
        recognized_earned_value=0.00,
    )
    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=1401.11,
        earned_revenue_to_date=0.00,
        total_charge_value=1401.11,
    )


def test_recording_a_judgement_recognises_a_quarter_of_the_fee(api):
    """
    A judgement of 0.2500 on a fee of 200000.00 recognises 50000.00 and lifts the
    project's earned revenue to the same figure, while the phase remains in
    progress.

    PRD §3.6: "`assessed_earned_value` is the `phase_fee` multiplied by `assessed_percent_complete`, rounded half up to 2 decimal places."
    PRD §3.6: "it recomputes both earned-value figures and refreshes the project's `earned_revenue_to_date`, though it moves `recognized_earned_value` only when the project's method is `ASSESSED`."

    Design: Corner/calculations/completing_a_phase_reconciles_the_assessed_variant_to_full_fee
    """
    ctx, entry = _assessed_project_carrying_one_approved_charge(api)

    assessed = validate_success(
        api.assess_phase(ctx.phase_id, assess_payload(0.2500), PROJECT_MANAGER)
    )

    assert assessed["status"] == PHASE_IN_PROGRESS
    assert_phase_earned_value(
        assessed,
        assessed_percent_complete=0.2500,
        assessed_earned_value=50000.00,
        recognized_earned_value=50000.00,
    )
    assert_project_ledger(
        read_project(api, ctx.project_id),
        earned_revenue_to_date=50000.00,
        unbilled_wip=1401.11,
        total_charge_value=1401.11,
    )


def test_completion_forces_the_full_fee_without_closing_the_project(api):
    """
    Completion discards the judged variant and recognises the whole 200000.00 in
    one hop, a reconciling delta of 150000.00, while the stored judgement is left
    as written and the project stays open because 1401.11 is still unbilled.

    PRD §3.6: "On success, `recognized_earned_value` is forced to the full `phase_fee` regardless of the project's `percent_complete_method`, so completion settles the delta between the selected variant and the full fee in a single step; that change re-derives the project's `earned_revenue_to_date` and, through it, the reported `total_charge_value` position; the project's closure condition is re-evaluated; and both the phase's `version` and the project's `version` increment by 1."
    PRD §3.6: "A project moves from `ACTIVE` to `CLOSED` when every leaf phase of the project has reached `COMPLETE` (non-leaf phases, which can carry no charges, are not required to reach `COMPLETE` — their fee is represented by their children), the project's `unbilled_wip` is exactly 0.00, and every invoice of the project is in `PAID`, `WRITTEN_OFF` or `VOID`."

    Design: Corner/calculations/completing_a_phase_reconciles_the_assessed_variant_to_full_fee
    """
    ctx, entry = _assessed_project_carrying_one_approved_charge(api)
    validate_success(
        api.assess_phase(ctx.phase_id, assess_payload(0.2500), PROJECT_MANAGER)
    )

    completed = validate_success(api.complete_phase(ctx.phase_id, PROJECT_MANAGER))

    assert completed["status"] == PHASE_COMPLETE
    assert_phase_earned_value(
        completed,
        phase_fee=200000.00,
        recognized_earned_value=200000.00,
        assessed_percent_complete=0.2500,
    )

    project = read_project(api, ctx.project_id)
    assert project["status"] == PROJECT_ACTIVE
    assert_project_ledger(
        project,
        unbilled_wip=1401.11,
        earned_revenue_to_date=200000.00,
        total_charge_value=1401.11,
    )
