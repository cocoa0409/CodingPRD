"""Reservations: matching, waitlisting, release, swap, return initiation, feedback."""
from flask import Blueprint

import calc
import core
import serialize
import services
from core import (DB, FIT_RATINGS, MAX_RENTAL_DAYS, MIN_RENTAL_DAYS,
                  RESERVATION_STATES, RESERVATION_TERMINAL, date_diff, fail, now_iso,
                  ok, ok_list, today_str)
from guards import (begin, body_json, enum_query, fk, lookup, pagination, paginate,
                    require_owner, sort_rows, str_query, validate)

bp = Blueprint("reservations", __name__)

ALL_ROLES = ["Member", "WarehouseTech", "ClaimsAdjuster", "InventoryPlanner",
             "PlatformAdmin"]

WINDOW_SPEC = [
    {"name": "style_id", "kind": "str", "required": True},
    {"name": "requested_size", "kind": "str", "required": True, "minlen": 1},
    {"name": "requested_start_date", "kind": "date", "required": True},
    {"name": "requested_end_date", "kind": "date", "required": True},
    {"name": "preferred_unit_id", "kind": "str"},
]


def _reservation_guards(style, size, start, end, preferred_unit,
                        freed_unit_id=None, ignore_res_id=None):
    """Ranks 21, 31, 32, 33, 40, 41, 42 in exact ladder order."""
    # Rank 21
    if preferred_unit is not None and preferred_unit["condition_state"] == "CONDEMNED":
        fail("ERR_UNIT_CONDEMNED", "The preferred unit is condemned")
    # Rank 31
    if size not in style["size_run"]:
        fail("ERR_SIZE_NOT_IN_SIZE_RUN",
             "requested_size %s is not in the style's size run" % size)
    if preferred_unit is not None:
        u = preferred_unit
        avail_ok = u["availability_state"] == "IN_STOCK" or (
            freed_unit_id is not None and u["id"] == freed_unit_id
            and u["availability_state"] == "RESERVED")
        # Rank 32
        if (u["style_id"] != style["id"] or u["size"] != size or not avail_ok
                or u["condition_state"] != "FLOOR_READY" or u["quarantine_hold"]):
            fail("ERR_UNIT_NOT_ALLOCATABLE", "The preferred unit is not allocatable")
        # Rank 33
        if u["turns_completed"] >= style["expected_rental_turns_per_unit"]:
            fail("ERR_UNIT_TURNS_EXHAUSTED",
                 "The preferred unit has exhausted its planned turns")
    # Rank 40
    length = date_diff(end, start)
    if length <= 0 or length < MIN_RENTAL_DAYS or length > MAX_RENTAL_DAYS:
        fail("ERR_INVALID_RENTAL_WINDOW",
             "The rental window must be between %d and %d days"
             % (MIN_RENTAL_DAYS, MAX_RENTAL_DAYS))
    # Rank 41
    if start < today_str():
        fail("ERR_WINDOW_IN_PAST", "requested_start_date is before the current date")
    # Rank 42
    if preferred_unit is not None and calc.interval_collision(
            preferred_unit["id"], start, end, ignore_res_id):
        fail("ERR_UNIT_WINDOW_COLLISION",
             "The preferred unit is already committed over that window")


def _new_reservation_row(member, style, data, is_swap=False,
                         superseded_reservation_id=None):
    row = services.base_row("reservations")
    row.update({
        "member_id": member["id"],
        "style_id": style["id"],
        "allocated_unit_id": None,
        "superseded_reservation_id": superseded_reservation_id,
        "requested_size": data["requested_size"],
        "requested_start_date": data["requested_start_date"],
        "requested_end_date": data["requested_end_date"],
        "state": "REQUESTED",
        "is_swap": is_swap,
        "matched_at": None,
        "shipped_at": None,
        "delivered_at": None,
        "returned_at": None,
        "rental_days": None,
        "late_days": 0,
        "late_fee_cents": 0,
        "revenue_attributed_cents": 0,
    })
    DB["reservations"][row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.post("/reservations")
def create_reservation():
    ctx = begin(["Member"])
    member = ctx.member
    body = body_json()
    style = fk(body, "style_id", "styles", "ERR_STYLE_NOT_FOUND")
    preferred = fk(body, "preferred_unit_id", "rental_units",
                   "ERR_RENTAL_UNIT_NOT_FOUND")
    data = validate(body, WINDOW_SPEC)
    # Rank 14
    if member["status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE", "Membership is not ACTIVE")
    _reservation_guards(style, data["requested_size"],
                        data["requested_start_date"], data["requested_end_date"],
                        preferred)
    # Rank 50
    plan = DB["membership_plans"][member["membership_plan_id"]]
    committed = (calc.member_units_out(member["id"])
                 + calc.member_waitlisted(member["id"]))
    if committed >= plan["item_slots"]:
        fail("ERR_ITEM_SLOTS_EXHAUSTED", "The plan's item slots are exhausted")

    row = _new_reservation_row(member, style, data)
    services.resolve_new_reservation(row, member, style, preferred)
    return ok(serialize.reservation_out(row), 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/reservations/<reservation_id>")
def get_reservation(reservation_id):
    ctx = begin(ALL_ROLES)
    row = lookup("reservations", reservation_id, "ERR_RESERVATION_NOT_FOUND")
    require_owner(ctx, row["member_id"])
    return ok(serialize.reservation_out(row))


@bp.get("/reservations")
def list_reservations():
    ctx = begin(ALL_ROLES)
    state = enum_query("state", RESERVATION_STATES)
    member_id = str_query("member_id")
    style_id = str_query("style_id")
    unit_id = str_query("allocated_unit_id")
    superseded = str_query("superseded_reservation_id")
    if ctx.role == "Member":
        if member_id is not None and member_id != ctx.user_id:
            fail("ERR_NOT_RESOURCE_OWNER", "Members may only read their own rows")
        member_id = ctx.user_id
    limit, offset = pagination()
    rows = []
    for r in DB["reservations"].values():
        if member_id is not None and r["member_id"] != member_id:
            continue
        if style_id is not None and r["style_id"] != style_id:
            continue
        if unit_id is not None and r["allocated_unit_id"] != unit_id:
            continue
        if superseded is not None and r["superseded_reservation_id"] != superseded:
            continue
        if state is not None and r["state"] != state:
            continue
        rows.append(r)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.reservation_out)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------
@bp.post("/reservations/<reservation_id>/release")
def release_reservation(reservation_id):
    ctx = begin(["Member", "PlatformAdmin"])
    res = lookup("reservations", reservation_id, "ERR_RESERVATION_NOT_FOUND")
    require_owner(ctx, res["member_id"])
    member = DB["members"][res["member_id"]]
    if res["state"] in RESERVATION_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Reservation is %s" % res["state"])
    if res["state"] not in ("MATCHED", "WAITLISTED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Release is not declared from %s" % res["state"])
    if res["state"] == "MATCHED":
        unit = DB["rental_units"].get(res["allocated_unit_id"])
        res["state"] = "RELEASED"
        res["allocated_unit_id"] = None
        services.touch(res)
        if unit is not None and unit["availability_state"] == "RESERVED":
            unit["availability_state"] = "IN_STOCK"
            services.touch(unit)
            services.promote_for_freed_unit(unit)
        services.touch(member)
    else:
        res["state"] = "CANCELLED"
        services.touch(res)
    return ok(serialize.reservation_out(res))


# ---------------------------------------------------------------------------
# Swap
# ---------------------------------------------------------------------------
@bp.post("/reservations/<reservation_id>/swap")
def swap_reservation(reservation_id):
    ctx = begin(["Member"])
    res = lookup("reservations", reservation_id, "ERR_RESERVATION_NOT_FOUND")
    require_owner(ctx, res["member_id"])
    member = ctx.member
    body = body_json()
    style = fk(body, "style_id", "styles", "ERR_STYLE_NOT_FOUND")
    preferred = fk(body, "preferred_unit_id", "rental_units",
                   "ERR_RENTAL_UNIT_NOT_FOUND")
    spec = [{"name": "expected_member_version", "kind": "int", "required": True}]
    spec.extend(WINDOW_SPEC)
    data = validate(body, spec)
    # Rank 12
    if data["expected_member_version"] != member["version"]:
        fail("ERR_STALE_MEMBER_VERSION",
             "expected_member_version does not match the member's current version")
    # Rank 14
    if member["status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE", "Membership is not ACTIVE")
    # Ranks 15 / 16
    if res["state"] in RESERVATION_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Reservation is %s" % res["state"])
    if res["state"] != "MATCHED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Swap is not declared from %s" % res["state"])
    old_unit = DB["rental_units"].get(res["allocated_unit_id"])
    freed_unit_id = old_unit["id"] if old_unit is not None else None
    _reservation_guards(style, data["requested_size"],
                        data["requested_start_date"], data["requested_end_date"],
                        preferred, freed_unit_id=freed_unit_id,
                        ignore_res_id=res["id"])
    # Rank 51
    plan = DB["membership_plans"][member["membership_plan_id"]]
    if calc.swaps_used_current_month(member["id"]) >= plan["monthly_swaps_allowed"]:
        fail("ERR_SWAP_ALLOWANCE_EXHAUSTED", "The month's swap allowance is exhausted")

    # Hop 1 — supersede
    res["state"] = "SUPERSEDED"
    services.touch(res)
    # Hop 2 — release the old unit before the replacement is allocated
    if old_unit is not None and old_unit["availability_state"] == "RESERVED":
        old_unit["availability_state"] = "IN_STOCK"
        services.touch(old_unit)
    # Hop 3 — the replacement
    row = _new_reservation_row(member, style, data, is_swap=True,
                               superseded_reservation_id=res["id"])
    services.resolve_new_reservation(row, member, style, preferred)
    return ok(serialize.reservation_out(row), 201)


# ---------------------------------------------------------------------------
# Return initiation
# ---------------------------------------------------------------------------
@bp.post("/reservations/<reservation_id>/return-initiation")
def return_initiation(reservation_id):
    ctx = begin(["Member"])
    res = lookup("reservations", reservation_id, "ERR_RESERVATION_NOT_FOUND")
    require_owner(ctx, res["member_id"])
    member = ctx.member
    body = body_json()
    data = validate(body, [
        {"name": "planned_ship_date", "kind": "date"},
        {"name": "carrier_reference", "kind": "str"},
    ])
    # Rank 14
    if member["status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE", "Membership is not ACTIVE")
    # Ranks 15 / 16
    if res["state"] in RESERVATION_TERMINAL:
        fail("ERR_RESOURCE_TERMINAL", "Reservation is %s" % res["state"])
    if res["state"] != "IN_POSSESSION":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Return initiation is not declared from %s" % res["state"])
    # Rank 39
    for s in DB["shipments"].values():
        if s["reservation_id"] == res["id"] and s["direction"] == "INBOUND":
            fail("ERR_SHIPMENT_ALREADY_EXISTS",
                 "An inbound leg already exists for this reservation")

    res["state"] = "RETURN_INITIATED"
    services.touch(res)
    leg = services.base_row("shipments")
    leg.update({
        "member_id": res["member_id"],
        "reservation_id": res["id"],
        "direction": "INBOUND",
        "planned_ship_date": data.get("planned_ship_date") or today_str(),
        "state": "CREATED",
        "carrier_reference": data.get("carrier_reference"),
        "dispatched_at": None,
        "delivered_at": None,
        "received_at": None,
        "exception_count": 0,
        "exception_reason": None,
    })
    DB["shipments"][leg["id"]] = leg
    unit = DB["rental_units"].get(res["allocated_unit_id"])
    if unit is not None and unit["availability_state"] == "OUT":
        unit["availability_state"] = "INBOUND"
        services.touch(unit)
    return ok(serialize.shipment_out(leg), 201)


# ---------------------------------------------------------------------------
# Fit feedback
# ---------------------------------------------------------------------------
@bp.post("/reservations/<reservation_id>/fit-feedback")
def create_fit_feedback(reservation_id):
    ctx = begin(["Member"])
    res = lookup("reservations", reservation_id, "ERR_RESERVATION_NOT_FOUND")
    require_owner(ctx, res["member_id"])
    body = body_json()
    data = validate(body, [
        {"name": "fit_rating", "kind": "enum", "required": True, "values": FIT_RATINGS},
        {"name": "occasion_match_score", "kind": "int", "required": True,
         "min": 1, "max": 5},
        {"name": "keep_intent", "kind": "bool", "default": False},
        {"name": "comment", "kind": "str", "default": None},
    ])
    # Rank 36
    if res["state"] not in ("RETURNED", "CLOSED"):
        fail("ERR_FEEDBACK_NOT_ELIGIBLE",
             "Feedback is only eligible on a RETURNED or CLOSED reservation")
    # Rank 37
    for f in DB["fit_feedbacks"].values():
        if f["reservation_id"] == res["id"]:
            fail("ERR_FEEDBACK_ALREADY_EXISTS",
                 "Feedback already exists for this reservation")
    row = services.base_row("fit_feedbacks", event=True)
    row.update({
        "reservation_id": res["id"],
        "member_id": res["member_id"],
        "style_id": res["style_id"],
        "fit_rating": data["fit_rating"],
        "occasion_match_score": data["occasion_match_score"],
        "keep_intent": data["keep_intent"],
        "comment": data.get("comment"),
    })
    DB["fit_feedbacks"][row["id"]] = row
    return ok(serialize.feedback_out(row), 201)


@bp.get("/fit-feedback/<feedback_id>")
def get_fit_feedback(feedback_id):
    ctx = begin(["Member", "InventoryPlanner", "PlatformAdmin"])
    row = lookup("fit_feedbacks", feedback_id, "ERR_FEEDBACK_NOT_FOUND")
    require_owner(ctx, row["member_id"])
    return ok(serialize.feedback_out(row))


@bp.get("/fit-feedback")
def list_fit_feedback():
    ctx = begin(["Member", "InventoryPlanner", "PlatformAdmin"])
    rating = enum_query("fit_rating", FIT_RATINGS)
    reservation_id = str_query("reservation_id")
    member_id = str_query("member_id")
    style_id = str_query("style_id")
    if ctx.role == "Member":
        if member_id is not None and member_id != ctx.user_id:
            fail("ERR_NOT_RESOURCE_OWNER", "Members may only read their own rows")
        member_id = ctx.user_id
    limit, offset = pagination()
    rows = []
    for r in DB["fit_feedbacks"].values():
        if reservation_id is not None and r["reservation_id"] != reservation_id:
            continue
        if member_id is not None and r["member_id"] != member_id:
            continue
        if style_id is not None and r["style_id"] != style_id:
            continue
        if rating is not None and r["fit_rating"] != rating:
            continue
        rows.append(r)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.feedback_out)
    return ok_list(items, limit, offset, total)
