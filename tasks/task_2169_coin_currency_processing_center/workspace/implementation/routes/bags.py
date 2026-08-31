"""SealedBag, CustodyEvent and CountingMachine routes."""

from flask import Blueprint

import calc
from core import (
    BAG_TYPES,
    COUNT_STATUSES,
    CUSTODY_EVENT_TYPES,
    CUSTODY_STATUSES,
    MACHINE_STATUSES,
    MACHINE_TYPES,
    ROLE_ARMORED_CARRIER,
    ROLE_CUSTOMER,
    ROLE_VAULT_MANAGER,
    ROLE_VAULT_TELLER,
    authorize,
    body_json,
    check_ownership,
    custody_events_of_bag,
    db,
    fail,
    get_bag,
    get_machine,
    get_pagination,
    get_ticket,
    get_vault,
    make_row,
    opt_enum,
    opt_int,
    ordered,
    paginate,
    query_enum,
    query_str,
    req_enum,
    req_int,
    req_str,
    respond,
    sessions_of_bag,
    touch,
)
from serializers import bag_out, custody_event_out, machine_out

bp = Blueprint("bags", __name__)


# ------------------------------------------------------------------ SealedBag
@bp.post("/sealed-bags")
def create_bag():
    authorize(ROLE_ARMORED_CARRIER)
    body = body_json()
    deposit_ticket_id = req_str(body, "deposit_ticket_id")
    seal_number = req_str(body, "seal_number")
    bag_type = req_enum(body, "bag_type", BAG_TYPES)
    declared_amount_cents = req_int(body, "declared_amount_cents", minimum=0)
    declared_note_count = opt_int(body, "declared_note_count", default=0, minimum=0)
    declared_coin_weight_grams = opt_int(body, "declared_coin_weight_grams", default=0, minimum=0)

    ticket = get_ticket(deposit_ticket_id)

    # ladder 29 - duplicate seal serial
    for existing in db.bags.values():
        if existing["seal_number"] == seal_number:
            fail("ERR_DUPLICATE_SEAL", "seal_number '%s' is already registered." % seal_number)

    row = make_row()
    row.update({
        "deposit_ticket_id": deposit_ticket_id,
        "seal_number": seal_number,
        "bag_type": bag_type,
        "declared_amount_cents": declared_amount_cents,
        "declared_note_count": declared_note_count,
        "declared_coin_weight_grams": declared_coin_weight_grams,
        "custody_status": "SEALED",
        "count_status": "PENDING",
        "counted_amount_cents": 0,
        "counted_note_count": 0,
        "counted_coin_weight_grams": 0,
        "variance_cents": 0,
        "materiality_flag": False,
        "processing_fee_cents": 0,
        "seized_amount_cents": 0,
        "claim_adjustment_cents": 0,
        "settlement_amount_cents": 0,
        "counted_at": None,
    })
    db.bags[row["id"]] = row

    calc.recompute_ticket_declared_total(ticket)
    touch(ticket)
    return respond(bag_out(row), 201)


@bp.get("/sealed-bags/<bag_id>")
def read_bag(bag_id):
    actor = authorize(
        ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_ARMORED_CARRIER, ROLE_CUSTOMER
    )
    bag = get_bag(bag_id)
    ticket = db.tickets.get(bag["deposit_ticket_id"])
    check_ownership(actor, ticket["customer_account_id"] if ticket else None)
    return respond(bag_out(bag))


@bp.get("/sealed-bags")
def list_bags():
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER)
    limit, offset = get_pagination()
    deposit_ticket_id = query_str("deposit_ticket_id")
    custody_status = query_enum("custody_status", CUSTODY_STATUSES)
    count_status = query_enum("count_status", COUNT_STATUSES)

    rows = ordered(db.bags.values())
    if deposit_ticket_id is not None:
        rows = [r for r in rows if r["deposit_ticket_id"] == deposit_ticket_id]
    if custody_status is not None:
        rows = [r for r in rows if r["custody_status"] == custody_status]
    if count_status is not None:
        rows = [r for r in rows if r["count_status"] == count_status]
    return paginate(rows, limit, offset, bag_out)


CUSTODY_MOVES = {
    "PICKUP": ("SEALED", "IN_TRANSIT"),
    "TRANSFER": ("IN_TRANSIT", "IN_TRANSIT"),
    "VAULT_RECEIPT": ("IN_TRANSIT", "VAULT_RECEIVED"),
    "OPEN": ("VAULT_RECEIVED", "OPENED"),
}


@bp.post("/sealed-bags/<bag_id>/custody-events")
def append_custody_event(bag_id):
    actor = authorize(ROLE_ARMORED_CARRIER, ROLE_VAULT_TELLER)
    body = body_json()
    event_type = req_enum(body, "event_type", CUSTODY_EVENT_TYPES)
    location_code = req_str(body, "location_code")
    observed_seal_number = req_str(body, "observed_seal_number")

    bag = get_bag(bag_id)

    required_from, target = CUSTODY_MOVES[event_type]
    # ladder 9 - transition legality
    if bag["custody_status"] != required_from:
        fail(
            "ERR_INVALID_STATE",
            "A %s hop requires custody_status %s but the bag is %s."
            % (event_type, required_from, bag["custody_status"]),
        )
    if event_type == "OPEN":
        scheduled = [s for s in sessions_of_bag(bag_id) if s["status"] == "SCHEDULED"]
        if not scheduled:
            fail("ERR_INVALID_STATE", "No SCHEDULED counting session exists for this bag.")

    # ladder 31 - the seal is legally read at vault receipt
    if event_type == "VAULT_RECEIPT" and observed_seal_number != bag["seal_number"]:
        fail("ERR_SEAL_TAMPERED", "Observed seal does not match the registered seal.")

    prior = custody_events_of_bag(bag_id)
    row = make_row(common=False)
    row.update({
        "sealed_bag_id": bag_id,
        "event_type": event_type,
        "actor_user_id": actor.user_id,
        "location_code": location_code,
        "observed_seal_number": observed_seal_number,
        "sequence_no": len(prior) + 1,
        "seal_intact": observed_seal_number == bag["seal_number"],
    })
    db.custody_events[row["id"]] = row

    bag["custody_status"] = target
    touch(bag)
    return respond(custody_event_out(row), 201)


@bp.get("/sealed-bags/<bag_id>/custody-events")
def list_custody_events(bag_id):
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_ARMORED_CARRIER)
    limit, offset = get_pagination()
    get_bag(bag_id)
    rows = custody_events_of_bag(bag_id)
    return paginate(rows, limit, offset, custody_event_out)


# ------------------------------------------------------------- CountingMachine
@bp.post("/counting-machines")
def create_machine():
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    vault_id = req_str(body, "vault_id")
    machine_code = req_str(body, "machine_code")
    machine_type = req_enum(body, "machine_type", MACHINE_TYPES)
    status = opt_enum(body, "status", MACHINE_STATUSES, "AVAILABLE")

    get_vault(vault_id)

    for existing in db.machines.values():
        if existing["machine_code"] == machine_code:
            fail("ERR_DUPLICATE_IDENTIFIER", "machine_code '%s' already exists." % machine_code)

    row = make_row()
    row.update({
        "vault_id": vault_id,
        "machine_code": machine_code,
        "machine_type": machine_type,
        "status": status,
    })
    db.machines[row["id"]] = row
    return respond(machine_out(row), 201)


@bp.get("/counting-machines/<machine_id>")
def read_machine(machine_id):
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER)
    return respond(machine_out(get_machine(machine_id)))


@bp.get("/counting-machines")
def list_machines():
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER)
    limit, offset = get_pagination()
    vault_id = query_str("vault_id")
    status = query_enum("status", MACHINE_STATUSES)

    rows = ordered(db.machines.values())
    if vault_id is not None:
        rows = [r for r in rows if r["vault_id"] == vault_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, machine_out)
