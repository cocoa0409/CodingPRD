"""Developer trust scoring: the onboarding snapshot and the enforcement audit."""
from decimal import Decimal

from constants import (
    CERTIFICATION_POINTS,
    CLEAN_WINDOW_CAP,
    CLEAN_WINDOW_POINTS_PER_WINDOW,
    CURRENT_DOCS_VERSION,
    DOCS_ACK_POINTS,
    HACKATHON_AWARD_CAP,
    HACKATHON_POINTS_PER_AWARD,
    LIVE_CASE_STATES,
    PENDING_CASE_WEIGHT,
    THROTTLE_HISTORY_PENALTY,
    THROTTLE_HISTORY_THRESHOLD,
    TRUST_BASE,
    TRUST_SCORE_MAX,
    TRUST_SCORE_MIN,
)
from db import store

from .common import certification_active, round_half_up_int


def _clamp(value):
    if value < TRUST_SCORE_MIN:
        return TRUST_SCORE_MIN
    if value > TRUST_SCORE_MAX:
        return TRUST_SCORE_MAX
    return int(value)


def _positive_components(developer):
    total = TRUST_BASE
    if certification_active(developer):
        total += CERTIFICATION_POINTS.get(developer["certification_level"], 0)
    acknowledged = developer["docs_version_acknowledged"]
    if acknowledged is not None and acknowledged >= CURRENT_DOCS_VERSION:
        total += DOCS_ACK_POINTS
    awards = min(developer["hackathon_award_count"], HACKATHON_AWARD_CAP)
    total += awards * HACKATHON_POINTS_PER_AWARD
    clean = min(developer["clean_window_count"], CLEAN_WINDOW_CAP)
    total += clean * CLEAN_WINDOW_POINTS_PER_WINDOW
    return total


def onboarding_snapshot(developer):
    """base + certification + docs + hackathon + clean - settled penalty."""
    return _clamp(_positive_components(developer) - developer["violation_points"])


def pending_exposure(developer):
    total = 0
    for case in store.violation_cases.values():
        if case["developer_id"] != developer["id"]:
            continue
        if case["state"] in LIVE_CASE_STATES:
            total += case["penalty_points"]
    return round_half_up_int(Decimal(total) * PENDING_CASE_WEIGHT)


def enforcement_audit(developer):
    value = _positive_components(developer) - developer["violation_points"]
    value -= pending_exposure(developer)
    if developer["throttled_window_count"] >= THROTTLE_HISTORY_THRESHOLD:
        value -= THROTTLE_HISTORY_PENALTY
    return _clamp(value)


def refresh_snapshot(developer):
    """Recompute trust_score in place; the caller owns the version bump."""
    developer["trust_score"] = onboarding_snapshot(developer)
    return developer["trust_score"]


def refresh_audit(developer):
    developer["audited_trust_score"] = enforcement_audit(developer)
    return developer["audited_trust_score"]
