"""Service contract endpoints: create, read, list, renew, cancel (PRD 3.4)."""
import uuid
from decimal import Decimal

from flask import Blueprint, request

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, forbid, get_body
from response import paginate, success
from util import add_months, is_int, parse_dt, remaining_full_months

bp = Blueprint("contracts", __name__)

_READ_ROLES = {"AccountManager", "LabProcurement", "ServiceDispatcher", "PlatformAdmin"}


def _contract_account_id(contract):
    inst = dbmod.store.instruments[contract["instrument_id"]]
    return inst["account_id"]


@bp.post("/lab/service-contracts")
def create_contract():
    authenticate({"AccountManager", "PlatformAdmin"})
    body = get_body()
    instrument_id = body.get("instrument_id")
    if not isinstance(instrument_id, str) or not instrument_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "instrument_id is required")
    inst = dbmod.store.instruments.get(instrument_id)
    if inst is None:
        raise ApiError("ERR_INSTRUMENT_NOT_FOUND", 404, "Instrument not found")
    if inst["placement_status"] != "INSTALLED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "A service contract requires an INSTALLED instrument",
        )
    tier = body.get("tier")
    if tier not in D.CONTRACT_TIERS:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "tier must be one of BRONZE, SILVER, GOLD, PLATINUM",
        )
    start = parse_dt(body.get("start_date"))
    end = parse_dt(body.get("end_date"))
    if start is None or end is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "start_date and end_date must be ISO8601 instants",
        )
    if not end > start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_date must be after start_date")
    if D.live_contract_for_instrument(instrument_id) is not None:
        raise ApiError(
            "ERR_CONTRACT_ALREADY_ACTIVE", 409,
            "Instrument already has a contract in ACTIVE or RENEWAL_DUE",
        )
    now = dbmod.now()
    contract = {
        "id": str(uuid.uuid4()),
        "instrument_id": instrument_id,
        "tier": tier,
        "start_date": start,
        "end_date": end,
        "used_pm_visits": 0,
        "renewal_count": 0,
        "cancelled_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.contracts[contract["id"]] = contract
    return success(D.contract_json(contract), code=201)


@bp.get("/lab/service-contracts/<contract_id>")
def get_contract(contract_id):
    uid, role = authenticate(_READ_ROLES)
    contract = dbmod.store.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "Service contract not found")
    if role == "LabProcurement" and _contract_account_id(contract) != uid:
        forbid("LabProcurement may read only its own account's contracts")
    return success(D.contract_json(contract))


@bp.get("/lab/service-contracts")
def list_contracts():
    uid, role = authenticate(_READ_ROLES)
    items = list(dbmod.store.contracts.values())
    if role == "LabProcurement":
        items = [c for c in items if _contract_account_id(c) == uid]
    f_inst = request.args.get("instrument_id")
    if f_inst is not None:
        items = [c for c in items if c["instrument_id"] == f_inst]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [c for c in items if D.contract_status(c) == f_status]
    f_tier = request.args.get("tier")
    if f_tier is not None:
        items = [c for c in items if c["tier"] == f_tier]
    items = D.created_sorted(items)
    page, meta = paginate(items)
    return success(
        [D.contract_json(c) for c in page], response_type="array", pagination=meta
    )


@bp.post("/lab/service-contracts/<contract_id>/renew")
def renew_contract(contract_id):
    authenticate({"AccountManager", "PlatformAdmin"})
    contract = dbmod.store.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "Service contract not found")
    # State guard before the OCC check (PRD 2.9 item 5).
    if D.contract_status(contract) != "RENEWAL_DUE":
        raise ApiError(
            "ERR_RENEWAL_WINDOW_CLOSED", 422,
            "Contract is not in the RENEWAL_DUE renewal window",
        )
    body = get_body()
    if "expected_contract_version" not in body:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_contract_version is required"
        )
    expected = body["expected_contract_version"]
    if not is_int(expected):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_contract_version must be an integer"
        )
    if expected != contract["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_contract_version does not match the current version",
        )
    now = dbmod.now()
    with dbmod.store.lock:
        contract["end_date"] = add_months(contract["end_date"], 12)
        contract["renewal_count"] += 1
        contract["version"] += 1
        contract["updated_at"] = now
    return success(D.contract_json(contract))


@bp.post("/lab/service-contracts/<contract_id>/cancel")
def cancel_contract(contract_id):
    authenticate({"AccountManager", "PlatformAdmin"})
    contract = dbmod.store.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "Service contract not found")
    if D.contract_status(contract) not in ("ACTIVE", "RENEWAL_DUE"):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "Only an ACTIVE or RENEWAL_DUE contract can be cancelled",
        )
    now = dbmod.now()
    with dbmod.store.lock:
        contract["cancelled_at"] = now
        contract["version"] += 1
        contract["updated_at"] = now
        # Early-termination fee (calculations.early_termination_fee).
        months = remaining_full_months(now.date(), contract["end_date"].date())
        fee = int(
            Decimal(D.TIER_MONTHLY_VALUE[contract["tier"]]) * months * Decimal("0.5")
        )
        inst = dbmod.store.instruments[contract["instrument_id"]]
        acct = dbmod.store.accounts[inst["account_id"]]
        D.post_charge(acct, fee, now)
    return success(D.contract_json(contract))
