"""Deterministic calculations (PRD §2.6, §3.1, §3.3, §3.4, §3.6, §3.7, §3.8, §3.9).

All money/indicator arithmetic uses Decimal with ROUND_HALF_UP; the pinned
rounding orders from the PRD are reproduced exactly.
"""
from decimal import Decimal, ROUND_HALF_UP

import constants as C
from db import STORE


def _dec(value):
    """Convert a JSON number to Decimal exactly (via its string form)."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    return Decimal(str(value))


def _q2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q1(x):
    return x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _q0(x):
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def f2(x):
    """Decimal -> JSON number (float), two-decimal value preserved numerically."""
    return float(x)


# --- annual_dues_assessment (PRD §3.1) -----------------------------------------
def annual_dues_cents(fte_enrollment, degree_levels_offered):
    """Per-line round-half-up to whole cents first, then sum, then add base."""
    total = 0
    for level in degree_levels_offered:
        line = _q0(Decimal(fte_enrollment) * Decimal(C.DUES_RATE_CENTS[level]) * C.DUES_MULT[level])
        total += int(line)
    return C.BASE_DUES_CENTS + total


def outstanding_dues_cents(institution):
    return max(0, institution["current_annual_dues_cents"] - institution["dues_paid_cents"])


# --- composite_financial_index (PRD §3.9) ---------------------------------------
def _scale(ratio):
    scaled = _q2(Decimal(20) * _dec(ratio))
    if scaled < C.CFI_SCALE_MIN:
        return C.CFI_SCALE_MIN
    if scaled > C.CFI_SCALE_MAX:
        return C.CFI_SCALE_MAX
    return scaled


def composite_financial_index(primary_reserve_ratio, viability_ratio, net_operating_ratio,
                              state_appropriation_ratio, legal_status):
    """Returns (cfi_value_float, variant) with the variant frozen at submit."""
    if legal_status == "PUBLIC":
        bonus = Decimal("0.00")
        if state_appropriation_ratio is not None and _dec(state_appropriation_ratio) >= C.APPROPRIATION_MIN_RATIO:
            bonus = C.APPROPRIATION_BONUS
        cfi = _q2(C.W_PRR_PUBLIC * _scale(primary_reserve_ratio)
                  + C.W_VIAB_PUBLIC * _scale(viability_ratio)
                  + bonus)
        return f2(cfi), "PUBLIC"
    cfi = _q2(C.W_PRR_PRIVATE * _scale(primary_reserve_ratio)
              + C.W_VIAB_PRIVATE * _scale(viability_ratio)
              + C.W_NOR_PRIVATE * _scale(net_operating_ratio))
    return f2(cfi), "PRIVATE"


def cfi_band(cfi_value):
    v = _dec(cfi_value)
    if v > C.CFI_CLEAR_ABOVE:
        return "CLEAR"
    if v <= C.CFI_PANEL_AT_OR_BELOW:
        return "PANEL"
    return "REVIEW"


# --- enrollment_momentum_index (PRD §3.9) ---------------------------------------
def enrollment_momentum_index(enrollment_change_pct, completion_rate, retention_rate):
    emi = _q2(Decimal("0.50") * _dec(enrollment_change_pct)
              + Decimal("0.30") * (_dec(completion_rate) - C.COMPLETION_NEUTRAL_PCT)
              + Decimal("0.20") * (_dec(retention_rate) - C.RETENTION_NEUTRAL_PCT))
    return f2(emi)


# --- assurance_readiness_score (PRD §3.4) ---------------------------------------
def readiness_score(evidence_items, variant):
    """variant SELF_REPORTED counts all items; TEAM_VERIFIED counts verified only."""
    total = Decimal("0")
    for code in C.CRITERION_CODES:
        if variant == "TEAM_VERIFIED":
            count = sum(1 for e in evidence_items if e["criterion_code"] == code and e["verified"])
        else:
            count = sum(1 for e in evidence_items if e["criterion_code"] == code)
        coverage = min(Decimal(count) / Decimal(C.MIN_EVIDENCE_PER_CRITERION), Decimal("1.0"))
        total += C.READINESS_WEIGHTS[code] * coverage
    return f2(_q2(Decimal(100) * total))


# --- recommended_action_determination (PRD §3.6) --------------------------------
def recommended_action(criterion_ratings, sanction_status, federal_compliance_status, latest_cfi_band, cycle_type):
    points = sum(C.RATING_POINTS[r["rating"]] for r in criterion_ratings)
    if points >= C.REAFFIRM_MIN_POINTS:
        severity = 1
    elif points >= C.NOTICE_MIN_POINTS:
        severity = 2
    elif points >= C.PROBATION_MIN_POINTS:
        severity = 3
    else:
        severity = 4
    # Severity floors, applied in the PRD's fixed order; each can only raise.
    if sanction_status in ("PROBATION", "SHOW_CAUSE"):
        severity = max(severity, 2)
    if federal_compliance_status == "DEFICIENT":
        severity = max(severity, 2)
    if latest_cfi_band == "PANEL":
        severity = max(severity, 3)
    if cycle_type == "REAFFIRMATION":
        return {1: "REAFFIRMATION", 2: "NOTICE", 3: "PROBATION", 4: "SHOW_CAUSE"}[severity]
    # INITIAL_ACCREDITATION
    if severity == 1:
        return "GRANT_INITIAL"
    if severity == 2:
        return "NOTICE"
    return "DENIAL"


# --- cohort_default_rate_assessment (PRD §3.3) ----------------------------------
def federal_compliance_verdict(federal_components, cohort_default_rates):
    """Returns COMPLIANT | DEFICIENT. Rates compared at one decimal place."""
    rates = [_q1(_dec(r)) for r in cohort_default_rates]
    if any(r >= C.CDR_SINGLE_YEAR_PCT for r in rates):
        return "DEFICIENT"
    if len(rates) == C.CDR_MAX_RATES and all(r >= C.CDR_CONSECUTIVE_YEAR_PCT for r in rates):
        return "DEFICIENT"
    if any(comp["result"] == "FAIL" for comp in federal_components):
        return "DEFICIENT"
    return "COMPLIANT"


# --- panel_decision_tally (PRD §3.7) --------------------------------------------
def panel_tally(votes):
    """Highest vote count wins; ties break toward the more severe choice."""
    counts = {}
    for vote in votes:
        counts[vote["choice"]] = counts.get(vote["choice"], 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], C.TALLY_SEVERITY[kv[0]]))[0]


# --- sanction_cure_determination (PRD §3.8) -------------------------------------
def cure_evidence_score(institution_id, cure_review_opened_at):
    count = 0
    for report in STORE.indicator_reports.values():
        if report["institution_id"] != institution_id:
            continue
        if report["status"] != "CLEARED" or report["evaluated_at"] is None:
            continue
        if report["_evaluated_dt"] > cure_review_opened_at:
            count += 1
    return min(C.CURE_SCORE_CAP, C.CLEARED_REPORT_POINTS * count)
