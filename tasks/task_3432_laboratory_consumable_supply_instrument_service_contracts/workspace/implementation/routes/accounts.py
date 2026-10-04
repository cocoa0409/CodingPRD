"""Account endpoints: create, read, patch, pull-through projection (PRD 3.1/3.3)."""
import uuid

from flask import Blueprint

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, forbid, get_body
from response import paginate, success
from util import round_half_up

bp = Blueprint("accounts", __name__)


@bp.post("/lab/accounts")
def create_account():
    authenticate({"AccountManager", "PlatformAdmin"})
    body = get_body()
    name = body.get("name")
    segment = body.get("segment")
    territory = body.get("territory_code")
    if not isinstance(name, str) or not name.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "name is required")
    if segment not in D.SEGMENTS:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "segment must be one of ACADEMIC, PHARMA, CLINICAL, INDUSTRIAL",
        )
    if not isinstance(territory, str) or not territory.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "territory_code is required")
    priority_class = body.get("priority_class", "STANDARD")
    if priority_class not in D.PRIORITY_CLASSES:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "priority_class must be one of STANDARD, PRIORITY, CRITICAL",
        )
    csl = body.get("controlled_substance_license", False)
    if not isinstance(csl, bool):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "controlled_substance_license must be a boolean",
        )
    now = dbmod.now()
    acct = {
        "id": str(uuid.uuid4()),
        "name": name,
        "segment": segment,
        "priority_class": priority_class,
        "territory_code": territory,
        "controlled_substance_license": csl,
        "status": "ACTIVE",
        "credit_status": "GOOD",
        "outstanding_balance_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.accounts[acct["id"]] = acct
    return success(D.account_json(acct), code=201)


@bp.get("/lab/accounts/<account_id>")
def get_account(account_id):
    uid, role = authenticate(
        {"AccountManager", "LabProcurement", "PlatformAdmin", "ServiceDispatcher"}
    )
    if role == "LabProcurement" and account_id != uid:
        forbid("LabProcurement may read only its own account")
    acct = dbmod.store.accounts.get(account_id)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "Account not found")
    return success(D.account_json(acct))


@bp.patch("/lab/accounts/<account_id>")
def patch_account(account_id):
    authenticate({"AccountManager", "PlatformAdmin"})
    acct = dbmod.store.accounts.get(account_id)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "Account not found")
    body = get_body()
    now = dbmod.now()
    # State guard (priority 4): CLOSED is terminal for any status attempt.
    if acct["status"] == "CLOSED" and "status" in body:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "CLOSED is terminal; status cannot change"
        )
    new_status = None
    if "status" in body:
        target = body["status"]
        if target not in D.ACCOUNT_STATUSES:
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid status value")
        if (acct["status"], target) not in D.ACCOUNT_TRANSITIONS:
            raise ApiError(
                "ERR_INVALID_STATE", 409,
                "status transition %s -> %s is not allowed" % (acct["status"], target),
            )
        new_status = target
    if "name" in body and (not isinstance(body["name"], str) or not body["name"].strip()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "name must be a non-empty string")
    if "segment" in body and body["segment"] not in D.SEGMENTS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid segment value")
    if "priority_class" in body and body["priority_class"] not in D.PRIORITY_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid priority_class value")
    if "territory_code" in body and (
        not isinstance(body["territory_code"], str) or not body["territory_code"].strip()
    ):
        raise ApiError("ERR_INVALID_REQUEST", 400, "territory_code must be a non-empty string")
    if "controlled_substance_license" in body and not isinstance(
        body["controlled_substance_license"], bool
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "controlled_substance_license must be a boolean"
        )
    mutated = False
    for field in (
        "name",
        "segment",
        "priority_class",
        "territory_code",
        "controlled_substance_license",
    ):
        if field in body:
            acct[field] = body[field]
            mutated = True
    if new_status is not None:
        acct["status"] = new_status
        mutated = True
    if mutated:
        acct["version"] += 1
        acct["updated_at"] = now
    return success(D.account_json(acct))


@bp.get("/lab/accounts/<account_id>/pull-through-projection")
def pull_through_projection(account_id):
    uid, role = authenticate({"AccountManager", "LabProcurement", "PlatformAdmin"})
    if role == "LabProcurement" and account_id != uid:
        forbid("LabProcurement may read the projection only for its own account")
    acct = dbmod.store.accounts.get(account_id)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "Account not found")
    installed = [
        i
        for i in dbmod.store.instruments.values()
        if i["account_id"] == account_id and i["placement_status"] == "INSTALLED"
    ]
    ordered = [
        i
        for i in dbmod.store.instruments.values()
        if i["account_id"] == account_id and i["placement_status"] == "ORDERED"
    ]
    installed_base = sum(i["monthly_baseline_consumable_cents"] for i in installed)
    ordered_sum = sum(i["monthly_baseline_consumable_cents"] for i in ordered)
    forward = installed_base + round_half_up(D.FORWARD_WEIGHT * ordered_sum)
    return success(
        {
            "installed_base_monthly_cents": installed_base,
            "forward_looking_monthly_cents": forward,
            "installed_instrument_count": len(installed),
            "ordered_instrument_count": len(ordered),
        }
    )
