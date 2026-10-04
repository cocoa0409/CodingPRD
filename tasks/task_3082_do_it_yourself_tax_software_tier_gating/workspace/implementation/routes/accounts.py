"""TaxpayerAccount endpoints: registration and fetch."""
from flask import Blueprint

from core import (
    ApiError,
    FILING_STATUSES,
    check_ownership,
    db,
    endpoint,
    f_bool,
    f_enum,
    f_int,
    f_str,
    body,
    dump,
    new_row,
    respond_object,
)

bp = Blueprint("accounts", __name__)


@bp.post("/tax/accounts")
@endpoint("Taxpayer")
def create_account():
    payload = body()
    email = f_str(payload, "email")
    full_name = f_str(payload, "full_name")
    filing_status = f_enum(payload, "filing_status", FILING_STATUSES)
    agi = f_int(payload, "agi_cents", minimum=0)
    resident_state = f_str(payload, "resident_state_code")
    enrolled = f_bool(payload, "accuracy_guarantee_enrolled", required=False, default=True)
    for existing in db.accounts.values():
        if existing["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email is already registered.")
    acct = new_row(
        "account",
        email=email,
        full_name=full_name,
        filing_status=filing_status,
        agi_cents=agi,
        resident_state_code=resident_state,
        accuracy_guarantee_enrolled=enrolled,
        disclosure_accepted_version=None,
        status="ACTIVE",
    )
    db.accounts[acct["id"]] = acct
    return respond_object(dump(acct), status=201)


@bp.get("/tax/accounts/<account_id>")
@endpoint("Taxpayer", "PlatformOperator", "ClaimsAdjuster")
def get_account(account_id):
    acct = db.accounts.get(account_id)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", "accountId does not exist.")
    check_ownership(acct)
    return respond_object(dump(acct))
