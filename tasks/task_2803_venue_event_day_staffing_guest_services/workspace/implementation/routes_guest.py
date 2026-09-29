"""Guest issue intake, response deadlines, resolution and the refund ladder."""

from datetime import timedelta

from flask import Blueprint

import calc
import services as svc
from core import (
    all_rows,
    auth,
    body_dict,
    conflict,
    db,
    err,
    invalid,
    lookup,
    minutes_between,
    new_record,
    now,
    pagination,
    q_enum,
    q_str,
    req_enum,
    req_int,
    req_str,
    respond,
    respond_list,
    role_not_permitted,
    touch,
    update,
    MISSING,
)
from serialize import guest_issue_json, issue_sla_breached

bp = Blueprint("guest", __name__)

CHANNELS = ("TEXT_LINE", "IN_PERSON", "KIOSK")
CATEGORIES = (
    "SEAT_RELOCATION",
    "CONDUCT_VIOLATION",
    "ACCESSIBILITY",
    "LOST_FOUND",
    "LOST_CHILD",
    "MEDICAL",
    "OTHER",
)
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
RESOLUTION_TYPES = (
    "SEAT_RELOCATION",
    "REFUND",
    "COMPLIMENTARY_CREDIT",
    "EJECTION",
    "REUNIFICATION",
    "MEDICAL_TRANSPORT",
    "ITEM_RETURNED",
    "NO_ACTION",
)
ISSUE_STATUSES = (
    "OPEN",
    "IN_PROGRESS",
    "AWAITING_AUTHORIZATION",
    "RESOLVED",
    "REOPENED",
    "ESCALATED",
    "CLOSED",
)
REFUND_STATUSES = (
    "NONE",
    "PENDING",
    "APPROVED",
    "PARTIALLY_APPROVED",
    "DENIED",
    "VOIDED",
)
DECISIONS = ("APPROVE", "DENY", "VOID")

PERMITTED_RESOLUTIONS = {
    "SEAT_RELOCATION": ("SEAT_RELOCATION", "REFUND", "COMPLIMENTARY_CREDIT", "NO_ACTION"),
    "CONDUCT_VIOLATION": ("EJECTION", "NO_ACTION"),
    "ACCESSIBILITY": ("SEAT_RELOCATION", "COMPLIMENTARY_CREDIT", "NO_ACTION"),
    "LOST_FOUND": ("ITEM_RETURNED", "NO_ACTION"),
    "LOST_CHILD": ("REUNIFICATION",),
    "MEDICAL": ("MEDICAL_TRANSPORT", "NO_ACTION"),
    "OTHER": RESOLUTION_TYPES,
}

FORCED_CRITICAL_CATEGORIES = ("LOST_CHILD", "MEDICAL")

READ_ROLES = (
    "GuestExperienceDirector",
    "StaffingCoordinator",
    "GuestServicesSupervisor",
)
FILE_ROLES = ("GuestServicesSupervisor", "GuestExperienceDirector")


def _issue_state(issue, allowed, message=None):
    if issue["status"] not in allowed:
        raise conflict(
            "ERR_ISSUE_STATE_INVALID",
            message or "The issue stands in %s." % issue["status"],
        )


def _new_issue(fields):
    row = new_record("guest_issues", fields)
    minutes = calc.SLA_MINUTES[row["severity"]]
    row["sla_minutes"] = minutes
    row["sla_clock_started_at"] = row["created_at"]
    row["sla_deadline"] = calc.sla_deadline(row["created_at"], minutes)
    return row


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------

@bp.post("/guest-issues")
def create_guest_issue():
    user_id, _ = auth(*FILE_ROLES)
    body = body_dict()
    event_id = req_str(body, "event_id")
    channel = req_enum(body, "channel", CHANNELS)
    category = req_enum(body, "category", CATEGORIES)
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")
    seat_reference = body.get("seat_reference", MISSING)
    if seat_reference is MISSING or seat_reference is None:
        seat_reference = None
    else:
        seat_reference = req_str(body, "seat_reference")
    lookup("events", event_id)
    if category in FORCED_CRITICAL_CATEGORIES:
        severity = "CRITICAL"
    row = _new_issue(
        {
            "event_id": event_id,
            "escalated_from_issue_id": None,
            "assigned_staff_member_id": None,
            "channel": channel,
            "category": category,
            "severity": severity,
            "description": description,
            "seat_reference": seat_reference,
            "relocation_zone_code": None,
            "reported_by_user_id": user_id,
            "resolved_by_user_id": None,
            "resolution_type": None,
            "sla_minutes": 0,
            "sla_clock_started_at": None,
            "sla_deadline": None,
            "resolved_at": None,
            "reopen_count": 0,
            "refund_requested_cents": 0,
            "refund_approved_cents": 0,
            "refund_status": "NONE",
            "refund_requested_by_user_id": None,
            "refund_decided_by_user_id": None,
            "status": "OPEN",
        }
    )
    return respond(guest_issue_json(row), 201)


@bp.get("/guest-issues/<issue_id>")
def read_guest_issue(issue_id):
    auth(*READ_ROLES)
    return respond(guest_issue_json(lookup("guest_issues", issue_id)))


@bp.get("/guest-issues")
def list_guest_issues():
    auth(*READ_ROLES)
    event_id = q_str("event_id")
    parent_id = q_str("escalated_from_issue_id")
    member_id = q_str("assigned_staff_member_id")
    status = q_enum("status", ISSUE_STATUSES)
    severity = q_enum("severity", SEVERITIES)
    category = q_enum("category", CATEGORIES)
    refund_status = q_enum("refund_status", REFUND_STATUSES)
    limit, offset = pagination()
    rows = all_rows("guest_issues")
    if event_id is not None:
        rows = [r for r in rows if r["event_id"] == event_id]
    if parent_id is not None:
        rows = [r for r in rows if r["escalated_from_issue_id"] == parent_id]
    if member_id is not None:
        rows = [r for r in rows if r["assigned_staff_member_id"] == member_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if refund_status is not None:
        rows = [r for r in rows if r["refund_status"] == refund_status]
    window = rows[offset:offset + limit]
    return respond_list(
        [guest_issue_json(r) for r in window], limit, offset, len(rows)
    )


@bp.post("/guest-issues/<issue_id>/assign")
def assign_guest_issue(issue_id):
    auth("GuestServicesSupervisor")
    body = body_dict()
    member_id = req_str(body, "staff_member_id")
    issue = lookup("guest_issues", issue_id)
    member = lookup("staff_members", member_id)
    _issue_state(
        issue,
        ("OPEN", "REOPENED"),
        "Only an OPEN or REOPENED issue can be handed to a responder.",
    )
    event = db.events[issue["event_id"]]
    if event["status"] != "IN_PROGRESS":
        raise conflict(
            "ERR_EVENT_STATE_INVALID",
            "Handing out an issue requires the event in IN_PROGRESS.",
        )
    if member["status"] != "ACTIVE":
        raise conflict(
            "ERR_STAFF_MEMBER_NOT_ACTIVE",
            "The responder stands in %s." % member["status"],
        )
    if not svc.has_valid_cert(member["id"], "CODE_OF_CONDUCT"):
        raise conflict(
            "ERR_CERTIFICATION_MISSING",
            "The responder holds no VALID CODE_OF_CONDUCT credential.",
        )
    # the response clock is deliberately not restarted
    update(issue, assigned_staff_member_id=member["id"], status="IN_PROGRESS")
    return respond(guest_issue_json(issue))


@bp.post("/guest-issues/<issue_id>/escalate")
def escalate_guest_issue(issue_id):
    auth("GuestServicesSupervisor")
    issue = lookup("guest_issues", issue_id)
    _issue_state(
        issue,
        ("OPEN", "IN_PROGRESS"),
        "Only an OPEN or IN_PROGRESS issue can be escalated.",
    )
    if not issue_sla_breached(issue):
        raise conflict(
            "ERR_ISSUE_STATE_INVALID",
            "The issue is still inside its response allowance.",
        )
    update(issue, status="ESCALATED")
    child = _new_issue(
        {
            "event_id": issue["event_id"],
            "escalated_from_issue_id": issue["id"],
            "assigned_staff_member_id": None,
            "channel": issue["channel"],
            "category": issue["category"],
            "severity": "CRITICAL",
            "description": issue["description"],
            "seat_reference": issue["seat_reference"],
            "relocation_zone_code": None,
            "reported_by_user_id": issue["reported_by_user_id"],
            "resolved_by_user_id": None,
            "resolution_type": None,
            "sla_minutes": 0,
            "sla_clock_started_at": None,
            "sla_deadline": None,
            "resolved_at": None,
            "reopen_count": 0,
            "refund_requested_cents": 0,
            "refund_approved_cents": 0,
            "refund_status": "NONE",
            "refund_requested_by_user_id": None,
            "refund_decided_by_user_id": None,
            "status": "OPEN",
        }
    )
    return respond(guest_issue_json(child), 201)


# ---------------------------------------------------------------------------
# resolution, reopen and close
# ---------------------------------------------------------------------------

@bp.post("/guest-issues/<issue_id>/resolve")
def resolve_guest_issue(issue_id):
    user_id, role = auth(*FILE_ROLES)
    body = body_dict()
    resolution_type = req_enum(body, "resolution_type", RESOLUTION_TYPES)
    zone_code = body.get("relocation_zone_code", MISSING)
    if zone_code is MISSING or zone_code is None:
        zone_code = None
    else:
        zone_code = req_str(body, "relocation_zone_code")
    if resolution_type == "SEAT_RELOCATION" and zone_code is None:
        raise invalid(
            "relocation_zone_code is required for a SEAT_RELOCATION resolution."
        )
    issue = lookup("guest_issues", issue_id)
    if issue["status"] == "ESCALATED" and role != "GuestExperienceDirector":
        raise role_not_permitted(
            "Only a GuestExperienceDirector may resolve an escalated issue."
        )
    _issue_state(
        issue,
        ("IN_PROGRESS", "ESCALATED"),
        "An issue in %s cannot be resolved." % issue["status"],
    )
    if resolution_type not in PERMITTED_RESOLUTIONS[issue["category"]]:
        raise conflict(
            "ERR_RESOLUTION_TYPE_MISMATCH",
            "%s is not permitted for a %s issue."
            % (resolution_type, issue["category"]),
        )
    event = db.events[issue["event_id"]]
    if resolution_type == "SEAT_RELOCATION":
        if zone_code not in svc.staffed_zones(event):
            raise conflict(
                "ERR_RELOCATION_ZONE_UNSTAFFED",
                "Zone %s is not staffed by the event's live plan." % zone_code,
            )
    if resolution_type == "REFUND" and issue["refund_status"] not in (
        "APPROVED",
        "PARTIALLY_APPROVED",
    ):
        raise conflict(
            "ERR_REFUND_STATE_INVALID",
            "A REFUND resolution requires an authorized refund.",
        )
    changes = {
        "status": "RESOLVED",
        "resolution_type": resolution_type,
        "resolved_at": now(),
        "resolved_by_user_id": user_id,
    }
    if resolution_type == "SEAT_RELOCATION":
        changes["relocation_zone_code"] = zone_code
    update(issue, **changes)
    return respond(guest_issue_json(issue))


@bp.post("/guest-issues/<issue_id>/reopen")
def reopen_guest_issue(issue_id):
    auth("GuestServicesSupervisor")
    issue = lookup("guest_issues", issue_id)
    _issue_state(
        issue, ("RESOLVED",), "Only a RESOLVED issue can be reopened."
    )
    elapsed = minutes_between(issue["resolved_at"], now())
    if elapsed > calc.REOPEN_WINDOW_MINUTES:
        raise conflict(
            "ERR_REOPEN_WINDOW_CLOSED",
            "The %d-minute reopen window has expired." % calc.REOPEN_WINDOW_MINUTES,
        )
    if issue["reopen_count"] >= 2:
        raise conflict(
            "ERR_REOPEN_LIMIT_REACHED", "The issue has already been reopened twice."
        )
    # money already authorized is never clawed back by a reopen
    update(
        issue,
        status="REOPENED",
        reopen_count=issue["reopen_count"] + 1,
        resolved_at=None,
        resolution_type=None,
        resolved_by_user_id=None,
    )
    return respond(guest_issue_json(issue))


@bp.post("/guest-issues/<issue_id>/close")
def close_guest_issue(issue_id):
    auth("GuestServicesSupervisor")
    issue = lookup("guest_issues", issue_id)
    _issue_state(issue, ("RESOLVED",), "Only a RESOLVED issue can be closed.")
    elapsed = minutes_between(issue["resolved_at"], now())
    if elapsed <= calc.REOPEN_WINDOW_MINUTES:
        raise conflict(
            "ERR_REOPEN_WINDOW_CLOSED",
            "The issue can only be closed once its reopen window has expired.",
        )
    update(issue, status="CLOSED")
    return respond(guest_issue_json(issue))


# ---------------------------------------------------------------------------
# the two-step refund ladder (§3.8)
# ---------------------------------------------------------------------------

@bp.post("/guest-issues/<issue_id>/refund-request")
def request_refund(issue_id):
    user_id, _ = auth("GuestServicesSupervisor")
    body = body_dict()
    amount = req_int(body, "refund_requested_cents", minimum=0)
    issue = lookup("guest_issues", issue_id)
    if issue["status"] == "CLOSED":
        raise conflict(
            "ERR_ISSUE_STATE_INVALID", "A CLOSED issue is frozen."
        )
    # no money moves here and the event ledger does not change
    update(
        issue,
        refund_requested_cents=amount,
        refund_requested_by_user_id=user_id,
        refund_status="PENDING",
    )
    return respond(guest_issue_json(issue))


@bp.post("/guest-issues/<issue_id>/refund-decision")
def decide_refund(issue_id):
    user_id, role = auth(*FILE_ROLES)
    body = body_dict()
    decision = req_enum(body, "decision", DECISIONS)
    if decision == "VOID" and role != "GuestExperienceDirector":
        raise role_not_permitted(
            "Only a GuestExperienceDirector may reverse an authorization."
        )
    issue = lookup("guest_issues", issue_id)
    # rung 8: the decider must be neither the requester nor the reporter
    if user_id == issue["refund_requested_by_user_id"] or user_id == issue[
        "reported_by_user_id"
    ]:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The deciding operator may not be the requester or the reporter.",
        )
    if issue["status"] == "CLOSED":
        raise conflict("ERR_ISSUE_STATE_INVALID", "A CLOSED issue is frozen.")
    event = db.events[issue["event_id"]]

    if decision == "DENY":
        update(
            issue,
            refund_status="DENIED",
            refund_approved_cents=0,
            refund_decided_by_user_id=user_id,
        )
        svc.rederive_ledger(event)
        return respond(guest_issue_json(issue))

    if decision == "VOID":
        if issue["refund_status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
            raise conflict(
                "ERR_REFUND_STATE_INVALID",
                "There is no live authorization to reverse.",
            )
        update(
            issue,
            refund_status="VOIDED",
            refund_approved_cents=0,
            refund_decided_by_user_id=user_id,
        )
        svc.rederive_ledger(event)
        return respond(guest_issue_json(issue))

    # APPROVE
    if issue["refund_status"] not in ("NONE", "PENDING", "PARTIALLY_APPROVED"):
        raise conflict(
            "ERR_REFUND_STATE_INVALID",
            "A %s refund does not admit an approval." % issue["refund_status"],
        )
    available = event["refund_budget_remaining_cents"] + issue["refund_approved_cents"]
    if available <= 0:
        raise conflict(
            "ERR_REFUND_BUDGET_EXHAUSTED",
            "The guest-recovery budget is exhausted.",
        )
    requested = issue["refund_requested_cents"]
    cap = calc.effective_refund_cap(role, issue["severity"], issue["category"])
    authorized = min(requested, cap, available)
    changes = {
        "refund_approved_cents": authorized,
        "refund_decided_by_user_id": user_id,
        "refund_status": "APPROVED" if authorized == requested else "PARTIALLY_APPROVED",
    }
    if (
        role == "GuestExperienceDirector"
        and issue["status"] == "AWAITING_AUTHORIZATION"
    ):
        # the director finishes the job in one request
        changes["status"] = "RESOLVED"
        changes["resolution_type"] = "REFUND"
        changes["resolved_at"] = now()
        changes["resolved_by_user_id"] = user_id
    elif role == "GuestServicesSupervisor" and cap < min(requested, available):
        changes["status"] = "AWAITING_AUTHORIZATION"
    update(issue, **changes)
    svc.rederive_ledger(event)
    return respond(guest_issue_json(issue))
