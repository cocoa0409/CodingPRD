"""DepositTicket routes: intake, verification, the credit fork and settlement."""

from flask import Blueprint

import calc
from core import (
    ROLE_ARMORED_CARRIER,
    ROLE_CUSTOMER,
    ROLE_VAULT_MANAGER,
    ROLE_VAULT_TELLER,
    TICKET_STATUSES,
    authorize,
    bags_of_ticket,
    body_json,
    check_ownership,
    db,
    fail,
    get_customer,
    get_pagination,
    get_ticket,
    get_vault,
    make_row,
    ordered,
    paginate,
    query_enum,
    query_str,
    req_int,
    req_str,
    respond,
    touch,
)
from serializers import ticket_out

bp = Blueprint("tickets", __name__)


@bp.post("/deposit-tickets")
def create_ticket():
    actor = authorize(ROLE_ARMORED_CARRIER)
    body = body_json()
    customer_account_id = req_str(body, "customer_account_id")
    vault_id = req_str(body, "vault_id")
    courier_manifest_number = req_str(body, "courier_manifest_number")
    declared_bag_count = req_int(body, "declared_bag_count", minimum=1)

    # ladder 6 - body references resolved in declared field order
    get_customer(customer_account_id)
    get_vault(vault_id)

    for existing in db.tickets.values():
        if existing["courier_manifest_number"] == courier_manifest_number:
            fail(
                "ERR_DUPLICATE_IDENTIFIER",
                "courier_manifest_number '%s' already exists." % courier_manifest_number,
            )

    row = make_row()
    row.update({
        "customer_account_id": customer_account_id,
        "vault_id": vault_id,
        "courier_manifest_number": courier_manifest_number,
        "carrier_courier_user_id": actor.user_id,
        "declared_bag_count": declared_bag_count,
        "status": "INTAKE",
        "declared_total_cents": 0,
        "counted_total_cents": 0,
        "processing_fee_total_cents": 0,
        "provisional_credit_cents": 0,
        "final_settlement_cents": 0,
        "settlement_delta_cents": 0,
        "material_variance_open_count": 0,
        "hold_reason": None,
    })
    db.tickets[row["id"]] = row
    return respond(ticket_out(row), 201)


@bp.get("/deposit-tickets/<ticket_id>")
def read_ticket(ticket_id):
    actor = authorize(
        ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_ARMORED_CARRIER, ROLE_CUSTOMER
    )
    ticket = get_ticket(ticket_id)
    check_ownership(actor, ticket["customer_account_id"])
    return respond(ticket_out(ticket))


@bp.get("/deposit-tickets")
def list_tickets():
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_CUSTOMER)
    limit, offset = get_pagination()
    customer_account_id = query_str("customer_account_id")
    vault_id = query_str("vault_id")
    status = query_enum("status", TICKET_STATUSES)

    rows = ordered(db.tickets.values())
    if customer_account_id is not None:
        rows = [r for r in rows if r["customer_account_id"] == customer_account_id]
    if vault_id is not None:
        rows = [r for r in rows if r["vault_id"] == vault_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, ticket_out)


@bp.post("/deposit-tickets/<ticket_id>/verify")
def verify_ticket(ticket_id):
    authorize(ROLE_VAULT_TELLER)
    ticket = get_ticket(ticket_id)

    if ticket["status"] != "INTAKE":
        fail("ERR_INVALID_STATE", "Ticket is not in INTAKE.")

    bags = bags_of_ticket(ticket_id)
    # ladder 10 - bag custody readiness precedes the declared-count agreement
    for bag in bags:
        if bag["custody_status"] not in ("VAULT_RECEIVED", "OPENED"):
            fail("ERR_BAG_NOT_RECEIVED", "Bag %s has not reached the vault." % bag["id"])
    if len(bags) != ticket["declared_bag_count"]:
        fail(
            "ERR_BAG_COUNT_MISMATCH",
            "Registered bag count %d does not match declared_bag_count %d."
            % (len(bags), ticket["declared_bag_count"]),
        )

    calc.recompute_ticket_declared_total(ticket)
    ticket["status"] = "VERIFIED"
    touch(ticket)
    return respond(ticket_out(ticket))


@bp.post("/deposit-tickets/<ticket_id>/provisional-credit")
def provisional_credit(ticket_id):
    authorize(ROLE_VAULT_TELLER)
    ticket = get_ticket(ticket_id)

    if ticket["status"] != "VERIFIED":
        fail("ERR_INVALID_STATE", "Ticket is not in VERIFIED.")

    account = db.customers.get(ticket["customer_account_id"])
    if account is None or account["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "The depositor account is not ACTIVE.")

    amount = calc.provisional_credit_amount(ticket, account)
    ticket["provisional_credit_cents"] = amount
    ticket["status"] = "PROVISIONAL_CREDITED"
    touch(ticket)

    account["provisional_credit_cents"] += amount
    calc.recompute_account_available(account)
    touch(account)
    return respond(ticket_out(ticket))


@bp.post("/deposit-tickets/<ticket_id>/reverse-provisional-credit")
def reverse_provisional_credit(ticket_id):
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    req_str(body, "reason")
    ticket = get_ticket(ticket_id)

    if ticket["status"] != "PROVISIONAL_CREDITED":
        fail("ERR_INVALID_STATE", "Ticket is not in PROVISIONAL_CREDITED.")

    account = db.customers.get(ticket["customer_account_id"])
    amount = ticket["provisional_credit_cents"]
    if account is not None:
        account["provisional_credit_cents"] -= amount
        calc.recompute_account_available(account)
        touch(account)

    ticket["provisional_credit_cents"] = 0
    ticket["status"] = "VERIFIED"
    touch(ticket)
    return respond(ticket_out(ticket))


@bp.post("/deposit-tickets/<ticket_id>/hold")
def hold_ticket(ticket_id):
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    hold_reason = req_str(body, "hold_reason")
    ticket = get_ticket(ticket_id)

    if ticket["status"] != "VERIFIED":
        fail("ERR_INVALID_STATE", "Ticket is not in VERIFIED.")

    ticket["hold_reason"] = hold_reason
    ticket["status"] = "HELD"
    touch(ticket)

    account = db.customers.get(ticket["customer_account_id"])
    if account is not None:
        account["hold_count"] += 1
        touch(account)
    return respond(ticket_out(ticket))


@bp.post("/deposit-tickets/<ticket_id>/settle")
def settle_ticket(ticket_id):
    authorize(ROLE_VAULT_MANAGER)
    ticket = get_ticket(ticket_id)

    if ticket["status"] != "SETTLEMENT_READY":
        fail("ERR_INVALID_STATE", "Ticket is not in SETTLEMENT_READY.")
    if ticket["material_variance_open_count"] != 0:
        fail(
            "ERR_MATERIAL_VARIANCE_UNRESOLVED",
            "The ticket still carries an unresolved material variance.",
        )

    final_settlement, delta = calc.final_settlement_amounts(ticket)
    ticket["final_settlement_cents"] = final_settlement
    ticket["settlement_delta_cents"] = delta

    account = db.customers.get(ticket["customer_account_id"])
    provisional = ticket["provisional_credit_cents"]
    ticket["provisional_credit_cents"] = 0
    ticket["status"] = "SETTLED"
    touch(ticket)

    if account is not None:
        account["provisional_credit_cents"] -= provisional
        account["ledger_balance_cents"] += final_settlement
        calc.recompute_account_available(account)
        calc.apply_settled_only_risk(account)
        touch(account)

    return respond(ticket_out(ticket))
