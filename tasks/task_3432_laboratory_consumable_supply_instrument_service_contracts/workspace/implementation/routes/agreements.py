"""Enterprise agreement endpoints: create, read, list, renew, terminate (PRD 3.2)."""
import uuid

from flask import Blueprint, request

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, forbid, get_body
from response import paginate, success
from util import add_months, is_int, parse_dt

bp = Blueprint("agreements", __name__)


@bp.post("/lab/enterprise-agreements")
def create_agreement():
    authenticate({"AccountManager", "PlatformAdmin"})
    body = get_body()
    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "account_id is required")
    acct = dbmod.store.accounts.get(account_id)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "Account not found")
    start = parse_dt(body.get("start_date"))
    end = parse_dt(body.get("end_date"))
    if start is None or end is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "start_date and end_date must be ISO8601 instants",
        )
    if not end > start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_date must be after start_date")
    committed = body.get("committed_annual_spend_cents")
    if not is_int(committed):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "committed_annual_spend_cents must be an integer",
        )
    # Half-open overlap against same-account agreements reading ACTIVE/EXPIRING.
    for g in dbmod.store.agreements.values():
        if g["account_id"] != account_id:
            continue
        if D.agreement_status(g) not in ("ACTIVE", "EXPIRING"):
            continue
        if start < g["end_date"] and g["start_date"] < end:
            raise ApiError(
                "ERR_AGREEMENT_WINDOW_OVERLAP", 409,
                "window overlaps an existing live agreement of this account",
            )
    now = dbmod.now()
    agr = {
        "id": str(uuid.uuid4()),
        "account_id": account_id,
        "start_date": start,
        "end_date": end,
        "committed_annual_spend_cents": committed,
        "renewal_count": 0,
        "terminated_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.agreements[agr["id"]] = agr
    return success(D.agreement_json(agr), code=201)


@bp.get("/lab/enterprise-agreements/<agreement_id>")
def get_agreement(agreement_id):
    uid, role = authenticate({"AccountManager", "LabProcurement", "PlatformAdmin"})
    agr = dbmod.store.agreements.get(agreement_id)
    if agr is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Enterprise agreement not found")
    if role == "LabProcurement" and agr["account_id"] != uid:
        forbid("LabProcurement may read only its own account's agreements")
    return success(D.agreement_json(agr))


@bp.get("/lab/enterprise-agreements")
def list_agreements():
    uid, role = authenticate({"AccountManager", "LabProcurement", "PlatformAdmin"})
    items = list(dbmod.store.agreements.values())
    if role == "LabProcurement":
        items = [g for g in items if g["account_id"] == uid]
    f_account = request.args.get("account_id")
    if f_account is not None:
        items = [g for g in items if g["account_id"] == f_account]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [g for g in items if D.agreement_status(g) == f_status]
    items = D.created_sorted(items)
    page, meta = paginate(items)
    return success(
        [D.agreement_json(g) for g in page], response_type="array", pagination=meta
    )


@bp.post("/lab/enterprise-agreements/<agreement_id>/renew")
def renew_agreement(agreement_id):
    authenticate({"AccountManager", "PlatformAdmin"})
    agr = dbmod.store.agreements.get(agreement_id)
    if agr is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Enterprise agreement not found")
    # State guard before the OCC check (PRD 2.9 item 5).
    if D.agreement_status(agr) != "EXPIRING":
        raise ApiError(
            "ERR_RENEWAL_WINDOW_CLOSED", 422,
            "Agreement is not in the EXPIRING renewal window",
        )
    body = get_body()
    if "expected_agreement_version" not in body:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_agreement_version is required"
        )
    expected = body["expected_agreement_version"]
    if not is_int(expected):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_agreement_version must be an integer"
        )
    if expected != agr["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_agreement_version does not match the current version",
        )
    now = dbmod.now()
    with dbmod.store.lock:
        agr["end_date"] = add_months(agr["end_date"], 12)
        agr["renewal_count"] += 1
        agr["version"] += 1
        agr["updated_at"] = now
    return success(D.agreement_json(agr))


@bp.post("/lab/enterprise-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    authenticate({"AccountManager", "PlatformAdmin"})
    agr = dbmod.store.agreements.get(agreement_id)
    if agr is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Enterprise agreement not found")
    if D.agreement_status(agr) not in ("ACTIVE", "EXPIRING"):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "Only an ACTIVE or EXPIRING agreement can be terminated",
        )
    now = dbmod.now()
    with dbmod.store.lock:
        agr["terminated_at"] = now
        agr["version"] += 1
        agr["updated_at"] = now
    return success(D.agreement_json(agr))
