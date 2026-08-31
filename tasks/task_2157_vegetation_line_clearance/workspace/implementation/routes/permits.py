"""Herbicide-permit endpoints."""
from flask import Blueprint, request

import constants as C
import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, actor_id, endpoint
from errors import ApiError

bp = Blueprint("permits", __name__)


def _intersects(a, b):
    return (a.get("window_start") <= b.get("window_end")
            and b.get("window_start") <= a.get("window_end"))


@bp.post("/vm/herbicide-permits")
@endpoint(["CertifiedArborist"])
def request_permit():
    data = V.body()
    circuit = V.body_fk(data, "circuit_id", store.circuits, "ERR_CIRCUIT_NOT_FOUND")
    if circuit is None:
        V.require(data, "circuit_id")
    chemical_code = V.as_enum(data, "chemical_code", C.CHEMICAL_CODES)
    license_no = V.as_string(data, "applicator_license_no")
    buffer_ft = V.as_number(data, "buffer_ft", minimum=0)
    window_start = V.as_date(data, "window_start")
    window_end = V.as_date(data, "window_end")

    rec = store.new_record()
    rec.update({
        "circuit_id": circuit["id"],
        "chemical_code": chemical_code,
        "applicator_license_no": license_no,
        "buffer_ft": buffer_ft,
        "window_start": window_start,
        "window_end": window_end,
        "status": "REQUESTED",
        "approved_by_user_id": None,
    })
    store.herbicide_permits[rec["id"]] = rec
    return envelope.created(store.public(rec))


@bp.post("/vm/herbicide-permits/<pid>/decision")
@endpoint(["UtilityForester"])
def decide_permit(pid):
    permit = V.find(store.herbicide_permits, pid, "ERR_PERMIT_NOT_FOUND")
    data = V.body()
    outcome = V.as_enum(data, "outcome", ["APPROVE", "DENY"])
    services.require_state(permit, "herbicide_permit", ["REQUESTED"])

    if outcome == "DENY":
        permit["status"] = "DENIED"
        store.touch(permit)
        return envelope.ok(store.public(permit))

    circuit = store.circuits.get(permit.get("circuit_id"))
    prescription = services.prescription_of_circuit(circuit)
    if prescription is None or not prescription.get("herbicide_allowed"):
        raise ApiError("ERR_HERBICIDE_NOT_PRESCRIBED",
                       "the resolved prescription forbids herbicide")

    counted = [p for p in store.ordered(list(store.herbicide_permits.values()))
               if p["id"] != permit["id"]
               and p.get("circuit_id") == permit.get("circuit_id")
               and p.get("status") in ("APPROVED", "ACTIVE")]
    for other in counted:
        if other.get("chemical_code") == permit.get("chemical_code") \
                and _intersects(permit, other):
            raise ApiError("ERR_PERMIT_WINDOW_CONFLICT",
                           "an approved permit with the same chemical overlaps")
    overlapping = [p for p in counted if _intersects(permit, p)]
    for i in range(len(overlapping)):
        for j in range(i + 1, len(overlapping)):
            if _intersects(overlapping[i], overlapping[j]):
                raise ApiError("ERR_PERMIT_WINDOW_CONFLICT",
                               "approval would create a third mutually overlapping permit")

    permit["status"] = "APPROVED"
    permit["approved_by_user_id"] = actor_id()
    store.touch(permit)
    return envelope.ok(store.public(permit))


@bp.post("/vm/herbicide-permits/<pid>/activate")
@endpoint(["CertifiedArborist"])
def activate_permit(pid):
    permit = V.find(store.herbicide_permits, pid, "ERR_PERMIT_NOT_FOUND")
    services.require_state(permit, "herbicide_permit", ["APPROVED"])
    today = store.today_str()
    if not (permit.get("window_start") <= today <= permit.get("window_end")):
        raise ApiError("ERR_PERMIT_WINDOW_NOT_OPEN",
                       "the logical clock date is outside the permit window")
    permit["status"] = "ACTIVE"
    store.touch(permit)
    return envelope.ok(store.public(permit))


@bp.post("/vm/herbicide-permits/<pid>/revoke")
@endpoint(["UtilityForester"])
def revoke_permit(pid):
    permit = V.find(store.herbicide_permits, pid, "ERR_PERMIT_NOT_FOUND")
    services.require_state(permit, "herbicide_permit", ["APPROVED", "ACTIVE"])
    permit["status"] = "REVOKED"
    store.touch(permit)
    return envelope.ok(store.public(permit))


@bp.get("/vm/herbicide-permits/<pid>")
@endpoint(ALL_ROLES)
def get_permit(pid):
    return envelope.ok(store.public(
        V.find(store.herbicide_permits, pid, "ERR_PERMIT_NOT_FOUND")))


@bp.get("/vm/herbicide-permits")
@endpoint(ALL_ROLES)
def list_permits():
    return envelope.list_response(list(store.herbicide_permits.values()), {
        "circuit_id": request.args.get("circuit_id"),
        "status": request.args.get("status"),
        "chemical_code": request.args.get("chemical_code"),
    })
