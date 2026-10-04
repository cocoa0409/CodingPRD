"""Paired-rule precedence on a purchase, and numeric boundary precision on
the risk rollup and the exact-balance payoff.
"""
import pytest

from test_helpers import (
    onboard_partner,
    setup_active_agreement,
    issue_program,
    issue_account,
    setup_program,
)

from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_program_with_account,
    apply_principal,
    make_cardholder_headers,
    OVER_LIMIT_POINTS,
)


def _two_limit_accounts(api, headers):
    """One program, two accounts at a 200000 limit: exactly at limit, one
    cent over. Each rollup is read from its own program."""
    at_limit_partner = onboard_partner(api)
    at_agreement = setup_active_agreement(api, at_limit_partner["id"])
    at_program = issue_program(api, at_limit_partner["id"], at_agreement["id"])
    at_account = issue_account(api, at_program["id"], 200000)
    apply_principal(api, at_account["id"], 200000)
    score_at = validate_success(api.get_program_summary(at_program["id"], headers), 200)

    over_partner = onboard_partner(api)
    over_agreement = setup_active_agreement(api, over_partner["id"])
    over_program = issue_program(api, over_partner["id"], over_agreement["id"])
    over_account = issue_account(api, over_program["id"], 200000)
    apply_principal(api, over_account["id"], 200001)
    score_over = validate_success(api.get_program_summary(over_program["id"], headers), 200)
    return at_account, score_at, over_account, score_over


class TestPromoTermVersusMinimumChargePrecedence:

    def test_unsupported_term_below_the_floor_reports_the_term_error(self, api, admin_headers):
        """PRD §3.4: "The term check is evaluated before the minimum-charge check,
        so a purchase that is both below the floor and on an unsupported term
        reports the term error." PRD §3.4: "if the cardholder elected promotional
        financing, the requested term must be a member of the supported term set".

        Design: Difficulty/priority_pair_validation_conflict/promo_term_vs_minimum_charge_safety_precedence
        """
        _partner, _agreement, _program, account = setup_program_with_account(api, credit_limit_cents=200000)
        resp = api.create_transaction(
            {"account_id": account["id"], "merchant_name": "Bramble Tools",
             "amount_cents": 15000, "transaction_channel": "IN_STORE",
             "promo_requested": True, "promo_term_months": 9},
            make_cardholder_headers(account["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_PROMO_TERM, 422)
        assert error["error_id"] != ApiErrorId.ERR_PROMO_MINIMUM_CHARGE

    def test_unsupported_term_above_the_floor_still_reports_the_term_error(self, api, admin_headers):
        """PRD §3.4: "First, if the cardholder elected promotional financing, the
        requested term must be a member of the supported term set — the only
        permissible values are 6, 12, 18, and 24 months — and a term outside that
        set is rejected with `ERR_INVALID_PROMO_TERM` (HTTP 422)." With the amount
        above the floor, only the term check can fail.

        Design: Difficulty/priority_pair_validation_conflict/promo_term_vs_minimum_charge_safety_precedence
        """
        _partner, _agreement, _program, account = setup_program_with_account(api, credit_limit_cents=200000)
        before = validate_paginated(api.list_transactions(admin_headers, {"account_id": account["id"]}))[0]
        resp = api.create_transaction(
            {"account_id": account["id"], "merchant_name": "Bramble Saws",
             "amount_cents": 45000, "transaction_channel": "DIGITAL",
             "promo_requested": True, "promo_term_months": 9},
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PROMO_TERM, 422)
        after = validate_paginated(api.list_transactions(admin_headers, {"account_id": account["id"]}))[0]
        assert len(after) == len(before) == 0, "a rejected purchase leaves no transaction behind"


class TestOverLimitStrictBoundary:

    def test_one_cent_over_the_limit_scores_three_hundred_points_higher(self, api, admin_headers):
        """PRD §3.6: "An account whose `outstanding_balance_cents` exceeds its
        `credit_limit_cents` contributes 300 points; the comparison is strictly
        greater, so an account sitting exactly at its limit contributes nothing
        extra, and the score at that exact boundary is a full 300 points lower
        than one cent above it."

        Design: Difficulty/boundary_precision_check/credit_limit_over_limit_strict_greater_than_boundary
        """
        at_limit, score_at, over_limit, score_over = _two_limit_accounts(api, admin_headers)

        assert score_at["account_count"] == 1 and score_over["account_count"] == 1
        assert score_over["program_risk_score"] - score_at["program_risk_score"] == OVER_LIMIT_POINTS, (
            "the boundary itself contributes nothing; one cent above contributes 300"
        )

    def test_the_exact_limit_account_carries_no_over_limit_term(self, api, admin_headers):
        """PRD §3.6: "an account sitting exactly at its limit contributes nothing
        extra, and the score at that exact boundary is a full 300 points lower
        than one cent above it."

        Design: Difficulty/boundary_precision_check/credit_limit_over_limit_strict_greater_than_boundary
        """
        at_limit, score_at, over_limit, score_over = _two_limit_accounts(api, admin_headers)

        assert score_over["program_risk_score"] > score_at["program_risk_score"]
        assert (score_over["program_risk_score"] - score_at["program_risk_score"]) % OVER_LIMIT_POINTS == 0


class TestExactBalancePayoff:

    def test_payment_equal_to_the_balance_pays_the_account_off(self, api, admin_headers):
        """PRD §3.5: "An `ACTIVE` account whose payment covers the whole
        outstanding balance moves to `PAID_OFF` and its `outstanding_balance_cents`
        is set to zero."

        Design: Difficulty/boundary_precision_check/minimum_payment_zero_balance_empty_set_boundary
        """
        _partner, _agreement, _program, account = setup_program_with_account(api, credit_limit_cents=200000)
        apply_principal(api, account["id"], 5000)
        assert get_success_data(api.get_account(account["id"], admin_headers))["outstanding_balance_cents"] == 5000

        result = validate_success(
            api.post_payment(account["id"], 5000, make_cardholder_headers(account["id"])), 200
        )
        assert result["account_status"] == "PAID_OFF"
        assert result["outstanding_balance_cents"] == 0

    def test_paying_the_balance_floor_does_not_drive_a_principal_row_negative(self, api, admin_headers):
        """PRD §3.5: "The payment reduces the account's `principal_balance_cents`
        rows by the payment amount, floored at zero so that no slice goes
        negative, and then recomputes both the account's `outstanding_balance_cents`
        and the program's `program_profitability_cents`."

        Design: Difficulty/boundary_precision_check/minimum_payment_zero_balance_empty_set_boundary
        """
        _partner, _agreement, _program, account = setup_program_with_account(api, credit_limit_cents=200000)
        apply_principal(api, account["id"], 5000)

        validate_success(
            api.post_payment(account["id"], 5000, make_cardholder_headers(account["id"])), 200
        )
        rows, _meta = validate_paginated(api.list_account_balances(account["id"], admin_headers))
        assert sum(r["principal_balance_cents"] for r in rows) == 0, (
            "the principal slices sum to zero and none went negative"
        )
        assert all(r["principal_balance_cents"] >= 0 for r in rows)