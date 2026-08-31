"""Every calculation rule from the PRD, in Decimal arithmetic."""
from decimal import Decimal

from core import dceil, dfloor, hours_between, ordered, parse_dt, rhu, rhu_f, rhu_int, store
import derive

LOAD_ANGLE_FACTORS = {90: Decimal("1.000"), 60: Decimal("1.155"),
                      45: Decimal("1.414"), 30: Decimal("2.000")}
MAT_PANEL_AREA_SQFT = Decimal(32)
WORST_CASE_OUTRIGGER_SHARE = Decimal("0.60")
DYNAMIC_FACTOR = Decimal("1.10")
STANDBY_INCREMENT = Decimal("0.25")
MINIMUM_BILLABLE_HOURS = Decimal("4.0")
REGULAR_HOURS_PER_DAY = Decimal("8.0")
OVERTIME_MULTIPLIER = Decimal("1.5")
STANDBY_MULTIPLIER = Decimal("0.75")
FREE_STANDBY_HOURS = Decimal("2.0")
MILEAGE_RATE_CENTS_PER_MILE = Decimal(285)
FUEL_SURCHARGE_PCT = Decimal("0.07")
PERMIT_CANCELLATION_PCT = Decimal("0.40")
ESCORT_CLASS_TONS_THRESHOLD = 200
ESCORT_LEAD_DAYS_ADDER = 5
ESCORT_FEE_CENTS = 60000
PERMIT_BASE_LEAD_DAYS = {"ROAD_CLOSURE": 10, "OVERSIZE_ESCORT": 7, "CRANE_PLACEMENT": 3}
PERMIT_BASE_FEE_CENTS = {"ROAD_CLOSURE": 85000, "OVERSIZE_ESCORT": 45000, "CRANE_PLACEMENT": 25000}


# --------------------------------------------------------- ground bearing ---
def ground_bearing(total_load_lb, crane, site, variant):
    total_vertical = Decimal(crane["gross_weight_lb"]) + Decimal(crane["counterweight_lb"]) \
        + Decimal(total_load_lb)
    if variant == "PROVISIONAL_SURVEY":
        per_outrigger = rhu(total_vertical / Decimal(4), 2)
    else:
        per_outrigger = rhu(total_vertical * WORST_CASE_OUTRIGGER_SHARE * DYNAMIC_FACTOR, 2)
    pad_area = Decimal(str(crane["outrigger_pad_area_sqft"]))
    pressure = rhu(per_outrigger / pad_area, 2)
    soil = Decimal(str(site["soil_bearing_capacity_psf"]))
    matting = pressure > soil
    if matting:
        mat_area = dceil(per_outrigger / soil)
        mat_count = 4 * dceil(Decimal(mat_area) / MAT_PANEL_AREA_SQFT)
    else:
        mat_area = 0
        mat_count = 0
    return {
        "bearing_variant": variant,
        "per_outrigger_load_lb": float(per_outrigger),
        "bearing_pressure_psf": float(pressure),
        "matting_required": matting,
        "mat_area_required_sqft": mat_area,
        "mat_count": mat_count,
    }


# ------------------------------------------------------------------- wind ---
def allowable_wind(plan_sail_area, plan_load_weight, crane):
    if plan_load_weight == 0:
        ratio = Decimal("0.00")
    else:
        ratio = rhu(Decimal(str(plan_sail_area)) * Decimal(1000) / Decimal(str(plan_load_weight)), 2)
    if ratio <= Decimal("1.00"):
        derate = Decimal("1.00")
    elif ratio <= Decimal("2.00"):
        derate = Decimal("0.85")
    elif ratio <= Decimal("3.00"):
        derate = Decimal("0.70")
    else:
        derate = Decimal("0.55")
    return dfloor(Decimal(crane["rated_max_wind_mph"]) * derate)


# ---------------------------------------------------------- lift class -----
def lift_class(utilization_pct, plan, site):
    util = Decimal(str(utilization_pct))
    if util >= Decimal("90.00"):
        base = "ENGINEERED_CRITICAL"
    elif util >= Decimal("75.00"):
        base = "CRITICAL"
    else:
        base = "STANDARD"
    forced = plan["personnel_lift"] or plan["multi_crane"] or site["over_water"]
    if forced:
        return "ENGINEERED_CRITICAL"
    if site["proximity_to_energized_lines_ft"] < 20:
        if derive.LIFT_CLASS_RANK["CRITICAL"] > derive.LIFT_CLASS_RANK[base]:
            return "CRITICAL"
        return base
    return base


# ------------------------------------------------------ standby intervals ---
def standby_merged_hours(plan_id):
    events = [e for e in ordered(store.standby_events)
              if e["lift_plan_id"] == plan_id and e["status"] == "CLOSED"]
    intervals = []
    for e in events:
        intervals.append((parse_dt(e["started_at"]), parse_dt(e["ended_at"]), e["_seq"]))
    intervals.sort(key=lambda t: (t[0], t[2]))
    merged = []
    for start, end, _seq in intervals:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    total = Decimal(0)
    for start, end in merged:
        total += hours_between(start, end)
    merged_hours = rhu(total, 4)
    billable = dceil(merged_hours / STANDBY_INCREMENT) * STANDBY_INCREMENT
    return float(billable)


# ------------------------------------------------------------- permit fee ---
def permit_fee_and_lead_days(permit_type, escort_required):
    lead = PERMIT_BASE_LEAD_DAYS[permit_type] + (ESCORT_LEAD_DAYS_ADDER if escort_required else 0)
    fee = PERMIT_BASE_FEE_CENTS[permit_type] + (ESCORT_FEE_CENTS if escort_required else 0)
    return lead, fee


def permit_cancellation_fee(permit_fee_cents):
    return rhu_int(Decimal(permit_fee_cents) * PERMIT_CANCELLATION_PCT)


# ---------------------------------------------------------------- invoice ---
def compute_invoice(inv, plan):
    crane = store.cranes.get(plan["crane_id"]) if plan["crane_id"] else None
    rate = Decimal(crane["hourly_rate_cents"]) if crane else Decimal(0)
    mob = crane["mob_demob_cents"] if crane else 0
    standby_source = Decimal(str(inv["standby_hours_source"]))

    if inv["billing_mode"] == "HOURLY":
        billable = max(Decimal(str(inv["on_site_hours"])) + Decimal(str(inv["travel_hours"])),
                       MINIMUM_BILLABLE_HOURS)
        regular = min(billable, REGULAR_HOURS_PER_DAY)
        overtime = max(billable - REGULAR_HOURS_PER_DAY, Decimal(0))
        standby_billable = standby_source
        line_regular = rhu_int(regular * rate)
        line_overtime = rhu_int(overtime * rate * OVERTIME_MULTIPLIER)
        line_mobdemob = mob
        line_lump_sum = 0
    else:
        billable = Decimal(0)
        regular = Decimal(0)
        overtime = Decimal(0)
        standby_billable = max(standby_source - FREE_STANDBY_HOURS, Decimal(0))
        line_regular = 0
        line_overtime = 0
        line_mobdemob = 0
        line_lump_sum = inv["lump_sum_cents"]

    line_standby = rhu_int(standby_billable * rate * STANDBY_MULTIPLIER)
    line_travel = rhu_int(Decimal(str(inv["travel_miles"])) * MILEAGE_RATE_CENTS_PER_MILE)
    line_permit_cancellation = sum(
        p["cancellation_fee_cents"] for p in store.permits.values()
        if p["lift_plan_id"] == plan["id"] and p["status"] == "VOIDED")

    subtotal = (line_regular + line_overtime + line_standby + line_travel
                + line_mobdemob + line_lump_sum + line_permit_cancellation)

    if subtotal >= 6000000:
        discount_pct = Decimal("0.08")
    elif subtotal >= 2500000:
        discount_pct = Decimal("0.05")
    elif subtotal >= 1000000:
        discount_pct = Decimal("0.02")
    else:
        discount_pct = Decimal("0.00")
    discount_cents = rhu_int(Decimal(subtotal) * discount_pct)
    fuel = rhu_int((Decimal(subtotal) - Decimal(discount_cents)) * FUEL_SURCHARGE_PCT)
    total = subtotal - discount_cents + fuel

    inv.update({
        "billable_hours": float(billable),
        "regular_hours": float(regular),
        "overtime_hours": float(overtime),
        "line_regular_cents": line_regular,
        "line_overtime_cents": line_overtime,
        "line_standby_cents": line_standby,
        "line_travel_cents": line_travel,
        "line_mobdemob_cents": line_mobdemob,
        "line_lump_sum_cents": line_lump_sum,
        "line_permit_cancellation_cents": line_permit_cancellation,
        "subtotal_cents": subtotal,
        "discount_pct": float(discount_pct),
        "discount_cents": discount_cents,
        "fuel_surcharge_cents": fuel,
        "total_cents": total,
    })
    return inv
