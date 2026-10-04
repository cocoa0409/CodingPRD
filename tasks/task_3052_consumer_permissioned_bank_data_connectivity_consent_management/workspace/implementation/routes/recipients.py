"""Recipient routes: create/list/get/review/suspend."""

from flask import Blueprint, request

import db
from middleware import require_role, parse_limit_offset
from response import success_object, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_SOD_VIOLATION, ERR_DUPLICATE_ACTIVE,
)
from services import core
from services.serializers import recipient_out

bp = Blueprint("recipients", __name__)

ALL_READ_ROLES = ("PlatformAdmin", "ComplianceReviewer", "Consumer", "Recipient")


def _get_recipient(recipient_id):
    r = db.recipients.get(recipient_id)
    if r is None:
        raise err(ERR_NOT_FOUND, "Recipient not found")
    return r


def revocation_cascade_for_recipient(recipient):
    """Revoke all ACTIVE consents of a recipient, disconnect connections,
    emit CONSENT_REVOKED webhooks. Used by suspend and reject."""
    for consent in list(db.consents.values()):
        if consent["recipient_id"] == recipient["id"] and consent["status"] == "ACTIVE":
            core.revoke_consent_cascade(consent, write_audit=False)


def end_active_tier_assignment(recipient):
    for ta in db.tier_assignments.values():
        if ta["recipient_id"] == recipient["id"] and ta["status"] == "ACTIVE":
            ta["status"] = "ENDED"
            core.touch(ta)


@bp.route("/recipients", methods=["POST"])
def create_recipient():
    user_id, role = require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    declared_use_case = body.get("declared_use_case")
    minimization_policy = body.get("minimization_policy")

    if not isinstance(name, str) or not name.strip():
        raise err(ERR_INVALID_REQUEST, "name must be a non-empty string")
    if not isinstance(declared_use_case, str):
        raise err(ERR_INVALID_REQUEST, "declared_use_case must be a string")
    if minimization_policy not in core.MINIMIZATION:
        raise err(ERR_INVALID_REQUEST, "minimization_policy must be STRICT, STANDARD, or BROAD")

    for other in db.recipients.values():
        if other["name"] == name:
            raise err(ERR_DUPLICATE_ACTIVE, "recipient name must be unique")

    r = {
        "name": name,
        "declared_use_case": declared_use_case,
        "minimization_policy": minimization_policy,
        "status": "PENDING_REVIEW",
        "_created_by": user_id,
        "_suspended_by": None,
        "_last_decision_by": None,  # reviewer id of last review decision
    }
    core.stamp_new(r)
    db.recipients[r["id"]] = r
    return success_object(recipient_out(r), 201)


@bp.route("/recipients", methods=["GET"])
def list_recipients():
    require_role(*ALL_READ_ROLES)
    limit, offset = parse_limit_offset(request.args)
    status_filter = request.args.get("status")
    items = list(db.recipients.values())
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([recipient_out(r) for r in page], limit, offset, total)


@bp.route("/recipients/<recipientId>", methods=["GET"])
def get_recipient(recipientId):
    require_role(*ALL_READ_ROLES)
    r = _get_recipient(recipientId)
    return success_object(recipient_out(r))


@bp.route("/recipients/<recipientId>/review", methods=["POST"])
def review_recipient(recipientId):
    user_id, role = require_role("ComplianceReviewer")
    r = _get_recipient(recipientId)
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise err(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT")

    current = r["status"]

    # Determine the applicable transition and SoD reference actor.
    # Transitions:
    #  PENDING_REVIEW --APPROVE--> APPROVED (SoD vs creator)
    #  PENDING_REVIEW --REJECT--> REJECTED (SoD vs creator)
    #  SUSPENDED --APPROVE--> APPROVED (SoD vs suspender)
    #  REJECTED --APPROVE--> APPROVED (SoD vs original rejecting reviewer)
    #  APPROVED --REJECT--> REJECTED (SoD vs approving reviewer)
    #  anything else -> ERR_INVALID_STATE
    if current == "PENDING_REVIEW":
        sod_ref = r["_created_by"]
        valid = True
    elif current == "SUSPENDED" and decision == "APPROVE":
        sod_ref = r["_suspended_by"]
        valid = True
    elif current == "REJECTED" and decision == "APPROVE":
        sod_ref = r["_last_decision_by"]
        valid = True
    elif current == "APPROVED" and decision == "REJECT":
        sod_ref = r["_last_decision_by"]
        valid = True
    else:
        valid = False
        sod_ref = None

    # Priority 4: SOD before state legality? PRD §2.9: SOD is priority 4,
    # state is priority 5. But SOD only applies to a *review* — if there is no
    # valid transition at all (e.g. SUSPENDED + REJECT), that's a state error.
    # The PRD example: "a reviewer who created a recipient and then attempts to
    # review it after the recipient was suspended by a different admin sees
    # ERR_SOD_VIOLATION before any state discussion" — that implies the SOD
    # check runs whenever a review is attempted and the reviewer matches the
    # prior decision actor, even before deciding whether the transition exists.
    # We implement: compute the SoD reference actor for the current state
    # regardless of decision validity, check it first, then state legality.
    sod_refs = {
        "PENDING_REVIEW": r["_created_by"],
        "SUSPENDED": r["_suspended_by"],
        "REJECTED": r["_last_decision_by"],
        "APPROVED": r["_last_decision_by"],
    }
    ref_actor = sod_refs.get(current)
    if ref_actor is not None and ref_actor == user_id:
        raise err(ERR_SOD_VIOLATION,
                  "Reviewer must differ from the prior decision actor")

    if not valid:
        raise err(ERR_INVALID_STATE,
                  f"Recipient in state {current} does not permit decision {decision}")

    old_status = r["status"]
    if decision == "APPROVE":
        r["status"] = "APPROVED"
        if old_status == "PENDING_REVIEW":
            action = "recipient.approve"
        elif old_status == "SUSPENDED":
            action = "recipient.reinstate"
        else:  # REJECTED appeal
            action = "recipient.approve"
        r["_last_decision_by"] = user_id
        core.audit(role, action, "Recipient", r["id"],
                   {"old_status": old_status, "new_status": "APPROVED"})
    else:  # REJECT
        r["status"] = "REJECTED"
        revocation_cascade_for_recipient(r)
        end_active_tier_assignment(r)
        r["_last_decision_by"] = user_id
        core.audit(role, "recipient.reject", "Recipient", r["id"],
                   {"old_status": old_status, "new_status": "REJECTED"})

    core.touch(r)
    return success_object(recipient_out(r))


@bp.route("/recipients/<recipientId>/suspend", methods=["POST"])
def suspend_recipient(recipientId):
    user_id, role = require_role("PlatformAdmin")
    r = _get_recipient(recipientId)
    if r["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Only an APPROVED recipient may be suspended")
    r["status"] = "SUSPENDED"
    r["_suspended_by"] = user_id
    revocation_cascade_for_recipient(r)
    end_active_tier_assignment(r)
    core.touch(r)
    return success_object(recipient_out(r))
