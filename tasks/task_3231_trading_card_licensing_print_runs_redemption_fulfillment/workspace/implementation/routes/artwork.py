"""ArtworkApproval resource: submit artwork and record the licensor's decision."""

import datetime

from flask import jsonify, request

import db
import requtil
import response
from core import app
from common import (
    license_in_force,
    recompute_license_counts,
    serialize,
)
from errors import (
    ApiError,
    ERR_APPROVAL_WINDOW_CLOSED,
    ERR_ARTWORK_APPROVAL_NOT_FOUND,
    ERR_CARD_SET_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_NOT_IN_FORCE,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import authenticate, require_licensor_ownership, require_role

READ_ROLES = ["ProductManager", "LicensorApprover", "PlatformAdmin"]


def _get(approval_id):
    rec = db.STORE.get("artwork_approvals", approval_id)
    if rec is None:
        raise ApiError(
            ERR_ARTWORK_APPROVAL_NOT_FOUND,
            "No ArtworkApproval exists with id %s" % approval_id,
        )
    return rec


def _serialize(rec):
    return serialize("artwork_approvals", rec)


def _deadline(lic, approval):
    return approval["submitted_on"] + datetime.timedelta(days=lic["approval_window_days"])


@app.route("/api/card-sets/<card_set_id>/artwork-approvals", methods=["POST"])
def create_artwork_approval(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    data = requtil.body()
    artwork_code = requtil.required_str(data, "artwork_code")
    approver_id = requtil.required_str(data, "approver_id")
    submitted_on = requtil.required_dt(data, "submitted_on")

    store = db.STORE
    if not store.exists("card_sets", card_set_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "card_set_id %s does not resolve" % card_set_id
        )
    if not store.exists("licenses", approver_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "approver_id %s does not resolve" % approver_id
        )

    now = store.now()
    rec = db.record("artwork_approvals", {
        "card_set_id": card_set_id,
        "artwork_code": artwork_code,
        "approver_id": approver_id,
        "submitted_on": submitted_on,
        "decided_on": None,
        "status": "SUBMITTED",
    }, now)
    store.insert("artwork_approvals", rec)

    card_set = store.get("card_sets", card_set_id)
    db.bump(card_set, now)
    return jsonify(response.ok_object(_serialize(rec))), 201


@app.route("/api/card-sets/<card_set_id>/artwork-approvals", methods=["GET"])
def list_set_artwork(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    if not db.STORE.exists("card_sets", card_set_id):
        raise ApiError(
            ERR_CARD_SET_NOT_FOUND, "No CardSet exists with id %s" % card_set_id
        )
    return _list_artwork({"card_set_id": card_set_id})


@app.route("/api/artwork-approvals", methods=["GET"])
def list_artwork():
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    return _list_artwork({})


def _list_artwork(fixed):
    store = db.STORE
    items = list(store.all("artwork_approvals"))
    card_set_id = fixed.get("card_set_id") or requtil.filter_value("card_set_id")
    approver_id = requtil.filter_value("approver_id")
    status = requtil.filter_value("status")
    if card_set_id is not None:
        items = [a for a in items if a["card_set_id"] == card_set_id]
    if approver_id is not None:
        items = [a for a in items if a["approver_id"] == approver_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(
        response.paginate([_serialize(a) for a in items], request.args)
    ), 200


@app.route("/api/artwork-approvals/<approval_id>", methods=["GET"])
def get_artwork(approval_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    rec = _get(approval_id)
    require_licensor_ownership(principal, rec["approver_id"])
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/artwork-approvals/<approval_id>/decide", methods=["POST"])
def decide_artwork(approval_id):
    principal = authenticate(request.headers)
    require_role(principal, ["LicensorApprover"])

    store = db.STORE
    now = store.now()
    rec = _get(approval_id)

    # The licensor acts for exactly one licensor instance at a time.
    require_licensor_ownership(principal, rec["approver_id"])

    data = requtil.body()
    decision = requtil.required(data, "decision")
    if not isinstance(decision, str) or decision not in ("APPROVE", "REJECT"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT")
    decided_on = requtil.required_dt(data, "decided_on")

    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Artwork approval is not SUBMITTED")

    lic = store.get("licenses", rec["approver_id"])
    if lic is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "The approver license does not resolve")

    # The same deadline governs approval and rejection.
    if now > _deadline(lic, rec):
        raise ApiError(ERR_APPROVAL_WINDOW_CLOSED, "The approval window has closed")

    if decision == "APPROVE":
        # No license-in-force gate appears on the rejection branch; the
        # asymmetry is deliberate (PRD 3.2).
        if not license_in_force(lic, now):
            raise ApiError(
                ERR_LICENSE_NOT_IN_FORCE,
                "The license holding the approval right is not in force",
            )
        rec["status"] = "APPROVED"
        rec["decided_on"] = decided_on
        db.bump(rec, now)
        db.bump(lic, now)
        recompute_license_counts(store, lic["id"], now)
        return jsonify(response.ok_object(_serialize(rec))), 200

    rec["status"] = "REJECTED"
    rec["decided_on"] = decided_on
    db.bump(rec, now)

    # If the rejection leaves the card set with no remaining APPROVED artwork
    # at all, that card set is returned to DRAFT.
    card_set_id = rec["card_set_id"]
    remaining = any(
        a["status"] == "APPROVED"
        for a in store.all("artwork_approvals")
        if a["card_set_id"] == card_set_id
    )
    if not remaining:
        card_set = store.get("card_sets", card_set_id)
        if card_set is not None:
            card_set["status"] = "DRAFT"
            db.touch(card_set, now)
    return jsonify(response.ok_object(_serialize(rec))), 200