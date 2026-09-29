"""Scoring: per-attribute agreement, raw/match score, conflict flags,
classification, the triage band chain, fraud risk score and site duplicate rate.

Rounding order (PRD §3.3 step two) is load-bearing: each attribute contribution
is rounded to 2dp FIRST, then the seven rounded values are summed and the sum is
rounded again.
"""

from decimal import Decimal

from core import (
    BAND_CUTOFF_P1, BAND_CUTOFF_P2, BAND_MULTIPLIER_P1, BAND_MULTIPLIER_P2,
    BAND_MULTIPLIER_P3, BPS_SCALE, FRAUD_CONFLICT_COMPONENT_POINTS,
    FRAUD_INSURANCE_COMPONENT_POINTS, FRAUD_SCORE_COMPONENT_CAP,
    FRAUD_SITE_COMPONENT_CAP, FRAUD_SITE_COMPONENT_PER_FLAGGED_RECORD,
    NULL_CREDIT_FRACTION, PREFIX_COMPARE_CHARS, SCORED_ATTRIBUTES, D, q2, qint,
    store,
)

ZERO = Decimal("0.00")
ONE = Decimal("1")
HALF = Decimal("0.5")


def _norm(value):
    if value is None:
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed.lower()
    return value


def _prefix_agreement(a, b):
    if a == b:
        return ONE
    if len(a) >= PREFIX_COMPARE_CHARS and len(b) >= PREFIX_COMPARE_CHARS \
            and a[:PREFIX_COMPARE_CHARS] == b[:PREFIX_COMPARE_CHARS]:
        return HALF
    return ZERO


def _dob_agreement(a, b):
    if a == b:
        return ONE
    pa, pb = a.split("-"), b.split("-")
    if len(pa) != 3 or len(pb) != 3:
        return ZERO
    ya, ma, da = pa
    yb, mb, db = pb
    if ya == yb and ma == mb and da != db:
        return HALF
    # day-and-month transposition
    if ya == yb and ma == db and da == mb and ma != da:
        return HALF
    return ZERO


def attribute_agreement(attr, a, b):
    """Returns the agreement fraction, or None when agreement is undefined."""
    av, bv = _norm(a), _norm(b)
    if av is None or bv is None:
        return None
    if attr in ("last_name", "first_name", "postal_code"):
        return _prefix_agreement(str(av), str(bv))
    if attr == "dob":
        return _dob_agreement(str(av), str(bv))
    # ssn_last4, sex, phone -- all or nothing
    return ONE if av == bv else ZERO


def _weight(rule_set, attr):
    weights = rule_set.get("attribute_weights") or {}
    return D(weights.get(attr, 0))


CONFLICT_ORDER = [
    ("SSN4_CONFLICT", "ssn_last4"),
    ("BIOMETRIC_CONFLICT", "biometric_template_hash"),
    ("INSURANCE_CONFLICT", "insurance_member_id"),
]


def conflict_flags(a, b):
    flags = []
    for flag, field in CONFLICT_ORDER:
        av, bv = a.get(field), b.get(field)
        if av is not None and bv is not None and _norm(av) != _norm(bv):
            flags.append(flag)
    return flags


def score(a, b, rule_set, variant):
    """The one reusable comparison (PRD §3.3). `a` and `b` are attribute dicts."""
    breakdown = {}
    total = ZERO
    for attr in SCORED_ATTRIBUTES:
        weight = _weight(rule_set, attr)
        agreement = attribute_agreement(attr, a.get(attr), b.get(attr))
        if agreement is None:
            if variant == "TOLERANT":
                contribution = q2(weight * NULL_CREDIT_FRACTION)
            else:
                contribution = ZERO.quantize(Decimal("0.01"))
        else:
            contribution = q2(weight * agreement)
        breakdown[attr] = contribution
        total += contribution
    raw_score = q2(total)
    flags = conflict_flags(a, b)
    penalty = D(rule_set.get("conflict_penalty_points", 0)) * Decimal(len(flags))
    match_score = q2(max(ZERO, raw_score - penalty))
    auto = D(rule_set.get("auto_link_threshold", 0))
    review = D(rule_set.get("review_threshold", 0))
    if match_score >= auto:
        classification = "AUTO_LINK"
    elif match_score >= review:
        classification = "POTENTIAL_DUPLICATE"
    else:
        classification = "NON_DUPLICATE"
    return {
        "attribute_score_breakdown": breakdown,
        "raw_score": raw_score,
        "conflict_flags": flags,
        "match_score": match_score,
        "classification": classification,
    }


def record_attrs(record):
    return {
        "last_name": record.get("last_name"),
        "first_name": record.get("first_name"),
        "dob": record.get("dob"),
        "ssn_last4": record.get("ssn_last4"),
        "sex": record.get("sex"),
        "postal_code": record.get("postal_code"),
        "phone": record.get("phone"),
        "biometric_template_hash": record.get("biometric_template_hash"),
        "insurance_member_id": record.get("insurance_member_id"),
    }


# --------------------------------------------------------------------------
# Band machinery (PRD §3.4)
# --------------------------------------------------------------------------
def band_of(value):
    value = D(value)
    if value >= BAND_CUTOFF_P1:
        return "P1"
    if value >= BAND_CUTOFF_P2:
        return "P2"
    return "P3"


def band_multiplier(band):
    if band == "P1":
        return BAND_MULTIPLIER_P1
    if band == "P2":
        return BAND_MULTIPLIER_P2
    return BAND_MULTIPLIER_P3


def evidence_of_pair(pair_id):
    rows = [e for e in store.evidence.values() if e["pair_id"] == pair_id]
    rows.sort(key=lambda e: (e["created_at"], e["evidence_type"], e["outcome"], e["_seq"]))
    return rows


def evidence_points(pair_id):
    total = ZERO
    for entry in evidence_of_pair(pair_id):
        weight = D(entry["weight_points"])
        if entry["outcome"] == "SUPPORTS_SAME_PERSON":
            total += weight
        elif entry["outcome"] == "SUPPORTS_DISTINCT":
            total -= weight
    return q2(total)


def recompute_bands(pair):
    """Steps one through four, in the pinned order."""
    match_score = D(pair["match_score"])
    base_band = band_of(match_score)
    multiplier = band_multiplier(base_band)
    points = evidence_points(pair["id"])
    adjustment = q2(points * multiplier)
    effective = match_score + adjustment
    effective = q2(min(Decimal("100.00"), max(ZERO, effective)))
    pair["evidence_points"] = points
    pair["base_band"] = base_band
    pair["evidence_adjustment"] = adjustment
    pair["effective_score"] = effective
    pair["priority_band"] = band_of(effective)


# --------------------------------------------------------------------------
# Fraud risk score (PRD §3.9)
# --------------------------------------------------------------------------
def flagged_record_count(site_id):
    return sum(
        1 for r in store.records.values()
        if r["site_id"] == site_id and r["identity_state"] == "ACTIVE"
        and r["integrity_state"] in ("FRAUD_SUSPECTED", "FRAUD_CONFIRMED")
    )


def compute_risk_score(investigation):
    record = store.records.get(investigation["record_id"])
    pair = store.pairs.get(investigation.get("pair_id")) if investigation.get("pair_id") else None

    if pair is not None:
        flags = pair.get("conflict_flags") or []
        conflict_component = FRAUD_CONFLICT_COMPONENT_POINTS * Decimal(len(flags))
        rule_set = store.rule_sets.get(pair.get("rule_set_id"))
        review = D(rule_set["review_threshold"]) if rule_set else ZERO
        diff = q2(D(pair["match_score"]) - review)
        score_component = min(FRAUD_SCORE_COMPONENT_CAP, max(ZERO, diff))
        insurance_component = (
            FRAUD_INSURANCE_COMPONENT_POINTS if "INSURANCE_CONFLICT" in flags else ZERO
        )
    else:
        conflict_component = ZERO
        score_component = ZERO
        insurance_component = ZERO

    flagged = flagged_record_count(record["site_id"]) if record else 0
    site_component = min(
        FRAUD_SITE_COMPONENT_CAP,
        FRAUD_SITE_COMPONENT_PER_FLAGGED_RECORD * Decimal(flagged),
    )

    total = conflict_component + score_component + site_component + insurance_component
    return q2(min(Decimal("100.00"), total))


# --------------------------------------------------------------------------
# Site duplicate rate (PRD §3.9 / §3.10)
# --------------------------------------------------------------------------
def duplicate_rate_bps(confirmed_duplicates, records_created):
    if records_created == 0:
        return 0
    return qint(Decimal(confirmed_duplicates) * Decimal(BPS_SCALE) / Decimal(records_created))
