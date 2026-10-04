"""Rating decisions: appeal windows, publication, withdrawal and appeals.

SCAFFOLD state_machines -> RatingDecision / IssuerAppeal,
PRD sections 3.5 and 3.6.
"""

from db import base_row, days_later, db, now, parse_ts, touch
from domain import APPEAL_WINDOW_DAYS, BLOCKING_RECONCILIATION
from errors import fail
from services import analysts as analyst_service
from services import calculations, common


# ---------------------------------------------------------------------------
# Appeal window
# ---------------------------------------------------------------------------
def open_appeal_window(decision):
    if decision["decision_status"] != "DRAFT":
        fail("ERR_DECISION_NOT_DRAFT")
    request = db.rating_requests.get(decision["rating_request_id"])
    if request is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if request["request_status"] != "COMMITTEE_DECIDED":
        fail("ERR_REQUEST_NOT_COMMITTEE_DECIDED")

    decision["decision_status"] = "APPEAL_WINDOW"
    decision["appeal_window_end_at"] = days_later(now(), APPEAL_WINDOW_DAYS)

    # The decision is now being prepared for publication, so the dissent score
    # switches to the publication-weighted variant (PRD section 3.5).
    committee = common.primary_committee_for_request(request["id"])
    if committee is not None:
        count, score = calculations.dissent_tally(
            committee["id"], decision["assigned_grade"], True
        )
        decision["dissent_count"] = count
        decision["dissent_score"] = score
    return touch(decision)


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------
def publish(decision, expected_rating_request_version):
    if expected_rating_request_version is not None:
        request = db.rating_requests.get(decision["rating_request_id"])
        if request is None:
            fail("ERR_RESOURCE_NOT_FOUND")
        if int(expected_rating_request_version) != int(request["version"]):
            fail("ERR_STALE_VERSION")

    if decision["decision_status"] != "APPEAL_WINDOW":
        fail("ERR_DECISION_NOT_IN_APPEAL_WINDOW")

    request = db.rating_requests.get(decision["rating_request_id"])
    if request is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    entity = db.rated_entities.get(request["rated_entity_id"])
    if entity is None:
        fail("ERR_RESOURCE_NOT_FOUND")

    engagement = db.engagement_letters.get(request["engagement_letter_id"])
    cooling = engagement["cooling_off_end_at"] if engagement else None
    if cooling is None or cooling > now():
        fail("ERR_COOLING_OFF_ACTIVE")

    methodology = common.entity_pinned_methodology(entity)
    if entity.get("solicitation_status") != "SOLICITED" and not methodology["is_public"]:
        fail("ERR_UNSOLICITED_DISCLOSURE_MISSING")

    if len(decision.get("rationale") or "") < 200:
        fail("ERR_RATIONALE_TOO_SHORT")

    published_at = now()
    decision["decision_status"] = "PUBLISHED"
    decision["published_at"] = published_at
    decision["is_unsolicited"] = entity.get("solicitation_status") == "UNSOLICITED"
    decision["methodology_code"] = methodology["methodology_code"]

    committee = common.primary_committee_for_request(request["id"])
    if committee is not None:
        count, score = calculations.dissent_tally(
            committee["id"], decision["assigned_grade"], True
        )
        decision["dissent_count"] = count
        decision["dissent_score"] = score
    touch(decision)

    # Hop 1 — record the grade and the first-rating instant.
    entity["current_grade"] = decision["assigned_grade"]
    if entity.get("first_rated_at") is None:
        entity["first_rated_at"] = published_at
    touch(entity)

    request["request_status"] = "PUBLISHED"
    request["updated_at"] = now()
    request["version"] = int(request["version"]) + 1

    # Fan-out — a successor review is created before the posture floor runs.
    reviewer = create_successor_review(entity, decision, published_at)

    # Hop 2 — posture recomputes from the published watch_status.
    if decision["watch_status"] in ("WATCH_UPGRADE", "WATCH_DOWNGRADE"):
        analyst_service.activate_watch(entity)
    return decision


def create_successor_review(entity, decision, anchor):
    """A successor SurveillanceReview due a full cycle after the anchor."""
    from services import surveillance

    cycle = surveillance.cycle_months(entity)
    return surveillance.create_row(
        rated_entity_id=entity["id"],
        rating_decision_id=decision["id"],
        review_type="PERIODIC",
        review_due_at=days_later(anchor, 30 * int(cycle)),
        review_status="SCHEDULED",
    )


def withdraw(decision):
    if decision["decision_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a draft decision can be withdrawn.")
    decision["decision_status"] = "WITHDRAWN"
    return touch(decision)


# ---------------------------------------------------------------------------
# Issuer appeals
# ---------------------------------------------------------------------------
def _restates(summary, decision):
    rationale = (decision.get("rationale") or "").strip().lower()
    text = (summary or "").strip().lower()
    if not rationale or not text:
        return False
    return text in rationale


def contains_new_information(summary, decision):
    if len(summary or "") < 100:
        return False
    return not _restates(summary, decision)


def blocking_reconciliation(decision_id):
    for row in db.appearance_reconciliations.values():
        if row["rating_decision_id"] != decision_id:
            continue
        if row["reconciliation_status"] in BLOCKING_RECONCILIATION:
            return row
    return None


def file_appeal(decision, filer_user_id, new_information_summary):
    if decision["decision_status"] != "APPEAL_WINDOW":
        fail("ERR_APPEAL_WINDOW_CLOSED")

    is_new = contains_new_information(new_information_summary, decision)
    if not is_new:
        fail("ERR_APPEAL_NOT_NEW_INFORMATION")

    if blocking_reconciliation(decision["id"]) is not None:
        fail("ERR_APPEALS_BLOCKED_PENDING_RECONCILIATION")

    row = base_row()
    row.update(
        {
            "rating_decision_id": decision["id"],
            "filer_user_id": filer_user_id,
            "new_information_summary": new_information_summary,
            "contains_new_information": is_new,
            "appeal_outcome": "PENDING",
            "submitted_at": now(),
            "resolution_notes": None,
        }
    )
    db.issuer_appeals[row["id"]] = row
    return row


def _appeal_admissible(appeal):
    """The linked decision must still be in APPEAL_WINDOW or DRAFT."""
    decision = db.rating_decisions.get(appeal["rating_decision_id"])
    if decision is None:
        return False
    return decision["decision_status"] in ("APPEAL_WINDOW", "DRAFT")


def resolve_appeal(appeal, appeal_outcome, resolution_notes):
    if appeal["appeal_outcome"] != "PENDING":
        fail("ERR_INVALID_STATE", "The appeal has already been resolved.")
    if len(resolution_notes or "") < 30:
        fail("ERR_APPEAL_RESOLUTION_NOTES_REQUIRED")
    if not _appeal_admissible(appeal):
        fail("ERR_APPEAL_WINDOW_CLOSED")

    outcome = "ACCEPTED" if appeal_outcome == "ACCEPTED" else "REJECTED"

    if outcome == "ACCEPTED":
        if not appeal.get("contains_new_information"):
            fail("ERR_APPEAL_NOT_NEW_INFORMATION")

        decision = db.rating_decisions.get(appeal["rating_decision_id"])
        request = db.rating_requests.get(decision["rating_request_id"])
        if request is None:
            fail("ERR_RESOURCE_NOT_FOUND")

        decision["decision_status"] = "DRAFT"
        decision["appeal_window_end_at"] = None
        touch(decision)

        committee = common.primary_committee_for_request(request["id"])
        if committee is not None and committee["committee_status"] == "DECIDED":
            committee["committee_status"] = "IN_SESSION"
            touch(committee)

        request["request_status"] = "APPEALED"
        request["updated_at"] = now()
        request["version"] = int(request["version"]) + 1

    appeal["appeal_outcome"] = outcome
    appeal["resolution_notes"] = resolution_notes
    return touch(appeal)


def supersede(decision):
    """Move a superseded decision to WITHDRAWN."""
    if decision["decision_status"] == "PUBLISHED":
        return decision
    decision["decision_status"] = "WITHDRAWN"
    return touch(decision)