"""Shared lookups and the team-assignment coverage map.

Coverage records which RatingRequest a task assignment actually covers for a
lead.  It is set when a team assignment is confirmed and cleared when that
assignment is revoked, so a revoked assignment removes the analyst's lead
credit for that window (SCAFFOLD state_machines -> AnalyticalTeamAssignment
CONFIRMED -> REVOKED, hop 1).  Coverage is a bookkeeping function of already
declared rows; it is never populated at startup.
"""

from db import db
from errors import fail

# team_assignment_id -> rating_request_id
COVERAGE = {}


def clear_coverage():
    COVERAGE.clear()


def cover(assignment_id, rating_request_id):
    COVERAGE[assignment_id] = rating_request_id


def uncover_where_request(rating_request_id):
    for key in [k for k, v in COVERAGE.items() if v == rating_request_id]:
        del COVERAGE[key]


def covered_requests(analyst_id):
    """Requests a lead still holds lead credit for."""
    result = []
    for assignment_id, request_id in COVERAGE.items():
        row = db.team_assignments.get(assignment_id)
        if row is None:
            continue
        if row.get("status") == "REVOKED":
            continue
        if row.get("lead_analyst_id") == analyst_id and request_id not in result:
            result.append(request_id)
    return result


def raise_not_found():
    fail("ERR_RESOURCE_NOT_FOUND")


# ---------------------------------------------------------------------------
# Path resolution helpers — left-to-right, first failure wins (PRD section 2.4)
# ---------------------------------------------------------------------------
def methodology_or_404(methodology_id):
    row = db.methodologies.get(methodology_id)
    if row is None:
        raise_not_found()
    return row


def entity_or_404(rated_entity_id):
    row = db.rated_entities.get(rated_entity_id)
    if row is None:
        raise_not_found()
    return row


def engagement_or_404(engagement_letter_id):
    row = db.engagement_letters.get(engagement_letter_id)
    if row is None:
        raise_not_found()
    return row


def request_or_404(rating_request_id):
    row = db.rating_requests.get(rating_request_id)
    if row is None:
        raise_not_found()
    return row


def analyst_or_404(analyst_id):
    row = db.analysts.get(analyst_id)
    if row is None:
        raise_not_found()
    return row


def assignment_or_404(team_assignment_id):
    row = db.team_assignments.get(team_assignment_id)
    if row is None:
        raise_not_found()
    return row


def committee_or_404(rating_committee_id):
    row = db.rating_committees.get(rating_committee_id)
    if row is None:
        raise_not_found()
    return row


def decision_or_404(rating_decision_id):
    row = db.rating_decisions.get(rating_decision_id)
    if row is None:
        raise_not_found()
    return row


def appeal_or_404(issuer_appeal_id):
    row = db.issuer_appeals.get(issuer_appeal_id)
    if row is None:
        raise_not_found()
    return row


def review_or_404(surveillance_review_id):
    row = db.surveillance_reviews.get(surveillance_review_id)
    if row is None:
        raise_not_found()
    return row


def action_event_or_404(rating_action_event_id):
    row = db.rating_action_events.get(rating_action_event_id)
    if row is None:
        raise_not_found()
    return row


def compensation_or_404(compensation_record_id):
    row = db.compensation_records.get(compensation_record_id)
    if row is None:
        raise_not_found()
    return row


def lookback_or_404(look_back_review_id):
    row = db.look_back_reviews.get(look_back_review_id)
    if row is None:
        raise_not_found()
    return row


def slot_or_404(review_slot_id):
    row = db.review_slots.get(review_slot_id)
    if row is None:
        raise_not_found()
    return row


def reconciliation_or_404(appearance_reconciliation_id):
    row = db.appearance_reconciliations.get(appearance_reconciliation_id)
    if row is None:
        raise_not_found()
    return row


def entity_pinned_methodology(entity):
    """Resolve the issuer's pinned methodology, or fail with the PRD errors."""
    methodology_id = entity.get("methodology_id")
    if methodology_id is None:
        fail("ERR_METHODOLOGY_NOT_FOUND")
    row = db.methodologies.get(methodology_id)
    if row is None:
        fail("ERR_METHODOLOGY_NOT_FOUND")
    return row


# ---------------------------------------------------------------------------
# Shared derivations
# ---------------------------------------------------------------------------
def current_decision_for_request(rating_request_id):
    """The request's current (non-superseded) RatingDecision, if any."""
    rows = [
        r
        for r in db.rating_decisions.values()
        if r["rating_request_id"] == rating_request_id
        and r["decision_status"] != "WITHDRAWN"
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows[-1]


def any_decision_for_request(rating_request_id):
    rows = [
        r
        for r in db.rating_decisions.values()
        if r["rating_request_id"] == rating_request_id
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows[-1]


def latest_committee_for_request(rating_request_id):
    rows = [
        r
        for r in db.rating_committees.values()
        if r["rating_request_id"] == rating_request_id
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows[-1]


def primary_committee_for_request(rating_request_id):
    """The committee a request's decisions belong to (first one convened)."""
    rows = [
        r
        for r in db.rating_committees.values()
        if r["rating_request_id"] == rating_request_id
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows[0]