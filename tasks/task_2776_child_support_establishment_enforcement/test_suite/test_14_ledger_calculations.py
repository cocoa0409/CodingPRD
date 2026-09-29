"""
The money engines: the interest input set, the payment waterfall, the withholding
ceiling and the controlling-order ranking.

Each scenario is built so the figure under test is the only one that can explain
the result — a charge leaves the interest input set retroactively, one payment
overflows all six waterfall buckets at once, an employer fee eats a cap to the
last cent, and three decoy orders sit around the one candidate that can win.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import CASE_WORKER_HEADERS, FINANCE_OFFICER_HEADERS

#: The three due dates the interest scenarios age to 2026-11-01, each mapped to
#: the calendar month its charge covers.
CHARGE_PERIODS = {
    "2026-08-15": ("2026-08-01", "2026-09-01"),
    "2026-09-15": ("2026-09-01", "2026-10-01"),
    "2026-10-15": ("2026-10-01", "2026-11-01"),
}
OLDEST_FIRST = ["2026-08-15", "2026-09-15", "2026-10-15"]
NEWEST_FIRST = ["2026-10-15", "2026-09-15", "2026-08-15"]


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _entered_order_at_seventy_five_thousand(
    ssn_cp: str, ssn_ncp: str, **order_overrides: Any
) -> fx.Scenario:
    """An entered two-child order of 75,000 cents effective 2026-08-01."""
    overrides: Dict[str, Any] = {
        "origin_state_code": "MN",
        "effective_date": "2026-08-01",
        "medical_support_monthly_cents": 0,
    }
    overrides.update(order_overrides)
    return fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Marta Vandeveld",
            "ssn_last4": ssn_cp,
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Piet Vandeveld",
            "ssn_last4": ssn_ncp,
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={
            "child_count": 2,
            "tanf_assistance": False,
            "good_cause_claim": False,
        },
        order_overrides=overrides,
    )


def _three_charges_aged_to_november(due_dates: List[str]) -> fx.Scenario:
    """
    Three 75,000-cent current-support charges posted in the given due-date order
    and then aged to 2026-11-01 with all three still `OPEN`.
    """
    scenario = _entered_order_at_seventy_five_thousand("6141", "6142")
    scenario.charges = []
    for due in due_dates:
        period_start, period_end = CHARGE_PERIODS[due]
        scenario.charges.append(
            fx.post_charge(
                scenario.order_id,
                charge_type="CURRENT_SUPPORT",
                period_start_date=period_start,
                period_end_date=period_end,
                due_date=due,
            )
        )
    fx.set_clock("2026-11-01T00:00:00Z")
    scenario.reload_case()
    return scenario


def _genetic_inclusion_with_all_three_charge_kinds() -> fx.Scenario:
    """
    A genetic-test paternity action carried to an inclusion — so the 48,000-cent
    test cost is billed to the obligor — beside an entered order of 75,000 plus
    20,000 of medical support and one charge of each kind.

    The clock rests at 2026-09-20, inside the September period and one month end
    past the arrears judgment, so every waterfall bucket has something to take.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Odile Marchetti",
            "ssn_last4": "6151",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Enzo Marchetti",
            "ssn_last4": "6152",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    action = fx.open_paternity_action(scenario.case_id, "GENETIC_TEST")
    fx.order_genetic_test(action["id"], "2026-08-05T00:00:00Z")
    fx.set_clock("2026-08-05T00:00:00Z")
    fx.collect_specimen(action["id"], True)
    scenario.paternity_action = fx.record_genetic_result(action["id"], 99.5)

    order = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="MN",
        effective_date="2026-08-01",
        medical_support_monthly_cents=20000,
    )
    fx.calculate_order(order["id"])
    scenario.order = fx.enter_order(order["id"])
    scenario.charges = [
        fx.post_charge(
            scenario.order_id,
            charge_type="ARREARS_JUDGMENT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-15",
            amount_cents=30000,
        ),
        fx.post_charge(
            scenario.order_id,
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-09-01",
            period_end_date="2026-10-01",
            due_date="2026-09-01",
        ),
        fx.post_charge(
            scenario.order_id,
            charge_type="MEDICAL_SUPPORT",
            period_start_date="2026-09-01",
            period_end_date="2026-10-01",
            due_date="2026-09-01",
        ),
    ]
    fx.set_clock("2026-09-20T00:00:00Z")
    scenario.reload_case()
    return scenario


def _order_beside_an_employer_whose_fee_eats_the_cap() -> fx.Scenario:
    """
    An entered order of 75,000 cents with no charges at all — so the case carries
    no arrears principal — and one Minnesota employer charging a 500-cent
    remittance fee, which is more than sixty percent of a near-empty paycheque.
    """
    scenario = _entered_order_at_seventy_five_thousand("6161", "6162")
    scenario.employer = fx.create_employer(
        state_code="MN", legal_name="Shorewood Cannery", remittance_fee_cents=500
    )
    return scenario


def _four_orders_of_which_only_one_can_control() -> Tuple[fx.Scenario, Dict[str, Any]]:
    """
    One case carrying an entered Minnesota medical order effective 2026-05-01, a
    vacated Wisconsin support order of 2026-06-01, a merely calculated Wisconsin
    support order of 2026-06-15 and an entered Wisconsin support order of
    2026-07-01 — the only candidate the ranking may consider.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Talia Brenner",
            "ssn_last4": "6171",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Ivo Brenner",
            "ssn_last4": "6172",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    fx.open_paternity_action(scenario.case_id, "PRESUMED_MARITAL")

    medical = fx.draft_order(
        scenario.case_id,
        order_type="MEDICAL_SUPPORT",
        origin_state_code="MN",
        effective_date="2026-05-01",
        medical_support_monthly_cents=20000,
    )
    fx.calculate_order(medical["id"])
    medical = fx.enter_order(medical["id"])

    vacated = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="WI",
        effective_date="2026-06-01",
    )
    fx.calculate_order(vacated["id"])
    fx.enter_order(vacated["id"])
    vacated = fx.vacate_order(vacated["id"], "CLERICAL_ERROR")

    calculated = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="WI",
        effective_date="2026-06-15",
    )
    calculated = fx.calculate_order(calculated["id"])

    winner = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="WI",
        effective_date="2026-07-01",
    )
    fx.calculate_order(winner["id"])
    scenario.order = fx.enter_order(winner["id"])

    decoys = {"medical": medical, "vacated": vacated, "calculated": calculated}
    return scenario, decoys


# ---------------------------------------------------------------------------
# Two exits from the interest input set, both retroactive
# ---------------------------------------------------------------------------


def test_01_voiding_the_oldest_charge_erases_interest_already_posted_for_earlier_months():
    """
    The receivable falls from 2,250 to 1,125 although only the oldest charge left.

    The **aggregate month-end measure** instead walks every calendar month-end date falling strictly before the as-of date. At each such snapshot it sums the `unpaid_balance_cents` of every charge in the input set whose `due_date` falls on or before that snapshot date, multiplies that pooled balance by the monthly rate of 0.005, rounds the product half up to whole cents, and adds it to a running total.

    Charges in `VOID` and charges in `SATISFIED` are excluded entirely and retroactively — once a charge is satisfied it contributes nothing to either measure, including for month-end snapshots that predate the payment that satisfied it.

    Design: Corner/calculations/void_and_satisfied_charges_leave_the_interest_input_set
    """
    scenario = _three_charges_aged_to_november(OLDEST_FIRST)

    # Pools of 75000, 150000 and 225000 at the three month ends before 11-01.
    assert scenario.case["interest_receivable_cents"] == 2250
    assert scenario.case["arrears_principal_cents"] == 225000
    # Certification adds the statutory 750 + 375 + 0 instead.
    assert fx.read_participant(scenario.ncp_id)["total_arrears_certified_cents"] == 226125

    voided = fx.void_charge(scenario.charges[0]["id"])
    assert voided["status"] == "VOID"

    after = fx.read_case(scenario.case_id)
    # The voided charge leaves all three pools: 0 + 375 + 750.
    assert after["interest_receivable_cents"] == 1125
    assert after["arrears_principal_cents"] == 150000
    assert fx.read_participant(scenario.ncp_id)["total_arrears_certified_cents"] == 150375


def test_02_an_exact_payment_satisfies_a_charge_and_takes_its_earlier_snapshots_with_it():
    """
    The second exit is a satisfaction, and it removes interest the same way.

    A participant's `total_arrears_certified_cents` is the sum, over every `SupportCase` whose `noncustodial_party_id` is that participant and whose `case_status` is anything other than `CLOSED`, of that case's `arrears_principal_cents` plus that case's per-charge statutory interest total.

    A charge that has been outstanding for less than one whole calendar month contributes exactly zero.

    Design: Corner/calculations/void_and_satisfied_charges_leave_the_interest_input_set
    """
    scenario = _three_charges_aged_to_november(OLDEST_FIRST)
    fx.void_charge(scenario.charges[0]["id"])

    payment = fx.post_payment(scenario.case_id, 75000, source="DIRECT_PAY")

    # 2026-11-01 lies outside every charge period, so bucket one is empty.
    assert payment["applied_current_cents"] == 0
    # Bucket three takes the oldest surviving charge in full.
    assert payment["applied_arrears_cents"] == 75000
    assert payment["applied_interest_cents"] == 0

    satisfied = fx.read_charge(scenario.charges[1]["id"])
    assert satisfied["status"] == "SATISFIED"
    assert satisfied["paid_cents"] == 75000

    after = fx.read_case(scenario.case_id)
    # Only the 10-15 charge survives, and only the 10-31 pool holds it.
    assert after["interest_receivable_cents"] == 375
    assert after["arrears_principal_cents"] == 75000
    # 2026-10-15 to 2026-11-01 is not one whole month, so nothing is certified.
    assert fx.read_participant(scenario.ncp_id)["total_arrears_certified_cents"] == 75000


# ---------------------------------------------------------------------------
# One payment large enough to show all six buckets at once
# ---------------------------------------------------------------------------


def test_03_a_two_hundred_thousand_cent_payment_overflows_every_bucket_in_turn():
    """
    Current, medical, arrears, interest, the genetic cost and then credit.

    **Bucket two, current medical support**: the identical loop over `MEDICAL_SUPPORT` charges in the same period window, accumulating into `applied_medical_cents`.

    **Bucket three, arrears principal**: every remaining `OPEN` charge of the case that buckets one and two did not consume, taken oldest `due_date` first and then `created_at`, each absorbing the smaller of the remaining balance and its own `unpaid_balance_cents`, accumulating into `applied_arrears_cents`.

    Second, interest sits *below* arrears principal, which means only a payment large enough to clear all outstanding principal ever touches interest at all.

    Design: Corner/calculations/waterfall_fills_current_then_medical_then_arrears_then_interest_then_genetic_cost
    """
    scenario = _genetic_inclusion_with_all_three_charge_kinds()

    assert scenario.order["monthly_obligation_cents"] == 75000
    assert scenario.paternity_action["genetic_cost_cents"] == 48000
    assert scenario.paternity_action["genetic_cost_liable_party"] == "NCP"

    payment = fx.post_payment(scenario.case_id, 200000, source="DIRECT_PAY")

    # The only current-support charge whose period contains 2026-09-20.
    assert payment["applied_current_cents"] == 75000
    assert payment["applied_medical_cents"] == 20000
    # The oldest charge on the case, and it is still paid third.
    assert payment["applied_arrears_cents"] == 30000
    # 08-31 is the only month end before 2026-09-20: 30000 * 0.005.
    assert payment["applied_interest_cents"] == 150
    assert payment["applied_genetic_cost_cents"] == 48000
    assert payment["unapplied_credit_cents"] == 26850


def test_04_the_non_assistance_split_sends_principal_home_and_keeps_the_rest():
    """
    125,000 reaches the family, 48,150 stays with the state, and nothing rounds.

    On a non-assistance case the family receives current support, medical support and arrears: `disbursed_to_cp_cents` is `applied_current_cents` plus `applied_medical_cents` plus `applied_arrears_cents`, and `retained_by_state_cents` is `applied_interest_cents` plus `applied_genetic_cost_cents`.

    Both branches are exact integer arithmetic with no rounding step, and both satisfy the same invariant: `disbursed_to_cp_cents` plus `retained_by_state_cents` plus the payment's `unapplied_credit_cents` equals `amount_cents`.

    **Bucket six**: whatever is still unabsorbed becomes the payment's `unapplied_credit_cents` and is added to the case's `unapplied_credit_cents`.

    Design: Corner/calculations/waterfall_fills_current_then_medical_then_arrears_then_interest_then_genetic_cost
    """
    scenario = _genetic_inclusion_with_all_three_charge_kinds()
    assert scenario.case["tanf_assistance"] is False

    payment = fx.post_payment(scenario.case_id, 200000, source="DIRECT_PAY")

    assert payment["disbursed_to_cp_cents"] == 125000
    assert payment["retained_by_state_cents"] == 48150
    assert (
        payment["disbursed_to_cp_cents"]
        + payment["retained_by_state_cents"]
        + payment["unapplied_credit_cents"]
        == 200000
    )

    after = fx.read_case(scenario.case_id)
    assert after["interest_collected_cents"] == 150
    assert after["unapplied_credit_cents"] == 26850
    # Every charge on the case is satisfied now.
    assert after["arrears_principal_cents"] == 0


# ---------------------------------------------------------------------------
# Insertion order is the exact reverse of due-date order, and nothing notices
# ---------------------------------------------------------------------------


def test_05_the_accrual_walks_due_dates_even_when_the_rows_were_posted_backwards():
    """
    Posted newest first, the three charges still accrue 750, 375 and nothing.

    The run writes each `OPEN` charge's `interest_accrued_cents` from the per-charge statutory measure, recomputes the case's `interest_receivable_cents` as the aggregate month-end measure less `interest_written_off_cents` less `interest_collected_cents`, and increases the case's `version` by 1.

    The **per-charge statutory measure** walks the input set ordered by `due_date` and then by `created_at`, and for each charge computes the number of whole calendar months between that charge's own `due_date` and the as-of date, multiplies the charge's `unpaid_balance_cents` by the monthly rate of 0.005 and by that month count, rounds the product half up to whole cents, and adds it to a running total.

    Design: Corner/calculations/out_of_order_charge_creation_still_accrues_by_due_date
    """
    scenario = _three_charges_aged_to_november(NEWEST_FIRST)
    newest, middle, oldest = scenario.charges

    settled = fx.run_accrual(scenario.case_id)
    assert settled["arrears_principal_cents"] == 225000

    # 2026-08-15 to 2026-11-01 is two whole months, not the three calendar
    # months the month numbers suggest, because the 1st precedes the 15th.
    assert fx.read_charge(oldest["id"])["interest_accrued_cents"] == 750
    assert fx.read_charge(middle["id"])["interest_accrued_cents"] == 375
    # 2026-10-15 to 2026-11-01 is no whole month at all.
    assert fx.read_charge(newest["id"])["interest_accrued_cents"] == 0
    assert fx.read_charge(oldest["id"])["due_date"] == "2026-08-15"


def test_06_the_ledger_receivable_is_the_aggregate_figure_and_not_the_statutory_sum():
    """
    2,250 from pooled month ends against 1,125 from the per-charge walk.

    The ledger read reports both measures side by side — `statutory_interest_cents` and `aggregate_interest_cents` — together with `interest_written_off_cents`, `interest_collected_cents`, `interest_receivable_cents`, `arrears_principal_cents`, `assigned_arrears_cents`, `unassigned_arrears_cents` and `unapplied_credit_cents`, and it accepts an optional `as_of_date` to value the ledger at a past or future date without mutating anything.

    Collections are returned in ascending `created_at` order — oldest row first — and that ordering is stable and unconditional; no list endpoint offers an alternative sort.

    Design: Corner/calculations/out_of_order_charge_creation_still_accrues_by_due_date
    """
    scenario = _three_charges_aged_to_november(NEWEST_FIRST)

    settled = fx.run_accrual(scenario.case_id)
    assert settled["interest_receivable_cents"] == 2250
    # 1125 is the statutory sum, which the ledger receivable must not report.
    assert settled["interest_receivable_cents"] != 1125

    ledger = fx.read_ledger(scenario.case_id)
    assert ledger["aggregate_interest_cents"] == 2250
    assert ledger["statutory_interest_cents"] == 1125
    assert ledger["arrears_principal_cents"] == 225000

    rows, meta = validate_paginated(
        api_client.list_charges(
            FINANCE_OFFICER_HEADERS, {"case_id": scenario.case_id, "status": "OPEN"}
        )
    )
    assert meta["total_count"] == 3
    # Insertion order, which here is the reverse of due-date order.
    assert [row["due_date"] for row in rows] == NEWEST_FIRST


# ---------------------------------------------------------------------------
# The employer's fee shares the ceiling, and the last cent decides
# ---------------------------------------------------------------------------


def test_07_one_cent_of_room_survives_the_fee_and_the_order_issues_for_that_cent():
    """
    A cap of 501 less a fee of 500 leaves a withholding of exactly one cent.

    `ccpa_cap_amount_cents` is the disposable income multiplied by `ccpa_cap_pct`, floored to whole cents — a cap is never rounded upward.

    The room available for support is `ccpa_cap_amount_cents` less the employer's `remittance_fee_cents`.

    `employer_fee_cents` is the employer's `remittance_fee_cents` when `withholding_amount_cents` is greater than zero, and zero otherwise; the fee is never counted against the cap a second time.

    Design: Corner/calculations/withholding_floors_at_zero_when_the_employer_fee_exceeds_the_cap
    """
    scenario = _order_beside_an_employer_whose_fee_eats_the_cap()

    assert scenario.order["monthly_obligation_cents"] == 75000
    assert scenario.case["arrears_principal_cents"] == 0
    assert scenario.employer.get("statutory_cap_pct") is None

    iwo = fx.issue_withholding_order(
        scenario.order_id,
        scenario.employer["id"],
        reported_disposable_income_cents=835,
    )

    # The case carries no outstanding arrears principal.
    assert iwo["arrears_recovery_cents"] == 0
    assert iwo["requested_amount_cents"] == 75000
    assert iwo["jurisdiction_state_code"] == "MN"
    # Minnesota publishes no state ceiling, so the federal base governs.
    assert iwo["federal_cap_pct"] == 0.60
    assert iwo["ccpa_cap_pct"] == 0.60
    # floor(835 * 0.60) = floor(501.0).
    assert iwo["ccpa_cap_amount_cents"] == 501
    assert iwo["withholding_amount_cents"] == 1
    assert iwo["employer_fee_cents"] == 500


def test_08_a_cap_that_the_fee_exhausts_exactly_refuses_issuance_outright():
    """
    834 floors the cap to 500, leaving no room, and 832 would leave less than none.

    `withholding_amount_cents` is the smaller of `requested_amount_cents` and that room, and never less than zero.

    If that arithmetic leaves `withholding_amount_cents` at zero, issuance is refused outright with `ERR_WITHHOLDING_CAP_EXHAUSTED` (HTTP 409).

    Design: Corner/calculations/withholding_floors_at_zero_when_the_employer_fee_exceeds_the_cap
    """
    scenario = _order_beside_an_employer_whose_fee_eats_the_cap()
    fx.issue_withholding_order(
        scenario.order_id, scenario.employer["id"], reported_disposable_income_cents=835
    )

    version_before = fx.read_order(scenario.order_id)["version"]
    # floor(834 * 0.60) = floor(500.4) = 500, so the room is exactly zero.
    exhausted = api_client.issue_withholding_order(
        scenario.order_id,
        f.withholding_order_payload(scenario.employer["id"], version_before, 834),
        CASE_WORKER_HEADERS,
    )
    validate_error(exhausted, ApiErrorId.WITHHOLDING_CAP_EXHAUSTED.value, 409)

    version_after = fx.read_order(scenario.order_id)["version"]
    assert version_after == version_before

    # floor(832 * 0.60) = 499, one cent less than the fee, clamped to zero.
    negative = api_client.issue_withholding_order(
        scenario.order_id,
        f.withholding_order_payload(scenario.employer["id"], version_after, 832),
        CASE_WORKER_HEADERS,
    )
    validate_error(negative, ApiErrorId.WITHHOLDING_CAP_EXHAUSTED.value, 409)

    live, meta = validate_paginated(
        api_client.list_withholding_orders(
            CASE_WORKER_HEADERS, {"order_id": scenario.order_id}
        )
    )
    # Neither refusal persisted a withholding order.
    assert meta["total_count"] == 1
    assert live[0]["withholding_amount_cents"] == 1


# ---------------------------------------------------------------------------
# The ranking with an empty home-state set, and three decoys around it
# ---------------------------------------------------------------------------


def test_09_with_no_home_state_order_the_earliest_candidate_controls():
    """
    Minnesota is the child's home state and no Minnesota candidate exists.

    Among the candidates, those whose `origin_state_code` equals the referral's `child_home_state_code` are the home-state orders.

    **If no home-state order exists**, the ranking direction flips: the candidate with the **smallest** `effective_date` prevails — the first order issued anywhere controls.

    The winner's identifier becomes `controlling_order_id` and its `origin_state_code` becomes `controlling_order_state_code`.

    Design: Corner/calculations/controlling_order_falls_back_to_the_first_issued_order_without_a_home_state_order
    """
    scenario, _decoys = _four_orders_of_which_only_one_can_control()

    referral = fx.register_responding_referral(
        scenario.case_id,
        other_state_code="WI",
        child_home_state_code="MN",
        transmittal_type="ENFORCEMENT",
    )

    assert referral["status"] == "REGISTERED"
    assert referral["child_home_state_code"] == "MN"
    # The sole entered current-support order of the case.
    assert referral["controlling_order_id"] == scenario.order_id
    assert referral["controlling_order_state_code"] == "WI"
    assert fx.read_case(scenario.case_id)["interstate_role"] == "RESPONDING"


def test_10_the_medical_the_vacated_and_the_calculated_orders_never_enter_the_ranking():
    """
    The earliest order of all is a medical one, and it still cannot win.

    The candidate set is the `ENTERED` support orders of the case whose `order_type` is `CURRENT_SUPPORT`; medical-support orders never compete, and neither does any order in `DRAFT`, `CALCULATED`, `PENDING_DEVIATION_FINDINGS`, `SUPERSEDED` or `VACATED`.

    From `DRAFT` it is the responding-state path: the referral's `direction` must be `RESPONDING`, and the case must have at least one `ENTERED` support order whose `origin_state_code` equals the referral's `other_state_code` — the foreign order being registered here must actually be the sister state's order.

    Design: Corner/calculations/controlling_order_falls_back_to_the_first_issued_order_without_a_home_state_order
    """
    scenario, decoys = _four_orders_of_which_only_one_can_control()

    assert decoys["medical"]["status"] == "ENTERED"
    assert decoys["medical"]["effective_date"] == "2026-05-01"
    assert decoys["vacated"]["status"] == "VACATED"
    assert decoys["calculated"]["status"] == "CALCULATED"
    assert scenario.order["effective_date"] == "2026-07-01"

    referral = fx.register_responding_referral(
        scenario.case_id,
        other_state_code="WI",
        child_home_state_code="MN",
        transmittal_type="ENFORCEMENT",
    )

    # Its earlier effective date and its Minnesota origin buy it nothing.
    assert referral["controlling_order_id"] != decoys["medical"]["id"]
    assert referral["controlling_order_id"] != decoys["vacated"]["id"]
    assert referral["controlling_order_id"] != decoys["calculated"]["id"]
    assert referral["controlling_order_state_code"] != "MN"
