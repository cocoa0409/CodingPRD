"""
Multi-entity propagation in an architecture practice's project accounting.

Two events in this domain are not local edits at all. Recording receipt of a
client invoice walks from the receivable through the consultant payment axis,
the subcontract commitment, the phase's open consultant exposure and the
phase-completion precondition all the way to project closure. Approving a
single timesheet line freezes a labour charge, raises its phase's actual cost
and earned value, refreshes the project's rollup position and re-evaluates the
project-level billing gate — and that last step is observable only as a refusal
on a different entity.

Every figure asserted here is the one the firm's books must show at that hop,
and the conserved charge ledger of PRD §2.10 is re-checked after each of them.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import (
    ERR_PHASE_HAS_OPEN_CHARGES,
    ERR_PROJECT_UNDER_BILLING_REVIEW,
)
from test_helpers.assertions import (
    assert_billing_posture,
    assert_invoice_money,
    assert_ledger_conserved,
    assert_money,
    assert_payable_axes,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_subcontract_rollup,
    assert_time_entry_frozen,
)
from test_helpers.constants import (
    CLOCK_2026_06_01,
    INVOICE_PAID,
    PAYABLE_APPROVED,
    PAYABLE_BILLED_TO_CLIENT,
    PAYMENT_RELEASED,
    PAYMENT_WITHHELD,
    PHASE_COMPLETE,
    PHASE_IN_PROGRESS,
    POSTURE_OPEN,
    POSTURE_REVIEW_REQUIRED,
    PROJECT_CLOSED,
    SUBCONTRACT_CLOSED,
    SUBCONTRACT_DRAFT,
    SUBCONTRACT_EXECUTED,
    TIME_ENTRY_APPROVED,
)
from test_helpers.factories import record_payment_payload
from test_helpers.fixtures import (
    add_approved_payable,
    add_approved_time_entry,
    add_executed_subcontract,
    approve_time_entry,
    build_active_project,
    build_approved_invoice,
    draft_subcontract,
    read_invoice,
    read_payable,
    read_phase,
    read_project,
    read_subcontract,
    submit_time_entry,
)
from test_helpers.test_users import CONTROLLER


def _stand_up_approved_invoice_over_a_pay_when_paid_subcontract(api):
    """
    The position the settlement chain starts from: a TIME_AND_MATERIALS project
    with one leaf phase, one EXECUTED pay-when-paid subcontract committed at
    exactly 20000.00 so a single release settles it in full, one approved payable
    of 20000.00 that froze the standard 0.1000 markup into a billable 22000.00,
    and one client-approved invoice that swept that payable at a gross of
    22000.00 against 1100.00 of retainage.
    """
    ctx = build_active_project(
        api,
        clock=CLOCK_2026_06_01,
        project_overrides={"name": "Lakeshore Pavilion"},
        phase_overrides={"consultant_budget": 100000.00},
    )
    subcontract = add_executed_subcontract(
        api, ctx, committed_amount=20000.00, pay_when_paid=True
    )
    payable = add_approved_payable(api, subcontract["id"], amount=20000.00)
    invoice = build_approved_invoice(api, ctx, period_end="2026-05-31")
    return ctx, subcontract["id"], payable["id"], invoice["id"]


def test_settling_the_invoice_releases_the_payable_and_closes_the_subcontract(api):
    """
    Recording receipt of the client invoice runs the first four hops of the
    settlement chain inside one request. The invoice reaches PAID and its
    22000.00 gross moves out of billed_open into paid_gross_to_date; the
    pay-when-paid payable reaches RELEASED with no release call of its own; the
    subcontract's released_to_date reaches its 20000.00 commitment so it closes;
    and the phase's consultant_committed_open falls to 0.00 — which is precisely
    the open commitment that refused phase completion moments earlier.

    PRD §3.6: "It requires that the phase be `IN_PROGRESS`, that no time entry on the phase remain in `SUBMITTED`, that no expense on the phase remain in `PENDING_REVIEW`, and that no `EXECUTED` subcontract on the phase still have a `released_to_date` below its `committed_amount`."
    PRD §3.7: "First, the project's `billed_open` falls by `gross_billed` while `paid_gross_to_date` rises by the same value."
    PRD §3.7: "Second, the settlement satisfies pay-when-paid, so every consultant payable whose `client_invoice_id` is this invoice and whose `payment_status` is `WITHHELD` moves `WITHHELD → RELEASED`."
    PRD §3.5: "When a subcontract's `released_to_date` reaches or passes its `committed_amount`, the subcontract moves `EXECUTED → CLOSED`."

    Design: Difficulty/transitive_cascade/invoice_payment_five_hop_close_cascade
    """
    ctx, subcontract_id, payable_id, invoice_id = (
        _stand_up_approved_invoice_over_a_pay_when_paid_subcontract(api)
    )

    approved_invoice = read_invoice(api, invoice_id)
    assert_invoice_money(
        approved_invoice,
        consultant_billed=22000.00,
        gross_billed=22000.00,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=1100.00,
        net_due=20900.00,
    )

    # The open commitment blocks completion while released_to_date is still 0.00.
    blocked = api.complete_phase(ctx.phase_id, CONTROLLER)
    validate_error(blocked, ERR_PHASE_HAS_OPEN_CHARGES, 409)
    assert_subcontract_rollup(
        read_subcontract(api, subcontract_id),
        approved_to_date=20000.00,
        released_to_date=0.00,
        committed_remaining=0.00,
        status=SUBCONTRACT_EXECUTED,
    )
    assert_payable_axes(
        read_payable(api, payable_id),
        PAYABLE_APPROVED,
        PAYMENT_WITHHELD,
        PAYABLE_BILLED_TO_CLIENT,
    )

    paid = get_success_data(
        api.record_invoice_payment(
            invoice_id, record_payment_payload("2026-06-01"), CONTROLLER
        )
    )
    assert paid["status"] == INVOICE_PAID, (
        f"invoice.status: expected {INVOICE_PAID}, got {paid['status']}"
    )
    assert paid["paid_on"] == "2026-06-01", (
        f"invoice.paid_on: expected 2026-06-01, got {paid['paid_on']}"
    )

    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=22000.00,
        written_off_gross=0.00,
        total_charge_value=22000.00,
    )
    assert_payable_axes(
        read_payable(api, payable_id),
        PAYABLE_APPROVED,
        PAYMENT_RELEASED,
        PAYABLE_BILLED_TO_CLIENT,
    )
    assert_subcontract_rollup(
        read_subcontract(api, subcontract_id),
        approved_to_date=20000.00,
        released_to_date=20000.00,
        committed_remaining=0.00,
        status=SUBCONTRACT_CLOSED,
    )

    phase = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(phase, consultant_committed_open=0.00)
    assert phase["status"] == PHASE_IN_PROGRESS, (
        f"phase.status: expected {PHASE_IN_PROGRESS}, got {phase['status']}"
    )


def test_completing_the_phase_after_settlement_bubbles_the_project_to_closed(api):
    """
    The fifth hop of the settlement chain is only visible on a second request:
    once the paid invoice has closed the subcontract and cleared the phase's open
    consultant commitment, the very phase completion that was refused beforehand
    now succeeds, forces recognized earned value to the full 200000.00 phase fee,
    and bubbles the project itself from ACTIVE to CLOSED with 200000.00 of earned
    revenue and a posture back at OPEN.

    PRD §3.6: "Open charges are refused with `ERR_PHASE_HAS_OPEN_CHARGES` (HTTP 409)."
    PRD §3.6: "On success, `recognized_earned_value` is forced to the full `phase_fee` regardless of the project's `percent_complete_method`"
    PRD §3.6: "A project moves from `ACTIVE` to `CLOSED` when every leaf phase of the project has reached `COMPLETE`"

    Design: Difficulty/transitive_cascade/invoice_payment_five_hop_close_cascade
    """
    ctx, subcontract_id, payable_id, invoice_id = (
        _stand_up_approved_invoice_over_a_pay_when_paid_subcontract(api)
    )

    validate_error(
        api.complete_phase(ctx.phase_id, CONTROLLER), ERR_PHASE_HAS_OPEN_CHARGES, 409
    )

    get_success_data(
        api.record_invoice_payment(
            invoice_id, record_payment_payload("2026-06-01"), CONTROLLER
        )
    )

    completed = get_success_data(api.complete_phase(ctx.phase_id, CONTROLLER))
    assert completed["status"] == PHASE_COMPLETE, (
        f"phase.status: expected {PHASE_COMPLETE}, got {completed['status']}"
    )
    assert_phase_earned_value(
        completed,
        phase_fee=200000.00,
        recognized_earned_value=200000.00,
        consultant_committed_open=0.00,
    )

    project = read_project(api, ctx.project_id)
    assert project["status"] == PROJECT_CLOSED, (
        f"project.status: expected {PROJECT_CLOSED}, got {project['status']}"
    )
    assert_billing_posture(project, POSTURE_OPEN)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=22000.00,
        written_off_gross=0.00,
        total_charge_value=22000.00,
        earned_revenue_to_date=200000.00,
    )
    assert_subcontract_rollup(
        read_subcontract(api, subcontract_id), status=SUBCONTRACT_CLOSED
    )
    assert_payable_axes(
        read_payable(api, payable_id),
        PAYABLE_APPROVED,
        PAYMENT_RELEASED,
        PAYABLE_BILLED_TO_CLIENT,
    )


def test_total_charge_value_is_unchanged_at_every_hop_of_the_settlement(api):
    """
    The conserved charge ledger is the invariant the whole settlement chain must
    respect: the 22000.00 of consultant value the invoice claimed is only ever
    moved between buckets, never created or destroyed. It sits in billed_open
    before the payment, in paid_gross_to_date after it, and stays at 22000.00
    once phase completion has bubbled the project to CLOSED.

    PRD §2.10: "`total_charge_value` is the sum of those four buckets — `unbilled_wip` plus `billed_open` plus `paid_gross_to_date` plus `written_off_gross` — and it is a **conserved quantity**."

    Design: Difficulty/transitive_cascade/invoice_payment_five_hop_close_cascade
    """
    ctx, _subcontract_id, _payable_id, invoice_id = (
        _stand_up_approved_invoice_over_a_pay_when_paid_subcontract(api)
    )

    before = read_project(api, ctx.project_id)
    assert_project_ledger(
        before,
        unbilled_wip=0.00,
        billed_open=22000.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=22000.00,
    )

    get_success_data(
        api.record_invoice_payment(
            invoice_id, record_payment_payload("2026-06-01"), CONTROLLER
        )
    )
    settled = read_project(api, ctx.project_id)
    assert_money(settled["total_charge_value"], 22000.00, "project.total_charge_value")
    assert_ledger_conserved(settled)

    get_success_data(api.complete_phase(ctx.phase_id, CONTROLLER))
    closed = read_project(api, ctx.project_id)
    assert_money(closed["total_charge_value"], 22000.00, "project.total_charge_value")
    assert_ledger_conserved(closed)
    assert closed["status"] == PROJECT_CLOSED, (
        f"project.status: expected {PROJECT_CLOSED}, got {closed['status']}"
    )


def _stand_up_project_just_below_its_alert_threshold(api):
    """
    A TIME_AND_MATERIALS project whose alert threshold is pulled down to 5000.00
    so one more timesheet line will cross it. Two approved architect lines at
    62.50 an hour under a 3.0500 multiplier — 7.35 h freezing 1401.11 and 10.00 h
    freezing 1906.25 — leave 3307.36 of unbilled work in progress, still below the
    threshold. A subcontract committed at 10000.00 is drafted but not executed,
    and a third line of 20.00 h waits in SUBMITTED.
    """
    ctx = build_active_project(
        api,
        clock=CLOCK_2026_06_01,
        project_overrides={"wip_alert_threshold": 5000.00},
        phase_overrides={"consultant_budget": 100000.00},
    )
    add_approved_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    add_approved_time_entry(api, ctx, hours=10.00, work_date="2026-05-12")
    drafted = draft_subcontract(
        api,
        ctx,
        committed_amount=10000.00,
        commitment_start="2026-06-01",
        commitment_end="2026-12-31",
    )
    pending = submit_time_entry(api, ctx, hours=20.00, work_date="2026-05-13")
    return ctx, drafted["id"], pending["id"]


def test_approving_one_timesheet_line_freezes_its_charge_and_rolls_it_up(api):
    """
    Approving a single 20.00 h architect line propagates three hops in the one
    response cycle. The line freezes a raw cost of 1250.00 and, through the
    3.0500 multiplier, a billable amount of 3812.50. Its phase's actual labour
    cost rises to 2334.38, which re-derives an effort-based completion of 0.0389
    and 7780.00 of recognized earned value against the 200000.00 phase fee. The
    project then reports 7119.86 of unbilled work in progress, 2334.38 of raw
    labour cost, a net multiplier of 3.0500 and 7780.00 of earned revenue.

    PRD §3.3: "Third, `billable_amount` is the already-rounded `raw_cost` multiplied by `applied_multiplier`, rounded half up to 2 decimal places."
    PRD §3.3: "The second hop raises the phase's `actual_labor_cost_to_date` by the new `raw_cost`, which re-derives that phase's `effort_based_percent_complete`, `effort_based_earned_value` and `recognized_earned_value`."
    PRD §2.10: "`net_multiplier_achieved` is the project's billable labour value divided by its raw labour cost: the sum of `billable_amount` over time entries whose `status` is `APPROVED`, `BILLED` or `WRITTEN_OFF`, divided by `raw_labor_cost_to_date`, rounded half up to 4 decimal places."

    Design: Difficulty/transitive_cascade/time_entry_approval_four_hop_posture_cascade
    """
    ctx, _subcontract_id, pending_entry_id = (
        _stand_up_project_just_below_its_alert_threshold(api)
    )

    before = read_project(api, ctx.project_id)
    assert_project_ledger(before, unbilled_wip=3307.36, total_charge_value=3307.36)
    assert_billing_posture(before, POSTURE_OPEN)

    approved = approve_time_entry(api, pending_entry_id)
    assert approved["status"] == TIME_ENTRY_APPROVED, (
        f"time_entry.status: expected {TIME_ENTRY_APPROVED}, got {approved['status']}"
    )
    assert_time_entry_frozen(
        approved, raw_cost=1250.00, applied_multiplier=3.0500, billable_amount=3812.50
    )

    phase = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(
        phase,
        phase_fee=200000.00,
        actual_labor_cost_to_date=2334.38,
        effort_based_percent_complete=0.0389,
        effort_based_earned_value=7780.00,
        recognized_earned_value=7780.00,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=7119.86,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=7119.86,
        raw_labor_cost_to_date=2334.38,
        earned_revenue_to_date=7780.00,
        net_multiplier_achieved=3.0500,
    )


def test_crossing_the_alert_threshold_blocks_a_consultant_subcontract_execution(api):
    """
    The fourth hop of the approval chain is observable only on a different
    entity. Once the third line carries unbilled work in progress to 7119.86,
    strictly above the 5000.00 alert threshold, the project's posture moves to
    REVIEW_REQUIRED and executing the drafted subcontract is refused. The refusal
    consumes no capacity: the subcontract stays DRAFT and the phase's open
    consultant commitment stays at 0.00.

    PRD §3.3: "The fourth hop re-evaluates `billing_posture` on the new `unbilled_wip`: when the figure passes strictly above `wip_alert_threshold` the posture moves from `OPEN` to `REVIEW_REQUIRED`, and from that moment the execution of a consultant subcontract on that project is blocked."
    PRD §2.11: "`REVIEW_REQUIRED` blocks the execution of a consultant subcontract, refused with `ERR_PROJECT_UNDER_BILLING_REVIEW` (HTTP 409), but never blocks invoicing"

    Design: Difficulty/transitive_cascade/time_entry_approval_four_hop_posture_cascade
    """
    ctx, subcontract_id, pending_entry_id = (
        _stand_up_project_just_below_its_alert_threshold(api)
    )

    assert_billing_posture(read_project(api, ctx.project_id), POSTURE_OPEN)

    approve_time_entry(api, pending_entry_id)

    crossed = read_project(api, ctx.project_id)
    assert_project_ledger(crossed, unbilled_wip=7119.86, total_charge_value=7119.86)
    assert_billing_posture(crossed, POSTURE_REVIEW_REQUIRED)

    refused = api.execute_subcontract(subcontract_id, CONTROLLER)
    validate_error(refused, ERR_PROJECT_UNDER_BILLING_REVIEW, 409)

    subcontract = read_subcontract(api, subcontract_id)
    assert_subcontract_rollup(
        subcontract,
        approved_to_date=0.00,
        released_to_date=0.00,
        committed_remaining=10000.00,
        status=SUBCONTRACT_DRAFT,
    )
    assert_phase_earned_value(
        read_phase(api, ctx.phase_id), consultant_committed_open=0.00
    )
