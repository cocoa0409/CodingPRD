"""Loss mitigation waterfall: ordering, evaluation, modification restructure."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_timestamp_startswith,
    create_lm_action,
    declare_default,
    evaluate_lm_action,
    get_case,
    setup_endorsed_case,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    make_admin_headers,
    make_servicer_officer_headers,
)


def _setup_defaulted_case(api, legal_name="LM Co", **case_overrides):
    lender, case = setup_endorsed_case(
        lender_overrides={"legal_name": legal_name}, case_overrides=case_overrides
    )
    declare_default(case["id"], lender["id"])
    return lender, get_case(case["id"])


def test_loss_mitigation_evaluate_fail_stamps_evaluated_at(api):
    """PRD §3.8: "Evaluating a pending action is also a `ServicerOfficer` duty and
    always stamps `evaluated_at` from the logical clock. A `FAIL` decision moves the
    action to `FAILED` and an `INFEASIBLE` decision to `INFEASIBLE`, with no further
    computation."

    Design: Corner/state_machines/loss_mitigation_evaluate_fail_stamps_evaluated_at
    """
    lender, case = _setup_defaulted_case(api, legal_name="Fail Co",
                                         borrower_reference="LM-1")
    action = create_lm_action(case["id"], lender["id"], "REPAYMENT_PLAN")
    assert action["status"] == "PENDING"
    assert action["tier"] == 1
    response = api_client.evaluate_loss_mitigation_action(
        action["id"], {"decision": "FAIL"}, make_servicer_officer_headers(lender["id"])
    )
    data = validate_success(response)
    assert data["status"] == "FAILED"
    assert_timestamp_startswith(
        data["evaluated_at"], "2026-09-01T00:00:00", "evaluated_at"
    )


def test_waterfall_tier_skipped_while_pending_rejected(api):
    """PRD §3.8: "While any action of the case is still `PENDING`, all further creation
    is likewise rejected with `ERR_WATERFALL_ORDER_VIOLATION`."

    Design: Corner/calculations/waterfall_tier_skipped_while_pending_rejected
    """
    lender, case = _setup_defaulted_case(api, legal_name="Pending Block Co",
                                         borrower_reference="WF-1")
    create_lm_action(case["id"], lender["id"], "REPAYMENT_PLAN")
    response = api_client.create_loss_mitigation_action(
        case["id"], {"action_type": "SPECIAL_FORBEARANCE"},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_WATERFALL_ORDER_VIOLATION)


def test_modification_approve_rate_floor_clamps_at_300bps(api):
    """PRD §3.8: "Fifth, the modified rate is the case's `note_rate_bps` reduced by 200
    basis points, floored at 300 basis points. Sixth, the restructured monthly payment
    `new_payment_cents` is the new balance multiplied by the modified rate and divided
    by 120,000, rounded half-up to whole cents."
    PRD §3.8: "Second, late fees are the old payment multiplied by 400 basis points —
    that is, multiplied by 400 and divided by ten thousand, rounded half-up to whole
    cents — and then multiplied by the months late. Third, arrears are the months late
    multiplied by the old payment, plus the late fees, plus the escrow advances.
    Fourth, the restructured unpaid principal `new_upb_cents` is the case's
    `base_loan_amount_cents` plus the arrears."

    Design: Corner/calculations/modification_approve_rate_floor_clamps_at_300bps
    """
    # note_rate 400 -> 400 - 200 = 200 would undercut the 300 bps floor.
    lender, case = _setup_defaulted_case(
        api, legal_name="Rate Floor Co", borrower_reference="FL-1",
        note_rate_bps=400,
    )
    evaluate_lm_action(
        create_lm_action(case["id"], lender["id"], "REPAYMENT_PLAN")["id"],
        lender["id"], "FAIL",
    )
    evaluate_lm_action(
        create_lm_action(case["id"], lender["id"], "SPECIAL_FORBEARANCE")["id"],
        lender["id"], "FAIL",
    )
    action = create_lm_action(case["id"], lender["id"], "LOAN_MODIFICATION")
    response = api_client.evaluate_loss_mitigation_action(
        action["id"],
        {"decision": "APPROVE", "months_late": 4, "escrow_advances_cents": 80_000},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["status"] == "APPROVED"
    # late_fees = round_half_up(200,000 * 400/10,000) * 4 = 32,000;
    # arrears = 4*200,000 + 32,000 + 80,000 = 912,000; new_upb = 30,912,000.
    assert data["new_upb_cents"] == 30_912_000
    # modified rate clamps to 300: round_half_up(30,912,000 * 300 / 120,000) = 77,280.
    assert data["new_payment_cents"] == 77_280
    # reduction = round_half_up((200,000 - 77,280) / 200,000 * 10,000) = 6,136.
    assert data["reduction_bps"] == 6136


def test_error_modification_insufficient_reduction(api):
    """PRD §3.8: "Eighth, the approval is allowed only when that reduction is at least
    1,000 basis points — a ten percent payment reduction — and is otherwise rejected
    with `ERR_MODIFICATION_INSUFFICIENT_REDUCTION`."

    Design: Corner/errors/error_modification_insufficient_reduction
    """
    # note_rate 950 -> modified rate 750; months_late 1, no advances:
    # late_fees = 8,000; arrears = 208,000; new_upb = 30,208,000;
    # new_payment = round_half_up(30,208,000 * 750 / 120,000) = 188,800;
    # reduction = round_half_up(11,200 / 200,000 * 10,000) = 560 < 1,000.
    lender, case = _setup_defaulted_case(
        api, legal_name="Low Reduction Co", borrower_reference="LR-1",
        note_rate_bps=950,
    )
    evaluate_lm_action(
        create_lm_action(case["id"], lender["id"], "REPAYMENT_PLAN")["id"],
        lender["id"], "FAIL",
    )
    evaluate_lm_action(
        create_lm_action(case["id"], lender["id"], "SPECIAL_FORBEARANCE")["id"],
        lender["id"], "FAIL",
    )
    action = create_lm_action(case["id"], lender["id"], "LOAN_MODIFICATION")
    response = api_client.evaluate_loss_mitigation_action(
        action["id"],
        {"decision": "APPROVE", "months_late": 1, "escrow_advances_cents": 0},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MODIFICATION_INSUFFICIENT_REDUCTION)
    data, _meta = validate_paginated(
        api_client.list_loss_mitigation_actions(case["id"], make_admin_headers())
    )
    by_id = {a["id"]: a for a in data}
    assert by_id[action["id"]]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Difficulty: modification restructure pinned evaluation order
# ---------------------------------------------------------------------------
def _setup_pending_modification(api):
    """Endorsed (base 20,000,000, note 750 bps, payment 120,000) then defaulted case
    with tiers 1-2 INFEASIBLE and the tier-3 LOAN_MODIFICATION action PENDING."""
    lender, case = _setup_defaulted_case(
        api, legal_name="Pinned Order Co", borrower_reference="PIN-1",
        base_loan_amount_cents=20_000_000, appraised_value_cents=24_000_000,
        note_rate_bps=750, current_monthly_payment_cents=120_000,
    )
    evaluate_lm_action(
        create_lm_action(case["id"], lender["id"], "REPAYMENT_PLAN")["id"],
        lender["id"], "INFEASIBLE",
    )
    evaluate_lm_action(
        create_lm_action(case["id"], lender["id"], "SPECIAL_FORBEARANCE")["id"],
        lender["id"], "INFEASIBLE",
    )
    action = create_lm_action(case["id"], lender["id"], "LOAN_MODIFICATION")
    return lender, case, action


def test_modification_restructure_pinned_evaluation_order(api):
    """PRD §3.8: "An `APPROVE` decision on a `LOAN_MODIFICATION` runs the modification
    restructure in a pinned eight-step order, supplied with the number of `months_late`
    and any `escrow_advances_cents`."
    PRD §3.8: "On an allowed approval the three computed values are stored on the
    action and it moves to `APPROVED`."

    Design: Difficulty/combinatorial_formula/modification_restructure_pinned_evaluation_order
    """
    lender, _case, action = _setup_pending_modification(api)
    response = api_client.evaluate_loss_mitigation_action(
        action["id"],
        {"decision": "APPROVE", "months_late": 4, "escrow_advances_cents": 30_000},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["status"] == "APPROVED"
    # late_fees = round_half_up(120,000 * 400/10,000) * 4 = 19,200;
    # arrears = 4*120,000 + 19,200 + 30,000 = 529,200; new_upb = 20,529,200.
    assert data["new_upb_cents"] == 20_529_200
    # modified rate = 750 - 200 = 550; round_half_up(20,529,200 * 550 / 120,000) = 94,092.
    assert data["new_payment_cents"] == 94_092
    # reduction = round_half_up((120,000 - 94,092) / 120,000 * 10,000) = 2,159 >= 1,000.
    assert data["reduction_bps"] == 2159
    assert_timestamp_startswith(
        data["evaluated_at"], "2026-09-01T00:00:00", "evaluated_at"
    )


def test_modification_restructure_values_persist(api):
    """PRD §3.8: "On an allowed approval the three computed values are stored on the
    action and it moves to `APPROVED`."
    PRD §3.8: "The tiers in order are: `REPAYMENT_PLAN` (tier 1), `SPECIAL_FORBEARANCE`
    (tier 2), `LOAN_MODIFICATION` (tier 3), `PARTIAL_CLAIM` (tier 4),
    `PRE_FORECLOSURE_SALE` (tier 5), and `DEED_IN_LIEU` (tier 6); each created action
    has its `tier` derived from its `action_type` and lands in `PENDING`."

    Design: Difficulty/combinatorial_formula/modification_restructure_pinned_evaluation_order
    """
    lender, case, action = _setup_pending_modification(api)
    evaluate_lm_action(
        action["id"], lender["id"], "APPROVE",
        months_late=4, escrow_advances_cents=30_000,
    )
    data, _meta = validate_paginated(
        api_client.list_loss_mitigation_actions(case["id"], make_admin_headers())
    )
    by_id = {a["id"]: a for a in data}
    stored = by_id[action["id"]]
    assert stored["status"] == "APPROVED"
    assert stored["tier"] == 3
    assert stored["new_upb_cents"] == 20_529_200
    assert stored["new_payment_cents"] == 94_092
    assert stored["reduction_bps"] == 2159
