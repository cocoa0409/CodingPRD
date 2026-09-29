"""
Validation rules of the architecture-practice project accounting API.

The rules exercised here are the ones that refuse a request outright: client
allowability of a reimbursable expense, the fixed-fee earned-revenue ceiling on
a client invoice, the accounting period lock, the two backdating guards on a
successor billing multiplier, consultant backup completeness at submission to a
public agency, the work breakdown structure's fee rollup and code uniqueness,
and the open-charge conjunction that blocks phase completion.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_BACKUP_DOCUMENTATION_MISSING,
    ERR_BILLING_EXCEEDS_EARNED,
    ERR_EXPENSE_UNALLOWABLE,
    ERR_MULTIPLIER_BACKDATED,
    ERR_PERIOD_LOCKED,
    ERR_PHASE_HAS_OPEN_CHARGES,
    ERR_PHASE_NOT_LEAF,
    ERR_WBS_CODE_DUPLICATE,
    ERR_WBS_FEE_ROLLUP_MISMATCH,
)
from test_helpers.assertions import (
    assert_expense_decision,
    assert_invoice_money,
    assert_money,
    assert_null,
    assert_outranks,
    assert_payable_axes,
    assert_payable_markup,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_ratio,
    assert_swept_counts,
    assert_time_entry_frozen,
)
from test_helpers.constants import (
    ALLOWABILITY_DISALLOWED,
    ALLOWABILITY_ALLOWED,
    ALLOWABILITY_PENDING_REVIEW,
    CATEGORY_ENTERTAINMENT,
    CATEGORY_MEALS,
    CATEGORY_PRINTING,
    CLOCK_2026_06_01,
    CONTRACT_FIXED_FEE,
    DECISION_ALLOW,
    DECISION_DISALLOW,
    FISCAL_YEAR_2026,
    INVOICE_DRAFT,
    INVOICE_PENDING_CLIENT_REVIEW,
    INVOICE_VOID,
    METHOD_ASSESSED,
    MULTIPLIER_ACTIVE,
    MULTIPLIER_SUPERSEDED,
    PAYABLE_APPROVED,
    PAYABLE_BILLED_TO_CLIENT,
    PAYABLE_UNBILLED,
    PAYMENT_WITHHELD,
    PHASE_COMPLETE,
    PHASE_IN_PROGRESS,
    PROJECT_ACTIVE,
    REASON_ALLOWED_BY_REVIEW,
    REASON_DISALLOWED_BY_REVIEW,
    REASON_RECEIPT_MISSING,
    REASON_STATUTORY_UNALLOWABLE,
    TIME_ENTRY_APPROVED,
)
from test_helpers.factories import (
    assess_payload,
    consultant_invoice_payload,
    expense_payload,
    expense_review_payload,
    invoice_payload,
    lock_period_payload,
    lump_sum_phase_payload,
    multiplier_payload,
    time_entry_payload,
    void_payload,
)
from test_helpers.fixtures import (
    activate_project,
    add_approved_time_entry,
    add_executed_subcontract,
    add_expense,
    add_lump_sum_phase,
    add_percent_phase,
    approve_payable,
    approve_time_entry,
    build_active_project,
    build_certified_public_project,
    certify_year,
    create_private_client,
    create_project,
    enter_payable,
    prepare_invoice,
    publish_labor_rate,
    read_earned_value,
    read_expense,
    read_invoice,
    read_payable,
    read_phase,
    read_project,
    read_time_entry,
    refresh_version,
    set_clock,
    set_multiplier,
    submit_time_entry,
)
from test_helpers.test_users import ACCOUNTANT, CONTROLLER, PROJECT_MANAGER


# ─── Local composite builders ─────────────────────────────────────────


def _public_and_private_expense_projects(api):
    """
    Two ACTIVE projects billing two differently configured clients: a public
    agency (5% expense markup, nothing contractually excluded) and a private
    client that contractually refuses ENTERTAINMENT at a 10% markup. Both
    require a receipt at or above 75.00. Fiscal 2026 is certified so the public
    project is not held for a missing overhead rate.
    """
    public = build_certified_public_project(api, multiplier=2.5000)
    private = build_active_project(
        api,
        clock=None,
        publish_rate=False,
        project_overrides={"name": "Riverside Library"},
    )
    return public, private


def _project_with_percent_of_contract_root(api):
    """
    A SETUP project of 800000.00 whose single top-level phase is priced at half
    the contract, so its phase_fee is 400000.00 and its children must fit inside
    that figure.
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    publish_labor_rate(api)
    project = create_project(api, client["id"], contract_amount=800000.00)
    root = add_percent_phase(
        api,
        project["id"],
        wbs_code="02",
        fee_percent=0.5000,
        budget_labor_cost=120000.00,
    )
    return project, root


def _public_project_with_undocumented_payable(api):
    """
    A public-agency project carrying one APPROVED consultant payable whose
    backup_attached is false, ready to be swept onto an invoice.
    """
    set_clock(api, CLOCK_2026_06_01)
    certify_year(api, FISCAL_YEAR_2026)
    ctx = build_active_project(
        api,
        clock=None,
        public_agency=True,
        multiplier=2.5000,
        project_overrides={
            "name": "Transit Center Renovation",
            "contract_amount": 900000.00,
            "target_multiplier": 2.5000,
        },
        phase_overrides={
            "wbs_code": "01-SD",
            "lump_sum_fee": 225000.00,
            "budget_labor_cost": 50000.00,
            "consultant_budget": 100000.00,
        },
    )
    subcontract = add_executed_subcontract(
        api,
        ctx,
        committed_amount=20000.00,
        commitment_start="2026-01-01",
        commitment_end="2026-12-31",
    )
    payable = enter_payable(
        api,
        subcontract["id"],
        amount=20000.00,
        invoice_date="2026-05-20",
        backup_attached=False,
    )
    return ctx, approve_payable(api, payable["id"])


def _private_project_with_undocumented_payable(api):
    """The same charge shape billing a private client instead."""
    ctx = build_active_project(
        api, phase_overrides={"consultant_budget": 100000.00}
    )
    subcontract = add_executed_subcontract(
        api,
        ctx,
        committed_amount=20000.00,
        commitment_start="2026-01-01",
        commitment_end="2026-12-31",
    )
    payable = enter_payable(
        api,
        subcontract["id"],
        amount=20000.00,
        invoice_date="2026-05-20",
        backup_attached=False,
    )
    return ctx, approve_payable(api, payable["id"])


# ─── Client allowability of a reimbursable expense (PRD §3.4) ──────────


def test_undocumented_public_agency_meal_is_held_rather_than_disallowed(api):
    """
    A 120.00 meal on a public-agency project with no receipt is held for backup
    rather than being disallowed outright, because the missing-receipt clause is
    adjudicated ahead of the statutory exclusion.

    PRD §3.4: "If the `amount` is at or above the client's `receipt_required_above` and `receipt_attached` is false, the expense is held with `allowability_status` `PENDING_REVIEW` and `allowability_reason` `RECEIPT_MISSING`."
    PRD §3.4: "An undocumented expense is therefore held in `PENDING_REVIEW` even when its category would have been excluded outright, and the exclusion is applied later, at review."

    Design: Corner/validations/expense_exclusion_depends_on_the_client_configuration
    """
    public, _private = _public_and_private_expense_projects(api)

    expense = add_expense(
        api,
        public,
        amount=120.00,
        category=CATEGORY_MEALS,
        incurred_on="2026-05-15",
        receipt_attached=False,
    )

    assert_expense_decision(
        expense,
        ALLOWABILITY_PENDING_REVIEW,
        REASON_RECEIPT_MISSING,
        0.00,
    )
    assert_project_ledger(read_project(api, public.project_id), unbilled_wip=0.00)


def test_statutory_meal_exclusion_survives_an_allow_decision(api):
    """
    Once the meal reaches review, allowing it is refused: a public agency's
    statutory exclusion is not something the reviewer may override, so the row
    stays held with no billable value.

    PRD §3.4: "An `ALLOW` decision, however, is refused with `ERR_EXPENSE_UNALLOWABLE` (HTTP 422) when the expense would have been excluded had the receipt been present — that is, when the client has `is_public_agency` set to true and the `category` is `MEALS` or `ENTERTAINMENT`, or when the `category` appears in the client's `disallowed_categories`."

    Design: Corner/validations/expense_exclusion_depends_on_the_client_configuration
    """
    public, _private = _public_and_private_expense_projects(api)
    expense = add_expense(
        api,
        public,
        amount=120.00,
        category=CATEGORY_MEALS,
        incurred_on="2026-05-15",
        receipt_attached=False,
    )

    refused = api.review_expense(
        expense["id"],
        expense_review_payload(
            DECISION_ALLOW, "Client verbally agreed to reimburse the working lunch"
        ),
        CONTROLLER,
    )

    validate_error(refused, ERR_EXPENSE_UNALLOWABLE, 422)
    assert_expense_decision(
        read_expense(api, expense["id"]),
        ALLOWABILITY_PENDING_REVIEW,
        REASON_RECEIPT_MISSING,
        0.00,
    )


def test_disallowing_the_held_meal_is_always_available(api):
    """
    The reviewer's other option always lands: the held meal becomes DISALLOWED
    by review with no billable value and never enters work in progress.

    PRD §3.4: "A `DISALLOW` decision is always available and always lands `DISALLOWED` with `allowability_reason` `DISALLOWED_BY_REVIEW` and `billable_amount` 0.00."

    Design: Corner/validations/expense_exclusion_depends_on_the_client_configuration
    """
    public, _private = _public_and_private_expense_projects(api)
    expense = add_expense(
        api,
        public,
        amount=120.00,
        category=CATEGORY_MEALS,
        incurred_on="2026-05-15",
        receipt_attached=False,
    )

    reviewed = validate_success(
        api.review_expense(
            expense["id"],
            expense_review_payload(
                DECISION_DISALLOW,
                "Statutorily unallowable on a public agency contract",
            ),
            CONTROLLER,
        ),
        200,
    )

    assert_expense_decision(
        reviewed, ALLOWABILITY_DISALLOWED, REASON_DISALLOWED_BY_REVIEW, 0.00
    )
    assert_project_ledger(read_project(api, public.project_id), unbilled_wip=0.00)


def test_contractually_refused_category_survives_an_allow_decision(api):
    """
    The private client's own exclusion list does the same work on a different
    category: an undocumented entertainment charge is held for backup, and
    allowing it at review is refused because the client contractually refuses to
    reimburse that category at all.

    PRD §3.4: "Otherwise, if the `category` appears in the client's `disallowed_categories`, the expense is `DISALLOWED` with `allowability_reason` `CLIENT_EXCLUDED`."
    PRD §3.4: "Neither exclusion is overridable by review."

    Design: Corner/validations/expense_exclusion_depends_on_the_client_configuration
    """
    _public, private = _public_and_private_expense_projects(api)
    expense = add_expense(
        api,
        private,
        amount=200.00,
        category=CATEGORY_ENTERTAINMENT,
        incurred_on="2026-05-15",
        receipt_attached=False,
    )
    assert_expense_decision(
        expense, ALLOWABILITY_PENDING_REVIEW, REASON_RECEIPT_MISSING, 0.00
    )

    refused = api.review_expense(
        expense["id"],
        expense_review_payload(DECISION_ALLOW, "Receipt located"),
        CONTROLLER,
    )

    validate_error(refused, ERR_EXPENSE_UNALLOWABLE, 422)
    assert_project_ledger(read_project(api, private.project_id), unbilled_wip=0.00)


def test_printing_charge_held_for_backup_is_admitted_with_the_client_markup(api):
    """
    A printing charge is refused by neither client, so the same held-for-backup
    row may be allowed at review, taking the private client's 10% markup and
    entering work in progress in the same request.

    PRD §3.4: "An `ALLOW` decision on an otherwise allowable expense held only for the missing receipt sets `allowability_reason` to `ALLOWED_BY_REVIEW`, computes the marked-up `billable_amount` by the same formula as the capture path, and admits it to `unbilled_wip` in the same request."
    PRD §3.4: "On an `ALLOWED` expense it is the `amount` multiplied by one plus the client's `expense_markup_pct`, rounded half up to 2 decimal places; in every other case it stays 0.00."

    Design: Corner/validations/expense_exclusion_depends_on_the_client_configuration
    """
    _public, private = _public_and_private_expense_projects(api)
    expense = add_expense(
        api,
        private,
        amount=200.00,
        category=CATEGORY_PRINTING,
        incurred_on="2026-05-15",
        receipt_attached=False,
    )
    assert_expense_decision(
        expense, ALLOWABILITY_PENDING_REVIEW, REASON_RECEIPT_MISSING, 0.00
    )

    allowed = validate_success(
        api.review_expense(
            expense["id"],
            expense_review_payload(
                DECISION_ALLOW, "Receipt located in the printing log"
            ),
            CONTROLLER,
        ),
        200,
    )

    assert_expense_decision(
        allowed, ALLOWABILITY_ALLOWED, REASON_ALLOWED_BY_REVIEW, 220.00
    )
    assert_project_ledger(read_project(api, private.project_id), unbilled_wip=220.00)


def test_documented_meal_below_the_receipt_threshold_reaches_the_statutory_clause(api):
    """
    With the backup in hand and the amount below the receipt threshold, the
    held-for-backup clause no longer applies and the public agency's statutory
    exclusion is reached directly at capture.

    PRD §3.4: "Otherwise, if the client has `is_public_agency` set to true and the `category` is `MEALS` or `ENTERTAINMENT`, the expense is `DISALLOWED` with `allowability_reason` `STATUTORY_UNALLOWABLE`."
    PRD §3.4: "A `DISALLOWED` expense costs the firm rather than the client: its `billable_amount` stays 0.00, it never enters `unbilled_wip`, and only the expense's own `version` increments."

    Design: Corner/validations/expense_exclusion_depends_on_the_client_configuration
    """
    public, _private = _public_and_private_expense_projects(api)

    expense = add_expense(
        api,
        public,
        amount=60.00,
        category=CATEGORY_MEALS,
        incurred_on="2026-05-16",
        receipt_attached=True,
    )

    assert_expense_decision(
        expense, ALLOWABILITY_DISALLOWED, REASON_STATUTORY_UNALLOWABLE, 0.00
    )
    assert_project_ledger(read_project(api, public.project_id), unbilled_wip=0.00)


# ─── The fixed-fee earned-revenue ceiling (PRD §3.7) ──────────────────


def _fixed_fee_project_with_one_approved_line(api):
    """
    An ACTIVE fixed-fee project whose recognised revenue is driven by the
    manager's physical assessment, carrying the worked example of PRD §3.3:
    7.35 h at 62.50 with a multiplier of 3.0500 freezes 1401.11 of billable
    labour while nothing has yet been assessed as built.
    """
    ctx = build_active_project(
        api,
        project_overrides={
            "name": "Museum Wing Addition",
            "contract_type": CONTRACT_FIXED_FEE,
            "percent_complete_method": METHOD_ASSESSED,
        },
    )
    entry = add_approved_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    return ctx, entry


def test_fixed_fee_invoice_is_refused_while_nothing_has_been_earned(api):
    """
    On a fixed-fee project with no earned revenue the headroom is 0.00, so an
    invoice sweeping 1401.11 of approved labour is refused outright.

    PRD §3.7: "The headroom is the project's `earned_revenue_to_date` less `already_billed`, rounded half up to 2 decimal places. If the new invoice's `gross_billed` is strictly greater than that headroom, the preparation is refused with `ERR_BILLING_EXCEEDS_EARNED` (HTTP 422); a `gross_billed` exactly equal to the headroom is permitted."

    Design: Corner/validations/fixed_fee_headroom_refuses_then_admits_the_same_invoice
    """
    ctx, _entry = _fixed_fee_project_with_one_approved_line(api)
    project = read_project(api, ctx.project_id)
    assert_project_ledger(project, unbilled_wip=1401.11, earned_revenue_to_date=0.00)

    refused = api.create_invoice(
        invoice_payload(ctx.project_id, project["version"], period_end="2026-05-31"),
        ACCOUNTANT,
    )

    validate_error(refused, ERR_BILLING_EXCEEDS_EARNED, 422)


def test_refused_fixed_fee_preparation_leaves_no_invoice_and_no_swept_charge(api):
    """
    The refusal is total: no draft invoice survives it and the approved labour
    line is still unbilled work in progress afterwards.

    PRD §3.7: "The sweep's side effects are that every swept time entry moves to `BILLED` with its `billed_invoice_id` set to this invoice, every swept expense moves to `BILLED` with its `billed_invoice_id` set, every swept payable moves to `BILLED_TO_CLIENT` with its `client_invoice_id` set, the project's `unbilled_wip` falls to whatever residual remains and its `billed_open` rises by `gross_billed`, and the project's `version` increments by 1."

    Design: Corner/validations/fixed_fee_headroom_refuses_then_admits_the_same_invoice
    """
    ctx, entry = _fixed_fee_project_with_one_approved_line(api)
    version = refresh_version(api, ctx)

    refused = api.create_invoice(
        invoice_payload(ctx.project_id, version, period_end="2026-05-31"), ACCOUNTANT
    )
    validate_error(refused, ERR_BILLING_EXCEEDS_EARNED, 422)

    rows, meta = validate_paginated(
        api.list_invoices(CONTROLLER, {"project_id": ctx.project_id})
    )
    assert meta["total_count"] == 0, "a refused preparation must create no invoice"
    assert rows == []
    line = read_time_entry(api, entry["id"])
    assert line["status"] == TIME_ENTRY_APPROVED
    assert_null(line["billed_invoice_id"], "time_entry.billed_invoice_id")
    assert_project_ledger(
        read_project(api, ctx.project_id), unbilled_wip=1401.11, billed_open=0.00
    )


def test_assessing_the_phase_opens_headroom_for_the_identical_invoice(api):
    """
    Nothing about the charge population changes: recording a quarter of the
    200000.00 phase as built lifts recognised revenue to 50000.00, and the same
    invoice request then bills 1401.11 net of 5% retainage.

    PRD §3.6: "`assessed_earned_value` is the `phase_fee` multiplied by `assessed_percent_complete`, rounded half up to 2 decimal places."
    PRD §3.7: "Third, `retainage_amount` is keyed on the **post-discount** base and never on `gross_billed` itself: it is `gross_billed` less `discount_amount`, multiplied by the client's `retainage_pct`, rounded half up to 2 decimal places. Fourth, `net_due` is `gross_billed` less `discount_amount` less `retainage_amount`."

    Design: Corner/validations/fixed_fee_headroom_refuses_then_admits_the_same_invoice
    """
    ctx, _entry = _fixed_fee_project_with_one_approved_line(api)
    version = refresh_version(api, ctx)
    validate_error(
        api.create_invoice(
            invoice_payload(ctx.project_id, version, period_end="2026-05-31"),
            ACCOUNTANT,
        ),
        ERR_BILLING_EXCEEDS_EARNED,
        422,
    )

    get_success_data(
        api.assess_phase(ctx.phase_id, assess_payload(0.2500), PROJECT_MANAGER)
    )
    assert_project_ledger(
        read_project(api, ctx.project_id), earned_revenue_to_date=50000.00
    )

    invoice = validate_success(
        api.create_invoice(
            invoice_payload(
                ctx.project_id, refresh_version(api, ctx), period_end="2026-05-31"
            ),
            ACCOUNTANT,
        ),
        201,
    )

    assert_invoice_money(
        invoice,
        labor_billed=1401.11,
        gross_billed=1401.11,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=70.06,
        net_due=1331.05,
    )
    assert_project_ledger(
        read_project(api, ctx.project_id), unbilled_wip=0.00, billed_open=1401.11
    )


def test_time_and_materials_project_bills_ahead_of_earned_revenue(api):
    """
    The ceiling is scoped by contract type: the identical unassessed charge set
    on a time-and-materials project bills immediately even though recognised
    revenue is still 0.00.

    PRD §3.7: "One fiscal ceiling then applies, and it applies only on a project whose `contract_type` is `FIXED_FEE`. Projects on `TIME_AND_MATERIALS` or `COST_PLUS_FIXED_FEE` are not subject to it."

    Design: Corner/validations/fixed_fee_headroom_refuses_then_admits_the_same_invoice
    """
    ctx = build_active_project(
        api,
        project_overrides={
            "name": "Harbor Master Plan",
            "percent_complete_method": METHOD_ASSESSED,
        },
    )
    add_approved_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=1401.11,
        earned_revenue_to_date=0.00,
    )

    invoice = validate_success(
        api.create_invoice(
            invoice_payload(
                ctx.project_id, refresh_version(api, ctx), period_end="2026-05-31"
            ),
            ACCOUNTANT,
        ),
        201,
    )

    assert_invoice_money(invoice, gross_billed=1401.11, net_due=1331.05)


# ─── The accounting period lock (PRD §2.6) ────────────────────────────


def _project_with_open_consultant_commitment(api):
    """
    An ACTIVE time-and-materials project with a leaf phase carrying 100000.00 of
    consultant capacity and one EXECUTED subcontract of 20000.00 to draw against.
    """
    ctx = build_active_project(
        api, phase_overrides={"consultant_budget": 100000.00}
    )
    subcontract = add_executed_subcontract(
        api,
        ctx,
        committed_amount=20000.00,
        commitment_start="2026-01-01",
        commitment_end="2026-12-31",
    )
    return ctx, subcontract


def test_locking_a_period_records_the_date_and_counts_as_a_mutation(api):
    """
    Closing the period through 2026-04-30 records the date on the project and
    counts as a mutation of it.

    PRD §3.1: "Locking a period increments the project's `version` by 1 and makes `ERR_PERIOD_LOCKED` reachable for every charge dated inside the closed window."

    Design: Corner/validations/period_lock_closes_the_creation_paths_and_only_those
    """
    ctx, _subcontract = _project_with_open_consultant_commitment(api)
    before = read_project(api, ctx.project_id)
    assert_null(before["locked_through_date"], "project.locked_through_date")

    locked = validate_success(
        api.lock_period(
            ctx.project_id, lock_period_payload("2026-04-30"), CONTROLLER
        ),
        200,
    )

    assert locked["locked_through_date"] == "2026-04-30"
    assert locked["version"] == before["version"] + 1, (
        "locking a period must increment the project's version by exactly 1"
    )


def test_all_three_charge_kinds_are_refused_inside_the_closed_window(api):
    """
    One lock date governs three different service-date fields on three different
    charge kinds, and the comparison is inclusive of the lock date itself: a
    timesheet line worked on 2026-04-30 is refused just as an expense incurred
    on 2026-04-15 and a consultant payable dated 2026-04-10 are.

    PRD §2.6: "Once set, a charge whose service date falls **on or before** `locked_through_date` may neither be created nor approved: the service date is `work_date` for a time entry, `incurred_on` for an expense and `invoice_date` for a consultant payable."

    Design: Corner/validations/period_lock_closes_the_creation_paths_and_only_those
    """
    ctx, subcontract = _project_with_open_consultant_commitment(api)
    get_success_data(
        api.lock_period(ctx.project_id, lock_period_payload("2026-04-30"), CONTROLLER)
    )

    on_the_lock_date = api.create_time_entry(
        time_entry_payload(
            ctx.project_id, ctx.phase_id, work_date="2026-04-30", hours=4.00
        ),
        ACCOUNTANT,
    )
    inside_the_window = api.create_expense(
        expense_payload(
            ctx.project_id,
            ctx.phase_id,
            category=CATEGORY_PRINTING,
            amount=40.00,
            incurred_on="2026-04-15",
            receipt_attached=True,
        ),
        ACCOUNTANT,
    )
    consultant_payable = api.create_consultant_invoice(
        consultant_invoice_payload(
            subcontract["id"],
            amount=5000.00,
            invoice_date="2026-04-10",
            backup_attached=True,
        ),
        ACCOUNTANT,
    )

    validate_error(on_the_lock_date, ERR_PERIOD_LOCKED, 422)
    validate_error(inside_the_window, ERR_PERIOD_LOCKED, 422)
    validate_error(consultant_payable, ERR_PERIOD_LOCKED, 422)
    assert_project_ledger(read_project(api, ctx.project_id), unbilled_wip=0.00)


def test_charges_one_day_after_the_lock_date_are_accepted_and_priced(api):
    """
    The lock is a date boundary rather than a freeze on the project: the same
    three charges dated 2026-05-01 are all accepted, the timesheet line approves
    and freezes 250.00 of raw cost at a multiplier of 3.0500, and only the
    approved labour and the allowable expense reach work in progress.

    PRD §2.6: "The rejection is `ERR_PERIOD_LOCKED` (HTTP 422), and it is reachable on time entry creation, expense creation, consultant payable creation and time entry approval."
    PRD §3.3: "Third, `billable_amount` is the already-rounded `raw_cost` multiplied by `applied_multiplier`, rounded half up to 2 decimal places."

    Design: Corner/validations/period_lock_closes_the_creation_paths_and_only_those
    """
    ctx, subcontract = _project_with_open_consultant_commitment(api)
    get_success_data(
        api.lock_period(ctx.project_id, lock_period_payload("2026-04-30"), CONTROLLER)
    )

    line = validate_success(
        api.create_time_entry(
            time_entry_payload(
                ctx.project_id, ctx.phase_id, work_date="2026-05-01", hours=4.00
            ),
            ACCOUNTANT,
        ),
        201,
    )
    expense = validate_success(
        api.create_expense(
            expense_payload(
                ctx.project_id,
                ctx.phase_id,
                category=CATEGORY_PRINTING,
                amount=40.00,
                incurred_on="2026-05-01",
                receipt_attached=True,
            ),
            ACCOUNTANT,
        ),
        201,
    )
    payable = validate_success(
        api.create_consultant_invoice(
            consultant_invoice_payload(
                subcontract["id"],
                amount=5000.00,
                invoice_date="2026-05-01",
                backup_attached=True,
            ),
            ACCOUNTANT,
        ),
        201,
    )

    approved = approve_time_entry(api, line["id"])
    assert_time_entry_frozen(approved, 250.00, 3.0500, 762.50)
    assert_money(expense["billable_amount"], 44.00, "expense.billable_amount")
    assert_payable_axes(payable, "RECEIVED", PAYMENT_WITHHELD, PAYABLE_UNBILLED)
    assert_project_ledger(read_project(api, ctx.project_id), unbilled_wip=806.50)


# ─── The two backdating guards on a successor multiplier (PRD §3.2) ────


def _project_whose_may_labour_is_already_billed(api):
    """
    An ACTIVE time-and-materials project whose incumbent multiplier of 3.0500
    runs from 2026-01-01, carrying one approved 7.35 hour line worked on
    2026-05-11 that a DRAFT invoice has already swept up.
    """
    ctx = build_active_project(api)
    entry = add_approved_time_entry(api, ctx, hours=7.35, work_date="2026-05-11")
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    return ctx, entry, invoice


def test_successor_multiplier_sharing_the_incumbent_start_date_is_refused(api):
    """
    A successor that starts on the very day the incumbent started is refused
    rather than treated as a replacement of it: the comparison is strictly
    later, not later-or-equal.

    PRD §3.2: "The successor's `effective_from` must be strictly later than the incumbent's `effective_from`, and it must not fall earlier than the `work_date` of any charge that has already been billed; either violation is refused with `ERR_MULTIPLIER_BACKDATED` (HTTP 409)."

    Design: Corner/validations/multiplier_effective_dates_may_not_move_backwards
    """
    ctx, _entry, _invoice = _project_whose_may_labour_is_already_billed(api)

    refused = api.create_billing_multiplier(
        multiplier_payload(
            ctx.project_id,
            refresh_version(api, ctx),
            multiplier=3.2000,
            effective_from="2026-01-01",
        ),
        CONTROLLER,
    )

    validate_error(refused, ERR_MULTIPLIER_BACKDATED, 409)
    incumbent = validate_success(
        api.get_billing_multiplier(ctx.multiplier_id, CONTROLLER), 200
    )
    assert incumbent["status"] == MULTIPLIER_ACTIVE
    assert_null(incumbent["effective_to"], "incumbent.effective_to")


def test_successor_multiplier_dated_before_the_incumbent_is_refused(api):
    """
    A successor dated 2025-12-01, well before the incumbent's own start, is
    refused and leaves the project with a single untouched multiplier.

    PRD §3.2: "The successor's `effective_from` must be strictly later than the incumbent's `effective_from`, and it must not fall earlier than the `work_date` of any charge that has already been billed; either violation is refused with `ERR_MULTIPLIER_BACKDATED` (HTTP 409)."

    Design: Corner/validations/multiplier_effective_dates_may_not_move_backwards
    """
    ctx, _entry, _invoice = _project_whose_may_labour_is_already_billed(api)

    refused = api.create_billing_multiplier(
        multiplier_payload(
            ctx.project_id,
            refresh_version(api, ctx),
            multiplier=3.2000,
            effective_from="2025-12-01",
        ),
        CONTROLLER,
    )

    validate_error(refused, ERR_MULTIPLIER_BACKDATED, 409)
    rows, meta = validate_paginated(
        api.list_billing_multipliers(CONTROLLER, {"project_id": ctx.project_id})
    )
    assert len(rows) == 1, (
        "a refused successor must not leave a multiplier row behind"
    )
    assert meta["total_count"] == 1, (
        "a refused successor must not leave a multiplier row behind"
    )
    assert rows[0]["id"] == ctx.multiplier_id


def test_successor_may_not_reach_back_over_an_already_billed_work_date(api):
    """
    A successor dated 2026-05-01 clears the first guard — it is strictly later
    than the incumbent's 2026-01-01 — yet is still refused, because the 7.35
    hour line worked on 2026-05-11 has already been billed and repricing its
    work date is exactly what the second guard forbids.

    PRD §3.2: "The successor's `effective_from` must be strictly later than the incumbent's `effective_from`, and it must not fall earlier than the `work_date` of any charge that has already been billed; either violation is refused with `ERR_MULTIPLIER_BACKDATED` (HTTP 409)."

    Design: Corner/validations/multiplier_effective_dates_may_not_move_backwards
    """
    ctx, entry, _invoice = _project_whose_may_labour_is_already_billed(api)

    refused = api.create_billing_multiplier(
        multiplier_payload(
            ctx.project_id,
            refresh_version(api, ctx),
            multiplier=3.2000,
            effective_from="2026-05-01",
        ),
        CONTROLLER,
    )

    validate_error(refused, ERR_MULTIPLIER_BACKDATED, 409)
    assert_time_entry_frozen(read_time_entry(api, entry["id"]), 459.38, 3.0500, 1401.11)


def test_successor_after_the_billed_work_date_truncates_the_incumbent_window(api):
    """
    A successor dated 2026-06-01 clears both guards and is accepted: it becomes
    the ACTIVE open-ended multiplier, the incumbent is truncated to end on the
    successor's start date and marked SUPERSEDED without any overlap complaint,
    both rows survive in the project's history, and the labour charge frozen
    under the incumbent keeps its 3.0500 factor and its 1401.11 of billable
    value.

    PRD §3.2: "When a successor multiplier is created on a project that already has an `ACTIVE` one, the incumbent's `effective_to` is set to the successor's `effective_from` — a half-open truncation, raising no overlap error at all — and the incumbent's `status` becomes `SUPERSEDED`, incrementing that multiplier's `version` by 1."

    Design: Corner/validations/multiplier_effective_dates_may_not_move_backwards
    """
    ctx, entry, _invoice = _project_whose_may_labour_is_already_billed(api)
    incumbent_before = validate_success(
        api.get_billing_multiplier(ctx.multiplier_id, CONTROLLER), 200
    )

    successor = validate_success(
        api.create_billing_multiplier(
            multiplier_payload(
                ctx.project_id,
                refresh_version(api, ctx),
                multiplier=3.2000,
                effective_from="2026-06-01",
            ),
            CONTROLLER,
        ),
        201,
    )

    assert successor["status"] == MULTIPLIER_ACTIVE
    assert_ratio(successor["multiplier"], 3.2000, "successor.multiplier")
    assert successor["effective_from"] == "2026-06-01"
    assert_null(successor["effective_to"], "successor.effective_to")

    incumbent = validate_success(
        api.get_billing_multiplier(ctx.multiplier_id, CONTROLLER), 200
    )
    assert incumbent["status"] == MULTIPLIER_SUPERSEDED
    assert incumbent["effective_to"] == "2026-06-01", (
        "the incumbent must be truncated to the successor's start date"
    )
    assert incumbent["version"] == incumbent_before["version"] + 1

    rows, meta = validate_paginated(
        api.list_billing_multipliers(CONTROLLER, {"project_id": ctx.project_id})
    )
    assert meta["total_count"] == 2, (
        "a superseded multiplier stays in the project's multiplier history"
    )
    assert {row["id"] for row in rows} == {ctx.multiplier_id, successor["id"]}, (
        "a superseded multiplier stays in the project's multiplier history"
    )
    assert_time_entry_frozen(read_time_entry(api, entry["id"]), 459.38, 3.0500, 1401.11)


# ─── Consultant backup completeness at submission (PRD §3.7) ───────────


def test_public_invoice_prepares_with_the_missing_backup_merely_counted(api):
    """
    Preparation does not police consultant paperwork. The undocumented 20000.00
    payable is marked up at the 0.0500 public-agency cap to 21000.00, sweeps
    onto a DRAFT invoice, and the absent documentation shows up only as a count
    of one.

    PRD §3.7: "`swept_labor_count`, `swept_expense_count` and `swept_consultant_count` are the numbers of time entries, expenses and consultant payables attached to it, and `backup_missing_count` is the count of swept consultant payables whose `backup_attached` is false."
    PRD §3.7: "Backup completeness is enforced here and deliberately not at preparation, giving the accountant a window in which to chase the paperwork."

    Design: Corner/validations/public_backup_completeness_is_enforced_only_at_submission
    """
    ctx, payable = _public_project_with_undocumented_payable(api)
    assert_payable_markup(payable, 0.0500, 1000.00, 21000.00)

    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")

    assert invoice["status"] == INVOICE_DRAFT
    assert_invoice_money(
        invoice,
        consultant_billed=21000.00,
        gross_billed=21000.00,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=1050.00,
        net_due=19950.00,
    )
    assert_swept_counts(
        invoice,
        swept_labor_count=0,
        swept_expense_count=0,
        swept_consultant_count=1,
        backup_missing_count=1,
    )
    assert_payable_axes(
        read_payable(api, payable["id"]),
        PAYABLE_APPROVED,
        PAYMENT_WITHHELD,
        PAYABLE_BILLED_TO_CLIENT,
    )


def test_public_submission_is_refused_while_consultant_backup_is_missing(api):
    """
    The public agency will not take a bill that passes through an undocumented
    subconsultant charge, so submission is refused and the invoice stays in
    DRAFT where the accountant can still chase the paperwork.

    PRD §3.7: "A public-agency submission with any missing backup is refused with `ERR_BACKUP_DOCUMENTATION_MISSING` (HTTP 409)."

    Design: Corner/validations/public_backup_completeness_is_enforced_only_at_submission
    """
    ctx, _payable = _public_project_with_undocumented_payable(api)
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")

    refused = api.submit_invoice(invoice["id"], CONTROLLER)

    validate_error(refused, ERR_BACKUP_DOCUMENTATION_MISSING, 409)
    still_draft = read_invoice(api, invoice["id"])
    assert still_draft["status"] == INVOICE_DRAFT
    assert_null(still_draft["submitted_by_user_id"], "invoice.submitted_by_user_id")
    assert_swept_counts(still_draft, backup_missing_count=1)


def test_private_client_submission_ignores_the_identical_missing_backup(api):
    """
    The very same undocumented 20000.00 payable billed to a private client is
    marked up at the full 0.1000 to 22000.00 and its invoice submits without
    complaint: the documentation gate belongs to the public agency alone.

    PRD §3.7: "The invoice must be in `DRAFT`, its `gross_billed` must be strictly greater than 0.00, and — for a client whose `is_public_agency` is true — its `backup_missing_count` must be 0, because a public agency will not accept a bill that passes through a subconsultant's charge with no supporting documentation."

    Design: Corner/validations/public_backup_completeness_is_enforced_only_at_submission
    """
    ctx, payable = _private_project_with_undocumented_payable(api)
    assert_payable_markup(payable, 0.1000, 2000.00, 22000.00)
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    assert_invoice_money(
        invoice,
        gross_billed=22000.00,
        retainage_amount=1100.00,
        net_due=20900.00,
    )
    assert_swept_counts(invoice, swept_consultant_count=1, backup_missing_count=1)

    submitted = validate_success(api.submit_invoice(invoice["id"], CONTROLLER), 200)

    assert submitted["status"] == INVOICE_PENDING_CLIENT_REVIEW


def test_voiding_the_refused_public_invoice_returns_the_payable_to_unbilled(api):
    """
    Voiding the bill the agency would not accept unwinds the sweep exactly: the
    payable goes back to UNBILLED with no invoice link and the project's 21000.00
    of marked-up consultant value returns to work in progress.

    PRD §3.7: "Every attached time entry moves `BILLED → APPROVED`, every attached expense moves `BILLED → UNBILLED`, and every attached consultant payable moves `BILLED_TO_CLIENT → UNBILLED`, each with its invoice link cleared."

    Design: Corner/validations/public_backup_completeness_is_enforced_only_at_submission
    """
    ctx, payable = _public_project_with_undocumented_payable(api)
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    validate_error(
        api.submit_invoice(invoice["id"], CONTROLLER),
        ERR_BACKUP_DOCUMENTATION_MISSING,
        409,
    )

    voided = validate_success(
        api.void_invoice(
            invoice["id"],
            void_payload("Rebuild once the consultant backup is on file"),
            CONTROLLER,
        ),
        200,
    )

    assert voided["status"] == INVOICE_VOID
    restored = read_payable(api, payable["id"])
    assert_payable_axes(
        restored, PAYABLE_APPROVED, PAYMENT_WITHHELD, PAYABLE_UNBILLED
    )
    assert_null(restored["client_invoice_id"], "payable.client_invoice_id")
    assert_project_ledger(
        read_project(api, ctx.project_id), unbilled_wip=21000.00, billed_open=0.00
    )


# ─── Fee rollup and code uniqueness across the tree (PRD §3.1) ─────────


def test_percent_of_contract_root_prices_itself_from_the_contract_amount(api):
    """
    A top-level phase priced at half of an 800000.00 contract carries a
    phase_fee of 400000.00, sits at depth 0 and is a leaf until it gains a
    child — and that fee is the ceiling its children will have to fit inside.

    PRD §3.1: "When `fee_basis` is `PERCENT_OF_CONTRACT`, a `fee_percent` between 0.0001 and 1.0000 at 4 decimal places is required and `lump_sum_fee` must be omitted; the resulting `phase_fee` is the project's `contract_amount` multiplied by `fee_percent`, rounded half up to 2 decimal places."

    Design: Corner/validations/sibling_fees_may_not_exceed_the_parent_and_codes_are_unique
    """
    _project, root = _project_with_percent_of_contract_root(api)

    assert_money(root["phase_fee"], 400000.00, "root.phase_fee")
    assert root["depth"] == 0
    assert root["is_leaf"] is True


def test_sibling_fees_may_not_collectively_exceed_the_parent_fee(api):
    """
    Each child fee is individually well inside the parent's 400000.00: it is the
    collective 450000.00 that breaches it, so the second child is the one
    refused even though 200000.00 on its own would have been unremarkable.

    PRD §3.1: "A further structural rule protects fee arithmetic across the tree: a phase may not be created such that the sum of the `phase_fee` values of a parent's children would exceed that parent's own `phase_fee`."

    Design: Corner/validations/sibling_fees_may_not_exceed_the_parent_and_codes_are_unique
    """
    project, root = _project_with_percent_of_contract_root(api)

    first = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="02-DD",
        lump_sum_fee=250000.00,
        budget_labor_cost=60000.00,
        parent_phase_id=root["id"],
    )
    refused = api.create_phase(
        lump_sum_phase_payload(
            project["id"],
            wbs_code="02-CD",
            lump_sum_fee=200000.00,
            budget_labor_cost=40000.00,
            parent_phase_id=root["id"],
        ),
        CONTROLLER,
    )

    assert first["depth"] == 1
    assert_money(first["phase_fee"], 250000.00, "first_child.phase_fee")
    validate_error(refused, ERR_WBS_FEE_ROLLUP_MISMATCH, 422)


def test_sibling_fees_that_land_exactly_on_the_parent_fee_are_accepted(api):
    """
    The rollup comparison bites only above the parent's fee: a corrected second
    child of 150000.00 takes the sibling total to exactly the parent's
    400000.00 and is accepted.

    PRD §3.1: "A further structural rule protects fee arithmetic across the tree: a phase may not be created such that the sum of the `phase_fee` values of a parent's children would exceed that parent's own `phase_fee`."

    Design: Corner/validations/sibling_fees_may_not_exceed_the_parent_and_codes_are_unique
    """
    project, root = _project_with_percent_of_contract_root(api)
    add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="02-DD",
        lump_sum_fee=250000.00,
        budget_labor_cost=60000.00,
        parent_phase_id=root["id"],
    )

    exact = validate_success(
        api.create_phase(
            lump_sum_phase_payload(
                project["id"],
                wbs_code="02-CD",
                lump_sum_fee=150000.00,
                budget_labor_cost=40000.00,
                parent_phase_id=root["id"],
            ),
            CONTROLLER,
        ),
        201,
    )

    assert_money(exact["phase_fee"], 150000.00, "second_child.phase_fee")
    assert exact["is_leaf"] is True
    assert_money(
        read_phase(api, root["id"])["phase_fee"], 400000.00, "root.phase_fee"
    )


def test_a_repeated_wbs_code_is_refused_before_the_fee_rollup_is_examined(api):
    """
    A fourth node repeating the 02-DD code carries two faults at once: the code
    is already taken and its 10000.00 fee would push the sibling total past the
    parent's 400000.00. The duplicate code is the fault reported, because the
    work breakdown structure's code uniqueness is examined ahead of its fee
    arithmetic.

    PRD §3.1: "The `wbs_code` must be unique within the project; a collision is refused with `ERR_WBS_CODE_DUPLICATE` (HTTP 409)."
    PRD §2.8: "15. Structural constraints on the work breakdown structure and on charge placement — `ERR_PHASE_NOT_LEAF`, then `ERR_WBS_CYCLE`, then `ERR_WBS_CODE_DUPLICATE`, then `ERR_NO_EFFECTIVE_LABOR_RATE`, then `ERR_NO_EFFECTIVE_MULTIPLIER`, then `ERR_PAY_WHEN_PAID_NOT_SATISFIED`, then `ERR_PHASE_HAS_OPEN_CHARGES`, then `ERR_CERTIFICATION_YEAR_DUPLICATE`, then `ERR_REVISION_LIMIT_EXCEEDED`, then `ERR_BACKUP_DOCUMENTATION_MISSING`, then `ERR_WBS_FEE_ROLLUP_MISMATCH`, then `ERR_PROJECT_UNDER_BILLING_REVIEW`."

    Design: Corner/validations/sibling_fees_may_not_exceed_the_parent_and_codes_are_unique
    """
    project, root = _project_with_percent_of_contract_root(api)
    for code, fee, budget in (("02-DD", 250000.00, 60000.00), ("02-CD", 150000.00, 40000.00)):
        add_lump_sum_phase(
            api,
            project["id"],
            wbs_code=code,
            lump_sum_fee=fee,
            budget_labor_cost=budget,
            parent_phase_id=root["id"],
        )

    refused = api.create_phase(
        lump_sum_phase_payload(
            project["id"],
            wbs_code="02-DD",
            lump_sum_fee=10000.00,
            budget_labor_cost=5000.00,
            parent_phase_id=root["id"],
        ),
        CONTROLLER,
    )

    assert_outranks(ERR_WBS_CODE_DUPLICATE, ERR_WBS_FEE_ROLLUP_MISMATCH)
    validate_error(refused, ERR_WBS_CODE_DUPLICATE, 409)


def test_wbs_codes_are_unique_across_the_project_and_not_within_a_parent(api):
    """
    The 02-DD code is taken by a child of the root, and a brand-new top-level
    node claiming the same code is refused even though it has no parent in
    common with the incumbent: uniqueness is scoped to the whole project.

    PRD §3.1: "The `wbs_code` must be unique within the project; a collision is refused with `ERR_WBS_CODE_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/sibling_fees_may_not_exceed_the_parent_and_codes_are_unique
    """
    project, root = _project_with_percent_of_contract_root(api)
    add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="02-DD",
        lump_sum_fee=250000.00,
        budget_labor_cost=60000.00,
        parent_phase_id=root["id"],
    )

    elsewhere_in_the_tree = api.create_phase(
        lump_sum_phase_payload(
            project["id"],
            wbs_code="02-DD",
            lump_sum_fee=50000.00,
            budget_labor_cost=10000.00,
        ),
        CONTROLLER,
    )

    validate_error(elsewhere_in_the_tree, ERR_WBS_CODE_DUPLICATE, 409)


def _activated_wbs_tree(api, percent_complete_method=None):
    """
    An ACTIVE project of 800000.00 whose 400000.00 top-level phase carries two
    lump-sum children of 250000.00 and 150000.00, so the top-level node has
    stopped being a leaf.
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    publish_labor_rate(api)
    overrides = {"contract_amount": 800000.00}
    if percent_complete_method is not None:
        overrides["percent_complete_method"] = percent_complete_method
    project = create_project(api, client["id"], **overrides)
    root = add_percent_phase(
        api,
        project["id"],
        wbs_code="02",
        fee_percent=0.5000,
        budget_labor_cost=120000.00,
    )
    children = [
        add_lump_sum_phase(
            api,
            project["id"],
            wbs_code=code,
            lump_sum_fee=fee,
            budget_labor_cost=budget,
            parent_phase_id=root["id"],
        )
        for code, fee, budget in (
            ("02-DD", 250000.00, 60000.00),
            ("02-CD", 150000.00, 40000.00),
        )
    ]
    set_multiplier(api, project["id"])
    activate_project(api, project["id"])
    return project, root, children


def test_a_parent_phase_stops_being_chargeable_once_it_gains_a_child(api):
    """
    Gaining children turns the 400000.00 top-level phase into a non-leaf, and
    from that moment a timesheet line may no longer be booked to it while the
    identical line against its child is accepted.

    PRD §3.1: "Charges — time entries, expenses and consultant subcontracts — may be booked only to a phase whose `is_leaf` is true; booking one to a phase that has child phases is refused with `ERR_PHASE_NOT_LEAF` (HTTP 422)."
    PRD §3.1: "The corollary bites during setup: adding a child under a phase that was previously a leaf makes that parent non-leaf, and it is no longer chargeable from that moment on."

    Design: Corner/validations/sibling_fees_may_not_exceed_the_parent_and_codes_are_unique
    """
    project, root, children = _activated_wbs_tree(api)

    to_the_parent = api.create_time_entry(
        time_entry_payload(
            project["id"], root["id"], work_date="2026-05-11", hours=4.00
        ),
        ACCOUNTANT,
    )
    to_the_child = api.create_time_entry(
        time_entry_payload(
            project["id"], children[0]["id"], work_date="2026-05-11", hours=4.00
        ),
        ACCOUNTANT,
    )

    validate_error(to_the_parent, ERR_PHASE_NOT_LEAF, 422)
    validate_success(to_the_child, 201)
    assert read_phase(api, root["id"])["is_leaf"] is False
    assert read_phase(api, children[0]["id"])["is_leaf"] is True
    assert read_phase(api, children[1]["id"])["is_leaf"] is True


def test_recognized_revenue_is_collected_from_the_leaves_alone(api):
    """
    Assessing the 400000.00 top-level phase at a quarter built recognises
    100000.00 on that phase, yet the project's earned revenue counts only the
    25000.00 recognised on its 250000.00 child: the parent's fee is already
    represented by its children and must not be counted a second time.

    PRD §2.10: "`earned_revenue_to_date` is the sum of `recognized_earned_value` over the project's **leaf** phases only; a non-leaf phase contributes nothing, because its fee is already represented by its children."

    Design: Corner/validations/sibling_fees_may_not_exceed_the_parent_and_codes_are_unique
    """
    project, root, children = _activated_wbs_tree(
        api, percent_complete_method=METHOD_ASSESSED
    )

    get_success_data(api.assess_phase(root["id"], assess_payload(0.2500), CONTROLLER))
    get_success_data(
        api.assess_phase(children[0]["id"], assess_payload(0.1000), CONTROLLER)
    )

    assert_phase_earned_value(
        read_earned_value(api, root["id"]),
        assessed_percent_complete=0.2500,
        assessed_earned_value=100000.00,
        recognized_earned_value=100000.00,
    )
    assert_phase_earned_value(
        read_earned_value(api, children[0]["id"]),
        assessed_earned_value=25000.00,
        recognized_earned_value=25000.00,
    )
    assert_phase_earned_value(
        read_earned_value(api, children[1]["id"]), recognized_earned_value=0.00
    )
    assert_project_ledger(
        read_project(api, project["id"]),
        unbilled_wip=0.00,
        earned_revenue_to_date=25000.00,
    )


# ─── Open charges blocking phase completion (PRD §3.6) ─────────────────


def _phase_in_progress_with_two_open_charges(api):
    """
    An ACTIVE time-and-materials project whose 200000.00 phase is IN_PROGRESS
    from one approved 4.00 hour line and still carries two unresolved charges: a
    2.00 hour line awaiting approval and a 100.00 printing charge held for a
    missing receipt.
    """
    ctx = build_active_project(api)
    settled = add_approved_time_entry(api, ctx, hours=4.00, work_date="2026-05-11")
    open_line = submit_time_entry(api, ctx, hours=2.00, work_date="2026-05-12")
    held_expense = add_expense(
        api,
        ctx,
        amount=100.00,
        category=CATEGORY_PRINTING,
        incurred_on="2026-05-12",
        receipt_attached=False,
    )
    return ctx, settled, open_line, held_expense


def test_completion_is_refused_while_a_line_and_an_expense_are_both_open(api):
    """
    A phase carrying an unapproved timesheet line and an unadjudicated expense
    cannot be completed: two unrelated populations of unfinished work report the
    same refusal, and the phase stays IN_PROGRESS.

    PRD §3.6: "It requires that the phase be `IN_PROGRESS`, that no time entry on the phase remain in `SUBMITTED`, that no expense on the phase remain in `PENDING_REVIEW`, and that no `EXECUTED` subcontract on the phase still have a `released_to_date` below its `committed_amount`."

    Design: Corner/validations/phase_completion_is_blocked_by_open_charges_of_two_kinds
    """
    ctx, _settled, _open_line, _held_expense = _phase_in_progress_with_two_open_charges(
        api
    )
    assert read_phase(api, ctx.phase_id)["status"] == PHASE_IN_PROGRESS

    refused = api.complete_phase(ctx.phase_id, PROJECT_MANAGER)

    validate_error(refused, ERR_PHASE_HAS_OPEN_CHARGES, 409)
    assert read_phase(api, ctx.phase_id)["status"] == PHASE_IN_PROGRESS


def test_clearing_only_the_timesheet_line_leaves_completion_blocked(api):
    """
    Approving the outstanding 2.00 hour line does not unblock completion: the
    held expense on its own is enough to refuse it, which is what makes the rule
    a conjunction over both populations rather than a choice between them.

    PRD §3.6: "Open charges are refused with `ERR_PHASE_HAS_OPEN_CHARGES` (HTTP 409)."

    Design: Corner/validations/phase_completion_is_blocked_by_open_charges_of_two_kinds
    """
    ctx, _settled, open_line, held_expense = _phase_in_progress_with_two_open_charges(api)
    approved = approve_time_entry(api, open_line["id"])
    assert_time_entry_frozen(approved, 125.00, 3.0500, 381.25)
    assert_expense_decision(
        read_expense(api, held_expense["id"]),
        ALLOWABILITY_PENDING_REVIEW,
        REASON_RECEIPT_MISSING,
        billable_amount=0.00,
    )

    refused = api.complete_phase(ctx.phase_id, PROJECT_MANAGER)

    validate_error(refused, ERR_PHASE_HAS_OPEN_CHARGES, 409)
    assert read_phase(api, ctx.phase_id)["status"] == PHASE_IN_PROGRESS


def test_disallowing_the_held_expense_resolves_it_and_completion_succeeds(api):
    """
    The rule asks for resolution rather than allowance: disallowing the held
    charge takes it out of review, adds nothing billable, and once both
    populations are resolved completion succeeds and forces the phase's full
    200000.00 fee into recognised revenue in place of the 1260.00 the
    cost-to-cost route would have recognised.

    PRD §3.6: "On success, `recognized_earned_value` is forced to the full `phase_fee` regardless of the project's `percent_complete_method`, so completion settles the delta between the selected variant and the full fee in a single step; that change re-derives the project's `earned_revenue_to_date` and, through it, the reported `total_charge_value` position; the project's closure condition is re-evaluated; and both the phase's `version` and the project's `version` increment by 1."

    Design: Corner/validations/phase_completion_is_blocked_by_open_charges_of_two_kinds
    """
    ctx, _settled, open_line, held_expense = _phase_in_progress_with_two_open_charges(api)
    approve_time_entry(api, open_line["id"])

    reviewed = validate_success(
        api.review_expense(
            held_expense["id"],
            expense_review_payload(
                DECISION_DISALLOW, "No receipt could be located"
            ),
            CONTROLLER,
        ),
        200,
    )
    assert_expense_decision(
        reviewed,
        ALLOWABILITY_DISALLOWED,
        REASON_DISALLOWED_BY_REVIEW,
        billable_amount=0.00,
    )

    completed = validate_success(api.complete_phase(ctx.phase_id, PROJECT_MANAGER), 200)

    assert completed["status"] == PHASE_COMPLETE
    assert_phase_earned_value(
        read_earned_value(api, ctx.phase_id),
        actual_labor_cost_to_date=375.00,
        effort_based_percent_complete=0.0063,
        effort_based_earned_value=1260.00,
        recognized_earned_value=200000.00,
    )


def test_the_completed_phase_does_not_close_a_project_still_holding_unbilled_work(api):
    """
    Every phase of the project is now COMPLETE, yet 1143.75 of approved labour
    has never been billed — 762.50 from the 4.00 hour line and 381.25 from the
    2.00 hour line, with the disallowed charge adding nothing — so the closure
    condition fails and the project stays ACTIVE.

    PRD §3.6: "A project moves from `ACTIVE` to `CLOSED` when every leaf phase of the project has reached `COMPLETE` (non-leaf phases, which can carry no charges, are not required to reach `COMPLETE` — their fee is represented by their children), the project's `unbilled_wip` is exactly 0.00, and every invoice of the project is in `PAID`, `WRITTEN_OFF` or `VOID`."

    Design: Corner/validations/phase_completion_is_blocked_by_open_charges_of_two_kinds
    """
    ctx, _settled, open_line, held_expense = _phase_in_progress_with_two_open_charges(api)
    approve_time_entry(api, open_line["id"])
    get_success_data(
        api.review_expense(
            held_expense["id"],
            expense_review_payload(DECISION_DISALLOW, "No receipt could be located"),
            CONTROLLER,
        )
    )
    get_success_data(api.complete_phase(ctx.phase_id, PROJECT_MANAGER))

    project = read_project(api, ctx.project_id)

    assert project["status"] == PROJECT_ACTIVE
    assert_project_ledger(
        project,
        unbilled_wip=1143.75,
        billed_open=0.00,
        earned_revenue_to_date=200000.00,
    )
