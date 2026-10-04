"""Originator resources, exposure computation, and the OCC-guarded
exposure-limit update (PRD sections 2.7 and 3.2)."""
from flask import Blueprint, g, request

from auth import ROLES, require_roles
from clock import CLOCK, banking_days_between, render_ts3
from envelope import ok
from errors import fail
from store import DB, add_record, touch
from validation import (
    get_body,
    list_response,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("originators", __name__)

RISK_TIERS = ("LOW", "STANDARD", "HIGH")
ORIGINATOR_STATES = ("PENDING_DUE_DILIGENCE", "APPROVED", "SUSPENDED", "TERMINATED")


def compute_exposures(originator_id):
    """exposure_position calculation: committed = sum over ORIGINATED entries;
    contingent = committed + sum over SETTLED entries whose return window
    (settled_date + return_timeframe_banking_days banking days) has not
    expired as of the logical clock."""
    committed = 0
    returnable = 0
    today = CLOCK.today()
    for entry in DB.payment_entries.values():
        if entry["originator_id"] != originator_id:
            continue
        if entry["status"] == "ORIGINATED":
            committed += entry["amount_cents"]
        elif entry["status"] == "SETTLED":
            code = DB.transaction_codes.get(entry["transaction_code_id"])
            if code is None:
                continue
            if (
                banking_days_between(entry["settled_date"], today)
                <= code["return_timeframe_banking_days"]
            ):
                returnable += entry["amount_cents"]
    return committed, committed + returnable


def serialize_originator(o):
    committed, contingent = compute_exposures(o["id"])
    return {
        "id": o["id"],
        "participant_id": o["participant_id"],
        "legal_name": o["legal_name"],
        "risk_tier": o["risk_tier"],
        "exposure_limit_cents": o["exposure_limit_cents"],
        "committed_exposure_cents": committed,
        "contingent_exposure_cents": contingent,
        "status": o["status"],
        "created_at": render_ts3(o["created_at"]),
        "updated_at": render_ts3(o["updated_at"]),
        "version": o["version"],
    }


def get_originator_or_404(originator_id):
    o = DB.originators.get(originator_id)
    if o is None:
        fail("ERR_NOT_FOUND", "Originator %s not found" % originator_id)
    return o


def require_owning_officer(originator):
    if g.user_id != originator["participant_id"]:
        fail("ERR_FORBIDDEN", "Originator belongs to another participant")


def participant_is_active(participant_id):
    p = DB.participants.get(participant_id)
    return p is not None and p["status"] == "ACTIVE"


@bp.post("/originators")
@require_roles("ParticipantOfficer")
def create_originator():
    body = get_body()
    legal_name = require_str(body, "legal_name")
    risk_tier = require_enum(body, "risk_tier", RISK_TIERS)
    exposure_limit_cents = require_int(body, "exposure_limit_cents")
    if exposure_limit_cents <= 0:
        fail("ERR_INVALID_REQUEST", "exposure_limit_cents must be > 0")
    rec = add_record(
        "originators",
        {
            # participant_id is bound from the acting officer's X-User-ID.
            "participant_id": g.user_id,
            "legal_name": legal_name,
            "risk_tier": risk_tier,
            "exposure_limit_cents": exposure_limit_cents,
            "status": "PENDING_DUE_DILIGENCE",
        },
    )
    return ok(serialize_originator(rec), 201)


@bp.get("/originators/<originator_id>")
@require_roles(*ROLES)
def get_originator(originator_id):
    return ok(serialize_originator(get_originator_or_404(originator_id)))


@bp.get("/originators")
@require_roles(*ROLES)
def list_originators():
    filters = []
    participant_id = request.args.get("participant_id")
    if participant_id is not None:
        filters.append(("participant_id", participant_id))
    status = request.args.get("status")
    if status is not None:
        filters.append(("status", status))
    return list_response(DB.originators.values(), serialize_originator, filters)


@bp.post("/originators/<originator_id>/transition")
@require_roles("ParticipantOfficer")
def transition_originator(originator_id):
    o = get_originator_or_404(originator_id)
    require_owning_officer(o)
    body = get_body()
    to_state = require_enum(body, "to_state", ORIGINATOR_STATES)
    current = o["status"]

    if to_state == "APPROVED":
        if current not in ("PENDING_DUE_DILIGENCE", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "Cannot transition %s to APPROVED" % current)
        if not participant_is_active(o["participant_id"]):
            fail(
                "ERR_PARTICIPANT_NOT_ACTIVE",
                "Owning participant is not ACTIVE",
            )
    elif to_state == "SUSPENDED":
        if current != "APPROVED":
            fail("ERR_INVALID_STATE", "Cannot transition %s to SUSPENDED" % current)
    elif to_state == "TERMINATED":
        if current not in ("PENDING_DUE_DILIGENCE", "APPROVED", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "Cannot transition %s to TERMINATED" % current)
    else:  # PENDING_DUE_DILIGENCE is never a legal target state
        fail("ERR_INVALID_STATE", "Cannot transition to PENDING_DUE_DILIGENCE")

    o["status"] = to_state
    touch(o)
    return ok(serialize_originator(o))


@bp.patch("/originators/<originator_id>/exposure-limit")
@require_roles("ParticipantOfficer")
def update_exposure_limit(originator_id):
    o = get_originator_or_404(originator_id)
    require_owning_officer(o)
    body = get_body()
    exposure_limit_cents = require_int(body, "exposure_limit_cents")
    if exposure_limit_cents <= 0:
        fail("ERR_INVALID_REQUEST", "exposure_limit_cents must be > 0")
    expected_version = require_int(body, "expected_originator_version")
    # OCC is evaluated LAST — after existence and all business rules (2.7/2.8).
    if expected_version != o["version"]:
        fail(
            "ERR_STALE_VERSION",
            "expected_originator_version does not match current version",
        )
    o["exposure_limit_cents"] = exposure_limit_cents
    touch(o)
    return ok(serialize_originator(o))
