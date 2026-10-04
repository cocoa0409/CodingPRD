"""Domain services: recomputation, cascades, calculations."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE
import common
from common import parse_iso, round_half_up_int, round_half_up_places

BASIC_ENTITLEMENT_CENTS = 3600000
COUNTY_LIMIT_CENTS = 76655000

RESIDUAL_TABLE = {
    "NORTHEAST": [45000, 75500, 90900, 102500, 106200],
    "MIDWEST": [44100, 73800, 88900, 100300, 103900],
    "SOUTH": [44100, 73800, 88900, 100300, 103900],
    "WEST": [49100, 82300, 99000, 111700, 115800],
}
OVER_FIVE_STEP = 8000

REGIONS = {"NORTHEAST", "MIDWEST", "SOUTH", "WEST"}
BRANCHES = {"ARMY", "NAVY", "AIR_FORCE", "MARINES", "COAST_GUARD", "SPACE_FORCE"}
DISCHARGE_CHARS = {"HONORABLE", "GENERAL", "OTHER_THAN_HONORABLE", "BAD_CONDUCT", "DISHONORABLE"}
SERVICE_CATEGORIES = {"REGULAR_MILITARY", "RESERVES_NATIONAL_GUARD"}
ENTITLEMENT_CODES = {"ERA_WWII", "ERA_KOREA", "ERA_VIETNAM", "ERA_PEACETIME", "ERA_GULF", "RESTORED", "UNREIMBURSED_SURVIVING_SPOUSE"}
PURPOSES = {"PURCHASE", "IRRRL", "CASH_OUT_REFINANCE"}
RATE_TYPES = {"FIXED", "ARM"}
PAYOFF_TYPES = {"SALE", "REFINANCE_PAYOFF"}
REFI_TYPES = {"IRRRL", "CASH_OUT"}
RESTORATION_TYPES = {"SALE_PAYOFF", "REFINANCE_PAYOFF", "ONE_TIME_RESTORATION"}


# ---------------------------------------------------------------------------
# Veteran-derived computations
# ---------------------------------------------------------------------------

def recompute_veteran_totals(veteran):
    periods = [p for p in STORE.service_periods.values() if p["veteran_id"] == veteran["id"]]
    veteran["total_qualifying_service_days"] = sum(p["qualifying_days"] for p in periods)
    veteran["has_issued_coe"] = any(
        c["veteran_id"] == veteran["id"] and c["status"] == "ISSUED"
        for c in STORE.coes.values()
    )
    veteran["charged_loan_count"] = compute_charged_loan_count(veteran["id"])
    return veteran


def compute_charged_loan_count(veteran_id):
    count = 0
    for loan in STORE.loans.values():
        if loan["veteran_id"] != veteran_id:
            continue
        if loan["entitlement_charged_cents"] <= 0:
            continue
        if loan["closing_status"] not in ("CLOSED", "PAID_IN_FULL"):
            continue
        if loan.get("_charge_fully_restored"):
            continue
        count += 1
    return count


def refresh_restoration_flags(veteran_id):
    """Mark loans whose charge has been fully restored."""
    restored_by_loan = {}
    for r in STORE.restoration_requests.values():
        if r["veteran_id"] == veteran_id and r["status"] == "GRANTED":
            restored_by_loan[r["loan_id"]] = restored_by_loan.get(r["loan_id"], 0) + r["restored_amount_cents"]
    # Assumption substitution restores the seller's charge on that loan.
    for a in STORE.assumption_requests.values():
        if a["status"] == "APPROVED" and a.get("substitute_entitlement"):
            loan = STORE.loans.get(a["loan_id"])
            if loan and loan["veteran_id"] == veteran_id:
                restored_by_loan[a["loan_id"]] = restored_by_loan.get(a["loan_id"], 0) + loan["entitlement_charged_cents"]
    for loan in STORE.loans.values():
        if loan["veteran_id"] != veteran_id:
            continue
        charged = loan["entitlement_charged_cents"]
        loan["_charge_fully_restored"] = charged > 0 and restored_by_loan.get(loan["id"], 0) >= charged


def recompute_entitlement_account(veteran_id):
    acct = None
    for a in STORE.entitlement_accounts.values():
        if a["veteran_id"] == veteran_id:
            acct = a
            break
    if acct is None:
        return None
    in_use = acct["total_charged_cents"] - acct["total_restored_cents"]
    acct["remaining_base_cents"] = max(0, BASIC_ENTITLEMENT_CENTS - in_use)
    acct["remaining_with_bonus_cents"] = max(0, COUNTY_LIMIT_CENTS // 4 - in_use)
    return acct


def get_account_for_veteran(veteran_id):
    for a in STORE.entitlement_accounts.values():
        if a["veteran_id"] == veteran_id:
            return a
    return None


# ---------------------------------------------------------------------------
# Funding fee calculation
# ---------------------------------------------------------------------------

def compute_down_payment_pct(down_payment_cents, purchase_price_cents):
    if purchase_price_cents == 0:
        return Decimal("0.0000")
    pct = (Decimal(down_payment_cents) * Decimal(100)) / Decimal(purchase_price_cents)
    return round_half_up_places(pct, 4)


def compute_funding_fee(veteran, loan_use, purpose, down_payment_cents, purchase_price_cents, loan_amount_cents):
    """Returns (exempt, fee_rate_decimal, assessed_fee_cents)."""
    if veteran.get("receives_disability_compensation") or veteran.get("is_surviving_spouse"):
        return True, Decimal("0"), 0
    dp_pct = compute_down_payment_pct(down_payment_cents, purchase_price_cents)
    if purpose == "IRRRL":
        fee_rate = Decimal("0.50")
    elif purpose == "CASH_OUT_REFINANCE":
        fee_rate = Decimal("2.15") if loan_use == "FIRST_USE" else Decimal("3.30")
    else:  # PURCHASE
        five = Decimal("5.0000")
        ten = Decimal("10.0000")
        if loan_use == "FIRST_USE":
            if dp_pct < five:
                fee_rate = Decimal("2.15")
            elif dp_pct < ten:
                fee_rate = Decimal("1.50")
            else:
                fee_rate = Decimal("1.25")
        else:
            if dp_pct < five:
                fee_rate = Decimal("3.30")
            elif dp_pct < ten:
                fee_rate = Decimal("1.50")
            else:
                fee_rate = Decimal("1.25")
    raw = Decimal(loan_amount_cents) * fee_rate / Decimal(100)
    # Truncate DOWN to whole dollars: floor to 100 cents.
    fee_dollars = int(raw // 100)
    assessed = fee_dollars * 100
    return False, fee_rate, assessed


# ---------------------------------------------------------------------------
# Underwriting calculations
# ---------------------------------------------------------------------------

def compute_other_obligations_monthly(annual_items):
    total = 0
    for item in annual_items:
        monthly = Decimal(item) / Decimal(12)
        total += round_half_up_int(monthly)
    return total


def compute_dti_percent(new_housing_payment_cents, other_obligations_monthly_cents, gross_monthly_income_cents):
    if gross_monthly_income_cents == 0:
        return Decimal("0.00")
    pct = Decimal(100) * Decimal(new_housing_payment_cents + other_obligations_monthly_cents) / Decimal(gross_monthly_income_cents)
    return round_half_up_places(pct, 2)


def residual_required_cents(region, family_size):
    table = RESIDUAL_TABLE[region]
    idx = min(family_size, 5) - 1
    if idx < 0:
        idx = 0
    base = table[idx]
    extra = max(0, family_size - 5) * OVER_FIVE_STEP
    return base + extra


def compute_underwriting_outcome(residual_income_cents, residual_required, dti_percent):
    if residual_income_cents < residual_required:
        return "DENIED"
    if dti_percent <= Decimal("41.00"):
        return "APPROVED"
    threshold = round_half_up_int(Decimal(residual_required) * Decimal("1.2"))
    if residual_income_cents >= threshold:
        return "APPROVED"
    return "DENIED"


# ---------------------------------------------------------------------------
# Appraisal assignment / queue promotion
# ---------------------------------------------------------------------------

def _appraiser_candidates(region):
    cands = []
    for ap in STORE.appraisers.values():
        if not ap.get("active", True):
            continue
        if ap["region"] != region:
            continue
        if ap["open_assignment_count"] < ap["max_open_assignments"]:
            cands.append(ap)
    return cands


def _rank_candidates(cands):
    return sorted(cands, key=lambda a: (a["open_assignment_count"], a["created_at"]))


def try_assign_appraisal(appraisal):
    """Attempt immediate assignment for a REQUESTED appraisal. Returns True if assigned."""
    loan = STORE.loans.get(appraisal["loan_id"])
    if loan is None:
        return False
    cands = _appraiser_candidates(loan["property_region"])
    if not cands:
        return False
    chosen = _rank_candidates(cands)[0]
    appraisal["appraiser_id"] = chosen["id"]
    appraisal["status"] = "ASSIGNED"
    chosen["open_assignment_count"] += 1
    common.touch(appraisal)
    common.touch(chosen)
    return True


def promote_queue_for_appraiser(appraiser):
    """Earliest-created REQUESTED appraisal in the appraiser's region becomes ASSIGNED."""
    if not appraiser.get("active", True):
        return
    if appraiser["open_assignment_count"] >= appraiser["max_open_assignments"]:
        return
    waiting = []
    for ap in STORE.appraisals.values():
        if ap["status"] != "REQUESTED":
            continue
        loan = STORE.loans.get(ap["loan_id"])
        if loan is None:
            continue
        if loan["property_region"] != appraiser["region"]:
            continue
        waiting.append(ap)
    if not waiting:
        return
    waiting.sort(key=lambda a: a["created_at"])
    target = waiting[0]
    target["appraiser_id"] = appraiser["id"]
    target["status"] = "ASSIGNED"
    appraiser["open_assignment_count"] += 1
    common.touch(target)
    common.touch(appraiser)


# ---------------------------------------------------------------------------
# Denial cascade (COE denial and loan underwriting denial)
# ---------------------------------------------------------------------------

def cancel_appraisal_with_cascade(appraisal):
    """Cancel an appraisal; if it was ASSIGNED, free the appraiser slot and promote."""
    if appraisal["status"] not in ("REQUESTED", "ASSIGNED"):
        return
    was_assigned = appraisal["status"] == "ASSIGNED"
    appraiser_id = appraisal.get("appraiser_id")
    appraisal["status"] = "CANCELLED"
    common.touch(appraisal)
    if was_assigned and appraiser_id:
        ap = STORE.appraisers.get(appraiser_id)
        if ap is not None:
            ap["open_assignment_count"] = max(0, ap["open_assignment_count"] - 1)
            common.touch(ap)
            promote_queue_for_appraiser(ap)


def cascade_loan_denied(loan):
    """Cascade for a loan whose underwriting_status just became DENIED."""
    for appraisal in list(STORE.appraisals.values()):
        if appraisal["loan_id"] == loan["id"]:
            cancel_appraisal_with_cascade(appraisal)


def cascade_coe_denied(veteran_id):
    """CASCADE A: deny SUBMITTED loans of the veteran, cancel their appraisals."""
    for loan in list(STORE.loans.values()):
        if loan["veteran_id"] == veteran_id and loan["underwriting_status"] == "SUBMITTED":
            loan["underwriting_status"] = "DENIED"
            common.touch(loan)
            cascade_loan_denied(loan)


# ---------------------------------------------------------------------------
# Loan close helpers
# ---------------------------------------------------------------------------

def loan_has_clearance_blockers(loan_id):
    for appraisal in STORE.appraisals.values():
        if appraisal["loan_id"] != loan_id:
            continue
        for repair in STORE.repair_requirements.values():
            if repair["appraisal_id"] != appraisal["id"]:
                continue
            if repair["required_for_clearance"] and repair["status"] in ("OPEN", "COMPLETED"):
                return True
    return False


def appraisal_has_clearance_blockers(appraisal_id):
    for repair in STORE.repair_requirements.values():
        if repair["appraisal_id"] != appraisal_id:
            continue
        if repair["required_for_clearance"] and repair["status"] in ("OPEN", "COMPLETED"):
            return True
    return False


def loan_has_value_issued_appraisal_covering(loan_id, purchase_price_cents):
    for appraisal in STORE.appraisals.values():
        if appraisal["loan_id"] != loan_id:
            continue
        if appraisal["status"] == "VALUE_ISSUED" and \
                (appraisal.get("appraised_value_cents") or 0) >= purchase_price_cents:
            return True
    return False


# ---------------------------------------------------------------------------
# Refinance calculations
# ---------------------------------------------------------------------------

def amortize_payment_cents(principal_cents, annual_rate_percent, n_months):
    """Level-payment annuity, round half up to whole cents."""
    P = Decimal(principal_cents)
    if annual_rate_percent == 0:
        return round_half_up_int(P / Decimal(n_months))
    r = Decimal(str(annual_rate_percent)) / Decimal(100) / Decimal(12)
    # (1+r)^n with Decimal power via float exponent approximation is unsafe;
    # use repeated multiplication via Decimal ** int (exact for integer exponents).
    factor = (Decimal(1) + r) ** n_months
    payment = P * r * factor / (factor - Decimal(1))
    return round_half_up_int(payment)


def compute_refinance_fee_cents(refi_type, new_base_cents, veteran, loan_use, down_payment_cents, purchase_price_cents):
    if refi_type == "IRRRL":
        raw = Decimal(new_base_cents) * Decimal("0.5") / Decimal(100)
        return int(raw // 100) * 100
    # CASH_OUT uses funding_fee_calc rate (down payment not considered)
    fee_rate = Decimal("2.15") if loan_use == "FIRST_USE" else Decimal("3.30")
    if veteran.get("receives_disability_compensation") or veteran.get("is_surviving_spouse"):
        fee_rate = Decimal("0")
    raw = Decimal(new_base_cents) * fee_rate / Decimal(100)
    return int(raw // 100) * 100


def rate_leg_satisfied(old_rate_type, new_rate_type, old_rate, new_rate):
    reduction = Decimal(str(old_rate)) - Decimal(str(new_rate))
    if old_rate_type == "FIXED" and new_rate_type == "FIXED":
        return reduction >= Decimal("0.50")
    if old_rate_type == "FIXED" and new_rate_type == "ARM":
        return reduction >= Decimal("2.00")
    if old_rate_type == "ARM" and new_rate_type == "FIXED":
        return True
    return reduction >= Decimal("0.50")  # ARM -> ARM
