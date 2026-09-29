"""The show calendar and the weather contingency cascade (PRD sections 3.6, 3.9)."""

import calc
import ledgers
import lookup
import schema
import scheduling
import spine
from authz import (
    ROLE_BOX_OFFICE,
    ROLE_FAIR_OPS,
    ROLE_PRODUCTION,
    ROLE_SETTLEMENT,
    ROLE_SPONSORSHIP,
    ROLE_TALENT_AGENT,
    ROLE_TALENT_BUYER,
    resolve_actor,
    roles,
)
from db import db, new_id, now_str, parse_ts, public, stamp_new, touch
from errors import ApiError
from flask import Blueprint
from response import collection, object_response

bp = Blueprint("bookings", __name__)

ALL = (
    ROLE_TALENT_BUYER,
    ROLE_TALENT_AGENT,
    ROLE_FAIR_OPS,
    ROLE_PRODUCTION,
    ROLE_BOX_OFFICE,
    ROLE_SPONSORSHIP,
    ROLE_SETTLEMENT,
)
LIST_ROLES = (ROLE_TALENT_BUYER, ROLE_FAIR_OPS, ROLE_BOX_OFFICE, ROLE_SETTLEMENT)


def require_booking_status(booking, allowed):
    if booking.get("booking_status") not in allowed:
        raise ApiError("ERR_INVALID_BOOKING_STATE")


def require_ticketing_status(booking, allowed):
    if booking.get("ticketing_status") not in allowed:
        raise ApiError("ERR_INVALID_TICKETING_STATE")


def require_booking_version(booking, expected):
    if expected != int(booking.get("version", 0)):
        raise ApiError("ERR_STALE_SHOW_BOOKING_VERSION")


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.get("/show-bookings/<identifier>")
@roles(*ALL)
def read_booking(identifier):
    resolve_actor()
    return object_response(public(lookup.get_booking(identifier)))


@bp.get("/show-bookings")
@roles(*ALL)
def list_bookings():
    limit, offset = schema.pagination()
    stage_id = schema.q_str("stage_id")
    offer_id = schema.q_str("offer_id")
    postponed_from_booking_id = schema.q_str("postponed_from_booking_id")
    booking_status = schema.q_enum("booking_status", schema.BOOKING_STATUSES)
    ticketing_status = schema.q_enum("ticketing_status", schema.TICKETING_STATUSES)
    resolve_actor()
    if stage_id is not None:
        lookup.get_stage(stage_id)
    if offer_id is not None:
        lookup.get_offer(offer_id)
    rows = []
    for booking in db.bookings.values():
        if stage_id is not None and booking.get("stage_id") != stage_id:
            continue
        if offer_id is not None and booking.get("offer_id") != offer_id:
            continue
        if postponed_from_booking_id is not None:
            if booking.get("postponed_from_booking_id") != postponed_from_booking_id:
                continue
        if booking_status is not None and booking.get("booking_status") != booking_status:
            continue
        if ticketing_status is not None and booking.get("ticketing_status") != ticketing_status:
            continue
        rows.append(booking)
    return collection(rows, limit, offset)


# ---------------------------------------------------------------------------
# reschedule
# ---------------------------------------------------------------------------

@bp.post("/show-bookings/<identifier>/reschedule")
@roles(ROLE_FAIR_OPS)
def reschedule_booking(identifier):
    payload = schema.body()
    new_show_date = schema.f_date(payload, "new_show_date")
    new_load_in_start_utc = schema.f_ts(payload, "new_load_in_start_utc")
    new_load_out_end_utc = schema.f_ts(payload, "new_load_out_end_utc")

    booking = lookup.get_booking(identifier)
    require_booking_status(booking, ("DATE_HELD",))

    edition = ledgers.edition_of_booking(booking)
    stage = ledgers.stage_of_booking(booking)
    if not scheduling.date_inside_run(edition, new_show_date):
        raise ApiError("ERR_SHOW_DATE_OUTSIDE_FAIR_RUN")
    if not scheduling.window_is_well_formed(
        new_show_date, new_load_in_start_utc, new_load_out_end_utc
    ):
        raise ApiError("ERR_INVALID_SLOT_WINDOW")
    scheduling.check_curfew(edition, new_show_date, new_load_out_end_utc)
    scheduling.check_scheduling_for_booking(
        booking, edition, stage, new_show_date, new_load_in_start_utc, new_load_out_end_utc
    )

    booking["show_date"] = new_show_date
    booking["load_in_start_utc"] = new_load_in_start_utc
    booking["load_out_end_utc"] = new_load_out_end_utc
    touch(booking)
    ledgers.recompute_stage_ledger(stage)
    return object_response(public(booking), 200)


# ---------------------------------------------------------------------------
# announce
# ---------------------------------------------------------------------------

@bp.post("/show-bookings/<identifier>/announce")
@roles(ROLE_FAIR_OPS)
def announce_booking(identifier):
    payload = schema.body()
    doors_time_utc = schema.f_ts(payload, "doors_time_utc")

    booking = lookup.get_booking(identifier)
    require_booking_status(booking, ("DATE_HELD",))

    doors = parse_ts(doors_time_utc)
    load_in = parse_ts(booking.get("load_in_start_utc"))
    load_out = parse_ts(booking.get("load_out_end_utc"))
    if not (doors > load_in and doors < load_out):
        raise ApiError("ERR_INVALID_SLOT_WINDOW")

    advance = ledgers.advance_of_booking(booking["id"])
    if advance is None or advance.get("status") != "ADVANCE_COMPLETE":
        raise ApiError("ERR_ADVANCE_NOT_COMPLETE")
    if not ledgers.scales_of_booking(booking["id"]):
        raise ApiError("ERR_NO_TICKET_SCALES")

    booking["booking_status"] = "ANNOUNCED"
    booking["doors_time_utc"] = doors_time_utc
    booking["announced_at_utc"] = now_str()
    if booking.get("ticketing_status") == "SCALED":
        booking["ticketing_status"] = "ON_SALE"
    touch(booking)
    return object_response(public(booking), 200)


# ---------------------------------------------------------------------------
# mark performed
# ---------------------------------------------------------------------------

@bp.post("/show-bookings/<identifier>/mark-performed")
@roles(ROLE_FAIR_OPS)
def mark_performed(identifier):
    booking = lookup.get_booking(identifier)
    require_booking_status(booking, ("ANNOUNCED",))
    require_ticketing_status(booking, ("ON_SALE",))
    if now_str() < booking.get("load_out_end_utc"):
        raise ApiError("ERR_SHOW_NOT_YET_CONCLUDED")

    booking["booking_status"] = "PERFORMED"
    booking["ticketing_status"] = "SALES_CLOSED"
    touch(booking)
    spine.close_scales(booking)
    spine.fulfil_activations(booking)
    return object_response(public(booking), 200)


# ---------------------------------------------------------------------------
# contingency actions
# ---------------------------------------------------------------------------

@bp.post("/show-bookings/<identifier>/contingency-actions")
@roles(ROLE_FAIR_OPS)
def create_contingency_action(identifier):
    payload = schema.body()
    expected_show_booking_version = schema.f_int(payload, "expected_show_booking_version")
    action_type = schema.f_enum(payload, "action_type", schema.ACTION_TYPES)
    reason_code = schema.f_enum(payload, "reason_code", schema.REASON_CODES)
    refund_policy = schema.f_enum(payload, "refund_policy", schema.REFUND_POLICIES)
    replacement_show_date = schema.f_date(payload, "replacement_show_date", default=None)

    booking = lookup.get_booking(identifier)
    require_booking_status(booking, ("DATE_HELD", "ANNOUNCED"))
    require_booking_version(booking, expected_show_booking_version)

    edition = ledgers.edition_of_booking(booking)
    stage = ledgers.stage_of_booking(booking)

    if action_type == "POSTPONE":
        if replacement_show_date is None:
            raise ApiError("ERR_REPLACEMENT_DATE_INVALID")
        if not (replacement_show_date > booking["show_date"]):
            raise ApiError("ERR_REPLACEMENT_DATE_INVALID")
        if not scheduling.date_inside_run(edition, replacement_show_date):
            raise ApiError("ERR_REPLACEMENT_DATE_INVALID")
    else:
        if replacement_show_date is not None:
            raise ApiError("ERR_REPLACEMENT_DATE_INVALID")

    if action_type == "POSTPONE" and booking.get("booking_status") == "ANNOUNCED":
        shift = (spine.day_delta(replacement_show_date, booking["show_date"]) or 0)
        new_load_in = spine._shift_instant(booking.get("load_in_start_utc"), shift)
        new_load_out = spine._shift_instant(booking.get("load_out_end_utc"), shift)
        scheduling.check_scheduling_for_booking(
            booking,
            edition,
            stage,
            replacement_show_date,
            new_load_in,
            new_load_out,
            include_radius=False,
        )

    decided_at_utc = now_str()
    doors = booking.get("doors_time_utc")
    pre_doors = doors is None or decided_at_utc < doors
    scales = ledgers.scales_of_booking(booking["id"])
    liability = calc.refund_liability_cents(
        scales, edition, action_type, refund_policy, pre_doors, decided_at_utc
    )

    committed = int(edition.get("refund_liability_committed_cents", 0))
    if committed + liability > int(edition.get("refund_reserve_cents", 0)):
        raise ApiError("ERR_REFUND_RESERVE_EXCEEDED")

    action = {
        "id": new_id(),
        "booking_id": booking["id"],
        "action_type": action_type,
        "reason_code": reason_code,
        "refund_policy": refund_policy,
        "replacement_show_date": replacement_show_date,
        "decided_at_utc": decided_at_utc,
        "pre_doors": pre_doors,
        "refund_liability_cents": liability,
    }
    stamp_new(action, common=False)
    db.contingency_actions[action["id"]] = action

    if action_type == "CANCEL":
        booking["booking_status"] = "CANCELLED"
        booking["ticketing_status"] = "REFUNDING"
        spine.mark_scales_refund_due(booking)
        spine.cancel_activations(booking)
        spine.void_advance(booking)
        if liability == 0:
            booking["ticketing_status"] = "REFUNDED"
        touch(booking)
        ledgers.recompute_stage_ledger(stage)
    else:
        booking["booking_status"] = "POSTPONED"
        if refund_policy == "RAIN_CHECK":
            booking["ticketing_status"] = "SALES_CLOSED"
        else:
            booking["ticketing_status"] = "REFUNDING"
            if liability == 0:
                booking["ticketing_status"] = "REFUNDED"
        # A POSTPONE shares the whole voiding cascade on the original records:
        # every proposed or confirmed activation becomes a make-good credit and
        # the show's sponsorship pool recomputes to 0.
        spine.cancel_activations(booking)
        spine.void_advance(booking)
        touch(booking)
        spine.create_replacement_booking(booking, replacement_show_date)
        ledgers.recompute_stage_ledger(stage)

    ledgers.recompute_booking_refund_liability(booking)
    ledgers.recompute_edition_refund_committed(edition)
    return object_response(public(action), 201)


@bp.get("/show-bookings/<identifier>/contingency-actions")
@roles(*LIST_ROLES)
def list_contingency_actions(identifier):
    limit, offset = schema.pagination()
    action_type = schema.q_enum("action_type", schema.ACTION_TYPES)
    booking = lookup.get_booking(identifier)
    rows = [
        a for a in ledgers.actions_of_booking(booking["id"])
        if action_type is None or a.get("action_type") == action_type
    ]
    return collection(rows, limit, offset, field="decided_at_utc")
