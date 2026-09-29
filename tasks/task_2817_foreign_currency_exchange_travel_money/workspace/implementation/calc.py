"""The sixteen pinned calculations plus the cascade machinery they drive."""
from datetime import timedelta

from core import (
    BUYBACK_FEE_BPS,
    BUYBACK_FEE_MIN_CENTS,
    COMMISSION_MIN_CENTS,
    COMMISSION_PREMIUM_UPLIFT_BPS,
    COMMISSION_TIER_1_BPS,
    COMMISSION_TIER_1_CEILING_CENTS,
    COMMISSION_TIER_2_BPS,
    COMMISSION_TIER_2_CEILING_CENTS,
    COMMISSION_TIER_3_BPS,
    DISPERSION_COMPONENT_MAX,
    DISPERSION_POINTS,
    EXOTIC_PLAN_CAP_MINOR_UNITS,
    FREQUENCY_COMPONENT_MAX,
    MIN_ROUTE_GAP_MINUTES,
    NEAR_THRESHOLD_FLOOR_CENTS,
    NEAR_THRESHOLD_POINTS,
    PLAN_VAULT_SHARE_BPS,
    REPORT_THRESHOLD_CENTS,
    RESTRICTED_EXPORT_MULTIPLE,
    RISK_TIER_ELEVATED_MIN,
    RISK_TIER_HIGH_MIN,
    ROLLING_WINDOW_DAYS,
    S,
    VAULT_FROZEN_MIN_BPS,
    VAULT_RESTRICTED_MIN_BPS,
    VAULT_TARGET_BPS,
    VOLUME_COMPONENT_MAX,
    D,
    clock,
    fail,
    fdiv,
    fmt_dt,
    month_start,
    need_currency,
    new_row,
    now_str,
    rhu,
    sort_created_asc,
    store,
    touch,
    utc_date,
)

# ==========================================================================
# 1. wholesale_rate_selection
# ==========================================================================
def wholesale_mid(currency_code):
    candidates = [
        w
        for w in S["WholesaleRate"].values()
        if w["currency_code"] == currency_code and D(w["effective_at"]) <= clock()
    ]
    if not candidates:
        fail("ERR_WHOLESALE_RATE_NOT_FOUND")
    candidates.sort(key=lambda w: (D(w["effective_at"]), w["created_at"], w["_seq"]), reverse=True)
    return candidates[0]["mid_rate_micros"]


# ==========================================================================
# 2. rate_card_derivation
# ==========================================================================
def derive_card_rates(mid, buy_spread_bps, sell_spread_bps):
    sell_rate = rhu(mid * (10000 - sell_spread_bps), 10000)
    buy_rate = rhu(mid * (10000 + buy_spread_bps), 10000)
    return buy_rate, sell_rate


# ==========================================================================
# 3. transaction_fx_gross
# ==========================================================================
def fx_gross(lines):
    return sum(l["denomination_minor_units"] * l["note_count"] for l in lines)


# ==========================================================================
# 4. transaction_usd_conversion  (pinned: round each line, then sum)
# ==========================================================================
def usd_conversion(lines, applied_rate_micros):
    total = 0
    for line in sorted(lines, key=lambda l: l["denomination_minor_units"]):
        line_fx = line["denomination_minor_units"] * line["note_count"]
        total += rhu(line_fx * 1000000, applied_rate_micros)
    return total


# ==========================================================================
# 5. transaction_commission_and_total  (pinned five-step order)
# ==========================================================================
def commission_and_total(gross, basis, commission_schedule_code, direction):
    if basis < COMMISSION_TIER_1_CEILING_CENTS:
        rate_bps = COMMISSION_TIER_1_BPS
    elif basis < COMMISSION_TIER_2_CEILING_CENTS:
        rate_bps = COMMISSION_TIER_2_BPS
    else:
        rate_bps = COMMISSION_TIER_3_BPS
    if commission_schedule_code == "PREMIUM":
        rate_bps += COMMISSION_PREMIUM_UPLIFT_BPS
    commission = max(COMMISSION_MIN_CENTS, rhu(gross * rate_bps, 10000))
    if direction == "SELL_FX_TO_CUSTOMER":
        total = gross + commission
    else:
        total = gross - commission
    return commission, total


def same_day_settled_basis(transaction, gross):
    """SETTLEMENT_FINAL tier basis: this gross plus the customer's other same-day,
    same-branch settled grosses."""
    day = utc_date(D(transaction["settled_at"]))
    basis = gross
    for other in S["ExchangeTransaction"].values():
        if other["id"] == transaction["id"]:
            continue
        if other["customer_id"] != transaction["customer_id"]:
            continue
        if other["branch_id"] != transaction["branch_id"]:
            continue
        if other["settlement_status"] != "SETTLED":
            continue
        settled_at = D(other.get("settled_at"))
        if settled_at is None or utc_date(settled_at) != day:
            continue
        basis += other["settled_usd_gross_cents"] or 0
    return basis


# ==========================================================================
# 6. corridor_inventory_target
# ==========================================================================
def corridor_targets(plan, corridor, branch):
    out = []
    for line in sorted(plan["target_lines"], key=lambda l: l["currency_code"]):
        profile = need_currency(line["currency_code"])
        mid = wholesale_mid(line["currency_code"])
        raw = fdiv(
            line["baseline_daily_minor_units"] * plan["season_days"] * corridor["demand_index_bps"],
            10000,
        )
        if profile["currency_class"] == "MAJOR":
            class_cap = raw
        elif profile["currency_class"] == "EXOTIC":
            class_cap = min(raw, EXOTIC_PLAN_CAP_MINOR_UNITS)
        else:
            class_cap = min(raw, profile["export_limit_minor_units"] * RESTRICTED_EXPORT_MULTIPLE)
        vault_cap = fdiv(
            branch["vault_limit_usd_cents"] * PLAN_VAULT_SHARE_BPS * mid, 10000 * 1000000
        )
        largest = max(profile["standard_denominations"])
        bounded = max(largest, min(class_cap, vault_cap))
        target = rhu(bounded, largest) * largest
        out.append({"currency_code": line["currency_code"], "target_minor_units": target})
    return out


# ==========================================================================
# 7. position_usd_equivalent  (cascade hops 1-2)
# ==========================================================================
def normalise_mix(position):
    position["denomination_mix"].sort(key=lambda e: e["denomination_minor_units"])


def recompute_position(position):
    normalise_mix(position)
    mix = position["denomination_mix"]
    position["total_minor_units"] = sum(
        e["denomination_minor_units"] * e["available_note_count"] for e in mix
    )
    position["quarantined_minor_units"] = sum(
        e["denomination_minor_units"] * e["quarantined_note_count"] for e in mix
    )
    mid = wholesale_mid(position["currency_code"])
    position["usd_equivalent_cents"] = rhu(position["total_minor_units"] * 1000000, mid)
    touch(position)
    return position


def mix_entry(position, denomination):
    for entry in position["denomination_mix"]:
        if entry["denomination_minor_units"] == denomination:
            return entry
    return None


def ensure_mix_entry(position, denomination):
    entry = mix_entry(position, denomination)
    if entry is None:
        entry = {
            "denomination_minor_units": denomination,
            "available_note_count": 0,
            "quarantined_note_count": 0,
            "written_off_note_count": 0,
        }
        position["denomination_mix"].append(entry)
        normalise_mix(position)
    return entry


def branch_position(branch_id, currency_code):
    for position in S["InventoryPosition"].values():
        if position["branch_id"] == branch_id and position["currency_code"] == currency_code:
            return position
    return None


# ==========================================================================
# 8. branch_vault_utilization_and_posture  (cascade hops 3-5)
# ==========================================================================
def branch_vault_total(branch):
    return sum(
        p["usd_equivalent_cents"]
        for p in S["InventoryPosition"].values()
        if p["branch_id"] == branch["id"] and p["status"] == "OPEN"
    )


def derive_posture(bps):
    if bps > VAULT_FROZEN_MIN_BPS:
        return "FROZEN"
    if bps >= VAULT_RESTRICTED_MIN_BPS:
        return "RESTRICTED"
    return "OPEN"


def recompute_branch(branch):
    before = (
        branch["vault_usd_equivalent_cents"],
        branch["vault_utilization_bps"],
        branch["posture"],
        branch["repatriation_pending"],
    )
    total = branch_vault_total(branch)
    branch["vault_usd_equivalent_cents"] = total
    branch["vault_utilization_bps"] = rhu(10000 * total, branch["vault_limit_usd_cents"])
    old_posture = branch["posture"]
    new_posture = derive_posture(branch["vault_utilization_bps"])
    branch["posture"] = new_posture
    if new_posture != old_posture and new_posture in ("RESTRICTED", "FROZEN") and old_posture in (
        "OPEN",
        "RESTRICTED",
    ):
        maybe_raise_repatriation(branch)
    after = (
        branch["vault_usd_equivalent_cents"],
        branch["vault_utilization_bps"],
        branch["posture"],
        branch["repatriation_pending"],
    )
    if after != before:
        touch(branch)
    return branch


def projected_vault_after(branch, position, added_minor_units):
    """Post-credit vault valuation, without mutating anything."""
    mid = wholesale_mid(position["currency_code"])
    new_total = position["total_minor_units"] + added_minor_units
    new_usd = rhu(new_total * 1000000, mid)
    total = 0
    for other in S["InventoryPosition"].values():
        if other["branch_id"] != branch["id"] or other["status"] != "OPEN":
            continue
        total += new_usd if other["id"] == position["id"] else other["usd_equivalent_cents"]
    return total


def inventory_cascade(position, branch):
    """The canonical four-hop cascade: mix (already adjusted) -> position -> branch -> posture."""
    recompute_position(position)
    recompute_branch(branch)


# ==========================================================================
# 9. repatriation_surplus_manifest
# ==========================================================================
def maybe_raise_repatriation(branch):
    if branch["repatriation_pending"]:
        return None
    candidates = [
        p
        for p in S["InventoryPosition"].values()
        if p["branch_id"] == branch["id"] and p["status"] == "OPEN" and p["total_minor_units"] > 0
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (-p["usd_equivalent_cents"], p["created_at"], p["_seq"]))
    position = candidates[0]
    target_usd_cents = branch["vault_usd_equivalent_cents"] - rhu(
        branch["vault_limit_usd_cents"] * VAULT_TARGET_BPS, 10000
    )
    mid = wholesale_mid(position["currency_code"])
    surplus_fx = fdiv(target_usd_cents * mid, 1000000)
    remaining = surplus_fx
    manifest = []
    for entry in sorted(
        position["denomination_mix"], key=lambda e: e["denomination_minor_units"], reverse=True
    ):
        denom = entry["denomination_minor_units"]
        if remaining <= 0:
            continue
        take = min(entry["available_note_count"], fdiv(remaining, denom))
        if take > 0:
            manifest.append({"denomination_minor_units": denom, "note_count": take})
            remaining -= take * denom
    manifest.sort(key=lambda e: e["denomination_minor_units"])
    shipment = create_shipment(
        branch, position["currency_code"], "REPATRIATION", manifest, auto_generated=True
    )
    branch["repatriation_pending"] = True
    return shipment


# ==========================================================================
# 10-11. customer_structuring_aggregates + customer_structuring_risk_score
# ==========================================================================
def recompute_customer_surveillance(customer):
    """Returns (old_tier, new_tier)."""
    now = clock()
    settled = [
        t
        for t in S["ExchangeTransaction"].values()
        if t["customer_id"] == customer["id"] and t["settlement_status"] == "SETTLED"
    ]
    rolling_start = now - timedelta(days=ROLLING_WINDOW_DAYS)
    rolling = [
        t
        for t in settled
        if D(t.get("settled_at")) is not None and rolling_start <= D(t["settled_at"]) <= now
    ]
    customer["rolling_30d_settled_usd_cents"] = sum(
        t["settled_usd_gross_cents"] or 0 for t in rolling
    )
    customer["near_threshold_txn_count"] = len(
        [
            t
            for t in rolling
            if NEAR_THRESHOLD_FLOOR_CENTS
            <= (t["settled_usd_gross_cents"] or 0)
            <= REPORT_THRESHOLD_CENTS - 1
        ]
    )
    customer["distinct_branch_count"] = len({t["branch_id"] for t in rolling})

    cal_start = month_start(now)
    calendar = [
        t
        for t in settled
        if D(t.get("settled_at")) is not None and cal_start <= D(t["settled_at"]) <= now
    ]
    customer["calendar_month_settled_usd_cents"] = sum(
        t["settled_usd_gross_cents"] or 0 for t in calendar
    )

    volume = min(
        VOLUME_COMPONENT_MAX,
        fdiv(VOLUME_COMPONENT_MAX * customer["rolling_30d_settled_usd_cents"], REPORT_THRESHOLD_CENTS),
    )
    frequency = min(
        FREQUENCY_COMPONENT_MAX, NEAR_THRESHOLD_POINTS * customer["near_threshold_txn_count"]
    )
    dispersion = max(
        0,
        min(DISPERSION_COMPONENT_MAX, DISPERSION_POINTS * (customer["distinct_branch_count"] - 1)),
    )
    score = volume + frequency + dispersion
    customer["structuring_risk_score"] = score
    old_tier = customer["structuring_risk_tier"]
    if score >= RISK_TIER_HIGH_MIN:
        new_tier = "HIGH"
    elif score >= RISK_TIER_ELEVATED_MIN:
        new_tier = "ELEVATED"
    else:
        new_tier = "NORMAL"
    customer["structuring_risk_tier"] = new_tier
    return old_tier, new_tier


def calendar_month_window():
    now = clock()
    return fmt_dt(month_start(now)), fmt_dt(now)


def settled_count_in_window(customer_id, start_dt, end_dt):
    count = 0
    for t in S["ExchangeTransaction"].values():
        if t["customer_id"] != customer_id or t["settlement_status"] != "SETTLED":
            continue
        settled_at = D(t.get("settled_at"))
        if settled_at is None:
            continue
        if start_dt <= settled_at <= end_dt:
            count += 1
    return count


# ==========================================================================
# 12. buyback_contract_pricing
# ==========================================================================
def buyback_pricing(origin, card):
    locked_buy_rate = card["buy_rate_micros"]
    locked_fx = origin["fx_gross_minor_units"]
    fee = max(BUYBACK_FEE_MIN_CENTS, rhu((origin["settled_usd_gross_cents"] or 0) * BUYBACK_FEE_BPS, 10000))
    liability = rhu(locked_fx * 1000000, locked_buy_rate)
    return locked_buy_rate, locked_fx, fee, liability


# ==========================================================================
# 13. buyback_liability_reconciliation
# ==========================================================================
def reconcile_branch_liability(branch):
    total = 0
    for contract in S["BuybackContract"].values():
        if contract["branch_id"] != branch["id"]:
            continue
        if contract["status"] not in ("ISSUED", "PARTIALLY_REDEEMED"):
            continue
        total += rhu(
            contract["remaining_fx_minor_units"] * 1000000, contract["locked_buy_rate_micros"]
        )
    if branch["buyback_liability_usd_cents"] != total:
        branch["buyback_liability_usd_cents"] = total
        touch(branch)
    return total


# ==========================================================================
# 14. damaged_note_recovery  (pinned two-step rounding)
# ==========================================================================
def damaged_note_recovery(face_fx_minor_units, card, profile):
    usd_face_cents = rhu(face_fx_minor_units * 1000000, card["buy_rate_micros"])
    return rhu(usd_face_cents * profile["damaged_note_recovery_bps"], 10000)


# ==========================================================================
# 15. shipment_manifest_valuation
# ==========================================================================
def manifest_valuation(manifest, currency_code):
    minor = sum(e["denomination_minor_units"] * e["note_count"] for e in manifest)
    mid = wholesale_mid(currency_code)
    return minor, rhu(minor * 1000000, mid)


def create_shipment(branch, currency_code, direction, manifest, auto_generated):
    manifest = sorted(
        [
            {
                "denomination_minor_units": e["denomination_minor_units"],
                "note_count": e["note_count"],
            }
            for e in manifest
        ],
        key=lambda e: e["denomination_minor_units"],
    )
    minor, usd = manifest_valuation(manifest, currency_code)
    row = new_row("CashShipment")
    row["branch_id"] = branch["id"]
    row["armored_route_id"] = None
    row["currency_code"] = currency_code
    row["direction"] = direction
    row["manifest_denominations"] = manifest
    row["manifest_minor_units"] = minor
    row["manifest_usd_equivalent_cents"] = usd
    row["window_start"] = None
    row["window_end"] = None
    row["status"] = "REQUESTED"
    row["delivered_minor_units"] = None
    row["variance_minor_units"] = None
    row["exception_reason"] = None
    row["written_off_minor_units"] = None
    row["auto_generated"] = auto_generated
    return store(row)


# ==========================================================================
# 16. route_day_capacity_check (+ closed-window separation)
# ==========================================================================
def route_window_conflict(route_id, shipment_id, start_dt, end_dt):
    gap = timedelta(minutes=MIN_ROUTE_GAP_MINUTES)
    for other in S["CashShipment"].values():
        if other["id"] == shipment_id:
            continue
        if other["armored_route_id"] != route_id:
            continue
        if other["status"] not in ("SCHEDULED", "IN_TRANSIT"):
            continue
        other_start = D(other["window_start"])
        other_end = D(other["window_end"])
        if other_start is None or other_end is None:
            continue
        separated = start_dt >= other_end + gap or end_dt + gap <= other_start
        if not separated:
            return True
    return False


def route_day_capacity_exceeded(route, shipment, start_dt):
    day = utc_date(start_dt)
    booked = 0
    for other in S["CashShipment"].values():
        if other["id"] == shipment["id"]:
            continue
        if other["armored_route_id"] != route["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "IN_TRANSIT"):
            continue
        other_start = D(other["window_start"])
        if other_start is None or utc_date(other_start) != day:
            continue
        booked += other["manifest_usd_equivalent_cents"]
    return booked + shipment["manifest_usd_equivalent_cents"] > route["daily_capacity_usd_cents"]


# ==========================================================================
# Rate-card window helpers
# ==========================================================================
def card_covers(card, instant):
    effective_from = D(card["effective_from"])
    effective_to = D(card["effective_to"])
    if instant < effective_from:
        return False
    if effective_to is not None and instant >= effective_to:
        return False
    return True


def published_cards(branch_id, currency_code):
    return [
        c
        for c in S["RateCard"].values()
        if c["branch_id"] == branch_id
        and c["currency_code"] == currency_code
        and c["status"] == "PUBLISHED"
    ]


def effective_published_card(branch_id, currency_code, instant):
    for card in sort_created_asc(published_cards(branch_id, currency_code)):
        if card_covers(card, instant):
            return card
    return None


def require_effective_card(branch_id, currency_code, instant, check_published=True):
    """Rank 12: PUBLISHED existence first, then window coverage."""
    cards = published_cards(branch_id, currency_code)
    if check_published and not cards:
        fail("ERR_RATE_CARD_NOT_PUBLISHED")
    card = effective_published_card(branch_id, currency_code, instant)
    if card is None:
        fail("ERR_RATE_CARD_NOT_EFFECTIVE")
    return card


# ==========================================================================
# Compliance report factory (reports are never created by a client request)
# ==========================================================================
def create_report(
    customer_id,
    branch_id,
    report_type,
    window_start,
    window_end,
    aggregate_usd_cents,
    transaction_count,
    triggering_transaction_id=None,
    note_assessment_id=None,
):
    row = new_row("ComplianceReport")
    row["customer_id"] = customer_id
    row["branch_id"] = branch_id
    row["triggering_transaction_id"] = triggering_transaction_id
    row["note_assessment_id"] = note_assessment_id
    row["report_type"] = report_type
    row["window_start"] = window_start
    row["window_end"] = window_end
    row["aggregate_usd_cents"] = aggregate_usd_cents
    row["transaction_count"] = transaction_count
    row["status"] = "DRAFT"
    row["filing_reference"] = None
    row["filed_at"] = None
    row["amendment_count"] = 0
    return store(row)


def has_outstanding_structuring_report(customer_id):
    for report in S["ComplianceReport"].values():
        if (
            report["customer_id"] == customer_id
            and report["report_type"] == "STRUCTURING_SUSPICION"
            and report["status"] in ("DRAFT", "AMENDING")
        ):
            return True
    return False


def raise_structuring_report(customer, branch_id, triggering_transaction_id=None):
    """A HIGH-tier arrival raises one report; the report (not the settlement) sets the hold.

    PRD 3.6: `triggering_transaction_id` names the settlement that raised the report and
    is null only on a COUNTERFEIT_SEIZURE, so a settlement-driven STRUCTURING_SUSPICION
    carries the settlement that pushed the customer into the HIGH tier.
    """
    if has_outstanding_structuring_report(customer["id"]):
        return None
    window_start, window_end = calendar_month_window()
    count = settled_count_in_window(customer["id"], month_start(clock()), clock())
    report = create_report(
        customer["id"],
        branch_id,
        "STRUCTURING_SUSPICION",
        window_start,
        window_end,
        customer["calendar_month_settled_usd_cents"],
        count,
        triggering_transaction_id=triggering_transaction_id,
    )
    customer["compliance_hold_active"] = True
    return report
