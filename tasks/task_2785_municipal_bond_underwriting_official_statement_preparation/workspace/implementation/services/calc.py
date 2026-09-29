"""The eight calculations of scaffold 1.3 / PRD 3.

Every monetary and rate figure is Decimal; rounding is ROUND_HALF_UP and the
rounding order is pinned exactly as the specification describes.
"""
from decimal import Decimal, getcontext

import lookup
from validation import dec, q2, q3, q4, floor_to_multiple

getcontext().prec = 60

REDEMPTION_AT_MATURITY_PCT = Decimal("100.000")
SEMIANNUAL_PERIODS_PER_YEAR = Decimal(2)
BOND_DENOMINATION_USD = Decimal(1000)
MIN_DENOMINATION_USD = Decimal(5000)
BPS_DENOMINATOR = Decimal(10000)
ONE_EIGHTH_ALLOWANCE_PCT = Decimal("0.125")
ARBITRAGE_DAY_COUNT_BASIS = Decimal(360)
DISCLOSURE_RISK_GATE = 40

LATE_ANNUAL_FILING_WEIGHT = 12
LATE_EVENT_NOTICE_WEIGHT = 8
MATERIAL_EVENT_WEIGHT = 25
ENTITY_TYPE_SURCHARGE = {
    "CITY": 5,
    "COUNTY": 5,
    "SCHOOL_DISTRICT": 10,
    "AUTHORITY": 15,
    "STATE": 0,
}

ORDER_PRIORITY_TIERS = {
    "RETAIL": 1,
    "INSTITUTIONAL_PRIORITY": 2,
    "MEMBER": 3,
    "STOCK": 4,
}


def issuer_disclosure_risk_score(entity_type, late_annual, late_event, material_event):
    raw = (
        LATE_ANNUAL_FILING_WEIGHT * late_annual
        + LATE_EVENT_NOTICE_WEIGHT * late_event
        + (MATERIAL_EVENT_WEIGHT if material_event else 0)
        + ENTITY_TYPE_SURCHARGE.get(entity_type, 0)
    )
    return min(100, max(0, raw))


def _present_value(rate, periods):
    return (Decimal(1) + rate) ** (-int(periods))


def _price(coupon_rate_pct, yield_pct, periods, redemption_pct):
    i = dec(yield_pct) / Decimal(200)
    c = dec(coupon_rate_pct) / SEMIANNUAL_PERIODS_PER_YEAR
    v = _present_value(i, periods)
    annuity = (Decimal(1) - v) / i
    return q3(c * annuity + dec(redemption_pct) * v)


def tranche_reoffering_price(tranche):
    """calculations.tranche_reoffering_price - yield-to-worst selection."""
    price_to_maturity = _price(
        tranche["coupon_rate_pct"],
        tranche["yield_pct"],
        tranche["periods_to_maturity"],
        REDEMPTION_AT_MATURITY_PCT,
    )
    price_to_call = None
    if tranche["is_callable"]:
        price_to_call = _price(
            tranche["coupon_rate_pct"],
            tranche["yield_pct"],
            tranche["periods_to_call"],
            tranche["call_price_pct"],
        )
    if price_to_call is not None and price_to_call < price_to_maturity:
        reoffering = price_to_call
        priced_to_call = True
    else:
        reoffering = price_to_maturity
        priced_to_call = False
    return {
        "price_to_maturity_pct": price_to_maturity,
        "price_to_call_pct": price_to_call,
        "reoffering_price_pct": reoffering,
        "is_priced_to_call": priced_to_call,
    }


def issue_price_total(tranches):
    """Rounded per tranche in ascending sequence_number, then summed."""
    total = Decimal("0.00")
    for tranche in tranches:
        total += q2(
            dec(tranche["principal_amount_usd"]) / Decimal(100)
            * dec(tranche["reoffering_price_pct"])
        )
    return q2(total)


def negotiated_gross_spread_total(tranches, takedown, management_fee, expenses):
    component = dec(takedown) + dec(management_fee) + dec(expenses)
    total = Decimal("0.00")
    for tranche in tranches:
        bonds = dec(tranche["principal_amount_usd"]) / BOND_DENOMINATION_USD
        total += q2(bonds * component)
    return q2(total)


def competitive_gross_spread_total(par_amount, winning_bid_price_pct, issue_price):
    bid_proceeds = q2(dec(par_amount) * dec(winning_bid_price_pct) / Decimal(100))
    return q2(dec(issue_price) - bid_proceeds)


def gross_spread_per_bond(gross_spread_total, par_amount):
    bonds = dec(par_amount) / BOND_DENOMINATION_USD
    if bonds == 0:
        return q3(Decimal(0))
    return q3(dec(gross_spread_total) / bonds)


def tranche_debt_service(tranche):
    principal = dec(tranche["principal_amount_usd"])
    return q2(
        principal
        + principal
        * dec(tranche["coupon_rate_pct"])
        / Decimal(100)
        / SEMIANNUAL_PERIODS_PER_YEAR
        * Decimal(int(tranche["periods_to_maturity"]))
    )


def insured_debt_service(tranches):
    """Rounded per tranche in ascending sequence_number, then summed."""
    total = Decimal("0.00")
    for tranche in tranches:
        total += tranche_debt_service(tranche)
    return q2(total)


def enhancement_premium(insured_debt_service_usd, premium_bps):
    return q2(dec(insured_debt_service_usd) * dec(premium_bps) / BPS_DENOMINATOR)


def net_proceeds(issue_price, gross_spread_total, premium):
    return q2(dec(issue_price) - dec(gross_spread_total) - dec(premium))


def arbitrage_yield(tranches):
    weighted = Decimal(0)
    total_bond_years = Decimal(0)
    for tranche in tranches:
        bond_years = (
            dec(tranche["principal_amount_usd"]) / BOND_DENOMINATION_USD
            * Decimal(int(tranche["periods_to_maturity"]))
            / SEMIANNUAL_PERIODS_PER_YEAR
        )
        total_bond_years += bond_years
        weighted += dec(tranche["yield_pct"]) * bond_years
    if total_bond_years == 0:
        return q4(Decimal(0))
    return q4(weighted / total_bond_years)


def permitted_investment_yield(arbitrage_yield_pct):
    return q4(dec(arbitrage_yield_pct) + ONE_EIGHTH_ALLOWANCE_PCT)


def excess_earnings(unspent_proceeds, projected_yield, permitted_yield, investment_days):
    return q2(
        dec(unspent_proceeds)
        * (dec(projected_yield) - dec(permitted_yield))
        / Decimal(100)
        * dec(investment_days)
        / ARBITRAGE_DAY_COUNT_BASIS
    )


def order_sort_key(order):
    return (order["submitted_at"], order["created_at"], order["_seq"])


def allot_tranche(tranche, period, all_orders_on_tranche):
    """Run the priority-of-orders waterfall for one tranche of one closing period.

    Mutates only the candidate orders' par_allotted_usd / status fields and
    returns the list of candidates that were touched.
    """
    other_period_allotted = Decimal(0)
    for order in all_orders_on_tranche:
        if order["order_period_id"] == period["id"]:
            continue
        if order["status"] in ("ALLOTTED", "PARTIALLY_ALLOTTED"):
            other_period_allotted += dec(order["par_allotted_usd"])
    available = dec(tranche["principal_amount_usd"]) - other_period_allotted
    if available < 0:
        available = Decimal(0)

    candidates = [
        order
        for order in all_orders_on_tranche
        if order["order_period_id"] == period["id"] and order["status"] == "PENDING"
    ]
    for tier in (1, 2, 3, 4):
        group = sorted(
            [
                order
                for order in candidates
                if ORDER_PRIORITY_TIERS[order["order_type"]] == tier
            ],
            key=order_sort_key,
        )
        if not group:
            continue
        tier_demand = sum((dec(order["par_requested_usd"]) for order in group), Decimal(0))
        if tier_demand <= available:
            for order in group:
                order["par_allotted_usd"] = dec(order["par_requested_usd"])
            available -= tier_demand
        else:
            for order in group:
                raw = available * dec(order["par_requested_usd"]) / tier_demand
                order["par_allotted_usd"] = floor_to_multiple(raw, MIN_DENOMINATION_USD)
            remainder = available - sum(
                (dec(order["par_allotted_usd"]) for order in group), Decimal(0)
            )
            while remainder >= MIN_DENOMINATION_USD:
                progressed = False
                for order in group:
                    if remainder < MIN_DENOMINATION_USD:
                        break
                    if dec(order["par_allotted_usd"]) < dec(order["par_requested_usd"]):
                        order["par_allotted_usd"] = (
                            dec(order["par_allotted_usd"]) + MIN_DENOMINATION_USD
                        )
                        remainder -= MIN_DENOMINATION_USD
                        progressed = True
                if not progressed:
                    break
            available = Decimal(0)
    for order in candidates:
        allotted = dec(order["par_allotted_usd"])
        requested = dec(order["par_requested_usd"])
        if allotted == requested:
            order["status"] = "ALLOTTED"
        elif allotted > 0:
            order["status"] = "PARTIALLY_ALLOTTED"
        else:
            order["status"] = "UNFILLED"
    return candidates


def takedown_credit_for_member(member, deal):
    per_bond = deal["takedown_per_bond_usd"]
    if per_bond is None:
        per_bond = Decimal(0)
    orders = [
        order
        for order in lookup.orders_of_deal(deal["id"])
        if order["syndicate_member_id"] == member["id"]
        and order["status"] in ("ALLOTTED", "PARTIALLY_ALLOTTED")
    ]
    orders.sort(key=order_sort_key)
    total = Decimal("0.00")
    for order in orders:
        total += q2(dec(order["par_allotted_usd"]) / BOND_DENOMINATION_USD * dec(per_bond))
    return q2(total)


def liability_par(member, deal):
    return q2(dec(member["liability_pct"]) / Decimal(100) * dec(deal["par_amount_usd"]))
