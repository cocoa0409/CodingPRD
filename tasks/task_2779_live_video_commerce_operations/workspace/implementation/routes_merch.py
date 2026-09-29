"""Lineup composition, replay merchandising and flash offers (PRD 3.2, 3.5, 3.9)."""

from flask import Blueprint, request

import calc
import serializers as ser
from envelope import respond, respond_list
from errors import ApiError
from guards import (
    ALL_ROLES, ROLE_MERCH, authenticate, body, fk_id, get_offer, get_product,
    get_show, get_slot, get_viewer, pagination, req_dt, req_int, req_str,
    slice_rows,
)
from store import by_created, db, new_record, now, touch

bp = Blueprint("merch", __name__)


# -------------------------------------------------------------- lineup slots
@bp.post("/lineup-slots")
def create_slot():
    authenticate([ROLE_MERCH])
    payload = body()
    show = get_show(fk_id(payload, "show_id"))
    product = get_product(fk_id(payload, "product_id"))
    slot_sequence = req_int(payload, "slot_sequence", 1)
    planned_start_at = req_dt(payload, "planned_start_at")
    planned_end_at = req_dt(payload, "planned_end_at")
    if not planned_end_at > planned_start_at:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "planned_end_at must be strictly after planned_start_at.")
    planned_qty = req_int(payload, "planned_qty", 1)
    for existing in calc.slots_of(show["id"]):
        if existing["slot_sequence"] == slot_sequence:
            raise ApiError("ERR_INVALID_REQUEST", "slot_sequence is already used on this show.")
    if (planned_start_at < show["scheduled_start_at"]
            or planned_end_at > show["scheduled_end_at"]):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "the segment must fall inside the show's planned airtime.")
    if show["status"] not in ("DRAFT", "READY"):
        raise ApiError("ERR_INVALID_SHOW_STATE")
    record = new_record()
    record.update({
        "show_id": show["id"],
        "product_id": product["id"],
        "slot_sequence": slot_sequence,
        "planned_start_at": planned_start_at,
        "planned_end_at": planned_end_at,
        "planned_qty": planned_qty,
        "unit_cost_snapshot_cents": product["unit_cost_cents"],
        "replay_marker_offset_sec": None,
        "replay_product_link_url": None,
        "replay_marker_status": "NONE",
        "replay_conversions_count": 0,
        "replay_attributed_revenue_cents": 0,
    })
    db.slots[record["id"]] = record
    touch(show)
    return respond(ser.slot_out(record), 201)


@bp.get("/lineup-slots/<slot_id>")
def read_slot(slot_id):
    authenticate(ALL_ROLES)
    return respond(ser.slot_out(get_slot(slot_id)))


@bp.get("/lineup-slots")
def list_slots():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.slots.values())
    for field in ("show_id", "product_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = slice_rows(by_created(rows), limit, offset)
    return respond_list([ser.slot_out(r) for r in page], limit, offset, total)


@bp.post("/lineup-slots/<slot_id>/replay-marker")
def set_replay_marker(slot_id):
    authenticate([ROLE_MERCH])
    slot = get_slot(slot_id)
    payload = body()
    marker_offset_sec = req_int(payload, "marker_offset_sec")
    product_link_url = req_str(payload, "product_link_url")
    show = db.shows.get(slot["show_id"])
    if show is None or show["status"] not in ("ENDED", "SETTLED"):
        raise ApiError("ERR_SHOW_NOT_ENDED")
    aired_seconds = 0
    if show["went_live_at"] is not None and show["ended_at"] is not None:
        aired_seconds = int((show["ended_at"] - show["went_live_at"]).total_seconds())
    if marker_offset_sec < 0 or marker_offset_sec > aired_seconds:
        raise ApiError("ERR_MARKER_OFFSET_OUT_OF_RANGE")
    slot["replay_marker_offset_sec"] = marker_offset_sec
    slot["replay_product_link_url"] = product_link_url
    slot["replay_marker_status"] = "DRAFT"
    touch(slot)
    return respond(ser.slot_out(slot))


@bp.post("/lineup-slots/<slot_id>/replay-marker/publish")
def publish_replay_marker(slot_id):
    authenticate([ROLE_MERCH])
    slot = get_slot(slot_id)
    show = db.shows.get(slot["show_id"])
    if show is None or show["status"] not in ("ENDED", "SETTLED"):
        raise ApiError("ERR_SHOW_NOT_ENDED")
    if slot["replay_marker_status"] != "DRAFT":
        raise ApiError("ERR_REPLAY_MARKER_NOT_PUBLISHED")
    slot["replay_marker_status"] = "PUBLISHED"
    touch(slot)
    return respond(ser.slot_out(slot))


@bp.post("/lineup-slots/<slot_id>/replay-conversions")
def record_replay_conversion(slot_id):
    authenticate([ROLE_MERCH])
    slot = get_slot(slot_id)
    payload = body()
    get_viewer(fk_id(payload, "viewer_id"))
    net_revenue_cents = req_int(payload, "net_revenue_cents")
    occurred_at = req_dt(payload, "occurred_at")
    show = db.shows.get(slot["show_id"])
    if show is not None and show["ended_at"] is not None and occurred_at < show["ended_at"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "occurred_at must be at or after the show's ended_at.")
    if show is None or show["status"] not in ("ENDED", "SETTLED"):
        raise ApiError("ERR_SHOW_NOT_ENDED")
    if slot["replay_marker_status"] != "PUBLISHED":
        raise ApiError("ERR_REPLAY_MARKER_NOT_PUBLISHED")
    weight = calc.decay_weight(show["ended_at"], occurred_at)
    slot["replay_attributed_revenue_cents"] += calc.rhu(calc.dec(net_revenue_cents) * weight)
    slot["replay_conversions_count"] += 1
    touch(slot)
    return respond(ser.slot_out(slot), 201)


# --------------------------------------------------------------- flash offers
@bp.post("/flash-offers")
def create_offer():
    authenticate([ROLE_MERCH])
    payload = body()
    slot = get_slot(fk_id(payload, "lineup_slot_id"))
    product = db.products.get(slot["product_id"])
    max_price = product["base_price_cents"] if product is not None else None
    offer_price_cents = req_int(payload, "offer_price_cents", 1, max_price)
    window_start_at = req_dt(payload, "window_start_at")
    window_end_at = req_dt(payload, "window_end_at")
    if not window_end_at > window_start_at:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "window_end_at must be strictly after window_start_at.")
    max_qty = req_int(payload, "max_qty", 1, 100000)
    expected_version = req_int(payload, "expected_lineup_slot_version")
    if expected_version != slot["version"]:
        raise ApiError("ERR_STALE_LINEUP_SLOT_VERSION")
    # Rung 15 — closed windows, zero buffer, per product across every show.
    for existing in by_created(list(db.offers.values())):
        if existing["status"] not in ("SCHEDULED", "ACTIVE", "EXHAUSTED"):
            continue
        other_slot = db.slots.get(existing["lineup_slot_id"])
        if other_slot is None or other_slot["product_id"] != slot["product_id"]:
            continue
        if (window_start_at <= existing["window_end_at"]
                and existing["window_start_at"] <= window_end_at):
            raise ApiError("ERR_OFFER_WINDOW_OVERLAP")
    record = new_record()
    record.update({
        "lineup_slot_id": slot["id"],
        "superseded_by_offer_id": None,
        "offer_price_cents": offer_price_cents,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "max_qty": max_qty,
        "status": "SCHEDULED",
        "activated_at": None,
    })
    db.offers[record["id"]] = record
    for existing in by_created(calc.offers_of_slot(slot["id"])):
        if existing["id"] == record["id"] or existing["status"] != "SCHEDULED":
            continue
        existing["status"] = "SUPERSEDED"
        existing["superseded_by_offer_id"] = record["id"]
        touch(existing)
    touch(slot)
    return respond(ser.offer_out(record), 201)


@bp.get("/flash-offers/<offer_id>")
def read_offer(offer_id):
    authenticate(ALL_ROLES)
    return respond(ser.offer_out(get_offer(offer_id)))


@bp.get("/flash-offers")
def list_offers():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.offers.values())
    for field in ("lineup_slot_id", "superseded_by_offer_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = slice_rows(by_created(rows), limit, offset)
    return respond_list([ser.offer_out(r) for r in page], limit, offset, total)


@bp.post("/flash-offers/<offer_id>/activate")
def activate_offer(offer_id):
    authenticate([ROLE_MERCH])
    offer = get_offer(offer_id)
    if offer["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_OFFER_STATE")
    show = calc.show_of_offer(offer)
    if show is None or show["status"] != "LIVE":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    slot = calc.slot_of_offer(offer)
    product = db.products.get(slot["product_id"]) if slot is not None else None
    if product is None or product["claim_substantiation_status"] != "SUBSTANTIATED":
        raise ApiError("ERR_CLAIM_NOT_SUBSTANTIATED")
    stamp = now()
    if stamp < offer["window_start_at"] or stamp > offer["window_end_at"]:
        raise ApiError("ERR_OFFER_WINDOW_CLOSED")
    offer["status"] = "ACTIVE"
    offer["activated_at"] = stamp
    touch(offer)
    return respond(ser.offer_out(offer))
