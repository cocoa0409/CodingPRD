"""Consistency corner: credit reservations are visible on the very next read."""

from test_helpers import (
    account_with_contract,
    assert_credit_ledger_invariant,
    create_report,
    read_contract,
)


def test_credit_reservation_visible_immediately(api):
    """A BRAND_OWN create is observable on the contract read in the very next request.

    PRD: "Creating the report reserves its cost against the contract — the reserved counter increases by `credit_cost`"
    PRD: "The invariant `report_credit_allowance` equals the sum of `report_credits_available`, `report_credits_reserved`, and `report_credits_consumed` holds at all times."
    Design: Corner/consistency_model/credit_reservation_visible_immediately
    """
    world = account_with_contract(
        api, name="Now Co", tier="TIER_BRAND", scope_category="SNACKS", scope_brands=["ACME"]
    )
    create_report(api, world["contract"]["id"], world["analyst_headers"], report_type="BRAND_OWN")
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credits_reserved"] == 2
    assert contract["report_credits_available"] == 8
    assert contract["report_credits_consumed"] == 0
    assert_credit_ledger_invariant(contract)
