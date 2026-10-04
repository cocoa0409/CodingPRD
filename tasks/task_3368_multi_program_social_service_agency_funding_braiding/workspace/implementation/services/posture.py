"""grant_burn_posture.

burn_ratio = committed_cents / total_award_cents, six decimal places round half
up, where committed is expended + obligated (the base committed_basis variant).
The comparisons are inclusive: exactly 0.850000 is THROTTLED and exactly
1.000000 is FROZEN. The cash_basis projection is reporting-only and never gates
a write.
"""

import db
from common import ratio6
from services import capacity

THROTTLE_THRESHOLD = 0.85
FREEZE_THRESHOLD = 1.0
RATIO_SCALE = 6


def committed_cents(grant):
    return grant.get("expended_cents", 0) + grant.get("obligated_cents", 0)


def burn_ratio(grant):
    total = grant.get("total_award_cents", 0)
    if not total:
        return 0.0
    return ratio6(committed_cents(grant) / total)


def cash_burn_ratio(grant):
    """Reporting-only cash_basis projection: expended cents only."""
    total = grant.get("total_award_cents", 0)
    if not total:
        return 0.0
    return ratio6(grant.get("expended_cents", 0) / total)


def posture_for(ratio):
    if ratio >= FREEZE_THRESHOLD:
        return "FROZEN"
    if ratio >= THROTTLE_THRESHOLD:
        return "THROTTLED"
    return "OPEN"


def _freeze_cascade(grant):
    """Reaching FROZEN suspends every ACTIVE enrollment carrying this grant and
    decrements each affected client's open_enrollment_count."""
    for enrollment in db.rows("enrollments"):
        if enrollment.get("grant_id") != grant["id"]:
            continue
        if enrollment.get("status") != "ACTIVE":
            continue
        enrollment["status"] = "SUSPENDED"
        db.touch(enrollment)
        client = db.get("clients", enrollment.get("client_id"))
        if client is not None:
            capacity.recompute_client(client)


def apply_transition(grant, ratio):
    """Apply whatever posture transition the new ratio implies."""
    current = grant.get("status", "OPEN")
    target = posture_for(ratio)
    if target == current:
        return False
    grant["status"] = target
    if target == "FROZEN":
        _freeze_cascade(grant)
    return True


def recompute(grant):
    """Recompute burn_ratio and re-apply the posture transition. A recomputed
    property is a mutation: updated_at is refreshed and version increments."""
    ratio = burn_ratio(grant)
    grant["burn_ratio"] = ratio
    apply_transition(grant, ratio)
    grant["posture_computed_at"] = db.clock.now()
    db.touch(grant)
    return grant


def initialize(grant):
    """At creation the posture is assigned from the freshly computed ratio."""
    ratio = burn_ratio(grant)
    grant["burn_ratio"] = ratio
    grant["status"] = posture_for(ratio)
    grant["posture_computed_at"] = db.clock.now()
    return grant
