"""Loaner coverage and rental billing (PRD 3.6)."""
from __future__ import annotations

from flask import Blueprint

import calc
import services
import util
import validate as v
from auth import authenticate, own_loaner, own_work_order_id
from common import respond, respond_list
from errors import ApiError, bad_request
from store import store

bp = Blueprint("loaners", __name__)

LOANER_STATUSES = ("DEPLOYED", "RETURNED", "CANCELLED")
SOURCES = ("POOL", "RENTAL")


def _occupied(unit_id, start_dt, end_dt):
    """Half-open occupancy test (PRD 3.6). Touching endpoints do NOT overlap."""
    for assignment in store.all("LoanerAssignment"):
        if assignment.get("loaner_device_id") != unit_id:
            continue
        if assignment["status"] not in ("DEPLOYED", "RETURNED"):
            continue
        occ_start = util.parse_dt(assignment["start_at"])
        occ_end = util.parse_dt(assignment["returned_at"] or assignment["end_at"])
        if start_dt < occ_end and occ_start < end_dt:
            return True
    return False


def _eligible_pool_unit(candidate, downed_device, model_of_downed, start_dt, end_dt):
    if candidate["facility_id"] != downed_device["facility_id"]:
        return False
    if candidate["device_model_id"] != downed_device["device_model_id"]:
        return False
    if not candidate["is_loaner_pool"]:
        return False
    if candidate["operational_state"] != "IN_SERVICE":
        return False
    if candidate["recall_hold"]:
        return False
    if candidate["security_state"] in ("VULNERABLE", "QUARANTINED"):
        return False
    if model_of_downed is not None and model_of_downed.get("is_network_connected"):
        if candidate["security_state"] not in ("ASSESSED_OK", "REMEDIATED"):
            return False
    if candidate["id"] == downed_device["id"]:
        return False
    if _occupied(candidate["id"], start_dt, end_dt):
        return False
    return True


@bp.post("/loaner-assignments")
def create_loaner():
    authenticate(["CEManager", "BiomedTech", "DeptSteward"])
    own_work_order_id(v.raw_body().get("work_order_id"))
    payload = v.body(
        required=("work_order_id", "source", "start_at", "end_at",
                  "expected_work_order_version"),
        optional=("loaner_device_id",),
    )
    work_order_id = v.req_id(payload, "work_order_id")
    source = v.req_enum(payload, "source", SOURCES)
    start_at, start_dt = v.req_dt(payload, "start_at")
    end_at, end_dt = v.req_dt(payload, "end_at")
    expected_version = v.req_int(payload, "expected_work_order_version")
    loaner_device_id = v.opt_id(payload, "loaner_device_id")
    if not end_dt > start_dt:
        raise bad_request("end_at must be strictly after start_at.")

    work_order = store.require("WorkOrder", work_order_id)
    named_unit = store.require("Device", loaner_device_id) if loaner_device_id else None

    if work_order["version"] != expected_version:
        raise ApiError("ERR_STALE_WORK_ORDER_VERSION",
                       "expected_work_order_version does not match the work order's version.")

    downed_device = store.require("Device", work_order["device_id"])
    if downed_device["operational_state"] == "RETIRED":
        raise ApiError("ERR_DEVICE_RETIRED", "A retired unit may not be covered by a loaner.")
    if downed_device["security_state"] == "QUARANTINED":
        raise ApiError("ERR_DEVICE_QUARANTINED", "The unit under service is quarantined.")
    if named_unit is not None and named_unit["security_state"] in ("VULNERABLE", "QUARANTINED"):
        raise ApiError("ERR_DEVICE_QUARANTINED",
                       "The named loaner unit is cyber-excluded from lending.")

    downed_model = services.model_of(downed_device)

    if named_unit is not None:
        if source == "RENTAL":
            raise ApiError("ERR_LOANER_NOT_IN_POOL",
                           "A RENTAL assignment may not name a loaner_device_id.")
        if (not named_unit["is_loaner_pool"]
                or named_unit["facility_id"] != downed_device["facility_id"]
                or named_unit["device_model_id"] != downed_device["device_model_id"]):
            raise ApiError("ERR_LOANER_NOT_IN_POOL",
                           "The named unit is not an eligible pool unit for this repair.")
        named_model = services.model_of(named_unit)
        if named_model is not None and named_model.get("is_network_connected"):
            if named_unit["security_state"] not in ("ASSESSED_OK", "REMEDIATED"):
                raise ApiError("ERR_LOANER_SECURITY_INELIGIBLE",
                               "A network-connected loaner unit must be ASSESSED_OK or REMEDIATED.")
        if named_unit["operational_state"] != "IN_SERVICE" or named_unit["recall_hold"]:
            raise ApiError("ERR_LOANER_UNAVAILABLE", "The named loaner unit is not available.")
        if _occupied(named_unit["id"], start_dt, end_dt):
            raise ApiError("ERR_LOANER_INTERVAL_CONFLICT",
                           "The named loaner unit is occupied across the requested interval.")

    selected = named_unit
    if source == "POOL" and named_unit is None:
        candidates = [
            d for d in store.all("Device")
            if _eligible_pool_unit(d, downed_device, downed_model, start_dt, end_dt)
        ]
        if not candidates:
            raise ApiError("ERR_NO_LOANER_AVAILABLE",
                           "No eligible pool unit is available for the requested interval.")
        candidates.sort(key=lambda d: (d["condition_score"], d["utilization_hours"],
                                       d["created_at"], d["_seq"]))
        selected = candidates[0]

    department = services.department_of(downed_device)
    if department is not None and department["budget_state"] == "ON_HOLD":
        raise ApiError("ERR_DEPARTMENT_BUDGET_ON_HOLD",
                       "The owning department has reached its downtime budget ceiling.")

    record = store.new_record("LoanerAssignment", {
        "work_order_id": work_order_id,
        "loaner_device_id": selected["id"] if (source == "POOL" and selected) else None,
        "source": source,
        "start_at": start_at,
        "end_at": end_at,
        "returned_at": None,
        "status": "DEPLOYED",
        "billable_days": 0,
        "rental_cost_cents": 0,
    })
    work_order["loaner_status"] = "COVERED"
    store.touch(work_order)
    if source == "POOL" and selected is not None:
        selected["operational_state"] = "ON_LOAN"
        store.touch(selected)
    return respond(record, 201)


@bp.get("/loaner-assignments/<lid>")
def read_loaner(lid):
    authenticate(["CEManager", "BiomedTech", "DeptSteward"])
    own_loaner(store.get("LoanerAssignment", lid))
    return respond(store.require("LoanerAssignment", lid))


@bp.get("/loaner-assignments")
def list_loaners():
    authenticate(["CEManager", "BiomedTech", "DeptSteward"])
    limit, offset = v.pagination()
    loaner_device_id = v.query_str("loaner_device_id")
    work_order_id = v.query_str("work_order_id")
    status = v.query_enum("status", LOANER_STATUSES)
    records = store.ordered([
        a for a in store.all("LoanerAssignment")
        if (loaner_device_id is None or a.get("loaner_device_id") == loaner_device_id)
        and (work_order_id is None or a["work_order_id"] == work_order_id)
        and (status is None or a["status"] == status)
    ])
    return respond_list(records, limit, offset)


@bp.post("/loaner-assignments/<lid>/return")
def return_loaner(lid):
    authenticate(["CEManager", "BiomedTech", "DeptSteward"])
    own_loaner(store.get("LoanerAssignment", lid))
    assignment = store.require("LoanerAssignment", lid)
    v.body()
    if assignment["status"] != "DEPLOYED":
        raise ApiError("ERR_INVALID_LOANER_STATE",
                       "Only a DEPLOYED loaner assignment may be returned.")

    assignment["returned_at"] = store.now_iso()
    billable_days = calc.loaner_billable_days(
        util.parse_dt(assignment["start_at"]), util.parse_dt(assignment["returned_at"])
    )
    assignment["billable_days"] = billable_days
    risk_class = "LOW"
    work_order = store.get("WorkOrder", assignment["work_order_id"])
    if work_order is not None:
        downed = store.get("Device", work_order["device_id"])
        if downed is not None:
            risk_class = downed["risk_class"]
    assignment["rental_cost_cents"] = calc.loaner_rental_cost(
        assignment["source"], billable_days, risk_class
    )
    assignment["status"] = "RETURNED"
    store.touch(assignment)

    if assignment["source"] == "POOL" and assignment.get("loaner_device_id"):
        unit = store.get("Device", assignment["loaner_device_id"])
        if unit is not None and unit["operational_state"] == "ON_LOAN":
            unit["operational_state"] = "IN_SERVICE"
            store.touch(unit)
    return respond(assignment)
