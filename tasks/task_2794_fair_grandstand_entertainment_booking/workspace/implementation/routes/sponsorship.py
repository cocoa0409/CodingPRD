"""Sponsors, activations, premium pricing and exclusivity (PRD section 3.8)."""

import calc
import ledgers
import lookup
import schema
from authz import (
    ROLE_FAIR_OPS,
    ROLE_SETTLEMENT,
    ROLE_SPONSORSHIP,
    ROLE_TALENT_BUYER,
    roles,
)
from db import db, new_id, public, stamp_new, touch
from errors import ApiError
from flask import Blueprint
from response import collection, object_response
from routes.bookings import require_booking_status, require_booking_version

bp = Blueprint("sponsorship", __name__)

READ_ROLES = (ROLE_TALENT_BUYER, ROLE_FAIR_OPS, ROLE_SPONSORSHIP, ROLE_SETTLEMENT)
SPONSOR_READ_ROLES = (ROLE_FAIR_OPS, ROLE_SPONSORSHIP, ROLE_SETTLEMENT)
LIVE = ("CONFIRMED", "FULFILLED")


def require_activation_status(activation, allowed):
    if activation.get("status") not in allowed:
        raise ApiError("ERR_INVALID_ACTIVATION_STATE")


def check_category_exclusivity(booking, sponsor_id, category, exclude_id=None):
    for other in ledgers.activations_of_booking(booking["id"]):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other.get("status") not in LIVE:
            continue
        if other.get("sponsor_id") == sponsor_id:
            continue
        if other.get("exclusivity_category") == category:
            raise ApiError("ERR_SPONSOR_CATEGORY_EXCLUSIVITY_CONFLICT")


def check_stage_naming(booking, rights, statuses, exclude_id=None):
    if rights != "STAGE_NAMING":
        return
    stage_id = booking.get("stage_id")
    for other in db.activations.values():
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other.get("rights") != "STAGE_NAMING":
            continue
        if other.get("status") not in statuses:
            continue
        sibling = db.bookings.get(other.get("booking_id"))
        if sibling is None or sibling.get("stage_id") != stage_id:
            continue
        raise ApiError("ERR_STAGE_NAMING_ALREADY_GRANTED")


# ---------------------------------------------------------------------------
# sponsors
# ---------------------------------------------------------------------------

@bp.post("/sponsors")
@roles(ROLE_SPONSORSHIP)
def create_sponsor():
    payload = schema.body()
    name = schema.f_str(payload, "name")
    category = schema.f_enum(payload, "category", schema.TRADE_CATEGORIES)
    exclusivity_tier = schema.f_enum(payload, "exclusivity_tier", schema.EXCLUSIVITY_TIERS)
    record = {
        "id": new_id(),
        "name": name,
        "category": category,
        "exclusivity_tier": exclusivity_tier,
    }
    stamp_new(record)
    db.sponsors[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/sponsors/<identifier>")
@roles(*SPONSOR_READ_ROLES)
def read_sponsor(identifier):
    return object_response(public(lookup.get_sponsor(identifier)))


# ---------------------------------------------------------------------------
# activations
# ---------------------------------------------------------------------------

@bp.post("/sponsorship-activations")
@roles(ROLE_SPONSORSHIP)
def create_activation():
    payload = schema.body()
    expected_show_booking_version = schema.f_int(payload, "expected_show_booking_version")
    sponsor_id = schema.f_str(payload, "sponsor_id")
    booking_id = schema.f_str(payload, "booking_id")
    rights = schema.f_enum(payload, "rights", schema.RIGHTS)
    base_fee_cents = schema.f_cents(payload, "base_fee_cents")
    exclusivity_category = schema.f_enum(
        payload, "exclusivity_category", schema.TRADE_CATEGORIES
    )

    booking = lookup.get_booking(booking_id)
    sponsor = lookup.get_sponsor(sponsor_id)
    require_booking_status(booking, ("DATE_HELD", "ANNOUNCED"))
    require_booking_version(booking, expected_show_booking_version)
    check_category_exclusivity(booking, sponsor["id"], exclusivity_category)
    check_stage_naming(booking, rights, ("PROPOSED", "CONFIRMED", "FULFILLED"))

    record = {
        "id": new_id(),
        "sponsor_id": sponsor["id"],
        "booking_id": booking["id"],
        "rights": rights,
        "base_fee_cents": base_fee_cents,
        "exclusivity_category": exclusivity_category,
        "status": "PROPOSED",
        "net_fee_cents": calc.activation_net_fee_cents(base_fee_cents, rights, booking, sponsor),
        "make_good_credit_cents": 0,
    }
    stamp_new(record)
    db.activations[record["id"]] = record
    touch(booking)
    return object_response(public(record), 201)


@bp.get("/sponsorship-activations/<identifier>")
@roles(*READ_ROLES)
def read_activation(identifier):
    return object_response(public(lookup.get_activation(identifier)))


@bp.get("/sponsorship-activations")
@roles(*READ_ROLES)
def list_activations():
    limit, offset = schema.pagination()
    sponsor_id = schema.q_str("sponsor_id")
    booking_id = schema.q_str("booking_id")
    rights = schema.q_enum("rights", schema.RIGHTS)
    status = schema.q_enum("status", schema.ACTIVATION_STATUSES)
    if booking_id is not None:
        lookup.get_booking(booking_id)
    if sponsor_id is not None:
        lookup.get_sponsor(sponsor_id)
    rows = []
    for activation in db.activations.values():
        if sponsor_id is not None and activation.get("sponsor_id") != sponsor_id:
            continue
        if booking_id is not None and activation.get("booking_id") != booking_id:
            continue
        if rights is not None and activation.get("rights") != rights:
            continue
        if status is not None and activation.get("status") != status:
            continue
        rows.append(activation)
    return collection(rows, limit, offset)


@bp.post("/sponsorship-activations/<identifier>/confirm")
@roles(ROLE_SPONSORSHIP)
def confirm_activation(identifier):
    activation = lookup.get_activation(identifier)
    booking = db.bookings.get(activation.get("booking_id"))
    if booking is None:
        raise ApiError("ERR_SHOW_BOOKING_NOT_FOUND")
    require_booking_status(booking, ("DATE_HELD", "ANNOUNCED"))
    require_activation_status(activation, ("PROPOSED",))
    check_category_exclusivity(
        booking,
        activation.get("sponsor_id"),
        activation.get("exclusivity_category"),
        exclude_id=activation["id"],
    )
    check_stage_naming(booking, activation.get("rights"), LIVE, exclude_id=activation["id"])

    activation["status"] = "CONFIRMED"
    touch(activation)
    ledgers.recompute_booking_sponsorship_revenue(booking)
    return object_response(public(activation), 200)


@bp.post("/sponsorship-activations/<identifier>/cancel")
@roles(ROLE_SPONSORSHIP)
def cancel_activation(identifier):
    activation = lookup.get_activation(identifier)
    require_activation_status(activation, ("PROPOSED", "CONFIRMED"))
    was_confirmed = activation.get("status") == "CONFIRMED"

    activation["status"] = "CANCELLED"
    activation["make_good_credit_cents"] = (
        int(activation.get("net_fee_cents") or 0) if was_confirmed else 0
    )
    touch(activation)
    if was_confirmed:
        ledgers.recompute_booking_sponsorship_revenue(db.bookings.get(activation.get("booking_id")))
    return object_response(public(activation), 200)
