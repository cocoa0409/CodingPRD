"""Account endpoints."""

from flask import Blueprint

from auth import require_ownership, require_roles
from envelope import ok
from errors import not_found
from serializers import account_json
from store import DB, new_id, stamp_new
from validate import f_enum, f_str, get_body

bp = Blueprint("accounts", __name__)


@bp.post("/genomics/accounts")
def create_account():
    require_roles("AccountManager")
    body = get_body()
    name = f_str(body, "name")
    regulatory_class = f_enum(body, "regulatory_class", ["RUO", "CLINICAL"])
    region = f_str(body, "region")
    account = {
        "id": new_id(),
        "name": name,
        "regulatory_class": regulatory_class,
        "region": region,
        "credit_balance_cents": 0,
    }
    stamp_new(account)
    DB["accounts"][account["id"]] = account
    return ok(account_json(account), 201)


@bp.get("/genomics/accounts/<account_id>")
def get_account(account_id):
    uid, role = require_roles(
        "AccountManager", "FinanceAdmin", "SupplyPlanner", "FieldServiceEngineer", "LabOperator"
    )
    # LabOperator ownership: the caller's X-User-ID IS the account id.
    if role == "LabOperator":
        require_ownership(account_id == uid)
    account = DB["accounts"].get(account_id)
    if account is None:
        raise not_found("Account not found")
    return ok(account_json(account))
