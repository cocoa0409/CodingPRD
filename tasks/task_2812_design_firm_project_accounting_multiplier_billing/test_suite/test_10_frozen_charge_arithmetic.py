"""
The three pinned arithmetics of an architecture practice's billable charge: the
consultant markup, the frozen labour charge and the client invoice waterfall.

None of the three is a simple product. The client-facing consultant markup is a
non-additive function of four separate inputs — how much consultant cost the
project has already approved, whether the contract is fixed fee, whether the
client is a public agency, and the payable's own amount — so the same payable is
worth different money on different projects. The labour charge rounds twice and
the order of those two roundings is pinned, because rounding the raw cost to
cents before applying the multiplier is a different number from rounding once at
the end. And the invoice waterfall looks circular: the volume-discount tier is
keyed on the gross before any discount, while retainage is keyed on the base
after it, so reversing the two steps produces a materially different bill.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_STALE_PROJECT_VERSION
from test_helpers.assertions import (
    assert_invoice_money,
    assert_money,
    assert_payable_axes,
    assert_payable_markup,
    assert_project_ledger,
    assert_ratio,
    assert_subcontract_rollup,
    assert_swept_counts,
    assert_time_entry_carries_no_money,
    assert_time_entry_frozen,
    quantize_money,
)
from test_helpers.constants import (
    CLOCK_2026_06_01,
    CONTRACT_FIXED_FEE,
    CONTRACT_TIME_AND_MATERIALS,
    INVOICE_DRAFT,
    METHOD_ASSESSED,
    METHOD_EFFORT_BASED,
    PAYABLE_APPROVED,
    PAYABLE_BILLED_TO_CLIENT,
    PAYABLE_UNBILLED,
    PAYMENT_WITHHELD,
    TIME_ENTRY_APPROVED,
)
from test_helpers.factories import invoice_payload
from test_helpers.fixtures import (
    CANONICAL_MULTIPLIER,
    RATE_EFFECTIVE_FROM,
    activate_project,
    add_executed_subcontract,
    add_approved_payable,
    add_lump_sum_phase,
    add_percent_phase,
    approve_time_entry,
    create_private_client,
    create_project,
    create_public_client,
    prepare_invoice,
    project_version,
    read_invoice,
    read_payable,
    read_project,
    read_subcontract,
    read_time_entry,
    set_clock,
    set_multiplier,
    submit_time_entry,
)
from test_helpers.test_users import ACCOUNTANT
from test_helpers.types import ProjectContext

# Consultant markup: the four interacting inputs and the figures they produce.
TIER1_PAYABLE_AMOUNT = 250000.00
TIER1_MARKUP_PCT = 0.1000
TIER1_MARKUP_AMOUNT = 25000.00
TIER1_BILLABLE = 275000.00
TIER2_PAYABLE_AMOUNT = 10000.00
TIER2_MARKUP_PCT = 0.0600
TIER2_MARKUP_AMOUNT = 600.00
TIER2_BILLABLE = 10600.00
SHARED_PAYABLE_AMOUNT = 40000.00
PRIVATE_FIXED_FEE_MARKUP_PCT = 0.1200
PRIVATE_FIXED_FEE_MARKUP_AMOUNT = 4800.00
PRIVATE_FIXED_FEE_BILLABLE = 44800.00
PUBLIC_FIXED_FEE_MARKUP_PCT = 0.0500
PUBLIC_FIXED_FEE_MARKUP_AMOUNT = 2000.00
PUBLIC_FIXED_FEE_BILLABLE = 42000.00

# The frozen labour charge: two operand sets whose two rounding orders diverge.
HOURS_A = 7.35
RAW_COST_A = 459.38
BILLABLE_A = 1401.11
SINGLE_STEP_A = 1401.09
HOURS_B = 3.25
RAW_COST_B = 203.13
BILLABLE_B = 619.55
SINGLE_STEP_B = 619.53
RAW_LABOR_TOTAL = 662.51
BILLABLE_TOTAL = 2020.66

# The invoice waterfall on a single consultant charge.
WATERFALL_PAYABLE_AMOUNT = 91363.64
WATERFALL_MARKUP_AMOUNT = 9136.36
WATERFALL_GROSS = 100500.00
WATERFALL_DISCOUNT_PCT = 0.0100
WATERFALL_DISCOUNT = 1005.00
WATERFALL_POST_DISCOUNT_BASE = 99495.00
WATERFALL_RETAINAGE = 4974.75
WATERFALL_NET_DUE = 94520.25
RETAINAGE_FIRST_NET_DUE = 95475.00
RETAINAGE_ON_GROSS = 5025.00


def _hourly_consultant_project(api, client_id):
    """
    An ACTIVE private TIME_AND_MATERIALS project carrying one EXECUTED 300000.00
    consultant commitment and no approved consultant cost at all.
    """
    project = create_project(
        api,
        client_id,
        name="P1 hourly tower",
        contract_type=CONTRACT_TIME_AND_MATERIALS,
        contract_amount=2000000.00,
        percent_complete_method=METHOD_EFFORT_BASED,
        target_multiplier=3.0000,
    )
    phase = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="03-CD",
        lump_sum_fee=800000.00,
        budget_labor_cost=200000.00,
        consultant_budget=400000.00,
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
        client_id=client_id,
        project_id=project["id"],
        version=activated["version"],
        phase_ids=[phase["id"]],
        contract_type=CONTRACT_TIME_AND_MATERIALS,
    )
    subcontract = add_executed_subcontract(
        api, ctx, committed_amount=300000.00, consultant_name="Meridian Structural"
    )
    return ctx, subcontract


def _fixed_fee_consultant_project(
    api, client_id, name, multiplier, target_multiplier, is_public_agency
):
    """
    An ACTIVE FIXED_FEE project carrying one EXECUTED 50000.00 consultant
    commitment and no approved consultant cost.
    """
    project = create_project(
        api,
        client_id,
        name=name,
        contract_type=CONTRACT_FIXED_FEE,
        contract_amount=500000.00,
        percent_complete_method=METHOD_ASSESSED,
        target_multiplier=target_multiplier,
    )
    phase = add_percent_phase(
        api,
        project["id"],
        wbs_code="03-CD",
        fee_percent=0.2000,
        budget_labor_cost=40000.00,
        consultant_budget=100000.00,
    )
    set_multiplier(
        api,
        project["id"],
        multiplier=multiplier,
        effective_from=RATE_EFFECTIVE_FROM,
        expected_project_version=project["version"],
    )
    activated = activate_project(api, project["id"])
    ctx = ProjectContext(
        client_id=client_id,
        project_id=project["id"],
        version=activated["version"],
        phase_ids=[phase["id"]],
        is_public_agency=is_public_agency,
        contract_type=CONTRACT_FIXED_FEE,
    )
    subcontract = add_executed_subcontract(
        api, ctx, committed_amount=50000.00, consultant_name="Meridian Structural"
    )
    return ctx, subcontract


def _private_fixed_fee(api, client_id):
    return _fixed_fee_consultant_project(
        api,
        client_id,
        name="P3 fixed fee annex",
        multiplier=CANONICAL_MULTIPLIER,
        target_multiplier=3.0000,
        is_public_agency=False,
    )


def _public_fixed_fee(api, client_id):
    return _fixed_fee_consultant_project(
        api,
        client_id,
        name="P2 fixed fee transit",
        multiplier=2.5000,
        target_multiplier=2.5000,
        is_public_agency=True,
    )


def _waterfall_project(api, client_id):
    """
    An ACTIVE private TIME_AND_MATERIALS project whose only charge is a single
    approved consultant payable worth exactly 100500.00 to the client.
    """
    project = create_project(
        api,
        client_id,
        name="Civic Center Fit-out",
        contract_type=CONTRACT_TIME_AND_MATERIALS,
        contract_amount=2000000.00,
        percent_complete_method=METHOD_EFFORT_BASED,
        target_multiplier=3.0000,
    )
    phase = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="04-CA",
        lump_sum_fee=500000.00,
        budget_labor_cost=150000.00,
        consultant_budget=200000.00,
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
        client_id=client_id,
        project_id=project["id"],
        version=activated["version"],
        phase_ids=[phase["id"]],
        contract_type=CONTRACT_TIME_AND_MATERIALS,
    )
    subcontract = add_executed_subcontract(
        api, ctx, committed_amount=100000.00, consultant_name="Halcyon MEP"
    )
    payable = add_approved_payable(
        api,
        subcontract["id"],
        amount=WATERFALL_PAYABLE_AMOUNT,
        invoice_date="2026-05-20",
        backup_attached=True,
    )
    return ctx, subcontract, payable


def test_cumulative_consultant_volume_crosses_the_inclusive_tier_boundary(api):
    """
    The first 250000.00 payable is approved against a cumulative base of 0.00 and
    so draws the standard 0.1000 on a private hourly project. It then becomes the
    cumulative base itself, and the next payable — only 10000.00 — is approved
    against exactly 250000.00 of prior approved cost, which is already enough to
    select the 0.0600 tier because the threshold is inclusive.

    PRD §3.5: "The system first measures `approved_cost_to_date`: the sum of `amount` over every payable belonging to **this project** across all of its subcontracts whose `approval_status` is already `APPROVED`, evaluated before the current approval is applied, so the row being approved is excluded from its own cumulative base."
    PRD §3.5: "A base markup fraction of 0.1000 applies as standard; once `approved_cost_to_date` reaches 250000.00 the base drops to 0.0600, and the threshold is inclusive, so cumulative approved consultant cost of exactly 250000.00 already selects the lower tier."

    Design: Difficulty/combinatorial_formula/consultant_markup_four_input_interaction
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    ctx, subcontract = _hourly_consultant_project(api, client["id"])

    first = add_approved_payable(
        api, subcontract["id"], amount=TIER1_PAYABLE_AMOUNT, invoice_date="2026-05-05"
    )
    assert_payable_markup(
        first,
        applied_markup_pct=TIER1_MARKUP_PCT,
        markup_amount=TIER1_MARKUP_AMOUNT,
        billable_amount=TIER1_BILLABLE,
    )
    assert_payable_axes(first, PAYABLE_APPROVED, PAYMENT_WITHHELD, PAYABLE_UNBILLED)

    second = add_approved_payable(
        api, subcontract["id"], amount=TIER2_PAYABLE_AMOUNT, invoice_date="2026-05-20"
    )
    assert_payable_markup(
        second,
        applied_markup_pct=TIER2_MARKUP_PCT,
        markup_amount=TIER2_MARKUP_AMOUNT,
        billable_amount=TIER2_BILLABLE,
    )

    # The first payable's frozen markup is untouched by the later approval.
    assert_payable_markup(
        read_payable(api, first["id"]),
        applied_markup_pct=TIER1_MARKUP_PCT,
        markup_amount=TIER1_MARKUP_AMOUNT,
        billable_amount=TIER1_BILLABLE,
    )
    assert_subcontract_rollup(
        read_subcontract(api, subcontract["id"]),
        approved_to_date=260000.00,
        released_to_date=0.00,
        committed_remaining=40000.00,
    )


def test_private_fixed_fee_project_adds_the_coordination_risk_premium(api):
    """
    A 40000.00 payable on a private FIXED_FEE project takes the standard 0.1000
    base plus the 0.0200 fixed-fee premium, so 0.1200 is frozen and the client is
    billed 44800.00 for a 40000.00 cost.

    PRD §3.5: "If the project's `contract_type` is `FIXED_FEE`, a further 0.0200 is added to that base, because on a fixed fee the firm carries the coordination risk itself."
    PRD §3.5: "`markup_amount` is the payable's `amount` multiplied by `applied_markup_pct`, rounded half up to 2 decimal places, and `billable_amount` is the `amount` plus that `markup_amount`"

    Design: Difficulty/combinatorial_formula/consultant_markup_four_input_interaction
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    ctx, subcontract = _private_fixed_fee(api, client["id"])

    payable = add_approved_payable(
        api, subcontract["id"], amount=SHARED_PAYABLE_AMOUNT, invoice_date="2026-05-20"
    )
    assert_payable_markup(
        payable,
        applied_markup_pct=PRIVATE_FIXED_FEE_MARKUP_PCT,
        markup_amount=PRIVATE_FIXED_FEE_MARKUP_AMOUNT,
        billable_amount=PRIVATE_FIXED_FEE_BILLABLE,
    )
    assert_project_ledger(
        read_project(api, ctx.project_id), unbilled_wip=PRIVATE_FIXED_FEE_BILLABLE
    )


def test_public_agency_cap_overrides_the_fixed_fee_premium(api):
    """
    The identical 40000.00 payable on a FIXED_FEE project billed to a public
    agency computes the same 0.1200 base and is then capped: 0.0500 is frozen, so
    the markup falls to 2000.00 and the client is billed 42000.00.

    PRD §3.5: "if the client has `is_public_agency` set to true, the result is capped at 0.0500 — the effective `applied_markup_pct` is the lesser of the computed base and that cap"

    Design: Difficulty/combinatorial_formula/consultant_markup_four_input_interaction
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_public_client(api)
    ctx, subcontract = _public_fixed_fee(api, client["id"])

    payable = add_approved_payable(
        api, subcontract["id"], amount=SHARED_PAYABLE_AMOUNT, invoice_date="2026-05-20"
    )
    assert_payable_markup(
        payable,
        applied_markup_pct=PUBLIC_FIXED_FEE_MARKUP_PCT,
        markup_amount=PUBLIC_FIXED_FEE_MARKUP_AMOUNT,
        billable_amount=PUBLIC_FIXED_FEE_BILLABLE,
    )
    assert_payable_axes(payable, PAYABLE_APPROVED, PAYMENT_WITHHELD, PAYABLE_UNBILLED)
    assert_project_ledger(
        read_project(api, ctx.project_id), unbilled_wip=PUBLIC_FIXED_FEE_BILLABLE
    )


def test_one_payable_amount_two_clients_two_different_markups(api):
    """
    Two FIXED_FEE projects, one private and one public agency, each receive a
    40000.00 consultant payable of their own. Nothing differs but the client's
    public-agency flag, and the client-facing markup differs by 2800.00.

    PRD §3.5: "Approval also fixes the markup, and four inputs interact non-linearly to produce it."

    Design: Difficulty/combinatorial_formula/consultant_markup_four_input_interaction
    """
    set_clock(api, CLOCK_2026_06_01)
    private = create_private_client(api)
    public = create_public_client(api)
    private_ctx, private_subcontract = _private_fixed_fee(api, private["id"])
    public_ctx, public_subcontract = _public_fixed_fee(api, public["id"])

    private_payable = add_approved_payable(
        api,
        private_subcontract["id"],
        amount=SHARED_PAYABLE_AMOUNT,
        invoice_date="2026-05-20",
    )
    public_payable = add_approved_payable(
        api,
        public_subcontract["id"],
        amount=SHARED_PAYABLE_AMOUNT,
        invoice_date="2026-05-20",
    )

    assert_money(private_payable["amount"], SHARED_PAYABLE_AMOUNT, "private payable amount")
    assert_money(public_payable["amount"], SHARED_PAYABLE_AMOUNT, "public payable amount")
    assert_ratio(
        private_payable["applied_markup_pct"],
        PRIVATE_FIXED_FEE_MARKUP_PCT,
        "private applied_markup_pct",
    )
    assert_ratio(
        public_payable["applied_markup_pct"],
        PUBLIC_FIXED_FEE_MARKUP_PCT,
        "public applied_markup_pct",
    )
    assert_money(
        private_payable["markup_amount"],
        PRIVATE_FIXED_FEE_MARKUP_AMOUNT,
        "private markup_amount",
    )
    assert_money(
        public_payable["markup_amount"], PUBLIC_FIXED_FEE_MARKUP_AMOUNT, "public markup_amount"
    )
    gap = quantize_money(private_payable["markup_amount"]) - quantize_money(
        public_payable["markup_amount"]
    )
    assert_money(gap, 2800.00, "markup gap on an identical payable")
    assert_money(
        private_payable["billable_amount"], PRIVATE_FIXED_FEE_BILLABLE, "private billable"
    )
    assert_money(
        public_payable["billable_amount"], PUBLIC_FIXED_FEE_BILLABLE, "public billable"
    )
    # Each project's own commitment is drawn down by cost, not by billable value.
    assert_subcontract_rollup(
        read_subcontract(api, private_subcontract["id"]),
        approved_to_date=SHARED_PAYABLE_AMOUNT,
        committed_remaining=10000.00,
    )
    assert_subcontract_rollup(
        read_subcontract(api, public_subcontract["id"]),
        approved_to_date=SHARED_PAYABLE_AMOUNT,
        committed_remaining=10000.00,
    )


def test_seven_hours_thirty_five_rounds_the_raw_cost_before_the_multiplier(api, active_project):
    """
    7.35 hours at 62.50 is 459.375 of raw cost, which becomes 459.38 at the
    first rounding step; only then is the 3.0500 multiplier applied, giving
    1401.11. Collapsing the two steps into one product would have given 1401.09.

    PRD §3.3: "First, `raw_cost` is the `hours` multiplied by the resolved `raw_cost_rate`, rounded half up to 2 decimal places."
    PRD §3.3: "Rounding the raw cost first gives 459.38, and 459.38 multiplied by 3.0500 rounds to 1401.11. Multiplying all three factors and rounding only once would give 1401.09, which is the wrong answer."

    Design: Difficulty/combinatorial_formula/labor_charge_two_step_rounding_order
    """
    submitted = submit_time_entry(api, active_project, hours=HOURS_A, work_date="2026-05-11")
    assert_time_entry_carries_no_money(submitted)

    approved = approve_time_entry(api, submitted["id"])
    assert approved["status"] == TIME_ENTRY_APPROVED
    assert_time_entry_frozen(approved, RAW_COST_A, CANONICAL_MULTIPLIER, BILLABLE_A)
    assert quantize_money(approved["billable_amount"]) != quantize_money(SINGLE_STEP_A), (
        "the single-step product must not be the frozen billable amount"
    )
    assert_time_entry_frozen(
        read_time_entry(api, submitted["id"]), RAW_COST_A, CANONICAL_MULTIPLIER, BILLABLE_A
    )


def test_three_hours_twenty_five_shows_the_same_order_on_a_second_operand_set(api, active_project):
    """
    A second, independent operand set behaves identically: 3.25 hours at 62.50 is
    203.125, rounded to 203.13 before the multiplier, and 203.13 at 3.0500 is
    619.55. The one-step product would have been 619.53.

    PRD §3.3: "Third, `billable_amount` is the already-rounded `raw_cost` multiplied by `applied_multiplier`, rounded half up to 2 decimal places."
    PRD §3.3: "The intermediate rounding is not cosmetic: consider 7.35 hours at a raw cost rate of 62.50 with a multiplier of 3.0500."

    Design: Difficulty/combinatorial_formula/labor_charge_two_step_rounding_order
    """
    submitted = submit_time_entry(api, active_project, hours=HOURS_B, work_date="2026-05-12")
    approved = approve_time_entry(api, submitted["id"])

    assert_time_entry_frozen(approved, RAW_COST_B, CANONICAL_MULTIPLIER, BILLABLE_B)
    assert quantize_money(approved["billable_amount"]) != quantize_money(SINGLE_STEP_B), (
        "the single-step product must not be the frozen billable amount"
    )
    assert_ratio(approved["applied_multiplier"], CANONICAL_MULTIPLIER, "applied_multiplier")


def test_project_rollups_sum_the_already_rounded_line_values(api, active_project):
    """
    Both lines together carry 662.51 of raw labour cost and 2020.66 of billable
    value, because the project sums the per-line frozen figures rather than
    re-deriving labour from hours. The achieved multiplier reports 3.0500.

    PRD §3.3: "Invoices later sum these already-rounded per-line values; they never re-derive labour from `hours`."
    PRD §2.10: "`net_multiplier_achieved` is the project's billable labour value divided by its raw labour cost: the sum of `billable_amount` over time entries whose `status` is `APPROVED`, `BILLED` or `WRITTEN_OFF`, divided by `raw_labor_cost_to_date`, rounded half up to 4 decimal places."

    Design: Difficulty/combinatorial_formula/labor_charge_two_step_rounding_order
    """
    first = submit_time_entry(api, active_project, hours=HOURS_A, work_date="2026-05-11")
    second = submit_time_entry(api, active_project, hours=HOURS_B, work_date="2026-05-12")
    approve_time_entry(api, first["id"])
    approve_time_entry(api, second["id"])

    project = read_project(api, active_project.project_id)
    assert_project_ledger(
        project,
        raw_labor_cost_to_date=RAW_LABOR_TOTAL,
        unbilled_wip=BILLABLE_TOTAL,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=BILLABLE_TOTAL,
        net_multiplier_achieved=CANONICAL_MULTIPLIER,
    )


def test_consultant_cost_of_91363_64_marks_up_to_exactly_the_tier_boundary(api):
    """
    A 91363.64 consultant cost on a private hourly project takes the standard
    0.1000 markup, which rounds to 9136.36 and makes the client-facing value
    exactly 100500.00 — the single charge the invoice will sweep.

    PRD §3.5: "`markup_amount` is the payable's `amount` multiplied by `applied_markup_pct`, rounded half up to 2 decimal places, and `billable_amount` is the `amount` plus that `markup_amount`"
    PRD §3.5: "The project's `unbilled_wip` rises by the payable's `billable_amount`, which re-runs `billing_posture`."

    Design: Difficulty/combinatorial_formula/invoice_discount_then_retainage_order
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    ctx, subcontract, payable = _waterfall_project(api, client["id"])

    assert_money(payable["amount"], WATERFALL_PAYABLE_AMOUNT, "payable.amount")
    assert_payable_markup(
        payable,
        applied_markup_pct=0.1000,
        markup_amount=WATERFALL_MARKUP_AMOUNT,
        billable_amount=WATERFALL_GROSS,
    )
    assert_project_ledger(read_project(api, ctx.project_id), unbilled_wip=WATERFALL_GROSS)


def test_discount_tiers_on_the_gross_then_retainage_on_the_post_discount_base(api):
    """
    A gross of 100500.00 reaches the 100000.00 discount tier, so 0.0100 gives a
    1005.00 discount; retainage is then 5% of the 99495.00 that remains, namely
    4974.75, and the net due is 94520.25. Withholding retainage from the gross
    first would have dropped the bill below the tier and produced 95475.00.

    PRD §3.7: "First, the volume discount tier is keyed on the **pre-discount** `gross_billed`: `volume_discount_pct` is 0.0200 once `gross_billed` reaches 250000.00, otherwise 0.0100 once it reaches 100000.00, otherwise 0.0000."
    PRD §3.7: "Third, `retainage_amount` is keyed on the **post-discount** base and never on `gross_billed` itself: it is `gross_billed` less `discount_amount`, multiplied by the client's `retainage_pct`, rounded half up to 2 decimal places."
    PRD §3.7: "Fourth, `net_due` is `gross_billed` less `discount_amount` less `retainage_amount`."

    Design: Difficulty/combinatorial_formula/invoice_discount_then_retainage_order
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    ctx, subcontract, payable = _waterfall_project(api, client["id"])

    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    assert invoice["status"] == INVOICE_DRAFT
    assert_invoice_money(
        invoice,
        labor_billed=0.00,
        expense_billed=0.00,
        consultant_billed=WATERFALL_GROSS,
        gross_billed=WATERFALL_GROSS,
        volume_discount_pct=WATERFALL_DISCOUNT_PCT,
        discount_amount=WATERFALL_DISCOUNT,
        retainage_amount=WATERFALL_RETAINAGE,
        net_due=WATERFALL_NET_DUE,
    )
    # The retainage really is taken on the post-discount base, not on the gross.
    base = quantize_money(invoice["gross_billed"]) - quantize_money(invoice["discount_amount"])
    assert_money(base, WATERFALL_POST_DISCOUNT_BASE, "post-discount base")
    assert quantize_money(invoice["retainage_amount"]) != quantize_money(RETAINAGE_ON_GROSS), (
        "retainage must not be withheld from the pre-discount gross"
    )
    assert quantize_money(invoice["net_due"]) != quantize_money(RETAINAGE_FIRST_NET_DUE), (
        "the retainage-first order must not be the net due"
    )
    assert_invoice_money(read_invoice(api, invoice["id"]), net_due=WATERFALL_NET_DUE)


def test_the_sweep_moves_the_single_charge_from_work_in_progress_to_billed(api):
    """
    The invoice records that it swept exactly one consultant payable and nothing
    else, with backup on file, and the ledger moves the whole 100500.00 out of
    work in progress and into the open billed position without changing the
    conserved total.

    PRD §3.7: "`swept_labor_count`, `swept_expense_count` and `swept_consultant_count` are the numbers of time entries, expenses and consultant payables attached to it, and `backup_missing_count` is the count of swept consultant payables whose `backup_attached` is false."
    PRD §3.7: "every swept payable moves to `BILLED_TO_CLIENT` with its `client_invoice_id` set, the project's `unbilled_wip` falls to whatever residual remains and its `billed_open` rises by `gross_billed`, and the project's `version` increments by 1"

    Design: Difficulty/combinatorial_formula/invoice_discount_then_retainage_order
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    ctx, subcontract, payable = _waterfall_project(api, client["id"])
    version_before = project_version(api, ctx.project_id)

    invoice = prepare_invoice(
        api, ctx, period_end="2026-05-31", expected_project_version=version_before
    )
    assert_swept_counts(
        invoice,
        swept_labor_count=0,
        swept_expense_count=0,
        swept_consultant_count=1,
        backup_missing_count=0,
    )

    swept = read_payable(api, payable["id"])
    assert_payable_axes(swept, PAYABLE_APPROVED, PAYMENT_WITHHELD, PAYABLE_BILLED_TO_CLIENT)
    assert swept["client_invoice_id"] == invoice["id"]
    # The frozen markup survives the sweep untouched.
    assert_payable_markup(
        swept,
        applied_markup_pct=0.1000,
        markup_amount=WATERFALL_MARKUP_AMOUNT,
        billable_amount=WATERFALL_GROSS,
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=WATERFALL_GROSS,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=WATERFALL_GROSS,
    )
    assert project["version"] == version_before + 1


def test_a_stale_project_version_refuses_the_sweep_outright(api):
    """
    Invoice preparation is optimistically concurrent on the project, so a
    preparer working from a version the project has already moved past is
    refused before any money is computed.

    PRD §2.7: "If the supplied value does not equal the project's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    Design: Difficulty/combinatorial_formula/invoice_discount_then_retainage_order
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_private_client(api)
    ctx, subcontract, payable = _waterfall_project(api, client["id"])
    current = project_version(api, ctx.project_id)

    refused = api.create_invoice(
        invoice_payload(ctx.project_id, current - 1, period_end="2026-05-31"), ACCOUNTANT
    )
    validate_error(refused, ERR_STALE_PROJECT_VERSION, 412)

    # Nothing was billed, so the whole charge is still in work in progress.
    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=WATERFALL_GROSS,
        billed_open=0.00,
        total_charge_value=WATERFALL_GROSS,
    )
    assert project_version(api, ctx.project_id) == current
