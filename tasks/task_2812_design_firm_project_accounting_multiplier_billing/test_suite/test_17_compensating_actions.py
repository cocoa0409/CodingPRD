"""
Compensating actions and the quantities they must restore exactly.

Voiding a draft client invoice has to hand back two separate charge populations —
labour and reimbursable expenses — clear their invoice links, and return the
project's conserved charge ledger to the position it held before the sweep.
Rejecting an already-approved consultant payable has to reverse the commitment
identity, the project's unbilled work in progress and the frozen markup triple at
once, and to withdraw the payable from the cumulative markup base.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_SUBCONTRACT_COMMITMENT_EXCEEDED
from test_helpers.assertions import (
    assert_billing_posture,
    assert_expense_decision,
    assert_invoice_money,
    assert_money,
    assert_null,
    assert_pagination_meta,
    assert_payable_axes,
    assert_payable_markup,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_subcontract_rollup,
    assert_swept_counts,
    assert_time_entry_frozen,
)
from test_helpers.constants import (
    ALLOWABILITY_ALLOWED,
    CATEGORY_PRINTING,
    EXPENSE_UNBILLED,
    INVOICE_DRAFT,
    INVOICE_VOID,
    PAYABLE_APPROVED,
    PAYABLE_RECEIVED,
    PAYABLE_REJECTED,
    PAYABLE_UNBILLED,
    PAYMENT_WITHHELD,
    POSTURE_OPEN,
    POSTURE_REVIEW_REQUIRED,
    REASON_ALLOWED_BY_RULE,
    SUBCONTRACT_EXECUTED,
    TIME_ENTRY_APPROVED,
)
from test_helpers.factories import consultant_invoice_payload, reject_payload, void_payload
from test_helpers.fixtures import (
    add_approved_payable,
    add_approved_time_entry,
    add_executed_subcontract,
    add_expense,
    approve_payable,
    build_active_project,
    enter_payable,
    prepare_invoice,
    read_expense,
    read_invoice,
    read_payable,
    read_phase,
    read_project,
    read_subcontract,
    read_time_entry,
)
from test_helpers.test_users import ACCOUNTANT, CONTROLLER

VOID_REASON = "Wrong billing period selected by the accountant"
REJECTION_REASON = "Duplicate of the consultant's April application"


def _project_with_two_labour_lines_and_one_reimbursable(api):
    """
    An ACTIVE time-and-materials project on a multiplier of 3.0500 carrying two
    approved lines — 7.35 hours worth 1401.11 and 10.00 hours worth 1906.25, so
    3307.36 of labour — plus an allowable 74.99 printing charge marked up at
    0.1000 to 82.49. Unbilled work in progress is therefore 3389.85.
    """
    ctx = build_active_project(api)
    first = add_approved_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    second = add_approved_time_entry(api, ctx, hours=10.00, work_date="2026-05-12")
    expense = add_expense(
        api,
        ctx,
        amount=74.99,
        category=CATEGORY_PRINTING,
        incurred_on="2026-05-13",
        receipt_attached=False,
    )
    return ctx, first, second, expense


def _executed_subcontract_with_one_approved_payable(api):
    """
    An ACTIVE project whose leaf phase carries a consultant budget of 100000.00,
    one EXECUTED subcontract committed at 50000.00 and one payable of 20000.00
    approved at a markup of 0.1000, worth 22000.00 to the client.
    """
    ctx = build_active_project(
        api,
        project_overrides={"name": "Harbor Master Plan", "contract_amount": 900000.00},
        phase_overrides={
            "wbs_code": "03-CD",
            "lump_sum_fee": 300000.00,
            "budget_labor_cost": 90000.00,
            "consultant_budget": 100000.00,
        },
    )
    subcontract = add_executed_subcontract(
        api,
        ctx,
        consultant_name="Halcyon MEP",
        committed_amount=50000.00,
        pay_when_paid=False,
        commitment_start="2026-04-01",
        commitment_end="2026-12-31",
    )
    payable = add_approved_payable(
        api, subcontract["id"], amount=20000.00, invoice_date="2026-05-20"
    )
    return ctx, subcontract, payable


def test_voiding_a_draft_invoice_returns_the_charge_ledger_to_its_pre_invoice_position(api):
    """
    A draft invoice moves 3389.85 out of unbilled work in progress and into billed
    open receivables, and the void moves exactly that value back: 3389.85 unbilled
    again, 0.00 billed open, nothing paid and nothing written off, with the total
    charge value never moving off 3389.85 and the labour ratio never moving off
    3.0500.

    PRD §2.10: "No forward action and its compensating counterpart may leave drift: voiding an invoice must return `unbilled_wip` to exactly the figure it held before the invoice was prepared and must reduce `billed_open` by exactly that invoice's `gross_billed`, leaving `total_charge_value` unchanged."
    PRD §2.10: "Invoices in `VOID` contribute to none of the four buckets."
    PRD §3.7: "Third, `retainage_amount` is keyed on the **post-discount** base and never on `gross_billed` itself: it is `gross_billed` less `discount_amount`, multiplied by the client's `retainage_pct`, rounded half up to 2 decimal places."

    Design: Difficulty/compensating_invariant/invoice_void_restores_every_swept_population_without_drift
    """
    ctx, _first, _second, _expense = _project_with_two_labour_lines_and_one_reimbursable(api)

    before = read_project(api, ctx.project_id)
    assert_project_ledger(
        before,
        unbilled_wip=3389.85,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=3389.85,
        raw_labor_cost_to_date=1084.38,
        net_multiplier_achieved=3.0500,
    )

    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    assert invoice["status"] == INVOICE_DRAFT
    assert_invoice_money(
        invoice,
        labor_billed=3307.36,
        expense_billed=82.49,
        consultant_billed=0.00,
        gross_billed=3389.85,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=169.49,
        net_due=3220.36,
    )
    assert_swept_counts(
        invoice, swept_labor_count=2, swept_expense_count=1, swept_consultant_count=0
    )

    billed = read_project(api, ctx.project_id)
    assert_project_ledger(
        billed,
        unbilled_wip=0.00,
        billed_open=3389.85,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=3389.85,
        net_multiplier_achieved=3.0500,
    )

    voided = validate_success(
        api.void_invoice(invoice["id"], void_payload(VOID_REASON), CONTROLLER), 200
    )
    assert voided["status"] == INVOICE_VOID
    assert voided["void_reason"] == VOID_REASON
    assert_money(voided["gross_billed"], 3389.85, "voided invoice gross_billed")

    after = read_project(api, ctx.project_id)
    assert_project_ledger(
        after,
        unbilled_wip=3389.85,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=3389.85,
        raw_labor_cost_to_date=1084.38,
        net_multiplier_achieved=3.0500,
    )
    assert_billing_posture(after, POSTURE_OPEN)


def test_the_void_hands_back_both_swept_populations_and_leaves_no_dangling_link(api):
    """
    The void returns both charge populations, not just the labour: the two lines go
    back to APPROVED and the printing charge back to UNBILLED, all three with their
    invoice link cleared, and the two filtered reads that are the only way to learn
    what an invoice swept come back empty.

    PRD §3.7: "Every attached time entry moves `BILLED → APPROVED`, every attached expense moves `BILLED → UNBILLED`, and every attached consultant payable moves `BILLED_TO_CLIENT → UNBILLED`, each with its invoice link cleared."
    PRD §2.9: "Filtering time entries by `billed_invoice_id` is the only way to learn which entries an invoice swept; filtering consultant payables by `client_invoice_id` is the only way to learn which payables it swept."

    Design: Difficulty/compensating_invariant/invoice_void_restores_every_swept_population_without_drift
    """
    ctx, first, second, expense = _project_with_two_labour_lines_and_one_reimbursable(api)
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")

    swept_labor, swept_labor_meta = validate_paginated(
        api.list_time_entries(CONTROLLER, {"billed_invoice_id": invoice["id"]})
    )
    assert_pagination_meta(swept_labor_meta, total_count=2, has_more=False)
    assert {row["id"] for row in swept_labor} == {first["id"], second["id"]}

    validate_success(
        api.void_invoice(invoice["id"], void_payload(VOID_REASON), CONTROLLER), 200
    )

    restored_first = read_time_entry(api, first["id"])
    assert restored_first["status"] == TIME_ENTRY_APPROVED
    assert_null(restored_first["billed_invoice_id"], "time_entry.billed_invoice_id")
    assert_time_entry_frozen(
        restored_first, raw_cost=459.38, applied_multiplier=3.0500, billable_amount=1401.11
    )

    restored_second = read_time_entry(api, second["id"])
    assert restored_second["status"] == TIME_ENTRY_APPROVED
    assert_null(restored_second["billed_invoice_id"], "time_entry.billed_invoice_id")
    assert_time_entry_frozen(
        restored_second, raw_cost=625.00, applied_multiplier=3.0500, billable_amount=1906.25
    )

    restored_expense = read_expense(api, expense["id"])
    assert restored_expense["billing_status"] == EXPENSE_UNBILLED
    assert_null(restored_expense["billed_invoice_id"], "expense.billed_invoice_id")
    assert_expense_decision(
        restored_expense,
        allowability_status=ALLOWABILITY_ALLOWED,
        allowability_reason=REASON_ALLOWED_BY_RULE,
        billable_amount=82.49,
    )

    _orphan_labor, orphan_labor_meta = validate_paginated(
        api.list_time_entries(CONTROLLER, {"billed_invoice_id": invoice["id"]})
    )
    assert_pagination_meta(orphan_labor_meta, total_count=0, has_more=False)

    _orphan_expenses, orphan_expense_meta = validate_paginated(
        api.list_expenses(CONTROLLER, {"billed_invoice_id": invoice["id"]})
    )
    assert_pagination_meta(orphan_expense_meta, total_count=0, has_more=False)


def test_earned_value_survives_the_void_and_re_invoicing_the_period_reproduces_the_money(api):
    """
    Billing and unbilling a period is invisible to earned value: the phase holds
    1084.38 of actual labour cost, 0.0181 complete and 3620.00 recognised both
    before and after the void. Re-invoicing the same period end then reproduces the
    bill exactly — 3389.85 gross, 169.49 retainage, 3220.36 net, two lines and one
    expense swept, at revision round 0.

    PRD §3.6: "From it, `effort_based_percent_complete` is `actual_labor_cost_to_date` divided by `budget_labor_cost`, rounded half up to 4 decimal places and then capped at 1.0000 by taking the lesser of the two; when `budget_labor_cost` is exactly 0.00 the figure is 0.0000 rather than undefined."
    PRD §3.6: "Take a phase with a `phase_fee` of 200000.00, a `budget_labor_cost` of 60000.00, an `actual_labor_cost_to_date` of 1084.38 and an `assessed_percent_complete` of 0.2500: the cost-to-cost route recognises 3620.00 while the assessed route recognises 50000.00."
    PRD §3.7: "the invoice lands in `status` `DRAFT` with `revision_round` 0, and its `submitted_by_user_id`, `client_decision_comment`, `paid_on` and `void_reason` are all `null`."

    Design: Difficulty/compensating_invariant/invoice_void_restores_every_swept_population_without_drift
    """
    ctx, _first, _second, _expense = _project_with_two_labour_lines_and_one_reimbursable(api)

    phase_before = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(
        phase_before,
        actual_labor_cost_to_date=1084.38,
        effort_based_percent_complete=0.0181,
        effort_based_earned_value=3620.00,
        recognized_earned_value=3620.00,
        phase_fee=200000.00,
    )

    first_invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    validate_success(
        api.void_invoice(first_invoice["id"], void_payload(VOID_REASON), CONTROLLER), 200
    )

    phase_after = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(
        phase_after,
        actual_labor_cost_to_date=1084.38,
        effort_based_percent_complete=0.0181,
        effort_based_earned_value=3620.00,
        recognized_earned_value=3620.00,
        phase_fee=200000.00,
    )

    voided = read_invoice(api, first_invoice["id"])
    assert voided["status"] == INVOICE_VOID
    # PRD §3.7 enumerates the void's side effects exhaustively — the swept charges
    # move back and their invoice links are cleared, unbilled_wip is restored,
    # billed_open falls by gross_billed, the versions increment — and it says
    # nothing about the three swept_*_count fields, while implying gross_billed is
    # retained on the voided row ("its `billed_open` falls by `gross_billed`").
    # Whether the counts are a live count of currently-attached charges or a
    # figure frozen at sweep time is therefore not determined by the PRD, so no
    # assertion is made on them here.

    second_invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    assert second_invoice["status"] == INVOICE_DRAFT
    assert second_invoice["revision_round"] == 0
    assert_null(second_invoice["void_reason"], "invoice.void_reason")
    assert_null(second_invoice["paid_on"], "invoice.paid_on")
    assert_invoice_money(
        second_invoice,
        labor_billed=3307.36,
        expense_billed=82.49,
        consultant_billed=0.00,
        gross_billed=3389.85,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=169.49,
        net_due=3220.36,
    )
    assert_swept_counts(
        second_invoice,
        swept_labor_count=2,
        swept_expense_count=1,
        swept_consultant_count=0,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=3389.85,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=3389.85,
        net_multiplier_achieved=3.0500,
    )


def test_rejecting_an_approved_payable_restores_the_commitment_identity_and_the_ledger(api):
    """
    A payable of 20000.00 approved at a markup of 0.1000 draws the commitment down
    to 30000.00 and admits 22000.00 to work in progress. Rejecting it while it is
    still unbilled reverses all three derived quantities at once: the commitment
    returns to 50000.00 with nothing approved against it, work in progress and the
    total charge value return to 0.00, and the frozen markup triple is reset to
    0.0000, 0.00 and 0.00. The phase's open commitment is untouched throughout.

    PRD §3.5: "That branch is a full compensating action: `approved_to_date` falls by the `amount` and `committed_remaining` rises by the same amount, restoring the identity that a subcontract's `committed_amount` always equals its `committed_remaining` plus its `approved_to_date`; the project's `unbilled_wip` falls by the previously frozen `billable_amount`; and `applied_markup_pct`, `markup_amount` and `billable_amount` are reset to 0.0000, 0.00 and 0.00 respectively."
    PRD §3.5: "A `RECEIVED → APPROVED → REJECTED` round trip therefore returns `committed_remaining` to exactly its starting value."
    PRD §3.5: "`REJECTED` is terminal on the approval axis, and a rejected payable's `payment_status` stays `WITHHELD` permanently — it can never be released."

    Design: Difficulty/compensating_invariant/payable_rejection_restores_commitment_and_markup_base
    """
    ctx, subcontract, payable = _executed_subcontract_with_one_approved_payable(api)

    assert_payable_axes(
        payable,
        approval_status=PAYABLE_APPROVED,
        payment_status=PAYMENT_WITHHELD,
        billing_status=PAYABLE_UNBILLED,
    )
    assert_payable_markup(
        payable, applied_markup_pct=0.1000, markup_amount=2000.00, billable_amount=22000.00
    )
    assert payable["version"] == 2

    before = read_subcontract(api, subcontract["id"])
    assert_subcontract_rollup(
        before,
        approved_to_date=20000.00,
        released_to_date=0.00,
        committed_remaining=30000.00,
        status=SUBCONTRACT_EXECUTED,
    )
    project_before = read_project(api, ctx.project_id)
    assert_project_ledger(
        project_before,
        unbilled_wip=22000.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=22000.00,
    )
    phase_before = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(phase_before, consultant_committed_open=50000.00)

    rejected = validate_success(
        api.reject_consultant_invoice(
            payable["id"], reject_payload(REJECTION_REASON), CONTROLLER
        ),
        200,
    )
    assert_payable_axes(
        rejected,
        approval_status=PAYABLE_REJECTED,
        payment_status=PAYMENT_WITHHELD,
        billing_status=PAYABLE_UNBILLED,
    )
    assert_payable_markup(
        rejected, applied_markup_pct=0.0000, markup_amount=0.00, billable_amount=0.00
    )
    assert rejected["rejection_reason"] == REJECTION_REASON
    assert_null(rejected["client_invoice_id"], "payable.client_invoice_id")
    assert rejected["version"] == 3

    after = read_subcontract(api, subcontract["id"])
    assert_subcontract_rollup(
        after,
        approved_to_date=0.00,
        released_to_date=0.00,
        committed_remaining=50000.00,
        status=SUBCONTRACT_EXECUTED,
    )
    assert_money(after["committed_amount"], 50000.00, "subcontract.committed_amount")

    project_after = read_project(api, ctx.project_id)
    assert_project_ledger(
        project_after,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=0.00,
    )
    assert_billing_posture(project_after, POSTURE_OPEN)

    phase_after = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(phase_after, consultant_committed_open=50000.00)


def test_a_rejected_payable_leaves_the_cumulative_markup_base_so_a_replacement_prices_the_same(api):
    """
    The rejected 20000.00 is withdrawn from the project's cumulative approved
    consultant cost as well as from the commitment, so a replacement payable for the
    same 20000.00 is priced against a base of 0.00 and freezes the identical markup
    triple: 0.1000, 2000.00 and 22000.00.

    PRD §3.5: "The system first measures `approved_cost_to_date`: the sum of `amount` over every payable belonging to **this project** across all of its subcontracts whose `approval_status` is already `APPROVED`, evaluated before the current approval is applied, so the row being approved is excluded from its own cumulative base."
    PRD §3.5: "A base markup fraction of 0.1000 applies as standard; once `approved_cost_to_date` reaches 250000.00 the base drops to 0.0600, and the threshold is inclusive, so cumulative approved consultant cost of exactly 250000.00 already selects the lower tier."
    PRD §3.5: "Rejected payables contribute to neither sum."

    Design: Difficulty/compensating_invariant/payable_rejection_restores_commitment_and_markup_base
    """
    ctx, subcontract, payable = _executed_subcontract_with_one_approved_payable(api)
    validate_success(
        api.reject_consultant_invoice(
            payable["id"], reject_payload(REJECTION_REASON), CONTROLLER
        ),
        200,
    )

    replacement = enter_payable(
        api, subcontract["id"], amount=20000.00, invoice_date="2026-05-25"
    )
    assert_payable_axes(
        replacement,
        approval_status=PAYABLE_RECEIVED,
        payment_status=PAYMENT_WITHHELD,
        billing_status=PAYABLE_UNBILLED,
    )
    assert_payable_markup(
        replacement, applied_markup_pct=0.0000, markup_amount=0.00, billable_amount=0.00
    )

    approved_replacement = approve_payable(api, replacement["id"])
    assert_payable_markup(
        approved_replacement,
        applied_markup_pct=0.1000,
        markup_amount=2000.00,
        billable_amount=22000.00,
    )
    assert_money(approved_replacement["amount"], 20000.00, "payable.amount")

    still_rejected = read_payable(api, payable["id"])
    assert still_rejected["approval_status"] == PAYABLE_REJECTED
    assert_payable_markup(
        still_rejected, applied_markup_pct=0.0000, markup_amount=0.00, billable_amount=0.00
    )

    redrawn = read_subcontract(api, subcontract["id"])
    assert_subcontract_rollup(
        redrawn,
        approved_to_date=20000.00,
        released_to_date=0.00,
        committed_remaining=30000.00,
        status=SUBCONTRACT_EXECUTED,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=22000.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=22000.00,
    )
    assert_billing_posture(project, POSTURE_OPEN)


def test_the_restored_commitment_is_the_figure_the_next_approval_is_measured_against(api):
    """
    After the rejection and the replacement approval the commitment has 30000.00
    left, and that restored figure is exactly what the next approval is tested
    against: 30000.01 is one cent too much and is refused, leaving the payable
    RECEIVED with no money on it, while 30000.00 exactly is admitted, drawing the
    commitment to 0.00 and lifting work in progress to 55000.00 — above the firm's
    default work-in-progress alert threshold, so the project moves to
    REVIEW_REQUIRED.

    PRD §3.5: "Approving a payable — a `ProjectManager` or `Controller` action moving `approval_status` from `RECEIVED` to `APPROVED` — requires that the payable be `RECEIVED`, that its subcontract be `EXECUTED`, that the owning project be `ACTIVE`, and that the `amount` not exceed the subcontract's `committed_remaining`; an over-draw is refused with `ERR_SUBCONTRACT_COMMITMENT_EXCEEDED` (HTTP 422)."
    PRD §3.5: "The project's `unbilled_wip` rises by the payable's `billable_amount`, which re-runs `billing_posture`."
    PRD §3.3: "The fourth hop re-evaluates `billing_posture` on the new `unbilled_wip`: when the figure passes strictly above `wip_alert_threshold` the posture moves from `OPEN` to `REVIEW_REQUIRED`, and from that moment the execution of a consultant subcontract on that project is blocked."

    Design: Difficulty/compensating_invariant/payable_rejection_restores_commitment_and_markup_base
    """
    ctx, subcontract, payable = _executed_subcontract_with_one_approved_payable(api)
    validate_success(
        api.reject_consultant_invoice(
            payable["id"], reject_payload(REJECTION_REASON), CONTROLLER
        ),
        200,
    )
    replacement = enter_payable(
        api, subcontract["id"], amount=20000.00, invoice_date="2026-05-25"
    )
    approve_payable(api, replacement["id"])

    over_draw = validate_success(
        api.create_consultant_invoice(
            consultant_invoice_payload(
                subcontract["id"],
                amount=30000.01,
                invoice_date="2026-05-26",
                backup_attached=True,
            ),
            ACCOUNTANT,
        ),
        201,
    )
    validate_error(
        api.approve_consultant_invoice(over_draw["id"], CONTROLLER),
        ERR_SUBCONTRACT_COMMITMENT_EXCEEDED,
        422,
    )
    refused = read_payable(api, over_draw["id"])
    assert_payable_axes(
        refused,
        approval_status=PAYABLE_RECEIVED,
        payment_status=PAYMENT_WITHHELD,
        billing_status=PAYABLE_UNBILLED,
    )
    assert_payable_markup(
        refused, applied_markup_pct=0.0000, markup_amount=0.00, billable_amount=0.00
    )
    assert_null(refused["approved_by_user_id"], "payable.approved_by_user_id")

    intact = read_subcontract(api, subcontract["id"])
    assert_subcontract_rollup(
        intact,
        approved_to_date=20000.00,
        released_to_date=0.00,
        committed_remaining=30000.00,
        status=SUBCONTRACT_EXECUTED,
    )

    to_the_cent = enter_payable(
        api, subcontract["id"], amount=30000.00, invoice_date="2026-05-27"
    )
    approved_to_the_cent = approve_payable(api, to_the_cent["id"])
    assert_payable_axes(
        approved_to_the_cent,
        approval_status=PAYABLE_APPROVED,
        payment_status=PAYMENT_WITHHELD,
        billing_status=PAYABLE_UNBILLED,
    )
    assert_payable_markup(
        approved_to_the_cent,
        applied_markup_pct=0.1000,
        markup_amount=3000.00,
        billable_amount=33000.00,
    )

    exhausted = read_subcontract(api, subcontract["id"])
    assert_subcontract_rollup(
        exhausted,
        approved_to_date=50000.00,
        released_to_date=0.00,
        committed_remaining=0.00,
        status=SUBCONTRACT_EXECUTED,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=55000.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=55000.00,
    )
    assert_billing_posture(project, POSTURE_REVIEW_REQUIRED)
    assert_money(project["wip_alert_threshold"], 50000.00, "project.wip_alert_threshold")

    phase = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(phase, consultant_committed_open=50000.00)
