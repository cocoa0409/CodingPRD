"""Composite setup helpers.

Every helper builds its preconditions from scratch through API calls (the
harness restarts the server before each test, so nothing carries over). Setup
calls use ``get_success_data`` so a failed precondition surfaces as a clear
"Setup step failed" message rather than a confusing assertion error.

Identity threading: ``ShareAdmin`` is entity-backed by ``Account``, so every
share/listing/usage write in these helpers is issued with
``make_share_admin_headers(provider_account_id)``.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_START, QUERIES_PER_CLUSTER, SECONDS_PER_HOUR
from .factories import (
    close_session_payload,
    create_account_payload,
    create_contract_payload,
    create_drawdown_payload,
    create_listing_payload,
    create_monitor_payload,
    create_paid_usage_payload,
    create_replication_payload,
    create_session_payload,
    create_share_payload,
    create_storage_record_payload,
    create_usage_event_payload,
    create_warehouse_payload,
    renew_contract_payload,
    revise_storage_record_payload,
)
from .test_users import (
    make_data_engineer_headers,
    make_finance_controller_headers,
    make_platform_operator_headers,
    make_share_admin_headers,
)

_LOCATOR_SEQ = [0]


def next_locator() -> str:
    """A fresh, globally-unique account locator (two lowercase letters + four
    digits)."""
    _LOCATOR_SEQ[0] += 1
    n = _LOCATOR_SEQ[0]
    letters = chr(ord("a") + (n // 26) % 26) + chr(ord("a") + n % 26)
    return f"{letters}{n % 10000:04d}"


def add_days(iso: str, days: int) -> str:
    from datetime import datetime, timedelta
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    return (dt + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Role headers
# ---------------------------------------------------------------------------

def op_headers(user_id: str = "ops-platform-1") -> dict:
    """PlatformOperator headers (opaque operator identity)."""
    return make_platform_operator_headers(user_id)


def fin_headers(user_id: str = "fin-controller-1") -> dict:
    """FinanceController headers (opaque operator identity)."""
    return make_finance_controller_headers(user_id)


def eng_headers(user_id: str = "eng-data-1") -> dict:
    """DataEngineer headers (opaque operator identity)."""
    return make_data_engineer_headers(user_id)


def admin_headers(provider_account_id: str) -> dict:
    """ShareAdmin headers bound to the acting provider Account.id."""
    return make_share_admin_headers(provider_account_id)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, op_headers())
    )


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def create_account(locator: str = None, region: str = "us-east-1",
                   tenant_name: str = "Test Organisation",
                   monitor_scope: str = "ACCOUNT_ONLY", **overrides) -> dict:
    payload = create_account_payload(
        account_locator=locator or next_locator(),
        org_name=tenant_name,
        region=region,
        monitor_scope=monitor_scope,
        **overrides,
    )
    return get_success_data(api_client.create_account(payload, op_headers()), 201)


def get_account(account_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_account(account_id, headers or op_headers())
    )


def get_billing_summary(account_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_account_billing_summary(account_id, headers or fin_headers())
    )


def get_account_billing_summary(account_id: str, headers: dict = None) -> dict:
    """Alias of ``get_billing_summary``."""
    return get_billing_summary(account_id, headers)


def list_ledger_entries(account_id: str, params: dict = None, headers: dict = None) -> list:
    entries, _ = validate_paginated(
        api_client.list_account_ledger_entries(
            account_id, headers or fin_headers(), params
        )
    )
    return entries


def ledger_entries_for_source(account_id: str, source_entity_id: str) -> list:
    return [e for e in list_ledger_entries(account_id)
            if e["source_entity_id"] == source_entity_id]


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------

def create_warehouse(account_id: str, name: str, size: str = "XSMALL",
                     actor: dict = None, **overrides) -> dict:
    payload = create_warehouse_payload(account_id, name, size, **overrides)
    return get_success_data(
        api_client.create_warehouse(payload, actor or eng_headers()), 201
    )


def get_warehouse(warehouse_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_warehouse(warehouse_id, headers or eng_headers())
    )


def current_version(warehouse_id: str) -> int:
    return get_warehouse(warehouse_id)["version"]


def resume_warehouse(warehouse_id: str, actor: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.resume_warehouse(warehouse_id, dict(overrides), actor or eng_headers())
    )


def suspend_warehouse(warehouse_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.suspend_warehouse(warehouse_id, actor or eng_headers())
    )


def patch_warehouse(warehouse_id: str, payload: dict, actor: dict = None) -> dict:
    return get_success_data(
        api_client.patch_warehouse(warehouse_id, payload, actor or eng_headers())
    )


def scale_warehouse(warehouse_id: str, clusters: int, queued_queries: int,
                    expected_warehouse_version=None, actor: dict = None,
                    **overrides) -> dict:
    payload = {
        "clusters": clusters,
        "queued_queries": queued_queries,
        "expected_warehouse_version": (
            current_version(warehouse_id) if expected_warehouse_version is None
            else expected_warehouse_version
        ),
    }
    payload.update(overrides)
    return get_success_data(
        api_client.scale_warehouse(warehouse_id, payload, actor or eng_headers())
    )


def create_running_warehouse(account_id: str, name: str, size: str = "SMALL",
                             **overrides) -> dict:
    """Create a warehouse and drive it to RUNNING (cluster_count = clusters_min)."""
    wh = create_warehouse(account_id, name, size, **overrides)
    return resume_warehouse(wh["id"])


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

def create_contract(account_id: str, base_credits: float = 1000,
                    actor: dict = None, **overrides) -> dict:
    payload = create_contract_payload(account_id, base_credits, **overrides)
    return get_success_data(
        api_client.create_contract(payload, actor or fin_headers()), 201
    )


def get_contract(contract_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_contract(contract_id, headers or fin_headers())
    )


def list_warehouses(account_id: str, headers: dict = None) -> list:
    data, _ = validate_paginated(
        api_client.list_warehouses(headers or eng_headers(), {"account_id": account_id})
    )
    return data


def get_paid_usage(paid_usage_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_paid_usage(paid_usage_id, headers or fin_headers())
    )


def activate_contract(contract_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.activate_contract(contract_id, {}, actor or fin_headers())
    )


def create_active_contract(account_id: str, base_credits: float = 1000,
                           activate_as: dict = None, **overrides) -> dict:
    contract = create_contract(account_id, base_credits, **overrides)
    return activate_contract(contract["id"], activate_as)


def renew_contract(contract_id: str, new_term_start: str, new_term_end: str,
                   base_credits: float = 1000, actor: dict = None,
                   **overrides) -> dict:
    payload = renew_contract_payload(
        new_term_start, new_term_end, base_credits, **overrides
    )
    return get_success_data(
        api_client.renew_contract(contract_id, payload, actor or fin_headers())
    )


def close_contract(contract_id: str, actor: dict, payload: dict = None) -> dict:
    return get_success_data(
        api_client.close_contract(contract_id, payload or {}, actor)
    )


def list_drawdowns(contract_id: str, headers: dict = None) -> list:
    """PRD §2.3: the credit-drawdown collection uses cursor pagination rather
    than offset paging — its `meta` carries `limit`, `total_count`, `has_more`
    and a `next_cursor`, and the `offset` parameter is not part of its contract.
    Every row requested with a generous limit lands on one page."""
    response = api_client.list_drawdowns(
        headers or fin_headers(), {"contract_id": contract_id, "limit": 100}
    )
    assert response.status_code == 200, (
        f"Expected 200 for the cursor-paginated drawdown list, got "
        f"{response.status_code}: {response.text}"
    )
    body = response.json()
    assert "data" in body, "Missing 'data'"
    meta = body["meta"]
    assert isinstance(meta.get("limit"), int), "meta.limit must be int"
    assert meta["limit"] > 0, "meta.limit must be positive"
    assert isinstance(meta.get("total_count"), int), "meta.total_count must be int"
    assert isinstance(meta.get("has_more"), bool), "meta.has_more must be bool"
    return body["data"]


def list_contracts(account_id: str, headers: dict = None) -> list:
    data, _ = validate_paginated(
        api_client.list_contracts(headers or fin_headers(), {"account_id": account_id})
    )
    return data


# ---------------------------------------------------------------------------
# Drawdowns
# ---------------------------------------------------------------------------

def post_drawdown(contract_id: str, warehouse_id: str, amount_credits: float,
                  idempotency_key: str, expected_contract_version=None,
                  actor: dict = None, source_kind: str = "SESSION", **overrides) -> dict:
    payload = create_drawdown_payload(
        contract_id, warehouse_id, amount_credits, idempotency_key,
        expected_contract_version if expected_contract_version is not None
        else get_contract(contract_id)["version"],
        source_kind=source_kind, **overrides,
    )
    return get_success_data(
        api_client.create_drawdown(payload, actor or eng_headers()), 201
    )


def reverse_drawdown(drawdown_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.reverse_drawdown(drawdown_id, {}, actor or fin_headers())
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def open_session(warehouse_id: str, actor: dict = None, **overrides) -> dict:
    payload = create_session_payload(warehouse_id, **overrides)
    return get_success_data(
        api_client.create_session(payload, actor or eng_headers()), 201
    )


def get_session(session_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_session(session_id, headers or eng_headers())
    )


def close_session(session_id: str, warehouse_id: str,
                  expected_warehouse_version=None, actor: dict = None) -> dict:
    payload = close_session_payload(
        expected_warehouse_version if expected_warehouse_version is not None
        else current_version(warehouse_id)
    )
    return get_success_data(
        api_client.close_session(session_id, payload, actor or eng_headers())
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def create_storage_record(account_id: str, usage_date: str, actor: dict = None,
                          **overrides) -> dict:
    payload = create_storage_record_payload(account_id, usage_date, **overrides)
    return get_success_data(
        api_client.create_storage_record(payload, actor or eng_headers()), 201
    )


def get_storage_record(record_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_storage_record(record_id, headers or eng_headers())
    )


def get_storage_billing_summary(record_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_storage_billing_summary(record_id, headers or fin_headers())
    )


def revise_storage_record(record_id: str, actor: dict = None, **overrides) -> dict:
    payload = revise_storage_record_payload(
        get_storage_record(record_id)["version"], **overrides
    )
    return get_success_data(
        api_client.revise_storage_record(record_id, payload, actor or eng_headers())
    )


def finalize_storage_record(record_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.finalize_storage_record(record_id, {}, actor or fin_headers())
    )


def list_storage_records(account_id: str, headers: dict = None) -> list:
    data, _ = validate_paginated(
        api_client.list_storage_records(
            headers or eng_headers(), {"account_id": account_id}
        )
    )
    return data


# ---------------------------------------------------------------------------
# Shares
# ---------------------------------------------------------------------------

def create_share(provider_account_id: str, name: str, consumer_account_ids: list,
                 objects_exposed: int = 2, actor: dict = None, **overrides) -> dict:
    payload = create_share_payload(
        provider_account_id, name, consumer_account_ids, objects_exposed, **overrides
    )
    return get_success_data(
        api_client.create_share(payload, actor or admin_headers(provider_account_id)),
        201,
    )


def get_share(share_id: str, provider_account_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_share(
            share_id, headers or admin_headers(provider_account_id)
        )
    )


def publish_share(share_id: str, provider_account_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.publish_share(
            share_id, actor or admin_headers(provider_account_id)
        )
    )


def suspend_share(share_id: str, provider_account_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.suspend_share(
            share_id, actor or admin_headers(provider_account_id)
        )
    )


def revoke_share(share_id: str, provider_account_id: str,
                 expected_account_version=None, actor: dict = None) -> dict:
    payload = {
        "expected_account_version": (
            expected_account_version if expected_account_version is not None
            else get_account(provider_account_id)["version"]
        )
    }
    return get_success_data(
        api_client.revoke_share(
            share_id, payload, actor or admin_headers(provider_account_id)
        )
    )


def create_published_share(provider_account_id: str, consumer_account_ids: list,
                           name: str = "SHARE", objects_exposed: int = 2,
                           **overrides) -> dict:
    share = create_share(provider_account_id, name, consumer_account_ids,
                         objects_exposed, **overrides)
    return publish_share(share["id"], provider_account_id)


def patch_share(share_id: str, provider_account_id: str, payload: dict,
                actor: dict = None) -> dict:
    return get_success_data(
        api_client.patch_share(
            share_id, payload, actor or admin_headers(provider_account_id)
        )
    )


# ---------------------------------------------------------------------------
# Usage events
# ---------------------------------------------------------------------------

def post_usage_event(share_id: str, provider_account_id: str,
                     consumer_account_id: str, credits_consumed: float = 1.0,
                     row_count: int = 1, actor: dict = None, **overrides) -> dict:
    payload = create_usage_event_payload(
        consumer_account_id, credits_consumed, row_count, **overrides
    )
    return get_success_data(
        api_client.create_usage_event(
            share_id, payload, actor or eng_headers()
        ),
        201,
    )


def list_usage_events(params: dict = None, headers: dict = None) -> list:
    data, _ = validate_paginated(
        api_client.list_usage_events(headers or fin_headers(), params)
    )
    return data


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

def create_listing(share_id: str, provider_account_id: str, title: str,
                   pricing_model: str = "USAGE_BASED", flat_price_usd: float = 0.50,
                   actor: dict = None, **overrides) -> dict:
    payload = create_listing_payload(
        share_id, title, pricing_model, flat_price_usd, **overrides
    )
    return get_success_data(
        api_client.create_listing(payload, actor or admin_headers(provider_account_id)),
        201,
    )


def get_listing(listing_id: str, provider_account_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_listing(
            listing_id, headers or admin_headers(provider_account_id)
        )
    )


def publish_listing(listing_id: str, provider_account_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.publish_listing(
            listing_id, actor or admin_headers(provider_account_id)
        )
    )


def withdraw_listing(listing_id: str, provider_account_id: str,
                     actor: dict = None) -> dict:
    return get_success_data(
        api_client.withdraw_listing(
            listing_id, actor or admin_headers(provider_account_id)
        )
    )


def get_provider_payout(listing_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_provider_payout(listing_id, headers or fin_headers())
    )


def create_published_listing(title: str = "LIST", pricing_model: str = "USAGE_BASED",
                             flat_price_usd: float = 0.50,
                             listing_title: str = None, credits_used: float = None,
                             **overrides) -> dict:
    """Provider + consumer + published share + published listing. When
    ``credits_used`` is given a paid usage row is recorded and settled.

    Returns a context dict carrying ``provider``/``provider_id``,
    ``consumer``/``consumer_id``, ``share``, ``listing`` and (when requested)
    ``paid_usage``.
    """
    ctx = setup_provider_consumer()
    ctx["share"] = create_published_share(ctx["provider_id"], [ctx["consumer_id"]])
    listing = create_listing(
        ctx["share"]["id"], ctx["provider_id"], listing_title or title,
        pricing_model=pricing_model, flat_price_usd=flat_price_usd, **overrides,
    )
    ctx["listing"] = publish_listing(listing["id"], ctx["provider_id"])
    if credits_used is not None:
        usage = post_paid_usage(
            ctx["listing"]["id"], ctx["provider_id"], ctx["consumer_id"], credits_used
        )
        ctx["paid_usage"] = settle_paid_usage(usage["id"])
    return ctx


# ---------------------------------------------------------------------------
# Paid share usage
# ---------------------------------------------------------------------------

def post_paid_usage(listing_id: str, provider_account_id: str, buyer_account_id: str,
                    credits_used: float, expected_listing_version=None,
                    actor: dict = None, **overrides) -> dict:
    payload = create_paid_usage_payload(
        listing_id, buyer_account_id, credits_used,
        expected_listing_version if expected_listing_version is not None
        else get_listing(listing_id, provider_account_id)["version"],
        **overrides,
    )
    return get_success_data(
        api_client.create_paid_usage(
            payload, actor or admin_headers(provider_account_id)
        ),
        201,
    )


def settle_paid_usage(paid_usage_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.settle_paid_usage(paid_usage_id, actor or fin_headers())
    )


def dispute_paid_usage(paid_usage_id: str, listing_id: str, provider_account_id: str,
                       expected_listing_version=None, actor: dict = None) -> dict:
    payload = {
        "expected_listing_version": (
            expected_listing_version if expected_listing_version is not None
            else get_listing(listing_id, provider_account_id)["version"]
        )
    }
    return get_success_data(
        api_client.dispute_paid_usage(
            paid_usage_id, payload, actor or op_headers()
        )
    )


def resolve_paid_usage(paid_usage_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.resolve_paid_usage(paid_usage_id, actor or op_headers())
    )


def list_paid_usage(params: dict = None, headers: dict = None) -> list:
    data, _ = validate_paginated(
        api_client.list_paid_usage(headers or fin_headers(), params)
    )
    return data


# ---------------------------------------------------------------------------
# Resource monitors
# ---------------------------------------------------------------------------

def create_monitor(account_id: str, name: str, credit_quota: float,
                   interval: str = "MONTHLY", action: str = "NOTIFY",
                   actor: dict = None, **overrides) -> dict:
    payload = create_monitor_payload(
        account_id, name, credit_quota, interval, action, **overrides
    )
    return get_success_data(
        api_client.create_monitor(payload, actor or fin_headers()), 201
    )


def get_monitor(monitor_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_monitor(monitor_id, headers or fin_headers())
    )


def reset_monitor(monitor_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.reset_monitor(monitor_id, actor or fin_headers())
    )


# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------

def create_replication(account_id: str, name: str, target_region: str,
                       replicated_tb: float, target_cloud: str = "SAME_CLOUD",
                       actor: dict = None, **overrides) -> dict:
    payload = create_replication_payload(
        account_id, name, target_region, replicated_tb, target_cloud, **overrides
    )
    return get_success_data(
        api_client.create_replication(payload, actor or eng_headers()), 201
    )


def get_replication(replication_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_replication(replication_id, headers or eng_headers())
    )


def refresh_replication(replication_id: str, actor: dict = None) -> dict:
    return get_success_data(
        api_client.refresh_replication(replication_id, actor or eng_headers())
    )


def list_replication(account_id: str, headers: dict = None) -> list:
    data, _ = validate_paginated(
        api_client.list_replication(
            headers or eng_headers(), {"account_id": account_id}
        )
    )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — state progression
# ---------------------------------------------------------------------------

def shift_clock(iso: str, seconds: int) -> str:
    from datetime import datetime, timedelta
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    return (dt + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_session_of_length(account_id: str, warehouse_name: str, size: str,
                          start_at: str, seconds: int,
                          clusters: int = None, **warehouse_overrides) -> dict:
    """Drive a warehouse to RUNNING, optionally scale it, open a session at
    ``start_at``, advance the clock ``seconds`` and close it.

    Returns {"warehouse", "session", "started_at", "ended_at"}.
    """
    warehouse = create_running_warehouse(account_id, warehouse_name, size,
                                         **warehouse_overrides)
    if clusters is not None and clusters != warehouse["cluster_count"]:
        queued = clusters * QUERIES_PER_CLUSTER
        warehouse = scale_warehouse(warehouse["id"], clusters, queued)
    set_clock(start_at)
    session = open_session(warehouse["id"])
    end_at = shift_clock(start_at, seconds)
    set_clock(end_at)
    closed = close_session(session["id"], warehouse["id"])
    return {
        "warehouse": warehouse,
        "session": closed,
        "started_at": start_at,
        "ended_at": end_at,
    }


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def setup_account_with_warehouse_and_contract(locator: str = None,
                                              size: str = "SMALL",
                                              base_credits: float = 1000,
                                              warehouse_name: str = "WH",
                                              monitor_scope: str = "ACCOUNT_ONLY",
                                              **warehouse_overrides) -> dict:
    """Account + one warehouse + one ACTIVE contract. The most common base."""
    account = create_account(locator=locator, monitor_scope=monitor_scope)
    warehouse = create_warehouse(account["id"], warehouse_name, size,
                                 **warehouse_overrides)
    contract = create_active_contract(account["id"], base_credits)
    return {
        "account": account,
        "account_id": account["id"],
        "warehouse": warehouse,
        "warehouse_id": warehouse["id"],
        "contract": contract,
        "contract_id": contract["id"],
    }


def setup_provider_consumer(provider_name: str = "P", consumer_name: str = "C",
                            region: str = "us-east-1") -> dict:
    provider = create_account(tenant_name=provider_name, region=region)
    consumer = create_account(tenant_name=consumer_name, region=region)
    return {
        "provider": provider,
        "provider_id": provider["id"],
        "consumer": consumer,
        "consumer_id": consumer["id"],
    }


def setup_published_share(share_name: str = "SHARE", objects_exposed: int = 2,
                          provider: dict = None, consumer: dict = None,
                          monitor_scope: str = "ACCOUNT_ONLY") -> dict:
    ctx = {
        "provider": provider or create_account(tenant_name="Prov"),
        "consumer": consumer or create_account(tenant_name="Cons"),
    }
    ctx["provider_id"] = ctx["provider"]["id"]
    ctx["consumer_id"] = ctx["consumer"]["id"]
    ctx["share"] = create_published_share(
        ctx["provider_id"], [ctx["consumer_id"]], name=share_name,
        objects_exposed=objects_exposed,
    )
    return ctx


def setup_published_listing(pricing_model: str = "USAGE_BASED",
                            flat_price_usd: float = 0.50,
                            listing_title: str = "LIST",
                            credits_used: float = None) -> dict:
    """Provider + consumer + published share + published listing. When
    ``credits_used`` is given a paid usage row is recorded and settled."""
    ctx = setup_published_share()
    ctx["listing"] = create_published_listing(
        ctx["share"]["id"], ctx["provider_id"], listing_title,
        pricing_model=pricing_model, flat_price_usd=flat_price_usd,
    )
    if credits_used is not None:
        ctx["paid_usage"] = post_paid_usage(
            ctx["listing"]["id"], ctx["provider_id"], ctx["consumer_id"], credits_used
        )
        ctx["paid_usage"] = settle_paid_usage(ctx["paid_usage"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_contract_in_expired_state(locator: str = None, base_credits: float = 1000,
                                     rollover_cap_credits: float = 200,
                                     term_start: str = CLOCK_START,
                                     term_end: str = None) -> dict:
    """An ACTIVE contract driven to EXPIRED by advancing the clock to its
    term_end."""
    account = create_account(locator=locator)
    contract = create_active_contract(
        account["id"], base_credits, rollover_cap_credits=rollover_cap_credits,
        term_start=term_start, term_end=term_end or add_days(term_start, 30),
    )
    set_clock(contract["term_end"])
    expired = get_contract(contract["id"])
    expire_day = expired["term_end"]
    return {
        "account": account,
        "account_id": account["id"],
        "contract": expired,
        "contract_id": expired["id"],
        "term_start": term_start,
        "term_end": expire_day,
        "next_term_end": add_days(expire_day, 30),
    }


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_monitor_at_consumption(consumption_credits: float, quota: float = 100,
                                 action: str = "NOTIFY",
                                 monitor_scope: str = "ACCOUNT_ONLY",
                                 warehouse_size: str = "LARGE",
                                 monitor_name: str = "MON") -> dict:
    """Account + monitor + a closed session whose billed credits land the
    monitor at exactly ``consumption_credits``.

    The session length is derived from the size factor so the billed figure is
    exact: credits = size_factor * clusters * billed_seconds / 3600.
    """
    from .constants import SIZE_FACTORS
    factor = SIZE_FACTORS[warehouse_size]
    billed_seconds = int(round(consumption_credits * SECONDS_PER_HOUR / factor))
    account = create_account(monitor_scope=monitor_scope)
    monitor = create_monitor(account["id"], monitor_name, quota, action=action)
    run = run_session_of_length(
        account["id"], "WH_MON", warehouse_size, CLOCK_START, billed_seconds,
        auto_suspend_seconds=60, clusters_min=1, clusters_max=1,
    )
    return {
        "account": account,
        "account_id": account["id"],
        "monitor": get_monitor(monitor["id"]),
        "monitor_id": monitor["id"],
        "warehouse": run["warehouse"],
        "session": run["session"],
        "expected_consumption": consumption_credits,
    }


def drain_account_via_monitor(locator: str = None, quota: float = 1000,
                              warehouse_size: str = "LARGE",
                              warehouse_name: str = "WH",
                              session_seconds: int = 5400,
                              monitor_name: str = "MON",
                              action: str = "SUSPEND",
                              extra_warehouses: int = 0,
                              monitor_scope: str = "ACCOUNT_ONLY") -> dict:
    """Drive an account to DRAINING by tipping its monitor past 100 percent.

    Returns the account, monitor, the warehouse whose session tipped it, and any
    sibling warehouses (/​contract/​warehouse ids) created for the scenario.
    """
    account = create_account(locator=locator, monitor_scope=monitor_scope)
    monitor = create_monitor(account["id"], monitor_name, quota, action=action)
    siblings = [
        create_warehouse(account["id"], f"{warehouse_name}_SIB{i}", warehouse_size,
                         auto_suspend_seconds=60, clusters_min=1, clusters_max=1)
        for i in range(1, extra_warehouses + 1)
    ]
    for sib in siblings:
        resume_warehouse(sib["id"])
    run = run_session_of_length(
        account["id"], warehouse_name, warehouse_size, CLOCK_START,
        session_seconds, auto_suspend_seconds=60, clusters_min=1, clusters_max=1,
    )
    ctx = {
        "account": get_account(account["id"]),
        "account_id": account["id"],
        "monitor": get_monitor(monitor["id"]),
        "monitor_id": monitor["id"],
        "warehouse": run["warehouse"],
        "warehouse_id": run["warehouse"]["id"],
        "session": run["session"],
        "siblings": siblings,
        "sibling_ids": [s["id"] for s in siblings],
    }
    return ctx


def setup_credit_drawdown_scenario(locator: str = None, base_credits: float = 1000,
                                   drawdown_amount: float = 1000,
                                   size: str = "SMALL",
                                   activate_as: dict = None,
                                   **contract_overrides) -> dict:
    """Account + ACTIVE contract + warehouse + one posted drawdown of
    ``drawdown_amount``."""
    ctx = setup_account_with_warehouse_and_contract(
        locator=locator, size=size, base_credits=base_credits,
        **contract_overrides,
    )
    if activate_as is not None:
        ctx["contract"] = activate_contract(ctx["contract_id"], activate_as)
    ctx["drawdown"] = post_drawdown(
        ctx["contract_id"], ctx["warehouse_id"], drawdown_amount, "auto-dd-1"
    )
    ctx["drawdown_id"] = ctx["drawdown"]["id"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — finalization / terminal state
# ---------------------------------------------------------------------------

def setup_revised_storage_snapshot(active_tb: float = 5.0, time_travel_tb: float = 1.0,
                                   fail_safe_tb: float = 1.0, time_travel_days: int = 7,
                                   usage_date: str = CLOCK_START) -> dict:
    """A storage snapshot captured and then revised once."""
    account = create_account()
    record = create_storage_record(
        account["id"], usage_date, active_tb=active_tb,
        time_travel_tb=time_travel_tb, fail_safe_tb=fail_safe_tb,
        time_travel_days=time_travel_days,
    )
    revised = revise_storage_record(
        record["id"], active_tb=active_tb + 1.0, time_travel_tb=time_travel_tb,
        fail_safe_tb=fail_safe_tb, time_travel_days=time_travel_days,
    )
    return {"account": account, "account_id": account["id"],
            "record": revised, "record_id": revised["id"]}


def setup_settled_dispute_row(listing_title: str = "LIST",
                              flat_price_usd: float = 0.50,
                              credits_used: float = 100,
                              dispute_as: str = "ops-dis-1") -> dict:
    """A published usage-based listing with a settled row, then disputed by an
    operator."""
    ctx = setup_published_listing(flat_price_usd=flat_price_usd,
                                  listing_title=listing_title,
                                  credits_used=credits_used)
    ctx["paid_usage"] = dispute_paid_usage(
        ctx["paid_usage"]["id"], ctx["listing"]["id"], ctx["provider_id"],
        actor=op_headers(dispute_as),
    )
    ctx["disputed_by_user_id"] = dispute_as
    return ctx