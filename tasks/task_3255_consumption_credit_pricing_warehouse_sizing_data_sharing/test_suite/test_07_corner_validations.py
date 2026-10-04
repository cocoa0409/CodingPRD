"""Corner queue B: validation claims."""
import pytest

from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    create_account,
    create_active_contract,
    create_contract,
    create_listing,
    create_monitor,
    create_published_listing,
    create_share,
    create_usage_event_payload,
    create_warehouse,
    create_warehouse_payload,
    current_version,
    eng_headers,
    fin_headers,
    get_contract,
    get_listing,
    get_monitor,
    list_drawdowns,
    list_warehouses,
    post_paid_usage,
    publish_listing,
    publish_share,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6


def test_an_absent_role_header_is_rejected_as_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers. `X-User-Role` names the
    operational capacity in which the caller is acting, and `X-User-ID`
    identifies the caller." PRD §2.1: "A request that omits `X-User-Role`, omits
    `X-User-ID` where it is required, or names a role outside that set is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    create_account(region="us-east-1")
    response = api_client.get_warehouse(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d3", {}
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_the_authentication_layer_precedes_path_resolution(api):
    """PRD §2.10: "The first layer is authentication, which is evaluated first on
    every endpoint except the clock capability: `ERR_UNAUTHENTICATED` (401) is
    raised when `X-User-Role` is missing". PRD §2.10: "an earlier layer always
    wins."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    create_account(region="us-east-1")
    anonymous = api_client.get_warehouse(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d3", {}
    )
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED)

    identified = api_client.get_warehouse(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d3", eng_headers()
    )
    validate_error(identified, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_the_share_publisher_role_cannot_activate_a_contract(api):
    """PRD §2.1: "A caller who is authenticated but whose role does not appear in
    the authorized-role list of the operation being attempted is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §2.1: "Contract activation, renewal and
    closure, drawdown reversal, storage re-finalization and quota-monitor
    authoring and reset belong exclusively to `FinanceController`."

    Design: Corner/validations/publisher_role_cannot_activate_contract
    """
    account = create_account(region="us-east-1")
    contract = create_contract(account["id"], 1000)
    response = api_client.activate_contract(
        contract["id"], {}, admin_headers(account["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_contract(contract["id"])["status"] == "DRAFT"


def test_the_allowance_ceiling_is_checked_before_any_allocation(api):
    """PRD §2.10: "The ninth layer is the contract credit ceiling, which refuses
    a drawdown that would breach the contract's allowance plus its rollover
    ceiling, with `ERR_CONTRACT_CREDIT_EXHAUSTED` (422)." PRD §3.4: "A drawdown
    that would push `drawn_credits` past `base_credits` plus
    `rolled_over_credits` plus the `rollover_cap_credits` of the active term is
    refused outright with `ERR_CONTRACT_CREDIT_EXHAUSTED` rather than being
    silently clipped".

    Design: Corner/validations/priority_nine_beats_budget_range_on_over_allowance
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_CL", "SMALL",
                                 auto_suspend_seconds=600)
    contract = create_active_contract(account["id"], 1000,
                                      rollover_cap_credits=200)
    response = api_client.create_drawdown(
        {"contract_id": contract["id"], "warehouse_id": warehouse["id"],
         "amount_credits": 1300, "source_kind": "SESSION",
         "idempotency_key": "cl-700",
         "expected_contract_version": get_contract(contract["id"])["version"]},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_CREDIT_EXHAUSTED)
    after = get_contract(contract["id"])
    assert after["drawn_credits"] == pytest.approx(0.0, abs=CREDIT_TOL)
    assert after["drawdown_count"] == 0
    assert list_drawdowns(contract["id"]) == []


def test_warehouse_name_uniqueness_is_scoped_to_the_owning_account(api):
    """PRD §2.10: "The twelfth layer is per-account uniqueness, refused with
    `ERR_DUPLICATE_RESOURCE` (409)." PRD §3.2: "A `DataEngineer` creates a
    `VirtualWarehouse` by supplying `account_id`, the `name` unique within that
    account".

    Design: Corner/validations/duplicate_warehouse_name_within_account_is_refused
    """
    first = create_account(tenant_name="Corp Dup A", region="us-east-1")
    second = create_account(tenant_name="Corp Dup B", region="us-east-1")
    create_warehouse(first["id"], "WH_DUP", "SMALL")

    response = api_client.create_warehouse(
        create_warehouse_payload(first["id"], "WH_DUP", "LARGE"), eng_headers()
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE)
    _, meta = validate_paginated(api_client.list_warehouses(
        eng_headers(), {"account_id": first["id"]}
    ))
    assert meta["total_count"] == 1

    # The same name inside another account is admitted.
    other = create_warehouse(second["id"], "WH_DUP", "LARGE")
    assert other["name"] == "WH_DUP"


def test_a_replication_target_in_the_account_own_region_is_refused(api):
    """PRD §3.8: "The target region must not equal the owning account's own
    region, or the configuration is refused with
    `ERR_REPLICATION_REGION_INVALID` — a same-region refresh is not replication
    at all and would be priced at a factor that describes nothing."

    Design: Corner/validations/same_region_replication_target_is_refused
    """
    account = create_account(region="eu-central-1")
    response = api_client.create_replication(
        {"account_id": account["id"], "name": "REPL_RG", "target_region":
         "eu-central-1", "target_cloud": "SAME_CLOUD", "replicated_tb": 1.0},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_REPLICATION_REGION_INVALID)
    _, meta = validate_paginated(api_client.list_replication(
        eng_headers(), {"account_id": account["id"]}
    ))
    assert meta["total_count"] == 0


def test_a_different_region_replication_target_is_admitted(api):
    """PRD §2.9: "A replication configuration whose `target_region` equals the
    owning account's own `region` is refused as well, with the dedicated code
    `ERR_REPLICATION_REGION_INVALID` (HTTP 422)".

    Design: Corner/validations/same_region_replication_target_is_refused
    """
    account = create_account(region="eu-central-1")
    created = api_client.create_replication(
        {"account_id": account["id"], "name": "REPL_RG", "target_region":
         "ap-southeast-1", "target_cloud": "SAME_CLOUD", "replicated_tb": 1.0},
        eng_headers(),
    )
    assert created.status_code in (200, 201), created.text
    created = validate_success(created, created.status_code)
    assert created["target_region"] == "ap-southeast-1"
    from test_helpers import list_replication
    assert len(list_replication(account["id"])) == 1


def test_paid_usage_against_a_free_listing_is_not_payable(api):
    """PRD §3.7: "a `FREE` listing is not payable at all — a payout or a paid
    usage row against one is refused with `ERR_FREE_LISTING_NOT_PAYABLE`,
    because a free listing has no credit volume to split." PRD §2.10: "The
    twentieth layer is listing pricing, which refuses payout work against a free
    listing with `ERR_FREE_LISTING_NOT_PAYABLE` (422)."

    Design: Corner/validations/free_listing_payout_is_not_payable
    """
    ctx = create_published_listing(title="LIST_NP", pricing_model="FREE",
                                   flat_price_usd=0.0)
    listing = ctx["listing"]
    response = api_client.create_paid_usage(
        {"listing_id": listing["id"], "buyer_account_id": ctx["consumer_id"],
         "credits_used": 10,
         "expected_listing_version": get_listing(listing["id"],
                                                 ctx["provider_id"])["version"]},
        admin_headers(ctx["provider_id"]),
    )
    validate_error(response, ApiErrorId.ERR_FREE_LISTING_NOT_PAYABLE)
    assert get_listing(listing["id"], ctx["provider_id"])[
        "listing_state"
    ] == "PUBLISHED", "the refusal is about the price model, not the state"
    _, meta = validate_paginated(api_client.list_paid_usage(
        fin_headers(), {"listing_id": listing["id"]}
    ))
    assert meta["total_count"] == 0


def test_a_drawdown_against_a_draft_contract_is_refused_before_allocation(api):
    """PRD §3.4: "In fact nothing is decremented while the contract is a draft,
    so a draft contract's `remaining_credits` sits at 0 and it draws nothing at
    all." PRD §3.4: "Only drawdown rows in `ACTIVE` status bound to a contract
    that is `ACTIVE`, `EXHAUSTED` or `CLOSED` participate in these rollups;
    reversed rows are excluded, and a drawdown bound to a draft contract is
    refused before the waterfall runs."

    Design: Corner/validations/drawdown_on_draft_contract_is_refused_before_allocation
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_DD", "SMALL")
    contract = create_contract(account["id"], 1000)
    assert contract["status"] == "DRAFT"
    assert contract["remaining_credits"] == pytest.approx(0.0, abs=CREDIT_TOL)

    response = api_client.create_drawdown(
        {"contract_id": contract["id"], "warehouse_id": warehouse["id"],
         "amount_credits": 10, "source_kind": "SESSION",
         "idempotency_key": "dd-10",
         "expected_contract_version": contract["version"]},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)