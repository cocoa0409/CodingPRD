"""Account routes: create/get/list, suspend/reinstate/close, run_ops, ops_runs."""
from flask import Blueprint, request

import store
from constants import PLAN_TIERS, COUNTRY_CODES
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    validation,
)
from response import success_object, success_list
from serializers import ser_account, ser_opsrun
from services.shared import (
    cascade_suspend_account,
    check_account_gate,
    drain_campaign_queue,
    record_charge,
    recurring_fee_pass,
    stale_sweep,
)
from util import (
    find_or_404,
    get_json_body,
    new_id,
    now_dt,
    pagination_params,
    parse_iso,
    format_iso,
    require_auth,
    require_enum,
    require_nonempty,
    sort_by_created,
    touch,
)

bp = Blueprint("accounts", __name__)

READ_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "BrandManager", "CampaignManager",
    "NumberProvisioner", "CarrierReviewer", "SystemDriver",
]


@bp.post("/messaging/accounts")
def create_account():
    require_auth(["PlatformAdmin"])
    body = get_json_body()
    require_nonempty(body, ["name"])
    plan_tier = require_enum(body, "plan_tier", PLAN_TIERS)
    country_code = require_enum(body, "country_code", COUNTRY_CODES)
    account = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "updated_at": store.now_iso(),
        "version": 1,
        "name": body["name"],
        "plan_tier": plan_tier,
        "country_code": country_code,
        "suspend_reason": "",
        "status": "ACTIVE",
    }
    store.ACCOUNTS[account["id"]] = account
    return success_object(ser_account(account), 201)


@bp.get("/messaging/accounts/<account_id>")
def get_account(account_id):
    require_auth(READ_ROLES + ["DeliverabilityAnalyst"])
    account = find_or_404(store.ACCOUNTS, account_id)
    return success_object(ser_account(account))


@bp.get("/messaging/accounts")
def list_accounts():
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    limit, offset = pagination_params()
    items = list(store.ACCOUNTS.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_account(a) for a in page], limit, offset, total)


@bp.post("/messaging/accounts/<account_id>/suspend")
def suspend_account(account_id):
    require_auth(["ComplianceOfficer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    if account["status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_CLOSED", "Account is closed", 409)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Account is not ACTIVE", 409)
    body = get_json_body()
    reason = body.get("reason", "")
    if not isinstance(reason, str):
        raise validation("reason must be a string")
    account["status"] = "SUSPENDED"
    account["suspend_reason"] = reason
    touch(account)
    cascade_suspend_account(account)
    return success_object(ser_account(account))


@bp.post("/messaging/accounts/<account_id>/reinstate")
def reinstate_account(account_id):
    require_auth(["ComplianceOfficer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    if account["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Account is not SUSPENDED", 409)
    account["status"] = "ACTIVE"
    account["suspend_reason"] = ""
    touch(account)
    return success_object(ser_account(account))


@bp.post("/messaging/accounts/<account_id>/close")
def close_account(account_id):
    require_auth(["PlatformAdmin"])
    account = find_or_404(store.ACCOUNTS, account_id)
    if account["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Account is not SUSPENDED", 409)
    account["status"] = "CLOSED"
    touch(account)
    numbers = [
        n for n in store.NUMBERS.values()
        if n["account_id"] == account["id"] and n["status"] in ("ACTIVE", "SUSPENDED")
    ]
    for number in sort_by_created(numbers):
        number["status"] = "RELEASED"
        number["suspended_reason"] = "ACCOUNT_CLOSED"
        number["campaign_id"] = ""
        touch(number)
    return success_object(ser_account(account))


@bp.post("/messaging/accounts/<account_id>/run_ops")
def run_ops(account_id):
    require_auth(["PlatformAdmin"])
    account = find_or_404(store.ACCOUNTS, account_id)
    check_account_gate(account)
    now = now_dt()
    previous_indexes = [
        r["run_index"] for r in store.OPSRUNS.values()
        if r["account_id"] == account_id
    ]
    run_index = (max(previous_indexes) if previous_indexes else 0) + 1

    # Duty 1: queue drain, APPROVED campaigns in created_at ASC.
    dequeued = 0
    campaigns = [
        c for c in store.CAMPAIGNS.values()
        if c["account_id"] == account_id and c["status"] == "APPROVED"
    ]
    for campaign in sort_by_created(campaigns):
        dequeued += drain_campaign_queue(campaign, run_index)

    # Duty 2: staleness sweep.
    stale = stale_sweep(account_id, run_index)

    # Duty 3: recurring + number fee pass.
    recurring_count, number_count = recurring_fee_pass(account, now)

    run = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "account_id": account_id,
        "run_index": run_index,
        "executed_at": store.now_iso(),
        "messages_dequeued": dequeued,
        "messages_stale_cancelled": stale,
        "recurring_fees_charged": recurring_count,
        "number_fees_charged": number_count,
    }
    store.OPSRUNS[run["id"]] = run
    return success_object(ser_opsrun(run))


@bp.get("/messaging/accounts/<account_id>/ops_runs")
def list_account_ops_runs(account_id):
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    find_or_404(store.ACCOUNTS, account_id)
    limit, offset = pagination_params()
    items = [r for r in store.OPSRUNS.values() if r["account_id"] == account_id]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_opsrun(r) for r in page], limit, offset, total)
