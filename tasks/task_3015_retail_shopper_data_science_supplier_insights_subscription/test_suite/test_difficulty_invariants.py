"""Compensating invariants: the report credit ledger and the query budget must
balance at every observation, across reserve/cancel and execute/suppress."""

from test_helpers import (
    account_with_contract,
    assert_credit_ledger_invariant,
    assert_query_budget_invariant,
    create_approved_grant,
    create_report,
    get_success_data,
    read_contract,
    read_grant,
)
from test_helpers import factories
from test_helpers.test_users import TEST_USERS


def test_competitor_blind_create_reserves_three_credits(api):
    """Creating a COMPETITOR_BLIND report moves three credits from available to reserved.

    PRD: "a `COMPETITOR_BLIND` report costs three credits."
    PRD: "The invariant `report_credit_allowance` equals the sum of `report_credits_available`, `report_credits_reserved`, and `report_credits_consumed` holds at all times."
    Design: Difficulty/compensating_invariant/report_credit_ledger_invariant_through_reserve_cancel
    """
    world = account_with_contract(
        api, name="Xi Xacuti", tier="TIER_PORTFOLIO", scope_category="SNACKS", scope_brands=["ACME"]
    )
    create_report(api, world["contract"]["id"], world["analyst_headers"], report_type="COMPETITOR_BLIND")
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credits_available"] == 7
    assert contract["report_credits_reserved"] == 3
    assert contract["report_credits_consumed"] == 0
    assert_credit_ledger_invariant(contract)


def test_cancel_refunds_reservation_and_restores_the_ledger(api):
    """Cancelling the REQUESTED report returns all three credits, leaving a balanced ledger.

    PRD: "A `SupplierAnalyst` may cancel a report while it is still `REQUESTED` (any other state fails with `ERR_REPORT_NOT_CANCELLABLE`); cancellation moves it to `CANCELLED` and refunds the reservation by decreasing the reserved counter by `credit_cost`."
    PRD: "The invariant `report_credit_allowance` equals the sum of `report_credits_available`, `report_credits_reserved`, and `report_credits_consumed` holds at all times."
    Design: Difficulty/compensating_invariant/report_credit_ledger_invariant_through_reserve_cancel
    """
    world = account_with_contract(
        api, name="Xi Xacuti", tier="TIER_PORTFOLIO", scope_category="SNACKS", scope_brands=["ACME"]
    )
    report = create_report(
        api, world["contract"]["id"], world["analyst_headers"], report_type="COMPETITOR_BLIND"
    )
    cancelled = get_success_data(api.cancel_report(report["id"], world["analyst_headers"]))
    assert cancelled["status"] == "CANCELLED"
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credits_available"] == 10
    assert contract["report_credits_reserved"] == 0
    assert contract["report_credits_consumed"] == 0
    assert_credit_ledger_invariant(contract)


def _approved_grant_200(api):
    world = account_with_contract(api, name="Omicron Oats")
    grant = create_approved_grant(
        api, world["account"]["id"], steward_user_id="steward-inv1", query_budget_total=200
    )
    return world, grant


def test_suppressed_query_refunds_its_cost_in_full(api):
    """A below-threshold query is charged then refunded, leaving the budget untouched.

    PRD: "If `result_rows` is below twenty, the query lands in `SUPPRESSED` instead, and the privacy refund policy applies — the cost is charged and then immediately refunded in full, leaving `query_budget_consumed` unchanged net-net"
    Design: Difficulty/compensating_invariant/query_budget_invariant_through_suppression_refund
    """
    world, grant = _approved_grant_200(api)
    query = get_success_data(api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES"], estimated_rows=10),
        world["analyst_headers"],
    ))
    assert query["status"] == "SUPPRESSED"
    assert query["query_cost"] == 1
    observed = read_grant(api, grant["id"])
    assert observed["query_budget_consumed"] == 0
    assert observed["query_budget_remaining"] == 200
    assert_query_budget_invariant(observed)


def test_executed_query_debits_permanently_and_balances(api):
    """A 5200-row single-join query on a TIER_CATEGORY contract debits six credits permanently.

    PRD: "A grant tracks its consumption through `query_budget_consumed`, the sum of the `query_cost` of its executed queries, and exposes `query_budget_remaining` as the read-only difference between `query_budget_total` and `query_budget_consumed`; the invariant that the total equals consumed plus remaining holds at all times."
    Design: Difficulty/compensating_invariant/query_budget_invariant_through_suppression_refund
    """
    world, grant = _approved_grant_200(api)
    query = get_success_data(api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES"], estimated_rows=5200),
        world["analyst_headers"],
    ))
    assert query["status"] == "EXECUTED"
    assert query["query_cost"] == 6
    observed = read_grant(api, grant["id"])
    assert observed["query_budget_consumed"] == 6
    assert observed["query_budget_remaining"] == 194
    assert_query_budget_invariant(observed)
