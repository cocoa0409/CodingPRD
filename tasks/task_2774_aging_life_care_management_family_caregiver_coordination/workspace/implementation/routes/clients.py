"""Client intake, capacity determination, discharge and the retainer ledger."""
from flask import Blueprint

import auth
import derive
import envelope
import lookup
import serialize
import validators as v
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("clients", __name__)

RESIDENCE_SETTINGS = ("PRIVATE_HOME", "ASSISTED_LIVING", "SKILLED_NURSING",
                      "HOSPITAL")
CLIENT_STATUSES = ("PROSPECT", "ASSESSMENT_IN_PROGRESS", "ACTIVE_CARE",
                   "SUSPENDED_NONPAYMENT", "DISCHARGED")
CAPACITY_STATUSES = ("PRESUMED_CAPABLE", "DIMINISHED_DOCUMENTED",
                     "ADJUDICATED_INCAPACITATED")

FILTER_SPEC = {
    "status": "status",
    "risk_posture": lambda rec: derive.risk_posture(rec),
}


@bp.route("/care/clients", methods=["POST"])
def create_client():
    auth.actor_for(auth.ROLE_ADMIN)
    body = v.json_body()
    full_name = v.req_str(body, "full_name", 1, 120)
    residence_setting = v.req_enum(body, "residence_setting", RESIDENCE_SETTINGS)
    billing_increment_min = v.opt_int_in(body, "billing_increment_min", (6, 15), 15)
    travel_billing_pct = v.opt_int(body, "travel_billing_pct", 50, 0, 100)
    retainer_floor_cents = v.opt_int(body, "retainer_floor_cents", 50000, 0, None)
    concurrent = v.opt_int(body, "authorized_concurrent_caregivers", 2, 1, None)
    record = new_record({
        "full_name": full_name,
        "residence_setting": residence_setting,
        "status": "PROSPECT",
        "capacity_status": "PRESUMED_CAPABLE",
        "capacity_basis": None,
        "billing_increment_min": billing_increment_min,
        "travel_billing_pct": travel_billing_pct,
        "retainer_floor_cents": retainer_floor_cents,
        "authorized_concurrent_caregivers": concurrent,
    })
    db.clients[record["id"]] = record
    return envelope.created(serialize.client(record))


@bp.route("/care/clients", methods=["GET"])
def list_clients():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.clients.values())
    if scope is not None:
        records = [r for r in records if r["id"] == scope]
    records = lookup.filter_records(records, FILTER_SPEC,
                                    v.filters(FILTER_SPEC.keys()))
    records = ordered(records, descending=True)
    return envelope.page([serialize.client(r) for r in records], limit, offset)


@bp.route("/care/clients/<client_id>", methods=["GET"])
def read_client(client_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_client(client_id)
    auth.family_read_guard(actor, record["id"])
    return envelope.ok(serialize.client(record))


@bp.route("/care/clients/<client_id>/state", methods=["PATCH"])
def client_state(client_id):
    actor = auth.actor_for(auth.ROLE_ADMIN, auth.ROLE_SUPERVISOR)
    body = v.json_body()
    to_state = v.req_enum(body, "to_state", CLIENT_STATUSES)
    v.opt_str(body, "reason")
    client = lookup.need_client(client_id)
    auth.resolve_supervisor(actor)
    if to_state == "DISCHARGED":
        if client["status"] == "DISCHARGED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "DISCHARGED is terminal.")
        if client["status"] in ("ASSESSMENT_IN_PROGRESS", "ACTIVE_CARE",
                               "SUSPENDED_NONPAYMENT"):
            for episode in db.episodes.values():
                if episode["client_id"] == client["id"] and \
                        episode["status"] in ("OPEN", "TRANSITION_OVERSIGHT"):
                    raise ApiError(
                        "ERR_INVALID_STATE_TRANSITION",
                        "The practice does not discharge a client while a crisis "
                        "episode is still active.")
        client["status"] = "DISCHARGED"
        derive.discharge_cascade(client)
    elif to_state == "ACTIVE_CARE":
        if client["status"] != "SUSPENDED_NONPAYMENT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "ACTIVE_CARE is only reachable from "
                           "SUSPENDED_NONPAYMENT on request.")
        if not derive.restore_client_from_nonpayment(client):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The recomputed retainer balance has not reached the "
                           "client's floor.")
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s may not be requested directly." % to_state)
    touch(client)
    return envelope.ok(serialize.client(client))


@bp.route("/care/clients/<client_id>/capacity-determination", methods=["POST"])
def capacity_determination(client_id):
    auth.actor_for(auth.ROLE_CARE_MANAGER, auth.ROLE_SUPERVISOR)
    body = v.json_body()
    capacity_status = v.req_enum(body, "capacity_status", CAPACITY_STATUSES)
    basis = v.req_str(body, "basis", 1, None)
    client = lookup.need_client(client_id)
    client["capacity_status"] = capacity_status
    client["capacity_basis"] = None if capacity_status == "PRESUMED_CAPABLE" \
        else basis
    touch(client)
    return envelope.ok(serialize.client(client))


@bp.route("/care/clients/<client_id>/retainer-deposits", methods=["POST"])
def retainer_deposit(client_id):
    auth.actor_for(auth.ROLE_BILLING)
    body = v.json_body()
    amount_cents = v.req_int(body, "amount_cents", 1, None)
    received_at = v.req_dt(body, "received_at")
    client = lookup.need_client(client_id)
    db.deposits.append({
        "client_id": client["id"],
        "amount_cents": amount_cents,
        "received_at": received_at,
    })
    derive.restore_client_from_nonpayment(client)
    touch(client)
    return envelope.ok(serialize.client(client))
