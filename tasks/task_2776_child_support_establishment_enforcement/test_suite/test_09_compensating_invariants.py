"""
Reversals that must move a quantity between buckets without creating any.

Each scenario runs an operation whose whole job is to undo an earlier one, then
adds up the same total on both sides of it: gross interest across a waiver and
its reinstatement, and an employer's live-withholding counter across two
asymmetric terminations and a refused repeat.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import CASE_WORKER_HEADERS, FINANCE_OFFICER_HEADERS

#: The gross aggregate month-end interest of the settled case valued at
#: 2027-04-02, which is the total that must be conserved across the default.
GROSS_INTEREST_CENTS = 10758


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _settlement_plan_one_day_past_its_second_installment() -> fx.Scenario:
    """
    Six unpaid monthly charges of 82,500 cents, a seven-installment settlement
    accepted at 2027-02-01, one installment of 71,333 cents paid on that day,
    and the clock then at 2027-04-02 — one day past the second due date.

    The ledger is carried forward with a second accrual run, so every interest
    figure in the tests is the settled one for that instant.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Uma Vance",
            "ssn_last4": "3434",
            "monthly_gross_income_cents": 150000,
        },
        ncp_overrides={
            "full_name": "Vic Vance",
            "ssn_last4": "3535",
            "monthly_gross_income_cents": 330000,
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

    scenario.compromise_offer = fx.create_compromise_offer(
        scenario.case_id, installment_count=7
    )
    fx.accept_compromise_offer(scenario.compromise_offer["id"], scenario.ncp_id)
    scenario.payments = [
        fx.pay_installment(scenario.case_id, scenario.compromise_offer["id"], 71333)
    ]
    fx.set_clock("2027-04-02T00:00:00Z")
    scenario.case = fx.run_accrual(scenario.case_id)
    scenario.compromise_offer = fx.read_compromise_offer(scenario.compromise_offer["id"])
    return scenario


def _two_employers_one_served_and_one_only_issued() -> Tuple[
    fx.Scenario, Dict[str, Any], Dict[str, Any]
]:
    """
    One entered order at 75,000 cents with a single charge already payable, two
    Minnesota employers, and one withholding order at each — the first served,
    the second left in `ISSUED`.

    The charge is due on the order's effective date so the case carries arrears
    principal at the opening clock, which is what puts the arrears add-on into
    both withholding requests.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Wren Xu",
            "ssn_last4": "3636",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Yan Xu",
            "ssn_last4": "3737",
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
    scenario.charges = [
        fx.post_charge(
            scenario.order_id,
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-01",
        )
    ]
    scenario.employer = fx.create_employer(
        state_code="MN", legal_name="Bluestem Machining", remittance_fee_cents=0
    )
    second_employer = fx.create_employer(
        state_code="MN", legal_name="Cedar Line Logistics", remittance_fee_cents=0
    )
    served = fx.issue_withholding_order(
        scenario.order_id, scenario.employer_id, reported_disposable_income_cents=234000
    )
    only_issued = fx.issue_withholding_order(
        scenario.order_id, second_employer["id"], reported_disposable_income_cents=234000
    )
    scenario.withholding_order = fx.serve_withholding_order(served["id"])
    scenario.reload_employer()
    return scenario, second_employer, only_issued


# ---------------------------------------------------------------------------
# The default declaration reverses the waiver and nothing else
# ---------------------------------------------------------------------------


def test_01_the_plan_is_active_with_the_waiver_still_written_off():
    """
    The state the compensation has to reverse, read one day past the due date.

    A compromise-installment payment referencing the offer drives `ACCEPTED → ACTIVE` on the first installment, setting `compliance_payment_count` to 1 and advancing `next_installment_due_date` by one month.

    Design: Difficulty/compensating_invariant/compromise_default_reinstates_written_off_interest
    """
    scenario = _settlement_plan_one_day_past_its_second_installment()
    offer = scenario.compromise_offer

    assert scenario.order["monthly_obligation_cents"] == 82500
    assert offer["status"] == "ACTIVE"
    assert offer["compliance_payment_count"] == 1
    a.assert_instant_equals(offer["accepted_at"], "2027-02-01T00:00:00Z", "accepted_at")
    assert offer["next_installment_due_date"] == "2027-04-01"
    assert offer["interest_waiver_cents"] == 4332
    assert offer["settlement_total_cents"] == 499332
    assert offer["monthly_installment_cents"] == 71333

    assert scenario.case["total_charged_principal_cents"] == 495000
    # 495000 less the 71333 the installment applied to the oldest charge.
    assert scenario.case["arrears_principal_cents"] == 423667
    assert scenario.case["interest_written_off_cents"] == 4332
    assert scenario.case["interest_collected_cents"] == 0
    # The gross aggregate figure at 2027-04-02, less the 4332 written off.
    assert scenario.case["interest_receivable_cents"] == 6426


def test_02_the_default_reinstates_exactly_the_waived_interest():
    """
    The receivable rises by 4,332 cents and stops there.

    Default stamps `defaulted_at`, subtracts `interest_waiver_cents` back out of the case's `interest_written_off_cents` so that the reinstated interest reappears in `interest_receivable_cents`, and sets the case's `enforcement_posture` to `ESCALATED`, which reopens enforcement eligibility.

    `interest_receivable_cents` is a computed field: the aggregate month-end interest total, less `interest_written_off_cents`, less `interest_collected_cents`, floored at zero so it never goes negative.

    Design: Difficulty/compensating_invariant/compromise_default_reinstates_written_off_interest
    """
    scenario = _settlement_plan_one_day_past_its_second_installment()
    receivable_before = scenario.case["interest_receivable_cents"]

    defaulted = fx.declare_compromise_default(scenario.compromise_offer["id"])

    assert defaulted["status"] == "DEFAULTED"
    a.assert_instant_equals(defaulted["defaulted_at"], "2027-04-02T00:00:00Z", "defaulted_at")
    # The offer keeps its own frozen terms; only the case-level write-off moved.
    assert defaulted["interest_waiver_cents"] == 4332

    settled = fx.run_accrual(scenario.case_id)
    assert settled["interest_written_off_cents"] == 0
    assert settled["interest_receivable_cents"] == GROSS_INTEREST_CENTS
    assert settled["interest_receivable_cents"] - receivable_before == 4332

    ledger = fx.read_ledger(scenario.case_id)
    # No interest was created: the same gross total stood on both sides.
    assert ledger["aggregate_interest_cents"] == GROSS_INTEREST_CENTS
    assert ledger["interest_receivable_cents"] == GROSS_INTEREST_CENTS


def test_03_the_installment_already_applied_is_not_clawed_back():
    """
    The reversal touches interest only; the 71,333 cents stays on its charge.

    Installments already paid are **not** clawed back — the money stays applied to the charges it satisfied, and only the waiver is reversed.

    Design: Difficulty/compensating_invariant/compromise_default_reinstates_written_off_interest
    """
    scenario = _settlement_plan_one_day_past_its_second_installment()
    oldest_charge_id = scenario.charges[0]["id"]

    fx.declare_compromise_default(scenario.compromise_offer["id"])
    settled = fx.run_accrual(scenario.case_id)

    assert settled["arrears_principal_cents"] == 423667
    assert settled["total_charged_principal_cents"] == 495000
    assert settled["unapplied_credit_cents"] == 0
    assert settled["enforcement_posture"] == "ESCALATED"

    oldest = fx.read_charge(oldest_charge_id)
    assert oldest["amount_cents"] == 82500
    assert oldest["paid_cents"] == 71333
    assert oldest["unpaid_balance_cents"] == 11167
    assert oldest["status"] == "OPEN"


def test_04_gross_interest_is_conserved_and_a_repeat_declaration_is_refused():
    """
    The three interest buckets sum to the same gross total either side of the
    default, and the terminal status blocks a second reversal.

    `DEFAULTED` is terminal, and every disallowed origin state on acceptance or on a default declaration answers with `ERR_INVALID_OFFER_STATUS` (HTTP 409).

    Design: Difficulty/compensating_invariant/compromise_default_reinstates_written_off_interest
    """
    scenario = _settlement_plan_one_day_past_its_second_installment()
    before = scenario.case
    assert (
        before["interest_receivable_cents"]
        + before["interest_written_off_cents"]
        + before["interest_collected_cents"]
        == GROSS_INTEREST_CENTS
    )

    fx.declare_compromise_default(scenario.compromise_offer["id"])
    after = fx.run_accrual(scenario.case_id)
    assert (
        after["interest_receivable_cents"]
        + after["interest_written_off_cents"]
        + after["interest_collected_cents"]
        == GROSS_INTEREST_CENTS
    )

    response = api_client.declare_compromise_default(
        scenario.compromise_offer["id"],
        f.default_declaration_payload(),
        FINANCE_OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.INVALID_OFFER_STATUS.value, 409)

    # The refused repeat did not reverse the waiver a second time.
    assert fx.read_case(scenario.case_id)["interest_written_off_cents"] == 0
    assert fx.read_compromise_offer(scenario.compromise_offer["id"])["status"] == "DEFAULTED"


# ---------------------------------------------------------------------------
# The employer withholding counter across two asymmetric terminations
# ---------------------------------------------------------------------------


def test_05_both_withholding_orders_compute_the_same_amount_under_the_federal_cap():
    """
    Two employers, one obligor, and a collection that fits the aggregate ceiling.

    `arrears_recovery_cents` is the parent order's `monthly_obligation_cents` multiplied by 0.20 — twenty percent — rounded half up to whole cents, and it is zero when the case has no outstanding arrears principal.

    Because an obligor may be withheld at two employers, the collection as a whole is checked against the most restrictive percentage in play: over all of the obligor's withholding orders whose `service_status` is not `TERMINATED`, the one being written included, the total reported disposable income is summed, the smallest `ccpa_cap_pct` among them is taken as the binding percentage, and the aggregate ceiling is that summed disposable income multiplied by the binding percentage, floored to whole cents.

    Design: Difficulty/compensating_invariant/iwo_termination_conserves_employer_active_iwo_count
    """
    scenario, second_employer, only_issued = _two_employers_one_served_and_one_only_issued()
    served = scenario.withholding_order

    assert scenario.order["monthly_obligation_cents"] == 75000
    # The charge is due on the opening clock date, so it is already arrears.
    assert fx.read_case(scenario.case_id)["arrears_principal_cents"] == 75000
    assert scenario.employer.get("statutory_cap_pct") is None
    assert second_employer["active_iwo_count"] == 0

    for iwo in (served, only_issued):
        # round_half_up(75000 * 0.20).
        assert iwo["arrears_recovery_cents"] == 15000
        assert iwo["requested_amount_cents"] == 90000
        # 75000 of arrears is below 3 x 75000, so the delinquency bump is absent.
        assert iwo["federal_cap_pct"] == 0.60
        assert iwo["ccpa_cap_pct"] == 0.60
        # floor(234000 * 0.60).
        assert iwo["ccpa_cap_amount_cents"] == 140400
        assert iwo["withholding_amount_cents"] == 90000
        assert iwo["jurisdiction_state_code"] == "MN"

    assert only_issued["service_status"] == "ISSUED"
    # 180000 of withholding against floor(468000 * 0.60) = 280800 of headroom.
    assert served["withholding_amount_cents"] + only_issued["withholding_amount_cents"] == 180000


def test_06_terminating_a_never_served_order_does_not_decrement_its_employer():
    """
    The counter of the employer that never had one withheld cannot fall.

    It stamps `served_at` with the current logical clock, computes `first_withholding_due_at` as `served_at` plus a fourteen-day employer implementation period, sets `next_remittance_due_at` equal to `first_withholding_due_at`, and increases the employer's `active_iwo_count` by 1.

    From `ISSUED` the employer's `active_iwo_count` is *not* decremented, because it was never incremented — that only happened at service.

    Design: Difficulty/compensating_invariant/iwo_termination_conserves_employer_active_iwo_count
    """
    scenario, second_employer, only_issued = _two_employers_one_served_and_one_only_issued()

    served = scenario.withholding_order
    assert served["service_status"] == "SERVED"
    a.assert_instant_equals(served["served_at"], "2026-08-01T00:00:00Z", "served_at")
    a.assert_instant_equals(served["first_withholding_due_at"], "2026-08-15T00:00:00Z", "first_withholding_due_at")
    assert served["next_remittance_due_at"] == served["first_withholding_due_at"]
    assert served["remittance_status"] == "NOT_DUE"
    # Service is the only event that raises the counter, and it raised this one.
    assert scenario.employer["active_iwo_count"] == 1

    count_before = fx.read_employer(second_employer["id"])["active_iwo_count"]
    terminated = fx.terminate_withholding_order(only_issued["id"], "EMPLOYMENT_ENDED")

    assert terminated["service_status"] == "TERMINATED"
    assert terminated["terminated_reason"] == "EMPLOYMENT_ENDED"

    count_after = fx.read_employer(second_employer["id"])["active_iwo_count"]
    assert count_after >= count_before
    assert count_after >= 0


def test_07_terminating_the_served_order_takes_its_employer_from_one_to_zero():
    """
    The counter falls by exactly one and the remittance dimension freezes.

    From `SERVED` or from `AMENDED` the employer's `active_iwo_count` is decremented by 1, `next_remittance_due_at` is cleared to absent, and the remittance dimension is frozen where it stands.

    Design: Difficulty/compensating_invariant/iwo_termination_conserves_employer_active_iwo_count
    """
    scenario, _second_employer, _only_issued = _two_employers_one_served_and_one_only_issued()

    assert scenario.employer["active_iwo_count"] == 1

    terminated = fx.terminate_withholding_order(scenario.iwo_id, "EMPLOYMENT_ENDED")

    assert terminated["service_status"] == "TERMINATED"
    assert terminated["terminated_reason"] == "EMPLOYMENT_ENDED"
    assert terminated.get("next_remittance_due_at") is None
    # Frozen, not advanced: the remittance dimension stands where it stood.
    assert terminated["remittance_status"] == "NOT_DUE"
    assert terminated["missed_remittance_count"] == 0

    assert fx.read_employer(scenario.employer_id)["active_iwo_count"] == 0


def test_08_a_repeat_termination_is_refused_and_never_decrements_a_second_time():
    """
    The counter has reached zero and the terminal status keeps it there.

    `TERMINATED` is terminal on the service dimension, and any further write answers with `ERR_INVALID_IWO_STATUS` (HTTP 409) — as does serving an order that is already served, or amending one that is still merely `ISSUED`.

    Withholding orders accept `order_id`, `employer_id`, `service_status`, `remittance_status` and `jurisdiction_state_code`.

    Design: Difficulty/compensating_invariant/iwo_termination_conserves_employer_active_iwo_count
    """
    scenario, _second_employer, _only_issued = _two_employers_one_served_and_one_only_issued()

    fx.terminate_withholding_order(scenario.iwo_id, "EMPLOYMENT_ENDED")
    assert fx.read_employer(scenario.employer_id)["active_iwo_count"] == 0

    response = api_client.terminate_withholding_order(
        scenario.iwo_id, f.iwo_termination_payload("CASE_CLOSED"), CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.INVALID_IWO_STATUS.value, 409)

    assert fx.read_employer(scenario.employer_id)["active_iwo_count"] == 0
    assert fx.read_withholding_order(scenario.iwo_id)["terminated_reason"] == "EMPLOYMENT_ENDED"

    live, meta = validate_paginated(
        api_client.list_withholding_orders(
            CASE_WORKER_HEADERS,
            {"employer_id": scenario.employer_id, "service_status": "SERVED"},
        )
    )
    # An empty served list is what a counter of zero is supposed to mean.
    assert live == []
    assert meta["total_count"] == 0
