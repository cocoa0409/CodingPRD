"""
Lifecycle transitions of the architecture practice project accounting API.

Covers the states a timesheet line, a project and a client invoice may legally
occupy: the money-free birth of a submitted timesheet line, the refusal of a
replayed approval, the two structural preconditions on opening a project for
business, the single legal from-state each invoice action names, and the
lockdown a closed project imposes on every further write.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_PROJECT_NOT_ACTIVE,
)
from test_helpers.assertions import (
    assert_aging_report,
    assert_billing_posture,
    assert_invoice_money,
    assert_money,
    assert_null,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_time_entry_carries_no_money,
    assert_time_entry_frozen,
)
from test_helpers.constants import (
    CATEGORY_PRINTING,
    INVOICE_DRAFT,
    INVOICE_PENDING_CLIENT_REVIEW,
    MULTIPLIER_ACTIVE,
    PHASE_COMPLETE,
    PHASE_PLANNED,
    POSTURE_OPEN,
    PROJECT_ACTIVE,
    PROJECT_CLOSED,
    PROJECT_SETUP,
    TIME_ENTRY_APPROVED,
    TIME_ENTRY_BILLED,
    TIME_ENTRY_SUBMITTED,
)
from test_helpers.factories import (
    expense_payload,
    multiplier_payload,
    record_payment_payload,
    time_entry_payload,
)
from test_helpers.fixtures import (
    activate_project,
    add_approved_payable,
    add_approved_time_entry,
    add_executed_subcontract,
    add_lump_sum_phase,
    approve_time_entry,
    build_active_project,
    build_paid_invoice,
    create_private_client,
    create_project,
    prepare_invoice,
    project_version,
    read_aging,
    read_invoice,
    read_phase,
    read_project,
    read_time_entry,
    refresh_version,
    submit_time_entry,
)
from test_helpers.test_users import (
    ACCOUNTANT,
    ACCOUNTANT_USER_ID,
    CONTROLLER,
    PROJECT_MANAGER,
    PROJECT_MANAGER_USER_ID,
    make_client_contact_headers,
)
from test_helpers.constants import DECISION_APPROVE
from test_helpers.factories import invoice_review_payload


def test_submitted_timesheet_line_starts_in_submitted_with_no_frozen_money(api):
    """
    A timesheet line records hours only: it lands SUBMITTED with no rate, no
    multiplier and no money, and with neither an approver nor a billing link.

    PRD §3.3: "The line lands in `status` `SUBMITTED` and, crucially, carries no money yet: its `raw_cost` and `billable_amount` are both 0.00 and its `applied_multiplier` is `null`."
    PRD §3.3: "Its `approved_by_user_id` is `null` and its `billed_invoice_id` is `null`."
    PRD §3.3: "The submitter's identifier is captured from the request header into `submitted_by_user_id`."

    Design: Corner/state_machines/time_entry_starts_submitted_with_no_frozen_money
    """
    ctx = build_active_project(api)

    entry = validate_success(
        api.create_time_entry(
            time_entry_payload(
                ctx.project_id, ctx.phase_id, work_date="2026-05-11", hours=7.35
            ),
            ACCOUNTANT,
        ),
        201,
    )

    assert entry["status"] == TIME_ENTRY_SUBMITTED
    assert_money(entry["hours"], 7.35, "time_entry.hours")
    assert entry["submitted_by_user_id"] == ACCOUNTANT_USER_ID
    assert_null(entry["approved_by_user_id"], "time_entry.approved_by_user_id")
    assert_null(entry["billed_invoice_id"], "time_entry.billed_invoice_id")
    assert_time_entry_carries_no_money(entry)


def test_submitted_timesheet_line_enters_no_rollup_and_no_aging_bucket(api):
    """
    While the line is still awaiting approval the phase carries no cost, the
    project carries no work in progress and the aging report is empty.

    PRD §3.3: "A `SUBMITTED` line contributes to no project rollup and appears in no aging bucket."
    PRD §3.6: "entries still in `SUBMITTED` are excluded, so an unapproved timesheet moves neither figure"
    PRD §2.10: "When `raw_labor_cost_to_date` is exactly 0.00, `net_multiplier_achieved` reports 0.0000 rather than being undefined."

    Design: Corner/state_machines/time_entry_starts_submitted_with_no_frozen_money
    """
    ctx = build_active_project(api)
    submit_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")

    phase = read_phase(api, ctx.phase_id)
    assert phase["status"] == PHASE_PLANNED
    assert_phase_earned_value(
        phase,
        actual_labor_cost_to_date=0.00,
        effort_based_percent_complete=0.0000,
        effort_based_earned_value=0.00,
        recognized_earned_value=0.00,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        raw_labor_cost_to_date=0.00,
        total_charge_value=0.00,
        net_multiplier_achieved=0.0000,
    )
    assert_billing_posture(project, POSTURE_OPEN)

    aging = read_aging(api, ctx.project_id)
    assert_aging_report(
        aging,
        bucket_0_30=0.00,
        bucket_31_60=0.00,
        bucket_61_90=0.00,
        bucket_over_90=0.00,
        total_unbilled=0.00,
        write_off_eligible_amount=0.00,
    )


def test_replayed_timesheet_approval_is_refused_and_leaves_the_approver_intact(api):
    """
    Approval names SUBMITTED as its only legal from-state, so a second approve
    on an already-approved line is refused and does not re-stamp the approver.

    PRD §3.3: "Approval is where the money is made, and it is performed by a `ProjectManager` or a `Controller`, moving the line from `SUBMITTED` to `APPROVED`."
    PRD §2.8: "12. Declared-transition legality for the target row's current state — `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/approving_an_already_approved_time_entry_is_refused
    """
    ctx = build_active_project(api)
    entry = submit_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    approved = approve_time_entry(api, entry["id"], PROJECT_MANAGER)
    assert approved["status"] == TIME_ENTRY_APPROVED
    assert approved["approved_by_user_id"] == PROJECT_MANAGER_USER_ID

    validate_error(
        api.approve_time_entry(entry["id"], CONTROLLER),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    reread = read_time_entry(api, entry["id"])
    assert reread["status"] == TIME_ENTRY_APPROVED
    assert reread["approved_by_user_id"] == PROJECT_MANAGER_USER_ID
    assert_time_entry_frozen(reread, 459.38, 3.0500, 1401.11)


def test_refused_replay_of_an_approval_doubles_no_cost_or_earned_value(api):
    """
    The refusal must leave the cascade applied exactly once: the phase holds one
    raw cost of 459.38 and the project one work-in-progress admission of 1401.11.

    PRD §3.3: "The second hop raises the phase's `actual_labor_cost_to_date` by the new `raw_cost`, which re-derives that phase's `effort_based_percent_complete`, `effort_based_earned_value` and `recognized_earned_value`."
    PRD §3.6: "`effort_based_earned_value` is then the `phase_fee` multiplied by `effort_based_percent_complete`, rounded half up to 2 decimal places."

    Design: Corner/state_machines/approving_an_already_approved_time_entry_is_refused
    """
    ctx = build_active_project(api)
    entry = submit_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    approve_time_entry(api, entry["id"], PROJECT_MANAGER)

    validate_error(
        api.approve_time_entry(entry["id"], CONTROLLER),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    phase = read_phase(api, ctx.phase_id)
    assert_phase_earned_value(
        phase,
        actual_labor_cost_to_date=459.38,
        effort_based_percent_complete=0.0077,
        effort_based_earned_value=1540.00,
        recognized_earned_value=1540.00,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=1401.11,
        raw_labor_cost_to_date=459.38,
        earned_revenue_to_date=1540.00,
        total_charge_value=1401.11,
    )


def test_project_with_no_phase_cannot_be_opened_for_business(api, clock_june):
    """
    Opening a project for business requires a shape: with no phase at all the
    move out of SETUP is refused and the project stays in SETUP.

    PRD §3.1: "Activation — moving a project's `status` from `SETUP` to `ACTIVE`, which a `FirmAdmin`, a `Controller` or the owning `ProjectManager` may perform — requires that the project already be in `SETUP`, that at least one phase exist on it, and that at least one billing multiplier with `status` `ACTIVE` exist on it."

    Design: Corner/state_machines/activation_requires_a_phase_and_an_active_multiplier
    """
    client = create_private_client(api)
    project = create_project(api, client["id"])

    validate_error(
        api.activate_project(project["id"], CONTROLLER),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    assert read_project(api, project["id"])["status"] == PROJECT_SETUP


def test_project_with_a_phase_but_no_active_multiplier_cannot_be_opened(api, clock_june):
    """
    A project also needs a price: a phase alone does not satisfy the second
    precondition, so the owning manager's activation is still refused.

    PRD §3.1: "Activation — moving a project's `status` from `SETUP` to `ACTIVE`, which a `FirmAdmin`, a `Controller` or the owning `ProjectManager` may perform — requires that the project already be in `SETUP`, that at least one phase exist on it, and that at least one billing multiplier with `status` `ACTIVE` exist on it."

    Design: Corner/state_machines/activation_requires_a_phase_and_an_active_multiplier
    """
    client = create_private_client(api)
    project = create_project(api, client["id"])
    add_lump_sum_phase(api, project["id"])

    validate_error(
        api.activate_project(project["id"], PROJECT_MANAGER),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    assert read_project(api, project["id"])["status"] == PROJECT_SETUP


def test_timesheet_capture_is_refused_while_the_project_is_still_in_setup(api, clock_june):
    """
    Charge capture waits for activation: a timesheet line booked against a phase
    of a SETUP project is refused and no line is created.

    PRD §3.1: "Time entries, expenses, consultant subcontracts, consultant payables, invoices and write-off preparations are all accepted only while the project's `status` is `ACTIVE`; attempting any of them, or a phase assessment or a phase completion, while the project is still `SETUP` or already `CLOSED` is refused with `ERR_PROJECT_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/activation_requires_a_phase_and_an_active_multiplier
    """
    client = create_private_client(api)
    project = create_project(api, client["id"])
    phase = add_lump_sum_phase(api, project["id"])

    validate_error(
        api.create_time_entry(
            time_entry_payload(
                project["id"], phase["id"], work_date="2026-05-11", hours=7.35
            ),
            ACCOUNTANT,
        ),
        ERR_PROJECT_NOT_ACTIVE,
        409,
    )

    rows = validate_success(
        api.list_time_entries(CONTROLLER, {"project_id": project["id"]})
    )
    assert rows == [], f"no timesheet line may exist on a project still in SETUP: {rows}"


def test_first_billing_multiplier_is_accepted_while_the_project_is_in_setup(api, clock_june):
    """
    Setting the first multiplier is the deliberate exemption from the active-project
    rule, and once phase and multiplier are both in place activation succeeds,
    reporting an OPEN posture and a bumped version.

    PRD §3.1: "Creating a billing multiplier is the one deliberate exemption: because a project cannot be activated until an `ACTIVE` multiplier exists, the first multiplier is necessarily written while the project is still in `SETUP`, so for multiplier creation the only status that triggers `ERR_PROJECT_NOT_ACTIVE` is `CLOSED`."
    PRD §3.1: "Activation recomputes `billing_posture` and increments the project's `version` by 1."

    Design: Corner/state_machines/activation_requires_a_phase_and_an_active_multiplier
    """
    client = create_private_client(api)
    project = create_project(api, client["id"])
    add_lump_sum_phase(api, project["id"])

    multiplier = validate_success(
        api.create_billing_multiplier(
            multiplier_payload(
                project["id"],
                project_version(api, project["id"]),
                multiplier=3.0500,
                effective_from="2026-01-01",
            ),
            CONTROLLER,
        ),
        201,
    )
    assert multiplier["status"] == MULTIPLIER_ACTIVE

    version_before = project_version(api, project["id"])
    activated = activate_project(api, project["id"])

    assert activated["status"] == PROJECT_ACTIVE
    assert_billing_posture(activated, POSTURE_OPEN)
    assert activated["version"] == version_before + 1, (
        f"activation must increment the project version from {version_before}, "
        f"got {activated['version']}"
    )


def _draft_invoice_over_one_approved_line(api):
    """An ACTIVE project, one approved line of 7.35 h and a DRAFT invoice over it."""
    ctx = build_active_project(api)
    entry = add_approved_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    return ctx, entry, invoice


def test_draft_invoice_refuses_client_review_revision_and_payment(api):
    """
    Each invoice action names exactly one legal from-state, so a DRAFT invoice
    refuses the client's decision, the return-to-draft and the payment recording
    alike, and its frozen totals survive every refusal.

    PRD §3.7: "`APPROVE` moves the invoice `PENDING_CLIENT_REVIEW → APPROVED`. `REQUEST_REVISION` first increments `revision_round` by 1 and then moves the invoice `PENDING_CLIENT_REVIEW → REVISION_REQUESTED`."
    PRD §3.7: "A revision-requested invoice is returned to draft by a `ProjectAccountant` or a `Controller`, moving it `REVISION_REQUESTED → DRAFT`"
    PRD §3.7: "Settlement is a `Controller` action recording receipt of the invoice's net due in full, moving the invoice `APPROVED → PAID` with a supplied `received_on` date stored as `paid_on`."

    Design: Corner/state_machines/invoice_actions_from_wrong_states_are_all_refused
    """
    ctx, entry, invoice = _draft_invoice_over_one_approved_line(api)
    assert invoice["status"] == INVOICE_DRAFT

    validate_error(
        api.review_invoice(
            invoice["id"],
            invoice_review_payload(DECISION_APPROVE),
            make_client_contact_headers(ctx.client_id),
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.revise_invoice(invoice["id"], ACCOUNTANT),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.record_invoice_payment(
            invoice["id"], record_payment_payload("2026-06-01"), CONTROLLER
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    reread = read_invoice(api, invoice["id"])
    assert reread["status"] == INVOICE_DRAFT
    assert reread["revision_round"] == 0
    assert_null(reread["paid_on"], "invoice.paid_on")
    assert_invoice_money(
        reread,
        labor_billed=1401.11,
        gross_billed=1401.11,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=70.06,
        net_due=1331.05,
    )

    swept = read_time_entry(api, entry["id"])
    assert swept["status"] == TIME_ENTRY_BILLED
    assert swept["billed_invoice_id"] == invoice["id"]


def test_replayed_invoice_submission_is_refused(api):
    """
    Submission is not idempotent: the first submit moves the invoice into client
    review and the replay is refused, leaving it in client review.

    PRD §3.7: "Submitting the invoice to the client moves it `DRAFT → PENDING_CLIENT_REVIEW` and is performed by a `ProjectAccountant` or a `Controller`. The invoice must be in `DRAFT`"
    PRD §3.7: "any attempt to repeat a transition already applied or to leave a terminal state is refused with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)"

    Design: Corner/state_machines/invoice_actions_from_wrong_states_are_all_refused
    """
    ctx, entry, invoice = _draft_invoice_over_one_approved_line(api)

    submitted = validate_success(api.submit_invoice(invoice["id"], CONTROLLER))
    assert submitted["status"] == INVOICE_PENDING_CLIENT_REVIEW

    validate_error(
        api.submit_invoice(invoice["id"], CONTROLLER),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    reread = read_invoice(api, invoice["id"])
    assert reread["status"] == INVOICE_PENDING_CLIENT_REVIEW
    assert reread["revision_round"] == 0
    assert_null(reread["paid_on"], "invoice.paid_on")
    assert read_time_entry(api, entry["id"])["status"] == TIME_ENTRY_BILLED


def _closed_project_after_a_paid_consultant_billing(api):
    """
    Drive one project to CLOSED: an executed pay-when-paid subcontract of
    20000.00, its approved payable billed at 22000.00, that invoice paid, and
    the phase then completed, which bubbles the project up to CLOSED.
    """
    ctx = build_active_project(api, phase_overrides={"consultant_budget": 100000.00})
    subcontract = add_executed_subcontract(
        api, ctx, committed_amount=20000.00, pay_when_paid=True
    )
    payable = add_approved_payable(api, subcontract["id"], amount=20000.00)
    invoice = build_paid_invoice(
        api, ctx, period_end="2026-05-31", received_on="2026-06-01"
    )
    completed = validate_success(api.complete_phase(ctx.phase_id, CONTROLLER))
    assert completed["status"] == PHASE_COMPLETE
    refresh_version(api, ctx)
    return ctx, payable, invoice


def test_settled_project_bubbles_up_to_closed_with_an_open_posture(api):
    """
    With its only leaf phase COMPLETE, no work in progress left and its only
    invoice PAID, the project closes itself, banks 22000.00 of receipts, reports
    the full phase fee as earned revenue and reports an OPEN posture.

    PRD §3.6: "A project moves from `ACTIVE` to `CLOSED` when every leaf phase of the project has reached `COMPLETE` (non-leaf phases, which can carry no charges, are not required to reach `COMPLETE` — their fee is represented by their children), the project's `unbilled_wip` is exactly 0.00, and every invoice of the project is in `PAID`, `WRITTEN_OFF` or `VOID`."
    PRD §3.6: "On success, `recognized_earned_value` is forced to the full `phase_fee` regardless of the project's `percent_complete_method`"
    PRD §2.11: "If the project's `status` is `CLOSED`, the posture is `OPEN`. A closed project reports `OPEN` because no gate can apply to it any more."

    Design: Corner/state_machines/closed_project_is_locked_against_every_further_write
    """
    ctx, payable, invoice = _closed_project_after_a_paid_consultant_billing(api)

    assert_invoice_money(
        read_invoice(api, invoice["id"]),
        consultant_billed=22000.00,
        gross_billed=22000.00,
        discount_amount=0.00,
        retainage_amount=1100.00,
        net_due=20900.00,
    )

    project = read_project(api, ctx.project_id)
    assert project["status"] == PROJECT_CLOSED
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=22000.00,
        written_off_gross=0.00,
        total_charge_value=22000.00,
        earned_revenue_to_date=200000.00,
    )
    assert_billing_posture(project, POSTURE_OPEN)


def test_closed_project_refuses_further_labour_and_expense_capture(api):
    """
    Charge capture is accepted only while a project is ACTIVE, so a closed
    project takes neither a timesheet line nor an expense.

    PRD §3.1: "Time entries, expenses, consultant subcontracts, consultant payables, invoices and write-off preparations are all accepted only while the project's `status` is `ACTIVE`; attempting any of them, or a phase assessment or a phase completion, while the project is still `SETUP` or already `CLOSED` is refused with `ERR_PROJECT_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/closed_project_is_locked_against_every_further_write
    """
    ctx, payable, invoice = _closed_project_after_a_paid_consultant_billing(api)

    validate_error(
        api.create_time_entry(
            time_entry_payload(
                ctx.project_id, ctx.phase_id, work_date="2026-05-11", hours=7.35
            ),
            ACCOUNTANT,
        ),
        ERR_PROJECT_NOT_ACTIVE,
        409,
    )
    validate_error(
        api.create_expense(
            expense_payload(
                ctx.project_id,
                ctx.phase_id,
                category=CATEGORY_PRINTING,
                amount=40.00,
                incurred_on="2026-05-11",
                receipt_attached=True,
            ),
            ACCOUNTANT,
        ),
        ERR_PROJECT_NOT_ACTIVE,
        409,
    )

    assert read_project(api, ctx.project_id)["status"] == PROJECT_CLOSED


def test_closed_project_refuses_a_new_multiplier_despite_a_current_version(api):
    """
    The multiplier exemption from the active-project rule covers SETUP only and
    names CLOSED explicitly, so a new multiplier is refused even when the
    supplied project version is the current one.

    PRD §3.1: "Creating a billing multiplier is the one deliberate exemption: because a project cannot be activated until an `ACTIVE` multiplier exists, the first multiplier is necessarily written while the project is still in `SETUP`, so for multiplier creation the only status that triggers `ERR_PROJECT_NOT_ACTIVE` is `CLOSED`."

    Design: Corner/state_machines/closed_project_is_locked_against_every_further_write
    """
    ctx, payable, invoice = _closed_project_after_a_paid_consultant_billing(api)

    validate_error(
        api.create_billing_multiplier(
            multiplier_payload(
                ctx.project_id,
                project_version(api, ctx.project_id),
                multiplier=3.2000,
                effective_from="2026-07-01",
            ),
            CONTROLLER,
        ),
        ERR_PROJECT_NOT_ACTIVE,
        409,
    )


def test_closed_project_cannot_be_reopened_for_business(api):
    """
    Closure is terminal: there is no path back to ACTIVE, and activation is not
    one of the operations the active-project rule governs, so re-activation is
    refused as an illegal transition and the project stays CLOSED.

    PRD §3.6: "`CLOSED` is terminal."
    PRD §3.1: "Activation — moving a project's `status` from `SETUP` to `ACTIVE`, which a `FirmAdmin`, a `Controller` or the owning `ProjectManager` may perform — requires that the project already be in `SETUP`, that at least one phase exist on it, and that at least one billing multiplier with `status` `ACTIVE` exist on it."

    Design: Corner/state_machines/closed_project_is_locked_against_every_further_write
    """
    ctx, payable, invoice = _closed_project_after_a_paid_consultant_billing(api)

    validate_error(
        api.activate_project(ctx.project_id, CONTROLLER),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    assert read_project(api, ctx.project_id)["status"] == PROJECT_CLOSED


def test_phase_completion_on_a_closed_project_is_refused_on_project_status(api):
    """
    Re-completing the phase is doubly illegal, and the owning project's status is
    checked before the target row's own transition legality, so the refusal is
    the project-status one.

    PRD §3.1: "Time entries, expenses, consultant subcontracts, consultant payables, invoices and write-off preparations are all accepted only while the project's `status` is `ACTIVE`; attempting any of them, or a phase assessment or a phase completion, while the project is still `SETUP` or already `CLOSED` is refused with `ERR_PROJECT_NOT_ACTIVE` (HTTP 409)."
    PRD §2.8: "11. Owning-project status — `ERR_PROJECT_NOT_ACTIVE`."
    PRD §2.8: "12. Declared-transition legality for the target row's current state — `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/closed_project_is_locked_against_every_further_write
    """
    ctx, payable, invoice = _closed_project_after_a_paid_consultant_billing(api)

    validate_error(
        api.complete_phase(ctx.phase_id, CONTROLLER),
        ERR_PROJECT_NOT_ACTIVE,
        409,
    )

    assert read_phase(api, ctx.phase_id)["status"] == PHASE_COMPLETE
