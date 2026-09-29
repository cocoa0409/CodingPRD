"""
Values that sit exactly on a documented edge, and one cent either side of it.

Each scenario is arranged so the metric under test lands on the boundary itself,
on the last value below it, or on the empty set at the bottom of a loop, which is
where an off-by-one comparison or a floating-point intermediate shows itself.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import CASE_WORKER_HEADERS


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _case_certified_one_hundred_and_forty_five_cents_short() -> fx.Scenario:
    """
    Principal of 298,000 cents at 2026-11-01, made of three monthly charges of
    75,000 cents due on the 15th and one arrears judgment of 73,000 cents.

    The two interest measures diverge sharply here: the per-charge statutory
    figure is 1,855 cents and the ledger's aggregate figure is 3,345, which is
    the difference between refusing a licence suspension and granting one.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Fay Gorman",
            "ssn_last4": "2020",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Gil Gorman",
            "ssn_last4": "2121",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
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
        ["2026-08-01", "2026-09-01", "2026-10-01"],
        due_day=15,
    )
    scenario.charges.append(
        fx.post_charge(
            scenario.order_id,
            charge_type="ARREARS_JUDGMENT",
            period_start_date="2026-01-01",
            period_end_date="2026-08-16",
            due_date="2026-08-15",
            amount_cents=73000,
        )
    )
    fx.set_clock("2026-11-01T00:00:00Z")
    scenario.case = fx.run_accrual(scenario.case_id)
    return scenario


def _entered_order_with_no_charges_at_all() -> fx.Scenario:
    """An entered order at 75,000 cents against which nothing has been charged."""
    return fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Hana Iyer",
            "ssn_last4": "2222",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Ish Iyer",
            "ssn_last4": "2323",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )


def _review_on_a_fifteen_percent_income_drop() -> fx.Scenario:
    """
    An order entered at 75,000 cents, both incomes then restated downward so the
    worksheet re-runs to 63,750 cents, and a party-requested review opened on it.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Jo Kwan",
            "ssn_last4": "2424",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Kai Kwan",
            "ssn_last4": "2525",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    fx.patch_income(scenario.cp_id, 170000, "VERIFIED_WAGE_RECORD")
    fx.patch_income(scenario.ncp_id, 255000, "VERIFIED_WAGE_RECORD")
    scenario.modification_review = fx.open_modification_review(
        scenario.order_id, "PARTY_REQUEST"
    )
    return scenario


# ---------------------------------------------------------------------------
# The certification gate, 145 cents below and exactly on the threshold
# ---------------------------------------------------------------------------


def test_01_certification_uses_the_statutory_measure_and_lands_below_the_threshold():
    """
    The ledger's own interest figure would have cleared the gate; certification's
    does not.

    `arrears_certified_snapshot_cents` is the case's `arrears_principal_cents` plus the **statutory per-charge** interest measure valued at the current logical clock date — certification always uses the statutory measure, never the ledger's aggregate measure, which is precisely why a certified balance can differ from the balance the ledger read shows for the same case at the same instant.

    Design: Difficulty/boundary_precision_check/enforcement_threshold_boundary_denies_at_statutory_interest
    """
    scenario = _case_certified_one_hundred_and_forty_five_cents_short()

    assert scenario.order["monthly_obligation_cents"] == 75000
    assert scenario.case["arrears_principal_cents"] == 298000
    assert scenario.case["interest_receivable_cents"] == 3345

    ledger = fx.read_ledger(scenario.case_id)
    assert ledger["statutory_interest_cents"] == 1855
    assert ledger["aggregate_interest_cents"] == 3345
    # 298000 + 1855 = 299855, while 298000 + 3345 = 301345 would have cleared.
    assert ledger["arrears_principal_cents"] + ledger["statutory_interest_cents"] == 299855

    response = api_client.propose_enforcement_action(
        scenario.case_id,
        f.enforcement_action_payload("LICENSE_SUSPENSION"),
        CASE_WORKER_HEADERS,
    )
    validate_error(response, ApiErrorId.ARREARS_BELOW_ENFORCEMENT_THRESHOLD.value, 409)


def test_02_the_same_certified_balance_clears_a_remedy_with_a_lower_threshold():
    """
    299,855 cents is short of one threshold and comfortably past another.

    `eligibility_threshold_cents` is the threshold the remedy had to clear, and it is fixed per remedy: 300,000 cents for `LICENSE_SUSPENSION`, 500,000 cents for `PROPERTY_LIEN`, 1,000,000 cents for `CONTEMPT_REFERRAL`, and 100,000 cents for `CREDIT_BUREAU_REPORT`.

    Design: Difficulty/boundary_precision_check/enforcement_threshold_boundary_denies_at_statutory_interest
    """
    scenario = _case_certified_one_hundred_and_forty_five_cents_short()

    action = fx.propose_enforcement_action(scenario.case_id, "CREDIT_BUREAU_REPORT")

    assert action["status"] == "PROPOSED"
    assert action["eligibility_threshold_cents"] == 100000
    # The statutory measure, not 298000 + 3345.
    assert action["arrears_certified_snapshot_cents"] == 299855


def test_03_one_extra_charge_that_accrues_nothing_lands_exactly_on_the_threshold():
    """
    A 145-cent charge due after the last full month makes the total 300,000 flat.

    Both gates compare with "at least", so a certified balance exactly equal to a threshold *is* eligible.

    Design: Difficulty/boundary_precision_check/enforcement_threshold_boundary_denies_at_statutory_interest
    """
    scenario = _case_certified_one_hundred_and_forty_five_cents_short()

    fx.post_charge(
        scenario.order_id,
        charge_type="ARREARS_JUDGMENT",
        period_start_date="2026-10-01",
        period_end_date="2026-11-01",
        due_date="2026-10-15",
        amount_cents=145,
    )
    assert fx.read_case(scenario.case_id)["arrears_principal_cents"] == 298145

    action = fx.propose_enforcement_action(scenario.case_id, "LICENSE_SUSPENSION")

    assert action["status"] == "PROPOSED"
    assert action["eligibility_threshold_cents"] == 300000
    # 298145 principal plus the unchanged 1855 of statutory interest.
    assert action["arrears_certified_snapshot_cents"] == 300000
    assert action["remedy_applied"] is False


# ---------------------------------------------------------------------------
# The waterfall against an empty charge set
# ---------------------------------------------------------------------------


def test_04_a_payment_against_a_case_with_no_charges_is_all_unapplied_credit():
    """
    Every bucket iterates an empty set and the last one absorbs the whole 60,000.

    `VOID` and `SATISFIED` charges are skipped entirely, and a case with no `OPEN` charges at all does not reject the money: the whole payment falls through to unapplied credit.

    Design: Difficulty/boundary_precision_check/payment_to_case_with_no_open_charges_is_all_unapplied_credit
    """
    scenario = _entered_order_with_no_charges_at_all()

    assert scenario.case["total_charged_principal_cents"] == 0
    assert scenario.case["arrears_principal_cents"] == 0

    payment = fx.post_payment(scenario.case_id, 60000, source="DIRECT_PAY")

    assert payment["applied_current_cents"] == 0
    assert payment["applied_medical_cents"] == 0
    assert payment["applied_arrears_cents"] == 0
    assert payment["applied_interest_cents"] == 0
    assert payment["applied_genetic_cost_cents"] == 0
    assert payment["unapplied_credit_cents"] == 60000

    settled = fx.read_case(scenario.case_id)
    assert settled["unapplied_credit_cents"] == 60000
    assert settled["arrears_principal_cents"] == 0


def test_05_the_distribution_split_holds_its_invariant_with_nothing_distributable():
    """
    Nothing was applied, so nothing is disbursed and nothing is retained.

    Both branches are exact integer arithmetic with no rounding step, and both satisfy the same invariant: `disbursed_to_cp_cents` plus `retained_by_state_cents` plus the payment's `unapplied_credit_cents` equals `amount_cents`.

    Design: Difficulty/boundary_precision_check/payment_to_case_with_no_open_charges_is_all_unapplied_credit
    """
    scenario = _entered_order_with_no_charges_at_all()

    payment = fx.post_payment(scenario.case_id, 60000, source="DIRECT_PAY")

    assert payment["disbursed_to_cp_cents"] == 0
    assert payment["retained_by_state_cents"] == 0
    assert (
        payment["disbursed_to_cp_cents"]
        + payment["retained_by_state_cents"]
        + payment["unapplied_credit_cents"]
        == 60000
    )
    # No interest bucket ran, so the case's collected-interest counter is untouched.
    assert fx.read_case(scenario.case_id)["interest_collected_cents"] == 0


# ---------------------------------------------------------------------------
# The substantial-change gate at exactly fifteen percent
# ---------------------------------------------------------------------------


def test_06_a_variance_of_exactly_fifteen_percent_meets_the_threshold():
    """
    11,250 against 75,000 is 15.00% to the cent, and the review must pass.

    The **relative gate** asks whether the variance is at least fifteen percent of the snapshot, and it is evaluated by integer cross-multiplication — the absolute difference multiplied by 10,000 compared against 1,500 multiplied by the snapshot — so no floating-point rounding can shift the boundary, and because the comparison is "at least", a variance of exactly 15.00% qualifies.

    Design: Difficulty/boundary_precision_check/substantial_change_variance_at_exactly_fifteen_percent
    """
    scenario = _review_on_a_fifteen_percent_income_drop()

    assert scenario.order["guideline_monthly_cents"] == 75000
    assert scenario.order["guideline_ncp_share_ratio"] == 0.6
    assert scenario.modification_review["status"] == "REQUESTED"

    screened = fx.screen_modification_review(scenario.modification_review["id"])

    assert screened["recalculated_guideline_cents"] == 63750
    assert screened["variance_numerator_cents"] == 11250
    assert 11250 * 10000 == 1500 * 75000
    assert screened["substantial_change_met"] is True
    assert screened["status"] == "THRESHOLD_MET"
    a.assert_instant_equals(screened["screened_at"], "2026-08-01T00:00:00Z", "screened_at")


def test_07_the_variance_is_measured_against_the_snapshot_taken_at_creation():
    """
    Both gates are required on a party request, and both are met here.

    `variance_numerator_cents` is the absolute difference between that recalculated figure and `current_obligation_snapshot_cents`.

    The **absolute gate** asks whether the variance is at least 5,000 cents, fifty dollars.

    A `PARTY_REQUEST` or `PA_MANDATORY` review must clear **both** gates together.

    Design: Difficulty/boundary_precision_check/substantial_change_variance_at_exactly_fifteen_percent
    """
    scenario = _review_on_a_fifteen_percent_income_drop()

    assert scenario.modification_review["trigger_type"] == "PARTY_REQUEST"
    assert scenario.modification_review["current_obligation_snapshot_cents"] == 75000
    assert scenario.modification_review["info_request_count"] == 0

    screened = fx.screen_modification_review(scenario.modification_review["id"])

    assert screened["current_obligation_snapshot_cents"] == 75000
    assert (
        abs(screened["recalculated_guideline_cents"] - 75000)
        == screened["variance_numerator_cents"]
    )
    # 11250 also clears the fifty-dollar floor, so the party request passes both.
    assert screened["variance_numerator_cents"] >= 5000
    assert screened.get("info_requested_reason") is None
    assert screened["info_request_count"] == 0
    # Screening reports on the order without rewriting it.
    assert fx.read_order(scenario.order_id)["monthly_obligation_cents"] == 75000
