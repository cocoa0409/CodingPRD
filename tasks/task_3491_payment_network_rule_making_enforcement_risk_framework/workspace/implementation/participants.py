"""Participant resources and the suspension/termination cascades (PRD
sections 2.9 and 3.1)."""
import re

from flask import Blueprint, request

from auth import ROLES, require_roles
from clock import render_ts3
from envelope import ok
from errors import fail
from store import DB, add_record, touch
from validation import get_body, list_response, require_enum, require_str

bp = Blueprint("participants", __name__)

PARTICIPANT_TYPES = ("ODFI", "RDFI", "BOTH")
PARTICIPANT_STATES = ("ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED")
_ROUTING_RE = re.compile(r"[0-9]{9}")


def serialize_participant(p):
    return {
        "id": p["id"],
        "legal_name": p["legal_name"],
        "participant_type": p["participant_type"],
        "routing_number": p["routing_number"],
        "status": p["status"],
        "current_period": p["current_period"],
        "current_period_fees_cents": p["current_period_fees_cents"],
        "created_at": render_ts3(p["created_at"]),
        "updated_at": render_ts3(p["updated_at"]),
        "version": p["version"],
    }


def get_participant_or_404(participant_id):
    p = DB.participants.get(participant_id)
    if p is None:
        fail("ERR_NOT_FOUND", "Participant %s not found" % participant_id)
    return p


def has_unresolved_enforcement(participant_id):
    """Any EnforcementAction of this participant in ISSUED or CONTESTED."""
    return any(
        a["participant_id"] == participant_id and a["status"] in ("ISSUED", "CONTESTED")
        for a in DB.enforcement_actions.values()
    )


def cascade_suspend_participant(participant):
    """PRD 2.9 link 1+2: every APPROVED originator of the participant becomes
    SUSPENDED, and every ORIGINATED entry of each such originator becomes
    CANCELLED, releasing its amount from the originator's exposure. Each
    mutated resource gets its own version increment."""
    for originator in DB.originators.values():
        if (
            originator["participant_id"] != participant["id"]
            or originator["status"] != "APPROVED"
        ):
            continue
        originator["status"] = "SUSPENDED"
        touch(originator)
        for entry in DB.payment_entries.values():
            if entry["originator_id"] == originator["id"] and entry["status"] == "ORIGINATED":
                entry["status"] = "CANCELLED"
                touch(entry)
                # The cancellation moves exposure, which advances the
                # originator's version (same release as a manual cancel).
                touch(originator)


def cascade_terminate_participant(participant):
    """PRD 2.9: terminating a participant terminates all of its originators in
    PENDING_DUE_DILIGENCE, APPROVED, or SUSPENDED."""
    for originator in DB.originators.values():
        if originator["participant_id"] != participant["id"]:
            continue
        if originator["status"] in ("PENDING_DUE_DILIGENCE", "APPROVED", "SUSPENDED"):
            originator["status"] = "TERMINATED"
            touch(originator)


@bp.post("/participants")
@require_roles("PlatformAdmin")
def create_participant():
    body = get_body()
    legal_name = require_str(body, "legal_name")
    participant_type = require_enum(body, "participant_type", PARTICIPANT_TYPES)
    routing_number = require_str(body, "routing_number")
    if _ROUTING_RE.fullmatch(routing_number) is None:
        fail("ERR_INVALID_REQUEST", "routing_number must be exactly 9 ASCII digits")
    for p in DB.participants.values():
        if p["routing_number"] == routing_number:
            fail("ERR_DUPLICATE_RESOURCE", "routing_number already in use")
    rec = add_record(
        "participants",
        {
            "legal_name": legal_name,
            "participant_type": participant_type,
            "routing_number": routing_number,
            "status": "ONBOARDING",
            "current_period": None,
            "current_period_fees_cents": 0,
        },
    )
    return ok(serialize_participant(rec), 201)


@bp.get("/participants/<participant_id>")
@require_roles(*ROLES)
def get_participant(participant_id):
    return ok(serialize_participant(get_participant_or_404(participant_id)))


@bp.get("/participants")
@require_roles(*ROLES)
def list_participants():
    filters = []
    status = request.args.get("status")
    if status is not None:
        filters.append(("status", status))
    participant_type = request.args.get("participant_type")
    if participant_type is not None:
        filters.append(("participant_type", participant_type))
    return list_response(DB.participants.values(), serialize_participant, filters)


@bp.post("/participants/<participant_id>/transition")
@require_roles("PlatformAdmin")
def transition_participant(participant_id):
    p = get_participant_or_404(participant_id)
    body = get_body()
    to_state = require_enum(body, "to_state", PARTICIPANT_STATES)
    current = p["status"]

    if to_state == "ACTIVE":
        if current == "ONBOARDING":
            pass
        elif current == "SUSPENDED":
            if has_unresolved_enforcement(p["id"]):
                fail(
                    "ERR_UNRESOLVED_ENFORCEMENT",
                    "Participant has enforcement actions in ISSUED or CONTESTED",
                )
        else:
            fail("ERR_INVALID_STATE", "Cannot transition %s to ACTIVE" % current)
        p["status"] = "ACTIVE"
    elif to_state == "SUSPENDED":
        if current != "ACTIVE":
            fail("ERR_INVALID_STATE", "Cannot transition %s to SUSPENDED" % current)
        p["status"] = "SUSPENDED"
        touch(p)
        cascade_suspend_participant(p)
        return ok(serialize_participant(p))
    elif to_state == "TERMINATED":
        if current not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "Cannot transition %s to TERMINATED" % current)
        p["status"] = "TERMINATED"
        touch(p)
        cascade_terminate_participant(p)
        return ok(serialize_participant(p))
    else:  # ONBOARDING is never a legal target state
        fail("ERR_INVALID_STATE", "Cannot transition to ONBOARDING")

    touch(p)
    return ok(serialize_participant(p))
