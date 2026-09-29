"""The royalty waterfall: the period-scoped provisional settlement and the
life-to-date final settlement, and what each posts to the agreement ledger."""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_fields_equal,
    assert_instant_format,
    assert_integer_cents,
    assert_ledger,
)
from test_helpers.fixtures import (
    authorize_payment,
    payment_of_milestone,
    setup_aurora_drift,
)
from test_helpers.api_client import original_data
from prd_bench_local_runner.testing import validate_success

ACCEPTED_BUILD_METRICS = {
    "feature_completeness_pct": 92.00,
    "crash_free_sessions_pct": 96.50,
    "content_completeness_pct": 61.00,
    "known_blocker_count": 3,
}


def _drift_with_disbursed_advance(api):
    """Aurora Drift with its first milestone accepted and its payment authorized:
    3600000 scheduled, a 500 bps holdback of 180000 and 3420000 disbursed."""
    scenario = setup_aurora_drift(api)
    reg = scenario.reg
    build = validate_success(
        api.create_build(
            f.build_payload_from_metrics(scenario.m1["id"], 1, ACCEPTED_BUILD_METRICS),
            reg.dev,
        ),
        201,
    )
    validate_success(
        api.create_review(f.accepted_review_payload(build["id"]), reg.reviewer), 201
    )
    payment = payment_of_milestone(reg, scenario.m1["id"])
    authorized = authorize_payment(reg, payment["id"])
    assert authorized["net_amount_cents"] == 3420000
    return scenario


def test_provisional_royalty_rounds_each_line_on_its_own(api):
    """PRD §3.9: "the royalty base is pro-rated onto each revenue line in
    proportion to that line's distributable amount over `distributable_total_cents`,
    each pro-rated share is multiplied by the agreement's `royalty_rate_bps` and
    divided by 10000, **each line's result is rounded half up on its own**, and only
    then are the per-line results summed."

    Design: Difficulty/dual_variant_calc/royalty_provisional_period_basis_vs_final_life_to_date_basis
    """
    scenario = _drift_with_disbursed_advance(api)
    reg = scenario.reg

    statement = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q3", scenario.version(),
                [f.revenue_line("PC-GLOBAL", 5000000, 125000),
                 f.revenue_line("CONSOLE-A", 2725000, 0)],
                1200000,
            ),
            reg.finance,
        ),
        201,
    )

    assert_fields_equal(
        statement,
        {
            "state": "DRAFT",
            "distributable_total_cents": 5320000,
            "cost_deduction_cents": 1064000,
            "recoupment_base_cents": 4256000,
            "recoup_applied_cents": 3420000,
            "royalty_base_cents": 836000,
            "provisional_royalty_payable_cents": 209001,
            "final_royalty_payable_cents": None,
            "finalized_at": None,
        },
        "royalty statement",
    )
    assert_integer_cents(statement["provisional_royalty_payable_cents"])


def test_final_royalty_rounds_the_cumulative_figure_exactly_once(api):
    """PRD §3.9: "the cumulative royalty owed is that base multiplied by
    `royalty_rate_bps`, divided by 10000 and rounded half up **exactly once** — a
    single rounding on the cumulative figure, not a per-line sum."

    Design: Difficulty/dual_variant_calc/royalty_provisional_period_basis_vs_final_life_to_date_basis
    """
    scenario = _drift_with_disbursed_advance(api)
    reg = scenario.reg

    statement = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q3", scenario.version(),
                [f.revenue_line("PC-GLOBAL", 5000000, 125000),
                 f.revenue_line("CONSOLE-A", 2725000, 0)],
                1200000,
            ),
            reg.finance,
        ),
        201,
    )
    finalized = validate_success(
        api.finalize_royalty_statement(statement["id"], reg.finance)
    )

    assert finalized["state"] == "FINALIZED"
    assert finalized["final_royalty_payable_cents"] == 209000
    assert finalized["provisional_royalty_payable_cents"] == 209001, (
        "the provisional figure must survive finalization untouched"
    )
    assert_instant_format(
        original_data(
            api.get_royalty_statement(statement["id"], reg.finance)
        )["finalized_at"],
        "finalized_at",
    )


def test_finalization_posts_the_life_to_date_recoupment_to_the_agreement(api):
    """PRD §3.9: "Step one sets `advance_recouped_cents` to the cumulative
    recoupment applied, then recomputes `unrecouped_advance_cents` as
    `advance_disbursed_cents` less that figure, floored at zero." Step two
    "advances `recoupment_state` from `RECOUPING` to `RECOUPED` the moment
    `unrecouped_advance_cents` reaches 0", and step three "adds
    `final_royalty_payable_cents` to `royalties_paid_to_date_cents`."

    Design: Difficulty/dual_variant_calc/royalty_provisional_period_basis_vs_final_life_to_date_basis
    """
    scenario = _drift_with_disbursed_advance(api)
    reg = scenario.reg

    statement = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q3", scenario.version(),
                [f.revenue_line("PC-GLOBAL", 5000000, 125000),
                 f.revenue_line("CONSOLE-A", 2725000, 0)],
                1200000,
            ),
            reg.finance,
        ),
        201,
    )
    validate_success(api.finalize_royalty_statement(statement["id"], reg.finance))

    agreement = scenario.read_agreement()
    assert_ledger(
        agreement,
        advance_disbursed_cents=3420000,
        advance_recouped_cents=3420000,
        unrecouped_advance_cents=0,
        royalties_paid_to_date_cents=209000,
        recoupment_state="RECOUPED",
    )
    summary = validate_success(
        api.get_recoupment_summary(scenario.agreement_id, reg.finance)
    )
    assert_fields_equal(
        summary,
        {
            "advance_disbursed_cents": 3420000,
            "advance_recouped_cents": 3420000,
            "unrecouped_advance_cents": 0,
            "royalties_paid_to_date_cents": 209000,
            "recoupment_state": "RECOUPED",
        },
        "recoupment summary",
    )


def test_empty_revenue_lines_settle_to_zero_and_cap_the_cost_claim_at_zero(api):
    """PRD §3.9: "`distributable_total_cents` is the sum of those per-line
    distributable amounts, and it is 0 when `revenue_lines` is empty." The cap
    follows the same figure: "the period's cap is `distributable_total_cents`
    multiplied by the agreement's `recoupable_cost_cap_bps`, divided by 10000 and
    rounded half up, and `cost_deduction_cents` is the smaller of the claimed
    `recoupable_cost_cents` and that cap."

    Design: Difficulty/boundary_precision_check/royalty_statement_with_empty_revenue_lines_and_uncapped_cost_claim
    """
    scenario = _drift_with_disbursed_advance(api)
    reg = scenario.reg

    statement = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q1", scenario.version(), [], 1000000
            ),
            reg.finance,
        ),
        201,
    )

    assert_fields_equal(
        statement,
        {
            "state": "DRAFT",
            "distributable_total_cents": 0,
            "cost_deduction_cents": 0,
            "recoupment_base_cents": 0,
            "recoup_applied_cents": 0,
            "royalty_base_cents": 0,
            "provisional_royalty_payable_cents": 0,
            "final_royalty_payable_cents": None,
        },
        "royalty statement",
    )


def test_finalizing_a_zero_revenue_period_leaves_the_recoupment_ledger_intact(api):
    """PRD §3.9: "When `distributable_total_cents` is 0 the sum is empty and the
    provisional royalty is therefore 0." A period that distributes nothing recoups
    nothing, so the agreement's `unrecouped_advance_cents` stays where the
    disbursement left it and `recoupment_state` stays `RECOUPING`.

    Design: Difficulty/boundary_precision_check/royalty_statement_with_empty_revenue_lines_and_uncapped_cost_claim
    """
    scenario = _drift_with_disbursed_advance(api)
    reg = scenario.reg

    before = scenario.read_agreement()
    assert before["recoupment_state"] == "RECOUPING"
    assert before["unrecouped_advance_cents"] == 3420000

    statement = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q1", scenario.version(), [], 1000000
            ),
            reg.finance,
        ),
        201,
    )
    finalized = validate_success(
        api.finalize_royalty_statement(statement["id"], reg.finance)
    )

    assert finalized["state"] == "FINALIZED"
    assert finalized["final_royalty_payable_cents"] == 0
    assert_ledger(
        scenario.read_agreement(),
        advance_disbursed_cents=3420000,
        advance_recouped_cents=0,
        unrecouped_advance_cents=3420000,
        royalties_paid_to_date_cents=0,
        recoupment_state="RECOUPING",
    )
