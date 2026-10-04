"""Corner/validations: fiscal gates, open-claim election block, RETURN gate,
credit boundary."""
from test_helpers import (
    api_client, validate_success, validate_error, create_account,
    create_consumable_product, setup_agreement_with_assets, setup_deployed_asset,
    report_claim, set_clock, make_contractor_manager_headers, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def test_suspend_without_balance_breach_returns_credit_error(api):
    """PRD §3.1: "A `FleetAdmin` may suspend an account only while its
    `outstanding_balance_cents` exceeds its `credit_limit_cents`; the attempt
    is otherwise rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/suspend_without_balance_breach_returns_credit_error
    """
    account = create_account(credit_limit_cents=100000)
    r = api_client.suspend_account(account["id"], ADMIN)
    validate_error(r, "ERR_CREDIT_LIMIT_EXCEEDED")


def _election_ready_env():
    set_clock("2026-09-01T00:00:00Z")
    return setup_agreement_with_assets(
        n_assets=1, term_months=1, start_date="2026-09-01T00:00:00Z",
        end_of_term_option="RETURN")


def test_election_blocked_by_open_claim(api):
    """PRD §3.7: "electing an end-of-term option is rejected with
    `ERR_AGREEMENT_HAS_OPEN_CLAIMS` while any claim on the agreement's assets
    is in `REPORTED` or `POLICE_VERIFIED`."

    Design: Corner/validations/election_blocked_by_open_claim
    """
    env = _election_ready_env()
    from test_helpers import create_jobsite, deploy_asset
    site = create_jobsite(env["account_id"], capacity_assets=5, cm=env["cm"])
    deploy_asset(env["asset_ids"][0], site["id"], env["js"])
    report_claim(env["asset_ids"][0], env["js"])
    r = api_client.elect_end_of_term(
        env["account_id"], env["agreement_id"],
        {"expected_agreement_version": env["agreement_version"],
         "end_of_term_option": "RETURN"}, env["cm"])
    validate_error(r, "ERR_AGREEMENT_HAS_OPEN_CLAIMS")
    from test_helpers import get_agreement, get_settlement_rows
    assert get_agreement(env["agreement_id"])["status"] == "ACTIVE"
    assert get_settlement_rows(env["agreement_id"]) == []


def test_return_finalize_blocked_by_deployed_asset(api):
    """PRD §3.9: "For `RETURN`, finalization additionally requires every asset
    of the agreement to be in `REGISTERED` or `RETIRED`; any asset still
    `DEPLOYED`, `IN_TRANSIT`, `IN_REPAIR`, or `LOST` blocks the close with
    `ERR_RETURN_INCOMPLETE`."

    Design: Corner/validations/return_finalize_blocked_by_deployed_asset
    """
    env = _election_ready_env()
    from test_helpers import create_jobsite, deploy_asset
    site = create_jobsite(env["account_id"], capacity_assets=5, cm=env["cm"])
    deploy_asset(env["asset_ids"][0], site["id"], env["js"])
    r = api_client.elect_end_of_term(
        env["account_id"], env["agreement_id"],
        {"expected_agreement_version": env["agreement_version"],
         "end_of_term_option": "RETURN"}, env["cm"])
    validate_success(r)
    r = api_client.finalize_settlement(
        env["account_id"], env["agreement_id"], 0, ADMIN)
    validate_error(r, "ERR_RETURN_INCOMPLETE")


def test_return_finalize_succeeds_after_check_in(api):
    """PRD §3.9: "For `RETURN`, finalization additionally requires every asset
    of the agreement to be in `REGISTERED` or `RETIRED`"
    PRD §3.9: "For `BUYOUT` and `RETURN`, finalization closes the agreement
    (`ENDING` to `CLOSED`)"

    Design: Corner/validations/return_finalize_blocked_by_deployed_asset
    """
    env = _election_ready_env()
    from test_helpers import create_jobsite, deploy_asset
    site = create_jobsite(env["account_id"], capacity_assets=5, cm=env["cm"])
    deploy_asset(env["asset_ids"][0], site["id"], env["js"])
    r = api_client.elect_end_of_term(
        env["account_id"], env["agreement_id"],
        {"expected_agreement_version": env["agreement_version"],
         "end_of_term_option": "RETURN"}, env["cm"])
    validate_success(r)
    r = api_client.check_in_asset(env["asset_ids"][0], env["js"])
    validate_success(r)
    r = api_client.finalize_settlement(
        env["account_id"], env["agreement_id"], 0, ADMIN)
    agreement = validate_success(r)
    assert agreement["status"] == "CLOSED"


def test_credit_boundary_exact_limit_approves(api):
    """PRD §3.8: "approval moves it to `APPROVED` but only while the order's
    `total_cents` plus the account's `outstanding_balance_cents` does not exceed
    the account's `credit_limit_cents` (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`),
    and on approval the total is added to the outstanding balance"

    Design: Corner/validations/credit_boundary_exact_limit_approves
    """
    account = create_account(credit_limit_cents=100000)
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    product = create_consumable_product(
        sku="P-V4A", name="Screws A", unit_price_cents=60000, pack_size=1,
        requires_application_approval=False)
    r = api_client.create_consumable_order(
        acct, [{"product_id": product["id"], "quantity_units": 1}], cm)
    order = validate_success(r, expected_status=201)
    r = api_client.submit_consumable_order(acct, order["id"], cm)
    validate_success(r)
    r = api_client.decide_consumable_order(acct, order["id"], "APPROVE", ADMIN)
    decided = validate_success(r)
    assert decided["status"] == "APPROVED", "60000 + 0 <= 100000"


def test_credit_boundary_one_cent_over_rejected(api):
    """PRD §3.8: "approval moves it to `APPROVED` but only while the order's
    `total_cents` plus the account's `outstanding_balance_cents` does not exceed
    the account's `credit_limit_cents` (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`)"

    Design: Corner/validations/credit_boundary_exact_limit_approves
    """
    account = create_account(credit_limit_cents=100000)
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    p_a = create_consumable_product(
        sku="P-V4A", name="Screws A", unit_price_cents=60000, pack_size=1,
        requires_application_approval=False)
    p_b = create_consumable_product(
        sku="P-V4B", name="Screws B", unit_price_cents=40001, pack_size=1,
        requires_application_approval=False)
    for product in (p_a, p_b):
        r = api_client.create_consumable_order(
            acct, [{"product_id": product["id"], "quantity_units": 1}], cm)
        order = validate_success(r, expected_status=201)
        r = api_client.submit_consumable_order(acct, order["id"], cm)
        validate_success(r)
        if product["id"] == p_a["id"]:
            r = api_client.decide_consumable_order(acct, order["id"], "APPROVE", ADMIN)
            validate_success(r)
    r = api_client.decide_consumable_order(acct, order["id"], "APPROVE", ADMIN)
    validate_error(r, "ERR_CREDIT_LIMIT_EXCEEDED")
