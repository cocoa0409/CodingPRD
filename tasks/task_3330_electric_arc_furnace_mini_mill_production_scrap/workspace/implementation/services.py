"""Shared business-logic services: posture, lookups, cascades, calculations."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import calendar

import db
from errors import err

BENCHMARK_CENTS_PER_TON = 40000
PROFIT_SHARE_RATE = Decimal("0.10")
SETTLEMENT_MIN_FILL_PCT = Decimal("0.80")
FURNACE_GRID_MINUTES = 45
EVENT_MIN_GAP_MINUTES = 15

FORM_TO_CATEGORY = {"BILLET": "SHREDDED", "BLOOM": "BUSHLING", "SLAB": "HMS"}


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def get_mill(mill_id):
    m = db.mills.get(mill_id)
    if m is None:
        raise err("ERR_MILL_NOT_FOUND", "mill not found")
    return m


def get_contract(contract_id, mill_id=None):
    c = db.contracts.get(contract_id)
    if c is None or (mill_id is not None and c["mill_id"] != mill_id):
        raise err("ERR_CONTRACT_NOT_FOUND", "contract not found")
    return c


def get_lot(lot_id):
    l = db.scrap_lots.get(lot_id)
    if l is None:
        raise err("ERR_LOT_NOT_FOUND", "scrap lot not found")
    return l


def get_grade(grade_id, mill_id=None):
    g = db.grades.get(grade_id)
    if g is None or (mill_id is not None and g["mill_id"] != mill_id):
        raise err("ERR_GRADE_NOT_FOUND", "grade not found")
    return g


def get_heat(heat_id, mill_id=None):
    h = db.heats.get(heat_id)
    if h is None or (mill_id is not None and h["mill_id"] != mill_id):
        raise err("ERR_HEAT_NOT_FOUND", "heat not found")
    return h


def get_sheet(sheet_id, heat_id=None):
    s = db.meltdown_sheets.get(sheet_id)
    if s is None or (heat_id is not None and s["heat_id"] != heat_id):
        raise err("ERR_SHEET_NOT_FOUND", "meltdown sheet not found")
    return s


def get_campaign(campaign_id, mill_id=None):
    c = db.campaigns.get(campaign_id)
    if c is None or (mill_id is not None and c["mill_id"] != mill_id):
        raise err("ERR_CAMPAIGN_NOT_FOUND", "campaign not found")
    return c


def get_account(account_id, mill_id=None):
    a = db.accounts.get(account_id)
    if a is None or (mill_id is not None and a["mill_id"] != mill_id):
        raise err("ERR_ACCOUNT_NOT_FOUND", "account not found")
    return a


def get_order(order_id, account_id=None):
    o = db.orders.get(order_id)
    if o is None or (account_id is not None and o["account_id"] != account_id):
        raise err("ERR_ORDER_NOT_FOUND", "order not found")
    return o


def get_window(window_id, mill_id=None):
    w = db.windows.get(window_id)
    if w is None or (mill_id is not None and w["mill_id"] != mill_id):
        raise err("ERR_WINDOW_NOT_FOUND", "window not found")
    return w


def get_event(event_id, mill_id=None):
    e = db.events.get(event_id)
    if e is None or (mill_id is not None and e["mill_id"] != mill_id):
        raise err("ERR_EVENT_NOT_FOUND", "event not found")
    return e


def get_scorecard(scorecard_id, mill_id=None):
    s = db.scorecards.get(scorecard_id)
    if s is None or (mill_id is not None and s["mill_id"] != mill_id):
        raise err("ERR_SCORECARD_NOT_FOUND", "scorecard not found")
    return s


def get_index(index_id, mill_id=None):
    i = db.surcharge_indices.get(index_id)
    if i is None or (mill_id is not None and i["mill_id"] != mill_id):
        raise err("ERR_INDEX_NOT_FOUND", "surcharge index not found")
    return i


def published_index(mill_id, grade_category, month):
    for i in db.surcharge_indices.values():
        if (i["mill_id"] == mill_id and i["grade_category"] == grade_category
                and i["effective_month"] == month and i["status"] == "PUBLISHED"):
            return i
    return None


def require_index(mill_id, grade_category, month):
    idx = published_index(mill_id, grade_category, month)
    if idx is None:
        raise err("ERR_INDEX_MISSING",
                  f"no PUBLISHED surcharge index for {grade_category} in {month}")
    return idx


# ---------------------------------------------------------------------------
# posture / clock-driven sweeps
# ---------------------------------------------------------------------------

def compute_posture(mill_id):
    clock = db.get_clock()
    for e in db.events.values():
        if e["mill_id"] == mill_id and e["status"] == "ACTIVE":
            return "INTERRUPTED"
    for w in db.windows.values():
        if (w["mill_id"] == mill_id and w.get("linked_event_id")
                and w["start_at"] <= clock <= w["end_at"]):
            return "INTERRUPTED"
    return "NORMAL"


def refresh_posture(mill_id):
    m = db.mills.get(mill_id)
    if m is not None:
        m["posture"] = compute_posture(mill_id)


def refresh_all_postures():
    for mill_id in db.mills:
        refresh_posture(mill_id)


def clock_sweep():
    """Apply time-driven lapses/expiries against the current logical clock."""
    clock = db.get_clock()
    for w in db.windows.values():
        if w["status"] == "SCHEDULED" and clock > w["end_at"]:
            linked_ok = False
            if w.get("linked_event_id"):
                ev = db.events.get(w["linked_event_id"])
                if ev is not None and ev["status"] in ("ACTIVE", "RELEASED"):
                    linked_ok = True
            if not linked_ok:
                w["status"] = "LAPSED"
    for e in db.events.values():
        if e["status"] == "DECLARED" and clock > e["released_at"]:
            e["status"] = "EXPIRED"
    refresh_all_postures()


# ---------------------------------------------------------------------------
# waivers
# ---------------------------------------------------------------------------

def heat_waiver_covered(heat):
    for w in db.waivers.values():
        if w["scope"] == "HEAT" and w["scope_id"] == heat["id"]:
            return True
    active = [e for e in db.events.values()
              if e["mill_id"] == heat["mill_id"] and e["status"] == "ACTIVE"]
    for ev in active:
        for w in db.waivers.values():
            if w["scope"] == "EVENT" and w["scope_id"] == ev["id"]:
                return True
    return False


def posture_gate(heat):
    """Raise ERR_MILL_INTERRUPTED when the heat's mill is INTERRUPTED and
    the heat carries no covering waiver."""
    refresh_posture(heat["mill_id"])
    if db.mills[heat["mill_id"]]["posture"] != "NORMAL":
        if not heat_waiver_covered(heat):
            raise err("ERR_MILL_INTERRUPTED", "mill interrupted and no covering waiver")


# ---------------------------------------------------------------------------
# heat helpers
# ---------------------------------------------------------------------------

def heat_lines(heat_id):
    return [l for l in db.charge_lines.values() if l["heat_id"] == heat_id]


def heat_sheet(heat_id):
    for s in db.meltdown_sheets.values():
        if s["heat_id"] == heat_id:
            return s
    return None


def check_heat_grid(mill_id, planned_tap_at, exclude_heat_id=None):
    for h in db.heats.values():
        if h["mill_id"] != mill_id or h["id"] == exclude_heat_id:
            continue
        if h["status"] not in ("CHARGED", "MELTDOWN_LOCKED", "TAPPED"):
            continue
        if abs((h["planned_tap_at"] - planned_tap_at)) < timedelta(minutes=FURNACE_GRID_MINUTES):
            raise err("ERR_HEAT_SEQUENCE_CONFLICT",
                      "another non-terminal heat within 45 minutes")


def blend_check(heat, grade, candidate_lot, candidate_tons):
    lines = heat_lines(heat["id"])
    total = Decimal("0")
    cu_sum = Decimal("0")
    mn_sum = Decimal("0")
    for line in lines:
        lot = db.scrap_lots[line["scrap_lot_id"]]
        t = Decimal(str(line["tons"]))
        total += t
        cu_sum += t * Decimal(str(lot["cu_pct"]))
        mn_sum += t * Decimal(str(lot["mn_pct"]))
    total += Decimal(str(candidate_tons))
    cu_sum += Decimal(str(candidate_tons)) * Decimal(str(candidate_lot["cu_pct"]))
    mn_sum += Decimal(str(candidate_tons)) * Decimal(str(candidate_lot["mn_pct"]))
    q = Decimal("0.000001")
    cu_blend = (cu_sum / total).quantize(q, rounding=ROUND_HALF_UP)
    mn_blend = (mn_sum / total).quantize(q, rounding=ROUND_HALF_UP)
    if cu_blend > Decimal(str(grade["cu_max_pct"])) or mn_blend < Decimal(str(grade["mn_min_pct"])):
        raise err("ERR_BLEND_INFEASIBLE", "blend outside grade chemistry limits")


def line_unit_price(contract, lot):
    if contract["contract_type"] == "FIXED":
        return Decimal(str(contract["contract_price_cents"]))
    month = lot["received_on"][:7]
    idx = require_index(contract["mill_id"], contract["grade_category"], month)
    return Decimal(str(idx["price_per_ton_cents"]))


def round_cents(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_charge(heat, lot, tons):
    contract = db.contracts[lot["contract_id"]]
    unit = line_unit_price(contract, lot)
    cost = round_cents(unit * Decimal(str(tons)))
    import uuid
    line = {
        "id": str(uuid.uuid4()),
        "heat_id": heat["id"],
        "scrap_lot_id": lot["id"],
        "tons": tons,
        "line_cost_cents": cost,
        "created_at": db.ts_now(),
    }
    db.charge_lines[line["id"]] = line
    lot["remaining_tons"] = float(Decimal(str(lot["remaining_tons"])) - Decimal(str(tons)))
    if lot["remaining_tons"] <= 0:
        lot["remaining_tons"] = 0
        lot["status"] = "CONSUMED"
    else:
        lot["status"] = "PARTIALLY_CONSUMED"
    return line


def recompute_lot_status(lot):
    if lot["remaining_tons"] <= 0:
        lot["remaining_tons"] = 0
        lot["status"] = "CONSUMED"
    elif lot["remaining_tons"] >= lot["dry_tons"]:
        lot["remaining_tons"] = lot["dry_tons"]
        lot["status"] = "RECEIVED"
    else:
        lot["status"] = "PARTIALLY_CONSUMED"


def abort_heat(heat):
    for line in heat_lines(heat["id"]):
        lot = db.scrap_lots[line["scrap_lot_id"]]
        lot["remaining_tons"] = float(Decimal(str(lot["remaining_tons"])) + Decimal(str(line["tons"])))
        recompute_lot_status(lot)
    sheet = heat_sheet(heat["id"])
    if sheet is not None and sheet["status"] != "CONFIRMED":
        sheet["status"] = "REJECTED"
    heat["status"] = "ABORTED"
    bump(heat)


def compute_scrap_surcharge_credit(heat):
    lines = heat_lines(heat["id"])
    total_tons = Decimal("0")
    actual = Decimal("0")
    for line in lines:
        lot = db.scrap_lots[line["scrap_lot_id"]]
        contract = db.contracts[lot["contract_id"]]
        unit = line_unit_price(contract, lot)
        actual += unit * Decimal(str(line["tons"]))
        total_tons += Decimal(str(line["tons"]))
    bench = total_tons * Decimal(BENCHMARK_CENTS_PER_TON)
    return round_cents(actual - bench)


# ---------------------------------------------------------------------------
# campaigns
# ---------------------------------------------------------------------------

def campaign_lines_for(campaign_id):
    lines = [l for l in db.campaign_lines.values() if l["campaign_id"] == campaign_id]
    def key(line):
        h = db.heats[line["heat_id"]]
        return (h["planned_tap_at"], h["created_at"])
    return sorted(lines, key=key)


def recompute_roll_changes(campaign):
    lines = campaign_lines_for(campaign["id"])
    count = 0
    prev = None
    for line in lines:
        heat = db.heats[line["heat_id"]]
        g = db.grades[heat["grade_id"]]["grade_group"]
        if prev is None:
            prev = g
        elif g != prev:
            count += 1
            prev = g
    campaign["roll_changes_used"] = count
    return count


# ---------------------------------------------------------------------------
# OCC
# ---------------------------------------------------------------------------

def bump(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = db.ts_now()


def new_common():
    now = db.ts_now()
    return {"created_at": now, "updated_at": now, "version": 1}


def check_occ(entity, expected):
    if expected is not None and expected != entity["version"]:
        raise err("ERR_STALE_VERSION", "stale version")


# ---------------------------------------------------------------------------
# scorecard helpers
# ---------------------------------------------------------------------------

def open_scorecard(mill_id, period):
    for s in db.scorecards.values():
        if s["mill_id"] == mill_id and s["period"] == period and s["status"] == "OPEN":
            return s
    return None


def recompute_scorecard_profit(sc):
    """Refresh the live profit fields on an OPEN scorecard after any accrual."""
    sc["profit_cents"] = (sc["revenue_cents"] - sc["material_cost_cents"]
                          - sc["energy_cost_cents"])
    sc["profit_pool_cents"] = int(Decimal(max(0, sc["profit_cents"])) * PROFIT_SHARE_RATE)


def month_last_day(month):
    y, m = int(month[:4]), int(month[5:7])
    return calendar.monthrange(y, m)[1]
