# =============================================================================
# Cardholders: POST /cardholders (Any), GET /cardholders/{id},
# GET /cardholders/{id}/devices
# =============================================================================
from flask import Blueprint

import db
from domain import sync_posture
from helpers import list_response, new_common_row, resolve_cardholder
from middleware import get_body, req_str
from response import success_object

bp = Blueprint("cardholders", __name__)


@bp.post("/cardholders")
def create_cardholder():
    # [Any] endpoint: no header check (priority 1 skipped)
    body = get_body()
    legal_name = req_str(body, "legal_name")
    email = req_str(body, "email")
    phone = req_str(body, "phone")
    row = new_common_row({
        "legal_name": legal_name,
        "email": email,
        "phone": phone,
        "status": "ACTIVE",
    })
    db.cardholders[row["id"]] = row
    return success_object(row, 201)


@bp.get("/cardholders/<cardholderId>")
def get_cardholder(cardholderId):
    row = resolve_cardholder(cardholderId)
    return success_object(row, 200)


@bp.get("/cardholders/<cardholderId>/devices")
def list_cardholder_devices(cardholderId):
    resolve_cardholder(cardholderId)
    rows = [d for d in db.devices.values() if d["cardholder_id"] == cardholderId]
    for d in rows:
        sync_posture(d)
    return list_response(rows)
