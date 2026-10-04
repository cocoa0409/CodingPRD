"""Pinned calculation rules and global constants (PRD section 2.10 and 3)."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"
Z_ALPHA_CRIT = Decimal("1.96")
Z_POWER_CRIT = Decimal("0.84")
QED_VARIANCE_INFLATION = Decimal("1.44")
YIELD_PROSPECTED = Decimal("0.10")
YIELD_CONTACTED = Decimal("0.35")
K_ANONYMITY_MIN = 5
MAX_DISCLOSURE_RISK = Decimal("0.20")
MAX_TOTAL_BURDEN_MINUTES = 480
MODE_FACTOR_SURVEY = Decimal("1.0")
MODE_FACTOR_SITE_VISIT = Decimal("1.25")
MODE_FACTOR_ADMIN_RECORDS = Decimal("0.5")
SITE_VISIT_MIN_GAP_DAYS = 7
IRB_MAX_APPROVAL_DAYS = 365
PEER_REVIEW_DAYS = 45
AGENCY_COMMENT_DAYS = 30
REVISION_DAYS = 60
PUBLICATION_DAYS = 90


def _d(value):
    return Decimal(str(value))


def required_sample_size(design_type, mde, cluster_size, icc, attrition_rate):
    """Per-arm requirement and total; stamped at creation, never recomputed."""
    design_effect = Decimal(1) + (Decimal(cluster_size) - 1) * _d(icc)
    raw = (Decimal(2) * (Z_ALPHA_CRIT + Z_POWER_CRIT) ** 2
           * design_effect / (_d(mde) ** 2))
    if design_type == "RCT":
        value = raw / (Decimal(1) - _d(attrition_rate))
    else:
        value = raw * QED_VARIANCE_INFLATION / (Decimal(1) - _d(attrition_rate))
    n_per_arm = int(value.to_integral_value(rounding=ROUND_CEILING))
    return n_per_arm, 2 * n_per_arm


def pipeline_credit(max_participants, status):
    """Floor per-site yield contribution for PROSPECTED/CONTACTED sites."""
    if status == "CONTACTED":
        return int((Decimal(max_participants) * YIELD_CONTACTED)
                   .to_integral_value(rounding=ROUND_FLOOR))
    if status == "PROSPECTED":
        return int((Decimal(max_participants) * YIELD_PROSPECTED)
                   .to_integral_value(rounding=ROUND_FLOOR))
    return 0


def billed_minutes(instrument_minutes, wave_type):
    """Per-record billed burden: round_half_up(instrument * mode factor)."""
    factor = {
        "SURVEY": MODE_FACTOR_SURVEY,
        "SITE_VISIT": MODE_FACTOR_SITE_VISIT,
        "ADMIN_RECORDS": MODE_FACTOR_ADMIN_RECORDS,
    }[wave_type]
    return int((Decimal(instrument_minutes) * factor)
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def disclosure_risk(cell_counts, sensitivity_weights):
    """Suppress sub-k cells first, then compute risk over survivors only.

    Returns (suppressed_cell_count, max_risk, mean_risk) with risks as
    Decimals quantized to 4 places, round-half-up. Empty-survivor fallback
    pins both risks to 1.0.
    """
    survivors = [(c, w) for c, w in zip(cell_counts, sensitivity_weights)
                 if c >= K_ANONYMITY_MIN]
    suppressed = len(cell_counts) - len(survivors)
    if not survivors:
        return suppressed, Decimal("1.0"), Decimal("1.0")
    risks = [_d(w) / Decimal(c) for c, w in survivors]
    max_risk = max(risks).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    total_w = sum((_d(w) for _, w in survivors), Decimal(0))
    total_c = sum((Decimal(c) for c, _ in survivors), Decimal(0))
    mean_risk = (total_w / total_c).quantize(Decimal("0.0001"),
                                             rounding=ROUND_HALF_UP)
    return suppressed, max_risk, mean_risk
