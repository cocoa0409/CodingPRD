"""Cross-entity state dependencies: suspension blocks deploy; anchor gate."""
from test_helpers import (
    api_client, validate_success, validate_error, setup_agreement_with_assets,
    create_account, create_jobsite, create_consumable_product,
    set_clock, make_contractor_manager_headers, make_field_engineer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]

SIX_UNIT_DRILL_CARD = {
    "tool_category": "DRILL", "base_monthly_rate_cents": 10000,
    "tier2_threshold": 5, "tier2_monthly_rate_cents": 9000,
    "tier3_threshold": 10, "tier3_monthly_rate_cents": 8000,
    "min_monthly_fee_cents": 25000,
}


def _suspended_agreement_env():
    set_clock("2026-09-16T00:00:00Z")
    env = setup_agreement_with_assets(
        n_assets=7, credit_limit_cents=25000,
        rate_card_overrides=SIX_UNIT_DRILL_CARD,
        start_date="2026-09-16T00:00:00Z")
    site = create_jobsite(env["account_id"], capacity_assets=10, cm=env["cm"])
    r = api_client.suspend_account(env["account_id"], ADMIN)
    account = validate_success(r)
    assert account["status"] == "SUSPENDED"
    env["jobsite"] = site
    return env


def test_deploy_blocked_when_agreement_suspended(api):
    """PRD §3.5: "Deploying a `REGISTERED` asset to a jobsite requires the
    owning agreement to be `ACTIVE` (otherwise `ERR_INVALID_STATE`)"

    Design: Difficulty/cross_entity_state_dependency/deploy_blocked_when_agreement_suspended
    """
    env = _suspended_agreement_env()
    r = api_client.deploy_asset(env["asset_ids"][0], env["jobsite"]["id"], env["js"])
    validate_error(r, "ERR_INVALID_STATE")


def test_deploy_unblocked_after_reinstate(api):
    """PRD §3.1: "reinstatement cascades every `SUSPENDED` agreement of the
    account back to `ACTIVE`"
    PRD §3.5: "Deploying a `REGISTERED` asset to a jobsite requires the owning
    agreement to be `ACTIVE` (otherwise `ERR_INVALID_STATE`)"

    Design: Difficulty/cross_entity_state_dependency/deploy_blocked_when_agreement_suspended
    """
    env = _suspended_agreement_env()
    # Activation at 2026-09-16 bills the prorated half-month: 7 units over the
    # SIX_UNIT_DRILL_CARD tier split (4*10000 + 3*9000 = 67000) at factor
    # 15/30 = 0.5 -> 33500 outstanding against the 25000 limit. Reinstatement
    # needs outstanding <= credit_limit (PRD §3.1), so pay down to exactly the
    # limit: 33500 - 25000 = 8500.
    r = api_client.record_payment(env["account_id"], 8500, env["cm"])
    validate_success(r)
    r = api_client.reinstate_account(env["account_id"], ADMIN)
    validate_success(r)
    asset = api_client.deploy_asset(env["asset_ids"][0], env["jobsite"]["id"],
                                    env["js"])
    deployed = validate_success(asset)
    assert deployed["status"] == "DEPLOYED"


def _anchor_gate_env():
    account = create_account()
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    product = create_consumable_product(
        sku="ANC-1", name="Wedge anchor", unit_price_cents=1200, pack_size=50,
        requires_application_approval=True)
    site = create_jobsite(acct, capacity_assets=5, cm=cm)
    r = api_client.create_support_case(
        acct, {"kind": "ANCHOR_DESIGN", "jobsite_id": site["id"],
               "scheduled_for": "2026-09-10T10:00:00Z"}, cm)
    case = validate_success(r, expected_status=201)
    r = api_client.create_consumable_order(
        acct, [{"product_id": product["id"], "quantity_units": 50}], cm)
    order = validate_success(r, expected_status=201)
    return {"account_id": acct, "cm": cm, "case": case, "order": order,
            "site": site}


def test_submit_blocked_while_anchor_case_open(api):
    """PRD §3.8: "every line whose product carries
    `requires_application_approval` must be covered by a `DOCUMENTED` support
    case of kind `ANCHOR_DESIGN` on the same account — a missing coverage is
    rejected with `ERR_APPLICATION_APPROVAL_REQUIRED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/consumable_submit_requires_documented_anchor_case
    """
    env = _anchor_gate_env()
    r = api_client.submit_consumable_order(
        env["account_id"], env["order"]["id"], env["cm"])
    validate_error(r, "ERR_APPLICATION_APPROVAL_REQUIRED")


def test_submit_allowed_after_anchor_case_documented(api):
    """PRD §3.8: "every line whose product carries
    `requires_application_approval` must be covered by a `DOCUMENTED` support
    case of kind `ANCHOR_DESIGN` on the same account — a missing coverage is
    rejected with `ERR_APPLICATION_APPROVAL_REQUIRED` (HTTP 422). A successful
    submit moves the order to `SUBMITTED` and stamps `submitted_at` from the
    logical clock."

    Design: Difficulty/cross_entity_state_dependency/consumable_submit_requires_documented_anchor_case
    """
    env = _anchor_gate_env()
    eng = make_field_engineer_headers("eng-gate1")
    r = api_client.review_support_case(
        env["account_id"], env["case"]["id"],
        {"decision": "APPROVE",
         "documentation_url": "https://docs.example/anchor-1.pdf"}, eng)
    case = validate_success(r)
    assert case["status"] == "DOCUMENTED"
    r = api_client.submit_consumable_order(
        env["account_id"], env["order"]["id"], env["cm"])
    order = validate_success(r)
    assert order["status"] == "SUBMITTED"
    assert order["total_cents"] == 60000, "1 pack * 50 * 1200"
    assert order["submitted_at"] is not None
