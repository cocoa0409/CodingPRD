"""Facility, Department, Vendor, DeviceModel and the logical clock."""
from __future__ import annotations

from flask import Blueprint

import calc
import services
import util
import validate as v
from auth import authenticate, own_department
from common import respond, respond_list, respond_raw
from errors import ApiError
from store import store

bp = Blueprint("core", __name__)

POSTURES = ("NORMAL", "HEIGHTENED", "LOCKDOWN")
BUDGET_STATES = ("OPEN", "WARNING", "ON_HOLD")


# ------------------------------------------------------------------ Facility
@bp.post("/facilities")
def create_facility():
    authenticate(["CEManager"])
    payload = v.body(required=("name", "facility_code", "pm_compliance_target_pct"))
    name = v.req_str(payload, "name")
    code = v.req_str(payload, "facility_code", min_len=1, max_len=16)
    target = v.req_number(payload, "pm_compliance_target_pct", minimum=0, maximum=100)
    for existing in store.all("Facility"):
        if existing["facility_code"] == code:
            raise ApiError("ERR_DUPLICATE_FACILITY_CODE", "facility_code '%s' is already registered." % code)
    record = store.new_record("Facility", {
        "name": name,
        "facility_code": code,
        "pm_compliance_target_pct": util.two_dp(_as_fraction(target)),
        "ce_posture": "NORMAL",
        "pm_compliance_pct_strict": 0.00,
        "pm_compliance_pct_operational": 100.00,
        "pm_audit_index": 0,
        "open_class_i_recall_count": 0,
        "departments_on_hold_count": 0,
    })
    return respond(record, 201)


def _as_fraction(value):
    from fractions import Fraction
    if isinstance(value, float):
        return Fraction(str(value))
    return Fraction(value)


@bp.get("/facilities/<fid>")
def read_facility(fid):
    authenticate(["CEManager", "BiomedTech", "SecurityOfficer", "DeptSteward", "VendorRep"])
    return respond(store.require("Facility", fid))


@bp.post("/facilities/<fid>/posture")
def set_posture(fid):
    authenticate(["CEManager"])
    facility = store.require("Facility", fid)
    payload = v.body(required=("to_posture",), optional=("note",))
    to_posture = v.req_enum(payload, "to_posture", POSTURES)
    v.opt_str(payload, "note")
    facility["ce_posture"] = to_posture
    store.touch(facility)
    return respond(facility)


@bp.post("/facilities/<fid>/pm-audit")
def pm_audit(fid):
    authenticate(["CEManager"])
    facility = store.require("Facility", fid)
    v.body()
    now = store.now()

    device_ids = {d["id"] for d in store.all("Device") if d["facility_id"] == facility["id"]}
    tasks = [t for t in store.all("PMTask") if t["device_id"] in device_ids]

    # Step 1 — sweep, processed due_at ASC then created_at ASC.
    sweepable = [
        t for t in tasks
        if t["status"] in ("SCHEDULED", "DEFERRED") and util.parse_dt(t["due_at"]) < now
    ]
    sweepable.sort(key=lambda t: (util.parse_dt(t["due_at"]), t["created_at"], t["_seq"]))
    for task in sweepable:
        task["status"] = "MISSED"
        store.touch(task)

    # Step 2 — measurement, keyed on original_due_at.
    window = [t for t in tasks if util.parse_dt(t["original_due_at"]) <= now]
    numerator = 0
    strict_den = 0
    operational_den = 0
    for task in window:
        if task["status"] == "COMPLETED" and task["completed_at"] is not None and \
                util.parse_dt(task["completed_at"]) <= util.parse_dt(task["original_due_at"]):
            numerator += 1
        if task["status"] in ("COMPLETED", "MISSED", "DEFERRED"):
            strict_den += 1
        if task["status"] in ("COMPLETED", "MISSED") or (
                task["status"] == "DEFERRED" and task["deferral_count"] >= 2):
            operational_den += 1

    strict = calc.EMPTY_STRICT_VALUE if strict_den == 0 else calc.pct_2dp(numerator, strict_den)
    operational = (calc.EMPTY_OPERATIONAL_VALUE if operational_den == 0
                   else calc.pct_2dp(numerator, operational_den))
    facility["pm_compliance_pct_strict"] = strict
    facility["pm_compliance_pct_operational"] = operational

    # Step 3 — posture escalation, guarded by a non-empty strict denominator.
    if strict_den > 0 and strict < facility["pm_compliance_target_pct"] \
            and facility["ce_posture"] == "NORMAL":
        facility["ce_posture"] = "HEIGHTENED"

    # Step 4
    facility["pm_audit_index"] = facility["pm_audit_index"] + 1
    store.touch(facility)
    return respond(facility)


@bp.get("/facilities/<fid>/replacement-plan")
def replacement_plan(fid):
    authenticate(["CEManager"])
    facility = store.require("Facility", fid)
    limit, offset = v.pagination()
    fiscal_budget = v.query_int("fiscal_budget_cents", minimum=0)

    ranked = [d for d in store.all("Device")
              if d["facility_id"] == facility["id"] and d["operational_state"] != "RETIRED"]
    for device in ranked:
        services.recompute_replacement_score(device)
    ranked.sort(key=lambda d: (-d["replacement_priority_score"],
                               d["acquisition_date"], d["created_at"], d["_seq"]))

    for index, device in enumerate(ranked, start=1):
        device["plan_rank"] = index

    if fiscal_budget is not None:
        remaining = fiscal_budget
        for device in ranked:
            model = services.model_of(device)
            cost = model["replacement_cost_cents"] if model else 0
            if cost <= remaining:
                device["plan_funded"] = True
                remaining -= cost
            else:
                device["plan_funded"] = False
    else:
        for device in ranked:
            device["plan_funded"] = False

    return respond_list(ranked, limit, offset)


# ---------------------------------------------------------------- Department
@bp.post("/departments")
def create_department():
    authenticate(["CEManager"])
    payload = v.body(required=("facility_id", "name", "cost_center_code", "downtime_budget_cents"))
    facility_id = v.req_id(payload, "facility_id")
    name = v.req_str(payload, "name")
    cost_center = v.req_str(payload, "cost_center_code")
    budget = v.req_int(payload, "downtime_budget_cents", minimum=1)
    store.require("Facility", facility_id)
    record = store.new_record("Department", {
        "facility_id": facility_id,
        "name": name,
        "cost_center_code": cost_center,
        "downtime_budget_cents": budget,
        "downtime_spend_cents": 0,
        "budget_state": "OPEN",
    })
    return respond(record, 201)


@bp.get("/departments/<did>")
def read_department(did):
    authenticate(["CEManager", "DeptSteward", "BiomedTech"])
    own_department(did)
    return respond(store.require("Department", did))


@bp.get("/departments")
def list_departments():
    authenticate(["CEManager", "DeptSteward", "BiomedTech"])
    limit, offset = v.pagination()
    facility_id = v.query_str("facility_id")
    budget_state = v.query_enum("budget_state", BUDGET_STATES)
    records = store.ordered([
        d for d in store.all("Department")
        if (facility_id is None or d["facility_id"] == facility_id)
        and (budget_state is None or d["budget_state"] == budget_state)
    ])
    return respond_list(records, limit, offset)


# -------------------------------------------------------------------- Vendor
@bp.post("/vendors")
def create_vendor():
    authenticate(["CEManager"])
    payload = v.body(
        required=("name", "vendor_code", "hourly_rate_cents", "travel_flat_cents"),
        optional=("security_attestation_on_file", "is_approved"),
    )
    record = store.new_record("Vendor", {
        "name": v.req_str(payload, "name"),
        "vendor_code": v.req_str(payload, "vendor_code"),
        "hourly_rate_cents": v.req_int(payload, "hourly_rate_cents", minimum=0),
        "travel_flat_cents": v.req_int(payload, "travel_flat_cents", minimum=0),
        "security_attestation_on_file": v.opt_bool(payload, "security_attestation_on_file", False),
        "is_approved": v.opt_bool(payload, "is_approved", True),
    })
    return respond(record, 201)


@bp.get("/vendors/<vid>")
def read_vendor(vid):
    authenticate(["CEManager", "BiomedTech", "VendorRep"])
    return respond(store.require("Vendor", vid))


# --------------------------------------------------------------- DeviceModel
@bp.post("/device-models")
def create_device_model():
    authenticate(["CEManager"])
    payload = v.body(
        required=("manufacturer", "model_number", "device_family",
                  "expected_life_years", "replacement_cost_cents"),
        optional=("is_network_connected",),
    )
    record = store.new_record("DeviceModel", {
        "manufacturer": v.req_str(payload, "manufacturer"),
        "model_number": v.req_str(payload, "model_number"),
        "device_family": v.req_str(payload, "device_family"),
        "is_network_connected": v.opt_bool(payload, "is_network_connected", False),
        "expected_life_years": v.req_int(payload, "expected_life_years", minimum=1),
        "replacement_cost_cents": v.req_int(payload, "replacement_cost_cents", minimum=1),
    })
    return respond(record, 201)


@bp.get("/device-models/<mid>")
def read_device_model(mid):
    authenticate(["CEManager", "BiomedTech", "SecurityOfficer"])
    return respond(store.require("DeviceModel", mid))


# --------------------------------------------------------------------- Clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["CEManager"])
    payload = v.body(required=("to_iso8601",))
    raw, parsed = v.req_dt(payload, "to_iso8601")
    store.set_clock(parsed, raw)
    return respond_raw({"current_utc": raw})
