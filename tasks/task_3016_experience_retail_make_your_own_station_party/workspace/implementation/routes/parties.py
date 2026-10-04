"""Party reservations, party guests, and appointment blocks (PRD 3.6-3.7)."""
from datetime import timedelta

from flask import Blueprint

from core import (
    ROLE_CUSTOMER,
    ROLE_MANAGER,
    ROLE_PARTY_HOST,
    body,
    db,
    endpoint,
    err,
    get_or_404,
    is_int,
    new_row,
    now,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    require_owner,
    respond_list,
    respond_object,
    sort_created,
    touch,
)
from domain import (
    MIN_BOOKING_LEAD_HOURS,
    PARTY_DURATION_MINUTES,
    abandon_session,
    check_room_available,
    compute_cancel_refund,
    compute_deposit,
    compute_final_amount_due,
    find_party_block,
    party_guests_of,
    release_party_block,
    select_host,
)

bp = Blueprint("parties", __name__)

CUSTOMER = (ROLE_CUSTOMER,)
MANAGER = (ROLE_MANAGER,)
READ_PARTY = (ROLE_CUSTOMER, ROLE_PARTY_HOST, ROLE_MANAGER)


def _require_whole_hour(dt_value, field):
    if dt_value.minute != 0 or dt_value.second != 0 or dt_value.microsecond != 0:
        err("ERR_VALIDATION", "%s must fall on a whole hour." % field)


# ---------------------------------------------------------------------------
# Party reservations
# ---------------------------------------------------------------------------
@bp.route("/parties", methods=["POST"])
@endpoint(*CUSTOMER)
def create_party():
    data = body()
    # Body-referenced existence (priority 4).
    store = get_or_404("stores", data.get("store_id"), "store")
    customer = get_or_404("customers", data.get("customer_id"), "customer")
    require_owner(customer["id"])
    # Field-level shape (priority 11).
    party_start = req_datetime(data, "party_start")
    _require_whole_hour(party_start, "party_start")
    duration = req_int(data, "duration_minutes")
    if duration != PARTY_DURATION_MINUTES:
        err("ERR_VALIDATION", "duration_minutes must be exactly 120.")
    guest_count = req_int(data, "guest_count", minimum=6, maximum=20)
    package_tier = req_enum(data, "package_tier", ("BASIC", "CELEBRATION", "ULTIMATE"))
    staffing_mode = req_enum(data, "staffing_mode", ("STAFF_HOSTED", "SELF_GUIDED"))
    party = new_row(
        store_id=store["id"],
        customer_id=customer["id"],
        party_start=party_start,
        duration_minutes=duration,
        guest_count=guest_count,
        package_tier=package_tier,
        staffing_mode=staffing_mode,
        deposit_amount_cents=compute_deposit(package_tier, guest_count),
        paid_amount_cents=0,
        final_amount_due_cents=0,
        status="QUOTED",
    )
    db.parties[party["id"]] = party
    return respond_object(party, status=201)


@bp.route("/parties/<party_id>", methods=["GET"])
@endpoint(*READ_PARTY)
def get_party(party_id):
    return respond_object(get_or_404("parties", party_id, "party reservation"))


@bp.route("/parties/<party_id>/pay-deposit", methods=["POST"])
@endpoint(*CUSTOMER)
def pay_party_deposit(party_id):
    party = get_or_404("parties", party_id, "party reservation")
    require_owner(party["customer_id"])
    # State (priority 5).
    if party["status"] != "QUOTED":
        err(
            "ERR_INVALID_STATE",
            "Only a QUOTED reservation can take a deposit (current: %s)."
            % party["status"],
        )
    # Temporal (priority 6): the 72-hour booking lead time.
    if now() > party["party_start"] - timedelta(hours=MIN_BOOKING_LEAD_HOURS):
        err(
            "ERR_OUTSIDE_TIME_WINDOW",
            "The deposit must be paid at least 72 hours before party_start.",
        )
    block_start = party["party_start"]
    block_end = block_start + timedelta(minutes=party["duration_minutes"])
    # Capacity / scheduling (priority 8): room overlap, then host selection.
    store = db.stores.get(party["store_id"])
    check_room_available(store, block_start, block_end)
    host = None
    if party["staffing_mode"] == "STAFF_HOSTED":
        host = select_host(party["store_id"], block_start, block_end)
        if host is None:
            err(
                "ERR_HOST_UNAVAILABLE",
                "No party host is free for the requested block.",
            )
    # Fiscal (priority 10): exact deposit amount.
    data = body()
    amount = data.get("payment_amount_cents")
    if not is_int(amount):
        err("ERR_VALIDATION", "payment_amount_cents must be an integer.")
    if amount != party["deposit_amount_cents"]:
        err(
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            "payment_amount_cents must equal the quoted deposit.",
        )
    # ---- side effects ----
    party["paid_amount_cents"] += party["deposit_amount_cents"]
    party["status"] = "DEPOSIT_PAID"
    touch(party)
    block = new_row(
        store_id=party["store_id"],
        party_reservation_id=party["id"],
        block_start=block_start,
        block_end=block_end,
        reserved_host_id=host["id"] if host else None,
        status="ACTIVE",
    )
    db.appointment_blocks[block["id"]] = block
    return respond_object(party)


@bp.route("/parties/<party_id>/pay-balance", methods=["POST"])
@endpoint(*CUSTOMER)
def pay_party_balance(party_id):
    party = get_or_404("parties", party_id, "party reservation")
    require_owner(party["customer_id"])
    if party["status"] != "COMPLETED":
        err(
            "ERR_INVALID_STATE",
            "The balance can only be paid after finalize (current: %s)."
            % party["status"],
        )
    data = body()
    amount = data.get("payment_amount_cents")
    if not is_int(amount):
        err("ERR_VALIDATION", "payment_amount_cents must be an integer.")
    if amount != party["final_amount_due_cents"]:
        err(
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            "payment_amount_cents must equal the final amount due.",
        )
    party["paid_amount_cents"] += amount
    touch(party)
    return respond_object(party)


@bp.route("/parties/<party_id>/finalize", methods=["POST"])
@endpoint(*MANAGER)
def finalize_party(party_id):
    party = get_or_404("parties", party_id, "party reservation")
    # State (priority 5): must be CONFIRMED with every confirmed guest resolved.
    if party["status"] != "CONFIRMED":
        err(
            "ERR_INVALID_STATE",
            "Only a CONFIRMED reservation can be finalized (current: %s)."
            % party["status"],
        )
    unresolved = [
        guest for guest in party_guests_of(party["id"]) if guest["status"] == "CONFIRMED"
    ]
    if unresolved:
        err(
            "ERR_INVALID_STATE",
            "Every confirmed guest must resolve to ATTENDED or NO_SHOW first.",
        )
    # Temporal (priority 6): only after the appointment block ends.
    block_end = party["party_start"] + timedelta(minutes=party["duration_minutes"])
    if now() < block_end:
        err(
            "ERR_OUTSIDE_TIME_WINDOW",
            "A party can only be finalized after its block has ended.",
        )
    party["final_amount_due_cents"] = compute_final_amount_due(party)
    party["status"] = "COMPLETED"
    touch(party)
    return respond_object(party)


@bp.route("/parties/<party_id>/cancel", methods=["POST"])
@endpoint(*CUSTOMER)
def cancel_party(party_id):
    party = get_or_404("parties", party_id, "party reservation")
    require_owner(party["customer_id"])
    if party["status"] not in ("QUOTED", "DEPOSIT_PAID", "CONFIRMED"):
        err(
            "ERR_INVALID_STATE",
            "A %s reservation cannot be cancelled." % party["status"],
        )
    # Deposit refund (cancel-refund mode); honored count is evaluated at cancel
    # time, before the CONFIRMED cascade marks guests NO_SHOW.
    refund = 0
    if party["status"] in ("DEPOSIT_PAID", "CONFIRMED"):
        refund = compute_cancel_refund(party)
    was_confirmed = party["status"] == "CONFIRMED"
    party["paid_amount_cents"] -= refund
    party["status"] = "CANCELLED"
    touch(party)
    release_party_block(party)
    if was_confirmed:
        # Cascade: abandon every non-terminal party-origin session and mark
        # the linked guests NO_SHOW.
        sessions = [
            s
            for s in db.workshops.values()
            if s["party_reservation_id"] == party["id"]
            and s["status"] not in ("PAID", "ABANDONED")
        ]
        for session in sort_created(sessions):
            abandon_session(session, cascade_parents=False)
        for guest in party_guests_of(party["id"]):
            if guest["status"] == "CONFIRMED":
                guest["status"] = "NO_SHOW"
                touch(guest)
    return respond_object(party)


@bp.route("/parties/<party_id>/reschedule", methods=["POST"])
@endpoint(*CUSTOMER)
def reschedule_party(party_id):
    party = get_or_404("parties", party_id, "party reservation")
    require_owner(party["customer_id"])
    if party["status"] not in ("QUOTED", "DEPOSIT_PAID"):
        err(
            "ERR_INVALID_STATE",
            "A %s reservation cannot be rescheduled." % party["status"],
        )
    data = body()
    # Optimistic concurrency control (PRD section 2.9).
    expected = data.get("expected_party_version")
    if not is_int(expected):
        err("ERR_VALIDATION", "expected_party_version is required.")
    if expected != party["version"]:
        err(
            "ERR_STALE_VERSION",
            "expected_party_version does not match the current version.",
        )
    new_start = req_datetime(data, "new_party_start")
    _require_whole_hour(new_start, "new_party_start")
    block_start = new_start
    block_end = block_start + timedelta(minutes=party["duration_minutes"])
    # Re-run room overlap and host selection against the new interval.
    store = db.stores.get(party["store_id"])
    check_room_available(store, block_start, block_end, exclude_party_id=party["id"])
    host = None
    if party["staffing_mode"] == "STAFF_HOSTED":
        host = select_host(
            party["store_id"], block_start, block_end, exclude_party_id=party["id"]
        )
        if host is None:
            err(
                "ERR_HOST_UNAVAILABLE",
                "No party host is free for the requested block.",
            )
    party["party_start"] = new_start
    touch(party)
    block = find_party_block(party["id"])
    if block is not None and block["status"] == "ACTIVE":
        block["block_start"] = block_start
        block["block_end"] = block_end
        block["reserved_host_id"] = host["id"] if host else None
        touch(block)
    return respond_object(party)


@bp.route("/parties/<party_id>/guests", methods=["GET"])
@endpoint(*READ_PARTY)
def list_party_guests(party_id):
    get_or_404("parties", party_id, "party reservation")
    return respond_list(party_guests_of(party_id))


@bp.route("/parties/<party_id>/workshops", methods=["GET"])
@endpoint(*READ_PARTY)
def list_party_workshops(party_id):
    get_or_404("parties", party_id, "party reservation")
    return respond_list(
        [w for w in db.workshops.values() if w["party_reservation_id"] == party_id]
    )


@bp.route("/parties/<party_id>/appointment-blocks", methods=["GET"])
@endpoint(*READ_PARTY)
def list_party_appointment_blocks(party_id):
    get_or_404("parties", party_id, "party reservation")
    return respond_list(
        [b for b in db.appointment_blocks.values() if b["party_reservation_id"] == party_id]
    )


# ---------------------------------------------------------------------------
# Party guests
# ---------------------------------------------------------------------------
@bp.route("/party-guests", methods=["POST"])
@endpoint(*CUSTOMER)
def create_party_guest():
    data = body()
    party = get_or_404("parties", data.get("party_reservation_id"), "party reservation")
    require_owner(party["customer_id"])
    if party["status"] in ("COMPLETED", "CANCELLED"):
        err(
            "ERR_INVALID_STATE",
            "Guests cannot be added to a %s reservation." % party["status"],
        )
    guest_name = req_str(data, "guest_name")
    guest = new_row(
        party_reservation_id=party["id"],
        guest_name=guest_name,
        workshop_session_id=None,
        status="INVITED",
    )
    db.party_guests[guest["id"]] = guest
    return respond_object(guest, status=201)


@bp.route("/party-guests/<guest_id>", methods=["GET"])
@endpoint(*READ_PARTY)
def get_party_guest(guest_id):
    return respond_object(get_or_404("party_guests", guest_id, "party guest"))


@bp.route("/party-guests/<guest_id>/confirm", methods=["POST"])
@endpoint(*CUSTOMER)
def confirm_party_guest(guest_id):
    guest = get_or_404("party_guests", guest_id, "party guest")
    party = db.parties.get(guest["party_reservation_id"])
    require_owner(party["customer_id"])
    if guest["status"] != "INVITED":
        err(
            "ERR_INVALID_STATE",
            "Only an INVITED guest can be confirmed (current: %s)." % guest["status"],
        )
    if party["status"] not in ("QUOTED", "DEPOSIT_PAID"):
        err(
            "ERR_INVALID_STATE",
            "Guests can only be confirmed while the reservation is QUOTED or "
            "DEPOSIT_PAID (current: %s)." % party["status"],
        )
    confirmed = sum(
        1 for g in party_guests_of(party["id"]) if g["status"] == "CONFIRMED"
    )
    if confirmed >= party["guest_count"]:
        err(
            "ERR_PARTY_GUEST_LIMIT",
            "Confirming this guest would exceed the reservation's guest_count.",
        )
    guest["status"] = "CONFIRMED"
    touch(guest)
    return respond_object(guest)


@bp.route("/party-guests/<guest_id>/cancel", methods=["POST"])
@endpoint(*CUSTOMER)
def cancel_party_guest(guest_id):
    guest = get_or_404("party_guests", guest_id, "party guest")
    party = db.parties.get(guest["party_reservation_id"])
    require_owner(party["customer_id"])
    if guest["status"] == "INVITED":
        pass
    elif guest["status"] == "CONFIRMED":
        if party["status"] not in ("QUOTED", "DEPOSIT_PAID"):
            err(
                "ERR_INVALID_STATE",
                "A confirmed guest can only be cancelled while the reservation is "
                "QUOTED or DEPOSIT_PAID.",
            )
    else:
        err(
            "ERR_INVALID_STATE",
            "A %s guest cannot be cancelled." % guest["status"],
        )
    guest["status"] = "CANCELLED"
    touch(guest)
    return respond_object(guest)
