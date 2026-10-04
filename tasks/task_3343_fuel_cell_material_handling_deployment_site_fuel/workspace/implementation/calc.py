"""Business calculations (scaffold calculations table; PRD sections 3.1-3.7).

All money math uses Decimal with ROUND_HALF_UP; per-line rounding then sum;
tier unit price held at 4 decimal places.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import validators as v

KG_PER_HOUR = Decimal("0.9")
TIER2_DISCOUNT = Decimal("0.92")
DELIVERED_LIQUID_MARKUP = Decimal("1.08")
SHORTFALL_RATE = Decimal("0.25")
HOURS_PER_MONTH = 730
AVAILABILITY_CREDIT_RATE = Decimal("0.10")
CAPEX_PER_UNIT_CENTS = 1500000
ITC_RATE = Decimal("0.30")
SELF_REPORTED_CONFIDENCE = Decimal("0.90")

NON_VOID_INVOICE_STATUSES = ("DRAFT", "ISSUED", "PAID", "DISPUTED")


def D(x):
    return Decimal(str(x))


def _num(d):
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def rhu(d, places):
    return d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- daily kg

def daily_kg_estimate(forklift_count, duty_cycle_hours_per_day, peak_shift_hours):
    daily = D(forklift_count) * D(duty_cycle_hours_per_day) * KG_PER_HOUR
    if int(peak_shift_hours) > 8:
        daily = daily * Decimal("1.15")
    return _num(rhu(daily, 2))


# ------------------------------------------------------- supply pricing tier

def price_line(invoice, contract, kg):
    """Price a new line item. Returns (unit_price_per_kg, line_amount_cents).

    prior_billed_kg sums kg over line items whose parent invoice shares this
    invoice's contract and period and is not VOID (the new line does not exist
    yet, so every existing matching line precedes it in created_at order).
    """
    prior = Decimal("0")
    for li in db.line_items.values():
        inv = db.invoices.get(li["invoice_id"])
        if inv is None:
            continue
        if (inv["supply_contract_id"] == invoice["supply_contract_id"]
                and inv["period_start"] == invoice["period_start"]
                and inv["period_end"] == invoice["period_end"]
                and inv["status"] in NON_VOID_INVOICE_STATUSES):
            prior += D(li["kg"])
    this_kg = D(kg)
    boundary = D(contract["committed_monthly_kg"])
    base = D(contract["base_price_per_kg"])
    cumulative = prior + this_kg
    if cumulative <= boundary:
        unit = base
    elif prior >= boundary:
        unit = base * TIER2_DISCOUNT
    else:
        over = cumulative - boundary
        under = this_kg - over
        unit = (under * base + over * base * TIER2_DISCOUNT) / this_kg
    if contract["supply_mode"] == "DELIVERED_LIQUID":
        unit = unit * DELIVERED_LIQUID_MARKUP
    unit_r = rhu(unit, 4)
    amount = int(rhu(this_kg * unit_r * 100, 0))
    return _num(unit_r), amount


# --------------------------------------------------------- take-or-pay credit

def invoice_lines(invoice_id):
    return [li for li in db.line_items.values() if li["invoice_id"] == invoice_id]


def _take_or_pay_cents(subtotal, total_kg, contract):
    shortfall = D(contract["committed_monthly_kg"]) - D(total_kg)
    if shortfall < 0:
        shortfall = Decimal("0")
    gross = int(rhu(shortfall * D(contract["base_price_per_kg"])
                    * SHORTFALL_RATE * 100, 0))
    return min(gross, subtotal)


def recompute_draft_totals(invoice):
    """DRAFT invoice: total_kg/subtotal are full sums; credit/total use the
    PROVISIONAL take-or-pay variant (lines whose fueling event occurred on the
    calendar day immediately preceding period_end are excluded)."""
    lines = invoice_lines(invoice["id"])
    contract = db.contracts[invoice["supply_contract_id"]]
    total_kg = sum((D(li["kg"]) for li in lines), Decimal("0"))
    subtotal = sum(li["line_amount_cents"] for li in lines)
    last_day = v.parse_date(invoice["period_end"]) - timedelta(days=1)
    inc_kg = Decimal("0")
    inc_sub = 0
    for li in lines:
        ev = db.fueling_events.get(li["fueling_event_id"])
        ev_date = v.parse_datetime(ev["occurred_at"]).date() if ev else None
        if ev_date == last_day:
            continue
        inc_kg += D(li["kg"])
        inc_sub += li["line_amount_cents"]
    credit = _take_or_pay_cents(inc_sub, inc_kg, contract)
    invoice["total_kg"] = _num(total_kg)
    invoice["subtotal_cents"] = subtotal
    invoice["credit_cents"] = credit
    invoice["total_cents"] = max(0, inc_sub - credit)


def finalize_invoice_totals(invoice):
    """DRAFT -> ISSUED freeze: FINAL take-or-pay variant (all lines) plus the
    availability SLA credit for period_start's calendar month, clamped at the
    subtotal (invoice_availability_reconciliation)."""
    lines = invoice_lines(invoice["id"])
    contract = db.contracts[invoice["supply_contract_id"]]
    total_kg = sum((D(li["kg"]) for li in lines), Decimal("0"))
    subtotal = sum(li["line_amount_cents"] for li in lines)
    top = _take_or_pay_cents(subtotal, total_kg, contract)
    month_str = invoice["period_start"][:7]
    avail = availability_report(invoice["site_id"], month_str)["credit_cents"]
    credit = min(top + avail, subtotal)
    invoice["total_kg"] = _num(total_kg)
    invoice["subtotal_cents"] = subtotal
    invoice["credit_cents"] = credit
    invoice["total_cents"] = max(0, subtotal - credit)


# -------------------------------------------------------- availability credit

def _month_bounds(year, month):
    return (date(year, month, 1),
            date(year, month, calendar.monthrange(year, month)[1]))


def availability_report(site_id, month_str):
    year, month = v.parse_month(month_str)
    first, last = _month_bounds(year, month)
    downtime = sum(
        (D(r["downtime_hours"]) for r in db.downtime_reports.values()
         if r["site_id"] == site_id and r["month"] == month_str),
        Decimal("0"),
    )
    approved = [a for a in db.assessments.values()
                if a["site_id"] == site_id and a["status"] == "APPROVED"]
    if approved:
        latest_a = max(approved, key=lambda a: a["created_at"])
        fleet = D(latest_a["forklift_count"]) * HOURS_PER_MONTH
    else:
        fleet = Decimal("0")
    if fleet == 0:
        availability_pct = None
    else:
        availability_pct = rhu(100 * (1 - downtime / fleet), 2)
    agreements = [a for a in db.agreements.values()
                  if a["site_id"] == site_id and a["status"] == "ACTIVE"
                  and v.parse_date(a["coverage_start"]) <= last
                  and v.parse_date(a["coverage_end"]) >= first]
    if agreements:
        agr = max(agreements, key=lambda a: a["created_at"])
        guarantee = agr["availability_guarantee_pct"]
    else:
        agr = None
        guarantee = None
    # Strictly below the guarantee triggers the credit; exactly AT earns none.
    if (availability_pct is not None and agr is not None
            and availability_pct < D(guarantee)):
        credit = int(rhu(D(agr["monthly_fee_cents"]) * AVAILABILITY_CREDIT_RATE, 0))
    else:
        credit = 0
    return {
        "availability_pct": (_num(availability_pct)
                             if availability_pct is not None else None),
        "guarantee_pct": guarantee,
        "credit_cents": credit,
        "downtime_hours": _num(downtime),
    }


# ------------------------------------------- productivity / incentive (ITC)

def recorded_productivity(measurement_mode, reported):
    if measurement_mode == "TELEMATICS":
        return reported
    return _num(rhu(D(reported) * SELF_REPORTED_CONFIDENCE, 2))


def governing_completed_plan(site_id):
    plans = [p for p in db.plans.values()
             if p["site_id"] == site_id and p["status"] == "COMPLETED"]
    if not plans:
        return None
    return max(plans, key=lambda p: p["created_at"])


def productivity_gate_passes(site, plan):
    actual = site["actual_productivity_units_per_hour"]
    if actual is None:
        return False
    threshold = (D(plan["baseline_productivity_units_per_hour"])
                 * (1 + D(plan["expected_productivity_gain_pct"]) / 100))
    return D(actual) >= threshold


def incentive_amount(plan, claimed_cents):
    """incentive_qualification_amount: plan -> converted units -> capex ->
    uplift -> rate -> cap."""
    units = sum(1 for e in db.events.values()
                if e["conversion_plan_id"] == plan["id"]
                and e["status"] == "COMPLETED")
    capex = units * CAPEX_PER_UNIT_CENTS
    uplifted = rhu(D(capex) * (1 + D(plan["expected_productivity_gain_pct"]) / 100), 0)
    itc = rhu(uplifted * ITC_RATE, 0)
    return min(int(itc), claimed_cents)
