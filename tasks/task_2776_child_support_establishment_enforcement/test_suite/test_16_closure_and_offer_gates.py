"""
The gates guarding case closure, enforcement notice and arrears compromise.

Each scenario builds the exact ledger or status the rule is written about and then
issues the same request twice — once from the state that must be refused and once
from the state that must pass — so that the rule, and not the setup, is what moves.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    CASE_WORKER_HEADERS,
    CASE_WORKER_USER_ID,
    FINANCE_OFFICER_HEADERS,
    SUPERVISING_ATTORNEY_HEADERS,
    SUPERVISING_ATTORNEY_USER_ID,
)


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _one_unpaid_arrears_charge_read_five_weeks_later() -> fx.Scenario:
    """
    An entered 75,000-cent order carrying a single 75,000-cent arrears judgment
    due 2026-08-15, with the clock then at 2026-09-20 so exactly one month-end
    snapshot has passed over the unpaid balance.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Marisol Quintero",
            "ssn_last4": "6219",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Abel Quintero",
            "ssn_last4": "6220",
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
            charge_type="ARREARS_JUDGMENT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-15",
            amount_cents=75000,
        )
    ]
    fx.set_clock("2026-09-20T00:00:00Z")
    return scenario


# ---------------------------------------------------------------------------
# Satisfaction clears the interest half of the closure conjunction by itself
# ---------------------------------------------------------------------------


def test_01_closure_is_refused_while_either_principal_or_interest_stands():
    """
    75,000 of principal and 375 of month-end interest each block the same closure.

    Across every path, a `closed_reason` of `ARREARS_SATISFIED` additionally requires that the case's `arrears_principal_cents` and `interest_receivable_cents` are both zero, and any outstanding balance answers with `ERR_ARREARS_OUTSTANDING` (HTTP 409).

    At each such snapshot it sums the `unpaid_balance_cents` of every charge in the input set whose `due_date` falls on or before that snapshot date, multiplies that pooled balance by the monthly rate of 0.005, rounds the product half up to whole cents, and adds it to a running total.

    Design: Corner/validations/arrears_satisfied_closure_needs_principal_and_interest_at_zero
    """
    scenario = _one_unpaid_arrears_charge_read_five_weeks_later()

    assert scenario.order["monthly_obligation_cents"] == 75000
    case = fx.read_case(scenario.case_id)
    assert case["case_status"] == "ENFORCEMENT"
    assert case["arrears_principal_cents"] == 75000
    # The one month-end 2026-08-31 falls strictly before 2026-09-20.
    assert case["interest_receivable_cents"] == 375

    response = api_client.close_case(
        scenario.case_id,
        f.closure_payload("ARREARS_SATISFIED"),
        SUPERVISING_ATTORNEY_HEADERS,
    )
    validate_error(response, ApiErrorId.ARREARS_OUTSTANDING.value, 409)
    assert fx.read_case(scenario.case_id)["case_status"] == "ENFORCEMENT"


def test_02_paying_only_the_principal_retires_the_interest_and_unlocks_closure():
    """
    Nothing reaches the interest bucket, yet the receivable falls from 375 to zero.

    Charges in `VOID` and charges in `SATISFIED` are excluded entirely and retroactively — once a charge is satisfied it contributes nothing to either measure, including for month-end snapshots that predate the payment that satisfied it.

    **Bucket three, arrears principal**: every remaining `OPEN` charge of the case that buckets one and two did not consume, taken oldest `due_date` first and then `created_at`, each absorbing the smaller of the remaining balance and its own `unpaid_balance_cents`, accumulating into `applied_arrears_cents`.

    On a non-assistance case the family receives current support, medical support and arrears: `disbursed_to_cp_cents` is `applied_current_cents` plus `applied_medical_cents` plus `applied_arrears_cents`, and `retained_by_state_cents` is `applied_interest_cents` plus `applied_genetic_cost_cents`.

    Design: Corner/validations/arrears_satisfied_closure_needs_principal_and_interest_at_zero
    """
    scenario = _one_unpaid_arrears_charge_read_five_weeks_later()

    payment = fx.post_payment(scenario.case_id, 75000, "DIRECT_PAY")
    # The judgment is not CURRENT_SUPPORT, so bucket one is empty from the start.
    assert payment["applied_current_cents"] == 0
    assert payment["applied_arrears_cents"] == 75000
    # Bucket three consumed the whole payment, so bucket four was never reached.
    assert payment["applied_interest_cents"] == 0
    assert payment["unapplied_credit_cents"] == 0
    assert payment["disbursed_to_cp_cents"] == 75000
    assert payment["retained_by_state_cents"] == 0

    charge = fx.read_charge(scenario.charges[0]["id"])
    assert charge["status"] == "SATISFIED"
    assert charge["unpaid_balance_cents"] == 0
    assert charge["interest_accrued_cents"] == 0

    case = fx.read_case(scenario.case_id)
    assert case["arrears_principal_cents"] == 0
    # The 375 vanished by retroactive exclusion, not by having been collected.
    assert case["interest_receivable_cents"] == 0
    assert case["interest_collected_cents"] == 0

    closed = fx.close_case(scenario.case_id, "ARREARS_SATISFIED")
    assert closed["case_status"] == "CLOSED"
    assert closed["closed_reason"] == "ARREARS_SATISFIED"
    a.assert_instant_equals(closed["closed_at"], "2026-09-20T00:00:00Z", "closed_at")


def _noticed_remedy_and_a_settlement_offer() -> Tuple[fx.Scenario, Dict[str, Any], Dict[str, Any]]:
    """
    An entered 75,000-cent order with two unpaid 75,000-cent charges due
    2026-08-15 and 2026-09-15, read at 2026-11-01, carrying a
    `CREDIT_BUREAU_REPORT` action already noticed and a three-installment
    settlement offer built at the same instant.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Odalys Ferreira",
            "ssn_last4": "6221",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Tobias Ferreira",
            "ssn_last4": "6222",
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
        scenario.order_id, ["2026-08-01", "2026-09-01"], due_day=15
    )
    fx.set_clock("2026-11-01T00:00:00Z")
    action = fx.propose_enforcement_action(scenario.case_id, "CREDIT_BUREAU_REPORT")
    scenario.enforcement_action = fx.send_enforcement_notice(action["id"])
    offer = fx.create_compromise_offer(scenario.case_id, installment_count=3)
    return scenario, scenario.enforcement_action, offer


# ---------------------------------------------------------------------------
# The two interest measures on one case, and what acceptance does to a remedy
# ---------------------------------------------------------------------------


def test_03_certification_and_settlement_value_the_same_arrears_differently():
    """
    The certified balance carries 1,125 of interest where the offer carries 1,875.

    `arrears_certified_snapshot_cents` is the case's `arrears_principal_cents` plus the **statutory per-charge** interest measure valued at the current logical clock date — certification always uses the statutory measure, never the ledger's aggregate measure, which is precisely why a certified balance can differ from the balance the ledger read shows for the same case at the same instant.

    `interest_due_snapshot_cents` captures the **aggregate month-end** interest measure valued at the current logical clock date — the settlement figure is a ledger figure, so it uses the ledger's measure and not the certification measure.

    The stay is not merely a flag: every enforcement action on the case in `ACTIVE` *or* in `NOTICE_SENT` is released with a `release_reason` of `COMPROMISE_ACCEPTED`, and for the `ACTIVE` ones the participant remedy flags are reversed exactly as a manual release reverses them, so `license_suspension_active` becomes false with `has_valid_drivers_license` restored to true, `lien_recorded` becomes false and `credit_bureau_reported` becomes false.

    Design: Corner/validations/invalid_action_status_outranks_the_enforcement_stay
    """
    scenario, action, offer = _noticed_remedy_and_a_settlement_offer()

    assert scenario.order["monthly_obligation_cents"] == 75000
    # 150000 plus two whole months on the older charge and one on the newer.
    assert action["arrears_certified_snapshot_cents"] == 151125
    assert action["eligibility_threshold_cents"] == 100000
    assert action["status"] == "NOTICE_SENT"
    a.assert_instant_equals(
        action["contest_deadline_at"], "2026-12-01T00:00:00Z", "contest_deadline_at"
    )

    # Three month-end snapshots over 75000, 150000 and 150000.
    assert offer["principal_due_snapshot_cents"] == 150000
    assert offer["interest_due_snapshot_cents"] == 1875
    assert offer["pre_waiver_total_cents"] == 151875
    assert offer["waiver_tier_pct"] == 0.25
    # round_half_up(1875 * 0.25) = round_half_up(468.75).
    assert offer["interest_waiver_cents"] == 469
    assert offer["settlement_total_cents"] == 151406
    assert offer["monthly_installment_cents"] == 50468
    assert offer["final_installment_cents"] == 50470

    accepted = fx.accept_compromise_offer(offer["id"], scenario.ncp_id)
    assert accepted["status"] == "ACCEPTED"

    case = fx.read_case(scenario.case_id)
    assert case["enforcement_posture"] == "STAYED"
    assert case["interest_written_off_cents"] == 469
    assert case["interest_receivable_cents"] == 1406

    released = fx.read_enforcement_action(action["id"])
    # A remedy that never activated is still swept up by the stay.
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "COMPROMISE_ACCEPTED"
    assert released["remedy_applied"] is False


def test_04_the_status_band_answers_before_the_stay_does():
    """
    Notice on the released remedy is both a bad status and a stayed case, and the
    status is what comes back.

    Only then are state preconditions evaluated: `ERR_INVALID_CASE_STATUS`, `ERR_INVALID_ORDER_STATUS`, `ERR_INVALID_PATERNITY_STATUS`, `ERR_INVALID_IWO_STATUS`, `ERR_INVALID_REVIEW_STATUS`, `ERR_INVALID_ACTION_STATUS`, `ERR_INVALID_REFERRAL_STATUS` and `ERR_INVALID_OFFER_STATUS`, each at HTTP 409.

    Notice requires that the case's `enforcement_posture` is not `STAYED` — a case under an accepted compromise is protected, and the attempt answers with `ERR_ENFORCEMENT_STAYED` (HTTP 409) — and that the case's `good_cause_claim` is false, since serving notice on the obligor discloses the existence of the case and a good-cause claim bars exactly that, answering with `ERR_GOOD_CAUSE_BARS_DISCLOSURE` (HTTP 409).

    `DENIED` and `RELEASED` are terminal.

    Design: Corner/validations/invalid_action_status_outranks_the_enforcement_stay
    """
    scenario, action, offer = _noticed_remedy_and_a_settlement_offer()
    fx.accept_compromise_offer(offer["id"], scenario.ncp_id)
    assert fx.read_case(scenario.case_id)["enforcement_posture"] == "STAYED"

    response = api_client.send_enforcement_notice(
        action["id"], f.notice_payload(), CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.INVALID_ACTION_STATUS.value, 409)

    # The stay never reaches a proposal, so this one meets the fiscal gate instead.
    response = api_client.propose_enforcement_action(
        scenario.case_id, f.enforcement_action_payload("PROPERTY_LIEN"), CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.ARREARS_BELOW_ENFORCEMENT_THRESHOLD.value, 409)

    rows, meta = validate_paginated(
        api_client.list_enforcement_actions(
            CASE_WORKER_HEADERS, {"case_id": scenario.case_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "RELEASED"


def _assistance_case_with_two_unpaid_months() -> fx.Scenario:
    """
    A public-assistance case whose obligor owes two 75,000-cent months, read at
    2026-09-20 so both charges are past due and the whole balance is assigned.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Ilona Radcliffe",
            "ssn_last4": "6223",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Grigor Radcliffe",
            "ssn_last4": "6224",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={
            "case_type": "PA_REFERRAL",
            "child_count": 2,
            "tanf_assistance": True,
            "good_cause_claim": False,
        },
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id, ["2026-08-01", "2026-09-01"], due_day=15
    )
    fx.set_clock("2026-09-20T00:00:00Z")
    return scenario


def _minimum_order_case_with_a_delinquent_employer() -> fx.Scenario:
    """
    A minimum-order case carrying 75,000 cents of arrears judgment and a served
    withholding order that has already missed one remittance cycle, so the
    obligor's delinquency component scores sixty.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Katrin Vasquez",
            "ssn_last4": "6225",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Roald Vasquez",
            "ssn_last4": "6226",
            "monthly_gross_income_cents": 113200,
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
            charge_type="ARREARS_JUDGMENT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-01",
            amount_cents=75000,
        )
    ]
    scenario.employer = fx.create_employer(
        state_code="MN", legal_name="Vasquez Cartage", remittance_fee_cents=0
    )
    issued = fx.issue_withholding_order(
        scenario.order_id, scenario.employer_id, reported_disposable_income_cents=100000
    )
    scenario.withholding_order = fx.serve_withholding_order(issued["id"])
    fx.set_clock("2026-08-16T00:00:00Z")
    scenario.withholding_order = fx.declare_lapse(scenario.iwo_id)
    return scenario


# ---------------------------------------------------------------------------
# Two different gates refuse two different offers on two different balances
# ---------------------------------------------------------------------------


def test_05_an_assistance_case_cannot_settle_arrears_it_does_not_own():
    """
    150,000 cents clears the minimum and the tier is not high, and it is still refused.

    The case's `tanf_assistance` must be false, because arrears assigned to the state in exchange for public assistance are not the agency's to forgive, and an assistance case answers with `ERR_ASSIGNED_ARREARS_NOT_COMPROMISABLE` (HTTP 409).

    Assignment is what splits the arrears figure into two computed components: `assigned_arrears_cents` equals `arrears_principal_cents` when `tanf_assistance` is true and equals zero otherwise, and `unassigned_arrears_cents` is `arrears_principal_cents` minus `assigned_arrears_cents`.

    Design: Corner/validations/assigned_arrears_and_high_risk_each_block_a_compromise_offer
    """
    scenario = _assistance_case_with_two_unpaid_months()

    assert scenario.order["monthly_obligation_cents"] == 75000
    case = fx.read_case(scenario.case_id)
    assert case["arrears_principal_cents"] == 150000
    assert case["assigned_arrears_cents"] == 150000
    assert case["unassigned_arrears_cents"] == 0

    obligor = fx.read_participant(scenario.ncp_id)
    # floor(100 * 150000 / (12 * 75000)) of arrears and a full payment-history score.
    assert obligor["compromise_risk_score"] == 44
    assert obligor["compromise_risk_tier"] == "MEDIUM"

    response = api_client.create_compromise_offer(
        scenario.case_id,
        f.compromise_offer_payload(case["version"], 3),
        FINANCE_OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.ASSIGNED_ARREARS_NOT_COMPROMISABLE.value, 409)

    offers, meta = validate_paginated(
        api_client.list_compromise_offers(
            FINANCE_OFFICER_HEADERS, {"case_id": scenario.case_id}
        )
    )
    assert offers == []
    assert meta["total_count"] == 0


def test_06_a_high_compromise_tier_answers_before_the_balance_is_even_measured():
    """
    The obligor scores 77 on the compromise weighting and 75 on the enforcement one.

    Because the weightings differ, the same underlying data routinely lands the two screens in different tiers, and each tier gates a different decision.

    The **compromise screen**, written to `compromise_risk_score` and `compromise_risk_tier`, weights payment history at 40, arrears at 25, delinquency at 20 and enforcement history at 15, and weights locate status and interstate exposure at 0.

    Both scores band identically: a score of at least 67 is `HIGH`, a score of at least 34 but below 67 is `MEDIUM`, and anything below 34 is `LOW`.

    Design: Corner/validations/assigned_arrears_and_high_risk_each_block_a_compromise_offer
    """
    scenario = _minimum_order_case_with_a_delinquent_employer()

    assert scenario.order["monthly_obligation_cents"] == 5000
    # 0.60 federal plus the five-point bump, since 75000 is at least 3 x 5000.
    assert scenario.withholding_order["ccpa_cap_pct"] == 0.65
    assert scenario.withholding_order["withholding_amount_cents"] == 6000
    assert scenario.withholding_order["remittance_status"] == "DELINQUENT"

    case = fx.read_case(scenario.case_id)
    assert case["arrears_principal_cents"] == 75000
    assert case["unassigned_arrears_cents"] == 75000

    obligor = fx.read_participant(scenario.ncp_id)
    # (25 x 100 + 20 x 60 + 40 x 100 + 15 x 0) / 100.
    assert obligor["compromise_risk_score"] == 77
    assert obligor["compromise_risk_tier"] == "HIGH"
    # The same six components under the other weighting.
    assert obligor["enforcement_risk_score"] == 75
    assert obligor["enforcement_risk_tier"] == "HIGH"

    response = api_client.create_compromise_offer(
        scenario.case_id,
        f.compromise_offer_payload(case["version"], 3),
        FINANCE_OFFICER_HEADERS,
    )
    # The balance is also below the 100,000 minimum, but the tier gate answers first.
    validate_error(response, ApiErrorId.COMPROMISE_RISK_TOO_HIGH.value, 409)

    offers, meta = validate_paginated(
        api_client.list_compromise_offers(
            FINANCE_OFFICER_HEADERS, {"case_id": scenario.case_id}
        )
    )
    assert offers == []
    assert meta["total_count"] == 0


def _two_offers_on_one_untouched_ledger() -> Tuple[fx.Scenario, Dict[str, Any], Dict[str, Any]]:
    """
    An entered 75,000-cent order with two unpaid 75,000-cent charges due
    2026-08-15 and 2026-09-15, read at 2026-11-01, and two three-installment
    offers built one after the other against the same untouched ledger.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Solveig Amadour",
            "ssn_last4": "6227",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Milo Amadour",
            "ssn_last4": "6228",
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
        scenario.order_id, ["2026-08-01", "2026-09-01"], due_day=15
    )
    fx.set_clock("2026-11-01T00:00:00Z")
    first = fx.create_compromise_offer(scenario.case_id, installment_count=3)
    second = fx.create_compromise_offer(scenario.case_id, installment_count=3)
    return scenario, first, second


# ---------------------------------------------------------------------------
# Every refusal below is decided by a row other than the one being written
# ---------------------------------------------------------------------------


def test_07_a_newer_offer_supersedes_the_older_one_and_the_older_cannot_be_accepted():
    """
    Two offers snapshot the same ledger, and only the second one survives.

    Creating an offer also drives any offer already `PROPOSED` on the same case to `SUPERSEDED`, which is terminal: the older offer can never be accepted afterwards, and an attempt answers with `ERR_OFFER_SUPERSEDED` (HTTP 409) rather than the generic status error.

    The new offer is created with `status` `PROPOSED`, `compliance_payment_count` at zero, and `accepted_at`, `next_installment_due_date`, `defaulted_at` and `completed_at` absent, and it increases the case's `version` by 1.

    Design: Corner/validations/offer_acceptance_is_validated_against_siblings_and_the_live_ledger
    """
    scenario, first, second = _two_offers_on_one_untouched_ledger()

    assert scenario.order["monthly_obligation_cents"] == 75000
    assert first["principal_due_snapshot_cents"] == 150000
    assert second["principal_due_snapshot_cents"] == 150000
    assert second["status"] == "PROPOSED"
    assert second["compliance_payment_count"] == 0
    assert second.get("accepted_at") is None

    # The older row was pushed out of PROPOSED by the act of creating the newer.
    assert fx.read_compromise_offer(first["id"])["status"] == "SUPERSEDED"

    response = api_client.accept_compromise_offer(
        first["id"], f.offer_acceptance_payload(), scenario.ncp_headers
    )
    validate_error(response, ApiErrorId.OFFER_SUPERSEDED.value, 409)


def test_08_a_ten_thousand_cent_payment_makes_the_surviving_snapshot_stale():
    """
    The offer row never changed, and it can no longer be accepted.

    Acceptance re-checks that no other offer on the case is `ACCEPTED` or `ACTIVE`, and it re-checks that the case's `arrears_principal_cents` still equals the offer's `principal_due_snapshot_cents` — a snapshot that has moved since the offer was built would waive interest against a balance that no longer exists, and a moved snapshot answers with `ERR_OFFER_SNAPSHOT_STALE` (HTTP 409).

    **Bucket one, current support for the current period**: the `OPEN` `CURRENT_SUPPORT` charges of the case whose period contains the payment's `received_at` date — that is, `period_start_date` less than or equal to that date and `period_end_date` strictly greater — are taken in order of `due_date` and then `created_at`, and each absorbs the smaller of the remaining balance and its own `unpaid_balance_cents`, accumulating into `applied_current_cents`.

    Design: Corner/validations/offer_acceptance_is_validated_against_siblings_and_the_live_ledger
    """
    scenario, _first, second = _two_offers_on_one_untouched_ledger()

    payment = fx.post_payment(scenario.case_id, 10000, "DIRECT_PAY")
    # 2026-11-01 falls in neither charge's period, so bucket one is empty.
    assert payment["applied_current_cents"] == 0
    assert payment["applied_arrears_cents"] == 10000

    surviving = fx.read_compromise_offer(second["id"])
    assert surviving["status"] == "PROPOSED"
    assert surviving["principal_due_snapshot_cents"] == 150000

    case = fx.read_case(scenario.case_id)
    assert case["arrears_principal_cents"] == 140000

    response = api_client.accept_compromise_offer(
        second["id"], f.offer_acceptance_payload(), scenario.ncp_headers
    )
    validate_error(response, ApiErrorId.OFFER_SNAPSHOT_STALE.value, 409)
    # The refusal compared values, so the untouched offer is still acceptable in form.
    assert fx.read_compromise_offer(second["id"])["status"] == "PROPOSED"


def test_09_the_offer_built_on_the_moved_ledger_accepts_and_locks_the_case():
    """
    A third offer snapshots 140,000, accepts, and then refuses both a premature
    default and a fourth offer.

    A `FinanceOfficer` declares the plan in default from either `ACCEPTED` or `ACTIVE`, and the only precondition is that the current logical clock date is **strictly past** `next_installment_due_date` — an installment due today is not yet late, and a premature declaration answers with `ERR_INSTALLMENT_NOT_YET_LATE` (HTTP 409).

    And no other offer on the case may already be `ACCEPTED` or `ACTIVE`, or the answer is `ERR_ACTIVE_OFFER_EXISTS` (HTTP 409) — one live plan at a time.

    Design: Corner/validations/offer_acceptance_is_validated_against_siblings_and_the_live_ledger
    """
    scenario, _first, _second = _two_offers_on_one_untouched_ledger()
    fx.post_payment(scenario.case_id, 10000, "DIRECT_PAY")

    third = fx.create_compromise_offer(scenario.case_id, installment_count=3)
    assert third["principal_due_snapshot_cents"] == 140000
    # Snapshots at 2026-08-31 over 65000 and at 09-30 and 10-31 over 140000.
    assert third["interest_due_snapshot_cents"] == 1725
    assert third["waiver_tier_pct"] == 0.25
    # round_half_up(1725 * 0.25) = round_half_up(431.25).
    assert third["interest_waiver_cents"] == 431
    assert third["settlement_total_cents"] == 141294
    # 141294 divides exactly by three, so the last installment carries no remainder.
    assert third["monthly_installment_cents"] == 47098
    assert third["final_installment_cents"] == 47098

    accepted = fx.accept_compromise_offer(third["id"], scenario.ncp_id)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["next_installment_due_date"] == "2026-12-01"

    response = api_client.declare_compromise_default(
        third["id"], f.default_declaration_payload(), FINANCE_OFFICER_HEADERS
    )
    validate_error(response, ApiErrorId.INSTALLMENT_NOT_YET_LATE.value, 409)

    case = fx.read_case(scenario.case_id)
    response = api_client.create_compromise_offer(
        scenario.case_id,
        f.compromise_offer_payload(case["version"], 3),
        FINANCE_OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.ACTIVE_OFFER_EXISTS.value, 409)

    # The accepted plan is the only live one, and it stayed accepted throughout.
    assert fx.read_compromise_offer(third["id"])["status"] == "ACCEPTED"


def _calculated_order_at_seventy_five_thousand() -> fx.Scenario:
    """
    A drafted and calculated Minnesota order whose guideline figure is 75,000
    cents, left short of entry so a deviation may still be requested on it.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Vivienne Beauchamp",
            "ssn_last4": "6229",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Lucien Beauchamp",
            "ssn_last4": "6230",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    fx.open_paternity_action(scenario.case_id, "PRESUMED_MARITAL")
    order = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="MN",
        effective_date="2026-08-01",
        medical_support_monthly_cents=0,
    )
    scenario.order = fx.calculate_order(order["id"])
    return scenario


# ---------------------------------------------------------------------------
# The materiality test, probed one cent either side of exact equality
# ---------------------------------------------------------------------------


def test_10_a_deviation_one_cent_short_of_ten_percent_is_refused():
    """
    67,501 fails the cross-multiplication and 67,500 passes it on the same order.

    A deviation must be material: the absolute difference between the requested amount and `guideline_monthly_cents` must be at least ten percent of `guideline_monthly_cents`, evaluated by integer cross-multiplication so that no floating-point artefact can move the boundary — the absolute difference multiplied by one hundred must be greater than or equal to `guideline_monthly_cents` multiplied by ten.

    The requested amount and reason are recorded on the order and its `version` increases by 1.

    Design: Corner/validations/deviation_request_at_exactly_ten_percent_of_guideline_is_accepted
    """
    scenario = _calculated_order_at_seventy_five_thousand()
    assert scenario.order["guideline_monthly_cents"] == 75000
    assert scenario.order["status"] == "CALCULATED"
    assert scenario.order["drafted_by_user_id"] == CASE_WORKER_USER_ID

    response = api_client.request_deviation(
        scenario.order_id,
        f.deviation_request_payload(67501, "SHARED_PARENTING"),
        CASE_WORKER_HEADERS,
    )
    # 7499 * 100 is 749900, one hundred short of 75000 * 10.
    validate_error(response, ApiErrorId.DEVIATION_BELOW_MIN_PCT.value, 422)

    unchanged = fx.read_order(scenario.order_id)
    assert unchanged["status"] == "CALCULATED"
    assert unchanged.get("deviation_requested_cents") is None
    assert unchanged["deviation_rejection_count"] == 0
    assert unchanged["deviation_applied"] is False

    requested = fx.request_deviation(scenario.order_id, 67500, "SHARED_PARENTING")
    # 7500 * 100 equals 750000 exactly, and the comparison is not a strict one.
    assert requested["status"] == "PENDING_DEVIATION_FINDINGS"
    assert requested["deviation_requested_cents"] == 67500
    assert requested["deviation_reason"] == "SHARED_PARENTING"
    assert requested["version"] == unchanged["version"] + 1


def test_11_approved_findings_enter_the_order_at_the_deviated_figure():
    """
    The obligation becomes 67,500 and the case still reaches enforcement.

    An `APPROVE` drives `PENDING_DEVIATION_FINDINGS → ENTERED`: `deviation_applied` becomes true, `findings_approved_by_user_id` is stamped with the deciding attorney's `X-User-ID`, `monthly_obligation_cents` is set to `deviation_requested_cents` rather than to the guideline figure, `next_accrual_due_date` is set to the order's `effective_date`, and the case moves to `ENFORCEMENT`.

    Both the guideline path and the deviation path converge on `ENTERED`, and they differ only in the `monthly_obligation_cents` the order ends up carrying.

    Design: Corner/validations/deviation_request_at_exactly_ten_percent_of_guideline_is_accepted
    """
    scenario = _calculated_order_at_seventy_five_thousand()
    fx.request_deviation(scenario.order_id, 67500, "SHARED_PARENTING")

    entered = fx.decide_deviation(scenario.order_id, "APPROVE")

    assert entered["status"] == "ENTERED"
    assert entered["deviation_applied"] is True
    assert entered["monthly_obligation_cents"] == 67500
    # The guideline figure survives beside the obligation that displaced it.
    assert entered["guideline_monthly_cents"] == 75000
    assert entered["findings_approved_by_user_id"] == SUPERVISING_ATTORNEY_USER_ID
    assert entered["next_accrual_due_date"] == "2026-08-01"
    # round_half_up(67500 * 0.20) on the deviated figure, not on the guideline one.
    assert entered["arrears_recovery_monthly_cents"] == 13500

    assert fx.read_case(scenario.case_id)["case_status"] == "ENFORCEMENT"
