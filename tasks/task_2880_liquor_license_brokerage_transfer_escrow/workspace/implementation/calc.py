"""Calculation rules (PRD 2.6, 2.10, 3.2, 3.3, 3.4, 3.6, 3.8, 3.9)."""

from decimal import Decimal, ROUND_HALF_UP

from store import add_months, db

# --- constants -------------------------------------------------------------
COUNTED_STATUSES = ("ACTIVE", "IN_ESCROW", "SAFEKEEPING", "TRANSFERRED")

TIER_3_MIN_BPS, TIER_3_UPLIFT_BPS = 9000, 2500
TIER_2_MIN_BPS, TIER_2_UPLIFT_BPS = 7500, 1200
TIER_1_MIN_BPS, TIER_1_UPLIFT_BPS = 5000, 500

COMP_FLOOR_CENTS = 4500000
AGR_MULTIPLE_BPS = 1800

REVOCATION_PENALTY = 25
REVOCATION_PENALTY_CAP_COUNT = 2
FELONY_PENALTY = 30
NO_CITIZENSHIP_PENALTY = 20
NONRESIDENT_PENALTY = 10
CUP_OUTSTANDING_PENALTY = 15
LANDLORD_OUTSTANDING_PENALTY = 15
QUALIFIED_MIN_SCORE = 70
PROVISIONAL_MIN_SCORE = 50
DISQUALIFYING_REVOCATIONS = 2

DEPOSIT_FLOOR_CENTS = 500000
DEPOSIT_CAP_CENTS = 7500000
EFFECTIVE_BPS_CAP = 3500
SCARCITY_DIVISOR = 5
CLASS_SURCHARGE_BPS = {
    "CLASS_47_ONSALE_GENERAL": 300,
    "CLASS_21_OFFSALE_GENERAL": 200,
    "CLASS_41_ONSALE_BEER_WINE": 0,
}

FILING_BASE_CENTS = 30000
POSTING_FEE_CENTS = 15000
RESUBMIT_FEE_CENTS = 30000
CLASS_FEE_CENTS = {
    "CLASS_47_ONSALE_GENERAL": 120000,
    "CLASS_21_OFFSALE_GENERAL": 90000,
    "CLASS_41_ONSALE_BEER_WINE": 45000,
}
EXPEDITE_TIER_2_MIN_CENTS = 200000
EXPEDITE_TIER_1_MIN_CENTS = 120000

DUAL_AGENCY_SPLIT_BPS = 4000

POSTING_QUIET_BUFFER_DAYS = 30

NONUSE_GRACE_DAYS = 180
SAFEKEEPING_INITIAL_MAX_MONTHS = 12
EXTENSION_MAX_MONTHS = 6
MAX_EXTENSIONS = 2
SAFEKEEPING_BASE_FEE_CENTS = 20000

MAX_DEFICIENCY_ROUNDS = 2


def rhu(value):
    """Round half up (away from zero) to a whole cent / integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def D(value):
    return Decimal(value)


# --- county quota position (PRD 2.10) --------------------------------------
def county_quota_position(county):
    county_id = county["id"]
    counted = 0
    in_escrow = 0
    for lic in db.licenses.values():
        if lic["county_id"] != county_id:
            continue
        if lic["counts_against_quota"] and lic["status"] in COUNTED_STATUSES:
            counted += 1
        if lic["status"] == "IN_ESCROW":
            in_escrow += 1
    total = county["quota_licenses_total"]
    county["quota_licenses_counted"] = counted
    county["quota_available"] = max(0, total - counted)
    if total == 0:
        county["quota_utilization_bps"] = 10000
    else:
        county["quota_utilization_bps"] = rhu(D(counted * 10000) / D(total))
    county["escrow_committed_count"] = in_escrow
    return county


def quota_scarcity_multiplier(county):
    u = county["quota_utilization_bps"]
    if u >= TIER_3_MIN_BPS:
        return TIER_3_UPLIFT_BPS
    if u >= TIER_2_MIN_BPS:
        return TIER_2_UPLIFT_BPS
    if u >= TIER_1_MIN_BPS:
        return TIER_1_UPLIFT_BPS
    return 0


# --- listing market valuation (PRD 3.3) -----------------------------------
def comparable_set(subject):
    prices = []
    for lic in db.licenses.values():
        if lic["id"] == subject["id"]:
            continue
        if lic["county_id"] != subject["county_id"]:
            continue
        if lic["license_class"] != subject["license_class"]:
            continue
        if lic.get("last_transfer_price_cents") is None:
            continue
        if lic["status"] not in COUNTED_STATUSES:
            continue
        prices.append(lic["last_transfer_price_cents"])
    prices.sort()
    return prices


def comparable_median(prices):
    n = len(prices)
    if n == 0:
        return COMP_FLOOR_CENTS
    if n % 2 == 1:
        return prices[(n - 1) // 2]
    return rhu(D(prices[n // 2 - 1] + prices[n // 2]) / D(2))


def comparable_sales_price(comp_median_cents, scarcity_bps):
    return rhu(D(comp_median_cents) * D(10000 + scarcity_bps) / D(10000))


def income_multiple_price(annual_gross_receipts_cents, scarcity_bps):
    exact = (D(annual_gross_receipts_cents) * D(AGR_MULTIPLE_BPS) / D(10000)
             * D(10000 + scarcity_bps) / D(10000))
    return rhu(exact)


def listing_market_valuation(subject_license, county, basis):
    scarcity_bps = quota_scarcity_multiplier(county)
    prices = comparable_set(subject_license)
    median = comparable_median(prices)
    comp_price = comparable_sales_price(median, scarcity_bps)
    income_price = income_multiple_price(subject_license["annual_gross_receipts_cents"], scarcity_bps)
    return {
        "comp_count": len(prices),
        "comp_median_cents": median,
        "scarcity_bps": scarcity_bps,
        "comparable_sales_price_cents": comp_price,
        "income_multiple_price_cents": income_price,
        "market_price_cents": comp_price if basis == "COMPARABLE_SALES" else income_price,
        "divergence_cents": income_price - comp_price,
    }


# --- buyer qualification (PRD 3.2) ---------------------------------------
def buyer_qualification_score(buyer, premises, county, mode):
    base = 100
    base -= REVOCATION_PENALTY * min(buyer["prior_revocation_count"], REVOCATION_PENALTY_CAP_COUNT)
    if buyer["felony_disclosure"]:
        base -= FELONY_PENALTY
    if not buyer["citizenship_verified"]:
        base -= NO_CITIZENSHIP_PENALTY
    if buyer["residency_state"] != county["state_code"]:
        base -= NONRESIDENT_PENALTY
    premises_component = 0
    if mode == "FINAL_REVIEW":
        if premises["conditional_use_permit_status"] not in ("NOT_REQUIRED", "GRANTED"):
            premises_component -= CUP_OUTSTANDING_PENALTY
        if premises["landlord_consent_status"] not in ("NOT_REQUIRED", "GRANTED"):
            premises_component -= LANDLORD_OUTSTANDING_PENALTY
    score = max(0, min(100, base + premises_component))
    if (buyer["prior_revocation_count"] >= DISQUALIFYING_REVOCATIONS
            or (buyer["felony_disclosure"] and not buyer["citizenship_verified"])):
        status = "DISQUALIFIED"
    elif score >= QUALIFIED_MIN_SCORE:
        status = "QUALIFIED"
    elif score >= PROVISIONAL_MIN_SCORE:
        status = "PROVISIONALLY_QUALIFIED"
    else:
        status = "UNQUALIFIED"
    return score, status


def buyer_is_qualified(buyer):
    return (buyer.get("qualification_status") in ("QUALIFIED", "PROVISIONALLY_QUALIFIED")
            and buyer.get("qualification_mode") == "FINAL_REVIEW")


# --- premises suitability (PRD 3.2) --------------------------------------
def premises_suitability(premises, county):
    if premises["distance_to_nearest_school_feet"] < county["distance_min_feet_school"]:
        return "UNSUITABLE", "SCHOOL_DISTANCE"
    if premises["distance_to_nearest_church_feet"] < county["distance_min_feet_church"]:
        return "UNSUITABLE", "CHURCH_DISTANCE"
    if premises["conditional_use_permit_status"] == "DENIED":
        return "UNSUITABLE", "CUP_DENIED"
    if premises["zoning_code"] not in county["permitted_zoning_codes"]:
        return "UNSUITABLE", "ZONING_NOT_PERMITTED"
    if premises["landlord_consent_status"] == "REFUSED":
        return "UNSUITABLE", "LANDLORD_REFUSED"
    if premises["conditional_use_permit_status"] in ("REQUIRED_NOT_FILED", "PENDING"):
        return "CONDITIONAL", "CUP_OUTSTANDING"
    if premises["census_tract_undue_concentration"]:
        return "CONDITIONAL", "UNDUE_CONCENTRATION"
    if premises["landlord_consent_status"] == "PENDING":
        return "CONDITIONAL", "LANDLORD_PENDING"
    return "SUITABLE", "NONE"


def apply_suitability(premises, county):
    status, reason = premises_suitability(premises, county)
    premises["suitability_status"] = status
    premises["suitability_reason_code"] = reason
    return premises


def distances_ok(premises, county):
    return (premises["distance_to_nearest_school_feet"] >= county["distance_min_feet_school"]
            and premises["distance_to_nearest_church_feet"] >= county["distance_min_feet_church"])


# --- escrow deposit requirement (PRD 3.4) --------------------------------
def escrow_deposit_requirement(purchase_price_cents, deposit_pct_bps, license_class,
                               scarcity_bps_at_activation):
    class_sur = CLASS_SURCHARGE_BPS.get(license_class, 0)
    scarcity = int(scarcity_bps_at_activation or 0)
    contribution = scarcity // SCARCITY_DIVISOR
    effective_bps = min(EFFECTIVE_BPS_CAP, deposit_pct_bps + class_sur + contribution)
    raw = D(purchase_price_cents) * D(effective_bps) / D(10000)
    rounded = rhu(raw)
    return max(DEPOSIT_FLOOR_CENTS, min(DEPOSIT_CAP_CENTS, rounded))


# --- transfer filing fee (PRD 3.6) --------------------------------------
def transfer_filing_fee(license_class, deficiency_round_count):
    subtotal = (FILING_BASE_CENTS + CLASS_FEE_CENTS.get(license_class, 0)
                + POSTING_FEE_CENTS + RESUBMIT_FEE_CENTS * int(deficiency_round_count))
    if subtotal >= EXPEDITE_TIER_2_MIN_CENTS:
        surcharge_bps = 800
    elif subtotal >= EXPEDITE_TIER_1_MIN_CENTS:
        surcharge_bps = 500
    else:
        surcharge_bps = 200
    return subtotal + rhu(D(subtotal) * D(surcharge_bps) / D(10000))


# --- commission disbursement (PRD 3.8) ----------------------------------
def commission_disbursement(purchase_price_cents, commission_rate_bps, commission_mode,
                            transfer_fee_bps, escrow_balance_cents):
    gross = D(purchase_price_cents) * D(commission_rate_bps) / D(10000)
    if commission_mode == "DUAL_AGENCY":
        seller_side = rhu(gross * D(10000 - DUAL_AGENCY_SPLIT_BPS) / D(10000))
        buyer_side = rhu(gross * D(DUAL_AGENCY_SPLIT_BPS) / D(10000))
        commission_total = seller_side + buyer_side
    else:
        seller_side = rhu(gross)
        buyer_side = 0
        commission_total = seller_side
    county_fee = rhu(D(purchase_price_cents) * D(transfer_fee_bps) / D(10000))
    seller_net = escrow_balance_cents - county_fee - commission_total
    return {
        "seller_side_line_cents": seller_side,
        "buyer_side_line_cents": buyer_side,
        "commission_total_cents": commission_total,
        "county_transfer_fee_cents": county_fee,
        "seller_net_cents": seller_net,
    }


# --- safekeeping grant (PRD 3.9) ---------------------------------------
def safekeeping_fee(extension_index):
    return SAFEKEEPING_BASE_FEE_CENTS * (2 ** int(extension_index))


def safekeeping_window(effective_from, granted_months):
    return add_months(effective_from, granted_months)
