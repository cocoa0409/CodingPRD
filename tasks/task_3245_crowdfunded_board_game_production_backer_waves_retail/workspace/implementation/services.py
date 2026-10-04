"""Calculation services — every rule from SCAFFOLD §1.3."""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from clock import now_dt

TIER1_THRESHOLD = 1000000
TIER2_THRESHOLD = 10000000
TIER1_RATE = Decimal("0.08")
TIER2_RATE = Decimal("0.06")
TIER3_RATE = Decimal("0.05")

PAYMENT_PCT = Decimal("0.029")
PAYMENT_FLAT = 30

DUTY_RATES = {
    "NA": Decimal("0.040"),
    "EU": Decimal("0.065"),
    "APAC": Decimal("0.052"),
    "ROW": Decimal("0.080"),
}

FREIGHT_BASE = {"NA": 350000, "EU": 420000, "APAC": 280000, "ROW": 510000}

RETAIL_DELAY_DAYS = 90
SPARE_PCT = Decimal("0.05")
REGIONS = ["NA", "EU", "APAC", "ROW"]


def round_half_up(value):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pledge pricing
# ---------------------------------------------------------------------------

def compute_pledge_total(level, is_late_pledge, add_on_lines, catalog_by_sku):
    """pledge_total_with_late_premium: per-line round_half_up then sum."""
    premium = Decimal(str(level.get("late_pledge_premium_pct") or 0)) if is_late_pledge else Decimal("0")
    factor = Decimal("1") + premium
    level_line = round_half_up(Decimal(int(level["price_cents"])) * factor)
    total = level_line
    for line in add_on_lines:
        entry = catalog_by_sku[line["sku"]]
        line_cents = round_half_up(
            Decimal(int(entry["price_cents"])) * int(line["quantity"]) * factor
        )
        total += line_cents
    return total


# ---------------------------------------------------------------------------
# Campaign aggregates
# ---------------------------------------------------------------------------

def recompute_campaign_aggregates(campaign):
    """campaign_net_payable pinned order: gross -> platform -> payment -> customs -> net."""
    pledges = [p for p in db.pledges.values() if p["campaign_id"] == campaign["id"]]
    charged = [p for p in pledges if p["charge_status"] == "CHARGED"]
    gross = sum(int(p["pledge_total_cents"]) for p in charged)
    campaign["gross_charged_cents"] = gross
    campaign["total_backers_charged"] = len(charged)

    if gross < TIER1_THRESHOLD:
        rate = TIER1_RATE
    elif gross < TIER2_THRESHOLD:
        rate = TIER2_RATE
    else:
        rate = TIER3_RATE
    campaign["platform_fee_cents"] = round_half_up(Decimal(gross) * rate)

    payment_fee = 0
    for p in charged:
        payment_fee += round_half_up(Decimal(int(p["pledge_total_cents"])) * PAYMENT_PCT + PAYMENT_FLAT)
    campaign["payment_fee_cents"] = payment_fee

    duty = 0
    for s in db.freight_shipments.values():
        run = db.production_runs.get(s["production_run_id"])
        if run and run["campaign_id"] == campaign["id"] and s["status"] in ("CLEARED", "DELIVERED"):
            duty += int(s.get("customs_duty_cents") or 0)
    campaign["customs_duty_paid_cents"] = duty

    campaign["net_payable_cents"] = gross - campaign["platform_fee_cents"] - payment_fee - duty


# ---------------------------------------------------------------------------
# Stretch goals
# ---------------------------------------------------------------------------

def evaluate_stretch_goals(campaign):
    """stretch_goal_unlock: ordered pass; goals later in the pass see updated gross."""
    goals = campaign.get("stretch_goals") or []
    levels = campaign.get("pledge_levels") or []
    catalog_by_sku = {a["sku"]: a for a in (campaign.get("add_on_catalog") or [])}
    locked = [g for g in goals if g.get("status") == "LOCKED"]
    locked.sort(key=lambda g: (int(g["threshold_cents"]), str(g["goal_id"])))
    now = now_dt()
    changed = False
    for goal in locked:
        if int(campaign["gross_charged_cents"]) >= int(goal["threshold_cents"]):
            goal["status"] = "UNLOCKED"
            goal["unlocked_at"] = now
            changed = True
            target = None
            for lv in levels:
                if lv["name"] == goal["target_pledge_level_name"]:
                    target = lv
                    break
            if target is not None:
                sku = goal["bonus_component_sku"]
                if sku not in target.setdefault("contents", []):
                    target["contents"].append(sku)
                # reprice pledges on this level
                for p in db.pledges.values():
                    if p["campaign_id"] != campaign["id"]:
                        continue
                    if p["pledge_level_name"] != target["name"]:
                        continue
                    if p["charge_status"] not in ("PENDING", "CHARGED"):
                        continue
                    old_total = int(p["pledge_total_cents"])
                    new_total = compute_pledge_total(
                        target, p["is_late_pledge"], p["add_on_lines"], catalog_by_sku
                    )
                    p["pledge_total_cents"] = new_total
                    if p["charge_status"] == "CHARGED":
                        campaign["gross_charged_cents"] = int(campaign["gross_charged_cents"]) + (new_total - old_total)
    return changed


# ---------------------------------------------------------------------------
# Manufacturing tier pricing
# ---------------------------------------------------------------------------

def tier_price(tier_breaks, units):
    """unit_price of the LAST tier whose min_units <= units; first tier as floor."""
    price = None
    for tb in tier_breaks:
        if int(tb["min_units"]) <= units:
            price = int(tb["unit_price_cents"])
    if price is None:
        price = int(tier_breaks[0]["unit_price_cents"]) if tier_breaks else 0
    return price


def signed_print_commitments(campaign_id):
    total = 0
    for la in db.localizations.values():
        if la["campaign_id"] == campaign_id and la["status"] == "SIGNED":
            total += int(la["print_commitment_units"])
    return total


def quote_units_provisional(campaign_id):
    count = 0
    for p in db.pledges.values():
        if p["campaign_id"] == campaign_id and p["charge_status"] in ("PENDING", "CHARGED"):
            count += 1
    return count + signed_print_commitments(campaign_id)


def quote_units_final(campaign_id):
    count = 0
    for p in db.pledges.values():
        if p["campaign_id"] == campaign_id and p["charge_status"] == "CHARGED":
            count += 1
    reserved = 0
    for a in db.allocations.values():
        if a["campaign_id"] == campaign_id and a["status"] == "RESERVED":
            reserved += int(a["units_reserved"])
    return count + signed_print_commitments(campaign_id) + reserved


def recompute_quote_provisional(quote):
    units = quote_units_provisional(quote["campaign_id"])
    quote["provisional_units"] = units
    quote["provisional_unit_price_cents"] = tier_price(quote["tier_breaks"], units)


# ---------------------------------------------------------------------------
# Customs duty
# ---------------------------------------------------------------------------

def compute_customs_duty(shipment):
    """customs_duty_calculation: dual variant, lower wins, tie -> DECLARED_VALUE."""
    run = db.production_runs.get(shipment["production_run_id"])
    quote = db.quotes.get(run["quote_id"]) if run else None
    rate = DUTY_RATES[shipment["region_code"]]

    declared_duty = round_half_up(Decimal(int(shipment["declared_value_cents"])) * rate)

    transaction_duty = None
    if run and quote and quote.get("final_unit_price_cents") is not None:
        total_containers = sum(
            int(s["container_count"])
            for s in db.freight_shipments.values()
            if s["production_run_id"] == run["id"]
        )
        if total_containers > 0:
            share = Decimal(int(shipment["container_count"])) / Decimal(total_containers)
            dutiable = Decimal(int(run["planned_units"] or 0)) * Decimal(int(quote["final_unit_price_cents"])) * share
            transaction_duty = round_half_up(dutiable * rate)

    if transaction_duty is None or declared_duty <= transaction_duty:
        return declared_duty, "DECLARED_VALUE"
    return transaction_duty, "TRANSACTION_VALUE"


# ---------------------------------------------------------------------------
# Spares
# ---------------------------------------------------------------------------

def compute_spares(planned_units):
    """Five percent of planned_units floored to whole units (PRD: 'the
    spare-units rule rounds down (floor) to whole units'), then divided
    equally across the four regions (integer division; the remainder stays
    in the general pool)."""
    total_spares = int(Decimal(str(planned_units)) * SPARE_PCT)  # floor
    per_region = total_spares // 4
    return {r: per_region for r in REGIONS}


def initial_spares_total(campaign_id):
    """Initial spare pool across the campaign's most recently LOCKED run."""
    run = most_recent_locked_run(campaign_id)
    if not run:
        return 0, 0
    spares = run.get("spare_units_by_region") or {}
    initial = sum(int(v) for v in spares.values())
    # "remaining" = initial minus shipped debits; shipped requests reduce the map directly
    return initial, initial


def most_recent_locked_run(campaign_id):
    """Most recently created ProductionRun for the campaign that reached LOCKED."""
    candidates = [
        r for r in db.production_runs.values()
        if r["campaign_id"] == campaign_id
        and r.get("_locked_at") is not None
        and r["status"] in ("LOCKED", "IN_PRODUCTION", "SHIPPED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["_locked_at"], r.get("_seq", 0)))
    return candidates[-1]


def available_spares(campaign_id, region):
    run = most_recent_locked_run(campaign_id)
    if not run:
        return 0
    spares = run.get("spare_units_by_region") or {}
    # current map value IS the remaining (ship decrements the map)
    return int(spares.get(region, 0))


def initial_spares_for_region(campaign_id, region):
    run = most_recent_locked_run(campaign_id)
    if not run:
        return 0
    return int((run.get("_initial_spare_units_by_region") or {}).get(region, 0))


# ---------------------------------------------------------------------------
# Freight consolidation preview
# ---------------------------------------------------------------------------

def freight_preview_cost(region, container_count, total_weight_kg, total_volume_m3):
    dim_weight = max(Decimal(str(total_weight_kg)), Decimal(str(total_volume_m3)) * Decimal("250"))
    base = int(container_count) * FREIGHT_BASE[region]
    weight_surcharge = max(Decimal("0"), dim_weight - Decimal("22000")) * Decimal("8")
    weight_surcharge = int(weight_surcharge)  # integer cents; kg*8 exact
    volume_surcharge = 0
    if Decimal(str(total_volume_m3)) > Decimal("67"):
        volume_surcharge = int((Decimal(str(total_volume_m3)) - Decimal("67")) * Decimal("4000"))
    return base + weight_surcharge + volume_surcharge


# ---------------------------------------------------------------------------
# Reprint risk
# ---------------------------------------------------------------------------

def compute_inventory_risk(campaign, demand_signal_cents):
    gross = max(int(campaign.get("gross_charged_cents") or 0), 1)
    sell_through = Decimal(int(demand_signal_cents)) / Decimal(gross)

    run = most_recent_locked_run(campaign["id"])
    initial_map = (run or {}).get("_initial_spare_units_by_region") or {}
    current_map = (run or {}).get("spare_units_by_region") or {}
    initial_total = sum(int(v) for v in initial_map.values()) if initial_map else 0
    remaining_total = sum(int(v) for v in current_map.values()) if current_map else 0
    spare_depletion = Decimal("1") - (Decimal(remaining_total) / Decimal(max(initial_total, 1)))

    demand_velocity = Decimal(int(demand_signal_cents)) / Decimal("90")
    velocity_term = min(demand_velocity / Decimal("100000"), Decimal("1"))

    raw = Decimal("100") * (
        Decimal("0.5") * (Decimal("1") - sell_through)
        + Decimal("0.3") * spare_depletion
        + Decimal("0.2") * velocity_term
    )
    score = round_half_up(raw)
    return max(0, min(100, score))
