"""Verification-round reads, tallying, voiding; cure-period reads and expiry."""

from flask import Blueprint

import response
import validation as v
from db import (db, get_cure_period, get_round, now, serialize, touch)
from errors import ApiError
from middleware import require_auth
from routes.petitions import serialize_cure_period
from services import calculations as calc
from services import verification

READ_ROLES = ("SosAdmin", "ElectionsExaminer", "Proponent", "CountyClerk",
              "Challenger")

bp = Blueprint("rounds", __name__)


# ---------------------------------------------------------------------------
# verification rounds
# ---------------------------------------------------------------------------
@bp.route("/verification-rounds/<round_id>", methods=["GET"])
def read_round(round_id):
    require_auth(READ_ROLES)
    return response.single(serialize(get_round(round_id)))


@bp.route("/verification-rounds", methods=["GET"])
def list_rounds():
    require_auth(READ_ROLES)
    return response.listing(list(db.rounds.values()), {
        "petition_id": ("str", "petition_id"),
        "cure_period_id": ("str", "cure_period_id"),
        "round_type": ("str", "round_type"),
        "status": ("str", "status"),
        "determination": ("str", "determination"),
    })


@bp.route("/verification-rounds/<round_id>/tally", methods=["POST"])
def tally_round(round_id):
    user_id, role = require_auth(["ElectionsExaminer"])
    v.body()
    rnd = get_round(round_id)
    if rnd["status"] != "OPEN":
        raise ApiError("ERR_INVALID_ROUND_STATE")
    for record in calc.selected_records(rnd):
        if record["validation_status"] == "PENDING":
            raise ApiError("ERR_ROUND_HAS_PENDING_SIGNATURES")
    verification.tally_round(rnd, user_id)
    return response.single(serialize(rnd))


@bp.route("/verification-rounds/<round_id>/void", methods=["POST"])
def void_round(round_id):
    require_auth(["SosAdmin"])
    body = v.body()
    reason = v.as_string(v.required(body, "voided_reason"), "voided_reason")
    rnd = get_round(round_id)
    if rnd["status"] not in ("OPEN", "CLOSED"):
        raise ApiError("ERR_INVALID_ROUND_STATE")
    petition = db.petitions[rnd["petition_id"]]
    if rnd["status"] == "CLOSED" and petition["status"] in ("CERTIFIED", "FAILED"):
        raise ApiError("ERR_INVALID_PETITION_STATE")
    verification.void_round(rnd, reason)
    return response.single(serialize(rnd))


# ---------------------------------------------------------------------------
# cure periods
# ---------------------------------------------------------------------------
@bp.route("/cure-periods/<cure_period_id>", methods=["GET"])
def read_cure_period(cure_period_id):
    require_auth(READ_ROLES)
    return response.single(serialize_cure_period(get_cure_period(cure_period_id)))


@bp.route("/cure-periods", methods=["GET"])
def list_cure_periods():
    require_auth(READ_ROLES)
    return response.listing(list(db.cure_periods.values()), {
        "petition_id": ("str", "petition_id"),
        "status": ("str", "status"),
    }, serializer=serialize_cure_period)


@bp.route("/cure-periods/<cure_period_id>/expire", methods=["POST"])
def expire_cure_period(cure_period_id):
    require_auth(["SosAdmin"])
    v.body()
    cure_period = get_cure_period(cure_period_id)
    if cure_period["status"] != "OPEN":
        raise ApiError("ERR_CURE_PERIOD_NOT_OPEN")
    if now() < cure_period["_deadline_at_dt"]:
        raise ApiError("ERR_CURE_PERIOD_NOT_EXPIRED")
    cure_period["status"] = "EXPIRED"
    touch(cure_period)
    petition = db.petitions.get(cure_period["petition_id"])
    if petition is not None and petition["status"] not in ("CERTIFIED", "FAILED"):
        petition["status"] = "PENDING_FAILURE"
        touch(petition)
    return response.single(serialize_cure_period(cure_period))
