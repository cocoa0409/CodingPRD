"""Blue-sky state registrations (PRD 3.4)."""
import re

from flask import Blueprint

import db
import dates
import response
import serializers
import validation
from constants import REGISTRATION_SELECTABLE
from errors import ApiError, invalid
from middleware import ROLE_CO, ROLE_DEALER, ROLE_FA, ROLE_TAO, authenticate
from money import ZERO, q2
from routes import helpers

bp = Blueprint("bluesky", __name__)

STATE_RE = re.compile(r"^[A-Z]{2}$")


@bp.route("/blue-sky-registrations", methods=["POST"])
def create_registration():
    authenticate((ROLE_CO,))
    body = validation.body()
    share_class_id = validation.get_id(body, "share_class_id", required=True)
    state_code = validation.get_string(body, "state_code", required=True)
    if not STATE_RE.match(state_code):
        raise invalid("Field 'state_code' must be exactly two uppercase letters.")
    registered_amount = validation.get_decimal(body, "registered_amount", 2,
                                               required=True, positive=True)
    effective_date = validation.get_date(body, "effective_date", required=True)
    expiration_date = validation.get_date(body, "expiration_date", required=True)
    if expiration_date <= effective_date:
        raise invalid("expiration_date must be strictly later than effective_date.")

    share_class = helpers.get_share_class(share_class_id)

    new_from = dates.fmt_date(effective_date)
    new_to = dates.fmt_date(expiration_date)
    for existing in db.store.registrations.values():
        if existing["share_class_id"] != share_class["id"]:
            continue
        if existing["state_code"] != state_code:
            continue
        if existing["status"] not in REGISTRATION_SELECTABLE:
            continue
        if new_from < existing["expiration_date"] and existing["effective_date"] < new_to:
            raise ApiError("ERR_BLUE_SKY_WINDOW_OVERLAP",
                           "The registration window overlaps an existing filing.")

    registration = db.create(db.store.registrations, {
        "share_class_id": share_class["id"],
        "state_code": state_code,
        "registered_amount": registered_amount,
        "effective_date": new_from,
        "expiration_date": new_to,
        "reserved_amount": q2(ZERO),
        "consumed_amount": q2(ZERO),
        "status": "ACTIVE",
    })
    return response.created(serializers.registration(registration))


@bp.route("/blue-sky-registrations/<registration_id>", methods=["GET"])
def read_registration(registration_id):
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO, ROLE_DEALER))
    registration = helpers.get_registration(registration_id)
    return response.ok(serializers.registration(registration))
