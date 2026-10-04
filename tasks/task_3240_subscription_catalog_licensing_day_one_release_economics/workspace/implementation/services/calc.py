"""The eleven calculation rules of the PRD (section 3.6-3.10).

Every rounding happens exactly where the PRD says it happens, and a value that
has already been rounded is never rounded again inside the same procedure.
"""
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP

from clock import month_start, next_month_start, term_months, whole_days
from db import db

D = Decimal
CENT = D("0.01")
HYBRID_ENGAGEMENT_SHARE = D("0.25")
ENGAGEMENT_SCORE_CEILING = D("100.00")
RETENTION_DISCOUNT_BONUS = D("0.05")
MAX_MEMBER_DISCOUNT_PCT = D("0.40")
UNIT_SALES_CANNIBALIZATION_FRACTION = D("0.30")
HOURS_PER_LOST_SALE = D("1.25")
NET_NEW_SUBSCRIBER_FRACTION = D("0.60")
TIER_UPLIFT_RATE = D("0.05")
TIER_UPLIFT_CAP_CENTS = D("250000")
DAY_ONE_APPROVE_THRESHOLD_CENTS = D("0")
HOLD_THRESHOLD_CENTS = D("-50000")
PARITY_MULTIPLIER_THRESHOLD = D("1.50")
PARITY_BLEND_FACTOR = D("0.90")
REGIONAL_MULTIPLIER_MIN = D("0.50")
SLOTS_PER_INDEX_CENT = D("0.5")
LAUNCH_SPIKE_WINDOW_DAYS = 14
LAUNCH_SPIKE_MULTIPLIER_EXCESS = D("0.40")
OVERHEAD_SLOTS_PER_REGION = D("200")
SLOTS_PER_CEILING_UNIT = D("30")
RETENTION_WEIGHT = D("0.60")
CONVERSION_WEIGHT = D("0.25")
ENGAGEMENT_WEIGHT = D("0.15")
ENGAGEMENT_HOURS_PER_INDEX_POINT = D("2.0")
TIER_WEIGHTS = {"ESSENTIAL": D("1.00"), "PREMIUM": D("1.50"), "ULTIMATE": D("2.00")}
MIN_NOTICE_DAYS = {"DAY_ONE": 14, "CATALOG_ADD": 7, "BACK_CATALOG": 0}
REMOVAL_REVERT_CUTOFF_DAYS = 3


def dec(value):
    if isinstance(value, Decimal):
        return value
    return D(str(value))


def r2(value):
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def r4(value):
    return dec(value).quantize(D("0.0001"), rounding=ROUND_HALF_UP)


def f2(value):
    return float(r2(value))


def region_multiplier(region):
    mult = dec(region["price_multiplier"])
    if mult > PARITY_MULTIPLIER_THRESHOLD:
        mult = r4(mult * PARITY_BLEND_FACTOR)
    return max(mult, REGIONAL_MULTIPLIER_MIN)


def regional_list_price_cents(title, region):
    return r2(dec(title["list_price_cents"]) * dec(region["price_multiplier"]))


def regional_monthly_price_cents(tier, region):
    return r2(dec(tier["monthly_price_cents"]) * region_multiplier(region))


# ---------------------------------------------------------------------------
# licensing_compensation
# ---------------------------------------------------------------------------
def _term_month_index(instant, start, months):
    if instant < start:
        return None
    idx = (instant.year * 12 + instant.month) - (start.year * 12 + start.month) + 1
    if idx < 1 or idx > months:
        return None
    return idx


def _monthly_hours(deal):
    months = term_months(deal["term_start_date"], deal["term_end_date"])
    if months < 1:
        months = 1
    buckets = [D("0")] * months
    for row in db.events.values():
        if row["title_id"] != deal["title_id"]:
            continue
        created = row["created_at_dt"]
        if created < deal["term_start_date"] or created >= deal["term_end_date"]:
            continue
        idx = _term_month_index(created, deal["term_start_date"], months)
        if idx is None:
            continue
        buckets[idx - 1] += dec(row["normalized_hours"])
    return months, buckets


def compensation_components(deal):
    """Return (months, capped_monthly[], fixed_component, engagement_component, floor)."""
    months, hours = _monthly_hours(deal)
    rate = dec(deal["engagement_rate_cents_per_hour"])
    cap = dec(deal["monthly_engagement_cap_cents"])
    capped = []
    for hours_m in hours:
        raw = hours_m * rate
        capped.append(min(raw, cap))
    fixed_component = dec(deal["monthly_fixed_fee_cents"]) * months
    engagement_component = sum(capped, D("0"))
    floor = dec(deal["guaranteed_compensation_cents"]) * months
    return months, capped, fixed_component, engagement_component, floor


def payable_compensation_cents(deal, view="LEDGER"):
    """licensing_compensation, ledger view (base) or publisher statement view."""
    months, capped, fixed_component, engagement_component, floor = compensation_components(deal)
    model = deal["compensation_model"]
    if view == "STATEMENT" and model == "HYBRID":
        shared = sum((component * HYBRID_ENGAGEMENT_SHARE for component in capped), D("0"))
        total = max(fixed_component + r2(shared), floor)
        return f2(r2(total))
    if model == "FIXED":
        total = fixed_component
    elif model == "ENGAGEMENT":
        total = engagement_component
    else:
        share = engagement_component * HYBRID_ENGAGEMENT_SHARE
        total = max(fixed_component + share, floor)
    return f2(r2(total))


def compensation_floor_cents(deal):
    months, _capped, fixed_component, engagement_component, floor = compensation_components(deal)
    model = deal["compensation_model"]
    if model == "FIXED":
        return float(fixed_component)
    if model == "ENGAGEMENT":
        return 0.0
    return float(floor)


# ---------------------------------------------------------------------------
# engagement_score
# ---------------------------------------------------------------------------
def engagement_window(now):
    return month_start(now), next_month_start(now)


def monthly_engaged_hours_avg(subscription_id, now):
    start, end = engagement_window(now)
    total = D("0")
    count = 0
    for row in db.events.values():
        if row["subscription_id"] != subscription_id:
            continue
        created = row["created_at_dt"]
        if start <= created < end:
            total += dec(row["normalized_hours"])
            count += 1
    if count == 0:
        return D("0")
    return total / D(count)


def engagement_score(subscription_id, now):
    avg = monthly_engaged_hours_avg(subscription_id, now)
    return min(ENGAGEMENT_SCORE_CEILING, r2(avg))


def engagement_score_export(subscription_id, now):
    """The analyst export variant: 7-place half-even, then 2-place half-up."""
    avg = monthly_engaged_hours_avg(subscription_id, now)
    quantised = avg.quantize(D("0.0000001"), rounding=ROUND_HALF_EVEN)
    return min(ENGAGEMENT_SCORE_CEILING, quantised.quantize(CENT, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# catalog_removal_notice
# ---------------------------------------------------------------------------
def removal_notice_days(announced_add_date, removal_date):
    return whole_days(announced_add_date, removal_date)


def minimum_notice_days(release_class):
    return MIN_NOTICE_DAYS[release_class]


def revert_cutoff(removal_date):
    from datetime import timedelta
    return removal_date - timedelta(days=REMOVAL_REVERT_CUTOFF_DAYS)


def retention_until(entry, tier):
    from datetime import timedelta
    days = tier["discount_retention_days"] if tier else 0
    return entry["removal_date"] + timedelta(days=days)


# ---------------------------------------------------------------------------
# member_purchase_discount
# ---------------------------------------------------------------------------
def purchase_figures(title, region, tier, entry, subscriber, quantity):
    list_price = regional_list_price_cents(title, region)
    bonus = RETENTION_DISCOUNT_BONUS if entry["release_class"] == "BACK_CATALOG" else D("0")
    applied = dec(tier["member_discount_pct"]) + bonus
    if applied > MAX_MEMBER_DISCOUNT_PCT:
        applied = MAX_MEMBER_DISCOUNT_PCT
    discount_amount = r2(list_price * applied)
    subtotal = list_price - discount_amount
    wallet_offset = min(dec(subscriber["wallet_credit_cents"]), subtotal)
    total_charged = subtotal - wallet_offset
    unit_credit = total_charged * D(quantity)
    return {
        "list_price_cents_per_unit": float(list_price),
        "discount_pct_applied": float(r2(applied)),
        "wallet_applied_cents": int(wallet_offset),
        "total_charged_cents": float(total_charged),
        "unit_sales_credit_cents": float(unit_credit),
    }


# ---------------------------------------------------------------------------
# day_one_cannibalization
# ---------------------------------------------------------------------------
def provisional_cannibalized_cents(title, region, projected_unit_sales_units):
    gross = D(projected_unit_sales_units) * regional_list_price_cents(title, region)
    return r2(gross * UNIT_SALES_CANNIBALIZATION_FRACTION)


def chronological_cannibalized_cents(title_id, region_code):
    rows = [r for r in db.purchases.values()
            if r["title_id"] == title_id and r["region_code"] == region_code
            and r["status"] == "COMPLETED"]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    running = sum((dec(r["total_charged_cents"]) for r in rows), D("0"))
    return r2(running * UNIT_SALES_CANNIBALIZATION_FRACTION)


# ---------------------------------------------------------------------------
# day_one_subscription_value
# ---------------------------------------------------------------------------
def subscription_value_cents(deal, title, projection):
    months = term_months(deal["term_start_date"], deal["term_end_date"])
    if months < 1:
        months = 1
    hours_per_subscriber = dec(title["unit_sales_30d"]) * HOURS_PER_LOST_SALE
    raw_hours = hours_per_subscriber * D(projection["launch_subscriber_count"])
    theoretical = raw_hours * dec(deal["engagement_rate_cents_per_hour"])
    cap_total = dec(deal["monthly_engagement_cap_cents"]) * months
    capped = min(theoretical, cap_total)
    net_new = r2(capped * NET_NEW_SUBSCRIBER_FRACTION)
    uplift = r2(capped * TIER_UPLIFT_RATE * D(projection["tier_step_count"]))
    uplift = min(uplift, TIER_UPLIFT_CAP_CENTS)
    return float(net_new + uplift), float(capped)


def decision_ladder(net_value_cents, title, release_class):
    net = dec(net_value_cents)
    if (net >= DAY_ONE_APPROVE_THRESHOLD_CENTS
            and bool(title["day_one_eligible"])
            and release_class == "DAY_ONE"):
        return "APPROVE_DAY_ONE"
    if net >= HOLD_THRESHOLD_CENTS:
        return "HOLD_FOR_CATALOG"
    return "REJECT_DAY_ONE"


# ---------------------------------------------------------------------------
# cloud_capacity_allocation
# ---------------------------------------------------------------------------
def active_entries(region_code, now):
    out = []
    for row in db.entries.values():
        if row["region_code"] != region_code:
            continue
        if row["status"] not in ("ADDED", "REMOVING"):
            continue
        actual = row.get("actual_add_date")
        if actual is None:
            continue
        if now >= actual and now < row["removal_date"]:
            out.append(row)
    return out


def capacity_figures(region, now):
    from datetime import timedelta
    active = active_entries(region["region_code"], now)
    base = D("0")
    spike = D("0")
    for row in active:
        contribution = dec(row["popularity_index_cents"]) * SLOTS_PER_INDEX_CENT
        base += contribution
        if now < row["actual_add_date"] + timedelta(days=LAUNCH_SPIKE_WINDOW_DAYS):
            spike += contribution * LAUNCH_SPIKE_MULTIPLIER_EXCESS
    required = base + spike + OVERHEAD_SLOTS_PER_REGION
    usable = dec(region["availability_ceiling_titles"]) * SLOTS_PER_CEILING_UNIT
    for window in db.maintenances.values():
        if window["region_code"] != region["region_code"]:
            continue
        if window["maintenance_start"] <= now < window["maintenance_end"]:
            usable = r2(usable * (D("1") - dec(window["capacity_reduction_pct"])))
    deficit = required - usable
    if usable == 0:
        utilization = D("0.00")
    else:
        utilization = r2(required / usable * D("100"))
    status = "OVER_CAPACITY" if required > usable else "WITHIN_CAPACITY"
    return {
        "capacity_required_slots": float(required),
        "capacity_usable_slots": float(usable),
        "capacity_deficit_slots": float(deficit),
        "capacity_utilization_pct": float(utilization),
        "capacity_status": status,
    }


def refresh_capacity(region, now):
    figures = capacity_figures(region, now)
    region.update(figures)
    return region


# ---------------------------------------------------------------------------
# weighted_engagement_score
# ---------------------------------------------------------------------------
def weighted_engagement_score(title_id):
    total = D("0")
    for row in db.entries.values():
        if row["title_id"] != title_id:
            continue
        if row["status"] not in ("ADDED", "REMOVING"):
            continue
        weight = max(TIER_WEIGHTS[t] for t in row["tiers"])
        total += dec(row["popularity_index_cents"]) / D("100") * weight
    return float(r2(total))


def refresh_title_score(title):
    title["weighted_engagement_score"] = weighted_engagement_score(title["id"])
    db.touch(title)
    return title


# ---------------------------------------------------------------------------
# publisher_deal_rollup
# ---------------------------------------------------------------------------
DEAL_COUNT_STATUSES = ("SIGNED", "LIVE", "EXPIRING")
COST_STATUSES = ("SIGNED", "LIVE", "EXPIRING", "COMPLETED")


def refresh_publisher_rollup(publisher):
    count = 0
    total = D("0")
    for row in db.deals.values():
        if row["publisher_id"] != publisher["id"]:
            continue
        if row["status"] in DEAL_COUNT_STATUSES:
            count += 1
        if row["status"] in COST_STATUSES:
            total += dec(row["compensation_floor_cents"])
    publisher["deal_count"] = count
    publisher["lifetime_licensing_cost_cents"] = float(r2(total))
    db.touch(publisher)
    return publisher


def refresh_all_publisher_rollups():
    for publisher in db.publishers.values():
        refresh_publisher_rollup(publisher)


# ---------------------------------------------------------------------------
# conversion_retention_index
# ---------------------------------------------------------------------------
def tier_analytics(tier, now):
    rows = [r for r in db.subscriptions.values() if r["tier_code"] == tier["tier_code"]]
    count = len(rows)
    subscribers = [s for s in db.subscribers.values()]
    engagement_total = D("0")
    for row in rows:
        engagement_total += dec(row.get("monthly_engaged_hours_avg", 0))
    if count:
        avg = engagement_total / D(count)
    else:
        avg = D("0")
    normalized = min(D("100.00"), r2(avg / ENGAGEMENT_HOURS_PER_INDEX_POINT * D("100")))
    denominator = max(D("1"), D(tier["current_subscriber_count"]))
    retained = D(len([r for r in rows if r["lifecycle_status"] in ("ACTIVE", "GRACE")]))
    # A purchase names a subscriber, not a subscription; a subscription counts
    # toward conversion when its owner has at least one purchase row, whatever
    # that row's status (PRD 3.10). Reversed purchases still count.
    buyers = set(p["subscriber_id"] for p in db.purchases.values())
    purchasing = D(len([r for r in rows if r["subscriber_id"] in buyers]))
    retention_pct = r2(D("100") * retained / denominator)
    conversion_pct = r2(D("100") * purchasing / denominator)
    index = r2(RETENTION_WEIGHT * retention_pct
               + CONVERSION_WEIGHT * conversion_pct
               + ENGAGEMENT_WEIGHT * normalized)
    return {
        "tier_code": tier["tier_code"],
        "current_subscriber_count": tier["current_subscriber_count"],
        "retention_pct": float(retention_pct),
        "conversion_pct": float(conversion_pct),
        "normalized_engagement": float(normalized),
        "conversion_retention_index": float(index),
    }


# ---------------------------------------------------------------------------
# catalog_rotation_availability
# ---------------------------------------------------------------------------
def playable(entry, region_code, now):
    if entry["status"] not in ("ADDED", "REMOVING"):
        return False
    if entry["region_code"] != region_code:
        return False
    actual = entry.get("actual_add_date")
    if actual is None:
        return False
    return actual <= now < entry["removal_date"]


def readable_entries(subscription, now):
    """Union of the three sets named in PRD 3.4."""
    out = {}
    for row in db.entries.values():
        if (row["region_code"] == subscription["region_code"]
                and subscription["tier_code"] in row["tiers"]
                and playable(row, subscription["region_code"], now)):
            out[row["id"]] = row
        elif row["status"] == "DELISTED" and row["release_class"] == "BACK_CATALOG":
            out[row["id"]] = row
    for ent in db.entitlements.values():
        if ent["subscription_id"] != subscription["id"]:
            continue
        if ent["status"] != "ACTIVE":
            continue
        until = ent.get("retained_until")
        if until is None or until > now:
            continue
        entry = db.entries.get(ent.get("entry_id"))
        if entry is not None:
            out[entry["id"]] = entry
    return list(out.values())
