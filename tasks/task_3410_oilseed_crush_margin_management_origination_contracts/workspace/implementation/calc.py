"""Calculation rules (SCAFFOLD section 1.3 / PRD section 3).

All money is integer cents; bushels carry 3 decimals; spreads 2 decimals;
rounding is always ROUND_HALF_UP.
"""
from decimal import Decimal, ROUND_HALF_UP

from dates import days_between
from quotes import asof
from store import db, get_clock

OIL_YIELD_LBS_PER_BUSHEL = 11
MEAL_YIELD_LBS_PER_BUSHEL = 47
BEAN_CONTRACT_BUSHELS = 5000
CARRY_STORAGE_CENTS_PER_BUSHEL_MONTH = 5
DEFAULT_CLAIM_RATE = Decimal("0.10")
BUYER_SUSPEND_CLAIM_THRESHOLD = 3
FEEDSTOCK_QUOTA_DAYS = 30
MAX_DELIVERY_WINDOW_DAYS = 62

D3 = Decimal("0.001")
D2 = Decimal("0.01")
D0 = Decimal("1")


def d3(x):
    return Decimal(x).quantize(D3, rounding=ROUND_HALF_UP)


def round2(x):
    return Decimal(x).quantize(D2, rounding=ROUND_HALF_UP)


def round_int(x):
    return int(Decimal(x).quantize(D0, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# quality_grade_factors
# ---------------------------------------------------------------------------

def grade_ticket(ticket, schedule, program):
    gross = Decimal(ticket["gross_bushels"])
    excess_m = max(Decimal(0), Decimal(ticket["moisture_pct"]) - Decimal(schedule["moisture_base_pct"]))
    excess_d = max(Decimal(0), Decimal(ticket["damage_pct"]) - Decimal(schedule["damage_free_pct"]))
    excess_f = max(Decimal(0), Decimal(ticket["foreign_material_pct"]) - Decimal(schedule["fm_free_pct"]))
    shrink = d3(gross * excess_m * Decimal(schedule["moisture_shrink_pct_per_point"]) / Decimal(100))
    net = d3(gross - shrink)
    discount = round_int(
        excess_m * schedule["moisture_discount_cents_per_point"]
        + excess_d * schedule["damage_discount_cents_per_point"]
        + excess_f * schedule["fm_discount_cents_per_point"])
    premium = program["premium_cents_per_bushel"] if program else 0
    return shrink, net, discount, premium


# ---------------------------------------------------------------------------
# dp_storage_accrual (DEFERRED contracts only)
# ---------------------------------------------------------------------------

def accrue_through(contract, T):
    """Finalize the pending accrual leg from last_accrual_date through T."""
    if contract["contract_type"] != "DEFERRED":
        return
    pool = contract["unpriced_pool_bushels"]
    anchor = contract["last_accrual_date"]
    if pool > 0 and anchor is not None:
        days = days_between(anchor, T)
        if days > 0:
            leg = Decimal(contract["storage_rate_cents_per_bushel_day"]) * pool * days
            contract["accrued_storage_cents"] += round_int(leg)


def pricing_event_accrual(contract, bushels, T):
    """A pricing event at T pricing `bushels` bushels out of the unpriced pool."""
    if contract["contract_type"] != "DEFERRED":
        return
    accrue_through(contract, T)
    pool = contract["unpriced_pool_bushels"] - bushels
    if pool < 0:
        pool = Decimal(0)
    contract["unpriced_pool_bushels"] = pool
    contract["last_accrual_date"] = T if pool > 0 else None


def delivery_accrual(contract, net_bushels, T):
    """A ticket apply at T joins net bushels to the unpriced pool."""
    if contract["contract_type"] != "DEFERRED":
        return
    accrue_through(contract, T)
    contract["unpriced_pool_bushels"] += net_bushels
    contract["last_accrual_date"] = T


def pending_accrual(contract, now):
    """accrued_storage_cents plus the pending leg through `now` (provisional)."""
    total = contract["accrued_storage_cents"]
    if (contract["contract_type"] == "DEFERRED"
            and contract["unpriced_pool_bushels"] > 0
            and contract["last_accrual_date"] is not None):
        days = days_between(contract["last_accrual_date"], now)
        if days > 0:
            leg = (Decimal(contract["storage_rate_cents_per_bushel_day"])
                   * contract["unpriced_pool_bushels"] * days)
            total += round_int(leg)
    return total


# ---------------------------------------------------------------------------
# contract_settlement: FIFO line math, round-per-line then sum (pinned order)
# ---------------------------------------------------------------------------

def applied_tickets(contract_id):
    """APPLIED tickets of a contract, applied_date ASC then created_at ASC."""
    ts = [t for t in db["tickets"].values()
          if t["contract_id"] == contract_id and t["status"] == "APPLIED"]
    ts.sort(key=lambda t: (t["applied_date"], t["_seq"]))
    return ts


def settlement_lines(contract, tickets, futures_unit):
    """Walk applied tickets in order, consuming elections FIFO (append order).
    Each sub-line is round_half_up(net_seg * (unit - discount + premium)) to
    integer cents FIRST, then summed.
    Bushels beyond election coverage are valued at `futures_unit` when given;
    otherwise they mark needs_quote. Returns (total_cents, needs_quote)."""
    elections = [[Decimal(e["bushels"]), e["unit_price_cents"]]
                 for e in contract["elections"]]
    ei = 0
    total = 0
    needs_quote = False
    for t in tickets:
        need = Decimal(t["net_bushels"])
        disc = t["discount_cents_per_bushel"]
        prem = t["premium_cents_per_bushel"]
        while need > 0:
            while ei < len(elections) and elections[ei][0] <= 0:
                ei += 1
            if ei >= len(elections):
                if futures_unit is None:
                    needs_quote = True
                    need = Decimal(0)
                    break
                total += round_int(need * (futures_unit - disc + prem))
                need = Decimal(0)
                break
            take = min(need, elections[ei][0])
            total += round_int(take * (elections[ei][1] - disc + prem))
            need -= take
            elections[ei][0] -= take
    return total, needs_quote


def provisional_estimate(contract):
    """estimated_settlement_cents: provisional variant of contract_settlement.
    Same FIFO lines over tickets applied so far; bushels not covered by any
    election are valued at the current as-of futures-derived unit price;
    accrual is the frozen balance plus the pending leg through now.
    Null when a required futures quote is missing."""
    if contract["contract_type"] == "CASH":
        unit = None  # fully covered by the seeded election
    else:
        fut = asof("BEAN", contract["futures_month"])
        unit = None
        if fut is not None:
            unit = fut + (contract["basis_cents_per_bushel"]
                          if contract["contract_type"] == "BASIS" else 0)
    total, needs_quote = settlement_lines(contract, applied_tickets(contract["id"]), unit)
    if needs_quote:
        return None
    return total - pending_accrual(contract, get_clock())


def final_settlement(contract):
    """FINAL variant at settle: every bushel at its actual election price;
    accrual frozen. Writes the three settlement fields."""
    tickets = applied_tickets(contract["id"])
    total, _needs = settlement_lines(contract, tickets, None)
    accrual = contract["accrued_storage_cents"]
    contract["settlement_line_total_cents"] = total
    contract["settlement_accrual_deduction_cents"] = accrual
    contract["settlement_net_payable_cents"] = total - accrual


# ---------------------------------------------------------------------------
# crush_margin / board_crush_spread
# ---------------------------------------------------------------------------

def crush_spread(bean, oil, meal):
    """round_half_up(oil*11 + meal*47 - bean, 2 decimals)."""
    return round2(oil * OIL_YIELD_LBS_PER_BUSHEL
                  + meal * MEAL_YIELD_LBS_PER_BUSHEL - bean)


def quotes3(month):
    """As-of BEAN/OIL/MEAL quotes for a futures month, or None if any missing."""
    bean = asof("BEAN", month)
    oil = asof("OIL", month)
    meal = asof("MEAL", month)
    if bean is None or oil is None or meal is None:
        return None
    return bean, oil, meal
