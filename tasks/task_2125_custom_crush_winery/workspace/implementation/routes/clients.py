"""Client registration, reads and the account lifecycle."""

import re

from flask import Blueprint

import domain
from auth import ALL_ROLES, FACILITY_ADMIN, guard, scope
from decimal import Decimal
from envelope import respond
from errors import (
    ApiError,
    ERR_CLIENT_HAS_BONDED_INVENTORY,
    ERR_DUPLICATE_PERMIT_NUMBER,
)
from helpers import declared, run_list
from store import db, new_entity, touch
from validation import v_enum, v_string

bp = Blueprint("clients", __name__)

PERMIT_PATTERN = re.compile(r"^BW-CA-[0-9]{5}$")
CLIENT_ACTIONS = {
    "SUSPEND": [FACILITY_ADMIN],
    "REINSTATE": [FACILITY_ADMIN],
    "CLOSE": [FACILITY_ADMIN],
}


@bp.route("/clients", methods=["POST"])
def create_client():
    ctx = guard([FACILITY_ADMIN])
    body = ctx.body
    name = v_string(body, "name")
    permit = v_string(body, "ttb_permit_number", pattern=PERMIT_PATTERN)
    email = v_string(body, "contact_email")

    # Rung 62 -- uniqueness.
    for existing in db.clients.values():
        if existing["ttb_permit_number"] == permit:
            raise ApiError(ERR_DUPLICATE_PERMIT_NUMBER,
                           "TTB permit number '%s' is already held." % permit)

    client = new_entity({
        "name": name,
        "ttb_permit_number": permit,
        "contact_email": email,
        "status": "ACTIVE",
        "bond_gallons_in_bond": Decimal(0),
        "taxpaid_gallons_ytd": Decimal(0),
        "last_filed_period_end": None,
    })
    db.clients[client["id"]] = client
    return respond(domain.serialize_client(client), 201)


@bp.route("/clients/<client_id>", methods=["GET"])
def read_client(client_id):
    ctx = guard(ALL_ROLES, read_body=False)
    client = domain.get_client(client_id)
    scope(ctx, client["id"])
    return respond(domain.serialize_client(client))


@bp.route("/clients", methods=["GET"])
def list_clients():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.clients.values(), ctx, domain.serialize_client,
                    owner_fn=lambda c: c["id"], filters=(("status", "status"),))


@bp.route("/clients/<client_id>/status", methods=["POST"])
def client_status(client_id):
    ctx = guard([FACILITY_ADMIN], CLIENT_ACTIONS)
    action = v_enum(ctx.body, "action", set(CLIENT_ACTIONS))
    client = domain.get_client(client_id)

    # Rung 30 -- declared transition.
    if action == "SUSPEND":
        declared(client["status"] == "ACTIVE")
        _suspend(client)
    elif action == "REINSTATE":
        declared(client["status"] == "SUSPENDED")
        _reinstate(client)
    else:
        declared(client["status"] in ("ACTIVE", "SUSPENDED"))
        _close(client)
    return respond(domain.serialize_client(client))


def _suspend(client):
    client["status"] = "SUSPENDED"
    touch(client)
    # HOP 1 -- every ACTIVE contract of this client moves to SUSPENDED.
    hop1 = []
    for contract in domain.client_contracts(client["id"]):
        if contract["status"] == "ACTIVE":
            contract["status"] = "SUSPENDED"
            touch(contract)
            hop1.append(contract)
    # HOP 2 -- each such contract cancels its own RESERVED allocations.
    for contract in hop1:
        cancelled = False
        for allocation in domain.contract_allocations(contract["id"]):
            if allocation["status"] == "RESERVED":
                allocation["status"] = "CANCELLED"
                touch(allocation)
                cancelled = True
        # HOP 3 -- recompute the counters from the survivors, version again.
        if cancelled:
            domain.recompute_contract_counters_and_touch(contract)


def _reinstate(client):
    client["status"] = "ACTIVE"
    touch(client)
    for contract in domain.client_contracts(client["id"]):
        if contract["status"] == "SUSPENDED":
            contract["status"] = "ACTIVE"
            touch(contract)


def _close(client):
    # Rung 85 -- terminal safety gate.
    for lot in domain.client_lots(client["id"]):
        if lot["bond_status"] == "IN_BOND" and lot["volume_gallons"] > 0:
            raise ApiError(ERR_CLIENT_HAS_BONDED_INVENTORY,
                           "The client still holds wine in bond.")
    client["status"] = "CLOSED"
    touch(client)
    for contract in domain.client_contracts(client["id"]):
        if contract["status"] in ("DRAFT", "PENDING_SIGNATURE", "ACTIVE", "SUSPENDED"):
            contract["status"] = "TERMINATED"
            touch(contract)
