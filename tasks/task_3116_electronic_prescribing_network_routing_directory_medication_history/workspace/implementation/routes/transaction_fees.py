"""TransactionFeeEntry routes and the network metadata read."""

from flask import Blueprint, request

import clock
import db
import serializers
from clock import ok
from errors import ApiError, ERR_INVALID_REQUEST
from request_context import (
    actor,
    allowed,
    body,
    created_order,
    enum_value,
    int_value,
    need_fee_entry,
    need_participant,
    page_args,
    paginate,
)
from services import billing
from services import directory as directory_service

bp = Blueprint("transaction_fees", __name__)

DIRECTIONS = ("SENT", "RECEIVED")
FEE_STATUSES = ("PARTIAL", "POSTED", "REVERSED")


@bp.post("/network/transaction-fees")
def post_fee_entry():
    role, _ = actor()
    allowed(role, ["NetworkOperator"])
    payload = body(
        required=("participant_id", "month_key", "transaction_type", "direction"),
        optional=("transaction_count",),
    )
    participant = need_participant(payload["participant_id"])
    month_key = payload["month_key"]
    if not isinstance(month_key, str) or len(month_key) != 7 or month_key[4] != "-":
        raise ApiError(ERR_INVALID_REQUEST, "'month_key' must be a YYYY-MM string.")
    transaction_type = enum_value(payload["transaction_type"], "transaction_type",
                                  billing.TRANSACTION_TYPES)
    direction = enum_value(payload["direction"], "direction", DIRECTIONS)
    count = None
    if payload.get("transaction_count") is not None:
        count = int_value(payload["transaction_count"], "transaction_count", minimum=0)

    entry = billing.post_entry(participant["id"], month_key, transaction_type, direction,
                               transaction_count=count)
    return ok(serializers.fee_entry(entry), status=201)


@bp.get("/network/transaction-fees")
def list_fee_entries():
    role, _ = actor()
    allowed(role, ["NetworkOperator", "ParticipantAdmin"])
    limit, offset = page_args()
    rows = db.all_rows("fee_entries")
    for field in ("participant_id", "month_key", "transaction_type", "direction", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.fee_entry(e) for e in window], **meta)


@bp.get("/network/transaction-fees/<fid>")
def get_fee_entry(fid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "ParticipantAdmin"])
    entry = need_fee_entry(fid)
    return ok(serializers.fee_entry(entry))


@bp.get("/network/transaction-fees/<fid>/reversal")
def get_reversal(fid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "ParticipantAdmin"])
    entry = need_fee_entry(fid)
    compensating = db.get("fee_entries", entry.get("reversal_entry_id"))
    return ok([serializers.fee_entry(compensating)] if compensating else [])


@bp.post("/network/transaction-fees/<fid>/reverse")
def reverse_fee_entry(fid):
    role, _ = actor()
    allowed(role, ["NetworkOperator"])
    payload = body(required=("expected_participant_version",), optional=())
    entry = need_fee_entry(fid)
    expected = payload["expected_participant_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "'expected_participant_version' must be an integer.")
    entry, compensating = billing.reverse_entry(entry, expected)
    return ok(billing.reversal_payload(entry, compensating))


# --------------------------------------------------------------------------
# Network metadata
# --------------------------------------------------------------------------

@bp.get("/network/")
def network_metadata():
    role, _ = actor()
    allowed(role, [
        "NetworkOperator", "ParticipantAdmin", "Prescriber",
        "Pharmacy", "HubOperator", "PatientService",
    ])
    participants = db.all_rows("participants")
    certified = sum(1 for p in participants if p["certification_status"] == "CERTIFIED")
    live_attempts = sum(1 for a in db.all_rows("routing_attempts") if a["outcome"] == "IN_PROGRESS")

    reachable = 0
    for participant in participants:
        count, _total, _label = directory_service.reachability(participant["id"])
        reachable += count
    if not participants:
        label = "UNREACHABLE"
    else:
        full = sum(
            1 for p in participants
            if directory_service.reachability(p["id"])[2] == "FULL"
        )
        at_risk = sum(
            1 for p in participants
            if directory_service.reachability(p["id"])[2] == "AT_RISK"
        )
        if full:
            label = "FULL"
        elif at_risk:
            label = "AT_RISK"
        else:
            label = "UNREACHABLE"

    return ok({
        "network_participant_count": len(participants),
        "certified_participant_count": certified,
        "live_routing_attempt_count": live_attempts,
        "delivery_reachability": label,
    })