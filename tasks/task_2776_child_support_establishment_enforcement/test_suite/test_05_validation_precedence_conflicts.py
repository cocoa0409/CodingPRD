"""
Requests that break two rules at once and may answer with only one of them.

Each scenario builds a single request that fails two independent checks from two
different bands of the documented evaluation order, asserts the band that must
answer, and then repairs only that violation to prove the second check was live
all along.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    FINANCE_OFFICER_HEADERS,
    make_supervising_attorney_headers,
)

#: The worksheet is run under this identifier, so it becomes the order's
#: ``drafted_by_user_id`` — the anchor the findings caller must differ from.
DRAFTER_USER_ID = "u-shared"

#: A second attorney, who may decide findings on that order.
REVIEWER_USER_ID = "u-attorney-1"


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _case_with_arrears_below_the_compromise_floor() -> fx.Scenario:
    """
    One unpaid charge of 75,000 cents, past due, and nothing else.

    The clock is moved to 2026-08-20 so the charge's due date of 2026-08-15 has
    passed and the balance really is arrears — 75,000 cents of it, which is
    under the settlement floor.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Bo Craven",
            "ssn_last4": "1616",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Cyd Craven",
            "ssn_last4": "1717",
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
    scenario.charges = [fx.post_monthly_charge(scenario.order_id, "2026-08-01", due_day=15)]
    fx.set_clock("2026-08-20T00:00:00Z")
    scenario.reload_case()
    return scenario


def _order_awaiting_findings_with_the_rejection_limit_spent() -> fx.Scenario:
    """
    A calculated order whose worksheet ran under `DRAFTER_USER_ID`, twice
    rejected on deviation, and now sitting on a third deviation request.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Dara Ellis",
            "ssn_last4": "1818",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Eli Ellis",
            "ssn_last4": "1919",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    scenario.paternity_action = fx.open_paternity_action(scenario.case_id, "PRESUMED_MARITAL")
    scenario.order = fx.draft_order(
        scenario.case_id,
        origin_state_code="MN",
        effective_date="2026-08-01",
        medical_support_monthly_cents=0,
    )
    scenario.order = fx.calculate_order(scenario.order_id, drafted_by_user_id=DRAFTER_USER_ID)
    for _ in range(2):
        fx.request_deviation(scenario.order_id, 60000, "HARDSHIP")
        scenario.order = fx.decide_deviation(
            scenario.order_id, "REJECT", decided_by_user_id=REVIEWER_USER_ID
        )
    scenario.order = fx.request_deviation(scenario.order_id, 60000, "HARDSHIP")
    return scenario


# ---------------------------------------------------------------------------
# The concurrency guard answers before the settlement floor
# ---------------------------------------------------------------------------


def test_01_a_stale_case_version_answers_before_the_settlement_floor():
    """
    The request is both stale and unaffordable, and the stale view answers.

    Next comes the optimistic-concurrency check on the two guarded writes (`ERR_STALE_ORDER_VERSION`, `ERR_STALE_CASE_VERSION`) — note that this sits *above* every state check, so a request that is both stale and state-invalid answers with the stale-version error.

    Design: Difficulty/priority_pair_validation_conflict/stale_case_version_beats_arrears_below_compromise_minimum
    """
    scenario = _case_with_arrears_below_the_compromise_floor()

    assert scenario.case["arrears_principal_cents"] == 75000
    # A settlement is only barred for this obligor by the balance, not by risk.
    assert fx.read_participant(scenario.ncp_id)["compromise_risk_tier"] == "MEDIUM"

    stale_version = scenario.case["version"]
    fresh = fx.run_accrual(scenario.case_id)
    assert fresh["version"] == stale_version + 1

    response = api_client.create_compromise_offer(
        scenario.case_id,
        f.compromise_offer_payload(stale_version, installment_count=6),
        FINANCE_OFFICER_HEADERS,
    )
    refusal = validate_error(response, ApiErrorId.STALE_CASE_VERSION.value, 412)
    assert refusal["error_id"] != ApiErrorId.ARREARS_BELOW_COMPROMISE_MINIMUM.value


def test_02_the_settlement_floor_refuses_the_repaired_request():
    """
    Repairing only the version leaves the second violation to answer.

    The case's `arrears_principal_cents` must be at least 100,000 cents, one thousand dollars, or the answer is `ERR_ARREARS_BELOW_COMPROMISE_MINIMUM` (HTTP 409); small balances are collected, not settled.

    Design: Difficulty/priority_pair_validation_conflict/stale_case_version_beats_arrears_below_compromise_minimum
    """
    scenario = _case_with_arrears_below_the_compromise_floor()

    stale_version = scenario.case["version"]
    fresh_version = fx.run_accrual(scenario.case_id)["version"]
    assert fresh_version != stale_version

    response = api_client.create_compromise_offer(
        scenario.case_id,
        f.compromise_offer_payload(fresh_version, installment_count=6),
        FINANCE_OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.ARREARS_BELOW_COMPROMISE_MINIMUM.value, 409)


def test_03_neither_refused_request_left_an_offer_on_the_case():
    """
    Both refusals are refusals: the case still carries no settlement offer.

    When a request violates more than one rule, exactly one error is returned, and which one is fully determined. Checks are evaluated in the following order, and the first failing check answers.

    Design: Difficulty/priority_pair_validation_conflict/stale_case_version_beats_arrears_below_compromise_minimum
    """
    scenario = _case_with_arrears_below_the_compromise_floor()

    stale_version = scenario.case["version"]
    fresh_version = fx.run_accrual(scenario.case_id)["version"]

    for version in (stale_version, fresh_version):
        api_client.create_compromise_offer(
            scenario.case_id,
            f.compromise_offer_payload(version, installment_count=6),
            FINANCE_OFFICER_HEADERS,
        )

    offers, meta = validate_paginated(
        api_client.list_compromise_offers(
            FINANCE_OFFICER_HEADERS, {"case_id": scenario.case_id}
        )
    )
    assert offers == []
    assert meta["total_count"] == 0
    # The refused writes did not move the case either.
    assert fx.read_case(scenario.case_id)["version"] == fresh_version


# ---------------------------------------------------------------------------
# Segregation of duties answers before the rejection limit
# ---------------------------------------------------------------------------


def test_04_the_drafter_is_refused_on_duties_even_with_the_rejection_limit_spent():
    """
    Two independent bars stand against this decision and the safety bar answers.

    Below the state band sit the safety and compliance checks in this order: good-cause confidentiality (`ERR_GOOD_CAUSE_BARS_DISCLOSURE`), paternity settlement before order work (`ERR_PATERNITY_NOT_ESTABLISHED`), and segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_deviation_rejection_limit
    """
    scenario = _order_awaiting_findings_with_the_rejection_limit_spent()

    assert scenario.order["drafted_by_user_id"] == DRAFTER_USER_ID
    assert scenario.order["guideline_monthly_cents"] == 75000
    assert scenario.order["status"] == "PENDING_DEVIATION_FINDINGS"
    assert scenario.order["deviation_rejection_count"] == 2

    response = api_client.decide_deviation_findings(
        scenario.order_id,
        f.deviation_findings_payload("REJECT"),
        make_supervising_attorney_headers(DRAFTER_USER_ID),
    )
    refusal = validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    assert refusal["error_id"] != ApiErrorId.DEVIATION_REJECTION_LIMIT.value


def test_05_a_second_attorney_meets_the_rejection_limit_on_the_same_decision():
    """
    Changing only the caller exposes the counting bar underneath.

    A rejection may only be recorded while `deviation_rejection_count` is still below two; a third rejection on the same order is refused with `ERR_DEVIATION_REJECTION_LIMIT` (HTTP 409).

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_deviation_rejection_limit
    """
    scenario = _order_awaiting_findings_with_the_rejection_limit_spent()

    response = api_client.decide_deviation_findings(
        scenario.order_id,
        f.deviation_findings_payload("REJECT"),
        make_supervising_attorney_headers(REVIEWER_USER_ID),
    )
    validate_error(response, ApiErrorId.DEVIATION_REJECTION_LIMIT.value, 409)


def test_06_neither_refused_decision_moved_the_order_or_its_counter():
    """
    A refused rejection is not a rejection: nothing advances and nobody signs.

    A `REJECT` drives `PENDING_DEVIATION_FINDINGS → CALCULATED`, increases `deviation_rejection_count` by 1, and clears both `deviation_requested_cents` and `deviation_reason` back to absent, leaving the caseworker free to try again.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_deviation_rejection_limit
    """
    scenario = _order_awaiting_findings_with_the_rejection_limit_spent()
    version_before = scenario.order["version"]

    for user_id in (DRAFTER_USER_ID, REVIEWER_USER_ID):
        api_client.decide_deviation_findings(
            scenario.order_id,
            f.deviation_findings_payload("REJECT"),
            make_supervising_attorney_headers(user_id),
        )

    settled = fx.read_order(scenario.order_id)
    assert settled["status"] == "PENDING_DEVIATION_FINDINGS"
    assert settled["deviation_rejection_count"] == 2
    assert settled["deviation_requested_cents"] == 60000
    assert settled.get("findings_approved_by_user_id") is None
    assert settled["version"] == version_before
