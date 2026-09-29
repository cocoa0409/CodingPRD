"""Accounts (PRD 3.1)."""

from flask import Blueprint

import auth
import calc
import envelope
import listing
import serialize
import shape
from store import insert, must_find, new_row, ordered, rows

bp = Blueprint("accounts", __name__)

READ_ONE_ROLES = (
    "ProgramManager",
    "ClaimsAssessor",
    "ClaimsApprover",
    "InstallCoordinator",
    "Subscriber",
    "MduOwner",
)
LIST_ROLES = ("ProgramManager", "ClaimsAssessor", "ClaimsApprover", "InstallCoordinator")


@bp.post("/accounts")
def create_account():
    auth.gate(("ProgramManager",))
    data = shape.body()
    full_name = shape.req_str(data, "full_name", 1, 120)
    email = shape.req_str(data, "email", 1)
    if "@" not in email:
        shape.bad("email", "must contain an at-sign")
    phone = shape.req_str(data, "phone", 1, 32)
    account_type = shape.req_enum(data, "account_type", calc.ACCOUNT_TYPES)
    for existing in rows("accounts"):
        if existing["email"] == email:
            shape.bad("email", "is already registered")
    row = new_row(
        {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "account_type": account_type,
        }
    )
    insert("accounts", row)
    return envelope.created(serialize.account(row))


@bp.get("/accounts/<account_id>")
def read_account(account_id):
    auth.gate(READ_ONE_ROLES)
    row = must_find("accounts", account_id)
    return envelope.ok(serialize.account(row))


@bp.get("/accounts")
def list_accounts():
    auth.gate(LIST_ROLES)
    items = listing.apply_filters(
        ordered(rows("accounts")),
        (listing.enum("account_type", "account_type", calc.ACCOUNT_TYPES),),
    )
    return envelope.list_response(items, serialize.account)
