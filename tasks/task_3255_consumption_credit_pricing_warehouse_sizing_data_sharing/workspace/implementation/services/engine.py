"""Business rules: STATE, LEDGER, LEDGERPOST, ATTR, SESSIONBILL,
CONTRACTSEG, POSTURESWEEP."""
from decimal import Decimal

from db import db, find
from errors import err
from util import r2, r6, out_num, now, fmt_dt, new_id

# ------------------------------------------------------------- constants ----

SIZE_FACTORS = {
    "XSMALL": 1, "SMALL": 2, "MEDIUM": 4, "LARGE": 8,
    "XLARGE": 16, "XXLARGE": 32, "XXXLARGE": 64, "X4LARGE": 128,
}
SIZES = list(SIZE_FACTORS.keys())
REGIONS = ("us-east-1", "us-west-2", "eu-central-1", "ap-southeast-1")
CLOUDS = ("SAME_CLOUD", "CROSS_CLOUD")
CURRENCIES = ("USD", "EUR", "GBP", "JPY")
INTERVALS = ("DAILY", "WEEKLY", "MONTHLY")
MONITOR_ACTIONS = ("NOTIFY", "SUSPEND", "SUSPEND_IMMEDIATE")
PRICING_MODELS = ("FREE", "FLAT", "USAGE_BASED")
SOURCES = ("SESSION", "SHARE_CONSUMPTION", "REPLICATION")

REGION_FACTOR = {"us-east-1": Decimal("1.00"), "us-west-2": Decimal("1.10"),
                 "eu-central-1": Decimal("1.20"), "ap-southeast-1": Decimal("1.30")}
CLOUD_FACTOR = {"SAME_CLOUD": Decimal("1.00"), "CROSS_CLOUD": Decimal("1.35")}
COST_PER_TB = Decimal("5.00")
DAYS_IN_MONTH = Decimal("30")
BILLABLE_RATE = {"ACTIVE": Decimal("0.77"), "TIME_TRAVEL": Decimal("0.84"),
                 "FAIL_SAFE": Decimal("1.01")}
PLATFORM_COMMISSION_PCT = Decimal("0.15")
QUERIES_PER_CLUSTER = 8
PROJECTED_SECONDS = Decimal("900")
SECONDS_PER_HOUR = Decimal("3600")

CREDIT_BUCKETS = ("CONSUMPTION", "SHARE_CONSUMPTION")
STORAGE_BUCKETS = ("STORAGE", "STORAGE_ADJUST")
DOLLAR_BUCKETS = ("STORAGE", "STORAGE_ADJUST", "OVERAGE", "REPLICATION",
                  "PAYOUT", "PAYOUT_ADJUST")
ALL_BUCKETS = ("CONSUMPTION", "OVERAGE", "ROLLOVER", "REPLICATION",
               "SHARE_CONSUMPTION", "STORAGE", "STORAGE_ADJUST", "PAYOUT",
               "PAYOUT_ADJUST")


# ---------------------------------------------------------------- STATE ----

def require(condition, error_id, message):
    if not condition:
        raise err(error_id, message)


def find_contract(contract_id):
    return find(db.contracts, contract_id)


def find_warehouse(warehouse_id):
    return find(db.warehouses, warehouse_id)


def find_account(account_id):
    return find(db.accounts, account_id)


def find_share(share_id):
    return find(db.shares, share_id)


def find_listing(listing_id):
    return find(db.listings, listing_id)


def find_session(session_id):
    return find(db.sessions, session_id)


def find_drawdown(drawdown_id):
    return find(db.drawdowns, drawdown_id)


def find_storage(record_id):
    return find(db.storage_records, record_id)


def find_monitor(monitor_id):
    return find(db.monitors, monitor_id)


def find_replication(repl_id):
    return find(db.replications, repl_id)


def find_usage(usage_id):
    return find(db.paid_usage, usage_id)


def account_of_warehouse(warehouse):
    return find_account(warehouse["account_id"])


def account_of_contract(contract):
    return find_account(contract["account_id"])


def child_warehouses(account_id):
    return [w for w in db.warehouses if w["account_id"] == account_id]


def child_contracts(account_id):
    return [c for c in db.contracts if c["account_id"] == account_id]


def child_monitors(account_id):
    return [m for m in db.monitors if m["account_id"] == account_id]


def child_sessions(warehouse_id):
    return [s for s in db.sessions if s["warehouse_id"] == warehouse_id]


def child_drawdowns(contract_id):
    return [d for d in db.drawdowns if d["contract_id"] == contract_id]


def child_storage(account_id):
    return [r for r in db.storage_records if r["account_id"] == account_id]


def child_shares(account_id):
    return [s for s in db.shares if s["provider_account_id"] == account_id]


def child_usage_events(share_id):
    return [e for e in db.share_usage_events if e["share_id"] == share_id]


def child_listings(share_id):
    return [l for l in db.listings if l["share_id"] == share_id]


def child_paid_usage(listing_id):
    return [p for p in db.paid_usage if p["listing_id"] == listing_id]


def child_replications(account_id):
    return [r for r in db.replications if r["account_id"] == account_id]


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] = entity["version"] + 1


# ---------------------------------------------------------------- LEDGER ----

def ledger_rows(account_id, buckets=CREDIT_BUCKETS, source_entity=None):
    rows = []
    for row in db.ledger:
        if row["account_id"] != account_id:
            continue
        if buckets is not None and row["bucket"] not in buckets:
            continue
        if source_entity is not None and row["source_entity"] != source_entity:
            continue
        rows.append(row)
    return rows


def ledger_sum_credits(account_id):
    return r6(sum((row["amount_credits"] for row in ledger_rows(account_id, CREDIT_BUCKETS)),
                  Decimal("0")))


def ledger_sum_storage_dollars(account_id):
    return r2(sum((row["amount_usd"] for row in ledger_rows(account_id, STORAGE_BUCKETS)),
                  Decimal("0")))


def ledger_sum_dollars(account_id):
    return r2(sum((row["amount_usd"] for row in ledger_rows(account_id, DOLLAR_BUCKETS)),
                  Decimal("0")))


def ledger_bucket_totals(account_id):
    totals = {}
    for bucket in ALL_BUCKETS:
        rows = ledger_rows(account_id, (bucket,))
        totals[bucket] = {
            "amount_credits": out_num(r6(sum((r["amount_credits"] for r in rows), Decimal("0")))),
            "amount_usd": out_num(r2(sum((r["amount_usd"] for r in rows), Decimal("0")))),
        }
    return totals


def ledger_totals_sum(account_id):
    totals = {"amount_credits": Decimal("0"), "amount_usd": Decimal("0")}
    for row in ledger_rows(account_id, None):
        totals["amount_credits"] += row["amount_credits"]
        totals["amount_usd"] += row["amount_usd"]
    return totals


def ledger_totals_posted_at_or_before(account_id, instant):
    totals = {"amount_credits": Decimal("0"), "amount_usd": Decimal("0")}
    for row in ledger_rows(account_id, None):
        if instant is not None and row["posted_at"] > instant:
            continue
        totals["amount_credits"] += row["amount_credits"]
        totals["amount_usd"] += row["amount_usd"]
    return totals


def ledger_totals_posted_after(account_id, instant):
    totals = {"amount_credits": Decimal("0"), "amount_usd": Decimal("0")}
    for row in ledger_rows(account_id, None):
        if instant is not None and row["posted_at"] <= instant:
            continue
        totals["amount_credits"] += row["amount_credits"]
        totals["amount_usd"] += row["amount_usd"]
    return totals


def ledger_window_credits(account_id, after, through):
    total = Decimal("0")
    for row in db.ledger:
        if row["account_id"] != account_id:
            continue
        if row["bucket"] not in CREDIT_BUCKETS:
            continue
        if after is not None and not row["posted_at"] > after:
            continue
        if through is not None and not row["posted_at"] <= through:
            continue
        total += row["amount_credits"]
    return r6(total)


# ------------------------------------------------------------ LEDGERPOST ----

def post_ledger(account_id, bucket, source_entity, source_entity_id,
                amount_credits=Decimal("0"), amount_usd=Decimal("0")):
    """Append a ledger row, reconcile the account, then run the monitor sweep."""
    row = {
        "id": new_id(),
        "account_id": account_id,
        "bucket": bucket,
        "source_entity": source_entity,
        "source_entity_id": source_entity_id,
        "amount_credits": amount_credits,
        "amount_usd": amount_usd,
        "posted_at": now(),
        "created_at": now(),
    }
    db.ledger.append(row)
    account = find_account(account_id)
    if account is not None:
        reconcile_account(account)
        monitor_sweep(account)
    return row


def reconcile_account(account):
    account["posted_consumption_credits_reconciled"] = ledger_sum_credits(account["id"])
    account["posted_storage_dollars_reconciled"] = ledger_sum_storage_dollars(account["id"])


# --------------------------------------------------------------- POSTURE ----

def derive_posture(account):
    monitors = child_monitors(account["id"])
    if any(m["monitor_state"] == "SUSPENDED" for m in monitors):
        posture = "DRAINING"
    # PRD §2.4: "otherwise, if the account's maximum `used_pct` across its
    # monitors is at least 50.0, the account is `RESTRICTED`" — the derivation
    # has only the three conditions stated there.
    elif max_used_pct(account["id"]) >= Decimal("50.0"):
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    account["account_state"] = posture
    if posture == "DRAINING":
        # PRD §2.4 / §2.11: reaching DRAINING moves every RUNNING warehouse of
        # the account to DRAINING as a distinct consequence. Warehouses already
        # DRAINING are swept too so a queued session still abandons into
        # RESUMING (PRD §3.3) rather than staying OPEN behind the gate.
        for warehouse in child_warehouses(account["id"]):
            if warehouse["status"] in ("RUNNING", "DRAINING"):
                drain_warehouse(warehouse)
    return posture


def complete_drains():
    """system event: drain complete — a DRAINING warehouse with no queued work
    settles into SUSPENDED, keeping cluster_count at 0."""
    for warehouse in db.warehouses:
        if warehouse["status"] == "DRAINING" and warehouse["multi_cluster_queued_queries"] == 0:
            warehouse["status"] = "SUSPENDED"
            warehouse["cluster_count"] = 0
            touch(warehouse)


def monitor_sweep(account):
    """Recompute every monitor of the account, then re-derive the posture."""
    complete_drains()
    for monitor in child_monitors(account["id"]):
        evaluate_monitor(monitor)
    for monitor in child_monitors(account["id"]):
        if monitor["monitor_state"] == "SUSPENDED":
            derive_posture(account)
            return
    derive_posture(account)


def evaluate_monitor(monitor):
    consumed = ledger_window_credits(monitor["account_id"], monitor["last_reset_at"], now())
    monitor["interval_consumption_credits"] = consumed
    quota = monitor["credit_quota"]
    pct = r6(consumed / quota * Decimal("100")) if quota > 0 else Decimal("0")
    monitor["used_pct"] = pct
    state = monitor["monitor_state"]
    if consumed < Decimal("0"):
        return
    if state == "SUSPENDED":
        return
    if pct >= Decimal("100.0"):
        if monitor["action"] in ("SUSPEND", "SUSPEND_IMMEDIATE"):
            if monitor["action"] == "SUSPEND" and state == "OK":
                monitor["monitor_state"] = "NOTIFY_SENT"
            monitor["monitor_state"] = "SUSPENDED"
        elif state == "OK":
            monitor["monitor_state"] = "NOTIFY_SENT"
    elif pct >= Decimal("50.0"):
        if state == "OK":
            monitor["monitor_state"] = "NOTIFY_SENT"


def immediate_suspend_monitor(account_id):
    for monitor in child_monitors(account_id):
        if monitor["monitor_state"] == "SUSPENDED" and \
                monitor["action"] == "SUSPEND_IMMEDIATE":
            return monitor
    return None


def account_of_session(session):
    warehouse = find_warehouse(session["warehouse_id"])
    return warehouse, account_of_warehouse(warehouse)


# --------------------------------------------------------- SESSIONBILL ----

def meter_session(session, warehouse):
    size = session["size"]
    clusters = session["clusters"]
    elapsed = session["elapsed_seconds"]
    factor = Decimal(SIZE_FACTORS[size])
    raw_credits = factor * Decimal(clusters) * Decimal(elapsed) / SECONDS_PER_HOUR
    if session["state"] == "RESUMING":
        billed_seconds = 0
    else:
        billed_seconds = max(elapsed, warehouse["auto_suspend_seconds"])
    metered = r6(raw_credits)
    billed = r6(factor * Decimal(clusters) * Decimal(billed_seconds) / SECONDS_PER_HOUR)
    return metered, billed, billed_seconds


# ------------------------------------------------------- CONTRACTSEG ----

def segment_drawdown(contract, drawdown):
    """Waterfall: BASE then ROLLOVER then OVERAGE.  Returns (base, rollover,
    overage_credits, overage_usd, outcome)."""
    drawdownable = contract["base_credits"] + contract["rolled_over_credits"]
    committed = contract["drawn_credits"] + drawdown["amount_credits"]
    overage_credits = max(Decimal("0"), committed - drawdownable)
    base_portion = min(drawdown["amount_credits"],
                       max(Decimal("0"), contract["base_credits"] - contract["base_consumed_credits"]))
    rollover_portion = drawdown["amount_credits"] - base_portion - overage_credits
    if overage_credits > 0:
        outcome = "OVERAGE"
    elif rollover_portion > 0:
        outcome = "ROLLOVER"
    else:
        outcome = "BASE"
    overage_usd = r2(overage_credits * contract["overage_rate_per_credit"])
    if outcome in ("BASE", "ROLLOVER"):
        overage_usd = Decimal("0.00")
    return base_portion, rollover_portion, overage_credits, overage_usd, outcome


def recompute_contract(contract):
    remaining = contract["base_credits"] + contract["rolled_over_credits"] - contract["drawn_credits"]
    contract["remaining_credits"] = r6(max(Decimal("0"), remaining))
    return contract["remaining_credits"]


def refresh_contract_posture(contract):
    if contract["status"] == "ACTIVE" and contract["remaining_credits"] <= Decimal("0"):
        contract["status"] = "EXHAUSTED"
    elif contract["status"] == "EXHAUSTED" and contract["remaining_credits"] > Decimal("0"):
        contract["status"] = "ACTIVE"


def recompute_drawdown_count(contract):
    contract["drawdown_count"] = len(child_drawdowns(contract["id"]))


def reconcile_drawdowns(contract):
    """drawn_credits is the sum of ACTIVE drawdown rows bound to the contract."""
    total = Decimal("0")
    base_total = Decimal("0")
    for drawdown in child_drawdowns(contract["id"]):
        if drawdown["status"] != "ACTIVE":
            continue
        total += drawdown["amount_credits"]
        base_total += drawdown["base_portion"]
    contract["drawn_credits"] = r6(total)
    contract["base_consumed_credits"] = r6(base_total)


# ------------------------------------------------------ DRAIN AND SWEEP ----

def drain_warehouse(warehouse):
    """RUNNING -> DRAINING: close open sessions and post their consumption."""
    if warehouse["status"] != "RUNNING":
        return
    has_suspended = any(m["monitor_state"] == "SUSPENDED"
                        for m in child_monitors(warehouse["account_id"]))
    for session in child_sessions(warehouse["id"]):
        if session["state"] != "OPEN":
            continue
        account = find_account(warehouse["account_id"])
        if has_suspended and warehouse["multi_cluster_queued_queries"] > 0:
            session["state"] = "RESUMING"
            session["ended_at"] = now()
            session["elapsed_seconds"] = max(
                0, int((now() - session["started_at"]).total_seconds()))
            session["metered_credits"] = Decimal("0")
            session["billed_credits"] = Decimal("0")
            session["billed_seconds"] = 0
            session["state"] = "CLOSED"
            touch(session)
            continue
        close_session_row(session, warehouse, account)
    warehouse["status"] = "DRAINING"
    warehouse["cluster_count"] = 0
    touch(warehouse)


def close_session_row(session, warehouse, account):
    """Sweep-close an OPEN session (OPEN -> CLOSING -> CLOSED)."""
    session["state"] = "CLOSING"
    session["ended_at"] = now()
    session["elapsed_seconds"] = max(
        0, int((now() - session["started_at"]).total_seconds()))
    metered, billed, billed_seconds = meter_session(session, warehouse)
    session["metered_credits"] = metered
    session["billed_credits"] = billed
    session["billed_seconds"] = billed_seconds
    session["state"] = "CLOSED"
    touch(session)
    post_ledger(account["id"], "CONSUMPTION", "WarehouseSession", session["id"],
                amount_credits=billed)


def sweep_suspend(warehouse):
    """Deliberate suspend: close sessions, then SUSPENDED with cluster_count 0."""
    account = find_account(warehouse["account_id"])
    for session in child_sessions(warehouse["id"]):
        if session["state"] != "OPEN":
            continue
        close_session_row(session, warehouse, account)
    warehouse["status"] = "SUSPENDED"
    warehouse["cluster_count"] = 0
    touch(warehouse)
    reconcile_account(account)
    monitor_sweep(account)


# --------------------------------------------------------------- ATTR ----

def attribution_charged_credits(event):
    if event["row_count"] > 0:
        return event["credits_consumed"]
    return Decimal("0")


def recompute_share(share):
    events = child_usage_events(share["id"])
    share["consumer_query_count"] = len(events)
    share["consumer_credits"] = r6(sum((attribution_charged_credits(e) for e in events),
                                       Decimal("0")))
    return share


# ------------------------------------------------- provider_payout_split ----

def recompute_listing_payout(listing):
    settled = [p for p in child_paid_usage(listing["id"]) if p["usage_state"] == "SETTLED"]
    gross = r6(sum((p["credits_used"] * p["price_per_credit"] for p in settled),
                   Decimal("0")))
    if listing["pricing_model"] == "FREE":
        commission_pct = Decimal("0")
    else:
        commission_pct = PLATFORM_COMMISSION_PCT
    platform_fee = r2(gross * commission_pct)
    provider_payout = r2(gross) - platform_fee
    listing["gross_credit_volume"] = gross
    listing["platform_fee_usd"] = platform_fee
    listing["provider_payout_usd"] = provider_payout
    return gross, provider_payout, platform_fee


# ------------------------------------------------- warehouse_cluster_scaling ----

def active_contract_with_credits(account_id):
    for contract in child_contracts(account_id):
        if contract["status"] == "ACTIVE" and contract["remaining_credits"] > 0:
            return contract
    return None


def scale_clusters(warehouse, account, requested_clusters, queued_queries):
    """Demand -> clamp -> budget shrink -> budget floor."""
    demand = -(-queued_queries // QUERIES_PER_CLUSTER)
    demand = max(warehouse["clusters_min"], min(demand, warehouse["clusters_max"]))
    candidate = min(requested_clusters, demand)
    candidate = max(candidate, warehouse["clusters_min"])
    # PRD §3.2: only when the account has NO active contract with credits left
    # are the budget steps skipped and cluster_count left to demand and clamping
    # alone ("19 queued queries ... yields 3 clusters"). A positive remaining
    # balance feeds the projection shrink below.
    contract = active_contract_with_credits(account["id"])
    if contract is None:
        return candidate
    factor = Decimal(SIZE_FACTORS[warehouse["size"]])
    while True:
        projected = factor * Decimal(candidate) * PROJECTED_SECONDS / SECONDS_PER_HOUR
        if projected <= contract["remaining_credits"] or candidate <= warehouse["clusters_min"]:
            break
        candidate -= 1
    return candidate


# ---------------------------------------------------- storage_billable_volume ----

def billable_storage_tb(active_tb, time_travel_tb, fail_safe_tb):
    return r6(active_tb + time_travel_tb + fail_safe_tb)


def storage_per_component(active_tb, time_travel_tb, time_travel_days,
                          fail_safe_tb, fail_safe_days):
    """PER_COMPONENT order: round each component to 2 decimals, then sum."""
    active = r2(active_tb * BILLABLE_RATE["ACTIVE"] * DAYS_IN_MONTH)
    time_travel = r2(time_travel_tb * BILLABLE_RATE["TIME_TRAVEL"] * DAYS_IN_MONTH) \
        if time_travel_days >= 1 else r2(0)
    fail_safe = r2(fail_safe_tb * BILLABLE_RATE["FAIL_SAFE"] * DAYS_IN_MONTH) \
        if fail_safe_days >= 1 else r2(0)
    return {"ACTIVE": active, "TIME_TRAVEL": time_travel, "FAIL_SAFE": fail_safe}


def storage_cost_per_component(active_tb, time_travel_tb, time_travel_days,
                               fail_safe_tb, fail_safe_days):
    parts = storage_per_component(active_tb, time_travel_tb, time_travel_days,
                                  fail_safe_tb, fail_safe_days)
    return r2(parts["ACTIVE"] + parts["TIME_TRAVEL"] + parts["FAIL_SAFE"]), parts


def storage_cost_sum_then_round(active_tb, time_travel_tb, time_travel_days,
                                fail_safe_tb, fail_safe_days):
    """SUM_THEN_ROUND: round once over the summed raw products."""
    active = active_tb * BILLABLE_RATE["ACTIVE"] * DAYS_IN_MONTH
    time_travel = (time_travel_tb * BILLABLE_RATE["TIME_TRAVEL"] * DAYS_IN_MONTH) \
        if time_travel_days >= 1 else Decimal("0")
    fail_safe = (fail_safe_tb * BILLABLE_RATE["FAIL_SAFE"] * DAYS_IN_MONTH) \
        if fail_safe_days >= 1 else Decimal("0")
    return r2(active + time_travel + fail_safe)


# ---------------------------------------------------- replication_transfer_cost ----

def replication_transfer_cost(config):
    return r2(config["replicated_tb"] * COST_PER_TB
              * REGION_FACTOR[config["target_region"]]
              * CLOUD_FACTOR[config["target_cloud"]])


# ---------------------------------------------------- contract_rollover_utilization ----

def rollover_at_expiry(contract):
    """AT_EXPIRY: basis is rollover_cap_credits."""
    contract["term_end_remaining_credits"] = r6(contract["remaining_credits"])
    cap = contract["rollover_cap_credits"]
    pct = r6(cap / cap * Decimal("100")) if cap > 0 else Decimal("0")
    return r6(min(pct * cap / Decimal("100"), cap))


# ---------------------------------------------------- account_posture_derivation ----

def max_used_pct(account_id):
    monitors = child_monitors(account_id)
    if not monitors:
        return Decimal("0")
    return max(m["used_pct"] for m in monitors)


def has_active_drawdown(account_id):
    for drawdown in db.drawdowns:
        if drawdown["status"] != "ACTIVE":
            continue
        contract = find_contract(drawdown["contract_id"])
        if contract is not None and contract["account_id"] == account_id:
            return True
    return False
