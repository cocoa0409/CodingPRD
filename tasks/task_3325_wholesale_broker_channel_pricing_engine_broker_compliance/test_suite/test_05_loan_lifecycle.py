"""Loan submission, underwriting decisions, the suspended-review loop and closing."""
from test_helpers import (
    ANY,
    ApiErrorId,
    broker_version,
    get_broker,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CM,
    record_decision,
    resolve_escalation,
    set_clock,
    setup_conditional_approval_loan,
    setup_full_scenario,
    setup_funded_loan,
    setup_loan_in_state,
    setup_suspended_review_loan,
    underwrite_loan,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_broker_headers,
    make_underwriter_headers,
)


def _loan(loan_id):
    return validate_success(api_client.get_loan_submission(loan_id, ANY))


def test_suspended_review_loan_traverses_the_cycle_and_takes_the_other_branch(api):
    """PRD §3.7: "Resubmission returns the loan to `SUBMITTED` and sets `underwriting_due_at`
    to the logical clock plus ten days"
    PRD §3.7: "A `CONDITIONAL` decision requires a non-empty `conditions` array, and without
    one the request is refused with `ERR_DECISION_CONDITIONS_REQUIRED`; it moves the loan to
    `CONDITIONAL_APPROVAL`, sets that decision's `is_final` to true, and resets
    `underwriting_due_at` to `decided_at` plus ten days."

    Design: Difficulty/non_linear_state_machine/loan_submission_branching_fork_join_and_cyclic_review_loop
    """
    scenario = setup_full_scenario(state_code="TX")
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    underwrite_loan(loan_id, broker_version(b))
    record_decision(loan_id, "SUSPENDED", decision_notes="missing income docs for suspension review")
    assert _loan(loan_id)["status"] == "SUSPENDED_REVIEW"

    resubmitted = validate_success(
        api_client.resubmit_loan(
            loan_id,
            {"resubmission_note": "income documents supplied by broker"},
            make_broker_headers(b),
        )
    )
    assert resubmitted["status"] == "SUBMITTED", "resubmission re-enters the cycle at SUBMITTED"

    underwrite_loan(loan_id, broker_version(b))
    assert _loan(loan_id)["status"] == "UNDERWRITING"
    record_decision(loan_id, "CONDITIONAL", conditions=["updated appraisal"],
                    decision_notes="conditions cleared path")
    assert _loan(loan_id)["status"] == "CONDITIONAL_APPROVAL", (
        "the cycle re-entered the fork and took the conditional branch"
    )


def test_the_suspend_resubmit_cycle_records_two_decisions_in_order(api):
    """PRD §4: "List the underwriting decisions recorded on a loan, oldest first"
    PRD §3.7: "A `SUSPENDED` decision moves the loan to `SUSPENDED_REVIEW` and marks the
    decision final"

    Design: Difficulty/non_linear_state_machine/loan_submission_branching_fork_join_and_cyclic_review_loop
    """
    scenario = setup_full_scenario(state_code="TX")
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    underwrite_loan(loan_id, broker_version(b))
    first = record_decision(loan_id, "SUSPENDED", decision_notes="missing income docs")
    validate_success(
        api_client.resubmit_loan(
            loan_id, {"resubmission_note": "income documents supplied by broker"},
            make_broker_headers(b),
        )
    )
    underwrite_loan(loan_id, broker_version(b))
    # A distinct instant so the two decision rows differ on their creation
    # timestamp, which is the field the list endpoint orders by (PRD §2.3).
    set_clock("2026-09-02T00:00:00Z")
    second = record_decision(loan_id, "CONDITIONAL", conditions=["updated appraisal"])

    decisions, meta = validate_paginated(
        api_client.list_loan_underwriting_decisions(loan_id, ANY)
    )
    assert len(decisions) == 2
    assert meta["total_count"] == 2
    assert decisions[0]["id"] == first["id"]
    assert decisions[0]["decision_type"] == "SUSPENDED"
    assert decisions[0]["is_final"] is True
    assert decisions[1]["id"] == second["id"]
    assert decisions[1]["decision_type"] == "CONDITIONAL"

    # closing_path stays unset until the loan actually reaches CLEAR_TO_CLOSE.
    assert _loan(loan_id)["closing_path"] is None


def test_resubmit_is_refused_unless_the_loan_sits_in_suspended_review(api):
    """PRD §3.7: "only while the loan actually sits in `SUSPENDED_REVIEW` — any other status
    yields `ERR_LOAN_NOT_SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/loan_submission_branching_fork_join_and_cyclic_review_loop
    """
    scenario = setup_full_scenario()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    response = api_client.resubmit_loan(
        loan_id, {"resubmission_note": "premature resubmission attempt"},
        make_broker_headers(b),
    )
    validate_error(response, ApiErrorId.ERR_LOAN_NOT_SUSPENDED, expected_status=409)
    assert _loan(loan_id)["status"] == "SUBMITTED"


def test_underwriting_is_not_idempotent(api):
    """PRD §3.7: "the loan's own status must be `SUBMITTED`, or the request fails with
    `ERR_LOAN_NOT_SUBMITTED`"

    Design: Corner/state_machines/underwrite_is_not_idempotent_and_second_call_rejects
    """
    scenario = setup_full_scenario()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    first = underwrite_loan(loan_id, broker_version(b))
    assert first["status"] == "UNDERWRITING"
    due_after_first = first["underwriting_due_at"]

    second = api_client.underwrite_loan(
        loan_id, {"expected_broker_version": broker_version(b)}, make_underwriter_headers()
    )
    validate_error(second, ApiErrorId.ERR_LOAN_NOT_SUBMITTED, expected_status=409)
    after = _loan(loan_id)
    assert after["status"] == "UNDERWRITING"
    assert after["underwriting_due_at"] == due_after_first, "the deadline was not re-stamped"


def test_cleared_loan_takes_the_escalation_path_when_any_escalation_exists(api):
    """PRD §3.8: "`closing_path` is stamped as a snapshot: it is `ESCALATION_PATH` when any
    `TurnTimeEscalation` of that loan exists at that instant — any stage, any status — and
    `STANDARD_PATH` otherwise."
    PRD §3.8: "It reports `escalated_count`, `standard_count`, `near_deadline_count`,
    `escalated_loan_ids` and `standard_loan_ids`"

    Design: Corner/state_machines/cleared_loan_takes_escalation_path_when_any_escalation_exists
    """
    scenario = setup_conditional_approval_loan()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    set_clock("2026-09-20T00:00:00Z")
    escalations = validate_success(api_client.list_loan_escalations(loan_id, ANY))
    assert len(escalations) == 1
    assert escalations[0]["stage"] == "UNDERWRITING"
    assert escalations[0]["status"] == "OPEN"

    resolve_escalation(escalations[0]["id"])

    cleared = validate_success(
        api_client.clear_to_close_loan(loan_id, make_underwriter_headers())
    )
    assert cleared["status"] == "CLEAR_TO_CLOSE"
    assert cleared["closing_path"] == "ESCALATION_PATH"
    assert cleared["cleared_at"] is not None
    assert cleared["closing_due_at"] is not None

    pipeline = validate_success(
        api_client.get_closing_pipeline(ANY, {"broker_id": b})
    )
    assert pipeline["escalated_count"] == 1
    assert pipeline["standard_count"] == 0
    assert loan_id in pipeline["escalated_loan_ids"]
    assert loan_id not in pipeline["standard_loan_ids"]


def test_a_clean_loan_clears_on_the_standard_path(api):
    """PRD §3.8: "it is `ESCALATION_PATH` when any `TurnTimeEscalation` of that loan exists at
    that instant — any stage, any status — and `STANDARD_PATH` otherwise."

    Design: Corner/state_machines/cleared_loan_takes_escalation_path_when_any_escalation_exists
    """
    scenario = setup_conditional_approval_loan()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    cleared = validate_success(api_client.clear_to_close_loan(loan_id, make_underwriter_headers()))
    assert cleared["closing_path"] == "STANDARD_PATH"

    pipeline = validate_success(api_client.get_closing_pipeline(ANY, {"broker_id": b}))
    assert pipeline["escalated_count"] == 0
    assert pipeline["standard_count"] == 1
    assert loan_id in pipeline["standard_loan_ids"]


def test_withdraw_is_refused_on_a_funded_loan(api):
    """PRD §3.6: "Withdrawal is permitted only while the loan is `SUBMITTED`, `UNDERWRITING` or
    `CONDITIONAL_APPROVAL`, and any other status yields `ERR_LOAN_NOT_WITHDRAWABLE`."

    Design: Corner/endpoints/withdraw_on_a_funded_loan_is_refused_by_the_state_gate
    """
    scenario = setup_funded_loan()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    response = api_client.withdraw_loan(loan_id, make_broker_headers(b))
    validate_error(response, ApiErrorId.ERR_LOAN_NOT_WITHDRAWABLE, expected_status=409)

    loan = _loan(loan_id)
    assert loan["status"] == "FUNDED"
    broker = get_broker(b)
    assert broker["rolling_funded_volume_cents"] == 40_000_000
    assert broker["total_active_compensation_commitment_cents"] == 0


def test_funded_volume_cohort_excludes_withdrawn_and_denied_loans(api):
    """PRD §2.5: "loans in `SUBMITTED`, `UNDERWRITING`, `CONDITIONAL_APPROVAL`,
    `SUSPENDED_REVIEW`, `CLEAR_TO_CLOSE`, `DENIED` or `WITHDRAWN` contribute zero."
    PRD §2.5: "`rolling_funded_volume_cents`, the sum of `loan_amount_cents` over the broker's
    `FUNDED` loans"

    Design: Corner/calculations/funded_volume_cohort_excludes_withdrawn_and_denied_loans
    """
    scenario = setup_full_scenario(with_borrower_plan=True)
    b = scenario["broker_id"]
    quote = scenario["quote"]
    plan = scenario["plan"]
    plan_borrower = scenario["plan_borrower"]

    # The scenario's own SUBMITTED loan is withdrawn first so that the only loans
    # left at the end are the two this test builds.
    validate_success(api_client.withdraw_loan(scenario["loan_id"], make_broker_headers(b)))

    withdrawn = validate_success(
        api_client.create_loan_submission(
            {
                "broker_id": b, "pricing_quote_id": quote["id"],
                "borrower_name": "Withdrawn Cohort Borrower", "property_state": "TX",
                "loan_amount_cents": 90_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
                "compensation_election": "BORROWER_PAID", "comp_plan_id": plan_borrower["id"],
            },
            make_broker_headers(b),
        ),
        expected_status=201,
    )
    validate_success(api_client.withdraw_loan(withdrawn["id"], make_broker_headers(b)))

    funded = validate_success(
        api_client.create_loan_submission(
            {
                "broker_id": b, "pricing_quote_id": quote["id"],
                "borrower_name": "Funded Cohort Borrower", "property_state": "TX",
                "loan_amount_cents": 40_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
                "compensation_election": "LENDER_PAID", "comp_plan_id": plan["id"],
            },
            make_broker_headers(b),
        ),
        expected_status=201,
    )
    underwrite_loan(funded["id"], broker_version(b))
    record_decision(funded["id"], "CONDITIONAL", conditions=["final HOA cert"])
    validate_success(api_client.clear_to_close_loan(funded["id"], make_underwriter_headers()))
    validate_success(api_client.fund_loan(funded["id"], make_underwriter_headers()))

    assert _loan(withdrawn["id"])["status"] == "WITHDRAWN"
    assert _loan(funded["id"])["status"] == "FUNDED"

    broker = get_broker(b)
    assert broker["rolling_funded_volume_cents"] == 40_000_000
    assert broker["rolling_funded_volume_cents"] != 130_000_000
    assert broker["active_loan_count"] == 0