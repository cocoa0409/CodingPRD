"""Entity-level claims: not-found reads, server-minted identifiers, and the
computed per-type credit cost of a report."""

from test_helpers import (
    NON_EXISTENT_UUID,
    account_with_contract,
    assert_credit_ledger_invariant,
    create_account,
    create_report,
    get_success_data,
    read_contract,
    validate_error,
)
from test_helpers import ApiErrorId
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]


def test_get_unknown_contract_returns_not_found(api):
    """A well-formed but nonexistent contract id reports a 404.

    PRD: "**Existence.** Path resource identifiers must exist, validated left-to-right (`ERR_RESOURCE_NOT_FOUND`)."
    Design: Corner/entities/get_unknown_contract_returns_not_found
    """
    resp = api.get_contract(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.RESOURCE_NOT_FOUND.value, 404)


def test_create_account_ignores_client_supplied_id(api):
    """A client-supplied id in the create payload is ignored in favor of a server mint.

    PRD: "`id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix."
    PRD: "The account's `status` is `ACTIVE` upon creation"
    Design: Corner/entities/create_account_client_id_input_ignored
    """
    supplied = "11111111-2222-3333-4444-555555555555"
    resp = api.create_supplier_account(
        {"account_name": "Pi Pasta", "region": "NW", "id": supplied}, ADMIN
    )
    account = get_success_data(resp)
    assert account["id"] != supplied, "server must mint its own id, not honor the client's"
    assert account["version"] == 1
    assert account["status"] == "ACTIVE"
    assert account.get("created_at"), "created_at must be present"


def test_report_credit_cost_computed_per_type(api):
    """CATEGORY costs one credit, BRAND_OWN two, COMPETITOR_BLIND three; reserved sums to six.

    PRD: "a `CATEGORY` report costs one credit, a `BRAND_OWN` report costs two credits, and a `COMPETITOR_BLIND` report costs three credits."
    PRD: "Creating the report reserves its cost against the contract — the reserved counter increases by `credit_cost`"
    Design: Corner/entities/report_credit_cost_by_type_computed
    """
    world = account_with_contract(
        api, name="Rho Rice", tier="TIER_PORTFOLIO", scope_category="SNACKS", scope_brands=["ACME"]
    )
    r1 = create_report(api, world["contract"]["id"], world["analyst_headers"], report_type="CATEGORY")
    r2 = create_report(api, world["contract"]["id"], world["analyst_headers"], report_type="BRAND_OWN")
    r3 = create_report(api, world["contract"]["id"], world["analyst_headers"], report_type="COMPETITOR_BLIND")
    assert r1["credit_cost"] == 1
    assert r2["credit_cost"] == 2
    assert r3["credit_cost"] == 3
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credits_reserved"] == 6
    assert_credit_ledger_invariant(contract)
