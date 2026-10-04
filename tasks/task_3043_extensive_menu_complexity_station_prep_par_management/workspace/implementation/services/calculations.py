import math
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.common import rack_load, recompute_par_health

OPTIMISTIC_BUFFER_PCT = Decimal("0.05")
CONSERVATIVE_BUFFER_PCT = Decimal("0.15")
SERVICE_WINDOW_HOURS = 12
SLICES_PER_CAKE = 14
CAKE_UNIT_COST_CENTS = 2500
MODIFIER_MULT = Decimal("1.25")
PEAK_WAIT_THRESHOLD_MINUTES = 45
PEAK_LOAD_MULTIPLIER = Decimal("1.5")
LOAD_SCORE_CAP = Decimal("2.0")


def round4(value):
    """Round half-up to 4 decimal places, returned as float for JSON."""
    d = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(d)


def forecast_prep_quantity(prep_list, forecast, variant):
    """Compute prep list lines per the pinned algorithm. Returns (lines, total)."""
    # Aggregate raw quantities per prep item across the forecast's item_mix.
    raw = {}
    order = []
    for entry in forecast["item_mix"]:
        recipe = db.recipes.get(entry["recipe_id"])
        if recipe is None:
            continue
        expected_count = entry["expected_count"]
        for comp in recipe.get("components", []):
            pid = comp["prep_item_id"]
            if pid not in raw:
                raw[pid] = 0
                order.append(pid)
            raw[pid] += expected_count * comp["quantity_per_portion"]

    lines = []
    total = 0
    for pid in order:
        item = db.prep_items.get(pid)
        if item is None:
            continue
        raw_q = raw[pid]
        if raw_q == 0:
            continue
        mbs = item["min_batch_size"]
        raw_dec = Decimal(raw_q)
        mbs_dec = Decimal(mbs)
        if variant == "OPTIMISTIC":
            buffered = raw_dec * (1 + OPTIMISTIC_BUFFER_PCT)
            batch_count = math.ceil(buffered / mbs_dec)
            rounded = batch_count * mbs
            capped = False
        else:  # CONSERVATIVE
            buffered = raw_dec * (1 + CONSERVATIVE_BUFFER_PCT)
            uncapped_batches = math.ceil(buffered / mbs_dec)
            uncapped = uncapped_batches * mbs
            cover_factor = min(Decimal(1), Decimal(item["shelf_life_hours"]) / Decimal(SERVICE_WINDOW_HOURS))
            cap_batches = math.floor((raw_dec * cover_factor) / mbs_dec)
            cap = cap_batches * mbs
            rounded = min(uncapped, cap)
            capped = rounded < uncapped
            batch_count = rounded // mbs
        # buffered_quantity is raw * (1 + pct) exactly; integer when integral
        if buffered == buffered.to_integral_value():
            buffered_report = int(buffered)
        else:
            buffered_report = float(buffered)
        line = {
            "prep_item_id": pid,
            "station_type": item["station_type"],
            "raw_quantity": raw_q,
            "buffered_quantity": buffered_report,
            "batch_count": batch_count,
            "rounded_quantity": rounded,
            "capped_by_shelf_life": capped,
        }
        lines.append(line)
        total += rounded
    return lines, total


def compute_station_load_score(station, restaurant):
    base = Decimal(0)
    for t in db.service_tickets.values():
        if t["restaurant_id"] != station["restaurant_id"]:
            continue
        if t["fire_status"] not in ("FIRED", "READY"):
            continue
        for item in t["items"]:
            recipe = db.recipes.get(item["recipe_id"])
            if recipe is None:
                continue
            if recipe["station_type"] != station["station_type"]:
                continue
            complexity = len(recipe.get("components", []))
            mult = MODIFIER_MULT if len(item.get("modifications") or []) > 0 else Decimal("1.0")
            base += Decimal(complexity) * mult
    normalized = base / Decimal(station["rack_slot_capacity"])
    peak_mult = (
        PEAK_LOAD_MULTIPLIER
        if restaurant["current_waitlist_minutes"] >= PEAK_WAIT_THRESHOLD_MINUTES
        else Decimal("1.0")
    )
    score = normalized * peak_mult
    if score > LOAD_SCORE_CAP:
        score = LOAD_SCORE_CAP
    return round4(score)


def compute_overprep_penalty(station_id):
    wasted = 0
    for w in db.waste_entries.values():
        if w["station_id"] == station_id and w["reason"] in ("OVER_PREP", "EXPIRED"):
            wasted += w["quantity"]
    consumed = 0
    for b in db.prep_batches.values():
        if b["station_id"] == station_id:
            consumed += b["consumed_quantity"]
    denom = wasted + consumed
    if denom == 0:
        ratio = Decimal(0)
    else:
        ratio = Decimal(wasted) / Decimal(denom)
    if ratio < Decimal("0.05"):
        points = 0
    elif ratio < Decimal("0.12"):
        points = 10
    elif ratio < Decimal("0.25"):
        points = 25
    else:
        points = 50
    return round4(ratio), points
