"""Corner queue B: entity-level claims (computed fields, defaults, not-found,
listing envelopes, references, enums, immutability, retrieval)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_account,
    create_active_contract,
    create_contract,
    create_drawdown_payload,
    create_warehouse,
    current_version,
    eng_headers,
    fin_headers,
    get_account,
    get_contract,
    list_ledger_entries,
    op_headers,
    open_session,
    close_session,
    resume_warehouse,
    set_clock,
    shift_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6


def test_warehouse_creation_returns_the_computed_credit_rate(api):
    """PRD §2.6: "each carries a size factor: 1, 2, 4, 8, 16, 32, 64, and 128
    respectively. The derived field `credits_per_hour` is the credit rate per
    hour for a single cluster at the current size, and it is recomputed from
    those size factors on every resize, on every resume, and whenever a
    warehouse is brought up from `SUSPENDED` through `STARTING` to `RUNNING`."
    PRD §3.2: "The warehouse materialises in `SUSPENDED` with `cluster_count` 0
    and `credits_per_hour` computed from the size factors for the requested
    size."

    Design: Corner/entities/warehouse_creation_returns_computed_credit_rate
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(
        account["id"], "WH_CW", "LARGE", auto_suspend_seconds=600,
        auto_resume=True, clusters_min=1, clusters_max=1, latency_slo_ms=1000,
    )
    assert warehouse["credits_per_hour"] == pytest.approx(8.0)
    assert warehouse["status"] == "SUSPENDED"
    assert warehouse["cluster_count"] == 0


def test_warehouse_creation_applies_the_declared_sizing_defaults(api):
    """PRD §3.2: "`auto_suspend_seconds` is the idle window before the warehouse
    suspends itself and also the billed floor applied to each session; it must
    be at least 60 and at most 3600 seconds, defaults to 600". PRD §3.2: "each
    of the three optional bounds falls back when absent: `clusters_min` to 1,
    `clusters_max` to 1, and `latency_slo_ms` to 1000." PRD §3.2: "`auto_resume`
    defaults to true and decides what happens when a query arrives at a
    suspended warehouse."

    Design: Corner/entities/warehouse_creation_defaults_auto_suspend_600
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_CD2", "XSMALL")

    assert warehouse["auto_suspend_seconds"] == 600
    assert warehouse["auto_resume"] is True
    assert warehouse["clusters_min"] == 1
    assert warehouse["clusters_max"] == 1
    assert warehouse["latency_slo_ms"] == 1000


def test_warehouse_creation_ignores_client_supplied_system_fields(api):
    """PRD §2.6: "A new warehouse is created in `SUSPENDED` with a
    `cluster_count` of 0." PRD §2.6: "The derived field `credits_per_hour` is
    the credit rate per hour for a single cluster at the current size, and it is
    recomputed from those size factors".

    Design: Corner/entities/warehouse_system_fields_ignore_client_input
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(
        account["id"], "WH_CS2", "SMALL", status="RUNNING", credits_per_hour=999,
        cluster_count=7,
    )
    assert warehouse["status"] == "SUSPENDED", "status is server-owned"
    assert warehouse["credits_per_hour"] == pytest.approx(2.0), (
        "credits_per_hour is derived from the size factor regardless of any "
        "client-supplied value"
    )
    assert warehouse["cluster_count"] == 0


def test_warehouse_creation_without_a_size_is_rejected(api):
    """PRD §3.2: "A `DataEngineer` creates a `VirtualWarehouse` by supplying
    `account_id`, the `name` unique within that account, and a `size`, with
    optional `auto_suspend_seconds`, `auto_resume`, `clusters_min`,
    `clusters_max` and `latency_slo_ms`." PRD §2.10: "an absent required field or
    an unknown enumeration member raises the generic `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/warehouse_creation_requires_size
    """
    account = create_account(region="us-east-1")
    response = api_client.create_warehouse(
        {"account_id": account["id"], "name": "WH_CM"}, eng_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api_client.list_warehouses(
        eng_headers(), {"account_id": account["id"]}
    ))
    assert meta["total_count"] == 0, "the rejected create left no row"


def test_an_unknown_warehouse_id_returns_resource_not_found(api):
    """PRD §2.9: "The first identifier in the path that does not resolve to an
    existing resource terminates the request with `ERR_RESOURCE_NOT_FOUND`
    (HTTP 404) — an unknown owning account is reported before an unknown child
    could ever be reached."

    Design: Corner/entities/warehouse_lookup_not_found
    """
    create_account(region="us-east-1")
    response = api_client.get_warehouse(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", eng_headers()
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_warehouse_listing_honours_the_pagination_envelope(api):
    """PRD §2.3: "`limit` caps the number of items in the returned page and
    defaults to 10; it must be at least 1 and at most 100. `offset` skips that
    many items from the head of the ordered result and defaults to 0." PRD
    §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` holding the total number of matching items regardless of the
    page, and `has_more` indicating whether further items remain beyond the
    returned page."

    Design: Corner/entities/warehouse_listing_pagination_envelope
    """
    account = create_account(region="us-east-1")
    for name, size in (("WH_P1", "XSMALL"), ("WH_P2", "SMALL"), ("WH_P3", "MEDIUM")):
        create_warehouse(account["id"], name, size)

    page, meta = validate_paginated(api_client.list_warehouses(
        op_headers(), {"account_id": account["id"], "limit": 2, "offset": 0}
    ))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    page2, meta2 = validate_paginated(api_client.list_warehouses(
        op_headers(), {"account_id": account["id"], "limit": 2, "offset": 2}
    ))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_a_drawdown_cannot_bind_a_contract_and_a_warehouse_from_different_accounts(api):
    """PRD §2.9: "A `CreditDrawdown` names its contract through `contract_id`,
    which must exist, and names its origin through `warehouse_id`, which must be
    a `VirtualWarehouse` owned by the same account that owns the named
    contract." PRD §2.9: "a drawdown whose `warehouse_id` points at a warehouse
    owned by a different account than its `contract_id` is refused".

    Design: Corner/entities/drawdown_rejects_warehouse_from_another_account
    """
    first = create_account(tenant_name="Corp A", region="us-east-1")
    second = create_account(tenant_name="Corp B", region="us-east-1")
    foreign_warehouse = create_warehouse(second["id"], "WH_CB", "SMALL")
    contract = create_active_contract(first["id"], 1000)

    response = api_client.create_drawdown(
        create_drawdown_payload(contract["id"], foreign_warehouse["id"], 10, "xacct-1",
                                get_contract(contract["id"])["version"]),
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_REFERENCE_INVALID)
    assert get_contract(contract["id"])["drawn_credits"] == pytest.approx(
        0.0, abs=CREDIT_TOL
    )


def test_account_registration_rejects_an_unknown_cloud_provider(api):
    """PRD §3.1: "`cloud_provider`, which is `SAME_CLOUD` or `CROSS_CLOUD` and
    drives the replication cloud factor later". PRD §2.10: "an absent required
    field or an unknown enumeration member raises the generic
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/account_creation_rejects_unknown_cloud_provider
    """
    response = api_client.create_account(
        {"org_name": "Corp Enum", "account_locator": "ce2009",
         "cloud_provider": "HYBRID_CLOUD", "region": "us-east-1",
         "monitor_scope": "ACCOUNT_ONLY"},
        op_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api_client.list_accounts(op_headers()))
    assert meta["total_count"] == 0


def test_a_ledger_row_is_append_only_with_the_standard_audit_trail_omitted(api):
    """PRD §2.5: "The ledger is the exception. `AccountLedgerEntry` carries only
    `id` and `created_at`; it has neither `updated_at` nor `version`, because a
    ledger row is append-only and immutable once posted." PRD §3.3: "posts a
    single ledger row on the owning account with bucket `CONSUMPTION`,
    `source_entity` \"WarehouseSession\", `source_entity_id` equal to the
    session's own id, and `amount_credits` equal to `billed_credits`".

    Design: Corner/entities/ledger_entry_is_append_only_with_no_update_route
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_AP", "SMALL",
                                 auto_suspend_seconds=600)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 60))
    closed = close_session(session["id"], warehouse["id"])

    entries = list_ledger_entries(account["id"])
    assert len(entries) == 1
    row = entries[0]
    assert row["bucket"] == "CONSUMPTION"
    assert row["source_entity"] == "WarehouseSession"
    assert row["source_entity_id"] == session["id"]
    assert row["amount_credits"] == pytest.approx(closed["billed_credits"], abs=CREDIT_TOL)
    assert "version" not in row
    assert "updated_at" not in row


def test_a_stored_account_reads_back_with_its_declared_fields(api):
    """PRD §3.1: "Registration creates the account in `OPEN` posture with both
    reconciled figures at 0. Accounts are read back individually and listed with
    filters on `region` and `cloud_provider`."

    Design: Corner/entities/account_retrieval_round_trips_stored_fields
    """
    account = create_account(
        tenant_name="Corp Round Trip", region="eu-central-1",
        monitor_scope="INCLUDE_CONSUMERS", cloud_provider="CROSS_CLOUD",
    )
    read_back = get_account(account["id"])

    assert read_back["org_name"] == "Corp Round Trip"
    assert read_back["account_locator"] == account["account_locator"]
    assert read_back["cloud_provider"] == "CROSS_CLOUD"
    assert read_back["region"] == "eu-central-1"
    assert read_back["monitor_scope"] == "INCLUDE_CONSUMERS"
    assert read_back["account_state"] == "OPEN"
    assert read_back["posted_consumption_credits_reconciled"] == pytest.approx(
        0.0, abs=CREDIT_TOL
    )