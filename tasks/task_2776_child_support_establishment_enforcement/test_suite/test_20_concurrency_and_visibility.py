"""
Version tokens under side effects from elsewhere, and the absence of a read lag.

The two guarded writes are both refused by a token the caller read correctly,
because a different endpoint moved the parent in between — a charge bumps the
order, a payment bumps the case. The sharper half is that each guarded write
bumps its own parent too, so a token accepted one call earlier is already stale.
The last scenario shows every write in a long chain readable on the next call.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import CASE_WORKER_HEADERS, FINANCE_OFFICER_HEADERS


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _entered_order_and_two_minnesota_payrolls() -> Tuple[
    fx.Scenario, Dict[str, Any], Dict[str, Any]
]:
    """
    An entered 75,000 order and two Minnesota employers, neither charging a fee.

    Minnesota has no state ceiling of its own, so the federal 0.60 governs both
    withholding orders and the aggregate check has exactly one percentage in it.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Rosalind Achterberg", "ssn_last4": "6258"},
        ncp_overrides={
            "full_name": "Tobias Achterberg",
            "ssn_last4": "6259",
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
    )
    employer_a = fx.create_employer(
        "MN", legal_name="Achterberg Tooling", fein="41-0000118", remittance_fee_cents=0
    )
    employer_b = fx.create_employer(
        "MN", legal_name="Rainy River Logistics", fein="41-0000119", remittance_fee_cents=0
    )
    return scenario, employer_a, employer_b


def _two_withholding_orders_and_an_arrears_judgment() -> fx.Scenario:
    """
    The same order carrying 225,000 of arrears principal and two live IWOs.

    Both charges are due on the clock date itself, so both count toward the
    arrears principal that the compromise offer will snapshot.
    """
    scenario, employer_a, employer_b = _entered_order_and_two_minnesota_payrolls()
    fx.post_charge(
        scenario.order_id,
        charge_type="CURRENT_SUPPORT",
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-01",
        amount_cents=75000,
    )
    scenario.employer = employer_a
    scenario.withholding_order = fx.issue_withholding_order(
        scenario.order_id, employer_a["id"], reported_disposable_income_cents=150000
    )
    fx.issue_withholding_order(
        scenario.order_id, employer_b["id"], reported_disposable_income_cents=150000
    )
    fx.post_charge(
        scenario.order_id,
        charge_type="ARREARS_JUDGMENT",
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-01",
        amount_cents=150000,
    )
    return scenario


# ---------------------------------------------------------------------------
# The order token: bumped by a charge, then by the guarded write itself
# ---------------------------------------------------------------------------


def test_01_the_order_token_is_spent_by_a_charge_and_then_by_the_issuance_itself():
    """
    One version read, three attempts: 412, accepted, 412 — and each retry converges.

    Issuing an income withholding order, `POST /child-support/orders/{order_id}/withholding-orders`, requires the non-optional field `expected_order_version` in the request body, carrying the client's last observed `version` of the parent `SupportOrder`.

    If that value does not equal the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` and HTTP 412.

    It adds its `amount_cents` to the case's `total_charged_principal_cents` and advances the order's `next_accrual_due_date` by one month, and it increases both the case's and the order's `version` by 1.

    Issuance also increases the parent support order's `version` by 1.

    Design: Corner/cross_cutting_complexity_layers/occ_tokens_are_invalidated_by_side_effects_of_unrelated_writes
    """
    scenario, employer_a, employer_b = _entered_order_and_two_minnesota_payrolls()
    assert scenario.order["monthly_obligation_cents"] == 75000
    assert scenario.order["guideline_monthly_cents"] == 75000

    first_read_version = fx.read_order(scenario.order_id)["version"]
    fx.post_charge(
        scenario.order_id,
        charge_type="CURRENT_SUPPORT",
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-01",
        amount_cents=75000,
    )

    # The token was read correctly; a charge posted through a different endpoint
    # is what invalidated it.
    validate_error(
        api_client.issue_withholding_order(
            scenario.order_id,
            f.withholding_order_payload(employer_a["id"], first_read_version, 150000),
            CASE_WORKER_HEADERS,
        ),
        ApiErrorId.STALE_ORDER_VERSION,
        412,
    )

    after_charge_version = fx.read_order(scenario.order_id)["version"]
    assert after_charge_version == first_read_version + 1

    first_iwo = fx.issue_withholding_order(
        scenario.order_id,
        employer_a["id"],
        reported_disposable_income_cents=150000,
        expected_order_version=after_charge_version,
    )
    assert first_iwo["ccpa_cap_amount_cents"] == 90000
    assert first_iwo["withholding_amount_cents"] == 90000

    # The very token just accepted is now stale, because the accepted issuance
    # moved the same parent.
    validate_error(
        api_client.issue_withholding_order(
            scenario.order_id,
            f.withholding_order_payload(employer_b["id"], after_charge_version, 150000),
            CASE_WORKER_HEADERS,
        ),
        ApiErrorId.STALE_ORDER_VERSION,
        412,
    )

    after_issuance_version = fx.read_order(scenario.order_id)["version"]
    assert after_issuance_version == after_charge_version + 1

    second_iwo = fx.issue_withholding_order(
        scenario.order_id,
        employer_b["id"],
        reported_disposable_income_cents=150000,
        expected_order_version=after_issuance_version,
    )
    assert second_iwo["withholding_amount_cents"] == 90000

    # Two live withholding orders on one support order, so the 412 was a version
    # comparison rather than a one-per-order rule.
    _orders, meta = validate_paginated(
        api_client.list_withholding_orders(
            CASE_WORKER_HEADERS, {"order_id": scenario.order_id}
        )
    )
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# The case token: bumped by a payment, then by the guarded write itself
# ---------------------------------------------------------------------------


def test_02_the_case_token_is_spent_by_a_payment_posted_through_another_endpoint():
    """
    The offer is refused on a token read one call too early, then accepted on a re-read.

    Creating a compromise offer, `POST /child-support/cases/{case_id}/compromise-offers`, requires the non-optional field `expected_case_version` in the request body, carrying the client's last observed `version` of the parent `SupportCase`.

    If that value does not equal the case's current `version`, the request is rejected with `ERR_STALE_CASE_VERSION` and HTTP 412.

    `received_at` is stamped from the logical clock, `iwo_id` is absent on this path, and the payment is allocated and split exactly as above, increasing the case's `version` by 1.

    The new offer is created with `status` `PROPOSED`, `compliance_payment_count` at zero, and `accepted_at`, `next_installment_due_date`, `defaulted_at` and `completed_at` absent, and it increases the case's `version` by 1.

    Design: Corner/cross_cutting_complexity_layers/occ_tokens_are_invalidated_by_side_effects_of_unrelated_writes
    """
    scenario = _two_withholding_orders_and_an_arrears_judgment()
    before_payment = fx.read_case(scenario.case_id)
    assert before_payment["arrears_principal_cents"] == 225000

    payment = fx.post_payment(scenario.case_id, 1000, source="DIRECT_PAY")
    assert payment["applied_current_cents"] == 1000

    validate_error(
        api_client.create_compromise_offer(
            scenario.case_id,
            f.compromise_offer_payload(before_payment["version"], 3),
            FINANCE_OFFICER_HEADERS,
        ),
        ApiErrorId.STALE_CASE_VERSION,
        412,
    )

    after_payment = fx.read_case(scenario.case_id)
    assert after_payment["version"] == before_payment["version"] + 1
    # The refused offer added nothing: only the payment moved the row.
    assert after_payment["arrears_principal_cents"] == 224000

    offer = fx.create_compromise_offer(
        scenario.case_id, 3, expected_case_version=after_payment["version"]
    )
    assert offer["status"] == "PROPOSED"
    assert offer["compliance_payment_count"] == 0

    after_offer = fx.read_case(scenario.case_id)
    assert after_offer["version"] == after_payment["version"] + 1

    _offers, meta = validate_paginated(
        api_client.list_compromise_offers(FINANCE_OFFICER_HEADERS, {"case_id": scenario.case_id})
    )
    assert meta["total_count"] == 1


def test_03_the_terms_frozen_onto_the_accepted_offer_are_the_post_payment_ones():
    """
    224,000 of principal, no interest yet, and a remainder that lands on the last installment.

    `principal_due_snapshot_cents` captures the case's `arrears_principal_cents`.

    `interest_due_snapshot_cents` captures the **aggregate month-end** interest measure valued at the current logical clock date — the settlement figure is a ledger figure, so it uses the ledger's measure and not the certification measure.

    `waiver_tier_pct` is the rate of the first band whose ceiling is at least `pre_waiver_total_cents`: 0.25 up to and including 500,000 cents, 0.50 up to and including 2,000,000 cents, and 0.75 above that with no ceiling.

    `monthly_installment_cents` is `settlement_total_cents` divided by `installment_count`, floored to whole cents, and `final_installment_cents` is `settlement_total_cents` less `monthly_installment_cents` multiplied by one fewer than `installment_count`, so the whole remainder lands entirely on the last installment and the schedule sums to `settlement_total_cents` exactly.

    Design: Corner/cross_cutting_complexity_layers/occ_tokens_are_invalidated_by_side_effects_of_unrelated_writes
    """
    scenario = _two_withholding_orders_and_an_arrears_judgment()
    fx.post_payment(scenario.case_id, 1000, source="DIRECT_PAY")

    offer = fx.create_compromise_offer(scenario.case_id, 3)
    assert offer["principal_due_snapshot_cents"] == 224000
    # The only month end strictly before 2026-08-01 is 2026-07-31, and no charge
    # was due on or before it.
    assert offer["interest_due_snapshot_cents"] == 0
    assert offer["pre_waiver_total_cents"] == 224000
    assert offer["waiver_tier_pct"] == 0.25
    assert offer["interest_waiver_cents"] == 0
    assert offer["settlement_total_cents"] == 224000
    # floor(224000 / 3) twice, and the whole remainder onto the third.
    assert offer["monthly_installment_cents"] == 74666
    assert offer["final_installment_cents"] == 74668
    assert offer["monthly_installment_cents"] * 2 + offer["final_installment_cents"] == 224000


def test_04_the_compromise_screen_lands_at_medium_so_the_only_refusal_was_the_412():
    """
    Payment history at 100 and arrears at 24 average to 46 under the settlement weighting.

    The **arrears component** is the smaller of 100 and the floor of one hundred times the summed `arrears_principal_cents` of those cases divided by the greater of 1 and twelve times the reference obligation.

    The **payment-history component** is 100 minus the floor of one hundred times the summed `total_collected_principal_cents` divided by the greater of 1 and the summed `total_charged_principal_cents`, and it is 0 outright when nothing has been charged.

    The **compromise screen**, written to `compromise_risk_score` and `compromise_risk_tier`, weights payment history at 40, arrears at 25, delinquency at 20 and enforcement history at 15, and weights locate status and interstate exposure at 0.

    Both scores band identically: a score of at least 67 is `HIGH`, a score of at least 34 but below 67 is `MEDIUM`, and anything below 34 is `LOW`.

    Design: Corner/cross_cutting_complexity_layers/occ_tokens_are_invalidated_by_side_effects_of_unrelated_writes
    """
    scenario = _two_withholding_orders_and_an_arrears_judgment()
    fx.post_payment(scenario.case_id, 1000, source="DIRECT_PAY")

    obligor = fx.read_participant(scenario.ncp_id)
    # floor(100 * 224000 / 900000) == 24 for arrears; 100 - floor(100 * 1000 / 225000)
    # == 100 for payment history; both withholding orders are still NOT_DUE, so
    # delinquency is 0 and no enforcement action has ever been proposed.
    assert obligor["compromise_risk_score"] == 46
    assert obligor["compromise_risk_tier"] == "MEDIUM"

    # MEDIUM is what let the offer through: the risk gate never fired.
    offer = fx.create_compromise_offer(scenario.case_id, 3)
    assert offer["status"] == "PROPOSED"
    assert offer["settlement_total_cents"] == 224000


# ---------------------------------------------------------------------------
# The twelve-week bump: one cent of arrears moves the federal rate
# ---------------------------------------------------------------------------


def _two_obligors_one_cent_apart_across_the_bump(
    employer: Dict[str, Any]
) -> Tuple[fx.Scenario, fx.Scenario]:
    """
    Two independent cases whose only difference is one cent of arrears principal.

    The first carries exactly three months of support — 225,000 against a 75,000
    obligation — and the second one cent less. Both charges on each case are due
    on the clock date itself so both count toward the arrears principal.
    """
    on_the_boundary = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Ingeborg Halvorsen", "ssn_last4": "6260"},
        ncp_overrides={
            "full_name": "Nils Halvorsen",
            "ssn_last4": "6261",
            "supports_second_family": False,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
    )
    one_cent_short = fx.case_with_entered_order(
        clock=None,
        cp_overrides={"full_name": "Solveig Nakamura", "ssn_last4": "6262"},
        ncp_overrides={
            "full_name": "Haruto Nakamura",
            "ssn_last4": "6263",
            "supports_second_family": False,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
    )
    for scenario, arrears_amount in ((on_the_boundary, 150000), (one_cent_short, 149999)):
        fx.post_charge(
            scenario.order_id,
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-01",
            amount_cents=75000,
        )
        fx.post_charge(
            scenario.order_id,
            charge_type="ARREARS_JUDGMENT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-01",
            amount_cents=arrears_amount,
        )
        scenario.employer = employer
    return on_the_boundary, one_cent_short


def test_05_one_cent_of_arrears_moves_the_federal_rate_and_six_thousand_of_withholding():
    """
    Identical requests of 90,000 meet a cap of 91,000 on one case and 84,000 on the other.

    `arrears_recovery_cents` is the parent order's `monthly_obligation_cents` multiplied by 0.20 — twenty percent — rounded half up to whole cents, and it is zero when the case has no outstanding arrears principal.

    To that base a further 0.05 — five percentage points — is added when the case's `arrears_principal_cents` is at least three times the order's `monthly_obligation_cents`, which is the statutory twelve-week delinquency bump.

    `ccpa_cap_amount_cents` is the disposable income multiplied by `ccpa_cap_pct`, floored to whole cents — a cap is never rounded upward.

    `withholding_amount_cents` is the smaller of `requested_amount_cents` and that room, and never less than zero.

    Design: Corner/cross_cutting_complexity_layers/arrears_bump_flips_the_federal_cap_at_exactly_three_months_of_support
    """
    employer = fx.create_employer(
        "MN", legal_name="Boundary Waters Assembly", fein="41-0000120", remittance_fee_cents=0
    )
    on_the_boundary, one_cent_short = _two_obligors_one_cent_apart_across_the_bump(employer)

    assert on_the_boundary.order["monthly_obligation_cents"] == 75000
    assert one_cent_short.order["monthly_obligation_cents"] == 75000
    assert fx.read_case(on_the_boundary.case_id)["arrears_principal_cents"] == 225000
    assert fx.read_case(one_cent_short.case_id)["arrears_principal_cents"] == 224999

    bumped = fx.issue_withholding_order(
        on_the_boundary.order_id, employer["id"], reported_disposable_income_cents=140000
    )
    unbumped = fx.issue_withholding_order(
        one_cent_short.order_id, employer["id"], reported_disposable_income_cents=140000
    )

    # The request is keyed on the obligation, so it is identical on both sides.
    for iwo in (bumped, unbumped):
        assert iwo["arrears_recovery_cents"] == 15000
        assert iwo["requested_amount_cents"] == 90000

    # 225000 is exactly three times 75000, and the test is "at least".
    assert bumped["federal_cap_pct"] == 0.65
    assert bumped["ccpa_cap_pct"] == 0.65
    assert bumped["ccpa_cap_amount_cents"] == 91000
    assert bumped["withholding_amount_cents"] == 90000

    assert unbumped["federal_cap_pct"] == 0.60
    assert unbumped["ccpa_cap_pct"] == 0.60
    assert unbumped["ccpa_cap_amount_cents"] == 84000
    assert unbumped["withholding_amount_cents"] == 84000

    assert bumped["withholding_amount_cents"] - unbumped["withholding_amount_cents"] == 6000


def test_06_the_threshold_is_re_read_on_amendment_rather_than_frozen_at_issuance():
    """
    A cent of arrears added after service lifts the served order to the bumped figure.

    It recomputes `ccpa_cap_pct`, `ccpa_cap_amount_cents`, `withholding_amount_cents` and `employer_fee_cents` through the same four movements, re-checks the aggregate ceiling, and increases the order's `version` by 1.

    `remittance_status` is untouched, because the two dimensions are independent.

    To that base a further 0.05 — five percentage points — is added when the case's `arrears_principal_cents` is at least three times the order's `monthly_obligation_cents`, which is the statutory twelve-week delinquency bump.

    Design: Corner/cross_cutting_complexity_layers/arrears_bump_flips_the_federal_cap_at_exactly_three_months_of_support
    """
    employer = fx.create_employer(
        "MN", legal_name="Boundary Waters Assembly", fein="41-0000120", remittance_fee_cents=0
    )
    on_the_boundary, one_cent_short = _two_obligors_one_cent_apart_across_the_bump(employer)
    bumped = fx.issue_withholding_order(
        on_the_boundary.order_id, employer["id"], reported_disposable_income_cents=140000
    )
    unbumped = fx.issue_withholding_order(
        one_cent_short.order_id, employer["id"], reported_disposable_income_cents=140000
    )
    assert unbumped["withholding_amount_cents"] == 84000

    served = fx.serve_withholding_order(unbumped["id"])
    assert served["service_status"] == "SERVED"
    assert served["remittance_status"] == "NOT_DUE"

    # One cent of a different charge type, on the same month, crosses the boundary.
    fx.post_charge(
        one_cent_short.order_id,
        charge_type="MEDICAL_SUPPORT",
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-01",
        amount_cents=1,
    )
    assert fx.read_case(one_cent_short.case_id)["arrears_principal_cents"] == 225000

    amended = fx.amend_withholding_order(unbumped["id"], 140001)
    assert amended["id"] == unbumped["id"]
    assert amended["service_status"] == "AMENDED"
    assert amended["remittance_status"] == "NOT_DUE"
    assert amended["federal_cap_pct"] == 0.65
    assert amended["ccpa_cap_pct"] == 0.65
    # floor(140001 * 0.60) is still 84000, so the extra cent of income cannot be
    # what moved the figure; floor(140001 * 0.65) is 91000.
    assert amended["ccpa_cap_amount_cents"] == 91000
    assert amended["withholding_amount_cents"] == 90000

    untouched = fx.read_withholding_order(bumped["id"])
    assert untouched["withholding_amount_cents"] == 90000
    assert untouched["service_status"] == "ISSUED"


# ---------------------------------------------------------------------------
# One payment, four read surfaces, no convergence window
# ---------------------------------------------------------------------------


def _one_month_charged_and_nothing_collected() -> Tuple[fx.Scenario, Dict[str, Any]]:
    """
    An entered 75,000 order carrying one current-support charge for August.

    The charge is due on the clock date itself, so it counts toward the case's
    arrears principal before any money arrives.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Beatrix Lindqvist", "ssn_last4": "6264"},
        ncp_overrides={
            "full_name": "Emil Lindqvist",
            "ssn_last4": "6265",
            "supports_second_family": False,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
    )
    charge = fx.post_charge(
        scenario.order_id,
        charge_type="CURRENT_SUPPORT",
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-01",
        amount_cents=75000,
    )
    scenario.charges.append(charge)
    return scenario, charge


def test_07_the_write_answers_with_the_allocation_and_both_rows_already_agree():
    """
    A 201 carrying the finished split, and the parent and child rows moved with it.

    **Bucket one, current support for the current period**: the `OPEN` `CURRENT_SUPPORT` charges of the case whose period contains the payment's `received_at` date — that is, `period_start_date` less than or equal to that date and `period_end_date` strictly greater — are taken in order of `due_date` and then `created_at`, and each absorbs the smaller of the remaining balance and its own `unpaid_balance_cents`, accumulating into `applied_current_cents`.

    On a non-assistance case the family receives current support, medical support and arrears: `disbursed_to_cp_cents` is `applied_current_cents` plus `applied_medical_cents` plus `applied_arrears_cents`, and `retained_by_state_cents` is `applied_interest_cents` plus `applied_genetic_cost_cents`.

    A new charge is created with `status` `OPEN`, `unpaid_balance_cents` equal to `amount_cents`, `paid_cents` at zero and `interest_accrued_cents` at zero.

    Reading a case is likewise a computing read: `arrears_principal_cents`, `assigned_arrears_cents`, `unassigned_arrears_cents` and `interest_receivable_cents` are all recomputed before the row is returned, with `arrears_principal_cents` defined as the sum of `unpaid_balance_cents` across the case's charges whose `status` is `OPEN` and whose `due_date` falls on or before the current logical clock date.

    Design: Corner/consistency_model/every_write_is_readable_immediately_with_no_convergence_window
    """
    scenario, charge = _one_month_charged_and_nothing_collected()
    before = fx.read_case(scenario.case_id)
    assert scenario.order["monthly_obligation_cents"] == 75000
    assert before["arrears_principal_cents"] == 75000

    payment = validate_success(
        api_client.post_payment(
            scenario.case_id,
            f.payment_payload(30000, source="DIRECT_PAY"),
            FINANCE_OFFICER_HEADERS,
        ),
        201,
    )
    assert payment["applied_current_cents"] == 30000
    assert payment["applied_arrears_cents"] == 0
    assert payment["applied_interest_cents"] == 0
    assert payment["unapplied_credit_cents"] == 0
    assert payment["disbursed_to_cp_cents"] == 30000
    assert payment["retained_by_state_cents"] == 0

    after = fx.read_case(scenario.case_id)
    assert after["arrears_principal_cents"] == 45000
    assert after["interest_receivable_cents"] == 0
    assert after["version"] == before["version"] + 1

    moved = validate_success(api_client.get_charge(charge["id"], FINANCE_OFFICER_HEADERS))
    assert moved["paid_cents"] == 30000
    assert moved["unpaid_balance_cents"] == 45000
    # 45000 is not zero, so the charge did not reach `SATISFIED`.
    assert moved["status"] == "OPEN"


def test_08_the_index_the_row_and_the_computed_ledger_all_agree_on_the_next_call():
    """
    Four surfaces, one figure each, and a second read of each changes nothing.

    Payments are readable individually with their full allocation breakdown, and listable filtered by case, by withholding order and by compromise offer, so that all three foreign keys are reverse-reachable.

    The ledger read reports both measures side by side — `statutory_interest_cents` and `aggregate_interest_cents` — together with `interest_written_off_cents`, `interest_collected_cents`, `interest_receivable_cents`, `arrears_principal_cents`, `assigned_arrears_cents`, `unassigned_arrears_cents` and `unapplied_credit_cents`, and it accepts an optional `as_of_date` to value the ledger at a past or future date without mutating anything.

    Third, ordering is by `due_date` and then `created_at` — the random identifier is never a tie-break — and there is no rounding anywhere in the waterfall, because every bucket takes a minimum of two integers, so the applied buckets plus the unapplied credit sum to `amount_cents` exactly.

    Design: Corner/consistency_model/every_write_is_readable_immediately_with_no_convergence_window
    """
    scenario, charge = _one_month_charged_and_nothing_collected()
    payment = fx.post_payment(scenario.case_id, 30000, source="DIRECT_PAY")
    assert payment["applied_current_cents"] + payment["unapplied_credit_cents"] == 30000

    payments, meta = validate_paginated(
        api_client.list_payments(FINANCE_OFFICER_HEADERS, {"case_id": scenario.case_id})
    )
    assert meta["total_count"] == 1
    assert payments[0]["id"] == payment["id"]

    reread = validate_success(api_client.get_payment(payment["id"], FINANCE_OFFICER_HEADERS))
    assert reread["applied_current_cents"] == 30000
    assert reread["disbursed_to_cp_cents"] == 30000

    ledger = fx.read_ledger(scenario.case_id)
    assert ledger["arrears_principal_cents"] == 45000
    assert ledger["statutory_interest_cents"] == 0
    assert ledger["aggregate_interest_cents"] == 0
    assert ledger["unapplied_credit_cents"] == 0

    # Reading everything a second time returns the same figures, so nothing was
    # still settling behind the first read.
    first_case = fx.read_case(scenario.case_id)
    second_case = fx.read_case(scenario.case_id)
    assert second_case["version"] == first_case["version"]
    assert second_case["arrears_principal_cents"] == first_case["arrears_principal_cents"] == 45000
    second_charge = validate_success(api_client.get_charge(charge["id"], FINANCE_OFFICER_HEADERS))
    assert second_charge["unpaid_balance_cents"] == 45000
    assert fx.read_ledger(scenario.case_id)["arrears_principal_cents"] == 45000
