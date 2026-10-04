"""Domain thresholds and expected-value helpers — every literal pinned to PRD prose.

Sources:
  §2.4  logical clock startup default
  §2.9  readiness index / burden penalty / posture thresholds
  §3.3  cancellation penalty percent
  §3.5  rework provisional/final rates, source multipliers, snag hours
  §3.7  storage volume discount, turnaround buffer
  §3.9  delay compensation constants, negotiation round limit
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value, places=0) -> float:
    """PRD §2.6: derived values are rounded half-up."""
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def round_half_up_int(value) -> int:
    """Half-up rounding to integer cents (PRD §2.6)."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --- Logical clock (PRD §2.4) ---
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Gating readiness index (PRD §2.9, §3.2) ---
GATING_THRESHOLD_INDEX = 85.0          # verdict PASS requires index >= 85.0
BURDEN_PENALTY_PER_OPEN_HOUR = 0.5     # points subtracted per open traveled hour
MAX_BURDEN_PENALTY = 20.0              # burden penalty cap
PCT_CAP = 100.0                        # readiness percentages capped at 100

# --- Posture derivation (PRD §2.9) ---
DISTRESS_INDEX_FLOOR = 60.0            # index < 60.0 -> DISTRESSED
STABLE_INDEX_FLOOR = 85.0              # index >= 85.0 and zero open escapes -> STABLE
DISTRESS_OPEN_ESCAPE_COUNT = 3         # open_escape_count >= 3 -> DISTRESSED

# --- Rework costing (PRD §3.5) ---
PROVISIONAL_RATE_CENTS = 15000         # cents per hour, provisional variant
ACTUAL_RATE_CENTS = 17500              # cents per hour, final variant
SNAG_HOURS_EACH = 4                    # walkthrough snag hours basis
REWORK_SOURCE_MULTIPLIERS = {
    "TRAVELED_WORK": 1.0,
    "QUALITY_ESCAPE": 1.5,
    "FLIGHT_TEST_FAILURE": 1.25,
    "WALKTHROUGH_SNAG": 1.0,
}

# --- Delay compensation (PRD §3.9) ---
LD_DAILY_CENTS = 250000                # contractual liquidated per-diem
LD_CAP_PCT = 0.10                      # cap: ten percent of contract_price_cents
GOODWILL_BASE_CENTS = 1000000          # goodwill flat base
GOODWILL_DAILY_CENTS = 100000          # goodwill per-diem
NEGOTIATION_MAX_ROUNDS = 6             # counter at round 6 -> EXPIRED

# --- Supplier cancellation (PRD §3.3) ---
CANCELLATION_PENALTY_PCT = 0.30        # thirty percent of cancelled units * price

# --- Storage (PRD §3.7) ---
VOLUME_DISCOUNT_FACTOR = 0.95          # five-percent volume discount
BAY_TURNAROUND_BUFFER_DAYS = 2         # closed window padded by 2 days each side

# --- Quality escapes (PRD §3.6) ---
LATE_NOTIFICATION_HOURS = 24           # notify later than created_at + 24h -> late


# --- Shared test input defaults (valid per PRD lower bounds) ---
TEST_DEFAULTS = {
    "MODEL_CODE": "M1",
    "CURRENT_RATE_PER_MONTH": 5,
    "REQUIRED_COMPONENT_CODES": 1,
    "REWORK_BUDGET_TOTAL_CENTS": 1_000_000,
    "SUPPLIER_CODE": "S1",
    "SUPPLIER_NAME": "Engines Co",
    "SUPPLIER_REGION": "NA",
    "CUSTOMER_AIRLINE_CODE": "AL1",
    "CUSTOMER_NAME": "Air One",
    "CUSTOMER_CREDIT_STANDING": "GOOD",
    "LINE_NUMBER": 1001,
    "CONFIGURATION_CODE": "CFG-A",
    "CONTRACT_PRICE_CENTS": 5_000_000_000,
    "CONTRACTED_DELIVERY_DATE": "2026-10-01",
    "STATION_SEQUENCE": 1,
    "WORK_PACKAGE_DESCRIPTION": "Join",
    "PLANNED_HOURS": 5,
    "SKILL_CODE": "AVIONICS",
    "REQUIRED_HEADCOUNT": 10,
    "COMPONENT_CODE": "ENG",
    "COMMITTED_RATE_PER_MONTH": 8,
    "LEAD_TIME_MONTHS": 4,
    "UNIT_PRICE_CENTS": 1_000_000,
    "ORDER_QUANTITY": 10,
    "ASSUMED_RATE_PER_MONTH": 8,
    "REQUIRED_BY_MONTH": "2027-01",
    "PROPOSED_RATE": 8,
    "EFFECTIVE_MONTH": "2027-01",
    "DEMAND_BACKLOG_UNITS": 100,
    "RANGE_CODE": "RANGE_ALPHA",
    "FLIGHT_WINDOW_START": "2026-10-02T09:00:00Z",
    "FLIGHT_WINDOW_END": "2026-10-02T12:00:00Z",
    "BAY_CODE": "B1",
    "STORAGE_WINDOW_START": "2026-09-10T00:00:00Z",
    "STORAGE_WINDOW_END": "2026-12-01T00:00:00Z",
    "DAILY_RATE_CENTS": 1000,
    "PRESERVATION_CYCLE_DAYS": 30,
    "PROPOSED_DELIVERY_DATE": "2026-10-11",
    "COMPENSATION_VARIANT": "CONTRACTUAL_LIQUIDATED",
}


# --- Expected-value calculators (pure functions of the PRD formulas) ---

def expected_provisional_cost_cents(hours_basis, source: str) -> int:
    """PRD §3.5 provisional variant: hours * 15000 * source multiplier, half-up."""
    return round_half_up_int(
        hours_basis * PROVISIONAL_RATE_CENTS * REWORK_SOURCE_MULTIPLIERS[source]
    )


def expected_final_cost_cents(actual_hours, parts_cents) -> int:
    """PRD §3.5 final variant: actual_hours * 17500 + parts_cents, half-up."""
    return round_half_up_int(actual_hours * ACTUAL_RATE_CENTS + parts_cents)


def expected_days_late(proposed_delivery_date: str, contracted_delivery_date: str) -> int:
    """PRD §3.9: whole-day difference floored at zero."""
    from datetime import date
    y, m, d = (int(x) for x in proposed_delivery_date.split("-"))
    proposed = date(y, m, d)
    y, m, d = (int(x) for x in contracted_delivery_date.split("-"))
    contracted = date(y, m, d)
    return max(0, (proposed - contracted).days)


def expected_compensation_cents(variant: str, days_late: int, contract_price_cents: int) -> int:
    """PRD §3.9: contractual capped at 10% of price; goodwill uncapped."""
    if variant == "CONTRACTUAL_LIQUIDATED":
        cap = round_half_up_int(LD_CAP_PCT * contract_price_cents)
        return min(days_late * LD_DAILY_CENTS, cap)
    if variant == "GOODWILL":
        return GOODWILL_BASE_CENTS + days_late * GOODWILL_DAILY_CENTS
    raise ValueError(f"unknown compensation_variant {variant!r}")


def expected_cancellation_penalty_cents(cancelled_quantity: int, unit_price_cents: int) -> int:
    """PRD §3.3: round_half_up(0.30 * cancelled * unit_price)."""
    return round_half_up_int(CANCELLATION_PENALTY_PCT * cancelled_quantity * unit_price_cents)


def expected_readiness_index(supply_pct: float, workforce_pct: float,
                             traveled_work_open_hours: int) -> float:
    """PRD §2.9: round_half_up(min(supply, workforce) - burden, 2)."""
    burden = min(MAX_BURDEN_PENALTY, BURDEN_PENALTY_PER_OPEN_HOUR * traveled_work_open_hours)
    return round_half_up(min(supply_pct, workforce_pct) - burden, 2)


def expected_storage_fee_cents(days_elapsed: int, daily_rate_cents: int) -> int:
    """PRD §3.7: per-aircraft round of days * rate * 0.95 (rounded BEFORE the sum)."""
    days = max(0, days_elapsed)
    return round_half_up_int(days * daily_rate_cents * VOLUME_DISCOUNT_FACTOR)
