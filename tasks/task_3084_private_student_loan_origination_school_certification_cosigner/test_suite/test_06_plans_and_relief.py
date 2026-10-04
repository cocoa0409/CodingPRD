"""Repayment-plan supersession and private-loan forbearance administration."""
from test_helpers import (
    ERR_DEFERMENT_CAP_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_PRODUCT_RULE_UNSUPPORTED,
    TEST_USERS,
    approve_plan,
    forbearance_payload,
    get_success_data,
    record_enrollment,
    setup_certified_loan,
    setup_loan_in_repayment,
    set_clock,
    submit_standard_plan,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client


def _loan(orig):
    return validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))


def test_approving_a_second_plan_supersedes_the_active_one(api):
    """PRD §3.6: "Activating a plan supersedes any sibling plan already `ACTIVE`, sets
    the loan's `active_plan_type` to the newly activated plan's `plan_type`, and
    increments the loan's `version`."
    PRD §3.6: "At most one plan may be `ACTIVE` on a loan at any time, and the loan's
    `active_plan_type` mirrors the `plan_type` of that single active child or is null
    when none is active."

    Design: Difficulty/non_linear_state_machine/repayment_plan_supersede_chain_on_one_loan
    """
    orig = setup_loan_in_repayment(plan_type="STANDARD", term_months=120)
    standard_plan = orig.plan
    assert _loan(orig)["active_plan_type"] == "STANDARD"
    assert standard_plan["monthly_payment_cents"] == 8055

    extended = submit_standard_plan(orig.loan["id"], plan_type="EXTENDED", term_months=180)
    # The plan snapshots the loan's live principal (805000 disbursed plus the
    # 15096 capitalized at repayment entry), so the 180-month annuity is 5964.
    assert extended["monthly_payment_cents"] == 5964, "the 180-month annuity on 820096"
    approve_plan(extended["id"])

    superseded = validate_success(
        client.list_repayment_plans(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    by_id = {plan["id"]: plan for plan in superseded}
    assert by_id[standard_plan["id"]]["plan_status"] == "SUPERSEDED"
    assert by_id[standard_plan["id"]]["monthly_payment_cents"] == 8055, (
        "the superseded row keeps its pinned payment"
    )
    assert by_id[extended["id"]]["plan_status"] == "ACTIVE"


def test_the_loan_active_plan_type_follows_the_newest_active_child(api):
    """PRD §3.6: "the loan's `active_plan_type` mirrors the `plan_type` of that single
    active child or is null when none is active."
    PRD §2.10: "When a sibling plan is activated, any plan already `ACTIVE` on that
    loan is superseded."

    Design: Difficulty/non_linear_state_machine/repayment_plan_supersede_chain_on_one_loan
    """
    orig = setup_loan_in_repayment(plan_type="STANDARD", term_months=120)
    assert _loan(orig)["active_plan_type"] == "STANDARD"

    extended = submit_standard_plan(orig.loan["id"], plan_type="EXTENDED", term_months=180)
    approve_plan(extended["id"])

    loan = _loan(orig)
    assert loan["active_plan_type"] == "EXTENDED"
    assert loan["loan_status"] == "REPAYMENT"
    active = [p for p in validate_success(
        client.list_repayment_plans(orig.loan["id"], TEST_USERS["servicer_headers"])
    ) if p["plan_status"] == "ACTIVE"]
    assert len(active) == 1, "at most one ACTIVE plan may exist per loan"


def test_activating_an_extended_plan_longer_than_the_product_term_is_refused(api):
    """PRD §3.6: "when the `plan_type` is `EXTENDED` — requires the requested
    `term_months` to be no longer than the product's `extended_term_months`, whose
    default is 120. An `EXTENDED` plan whose term exceeds that ceiling is rejected
    outright rather than silently clamped, with `ERR_PRODUCT_RULE_UNSUPPORTED`"

    Design: Difficulty/non_linear_state_machine/repayment_plan_supersede_chain_on_one_loan
    """
    orig = setup_loan_in_repayment(periods=30, policy_overrides={"extended_term_months": 120})
    version = _loan(orig)["version"]
    response = client.create_repayment_plan(
        orig.loan["id"],
        {"plan_type": "EXTENDED", "term_months": 180, "expected_loan_version": version},
        orig.applicant_headers,
    )
    validate_error(response, ERR_PRODUCT_RULE_UNSUPPORTED)


def test_a_declined_plan_can_never_be_approved(api):
    """PRD §3.6: "A pending plan may instead be declined, which leaves the loan's
    `active_plan_type` unchanged."
    PRD §3.6: "A plan opens in `PENDING_APPROVAL` — its `plan_status` — and
    `SUPERSEDED` and `DECLINED` are its terminal states."

    Design: Corner/state_machines/approve_a_declined_repayment_plan_returns_invalid_state
    """
    orig = setup_loan_in_repayment(plan_type="STANDARD", term_months=120)
    graduated = submit_standard_plan(orig.loan["id"], plan_type="GRADUATED", term_months=120)
    declined = validate_success(
        client.decline_plan(graduated["id"], TEST_USERS["servicer_headers"])
    )
    assert declined["plan_status"] == "DECLINED"

    response = client.approve_plan(graduated["id"], TEST_USERS["servicer_headers"])
    validate_error(response, ERR_INVALID_STATE)
    loan = _loan(orig)
    assert loan["active_plan_type"] == "STANDARD"
    assert validate_success(
        client.list_repayment_plans(orig.loan["id"], TEST_USERS["servicer_headers"])
    )[-1]["plan_status"] == "DECLINED"


def test_a_relief_guard_that_has_already_started_cannot_be_cancelled(api):
    """PRD §3.7: "A granted relief that has not yet started — its `start_date` is not
    in the past relative to the logical clock — may be cancelled... Cancelling
    reduces the loan's `cumulative_deferment_months` by the cancelled
    `months_granted` and restores the loan to the state it held before the relief"

    Design: Corner/state_machines/forbearance_cancel_is_refused_once_the_grant_has_started
    """
    orig = setup_certified_loan(disburse=True)
    first = get_success_data(
        client.request_forbearance(
            orig.loan["id"],
            forbearance_payload(relief_type="IN_SCHOOL_DEFERMENT", months_requested=2,
                                start_date="2026-11-01T00:00:00Z"),
            TEST_USERS["servicer_headers"],
        )
    )
    second = get_success_data(
        client.request_forbearance(
            orig.loan["id"],
            forbearance_payload(relief_type="RESIDENCY_DEFERMENT", months_requested=2,
                                start_date="2027-01-02T00:00:00Z"),
            TEST_USERS["servicer_headers"],
        )
    )
    assert first["relief_status"] == "GRANTED"
    assert second["relief_status"] == "GRANTED"
    assert _loan(orig)["cumulative_deferment_months"] == 4

    set_clock("2026-12-01T00:00:00Z")
    started = client.cancel_forbearance(
        orig.loan["id"], first["id"], TEST_USERS["servicer_headers"]
    )
    validate_error(started, ERR_INVALID_STATE)

    cancelled = validate_success(
        client.cancel_forbearance(orig.loan["id"], second["id"], TEST_USERS["servicer_headers"])
    )
    assert cancelled["relief_status"] == "CANCELLED"
    assert _loan(orig)["cumulative_deferment_months"] == 2


def test_a_relief_type_the_private_product_does_not_offer_is_refused(api):
    """PRD §3.7: "A request naming a type outside that set is denied and changes
    nothing on the loan, and it is refused with `ERR_PRODUCT_RULE_UNSUPPORTED`."

    Design: Corner/errors/private_product_refuses_a_relief_type_it_does_not_offer
    """
    orig = setup_certified_loan(disburse=True)
    response = client.request_forbearance(
        orig.loan["id"],
        forbearance_payload(
            relief_type="PUBLIC_SERVICE_LOAN_FORGIVENESS_DEFERMENT", months_requested=12
        ),
        TEST_USERS["servicer_headers"],
    )
    validate_error(response, ERR_PRODUCT_RULE_UNSUPPORTED)
    loan = _loan(orig)
    assert loan["cumulative_deferment_months"] == 0
    assert loan["loan_status"] == "IN_SCHOOL"


def test_relief_that_would_breach_the_in_school_cap_is_refused(api):
    """PRD §3.7: "while the loan is `IN_SCHOOL` or `GRACE` the cap is the policy's
    `in_school_max_deferment_months`, whose default is 48 months... A request that
    would breach the cap is refused with `ERR_DEFERMENT_CAP_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/repayment_plan_supersede_chain_on_one_loan
    """
    orig = setup_certified_loan(
        disburse=True,
        policy_overrides={"in_school_max_deferment_months": 48},
    )
    response = client.request_forbearance(
        orig.loan["id"],
        forbearance_payload(months_requested=49, start_date="2026-11-01T00:00:00Z"),
        TEST_USERS["servicer_headers"],
    )
    validate_error(response, ERR_DEFERMENT_CAP_EXCEEDED)
    assert _loan(orig)["cumulative_deferment_months"] == 0


def test_months_granted_is_the_lesser_of_the_request_and_the_remaining_headroom(api):
    """PRD §3.7: "When a grant succeeds, `months_granted` is the lesser of the
    requested months and the remaining headroom under the applicable cap — that is,
    the cap minus the months already granted — the loan's
    `cumulative_deferment_months` is increased by that granted figure, and the
    loan's status moves to `FORBEARANCE_DEFERMENT`."

    Design: Difficulty/non_linear_state_machine/repayment_plan_supersede_chain_on_one_loan
    """
    orig = setup_certified_loan(
        disburse=True,
        policy_overrides={"in_school_max_deferment_months": 3},
    )
    granted = get_success_data(
        client.request_forbearance(
            orig.loan["id"],
            forbearance_payload(months_requested=3, start_date="2026-10-01T00:00:00Z"),
            TEST_USERS["servicer_headers"],
        )
    )
    # months_granted is the lesser of the requested months and the remaining
    # headroom under the applicable cap (3 - 0 here).
    assert granted["months_granted"] == 3, "capped at the remaining headroom"
    loan = _loan(orig)
    assert loan["cumulative_deferment_months"] == 3
    assert loan["loan_status"] == "FORBEARANCE_DEFERMENT"


def test_relief_refused_when_the_loan_is_not_in_a_relief_admitting_state(api):
    """PRD §3.7: "A relief grant is permitted only when the requested window is at
    least one month long, when the loan's current status admits relief — `IN_SCHOOL`,
    `GRACE`, `REPAYMENT` or `FORBEARANCE_DEFERMENT`"

    Design: Difficulty/cross_entity_state_dependency/loan_relief_transition_gated_by_the_loans_own_origination_state
    """
    from test_helpers import build_origination, approve as approve_application

    orig = build_origination(
        borrower_score=700, with_cosigner=False,
        policy_overrides={"allows_standalone_borrower": True},
        application_overrides={
            "requested_amount_cents": 500000,
            "cost_of_attendance_cents": 600000,
            "other_aid_cents": 100000,
        },
    )
    approve_application(orig)
    assert orig.loan["loan_status"] == "APPROVED"

    response = client.request_forbearance(
        orig.loan["id"],
        forbearance_payload(months_requested=3, start_date="2026-11-01T00:00:00Z"),
        TEST_USERS["servicer_headers"],
    )
    validate_error(response, ERR_INVALID_STATE)