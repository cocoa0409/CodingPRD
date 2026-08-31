"""Deterministic calculation rules (PRD 2.7 / 3.x)."""
from decimal import Decimal, ROUND_HALF_UP

import store

# ---------------------------------------------------------------- constants
GROWTH_FACTOR = {"SLOW": Decimal("1.25"), "MODERATE": Decimal("1.00"), "RAPID": Decimal("0.75")}
TIER_FACTOR = {"TIER_NORMAL": Decimal("1.00"), "TIER_ELEVATED": Decimal("0.80"),
               "TIER_CRITICAL": Decimal("0.60")}
VOLTAGE_FLOOR_MONTHS = {"DISTRIBUTION_4KV": 24, "DISTRIBUTION_12KV": 24,
                        "DISTRIBUTION_35KV": 30, "SUBTRANSMISSION_69KV": 36,
                        "TRANSMISSION_115KV": 36}
VOLTAGE_CEIL_MONTHS = {"DISTRIBUTION_4KV": 72, "DISTRIBUTION_12KV": 72,
                       "DISTRIBUTION_35KV": 84, "SUBTRANSMISSION_69KV": 96,
                       "TRANSMISSION_115KV": 96}
UNIT_RATE_CENTS = {"DISTRIBUTION_4KV": 4200, "DISTRIBUTION_12KV": 4800,
                   "DISTRIBUTION_35KV": 6100, "SUBTRANSMISSION_69KV": 7500,
                   "TRANSMISSION_115KV": 9000}
EQUIP_RATE_CENTS = {"BUCKET": 9500, "CLIMBING": 3000, "MANUAL": 1500,
                    "HERBICIDE": 4000, "STORM": 11000}
DISPOSAL_RATE_CENTS = 2800
OVERTIME_THRESHOLD_HOURS = Decimal("10")
OVERTIME_MULTIPLIER = Decimal("1.5")
DENSITY_LOW_BREAK = Decimal("40")
DENSITY_HIGH_BREAK = Decimal("80")
DENSITY_SPARSE = Decimal("1.15")
DENSITY_MID = Decimal("1.00")
DENSITY_DENSE = Decimal("0.92")
RETAINAGE_TIER_1_BREAK_CENTS = 500000
RETAINAGE_TIER_2_BREAK_CENTS = 2000000
RETAINAGE_PCT_TIER_1 = Decimal("0.05")
RETAINAGE_PCT_TIER_2 = Decimal("0.10")
STORM_PREMIUM_PCT = Decimal("0.20")
MOBILIZATION_CREDIT_BREAK_CENTS = 1000000
MOBILIZATION_CREDIT_CENTS = 25000
DEFECT_WEIGHT = {"DEAD": 40, "CAVITY": 30, "LEAN": 25, "CODOMINANT": 15, "HEALTHY": 0}
SPECIES_WEIGHT = {"SILVER_MAPLE": 20, "COTTONWOOD": 18, "ASH": 15, "OAK": 8, "CONIFER": 5}
TARGET_WEIGHT = {"DISTRIBUTION_4KV": 6, "DISTRIBUTION_12KV": 8, "DISTRIBUTION_35KV": 12,
                 "SUBTRANSMISSION_69KV": 16, "TRANSMISSION_115KV": 20}
REMOVAL_RISK_THRESHOLD = Decimal("60.00")
PROXIMITY_MAX_POINTS = Decimal("30")
ROLLING_WINDOW_MONTHS = 36
TIER_ELEVATED_OUTAGE_COUNT = 4
TIER_CRITICAL_OUTAGE_COUNT = 6
MAX_REFUSAL_ROUNDS = 3
TRAVEL_BUFFER_MINUTES = 60
DISPUTE_WINDOW_DAYS = 30
UNIT_OVERRUN_TOLERANCE = Decimal("1.10")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    return int(rhu(value, 0))


def two_dp(value):
    return float(rhu(value, 2))


# ---------------------------------------------------------------- trim cycle
def trim_cycle_months(circuit, prescription):
    raw = (dec(prescription["base_cycle_years"]) * Decimal(12)
           * GROWTH_FACTOR[circuit["growth_zone"]]
           * TIER_FACTOR[circuit["reliability_tier"]])
    rounded = int(rhu(raw, 0))
    floor_m = VOLTAGE_FLOOR_MONTHS[circuit["voltage_class"]]
    ceil_m = VOLTAGE_CEIL_MONTHS[circuit["voltage_class"]]
    bounded = max(floor_m, min(ceil_m, rounded))
    due = store.add_calendar_months(circuit.get("last_trim_completed_on"), bounded)
    return bounded, (due.isoformat() if due else None)


# ---------------------------------------------------------------- reliability
def reliability_windows(circuit, outages, clock):
    """Return (index_36mo, index_ytd, count_36mo, tier)."""
    qualifying = []
    for rec in outages:
        if rec.get("circuit_id") != circuit["id"]:
            continue
        if rec.get("cause_code") not in ("TREE_GROWN_IN", "TREE_FELL_ON"):
            continue
        moment = store.parse_datetime(rec.get("outage_at"))
        if moment is None:
            continue
        qualifying.append((moment, rec))

    rolling_start = store.shift_months_dt(clock, -ROLLING_WINDOW_MONTHS)
    ytd_start = clock.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    denominator = circuit.get("customer_count") or 0
    denominator = max(1, int(denominator))

    rolling_rows = [r for (m, r) in qualifying if rolling_start <= m <= clock]
    ytd_rows = [r for (m, r) in qualifying if ytd_start <= m <= clock]

    rolling_minutes = sum(dec(r.get("customer_minutes") or 0) for r in rolling_rows)
    ytd_minutes = sum(dec(r.get("customer_minutes") or 0) for r in ytd_rows)

    index_36 = two_dp(dec(rolling_minutes) / Decimal(denominator))
    index_ytd = two_dp(dec(ytd_minutes) / Decimal(denominator))
    count_36 = len(rolling_rows)
    if count_36 >= TIER_CRITICAL_OUTAGE_COUNT:
        tier = "TIER_CRITICAL"
    elif count_36 >= TIER_ELEVATED_OUTAGE_COUNT:
        tier = "TIER_ELEVATED"
    else:
        tier = "TIER_NORMAL"
    return index_36, index_ytd, count_36, tier


# ---------------------------------------------------------------- hazard tree
def hazard_risk(species, defect_class, height_ft, offset_ft, voltage_class):
    height = dec(height_ft)
    offset = dec(offset_ft)
    strike = offset <= height
    if not strike:
        return False, 0.00, False
    ratio = offset / height if height != 0 else Decimal(0)
    proximity = PROXIMITY_MAX_POINTS * (Decimal(1) - ratio)
    if proximity < 0:
        proximity = Decimal(0)
    proximity = rhu(proximity, 2)
    total = (Decimal(DEFECT_WEIGHT[defect_class]) + Decimal(SPECIES_WEIGHT[species])
             + proximity + Decimal(TARGET_WEIGHT[voltage_class]))
    score = rhu(total, 2)
    if score > Decimal("100.00"):
        score = Decimal("100.00")
    return True, float(score), score >= REMOVAL_RISK_THRESHOLD


# ---------------------------------------------------------------- production
def production_entry_cents(entry, crew):
    hours = dec(entry.get("labor_hours") or 0)
    straight = min(hours, OVERTIME_THRESHOLD_HOURS)
    overtime = hours - OVERTIME_THRESHOLD_HOURS
    if overtime < 0:
        overtime = Decimal(0)
    rate = dec(crew.get("hourly_rate_cents") or 0)
    equip = dec(entry.get("equipment_hours") or 0) * Decimal(EQUIP_RATE_CENTS[crew["crew_type"]])
    disposal = dec(entry.get("disposal_tons") or 0) * Decimal(DISPOSAL_RATE_CENTS)
    total = straight * rate + overtime * rate * OVERTIME_MULTIPLIER + equip + disposal
    return cents(total)


# ---------------------------------------------------------------- billing
def density_multiplier(billable_units, span_miles):
    miles = dec(span_miles)
    if miles == 0:
        per_mile = Decimal(0)
    else:
        per_mile = dec(billable_units) / miles
    if per_mile < DENSITY_LOW_BREAK:
        return DENSITY_SPARSE
    if per_mile < DENSITY_HIGH_BREAK:
        return DENSITY_MID
    return DENSITY_DENSE


def unit_price_gross(billable_units, multiplier, voltage_class):
    return cents(dec(billable_units) * Decimal(UNIT_RATE_CENTS[voltage_class]) * multiplier)


def settlement(gross_cents, has_storm):
    """Six-step waterfall; returns the settlement fields."""
    gross = int(gross_cents)
    if gross >= RETAINAGE_TIER_2_BREAK_CENTS:
        pct = RETAINAGE_PCT_TIER_2
    elif gross >= RETAINAGE_TIER_1_BREAK_CENTS:
        pct = RETAINAGE_PCT_TIER_1
    else:
        pct = Decimal("0.00")
    retainage = cents(Decimal(gross) * pct)
    premium = cents(Decimal(gross) * STORM_PREMIUM_PCT) if has_storm else 0
    net = gross - retainage + premium
    credit = MOBILIZATION_CREDIT_CENTS if net >= MOBILIZATION_CREDIT_BREAK_CENTS else 0
    final = net - credit
    return {
        "gross_cents": gross,
        "retainage_cents": retainage,
        "storm_premium_cents": premium,
        "net_payable_cents": net,
        "mobilization_credit_cents": credit,
        "final_payable_cents": final,
    }


def ratio_pct(numerator, denominator):
    if denominator == 0:
        return 0.00
    return two_dp(Decimal(100) * dec(numerator) / dec(denominator))


def rate_per_hour(units, hours):
    if dec(hours) == 0:
        return 0.00
    return two_dp(dec(units) / dec(hours))
