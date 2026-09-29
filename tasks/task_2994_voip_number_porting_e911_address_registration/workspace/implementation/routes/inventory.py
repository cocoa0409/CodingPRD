"""Number inventory: blocks, minting, release, reclamation and reservations."""
from flask import Blueprint

import lookup
import store
import util
import validate as v
from common import (auth_for, body_or_error, bump, enum_filter, list_response,
                    new_entity, object_response, optional_body, pagination, paginate,
                    sort_created_asc, str_filter)
from errors import ApiError
from services import derive

bp = Blueprint("inventory", __name__)

NUMBER_STATUSES = ("AVAILABLE", "RESERVED", "ASSIGNED", "PARKED")
RESERVATION_STATUSES = ("HELD", "CONSUMED", "RELEASED", "EXPIRED")
RESERVATION_PURPOSES = ("PORT_BRIDGE", "NEW_LINE")
MAX_RESERVATION_DAYS = 45


# ---------------------------------------------------------------------------
# Number blocks
# ---------------------------------------------------------------------------
@bp.route("/voip/number-blocks", methods=["POST"])
def create_block():
    auth_for(("NumberingAdmin",))
    body = body_or_error()
    jurisdiction_id = v.req_id(body, "jurisdiction_id")
    npa_nxx = v.req_str(body, "npa_nxx", exact_len=6, pattern=v.DIGITS_RE)
    total_capacity = v.req_int(body, "total_capacity", minimum=1, maximum=10000)
    max_concurrent = v.req_int(body, "max_concurrent_reservations", minimum=1)
    lookup.jurisdiction(jurisdiction_id)
    for existing in store.number_blocks.values():
        if existing["npa_nxx"] == npa_nxx:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "A number block with that npa_nxx already exists.")
    row = new_entity()
    row.update({
        "jurisdiction_id": jurisdiction_id,
        "npa_nxx": npa_nxx,
        "total_capacity": total_capacity,
        "max_concurrent_reservations": max_concurrent,
        "minted_count": 0,
        "available_count": 0,
        "reserved_count": 0,
        "assigned_count": 0,
        "parked_count": 0,
    })
    store.number_blocks[row["id"]] = row
    return object_response(row, 201)


@bp.route("/voip/number-blocks/<block_id>", methods=["GET"])
def get_block(block_id):
    auth_for(("NumberingAdmin", "PlatformAdmin", "PortingSpecialist"))
    return object_response(lookup.number_block(block_id))


@bp.route("/voip/number-blocks", methods=["GET"])
def list_blocks():
    auth_for(("NumberingAdmin", "PlatformAdmin"))
    limit, offset = pagination()
    jurisdiction_id = str_filter("jurisdiction_id")
    rows = list(store.number_blocks.values())
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    rows = sort_created_asc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------
@bp.route("/voip/number-blocks/<block_id>/phone-numbers", methods=["POST"])
def mint_number(block_id):
    auth_for(("NumberingAdmin",))
    body = body_or_error()
    line_number = v.req_str(body, "line_number", exact_len=4, pattern=v.DIGITS_RE)
    block = lookup.number_block(block_id)
    for existing in store.phone_numbers.values():
        if existing["block_id"] == block["id"] and existing["line_number"] == line_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "That line_number already exists in this block.")
    if block["minted_count"] >= block["total_capacity"]:
        raise ApiError("ERR_BLOCK_CAPACITY_EXHAUSTED",
                       "The block has no capacity left to mint into.")
    row = new_entity()
    row.update({
        "block_id": block["id"],
        "line_number": line_number,
        "e164": "+1" + block["npa_nxx"] + line_number,
        "status": "AVAILABLE",
        "assigned_account_id": None,
        "parked_until": None,
        "park_cycle_count": 0,
    })
    store.phone_numbers[row["id"]] = row
    derive.recompute_census(block)
    return object_response(row, 201)


@bp.route("/voip/phone-numbers/<number_id>", methods=["GET"])
def get_number(number_id):
    auth_for(("NumberingAdmin", "PlatformAdmin", "PortingSpecialist"))
    return object_response(lookup.phone_number(number_id))


@bp.route("/voip/phone-numbers", methods=["GET"])
def list_numbers():
    auth_for(("NumberingAdmin", "PlatformAdmin"))
    limit, offset = pagination()
    block_id = str_filter("block_id")
    assigned_account_id = str_filter("assigned_account_id")
    status = enum_filter("status", NUMBER_STATUSES)
    rows = list(store.phone_numbers.values())
    if block_id is not None:
        rows = [r for r in rows if r["block_id"] == block_id]
    if assigned_account_id is not None:
        rows = [r for r in rows if r["assigned_account_id"] == assigned_account_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_asc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/voip/phone-numbers/<number_id>/release", methods=["POST"])
def release_number(number_id):
    auth_for(("NumberingAdmin",))
    optional_body()
    number = lookup.phone_number(number_id)
    if number["status"] != "ASSIGNED":
        raise ApiError("ERR_PHONE_NUMBER_STATE_INVALID",
                       "Only an ASSIGNED number can be released.")
    former_account_id = number["assigned_account_id"]
    number["status"] = "PARKED"
    number["parked_until"] = store.now() + util.hours(derive.NUMBER_PARK_HOURS)
    number["park_cycle_count"] = number["park_cycle_count"] + 1
    number["assigned_account_id"] = None
    bump(number)
    for device in store.all_of(store.devices):
        if device["assigned_number_id"] == number["id"]:
            device["assigned_number_id"] = None
            bump(device)
    block = store.number_blocks.get(number["block_id"])
    if block is not None:
        derive.recompute_census(block)
    derive.recompute_posture(store.accounts.get(former_account_id))
    return object_response(number)


@bp.route("/voip/number-blocks/<block_id>/reclamation-runs", methods=["POST"])
def reclamation_run(block_id):
    auth_for(("NumberingAdmin",))
    optional_body()
    block = lookup.number_block(block_id)
    now = store.now()
    parked = [n for n in store.phone_numbers.values()
              if n["block_id"] == block["id"] and n["status"] == "PARKED"
              and n["parked_until"] is not None and n["parked_until"] <= now]
    for number in sorted(parked, key=lambda n: (n["line_number"], n["created_at"], n["_seq"])):
        number["status"] = "AVAILABLE"
        number["parked_until"] = None
        bump(number)
    reservations = [r for r in store.number_reservations.values()
                    if r["block_id"] == block["id"] and r["status"] == "HELD"
                    and r["reserved_until"] < now]
    for reservation in sorted(reservations, key=lambda r: (r["created_at"], r["_seq"])):
        reservation["status"] = "EXPIRED"
        bump(reservation)
        number = store.phone_numbers.get(reservation["number_id"])
        if number is None or number["status"] != "RESERVED":
            continue
        if derive.other_held_reservation_exists(number["id"], reservation["id"]):
            continue
        number["status"] = "AVAILABLE"
        bump(number)
    derive.recompute_census(block)
    return object_response(block)


# ---------------------------------------------------------------------------
# Number reservations
# ---------------------------------------------------------------------------
def _intersects(from_a, until_a, from_b, until_b):
    """Closed intervals: intervals that merely touch at an endpoint intersect."""
    return from_a <= until_b and from_b <= until_a


def _held_reservations_of_block(block_id):
    return [r for r in store.number_reservations.values()
            if r["block_id"] == block_id and r["status"] == "HELD"]


def _select_number(block, reserved_from, reserved_until):
    candidates = [n for n in store.phone_numbers.values()
                  if n["block_id"] == block["id"] and n["status"] == "AVAILABLE"]
    if not candidates:
        raise ApiError("ERR_NO_NUMBERS_AVAILABLE",
                       "No AVAILABLE number remains in this block.")
    candidates.sort(key=lambda n: (n["line_number"], n["created_at"], n["_seq"]))
    return candidates[0]


@bp.route("/voip/number-reservations", methods=["POST"])
def create_reservation():
    auth_for(("NumberingAdmin",))
    body = body_or_error()
    block_id = v.req_id(body, "block_id")
    account_id = v.req_id(body, "account_id")
    purpose = v.req_enum(body, "purpose", RESERVATION_PURPOSES)
    reserved_from = v.req_instant(body, "reserved_from")
    reserved_until = v.req_instant(body, "reserved_until")
    expected_version = v.req_int(body, "expected_number_block_version")
    number_id = v.opt_id(body, "number_id")

    account = lookup.account(account_id)
    block = lookup.number_block(block_id)
    number = lookup.phone_number(number_id) if number_id is not None else None
    lookup.require_active(account)

    if number is not None and number["status"] not in ("AVAILABLE", "RESERVED"):
        raise ApiError("ERR_PHONE_NUMBER_STATE_INVALID",
                       "A named number must be AVAILABLE or RESERVED.")
    if expected_version != block["version"]:
        raise ApiError("ERR_STALE_NUMBER_BLOCK_VERSION",
                       "The number block has moved on since it was read.")
    if account["e911_compliance_posture"] == "BLOCKED":
        raise ApiError("ERR_ACCOUNT_E911_BLOCKED",
                       "The account's E911 compliance posture is BLOCKED.")

    if (reserved_until <= reserved_from
            or reserved_from < store.now()
            or (reserved_until - reserved_from) > util.hours(24 * MAX_RESERVATION_DAYS)):
        raise ApiError("ERR_RESERVATION_WINDOW_INVALID",
                       "The reservation interval is not well formed.")

    intersecting = [r for r in _held_reservations_of_block(block["id"])
                    if _intersects(reserved_from, reserved_until,
                                   r["reserved_from"], r["reserved_until"])]
    if len(intersecting) + 1 > block["max_concurrent_reservations"]:
        raise ApiError("ERR_BLOCK_RESERVATION_CAPACITY_EXCEEDED",
                       "The block's concurrent-reservation ceiling would be exceeded.")

    if number is None:
        number = _select_number(block, reserved_from, reserved_until)

    for other in store.number_reservations.values():
        if other["number_id"] != number["id"] or other["status"] != "HELD":
            continue
        if _intersects(reserved_from, reserved_until,
                       other["reserved_from"], other["reserved_until"]):
            raise ApiError("ERR_NUMBER_RESERVATION_OVERLAP",
                           "That number is already held over an intersecting interval.")

    row = new_entity()
    row.update({
        "number_id": number["id"],
        "block_id": block["id"],
        "account_id": account["id"],
        "purpose": purpose,
        "reserved_from": reserved_from,
        "reserved_until": reserved_until,
        "status": "HELD",
        "released_reason": None,
    })
    store.number_reservations[row["id"]] = row
    if number["status"] == "AVAILABLE":
        number["status"] = "RESERVED"
        bump(number)
    derive.recompute_census(block)
    return object_response(row, 201)


@bp.route("/voip/number-reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    auth_for(("NumberingAdmin", "PortingSpecialist", "PlatformAdmin"))
    return object_response(lookup.reservation(reservation_id))


@bp.route("/voip/number-reservations", methods=["GET"])
def list_reservations():
    auth_for(("NumberingAdmin", "PortingSpecialist", "PlatformAdmin"))
    limit, offset = pagination()
    number_id = str_filter("number_id")
    block_id = str_filter("block_id")
    account_id = str_filter("account_id")
    status = enum_filter("status", RESERVATION_STATUSES)
    rows = list(store.number_reservations.values())
    if number_id is not None:
        rows = [r for r in rows if r["number_id"] == number_id]
    if block_id is not None:
        rows = [r for r in rows if r["block_id"] == block_id]
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_asc(rows)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/voip/number-reservations/<reservation_id>/release", methods=["POST"])
def release_reservation(reservation_id):
    auth_for(("NumberingAdmin",))
    optional_body()
    reservation = lookup.reservation(reservation_id)
    if reservation["status"] != "HELD":
        raise ApiError("ERR_RESERVATION_NOT_HELD",
                       "Only a HELD reservation can be released.")
    reservation["status"] = "RELEASED"
    reservation["released_reason"] = "MANUAL"
    bump(reservation)
    number = store.phone_numbers.get(reservation["number_id"])
    if (number is not None and number["status"] == "RESERVED"
            and not derive.other_held_reservation_exists(number["id"], reservation["id"])):
        number["status"] = "AVAILABLE"
        bump(number)
    block = store.number_blocks.get(reservation["block_id"])
    if block is not None:
        derive.recompute_census(block)
    return object_response(reservation)
