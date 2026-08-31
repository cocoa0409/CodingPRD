"""Device inventory and the cyber dimension of the device state machine."""
from __future__ import annotations

from flask import Blueprint

import services
import validate as v
from auth import authenticate, own_device
from common import respond, respond_list
from errors import ApiError
from store import store

bp = Blueprint("devices", __name__)

OPERATIONAL_STATES = ("IN_SERVICE", "DOWN", "ON_LOAN", "RETIRED")
SECURITY_STATES = ("UNASSESSED", "ASSESSED_OK", "VULNERABLE", "QUARANTINED", "REMEDIATED")
RISK_CLASSES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

SECURITY_TRANSITIONS = {
    "UNASSESSED": ("ASSESSED_OK", "VULNERABLE"),
    "ASSESSED_OK": ("VULNERABLE",),
    "VULNERABLE": ("QUARANTINED", "REMEDIATED"),
    "QUARANTINED": ("REMEDIATED",),
    "REMEDIATED": ("ASSESSED_OK",),
}


@bp.post("/devices")
def create_device():
    authenticate(["CEManager"])
    payload = v.body(
        required=("facility_id", "department_id", "device_model_id", "serial_number",
                  "acquisition_date", "acquisition_cost_cents", "function_code",
                  "physical_risk_code", "maintenance_requirement_code"),
        optional=("lot_number", "condition_score", "utilization_hours", "is_loaner_pool"),
    )
    facility_id = v.req_id(payload, "facility_id")
    department_id = v.req_id(payload, "department_id")
    model_id = v.req_id(payload, "device_model_id")
    serial_number = v.req_str(payload, "serial_number")
    acquisition_date, _ = v.req_date(payload, "acquisition_date")
    acquisition_cost = v.req_int(payload, "acquisition_cost_cents", minimum=0)
    function_code = v.req_int(payload, "function_code", minimum=1, maximum=10)
    physical_risk_code = v.req_int(payload, "physical_risk_code", minimum=1, maximum=5)
    maintenance_code = v.req_int(payload, "maintenance_requirement_code", minimum=1, maximum=5)
    lot_number = v.opt_str(payload, "lot_number")
    condition_score = v.opt_int(payload, "condition_score", 1, minimum=1, maximum=5)
    utilization_hours = v.opt_int(payload, "utilization_hours", 0, minimum=0)
    is_loaner_pool = v.opt_bool(payload, "is_loaner_pool", False)

    store.require("Facility", facility_id)
    store.require("Department", department_id)
    store.require("DeviceModel", model_id)

    record = store.new_record("Device", {
        "facility_id": facility_id,
        "department_id": department_id,
        "device_model_id": model_id,
        "serial_number": serial_number,
        "lot_number": lot_number,
        "acquisition_date": acquisition_date,
        "acquisition_cost_cents": acquisition_cost,
        "function_code": function_code,
        "physical_risk_code": physical_risk_code,
        "maintenance_requirement_code": maintenance_code,
        "condition_score": condition_score,
        "utilization_hours": utilization_hours,
        "is_loaner_pool": is_loaner_pool,
        "risk_score": 0,
        "risk_class": "LOW",
        "pm_interval_days": 365,
        "operational_state": "IN_SERVICE",
        "security_state": "UNASSESSED",
        "recall_hold": False,
        "lifetime_maintenance_cost_cents": 0,
        "replacement_priority_score": 0.00,
        "plan_rank": 0,
        "plan_funded": False,
    })
    services.recompute_classification(record)
    return respond(record, 201)


@bp.get("/devices/<did>")
def read_device(did):
    authenticate(["CEManager", "BiomedTech", "SecurityOfficer", "DeptSteward"])
    device = store.get("Device", did)
    own_device(device)
    return respond(store.require("Device", did))


@bp.get("/devices")
def list_devices():
    authenticate(["CEManager", "BiomedTech", "SecurityOfficer", "DeptSteward"])
    limit, offset = v.pagination()
    facility_id = v.query_str("facility_id")
    department_id = v.query_str("department_id")
    model_id = v.query_str("device_model_id")
    operational_state = v.query_enum("operational_state", OPERATIONAL_STATES)
    security_state = v.query_enum("security_state", SECURITY_STATES)
    risk_class = v.query_enum("risk_class", RISK_CLASSES)
    is_loaner_pool = v.query_bool("is_loaner_pool")
    records = store.ordered([
        d for d in store.all("Device")
        if (facility_id is None or d["facility_id"] == facility_id)
        and (department_id is None or d["department_id"] == department_id)
        and (model_id is None or d["device_model_id"] == model_id)
        and (operational_state is None or d["operational_state"] == operational_state)
        and (security_state is None or d["security_state"] == security_state)
        and (risk_class is None or d["risk_class"] == risk_class)
        and (is_loaner_pool is None or d["is_loaner_pool"] == is_loaner_pool)
    ])
    return respond_list(records, limit, offset)


@bp.patch("/devices/<did>")
def update_device(did):
    authenticate(["CEManager", "BiomedTech"])
    device = store.require("Device", did)
    payload = v.body(optional=("condition_score", "utilization_hours", "is_loaner_pool"))
    condition_score = v.opt_int(payload, "condition_score", None, minimum=1, maximum=5)
    utilization_hours = v.opt_int(payload, "utilization_hours", None, minimum=0)
    is_loaner_pool = v.opt_bool(payload, "is_loaner_pool", None)
    if device["operational_state"] == "RETIRED":
        raise ApiError("ERR_DEVICE_RETIRED", "A retired unit may not be updated.")
    supplied = False
    if condition_score is not None:
        device["condition_score"] = condition_score
        supplied = True
    if utilization_hours is not None:
        device["utilization_hours"] = utilization_hours
        supplied = True
    if is_loaner_pool is not None:
        device["is_loaner_pool"] = is_loaner_pool
        supplied = True
    if supplied:
        services.recompute_classification(device)
    store.touch(device)
    return respond(device)


@bp.post("/devices/<did>/security-state")
def set_security_state(did):
    authenticate(["SecurityOfficer"])
    device = store.require("Device", did)
    payload = v.body(required=("to_state",), optional=("note",))
    to_state = v.req_enum(payload, "to_state", SECURITY_STATES)
    v.opt_str(payload, "note")

    current = device["security_state"]
    if to_state not in SECURITY_TRANSITIONS.get(current, ()):
        raise ApiError(
            "ERR_INVALID_SECURITY_STATE",
            "security_state %s -> %s is not a declared transition." % (current, to_state),
        )
    if to_state == "ASSESSED_OK" and services.has_open_finding(device["id"]):
        raise ApiError(
            "ERR_SECURITY_FINDING_OPEN",
            "A security finding on this device is still OPEN or REMEDIATION_SCHEDULED.",
        )

    device["security_state"] = to_state
    if to_state == "QUARANTINED":
        services.quarantine_cascade(device)
    elif to_state == "REMEDIATED" and current == "QUARANTINED":
        services.conditional_restore(device)
    store.touch(device)
    return respond(device)
