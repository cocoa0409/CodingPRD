"""Collateral postings, deposit coverage and the deposit ledger."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_deposit, assert_deposit_transaction,
    set_clock, create_participant, create_active_participant, get_deposit,
    post_deposit, member, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_deposit_balance_sums_signed_postings():
    """PRD §2.5: "The pool's read-only `posted_amount_cents` is the sum of
    `amount_cents` over every transaction of that deposit, including negative
    releases."
    PRD §2.5: "a `txn_type` of `POST` or `RELEASE` derived from the sign of
    `amount_cents`."

    Design: Corner/calculations/deposit_posted_balance_sums_signed_postings
    """
    set_clock()
    participant = create_active_participant("Deposit Corner Co", "LEI-DEP1")
    pool = get_deposit(participant["id"])

    posted = post_deposit(pool["id"], participant["id"], 500000)
    assert_deposit_transaction(posted)
    assert posted["txn_type"] == "POST"

    released = post_deposit(pool["id"], participant["id"], -200000, "COLLATERAL_RELEASE")
    assert_deposit_transaction(released)
    assert released["txn_type"] == "RELEASE"

    pool_after = validate_success(api_client.get_deposit(pool["id"], ADMIN), 200)
    assert_deposit(pool_after)
    assert pool_after["posted_amount_cents"] == 300000
    assert pool_after["status"] == "SATISFIED"


def test_release_without_reason_code_is_refused():
    """PRD §2.5: "A negative posting must carry a `reason_code`".
    PRD §2.5: "A release that would drive `posted_amount_cents` below zero, or
    that omits its reason, is rejected with `ERR_DEPOSIT_RELEASE_INVALID`".

    Design: Corner/errors/release_without_reason_code_rejected
    """
    set_clock()
    participant = create_active_participant("Release Co", "LEI-DP2")
    pool = get_deposit(participant["id"])
    post_deposit(pool["id"], participant["id"], 500000)

    res = api_client.post_deposit_transaction(
        pool["id"], {"amount_cents": -100000}, member(participant["id"]))
    validate_error(res, "ERR_DEPOSIT_RELEASE_INVALID")

    over = api_client.post_deposit_transaction(
        pool["id"], {"amount_cents": -600000, "reason_code": "OVER_RELEASE"},
        member(participant["id"]))
    validate_error(over, "ERR_DEPOSIT_RELEASE_INVALID")

    unchanged = validate_success(api_client.get_deposit(pool["id"], ADMIN), 200)
    assert unchanged["posted_amount_cents"] == 500000


def test_clearing_member_cannot_fund_another_participants_obligation():
    """PRD §2.1: "When `X-User-Role` is `ClearingMember`, by contrast,
    `X-User-ID` is the `id` of the acting `Participant`".
    PRD §2.1: "is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/clearing_member_cannot_fund_another_participants_obligation
    """
    from test_helpers import setup_netted_obligation

    owner, other, _security, _window, obligation = setup_netted_obligation(
        ticker="OWN1", cusip="912828XV3")

    res = api_client.fund_net_position(
        obligation["id"], {"amount_cents": 400000}, member(other["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")

    assert validate_success(
        api_client.get_net_position(obligation["id"], ADMIN), 200
    )["funded_amount_cents"] == 0

    funded = validate_success(
        api_client.fund_net_position(obligation["id"], {"amount_cents": 400000},
                                     member(owner["id"])), 200)
    assert funded["funded_amount_cents"] == 400000


def test_financial_review_rederives_deposit_standing_against_obligations():
    """PRD §2.5: "Coverage is evaluated in the same pass against the member's
    obligations: those obligations are the sum of `settlement_obligation_cents`
    across all of the member's net positions whose `dvp_status` is not
    `FAILED`."
    PRD §3.1: "it also re-evaluates the member's deposit pool standing and
    advances the member's version."

    Design: Corner/calculations/deposit_posted_balance_sums_signed_postings
    """
    from test_helpers import setup_netted_obligation

    owner, other, security, window, obligation = setup_netted_obligation(
        ticker="NET1", cusip="912828XK1")

    assert obligation["settlement_obligation_cents"] == max(obligation["cash_delta_cents"], 0)
    obligation_sum = obligation["settlement_obligation_cents"]

    before = validate_success(api_client.get_participant(owner["id"], ADMIN), 200)
    after = validate_success(api_client.financial_review(
        owner["id"], {"net_capital_cents": 2000000000}, TEST_USERS["risk_officer_headers"]),
        200)
    assert after["version"] > before["version"]

    pool = validate_success(api_client.get_deposit(
        get_deposit(owner["id"])["id"], ADMIN), 200)
    if obligation_sum > 0:
        assert pool["status"] in ("SATISFIED", "DEFICIENT_GRACE")
    else:
        assert pool["status"] == "SATISFIED"