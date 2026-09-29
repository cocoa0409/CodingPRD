"""
The two statutory measures of accrued interest, and the two risk screens.

Both pairs are dual-variant computations: one set of underlying data feeds two
formulas that are chosen by purpose rather than by caller preference, and the two
answers are deliberately different numbers on the same request.
"""

from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_START


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _case_with_three_unpaid_monthly_charges() -> fx.Scenario:
    """
    An entered order at the guideline 75,000 cents carrying three unpaid monthly
    charges due on the fifteenth, with the clock then advanced to 2026-11-01.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Dana Ruiz",
            "ssn_last4": "1111",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Alex Ruiz",
            "ssn_last4": "2222",
            "monthly_gross_income_cents": 300000,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={"origin_state_code": "MN", "effective_date": "2026-08-01"},
    )
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id,
        ["2026-08-01", "2026-09-01", "2026-10-01"],
        due_day=15,
    )
    fx.set_clock("2026-11-01T00:00:00Z")
    return scenario


def _obligor_in_employer_default() -> fx.Scenario:
    """
    An obligor with six unpaid monthly charges of 82,500 cents and a served
    withholding order that has lapsed twice, read at 2027-02-01.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Bree Okafor",
            "ssn_last4": "3131",
            "monthly_gross_income_cents": 150000,
        },
        ncp_overrides={
            "full_name": "Cal Okafor",
            "ssn_last4": "3232",
            "monthly_gross_income_cents": 330000,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={"origin_state_code": "MN", "effective_date": "2026-08-01"},
    )
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id,
        [
            "2026-08-01",
            "2026-09-01",
            "2026-10-01",
            "2026-11-01",
            "2026-12-01",
            "2027-01-01",
        ],
        due_day=15,
    )
    scenario.employer = fx.create_employer(
        state_code="MN", legal_name="Northshore Foundry", remittance_fee_cents=0
    )
    scenario.withholding_order = fx.issue_withholding_order(
        scenario.order_id,
        scenario.employer_id,
        reported_disposable_income_cents=155000,
    )
    scenario.withholding_order = fx.serve_withholding_order(scenario.iwo_id)
    fx.set_clock("2027-02-01T00:00:00Z")
    return scenario


# ---------------------------------------------------------------------------
# The two interest measures
# ---------------------------------------------------------------------------


def test_01_per_charge_and_aggregate_interest_diverge_by_exactly_1125_cents():
    """
    Three identical unpaid charges produce two different interest totals.

    The **per-charge statutory measure** walks the input set ordered by `due_date` and then by `created_at`, and for each charge computes the number of whole calendar months between that charge's own `due_date` and the as-of date, multiplies the charge's `unpaid_balance_cents` by the monthly rate of 0.005 and by that month count, rounds the product half up to whole cents, and adds it to a running total.

    Design: Difficulty/dual_variant_calc/interest_variant_divergence_on_case_ledger
    """
    scenario = _case_with_three_unpaid_monthly_charges()

    assert scenario.order["monthly_obligation_cents"] == 75000
    assert scenario.charges[0]["amount_cents"] == 75000

    accrual_run = fx.run_accrual(scenario.case_id)

    interest_1 = fx.read_charge(scenario.charges[0]["id"])["interest_accrued_cents"]
    interest_2 = fx.read_charge(scenario.charges[1]["id"])["interest_accrued_cents"]
    interest_3 = fx.read_charge(scenario.charges[2]["id"])["interest_accrued_cents"]

    # Two whole calendar months from 2026-08-15 to 2026-11-01.
    assert interest_1 == 750
    # One whole calendar month from 2026-09-15.
    assert interest_2 == 375
    # Less than one whole calendar month from 2026-10-15 contributes exactly zero.
    assert interest_3 == 0
    assert interest_1 + interest_2 + interest_3 == 1125

    case = fx.read_case(scenario.case_id)
    assert case["arrears_principal_cents"] == 225000
    # 375 at the 2026-08-31 snapshot, 750 at 2026-09-30 and 1125 at 2026-10-31.
    assert case["interest_receivable_cents"] == 2250
    assert accrual_run["interest_receivable_cents"] == 2250

    assert case["interest_receivable_cents"] - (interest_1 + interest_2 + interest_3) == 1125


def test_02_ledger_read_reports_both_measures_side_by_side_at_the_as_of_date():
    """
    The ledger values both measures at a supplied as-of date without mutating.

    The ledger read reports both measures side by side — `statutory_interest_cents` and `aggregate_interest_cents` — together with `interest_written_off_cents`, `interest_collected_cents`, `interest_receivable_cents`, `arrears_principal_cents`, `assigned_arrears_cents`, `unassigned_arrears_cents` and `unapplied_credit_cents`, and it accepts an optional `as_of_date` to value the ledger at a past or future date without mutating anything.

    Design: Difficulty/dual_variant_calc/interest_variant_divergence_on_case_ledger
    """
    scenario = _case_with_three_unpaid_monthly_charges()
    fx.run_accrual(scenario.case_id)

    ledger = fx.read_ledger(scenario.case_id, as_of_date="2026-11-01")

    assert ledger["statutory_interest_cents"] == 1125
    assert ledger["aggregate_interest_cents"] == 2250
    assert ledger["interest_written_off_cents"] == 0
    assert ledger["interest_collected_cents"] == 0
    assert ledger["interest_receivable_cents"] == 2250
    assert ledger["arrears_principal_cents"] == 225000
    assert ledger["aggregate_interest_cents"] - ledger["statutory_interest_cents"] == 1125


def test_03_case_interest_receivable_takes_the_aggregate_month_end_total():
    """
    The case's receivable figure is the ledger measure, not the certified one.

    `interest_receivable_cents` is a computed field: the aggregate month-end interest total, less `interest_written_off_cents`, less `interest_collected_cents`, floored at zero so it never goes negative.

    Design: Difficulty/dual_variant_calc/interest_variant_divergence_on_case_ledger
    """
    scenario = _case_with_three_unpaid_monthly_charges()

    case_before_run = fx.read_case(scenario.case_id)
    assert case_before_run["interest_receivable_cents"] == 2250

    first_run = fx.run_accrual(scenario.case_id)
    second_run = fx.run_accrual(scenario.case_id)

    assert first_run["interest_receivable_cents"] == 2250
    assert second_run["interest_receivable_cents"] == 2250

    ledger = fx.read_ledger(scenario.case_id)
    assert (
        ledger["interest_receivable_cents"]
        == ledger["aggregate_interest_cents"]
        - ledger["interest_written_off_cents"]
        - ledger["interest_collected_cents"]
    )


# ---------------------------------------------------------------------------
# The two risk screens
# ---------------------------------------------------------------------------


def test_04_enforcement_and_compromise_screens_land_the_same_obligor_in_different_tiers():
    """
    One set of six components, two weightings, two tiers.

    The **enforcement screen**, written to `enforcement_risk_score` and `enforcement_risk_tier`, weights arrears at 40, delinquency at 25, payment history at 20, locate at 10 and interstate exposure at 5, and weights enforcement history at 0 — past remedies are not evidence for a new remedy.

    Design: Difficulty/dual_variant_calc/risk_variant_tier_flip_on_noncustodial_participant
    """
    scenario = _obligor_in_employer_default()

    first_lapse = fx.declare_lapse(scenario.iwo_id)
    second_lapse = fx.declare_lapse(scenario.iwo_id)
    assert first_lapse["remittance_status"] == "DELINQUENT"
    assert second_lapse["remittance_status"] == "DEFAULTED"
    assert second_lapse["missed_remittance_count"] == 2

    fx.run_accrual(scenario.case_id)
    obligor = fx.read_participant(scenario.ncp_id)

    # arrears 50, delinquency 100, payment history 100, locate 0, enforcement 0,
    # interstate 0: (40*50 + 25*100 + 20*100) / 100.
    assert obligor["enforcement_risk_score"] == 65
    assert obligor["enforcement_risk_tier"] == "MEDIUM"
    # The same components under the compromise weighting: (25*50 + 20*100 + 40*100) / 100.
    assert obligor["compromise_risk_score"] == 73
    assert obligor["compromise_risk_tier"] == "HIGH"
    assert obligor["enforcement_risk_tier"] != obligor["compromise_risk_tier"]


def test_05_certified_arrears_total_uses_the_per_charge_measure_across_open_cases():
    """
    The obligor's certified total is principal plus the certification measure.

    A participant's `total_arrears_certified_cents` is the sum, over every `SupportCase` whose `noncustodial_party_id` is that participant and whose `case_status` is anything other than `CLOSED`, of that case's `arrears_principal_cents` plus that case's per-charge statutory interest total.

    Design: Difficulty/dual_variant_calc/risk_variant_tier_flip_on_noncustodial_participant
    """
    scenario = _obligor_in_employer_default()

    assert scenario.order["monthly_obligation_cents"] == 82500
    # Requested 82,500 with no arrears recovery yet, against a 60 percent ceiling
    # of floor(155000 * 0.60) = 93,000 cents and no employer fee.
    assert scenario.withholding_order["withholding_amount_cents"] == 82500

    fx.declare_lapse(scenario.iwo_id)
    fx.declare_lapse(scenario.iwo_id)
    fx.run_accrual(scenario.case_id)

    case = fx.read_case(scenario.case_id)
    obligor = fx.read_participant(scenario.ncp_id)
    ledger = fx.read_ledger(scenario.case_id)

    assert case["arrears_principal_cents"] == 495000
    # 2063 + 1650 + 1238 + 825 + 413 + 0 across the six charges at 2027-02-01.
    assert ledger["statutory_interest_cents"] == 6189
    assert obligor["total_arrears_certified_cents"] == 501189
    assert (
        obligor["total_arrears_certified_cents"]
        == case["arrears_principal_cents"] + ledger["statutory_interest_cents"]
    )
