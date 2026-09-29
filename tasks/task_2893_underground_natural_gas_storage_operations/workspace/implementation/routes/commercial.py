"""Shipper, storage contract, cash-out and balancing ledger endpoints (PRD 3.4, 3.7)."""
import re

from flask import Blueprint

import auth
import config
import engine
import envelope
import serialize
import store
import validate
from errors import ApiError, bad_request
from routes.helpers import filter_eq, list_result
from utils import D, q2, q3

bp = Blueprint("commercial", __name__)

_DUNS_RE = re.compile(r"^\d{9}$")


# ================================================================ shippers
@bp.post("/shippers")
def create_shipper():
    auth.require([config.ROLE_SCHEDULING_COORDINATOR])
    body = validate.json_body()

    legal_name = validate.field_str(body, "legal_name", allow_empty=False)
    duns_number = validate.field_str(body, "duns_number")
    if not _DUNS_RE.match(duns_number):
        raise bad_request("duns_number must be exactly nine digits.")
    threshold = validate.field_number(body, "penalty_threshold_usd", exclusive_minimum=0)

    for existing in store.shippers.values():
        if existing["duns_number"] == duns_number:
            raise ApiError("ERR_DUPLICATE_DUNS", "duns_number %s already exists." % duns_number)

    shipper = store.new_record()
    shipper.update({
        "legal_name": legal_name,
        "duns_number": duns_number,
        "penalty_threshold_usd": q2(threshold),
        "outstanding_penalty_usd": D("0.00"),
        "credit_status": "GOOD",
    })
    store.put("Shipper", shipper)
    return envelope.created(serialize.shipper(shipper))


@bp.get("/shippers/<shipper_id>")
def read_shipper(shipper_id):
    auth.require(config.COMMERCIAL_READ_ROLES)
    shipper = validate.resolve_path("Shipper", shipper_id)
    return envelope.object_response(serialize.shipper(shipper))


# ================================================================ contracts
@bp.post("/storage-contracts")
def create_contract():
    auth.require([config.ROLE_SCHEDULING_COORDINATOR])
    body = validate.json_body()

    shipper_id = validate.field_id(body, "shipper_id")
    field_id = validate.field_id(body, "storage_field_id")
    contract_code = validate.field_str(body, "contract_code", allow_empty=False)
    service_class = validate.field_enum(body, "service_class", config.SERVICE_CLASSES)
    max_storage = validate.field_number(body, "max_storage_quantity_dth", exclusive_minimum=0)
    max_injection = validate.field_number(body, "max_daily_injection_dth", exclusive_minimum=0)
    max_withdrawal = validate.field_number(body, "max_daily_withdrawal_dth", exclusive_minimum=0)
    term_start = validate.field_date(body, "term_start_date")
    term_end = validate.field_date(body, "term_end_date")
    if term_end < term_start:
        raise bad_request("term_end_date must fall on or after term_start_date.")
    commodity_rate = validate.field_number(body, "commodity_rate_usd_per_dth",
                                           exclusive_minimum=0)
    index_price = validate.field_number(body, "index_price_usd_per_dth", exclusive_minimum=0)
    cash_out_method = validate.field_enum(body, "cash_out_method", config.CASH_OUT_METHODS)

    shipper = validate.resolve_body_fk("Shipper", shipper_id)
    field = validate.resolve_body_fk("StorageField", field_id)

    for existing in store.contracts.values():
        if existing["contract_code"] == contract_code:
            raise ApiError("ERR_DUPLICATE_CONTRACT_CODE",
                           "contract_code %s already exists." % contract_code)

    contract = store.new_record()
    contract.update({
        "shipper_id": shipper["id"],
        "storage_field_id": field["id"],
        "contract_code": contract_code,
        "service_class": service_class,
        "max_storage_quantity_dth": max_storage,
        "max_daily_injection_dth": max_injection,
        "max_daily_withdrawal_dth": max_withdrawal,
        "term_start_date": term_start.isoformat(),
        "term_end_date": term_end.isoformat(),
        "commodity_rate_usd_per_dth": commodity_rate,
        "index_price_usd_per_dth": index_price,
        "cash_out_method": cash_out_method,
        "status": "DRAFT",
        "inventory_balance_dth": D("0.000"),
        "scheduled_injection_dth": 0,
        "scheduled_withdrawal_dth": 0,
        "imbalance_dth": D("0.000"),
        "cash_out_amount_usd": D("0.00"),
        "cash_out_through_date": None,
        "activated_at": None,
        "_cash_outs": [],
    })
    store.put("StorageContract", contract)
    return envelope.created(serialize.contract(contract))


@bp.get("/storage-contracts")
def list_contracts():
    user_id, role = auth.require(config.COMMERCIAL_READ_ROLES)
    limit, offset = validate.pagination()
    shipper_id = validate.query_id("shipper_id")
    field_id = validate.query_id("storage_field_id")
    status = validate.query_enum("status", config.CONTRACT_STATUSES)
    service_class = validate.query_enum("service_class", config.SERVICE_CLASSES)

    rows = store.values("StorageContract")
    visible = auth.visible_contract_ids(user_id, role)
    if visible is not None:
        rows = [row for row in rows if row["id"] in visible]
    rows = filter_eq(rows, "shipper_id", shipper_id)
    rows = filter_eq(rows, "storage_field_id", field_id)
    rows = filter_eq(rows, "status", status)
    rows = filter_eq(rows, "service_class", service_class)
    return list_result(rows, serialize.contract, limit, offset)


@bp.get("/storage-contracts/<contract_id>")
def read_contract(contract_id):
    user_id, role = auth.require(config.COMMERCIAL_READ_ROLES)
    contract = validate.resolve_path("StorageContract", contract_id)
    auth.check_contract_ownership(contract, user_id, role)
    return envelope.object_response(serialize.contract(contract))


@bp.post("/storage-contracts/<contract_id>/activate")
def activate_contract(contract_id):
    auth.require([config.ROLE_SCHEDULING_COORDINATOR])
    validate.json_body(required=False)
    contract = validate.resolve_path("StorageContract", contract_id)

    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CONTRACT_STATE",
                       "only a DRAFT contract may be activated.")
    field = store.storage_fields[contract["storage_field_id"]]
    if field["field_posture"] == "FROZEN":
        raise ApiError("ERR_FIELD_FROZEN", "no contract may be activated on a frozen field.")
    shipper = store.shippers[contract["shipper_id"]]
    if shipper["credit_status"] != "GOOD":
        raise ApiError("ERR_SHIPPER_CREDIT_SUSPENDED", "the shipper's credit is suspended.")

    contract["status"] = "ACTIVE"
    contract["activated_at"] = store.now()
    store.touch(contract)
    return envelope.object_response(serialize.contract(contract))


@bp.post("/storage-contracts/<contract_id>/cash-out")
def cash_out(contract_id):
    auth.require([config.ROLE_SCHEDULING_COORDINATOR])
    body = validate.json_body()
    period_start = validate.field_date(body, "period_start_date")
    period_end = validate.field_date(body, "period_end_date")
    if period_end < period_start:
        raise bad_request("period_end_date must fall on or after period_start_date.")
    contract = validate.resolve_path("StorageContract", contract_id)

    through = contract["cash_out_through_date"]
    if through is not None and period_start.isoformat() <= through:
        raise ApiError("ERR_CASH_OUT_PERIOD_SETTLED",
                       "period_start_date must fall strictly after cash_out_through_date.")
    entries = engine.cash_out_scope(contract, period_start.isoformat(), period_end.isoformat())
    if not entries:
        raise ApiError("ERR_NOTHING_TO_CASH_OUT",
                       "no daily imbalance entries fall inside the requested period.")

    amount = engine.imbalance_cash_out(contract, entries)
    ledger_entry = engine.add_ledger(contract, "CASH_OUT", None, D(0), amount,
                                     "cash out %s..%s" % (period_start.isoformat(),
                                                          period_end.isoformat()))
    contract["_cash_outs"].append({
        "entry_id": ledger_entry["id"],
        "amount_usd": amount,
        "prior_through": through,
        "reversed": False,
    })
    contract["cash_out_amount_usd"] = amount
    contract["cash_out_through_date"] = period_end.isoformat()
    contract["imbalance_dth"] = D("0.000")
    engine.reconcile_contract(contract, force_touch=True)

    shipper = store.shippers[contract["shipper_id"]]
    engine.reconcile_shipper(shipper)
    return envelope.object_response(serialize.contract(contract))


@bp.post("/storage-contracts/<contract_id>/cash-out-reversal")
def cash_out_reversal(contract_id):
    auth.require([config.ROLE_SCHEDULING_COORDINATOR])
    body = validate.json_body()
    reason = validate.field_str(body, "reason")
    contract = validate.resolve_path("StorageContract", contract_id)

    pending = [record for record in contract["_cash_outs"] if not record["reversed"]]
    if not pending:
        raise ApiError("ERR_NOTHING_TO_CASH_OUT",
                       "this contract carries no unreversed cash-out.")
    settlement = pending[-1]
    settlement["reversed"] = True

    engine.add_ledger(contract, "CASH_OUT_REVERSAL", None, D(0),
                      -D(settlement["amount_usd"]),
                      "cash out reversal: %s" % reason)
    contract["cash_out_amount_usd"] = D("0.00")
    contract["cash_out_through_date"] = settlement["prior_through"]
    engine.reconcile_contract(contract, force_touch=True)

    shipper = store.shippers[contract["shipper_id"]]
    engine.reconcile_shipper(shipper)
    return envelope.object_response(serialize.contract(contract))


@bp.get("/storage-contracts/<contract_id>/imbalance-ledger-entries")
def list_ledger(contract_id):
    user_id, role = auth.require(config.COMMERCIAL_READ_ROLES)
    limit, offset = validate.pagination()
    entry_type = validate.query_enum("entry_type", config.LEDGER_ENTRY_TYPES)
    gas_day = validate.query_date("gas_day")
    contract = validate.resolve_path("StorageContract", contract_id)
    auth.check_contract_ownership(contract, user_id, role)

    rows = store.ledger_of_contract(contract["id"])
    rows = filter_eq(rows, "entry_type", entry_type)
    rows = filter_eq(rows, "gas_day", gas_day)
    return list_result(rows, serialize.ledger_entry, limit, offset)
