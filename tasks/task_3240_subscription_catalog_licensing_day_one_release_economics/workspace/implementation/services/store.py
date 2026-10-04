"""Derived-state engine: entitlement resolution, the two cascades, clock sweep."""
from datetime import timedelta
from decimal import Decimal

from clock import add_months, term_months
from db import db
from services import calc


def access_channels(tier):
    channels = []
    if tier["console_access"]:
        channels.append("CONSOLE")
    if tier["pc_access"]:
        channels.append("PC")
    if tier["cloud_access"]:
        channels.append("CLOUD")
    if tier["online_play_bundle"]:
        channels.append("ONLINE_PLAY")
    return channels


def tier_for(subscription):
    return db.tiers.get(subscription["tier_code"])


def entitlements_of_subscription(subscription_id):
    return [r for r in db.entitlements.values() if r["subscription_id"] == subscription_id]


def entitlements_naming_entry(entry_id):
    return [r for r in db.entitlements.values() if r.get("entry_id") == entry_id]


def refresh_subscriber_impact(entry):
    """Count the live entitlements resolving to this entry (PRD 3.3 / 3.4).

    PRD 2.8 fixes the entitlement's grain at the (subscription, title, region)
    triple — "at most one entitlement row may exist for a given (subscription,
    title, region) triple" — so a single subscription resolves at most one row
    per entry, which is what keeps this count stable across the cascade hops.
    """
    live = [r for r in db.entitlements.values()
            if r.get("entry_id") == entry["id"] and r["status"] in ("ACTIVE", "GRACE")]
    entry["subscriber_impact_count"] = len(live)
    db.touch(entry)
    return entry


def refresh_subscriber_impact_many(entries):
    for entry in entries:
        refresh_subscriber_impact(entry)


def refresh_tier_counts():
    for tier in db.tiers.values():
        count = len([r for r in db.subscriptions.values()
                     if r["tier_code"] == tier["tier_code"]
                     and r["lifecycle_status"] in ("ACTIVE", "GRACE")])
        if tier["current_subscriber_count"] != count:
            tier["current_subscriber_count"] = count
            db.touch(tier)


def refresh_region_capacities():
    for region in db.regions.values():
        before = dict(region)
        calc.refresh_capacity(region, db.clock)
        if any(before.get(k) != region.get(k) for k in
               ("capacity_required_slots", "capacity_usable_slots",
                "capacity_deficit_slots", "capacity_utilization_pct",
                "capacity_status")):
            pass


def refresh_title_status(title):
    live = [r for r in db.entries.values()
            if r["title_id"] == title["id"] and r["status"] in ("ADDED", "REMOVING")]
    if live:
        if title["status"] == "DRAFT":
            title["status"] = "RELEASED"
            db.touch(title)
    else:
        if title["status"] == "RELEASED":
            title["status"] = "RETIRED"
            db.touch(title)
    calc.refresh_title_score(title)
    return title


# ---------------------------------------------------------------------------
# selector policy: pick the winning entry for a (subscription, title, region)
# ---------------------------------------------------------------------------
def select_entry(subscription, title_id, region_code, now):
    candidates = [r for r in db.entries.values()
                  if r["title_id"] == title_id
                  and r["region_code"] == region_code
                  and subscription["tier_code"] in r["tiers"]
                  and calc.playable(r, region_code, now)]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["actual_add_date"], r["_seq"]))
    return candidates[0]


def resolve_entitlement(subscription, title_id, region_code, now):
    """Create or refresh the single entitlement for the triple (PRD 3.3)."""
    tier = tier_for(subscription)
    if tier is None:
        return None
    existing = None
    for row in db.entitlements.values():
        if (row["subscription_id"] == subscription["id"]
                and row["title_id"] == title_id
                and row["region_code"] == region_code):
            existing = row
            break
    winner = select_entry(subscription, title_id, region_code, now)
    # PRD 3.3: "a subscription whose tier grant is suspended because its billing
    # has failed resolves to `GRACE` instead" — the suspension is the lifecycle
    # dimension's GRACE, which is the dimension the entitlement tracks (2.8).
    grace = subscription["lifecycle_status"] == "GRACE"
    if existing is None:
        row = db.new_row()
        row.update({
            "subscription_id": subscription["id"],
            "title_id": title_id,
            "region_code": region_code,
            "entry_id": winner["id"] if winner else None,
            "access_channels": access_channels(tier),
            "status": "GRACE" if grace else "ACTIVE",
            "retained_until": None,
        })
        db.entitlements[row["id"]] = row
        return row
    if winner is not None and existing.get("entry_id") != winner["id"]:
        existing["entry_id"] = winner["id"]
    existing["access_channels"] = access_channels(tier)
    if existing["status"] in ("ACTIVE", "GRACE") or existing["status"] == "REVOKED":
        if existing["status"] != "REVOKED":
            existing["status"] = "REVOKED" if subscription["lifecycle_status"] == "CANCELLED" else (
                "GRACE" if grace else "ACTIVE")
    db.touch(existing)
    return existing


def publish_entitlements(entry, now):
    """Resolve one entitlement per eligible subscription (PRD 3.3)."""
    title = db.titles[entry["title_id"]]
    created = []
    for subscription in db.subscriptions.values():
        if subscription["tier_code"] not in entry["tiers"]:
            continue
        subscriber = db.subscribers.get(subscription["subscriber_id"])
        if subscriber is None or subscriber["home_region_code"] != entry["region_code"]:
            continue
        if subscription["lifecycle_status"] == "CANCELLED":
            continue
        row = resolve_entitlement(subscription, entry["title_id"],
                                  entry["region_code"], now)
        if row is not None:
            created.append(row)
    return created


# ---------------------------------------------------------------------------
# CASCADE C1 hop 2 + hop 3
# ---------------------------------------------------------------------------
def retention_holds(entry, now):
    if entry["release_class"] == "BACK_CATALOG":
        return True
    tier_days = {}
    for tier in db.tiers.values():
        tier_days[tier["tier_code"]] = tier["discount_retention_days"]
    for ent in entitlements_naming_entry(entry["id"]):
        if ent["status"] not in ("ACTIVE", "GRACE"):
            continue
        subscription = db.subscriptions.get(ent["subscription_id"])
        if subscription is None:
            continue
        days = tier_days.get(subscription["tier_code"], 0)
        limit = entry["removal_date"] + timedelta(days=days) - timedelta(seconds=1)
        if now <= limit:
            return True
    return False


def delist_entry(entry, now):
    if entry["status"] == "DELISTED":
        return []
    entry["status"] = "DELISTED"
    db.touch(entry)
    return [entry]


def sweep_delisted(delisted, now):
    """Hop 3: revoke entitlements unless the retention clause holds."""
    for entry in delisted:
        for ent in entitlements_naming_entry(entry["id"]):
            if ent["status"] not in ("ACTIVE", "GRACE"):
                continue
            if entry["release_class"] == "BACK_CATALOG":
                continue
            subscription = db.subscriptions.get(ent["subscription_id"])
            days = 0
            if subscription is not None:
                tier = tier_for(subscription)
                if tier is not None:
                    days = tier["discount_retention_days"]
            retained_until = entry["removal_date"] + timedelta(days=days)
            if now <= retained_until - timedelta(seconds=1):
                ent["status"] = "ACTIVE"
                ent["retained_until"] = retained_until
            else:
                ent["status"] = "REVOKED"
            db.touch(ent)
    refresh_subscriber_impact_many(delisted)


def cascade_retire(entry, now):
    """CASCADE C1: hop 1 (self) + hop 2 (NA fan-out) + hop 3 (sweep)."""
    delisted = delist_entry(entry, now)
    fan = [r for r in db.entries.values()
           if r["title_id"] == entry["title_id"]
           and r["region_code"] == "NA"
           and r["status"] in ("ADDED", "REMOVING")]
    for row in fan:
        delisted.extend(delist_entry(row, now))
    seen = {}
    for row in delisted:
        seen[row["id"]] = row
    ordered = sorted(seen.values(), key=lambda r: r["_seq"])
    sweep_delisted(ordered, now)
    title = db.titles.get(entry["title_id"])
    if title is not None:
        refresh_title_status(title)
    refresh_region_capacities()
    return ordered


def cascade_deal_completion(deal, now):
    """Clock-driven termination: every entry of the deal is delisted."""
    delisted = []
    for row in sorted(db.entries.values(), key=lambda r: r["_seq"]):
        if row["deal_id"] != deal["id"]:
            continue
        if row["status"] not in ("ADDED", "REMOVING"):
            continue
        delisted.extend(delist_entry(row, now))
    sweep_delisted(delisted, now)
    titles = set(row["title_id"] for row in delisted)
    for title_id in titles:
        title = db.titles.get(title_id)
        if title is not None:
            refresh_title_status(title)
    return delisted


def cascade_cancel(subscription, now):
    """CASCADE C2: entitlements revoked with no retention clause."""
    named = []
    for ent in entitlements_of_subscription(subscription["id"]):
        if ent["status"] == "REVOKED":
            continue
        ent["status"] = "REVOKED"
        db.touch(ent)
        if ent.get("entry_id"):
            named.append(ent["entry_id"])
    touched = []
    for entry_id in set(named):
        entry = db.entries.get(entry_id)
        if entry is not None:
            refresh_subscriber_impact(entry)
            touched.append(entry)
    refresh_tier_counts()
    return touched


# ---------------------------------------------------------------------------
# logical clock sweep (PRD 2.12)
# ---------------------------------------------------------------------------
def _maintenance_transitions(now, log):
    for row in sorted(db.maintenances.values(), key=lambda r: r["_seq"]):
        if row["status"] == "SCHEDULED" and now >= row["maintenance_start"]:
            row["status"] = "ACTIVE"
            db.touch(row)
            log.append(("maintenance", row["id"]))
        if row["status"] == "ACTIVE" and now >= row["maintenance_end"]:
            row["status"] = "COMPLETED"
            db.touch(row)
            log.append(("maintenance", row["id"]))


def _deal_transitions(now, log):
    for deal in sorted(db.deals.values(), key=lambda r: r["_seq"]):
        if deal["status"] == "SIGNED" and now >= deal["term_start_date"]:
            deal["status"] = "LIVE"
            db.touch(deal)
            log.append(("deal-live", deal["id"]))
        if deal["status"] == "LIVE":
            removal = deal.get("removal_effective_date")
            if removal is None:
                removal = deal["term_end_date"] - timedelta(days=2)
                deal["removal_effective_date"] = removal
            if now >= removal:
                deal["status"] = "EXPIRING"
                db.touch(deal)
                log.append(("deal-expiring", deal["id"]))
                for row in db.entries.values():
                    if row["deal_id"] == deal["id"] and row["status"] == "ADDED":
                        row["status"] = "REMOVING"
                        db.touch(row)
        if deal["status"] == "EXPIRING" and now >= deal["term_end_date"]:
            deal["status"] = "COMPLETED"
            db.touch(deal)
            log.append(("deal-completed", deal["id"]))
            cascade_deal_completion(deal, now)
    calc.refresh_all_publisher_rollups()


def _billing_transitions(now, log):
    for subscription in sorted(db.subscriptions.values(), key=lambda r: r["_seq"]):
        if subscription["billing_period"] != "MONTHLY":
            continue
        if subscription["lifecycle_status"] == "CANCELLED":
            continue
        created = subscription["created_at_dt"]
        nxt = subscription.get("_next_renewal")
        if nxt is None:
            nxt = add_months(created, 1)
        while nxt <= now:
            _fail_charge(subscription, log, nxt)
            nxt = add_months(nxt, 1)
        subscription["_next_renewal"] = nxt


def _fail_charge(subscription, log, _instant):
    """A charge attempt at a renewal instant fails.

    A subscription that has never paid (billing_status PENDING, no outstanding
    month) has its first charge attempt fail, which sets unpaid_months to one
    rather than incrementing it; every later attempt increments the count.
    """
    if subscription["billing_status"] == "PENDING":
        subscription["unpaid_months"] = 1
    else:
        subscription["unpaid_months"] += 1
    subscription["billing_status"] = "FAILED"
    if subscription["lifecycle_status"] == "ACTIVE":
        subscription["lifecycle_status"] = "GRACE"
    db.touch(subscription)
    for ent in entitlements_of_subscription(subscription["id"]):
        if ent["status"] == "ACTIVE":
            ent["status"] = "GRACE"
            db.touch(ent)
    log.append(("charge-failed", subscription["id"]))
    refresh_tier_counts()


def _engagement_rollover(now, previous):
    if previous is None:
        return
    from clock import month_start
    if month_start(previous) == month_start(now):
        return
    for subscription in db.subscriptions.values():
        avg = calc.monthly_engaged_hours_avg(subscription["id"], now)
        subscription["monthly_engaged_hours_avg"] = float(avg)
        subscription["engagement_score"] = float(calc.engagement_score(subscription["id"], now))
        db.touch(subscription)


def advance_clock(now):
    """Advance the logical clock, applying every clock-driven transition."""
    previous = db.clock
    if now > previous:
        db.clock = now
    effective = db.clock
    log = []
    _maintenance_transitions(effective, log)
    _deal_transitions(effective, log)
    _billing_transitions(effective, log)
    _engagement_rollover(db.clock, previous)
    refresh_region_capacities()
    return log
