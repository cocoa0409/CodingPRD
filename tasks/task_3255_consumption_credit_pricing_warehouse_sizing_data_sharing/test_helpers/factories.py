"""Payload factories — input fields only, per entity."""
from .constants import CLOCK_START

# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

def create_account_payload(account_locator: str, **overrides) -> dict:
    defaults = {
        "org_name": "Test Organisation",
        "account_locator": account_locator,
        "cloud_provider": "SAME_CLOUD",
        "region": "us-east-1",
        "monitor_scope": "ACCOUNT_ONLY",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# VirtualWarehouse
# ---------------------------------------------------------------------------

def create_warehouse_payload(account_id: str, name: str, size: str = "XSMALL",
                             **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "name": name,
        "size": size,
    }
    defaults.update(overrides)
    return defaults


def patch_warehouse_payload(**overrides) -> dict:
    return dict(overrides)


# ---------------------------------------------------------------------------
# WarehouseSession
# ---------------------------------------------------------------------------

def create_session_payload(warehouse_id: str, **overrides) -> dict:
    defaults = {"warehouse_id": warehouse_id}
    defaults.update(overrides)
    return defaults


def close_session_payload(expected_warehouse_version, **overrides) -> dict:
    defaults = {"expected_warehouse_version": expected_warehouse_version}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# CapacityContract
# ---------------------------------------------------------------------------

def _add_month(iso: str) -> str:
    """Return the same day-of-month one calendar month later (dates in this API
    use a day-01 convention)."""
    from datetime import datetime, timedelta
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    return (dt + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_contract_payload(account_id: str, base_credits: float = 1000,
                            **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "term_start": CLOCK_START,
        "term_end": _add_month(CLOCK_START),
        "base_credits": base_credits,
        "overage_rate_per_credit": 3.00,
        "rollover_cap_credits": 200,
        "currency": "USD",
    }
    defaults.update(overrides)
    return defaults


def renew_contract_payload(new_term_start: str, new_term_end: str,
                           base_credits: float = 1000, **overrides) -> dict:
    defaults = {
        "new_term_start": new_term_start,
        "new_term_end": new_term_end,
        "base_credits": base_credits,
        "overage_rate_per_credit": 3.00,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# CreditDrawdown
# ---------------------------------------------------------------------------

def create_drawdown_payload(contract_id: str, warehouse_id: str, amount_credits: float,
                            idempotency_key: str, expected_contract_version,
                            source_kind: str = "SESSION", **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "warehouse_id": warehouse_id,
        "amount_credits": amount_credits,
        "source_kind": source_kind,
        "idempotency_key": idempotency_key,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# StorageUsageRecord
# ---------------------------------------------------------------------------

def create_storage_record_payload(account_id: str, usage_date: str,
                                  active_tb: float = 1.0, time_travel_tb: float = 0.0,
                                  fail_safe_tb: float = 0.0, time_travel_days: int = 0,
                                  **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "usage_date": usage_date,
        "active_tb": active_tb,
        "time_travel_tb": time_travel_tb,
        "fail_safe_tb": fail_safe_tb,
        "time_travel_days": time_travel_days,
    }
    defaults.update(overrides)
    return defaults


def revise_storage_record_payload(expected_storage_usage_record_version,
                                  **overrides) -> dict:
    defaults = {
        "active_tb": 1.0,
        "time_travel_tb": 0.0,
        "fail_safe_tb": 0.0,
        "time_travel_days": 0,
        "expected_storage_usage_record_version":
            expected_storage_usage_record_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# DataShare
# ---------------------------------------------------------------------------

def create_share_payload(provider_account_id: str, name: str,
                         consumer_account_ids: list, objects_exposed: int = 2,
                         **overrides) -> dict:
    defaults = {
        "provider_account_id": provider_account_id,
        "name": name,
        "objects_exposed": objects_exposed,
        "consumer_account_ids": list(consumer_account_ids),
    }
    defaults.update(overrides)
    return defaults


def create_usage_event_payload(consumer_account_id: str, credits_consumed: float = 1.0,
                               row_count: int = 1, **overrides) -> dict:
    defaults = {
        "consumer_account_id": consumer_account_id,
        "credits_consumed": credits_consumed,
        "row_count": row_count,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def create_listing_payload(share_id: str, title: str, pricing_model: str = "USAGE_BASED",
                           flat_price_usd: float = 0.50, **overrides) -> dict:
    defaults = {
        "share_id": share_id,
        "title": title,
        "pricing_model": pricing_model,
        "flat_price_usd": flat_price_usd,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# PaidShareUsage
# ---------------------------------------------------------------------------

def create_paid_usage_payload(listing_id: str, buyer_account_id: str,
                              credits_used: float, expected_listing_version,
                              **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "buyer_account_id": buyer_account_id,
        "credits_used": credits_used,
        "expected_listing_version": expected_listing_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ResourceMonitor
# ---------------------------------------------------------------------------

def create_monitor_payload(account_id: str, name: str, credit_quota: float,
                           interval: str = "MONTHLY", action: str = "NOTIFY",
                           **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "name": name,
        "credit_quota": credit_quota,
        "interval": interval,
        "action": action,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ReplicationConfiguration
# ---------------------------------------------------------------------------

def create_replication_payload(account_id: str, name: str, target_region: str,
                               replicated_tb: float, target_cloud: str = "SAME_CLOUD",
                               **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "name": name,
        "target_region": target_region,
        "target_cloud": target_cloud,
        "replicated_tb": replicated_tb,
    }
    defaults.update(overrides)
    return defaults