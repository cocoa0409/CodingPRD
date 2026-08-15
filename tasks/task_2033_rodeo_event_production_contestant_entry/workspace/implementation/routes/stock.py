"""StockContract and StockAnimal endpoints (PRD 3.3)."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    EVENT_CODES,
    get_or_404,
    ser,
    sorted_created,
    stamp,
    terminate_contract_cascade,
    touch,
)
from util import as_enum, as_int_range, as_str, body, pagination_args, required

contracts_bp = Blueprint("stock_contracts", __name__, url_prefix="/api")
animals_bp = Blueprint("stock_animals", __name__, url_prefix="/api")

_CONTRACT_ACTIONS = {"ACTIVATE", "TERMINATE"}


@contracts_bp.post("/stock-contracts")
def create_contract():
    auth(["CommitteeAdmin"])
    data = body()
    rodeo_id = data.get("rodeo_id")
    if rodeo_id is not None:
        get_or_404("rodeos", rodeo_id)
    as_str(required(data, "rodeo_id"), "rodeo_id")
    contractor_name = as_str(required(data, "contractor_name"), "contractor_name")
    day_rate_cents = as_int_range(
        required(data, "day_rate_cents"), "day_rate_cents", 0, None
    )
    per_out_fee_cents = as_int_range(
        required(data, "per_out_fee_cents"), "per_out_fee_cents", 0, None
    )
    rec = {
        "id": new_id(),
        "rodeo_id": rodeo_id,
        "contractor_name": contractor_name,
        "day_rate_cents": day_rate_cents,
        "per_out_fee_cents": per_out_fee_cents,
        "status": "PROPOSED",
        "day_rate_total_cents": 0,
        "per_out_total_cents": 0,
        "settlement_cents": 0,
        "settlement_basis": None,
    }
    stamp(rec)
    DB["stock_contracts"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@contracts_bp.get("/stock-contracts")
def list_contracts():
    auth(ALL_ROLES)
    rodeo_id = request.args.get("rodeo_id")
    status = request.args.get("status")
    items = DB["stock_contracts"].values()
    if rodeo_id is not None:
        items = [c for c in items if c["rodeo_id"] == rodeo_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(c) for c in items[offset : offset + limit]], len(items), limit, offset
    )


@contracts_bp.get("/stock-contracts/<contract_id>")
def get_contract(contract_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("stock_contracts", contract_id)))


@contracts_bp.post("/stock-contracts/<contract_id>/transition")
def transition_contract(contract_id):
    auth(["CommitteeAdmin"])
    contract = get_or_404("stock_contracts", contract_id)
    data = body()
    action = data.get("action")
    if action not in _CONTRACT_ACTIONS:
        raise ApiError(
            "ERR_VALIDATION",
            400,
            f"Field action must be one of {sorted(_CONTRACT_ACTIONS)}",
        )
    if action == "ACTIVATE":
        if contract["status"] != "PROPOSED":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                f"ACTIVATE is not valid from status {contract['status']}",
            )
        rodeo = DB["rodeos"][contract["rodeo_id"]]
        if rodeo["posture"] not in ("DRAFT", "ENTRIES_OPEN"):
            raise ApiError(
                "ERR_RODEO_NOT_OPEN",
                409,
                "Activation requires the rodeo to be DRAFT or ENTRIES_OPEN",
            )
        contract["status"] = "ACTIVE"
    else:  # TERMINATE
        if contract["status"] != "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                f"TERMINATE is not valid from status {contract['status']}",
            )
        terminate_contract_cascade(contract)
        contract["status"] = "TERMINATED"
    touch(contract)
    return ok(ser(contract))


@animals_bp.post("/stock-animals")
def create_animal():
    auth(["CommitteeAdmin"])
    data = body()
    contract_id = data.get("contract_id")
    if contract_id is not None:
        get_or_404("stock_contracts", contract_id)
    as_str(required(data, "contract_id"), "contract_id")
    tag_number = as_str(required(data, "tag_number"), "tag_number")
    event_code = as_enum(required(data, "event_code"), "event_code", EVENT_CODES)
    for a in DB["stock_animals"].values():
        if a["contract_id"] == contract_id and a["tag_number"] == tag_number:
            raise ApiError(
                "ERR_DUPLICATE_TAG", 409, "tag_number already exists in this contract"
            )
    rec = {
        "id": new_id(),
        "contract_id": contract_id,
        "tag_number": tag_number,
        "event_code": event_code,
        "welfare_out_count": 0,
        "status": "AVAILABLE",
    }
    stamp(rec)
    DB["stock_animals"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@animals_bp.get("/stock-animals")
def list_animals():
    auth(ALL_ROLES)
    contract_id = request.args.get("contract_id")
    event_code = request.args.get("event_code")
    status = request.args.get("status")
    items = DB["stock_animals"].values()
    if contract_id is not None:
        items = [a for a in items if a["contract_id"] == contract_id]
    if event_code is not None:
        items = [a for a in items if a["event_code"] == event_code]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(a) for a in items[offset : offset + limit]], len(items), limit, offset
    )


@animals_bp.get("/stock-animals/<animal_id>")
def get_animal(animal_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("stock_animals", animal_id)))
