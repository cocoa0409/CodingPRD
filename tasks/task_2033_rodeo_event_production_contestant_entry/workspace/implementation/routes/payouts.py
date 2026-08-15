"""Payout endpoints: compute, list, get, finalize (PRD 3.7)."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    compute_purse_and_places,
    get_or_404,
    payout_of_event,
    rodeo_of_event,
    ser,
    sorted_created,
    stamp,
    touch,
)
from util import as_enum, body, pagination_args, required

bp = Blueprint("payouts", __name__, url_prefix="/api")

_VARIANTS = {"PROVISIONAL", "FINAL"}


@bp.post("/payouts/compute")
def compute_payout():
    auth(["CommitteeAdmin"])
    data = body()
    rodeo_event_id = data.get("rodeo_event_id")
    if rodeo_event_id is not None:
        get_or_404("rodeo_events", rodeo_event_id)
    if not isinstance(rodeo_event_id, str):
        raise ApiError(
            "ERR_VALIDATION", 400, "Missing required field: rodeo_event_id"
        )
    variant = as_enum(required(data, "variant"), "variant", _VARIANTS)
    event = DB["rodeo_events"][rodeo_event_id]
    payout = payout_of_event(rodeo_event_id)
    if payout is not None and payout["status"] == "DISBURSED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "A disbursed payout cannot be recomputed"
        )
    numbers = compute_purse_and_places(event, variant)
    if payout is None:
        payout = {
            "id": new_id(),
            "rodeo_event_id": rodeo_event_id,
            "computed_variant": variant,
            "purse_cents": numbers["purse_cents"],
            "go_round_pools": numbers["go_round_pools"],
            "average_pool_cents": numbers["average_pool_cents"],
            "place_lines": numbers["place_lines"],
            "status": "PROVISIONAL",
        }
        stamp(payout)
        DB["payouts"][payout["id"]] = payout
    else:
        payout["computed_variant"] = variant
        payout["purse_cents"] = numbers["purse_cents"]
        payout["go_round_pools"] = numbers["go_round_pools"]
        payout["average_pool_cents"] = numbers["average_pool_cents"]
        payout["place_lines"] = numbers["place_lines"]
        # Every payout before finalization is in PROVISIONAL status.
        payout["status"] = "PROVISIONAL"
        touch(payout)
    return ok(ser(payout))


@bp.get("/payouts")
def list_payouts():
    auth(ALL_ROLES)
    rodeo_event_id = request.args.get("rodeo_event_id")
    status = request.args.get("status")
    items = DB["payouts"].values()
    if rodeo_event_id is not None:
        items = [p for p in items if p["rodeo_event_id"] == rodeo_event_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(p) for p in items[offset : offset + limit]], len(items), limit, offset
    )


@bp.get("/payouts/<payout_id>")
def get_payout(payout_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("payouts", payout_id)))


@bp.post("/payouts/<payout_id>/transition")
def transition_payout(payout_id):
    auth(["CommitteeAdmin"])
    payout = get_or_404("payouts", payout_id)
    data = body()
    action = data.get("action")
    if action != "FINALIZE":
        raise ApiError("ERR_VALIDATION", 400, "Field action must be FINALIZE")
    if payout["status"] != "PROVISIONAL":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"FINALIZE is not valid from status {payout['status']}",
        )
    event = DB["rodeo_events"][payout["rodeo_event_id"]]
    rodeo = rodeo_of_event(event)
    if rodeo["posture"] != "COMPLETED":
        raise ApiError(
            "ERR_RODEO_NOT_OPEN",
            409,
            "Finalization requires the rodeo to be COMPLETED",
        )
    # Finalization recomputes under the FINAL variant (VERIFIED results only).
    numbers = compute_purse_and_places(event, "FINAL")
    payout["computed_variant"] = "FINAL"
    payout["purse_cents"] = numbers["purse_cents"]
    payout["go_round_pools"] = numbers["go_round_pools"]
    payout["average_pool_cents"] = numbers["average_pool_cents"]
    payout["place_lines"] = numbers["place_lines"]
    payout["status"] = "FINAL"
    touch(payout)
    return ok(ser(payout))
