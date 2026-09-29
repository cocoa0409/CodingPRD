"""
Formulas whose answer is a joint product of several inputs.

Each computation here combines four or more inputs, or nests one rounding inside
another, or looks circular and is nevertheless resolved in a single pass, so that
moving any single input moves the observable result.
"""

from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_START


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _obligor_in_arrears_for_withholding(employer_state_code: str, remittance_fee_cents: int):
    """
    An entered order at 82,500 cents with six unpaid monthly charges, the clock
    then at 2027-02-01 so all six are past due, and one employer registered in
    the requested state.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Ines Marek",
            "ssn_last4": "4141",
            "monthly_gross_income_cents": 150000,
        },
        ncp_overrides={
            "full_name": "Jon Marek",
            "ssn_last4": "4242",
            "monthly_gross_income_cents": 330000,
            "supports_second_family": False,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
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
        state_code=employer_state_code,
        legal_name="Lone Star Rigging" if employer_state_code == "TX" else "Northline Payroll",
        remittance_fee_cents=remittance_fee_cents,
    )
    fx.set_clock("2027-02-01T00:00:00Z")
    scenario.reload_case()
    return scenario


def _draft_order_on_three_hundred_thousand_combined_income() -> fx.Scenario:
    """
    A drafted order whose parties earn 100,000 and 200,000 cents a month, so the
    obligor's share ratio is a repeating decimal.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Nia Bell",
            "ssn_last4": "5151",
            "monthly_gross_income_cents": 100000,
        },
        ncp_overrides={
            "full_name": "Omar Bell",
            "ssn_last4": "5252",
            "monthly_gross_income_cents": 200000,
            "supports_second_family": False,
        },
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    scenario.paternity_action = fx.open_paternity_action(scenario.case_id, "PRESUMED_MARITAL")
    scenario.order = fx.draft_order(
        scenario.case_id, origin_state_code="MN", effective_date="2026-08-01"
    )
    return scenario


def _case_ready_to_settle() -> fx.Scenario:
    """
    Six unpaid monthly charges of 82,500 cents, no withholding order and no
    remedy, with one accrual run posted at 2027-02-01.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Pia Rowe",
            "ssn_last4": "6161",
            "monthly_gross_income_cents": 150000,
        },
        ncp_overrides={
            "full_name": "Quinn Rowe",
            "ssn_last4": "6262",
            "monthly_gross_income_cents": 330000,
            "supports_second_family": False,
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
    fx.set_clock("2027-02-01T00:00:00Z")
    fx.run_accrual(scenario.case_id)
    scenario.reload_case()
    return scenario


# ---------------------------------------------------------------------------
# The withholding ceiling
# ---------------------------------------------------------------------------


def test_01_texas_employer_cap_wins_the_minimum_against_the_bumped_federal_cap():
    """
    Five inputs combine to a withholding amount of 77,300 cents.

    The employer's state ceiling is then brought in: `ccpa_cap_pct` is the smaller of `federal_cap_pct` and the employer's `statutory_cap_pct` when that state ceiling exists, and is simply `federal_cap_pct` when the employer's state has none.

    Design: Difficulty/combinatorial_formula/withholding_cap_nested_min_state_override
    """
    scenario = _obligor_in_arrears_for_withholding("TX", 200)

    assert scenario.order["monthly_obligation_cents"] == 82500
    assert scenario.case["arrears_principal_cents"] == 495000
    assert scenario.employer["statutory_cap_pct"] == 0.50

    iwo = fx.issue_withholding_order(
        scenario.order_id,
        scenario.employer_id,
        reported_disposable_income_cents=155000,
    )

    # The employer's state governs, not the MN case and not the MN order origin.
    assert iwo["jurisdiction_state_code"] == "TX"
    # round_half_up(82500 * 0.20).
    assert iwo["arrears_recovery_cents"] == 16500
    # 82500 monthly plus 0 medical plus 16500 arrears recovery.
    assert iwo["requested_amount_cents"] == 99000
    # 0.60 base plus the 0.05 bump, because 495000 is at least 3 x 82500.
    assert iwo["federal_cap_pct"] == 0.65
    assert iwo["ccpa_cap_pct"] == 0.50
    # floor(155000 * 0.50) — a ceiling is never rounded upward.
    assert iwo["ccpa_cap_amount_cents"] == 77500
    # max(0, min(99000, 77500 - 200)).
    assert iwo["withholding_amount_cents"] == 77300
    assert iwo["employer_fee_cents"] == 200
    assert iwo["withholding_amount_cents"] != iwo["requested_amount_cents"]
    assert (
        iwo["withholding_amount_cents"] + iwo["employer_fee_cents"]
        == iwo["ccpa_cap_amount_cents"]
    )


def test_02_same_arrears_and_income_reach_the_full_request_when_the_employer_state_has_no_ceiling():
    """
    Removing the one state ceiling moves the answer, so the minimum was binding.

    Two of the seven recognised states place their own ceiling on wage withholding: an employer whose principal place of business is in `TX` or in `WI` carries a `statutory_cap_pct` of 0.50, a fifty percent ceiling.

    Design: Difficulty/combinatorial_formula/withholding_cap_nested_min_state_override
    """
    scenario = _obligor_in_arrears_for_withholding("MN", 200)

    assert "statutory_cap_pct" not in scenario.employer or scenario.employer.get(
        "statutory_cap_pct"
    ) is None

    iwo = fx.issue_withholding_order(
        scenario.order_id,
        scenario.employer_id,
        reported_disposable_income_cents=155000,
    )

    assert iwo["jurisdiction_state_code"] == "MN"
    assert iwo["requested_amount_cents"] == 99000
    assert iwo["federal_cap_pct"] == 0.65
    # No state ceiling exists, so the bumped federal percentage stands alone.
    assert iwo["ccpa_cap_pct"] == 0.65
    # floor(155000 * 0.65).
    assert iwo["ccpa_cap_amount_cents"] == 100750
    # min(99000, 100750 - 200) — the request now fits under the room.
    assert iwo["withholding_amount_cents"] == 99000
    assert iwo["employer_fee_cents"] == 200
    assert iwo["withholding_amount_cents"] == iwo["requested_amount_cents"]


# ---------------------------------------------------------------------------
# The guideline share ratio
# ---------------------------------------------------------------------------


def test_03_share_ratio_is_rounded_to_four_places_before_it_multiplies_the_basic_obligation():
    """
    The nested rounding order is worth three cents on this worksheet.

    The guideline share ratio is the one intermediate kept as a decimal: it is rounded half up to four decimal places before it is used.

    Design: Difficulty/combinatorial_formula/guideline_ratio_rounded_to_four_dp_before_share
    """
    scenario = _draft_order_on_three_hundred_thousand_combined_income()

    calculated = fx.calculate_order(scenario.order_id)

    assert calculated["status"] == "CALCULATED"
    assert calculated["guideline_cp_income_cents"] == 100000
    assert calculated["guideline_ncp_income_cents"] == 200000
    assert calculated["imputation_applied"] is False
    # Combined 300000 sits in the first band, whose two-child rate is 0.28.
    assert calculated["guideline_basic_obligation_cents"] == 84000
    assert calculated["guideline_ncp_share_ratio"] == 0.6667
    assert calculated["multi_family_credit_cents"] == 0
    # round_half_up(84000 * 0.6667); the 86800 reserve headroom does not bind.
    assert calculated["guideline_monthly_cents"] == 56003
    # The figure an unrounded two-thirds ratio would have produced.
    assert calculated["guideline_monthly_cents"] != 56000
    assert calculated["guideline_monthly_cents"] != 55999


def test_04_entry_carries_the_four_decimal_share_result_onto_the_obligation():
    """
    The three-cent difference survives into the order the obligor must pay.

    Entry sets `monthly_obligation_cents` to `guideline_monthly_cents`, sets `next_accrual_due_date` to the order's `effective_date`, and moves the case `ORDER_ESTABLISHMENT → ENFORCEMENT`, from which point the case is eligible for withholding, enforcement and modification.

    Design: Difficulty/combinatorial_formula/guideline_ratio_rounded_to_four_dp_before_share
    """
    scenario = _draft_order_on_three_hundred_thousand_combined_income()

    fx.calculate_order(scenario.order_id)
    entered = fx.enter_order(scenario.order_id)

    assert entered["status"] == "ENTERED"
    assert entered["guideline_ncp_share_ratio"] == 0.6667
    assert entered["monthly_obligation_cents"] == 56003
    assert entered["monthly_obligation_cents"] == entered["guideline_monthly_cents"]
    assert entered["next_accrual_due_date"] == "2026-08-01"

    order = fx.read_order(scenario.order_id)
    # round_half_up(56003 * 0.20) — the odd cent is carried, not dropped.
    assert order["arrears_recovery_monthly_cents"] == 11201

    charge = fx.post_monthly_charge(scenario.order_id, "2026-08-01", due_day=15)
    assert charge["amount_cents"] == 56003


# ---------------------------------------------------------------------------
# The compromise waiver tier
# ---------------------------------------------------------------------------


def test_05_waiver_tier_is_keyed_on_the_pre_waiver_total_and_never_recomputed():
    """
    The tier is selected once, on the total before the waiver shrinks it.

    The tier is keyed on the pre-waiver total and never recomputed after the waiver has been applied; recomputing it against the reduced total is a self-referential loop that can only produce a smaller waiver than the statute allows.

    Design: Difficulty/combinatorial_formula/compromise_tier_keyed_on_pre_waiver_total
    """
    scenario = _case_ready_to_settle()

    obligor = fx.read_participant(scenario.ncp_id)
    assert obligor["compromise_risk_tier"] == "MEDIUM"
    assert scenario.case["arrears_principal_cents"] == 495000
    assert scenario.case["interest_receivable_cents"] == 8664

    offer = fx.create_compromise_offer(scenario.case_id, installment_count=7)

    assert offer["principal_due_snapshot_cents"] == 495000
    # The aggregate month-end measure valued at 2027-02-01.
    assert offer["interest_due_snapshot_cents"] == 8664
    assert offer["pre_waiver_total_cents"] == 503664
    # 503664 exceeds the 500000 ceiling by 3664, so the 2000000 band applies.
    assert offer["waiver_tier_pct"] == 0.50
    # round_half_up(8664 * 0.50).
    assert offer["interest_waiver_cents"] == 4332
    assert offer["settlement_total_cents"] == 499332
    # The figures a tier re-keyed on the post-waiver total would have produced.
    assert offer["settlement_total_cents"] != 501498
    assert offer["interest_waiver_cents"] != 2166
    assert offer["settlement_total_cents"] >= offer["principal_due_snapshot_cents"]
    assert offer["status"] == "PROPOSED"


def test_06_installment_split_floors_the_recurring_amount_and_pushes_the_remainder_to_the_last():
    """
    Seven installments of the settled total sum back to it exactly.

    `monthly_installment_cents` is `settlement_total_cents` divided by `installment_count`, floored to whole cents, and `final_installment_cents` is `settlement_total_cents` less `monthly_installment_cents` multiplied by one fewer than `installment_count`, so the whole remainder lands entirely on the last installment and the schedule sums to `settlement_total_cents` exactly.

    Design: Difficulty/combinatorial_formula/compromise_tier_keyed_on_pre_waiver_total
    """
    scenario = _case_ready_to_settle()

    offer = fx.create_compromise_offer(scenario.case_id, installment_count=7)

    assert offer["installment_count"] == 7
    assert offer["settlement_total_cents"] == 499332
    # floor(499332 / 7).
    assert offer["monthly_installment_cents"] == 71333
    # 499332 - 71333 * 6.
    assert offer["final_installment_cents"] == 71334
    assert offer["monthly_installment_cents"] * 6 + offer["final_installment_cents"] == 499332
    assert offer["final_installment_cents"] > offer["monthly_installment_cents"]
