"""Pure calculation rules (PRD sections 2.5, 3.2, 3.3, 3.5, 3.7, 3.8, 3.9)."""
from decimal import Decimal, ROUND_HALF_UP

import clock

ZERO = Decimal("0.00")
HUNDRED = Decimal("100")
SUBSTANTIALLY_ALL_THRESHOLD = Decimal("85.00")
FTE_HOURS_PER_YEAR = Decimal("2080")

RECAPTURE_LADDER_BPS = {1: 500, 2: 1000, 3: 1500, 4: 2100, 5: 2700, 6: 3300, 7: 3900}
RECAPTURE_INTEREST_BPS_PER_YEAR = 300
CDE_ASSET_MANAGEMENT_FEE_BPS = 50
COMPLIANCE_PERIOD_DAYS = 2555
OPTION_WINDOW_DAYS = 90
CURE_WINDOW_DAYS = 180
YEAR_DAYS = 365
PUT_PRICE_CENTS = 100000
CALL_PRICE_FLOOR_CENTS = 100000
CALL_PRICE_BPS = 250
QALICB_BUFFER_DAYS = 30


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents_from_bps(base_cents, bps):
    """Convert a basis-point rate on a cent base into whole cents, round half-up."""
    return int(round_half_up(Decimal(base_cents) * Decimal(bps) / Decimal(10000), 0))


def pct(numerator, denominator):
    """100 * numerator / denominator rounded half-up to 2 places; 0.00 on a zero base."""
    if denominator is None or Decimal(denominator) == 0:
        return ZERO
    return round_half_up(HUNDRED * Decimal(numerator) / Decimal(denominator), 2)


# --- census tract distress profile (PRD 3.2) -------------------------------

def tract_profile(poverty_rate_pct, mfi_ratio_pct, unemployment_ratio, contiguous_lic_tract_id):
    is_lic = poverty_rate_pct >= Decimal("20.00") or mfi_ratio_pct <= Decimal("80.00")
    by_contiguity = (
        (not is_lic)
        and contiguous_lic_tract_id is not None
        and poverty_rate_pct >= Decimal("15.00")
    )
    eligible = bool(is_lic or by_contiguity)

    severe_count = 0
    if poverty_rate_pct >= Decimal("30.00"):
        severe_count += 1
    if mfi_ratio_pct <= Decimal("60.00"):
        severe_count += 1
    if unemployment_ratio >= Decimal("1.50"):
        severe_count += 1

    poverty_factor = _clamp01(poverty_rate_pct / Decimal("30.00"))
    income_factor = _clamp01(max(ZERO, Decimal("80.00") - mfi_ratio_pct) / Decimal("20.00"))
    unemployment_factor = _clamp01(
        max(ZERO, unemployment_ratio - Decimal("1.00")) / Decimal("0.50")
    )
    raw = (
        Decimal(40) * poverty_factor
        + Decimal(35) * income_factor
        + Decimal(25) * unemployment_factor
    )
    score = min(Decimal("100.00"), round_half_up(raw, 2))

    if not eligible:
        tier = "INELIGIBLE"
    elif severe_count >= 2 and score >= Decimal("75.00"):
        tier = "SEVERE"
    elif severe_count >= 1 and score >= Decimal("50.00"):
        tier = "HIGH"
    else:
        tier = "MODERATE"

    return {
        "is_low_income_community": bool(is_lic),
        "qualifies_by_contiguity": bool(by_contiguity),
        "eligible_for_qlici": eligible,
        "severe_criteria_met_count": severe_count,
        "distress_score": round_half_up(score, 2),
        "distress_tier": tier,
    }


def _clamp01(value):
    if value < 0:
        return Decimal(0)
    if value > 1:
        return Decimal(1)
    return value


# --- six-prong eligibility test (PRD 3.3) ---------------------------------

PRONG_ORDER = (
    "LOCATION",
    "GROSS_INCOME",
    "SERVICES",
    "TANGIBLE_PROPERTY",
    "COLLECTIBLES",
    "NQFP",
)


def eligibility_result(location_prong_passed, gross_income_lic_pct, services_lic_pct,
                       tangible_property_lic_pct, collectibles_pct,
                       nonqualified_financial_property_pct):
    outcomes = {
        "LOCATION": bool(location_prong_passed),
        "GROSS_INCOME": gross_income_lic_pct >= Decimal("50.00"),
        "SERVICES": services_lic_pct >= Decimal("40.00"),
        "TANGIBLE_PROPERTY": tangible_property_lic_pct >= Decimal("40.00"),
        "COLLECTIBLES": collectibles_pct <= Decimal("5.00"),
        "NQFP": nonqualified_financial_property_pct <= Decimal("5.00"),
    }
    failed = [name for name in PRONG_ORDER if not outcomes[name]]
    return ("PASS" if not failed else "FAIL"), failed


# --- qualified equity investment reserves (PRD 3.4) -----------------------

def reserve_bps_for(gross_cents):
    if gross_cents < 500000000:
        return 500
    if gross_cents < 1500000000:
        return 400
    return 300


# --- recapture exposure (PRD 3.8) -----------------------------------------

def recapture_exposure_cents(gross_cents, completed_years):
    bps = RECAPTURE_LADDER_BPS.get(completed_years)
    if not completed_years or bps is None:
        return 0
    claimed = cents_from_bps(gross_cents, bps)
    interest = int(round_half_up(
        Decimal(claimed) * Decimal(RECAPTURE_INTEREST_BPS_PER_YEAR)
        * Decimal(completed_years) / Decimal(10000), 0))
    return claimed + interest


# --- unwind pricing (PRD 3.9) --------------------------------------------

def call_price_cents(residual_cents, accrued_unpaid_fee_cents):
    base = max(0, residual_cents)
    priced = cents_from_bps(base, CALL_PRICE_BPS)
    net = priced - accrued_unpaid_fee_cents
    return max(CALL_PRICE_FLOOR_CENTS, net)


# --- asset-management fee waterfall (PRD 3.8) ----------------------------

def fee_allocation(fee_total_cents, targets):
    """targets: rows ordered by created_at ascending. Returns {qlici_id: share}."""
    basis = sum(t["principal_cents"] for t in targets)
    if not targets or basis == 0:
        return {}, basis
    shares = {}
    for target in targets:
        shares[target["id"]] = int(round_half_up(
            Decimal(fee_total_cents) * Decimal(target["principal_cents"]) / Decimal(basis), 0))
    residual = fee_total_cents - sum(shares.values())
    if residual != 0:
        chosen = sorted(
            targets,
            key=lambda t: (-t["outstanding_principal_cents"], t["created_at"], t["_seq"]),
        )[0]
        shares[chosen["id"]] = shares[chosen["id"]] + residual
    return shares, basis


# --- job quality certification (PRD 3.7) ---------------------------------

def job_quality(reports, measurement_basis, target_fte_count, local_hire_pct_target):
    wage_passing = [r for r in reports if r["wage_floor_met"]]
    if measurement_basis == "HEADCOUNT":
        achieved = Decimal(sum(r["qualifying_headcount"] for r in wage_passing))
        achieved_out = int(achieved)
    else:
        total_hours = Decimal(sum(r["qualifying_hours"] for r in wage_passing))
        achieved = round_half_up(total_hours / FTE_HOURS_PER_YEAR, 2)
        achieved_out = achieved
    compliance_pct = pct(achieved, Decimal(target_fte_count))
    total_headcount = sum(r["headcount"] for r in reports)
    local_hires = sum(r["local_hires"] for r in reports)
    local_hire_pct = pct(local_hires, total_headcount) if total_headcount else ZERO

    if compliance_pct >= Decimal("100.00") and local_hire_pct >= local_hire_pct_target:
        classification = "CERTIFIED"
    elif (Decimal("80.00") <= compliance_pct < Decimal("100.00")
          and local_hire_pct >= local_hire_pct_target):
        classification = "CURE_REQUIRED"
    else:
        classification = "SHORTFALL"

    return {
        "achieved_fte": achieved_out,
        "compliance_pct": compliance_pct,
        "local_hire_pct": local_hire_pct,
        "classification": classification,
        "report_count": len(reports),
        "excluded_wage_failing_report_count": len(reports) - len(wage_passing),
    }


# --- compliance-year windows (PRD 2.4) -----------------------------------

def compliance_window(issued_at, year):
    start = clock.plus_days(issued_at, YEAR_DAYS * (year - 1))
    end = clock.plus_days(issued_at, YEAR_DAYS * year)
    return start, end
