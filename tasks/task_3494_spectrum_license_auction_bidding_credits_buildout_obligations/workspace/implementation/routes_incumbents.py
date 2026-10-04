"""Incumbents: registration and the relocation/clearing machine (PRD §3.1,
§3.7)."""
from flask import Blueprint, request

import store
import calcs
import serializers
from errors import ApiError, success
from helpers import (auth, require_role, body, req_present, as_str, as_int,
                     as_enum, as_datetime, get_or_404, paginate, touch)

bp = Blueprint("incumbents", __name__)

OPERATOR_ACTIONS = ("SUBMIT_PLAN", "DISPUTE", "RESUBMIT_PLAN",
                    "CONFIRM_CLEARED")
ALL_ACTIONS = OPERATOR_ACTIONS + ("BEGIN_RELOCATION",)


@bp.route("/spectrum-auctions/incumbents", methods=["POST"])
def register_incumbent():
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    b = body()
    plan_id = as_str(req_present(b, "band_plan_id"), "band_plan_id")
    area_id = as_str(req_present(b, "area_id"), "area_id")
    callsign = as_str(req_present(b, "callsign"), "callsign")
    cost = as_int(req_present(b, "relocation_cost_cents"),
                  "relocation_cost_cents", minimum=0)
    get_or_404("band_plans", plan_id)
    get_or_404("areas", area_id)
    inc = store.stamp_new({
        "id": store.new_id(),
        "band_plan_id": plan_id,
        "area_id": area_id,
        "callsign": callsign,
        "relocation_cost_cents": cost,
        "transition_window_start": None,
        "transition_window_end": None,
        "shares_proportional": None,
        "shares_equal": None,
        "status": "NOTIFIED",
    })
    store.DB["incumbents"][inc["id"]] = inc
    return success(serializers.incumbent(inc), 201)


@bp.route("/spectrum-auctions/incumbents", methods=["GET"])
def list_incumbents():
    auth()
    items = list(store.DB["incumbents"].values())
    for param in ("band_plan_id", "area_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [i for i in items if i[param] == value]
    page, meta = paginate(items)
    return success([serializers.incumbent(i) for i in page], 200, meta)


@bp.route("/spectrum-auctions/incumbents/<iid>", methods=["GET"])
def get_incumbent(iid):
    auth()
    return success(serializers.incumbent(get_or_404("incumbents", iid)), 200)


@bp.route("/spectrum-auctions/incumbents/<iid>/transition", methods=["POST"])
def transition_incumbent(iid):
    uid, role = auth()
    require_role(role, ("IncumbentOperator", "AuctionAdmin"))
    b = body()
    action = as_enum(req_present(b, "action"), "action", ALL_ACTIONS)
    # Per-action authorization (PRD §2.1): IncumbentOperator may not
    # BEGIN_RELOCATION; AuctionAdmin may not run the operator actions.
    if action == "BEGIN_RELOCATION" and role != "AuctionAdmin":
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "BEGIN_RELOCATION requires AuctionAdmin")
    if action in OPERATOR_ACTIONS and role != "IncumbentOperator":
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Action %s requires IncumbentOperator" % action)
    win_start = win_end = None
    if action == "BEGIN_RELOCATION":
        win_start = as_datetime(req_present(b, "transition_window_start"),
                                "transition_window_start")
        win_end = as_datetime(req_present(b, "transition_window_end"),
                              "transition_window_end")
        if not win_end > win_start:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "transition_window_end must be strictly after "
                           "transition_window_start")
    inc = get_or_404("incumbents", iid)
    if action in OPERATOR_ACTIONS and uid != inc["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "X-User-ID must equal the incumbent id")

    def bad_state():
        raise ApiError("ERR_INCUMBENT_INVALID_STATE", 409,
                       "Incumbent transition %s is not available from %s"
                       % (action, inc["status"]))

    if action == "SUBMIT_PLAN":
        if inc["status"] != "NOTIFIED":
            bad_state()
        inc["status"] = "PLAN_SUBMITTED"
        touch(inc)
    elif action == "DISPUTE":
        if inc["status"] != "PLAN_SUBMITTED":
            bad_state()
        inc["status"] = "DISPUTED"
        touch(inc)
    elif action == "RESUBMIT_PLAN":
        if inc["status"] != "DISPUTED":
            bad_state()
        inc["status"] = "PLAN_SUBMITTED"
        touch(inc)
    elif action == "BEGIN_RELOCATION":
        if inc["status"] != "PLAN_SUBMITTED":
            bad_state()
        # Buffer rule: closed intervals with a symmetric
        # INCUMBENT_TRANSITION_BUFFER_DAYS gap against every OTHER
        # RELOCATING window in the same area.
        for other in store.DB["incumbents"].values():
            if (other["id"] != inc["id"]
                    and other["area_id"] == inc["area_id"]
                    and other["status"] == "RELOCATING"):
                gap_after = win_start >= store.add_days(
                    other["transition_window_end"],
                    calcs.INCUMBENT_TRANSITION_BUFFER_DAYS)
                gap_before = win_end <= store.add_days(
                    other["transition_window_start"],
                    -calcs.INCUMBENT_TRANSITION_BUFFER_DAYS)
                if not (gap_after or gap_before):
                    raise ApiError("ERR_TRANSITION_WINDOW_CONFLICT", 409,
                                   "The relocation window violates the "
                                   "buffer-day gap rule")
        inc["transition_window_start"] = win_start
        inc["transition_window_end"] = win_end
        inc["status"] = "RELOCATING"
        touch(inc)
    else:  # CONFIRM_CLEARED
        if inc["status"] != "RELOCATING":
            bad_state()
        if store.now() < inc["transition_window_end"]:
            raise ApiError("ERR_INCUMBENT_INVALID_STATE", 409,
                           "Clearing may be confirmed only at or after "
                           "transition_window_end")
        active = []
        for lic in store.DB["licenses"].values():
            if lic["area_id"] == inc["area_id"] and lic["status"] == "ACTIVE":
                auction = store.DB["auctions"][lic["auction_id"]]
                block = calcs.find_block_by_category(
                    auction["band_plan_id"], lic["category"])
                area = store.DB["areas"][lic["area_id"]]
                lic["_units"] = calcs.bidding_units(block, area)
                active.append(lic)
        prop, equal = calcs.relocation_shares(
            active, inc["relocation_cost_cents"])
        inc["shares_proportional"] = prop
        inc["shares_equal"] = equal
        inc["status"] = "CLEARED"
        touch(inc)
        # Ledger sync: the binding proportional share posts onto each
        # license's relocation_share_owed_cents.
        for entry in prop:
            lic = store.DB["licenses"][entry["license_id"]]
            lic["relocation_share_owed_cents"] += entry["amount_cents"]
            touch(lic)
        for lic in active:
            lic.pop("_units", None)
    return success(serializers.incumbent(inc), 200)
