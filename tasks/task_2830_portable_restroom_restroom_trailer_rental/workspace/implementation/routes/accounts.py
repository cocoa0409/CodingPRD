"""RentalAccount endpoints."""
from flask import Blueprint

from auth import ALL_ROLES, endpoint
from db import db, insert, ordered, serialize
import constants as C
from responses import created, ok
from routes.common import list_response, resolve
import validation as V

bp = Blueprint("accounts", __name__)


@bp.post("/rental-accounts")
@endpoint(["PlatformAdmin"])
def create_account():
    body = V.body()
    legal_name = V.str_field(body, "legal_name", 1, 120)
    account_type = V.enum_field(body, "account_type", C.ACCOUNT_TYPES)
    credit_terms_days = V.int_field(body, "credit_terms_days", required=False, default=30)
    if credit_terms_days not in C.CREDIT_TERMS_DAYS:
        V.bad("Field 'credit_terms_days' must be one of 0, 15, 30, 45.")
    status = V.enum_field(body, "status", C.ACCOUNT_STATUSES, required=False,
                          default="ACTIVE")
    row = insert("rental_accounts", {
        "legal_name": legal_name,
        "account_type": account_type,
        "credit_terms_days": credit_terms_days,
        "status": status,
        "open_credit_balance_cents": 0,
        "billing_hold": False,
    })
    return created(serialize(row))


@bp.get("/rental-accounts/<account_id>")
@endpoint(ALL_ROLES)
def read_account(account_id):
    account = resolve("rental_accounts", account_id)
    return ok(serialize(account))


@bp.get("/rental-accounts/<account_id>/service-sites")
@endpoint(ALL_ROLES)
def list_account_sites(account_id):
    limit, offset = V.pagination()
    account = resolve("rental_accounts", account_id)
    rows = [s for s in ordered(db.service_sites.values())
            if s["account_id"] == account["id"]]
    return list_response(rows, limit, offset)
