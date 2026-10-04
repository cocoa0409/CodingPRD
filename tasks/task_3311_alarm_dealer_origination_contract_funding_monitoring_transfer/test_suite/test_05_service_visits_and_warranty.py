"""Service visits, the warranty line and the post-warranty dealer holdback sweep."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    set_logical_clock,
    setup_funded_direct_contract,
    setup_package_with_contract,
    submit_and_approve_package,
    fund_package,
    declare_package_contract,
    provision_monitoring_account,
    register_customer,
    setup_scheduled_visit,
    create_dealer_payload,
    validate_success,
    TEST_USERS,
)

_CHANNEL = TEST_USERS["channel_manager_headers"]
_ANALYST = TEST_USERS["funding_analyst_headers"]

# A PREMIUM contract funded on 2026-09-01 carries a warranty window ending 2027-03-01.
_POST_WARRANTY_AT = "2027-06-15T00:00:00Z"


def _dealer_package_children(dealer_code, holdback_rate, quality_tier,
                             package_reference, configs):
    """One dealer, one package, N children (one per config) all provisioned and funded.

    Returns (dealer, package, [child contracts]).
    """
    from test_helpers import validate_success as _vs
    dealer = _vs(api_client.create_dealer(
        create_dealer_payload(dealer_code=dealer_code, holdback_rate=holdback_rate,
                              quality_tier=quality_tier), _CHANNEL), 201)
    package = _vs(api_client.create_package(
        {"package_reference": package_reference, "dealer_id": dealer["id"]}, _ANALYST), 201)

    children = []
    for idx, config in enumerate(configs):
        customer = register_customer(
            full_name=f"{dealer_code} Sub {idx}",
            email=f"{dealer_code.lower()}.{idx}@example.com")
        child = declare_package_contract(
            package["id"], customer["id"], equipment_config_code=config,
            credit_score=700, contract_term_months=60, monthly_monitoring_cents=4999,
            installation_scheduled_at="2026-09-02T00:00:00Z",
            installation_engineer_id=f"ENG-{idx + 1}")
        provision_monitoring_account(child["id"])
        children.append(child)

    package = submit_and_approve_package(dealer, package["id"])
    fund_package(package["id"])
    children = [get_success_data(api_client.get_contract(c["id"], _ANALYST))
                for c in children]
    return dealer, package, children


def _perform_post_warranty_visit(contract_id):
    """Schedule and perform a post-warranty dealer-billable visit."""
    set_logical_clock(_POST_WARRANTY_AT)
    visit = setup_scheduled_visit(
        contract_id, scheduled_at=_POST_WARRANTY_AT, work_type="WARRANTY_REPAIR",
        technician_id="TECH-1")
    res = api_client.perform_service_visit(visit["id"], TEST_USERS["service_coordinator_headers"])
    return visit, validate_success(res, 200)


# ─── Difficulty: combinatorial_formula / post_warranty_sweep_holdback_waterfall_cash_balance_cascade ───

def test_post_warranty_visit_bills_the_dealer_holdback_route(api):
    """PRD §3.8: "When the flag is false the visit is post-warranty, so its `billing_route` is `DEALER_HOLDBACK` and `dealer_sweep_cents` equals the 89-cent visit fee."
    PRD §3.8: "Performing the visit stamps `performed_at` from the logical clock and advances both the visit's `version` and the dealer's `version`."

    Design: Difficulty/combinatorial_formula/post_warranty_sweep_holdback_waterfall_cash_balance_cascade
    """
    dealer, package, children = _dealer_package_children(
        "D1", 0.10, "TIER_1", "PKG-P3", ["PREMIUM"])
    contract = children[0]

    visit, performed = _perform_post_warranty_visit(contract["id"])

    assert performed["billing_route"] == "DEALER_HOLDBACK"
    assert performed["billed_cents"] == 89
    assert performed["dealer_sweep_cents"] == 89
    assert performed["performed_at"] is not None


def test_post_warranty_sweep_remainder_becomes_a_cash_recovery_balance(api):
    """PRD §3.8: "The draw against the dealer's reserve is twenty percent of that base, rounded half-up to whole cents, and it is applied only up to what the dealer's `holdback_reserve_cents` can cover: the applied amount is the smaller of the rounded draw and the reserve."
    PRD §3.8: "If the draw exceeds what the reserve could cover, the remainder is added to the dealer's `chargeback_balance_due_cents` as a cash recovery case; otherwise the case is a holdback-only recovery."
    PRD §3.8: "the visit is billed against the contract's post-warranty base, `post_warranty_cents`, which is three times the contract's `capex_cents`"

    Design: Difficulty/combinatorial_formula/post_warranty_sweep_holdback_waterfall_cash_balance_cascade
    """
    dealer, package, children = _dealer_package_children(
        "D1", 0.10, "TIER_1", "PKG-P3", ["PREMIUM"])
    contract = children[0]
    # PREMIUM: capex 24900, holdback 2490 (the whole reserve at this point),
    # post_warranty base 74700, draw = round(0.20 * 74700) = 14940.
    assert contract["capex_cents"] == 24900

    _perform_post_warranty_visit(contract["id"])

    after = validate_success(api_client.get_dealer(dealer["id"], _ANALYST), 200)
    assert after["holdback_reserve_cents"] == 0
    assert after["chargeback_balance_due_cents"] == 14940 - 2490
    assert after["standing"] == "ACTIVE"