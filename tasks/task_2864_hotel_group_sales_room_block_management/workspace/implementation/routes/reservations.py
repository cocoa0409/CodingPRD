"""Rooming-list entries: creation, advancement and cancellation (PRD §3.6)."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from logic import *  # noqa: F401,F403
from serialize import reservation_json

bp = Blueprint("reservations", __name__)

ADVANCES = {
    ("PENDING", "CONFIRMED"),
    ("CONFIRMED", "CHECKED_IN"),
    ("CHECKED_IN", "CHECKED_OUT"),
    ("CONFIRMED", "NO_SHOW"),
}


@bp.route("/group-sales/reservations", methods=["POST"])
@endpoint([ROLE_RESERVATIONS_AGENT, ROLE_GROUP_CONTACT])
def create_reservation():
    body = body_json()
    block_id = v_id(body, "block_id")
    guest_name = v_string(body, "guest_name", min_len=1, max_len=80)
    arrival = v_date(body, "arrival_date")
    departure = v_date(body, "departure_date")
    source = v_enum(body, "source", RESERVATION_SOURCES)
    block = need_block(block_id)
    require_owner(owner_of_block(block))
    if departure <= arrival:
        fail("ERR_INVALID_DATE_RANGE",
             "'departure_date' must be strictly later than 'arrival_date'.")
    if block["inventory_status"] != "OPEN":
        fail("ERR_BLOCK_NOT_OPEN",
             "The block's inventory_status is %s, not OPEN."
             % block["inventory_status"])
    if store.today() >= parse_date_str(block["cutoff_date"]):
        fail("ERR_PAST_CUTOFF_DATE",
             "The block's cutoff date of %s has been reached." % block["cutoff_date"])
    days = date_range(arrival, departure)
    nights = []
    for day in days:
        night = night_of_block(block_id, iso_date(day))
        if night is None:
            fail("ERR_STAY_DATE_OUTSIDE_BLOCK",
                 "The block holds no night for %s." % iso_date(day))
        nights.append(night)
    contract = contract_of_block(block)
    arrival_iso = iso_date(arrival)
    for other in reservations_of_contract(block["contract_id"]):
        if other["status"] == "CANCELLED":
            continue
        if other["guest_name"] == guest_name and other["arrival_date"] == arrival_iso:
            fail("ERR_DUPLICATE_ROOMING_LIST_ENTRY",
                 "%s already has a reservation arriving %s on this contract."
                 % (guest_name, arrival_iso))
    for night in nights:
        if night_rooms_open(night) < 1:
            fail("ERR_BLOCK_ALLOTMENT_EXCEEDED",
                 "The block night %s has no open room left." % night["stay_date"])
    row = new_row({
        "block_id": block_id,
        "guest_name": guest_name,
        "arrival_date": arrival_iso,
        "departure_date": iso_date(departure),
        "source": source,
        "room_nights": whole_days(departure, arrival),
        "is_comp": False,
        "rate_cents": (contract["contracted_rate_cents"]
                       if contract is not None else 0),
        "status": "PENDING",
        "disposition_reason": None,
    })
    store.reservations[row["id"]] = row
    rederive_comp_designations(contract)
    # The comp walk must not make a brand-new row look already-mutated.
    row["version"] = 1
    row["updated_at"] = row["created_at"]
    return ok(reservation_json(row), 201)


@bp.route("/group-sales/reservations/<reservation_id>", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
           ROLE_RESERVATIONS_AGENT, ROLE_ACCOUNTING_CLERK, ROLE_GROUP_CONTACT])
def read_reservation(reservation_id):
    reservation = need_reservation(reservation_id)
    require_owner(owner_of_reservation(reservation))
    return ok(reservation_json(reservation))


@bp.route("/group-sales/reservations/<reservation_id>/advance", methods=["POST"])
@endpoint([ROLE_RESERVATIONS_AGENT])
def advance_reservation(reservation_id):
    body = body_json()
    to_status = v_enum(body, "to_status", RESERVATION_STATUSES)
    reservation = need_reservation(reservation_id)
    if (reservation["status"], to_status) not in ADVANCES:
        fail("ERR_RESERVATION_INVALID_STATE",
             "No transition from %s to %s is declared."
             % (reservation["status"], to_status))
    block = need_block(reservation["block_id"])
    today = store.today()
    if to_status == "CONFIRMED":
        if block["inventory_status"] not in ("OPEN", "CUT_OFF"):
            fail("ERR_BLOCK_INVALID_STATE",
                 "Confirmation requires the block to be OPEN or CUT_OFF; it is %s."
                 % block["inventory_status"])
    elif to_status == "CHECKED_IN":
        if today < parse_date_str(reservation["arrival_date"]):
            fail("ERR_RESERVATION_INVALID_STATE",
                 "Check-in requires the clock date to be on or after %s."
                 % reservation["arrival_date"])
    elif to_status == "CHECKED_OUT":
        if today < parse_date_str(reservation["departure_date"]):
            fail("ERR_RESERVATION_INVALID_STATE",
                 "Check-out requires the clock date to be on or after %s."
                 % reservation["departure_date"])
    else:
        if today < parse_date_str(reservation["arrival_date"]):
            fail("ERR_RESERVATION_INVALID_STATE",
                 "A no-show requires the clock date to be on or after %s."
                 % reservation["arrival_date"])
    reservation["status"] = to_status
    touch(reservation)
    if to_status == "NO_SHOW":
        # Leaves the pickup set but stays inside the actualized set.
        rederive_comp_designations(contract_of_reservation(reservation))
    return ok(reservation_json(reservation))


@bp.route("/group-sales/reservations/<reservation_id>/cancel", methods=["POST"])
@endpoint([ROLE_RESERVATIONS_AGENT, ROLE_GROUP_CONTACT])
def cancel_reservation(reservation_id):
    body = body_json()
    reason = v_string(body, "disposition_reason", min_len=1, max_len=500)
    reservation = need_reservation(reservation_id)
    require_owner(owner_of_reservation(reservation))
    if reservation["status"] not in ("PENDING", "CONFIRMED"):
        fail("ERR_RESERVATION_INVALID_STATE",
             "Cancellation is declared from PENDING or CONFIRMED; the reservation is %s."
             % reservation["status"])
    block = need_block(reservation["block_id"])
    if block["inventory_status"] not in ("OPEN", "CUT_OFF"):
        fail("ERR_BLOCK_INVALID_STATE",
             "Cancellation requires the block to be OPEN or CUT_OFF; it is %s."
             % block["inventory_status"])
    if store.today() >= parse_date_str(reservation["arrival_date"]):
        fail("ERR_CANCEL_AFTER_ARRIVAL",
             "The guest has begun arriving; the cancellation channel is closed.")
    reservation["status"] = "CANCELLED"
    reservation["disposition_reason"] = reason
    touch(reservation)
    if block["inventory_status"] == "CUT_OFF":
        # A cut-off night keeps rooms_open at 0: the freed room is released
        # rather than returned to the pool.
        for day in date_range(parse_date_str(reservation["arrival_date"]),
                              parse_date_str(reservation["departure_date"])):
            night = night_of_block(block["id"], iso_date(day))
            if night is not None:
                night["rooms_released"] = night["rooms_released"] + 1
                touch(night)
    rederive_comp_designations(contract_of_reservation(reservation))
    return ok(reservation_json(reservation))
