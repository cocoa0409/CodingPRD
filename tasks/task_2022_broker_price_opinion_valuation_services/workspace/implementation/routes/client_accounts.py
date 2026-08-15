"""Client account endpoints (PRD 3.1)."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_FORBIDDEN
from middleware import allowed
from response import success_object, success_list
from serializers import ser_client_account
from validation import body, req_str, req_int, opt_int, opt_num, sort_and_page

bp = Blueprint("client_accounts", __name__)

CODE_PATTERN = r"^[A-Z0-9]{3,12}$"


@bp.post("/bpo/client-accounts")
@allowed("PlatformAdmin")
def create_client_account(user_id, role):
    b = body()
    # Priority 29: body field validation
    client_code = req_str(b, "client_code", pattern=CODE_PATTERN)
    display_name = req_str(b, "display_name")
    sla_standard = req_int(b, "sla_hours_standard", min_v=24, max_v=240)
    sla_rush = req_int(b, "sla_hours_rush", min_v=4)
    if sla_rush >= sla_standard:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'sla_hours_rush' must be strictly less than 'sla_hours_standard'",
            400,
        )
    bps = opt_int(b, "late_penalty_bps_per_day", default=250, min_v=0, max_v=2000)
    w_t = opt_num(b, "scorecard_weight_turnaround", default=None, min_v=0, max_v=1)
    w_q = opt_num(b, "scorecard_weight_quality", default=None, min_v=0, max_v=1)
    w_r = opt_num(b, "scorecard_weight_revision", default=None, min_v=0, max_v=1)

    for existing in db.client_accounts.values():
        if existing["client_code"] == client_code:
            raise ApiError(ERR_INVALID_REQUEST, f"client_code '{client_code}' is already in use", 400)

    record = db.stamp_new({
        "id": db.new_id(),
        "client_code": client_code,
        "display_name": display_name,
        "sla_hours_standard": sla_standard,
        "sla_hours_rush": sla_rush,
        "late_penalty_bps_per_day": bps,
        "scorecard_weight_turnaround": float(w_t) if w_t is not None else 0.5,
        "scorecard_weight_quality": float(w_q) if w_q is not None else 0.3,
        "scorecard_weight_revision": float(w_r) if w_r is not None else 0.2,
        "status": "ACTIVE",
    })
    db.client_accounts[record["id"]] = record
    return success_object(ser_client_account(record), 201)


@bp.get("/bpo/client-accounts")
@allowed("PlatformAdmin", "OperationsManager", "BillingClerk")
def list_client_accounts(user_id, role):
    records = list(db.client_accounts.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = sort_and_page(records, ser_client_account)
    return success_list(items, limit, offset, total)


@bp.get("/bpo/client-accounts/<account_id>")
@allowed("PlatformAdmin", "OperationsManager", "BillingClerk", "ClientAdmin")
def get_client_account(user_id, role, account_id):
    record = db.client_accounts.get(account_id)
    if record is None:
        raise ApiError(ERR_NOT_FOUND, f"ClientAccount {account_id} not found", 404)
    # PRD 3.1: a ClientAdmin may retrieve only its own account record
    if role == "ClientAdmin" and user_id != account_id:
        raise ApiError(ERR_FORBIDDEN, "ClientAdmin may only retrieve its own account", 403)
    return success_object(ser_client_account(record))
