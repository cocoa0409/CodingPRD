"""Chat moderation, question routing and polls (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers as ser
from envelope import respond, respond_list
from errors import ApiError
from guards import (
    ALL_ROLES, ROLE_HOST, ROLE_MODERATOR, ROLE_VIEWER, authenticate, body,
    fk_id, get_interaction, get_show, opt_str, pagination, req_enum, req_int,
    req_str, slice_rows,
)
from store import by_created, db, new_record, now, touch

bp = Blueprint("interactions", __name__)

KINDS = ("CHAT", "QUESTION", "POLL")
VIEWER_KINDS = ("CHAT", "QUESTION")
PIPELINE_STATES = ("PENDING_MODERATION", "QUEUED", "ROUTED", "DEFERRED")


def _mute_gate(user_id):
    """PRD 3.8: an acting viewer must be ACTIVE, or have a lapsed mute — in which
    case the viewer is auto-unmuted on that first submission and the request
    proceeds."""
    viewer = db.viewers.get(user_id)
    if viewer is None or viewer["chat_status"] != "MUTED":
        return viewer
    muted_until = viewer["muted_until"]
    if muted_until is not None and muted_until <= now():
        viewer["chat_status"] = "ACTIVE"
        touch(viewer)
        return viewer
    raise ApiError("ERR_VIEWER_MUTED")


# -------------------------------------------------------------- submission
@bp.post("/interactions")
def create_interaction():
    user_id, role = authenticate([ROLE_VIEWER, ROLE_HOST])
    payload = body()
    # Rung 2 — a Viewer may only submit CHAT or QUESTION, a Host only a POLL.
    raw_kind = payload.get("kind")
    if isinstance(raw_kind, str) and raw_kind in KINDS:
        if role == ROLE_VIEWER and raw_kind not in VIEWER_KINDS:
            raise ApiError("ERR_ROLE_NOT_PERMITTED")
        if role == ROLE_HOST and raw_kind != "POLL":
            raise ApiError("ERR_ROLE_NOT_PERMITTED")
    show = get_show(fk_id(payload, "show_id"))
    kind = req_enum(payload, "kind", KINDS)
    text = req_str(payload, "body")
    options = payload.get("options")
    if kind == "POLL":
        if not isinstance(options, list) or not 2 <= len(options) <= 4:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "a poll requires an options array holding between two and four labels.")
        for label in options:
            if not isinstance(label, str) or label == "":
                raise ApiError("ERR_INVALID_REQUEST", "each poll option must be a label.")
    elif options is not None:
        raise ApiError("ERR_INVALID_REQUEST", "options is forbidden unless kind is POLL.")
    if show["status"] != "LIVE":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    if role == ROLE_VIEWER:
        _mute_gate(user_id)
    record = new_record()
    record.update({
        "show_id": show["id"],
        "viewer_id": None,
        "host_id": None,
        "kind": kind,
        "body": text,
        "state": "PENDING_MODERATION",
        "moderated_at": None,
        "blocked_reason": None,
        "routed_at": None,
        "defer_count": 0,
        "answered_at": None,
        "answer_body": None,
        "options": None,
        "tallies": None,
        "voted_viewer_ids": None,
        "vote_count": 0,
    })
    if kind == "POLL":
        record["host_id"] = user_id
        record["state"] = "OPEN"
        record["options"] = list(options)
        record["tallies"] = dict((str(index), 0) for index in range(len(options)))
        record["voted_viewer_ids"] = []
    else:
        record["viewer_id"] = user_id
    db.interactions[record["id"]] = record
    return respond(ser.interaction_out(record), 201)


@bp.get("/interactions/<interaction_id>")
def read_interaction(interaction_id):
    authenticate(ALL_ROLES)
    return respond(ser.interaction_out(get_interaction(interaction_id)))


@bp.get("/interactions")
def list_interactions():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.interactions.values())
    for field in ("show_id", "viewer_id", "host_id", "kind", "state"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = slice_rows(by_created(rows), limit, offset)
    return respond_list([ser.interaction_out(r) for r in page], limit, offset, total)


# -------------------------------------------------------------- moderation
@bp.post("/interactions/<interaction_id>/moderate")
def moderate_interaction(interaction_id):
    authenticate([ROLE_MODERATOR])
    item = get_interaction(interaction_id)
    payload = body()
    action = req_enum(payload, "action", ("APPROVE", "BLOCK"))
    blocked_reason = opt_str(payload, "blocked_reason")
    if item["state"] != "PENDING_MODERATION" or item["kind"] not in VIEWER_KINDS:
        raise ApiError("ERR_INVALID_INTERACTION_STATE")
    show = db.shows.get(item["show_id"])
    if show is None or show["status"] != "LIVE":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    stamp = now()
    if action == "APPROVE":
        item["state"] = "APPROVED" if item["kind"] == "CHAT" else "QUEUED"
        item["moderated_at"] = stamp
        touch(item)
        return respond(ser.interaction_out(item))
    # BLOCK — the deepest cascade in the interactive layer, five links long.
    item["state"] = "BLOCKED"
    item["blocked_reason"] = blocked_reason
    item["moderated_at"] = stamp
    touch(item)
    viewer = db.viewers.get(item["viewer_id"])
    if viewer is not None:
        viewer["strike_count"] += 1
        muted = viewer["strike_count"] >= calc.MUTE_STRIKE_THRESHOLD
        if muted:
            viewer["chat_status"] = "MUTED"
            viewer["muted_until"] = stamp + timedelta(minutes=calc.MUTE_DURATION_MIN)
        touch(viewer)
        if muted:
            for other in by_created(list(db.interactions.values())):
                if other["id"] == item["id"]:
                    continue
                if other["viewer_id"] != viewer["id"]:
                    continue
                if other["state"] not in PIPELINE_STATES:
                    continue
                other["state"] = "WITHDRAWN"
                touch(other)
    return respond(ser.interaction_out(item))


@bp.post("/interactions/<interaction_id>/route")
def route_interaction(interaction_id):
    authenticate([ROLE_MODERATOR])
    item = get_interaction(interaction_id)
    if item["state"] != "QUEUED" or item["kind"] != "QUESTION":
        raise ApiError("ERR_INVALID_INTERACTION_STATE")
    show = db.shows.get(item["show_id"])
    if show is None or show["status"] != "LIVE":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    item["state"] = "ROUTED"
    item["routed_at"] = now()
    touch(item)
    return respond(ser.interaction_out(item))


# ------------------------------------------------------------- host actions
@bp.post("/interactions/<interaction_id>/host-action")
def host_action(interaction_id):
    user_id, _ = authenticate([ROLE_HOST])
    item = get_interaction(interaction_id)
    # Rung 3 — a poll is closed by the host who opened it; a routed question is
    # fielded by the host of the show's PRIMARY CONFIRMED booking.
    if item["kind"] == "POLL":
        if item["host_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
    else:
        booking = calc.primary_booking(item["show_id"], ("CONFIRMED",))
        if booking is None or booking["host_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
    payload = body()
    action = req_enum(payload, "action", ("ANSWER", "DEFER", "CLOSE_POLL"))
    answer_body = opt_str(payload, "answer_body")
    if action == "CLOSE_POLL":
        if item["kind"] != "POLL" or item["state"] != "OPEN":
            raise ApiError("ERR_INVALID_INTERACTION_STATE")
    else:
        if item["kind"] != "QUESTION" or item["state"] != "ROUTED":
            raise ApiError("ERR_INVALID_INTERACTION_STATE")
    show = db.shows.get(item["show_id"])
    if show is None or show["status"] != "LIVE":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    if action == "DEFER" and item["defer_count"] >= calc.MAX_DEFERRALS:
        raise ApiError("ERR_DEFERRAL_LIMIT_REACHED")
    if action == "ANSWER":
        item["state"] = "ANSWERED"
        item["answer_body"] = answer_body
        item["answered_at"] = now()
        touch(item)
    elif action == "DEFER":
        item["state"] = "DEFERRED"
        item["defer_count"] += 1
        touch(item)
        # Unconditionally, in the same request, the question returns to the queue.
        item["state"] = "QUEUED"
        item["routed_at"] = None
        touch(item)
    else:
        item["state"] = "CLOSED"
        touch(item)
    return respond(ser.interaction_out(item))


# -------------------------------------------------------------------- votes
@bp.post("/interactions/<interaction_id>/votes")
def cast_vote(interaction_id):
    user_id, _ = authenticate([ROLE_VIEWER])
    item = get_interaction(interaction_id)
    payload = body()
    option_index = req_int(payload, "option_index")
    show = db.shows.get(item["show_id"])
    if show is None or show["status"] != "LIVE":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    _mute_gate(user_id)
    if item["kind"] != "POLL" or item["state"] != "OPEN":
        raise ApiError("ERR_POLL_NOT_OPEN")
    if user_id in item["voted_viewer_ids"]:
        raise ApiError("ERR_DUPLICATE_VOTE")
    if option_index < 0 or option_index >= len(item["options"]):
        raise ApiError("ERR_INVALID_REQUEST", "option_index is outside the poll's options.")
    key = str(option_index)
    item["tallies"][key] = item["tallies"].get(key, 0) + 1
    item["vote_count"] += 1
    item["voted_viewer_ids"].append(user_id)
    touch(item)
    return respond(ser.interaction_out(item))
