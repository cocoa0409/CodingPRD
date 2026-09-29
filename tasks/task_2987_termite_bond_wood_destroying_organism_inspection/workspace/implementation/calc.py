"""Domain constants and every calculation rule (PRD 2.8, 2.10, 3.5-3.10).

All money is Decimal.  Rounding is half up and happens only at the steps the
PRD names; intermediates carry full precision.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# --- enum domains ----------------------------------------------------------

STATE_CODES = ("AL", "FL", "GA", "TX", "CA")
CONSTRUCTION_TYPES = ("SLAB", "CRAWLSPACE", "BASEMENT", "PIER_AND_BEAM")
LICENSE_CATEGORIES = ("WDO_INSPECTOR", "TERMITE_APPLICATOR", "FUMIGATION_CERTIFIED")
INSPECTOR_STATUSES = ("ACTIVE", "SUSPENDED", "EXPIRED")
INSPECTION_PURPOSES = ("INITIAL", "RENEWAL", "REAL_ESTATE", "REINSTATEMENT")
INSPECTION_STATUSES = ("DRAFT", "GRAPHED", "SUPERSEDED")
FINDING_TYPES = ("ACTIVE_INFESTATION", "PREVIOUS_TREATMENT_EVIDENCE", "DAMAGE",
                 "CONDUCIVE_CONDITION")
ORGANISMS = ("SUBTERRANEAN_TERMITE", "DRYWOOD_TERMITE", "WOOD_BORING_BEETLE",
             "FUNGUS", "CARPENTER_ANT", "NONE")
CONDUCIVE_CODES = ("WOOD_TO_GROUND", "EXCESS_MOISTURE", "DEBRIS_UNDER_STRUCTURE",
                   "INSUFFICIENT_CLEARANCE", "FAULTY_GRADE", "NONE")
CONDUCIVE_CODES_NO_NONE = tuple(c for c in CONDUCIVE_CODES if c != "NONE")
METHODS = ("LIQUID_BARRIER", "BAIT_STATION", "FUMIGATION")
PRODUCTS = ("FIPRO_9", "IMID_4", "HEXA_BAIT_2", "SULFURYL_F")
PLAN_STATUSES = ("PROPOSED", "APPROVED", "COMPLETED", "ABANDONED")
COVERAGE_TIERS = ("RETREAT_ONLY", "REPAIR_AND_RETREAT")
BOND_STATUSES = ("ACTIVE", "LAPSED", "TERMINATED")
RENEWAL_STATUSES = ("PENDING", "PAID", "VOID")
FORM_CODES = ("NPMA_33", "FL_DACS_13645", "GA_100", "TX_SPCS_TWDIR", "CA_NPCA_1")
REPORT_STATUSES = ("DRAFT", "ISSUED", "AMENDED", "VOID")
AMENDMENT_REASONS = ("SECONDARY_EVIDENCE_ADDED", "INACCESSIBLE_AREA_CLARIFIED",
                     "DAMAGE_SCOPE_REVISED", "CLERICAL_CORRECTION")
STATION_STATUSES = ("INSTALLED", "ACTIVE_HIT", "ESCALATED", "REMOVED")
ACTIVITY_LEVELS = ("NONE", "LIGHT", "MODERATE", "HEAVY")
COMPLIANCE_GRADES = ("ON_TIME", "LATE", "MISSED")
CLAIM_TYPES = ("REPAIR", "RETREAT")
CLAIM_STATUSES = ("SUBMITTED", "UNDER_ADJUDICATION", "APPROVED_REPAIR",
                  "APPROVED_RETREAT_ONLY", "DENIED", "WITHDRAWN")
EXCLUSION_BASES = ("FINDING_LEVEL", "AGGREGATE_PRORATION")
DENIAL_REASONS = ("PRE_EXISTING_DAMAGE", "NO_ELIGIBLE_DAMAGE", "BOND_LAPSED",
                  "OUTSIDE_COVERAGE")
DECISIONS = ("APPROVE_REPAIR", "APPROVE_RETREAT_ONLY", "DENY")

# --- compatibility matrices ------------------------------------------------

METHOD_BY_CONSTRUCTION = {
    "SLAB": ("LIQUID_BARRIER", "BAIT_STATION", "FUMIGATION"),
    "CRAWLSPACE": ("LIQUID_BARRIER", "BAIT_STATION"),
    "BASEMENT": ("BAIT_STATION", "FUMIGATION"),
    "PIER_AND_BEAM": ("LIQUID_BARRIER", "BAIT_STATION", "FUMIGATION"),
}
PRODUCT_BY_METHOD = {
    "LIQUID_BARRIER": ("FIPRO_9", "IMID_4"),
    "BAIT_STATION": ("HEXA_BAIT_2",),
    "FUMIGATION": ("SULFURYL_F",),
}

# --- treatment sizing and quote -------------------------------------------

TIER1_RATE = Decimal("0.42")
TIER2_RATE = Decimal("0.35")
TIER3_RATE = Decimal("0.28")
BASE_FEE = {"LIQUID_BARRIER": Decimal("275.00"), "BAIT_STATION": Decimal("390.00"),
            "FUMIGATION": Decimal("640.00")}
CONSTRUCTION_MULTIPLIER = {"SLAB": Decimal("1.00"), "CRAWLSPACE": Decimal("1.15"),
                           "BASEMENT": Decimal("1.25"), "PIER_AND_BEAM": Decimal("1.10")}
INFESTATION_SURCHARGE_RATE = Decimal("0.12")
METHOD_PRICE_CAP = {"LIQUID_BARRIER": Decimal("4200.00"),
                    "BAIT_STATION": Decimal("3600.00"),
                    "FUMIGATION": Decimal("9800.00")}
TRENCH_GAL_PER_LF = {"SLAB": Decimal("1.0"), "CRAWLSPACE": Decimal("1.5"),
                     "BASEMENT": Decimal("2.0"), "PIER_AND_BEAM": Decimal("1.25")}
SLAB_DRILL_GAL_PER_100_SQFT = Decimal("0.5")
STATION_SPACING_FT = 10

# --- bond premium, cap and term windows -----------------------------------

PREMIUM_RATE_OF_QUOTE = Decimal("0.18")
CAP_MULTIPLIER = {"RETREAT_ONLY": Decimal("0"), "REPAIR_AND_RETREAT": Decimal("60")}
CAP_LOADING_RATE = Decimal("0.004")

TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 60
GRACE_DAYS = 30
REINSTATEMENT_WINDOW_DAYS = 90
REINSTATEMENT_INSPECTION_MAX_AGE_DAYS = 30

# --- renewal invoice -------------------------------------------------------

RENEWAL_RATE_OF_PREMIUM = Decimal("0.345")
INSPECTION_BASE_FEE = Decimal("85.00")
INSPECTION_FEE_PER_100_SQFT = Decimal("2.155")
CONDUCIVE_SURCHARGE_PER_CONDITION = Decimal("7.335")
LATE_FEE_PER_DAY = Decimal("0.415")

# --- reinstatement settlement ---------------------------------------------

PRORATION_CUTOFF_DAYS = 30
REINSTATEMENT_FEE_BASE = Decimal("95.00")
LAPSE_DAY_FEE = Decimal("1.75")

# --- claim waterfall -------------------------------------------------------

DEDUCTIBLE_TIER1_LIMIT = Decimal("2000.00")
DEDUCTIBLE_TIER2_LIMIT = Decimal("10000.00")
DEDUCTIBLE_RATE_TIER1 = Decimal("0.10")
DEDUCTIBLE_RATE_TIER2 = Decimal("0.07")
DEDUCTIBLE_RATE_TIER3 = Decimal("0.05")

# --- stations --------------------------------------------------------------

STATION_INTERVAL_DAYS = {"INSTALLED": 90, "ACTIVE_HIT": 30, "ESCALATED": 14}
LATE_GRACE_DAYS = 7
ESCALATION_RUN_LENGTH = 3
ESCALATION_STATION_RATIO = Decimal("0.05")

# --- state jurisdiction ----------------------------------------------------

STATE_TURNAROUND_HOURS = {"AL": 120, "FL": 72, "GA": 96, "TX": 96, "CA": 168}
STATE_FORM_MAP = {"AL": "NPMA_33", "FL": "FL_DACS_13645", "GA": "GA_100",
                  "TX": "TX_SPCS_TWDIR", "CA": "CA_NPCA_1"}
CLOSING_LEAD_HOURS = 24
AMENDMENT_WINDOW_DAYS = 30
RETENTION_YEARS = {"AL": 2, "FL": 4, "GA": 2, "TX": 2, "CA": 3}

CE_CREDITS_REQUIRED = 8

ZERO = Decimal("0.00")


def r2(value):
    """Round half up to two decimal places."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil_int(value):
    """Raise to the next integer unless already integral."""
    return int(math.ceil(Decimal(value)))


# --------------------------------------------------------------------------
# treatment_sizing_and_quote
# --------------------------------------------------------------------------

def target_gallons(method, prop):
    if method != "LIQUID_BARRIER":
        return ZERO
    trench = Decimal(prop["linear_footage"]) * TRENCH_GAL_PER_LF[prop["construction_type"]]
    drill = ZERO
    if prop["construction_type"] == "SLAB":
        blocks = ceil_int(Decimal(prop["square_footage"]) / Decimal(100))
        drill = Decimal(blocks) * SLAB_DRILL_GAL_PER_100_SQFT
    return Decimal(ceil_int(trench + drill))


def target_station_count(method, prop):
    if method != "BAIT_STATION":
        return 0
    count = ceil_int(Decimal(prop["linear_footage"]) / Decimal(STATION_SPACING_FT))
    if prop["has_attached_structures"]:
        count += 2
    return count


def quoted_price(method, prop, inspection):
    sqft = Decimal(prop["square_footage"])
    tier1 = min(sqft, Decimal(1500)) * TIER1_RATE
    tier2 = max(Decimal(0), min(sqft, Decimal(3000)) - Decimal(1500)) * TIER2_RATE
    tier3 = max(Decimal(0), sqft - Decimal(3000)) * TIER3_RATE
    subtotal = tier1 + tier2 + tier3
    pre_multiplier = BASE_FEE[method] + subtotal
    after_construction = pre_multiplier * CONSTRUCTION_MULTIPLIER[prop["construction_type"]]
    if inspection is not None and inspection.get("active_infestation_found"):
        after_infestation = after_construction * (Decimal(1) + INFESTATION_SURCHARGE_RATE)
    else:
        after_infestation = after_construction
    rounded = r2(after_infestation)
    return min(rounded, METHOD_PRICE_CAP[method])


# --------------------------------------------------------------------------
# bond_premium_and_cap
# --------------------------------------------------------------------------

def bond_premium_and_cap(plan_quote, coverage_tier):
    base_premium = r2(plan_quote * PREMIUM_RATE_OF_QUOTE)
    cap = r2(base_premium * CAP_MULTIPLIER[coverage_tier])
    annual = r2(base_premium + CAP_LOADING_RATE * cap)
    return base_premium, cap, annual


# --------------------------------------------------------------------------
# renewal_invoice_total
# --------------------------------------------------------------------------

def renewal_components(annual_premium, square_footage, conducive_basis_count,
                       past_due_days):
    c1 = r2(annual_premium * RENEWAL_RATE_OF_PREMIUM)
    c2 = r2(INSPECTION_BASE_FEE
            + INSPECTION_FEE_PER_100_SQFT * (Decimal(square_footage) / Decimal(100)))
    c3 = r2(CONDUCIVE_SURCHARGE_PER_CONDITION * Decimal(conducive_basis_count))
    c4 = r2(LATE_FEE_PER_DAY * Decimal(past_due_days))
    return c1, c2, c3, c4, c1 + c2 + c3 + c4


# --------------------------------------------------------------------------
# reinstatement_settlement
# --------------------------------------------------------------------------

def reinstatement_settlement(annual_premium, lapse_days):
    """Returns (variant, premium_charge_usd, reinstatement_total_usd)."""
    if lapse_days <= PRORATION_CUTOFF_DAYS:
        variant = "PRORATED_REMAINDER"
        premium_charge = r2(annual_premium
                            * (Decimal(TERM_DAYS) - Decimal(lapse_days))
                            / Decimal(TERM_DAYS))
    else:
        variant = "FULL_TERM_RESTART"
        premium_charge = annual_premium
    total = r2(premium_charge + REINSTATEMENT_FEE_BASE
               + LAPSE_DAY_FEE * Decimal(lapse_days))
    return variant, premium_charge, total


# --------------------------------------------------------------------------
# claim_exclusion_and_eligibility
# --------------------------------------------------------------------------

def claim_exclusion(claimed_damage, verifying_inspection, damage_findings):
    """Returns (exclusion_basis, eligible_damage_usd, excluded_pre_existing_usd)."""
    if verifying_inspection.get("supersedes_inspection_id") is not None:
        basis = "FINDING_LEVEL"
        new_damage_sum = sum((f["damage_estimate_usd"] for f in damage_findings
                              if not f["pre_existing"]), ZERO)
        eligible = r2(min(claimed_damage, new_damage_sum))
    else:
        basis = "AGGREGATE_PRORATION"
        new_severity = sum((f["severity"] for f in damage_findings
                            if not f["pre_existing"]), 0)
        total_severity = sum((f["severity"] for f in damage_findings), 0)
        if total_severity == 0:
            eligible = ZERO
        else:
            eligible = r2(claimed_damage * Decimal(new_severity) / Decimal(total_severity))
    excluded = r2(claimed_damage - eligible)
    return basis, eligible, excluded


# --------------------------------------------------------------------------
# claim_payout_waterfall
# --------------------------------------------------------------------------

def deductible_rate(eligible):
    if eligible < DEDUCTIBLE_TIER1_LIMIT:
        return DEDUCTIBLE_RATE_TIER1
    if eligible < DEDUCTIBLE_TIER2_LIMIT:
        return DEDUCTIBLE_RATE_TIER2
    return DEDUCTIBLE_RATE_TIER3


def claim_waterfall(eligible, cap, claims_paid, reserved_excluding_this):
    """Returns (deductible_usd, projected_payout_usd)."""
    rate = deductible_rate(eligible)
    deductible = r2(eligible * rate)
    net_claim = eligible - deductible
    cap_headroom = cap - claims_paid - reserved_excluding_this
    projected = r2(min(net_claim, cap_headroom))
    if projected < ZERO:
        projected = ZERO
    return deductible, projected


# --------------------------------------------------------------------------
# station_interval_and_escalation
# --------------------------------------------------------------------------

def interval_compliance(days_since, prior_status):
    limit_days = STATION_INTERVAL_DAYS[prior_status]
    if days_since <= limit_days:
        return "ON_TIME"
    if days_since <= limit_days + LATE_GRACE_DAYS:
        return "LATE"
    return "MISSED"


def station_transition(prior_status, prior_run, activity_level):
    """Returns (new_status, run_after)."""
    if activity_level == "NONE":
        return "INSTALLED", 0
    if activity_level == "LIGHT":
        return prior_status, prior_run
    run_after = prior_run + 1
    if run_after >= ESCALATION_RUN_LENGTH:
        return "ESCALATED", run_after
    return "ACTIVE_HIT", run_after


def plan_escalation_threshold(target_count):
    return ceil_int(Decimal(target_count) * ESCALATION_STATION_RATIO)


def station_grid_ref(station_index):
    column = chr(65 + ((station_index - 1) // 10))
    row = ((station_index - 1) % 10) + 1
    return "%s%d" % (column, row)


# --------------------------------------------------------------------------
# wdo_turnaround / pesticide retention
# --------------------------------------------------------------------------

def turnaround_hours(requested_at, issued_at):
    seconds = (issued_at - requested_at).total_seconds()
    return int(math.ceil(seconds / 3600.0))
