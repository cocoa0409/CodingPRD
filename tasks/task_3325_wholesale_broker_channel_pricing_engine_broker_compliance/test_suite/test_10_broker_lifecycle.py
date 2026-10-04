"""Broker suspension, reinstatement, termination and the loan-underwriting gate."""
from test_helpers import (
    ANY,
    ApiErrorId,
    broker_version,
    financial_strength_score,
    get_broker,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CM,
    approve_broker,
    create_and_approve_broker,
    create_submitted_broker,
    record_and_pass_financial_review,
    record_license,
    set_clock,
    setup_full_scenario,
    setup_loan_in_state,
    underwrite_loan,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_broker_headers,
    make_channel_manager_headers,
    make_underwriter_headers,
)


def _approved_broker_with_no_active_loans():
    """Approved broker holding one funded loan, so active_loan_count is back at 0."""
    return setup_loan_in_state("FUNDED")


def test_automatic_suspension_blocks_the_loan_advance_and_reinstatement_restores_it(api):
    """PRD §3.7: "then the broker must be `APPROVED` and its `exclusivity_status` must not be
    `BLOCKED`, or the request fails with `ERR_BROKER_NOT_APPROVED`"
    PRD §2.4: "an `APPROVED` broker is moved to `SUSPENDED` automatically the moment any of
    four triggers holds ... when `financial_strength_score` is less than 40.00, the reason is
    `FINANCIAL`"

    Design: Difficulty/cross_entity_state_dependency/loan_underwriting_requires_broker_approved_and_not_blocked
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]
    loan_id = scenario["loan_id"]

    # A PASSED review carrying a sub-40 financial score trips the automatic FINANCIAL
    # suspension (PRD §2.4).
    validate_success(
        api_client.create_financial_review(
            b,
            {
                "net_worth_cents": 25_000_000,
                "liquidity_cents": 0,
                "total_liabilities_cents": 0,
                "years_in_business": 0,
                "prior_year_funded_volume_cents": 0,
                "audit_attested": True,
            },
            make_channel_manager_headers(),
        ),
        expected_status=201,
    )
    reviews, _ = validate_paginated(api_client.list_financial_reviews(b, ANY))
    pending = [r for r in reviews if r["status"] == "PENDING"]
    assert len(pending) == 1, "exactly the review just recorded is still undecided"
    validate_success(
        api_client.decide_financial_review(
            pending[0]["id"], {"outcome": "PASSED"}, make_channel_manager_headers()
        )
    )

    suspended = get_broker(b)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspended_reason"] == "FINANCIAL"
    assert suspended["financial_strength_score"] == 30.00

    # The loan cannot advance while the broker is not APPROVED. Which gate answers
    # depends on how the reader models the suspension cascade, so the assertion is
    # the shared invariant: the call is refused and the loan does not move.
    blocked = api_client.underwrite_loan(
        loan_id, {"expected_broker_version": broker_version(b)}, make_underwriter_headers()
    )
    assert blocked.status_code >= 400, "a non-APPROVED broker must not advance a loan"
    assert blocked.json()["data"]["error_id"] in (
        ApiErrorId.ERR_BROKER_NOT_APPROVED, ApiErrorId.ERR_LOAN_NOT_SUBMITTED,
    )
    assert validate_success(
        api_client.get_loan_submission(loan_id, ANY)
    )["status"] != "UNDERWRITING"

    reinstated = validate_success(api_client.reinstate_broker(b, make_channel_manager_headers()))
    assert reinstated["status"] == "APPROVED"
    assert reinstated["suspended_reason"] is None
    assert reinstated["version"] > suspended["version"]


def test_reinstatement_keeps_every_derived_counter_exactly(api):
    """PRD §2.4: "the broker returns to `APPROVED` and its `active_loan_count`,
    `rolling_funded_volume_cents` and `total_active_compensation_commitment_cents` are exactly
    the values they held immediately before the suspension — the system adds nothing and removes
    nothing."

    Design: Corner/cross_cutting_complexity_layers/soft_posture_reinstatement_keeps_every_derived_counter_exactly
    """
    # A loan in CONDITIONAL_APPROVAL counts toward both the active-loan count and the
    # lender-paid commitment, and — unlike a SUBMITTED loan — it is untouched by any
    # suspension cascade, so the counters have to survive the round trip on their own.
    scenario = setup_loan_in_state("CONDITIONAL_APPROVAL")
    b = scenario["broker_id"]
    before = get_broker(b)
    assert before["active_loan_count"] == 1
    assert before["total_active_compensation_commitment_cents"] == 250_000

    # Automatic suspension via a sub-40 PASSED financial review (PRD §2.4).
    validate_success(
        api_client.create_financial_review(
            b,
            {
                "net_worth_cents": 25_000_000,
                "liquidity_cents": 0,
                "total_liabilities_cents": 0,
                "years_in_business": 0,
                "prior_year_funded_volume_cents": 0,
                "audit_attested": True,
            },
            make_channel_manager_headers(),
        ),
        expected_status=201,
    )
    reviews, _ = validate_paginated(api_client.list_financial_reviews(b, ANY))
    pending = [r for r in reviews if r["status"] == "PENDING"]
    assert len(pending) == 1, "exactly the review just recorded is still undecided"
    validate_success(
        api_client.decide_financial_review(
            pending[0]["id"], {"outcome": "PASSED"}, make_channel_manager_headers()
        )
    )

    suspended = get_broker(b)
    assert suspended["status"] == "SUSPENDED"

    validate_success(api_client.reinstate_broker(b, make_channel_manager_headers()))
    after = get_broker(b)

    assert after["rolling_quality_score"] == 100.00
    assert after["rolling_funded_volume_cents"] == before["rolling_funded_volume_cents"] == 0
    assert after["active_loan_count"] == before["active_loan_count"] == 1
    assert (after["total_active_compensation_commitment_cents"]
            == before["total_active_compensation_commitment_cents"] == 250_000)
    assert after["suspended_reason"] is None
    assert after["version"] > suspended["version"]


def test_reinstatement_of_an_approved_broker_is_refused(api):
    """PRD §2.4: "a `SUSPENDED` broker may be reinstated to `APPROVED` only when
    `rolling_quality_score` is at least 60.00"
    PRD §3.1: "the broker's status must be `SUBMITTED`, or the request fails with
    `ERR_BROKER_NOT_SUBMITTED`"

    Design: Difficulty/cross_entity_state_dependency/loan_underwriting_requires_broker_approved_and_not_blocked
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]

    response = api_client.reinstate_broker(b, make_channel_manager_headers())
    validate_error(response, ApiErrorId.ERR_BROKER_NOT_SUBMITTED, expected_status=409)
    assert get_broker(b)["status"] == "APPROVED"


def test_suspension_withdraws_still_unstarted_loans_and_their_commitment(api):
    """PRD §3.1: "Both manual suspension and termination withdraw the broker's still-unstarted
    work: every loan of that broker in `SUBMITTED` status is moved to `WITHDRAWN`"
    PRD §3.1: "for each loan so withdrawn the broker's
    `total_active_compensation_commitment_cents` is reduced by that loan's `lender_paid_comp_cents`"

    Design: Difficulty/cross_entity_state_dependency/loan_underwriting_requires_broker_approved_and_not_blocked
    """
    scenario = setup_loan_in_state("UNDERWRITING")
    b = scenario["broker_id"]
    quote = scenario["quote"]
    plan = scenario["plan"]

    submitted = validate_success(
        api_client.create_loan_submission(
            {
                "broker_id": b, "pricing_quote_id": quote["id"],
                "borrower_name": "Still Unstarted Borrower", "property_state": "TX",
                "loan_amount_cents": 40_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
                "compensation_election": "LENDER_PAID", "comp_plan_id": plan["id"],
            },
            make_broker_headers(b),
        ),
        expected_status=201,
    )

    commitment_before = get_broker(b)["total_active_compensation_commitment_cents"]
    assert commitment_before == 500_000

    validate_success(
        api_client.suspend_broker(
            b, {"reason": "suspension withdraws unstarted work"},
            make_channel_manager_headers(),
        )
    )
    assert validate_success(api_client.get_loan_submission(submitted["id"], ANY))["status"] == "WITHDRAWN"
    assert get_broker(b)["total_active_compensation_commitment_cents"] == 250_000


def test_termination_is_refused_while_active_loans_remain(api):
    """PRD §2.5: "a termination requested while `active_loan_count` is non-zero is refused with
    `ERR_ACTIVE_LOANS_PRESENT`."
    PRD §3.1: "A `ChannelManager` may terminate a brokerage from `SUBMITTED`, `APPROVED` or
    `SUSPENDED`, provided `active_loan_count` is 0"

    Design: Difficulty/cross_entity_state_dependency/loan_underwriting_requires_broker_approved_and_not_blocked
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]
    assert get_broker(b)["active_loan_count"] == 1

    response = api_client.terminate_broker(b, make_channel_manager_headers())
    validate_error(response, ApiErrorId.ERR_ACTIVE_LOANS_PRESENT, expected_status=409)
    assert get_broker(b)["status"] == "APPROVED"


def test_termination_succeeds_on_a_broker_with_no_active_loans(api):
    """PRD §2.5: "it counts loans in a non-terminal status — `SUBMITTED`, `UNDERWRITING`,
    `CONDITIONAL_APPROVAL`, `SUSPENDED_REVIEW` and `CLEAR_TO_CLOSE`"
    PRD §3.1: "A `ChannelManager` may terminate a brokerage from `SUBMITTED`, `APPROVED` or
    `SUSPENDED`, provided `active_loan_count` is 0"

    Design: Difficulty/cross_entity_state_dependency/loan_underwriting_requires_broker_approved_and_not_blocked
    """
    scenario = _approved_broker_with_no_active_loans()
    b = scenario["broker_id"]
    assert get_broker(b)["active_loan_count"] == 0

    terminated = validate_success(api_client.terminate_broker(b, make_channel_manager_headers()))
    assert terminated["status"] == "TERMINATED"

    fetched = get_broker(b)
    assert fetched["status"] == "TERMINATED"
    assert fetched["active_loan_count"] == 0