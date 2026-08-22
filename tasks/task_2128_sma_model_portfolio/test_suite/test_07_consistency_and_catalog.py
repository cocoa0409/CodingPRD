"""Immediate visibility of allocation side effects, the resource-specific 404 family,
two state-precondition refusals, and the filtered-list discovery channel."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_account_payload,
    create_distribution_payload,
    create_block,
    create_fee_invoice_payload,
    create_harvest_proposal_payload,
    create_restriction,
    evaluate_drift,
    execute_block,
    get_account,
    get_trade_order,
    list_trade_orders,
    rebalance,
    setup_funded_account,
    setup_platform,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
MANAGER_HEADERS = TEST_USERS["portfolio_manager_headers"]
COMPLIANCE_HEADERS = TEST_USERS["compliance_officer_headers"]
BILLING_HEADERS = TEST_USERS["billing_officer_headers"]


def _single_cash_account(cash_cents=1000000, **account_overrides):
    """One published ALFA-only strategy with a single cash-funded account."""
    overrides = {"cash_reserve_bps": 100}
    overrides.update(account_overrides)
    return setup_funded_account(
        securities=[("ALFA", "Alfa Industrials", 10000)],
        sleeves=[("ALFA", 10000)],
        model_overrides={"drift_threshold_bps": 10},
        account_overrides=overrides,
        cash_cents=cash_cents,
    )


def test_allocation_reports_its_own_side_effects_without_a_reconciliation_step(api):
    """PRD §3.7: "A `BUY` allocation opens a new tax lot for the member's account and security, in status `OPEN`, with `origin` set to `TRADE`, `open_date` at the clock instant, `shares_open` equal to the allocated share count, `cost_basis_cents` equal to that share count multiplied by the fill price, `opening_trade_order_id` naming the order, a `sequence_number` drawn from the account's `next_order_sequence`, and `shares_closed` at 0 with `realized_gain_cents`, `close_date`, `closing_trade_order_id`, `parent_tax_lot_id`, `wash_window_start` and `wash_window_end` all null; the account's `cash_cents` is debited by the lot's cost basis."

    Design: Corner/consistency_model/allocation_side_effects_are_visible_in_the_same_response
    """
    env = _single_cash_account()
    account_id = env["account"]["id"]
    sponsor_id = env["sponsor"]["id"]

    evaluate_drift(account_id, sponsor_id, basis="SETTLED")
    rebalance(account_id, sponsor_id)
    orders = list_trade_orders(
        account_id=account_id,
        security_id=env["securities"]["ALFA"]["id"],
        status="PROPOSED",
    )
    assert len(orders) == 1
    order_id = orders[0]["id"]

    block = create_block([order_id], sponsor_id)
    execute_block(block["id"], 99, 10000)

    allocated = validate_success(api.allocate_block(block["id"], ADMIN_HEADERS), 200)
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_shares"] == 99
    assert allocated["unallocated_shares"] == 0

    lots, lots_meta = validate_paginated(
        api.list_tax_lots(
            ADMIN_HEADERS,
            params={"account_id": account_id, "opening_trade_order_id": order_id},
        )
    )
    assert lots_meta["total_count"] == 1
    new_lot = lots[0]
    assert new_lot["origin"] == "TRADE"
    assert new_lot["shares_open"] == 99
    assert new_lot["cost_basis_cents"] == 990000
    assert new_lot["status"] == "OPEN"
    assert new_lot["opening_trade_order_id"] == order_id
    assert new_lot["closing_trade_order_id"] is None

    account = get_account(account_id)
    assert account["cash_cents"] == 10000
    assert account["market_value_cents"] == 1000000

    order = get_trade_order(order_id)
    assert order["status"] == "ALLOCATED"
    assert order["allocated_shares"] == 99
    assert order["fill_price_cents"] == 10000


@pytest.mark.parametrize(
    "collection,role_key,expected_error",
    [
        ("securities", "platform_admin_headers", ApiErrorId.ERR_SECURITY_NOT_FOUND),
        ("sponsors", "platform_admin_headers", ApiErrorId.ERR_SPONSOR_NOT_FOUND),
        ("models", "portfolio_manager_headers", ApiErrorId.ERR_MODEL_NOT_FOUND),
        (
            "model-versions",
            "portfolio_manager_headers",
            ApiErrorId.ERR_MODEL_VERSION_NOT_FOUND,
        ),
        (
            "sponsor-distributions",
            "portfolio_manager_headers",
            ApiErrorId.ERR_DISTRIBUTION_NOT_FOUND,
        ),
        (
            "account-restrictions",
            "compliance_officer_headers",
            ApiErrorId.ERR_RESTRICTION_NOT_FOUND,
        ),
        (
            "trade-orders",
            "sponsor_operator_headers",
            ApiErrorId.ERR_TRADE_ORDER_NOT_FOUND,
        ),
        ("blocks", "platform_admin_headers", ApiErrorId.ERR_BLOCK_NOT_FOUND),
        ("tax-lots", "portfolio_manager_headers", ApiErrorId.ERR_TAX_LOT_NOT_FOUND),
        (
            "harvest-proposals",
            "portfolio_manager_headers",
            ApiErrorId.ERR_HARVEST_PROPOSAL_NOT_FOUND,
        ),
        ("fee-invoices", "billing_officer_headers", ApiErrorId.ERR_INVOICE_NOT_FOUND),
    ],
)
def test_an_unused_identifier_names_the_missing_resource_type(
    api, collection, role_key, expected_error
):
    """PRD §2.6: "The failure code names the missing type: `ERR_SECURITY_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_MODEL_VERSION_NOT_FOUND`, `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_RESTRICTION_NOT_FOUND`, `ERR_TRADE_ORDER_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_TAX_LOT_NOT_FOUND`, `ERR_HARVEST_PROPOSAL_NOT_FOUND` or `ERR_INVOICE_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/unknown_path_ids_return_the_resource_specific_not_found_error
    """
    response = api.raw_get(
        f"/sma/{collection}/{NON_EXISTENT_UUID}", headers=TEST_USERS[role_key]
    )
    validate_error(response, expected_error.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}


def test_rebalancing_an_account_that_was_never_evaluated_is_refused(api):
    """PRD §3.5: "The request is refused with `ERR_ACCOUNT_NOT_DRIFTED` when the account is in any other implementation state, and it requires a non-null `current_model_version_id`, which is the version whose sleeves drive the generation."

    Design: Corner/errors/rebalancing_a_synced_account_returns_account_not_drifted
    """
    env = _single_cash_account()
    account_id = env["account"]["id"]

    response = api.rebalance_account(account_id, env["sponsor_headers"])
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_DRIFTED.value)

    account = get_account(account_id)
    assert account["implementation_status"] == "SYNCED"
    assert account["drift_bps"] is None
    assert account["drift_evaluated_at"] is None

    orders, meta = validate_paginated(
        api.list_trade_orders(ADMIN_HEADERS, params={"account_id": account_id})
    )
    assert meta["total_count"] == 0
    assert orders == []


def test_opening_an_account_before_the_strategy_has_published_is_refused(api):
    """PRD §3.4: "If the strategy's `published_model_version_id` is null, the request is refused with `ERR_MODEL_NOT_PUBLISHED`."

    Design: Corner/errors/opening_an_account_on_an_unpublished_model_returns_model_not_published
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10000)],
        sleeves=[("ALFA", 10000)],
        publish=False,
    )
    sponsor = env["sponsor"]
    model = env["model"]

    response = api.create_account(
        create_account_payload(sponsor["id"], model["id"], account_number="ACC-001"),
        env["sponsor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_MODEL_NOT_PUBLISHED.value)

    stored_model = validate_success(api.get_model(model["id"], MANAGER_HEADERS), 200)
    assert stored_model["published_model_version_id"] is None

    stored_sponsor = validate_success(
        api.get_sponsor(sponsor["id"], ADMIN_HEADERS), 200
    )
    assert stored_sponsor["account_count"] == 0

    accounts, meta = validate_paginated(
        api.list_accounts(ADMIN_HEADERS, params={"sponsor_id": sponsor["id"]})
    )
    assert meta["total_count"] == 0
    assert accounts == []


def test_each_filtered_collection_read_resolves_the_child_of_its_parent(api):
    """PRD §2.11: "Collection reads narrow their result with query parameters rather than with path segments: model versions filter by `model_id` and `status`; distributions filter by `sponsor_id`, `model_version_id`, `model_id` and `status`; accounts filter by `sponsor_id`, `model_id`, `current_model_version_id`, `pending_model_version_id`, `implementation_status` and `billing_status`; restrictions filter by `account_id`, `security_id` and `status`; trade orders filter by `account_id`, `security_id`, `model_version_id`, `block_id`, `status`, `source` and `side`; blocks filter by `security_id`, `status` and `side`; tax lots filter by `account_id`, `security_id`, `parent_tax_lot_id`, `opening_trade_order_id`, `closing_trade_order_id`, `status` and `origin`; harvest proposals filter by `account_id`, `security_id`, `replacement_security_id` and `status`; and fee invoices filter by `account_id` and `status`."

    Design: Corner/endpoints/filtered_list_endpoints_resolve_children_from_their_foreign_keys
    """
    env = setup_funded_account(
        securities=[("ALFA", "Alfa Industrials", 10000)],
        sleeves=[("ALFA", 10000)],
        model_overrides={"drift_threshold_bps": 10},
        account_overrides={
            "cash_reserve_bps": 100,
            "tax_overlay_enabled": True,
            "harvest_budget_cents": 500000,
        },
        cash_cents=1000000,
        positions=[("ALFA", 100, 1200000, "TRANSFER_IN")],
    )
    alfa = env["securities"]["ALFA"]
    sponsor_id = env["sponsor"]["id"]
    model_version = env["model_version"]
    account_id = env["account"]["id"]

    distribution = validate_success(
        api.create_distribution(
            create_distribution_payload(
                sponsor_id,
                model_version["id"],
                model_version["version"],
                "2026-01-01T00:00:00Z",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    restriction = create_restriction(account_id, alfa["id"], "MAX_POSITION", 9000)

    account = evaluate_drift(account_id, sponsor_id, basis="SETTLED")
    assert account["market_value_cents"] == 2000000
    assert account["drift_bps"] == 4000
    assert account["implementation_status"] == "DRIFTED"

    rebalance(account_id, sponsor_id)
    orders = list_trade_orders(
        account_id=account_id, security_id=alfa["id"], status="PROPOSED"
    )
    assert len(orders) == 1
    order = orders[0]
    assert order["side"] == "BUY"
    assert order["shares"] == 78
    assert order["target_shares"] == 178
    assert order["effective_weight_bps"] == 9000

    block = create_block([order["id"]], sponsor_id)
    assert block["requested_shares"] == 78
    assert block["order_count"] == 1
    assert block["side"] == "BUY"
    assert block["security_id"] == alfa["id"]

    proposal = validate_success(
        api.create_harvest_proposal(
            create_harvest_proposal_payload(
                account_id, alfa["id"], 100, get_account(account_id)["version"]
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert proposal["target_loss_cents"] == -200000
    assert proposal["proposed_loss_cents"] == 200000

    invoice = validate_success(
        api.create_fee_invoice(
            create_fee_invoice_payload(
                account_id,
                period_start="2026-01-01T00:00:00Z",
                period_end="2026-04-01T00:00:00Z",
                average_daily_value_cents=30000000,
            ),
            BILLING_HEADERS,
        ),
        201,
    )

    reads = [
        (
            api.list_model_versions(
                MANAGER_HEADERS, params={"model_id": env["model"]["id"]}
            ),
            model_version["id"],
        ),
        (
            api.list_distributions(
                MANAGER_HEADERS, params={"model_version_id": model_version["id"]}
            ),
            distribution["id"],
        ),
        (
            api.list_restrictions(
                COMPLIANCE_HEADERS, params={"account_id": account_id}
            ),
            restriction["id"],
        ),
        (
            api.list_harvest_proposals(
                MANAGER_HEADERS, params={"account_id": account_id}
            ),
            proposal["id"],
        ),
        (
            api.list_fee_invoices(BILLING_HEADERS, params={"account_id": account_id}),
            invoice["id"],
        ),
        (
            api.list_blocks(ADMIN_HEADERS, params={"security_id": alfa["id"]}),
            block["id"],
        ),
    ]
    for response, expected_id in reads:
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [expected_id]
