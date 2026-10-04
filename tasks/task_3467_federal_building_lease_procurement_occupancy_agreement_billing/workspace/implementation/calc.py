"""Calculation rules (scaffold section 1.3). All money is integer cents;
every rounding is round-half-up; bill components are rounded to whole cents
BEFORE the subtotal is summed (component-first order pinned).
"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, getcontext

from dates import parse_date, month_of_date_str, next_month_str

getcontext().prec = 60

ONE = Decimal("1")
FEE_PCT = Decimal("0.05")
TI_R = Decimal("0.005")            # TI_AMORT_ANNUAL_RATE 0.06 / 12
ALT_R = Decimal("0.07") / 12       # ALTERATION_AMORT_ANNUAL_RATE / 12
TAX_CAP = Decimal("0.20")          # TAX_ESC_CAP_PCT
TARGET_SF_PER_PERSON = 150
UTILIZATION_THRESHOLD = Decimal("0.60")
SLA_CREDIT_DAILY_CENTS = 10000
SLA_CREDIT_CAP_CENTS = 100000


def rhu(x):
    """Round half up to whole integer cents."""
    return int(Decimal(x).quantize(ONE, rounding=ROUND_HALF_UP))


def headcount_projection(base_headcount, annual_growth_pct, years):
    """projected = round_half_up(base * (1 + g) ^ years), years >= 0."""
    g = Decimal(str(annual_growth_pct))
    value = Decimal(base_headcount) * ((Decimal(1) + g) ** years)
    return int(value.quantize(ONE, rounding=ROUND_HALF_UP))


def security_level(mission, population, size, criticality, special_needs):
    pts = mission + population + size + criticality
    if pts < 15:
        lvl = 1
    elif pts < 30:
        lvl = 2
    elif pts < 45:
        lvl = 3
    elif pts < 60:
        lvl = 4
    else:
        lvl = 5
    if any(n.get("need_type") == "SCIF" for n in (special_needs or [])):
        lvl = max(lvl, 4)
    return lvl


def ti_schedule(P, n, method):
    """TI amortization schedule, n entries, each rounded half up before the
    next month is computed. Empty when principal is zero."""
    if P <= 0 or n <= 0:
        return []
    if method == "ANNUITY":
        level = rhu(Decimal(P) * TI_R / (Decimal(1) - (Decimal(1) + TI_R) ** (-n)))
        return [level] * n
    # STRAIGHT_LINE: equal principal + interest on declining balance
    eq_principal = rhu(Decimal(P) / n)
    balance = Decimal(P)
    out = []
    for _ in range(n):
        interest = rhu(balance * TI_R)
        out.append(eq_principal + interest)
        balance -= eq_principal
    return out


def _latest_statement(lease, year):
    qual = [s for s in lease["tax_statements"] if s["tax_year"] <= year]
    return max(qual, key=lambda s: s["tax_year"]) if qual else None


def tax_escalation(lease, sf, bill_year):
    """Monthly tax escalation component for a leased OA. Annual figure is
    rounded half up first, then divided by 12 and rounded half up again."""
    stmt = _latest_statement(lease, bill_year)
    if lease["escalation_method"] == "BASE_YEAR_STOP":
        actual = stmt["actual_tax_per_sf_yr_cents"] if stmt else lease["base_year_tax_per_sf_yr_cents"]
        esc_annual = Decimal(max(0, actual - lease["base_year_tax_per_sf_yr_cents"])) * sf
    else:  # CPI_INDEXED
        cpi = Decimal(str(stmt["cpi_index"])) if stmt else Decimal(str(lease["cpi_base_index"]))
        base_cpi = Decimal(str(lease["cpi_base_index"]))
        ratio = cpi / base_cpi
        factor = min(max(ratio - Decimal(1), Decimal(0)), TAX_CAP)
        esc_annual = Decimal(lease["base_year_tax_per_sf_yr_cents"]) * sf * factor
    esc_annual = esc_annual.quantize(ONE, rounding=ROUND_HALF_UP)
    return rhu(esc_annual / 12)


def bill_components(oa, lease, billing_month, alterations):
    """The pinned monthly_rent_bill sequence. Mutates covered COMPLETED
    alterations (amortization balance advance, lump PENDING -> BILLED) and
    returns the bill's computed component fields plus '_touched' alterations."""
    by, bm = int(billing_month[:4]), int(billing_month[5:7])
    sf = oa["assigned_sf"]
    leased = lease is not None
    month_index = None
    if leased:
        comm = parse_date(lease["commencement_date"])
        month_index = (by - comm.year) * 12 + (bm - comm.month) + 1
        shell_rate = lease["shell_rate_per_sf_yr_cents"]
        op_rate = lease["operating_rate_per_sf_yr_cents"]
    else:
        shell_rate = oa["shell_equivalent_rate_per_sf_yr_cents"]
        op_rate = oa["operating_rate_per_sf_yr_cents"]
    shell = rhu(Decimal(shell_rate) * sf / 12)
    operating = rhu(Decimal(op_rate) * sf / 12)
    abatement = shell if (leased and month_index <= lease["free_rent_months"]) else 0
    tax = tax_escalation(lease, sf, by) if leased else 0
    ti = 0
    if leased and 1 <= month_index <= lease["term_months"] and lease["ti_schedule_monthly_cents"]:
        ti = lease["ti_schedule_monthly_cents"][month_index - 1]
    oa_end_month = month_of_date_str(oa["end_date"])
    alt_amort = 0
    lump = 0
    touched = []
    for alt in alterations:
        if alt["status"] != "COMPLETED":
            continue
        if alt["funding_method"] == "AMORTIZED" and alt.get("amortization_start_month"):
            if alt["amortization_start_month"] <= billing_month <= oa_end_month:
                # The schedule is fixed at completion: replay the exact
                # unrounded balance from the principal through every schedule
                # month before this one, so the charge is independent of
                # which prior months were actually billed.
                sy, sm = int(alt["amortization_start_month"][:4]), int(alt["amortization_start_month"][5:7])
                k = (by - sy) * 12 + (bm - sm) + 1  # 1-based schedule position
                monthly = alt["monthly_amort_cents"]
                bal = Decimal(alt["estimated_cost_cents"])
                for _ in range(k - 1):
                    bal = bal * (Decimal(1) + ALT_R) - monthly
                if billing_month == oa_end_month:
                    # final schedule month absorbs the residual
                    charge = rhu(bal * (Decimal(1) + ALT_R))
                else:
                    charge = monthly
                alt["amortization_balance_cents"] = bal * (Decimal(1) + ALT_R) - charge
                alt_amort += charge
                touched.append(alt)
        elif alt["funding_method"] == "LUMP_SUM" and alt.get("completion_date"):
            c = parse_date(alt["completion_date"])
            if next_month_str(c.year, c.month) == billing_month:
                lump += alt["estimated_cost_cents"]
                if alt["lump_charge_status"] == "PENDING":
                    alt["lump_charge_status"] = "BILLED"
                    touched.append(alt)
    subtotal = shell - abatement + operating + tax + ti + alt_amort + lump
    fee = rhu(Decimal(subtotal) * FEE_PCT)
    credit = min(oa["pending_service_credit_cents"], subtotal + fee)
    total = max(0, subtotal + fee - credit)
    return {
        "shell_cents": shell,
        "operating_cents": operating,
        "tax_escalation_cents": tax,
        "ti_amortization_cents": ti,
        "alteration_amortization_cents": alt_amort,
        "lump_sum_charges_cents": lump,
        "abatement_credit_cents": abatement,
        "fee_cents": fee,
        "service_credit_applied_cents": credit,
        "total_cents": total,
        "_touched": touched,
    }


def alteration_amortization(P, n):
    """Returns (monthly_amort_cents, exact_balance). Monthly payment rounded
    half up FIRST; the final month absorbs the residual at billing time."""
    if n <= 0:
        return 0, Decimal(P)
    monthly = rhu(Decimal(P) * ALT_R / (Decimal(1) - (Decimal(1) + ALT_R) ** (-n)))
    return monthly, Decimal(P)


def utilization(method, measured_headcount, utilized_sf, assigned_sf):
    """Returns (rate_4dp, recommended_release_sf, below_threshold). The
    threshold comparison uses the rounded rate; exactly 0.6000 does not
    trigger a reduction."""
    if assigned_sf and assigned_sf > 0:
        if method == "SPACE_BASED":
            rate = Decimal(utilized_sf) / Decimal(assigned_sf)
        else:  # HEADCOUNT_BASED
            rate = Decimal(measured_headcount * TARGET_SF_PER_PERSON) / Decimal(assigned_sf)
    else:
        rate = Decimal(0)
    rate4 = rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    release = max(0, (assigned_sf or 0) - measured_headcount * TARGET_SF_PER_PERSON)
    return float(rate4), release, rate4 < UTILIZATION_THRESHOLD


def score_options(p, sf):
    """expiration_option_scoring over a 120-month horizon; ties break by the
    fixed priority SUCCEEDING_LEASE > RELOCATION > REPLACEMENT_CONSTRUCTION."""
    sc = (p["succeeding_shell_rate"] + p["succeeding_operating_rate"]) * sf * 10
    rel = (p["relocation_move_cost_cents"] + p["relocation_downtime_cost_cents"]
           + (p["market_shell_rate"] + p["market_operating_rate"]) * sf * 10)
    con = rhu(Decimal(p["construction_cost_cents"]) * 120 / 300) + p["construction_operating_rate"] * sf * 10
    costs = [
        {"option": "SUCCEEDING_LEASE", "projected_cost_cents": sc},
        {"option": "RELOCATION", "projected_cost_cents": rel},
        {"option": "REPLACEMENT_CONSTRUCTION", "projected_cost_cents": con},
    ]
    best, best_cost = "SUCCEEDING_LEASE", sc
    if rel < best_cost:
        best, best_cost = "RELOCATION", rel
    if con < best_cost:
        best, best_cost = "REPLACEMENT_CONSTRUCTION", con
    return costs, best


def sla_adjudicate(ticket):
    """Returns (breached, credit_cents). Open hours measured exactly from
    created_at to resolved_at; breach only when strictly greater than
    sla_hours. Credit: 10000 per started 24h block of overrun, cap 100000."""
    created = datetime.strptime(ticket["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
    resolved = datetime.strptime(ticket["resolved_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
    hours = Decimal(str((resolved - created).total_seconds())) / Decimal(3600)
    sla = ticket["sla_hours"]
    if hours > sla:
        over = hours - sla
        blocks = int((over / Decimal(24)).to_integral_value(rounding=ROUND_CEILING))
        return True, min(SLA_CREDIT_CAP_CENTS, SLA_CREDIT_DAILY_CENTS * blocks)
    return False, 0
