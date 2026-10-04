"""Enforcement domain: InquiryCases and EnforcementActions, including the
three-strike suspension cascade and the fine schedule (PRD section 3.8)."""
from flask import Blueprint, g, request

from auth import ROLES, require_roles
from clock import CLOCK, render_date, render_ts, render_ts3
from envelope import ok
from errors import fail
from participants import cascade_suspend_participant
from store import DB, add_record, touch
from validation import (
    get_body,
    list_response,
    optional_str,
    require_enum,
    require_str,
)

bp = Blueprint("enforcement", __name__)

INQUIRY_STATES = ("OPENED", "RESPONSE_SUBMITTED", "RESOLVED", "ESCALATED")
VIOLATION_CODES = (
    "EXCESSIVE_UNAUTHORIZED_RETURNS",
    "EXCESSIVE_ADMINISTRATIVE_RETURNS",
    "MISSING_ACCOUNT_VALIDATION",
    "LATE_ATTESTATION",
    "AUDIT_NONCOMPLIANCE",
)
ACTION_STATES = ("ISSUED", "CONTESTED", "UPHELD", "WITHDRAWN", "PAID")
VIOLATION_BY_RETURN_CLASS = {
    "UNAUTHORIZED": "EXCESSIVE_UNAUTHORIZED_RETURNS",
    "ADMINISTRATIVE": "EXCESSIVE_ADMINISTRATIVE_RETURNS",
    "OVERALL": "EXCESSIVE_UNAUTHORIZED_RETURNS",
}

# enforcement_fine_schedule constants (integer cents)
FINE_BASE_BY_TIER = [5000000, 10000000, 25000000, 50000000]
LATE_GRACE_DAYS = 30
LATE_DAILY_CENTS = 100000
STATUTORY_CAP_CENTS = 100000000


def serialize_inquiry(iq):
    return {
        "id": iq["id"],
        "participant_id": iq["participant_id"],
        "return_rate_snapshot_id": iq["return_rate_snapshot_id"],
        "return_class": iq["return_class"],
        "response_deadline": render_ts(iq["response_deadline"]),
        "response_text": iq["response_text"],
        "status": iq["status"],
        "created_at": render_ts3(iq["created_at"]),
        "updated_at": render_ts3(iq["updated_at"]),
        "version": iq["version"],
    }


def serialize_action(a):
    return {
        "id": a["id"],
        "participant_id": a["participant_id"],
        "inquiry_case_id": a["inquiry_case_id"],
        "violation_code": a["violation_code"],
        "escalation_tier": a["escalation_tier"],
        "fine_base_cents": a["fine_base_cents"],
        "fine_total_cents": a["fine_total_cents"],
        "escalated_by_user_id": a["escalated_by_user_id"],
        "issued_date": render_date(a["issued_date"]),
        "paid_at": render_ts(a["paid_at"]),
        "status": a["status"],
        "created_at": render_ts3(a["created_at"]),
        "updated_at": render_ts3(a["updated_at"]),
        "version": a["version"],
    }


def get_inquiry_or_404(inquiry_id):
    iq = DB.inquiry_cases.get(inquiry_id)
    if iq is None:
        fail("ERR_NOT_FOUND", "Inquiry case %s not found" % inquiry_id)
    return iq


def get_action_or_404(action_id):
    a = DB.enforcement_actions.get(action_id)
    if a is None:
        fail("ERR_NOT_FOUND", "Enforcement action %s not found" % action_id)
    return a


def upheld_or_paid_count(participant_id):
    return sum(
        1
        for a in DB.enforcement_actions.values()
        if a["participant_id"] == participant_id and a["status"] in ("UPHELD", "PAID")
    )


def compute_tier_and_base(participant):
    """enforcement_fine_schedule: tier = min(prior UPHELD/PAID count, 3);
    base = BASE_BY_TIER[tier] * type multiplier (exact integers for all three
    multipliers), capped at the statutory maximum."""
    tier = min(upheld_or_paid_count(participant["id"]), 3)
    base = FINE_BASE_BY_TIER[tier]
    participant_type = participant["participant_type"]
    if participant_type == "RDFI":
        base = base // 2
    elif participant_type == "BOTH":
        base = (base * 3) // 2
    return tier, min(base, STATUTORY_CAP_CENTS)


def create_enforcement_action(participant, violation_code, inquiry_case_id, escalated_by):
    tier, fine_base = compute_tier_and_base(participant)
    return add_record(
        "enforcement_actions",
        {
            "participant_id": participant["id"],
            "inquiry_case_id": inquiry_case_id,
            "violation_code": violation_code,
            "escalation_tier": tier,
            "fine_base_cents": fine_base,
            "fine_total_cents": None,
            "escalated_by_user_id": escalated_by,
            "issued_date": CLOCK.today(),
            "paid_at": None,
            "status": "ISSUED",
        },
    )


# ---------------------------------------------------------------------------
# Inquiry cases
# ---------------------------------------------------------------------------


@bp.get("/inquiry-cases/<inquiry_id>")
@require_roles(*ROLES)
def get_inquiry_case(inquiry_id):
    return ok(serialize_inquiry(get_inquiry_or_404(inquiry_id)))


@bp.get("/inquiry-cases")
@require_roles(*ROLES)
def list_inquiry_cases():
    filters = []
    for param in ("participant_id", "return_rate_snapshot_id", "status"):
        value = request.args.get(param)
        if value is not None:
            filters.append((param, value))
    return list_response(DB.inquiry_cases.values(), serialize_inquiry, filters)


@bp.post("/inquiry-cases/<inquiry_id>/respond")
@require_roles("ParticipantOfficer")
def respond_inquiry(inquiry_id):
    iq = get_inquiry_or_404(inquiry_id)
    if iq["participant_id"] != g.user_id:
        fail("ERR_FORBIDDEN", "Inquiry belongs to another participant")
    body = get_body()
    response_text = require_str(body, "response_text")
    if iq["status"] != "OPENED":
        fail("ERR_INVALID_STATE", "Inquiry is not OPENED")
    iq["response_text"] = response_text
    iq["status"] = "RESPONSE_SUBMITTED"
    touch(iq)
    return ok(serialize_inquiry(iq))


@bp.post("/inquiry-cases/<inquiry_id>/resolve")
@require_roles("PlatformAdmin")
def resolve_inquiry(inquiry_id):
    iq = get_inquiry_or_404(inquiry_id)
    if iq["status"] != "RESPONSE_SUBMITTED":
        fail("ERR_INVALID_STATE", "Inquiry is not RESPONSE_SUBMITTED")
    iq["status"] = "RESOLVED"
    touch(iq)
    return ok(serialize_inquiry(iq))


@bp.post("/inquiry-cases/<inquiry_id>/escalate")
@require_roles("PlatformAdmin")
def escalate_inquiry(inquiry_id):
    iq = get_inquiry_or_404(inquiry_id)
    if iq["status"] == "OPENED":
        # Escalation out of OPENED requires the deadline to have passed.
        if not CLOCK.now() > iq["response_deadline"]:
            fail(
                "ERR_RESPONSE_DEADLINE_NOT_PASSED",
                "Response deadline has not passed",
            )
    elif iq["status"] != "RESPONSE_SUBMITTED":
        fail("ERR_INVALID_STATE", "Inquiry cannot be escalated from %s" % iq["status"])

    iq["status"] = "ESCALATED"
    touch(iq)
    participant = DB.participants.get(iq["participant_id"])
    if participant is None:
        fail("ERR_NOT_FOUND", "Participant %s not found" % iq["participant_id"])
    action = create_enforcement_action(
        participant,
        VIOLATION_BY_RETURN_CLASS[iq["return_class"]],
        iq["id"],
        g.user_id,
    )
    return ok(serialize_action(action))


# ---------------------------------------------------------------------------
# Enforcement actions
# ---------------------------------------------------------------------------


@bp.post("/enforcement-actions")
@require_roles("PlatformAdmin")
def create_enforcement_action_endpoint():
    body = get_body()
    participant_id = require_str(body, "participant_id")
    violation_code = require_enum(body, "violation_code", VIOLATION_CODES)
    inquiry_case_id = optional_str(body, "inquiry_case_id")
    participant = DB.participants.get(participant_id)
    if participant is None:
        fail("ERR_NOT_FOUND", "Participant %s not found" % participant_id)
    if inquiry_case_id is not None and inquiry_case_id not in DB.inquiry_cases:
        fail("ERR_NOT_FOUND", "Inquiry case %s not found" % inquiry_case_id)
    # Direct filing: escalated_by_user_id stays null.
    action = create_enforcement_action(participant, violation_code, inquiry_case_id, None)
    return ok(serialize_action(action), 201)


@bp.get("/enforcement-actions/<action_id>")
@require_roles(*ROLES)
def get_enforcement_action(action_id):
    return ok(serialize_action(get_action_or_404(action_id)))


@bp.get("/enforcement-actions")
@require_roles(*ROLES)
def list_enforcement_actions():
    filters = []
    for param in ("participant_id", "inquiry_case_id", "status"):
        value = request.args.get(param)
        if value is not None:
            filters.append((param, value))
    return list_response(DB.enforcement_actions.values(), serialize_action, filters)


@bp.post("/enforcement-actions/<action_id>/transition")
@require_roles("PlatformAdmin")
def transition_enforcement_action(action_id):
    a = get_action_or_404(action_id)
    body = get_body()
    to_state = require_enum(body, "to_state", ACTION_STATES)
    current = a["status"]

    if to_state == "CONTESTED":
        if current != "ISSUED":
            fail("ERR_INVALID_STATE", "Cannot transition %s to CONTESTED" % current)
        a["status"] = "CONTESTED"
    elif to_state == "UPHELD":
        if current not in ("ISSUED", "CONTESTED"):
            fail("ERR_INVALID_STATE", "Cannot transition %s to UPHELD" % current)
        # Segregation of duties: the admin who escalated the parent inquiry
        # cannot uphold the resulting action.
        if (
            a["escalated_by_user_id"] is not None
            and a["escalated_by_user_id"] == g.user_id
        ):
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "The escalating admin may not uphold this action",
            )
        a["status"] = "UPHELD"
        touch(a)
        # Three-strike rule: at >= 3 cumulative UPHELD/PAID actions (this one
        # included) the participant is suspended with the full cascade.
        participant = DB.participants.get(a["participant_id"])
        if (
            participant is not None
            and participant["status"] == "ACTIVE"
            and upheld_or_paid_count(participant["id"]) >= 3
        ):
            participant["status"] = "SUSPENDED"
            touch(participant)
            cascade_suspend_participant(participant)
        return ok(serialize_action(a))
    elif to_state == "WITHDRAWN":
        if current not in ("ISSUED", "CONTESTED"):
            fail("ERR_INVALID_STATE", "Cannot transition %s to WITHDRAWN" % current)
        a["status"] = "WITHDRAWN"
    elif to_state == "PAID":
        if current not in ("ISSUED", "UPHELD"):
            fail("ERR_INVALID_STATE", "Cannot transition %s to PAID" % current)
        days = (CLOCK.today() - a["issued_date"]).days
        days_overdue = max(0, days - LATE_GRACE_DAYS)
        a["fine_total_cents"] = min(
            a["fine_base_cents"] + LATE_DAILY_CENTS * days_overdue,
            STATUTORY_CAP_CENTS,
        )
        a["paid_at"] = CLOCK.now()
        a["status"] = "PAID"
    else:  # ISSUED is never a legal target state
        fail("ERR_INVALID_STATE", "Cannot transition to ISSUED")

    touch(a)
    return ok(serialize_action(a))
