"""Calculation rules (scaffold 1.3). All monetary math uses Decimal with
ROUND_HALF_UP; never float for money."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import DB, now

# ---- pinned constants -------------------------------------------------------
FLOW_CELL_BASE_GB = {"FC_LOW": 50, "FC_MID": 120, "FC_HIGH": 300}
CHEMISTRY_THROUGHPUT_MULT = {"V1": "1.0", "V2": "1.5", "V3": "2.2"}
SUBSIDY_CAP_PCT = Decimal("0.40")
SAMPLE_TIER_T2_MIN = 1000
SAMPLE_TIER_T3_MIN = 5000
SAMPLE_RATE_CENTS = {"T1": 250, "T2": 200, "T3": 150}
CREDIT_VALUE_CENTS = 100
CREDIT_OFFSET_MAX_PCT = Decimal("0.5")
CREDIT_EXPIRY_DAYS = 365
CLOUD_CREDIT_COST = {"LOCAL": 0, "CLOUD_STANDARD": 10, "CLOUD_DEEP": 25}
TRADEIN_PCT = {1: Decimal("0.20"), 2: Decimal("0.35")}
TRADEIN_PCT_3_PLUS = Decimal("0.50")
CONDITION_DEDUCTION_PCT = {
    "COSMETIC_DAMAGE": Decimal("0.05"),
    "FUNCTIONAL_DEFECT": Decimal("0.20"),
    "MISSING_ACCESSORIES": Decimal("0.10"),
}
AGE_FREE_YEARS = 3
AGE_DEDUCTION_PCT_PER_YEAR = Decimal("0.02")
TRADEIN_FLOOR_PCT = Decimal("0.05")
SHORTFALL_PENALTY_RATE = Decimal("0.10")
COLD_CHAIN_WEEKLY_CAPACITY = {"FROZEN_20": 500, "REFRIGERATED_4": 1000}
FORECAST_HORIZON_WEEKS = 26
TIER1_MAX_DEFICIT = Decimal("1.0")
TIER1_RATE = Decimal("0.05")
TIER2_MAX_DEFICIT = Decimal("3.0")
TIER2_RATE = Decimal("0.10")
TIER3_RATE = Decimal("0.25")


def D(x):
    return Decimal(str(x))


def rhu_int(dec):
    """Round half up to whole cents/units -> int."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_1dp(dec):
    """Round half up to 1 decimal place -> float."""
    return float(dec.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def rhu_2dp(dec):
    """Round half up to 2 decimal places -> Decimal."""
    return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---- kit_capacity_calc ------------------------------------------------------
def kit_capacity_gb(flow_cell_version, chemistry_version):
    base = D(FLOW_CELL_BASE_GB[flow_cell_version])
    mult = D(CHEMISTRY_THROUGHPUT_MULT[chemistry_version])
    return rhu_1dp(base * mult)


# ---- subsidy_pool_calc (rounding order pinned: per line, then sum) ----------
def subsidy_pool_cents(hardware_lines, subsidy_pct):
    total = 0
    for ln in hardware_lines:
        line_subsidy = D(ln["quantity"]) * D(ln["unit_price_cents"]) * D(subsidy_pct)
        total += rhu_int(line_subsidy)
    return total


def subsidy_cap_ok(pool_cents, committed_annual_reagent_cents):
    return D(pool_cents) <= SUBSIDY_CAP_PCT * D(committed_annual_reagent_cents)


# ---- lot_allocation_calc (FEFO, all-or-nothing) -----------------------------
def lot_available(lot):
    return lot["quantity_units"] - lot["reserved_units"] - lot["consumed_units"]


def usable_lots_for_kit(kit_code):
    """Usable lots: QC_PASSED, INTACT, unexpired (expiry strictly after the
    logical clock), available > 0; sorted expiry ASC, created_at ASC."""
    t = now()
    out = []
    for lot in DB["lots"].values():
        kit = DB["kits"].get(lot["kit_id"])
        if kit is None or kit["kit_code"] != kit_code:
            continue
        if lot["qc_status"] != "QC_PASSED":
            continue
        if lot["cold_chain_status"] != "INTACT":
            continue
        if not (lot["expiry_date"] > t):
            continue
        if lot_available(lot) <= 0:
            continue
        out.append(lot)
    out.sort(key=lambda l: (l["expiry_date"], l["created_at"], l["_seq"]))
    return out


def fefo_allocate(kit_code, quantity, pending_takes):
    """Simulate a FEFO take of `quantity` units of kit_code. pending_takes maps
    lot_id -> units already earmarked earlier in the same allocation pass.
    Returns a list of reservations, or None if the line cannot be satisfied."""
    remaining = quantity
    takes = []
    for lot in usable_lots_for_kit(kit_code):
        if remaining == 0:
            break
        avail = lot_available(lot) - pending_takes.get(lot["id"], 0)
        if avail <= 0:
            continue
        take = min(remaining, avail)
        takes.append({"kit_code": kit_code, "lot_id": lot["id"], "quantity": take})
        pending_takes[lot["id"]] = pending_takes.get(lot["id"], 0) + take
        remaining -= take
    if remaining > 0:
        return None
    return takes


def allocate_order_lines(lines):
    """Full FEFO allocation of every line, in line order; all-or-nothing.
    Returns the reservation list or None. Does not mutate the store."""
    pending = {}
    reservations = []
    for ln in lines:
        takes = fefo_allocate(ln["kit_code"], ln["quantity"], pending)
        if takes is None:
            return None
        reservations.extend(takes)
    return reservations


# ---- uptime_credit_calc -----------------------------------------------------
def uptime_credit(contract, instrument, period_start, period_end):
    """Returns (downtime_minutes:int, uptime_percent:float, credit_cents:int)."""
    t = now()
    pmin = D((period_end - period_start).total_seconds()) / D(60)
    dmin = Decimal(0)
    for w in instrument["service_windows"]:
        opened = w["opened_at"]
        closed = w["closed_at"] if w["closed_at"] is not None else t
        lo = opened if opened > period_start else period_start
        hi = closed if closed < period_end else period_end
        if hi > lo:
            dmin += D((hi - lo).total_seconds()) / D(60)
    if pmin <= 0:
        uptime = Decimal("100.00")
    else:
        uptime = rhu_2dp(D(100) * (pmin - dmin) / pmin)
    committed = D(contract["committed_uptime_percent"])
    if uptime >= committed:
        credit = 0  # exact threshold pays nothing
    else:
        deficit = rhu_2dp(committed - uptime)
        if deficit < TIER1_MAX_DEFICIT:
            rate = TIER1_RATE
        elif deficit < TIER2_MAX_DEFICIT:
            rate = TIER2_RATE  # deficit exactly 1.0 lands here
        else:
            rate = TIER3_RATE
        raw = rhu_int(D(contract["monthly_fee_cents"]) * rate)
        headroom = contract["annual_credit_cap_cents"] - contract["credits_issued_ytd_cents"]
        credit = max(0, min(raw, headroom))
    downtime_minutes = rhu_int(dmin)
    return downtime_minutes, float(uptime), credit


# ---- sample_billing_calc helpers --------------------------------------------
def sample_tier(samples):
    if samples < SAMPLE_TIER_T2_MIN:
        return "T1"
    if samples < SAMPLE_TIER_T3_MIN:
        return "T2"
    return "T3"


def billing_window(license_rec):
    start = license_rec["activated_at"] + timedelta(days=30 * (license_rec["period_index"] - 1))
    return start, start + timedelta(days=30)


# ---- tradein_credit_calc ----------------------------------------------------
def tradein_provisional_cents(old_model, new_model):
    gap = new_model["generation"] - old_model["generation"]
    if gap == 1:
        pct = TRADEIN_PCT[1]
    elif gap == 2:
        pct = TRADEIN_PCT[2]
    else:
        pct = TRADEIN_PCT_3_PLUS
    return rhu_int(D(old_model["base_price_cents"]) * pct)


def tradein_final_cents(old_model, provisional_cents, condition_flags, installed_at, appraisal_at):
    cond_pct = Decimal(0)
    flags = set(condition_flags or [])
    for flag, pct in CONDITION_DEDUCTION_PCT.items():
        if flag in flags:
            cond_pct += pct
    years = 0
    if installed_at is not None:
        years = int((appraisal_at - installed_at).total_seconds() // (365 * 86400))
    age_pct = AGE_DEDUCTION_PCT_PER_YEAR * max(0, years - AGE_FREE_YEARS)
    deduction = rhu_int(D(provisional_cents) * (cond_pct + age_pct))
    floor = rhu_int(D(old_model["base_price_cents"]) * TRADEIN_FLOOR_PCT)
    final = provisional_cents - deduction
    if final < floor:
        final = floor
    if final > provisional_cents:
        final = provisional_cents
    return final


# ---- commitment_reconciliation_calc helpers ---------------------------------
def committed_total_cents(program):
    # term_months in {12,24,36} -> exact integer years
    return program["committed_annual_reagent_cents"] * program["term_months"] // 12


def accrual_expected_cents(program):
    expected = (
        D(program["committed_annual_reagent_cents"]) * D(program["period_index"]) / D(12)
    )
    return rhu_int(expected)


def final_shortfall_and_penalty(program):
    shortfall = max(0, committed_total_cents(program) - program["delivered_spend_cents"])
    penalty = rhu_int(D(shortfall) * SHORTFALL_PENALTY_RATE)
    return shortfall, penalty


# ---- forecast horizon / capacity --------------------------------------------
def current_week_monday():
    t = now()
    monday = t - timedelta(days=t.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def forecast_week_ok(week_start):
    """week_start must be a Monday 00:00:00Z, not before the current week, and
    within 26 weeks of the current logical clock."""
    if week_start.weekday() != 0:
        return False
    if (week_start.hour, week_start.minute, week_start.second, week_start.microsecond) != (0, 0, 0, 0):
        return False
    if week_start < current_week_monday():
        return False
    if week_start > now() + timedelta(weeks=FORECAST_HORIZON_WEEKS):
        return False
    return True


def cold_chain_capacity_ok(these_lines):
    """Aggregate (ISO week, cold_chain_class) demand across this forecast's
    lines plus every other SUBMITTED/FROZEN forecast (any account)."""
    demand = {}

    def add(lines):
        for ln in lines:
            kit = None
            for k in DB["kits"].values():
                if k["kit_code"] == ln["kit_code"]:
                    kit = k
                    break
            if kit is None:
                continue
            key = (ln["week_start"], kit["cold_chain_class"])
            demand[key] = demand.get(key, 0) + ln["quantity"]

    add(these_lines)
    for f in DB["forecasts"].values():
        if f["forecast_state"] in ("SUBMITTED", "FROZEN"):
            add(f["lines"])
    for (_week, cls), qty in demand.items():
        if qty > COLD_CHAIN_WEEKLY_CAPACITY[cls]:
            return False
    return True


# ---- forecast_variance_calc ---------------------------------------------------
def forecast_variance_lines(forecast):
    from timeutil import iso

    t = now()
    out = []
    for ln in forecast["lines"]:
        kit_code = ln["kit_code"]
        week_start = ln["week_start"]
        week_end = week_start + timedelta(days=7)
        actual = 0
        for order in DB["orders"].values():
            if order["account_id"] != forecast["account_id"]:
                continue
            if order["order_state"] != "DELIVERED":
                continue
            delivered = order.get("delivered_at")
            if delivered is None or not (week_start <= delivered < week_end):
                continue
            for r in order["line_reservations"]:
                if r["kit_code"] == kit_code:
                    actual += r["quantity"]
        conservative = 0
        pending_extra = 0
        for lot in DB["lots"].values():
            kit = DB["kits"].get(lot["kit_id"])
            if kit is None or kit["kit_code"] != kit_code:
                continue
            if lot["cold_chain_status"] != "INTACT":
                continue
            if not (lot["expiry_date"] > t):
                continue
            avail = lot_available(lot)
            if lot["qc_status"] == "QC_PASSED":
                conservative += avail
            elif lot["qc_status"] == "PENDING_QC":
                pending_extra += avail
        out.append(
            {
                "kit_code": kit_code,
                "week_start": iso(week_start),
                "forecast_quantity": ln["quantity"],
                "actual_delivered_units": actual,
                "variance": actual - ln["quantity"],
                "coverage_optimistic_units": conservative + pending_extra,
                "coverage_conservative_units": conservative,
            }
        )
    return out
