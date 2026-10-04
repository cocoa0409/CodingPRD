"""Business logic: calculations, state helpers, capital ledger, events."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB, new_id, now_iso, parse_iso

# ---- constants -------------------------------------------------------------
REV_PER_HH = {"TRADITIONAL": 420, "DG_FRESH": 560, "DG_MARKET": 640}
MIN_REVENUE = {"TRADITIONAL": 40000000, "DG_FRESH": 90000000, "DG_MARKET": 220000000}
BUILD_COST = {"TRADITIONAL": 350000000, "DG_FRESH": 500000000, "DG_MARKET": 700000000}
WEEKLY_CASES = {"TRADITIONAL": 900, "DG_FRESH": 1400, "DG_MARKET": 2600}
BASE_HOURS = {"TRADITIONAL": 220, "DG_FRESH": 340, "DG_MARKET": 520}
KIND_MULTIPLIER = {"REMODEL": Decimal("1.1"), "RELOCATION": Decimal("0.9"),
                   "NEW_BUILD": Decimal("1.0")}
COST_PER_MILE_CENTS = 285
TRUCK_CAPACITY_CASES = 1800
PER_STOP_CENTS = 35000
LOW_FILL_THRESHOLD_PCT = 55
LOW_FILL_SURCHARGE_CENTS = 15000
DAILY_PENALTY_CENTS = 500000
PENALTY_CAP_CENTS = 45000000
LABOR_RATE_CENTS = 2400

_order_counter = [0]


def next_order():
    _order_counter[0] += 1
    return _order_counter[0]


def D(x):
    return Decimal(str(x))


def round2(x):
    return float(D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round0(x):
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt_dt(dt):
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def base_entity():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_order": next_order()}


# ---- events ----------------------------------------------------------------

def append_event(program, event_type, store_id=None, payload=None):
    program["event_log_cursor"] = program.get("event_log_cursor", 0) + 1
    ev = {
        "id": new_id(),
        "created_at": now_iso(),
        "rollout_program_id": program["id"],
        "sequence_number": program["event_log_cursor"],
        "event_type": event_type,
        "store_id": store_id,
        "payload": payload or {},
        "_order": next_order(),
    }
    DB.events[ev["id"]] = ev
    return ev


# ---- capital ledger ---------------------------------------------------------

def recompute_capital(program):
    pid = program["id"]
    committed = 0
    for s in DB.stores.values():
        if s["rollout_program_id"] == pid and s["status"] in (
                "UNDER_CONSTRUCTION", "DELIVERED", "OPEN"):
            committed += s.get("build_cost_cents") or 0
    for p in DB.capital_projects.values():
        if p["rollout_program_id"] == pid and p["status"] == "APPROVED":
            if p["kind"] == "NEW_BUILD":
                committed += p.get("new_build_cost_cents") or 0
            elif p["kind"] == "RELOCATION":
                committed += p.get("project_cost_cents") or 0
            elif p["kind"] == "REMODEL":
                committed += p.get("remodel_cost_cents") or 0
    program["committed_capital_cents"] = committed
    program["available_capital_cents"] = (
        program["new_build_capital_budget_cents"] - committed)


# ---- trade-area scoring -----------------------------------------------------

def compute_trade_area_score(ta, program):
    gap_norm = min(D(ta["grocery_gap_pct"]) / D(40), D(1))
    income_norm = max(D(0), min(
        (D(ta["median_household_income_cents"]) / D(100) - D(25000)) / D(50000),
        D(1)))
    drive_norm = max(D(0), D(1) - D(ta["drive_time_minutes"]) / D(45))
    hh_norm = min(D(ta["household_count"]) / D(6000), D(1))
    raw = (D("0.35") * gap_norm + D("0.25") * income_norm
           + D("0.20") * drive_norm + D("0.20") * hh_norm)
    standard = round2(raw * 100)

    overlap = D(0)
    for s in DB.stores.values():
        if s["rollout_program_id"] != program["id"]:
            continue
        if s["status"] not in ("OPEN", "EXISTING"):
            continue
        other_ta = DB.trade_areas.get(s["trade_area_id"])
        if other_ta is None:
            continue
        if abs(other_ta["drive_time_minutes"] - ta["drive_time_minutes"]) <= 10:
            overlap += min(D(other_ta["grocery_gap_pct"]), D(25))
    overlap = min(overlap, D(100))

    if overlap > 0:
        final = round2(raw * 100 * (D(1) - overlap / D(100) * D("0.5")))
    else:
        final = standard

    qualifies = (
        ta["drive_time_minutes"] <= 30
        and ta["household_count"] >= 650
        and ta["median_household_income_cents"] >= 3500000
        and D(ta["grocery_gap_pct"]) >= D(12)
        and D(final) >= D(40)
    )
    return final, qualifies


# ---- format selection -------------------------------------------------------

def select_format(ta):
    hh = D(ta["household_count"])
    gap_factor = D(1) + D(ta["grocery_gap_pct"]) / D(100)
    for fmt in ("DG_MARKET", "DG_FRESH", "TRADITIONAL"):
        proj = hh * D(REV_PER_HH[fmt]) * D(100) * gap_factor
        proj_cents = round0(proj)
        if proj_cents >= MIN_REVENUE[fmt]:
            return fmt, proj_cents
    return None, None


# ---- stem cost ---------------------------------------------------------------

def compute_stem_cost(store, stem_miles, deliveries_per_week):
    standard = D(stem_miles) * D(2) * D(COST_PER_MILE_CENTS) * D(deliveries_per_week)
    weekly = D(store.get("weekly_case_volume_base") or 0) * D(store.get("volume_index") or 1)
    if weekly < D(TRUCK_CAPACITY_CASES):
        return round0(standard * D("1.25"))
    return round0(standard)


# ---- delivery penalty --------------------------------------------------------

def compute_penalty(committed_dt, actual_dt):
    delta_days = math.floor((actual_dt - committed_dt).total_seconds() / 86400)
    late_days = max(0, delta_days)
    base = DAILY_PENALTY_CENTS * min(late_days, 180)
    bonus = 0
    if late_days > 60:
        bonus = int(D(DAILY_PENALTY_CENTS) * D(late_days - 60) * D("0.5"))
    penalty = min(base + bonus, PENALTY_CAP_CENTS)
    return late_days, int(penalty)


# ---- route planning ----------------------------------------------------------

def compute_route_plan(store):
    weekly = D(store.get("weekly_case_volume_base") or 0) * D(store.get("volume_index") or 1)
    deliveries = max(1, math.ceil(weekly / D(TRUCK_CAPACITY_CASES)))
    cases_per_truck = math.ceil(weekly / D(deliveries))
    truck_fill_pct = round2(D(cases_per_truck) / D(TRUCK_CAPACITY_CASES) * D(100))
    surcharge = LOW_FILL_SURCHARGE_CENTS if D(truck_fill_pct) < D(LOW_FILL_THRESHOLD_PCT) else 0
    per_delivery = (D(store.get("stem_miles") or 0) * D(2) * D(COST_PER_MILE_CENTS)
                    + D(PER_STOP_CENTS) + D(surcharge))
    weekly_cost = round0(D(deliveries) * per_delivery)
    return {
        "deliveries_per_week": deliveries,
        "cases_per_truck": cases_per_truck,
        "truck_fill_pct": truck_fill_pct,
        "weekly_cost_cents": weekly_cost,
    }


# ---- cannibalization ---------------------------------------------------------

def compute_study(store, overlap_entries, coefficient):
    coef = D(coefficient)
    total = 0
    entries_out = []
    impacts = []
    for e in overlap_entries:
        es = DB.stores[e["existing_store_id"]]
        sales = D(es["open_year_sales_cents"])
        w = D(e["overlap_weight"])
        transferred = round0(sales * w * coef)
        impact = round2(D(transferred) / sales * D(100)) if sales != 0 else 0.0
        total += transferred
        impacts.append(impact)
        entries_out.append({
            "existing_store_id": e["existing_store_id"],
            "overlap_weight": e["overlap_weight"],
            "transferred_cents": transferred,
            "impact_pct": impact,
        })
    rev = D(store.get("projected_revenue_cents") or 0)
    transfer_pct = round2(D(total) / rev * D(100)) if rev != 0 else 0.0
    if any(D(i) > D(20) for i in impacts) or D(transfer_pct) > D(15):
        rec = "BLOCKED"
    elif any(D(i) > D(12) for i in impacts) or D(transfer_pct) > D(8):
        rec = "MITIGATE"
    else:
        rec = "PROCEED"
    return entries_out, total, transfer_pct, rec


def compute_study_symmetric(store, overlap_entries, coefficient):
    coef = D(coefficient)
    total = 0
    entries_out = []
    for e in overlap_entries:
        es = DB.stores[e["existing_store_id"]]
        sales = D(es["open_year_sales_cents"])
        w = D(e["overlap_weight"])
        factor = coef / D(2) + w / D(2)
        transferred = round0(sales * w * factor)
        total += transferred
        entries_out.append({
            "existing_store_id": e["existing_store_id"],
            "overlap_weight": e["overlap_weight"],
            "transferred_cents": transferred,
        })
    rev = D(store.get("projected_revenue_cents") or 0)
    transfer_pct = round2(D(total) / rev * D(100)) if rev != 0 else 0.0
    return {"overlap_entries": entries_out,
            "total_transferred_cents": total,
            "transfer_pct": transfer_pct}


# ---- opening labor -----------------------------------------------------------

def compute_labor(format_type, peak_season):
    base = BASE_HOURS[format_type]
    hours = math.ceil(D(base) * D("1.15")) if peak_season else base
    return int(hours), int(hours) * LABOR_RATE_CENTS


# ---- capital scoring ----------------------------------------------------------

def effective_cost(project):
    if project["kind"] == "REMODEL":
        return project.get("remodel_cost_cents") or 0
    if project["kind"] == "RELOCATION":
        return project.get("project_cost_cents") or 0
    return project.get("new_build_cost_cents") or 0


def compute_new_build_cost(store):
    credit = 0
    for ag in DB.agreements.values():
        if ag["store_id"] == store["id"] and ag["status"] == "COMPLETED":
            credit += ag.get("penalty_cents") or 0
    return (store.get("build_cost_cents") or 0) - credit


def compute_capital_score(project, store):
    c = D(effective_cost(project))
    if project["kind"] == "NEW_BUILD":
        u = D(store.get("projected_revenue_cents") or 0)
    else:
        u = D(project.get("projected_uplift_cents") or 0)
    npv = u * D(3) - c
    if c == 0:
        return 0.0
    return round2(npv / c * D(100) * KIND_MULTIPLIER[project["kind"]])


def recompute_ranks(program_id):
    decided = [p for p in DB.capital_projects.values()
               if p["rollout_program_id"] == program_id
               and p["status"] in ("APPROVED", "REJECTED")]
    decided.sort(key=lambda p: (-D(p.get("capital_score") or 0),
                                p.get("decided_at") or ""))
    for i, p in enumerate(decided, start=1):
        p["rank"] = i
