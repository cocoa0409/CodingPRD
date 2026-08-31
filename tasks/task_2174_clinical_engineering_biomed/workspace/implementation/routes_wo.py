"""Corrective work orders: intake, the two repair cycles, closure (PRD 3.4/3.5)."""
from __future__ import annotations

from fractions import Fraction

import calc
import services
import util
import validate as v
from flask import Blueprint
from auth import authenticate, current_user, own_device_id, own_work_order
from common import respond, respond_list
from errors import ApiError, bad_request
from store import store

bp = Blueprint("workorders", __name__)

WO_STATUSES = ("INTAKE", "IN_REPAIR", "AWAITING_PARTS", "REPAIR_COMPLETE",
               "VERIFIED", "CLOSED", "CANCELLED")
PRIORITIES = ("P1", "P2", "P3")
SEVERITIES = ("PATIENT_HARM", "CLINICAL_IMPACT", "ROUTINE")
SERVICE_MODES = ("IN_HOUSE", "VENDOR")


def _open_segment(work_order):
    work_order["_segment_start"] = store.now_iso()


def _close_segment(work_order):
    started = work_order.get("_segment_start")
    if started:
        elapsed = util.seconds_between(store.now(), util.parse_dt(started))
        if elapsed > 0:
            work_order["active_repair_seconds"] = work_order["active_repair_seconds"] + elapsed
        work_order["_segment_start"] = None


def _recompute_estimate(work_order):
    vendor = store.get("Vendor", work_order["vendor_id"]) if work_order["vendor_id"] else None
    work_order["estimated_cost_cents"] = calc.service_cost(
        work_order["labor_minutes"],
        work_order["parts_cost_cents"],
        work_order["service_mode"],
        Fraction(str(work_order["shift_multiplier_applied"])),
        vendor,
    )


# ------------------------------------------------------------------- intake
@bp.post("/work-orders")
def create_work_order():
    authenticate(["DeptSteward", "BiomedTech", "CEManager", "SecurityOfficer"])
    own_device_id(v.raw_body().get("device_id"))
    payload = v.body(
        required=("device_id", "reported_severity", "problem_summary"),
        optional=("origin_security_finding_id",),
    )
    device_id = v.req_id(payload, "device_id")
    severity = v.req_enum(payload, "reported_severity", SEVERITIES)
    summary = v.req_str(payload, "problem_summary")
    finding_id = v.opt_id(payload, "origin_security_finding_id")

    device = store.require("Device", device_id)
    finding = store.require("SecurityFinding", finding_id) if finding_id else None

    if device["operational_state"] == "RETIRED":
        raise ApiError("ERR_DEVICE_RETIRED", "A retired unit refuses work-order intake.")
    department = services.department_of(device)
    if department is not None and department["budget_state"] == "ON_HOLD":
        raise ApiError("ERR_DEPARTMENT_BUDGET_ON_HOLD",
                       "The owning department has reached its downtime budget ceiling.")

    record = services.new_work_order(device, severity, summary, finding_id)
    device["operational_state"] = "DOWN"
    store.touch(device)
    if finding is not None and finding["status"] == "OPEN":
        finding["status"] = "REMEDIATION_SCHEDULED"
        store.touch(finding)
    return respond(record, 201)


@bp.get("/work-orders/<wid>")
def read_work_order(wid):
    authenticate(["CEManager", "BiomedTech", "DeptSteward", "VendorRep", "SecurityOfficer"])
    own_work_order(store.get("WorkOrder", wid))
    return respond(store.require("WorkOrder", wid))


@bp.get("/work-orders")
def list_work_orders():
    authenticate(["CEManager", "BiomedTech", "DeptSteward", "VendorRep", "SecurityOfficer"])
    limit, offset = v.pagination()
    device_id = v.query_str("device_id")
    vendor_id = v.query_str("vendor_id")
    contract_id = v.query_str("service_contract_id")
    finding_id = v.query_str("origin_security_finding_id")
    status = v.query_enum("status", WO_STATUSES)
    priority = v.query_enum("priority", PRIORITIES)
    records = store.ordered([
        w for w in store.all("WorkOrder")
        if (device_id is None or w["device_id"] == device_id)
        and (vendor_id is None or w["vendor_id"] == vendor_id)
        and (contract_id is None or w["service_contract_id"] == contract_id)
        and (finding_id is None or w["origin_security_finding_id"] == finding_id)
        and (status is None or w["status"] == status)
        and (priority is None or w["priority"] == priority)
    ])
    return respond_list(records, limit, offset)


# ------------------------------------------------------------------- assign
@bp.post("/work-orders/<wid>/assign")
def assign_work_order(wid):
    authenticate(["CEManager", "BiomedTech"])
    work_order = store.require("WorkOrder", wid)
    payload = v.body(required=("service_mode",), optional=("vendor_id",))
    service_mode = v.req_enum(payload, "service_mode", SERVICE_MODES)
    vendor_id = v.opt_id(payload, "vendor_id")
    if service_mode == "VENDOR" and vendor_id is None:
        raise bad_request("vendor_id is required when service_mode is VENDOR.")

    vendor = store.require("Vendor", vendor_id) if (service_mode == "VENDOR") else None

    if work_order["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE",
                       "Assignment is only declared from INTAKE.")
    device = store.require("Device", work_order["device_id"])
    if device["operational_state"] == "RETIRED":
        raise ApiError("ERR_DEVICE_RETIRED", "A retired unit may not be assigned for repair.")
    facility = services.facility_of(device)
    if facility is not None and facility["ce_posture"] == "LOCKDOWN":
        raise ApiError("ERR_FACILITY_LOCKDOWN",
                       "The device's campus is in LOCKDOWN posture.")
    if vendor is not None and not vendor["is_approved"]:
        raise ApiError("ERR_VENDOR_NOT_APPROVED", "The named vendor is not on the approved list.")

    now_iso = store.now_iso()
    work_order["status"] = "IN_REPAIR"
    work_order["service_mode"] = service_mode
    work_order["vendor_id"] = vendor["id"] if vendor is not None else None
    work_order["assigned_user_id"] = current_user()
    work_order["repair_started_at"] = now_iso
    multiplier = calc.shift_multiplier_for(store.now())
    work_order["shift_multiplier_applied"] = float(multiplier)
    _open_segment(work_order)
    store.touch(work_order)
    return respond(work_order)


@bp.post("/work-orders/<wid>/parts-hold")
def parts_hold(wid):
    authenticate(["CEManager", "BiomedTech"])
    work_order = store.require("WorkOrder", wid)
    payload = v.body(optional=("note",))
    v.opt_str(payload, "note")
    if work_order["status"] != "IN_REPAIR":
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE",
                       "A parts hold is only declared from IN_REPAIR.")
    _close_segment(work_order)
    work_order["status"] = "AWAITING_PARTS"
    store.touch(work_order)
    return respond(work_order)


@bp.post("/work-orders/<wid>/resume")
def resume(wid):
    authenticate(["CEManager", "BiomedTech"])
    work_order = store.require("WorkOrder", wid)
    v.body()
    if work_order["status"] != "AWAITING_PARTS":
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE",
                       "Resume is only declared from AWAITING_PARTS.")
    work_order["status"] = "IN_REPAIR"
    _open_segment(work_order)
    store.touch(work_order)
    return respond(work_order)


@bp.post("/work-orders/<wid>/complete-repair")
def complete_repair(wid):
    authenticate(["BiomedTech", "VendorRep"])
    own_work_order(store.get("WorkOrder", wid))
    work_order = store.require("WorkOrder", wid)
    payload = v.body(required=("labor_minutes", "parts_cost_cents"))
    labor_minutes = v.req_int(payload, "labor_minutes", minimum=0)
    parts_cost = v.req_int(payload, "parts_cost_cents", minimum=0)
    if work_order["status"] != "IN_REPAIR":
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE",
                       "A repair pass is only declared from IN_REPAIR.")

    work_order["labor_minutes"] = work_order["labor_minutes"] + labor_minutes
    work_order["parts_cost_cents"] = work_order["parts_cost_cents"] + parts_cost
    _close_segment(work_order)
    work_order["repaired_by_user_id"] = current_user()
    work_order["repair_completed_at"] = store.now_iso()
    work_order["status"] = "REPAIR_COMPLETE"
    _recompute_estimate(work_order)
    store.touch(work_order)
    return respond(work_order)


@bp.post("/work-orders/<wid>/verify")
def verify(wid):
    authenticate(["BiomedTech", "CEManager"])
    work_order = store.require("WorkOrder", wid)
    payload = v.body(required=("result",), optional=("note",))
    result = v.req_enum(payload, "result", ("PASS", "FAIL"))
    v.opt_str(payload, "note")
    if work_order["status"] != "REPAIR_COMPLETE":
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE",
                       "Verification is only declared from REPAIR_COMPLETE.")
    if current_user() == work_order["repaired_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The technician who performed the repair may not verify it.")
    if result == "PASS":
        work_order["status"] = "VERIFIED"
        work_order["verified_by_user_id"] = current_user()
    else:
        work_order["status"] = "IN_REPAIR"
        work_order["verify_fail_count"] = work_order["verify_fail_count"] + 1
        _open_segment(work_order)
    store.touch(work_order)
    return respond(work_order)


# -------------------------------------------------------------------- close
def _select_contract(work_order, device):
    if work_order["vendor_id"] is None:
        return None
    started = util.parse_dt(work_order["repair_started_at"])
    candidates = []
    for contract in store.all("ServiceContract"):
        if contract["device_model_id"] != device["device_model_id"]:
            continue
        if contract["vendor_id"] != work_order["vendor_id"]:
            continue
        if contract["status"] != "ACTIVE":
            continue
        if not (util.parse_dt(contract["coverage_start"]) <= started
                <= util.parse_dt(contract["coverage_end"])):
            continue
        if contract["covered_events_used"] >= contract["covered_event_cap"]:
            continue
        candidates.append(contract)
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["deductible_cents"],
                                   util.parse_dt(c["coverage_end"]),
                                   c["created_at"], c["_seq"]))
    return candidates[0]


@bp.post("/work-orders/<wid>/close")
def close_work_order(wid):
    authenticate(["CEManager"])
    work_order = store.require("WorkOrder", wid)
    payload = v.body(required=("expected_department_version",))
    expected = v.req_int(payload, "expected_department_version")

    device = store.require("Device", work_order["device_id"])
    department = services.department_of(device)
    if department is not None and department["version"] != expected:
        raise ApiError("ERR_STALE_DEPARTMENT_VERSION",
                       "expected_department_version does not match the department's version.")
    if work_order["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE", "Closure is only declared from VERIFIED.")
    if device["security_state"] == "QUARANTINED":
        raise ApiError("ERR_DEVICE_QUARANTINED", "The unit under service is quarantined.")
    for assignment in store.all("LoanerAssignment"):
        if assignment["work_order_id"] == work_order["id"] and assignment["status"] == "DEPLOYED":
            raise ApiError("ERR_INVALID_LOANER_STATE",
                           "A deployed loaner assignment still blocks this closure.")

    # 1. contract selection, then the final cost variant
    contract = _select_contract(work_order, device)
    _recompute_estimate(work_order)
    if work_order["service_mode"] == "VENDOR" and contract is not None:
        work_order["service_contract_id"] = contract["id"]
        work_order["final_cost_cents"] = contract["deductible_cents"]
        contract["covered_events_used"] = contract["covered_events_used"] + 1
        if contract["covered_events_used"] >= contract["covered_event_cap"]:
            contract["status"] = "EXHAUSTED"
        store.touch(contract)
    else:
        work_order["final_cost_cents"] = work_order["estimated_cost_cents"]

    # 2. departmental debit under the PRE-debit overhead tier
    loaner_total = sum(
        a["rental_cost_cents"] for a in store.all("LoanerAssignment")
        if a["work_order_id"] == work_order["id"] and a["status"] == "RETURNED"
    )
    if department is not None:
        pre_spend = department["downtime_spend_cents"]
        charge = calc.department_charge(
            work_order["final_cost_cents"], pre_spend,
            department["downtime_budget_cents"], loaner_total,
        )
        work_order["department_charge_cents"] = charge
        department["downtime_spend_cents"] = pre_spend + charge
        services.apply_budget_state(department)
        store.touch(department)

    # 3. timing fields
    work_order["closed_at"] = store.now_iso()
    work_order["active_repair_hours"] = calc.hours_2dp(work_order["active_repair_seconds"])
    work_order["turnaround_hours"] = calc.hours_2dp(
        util.seconds_between(util.parse_dt(work_order["closed_at"]),
                             util.parse_dt(work_order["reported_at"]))
    )
    work_order["sla_met"] = work_order["active_repair_hours"] <= work_order["sla_hours"]
    work_order["status"] = "CLOSED"
    store.touch(work_order)

    # 4. the originating security finding, when this was a remediation order
    finding_id = work_order.get("origin_security_finding_id")
    if finding_id:
        finding = store.get("SecurityFinding", finding_id)
        if finding is not None and finding["status"] in ("OPEN", "REMEDIATION_SCHEDULED"):
            services.mitigate_finding(finding, touch_device=False)

    # 5. device settlement and the conditional restoration
    device["lifetime_maintenance_cost_cents"] = (
        device["lifetime_maintenance_cost_cents"] + work_order["final_cost_cents"]
    )
    services.recompute_replacement_score(device)
    services.conditional_restore(device)
    store.touch(device)
    return respond(work_order)


@bp.post("/work-orders/<wid>/cancel")
def cancel_work_order(wid):
    authenticate(["CEManager", "DeptSteward"])
    own_work_order(store.get("WorkOrder", wid))
    work_order = store.require("WorkOrder", wid)
    payload = v.body(required=("reason",))
    v.req_str(payload, "reason")
    if work_order["status"] not in ("INTAKE", "IN_REPAIR", "AWAITING_PARTS"):
        raise ApiError("ERR_INVALID_WORK_ORDER_STATE",
                       "A %s work order may not be cancelled." % work_order["status"])

    work_order["status"] = "CANCELLED"
    work_order["closed_at"] = store.now_iso()
    work_order["_segment_start"] = None

    deployed = store.ordered([
        a for a in store.all("LoanerAssignment")
        if a["work_order_id"] == work_order["id"] and a["status"] == "DEPLOYED"
    ])
    for assignment in deployed:
        services.cancel_loaner_assignment(assignment, release_pool_unit=True, escalate=False)
    if deployed:
        work_order["loaner_status"] = "UNCOVERED"
    store.touch(work_order)

    device = store.get("Device", work_order["device_id"])
    if device is not None and services.conditional_restore(device):
        store.touch(device)
    return respond(work_order)
