"""Calculation rules: attestation ladder, traffic risk index, effectiveness
score and forfeiture assessment (PRD 3.6, 3.7, 3.9)."""
from decimal import Decimal, ROUND_HALF_UP

# --- rounding --------------------------------------------------------------
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
Q0 = Decimal("1")


def round_half_up(value, places):
    quant = {0: Q0, 2: Q2, 4: Q4}[places]
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def dec4(value):
    return float(round_half_up(value, 4))


def dec2(value):
    return float(round_half_up(value, 2))


# --- attestation level assignment (PRD 3.6) --------------------------------
LEVEL_A = "A"
LEVEL_B = "B"
LEVEL_C = "C"

VERIFIED_OWNERSHIP_EVIDENCE = ("DIRECT_ALLOCATION", "PORTED_IN")


def assign_attestation(auth_posture, risk_tier, kyc_evidence_level,
                       ownership_verified):
    """Seven-step ladder, first match wins."""
    if auth_posture == "GATEWAY_LIMITED":
        return LEVEL_C, "GATEWAY_PASSTHROUGH"
    if risk_tier == "HIGH":
        return LEVEL_C, "RISK_DOWNGRADE"
    if kyc_evidence_level == "BUSINESS_REGISTRY_VERIFIED" and ownership_verified:
        return LEVEL_A, "FULL_KYC_AND_OWNERSHIP"
    if kyc_evidence_level == "BUSINESS_REGISTRY_VERIFIED" and not ownership_verified:
        return LEVEL_B, "KYC_ONLY_NO_OWNERSHIP"
    if kyc_evidence_level == "CONTRACT_ONLY" and ownership_verified:
        return LEVEL_B, "OWNERSHIP_WITH_PARTIAL_KYC"
    if kyc_evidence_level == "CONTRACT_ONLY" and not ownership_verified:
        return LEVEL_C, "NO_VERIFIED_BASIS"
    return LEVEL_C, "NO_VERIFIED_BASIS"


def passport_token(certificate_id, attestation_level):
    return "shaken;" + str(certificate_id) + ";" + str(attestation_level)


# --- customer traffic risk index (PRD 3.7) ---------------------------------
COMPLAINT_AMPLIFIER = Decimal("50")
RECENCY_DEPTH = 3
RECENCY_WEIGHTS = (Decimal("0.50"), Decimal("0.30"), Decimal("0.20"))
HIGH_TIER_THRESHOLD = Decimal("0.7500")
ELEVATED_TIER_THRESHOLD = Decimal("0.4000")
AUTO_SUSPEND_THRESHOLD = Decimal("0.9000")
SHORT_WEIGHT = Decimal("0.45")
UNANSWERED_WEIGHT = Decimal("0.35")
COMPLAINT_WEIGHT = Decimal("0.20")


def window_subscore(total, short, unanswered, complaints):
    """Per-window robocall signature score, rounded half up to 2 decimals."""
    if total == 0:
        raw = Decimal("0")
    else:
        total_d = Decimal(total)
        short_ratio = Decimal(short) / total_d
        unanswered_ratio = Decimal(unanswered) / total_d
        complaint_ratio = Decimal(complaints) / total_d
        complaint_term = complaint_ratio * COMPLAINT_AMPLIFIER
        if complaint_term > Decimal("1"):
            complaint_term = Decimal("1")
        raw = (SHORT_WEIGHT * short_ratio
               + UNANSWERED_WEIGHT * unanswered_ratio
               + COMPLAINT_WEIGHT * complaint_term)
    return round_half_up(raw, 2)


def order_observations(observations):
    """window_end descending, ties broken on created_at ascending."""
    by_creation = sorted(observations, key=lambda o: (o["created_at"], o["_seq"]))
    return sorted(by_creation, key=lambda o: o["window_end"], reverse=True)


def traffic_risk_index(observations):
    """Recency-weighted index over the stored two-decimal subscores."""
    ordered = order_observations(observations)[:RECENCY_DEPTH]
    if not ordered:
        return Decimal("0.0000")
    weights = RECENCY_WEIGHTS[:len(ordered)]
    numerator = Decimal("0")
    for weight, observation in zip(weights, ordered):
        numerator += weight * Decimal(str(observation["window_subscore"]))
    denominator = sum(weights, Decimal("0"))
    return round_half_up(numerator / denominator, 4)


def risk_tier(index):
    index = Decimal(str(index))
    if index >= HIGH_TIER_THRESHOLD:
        return "HIGH"
    if index >= ELEVATED_TIER_THRESHOLD:
        return "ELEVATED"
    return "LOW"


# --- mitigation effectiveness score (PRD 3.9) ------------------------------
ATTESTATION_WEIGHT = Decimal("0.40")
TRACEBACK_WEIGHT = Decimal("0.35")
NOTICE_WEIGHT = Decimal("0.25")
HIGH_BAND_THRESHOLD = Decimal("0.8000")
MID_BAND_THRESHOLD = Decimal("0.6000")


def effectiveness(variant, signed_total, level_a, tb_total, tb_ontime,
                  tb_pending, n_total, n_done, n_open):
    provisional = (variant == "PROVISIONAL")

    if signed_total == 0:
        attestation_component = Decimal("0.0000")
        sufficiency = "INSUFFICIENT"
    else:
        attestation_component = round_half_up(
            Decimal(level_a) / Decimal(signed_total), 4)
        sufficiency = "SUFFICIENT"

    if tb_total == 0:
        traceback_component = Decimal("1.0000")
    else:
        numerator = tb_ontime + (tb_pending if provisional else 0)
        traceback_component = round_half_up(
            Decimal(numerator) / Decimal(tb_total), 4)

    if n_total == 0:
        notice_component = Decimal("1.0000")
    else:
        numerator = n_done + (n_open if provisional else 0)
        notice_component = round_half_up(
            Decimal(numerator) / Decimal(n_total), 4)

    score = round_half_up(
        ATTESTATION_WEIGHT * attestation_component
        + TRACEBACK_WEIGHT * traceback_component
        + NOTICE_WEIGHT * notice_component, 4)

    if score >= HIGH_BAND_THRESHOLD:
        band = "HIGH"
    elif score >= MID_BAND_THRESHOLD:
        band = "MID"
    else:
        band = "LOW"

    return {
        "attestation_component": float(attestation_component),
        "traceback_component": float(traceback_component),
        "notice_component": float(notice_component),
        "effectiveness_score": float(score),
        "score_band": band,
        "data_sufficiency": sufficiency,
    }


# --- forfeiture assessment (PRD 3.9) --------------------------------------
PER_VIOLATION_CENTS = 1000000
CONTINUING_DAILY_CENTS = 250000
STATUTORY_CAP_CENTS = 100000000
TIER_1_CEILING_CENTS = 2000000
TIER_2_CEILING_CENTS = 20000000

CREDIT_TABLE = {
    "TIER_1": {"HIGH": Decimal("0.30"), "MID": Decimal("0.15"),
               "LOW": Decimal("0.05"), "NONE": Decimal("0.00")},
    "TIER_2": {"HIGH": Decimal("0.25"), "MID": Decimal("0.10"),
               "LOW": Decimal("0.05"), "NONE": Decimal("0.00")},
    "TIER_3": {"HIGH": Decimal("0.15"), "MID": Decimal("0.05"),
               "LOW": Decimal("0.00"), "NONE": Decimal("0.00")},
}


def forfeiture(assessment_basis, violation_count, violation_days, score_band):
    if assessment_basis == "PER_VIOLATION":
        base = violation_count * PER_VIOLATION_CENTS
    else:
        base = violation_days * CONTINUING_DAILY_CENTS

    capped = min(base, STATUTORY_CAP_CENTS)

    if capped <= TIER_1_CEILING_CENTS:
        tier = "TIER_1"
    elif capped <= TIER_2_CEILING_CENTS:
        tier = "TIER_2"
    else:
        tier = "TIER_3"

    pct = CREDIT_TABLE[tier][score_band]
    credit = int(round_half_up(Decimal(capped) * pct, 0))
    return {
        "base_assessment_cents": base,
        "base_capped_cents": capped,
        "assessment_tier": tier,
        "score_band": score_band,
        "mitigation_credit_cents": credit,
        "total_forfeiture_cents": capped - credit,
    }


# --- provider posture ladder (PRD 2.9) ------------------------------------
SUSPENSION_POINT_THRESHOLD = 10
OVERDUE_TRACEBACK_GATEWAY_THRESHOLD = 1
PLAN_DEFICIENCY_POINTS = 2
LATE_TRACEBACK_POINTS = 3
EXPIRED_NOTICE_POINTS = 5


def posture(rmd_filing_status, penalty_points, overdue_traceback_count,
            active_certificate_id):
    if (rmd_filing_status == "UNFILED"
            or penalty_points >= SUSPENSION_POINT_THRESHOLD
            or active_certificate_id is None):
        return "SIGNING_SUSPENDED"
    if (rmd_filing_status == "PARTIAL"
            or overdue_traceback_count >= OVERDUE_TRACEBACK_GATEWAY_THRESHOLD):
        return "GATEWAY_LIMITED"
    return "FULL_ATTESTATION"


def false_positive_rate(total, reversed_count):
    if total == 0:
        return 0.0
    return float(round_half_up(Decimal(reversed_count) / Decimal(total), 4))
