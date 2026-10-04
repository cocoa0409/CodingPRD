"""Client registry endpoints."""

from flask import Blueprint

import db
from auth import STAFF_ROLES, require_ownership, require_roles
from envelope import ok
from errors import ERR_CLIENT_NOT_FOUND
from validation import body_json, opt_str, reject_unknown, req_str

bp = Blueprint("clients", __name__)


@bp.post("/clients")
def create_client():
    require_roles("IntakeSpecialist")
    body = body_json()
    reject_unknown(body, {"full_name", "inmate_number", "facility_name"})
    client = db.new_entity()
    client.update({
        "full_name": req_str(body, "full_name"),
        "inmate_number": req_str(body, "inmate_number"),
        "facility_name": opt_str(body, "facility_name"),
    })
    db.clients[client["id"]] = client
    return ok(client, 201)


@bp.get("/clients/<cid>")
def get_client(cid):
    uid, role = require_roles(*STAFF_ROLES, "Client")
    client = db.lookup(db.clients, cid, ERR_CLIENT_NOT_FOUND)
    if role == "Client":
        require_ownership(client["id"] == uid)
    return ok(client)
