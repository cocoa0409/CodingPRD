"""Entity -> JSON projections.  Decimals are emitted as JSON numbers."""
from util import out_num, fmt_dt, r6, r2, r2 as _r2
from services import engine


def dt(value):
    return fmt_dt(value)


def account(a):
    return {
        "id": a["id"],
        "org_name": a["org_name"],
        "account_locator": a["account_locator"],
        "region": a["region"],
        "region_factor": out_num(a["region_factor"]),
        "cloud_provider": a["cloud_provider"],
        "monitor_scope": a["monitor_scope"],
        "posted_consumption_credits_reconciled": out_num(a["posted_consumption_credits_reconciled"]),
        "posted_storage_dollars_reconciled": out_num(a["posted_storage_dollars_reconciled"]),
        "account_state": a["account_state"],
        "created_at": dt(a["created_at"]),
        "updated_at": dt(a["updated_at"]),
        "version": a["version"],
    }


def warehouse(w):
    return {
        "id": w["id"],
        "account_id": w["account_id"],
        "name": w["name"],
        "size": w["size"],
        "credits_per_hour": out_num(w["credits_per_hour"]),
        "auto_suspend_seconds": w["auto_suspend_seconds"],
        "auto_resume": w["auto_resume"],
        "status": w["status"],
        "cluster_count": w["cluster_count"],
        "clusters_min": w["clusters_min"],
        "clusters_max": w["clusters_max"],
        "multi_cluster_queued_queries": w["multi_cluster_queued_queries"],
        "latency_slo_ms": w["latency_slo_ms"],
        "created_at": dt(w["created_at"]),
        "updated_at": dt(w["updated_at"]),
        "version": w["version"],
    }


def session(s):
    return {
        "id": s["id"],
        "warehouse_id": s["warehouse_id"],
        "originating_query_id": s.get("originating_query_id"),
        "size": s["size"],
        "clusters": s["clusters"],
        "started_at": dt(s["started_at"]),
        "ended_at": dt(s["ended_at"]),
        "elapsed_seconds": s["elapsed_seconds"],
        "state": s["state"],
        "metered_credits": out_num(s["metered_credits"]),
        "billed_credits": out_num(s["billed_credits"]),
        "billed_seconds": s["billed_seconds"],
        "created_at": dt(s["created_at"]),
        "updated_at": dt(s["updated_at"]),
        "version": s["version"],
    }


def contract(c):
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "term_start": dt(c["term_start"]),
        "term_end": dt(c["term_end"]),
        "base_credits": out_num(c["base_credits"]),
        "overage_rate_per_credit": out_num(c["overage_rate_per_credit"]),
        "rollover_cap_credits": out_num(c["rollover_cap_credits"]),
        "currency": c["currency"],
        "status": c["status"],
        "drawdown_count": c["drawdown_count"],
        "remaining_credits": out_num(c["remaining_credits"]),
        "drawn_credits": out_num(c["drawn_credits"]),
        "rolled_over_credits": out_num(c["rolled_over_credits"]),
        "base_consumed_credits": out_num(c["base_consumed_credits"]),
        "term_end_remaining_credits": out_num(c["term_end_remaining_credits"]),
        "activated_by_user_id": c["activated_by_user_id"],
        "created_at": dt(c["created_at"]),
        "updated_at": dt(c["updated_at"]),
        "version": c["version"],
    }


def drawdown(d):
    return {
        "id": d["id"],
        "contract_id": d["contract_id"],
        "warehouse_id": d["warehouse_id"],
        "amount_credits": out_num(d["amount_credits"]),
        "source_kind": d["source_kind"],
        "status": d["status"],
        "idempotency_key": d["idempotency_key"],
        "outcome": d["outcome"],
        "overage_usd": out_num(d["overage_usd"]),
        "base_portion": out_num(d.get("base_portion", 0)) if "base_portion" in d else 0.0,
        "created_at": dt(d["created_at"]),
        "updated_at": dt(d["updated_at"]),
        "version": d["version"],
    }


def storage(r):
    return {
        "id": r["id"],
        "account_id": r["account_id"],
        "usage_date": dt(r["usage_date"]),
        "active_tb": out_num(r["active_tb"]),
        "time_travel_tb": out_num(r["time_travel_tb"]),
        "fail_safe_tb": out_num(r["fail_safe_tb"]),
        "time_travel_days": r["time_travel_days"],
        "fail_safe_days": r["fail_safe_days"],
        "billable_storage_tb": out_num(r["billable_storage_tb"]),
        "storage_cost_dollars": out_num(r["storage_cost_dollars"]),
        "snapshot_state": r["snapshot_state"],
        "per_component": {k: out_num(v) for k, v in r["per_component"].items()},
        "created_at": dt(r["created_at"]),
        "updated_at": dt(r["updated_at"]),
        "version": r["version"],
    }


def share(s):
    return {
        "id": s["id"],
        "provider_account_id": s["provider_account_id"],
        "name": s["name"],
        "objects_exposed": s["objects_exposed"],
        "consumer_account_ids": list(s["consumer_account_ids"]),
        "status": s["status"],
        "consumer_query_count": s["consumer_query_count"],
        "consumer_credits": out_num(s["consumer_credits"]),
        "created_at": dt(s["created_at"]),
        "updated_at": dt(s["updated_at"]),
        "version": s["version"],
    }


def share_usage(e):
    return {
        "id": e["id"],
        "share_id": e["share_id"],
        "consumer_account_id": e["consumer_account_id"],
        "queried_at": dt(e["queried_at"]),
        "credits_consumed": out_num(e["credits_consumed"]),
        "row_count": e["row_count"],
        "attribution": e["attribution"],
        "attributed_row_count": e["attributed_row_count"],
        "credited_account_id": e["credited_account_id"],
        "created_at": dt(e["created_at"]),
        "updated_at": dt(e["updated_at"]),
        "version": e["version"],
    }


def listing(l):
    return {
        "id": l["id"],
        "share_id": l["share_id"],
        "title": l["title"],
        "pricing_model": l["pricing_model"],
        "flat_price_usd": out_num(l["flat_price_usd"]),
        "listing_state": l["listing_state"],
        "gross_credit_volume": out_num(l["gross_credit_volume"]),
        "provider_payout_usd": out_num(l["provider_payout_usd"]),
        "platform_fee_usd": out_num(l["platform_fee_usd"]),
        "frozen_price_usd": out_num(l["frozen_price_usd"]),
        "created_at": dt(l["created_at"]),
        "updated_at": dt(l["updated_at"]),
        "version": l["version"],
    }


def paid_usage(p):
    return {
        "id": p["id"],
        "listing_id": p["listing_id"],
        "buyer_account_id": p["buyer_account_id"],
        "credits_used": out_num(p["credits_used"]),
        "price_per_credit": out_num(p["price_per_credit"]),
        "usage_state": p["usage_state"],
        "disputed_by_user_id": p["disputed_by_user_id"],
        "created_at": dt(p["created_at"]),
        "updated_at": dt(p["updated_at"]),
        "version": p["version"],
    }


def monitor(m):
    return {
        "id": m["id"],
        "account_id": m["account_id"],
        "name": m["name"],
        "credit_quota": out_num(m["credit_quota"]),
        "interval": m["interval"],
        "action": m["action"],
        "monitor_state": m["monitor_state"],
        "interval_consumption_credits": out_num(m["interval_consumption_credits"]),
        "used_pct": out_num(m["used_pct"]),
        "last_reset_at": dt(m["last_reset_at"]),
        "created_at": dt(m["created_at"]),
        "updated_at": dt(m["updated_at"]),
        "version": m["version"],
    }


def replication(r):
    return {
        "id": r["id"],
        "account_id": r["account_id"],
        "name": r["name"],
        "target_region": r["target_region"],
        "target_cloud": r["target_cloud"],
        "replicated_tb": out_num(r["replicated_tb"]),
        "refresh_count": r["refresh_count"],
        "transfer_cost_dollars": out_num(r["transfer_cost_dollars"]),
        "last_refresh_at": dt(r["last_refresh_at"]),
        "replication_state": r["replication_state"],
        "created_at": dt(r["created_at"]),
        "updated_at": dt(r["updated_at"]),
        "version": r["version"],
    }


def ledger(row):
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "bucket": row["bucket"],
        "source_entity": row["source_entity"],
        "source_entity_id": row["source_entity_id"],
        "amount_credits": out_num(row["amount_credits"]),
        "amount_usd": out_num(row["amount_usd"]),
        "posted_at": dt(row["posted_at"]),
        "created_at": dt(row["created_at"]),
    }
