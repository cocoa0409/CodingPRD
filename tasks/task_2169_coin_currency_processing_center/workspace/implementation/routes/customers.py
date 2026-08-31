"""CustomerAccount routes and the read-only customer statement projection."""

from decimal import Decimal

from flask import Blueprint

import calc
from core import (
    CUSTOMER_STATUSES,
    CUSTOMER_TIERS,
    ROLE_CUSTOMER,
    ROLE_VAULT_MANAGER,
    ROLE_VAULT_TELLER,
    authorize,
    body_json,
    check_ownership,
    db,
    dec2,
    fail,
    get_customer,
    make_row,
    opt_enum,
    req_str,
    respond,
)
from serializers import customer_out

bp = Blueprint("customers", __name__)


@bp.post("/customer-accounts")
def create_customer():
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    account_number = req_str(body, "account_number")
    customer_name = req_str(body, "customer_name")
    tier = opt_enum(body, "tier", CUSTOMER_TIERS, "STANDARD")
    status = opt_enum(body, "status", CUSTOMER_STATUSES, "ACTIVE")

    for existing in db.customers.values():
        if existing["account_number"] == account_number:
            fail("ERR_DUPLICATE_IDENTIFIER", "account_number '%s' already exists." % account_number)

    row = make_row()
    row.update({
        "account_number": account_number,
        "customer_name": customer_name,
        "tier": tier,
        "status": status,
        "ledger_balance_cents": 0,
        "provisional_credit_cents": 0,
        "available_balance_cents": 0,
        "risk_score": Decimal("100.00"),
        "risk_grade": "A",
        "denied_claim_count": 0,
        "counterfeit_incident_count": 0,
        "hold_count": 0,
    })
    db.customers[row["id"]] = row
    return respond(customer_out(row), 201)


@bp.get("/customer-accounts/<customer_id>")
def read_customer(customer_id):
    actor = authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_CUSTOMER)
    account = get_customer(customer_id)
    check_ownership(actor, account["id"])
    return respond(customer_out(account))


@bp.get("/customer-accounts/<customer_id>/statement")
def read_statement(customer_id):
    actor = authorize(ROLE_VAULT_MANAGER, ROLE_CUSTOMER)
    account = get_customer(customer_id)
    check_ownership(actor, account["id"])

    projected_score, projected_grade = calc.risk_point_in_time(account)

    tickets = [t for t in db.tickets.values() if t["customer_account_id"] == customer_id]
    open_ticket_count = len([t for t in tickets if t["status"] != "SETTLED"])
    settled_ticket_count = len([t for t in tickets if t["status"] == "SETTLED"])
    open_claim_count = len([
        c for c in db.claims.values()
        if c["customer_account_id"] == customer_id
        and c["status"] in ("SUBMITTED", "INFO_REQUESTED")
    ])

    return respond({
        "customer_account_id": account["id"],
        "ledger_balance_cents": account["ledger_balance_cents"],
        "provisional_credit_cents": account["provisional_credit_cents"],
        "available_balance_cents": account["available_balance_cents"],
        "risk_score": dec2(account["risk_score"]),
        "risk_grade": account["risk_grade"],
        "projected_risk_score": dec2(projected_score),
        "projected_risk_grade": projected_grade,
        "open_ticket_count": open_ticket_count,
        "settled_ticket_count": settled_ticket_count,
        "open_claim_count": open_claim_count,
    })
