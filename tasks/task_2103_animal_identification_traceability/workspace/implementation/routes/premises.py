"""Premises registration and approval (PRD 3.1)."""
from flask import Blueprint

import derive
import shape
from authz import (HARVEST_OPERATOR, PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL,
                   SUPPLIER_REP, TRACE_ANALYST, require_owner, require_roles)
from db import base_record, store, touch
from errors import conflict, invalid_state
from respond import success
from routes._common import page, premises_or_404, producer_or_404
from serialize import public

bp = Blueprint("premises", __name__)

OPERATION_TYPES = ("COW_CALF", "FEEDLOT", "MARKET", "HARVEST_FACILITY")


@bp.post("/premises")
def create_premises():
    uid, role = require_roles(PRODUCER)
    body = shape.body()
    producer_id = shape.s_str(body, "producer_id")
    pin = shape.s_str(body, "pin", pattern=shape.PIN_RE)
    operation_type = shape.s_enum(body, "operation_type", OPERATION_TYPES)
    state_code = shape.s_str(body, "state_code", pattern=shape.STATE_CODE_RE)
    capacity = shape.s_int(body, "capacity", minimum=1)
    # Band 5 - body FK existence.
    producer = producer_or_404(producer_id)
    # Band 6 - a producer registers only its own premises.
    require_owner(uid == producer["id"])
    # Band 15 - the PIN is globally unique.
    if any(p["pin"] == pin for p in store.premises.values()):
        raise conflict("ERR_DUPLICATE_PIN", "Another premises already uses this pin")

    rec = base_record()
    rec.update({
        "producer_id": producer["id"],
        "pin": pin,
        "operation_type": operation_type,
        "state_code": state_code,
        "capacity": capacity,
        "registration_status": "PENDING_REVIEW",
        "health_status": "CLEAR",
        "animal_count": 0,
        "pending_hold_count": 0,
        "last_hold_released_at": None,
        "last_reconciliation_run_at": None,
    })
    store.premises[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/premises/<premises_id>")
def read_premises(premises_id):
    require_roles(PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, TRACE_ANALYST,
                  HARVEST_OPERATOR, SUPPLIER_REP)
    return success(public(premises_or_404(premises_id)))


@bp.get("/premises")
def list_premises():
    require_roles(PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL)
    limit, offset = shape.pagination_params()
    rows = list(store.premises.values())
    for field in ("producer_id", "state_code", "operation_type",
                  "registration_status", "health_status"):
        value = shape.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return page(rows, limit, offset)


@bp.post("/premises/<premises_id>/approve")
def approve_premises(premises_id):
    require_roles(STATE_OFFICIAL)
    premises = premises_or_404(premises_id)
    if premises["registration_status"] != "PENDING_REVIEW":
        raise invalid_state("Premises registration is not PENDING_REVIEW")
    premises["registration_status"] = "ACTIVE"
    touch(premises)
    derive.mark_producer(premises["producer_id"])
    return success(public(premises))


@bp.get("/premises/<premises_id>/reconciliation-runs")
def list_premises_runs(premises_id):
    require_roles(PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL)
    limit, offset = shape.pagination_params()
    premises = premises_or_404(premises_id)
    rows = [r for r in store.recon_runs.values() if r["premises_id"] == premises["id"]]
    status = shape.q("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, limit, offset)
