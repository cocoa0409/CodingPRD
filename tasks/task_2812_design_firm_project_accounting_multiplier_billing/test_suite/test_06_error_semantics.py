"""
Refusal semantics on the receivable write-off and the multiplier lookup.

Two refusals in this area are easy to get subtly wrong. A write-off of an
uncollectible receivable is keyed on the invoice's net amount due, so a figure
one cent either side of it — and the gross figure in particular — must be
refused, yet the approval that follows moves the gross out of billed-and-open
because the withheld retainage was never a receivable in the first place. And a
billing multiplier is resolved against the work date rather than the approval
date, so a project that is perfectly well configured today still cannot approve
a timesheet dated before its first multiplier window, while the labour rate
window that does cover that date is not the failing check.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_invoice_money,
    assert_project_ledger,
    assert_time_entry_carries_no_money,
    assert_time_entry_frozen,
    assert_write_off_routing,
)
from test_helpers.constants import (
    APPROVER_CONTROLLER,
    CLOCK_2026_06_01,
    INVOICE_APPROVED,
    INVOICE_WRITTEN_OFF,
    TARGET_INVOICE_RECEIVABLE,
    TIME_ENTRY_BILLED,
    TIME_ENTRY_SUBMITTED,
    WRITE_OFF_APPROVED,
    WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
)
from test_helpers.fixtures import (
    add_approved_time_entry,
    build_active_project,
    build_approved_invoice,
    prepare_receivable_write_off,
    read_invoice,
    read_project,
    read_time_entry,
    refresh_version,
    submit_time_entry,
)
from test_helpers.test_users import ACCOUNTANT, CONTROLLER_ALT, PROJECT_MANAGER

# The PRD's own worked labour example: 7.35 h at 62.50 with a multiplier of
# 3.0500 freezes a raw cost of 459.38 and a billable amount of 1401.11. Billed
# to a client withholding 5% retainage that gross becomes a 1331.05 net due.
CANONICAL_MULTIPLIER = 3.0500
GROSS_BILLED = 1401.11
RETAINAGE_AMOUNT = 70.06
NET_DUE = 1331.05


def _project_with_client_approved_invoice(api):
    """
    An ACTIVE time-and-materials project whose single 7.35 h line has been swept
    onto an invoice that the client has already approved, so the receivable is
    open at a gross of 1401.11 and a net due of 1331.05.
    """
    ctx = build_active_project(api, clock=CLOCK_2026_06_01, multiplier=CANONICAL_MULTIPLIER)
    entry = add_approved_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    invoice = build_approved_invoice(api, ctx, period_end="2026-05-31")
    refresh_version(api, ctx)
    return ctx, entry, invoice


def test_receivable_write_off_refuses_the_gross_and_a_one_cent_near_miss(api):
    """
    The receivable write-off amount must equal the invoice's net due of 1331.05
    exactly. The gross of 1401.11 is refused even though it is the figure the
    project rollup will later move, and so is 1331.04, one cent short.

    PRD §3.8: "For `INVOICE_RECEIVABLE` there is no allocation at all: `allocated_time_entry_ids` is empty, the `amount` must equal the named invoice's `net_due` exactly — any other figure is refused with `ERR_WRITE_OFF_AMOUNT_MISMATCH` (HTTP 422) — and `aging_days` is frozen at the age in whole days of that invoice's `period_end`."

    Design: Corner/errors/receivable_write_off_must_equal_net_due_while_the_rollup_moves_gross
    """
    ctx, _entry, invoice = _project_with_client_approved_invoice(api)

    assert invoice["status"] == INVOICE_APPROVED
    assert_invoice_money(
        invoice,
        gross_billed=GROSS_BILLED,
        discount_amount=0.00,
        retainage_amount=RETAINAGE_AMOUNT,
        net_due=NET_DUE,
    )

    for wrong_amount in (GROSS_BILLED, 1331.04):
        response = api.create_write_off(
            f.receivable_write_off_payload(
                ctx.project_id, invoice["id"], wrong_amount, reason="Client insolvent"
            ),
            ACCOUNTANT,
        )
        validate_error(response, err.ERR_WRITE_OFF_AMOUNT_MISMATCH, 422)

    # Nothing moved: the receivable is still open at its billed gross.
    assert_project_ledger(
        read_project(api, ctx.project_id),
        billed_open=GROSS_BILLED,
        written_off_gross=0.00,
        unbilled_wip=0.00,
        total_charge_value=GROSS_BILLED,
    )
    assert read_invoice(api, invoice["id"])["status"] == INVOICE_APPROVED


def test_receivable_write_off_at_the_net_due_always_routes_to_the_controller(api):
    """
    At exactly 1331.05 the write-off is accepted, allocates against no labour at
    all, freezes its age from the invoice's 2026-05-31 period end against the
    2026-06-01 logical clock, and routes to controller authority even though
    1331.05 sits well below the 5000.00 escalation amount and one day is well
    below the 90-day escalation age.

    PRD §3.8: "An `INVOICE_RECEIVABLE` write-off always routes to `CONTROLLER` regardless of its amount or age."
    PRD §3.8: "The write-off's initial `status` is `PENDING_CONTROLLER_APPROVAL` when `required_approver` is `CONTROLLER` and `PENDING_PM_APPROVAL` when it is `PROJECT_MANAGER`."

    Design: Corner/errors/receivable_write_off_must_equal_net_due_while_the_rollup_moves_gross
    """
    ctx, _entry, invoice = _project_with_client_approved_invoice(api)

    write_off = prepare_receivable_write_off(api, ctx, invoice["id"], NET_DUE)

    assert write_off["target_type"] == TARGET_INVOICE_RECEIVABLE
    assert write_off["invoice_id"] == invoice["id"]
    assert_write_off_routing(
        write_off,
        required_approver=APPROVER_CONTROLLER,
        status=WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
        aging_days=1,
        allocated_time_entry_ids=[],
    )
    assert write_off["approved_by_user_id"] is None, (
        "a freshly prepared write-off has no approver yet: "
        f"{write_off['approved_by_user_id']!r}"
    )


def test_approving_the_receivable_write_off_moves_the_gross_not_the_net_due(api):
    """
    Approval writes the invoice off, and the rollup moves the 1401.11 gross rather
    than the 1331.05 amount, which is exactly what keeps the conserved ledger at
    1401.11 throughout. The controller branch also raises the overhead adjustment
    flag, and the labour line — which this write-off never allocated — stays BILLED.

    PRD §3.8: "For an `INVOICE_RECEIVABLE` target — a case only this branch can reach — the named invoice moves `APPROVED → WRITTEN_OFF`, which requires that invoice to be in `APPROVED` and the write-off `amount` to equal its `net_due`; the project's `billed_open` falls by that invoice's `gross_billed` while `written_off_gross` rises by that same `gross_billed`."
    PRD §3.8: "This branch, and only this branch, sets the project's `overhead_adjustment_required` flag to true, because a write-off approved at controller level must be disclosed in the firm's next overhead certification."
    PRD §3.3: "The only terminal destination is `WRITTEN_OFF`, reached from `APPROVED` when a write-off that allocated the line is approved."

    Design: Corner/errors/receivable_write_off_must_equal_net_due_while_the_rollup_moves_gross
    """
    ctx, entry, invoice = _project_with_client_approved_invoice(api)
    write_off = prepare_receivable_write_off(api, ctx, invoice["id"], NET_DUE)

    # The approving controller is a different operator from the preparer.
    approved = validate_success(api.approve_write_off(write_off["id"], CONTROLLER_ALT))
    assert approved["status"] == WRITE_OFF_APPROVED

    assert read_invoice(api, invoice["id"])["status"] == INVOICE_WRITTEN_OFF
    assert read_time_entry(api, entry["id"])["status"] == TIME_ENTRY_BILLED

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=GROSS_BILLED,
        total_charge_value=GROSS_BILLED,
    )
    assert project["overhead_adjustment_required"] is True, (
        "a write-off approved at controller level must raise the overhead "
        f"adjustment flag: {project['overhead_adjustment_required']!r}"
    )


def _project_whose_multiplier_starts_in_may(api):
    """
    An ACTIVE time-and-materials project whose only billing multiplier is 3.0500
    effective from 2026-05-01, against a PROJECT_ARCHITECT cost rate of 62.50
    that has been effective since 2026-01-01 and therefore covers both dates.
    """
    return build_active_project(
        api,
        clock=CLOCK_2026_06_01,
        multiplier=CANONICAL_MULTIPLIER,
        multiplier_effective_from="2026-05-01",
    )


def test_a_work_date_before_the_first_multiplier_window_cannot_be_approved(api):
    """
    A 2026-04-28 line is refused at approval because no multiplier window covers
    that work date, and the refusal is the multiplier one rather than the labour
    rate one — the 62.50 rate has been effective since 2026-01-01. The line stays
    awaiting approval, carrying no money at all.

    PRD §3.3: "If no rate window covers the pair, the request is refused with `ERR_NO_EFFECTIVE_LABOR_RATE` (HTTP 422); if no multiplier window covers the date, `ERR_NO_EFFECTIVE_MULTIPLIER` (HTTP 422)."
    PRD §3.3: "The line lands in `status` `SUBMITTED` and, crucially, carries no money yet: its `raw_cost` and `billable_amount` are both 0.00 and its `applied_multiplier` is `null`."

    Design: Corner/errors/a_charge_before_the_first_multiplier_window_cannot_be_approved
    """
    ctx = _project_whose_multiplier_starts_in_may(api)
    early_line = submit_time_entry(api, ctx, hours=4.00, work_date="2026-04-28")

    validate_error(
        api.approve_time_entry(early_line["id"], PROJECT_MANAGER),
        err.ERR_NO_EFFECTIVE_MULTIPLIER,
        422,
    )

    unchanged = read_time_entry(api, early_line["id"])
    assert unchanged["status"] == TIME_ENTRY_SUBMITTED
    assert_time_entry_carries_no_money(unchanged)
    assert unchanged["approved_by_user_id"] is None

    assert_project_ledger(
        read_project(api, ctx.project_id),
        raw_labor_cost_to_date=0.00,
        unbilled_wip=0.00,
        total_charge_value=0.00,
    )


def test_a_work_date_on_the_inclusive_window_start_approves_and_freezes_the_charge(api):
    """
    The very first date the 2026-05-01 window covers is 2026-05-01 itself, because
    a multiplier covers a date when its effective start is on or before it. That
    line approves and freezes 250.00 of raw cost at 3.0500 for 762.50 of billable
    value, while the 2026-04-28 line beside it still cannot be approved.

    PRD §3.3: "in both cases a row covers the date when its `effective_from` is on or before the `work_date` and either it has no `effective_to` or the `work_date` is strictly earlier than that `effective_to`."
    PRD §3.3: "Third, `billable_amount` is the already-rounded `raw_cost` multiplied by `applied_multiplier`, rounded half up to 2 decimal places."

    Design: Corner/errors/a_charge_before_the_first_multiplier_window_cannot_be_approved
    """
    ctx = _project_whose_multiplier_starts_in_may(api)
    early_line = submit_time_entry(api, ctx, hours=4.00, work_date="2026-04-28")
    boundary_line = submit_time_entry(api, ctx, hours=4.00, work_date="2026-05-01")

    validate_error(
        api.approve_time_entry(early_line["id"], PROJECT_MANAGER),
        err.ERR_NO_EFFECTIVE_MULTIPLIER,
        422,
    )
    approved = validate_success(
        api.approve_time_entry(boundary_line["id"], PROJECT_MANAGER)
    )
    assert_time_entry_frozen(approved, 250.00, CANONICAL_MULTIPLIER, 762.50)

    # Only the approvable line moved any money onto the project.
    assert_project_ledger(
        read_project(api, ctx.project_id),
        raw_labor_cost_to_date=250.00,
        unbilled_wip=762.50,
        total_charge_value=762.50,
        net_multiplier_achieved=CANONICAL_MULTIPLIER,
    )
    assert read_time_entry(api, early_line["id"])["status"] == TIME_ENTRY_SUBMITTED
