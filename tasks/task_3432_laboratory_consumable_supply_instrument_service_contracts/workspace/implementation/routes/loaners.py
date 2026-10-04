"""Loaner unit endpoints: register and list (PRD 3.5)."""
import uuid

from flask import Blueprint, request

import db as dbmod
import domain as D
from errors import ApiError
from middleware import authenticate, get_body
from response import paginate, success

bp = Blueprint("loaners", __name__)


@bp.post("/lab/loaner-units")
def create_loaner_unit():
    authenticate({"ServiceDispatcher", "PlatformAdmin"})
    body = get_body()
    model = body.get("model")
    serial = body.get("serial_number")
    if not isinstance(model, str) or not model.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "model is required")
    if not isinstance(serial, str) or not serial.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "serial_number is required")
    now = dbmod.now()
    unit = {
        "id": str(uuid.uuid4()),
        "model": model,
        "serial_number": serial,
        "status": "AVAILABLE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": dbmod.store.next_seq(),
    }
    with dbmod.store.lock:
        dbmod.store.loaner_units[unit["id"]] = unit
    return success(D.loaner_unit_json(unit), code=201)


@bp.get("/lab/loaner-units")
def list_loaner_units():
    authenticate({"ServiceDispatcher", "AccountManager", "PlatformAdmin"})
    items = list(dbmod.store.loaner_units.values())
    f_status = request.args.get("status")
    if f_status is not None:
        items = [u for u in items if u["status"] == f_status]
    f_model = request.args.get("model")
    if f_model is not None:
        items = [u for u in items if u["model"] == f_model]
    items = D.created_sorted(items)
    page, meta = paginate(items)
    return success(
        [D.loaner_unit_json(u) for u in page], response_type="array", pagination=meta
    )
