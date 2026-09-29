"""Show calendar, the readiness gate, air, end-of-broadcast, settlement,
analytics, and simulcast production (PRD 3.1, 3.3, 3.4, 3.9)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers as ser
from envelope import respond, respond_list
from errors import ApiError
from guards import (
    ALL_ROLES, ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_MERCH, ROLE_SHOW_PRODUCER,
    authenticate, body, fk_id, get_channel, get_show, opt_str, pagination,
    req_bool, req_dt, req_enum, req_fraction, req_int, req_str, slice_rows,
)
from store import by_created, db, new_record, now, touch

bp = Blueprint("shows", __name__)


# --------------------------------------------------------------------- shows
@bp.post("/shows")
def create_show():
    user_id, _ = authenticate([ROLE_SHOW_PRODUCER])
    payload = body()
    title = req_str(payload, "title")
    start = req_dt(payload, "scheduled_start_at")
    end = req_dt(payload, "scheduled_end_at")
    if not end > start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "scheduled_end_at must be strictly after scheduled_start_at.")
    record = new_record()
    record.update({
        "title": title,
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "readiness_checked_at": None,
        "went_live_at": None,
        "ended_at": None,
        "settled_at": None,
        "compliance_signoff_by_user_id": None,
        "simulcast_readiness_index": 0,
        "margin_provisional_cents": 0,
        "margin_final_cents": 0,
    })
    db.shows[record["id"]] = record
    return respond(ser.show_out(record), 201)


@bp.get("/shows/<show_id>")
def read_show(show_id):
    authenticate(ALL_ROLES)
    return respond(ser.show_out(get_show(show_id)))


@bp.post("/shows/<show_id>/ready")
def run_readiness_gate(show_id):
    authenticate([ROLE_SHOW_PRODUCER])
    show = get_show(show_id)
    if show["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    slots = calc.slots_of(show_id)
    # Rung 10 — every product reachable through the lineup must be SUBSTANTIATED.
    for slot in by_created(slots):
        product = db.products.get(slot["product_id"])
        if product is None or product["claim_substantiation_status"] != "SUBSTANTIATED":
            raise ApiError("ERR_CLAIM_NOT_SUBSTANTIATED")
    # Rung 11 — no disclosure record of this show may still be PENDING.
    for record in calc.disclosures_of(show_id):
        if record["status"] == "PENDING":
            raise ApiError("ERR_DISCLOSURE_NOT_ACKNOWLEDGED")
    # Rung 12 — the confirmed primary host must be CERTIFIED at gate time.
    booking = calc.primary_booking(show_id, ("CONFIRMED",))
    if booking is not None:
        host = db.hosts.get(booking["host_id"])
        if host is None or calc.certification_status(host) != "CERTIFIED":
            raise ApiError("ERR_HOST_CERTIFICATION_EXPIRED")
    # Rung 21 — exactly one PRIMARY booking of this show must be CONFIRMED.
    if booking is None:
        raise ApiError("ERR_PRIMARY_HOST_MISSING")
    # Rung 22 — the show must have at least one lineup slot.
    if not slots:
        raise ApiError("ERR_LINEUP_EMPTY")
    # Rung 23 — at least one destination must be PROVISIONED (presence, not quality).
    if not [c for c in calc.channels_of(show_id) if c["status"] == "PROVISIONED"]:
        raise ApiError("ERR_SIMULCAST_NOT_READY")
    calc.recompute_show_index(show)
    show["status"] = "READY"
    show["readiness_checked_at"] = now()
    touch(show)
    return respond(ser.show_out(show))


@bp.post("/shows/<show_id>/go-live")
def go_live(show_id):
    authenticate([ROLE_SHOW_PRODUCER])
    show = get_show(show_id)
    if show["status"] != "READY":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    stamp = now()
    opens_at = show["scheduled_start_at"] - timedelta(minutes=calc.GO_LIVE_EARLY_MAX_MIN)
    if stamp < opens_at or not stamp < show["scheduled_end_at"]:
        raise ApiError("ERR_GO_LIVE_WINDOW_CLOSED")
    if calc.primary_booking(show_id, ("CONFIRMED",)) is None:
        raise ApiError("ERR_PRIMARY_HOST_MISSING")
    if calc.recompute_show_index(show) < calc.GO_LIVE_MIN_INDEX:
        raise ApiError("ERR_SIMULCAST_NOT_READY")
    show["status"] = "LIVE"
    show["went_live_at"] = stamp
    touch(show)
    for channel in by_created(calc.channels_of(show_id)):
        if channel["status"] == "PROVISIONED":
            channel["status"] = "LIVE"
            touch(channel)
    return respond(ser.show_out(show))


@bp.post("/shows/<show_id>/end")
def end_broadcast(show_id):
    authenticate([ROLE_SHOW_PRODUCER])
    show = get_show(show_id)
    if show["status"] != "LIVE":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    calc.end_show(show)
    return respond(ser.show_out(show))


@bp.post("/shows/<show_id>/compliance-signoff")
def compliance_signoff(show_id):
    user_id, _ = authenticate([ROLE_COMPLIANCE])
    show = get_show(show_id)
    payload = body()
    opt_str(payload, "attestation_note")
    if show["status"] != "ENDED":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    for order in calc.orders_of(show_id):
        if order["payment_state"] == "AUTHORIZED":
            raise ApiError("ERR_INVALID_ORDER_STATE")
    # PRD 2.12 — the signing officer must not have substantiated any product
    # reachable through this show's lineup slots.
    for slot in calc.slots_of(show_id):
        product = db.products.get(slot["product_id"])
        if product is not None and product["substantiated_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    stamp = now()
    show["status"] = "SETTLED"
    show["settled_at"] = stamp
    show["compliance_signoff_by_user_id"] = user_id
    show["margin_final_cents"] = calc.margin_analysis(show, "FINAL")["margin_cents"]
    touch(show)
    for cart in by_created(calc.carts_of(show_id)):
        if cart["status"] != "ABANDONED":
            continue
        deadline = cart["recovery_deadline_at"]
        if deadline is not None and deadline <= stamp:
            cart["status"] = "EXPIRED"
            touch(cart)
    return respond(ser.show_out(show))


@bp.get("/shows/<show_id>/analytics")
def show_analytics(show_id):
    authenticate([ROLE_SHOW_PRODUCER, ROLE_MERCH, ROLE_ADMIN])
    show = get_show(show_id)
    variant = request.args.get("variant")
    if variant is None:
        variant = "PROVISIONAL"
    if variant not in ("PROVISIONAL", "FINAL"):
        raise ApiError("ERR_INVALID_REQUEST", "variant is not a permitted value.")
    result = calc.margin_analysis(show, variant)
    if variant == "PROVISIONAL":
        show["margin_provisional_cents"] = result["margin_cents"]
        touch(show)
    data = {"show_id": show["id"], "variant": variant}
    data.update(result)
    data.update({
        "gross_merchandise_cents": calc.gross_merchandise_cents(show_id),
        "abandoned_cart_count": calc.abandoned_cart_count(show_id),
        "abandonment_rate_bp": calc.abandonment_rate_bp(show_id),
        "replay_attributed_revenue_cents": calc.replay_attributed_revenue_cents(show_id),
    })
    return respond(data)


# --------------------------------------------------------- simulcast channels
@bp.post("/stream-channels")
def create_channel():
    authenticate([ROLE_SHOW_PRODUCER])
    payload = body()
    show = get_show(fk_id(payload, "show_id"))
    platform = req_enum(payload, "platform", calc.PLATFORMS)
    target_latency_ms = req_int(payload, "target_latency_ms", 500, 8000)
    is_primary = req_bool(payload, "is_primary", False)
    for existing in calc.channels_of(show["id"]):
        if existing["platform"] == platform:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "the show already carries a destination on this platform.")
    if show["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    record = new_record()
    record.update({
        "show_id": show["id"],
        "platform": platform,
        "is_primary": is_primary,
        "target_latency_ms": target_latency_ms,
        "status": "DRAFT",
        "latency_ms": None,
        "dropped_frame_pct": 0.0,
        "readiness_index": 0,
        "health_report_count": 0,
    })
    db.channels[record["id"]] = record
    return respond(ser.channel_out(record), 201)


@bp.get("/stream-channels/<channel_id>")
def read_channel(channel_id):
    authenticate(ALL_ROLES)
    return respond(ser.channel_out(get_channel(channel_id)))


@bp.get("/stream-channels")
def list_channels():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.channels.values())
    for field in ("show_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = slice_rows(by_created(rows), limit, offset)
    return respond_list([ser.channel_out(r) for r in page], limit, offset, total)


@bp.post("/stream-channels/<channel_id>/provision")
def provision_channel(channel_id):
    authenticate([ROLE_SHOW_PRODUCER])
    channel = get_channel(channel_id)
    if channel["status"] not in ("DRAFT", "FAILED"):
        raise ApiError("ERR_INVALID_CHANNEL_STATE")
    show = db.shows.get(channel["show_id"])
    if show is None or show["status"] not in ("DRAFT", "READY"):
        raise ApiError("ERR_INVALID_SHOW_STATE")
    recovering = channel["status"] == "FAILED"
    channel["status"] = "PROVISIONED"
    touch(channel)
    if recovering:
        # PRD 3.3 — only the recovery branch recomputes the show-level figure.
        calc.recompute_show_index(show)
    return respond(ser.channel_out(channel))


@bp.post("/stream-channels/<channel_id>/health-reports")
def report_channel_health(channel_id):
    authenticate([ROLE_SHOW_PRODUCER, ROLE_ADMIN])
    channel = get_channel(channel_id)
    payload = body()
    latency_ms = req_int(payload, "latency_ms")
    dropped_frame_pct = req_fraction(payload, "dropped_frame_pct", 0.0, 1.0)
    if channel["status"] in ("DRAFT", "ENDED"):
        raise ApiError("ERR_INVALID_CHANNEL_STATE")
    channel["latency_ms"] = latency_ms
    channel["dropped_frame_pct"] = dropped_frame_pct
    channel["health_report_count"] += 1
    touch(channel)
    show = db.shows.get(channel["show_id"])
    if show is not None:
        reported = calc.recompute_channel_indices(show["id"])
        for candidate in by_created(reported):
            if candidate["readiness_index"] < calc.CHANNEL_FAIL_INDEX:
                candidate["status"] = "FAILED"
                touch(candidate)
        calc.recompute_show_index(show)
        remaining = [
            c for c in calc.channels_of(show["id"])
            if c["status"] in ("PROVISIONED", "LIVE")
        ]
        if show["status"] == "READY" and not remaining:
            calc.revert_show_to_draft(show)
    return respond(ser.channel_out(channel))
