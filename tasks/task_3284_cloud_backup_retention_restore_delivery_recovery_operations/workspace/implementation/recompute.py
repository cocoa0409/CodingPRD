"""Derived-field recomputation and cascade hops (PRD 3.1-3.9).

Each helper is a pure recompute: it rewrites the derived fields but does not
touch `version` / `updated_at`.  Callers bump the entities they actually
mutate (PRD 2.4: any recomputation is a mutation, and the scaffold's endpoint
table states exactly one increment per affected entity per operation).
"""

from datetime import timedelta

import calc
import constants as K
from models import touch
from util import dec2, fmt_ts, parse_instant, q2


# ---------------------------------------------------------------------------
# group / account retention roll-up (PRD 3.4)
# ---------------------------------------------------------------------------
def recompute_group_retention(store, group):
    account = store.accounts.get(group["account_id"])
    policy = store.active_policy(group["id"], "RETENTION")
    if account is not None:
        group["group_retention_days"] = calc.group_retention_days(account, group, policy)
    return group


def recompute_account_retention(store, account):
    groups = store.groups_of_account(account["id"])
    # the roll-up reads the groups' already-computed windows
    account["retention_days"] = calc.account_retention_days(groups)
    account["has_extended_history"] = calc.has_extended_history(account["retention_days"])
    return account


# ---------------------------------------------------------------------------
# account volume ledger (PRD 3.1)
# ---------------------------------------------------------------------------
def live_and_staged_bytes(store, account_id):
    """Only INITIAL_RUNNING / ACTIVE / SUSPENDED sets contribute (PRD 3.1)."""
    set_ids = {s["id"] for s in store.sets_of_account(account_id)
               if s["state"] in ("INITIAL_RUNNING", "ACTIVE", "SUSPENDED")}
    rows = [v for v in store.versions.values() if v["backup_set_id"] in set_ids]
    live = calc.live_path_bytes(rows)
    staged = sum(int(v["size_bytes"] or 0) for v in rows
                 if v["is_deleted"] and not v["is_expired"])
    return live, staged


def recompute_account_usage(store, account):
    live, _staged = live_and_staged_bytes(store, account["id"])
    account["usage_gb"] = calc.account_usage_gb(live)
    account["peak_usage_gb"] = calc.peak_usage(account.get("peak_usage_gb"),
                                               account["usage_gb"])
    return account


def recompute_account_group_count(store, account):
    account["group_count"] = len(store.groups_of_account(account["id"]))
    return account


def recompute_initial_full_backup_gb(store, account):
    """Max storage_gb over the sets still flushing; keep the recorded value once
    the flush has completed, since it is the basis of the one-time credit."""
    flushing = [s for s in store.sets_of_account(account["id"]) if s.get("is_initial_flush")]
    if flushing:
        account["initial_full_backup_gb"] = q2(
            max(dec2(s.get("storage_gb") or 0) for s in flushing))
    return account


# ---------------------------------------------------------------------------
# backup set projections (PRD 3.3)
# ---------------------------------------------------------------------------
def set_versions(store, set_id):
    return store.all_versions_of_set(set_id)


def group_retention_for_set(store, bset):
    agent = store.agents.get(bset.get("agent_id"))
    if agent is None:
        return K.BASE_RETENTION_DAYS
    group = store.groups.get(agent.get("group_id"))
    if group is None:
        return K.BASE_RETENTION_DAYS
    return int(group.get("group_retention_days") or K.BASE_RETENTION_DAYS)


def recompute_version_flags(store, bset):
    """recoverable_until_utc = event_utc + group_retention_days;
    is_expired = (logical clock >= recoverable_until_utc) -- PRD 3.3."""
    window = group_retention_for_set(store, bset)
    now = store.now()
    for v in store.all_versions_of_set(bset["id"]):
        v["recoverable_until_utc"] = _plus_days(v["event_utc"], window)
        v["is_expired"] = now >= parse_instant(v["recoverable_until_utc"])
    return bset


def _plus_days(event_utc, days):
    return fmt_ts(parse_instant(event_utc) + timedelta(days=days))


def recompute_set(store, bset):
    versions = set_versions(store, bset["id"])
    bset["storage_gb"] = calc.set_storage_gb(versions)
    bset["version_chain_depth"] = calc.version_chain_depth(versions)
    bset["recovery_points"] = calc.recovery_points(versions)
    bset["retention_floor_utc"] = calc.retention_floor_utc(versions)
    return bset


def recompute_set_last_backup(store, bset, event_utc=None):
    if event_utc is not None:
        bset["last_backup_at"] = event_utc
    return bset


# ---------------------------------------------------------------------------
# group metrics (PRD 3.2)
# ---------------------------------------------------------------------------
def recompute_group_metrics(store, group):
    """agent_count is the count of agents that were activated and not retired --
    i.e. status in {ACTIVE, BLOCKED}.  This reproduces every declared
    increment/decrement on the activation, retirement and block edges."""
    group["agent_count"] = len([a for a in store.agents_of_group(group["id"])
                                if a["status"] in ("ACTIVE", "BLOCKED")])
    metrics = calc.group_transaction_metrics(store, group["account_id"], store.now())
    for m in metrics:
        if m["group"]["id"] == group["id"]:
            group["expected_daily_transactions"] = m["expected_daily_transactions"]
            group["member_transaction_share"] = m["member_transaction_share"]
            return group
    return group


def recompute_all_group_metrics(store, account_id):
    metrics = calc.group_transaction_metrics(store, account_id, store.now())
    for m in metrics:
        m["group"]["expected_daily_transactions"] = m["expected_daily_transactions"]
        m["group"]["member_transaction_share"] = m["member_transaction_share"]


# ---------------------------------------------------------------------------
# agent (PRD 3.1-3.3)
# ---------------------------------------------------------------------------
def recompute_agent(store, agent):
    sets = store.sets_of_agent(agent["id"])
    highest = 0
    stored = 0.0
    for bset in sets:
        for v in set_versions(store, bset["id"]):
            highest = max(highest, int(v["version_number"] or 0))
        stored += float(bset.get("storage_gb") or 0)
    agent["last_change_sequence"] = highest
    agent["data_stored_gb"] = q2(stored)
    agent["in_throttle_window"] = any(s.get("is_initial_flush") for s in sets)
    group = store.groups.get(agent.get("group_id"))
    if group is not None:
        peers = store.agents_of_group(group["id"])
        total = sum(float(a.get("data_stored_gb") or 0) for a in peers)
        agent["data_stored_share"] = q2(float(agent["data_stored_gb"]) / total) if total > 0 else 0.0
    return agent


def recompute_all_agents(store, account_id):
    for agent in store.agents_of_account(account_id):
        recompute_agent(store, agent)


# ---------------------------------------------------------------------------
# deposits and shipments (PRD 3.7)
# ---------------------------------------------------------------------------
def recompute_deposit_held(store, account):
    account["deposit_held_cents"] = calc.deposit_conservation(
        store.shipments_of_account(account["id"]))
    return account


def recompute_shipment(store, shipment):
    if shipment.get("shipped_at"):
        shipment["return_deadline_utc"] = fmt_ts(calc.shipment_return_deadline(
            shipment["shipped_at"]))
    shipment["return_credit_cents"] = calc.shipment_return_credit(
        shipment.get("drive_count"), shipment.get("deposit_fee_cents"),
        bool(shipment.get("was_delinquent")))
    return shipment


# ---------------------------------------------------------------------------
# billing period (PRD 3.6)
# ---------------------------------------------------------------------------
def recompute_period_open(store, period):
    """Opening recomputes usage_gb_avg and peak_usage_gb from the account's
    sets (PRD 3.6), so the account's own ledger is refreshed first."""
    account = store.accounts.get(period["account_id"])
    if account is None:
        return period
    recompute_account_usage(store, account)
    period["usage_gb_avg"] = q2(account.get("usage_gb") or 0)
    period["peak_usage_gb"] = q2(account.get("peak_usage_gb") or 0)
    return period


def recompute_period_close(store, period):
    """Settle every charge term; the account's accumulated egress and
    transactions are what the period bills (PRD 3.6)."""
    account = store.accounts.get(period["account_id"])
    if account is None:
        return period
    period["egress_gb"] = q2(account.get("restore_download_gb") or 0)
    period["transaction_count"] = int(account.get("transaction_count") or 0)
    terms = calc.storage_charge(account, period)
    period["storage_fee_cents"] = terms["storage_fee_cents"]
    period["initial_upload_credit_cents"] = terms["initial_upload_credit_cents"]
    period["storage_credit_applied_cents"] = terms["storage_credit_applied_cents"]
    period["egress_fee_cents"] = terms["egress_fee_cents"]
    period["transaction_fee_cents"] = terms["transaction_fee_cents"]
    period["total_cents"] = terms["total_cents"]
    return period


def settle_closed_period(store, account, period):
    """A closing period whose total is at least the 5000-cent threshold moves a
    still-ACTIVE account to DELINQUENT and suspends its ACTIVE sets; the first
    closed period is also what consumes the one-time initial-upload credit
    (PRD 3.1, 3.6).

    Returns True when the account itself was mutated, so the caller can advance
    `version` exactly once for the whole operation.
    """
    changed = False
    if account["status"] == "ACTIVE" and calc.is_delinquent_total(period["total_cents"]):
        account["status"] = "DELINQUENT"
        for bset in store.sets_of_account(account["id"]):
            if bset["state"] == "ACTIVE":
                bset["state"] = "SUSPENDED"
                touch(store, bset)
        changed = True
    if account.get("first_closed_period_utc") is None:
        account["first_closed_period_utc"] = period["period_end_utc"]
        changed = True
    return changed


def cascade_close_shipment(store, shipment, bump_shipment=True):
    """RETURNED -> CLOSED plus the whole cascade (PRD 3.7): the account's held
    deposit is recomputed and every OPEN billing period of the account is
    recomputed and closed."""
    account = store.accounts.get(shipment["account_id"])
    shipment["state"] = "CLOSED"
    if account is not None:
        account_changed = False
        for period in store.periods_of_account(account["id"]):
            if period["state"] == "OPEN":
                recompute_period_close(store, period)
                period["state"] = "CLOSED"
                account_changed = settle_closed_period(store, account, period) or account_changed
                touch(store, period)
        recompute_deposit_held(store, account)
        touch(store, account)
    if bump_shipment:
        touch(store, shipment)
    return shipment


# ---------------------------------------------------------------------------
# storage pod geometry (PRD 2.7)
# ---------------------------------------------------------------------------
def recompute_pod(store, pod):
    geom = calc.pod_shard_geometry(pod["total_shards"], pod["data_shards"],
                                   pod["failed_shards"])
    pod["parity_shards"] = geom["parity_shards"]
    pod["is_reconstructable"] = geom["is_reconstructable"]
    pod["reliability_pct"] = calc.pod_reliability_pct(pod["total_shards"],
                                                      pod["data_shards"])
    # status is only cascaded by the explicit transitions; a pure recompute of
    # the geometry does not move HEALTHY/REPAIRING pods on its own.
    if pod.get("status") in ("HEALTHY", "DEGRADED", "FAILED"):
        pod["status"] = geom["status"]
    return pod


def recompute_pod_status_only(store, pod):
    geom = calc.pod_shard_geometry(pod["total_shards"], pod["data_shards"],
                                   pod["failed_shards"])
    pod["parity_shards"] = geom["parity_shards"]
    pod["is_reconstructable"] = geom["is_reconstructable"]
    return pod