"""Redemption resource: issue, fulfil, close, cancel, and serve notifications."""

import datetime

from flask import jsonify, request

import calc
import db
import requtil
import response
from core import app
from common import (
    license_of_card_set,
    recompute_license_counts,
    serialize,
)
from constants import REDEMPTION_STATUSES
from errors import (
    ApiError,
    ERR_CARD_SET_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_REDEMPTION_CODE_DUPLICATE,
    ERR_REDEMPTION_DEADLINE_EXCEEDED,
    ERR_REDEMPTION_DEADLINE_NOT_EXCEEDED,
    ERR_REDEMPTION_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_RIGHTS_VERSION_MISMATCH,
)
from middleware import authenticate, require_role

READ_ROLES = ["RedemptionFulfilmentAnalyst", "QualityAnalyst", "PlatformAdmin"]


def get_redemption(redemption_id):
    rec = db.STORE.get("redemptions", redemption_id)
    if rec is None:
        raise ApiError(
            ERR_REDEMPTION_NOT_FOUND, "No Redemption exists with id %s" % redemption_id
        )
    return rec


def _serialize(rec):
    return serialize("redemptions", rec)


def _deadline(rec):
    return rec["opened_on"] + datetime.timedelta(days=rec["deadline_days"])


def _refresh_outstanding(store, card_set_id, now):
    if card_set_id is None:
        return
    card_set = store.get("card_sets", card_set_id)
    if card_set is None:
        return
    card_set["autograph_redemptions_outstanding"] = sum(
        1
        for r in store.all("redemptions")
        if r["card_set_id"] == card_set_id and r["status"] in ("ISSUED", "FULFILLED")
    )
    db.touch(card_set, now)


def _require_rights_pin(card_set):
    store = db.STORE
    lic = license_of_card_set(store, card_set)
    if lic is None or card_set["rights_pinned_version"] != lic["rights_version"]:
        raise ApiError(
            ERR_RIGHTS_VERSION_MISMATCH,
            "CardSet.rights_pinned_version does not equal License.rights_version",
        )
    return lic


@app.route("/api/card-sets/<card_set_id>/redemptions", methods=["POST"])
def issue_redemption(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["RedemptionFulfilmentAnalyst"])

    data = requtil.body()
    redemption_code = requtil.required_str(data, "redemption_code")
    signer_name = requtil.required_str(data, "signer_name")
    estimated_value_cents = requtil.required_int(data, "estimated_value_cents")
    opened_on = requtil.required_dt(data, "opened_on")

    store = db.STORE
    if not store.exists("card_sets", card_set_id):
        raise ApiError(
            ERR_CARD_SET_NOT_FOUND, "No CardSet exists with id %s" % card_set_id
        )

    # redemption_code is globally unique.
    for existing in store.all("redemptions"):
        if existing["redemption_code"] == redemption_code:
            raise ApiError(
                ERR_REDEMPTION_CODE_DUPLICATE,
                "redemption_code %s is already in use" % redemption_code,
            )

    now = store.now()
    rec = db.record("redemptions", {
        "card_set_id": card_set_id,
        "redemption_code": redemption_code,
        "signer_name": signer_name,
        "estimated_value_cents": estimated_value_cents,
        "opened_on": opened_on,
        "deadline_days": calc.redemption_deadline_days(estimated_value_cents),
        "status": "ISSUED",
        "collector_notification_count": 0,
    }, now)
    store.insert("redemptions", rec)
    _refresh_outstanding(store, card_set_id, now)
    return jsonify(response.ok_object(_serialize(rec))), 201


@app.route("/api/card-sets/<card_set_id>/redemptions", methods=["GET"])
def list_set_redemptions(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    if not db.STORE.exists("card_sets", card_set_id):
        raise ApiError(
            ERR_CARD_SET_NOT_FOUND, "No CardSet exists with id %s" % card_set_id
        )
    return _list_redemptions({"card_set_id": card_set_id})


@app.route("/api/redemptions", methods=["GET"])
def list_redemptions():
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    return _list_redemptions({})


def _list_redemptions(fixed):
    store = db.STORE
    items = list(store.all("redemptions"))
    card_set_id = fixed.get("card_set_id") or requtil.filter_value("card_set_id")
    signer_name = requtil.filter_value("signer_name")
    status = requtil.filter_value("status")
    if card_set_id is not None:
        items = [r for r in items if r["card_set_id"] == card_set_id]
    if signer_name is not None:
        items = [r for r in items if r["signer_name"] == signer_name]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(response.paginate([_serialize(r) for r in items], request.args)), 200


@app.route("/api/redemptions/<redemption_id>", methods=["GET"])
def get_redemption_route(redemption_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    return jsonify(response.ok_object(_serialize(get_redemption(redemption_id)))), 200


@app.route("/api/redemptions/<redemption_id>/fulfill", methods=["POST"])
def fulfill_redemption(redemption_id):
    principal = authenticate(request.headers)
    require_role(principal, ["RedemptionFulfilmentAnalyst"])

    store = db.STORE
    now = store.now()
    rec = get_redemption(redemption_id)

    card_set = store.get("card_sets", rec["card_set_id"])
    if card_set is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "The referenced card set does not resolve")
    lic = _require_rights_pin(card_set)

    if rec["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "Redemption is not ISSUED")

    rec["status"] = "FULFILLED"
    db.bump(rec, now)

    if lic is not None:
        db.bump(lic, now)
        recompute_license_counts(store, lic["id"], now)

    _refresh_outstanding(store, rec["card_set_id"], now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/redemptions/<redemption_id>/close", methods=["POST"])
def close_redemption(redemption_id):
    principal = authenticate(request.headers)
    require_role(principal, ["RedemptionFulfilmentAnalyst"])

    store = db.STORE
    now = store.now()
    rec = get_redemption(redemption_id)
    if rec["status"] != "FULFILLED":
        raise ApiError(ERR_INVALID_STATE, "Redemption is not FULFILLED")

    # The boundary is inclusive: closing exactly on the deadline is allowed.
    if now > _deadline(rec):
        raise ApiError(
            ERR_REDEMPTION_DEADLINE_EXCEEDED, "The redemption deadline has passed"
        )

    rec["status"] = "CLOSED"
    db.bump(rec, now)
    _refresh_outstanding(store, rec["card_set_id"], now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/redemptions/<redemption_id>/cancel", methods=["POST"])
def cancel_redemption(redemption_id):
    principal = authenticate(request.headers)
    require_role(principal, ["RedemptionFulfilmentAnalyst"])

    store = db.STORE
    now = store.now()
    rec = get_redemption(redemption_id)
    if rec["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "Redemption is not ISSUED")
    if not now > _deadline(rec):
        raise ApiError(
            ERR_REDEMPTION_DEADLINE_NOT_EXCEEDED,
            "A redemption still inside its window must be fulfilled, not abandoned",
        )

    # The scratch value the redemption held before cancellation is what drives
    # the substitution arithmetic, so the compensation is computed and left on
    # an internal ledger key before the public field is zeroed.
    rec["_scratch_before_cancel"] = rec["estimated_value_cents"]
    rec["_compensation_value_cents"] = calc.redemption_compensation_cents(
        rec["estimated_value_cents"]
    )
    rec["estimated_value_cents"] = 0
    rec["status"] = "CANCELLED"
    db.bump(rec, now)
    _refresh_outstanding(store, rec["card_set_id"], now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/redemptions/<redemption_id>/notifications", methods=["POST"])
def serve_notification(redemption_id):
    principal = authenticate(request.headers)
    require_role(principal, ["RedemptionFulfilmentAnalyst"])

    data = requtil.body()
    notice_code = requtil.required_str(data, "notice_code")
    opened_on = requtil.required_dt(data, "opened_on")

    store = db.STORE
    now = store.now()
    redemption = get_redemption(redemption_id)

    card_set = store.get("card_sets", redemption["card_set_id"])
    card_set_name = card_set["set_name"] if card_set else redemption["card_set_id"]
    deadline = _deadline(redemption)
    notice_text = _render_notice(
        notice_code, card_set_name, redemption["estimated_value_cents"], deadline
    )

    rec = db.record("collector_notifications", {
        "redemption_id": redemption_id,
        "notice_code": notice_code,
        "notice_text": notice_text,
        "opened_on": opened_on,
        "status": "ISSUED",
    }, now)
    store.insert("collector_notifications", rec)

    redemption["collector_notification_count"] = sum(
        1
        for n in store.all("collector_notifications")
        if n["redemption_id"] == redemption_id
    )
    db.touch(redemption, now)
    return jsonify(response.ok_object(serialize("collector_notifications", rec))), 201


def _render_notice(notice_code, set_name, scratch_cents, deadline):
    """Server-rendered notice text, including the computed deadline date so the
    collector sees an absolute date rather than a relative window."""
    label = {
        "SUBST-90": "Substitution offer",
        "MISS-120": "Missed card notification",
    }.get(notice_code, "Collector notice")
    return (
        "%s (%s) for %s: the promised autograph with a scratch value of %d cents "
        "must be resolved on or before %s UTC."
        % (label, notice_code, set_name, scratch_cents, deadline.strftime("%Y-%m-%dT%H:%M:%S"))
    )


@app.route("/api/redemptions/<redemption_id>/notifications", methods=["GET"])
def list_redemption_notifications(redemption_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    get_redemption(redemption_id)
    return _list_notifications({"redemption_id": redemption_id})


@app.route("/api/collector-notifications", methods=["GET"])
def list_collector_notifications():
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    return _list_notifications({})


def _list_notifications(fixed):
    store = db.STORE
    items = list(store.all("collector_notifications"))
    redemption_id = fixed.get("redemption_id") or requtil.filter_value("redemption_id")
    status = requtil.filter_value("status")
    if redemption_id is not None:
        items = [n for n in items if n["redemption_id"] == redemption_id]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(
        response.paginate(
            [serialize("collector_notifications", n) for n in items], request.args
        )
    ), 200