"""SigningSession resource: booking, stock logistics, completion and cancel.

Two governing regimes (PRD 3.4): a PLAYER_ASSOCIATION signer is bound by the
license term window, whereas an INDEPENDENT signer carries no license tie and
only the overlap rule applies.  The signer-availability overlap rule applies to
signers of either kind.
"""

import datetime

from flask import jsonify, request

import calc
import db
import requtil
import response
from core import app
from common import (
    license_in_force,
    recompute_license_counts,
    serialize,
)
from constants import (
    SIGNER_ATTENDANCE,
    SIGNER_KINDS,
    SIGNER_ROYALTY_CENTS,
    SIGNER_SHIP_LEAD_DAYS,
)
from errors import (
    ApiError,
    ERR_AUTOGRAPH_ALLOCATION_EXCEEDS_PLAN,
    ERR_AUTOGRAPH_AUTHENTICATION_FAILED,
    ERR_CARD_SET_NOT_APPROVED,
    ERR_CARD_STOCK_NOT_PRODUCED_AT_SIGNING,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_NOT_IN_FORCE,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SIGNER_DOUBLE_BOOKED,
    ERR_SIGNER_SHIP_WINDOW_CLOSED,
    ERR_SIGNING_SESSION_NOT_FOUND,
)
from middleware import authenticate, require_role

READ_ROLES = ["SigningCoordinator", "ProductionPlanner", "PlatformAdmin"]
ACTIVE_SESSION_STATUSES = ("SCHEDULED", "STOCK_PREPARED", "STOCK_SHIPPED")


def _get(session_id):
    rec = db.STORE.get("signing_sessions", session_id)
    if rec is None:
        raise ApiError(
            ERR_SIGNING_SESSION_NOT_FOUND,
            "No SigningSession exists with id %s" % session_id,
        )
    return rec


def _serialize(rec):
    store = db.STORE
    rec["total_allocated_count"] = sum(
        line["quantity_delivered"] for line in rec["allocation_lines"]
    )
    return serialize("signing_sessions", rec)


def _parse_allocation_lines(raw):
    """Each line is { card_set_id, player_id, quantity_delivered }; the
    quantity is a client-declared literal."""
    if raw is None:
        raise ApiError(ERR_INVALID_REQUEST, "allocation_lines is required")
    if not isinstance(raw, list):
        raise ApiError(ERR_INVALID_REQUEST, "allocation_lines must be an array")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, "Each allocation line must be an object")
        card_set_id = entry.get("card_set_id")
        player_id = entry.get("player_id")
        quantity = entry.get("quantity_delivered")
        if not isinstance(card_set_id, str) or not card_set_id:
            raise ApiError(
                ERR_INVALID_REQUEST, "allocation_lines[].card_set_id must be a string"
            )
        if not isinstance(player_id, str) or not player_id:
            raise ApiError(
                ERR_INVALID_REQUEST, "allocation_lines[].player_id must be a string"
            )
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ApiError(
                ERR_INVALID_REQUEST,
                "allocation_lines[].quantity_delivered must be an integer",
            )
        lines.append({
            "card_set_id": card_set_id,
            "player_id": player_id,
            "quantity_delivered": quantity,
        })
    return lines


def _windows_overlap(a, b):
    """Half-open day windows [scheduled_on, scheduled_on + 1 day)."""
    a_start = a["scheduled_on"]
    a_end = a_start + datetime.timedelta(days=1)
    b_start = b["scheduled_on"]
    b_end = b_start + datetime.timedelta(days=1)
    return a_start < b_end and b_start < a_end


def _produced_for_pair_excluding(store, session, card_set_id, player_id):
    """QuantityProduced(card_set_id, player_id): the number of that player's
    cards of that set whose stock has already physically moved, i.e. shipped
    from a session other than the one under check (PRD 3.4, priority 11)."""
    total = 0
    for other in store.all("signing_sessions"):
        if other["id"] == session["id"]:
            continue
        if other["status"] not in ("STOCK_SHIPPED", "COMPLETED"):
            continue
        for line in other["allocation_lines"]:
            if line["card_set_id"] == card_set_id and line["player_id"] == player_id:
                total += line["quantity_delivered"]
    return total


@app.route("/api/signing-sessions", methods=["POST"])
def create_signing_session():
    principal = authenticate(request.headers)
    require_role(principal, ["SigningCoordinator"])

    data = requtil.body()
    signer_name = requtil.required_str(data, "signer_name")
    signer_kind = requtil.required_enum(data, "signer_kind", SIGNER_KINDS)
    license_id = requtil.required_str(data, "license_id")
    scheduled_on = requtil.required_dt(data, "scheduled_on")
    allocation_lines = _parse_allocation_lines(data.get("allocation_lines"))

    store = db.STORE
    if not store.exists("licenses", license_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "license_id %s does not resolve" % license_id
        )

    now = store.now()
    rec = db.record("signing_sessions", {
        "signer_name": signer_name,
        "signer_kind": signer_kind,
        "license_id": license_id,
        "scheduled_on": scheduled_on,
        "ship_date": scheduled_on - datetime.timedelta(days=SIGNER_SHIP_LEAD_DAYS),
        "total_allocated_count": sum(
            line["quantity_delivered"] for line in allocation_lines
        ),
        "allocation_lines": allocation_lines,
        "autograph_royalty_cents": 0,
        "status": "SCHEDULED",
    }, now)
    store.insert("signing_sessions", rec)
    return jsonify(response.ok_object(_serialize(rec))), 201


@app.route("/api/signing-sessions", methods=["GET"])
def list_signing_sessions():
    principal = authenticate(request.headers)
    require_role(principal, ["SigningCoordinator", "ProductionPlanner", "PlatformAdmin"])

    store = db.STORE
    items = list(store.all("signing_sessions"))
    signer_name = requtil.filter_value("signer_name")
    license_id = requtil.filter_value("license_id")
    status = requtil.filter_value("status")
    if signer_name is not None:
        items = [r for r in items if r["signer_name"] == signer_name]
    if license_id is not None:
        items = [r for r in items if r["license_id"] == license_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(response.paginate([_serialize(r) for r in items], request.args)), 200


@app.route("/api/signing-sessions/<session_id>", methods=["GET"])
def get_signing_session(session_id):
    principal = authenticate(request.headers)
    require_role(
        principal, ["SigningCoordinator", "AuthenticationOfficer", "PlatformAdmin"]
    )
    return jsonify(response.ok_object(_serialize(_get(session_id)))), 200


@app.route("/api/signing-sessions/<session_id>/prepare-stock", methods=["POST"])
def prepare_stock(session_id):
    principal = authenticate(request.headers)
    require_role(principal, ["SigningCoordinator"])

    store = db.STORE
    now = store.now()
    rec = _get(session_id)
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Signing session is not SCHEDULED")

    lic = store.get("licenses", rec["license_id"])
    if lic is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "The licence does not resolve")

    # The license-in-force gate applies to association-bound signers only.
    if rec["signer_kind"] == "PLAYER_ASSOCIATION" and not license_in_force(lic, now):
        raise ApiError(
            ERR_LICENSE_NOT_IN_FORCE,
            "The license authorising this signing session is not in force",
        )

    # Signer-availability overlap rule, applied to signers of either kind.
    for other in store.all("signing_sessions"):
        if other["id"] == rec["id"]:
            continue
        if other["signer_name"] != rec["signer_name"]:
            continue
        if other["status"] not in ACTIVE_SESSION_STATUSES:
            continue
        if _windows_overlap(rec, other):
            raise ApiError(
                ERR_SIGNER_DOUBLE_BOOKED,
                "The signer already has an overlapping session",
            )

    # Every allocation line's card set must be APPROVED.
    for line in rec["allocation_lines"]:
        card_set = store.get("card_sets", line["card_set_id"])
        if card_set is None:
            raise ApiError(
                ERR_REFERENCE_NOT_FOUND,
                "allocation line card_set_id %s does not resolve" % line["card_set_id"],
            )
        if card_set["status"] != "APPROVED":
            raise ApiError(
                ERR_CARD_SET_NOT_APPROVED,
                "Allocation line card set %s is not APPROVED" % line["card_set_id"],
            )

    rec["status"] = "STOCK_PREPARED"
    db.bump(rec, now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/signing-sessions/<session_id>/ship-stock", methods=["POST"])
def ship_stock(session_id):
    principal = authenticate(request.headers)
    require_role(principal, ["SigningCoordinator"])

    store = db.STORE
    now = store.now()
    rec = _get(session_id)
    if rec["status"] != "STOCK_PREPARED":
        raise ApiError(ERR_INVALID_STATE, "Signing session is not STOCK_PREPARED")

    # The clock gate: the session cannot ship before its ship_date.
    if now < rec["ship_date"]:
        raise ApiError(
            ERR_SIGNER_SHIP_WINDOW_CLOSED,
            "Card stock cannot ship before the session's ship_date",
        )

    for line in rec["allocation_lines"]:
        card_set = store.get("card_sets", line["card_set_id"])
        if card_set is None:
            raise ApiError(
                ERR_REFERENCE_NOT_FOUND,
                "allocation line card_set_id %s does not resolve" % line["card_set_id"],
            )
        if card_set["status"] != "APPROVED":
            raise ApiError(
                ERR_CARD_SET_NOT_APPROVED,
                "Allocation line card set %s is not APPROVED" % line["card_set_id"],
            )

    # Physical-production check, then the autograph plan check (PRD 3.9).
    for line in rec["allocation_lines"]:
        produced = _produced_for_pair_excluding(
            store, rec, line["card_set_id"], line["player_id"]
        )
        if produced > line["quantity_delivered"]:
            raise ApiError(
                ERR_CARD_STOCK_NOT_PRODUCED_AT_SIGNING,
                "The allocated player's produced card count is below the delivered quantity",
            )

    for line in rec["allocation_lines"]:
        card_set = store.get("card_sets", line["card_set_id"])
        secured = _secured_count(store, card_set["id"], exclude_session_id=rec["id"])
        if secured + line["quantity_delivered"] > card_set["autograph_planned_count"]:
            raise ApiError(
                ERR_AUTOGRAPH_ALLOCATION_EXCEEDS_PLAN,
                "This allocation would exceed the set's planned autograph count",
            )

    rec["status"] = "STOCK_SHIPPED"
    rec["autograph_royalty_cents"] = calc.autograph_royalty_cents(
        rec["allocation_lines"], SIGNER_ROYALTY_CENTS
    )
    rec["total_allocated_count"] = sum(
        line["quantity_delivered"] for line in rec["allocation_lines"]
    )
    db.bump(rec, now)

    for line in rec["allocation_lines"]:
        card_set = store.get("card_sets", line["card_set_id"])
        if card_set is not None:
            _refresh_set_autographs(store, card_set, now)

    lic = store.get("licenses", rec["license_id"])
    if lic is not None:
        db.bump(lic, now)
        recompute_license_counts(store, lic["id"], now)

    return jsonify(response.ok_object(_serialize(rec))), 200


def _secured_count(store, card_set_id, exclude_session_id=None):
    total = 0
    for session in store.all("signing_sessions"):
        if session["id"] == exclude_session_id:
            continue
        if session["status"] in ("SCHEDULED", "CANCELLED"):
            continue
        for line in session["allocation_lines"]:
            if line["card_set_id"] == card_set_id:
                total += line["quantity_delivered"]
    return total


def _refresh_set_autographs(store, card_set, now):
    card_set["autograph_secured_count"] = _secured_count(store, card_set["id"])
    db.touch(card_set, now)


@app.route("/api/signing-sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    principal = authenticate(request.headers)
    require_role(principal, ["AuthenticationOfficer"])

    data = requtil.body()
    attendance = requtil.required(data, "signer_attendance")
    if not isinstance(attendance, str):
        raise ApiError(ERR_INVALID_REQUEST, "signer_attendance must be a string")

    store = db.STORE
    now = store.now()
    rec = _get(session_id)
    if rec["status"] != "STOCK_SHIPPED":
        raise ApiError(ERR_INVALID_STATE, "Signing session is not STOCK_SHIPPED")
    if attendance == "NO_SHOW":
        raise ApiError(
            ERR_AUTOGRAPH_AUTHENTICATION_FAILED,
            "The signer did not appear, so the session cannot be completed",
        )

    rec["status"] = "COMPLETED"
    db.bump(rec, now)

    # Every ISSUED redemption for this signer in this session's sets is
    # fulfilled.
    set_ids = {line["card_set_id"] for line in rec["allocation_lines"]}
    touched_sets = set()
    for redemption in store.all("redemptions"):
        if redemption["status"] != "ISSUED":
            continue
        if redemption["signer_name"] != rec["signer_name"]:
            continue
        if redemption["card_set_id"] not in set_ids:
            continue
        redemption["status"] = "FULFILLED"
        db.touch(redemption, now)
        touched_sets.add(redemption["card_set_id"])

    for set_id in touched_sets | set_ids:
        card_set = store.get("card_sets", set_id)
        if card_set is not None:
            card_set["autograph_redemptions_outstanding"] = sum(
                1
                for r in store.all("redemptions")
                if r["card_set_id"] == set_id and r["status"] in ("ISSUED", "FULFILLED")
            )
            db.touch(card_set, now)

    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/signing-sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    principal = authenticate(request.headers)
    require_role(principal, ["SigningCoordinator"])

    store = db.STORE
    now = store.now()
    rec = _get(session_id)
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Signing session is not SCHEDULED")

    rec["status"] = "CANCELLED"
    db.bump(rec, now)
    return jsonify(response.ok_object(_serialize(rec))), 200