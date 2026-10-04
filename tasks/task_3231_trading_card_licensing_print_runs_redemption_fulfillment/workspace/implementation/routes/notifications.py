"""CollectorNotification resource: acknowledge, settle, resolve.

Settlement is the notice-level act that books the substitution credit and is
available directly from ISSUED.  Two conditions must hold, and both fail with
ERR_INVALID_STATE: the parent redemption is CANCELLED, and the asserted
compensation value equals the scratch value exactly (PRD 3.6).
"""

import calc
import db
import requtil
import response
from core import app
from common import serialize
from errors import (
    ApiError,
    ERR_COLLECTOR_NOTIFICATION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REDEMPTION_DEADLINE_EXCEEDED,
    ERR_REFERENCE_NOT_FOUND,
)
from flask import jsonify, request
from middleware import authenticate, require_role

READ_ROLES = ["RedemptionFulfilmentAnalyst", "QualityAnalyst", "PlatformAdmin"]


def _get(notification_id):
    rec = db.STORE.get("collector_notifications", notification_id)
    if rec is None:
        raise ApiError(
            ERR_COLLECTOR_NOTIFICATION_NOT_FOUND,
            "No CollectorNotification exists with id %s" % notification_id,
        )
    return rec


def _serialize(rec):
    return serialize("collector_notifications", rec)


def _refresh_redemption(store, redemption_id, now):
    redemption = store.get("redemptions", redemption_id)
    if redemption is None:
        return None
    redemption["collector_notification_count"] = sum(
        1
        for n in store.all("collector_notifications")
        if n["redemption_id"] == redemption_id
    )
    db.touch(redemption, now)
    return redemption


def _refresh_settled_complaints(store, card_set_id, now):
    card_set = store.get("card_sets", card_set_id)
    if card_set is None:
        return
    card_set["settled_complaint_count"] = sum(
        1
        for c in store.all("collector_complaints")
        if c["card_set_id"] == card_set_id and c["status"] == "APPROVED"
    )
    db.touch(card_set, now)


@app.route("/api/collector-notifications", methods=["GET"])
def list_notifications():
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    store = db.STORE
    items = list(store.all("collector_notifications"))
    redemption_id = requtil.filter_value("redemption_id")
    status = requtil.filter_value("status")
    if redemption_id is not None:
        items = [n for n in items if n["redemption_id"] == redemption_id]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(response.paginate([_serialize(n) for n in items], request.args)), 200


@app.route("/api/collector-notifications/<notification_id>", methods=["GET"])
def get_notification(notification_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    return jsonify(response.ok_object(_serialize(_get(notification_id)))), 200


@app.route("/api/collector-notifications/<notification_id>/acknowledge", methods=["POST"])
def acknowledge_notification(notification_id):
    principal = authenticate(request.headers)
    require_role(principal, ["RedemptionFulfilmentAnalyst"])

    store = db.STORE
    now = store.now()
    rec = _get(notification_id)
    if rec["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "Collector notification is not ISSUED")

    rec["status"] = "ACKNOWLEDGED"
    db.bump(rec, now)

    # Unusually for a notice-level action, the parent redemption's version is
    # advanced by one as well.
    redemption = store.get("redemptions", rec["redemption_id"])
    if redemption is not None:
        db.bump(redemption, now)
    _refresh_redemption(store, rec["redemption_id"], now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/collector-notifications/<notification_id>/settle", methods=["POST"])
def settle_notification(notification_id):
    principal = authenticate(request.headers)
    require_role(principal, ["RedemptionFulfilmentAnalyst"])

    store = db.STORE
    now = store.now()
    rec = _get(notification_id)
    if rec["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "Collector notification is not ISSUED")

    data = requtil.body()
    redemption_status = requtil.required(data, "redemption_status")
    if not isinstance(redemption_status, str):
        raise ApiError(ERR_INVALID_REQUEST, "redemption_status must be a string")
    equals_scratch = requtil.required_bool(data, "compensation_value_equals_scratch")

    redemption = store.get("redemptions", rec["redemption_id"])
    if redemption is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "The parent redemption does not resolve")

    # Both conditions fail with ERR_INVALID_STATE.
    if redemption["status"] != "CANCELLED" or redemption_status != "CANCELLED":
        raise ApiError(
            ERR_INVALID_STATE,
            "A substitution notice cannot settle against a redemption that is not CANCELLED",
        )
    if not equals_scratch:
        raise ApiError(
            ERR_INVALID_STATE,
            "The compensation value must equal the scratch value exactly",
        )

    # Settlement is evaluated against the same consumer-facing deadline that
    # governs redemption closure; the boundary is inclusive.
    deadline = redemption["opened_on"] + _days(redemption["deadline_days"])
    if now > deadline:
        raise ApiError(
            ERR_REDEMPTION_DEADLINE_EXCEEDED,
            "The consumer-facing deadline for this notice has passed",
        )

    rec["status"] = "SETTLED"
    rec["compensation_value_cents"] = calc.redemption_compensation_cents(
        redemption.get("_scratch_before_cancel", 0)
    )
    db.bump(rec, now)

    _refresh_redemption(store, rec["redemption_id"], now)
    _refresh_settled_complaints(store, redemption["card_set_id"], now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/collector-notifications/<notification_id>/resolve", methods=["POST"])
def resolve_notification(notification_id):
    principal = authenticate(request.headers)
    require_role(principal, ["RedemptionFulfilmentAnalyst"])

    store = db.STORE
    now = store.now()
    rec = _get(notification_id)
    if rec["status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_INVALID_STATE, "Collector notification is not ACKNOWLEDGED")

    rec["status"] = "RESOLVED"
    db.bump(rec, now)
    _refresh_redemption(store, rec["redemption_id"], now)
    return jsonify(response.ok_object(_serialize(rec))), 200


def _days(count):
    import datetime

    return datetime.timedelta(days=count)