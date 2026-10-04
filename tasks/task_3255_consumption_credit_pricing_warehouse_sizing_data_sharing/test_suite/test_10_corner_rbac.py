"""Corner queue B: role-based access control and segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    create_account,
    create_active_contract,
    create_listing,
    create_share,
    create_warehouse,
    eng_headers,
    fin_headers,
    get_account,
    get_contract,
    get_listing,
    get_paid_usage,
    get_share,
    get_warehouse,
    op_headers,
    dispute_paid_usage,
    post_paid_usage,
    publish_listing,
    publish_share,
    resolve_paid_usage,
    resume_warehouse,
    settle_paid_usage,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-09-01T00:00:00Z"
DOLLAR_TOL = 0.005


def test_the_engineering_role_cannot_publish_a_share(api):
    """PRD §2.1: "Role exclusivity is meaningful beyond the per-operation
    authorization lists." PRD §2.1: "Publishing, suspending and revoking shares,
    publishing and withdrawing listings, and amending a share's exposed objects
    or consumer list belong exclusively to `ShareAdmin`." PRD §2.1: "a data
    engineer may never publish a share".

    Design: Corner/rbac/data_engineer_cannot_publish_a_share
    """
    provider = create_account(tenant_name="Rbac Publish P", region="us-east-1")
    consumer = create_account(tenant_name="Rbac Publish C", region="us-east-1")
    share = create_share(provider["id"], "SHARE_RB", [consumer["id"]],
                         objects_exposed=2)

    response = api_client.publish_share(share["id"], eng_headers())
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_share(share["id"], provider["id"])["status"] == "DRAFT"


def test_the_share_administrator_role_can_publish_the_same_share(api):
    """PRD §2.1: "Four roles exist, and their names must be spelled exactly as
    written here: `PlatformOperator`, `FinanceController`, `ShareAdmin`, and
    `DataEngineer`."

    Design: Corner/rbac/data_engineer_cannot_publish_a_share
    """
    provider = create_account(tenant_name="Rbac Publish P", region="us-east-1")
    consumer = create_account(tenant_name="Rbac Publish C", region="us-east-1")
    share = create_share(provider["id"], "SHARE_RB", [consumer["id"]],
                         objects_exposed=2)
    published = publish_share(share["id"], provider["id"])
    assert published["status"] == "PUBLISHED"


def test_the_finance_role_cannot_create_a_warehouse(api):
    """PRD §2.1: "Sizing, resuming, suspending, scaling and metering warehouses,
    capturing and revising storage snapshots, and configuring and refreshing
    replication belong exclusively to `DataEngineer` — a data engineer may never
    publish a share and may never activate a contract." PRD §2.1: "A caller who
    is authenticated but whose role does not appear in the authorized-role list
    of the operation being attempted is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
    403)."

    Design: Corner/rbac/finance_controller_cannot_create_a_warehouse
    """
    account = create_account(tenant_name="Rbac Create", region="us-east-1")
    response = api_client.create_warehouse(
        {"account_id": account["id"], "name": "WH_RBC", "size": "SMALL"},
        fin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    from test_helpers import validate_paginated
    _, meta = validate_paginated(api_client.list_warehouses(
        eng_headers(), {"account_id": account["id"]}
    ))
    assert meta["total_count"] == 0


def test_the_denied_role_is_still_allowed_its_own_operations(api):
    """PRD §2.1: "Contract activation, renewal and closure, drawdown reversal,
    storage re-finalization and quota-monitor authoring and reset belong
    exclusively to `FinanceController`."

    Design: Corner/rbac/finance_controller_cannot_create_a_warehouse
    """
    from test_helpers import create_monitor
    account = create_account(tenant_name="Rbac Create", region="us-east-1")
    monitor = create_monitor(account["id"], "MON_RBC", 100, interval="MONTHLY",
                             action="NOTIFY")
    assert monitor["account_id"] == account["id"]


def test_the_resume_operation_is_shared_by_two_roles(api):
    """PRD §2.1: "A resume is attempted by a `DataEngineer` or a
    `PlatformOperator` and requires the warehouse to be `SUSPENDED`". PRD §2.1:
    "The one operation exempt from both of these checks is the test-driving clock
    capability".

    Design: Corner/rbac/shared_resume_operation_admits_both_roles
    """
    account = create_account(tenant_name="Rbac Shared", region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_RSH", "SMALL")

    by_operator = resume_warehouse(warehouse["id"], actor=op_headers())
    assert by_operator["status"] == "RUNNING"

    from test_helpers import suspend_warehouse
    suspend_warehouse(warehouse["id"])
    by_engineer = resume_warehouse(warehouse["id"], actor=eng_headers())
    assert by_engineer["status"] == "RUNNING"


def test_the_finance_role_is_outside_the_shared_resume_operation(api):
    """PRD §2.1: "A caller who is authenticated but whose role does not appear in
    the authorized-role list of the operation being attempted is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/shared_resume_operation_admits_both_roles
    """
    account = create_account(tenant_name="Rbac Shared", region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_RSH", "SMALL")
    response = api_client.resume_warehouse(warehouse["id"], {}, fin_headers())
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_warehouse(warehouse["id"])["status"] == "SUSPENDED"


def test_the_share_administrator_identity_is_bound_to_the_provider_account(api):
    """PRD §2.1: "When `X-User-Role` is `ShareAdmin`, `X-User-ID` is the `id` of
    the acting `Account`; a share admin is an entity-backed operator, and
    ownership checks on any resource that references an `Account` — a share's
    `provider_account_id`, the account a warehouse or contract belongs to, the
    account a storage snapshot or quota monitor watches — compare that resource's
    foreign-key field to `X-User-ID`."

    Design: Corner/rbac/share_admin_identity_is_account_backed
    """
    account_a = create_account(tenant_name="Rbac Id A", region="us-east-1")
    account_b = create_account(tenant_name="Rbac Id B", region="us-east-1")
    share_a = create_share(account_a["id"], "SHARE_RIA", [account_b["id"]],
                           objects_exposed=1)
    share_b = create_share(account_b["id"], "SHARE_RIB", [account_a["id"]],
                           objects_exposed=1)

    # PRD §2.1: a share admin is entity-backed, and ownership checks compare the
    # share's provider_account_id to X-User-ID.
    crossed = api_client.publish_share(share_b["id"], admin_headers(account_a["id"]))
    validate_error(crossed, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_share(share_b["id"], account_b["id"])["status"] == "DRAFT"

    own = publish_share(share_a["id"], account_a["id"])
    assert own["status"] == "PUBLISHED"


def test_the_activating_operator_cannot_close_the_contract(api):
    """PRD §3.4: "The close carries a segregation-of-duties constraint: a
    contract whose `activated_by_user_id` equals the acting `X-User-ID` cannot be
    closed by that same operator, and the attempt is refused with
    `ERR_ROLE_CONFLICT`."

    Design: Corner/rbac/segregated_contract_close_by_activating_operator
    """
    account = create_account(tenant_name="Rbac Sod", region="us-east-1")
    contract = create_active_contract(account["id"], 1000,
                                      activate_as=fin_headers("fin-sod-9"))
    assert get_contract(contract["id"])["activated_by_user_id"] == "fin-sod-9"

    response = api_client.close_contract(contract["id"], {}, fin_headers("fin-sod-9"))
    validate_error(response, ApiErrorId.ERR_ROLE_CONFLICT)


def test_a_second_operator_can_close_what_the_first_operator_activated(api):
    """PRD §2.10: "The eighth layer is segregation of duties on the contract
    path: closing a contract that the acting operator activated is refused with
    `ERR_ROLE_CONFLICT` (422)."

    Design: Corner/rbac/segregated_contract_close_by_activating_operator
    """
    account = create_account(tenant_name="Rbac Sod", region="us-east-1")
    contract = create_active_contract(account["id"], 1000,
                                      activate_as=fin_headers("fin-sod-9"))
    closed = api_client.close_contract(contract["id"], {}, fin_headers("fin-sod-10"))
    data = validate_success(closed)
    assert data["status"] == "CLOSED"


def _disputed_row(dispute_as: str = "ops-dis-1"):
    """A published usage-based listing with a settled row disputed by an
    operator."""
    provider = create_account(tenant_name="Rbac Payout P", region="us-east-1")
    consumer = create_account(tenant_name="Rbac Payout C", region="us-east-1")
    share = create_share(provider["id"], "SHARE_RP2", [consumer["id"]],
                         objects_exposed=2)
    publish_share(share["id"], provider["id"])
    listing = create_listing(share["id"], provider["id"], "LIST_RP2",
                             pricing_model="USAGE_BASED", flat_price_usd=0.50)
    publish_listing(listing["id"], provider["id"])
    usage = post_paid_usage(listing["id"], provider["id"], consumer["id"], 100)
    settle_paid_usage(usage["id"])
    disputed = dispute_paid_usage(usage["id"], listing["id"], provider["id"],
                                  actor=op_headers(dispute_as))
    return provider, consumer, listing, disputed


def test_the_disputing_operator_cannot_resolve_their_own_dispute(api):
    """PRD §3.7: "The payout path carries its own segregation-of-duties
    constraint, distinct from the contract path: a row whose
    `disputed_by_user_id` equals the acting `X-User-ID` cannot be resolved by
    that same operator, and the attempt is refused with
    `ERR_DISPUTE_SELF_RESOLVE`."

    Design: Corner/rbac/segregated_dispute_resolution_by_raising_operator
    """
    provider, consumer, listing, disputed = _disputed_row("ops-dis-1")
    assert get_paid_usage(disputed["id"])["disputed_by_user_id"] == "ops-dis-1"

    response = api_client.resolve_paid_usage(disputed["id"], op_headers("ops-dis-1"))
    validate_error(response, ApiErrorId.ERR_DISPUTE_SELF_RESOLVE)
    assert get_paid_usage(disputed["id"])["usage_state"] == "DISPUTED"


def test_a_third_operator_can_resolve_the_dispute_and_restore_the_payout(api):
    """PRD §3.7: "Resolution is admitted only from `DISPUTED` and is also a
    `PlatformOperator` action; it moves the row back to `SETTLED`, adds the
    contribution back to all three listing figures, and posts a `PAYOUT` ledger
    row on the provider account for the restored provider share."

    Design: Corner/rbac/segregated_dispute_resolution_by_raising_operator
    """
    provider, consumer, listing, disputed = _disputed_row("ops-dis-1")
    resolved = resolve_paid_usage(disputed["id"], op_headers("ops-dis-2"))
    assert resolved["usage_state"] == "SETTLED"
    # 100 credits at 0.50 = 50.00 gross; 15 percent = 7.50 fee, 42.50 provider.
    after = get_listing(listing["id"], provider["id"])
    assert after["provider_payout_usd"] == pytest.approx(42.5, abs=DOLLAR_TOL)
    assert after["platform_fee_usd"] == pytest.approx(7.5, abs=DOLLAR_TOL)