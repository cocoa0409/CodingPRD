"""Instrument endpoints: create, read, list, install, decommission (PRD 3.3)."""
import uuid

from flask import Blueprint, request

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, forbid, get_body
from response import paginate, success
from util import is_int

bp = Blueprint("instruments", __name__)

_READ_ROLES = {"AccountManager", "LabProcurement", "ServiceDispatcher", "PlatformAdmin"}


@bp.post("/lab/instruments")
def create_instrument():
    authenticate({"AccountManager", "PlatformAdmin"})
    body = get_body()
    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "account_id is required")
    acct = dbmod.store.accounts.get(account_id)
    if acct is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "Account not found")
    model = body.get("model")
    serial = body.get("serial_number")
    if not isinstance(model, str) or not model.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "model is required")
    if not isinstance(serial, str) or not serial.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "serial_number is required")
    placement_type = body.get("placement_type")
    if placement_type not in D.PLACEMENT_TYPES:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "placement_type must be one of CAPITAL, REAGENT_RENTAL, LEASE",
        )
    commitment = body.get("monthly_consumable_commitment_cents", 0)
    if not is_int(commitment):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "monthly_consumable_commitment_cents must be an integer",
        )
    if placement_type in ("REAGENT_RENTAL", "LEASE"):
        if "monthly_consumable_commitment_cents" not in body or commitment <= 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                "REAGENT_RENTAL/LEASE require monthly_consumable_commitment_cents > 0",
            )
    else:  # CAPITAL
        if commitment != 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                "CAPITAL placements must carry a commitment of exactly 0",
            )
    baseline = body.get("monthly_baseline_consumable_cents", 0)
    if not is_int(baseline):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "monthly_baseline_consumable_cents must be an integer",
        )
    now = dbmod.now()
    inst = {
        "id": str(uuid.uuid4()),
        "account_id": account_id,
        "model": model,
        "serial_number": serial,
        "placement_type": placement_type,
        "monthly_consumable_commitment_cents": commitment,
        "monthly_baseline_consumable_cents": baseline,
        "placement_status": "ORDERED",
        "installed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.instruments[inst["id"]] = inst
    return success(D.instrument_json(inst), code=201)


@bp.get("/lab/instruments/<instrument_id>")
def get_instrument(instrument_id):
    uid, role = authenticate(_READ_ROLES)
    inst = dbmod.store.instruments.get(instrument_id)
    if inst is None:
        raise ApiError("ERR_INSTRUMENT_NOT_FOUND", 404, "Instrument not found")
    if role == "LabProcurement" and inst["account_id"] != uid:
        forbid("LabProcurement may read only its own account's instruments")
    return success(D.instrument_json(inst))


@bp.get("/lab/instruments")
def list_instruments():
    uid, role = authenticate(_READ_ROLES)
    items = list(dbmod.store.instruments.values())
    if role == "LabProcurement":
        items = [i for i in items if i["account_id"] == uid]
    f_account = request.args.get("account_id")
    if f_account is not None:
        items = [i for i in items if i["account_id"] == f_account]
    f_status = request.args.get("placement_status")
    if f_status is not None:
        items = [i for i in items if i["placement_status"] == f_status]
    f_type = request.args.get("placement_type")
    if f_type is not None:
        items = [i for i in items if i["placement_type"] == f_type]
    items = D.created_sorted(items)
    page, meta = paginate(items)
    return success(
        [D.instrument_json(i) for i in page], response_type="array", pagination=meta
    )


@bp.post("/lab/instruments/<instrument_id>/install")
def install_instrument(instrument_id):
    authenticate({"ServiceDispatcher", "PlatformAdmin"})
    inst = dbmod.store.instruments.get(instrument_id)
    if inst is None:
        raise ApiError("ERR_INSTRUMENT_NOT_FOUND", 404, "Instrument not found")
    if inst["placement_status"] != "ORDERED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an ORDERED instrument can be installed"
        )
    acct = dbmod.store.accounts[inst["account_id"]]
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account is not ACTIVE")
    eligible = any(
        e["status"] == "ACTIVE"
        and e["territory_code"] == acct["territory_code"]
        and "INSTALL" in e["skills"]
        for e in dbmod.store.engineers.values()
    )
    if not eligible:
        raise ApiError(
            "ERR_NO_ELIGIBLE_ENGINEER", 422,
            "No ACTIVE engineer with INSTALL skill covers the account territory",
        )
    now = dbmod.now()
    with dbmod.store.lock:
        inst["placement_status"] = "INSTALLED"
        inst["installed_at"] = now
        inst["version"] += 1
        inst["updated_at"] = now
    return success(D.instrument_json(inst))


@bp.post("/lab/instruments/<instrument_id>/decommission")
def decommission_instrument(instrument_id):
    authenticate({"AccountManager", "PlatformAdmin"})
    inst = dbmod.store.instruments.get(instrument_id)
    if inst is None:
        raise ApiError("ERR_INSTRUMENT_NOT_FOUND", 404, "Instrument not found")
    if inst["placement_status"] != "INSTALLED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "Only an INSTALLED instrument can be decommissioned",
        )
    has_open = any(
        r["instrument_id"] == instrument_id and r["status"] in ("OPEN", "DISPATCHED")
        for r in dbmod.store.service_requests.values()
    )
    if has_open or D.live_contract_for_instrument(instrument_id) is not None:
        raise ApiError(
            "ERR_DECOMMISSION_BLOCKED", 409,
            "Instrument has open service requests or a live contract",
        )
    now = dbmod.now()
    with dbmod.store.lock:
        inst["placement_status"] = "DECOMMISSIONED"
        inst["version"] += 1
        inst["updated_at"] = now
    return success(D.instrument_json(inst))
