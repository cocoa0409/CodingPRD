"""Metals recovery contracts and batches."""

from flask import Blueprint, request

from auth import require_role
from db import store
from errors import err_invalid_state, err_not_found, err_invalid_request
from helpers import (body_json, new_entity, require_fields, success_list,
                     success_obj, to_decimal, to_int, touch)
from calculations import compute_metals_settlement
from serializers import metals_contract_out, metals_batch_out

bp = Blueprint("metals", __name__)

CM = ["ContractsManager"]
PO = ["PlantOperator"]
READERS = ["ContractsManager", "PlantOperator", "Regulator"]


@bp.post("/wte/metals-recovery-contracts")
def create_contract():
    require_role(CM)
    b = body_json()
    require_fields(b, ["processor_name", "ferrous_recovery_pct",
                       "nonferrous_recovery_pct", "processing_fee_cents_per_tonne"])
    name = b["processor_name"]
    if not isinstance(name, str) or not name:
        raise err_invalid_request("processor_name must be a non-empty string")
    fer = to_decimal(b["ferrous_recovery_pct"], "ferrous_recovery_pct")
    if fer <= 0 or fer > to_decimal("0.15", "x"):
        raise err_invalid_request("ferrous_recovery_pct must be > 0 and <= 0.15")
    nfer = to_decimal(b["nonferrous_recovery_pct"], "nonferrous_recovery_pct")
    if nfer <= 0 or nfer > to_decimal("0.05", "x"):
        raise err_invalid_request("nonferrous_recovery_pct must be > 0 and <= 0.05")
    fee = to_int(b["processing_fee_cents_per_tonne"], "processing_fee_cents_per_tonne")
    if fee < 0:
        raise err_invalid_request("processing_fee_cents_per_tonne must be >= 0")
    c = new_entity({
        "processor_name": name,
        "ferrous_recovery_pct": fer,
        "nonferrous_recovery_pct": nfer,
        "processing_fee_cents_per_tonne": fee,
        "status": "ACTIVE",
    })
    store.metals_contracts[c["id"]] = c
    return success_obj(metals_contract_out(c), 201)


@bp.get("/wte/metals-recovery-contracts")
def list_contracts():
    require_role(READERS)
    items = sorted(store.metals_contracts.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("status")
    if q is not None:
        items = [c for c in items if c["status"] == q]
    return success_list([metals_contract_out(c) for c in items])


@bp.get("/wte/metals-recovery-contracts/<cid>")
def get_contract(cid):
    require_role(READERS)
    c = store.metals_contracts.get(cid)
    if c is None:
        raise err_not_found("contract not found")
    return success_obj(metals_contract_out(c))


@bp.post("/wte/metals-recovery-contracts/<cid>/suspend")
def suspend_contract(cid):
    require_role(CM)
    c = store.metals_contracts.get(cid)
    if c is None:
        raise err_not_found("contract not found")
    if c["status"] != "ACTIVE":
        raise err_invalid_state("contract is not ACTIVE")
    c["status"] = "SUSPENDED"
    touch(c)
    return success_obj(metals_contract_out(c))


@bp.post("/wte/metals-recovery-contracts/<cid>/terminate")
def terminate_contract(cid):
    require_role(CM)
    c = store.metals_contracts.get(cid)
    if c is None:
        raise err_not_found("contract not found")
    if c["status"] == "TERMINATED":
        raise err_invalid_state("contract is already TERMINATED")
    c["status"] = "TERMINATED"
    touch(c)
    return success_obj(metals_contract_out(c))


@bp.post("/wte/metals-recovery-batches")
def create_batch():
    require_role(PO)
    b = body_json()
    require_fields(b, ["contract_id", "ash_input_tonnes",
                       "ferrous_price_cents_per_tonne", "nonferrous_price_cents_per_tonne"])
    c = store.metals_contracts.get(b["contract_id"])
    if c is None:
        raise err_not_found("contract not found")
    if c["status"] != "ACTIVE":
        raise err_invalid_state("contract is not ACTIVE")
    ash = to_decimal(b["ash_input_tonnes"], "ash_input_tonnes")
    if ash <= 0:
        raise err_invalid_request("ash_input_tonnes must be > 0")
    fp = to_int(b["ferrous_price_cents_per_tonne"], "ferrous_price_cents_per_tonne")
    nfp = to_int(b["nonferrous_price_cents_per_tonne"], "nonferrous_price_cents_per_tonne")
    batch = new_entity({
        "contract_id": c["id"],
        "ash_input_tonnes": ash,
        "ferrous_price_cents_per_tonne": fp,
        "nonferrous_price_cents_per_tonne": nfp,
        "status": "RECORDED",
    })
    compute_metals_settlement(batch, c)
    store.metals_batches[batch["id"]] = batch
    return success_obj(metals_batch_out(batch), 201)


@bp.get("/wte/metals-recovery-batches")
def list_batches():
    require_role(READERS)
    items = sorted(store.metals_batches.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("contract_id")
    if q is not None:
        items = [b for b in items if b["contract_id"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [b for b in items if b["status"] == q]
    return success_list([metals_batch_out(b) for b in items])


@bp.get("/wte/metals-recovery-batches/<bid>")
def get_batch(bid):
    require_role(READERS)
    b = store.metals_batches.get(bid)
    if b is None:
        raise err_not_found("batch not found")
    return success_obj(metals_batch_out(b))


@bp.post("/wte/metals-recovery-batches/<bid>/settle")
def settle_batch(bid):
    require_role(CM)
    b = store.metals_batches.get(bid)
    if b is None:
        raise err_not_found("batch not found")
    if b["status"] != "RECORDED":
        raise err_invalid_state("batch is not RECORDED")
    c = store.metals_contracts.get(b["contract_id"])
    if c is None or c["status"] != "ACTIVE":
        raise err_invalid_state("contract is not ACTIVE")
    b["status"] = "SETTLED"
    touch(b)
    return success_obj(metals_batch_out(b))


@bp.post("/wte/metals-recovery-batches/<bid>/dispute")
def dispute_batch(bid):
    require_role(CM)
    b = store.metals_batches.get(bid)
    if b is None:
        raise err_not_found("batch not found")
    if b["status"] != "RECORDED":
        raise err_invalid_state("batch is not RECORDED")
    b["status"] = "DISPUTED"
    touch(b)
    return success_obj(metals_batch_out(b))


@bp.post("/wte/metals-recovery-batches/<bid>/resolve")
def resolve_batch(bid):
    require_role(CM)
    b = store.metals_batches.get(bid)
    if b is None:
        raise err_not_found("batch not found")
    if b["status"] != "DISPUTED":
        raise err_invalid_state("batch is not DISPUTED")
    c = store.metals_contracts.get(b["contract_id"])
    if c is not None:
        compute_metals_settlement(b, c)
    b["status"] = "RECORDED"
    touch(b)
    return success_obj(metals_batch_out(b))
