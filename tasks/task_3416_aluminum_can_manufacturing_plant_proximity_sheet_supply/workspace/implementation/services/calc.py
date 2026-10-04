"""Calculation rules (scaffold section 1.3 / PRD section 3).

All money and percentage math uses Decimal with ROUND_HALF_UP. Rounding order
is pinned: per-run / per-component rounding happens BEFORE any summation.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import store, clock_year

# ---------------------------------------------------------------------------
# Constants (scaffold "constants" table — transcribed exactly)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
VOLUME_REBATE_PCT = Decimal("0.04")
SPECIALTY_SURCHARGE_PCT = Decimal("0.12")
SHORTFALL_FEE_CENTS_PER_1000 = Decimal("400")
MAX_SPOILAGE_PCT = Decimal("0.15")
SPECIALTY_SPOILAGE_PREMIUM_PCT = Decimal("0.03")
CHANGEOVER_SPOILAGE_PENALTY_PCT = Decimal("0.02")
CHANGEOVER_BUFFER_MINUTES = 240
MAX_PICKUPS_PER_DAY = 2
FORECAST_ROLLING_WINDOW = 3
CONGESTED_FREE_FRACTION = Decimal("0.20")
MIN_RUN_QTY = 5000
MIN_COMMITTED_ANNUAL_UNITS = 1000000
PROVISIONAL_INDEX_LAG_MONTHS = 1

CENT = Decimal("0.01")
TENK = Decimal("0.0001")
WHOLE = Decimal("1")

NON_TERMINAL_RUN_STATUSES = ("SCHEDULED", "IN_PROGRESS", "HELD", "COMPLETED", "SETTLED")
OPEN_RUN_STATUSES = ("SCHEDULED", "IN_PROGRESS", "HELD")


def D(v):
    return Decimal(str(v))


def q2(v):
    return D(v).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# can_unit_price (PROVISIONAL / FINAL variants share this formula)
# ---------------------------------------------------------------------------
def tier_factor_for(agreement, ytd_basis=None):
    """Volume factor evaluated against ytd BEFORE the current run's units."""
    ytd = agreement["ytd_settled_units"] if ytd_basis is None else ytd_basis
    if ytd >= agreement["committed_annual_units"]:
        return Decimal("1") - VOLUME_REBATE_PCT
    return Decimal("1")


def can_unit_price(agreement, fmt, index_cents_per_lb, ytd_basis=None):
    tier_factor = tier_factor_for(agreement, ytd_basis)
    specialty_factor = (Decimal("1") + SPECIALTY_SURCHARGE_PCT) if fmt["is_specialty"] else Decimal("1")
    conversion_effective = D(agreement["conversion_cost_cents_per_1000"]) * tier_factor * specialty_factor
    metal = D(fmt["metal_lbs_per_1000_units"]) * D(index_cents_per_lb) * D(agreement["pass_through_pct"])
    return q2(metal + conversion_effective)


def run_invoice_amount(final_unit_price, produced_qty):
    """Per-run rounding to 2 decimals BEFORE any summation (pinned order)."""
    return q2(D(final_unit_price) * D(produced_qty) / D(1000))


# ---------------------------------------------------------------------------
# Index period helpers
# ---------------------------------------------------------------------------
def delivery_period(window_end):
    """YYYY-MM of the run's window_end."""
    return window_end[:7]


def prior_month_period(period):
    year = int(period[:4])
    month = int(period[5:7])
    month -= PROVISIONAL_INDEX_LAG_MONTHS
    while month < 1:
        month += 12
        year -= 1
    return "%04d-%02d" % (year, month)


def find_index(period):
    for idx in store["indices"].values():
        if idx["period"] == period:
            return idx
    return None


# ---------------------------------------------------------------------------
# Spoilage expectation
# ---------------------------------------------------------------------------
def previous_run(line_id, window_start_dt, exclude_id=None):
    """Non-terminal run on the line with the latest window_end <= this start;
    ties broken by earliest created_at (insertion order via _created_sort)."""
    best = None
    for r in store["runs"].values():
        if r["line_id"] != line_id or r["id"] == exclude_id:
            continue
        if r["status"] not in NON_TERMINAL_RUN_STATUSES:
            continue
        end_dt = r["_window_end_dt"]
        if end_dt > window_start_dt:
            continue
        if best is None or end_dt > best["_window_end_dt"]:
            best = r
        elif end_dt == best["_window_end_dt"] and r["_created_sort"] < best["_created_sort"]:
            best = r
    return best


def expected_spoilage_pct(line, fmt, changeover):
    total = D(line["base_spoilage_pct"])
    if fmt["is_specialty"]:
        total += SPECIALTY_SPOILAGE_PREMIUM_PCT
    if changeover:
        total += CHANGEOVER_SPOILAGE_PENALTY_PCT
    if total > MAX_SPOILAGE_PCT:
        total = MAX_SPOILAGE_PCT
    return total.quantize(TENK, rounding=ROUND_HALF_UP)


def effective_spoilage_pct(produced_qty, spoiled_qty):
    total = produced_qty + spoiled_qty
    if total == 0:
        return Decimal("0.0000")
    return (D(spoiled_qty) / D(total)).quantize(TENK, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Forecast accuracy (rolling mean-of-ratios vs lifetime ratio-of-aggregates)
# ---------------------------------------------------------------------------
def forecast_accuracy_pct(forecast_qty, actual_qty):
    if forecast_qty == 0 and actual_qty == 0:
        return Decimal("100")
    return (D(100) * (D(1) - D(abs(forecast_qty - actual_qty)) / D(max(forecast_qty, actual_qty)))).quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def agreement_accuracy(agreement_id):
    closed = [
        f for f in store["forecasts"].values()
        if f["agreement_id"] == agreement_id and f["status"] == "CLOSED"
    ]
    if not closed:
        return Decimal("100"), Decimal("100")
    ordered = sorted(closed, key=lambda f: (f["period"], f["_created_sort"]), reverse=True)
    window = ordered[:FORECAST_ROLLING_WINDOW]
    rolling = (sum(D(f["accuracy_pct"]) for f in window) / D(len(window))).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    sum_f = sum(f["forecast_qty"] for f in closed)
    sum_a = sum(f["actual_qty"] for f in closed)
    if max(sum_f, sum_a) == 0:
        lifetime = Decimal("100")
    else:
        lifetime = (D(100) * (D(1) - D(abs(sum_f - sum_a)) / D(max(sum_f, sum_a)))).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    return rolling, lifetime


# ---------------------------------------------------------------------------
# Warehouse projection and plant posture
# ---------------------------------------------------------------------------
def projected_warehouse_units(plant):
    total = plant["warehouse_on_hand_units"]
    for r in store["runs"].values():
        if r["status"] not in OPEN_RUN_STATUSES:
            continue
        line = store["lines"].get(r["line_id"])
        if line is not None and line["plant_id"] == plant["id"]:
            total += r["scheduled_qty"]
    return total


def plant_posture(plant):
    free = plant["warehouse_capacity_units"] - projected_warehouse_units(plant)
    if free <= 0:
        return "LOCKDOWN"
    threshold = int(
        (D(plant["warehouse_capacity_units"]) * CONGESTED_FREE_FRACTION).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    if free <= threshold:
        return "CONGESTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# Agreement volume tier and tier true-up
# ---------------------------------------------------------------------------
def volume_tier(agreement):
    if agreement["ytd_settled_units"] >= agreement["committed_annual_units"]:
        return "REBATE"
    return "STANDARD"


def tier_true_up_delta(agreement, settled_run, fmt):
    """Retroactive rebate credit for one already-SETTLED sibling run."""
    specialty = (Decimal("1") + SPECIALTY_SURCHARGE_PCT) if fmt["is_specialty"] else Decimal("1")
    conv_eff = D(agreement["conversion_cost_cents_per_1000"]) * specialty
    return -q2(conv_eff * VOLUME_REBATE_PCT * D(settled_run["produced_qty"]) / D(1000))


# ---------------------------------------------------------------------------
# Early-termination exposure
# ---------------------------------------------------------------------------
def format_unamortized_exposure(fmt):
    # PRD section 3.3: exposure is 0 while PROPOSED; it initializes to the full
    # tooling_investment_cents at tooling and amortizes from there.
    if fmt["status"] == "PROPOSED":
        return 0
    min_vol = fmt["min_volume_commitment_units"]
    if min_vol <= 0:
        return 0
    undelivered = D(1) - D(fmt["delivered_units"]) / D(min_vol)
    if undelivered < 0:
        undelivered = D(0)
    return int((D(fmt["tooling_investment_cents"]) * undelivered).quantize(WHOLE, rounding=ROUND_HALF_UP))


def early_termination_exposure(agreement):
    shortfall_units = max(0, agreement["committed_annual_units"] - agreement["ytd_settled_units"])
    shortfall_fee = int(
        (D(shortfall_units) / D(1000) * SHORTFALL_FEE_CENTS_PER_1000).quantize(WHOLE, rounding=ROUND_HALF_UP)
    )
    tooling = 0
    for fmt in store["formats"].values():
        if fmt["customer_id"] != agreement["customer_id"]:
            continue
        if fmt["plant_id"] != agreement["plant_id"]:
            continue
        if fmt["status"] not in ("TOOLED", "QUALIFIED"):
            continue
        tooling += format_unamortized_exposure(fmt)
    return {
        "agreement_id": agreement["id"],
        "status": "TERMINATED",
        "shortfall_fee_cents": shortfall_fee,
        "unamortized_tooling_cents": tooling,
        "total_exposure_cents": shortfall_fee + tooling,
    }


# ---------------------------------------------------------------------------
# Year-matched YTD accumulators and recycled content
# ---------------------------------------------------------------------------
def plant_ytd(plant):
    """Event-sourced YTD: only events whose year equals the clock's current
    calendar year count, so the accumulators always reflect the clock year."""
    year = clock_year()
    metal = sum((D(e["lbs"]) for e in plant["_metal_events"] if e["year"] == year), Decimal("0"))
    scrap = sum((D(e["lbs"]) for e in plant["_scrap_events"] if e["year"] == year), Decimal("0"))
    return scrap, metal


def recycled_content_pct(plant):
    scrap, metal = plant_ytd(plant)
    if metal == 0:
        return Decimal("0")
    return (D(100) * scrap / metal).quantize(CENT, rounding=ROUND_HALF_UP)
