"""Analytical scorecard calculation (PRD §3.2) and committee outcome tally
(PRD §3.3). Money-free, but precision-sensitive: Decimal everywhere."""
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    ANCHOR_A,
    ANCHOR_AA,
    ANCHOR_AAA,
    ANCHOR_B,
    ANCHOR_BB,
    ANCHOR_BBB,
    NOTCH_DEVIATION_MAX,
    NOTCH_SCALE,
    QUORUM_MIN_VOTES,
    WEAK_LINK_CAP_NOTCH,
    WEAK_LINK_MIN_SCORE,
)
from store import db

FACTOR_FIELDS = [
    ("score_economy", "w_economy"),
    ("score_management", "w_management"),
    ("score_budgetary_performance", "w_budgetary_performance"),
    ("score_flexibility", "w_flexibility"),
    ("score_liquidity", "w_liquidity"),
    ("score_debt_profile", "w_debt_profile"),
]

_4DP = Decimal("0.0001")


def weights_sum(weights):
    """Exact decimal sum of the six weights; inputs converted via str() so
    JSON floats contribute their decimal value, not their binary expansion."""
    return sum((Decimal(str(w)) for w in weights), Decimal("0"))


def active_criteria_for(jurisdiction_code, credit_type):
    """The single ACTIVE CriteriaVersion for a (jurisdiction, credit) segment,
    or None."""
    for cv in db.criteria_versions.values():
        if (
            cv["jurisdiction_code"] == jurisdiction_code
            and cv["credit_type"] == credit_type
            and cv["status"] == "ACTIVE"
        ):
            return cv
    return None


def anchor_for(weighted_score):
    """Anchor table on the ROUNDED 4-decimal weighted score; thresholds are
    inclusive lower bounds (PRD §3.2)."""
    if weighted_score >= ANCHOR_AAA:
        return "AAA"
    if weighted_score >= ANCHOR_AA:
        return "AA"
    if weighted_score >= ANCHOR_A:
        return "A"
    if weighted_score >= ANCHOR_BBB:
        return "BBB"
    if weighted_score >= ANCHOR_BB:
        return "BB"
    if weighted_score >= ANCHOR_B:
        return "B"
    return "CCC"


def compute_scorecard(criteria, scores, credit_type):
    """Derive weighted_score / anchor_notch / capped / indicative_notch.

    scores: dict of the six integer factor scores. criteria: the pinned ACTIVE
    CriteriaVersion whose weights apply.
    """
    total = Decimal("0")
    for score_field, weight_field in FACTOR_FIELDS:
        weight = Decimal(str(criteria[weight_field]))
        total += weight * Decimal(scores[score_field])
    weighted_score = total.quantize(_4DP, rounding=ROUND_HALF_UP)
    anchor_notch = anchor_for(weighted_score)

    capped = False
    indicative_notch = anchor_notch
    if credit_type == "ENTERPRISE" and min(scores[f] for f, _ in FACTOR_FIELDS) == WEAK_LINK_MIN_SCORE:
        # Weak-link cap: indicative is the worse of (anchor, BB).
        capped = True
        cap_idx = NOTCH_SCALE.index(WEAK_LINK_CAP_NOTCH)
        anchor_idx = NOTCH_SCALE.index(anchor_notch)
        indicative_notch = NOTCH_SCALE[max(anchor_idx, cap_idx)]

    return {
        "criteria_version_id": criteria["id"],
        "weighted_score": weighted_score,
        "anchor_notch": anchor_notch,
        "capped": capped,
        "indicative_notch": indicative_notch,
    }


def current_scorecard(engagement_id):
    """The engagement's current (latest submitted) scorecard, or None."""
    best = None
    for sc in db.scorecards.values():
        if sc["engagement_id"] != engagement_id:
            continue
        if best is None or sc["_seq"] > best["_seq"]:
            best = sc
    return best


def tally_session(session, indicative_notch):
    """Committee tally (PRD §3.3 / scaffold committee_outcome_tally).

    Returns (new_status, outcome_notch, adjourn_reason): COMPLETED with the
    median notch, or ADJOURNED with QUORUM_NOT_MET / NOTCH_DEVIATION_EXCEEDED.
    """
    vote_notches = [
        v["notch_vote"]
        for v in db.votes.values()
        if v["session_id"] == session["id"] and v["kind"] == "VOTE"
    ]
    if len(vote_notches) < QUORUM_MIN_VOTES:
        return "ADJOURNED", None, "QUORUM_NOT_MET"
    indices = sorted(NOTCH_SCALE.index(n) for n in vote_notches)
    # Even count: integer division picks the worse (higher-index) middle value.
    median_idx = indices[len(indices) // 2]
    indicative_idx = NOTCH_SCALE.index(indicative_notch)
    if abs(median_idx - indicative_idx) > NOTCH_DEVIATION_MAX:
        return "ADJOURNED", None, "NOTCH_DEVIATION_EXCEEDED"
    return "COMPLETED", NOTCH_SCALE[median_idx], None
