"""Disposition orders (PRD 3.9)."""

from flask import Blueprint

from db import db, new_row, touch
from errors import ApiError
from middleware import (ROLE_CONTROLLER, ROLE_MERCHANDISE_DIRECTOR,
                        ROLE_PRICING_ANALYST, body, endpoint)
from response import created, ok
from serializers import disposition_json
from services import calc, lookup
from services.lifecycle import (is_disposition_eligible, maybe_complete_plan,
                                plans_of_item, refresh_item)

bp = Blueprint("disposition", __name__)

CHANNELS = ("SALVAGE", "JOBBER", "DONATION")


def _check_channel_coherence(channel, payload_has_recovery, unit_recovery_cents,
                             payload_has_fmv, fmv_cents):
    if channel in ("SALVAGE", "JOBBER"):
        if not payload_has_recovery or unit_recovery_cents < 1:
            raise ApiError("ERR_DISPOSITION_CHANNEL_MISMATCH",
                           "%s requires unit_recovery_cents of at least one "
                           "cent." % channel)
        if payload_has_fmv:
            raise ApiError("ERR_DISPOSITION_CHANNEL_MISMATCH",
                           "%s must not carry fmv_cents." % channel)
    else:
        if not payload_has_fmv or fmv_cents < 1:
            raise ApiError("ERR_DISPOSITION_CHANNEL_MISMATCH",
                           "DONATION requires fmv_cents of at least one cent.")
        if payload_has_recovery and unit_recovery_cents != 0:
            raise ApiError("ERR_DISPOSITION_CHANNEL_MISMATCH",
                           "DONATION must not carry a non-zero "
                           "unit_recovery_cents.")


@endpoint(bp, "/disposition-orders", ["POST"], (ROLE_PRICING_ANALYST,))
def create_disposition(user_id, role):
    from validation import opt_int, req_enum, req_int, req_str
    payload = body()
    season_id = req_str(payload, "season_id")
    item_id = req_str(payload, "item_id")
    channel = req_enum(payload, "channel", CHANNELS)
    units = req_int(payload, "units", minimum=1)
    unit_recovery_cents = opt_int(payload, "unit_recovery_cents", minimum=0)
    fmv_cents = opt_int(payload, "fmv_cents", minimum=0)

    season = lookup.season(season_id)
    item = lookup.item(item_id)
    lookup.gate_active(season)

    if not is_disposition_eligible(item):
        raise ApiError("ERR_ITEM_NOT_EXIT_ELIGIBLE",
                       "The item's lifecycle_stage is not exit eligible.")

    available = item["on_hand_units"] - item["units_committed_disposition"]
    if units > available:
        raise ApiError("ERR_INSUFFICIENT_AVAILABLE_UNITS",
                       "units exceeds the item's uncommitted on-hand pool.")

    _check_channel_coherence(channel, unit_recovery_cents is not None,
                             unit_recovery_cents, fmv_cents is not None,
                             fmv_cents)

    order = new_row(
        season_id=season["id"],
        item_id=item["id"],
        channel=channel,
        units=units,
        unit_recovery_cents=unit_recovery_cents,
        fmv_cents=fmv_cents,
        projected_recovery_cents=calc.disposition_recovery_cents(
            channel, units, unit_recovery_cents, fmv_cents,
            item["unit_cost_cents"]),
        settled_units=0,
        settled_recovery_cents=0,
        created_by_user_id=user_id,
        approved_by_user_id=None,
        status="DRAFT",
    )
    db.insert("dispositions", order)
    refresh_item(item, force=True)
    return created(disposition_json(order))


@endpoint(bp, "/disposition-orders/<disposition_order_id>/approve", ["POST"],
          (ROLE_CONTROLLER,))
def approve_disposition(user_id, role, disposition_order_id):
    order = lookup.disposition(disposition_order_id)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DRAFT disposition order may be approved.")
    season = lookup.season(order["season_id"])
    lookup.gate_exit_window(season)
    if user_id == order["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver may not be the order's author.")

    order["status"] = "APPROVED"
    order["approved_by_user_id"] = user_id
    touch(order)
    refresh_item(lookup.item(order["item_id"]), force=True)
    return ok(disposition_json(order))


@endpoint(bp, "/disposition-orders/<disposition_order_id>/settle", ["POST"],
          (ROLE_CONTROLLER,))
def settle_disposition(user_id, role, disposition_order_id):
    from validation import req_int
    payload = body()
    settled_units = req_int(payload, "settled_units", minimum=1)
    order = lookup.disposition(disposition_order_id)
    if order["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an APPROVED disposition order may be settled.")
    season = lookup.season(order["season_id"])
    lookup.gate_exit_window(season)
    if settled_units > order["units"]:
        raise ApiError("ERR_INSUFFICIENT_AVAILABLE_UNITS",
                       "settled_units exceeds the order's units.")

    item = lookup.item(order["item_id"])
    order["settled_units"] = settled_units
    order["settled_recovery_cents"] = calc.disposition_recovery_cents(
        order["channel"], settled_units, order["unit_recovery_cents"],
        order["fmv_cents"], item["unit_cost_cents"])
    order["status"] = "SETTLED"
    touch(order)

    refresh_item(item, force=True)
    for plan in plans_of_item(item):
        maybe_complete_plan(plan)
    return ok(disposition_json(order))


@endpoint(bp, "/disposition-orders/<disposition_order_id>/cancel", ["POST"],
          (ROLE_PRICING_ANALYST, ROLE_MERCHANDISE_DIRECTOR))
def cancel_disposition(user_id, role, disposition_order_id):
    from validation import opt_str
    payload = body()
    opt_str(payload, "cancel_reason", max_len=1024)
    order = lookup.disposition(disposition_order_id)
    if order["status"] not in ("DRAFT", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DRAFT or APPROVED order may be cancelled.")
    lookup.gate_not_closed(lookup.season(order["season_id"]))

    order["status"] = "CANCELLED"
    touch(order)
    refresh_item(lookup.item(order["item_id"]), force=True)
    return ok(disposition_json(order))
