"""Analytical team assignments: proposal, screening, confirmation, revocation.

SCAFFOLD state_machines -> AnalyticalTeamAssignment, PRD section 3.3.

The eligible-list selector order for the screen is fixed by the PRD so that an
earlier failure is never masked by a later one:
  1. issuer pinned to a PUBLISHED methodology
  2. every team member carries a ConflictScreening row that is not DISQUALIFYING
  3. lead and support name different analysts
  4. no member departed to a rated issuer inside the 24-month look-back
  5. the lead's sector matches the request entity's sector
"""

from db import base_row, db, now, parse_ts, touch
from domain import CONFLICT_SEVERITY
from errors import fail
from services import analysts as analyst_service
from services import calculations, common


def create(rating_request_id, lead_analyst_id, support_analyst_id, window_start, window_end,
           rotation_exemption_granted, rotation_exemption_reason):
    lead = db.analysts.get(lead_analyst_id)
    if lead is None or lead["analyst_tier"] != "LEAD":
        fail("ERR_ANALYST_NOT_LEAD")
    if rotation_exemption_granted and len(rotation_exemption_reason or "") < 20:
        fail("ERR_ROTATION_EXEMPTION_REASON_REQUIRED")

    row = base_row()
    row.update(
        {
            "rating_request_id": rating_request_id,
            "lead_analyst_id": lead_analyst_id,
            "support_analyst_id": support_analyst_id,
            "assigned_at": now(),
            "window_start": parse_ts(window_start),
            "window_end": parse_ts(window_end),
            "conflict_status": "PENDING_SCREEN",
            "rotation_exemption_granted": bool(rotation_exemption_granted),
            "rotation_exemption_reason": rotation_exemption_reason,
            "status": "PROPOSED",
        }
    )
    db.team_assignments[row["id"]] = row
    return row


def screening_rows(assignment_id):
    return [r for r in db.conflict_screenings.values() if r["team_assignment_id"] == assignment_id]


def recompute_conflict_status(assignment):
    """Most severe result present: DISQUALIFYING > POTENTIAL > CLEAR."""
    rows = screening_rows(assignment["id"])
    if not rows:
        return "PENDING_SCREEN"
    severity = max(CONFLICT_SEVERITY.get(r["screening_result"], 0) for r in rows)
    if severity >= CONFLICT_SEVERITY["DISQUALIFYING"]:
        return "DISQUALIFYING"
    if severity >= CONFLICT_SEVERITY["POTENTIAL"]:
        return "POTENTIAL"
    if severity >= CONFLICT_SEVERITY["CLEAR"]:
        return "CLEAR"
    return "PENDING_SCREEN"


def screen(assignment):
    if assignment["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "The team assignment must be PROPOSED to screen.")

    request = db.rating_requests.get(assignment["rating_request_id"])
    if request is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    entity = db.rated_entities.get(request["rated_entity_id"])
    if entity is None:
        fail("ERR_RESOURCE_NOT_FOUND")

    # 1. Methodology gate runs before any analyst conflict check.
    methodology = common.entity_pinned_methodology(entity)
    if methodology["status"] != "PUBLISHED":
        fail("ERR_METHODOLOGY_NOT_PUBLISHED")

    lead_id = assignment["lead_analyst_id"]
    support_id = assignment["support_analyst_id"]

    # 2. Non-DISQUALIFYING screening row for each of the two members.
    for member_id in (lead_id, support_id):
        rows = [
            r
            for r in screening_rows(assignment["id"])
            if r["analyst_id"] == member_id
        ]
        if not rows or all(r["screening_result"] == "DISQUALIFYING" for r in rows):
            fail("ERR_CONFLICT_SCREENING_DISQUALIFYING")

    # 3. Lead and support must differ.
    if lead_id == support_id:
        fail("ERR_DUAL_ROLE_ASSIGNMENT")

    # 4. No member departed to a rated issuer inside the look-back window.
    for member_id in (lead_id, support_id):
        member = db.analysts.get(member_id)
        if member is not None and analyst_service.in_lookback_window(member):
            fail("ERR_LOOKBACK_WINDOW_BLOCKING")

    # 5. Lead sector must match the request entity's sector.
    lead = db.analysts.get(lead_id)
    if lead is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if lead["primary_sector"] != entity["sector"]:
        fail("ERR_SECTOR_MISMATCH")

    assignment["status"] = "SCREENED"
    assignment["conflict_status"] = recompute_conflict_status(assignment)
    if lead["first_assignment_at"] is None:
        lead["first_assignment_at"] = assignment["assigned_at"]
    touch(assignment)
    return assignment


def return_to_proposed(assignment):
    if assignment["status"] != "SCREENED":
        fail("ERR_TEAM_ASSIGNMENT_NOT_SCREENED")
    assignment["status"] = "PROPOSED"
    assignment["conflict_status"] = "PENDING_SCREEN"
    return touch(assignment)


def windows_overlap(assignment):
    """Does the lead's new window overlap another non-REVOKED assignment?"""
    start = assignment["window_start"]
    end = assignment["window_end"]
    if start is None:
        return False
    for other in db.team_assignments.values():
        if other["id"] == assignment["id"]:
            continue
        if other["lead_analyst_id"] != assignment["lead_analyst_id"]:
            continue
        # Every non-REVOKED assignment of the lead occupies its window.
        if other["status"] == "REVOKED":
            continue
        other_start = other["window_start"]
        if other_start is None:
            continue
        if end is None:
            if other_start >= start:
                return True
            continue
        other_end = other["window_end"]
        if other_end is None:
            if other_start <= end:
                return True
            continue
        if start < other_end and other_start < end:
            return True
    return False


def confirm(assignment, expected_rating_request_version):
    if assignment["status"] != "SCREENED":
        fail("ERR_TEAM_ASSIGNMENT_NOT_SCREENED")

    request = db.rating_requests.get(assignment["rating_request_id"])
    if request is None:
        fail("ERR_RESOURCE_NOT_FOUND")

    # Optimistic concurrency: compare against the parent's current version.
    if expected_rating_request_version is not None:
        if int(expected_rating_request_version) != int(request["version"]):
            fail("ERR_STALE_VERSION")

    lead = db.analysts.get(assignment["lead_analyst_id"])
    if lead is None:
        fail("ERR_RESOURCE_NOT_FOUND")

    # Rotation rule — the streak is recomputed first, then checked against the
    # inclusive 60-month boundary.
    months = calculations.recompute_rotation(lead, now())
    if months >= 60 and not assignment["rotation_exemption_granted"]:
        fail("ERR_ANALYST_ROTATION_REQUIRED")

    if assignment["conflict_status"] != "CLEAR":
        fail("ERR_CONFLICT_NOT_CLEARED")

    if windows_overlap(assignment):
        fail("ERR_ANALYST_ASSIGNMENT_OVERLAP")

    assignment["status"] = "CONFIRMED"
    touch(assignment)

    common.cover(assignment["id"], request["id"])

    lead["last_lead_assignment_at"] = assignment["assigned_at"]
    calculations.recompute_rotation(lead, now())
    lead["rotation_eligible"] = lead["consecutive_lead_months"] < 60
    touch(lead)

    # The parent request's version increments on a successful confirmation.
    request["updated_at"] = now()
    request["version"] = int(request["version"]) + 1
    return assignment


def revoke(assignment, revocation_reason=None):
    if assignment["status"] == "REVOKED":
        fail("ERR_TEAM_ASSIGNMENT_ALREADY_REVOKED")
    if assignment["status"] not in ("PROPOSED", "SCREENED", "CONFIRMED"):
        fail("ERR_TEAM_ASSIGNMENT_ALREADY_REVOKED")

    was_confirmed = assignment["status"] == "CONFIRMED"
    assignment["status"] = "REVOKED"
    if revocation_reason:
        assignment["revocation_reason"] = revocation_reason
    touch(assignment)
    common.COVERAGE.pop(assignment["id"], None)

    lead = db.analysts.get(assignment["lead_analyst_id"])
    if lead is not None:
        calculations.recompute_rotation(lead, now())
        lead["rotation_eligible"] = lead["consecutive_lead_months"] < 60
        touch(lead)

    request = db.rating_requests.get(assignment["rating_request_id"])
    if was_confirmed and request is not None and request["request_status"] == "TEAM_CONFIRMED":
        request["request_status"] = "SCREENING"
        touch(request)
        for committee in db.rating_committees.values():
            if committee["rating_request_id"] != request["id"]:
                continue
            if committee["committee_status"] in ("CONVENED", "IN_SESSION"):
                committee["committee_status"] = "DISSOLVED"
                touch(committee)
    return assignment