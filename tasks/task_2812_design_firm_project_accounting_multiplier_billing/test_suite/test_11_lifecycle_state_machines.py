"""
Three lifecycles in this practice that are not simple forward chains: the
bounded client revision loop, the consultant payable's three orthogonal status
axes, and the forked write-off approval whose two branches rejoin on one state
while doing different things on the way.

The client review cycle is a genuine loop — a draft goes out, comes back for
revision and returns to draft — and each traversal re-runs the sweep, so an
invoice leaves the loop carrying charges it never held when it entered. The loop
is nevertheless bounded, and once the counter is spent the client's only
remaining move is to approve.

A consultant payable is one row with three independent state dimensions. Billing
the client advances one axis, paying the subconsultant advances another, and the
approval axis has an unwind edge that quietly disappears the moment the charge
has been passed on to the client.

A write-off forks at preparation into either a project-manager or a controller
approval branch. Both end in the same state, yet only the controller branch flags
the project for an overhead adjustment and only it can retire a receivable.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_REVISION_LIMIT_EXCEEDED,
)
from test_helpers.assertions import (
    assert_invoice_money,
    assert_money,
    assert_null,
    assert_payable_axes,
    assert_payable_markup,
    assert_project_ledger,
    assert_subcontract_rollup,
    assert_swept_counts,
    assert_write_off_routing,
)
from test_helpers.constants import (
    APPROVER_CONTROLLER,
    APPROVER_PROJECT_MANAGER,
    CLOCK_2026_06_01,
    CONTRACT_TIME_AND_MATERIALS,
    DECISION_APPROVE,
    DECISION_REQUEST_REVISION,
    INVOICE_APPROVED,
    INVOICE_DRAFT,
    INVOICE_PENDING_CLIENT_REVIEW,
    INVOICE_REVISION_REQUESTED,
    INVOICE_WRITTEN_OFF,
    MAX_REVISION_ROUND,
    METHOD_EFFORT_BASED,
    PAYABLE_APPROVED,
    PAYABLE_BILLED_TO_CLIENT,
    PAYABLE_UNBILLED,
    PAYMENT_RELEASED,
    PAYMENT_WITHHELD,
    SUBCONTRACT_EXECUTED,
    TIME_ENTRY_BILLED,
    TIME_ENTRY_WRITTEN_OFF,
    WRITE_OFF_APPROVED,
    WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
    WRITE_OFF_PENDING_PM_APPROVAL,
)
from test_helpers.factories import invoice_review_payload, reject_payload
from test_helpers.fixtures import (
    CANONICAL_MULTIPLIER,
    RATE_EFFECTIVE_FROM,
    activate_project,
    add_approved_payable,
    add_approved_time_entry,
    add_executed_subcontract,
    add_lump_sum_phase,
    approve_write_off,
    client_review,
    create_private_client,
    create_project,
    prepare_invoice,
    prepare_labor_write_off,
    prepare_receivable_write_off,
    project_version,
    publish_labor_rate,
    read_invoice,
    read_payable,
    read_project,
    read_subcontract,
    read_time_entry,
    revise_invoice,
    set_clock,
    set_multiplier,
    submit_invoice,
)
from test_helpers.test_users import (
    CONTROLLER,
    PROJECT_MANAGER,
    make_client_contact_headers,
)
from test_helpers.types import ProjectContext

# The revision loop: one line in, two lines out.
FIRST_LINE_HOURS = 7.35
FIRST_LINE_BILLABLE = 1401.11
SECOND_LINE_HOURS = 10.00
SECOND_LINE_BILLABLE = 1906.25
ROUND_ONE_GROSS = 1401.11
ROUND_ONE_RETAINAGE = 70.06
ROUND_ONE_NET_DUE = 1331.05
ROUND_TWO_GROSS = 3307.36
ROUND_TWO_RETAINAGE = 165.37
ROUND_TWO_NET_DUE = 3141.99

# The three-axis payable.
AXES_COMMITMENT = 30000.00
AXES_PAYABLE_AMOUNT = 20000.00
AXES_MARKUP_PCT = 0.1000
AXES_MARKUP_AMOUNT = 2000.00
AXES_BILLABLE = 22000.00
AXES_COMMITTED_REMAINING = 10000.00

# The forked write-off.
LABOR_WRITE_OFF_AMOUNT = 1906.25
LABOR_WRITE_OFF_AGING_DAYS = 20
RECEIVABLE_WRITE_OFF_AMOUNT = 1331.05
RECEIVABLE_WRITE_OFF_AGING_DAYS = 1
WRITTEN_OFF_GROSS_BOTH_BRANCHES = 3307.36


def _labor_billing_project(api):
    """
    An ACTIVE private hourly project with a published architect rate, ready to
    accrue labour at 62.50 an hour against a 3.0500 multiplier.
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    publish_labor_rate(api)
    project = create_project(
        api,
        client["id"],
        name="Riverside Library",
        contract_type=CONTRACT_TIME_AND_MATERIALS,
        contract_amount=800000.00,
        percent_complete_method=METHOD_EFFORT_BASED,
        target_multiplier=3.0000,
    )
    phase = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="02-DD",
        lump_sum_fee=200000.00,
        budget_labor_cost=60000.00,
        consultant_budget=100000.00,
    )
    set_multiplier(
        api,
        project["id"],
        multiplier=CANONICAL_MULTIPLIER,
        effective_from=RATE_EFFECTIVE_FROM,
        expected_project_version=project["version"],
    )
    activated = activate_project(api, project["id"])
    return ProjectContext(
        client_id=client["id"],
        project_id=project["id"],
        version=activated["version"],
        phase_ids=[phase["id"]],
        contract_type=CONTRACT_TIME_AND_MATERIALS,
    )


def _invoice_out_for_review(api):
    """
    The 7.35 h line swept onto a draft invoice for the May period and submitted
    to the client, so the invoice sits awaiting the client's decision.
    """
    ctx = _labor_billing_project(api)
    first_line = add_approved_time_entry(
        api, ctx, hours=FIRST_LINE_HOURS, work_date="2026-05-11"
    )
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    submitted = submit_invoice(api, invoice["id"])
    return ctx, first_line, submitted


def _consultant_axes_project(api):
    """
    An ACTIVE private hourly project with one EXECUTED 30000.00 commitment and a
    single approved 20000.00 payable worth 22000.00 to the client.
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    project = create_project(
        api,
        client["id"],
        name="Harbor Master Plan",
        contract_type=CONTRACT_TIME_AND_MATERIALS,
        contract_amount=900000.00,
        percent_complete_method=METHOD_EFFORT_BASED,
        target_multiplier=3.0000,
    )
    phase = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="02-DD",
        lump_sum_fee=300000.00,
        budget_labor_cost=90000.00,
        consultant_budget=100000.00,
    )
    set_multiplier(
        api,
        project["id"],
        multiplier=CANONICAL_MULTIPLIER,
        effective_from=RATE_EFFECTIVE_FROM,
        expected_project_version=project["version"],
    )
    activated = activate_project(api, project["id"])
    ctx = ProjectContext(
        client_id=client["id"],
        project_id=project["id"],
        version=activated["version"],
        phase_ids=[phase["id"]],
        contract_type=CONTRACT_TIME_AND_MATERIALS,
    )
    subcontract = add_executed_subcontract(
        api, ctx, committed_amount=AXES_COMMITMENT, pay_when_paid=False
    )
    payable = add_approved_payable(
        api, subcontract["id"], amount=AXES_PAYABLE_AMOUNT, invoice_date="2026-05-20"
    )
    return ctx, subcontract, payable


def _forked_write_off_project(api):
    """
    The 7.35 h line billed on a client-approved invoice, plus a second 10.00 h
    line approved afterwards and still unbilled — one charge on each side of the
    billing line, so the two write-off branches have distinct targets.
    """
    ctx = _labor_billing_project(api)
    first_line = add_approved_time_entry(
        api, ctx, hours=FIRST_LINE_HOURS, work_date="2026-05-11"
    )
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    submit_invoice(api, invoice["id"])
    approved_invoice = client_review(
        api, invoice["id"], ctx.client_id, decision=DECISION_APPROVE
    )
    second_line = add_approved_time_entry(
        api, ctx, hours=SECOND_LINE_HOURS, work_date="2026-05-12"
    )
    return ctx, first_line, second_line, approved_invoice


def _exhaust_the_revision_cycle(api, ctx, invoice_id):
    """
    Traverse the review loop until the revision counter is spent, leaving the
    invoice back out with the client.
    """
    for round_number in (1, 2, 3):
        returned = client_review(
            api,
            invoice_id,
            ctx.client_id,
            decision=DECISION_REQUEST_REVISION,
            comment=f"look number {round_number}",
        )
        assert returned["status"] == INVOICE_REVISION_REQUESTED
        assert returned["revision_round"] == round_number
        redrafted = revise_invoice(api, invoice_id)
        assert redrafted["status"] == INVOICE_DRAFT
        resubmitted = submit_invoice(api, invoice_id)
        assert resubmitted["status"] == INVOICE_PENDING_CLIENT_REVIEW
    return read_invoice(api, invoice_id)


def test_first_pass_bills_only_the_single_swept_line(api):
    """
    The invoice enters the loop carrying one 1401.11 labour line: no volume
    discount applies at that size, retainage is 70.06 and the client is asked
    for 1331.05, with the revision counter still at zero.

    PRD §3.7: "the invoice lands in `status` `DRAFT` with `revision_round` 0, and its `submitted_by_user_id`, `client_decision_comment`, `paid_on` and `void_reason` are all `null`"
    PRD §3.7: "`labor_billed` is the sum of `billable_amount` over time entries whose `status` is `APPROVED`, whose `billed_invoice_id` is null and whose `work_date` is on or before `period_end`."

    Design: Difficulty/non_linear_state_machine/invoice_revision_cycle_with_bounded_termination
    """
    ctx = _labor_billing_project(api)
    first_line = add_approved_time_entry(
        api, ctx, hours=FIRST_LINE_HOURS, work_date="2026-05-11"
    )

    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    assert invoice["status"] == INVOICE_DRAFT
    assert invoice["revision_round"] == 0
    assert_null(invoice["submitted_by_user_id"], "invoice.submitted_by_user_id")
    assert_null(invoice["client_decision_comment"], "invoice.client_decision_comment")
    assert_null(invoice["paid_on"], "invoice.paid_on")
    assert_null(invoice["void_reason"], "invoice.void_reason")
    assert_swept_counts(invoice, swept_labor_count=1, swept_consultant_count=0)
    assert_invoice_money(
        invoice,
        labor_billed=ROUND_ONE_GROSS,
        consultant_billed=0.00,
        expense_billed=0.00,
        gross_billed=ROUND_ONE_GROSS,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=ROUND_ONE_RETAINAGE,
        net_due=ROUND_ONE_NET_DUE,
    )

    out_for_review = submit_invoice(api, invoice["id"])
    assert out_for_review["status"] == INVOICE_PENDING_CLIENT_REVIEW
    assert out_for_review["revision_round"] == 0
    assert read_time_entry(api, first_line["id"])["status"] == TIME_ENTRY_BILLED


def test_returning_to_draft_re_sweeps_and_changes_the_bill(api):
    """
    A revision request bumps the counter and sends the invoice back; a second
    labour line approved while it is out there is picked up when the invoice
    returns to draft, so the same invoice now carries two lines, 3307.36 gross,
    165.37 of retainage and 3141.99 due.

    PRD §3.7: "`REQUEST_REVISION` first increments `revision_round` by 1 and then moves the invoice `PENDING_CLIENT_REVIEW → REVISION_REQUESTED`."
    PRD §3.7: "Charges already attached stay attached; the sweep re-runs and additionally attaches every newly eligible charge dated on or before `period_end`."
    PRD §3.7: "Because the charge set has changed, `gross_billed`, `volume_discount_pct`, `discount_amount`, `retainage_amount` and `net_due` are all recomputed from the new set by the same pinned order."

    Design: Difficulty/non_linear_state_machine/invoice_revision_cycle_with_bounded_termination
    """
    ctx, first_line, submitted = _invoice_out_for_review(api)
    assert_invoice_money(submitted, gross_billed=ROUND_ONE_GROSS, net_due=ROUND_ONE_NET_DUE)

    returned = client_review(
        api,
        submitted["id"],
        ctx.client_id,
        decision=DECISION_REQUEST_REVISION,
        comment="split the schematic phase",
    )
    assert returned["status"] == INVOICE_REVISION_REQUESTED
    assert returned["revision_round"] == 1
    assert returned["client_decision_comment"] == "split the schematic phase"

    second_line = add_approved_time_entry(
        api, ctx, hours=SECOND_LINE_HOURS, work_date="2026-05-12"
    )
    assert_money(second_line["billable_amount"], SECOND_LINE_BILLABLE, "second line billable")

    redrafted = revise_invoice(api, submitted["id"])
    assert redrafted["status"] == INVOICE_DRAFT
    assert redrafted["revision_round"] == 1
    assert_null(redrafted["submitted_by_user_id"], "invoice.submitted_by_user_id")
    assert_swept_counts(redrafted, swept_labor_count=2)
    assert_invoice_money(
        redrafted,
        labor_billed=ROUND_TWO_GROSS,
        gross_billed=ROUND_TWO_GROSS,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=ROUND_TWO_RETAINAGE,
        net_due=ROUND_TWO_NET_DUE,
    )

    assert read_time_entry(api, first_line["id"])["billed_invoice_id"] == submitted["id"]
    assert read_time_entry(api, second_line["id"])["billed_invoice_id"] == submitted["id"]
    assert_project_ledger(
        read_project(api, ctx.project_id), unbilled_wip=0.00, billed_open=ROUND_TWO_GROSS
    )


def test_a_fourth_revision_request_is_refused_once_the_counter_is_spent(api):
    """
    Three traversals of the loop take the counter to its ceiling. A fourth
    revision request is refused outright, and the refusal is inert: the counter
    stays at three and the invoice stays out with the client.

    PRD §3.7: "The cycle is bounded: `revision_round` ranges from 0 to 3, and a `REQUEST_REVISION` attempted once `revision_round` has already reached 3 is refused with `ERR_REVISION_LIMIT_EXCEEDED` (HTTP 409), which leaves the client only `APPROVE` while the firm retains the option to void."

    Design: Difficulty/non_linear_state_machine/invoice_revision_cycle_with_bounded_termination
    """
    ctx, first_line, submitted = _invoice_out_for_review(api)
    spent = _exhaust_the_revision_cycle(api, ctx, submitted["id"])
    assert spent["revision_round"] == MAX_REVISION_ROUND
    assert spent["status"] == INVOICE_PENDING_CLIENT_REVIEW

    refused = api.review_invoice(
        submitted["id"],
        invoice_review_payload(DECISION_REQUEST_REVISION, "fourth look"),
        make_client_contact_headers(ctx.client_id),
    )
    validate_error(refused, ERR_REVISION_LIMIT_EXCEEDED, 409)

    unchanged = read_invoice(api, submitted["id"])
    assert unchanged["revision_round"] == MAX_REVISION_ROUND
    assert unchanged["status"] == INVOICE_PENDING_CLIENT_REVIEW


def test_approval_is_still_open_from_the_state_that_refused_the_revision(api):
    """
    The bound removes only one of the client's two moves. From the very state
    that refused a fourth revision request, approval succeeds and the invoice
    leaves the loop for good.

    PRD §3.7: "`APPROVE` moves the invoice `PENDING_CLIENT_REVIEW → APPROVED`."
    PRD §3.7: "Either decision increments the invoice's `version` by 1."

    Design: Difficulty/non_linear_state_machine/invoice_revision_cycle_with_bounded_termination
    """
    ctx, first_line, submitted = _invoice_out_for_review(api)
    spent = _exhaust_the_revision_cycle(api, ctx, submitted["id"])
    validate_error(
        api.review_invoice(
            submitted["id"],
            invoice_review_payload(DECISION_REQUEST_REVISION, "fourth look"),
            make_client_contact_headers(ctx.client_id),
        ),
        ERR_REVISION_LIMIT_EXCEEDED,
        409,
    )

    accepted = validate_success(
        api.review_invoice(
            submitted["id"],
            invoice_review_payload(DECISION_APPROVE),
            make_client_contact_headers(ctx.client_id),
        )
    )
    assert accepted["status"] == INVOICE_APPROVED
    assert accepted["revision_round"] == MAX_REVISION_ROUND
    assert accepted["version"] == spent["version"] + 1
    # No new charge arrived during the loop, so the bill is the one it entered with.
    assert_invoice_money(
        accepted, gross_billed=ROUND_ONE_GROSS, net_due=ROUND_ONE_NET_DUE
    )


def test_billing_the_client_advances_only_the_billing_axis(api):
    """
    Sweeping the payable onto a client invoice moves its billing axis to
    BILLED_TO_CLIENT and records the client invoice, while its approval axis
    stays APPROVED and the subconsultant is still unpaid.

    PRD §3.5: "On the third axis, an approved payable moves `UNBILLED → BILLED_TO_CLIENT` when a client invoice sweeps it, taking a `client_invoice_id`, and moves back `BILLED_TO_CLIENT → UNBILLED` with `client_invoice_id` cleared when that invoice is voided — but only while its `payment_status` is still `WITHHELD`."

    Design: Difficulty/non_linear_state_machine/consultant_invoice_three_independent_axes
    """
    ctx, subcontract, payable = _consultant_axes_project(api)
    assert_payable_axes(payable, PAYABLE_APPROVED, PAYMENT_WITHHELD, PAYABLE_UNBILLED)
    assert_payable_markup(
        payable,
        applied_markup_pct=AXES_MARKUP_PCT,
        markup_amount=AXES_MARKUP_AMOUNT,
        billable_amount=AXES_BILLABLE,
    )
    assert_null(payable["client_invoice_id"], "payable.client_invoice_id")

    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    swept = read_payable(api, payable["id"])
    assert_payable_axes(swept, PAYABLE_APPROVED, PAYMENT_WITHHELD, PAYABLE_BILLED_TO_CLIENT)
    assert swept["client_invoice_id"] == invoice["id"]
    assert_money(swept["billable_amount"], AXES_BILLABLE, "payable.billable_amount")
    assert_invoice_money(invoice, consultant_billed=AXES_BILLABLE, gross_billed=AXES_BILLABLE)

    rows, meta = validate_paginated(
        api.list_consultant_invoices(CONTROLLER, {"client_invoice_id": invoice["id"]})
    )
    assert meta["total_count"] == 1, (
        f"exactly one payable was swept onto the invoice, got total_count {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [payable["id"]]


def test_paying_the_subconsultant_advances_only_the_payment_axis(api):
    """
    An explicit release on a subcontract that is not pay-when-paid moves the
    payment axis to RELEASED and leaves the billing axis exactly where the client
    invoice put it. The commitment records 20000.00 released against a 30000.00
    commitment, so the subcontract stays EXECUTED.

    PRD §3.5: "Either route raises the subcontract's `released_to_date` by the `amount` and increments both the payable's `version` and the subcontract's `version` by 1."
    PRD §3.5: "The three axes genuinely evolve independently: a payable can be `RELEASED` while still `BILLED_TO_CLIENT`, and can be rejected only while `UNBILLED`."

    Design: Difficulty/non_linear_state_machine/consultant_invoice_three_independent_axes
    """
    ctx, subcontract, payable = _consultant_axes_project(api)
    prepare_invoice(api, ctx, period_end="2026-05-31")

    released = validate_success(api.release_consultant_payment(payable["id"], CONTROLLER))
    assert_payable_axes(
        released, PAYABLE_APPROVED, PAYMENT_RELEASED, PAYABLE_BILLED_TO_CLIENT
    )
    assert_money(released["billable_amount"], AXES_BILLABLE, "payable.billable_amount")

    assert_subcontract_rollup(
        read_subcontract(api, subcontract["id"]),
        approved_to_date=AXES_PAYABLE_AMOUNT,
        released_to_date=AXES_PAYABLE_AMOUNT,
        committed_remaining=AXES_COMMITTED_REMAINING,
        status=SUBCONTRACT_EXECUTED,
    )


def test_the_unwind_edge_closes_once_the_charge_has_been_billed_on(api):
    """
    Rejecting an already-approved payable is a full compensating action, but only
    while the charge is still unbilled. Once the client invoice has taken it, the
    edge is gone and the approval axis cannot be walked back.

    PRD §3.5: "The same actors may also reject a payable that has already been `APPROVED`, but only while its `billing_status` is still `UNBILLED`."
    PRD §3.7: "any attempt to repeat a transition already applied or to leave a terminal state is refused with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)"

    Design: Difficulty/non_linear_state_machine/consultant_invoice_three_independent_axes
    """
    ctx, subcontract, payable = _consultant_axes_project(api)
    prepare_invoice(api, ctx, period_end="2026-05-31")
    validate_success(api.release_consultant_payment(payable["id"], CONTROLLER))

    refused = api.reject_consultant_invoice(
        payable["id"], reject_payload("too late to unwind"), CONTROLLER
    )
    validate_error(refused, ERR_INVALID_STATE_TRANSITION, 409)

    unchanged = read_payable(api, payable["id"])
    assert_payable_axes(
        unchanged, PAYABLE_APPROVED, PAYMENT_RELEASED, PAYABLE_BILLED_TO_CLIENT
    )
    assert_payable_markup(
        unchanged,
        applied_markup_pct=AXES_MARKUP_PCT,
        markup_amount=AXES_MARKUP_AMOUNT,
        billable_amount=AXES_BILLABLE,
    )
    assert_null(unchanged["rejection_reason"], "payable.rejection_reason")
    assert_subcontract_rollup(
        read_subcontract(api, subcontract["id"]),
        approved_to_date=AXES_PAYABLE_AMOUNT,
        committed_remaining=AXES_COMMITTED_REMAINING,
    )


def test_the_frozen_billable_value_survives_all_three_axis_movements(api):
    """
    The money on the payable is frozen at approval and none of the three axes
    disturbs it: 22000.00 is what the client is billed, what stays on the
    payable after release, and what the refused unwind leaves behind.

    PRD §3.5: "All three figures are frozen on the payable at approval."

    Design: Difficulty/non_linear_state_machine/consultant_invoice_three_independent_axes
    """
    ctx, subcontract, payable = _consultant_axes_project(api)
    assert_money(payable["billable_amount"], AXES_BILLABLE, "at approval")

    prepare_invoice(api, ctx, period_end="2026-05-31")
    assert_money(
        read_payable(api, payable["id"])["billable_amount"], AXES_BILLABLE, "after billing"
    )

    validate_success(api.release_consultant_payment(payable["id"], CONTROLLER))
    assert_money(
        read_payable(api, payable["id"])["billable_amount"], AXES_BILLABLE, "after release"
    )

    validate_error(
        api.reject_consultant_invoice(
            payable["id"], reject_payload("too late to unwind"), CONTROLLER
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    assert_money(
        read_payable(api, payable["id"])["billable_amount"],
        AXES_BILLABLE,
        "after the refused unwind",
    )
    assert_project_ledger(
        read_project(api, ctx.project_id), billed_open=AXES_BILLABLE, unbilled_wip=0.00
    )


def test_small_recent_unbilled_labour_forks_to_the_project_manager_branch(api):
    """
    A 1906.25 write-off against a single 20-day-old unbilled line is below the
    escalation amount and well inside the escalation age, so it routes to the
    project manager and waits for that approval, with the one line it could be
    allocated to named in order.

    PRD §3.8: "`required_approver` is set to `CONTROLLER` when the `amount` is at or above 5000.00 or the `aging_days` is at or above 90 — both thresholds inclusive, so an amount of exactly 5000.00 and an age of exactly 90 days each escalate — and to `PROJECT_MANAGER` otherwise."
    PRD §3.8: "On success, `allocated_time_entry_ids` holds the ordered list of identifiers the amount was allocated to, and `aging_days` is frozen at the greatest age in whole days among those allocated entries, measured from each entry's `work_date` against the logical clock."

    Design: Difficulty/non_linear_state_machine/write_off_fork_join_divergent_side_effects
    """
    ctx, first_line, second_line, invoice = _forked_write_off_project(api)

    write_off = prepare_labor_write_off(
        api, ctx, LABOR_WRITE_OFF_AMOUNT, reason="client refused the extra site visits"
    )
    assert_write_off_routing(
        write_off,
        required_approver=APPROVER_PROJECT_MANAGER,
        status=WRITE_OFF_PENDING_PM_APPROVAL,
        aging_days=LABOR_WRITE_OFF_AGING_DAYS,
        allocated_time_entry_ids=[second_line["id"]],
    )
    assert_money(write_off["amount"], LABOR_WRITE_OFF_AMOUNT, "write_off.amount")
    assert_null(write_off["approved_by_user_id"], "write_off.approved_by_user_id")
    # The already-billed line is not a candidate, so it is untouched.
    assert read_time_entry(api, first_line["id"])["status"] == TIME_ENTRY_BILLED


def test_the_project_manager_branch_leaves_the_overhead_flag_alone(api):
    """
    Project-manager approval retires the allocated line and moves 1906.25 out of
    work in progress into the written-off bucket, and it deliberately does not
    raise the overhead disclosure flag.

    PRD §3.8: "This branch leaves the project's `overhead_adjustment_required` flag **unchanged**."
    PRD §3.8: "Every time entry named in `allocated_time_entry_ids` moves `APPROVED → WRITTEN_OFF`, each such entry's `version` incrementing by 1; the project's `unbilled_wip` falls by the write-off `amount` while `written_off_gross` rises by the same amount"

    Design: Difficulty/non_linear_state_machine/write_off_fork_join_divergent_side_effects
    """
    ctx, first_line, second_line, invoice = _forked_write_off_project(api)
    before = read_project(api, ctx.project_id)
    assert before["overhead_adjustment_required"] is False

    write_off = prepare_labor_write_off(
        api, ctx, LABOR_WRITE_OFF_AMOUNT, reason="client refused the extra site visits"
    )
    approved = approve_write_off(api, write_off["id"], PROJECT_MANAGER)
    assert approved["status"] == WRITE_OFF_APPROVED

    assert read_time_entry(api, second_line["id"])["status"] == TIME_ENTRY_WRITTEN_OFF
    project = read_project(api, ctx.project_id)
    assert project["overhead_adjustment_required"] is False, (
        "the project-manager branch must not raise the overhead disclosure flag"
    )
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=ROUND_ONE_GROSS,
        paid_gross_to_date=0.00,
        written_off_gross=LABOR_WRITE_OFF_AMOUNT,
    )


def test_a_receivable_always_forks_to_the_controller_branch(api):
    """
    A write-off aimed at a client receivable escalates regardless of size: 1331.05
    is far below the escalation amount and the receivable is only a day old, yet
    the write-off still waits for a controller and carries no labour allocation.

    PRD §3.8: "An `INVOICE_RECEIVABLE` write-off always routes to `CONTROLLER` regardless of its amount or age."
    PRD §3.8: "For `INVOICE_RECEIVABLE` there is no allocation at all: `allocated_time_entry_ids` is empty, the `amount` must equal the named invoice's `net_due` exactly — any other figure is refused with `ERR_WRITE_OFF_AMOUNT_MISMATCH` (HTTP 422) — and `aging_days` is frozen at the age in whole days of that invoice's `period_end`."

    Design: Difficulty/non_linear_state_machine/write_off_fork_join_divergent_side_effects
    """
    ctx, first_line, second_line, invoice = _forked_write_off_project(api)
    assert invoice["status"] == INVOICE_APPROVED
    assert_invoice_money(invoice, gross_billed=ROUND_ONE_GROSS, net_due=ROUND_ONE_NET_DUE)

    write_off = prepare_receivable_write_off(
        api, ctx, invoice["id"], RECEIVABLE_WRITE_OFF_AMOUNT, reason="receivable uncollectible"
    )
    assert_write_off_routing(
        write_off,
        required_approver=APPROVER_CONTROLLER,
        status=WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
        aging_days=RECEIVABLE_WRITE_OFF_AGING_DAYS,
        allocated_time_entry_ids=[],
    )
    assert_money(write_off["amount"], RECEIVABLE_WRITE_OFF_AMOUNT, "write_off.amount")
    assert write_off["invoice_id"] == invoice["id"]


def test_the_controller_branch_raises_the_flag_and_retires_the_receivable(api):
    """
    Both branches end in the same approved state, but the controller branch does
    more: it flips the invoice to written off, moves the invoice's gross rather
    than its net out of the open billed position, and raises the overhead
    disclosure flag the project-manager branch left alone. The conserved total
    across both branches is 3307.36.

    PRD §3.8: "This branch, and only this branch, sets the project's `overhead_adjustment_required` flag to true, because a write-off approved at controller level must be disclosed in the firm's next overhead certification."
    PRD §3.8: "the named invoice moves `APPROVED → WRITTEN_OFF`, which requires that invoice to be in `APPROVED` and the write-off `amount` to equal its `net_due`; the project's `billed_open` falls by that invoice's `gross_billed` while `written_off_gross` rises by that same `gross_billed`"
    PRD §3.8: "The write-off amount is the `net_due` but the rollup moves the gross, which is exactly what keeps `total_charge_value` conserved."

    Design: Difficulty/non_linear_state_machine/write_off_fork_join_divergent_side_effects
    """
    ctx, first_line, second_line, invoice = _forked_write_off_project(api)

    labor_write_off = prepare_labor_write_off(
        api, ctx, LABOR_WRITE_OFF_AMOUNT, reason="client refused the extra site visits"
    )
    approve_write_off(api, labor_write_off["id"], PROJECT_MANAGER)

    receivable_write_off = prepare_receivable_write_off(
        api, ctx, invoice["id"], RECEIVABLE_WRITE_OFF_AMOUNT, reason="receivable uncollectible"
    )
    version_before = project_version(api, ctx.project_id)
    approved = approve_write_off(api, receivable_write_off["id"], CONTROLLER)
    assert approved["status"] == WRITE_OFF_APPROVED

    assert read_invoice(api, invoice["id"])["status"] == INVOICE_WRITTEN_OFF
    project = read_project(api, ctx.project_id)
    assert project["overhead_adjustment_required"] is True, (
        "the controller branch must raise the overhead disclosure flag"
    )
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=WRITTEN_OFF_GROSS_BOTH_BRANCHES,
        total_charge_value=WRITTEN_OFF_GROSS_BOTH_BRANCHES,
    )
    assert project["version"] == version_before + 1
    assert read_time_entry(api, first_line["id"])["status"] == TIME_ENTRY_BILLED
    assert read_time_entry(api, second_line["id"])["status"] == TIME_ENTRY_WRITTEN_OFF
