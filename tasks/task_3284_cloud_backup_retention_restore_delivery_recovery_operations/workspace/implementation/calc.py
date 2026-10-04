"""All fifteen calculation rules from PRD 3 / SCAFFOLD 1.3, plus the erasure
geometry.  Pure functions -- no store access, so precedence bugs stay visible.
"""

from decimal import Decimal

import constants as K
from util import (D, comb, dec2, f2, money, money_ceil, money_floor, q2, q6,
                  parse_instant)


# =============================================================================
# Rule 1 instance A -- effective retention window (PRD 3.4 pinned waterfall)
# =============================================================================
def group_retention_days(account, group, active_policy):
    """Steps 1-9 of the pinned waterfall.  Each step consumes the previous."""
    # 1. base window: extended when the account already carries extended history
    base = (K.EXTENDED_RETENTION_DAYS if account.get("has_extended_history")
            else K.BASE_RETENTION_DAYS)
    # 2. account window: the account's own retention_days when it has one
    account_days = account.get("retention_days")
    account_window = base if account_days is None else int(account_days)
    # 3. group request
    group_request = group.get("retention_days_override")
    # 4-6. floor and ceiling from the ACTIVE RETENTION policy (null when absent)
    floor = 0 if active_policy is None else int(active_policy.get("min_retention_days") or 0)
    ceiling = None if active_policy is None else active_policy.get("max_extended_history_days")
    # 7. requested window
    requested = account_window if group_request is None else int(group_request)
    # 8. cap first (no ceiling -> unchanged)
    capped = requested if ceiling is None else min(requested, int(ceiling))
    # 9. the floor always wins a conflict
    return max(capped, floor)


def account_retention_days(groups):
    """Step 10: max over the account's groups, zero when it has none."""
    if not groups:
        return 0
    return max(int(g.get("group_retention_days") or 0) for g in groups)


def has_extended_history(retention_days):
    """Step 11: strictly greater than the standard 30-day window."""
    return int(retention_days or 0) > K.BASE_RETENTION_DAYS


# =============================================================================
# Rule 1 instance B -- billable egress (PRD 3.6 threshold rule + variant)
# =============================================================================
def billable_egress_gb(requested_size_gb, is_ransomware_recovery):
    raw = dec2(requested_size_gb or 0)
    if is_ransomware_recovery:
        # protected variant: only the 100 GB ransomware allowance applies
        return q2(max(Decimal("0"), raw - D(K.RANSOMWARE_PROTECTED_GB)))
    free = min(raw, D(K.FREE_EGRESS_GB))
    partial = raw - free
    overage = max(Decimal("0"), raw - D(K.OVERSIZE_THRESHOLD_GB))
    return q2(partial + overage * D(K.OPERATOR_SURCHARGE_RATE))


# =============================================================================
# Rule 3+4 -- per-restore egress fee (PRD 3.6, pinned evaluation order)
# =============================================================================
def restore_egress_fee_cents(egress_gb, storage_tier, restore_transaction_count):
    rate = D(K.EGRESS_TIER_RATES_CENTS_PER_GB.get(storage_tier, 1))
    transaction_fee = D(int(restore_transaction_count or 0)) * D(K.PER_RESTORE_TRANSACTION_CENTS)
    raw_fee = dec2(egress_gb or 0) * rate
    if raw_fee >= D(K.DISCOUNT_HIGH_MIN_CENTS):
        pct = Decimal("0.10")
    elif raw_fee >= D(K.DISCOUNT_LOW_MIN_CENTS):
        pct = Decimal("0.05")
    else:
        pct = Decimal("0.00")
    discount = raw_fee * pct
    net_fee = raw_fee - discount + transaction_fee
    return money_ceil(net_fee)


# =============================================================================
# Rule 2 mode (b) -- storage charge, pinned rounding order (PRD 3.6)
# =============================================================================
def storage_charge(account, period):
    """Returns the full term dict; every per-term value floored before summing."""
    period_days = int((parse_instant(period["period_end_utc"])
                       - parse_instant(period["period_start_utc"])).total_seconds() // 86400)
    if period_days <= 0:
        period_days = 0
    active_days = int(period.get("restore_active_days") or 0)
    active_days = max(0, min(active_days, period_days))

    usage_avg = dec2(period.get("usage_gb_avg") or 0)
    peak = dec2(period.get("peak_usage_gb") or 0)
    if period_days == 0:
        weighted_avg = Decimal("0")
    else:
        weighted_avg = (usage_avg * (period_days - active_days)
                        + peak * active_days) / Decimal(period_days)

    tier = account.get("storage_tier", "BASIC")
    storage_rate = D(K.STORAGE_TIER_RATE_CENTS_PER_GB_MONTH.get(tier, 6))
    egress_rate = D(K.EGRESS_TIER_RATES_CENTS_PER_GB.get(tier, 1))

    gross_storage = money_floor(weighted_avg * storage_rate
                                * Decimal(period_days) / Decimal(K.DAYS_PER_MONTH))

    credit_observed = money_floor(dec2(account.get("initial_full_backup_gb") or 0)
                                  * storage_rate)
    initial_upload_credit = min(credit_observed, K.CREDIT_CAP_CENTS)
    # consumed by the FIRST closed period of the account only
    if account.get("first_closed_period_utc") is not None:
        initial_upload_credit = 0
    storage_credit_applied = min(gross_storage, initial_upload_credit)
    storage_fee = gross_storage - storage_credit_applied

    egress_fee = money_floor(dec2(period.get("egress_gb") or 0) * egress_rate)
    transaction_fee = int(period.get("transaction_count") or 0) * K.PER_TRANSACTION_CENTS
    total = storage_fee + egress_fee + transaction_fee

    return {
        "period_days": period_days,
        "gross_storage_fee_cents": gross_storage,
        "storage_fee_cents": storage_fee,
        "initial_upload_credit_cents": initial_upload_credit,
        "storage_credit_applied_cents": storage_credit_applied,
        "egress_fee_cents": egress_fee,
        "transaction_fee_cents": transaction_fee,
        "total_cents": total,
    }


# =============================================================================
# Rule 2 mode (a) -- delinquency threshold (PRD 3.6, inclusive)
# =============================================================================
def is_delinquent_total(total_cents):
    return int(total_cents or 0) >= K.DELINQUENCY_THRESHOLD_CENTS


# =============================================================================
# Rule 2 mode (a) companion -- account usage / peak (PRD 3.1)
# =============================================================================
def account_usage_gb(live_bytes):
    return q2(D(live_bytes) / D(K.GB_BYTES))


def peak_usage(prior_peak, usage_gb):
    """PRD 3.1: the larger of its own prior value and the fresh usage_gb."""
    return q2(max(D(prior_peak or 0), D(usage_gb or 0)))


# =============================================================================
# Rule 5 -- retention floor (PRD 3.3)
# =============================================================================
def retention_floor_utc(versions):
    """Earliest event_utc among versions neither expired nor deleted."""
    candidates = [v for v in versions if not v["is_expired"] and not v["is_deleted"]]
    if not candidates:
        return None
    candidates.sort(key=lambda v: (v["event_utc"], v["created_at"], v["_order"]))
    return candidates[0]["event_utc"]


# =============================================================================
# Rule 6 -- version chain projection (PRD 3.3)
# =============================================================================
def version_chain_depth(versions):
    ordered = sorted(versions, key=lambda v: (v["event_utc"], v["created_at"],
                                              v["_order"], v["_seq"]))
    depth = 0
    for v in ordered:
        op = v["operation"]
        if op == "CREATE":
            depth = 1
        elif op == "MODIFY":
            depth = depth + 1
        elif op == "DELETE":
            depth = 0
    return depth


# =============================================================================
# Rule 3 companion -- recovery points (PRD 3.3)
# =============================================================================
def recovery_points(versions):
    eligible = [v for v in versions if not v["is_expired"]]
    if not eligible:
        return 0
    eligible.sort(key=lambda v: v["created_at"])
    return len({v["event_utc"] for v in eligible})


def live_path_bytes(versions):
    """Live byte total: for each file_path, the size of the chain's newest
    surviving version whose operation is not DELETE -- that is, the current
    content of the file (PRD 3.1 / 3.2 / 3.3).  A DELETE leaves the path with
    no live content.
    """
    newest = {}
    for v in versions:
        if v["is_expired"]:
            continue
        path = v["file_path"]
        key = (int(v["version_number"]), v["_order"], v["_seq"])
        if path not in newest or key > newest[path][0]:
            newest[path] = (key, v)
    total = 0
    for _key, v in newest.values():
        if v["operation"] != "DELETE" and not v["is_deleted"]:
            total += int(v["size_bytes"] or 0)
    return total


def set_storage_gb(versions):
    """Current live content over GB_BYTES, 2dp floor (PRD 3.2)."""
    return f2(D(live_path_bytes(versions)) / D(K.GB_BYTES))


def archive_entry_count(versions, requested_file_count):
    """PRD 3.5: 0 means every live file in the set."""
    live_paths = {v["file_path"] for v in versions
                  if not v["is_deleted"] and not v["is_expired"]}
    if int(requested_file_count or 0) == 0:
        return len(live_paths)
    return int(requested_file_count)


# =============================================================================
# Rule 1 companion -- ransomware detection (PRD 3.5, strict comparison)
# =============================================================================
def ransomware_recovery_flag(versions, restore_point_in_utc):
    target = parse_instant(restore_point_in_utc)
    delete_instants = {v["event_utc"] for v in versions if v["operation"] == "DELETE"}
    for instant in delete_instants:
        if parse_instant(instant) > target:
            return True
    return False


def restore_point_expired(versions, restore_point_in_utc):
    """PRD 3.5 prepare: every requested file must be non-expired at the point."""
    for v in versions:
        if v["is_expired"]:
            return True
    return False


# =============================================================================
# Rule 2 mode (b) companion -- group transaction apportionment (PRD 3.2)
# =============================================================================
def group_transaction_metrics(store, account_id, clock):
    """Walk the account's ACTIVE groups in ascending created_seq."""
    groups = [g for g in store.groups_of_account(account_id) if g["status"] == "ACTIVE"]
    metrics = []
    total_marginal = 0
    for group in groups:
        increments_day = K.INCREMENTS_PER_DAY.get(group["tier"], 24)
        dedup = _deduplicated_transactions(store, group["id"], clock)
        marginal = max(0, increments_day - dedup)
        total_marginal += marginal
        metrics.append({"group": group, "increments_day": increments_day,
                        "deduplicated": dedup, "marginal": marginal})
    denominator = max(1, total_marginal)
    for m in metrics:
        m["expected_daily_transactions"] = m["increments_day"]
        m["member_transaction_share"] = q2(D(m["marginal"]) / D(denominator))
    return metrics


def _deduplicated_transactions(store, group_id, clock):
    """Distinct (backup_set_id, file_path) pairs recording CREATE/MODIFY in the
    last completed day (the 24 hours ending at the logical clock)."""
    from datetime import timedelta
    set_ids = [s["id"] for s in store.sets.values() if s["agent_id"] in
               {a["id"] for a in store.agents_of_group(group_id)}]
    if not set_ids:
        return 0
    window_end = clock
    window_start = clock - timedelta(days=1)
    pairs = set()
    for v in store.versions.values():
        if v["backup_set_id"] not in set_ids:
            continue
        if v["operation"] not in ("CREATE", "MODIFY"):
            continue
        instant = parse_instant(v["event_utc"])
        if window_start <= instant < window_end:
            pairs.add((v["backup_set_id"], v["file_path"]))
    return len(pairs)


# =============================================================================
# Rule 9 instance B -- deletion purge selection + conservation (PRD 3.8)
# =============================================================================
def deletion_targets(store, account_id, deletion_scope):
    rows = store.all_versions_of_account(account_id)
    if deletion_scope == "DELETED_FILES":
        return [v for v in rows if v["is_deleted"] or v["is_expired"]]
    return list(rows)


def purge_conservation(purged):
    """round_half_up(live purged GB) - round_half_up(staged purged GB)."""
    live_bytes = sum(int(v["size_bytes"] or 0) for v in purged
                     if not v["is_deleted"] and not v["is_expired"])
    staged_bytes = sum(int(v["size_bytes"] or 0) for v in purged
                       if v["is_deleted"] or v["is_expired"])
    return q2(D(live_bytes) / D(K.GB_BYTES)) - q2(D(staged_bytes) / D(K.GB_BYTES))


# =============================================================================
# Rule 9 companion -- deposit conservation (PRD 3.7)
# =============================================================================
def deposit_conservation(shipments):
    held_refundable = 0
    forfeited = 0
    for s in shipments:
        count = int(s.get("drive_count") or 0)
        fee = int(s.get("deposit_fee_cents") or 0)
        if s["state"] in ("PREPARING", "SHIPPED", "DELIVERED", "AWAITING_RETURN"):
            held_refundable += count * fee
        if s.get("was_delinquent"):
            forfeited += count * K.LATE_RETURN_PENALTY_CENTS_PER_DRIVE
    return held_refundable + forfeited


# =============================================================================
# Rule 6 companion -- pod shard geometry (PRD 2.7)
# =============================================================================
def pod_shard_geometry(total_shards, data_shards, failed_shards):
    parity = int(total_shards) - int(data_shards)
    reconstructable = int(failed_shards) <= parity
    if failed_shards == 0:
        status = "HEALTHY"
    elif failed_shards <= parity:
        status = "DEGRADED"
    else:
        status = "FAILED"
    return {"parity_shards": parity, "is_reconstructable": reconstructable,
            "status": status}


def pod_reliability_pct(total_shards, data_shards):
    parity = int(total_shards) - int(data_shards)
    exponent = parity + 1
    unrecoverable = (D(comb(int(total_shards), exponent))
                     * D(K.ANNUAL_SHARD_FAILURE_RATE) ** exponent)
    return q6(D(100) * (D(1) - unrecoverable))


def shipment_return_deadline(shipped_at, return_window_days=K.RETURN_WINDOW_DAYS):
    from util import add_days
    return add_days(parse_instant(shipped_at), return_window_days)


def shipment_return_credit(drive_count, deposit_fee_cents, was_delinquent):
    """Deposit minus the late penalty, never below zero (PRD 3.7)."""
    gross = int(drive_count or 0) * int(deposit_fee_cents or 0)
    if was_delinquent:
        penalty = int(drive_count or 0) * K.LATE_RETURN_PENALTY_CENTS_PER_DRIVE
        return max(0, gross - penalty)
    return gross