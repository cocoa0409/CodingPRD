"""The two valuation bases and the loan-to-value covenant (PRD section 3.11)."""
from __future__ import annotations

from decimal import Decimal

import repo
from calc import rhu_int
from db import PRODUCT_TYPES
from errors import ApiError
from services import pricing

CAP_RATE_BPS = 525
STABILIZED_VACANCY_BPS = 500
OPEX_RATIO_BPS = 3400
MAX_LTV_BPS = 6500
BASES = ("TRAILING_ACTUAL", "FORWARD_STABILIZED")


def _bps(amount, bps):
    return rhu_int(Decimal(amount) * Decimal(bps) / Decimal(10000))


def blended_market_rent_cents(community):
    """Planned counts weighted by the published asking rent for each product type."""
    weighted = 0
    for product_type in PRODUCT_TYPES:
        planned = community["product_mix"].get(product_type, 0)
        if planned <= 0:
            continue
        schedule = pricing.published_schedule(community, product_type)
        if schedule is None:
            raise ApiError("ERR_NO_PUBLISHED_RENT_SCHEDULE")
        weighted += planned * schedule["asking_rent_cents"]
    return rhu_int(Decimal(weighted) / Decimal(community["total_planned_units"]))


def valuation(community, basis):
    leases = repo.leases_of_community(community)
    if basis == "TRAILING_ACTUAL":
        # The conservative lender view: concessions burden the income.
        in_place = sum(l["gross_monthly_charge_cents"] - l["monthly_concession_credit_cents"]
                       for l in leases if l["lease_status"] == "ACTIVE")
        pro_forma = 0
        annual_gross = (in_place + pro_forma) * 12
        vacancy = 0
        egi = annual_gross - community["construction_impact_credit_cents"]
    else:
        # The sponsor view: unburdened gross plus a blended pro forma on vacancy.
        in_place = sum(l["gross_monthly_charge_cents"] for l in leases
                       if l["lease_status"] in ("EXECUTED", "ACTIVE"))
        blended = blended_market_rent_cents(community)
        pro_forma = (community["total_planned_units"] - community["leased_unit_count"]) * blended
        annual_gross = (in_place + pro_forma) * 12
        vacancy = _bps(annual_gross, STABILIZED_VACANCY_BPS)
        egi = annual_gross - vacancy

    opex = _bps(egi, OPEX_RATIO_BPS)
    noi = egi - opex
    value = rhu_int(Decimal(noi) * Decimal(10000) / Decimal(CAP_RATE_BPS))
    commitment = community["facility_commitment_cents"]
    if value > 0:
        ltv = rhu_int(Decimal(commitment) * Decimal(10000) / Decimal(value))
    elif commitment == 0:
        # Nothing borrowed against nothing: the covenant cannot be breached.
        ltv = 0
    else:
        # A positive commitment against no value is a definite breach.
        ltv = 999999999
    return {
        "basis": basis,
        "in_place_monthly_cents": in_place,
        "pro_forma_monthly_cents": pro_forma,
        "annual_gross_cents": annual_gross,
        "vacancy_deduction_cents": vacancy,
        "egi_cents": egi,
        "opex_cents": opex,
        "noi_cents": noi,
        "value_cents": value,
        "loan_to_value_bps": ltv,
        "covenant_satisfied": ltv <= MAX_LTV_BPS,
    }


def trailing_ltv_bps(community, commitment_cents):
    """The trailing-actual loan-to-value every covenant test in the spec uses,
    measured against a candidate commitment."""
    saved = community["facility_commitment_cents"]
    community["facility_commitment_cents"] = commitment_cents
    try:
        return valuation(community, "TRAILING_ACTUAL")["loan_to_value_bps"]
    finally:
        community["facility_commitment_cents"] = saved
