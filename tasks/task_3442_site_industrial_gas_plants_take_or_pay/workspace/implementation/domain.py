"""Shared business logic: tank analytics, delivery creation/ranking, cascades,
the logical-clock sweep, and the pinned 14-step settlement calculation."""
from datetime import datetime, timezone, timedelta, time as dtime
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from store import (db, clock_now, now_iso, fmt_ts, new_id, next_seq, touch,
                   base_entity, ApiError)


CENT = Decimal("1")
FOUR_DP = Decimal("0.0001")
MAKEUP_CREDIT_RATE = Decimal("0.6")
WMA_WEIGHTS = (Fraction(1, 2), Fraction(1, 4), Fraction(1, 8), Fraction(1, 8))

MODE_MIN_MONTHLY_VOLUME_NM3 = {
    "ONSITE_PLANT": 2000000,
    "PIPELINE": 800000,
    "BULK_LIQUID": 150000,
    "CYLINDER": 0,
}

ONSITE_MIN_AVG_NM3H = 4000
PIPELINE_MIN_AVG_NM3H = 1500
BULK_MIN_AVG_NM3H = 200


def recommend_mode(demand_avg, pipeline_available):
    """demand_avg is a Decimal; thresholds are inclusive (>=)."""
    if demand_avg >= ONSITE_MIN_AVG_NM3H:
        return "ONSITE_PLANT"
    if pipeline_available and demand_avg >= PIPELINE_MIN_AVG_NM3H:
        return "PIPELINE"
    if demand_avg >= BULK_MIN_AVG_NM3H:
        return "BULK_LIQUID"
    return "CYLINDER"


# ---------------------------------------------------------------------------
# Tank analytics (PRD 3.5): burn variants, runouts, posture
# ---------------------------------------------------------------------------
def readings_of(tank_id):
    rs = [r for r in db["readings"].values() if r["tank_id"] == tank_id]
    rs.sort(key=lambda r: (r["_measured"], r["_seq"]))
    return rs


def latest_reading(tank_id):
    rs = readings_of(tank_id)
    return rs[-1] if rs else None


def posture_for(tank, level):
    if level <= tank["safety_stock_liters"]:
        return "CRITICAL"
    if level <= tank["reorder_point_liters"]:
        return "REORDER_DUE"
    return "NORMAL"


def headroom_liters(tank):
    level = tank["current_level_liters"]
    return tank["capacity_liters"] - (level if level is not None else 0)


def _runout_iso(last_dt, level_liters, safety_stock_liters, burn_lph):
    """last_dt + (level - safety)/burn hours, round-half-up to whole seconds."""
    if burn_lph <= 0:
        return None
    seconds = Fraction(level_liters - safety_stock_liters) * 3600 / burn_lph
    dec = Decimal(seconds.numerator) / Decimal(seconds.denominator)
    whole = int(dec.quantize(CENT, rounding=ROUND_HALF_UP))
    return fmt_ts(last_dt + timedelta(seconds=whole))


def recompute_tank_analytics(tank):
    rs = readings_of(tank["id"])
    if len(rs) < 2:
        tank["burn_rate_instant_lph"] = None
        tank["burn_rate_wma_lph"] = None
        tank["projected_runout_instant_at"] = None
        tank["projected_runout_wma_at"] = None
        return
    burns = []
    for i in range(1, len(rs)):
        delta = rs[i]["_measured"] - rs[i - 1]["_measured"]
        micros = (delta.days * 86400 + delta.seconds) * 10**6 + delta.microseconds
        drop = rs[i - 1]["level_liters"] - rs[i]["level_liters"]
        if drop <= 0 or micros <= 0:
            burns.append(Fraction(0))
        else:
            burns.append(Fraction(drop) / (Fraction(micros) / Fraction(3600 * 10**6)))
    instant = burns[-1]
    wma = Fraction(0)
    latest_first = list(reversed(burns))
    for j in range(min(4, len(latest_first))):
        wma += WMA_WEIGHTS[j] * latest_first[j]
    tank["burn_rate_instant_lph"] = float(instant)
    tank["burn_rate_wma_lph"] = float(wma)
    last = rs[-1]
    level = tank["current_level_liters"]
    safety = tank["safety_stock_liters"]
    tank["projected_runout_instant_at"] = _runout_iso(last["_measured"], level, safety, instant)
    tank["projected_runout_wma_at"] = _runout_iso(last["_measured"], level, safety, wma)


# ---------------------------------------------------------------------------
# Deliveries (PRD 3.5/3.6): open-ness, creation, stop sequencing
# ---------------------------------------------------------------------------
def has_open_delivery(tank_id):
    for d in db["deliveries"].values():
        if d["tank_id"] != tank_id:
            continue
        if d["transport_status"] == "SCHEDULED":
            return True
        if d["transport_status"] == "DELIVERED" and d["quality_status"] == "QC_PENDING":
            return True
    return False


def recompute_stop_sequences(route_date):
    cands = [d for d in db["deliveries"].values()
             if d["route_date"] == route_date and d["transport_status"] == "SCHEDULED"]

    def key(d):
        tank = db["tanks"][d["tank_id"]]
        runout = tank["projected_runout_wma_at"]
        null_flag = 1 if runout is None else 0
        return (null_flag, runout or "",
                (tank["created_at"], tank["_seq"]),
                (d["created_at"], d["_seq"]))

    cands.sort(key=key)
    for idx, d in enumerate(cands, start=1):
        if d["stop_sequence"] != idx:
            d["stop_sequence"] = idx
            touch(d)


def create_delivery(tank, triggered_by):
    route_date = clock_now().strftime("%Y-%m-%d")
    ent = base_entity()
    ent.update({
        "tank_id": tank["id"],
        "customer_id": tank["customer_id"],
        "product": tank["product"],
        "quantity_liters": headroom_liters(tank),
        "triggered_by": triggered_by,
        "route_date": route_date,
        "route_code": "RT-" + route_date,
        "stop_sequence": None,
        "required_purity_percent": tank["required_purity_percent"],
        "max_impurity_ppm": tank["max_impurity_ppm"],
        "transport_status": "SCHEDULED",
        "quality_status": "QC_PENDING",
        "delivered_quantity_liters": None,
        "confirmed_at": None,
    })
    db["deliveries"][ent["id"]] = ent
    recompute_stop_sequences(route_date)
    return ent


# ---------------------------------------------------------------------------
# Cascades (PRD 2.9 / 3.2 / 3.7)
# ---------------------------------------------------------------------------
def terminate_cascade(contract):
    """ACTIVE/RENEWAL_OPEN -> TERMINATED side effects."""
    for p in db["plants"].values():
        if p["contract_id"] == contract["id"] and p["status"] != "DECOMMISSIONED":
            p["status"] = "DECOMMISSIONED"
            p["effective_capacity_nm3h"] = 0
            touch(p)
            for t in db["turnarounds"].values():
                if (t["plant_id"] == p["id"]
                        and t["status"] in ("PROPOSED", "AGREED", "SCHEDULED")):
                    t["status"] = "CANCELLED"
                    touch(t)
    touched_networks = set()
    for c in db["connections"].values():
        if c["contract_id"] == contract["id"] and c["status"] == "ACTIVE":
            c["status"] = "RELEASED"
            touch(c)
            touched_networks.add(c["network_id"])
    for nid in touched_networks:
        net = db["networks"].get(nid)
        if net is not None:
            touch(net)
    for d in db["deliveries"].values():
        if (d["transport_status"] == "SCHEDULED"
                and d["customer_id"] == contract["customer_id"]
                and d["product"] == contract["product"]):
            d["transport_status"] = "CANCELLED"
            touch(d)


def start_turnaround_effects(t):
    """SCHEDULED -> IN_PROGRESS failover cascade (PRD 3.7)."""
    plant = db["plants"][t["plant_id"]]
    contract = db["contracts"][plant["contract_id"]]
    plant["status"] = "TURNAROUND"
    plant["effective_capacity_nm3h"] = 0
    touch(plant)
    contract["failover_active"] = True
    touch(contract)
    for tank in db["tanks"].values():
        if (tank["customer_id"] == contract["customer_id"]
                and tank["product"] == contract["product"]
                and not has_open_delivery(tank["id"])):
            create_delivery(tank, "BACKUP")


def complete_turnaround(t):
    """IN_PROGRESS -> COMPLETED; plant returns to OPERATING if still parked."""
    t["status"] = "COMPLETED"
    touch(t)
    plant = db["plants"].get(t["plant_id"])
    if plant is None:
        return
    if plant["status"] == "TURNAROUND":
        plant["status"] = "OPERATING"
        plant["effective_capacity_nm3h"] = plant["nameplate_capacity_nm3h"]
        touch(plant)
    contract = db["contracts"].get(plant["contract_id"])
    if contract is not None and contract["failover_active"]:
        contract["failover_active"] = False
        touch(contract)


# ---------------------------------------------------------------------------
# Logical-clock sweep (PRD 2.4)
# ---------------------------------------------------------------------------
def sweep(now):
    for c in list(db["contracts"].values()):
        if c["status"] == "ACTIVE":
            end_dt = datetime.combine(c["_end"], dtime.min, tzinfo=timezone.utc)
            if now >= end_dt - timedelta(days=90):
                c["status"] = "RENEWAL_OPEN"
                touch(c)
    for c in list(db["contracts"].values()):
        if c["status"] == "RENEWAL_OPEN":
            end_dt = datetime.combine(c["_end"], dtime.min, tzinfo=timezone.utc)
            if now > end_dt:
                c["status"] = "EXPIRED"
                touch(c)
    for t in list(db["turnarounds"].values()):
        if t["status"] == "IN_PROGRESS" and now >= t["_we"]:
            complete_turnaround(t)


# ---------------------------------------------------------------------------
# Settlement (PRD 3.8): pinned 14-step invoice
# ---------------------------------------------------------------------------
def escalation_multiplier(pct, months_elapsed):
    """Per-year compounded multiplier, rounded half-up to 4dp after EACH year."""
    years = months_elapsed // 12
    mult = Decimal("1.0000")
    one_plus = Decimal(1) + pct
    for _ in range(years):
        mult = (mult * one_plus).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
    return mult


def live_plant_for_contract(contract_id):
    for p in db["plants"].values():
        if p["contract_id"] == contract_id and p["status"] != "DECOMMISSIONED":
            return p
    return None


def compute_settlement(contract, period_year, period_month, variant,
                       metered, projected, power_index_actual, apply_makeup):
    """Pure computation; performs no ledger mutation. Money in integer cents."""
    sy, sm = contract["_start"].year, contract["_start"].month
    months_elapsed = (period_year - sy) * 12 + (period_month - sm)          # (1)
    mult = escalation_multiplier(
        Decimal(str(contract["facility_fee_escalation_pct_annual"])),
        months_elapsed)                                                      # (2)
    effective = metered if variant == "FINAL" else projected                 # (3)
    billable = max(effective, contract["min_monthly_volume_nm3"])            # (4)
    volume_charge = billable * contract["unit_price_cents_per_nm3"]          # (5)
    if variant == "FINAL":                                                   # (6)
        pp = (Decimal(effective)
              * Decimal(str(contract["power_kwh_per_nm3"]))
              * (Decimal(str(power_index_actual))
                 - Decimal(str(contract["base_power_index"]))))
        power_passthrough = int(pp.quantize(CENT, rounding=ROUND_HALF_UP))
    else:
        power_passthrough = 0
    facility_fee = int((Decimal(contract["monthly_facility_fee_cents"]) * mult)
                       .quantize(CENT, rounding=ROUND_HALF_UP))              # (7)
    capital = 0                                                              # (8)
    if contract["mode"] == "ONSITE_PLANT":
        plant = live_plant_for_contract(contract["id"])
        if plant is not None:
            capital = plant["capital_cost_cents"] // contract["term_months"]
    subtotal = volume_charge + power_passthrough + facility_fee + capital    # (9)
    shortfall = max(0, contract["min_monthly_volume_nm3"] - effective)       # (10)
    balance_pre = contract["makeup_credit_balance_cents"]
    if variant == "FINAL":                                                   # (11)
        applied = min(apply_makeup if apply_makeup is not None else 0,
                      balance_pre, subtotal)
    else:
        applied = 0
    raw_grant = int((Decimal(shortfall)
                     * Decimal(contract["unit_price_cents_per_nm3"])
                     * MAKEUP_CREDIT_RATE).quantize(CENT,
                                                    rounding=ROUND_HALF_UP))
    cap = int((Decimal(str(contract["makeup_credit_cap_pct"]))
               * 12
               * Decimal(contract["min_monthly_volume_nm3"])
               * Decimal(contract["unit_price_cents_per_nm3"]))
              .quantize(CENT, rounding=ROUND_HALF_UP))
    grant_room = max(0, cap - balance_pre)
    granted = min(raw_grant, grant_room)                                     # (12)
    total_due = subtotal - applied                                           # (13)
    return {
        "months_elapsed": months_elapsed,
        "escalation_multiplier": float(mult),
        "billable_volume_nm3": billable,
        "volume_charge_cents": volume_charge,
        "power_passthrough_cents": power_passthrough,
        "facility_fee_cents": facility_fee,
        "capital_recovery_cents": capital,
        "subtotal_cents": subtotal,
        "shortfall_volume_nm3": shortfall,
        "makeup_credit_granted_cents": granted,
        "makeup_credit_applied_cents": applied,
        "total_due_cents": total_due,
    }
