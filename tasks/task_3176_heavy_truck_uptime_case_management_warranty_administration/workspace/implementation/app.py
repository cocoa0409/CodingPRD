"""Flask application: all routes for the Heavy Truck Uptime & Warranty API."""

import os
import uuid
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request

from db import db
from helpers import (
    ApiError, api_err, authenticate, err_forbidden, error_response,
    get_pagination, iso,
    new_entity, opt_int, opt_num, opt_str, paginate, parse_dt, req_enum,
    req_int, require_fields, round_half_up_2dp, success_list, success_object,
    touch,
)
import services as svc

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(api_err("ERR_INVALID_REQUEST", "route not found"))


@app.errorhandler(405)
def handle_405(_e):
    return error_response(api_err("ERR_INVALID_REQUEST", "method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(api_err("ERR_INVALID_REQUEST", f"internal error: {err}"))


def body():
    if not request.data:
        return {}
    try:
        data = request.get_json(silent=False)
    except Exception:
        raise api_err("ERR_INVALID_REQUEST", "request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise api_err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def fleet_out(f):
    return {k: f[k] for k in (
        "id", "fleet_name", "home_region", "reliability_score",
        "total_downtime_hours", "open_case_count", "fleet_status",
        "created_at", "updated_at", "version")}


def truck_out(t):
    return {k: t[k] for k in (
        "id", "fleet_id", "vin", "model_code", "in_service_on", "odometer_miles",
        "base_warranty_until_miles", "base_warranty_until_on", "truck_status",
        "open_case_count", "repeat_repair_flag", "created_at", "updated_at",
        "version")}


def dealer_out(d):
    return {k: d[k] for k in (
        "id", "dealer_name", "region", "hourly_labor_rate_cents",
        "dealer_status", "bay_count", "active_case_count", "created_at",
        "updated_at", "version")}


def bay_out(b):
    return {k: b[k] for k in (
        "id", "dealer_id", "bay_code", "bay_status", "created_at", "updated_at",
        "version")}


def fault_event_out(e):
    return {k: e[k] for k in (
        "id", "truck_id", "fault_code", "severity", "recommended_action",
        "occurred_at", "event_status", "created_at")}


def case_out(c):
    return {k: c[k] for k in (
        "id", "truck_id", "fleet_id", "dealer_id",
        "opened_from_fault_event_id", "case_status", "fault_code",
        "severity_at_open", "opened_at", "closed_at", "downtime_hours",
        "diagnostic_minutes_authorized", "expedite_count", "created_at",
        "updated_at", "version")}


def work_order_out(w):
    return {k: w[k] for k in (
        "id", "case_id", "dealer_id", "bay_id", "scheduled_start_at",
        "scheduled_end_at", "work_order_status", "diagnostic_minutes_authorized",
        "labor_minutes_actual", "repair_outcome", "created_at", "updated_at",
        "version")}


def part_order_out(p):
    return {k: p[k] for k in (
        "id", "case_id", "part_number", "quantity", "part_weight_kg_per_unit",
        "part_cost_cents", "expedite_decision", "expedite_cost_cents",
        "downtime_cost_cents", "part_order_status", "created_at", "updated_at",
        "version")}


def claim_out(c):
    return {k: c[k] for k in (
        "id", "case_id", "claim_type", "labor_minutes_claimed",
        "parts_claimed_cents", "labor_rate_cents_per_hour",
        "labor_hours_allowed", "labor_amount_allowed_cents",
        "parts_amount_allowed_cents", "submission_status", "recovery_status",
        "recovery_amount_cents", "created_at", "updated_at", "version")}


def part_return_out(p):
    return {k: p[k] for k in (
        "id", "claim_id", "part_number", "return_window_days", "shipped_at",
        "received_at", "part_return_status", "inspection_disposition",
        "created_at", "updated_at", "version")}


def recovery_out(r):
    return {k: r[k] for k in (
        "id", "claim_id", "part_return_id", "supplier_id",
        "claimed_amount_cents", "paid_amount_cents", "recovery_status",
        "created_at", "updated_at", "version")}


def contract_out(c):
    return {k: c[k] for k in (
        "id", "truck_id", "contract_type", "starts_on", "ends_on", "max_miles",
        "premium_cents", "contract_status", "prorated_credit_cents",
        "created_at", "updated_at", "version")}


def campaign_out(c):
    return {k: c[k] for k in (
        "id", "campaign_code", "campaign_kind", "affected_model_codes",
        "fault_code", "opens_on", "closes_on", "campaign_status",
        "completion_pct", "overdue_count", "created_at", "updated_at",
        "version")}


def completion_out(c):
    return {k: c[k] for k in (
        "id", "campaign_id", "truck_id", "case_id", "completion_status",
        "exemption_reason", "created_at", "updated_at", "version")}


def report_out(r):
    return {k: r[k] for k in (
        "id", "fleet_id", "ops_run_index", "computed_at", "trucks_in_service",
        "trucks_down", "total_downtime_hours", "repeat_repair_truck_count",
        "campaign_completion_pct", "reliability_score", "created_at")}


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def resolve_fleet(fid):
    f = db.fleets.get(fid)
    if not f:
        raise api_err("ERR_FLEET_NOT_FOUND", "Fleet id does not exist")
    return f


def resolve_truck(fleet, tid):
    t = db.trucks.get(tid)
    if not t or t["fleet_id"] != fleet["id"]:
        raise api_err("ERR_TRUCK_NOT_FOUND", "Truck id does not exist within the fleet")
    return t


def resolve_case(truck, cid):
    c = db.cases.get(cid)
    if not c or c["truck_id"] != truck["id"]:
        raise api_err("ERR_CASE_NOT_FOUND", "Case id does not exist within the truck")
    return c


def resolve_work_order(case, wid):
    w = db.work_orders.get(wid)
    if not w or w["case_id"] != case["id"]:
        raise api_err("ERR_WORK_ORDER_NOT_FOUND", "WorkOrder id does not exist within the case")
    return w


def resolve_part_order(case, pid):
    p = db.part_orders.get(pid)
    if not p or p["case_id"] != case["id"]:
        raise api_err("ERR_PART_ORDER_NOT_FOUND", "PartOrder id does not exist within the case")
    return p


def resolve_claim(case, cid):
    c = db.claims.get(cid)
    if not c or c["case_id"] != case["id"]:
        raise api_err("ERR_CLAIM_NOT_FOUND", "WarrantyClaim id does not exist within the case")
    return c


def resolve_part_return(claim, pid):
    p = db.part_returns.get(pid)
    if not p or p["claim_id"] != claim["id"]:
        raise api_err("ERR_PART_RETURN_NOT_FOUND", "PartReturn id does not exist within the claim")
    return p


def resolve_recovery(claim, rid):
    r = db.recoveries.get(rid)
    if not r or r["claim_id"] != claim["id"]:
        raise api_err("ERR_RECOVERY_NOT_FOUND", "SupplierRecovery id does not exist within the claim")
    return r


def resolve_dealer(did):
    d = db.dealers.get(did)
    if not d:
        raise api_err("ERR_DEALER_NOT_FOUND", "Dealer id does not exist")
    return d


def resolve_bay(dealer, bid):
    b = db.bays.get(bid)
    if not b or b["dealer_id"] != dealer["id"]:
        raise api_err("ERR_BAY_NOT_FOUND", "ServiceBay id does not exist within the dealer")
    return b


def resolve_campaign(cid):
    c = db.campaigns.get(cid)
    if not c:
        raise api_err("ERR_CAMPAIGN_NOT_FOUND", "Campaign id does not exist")
    return c


def resolve_completion(campaign, cid):
    c = db.campaign_completions.get(cid)
    if not c or c["campaign_id"] != campaign["id"]:
        raise api_err("ERR_CAMPAIGN_COMPLETION_NOT_FOUND",
                      "CampaignCompletion id does not exist within the campaign")
    return c


def resolve_fault_event(truck, fid):
    e = db.fault_events.get(fid)
    if not e or e["truck_id"] != truck["id"]:
        raise api_err("ERR_FAULT_EVENT_NOT_FOUND", "FaultEvent id does not exist within the truck")
    return e


def resolve_contract(truck, cid):
    c = db.coverage_contracts.get(cid)
    if not c or c["truck_id"] != truck["id"]:
        raise api_err("ERR_COVERAGE_CONTRACT_NOT_FOUND",
                      "CoverageContract id does not exist within the truck")
    return c


def check_fleet_active(fleet):
    if fleet["fleet_status"] != "ACTIVE":
        raise api_err("ERR_FLEET_NOT_ACTIVE", "Fleet is not ACTIVE for mutating operation")


def fleet_truck_case(fleet_id, truck_id, case_id):
    fleet = resolve_fleet(fleet_id)
    truck = resolve_truck(fleet, truck_id)
    case = resolve_case(truck, case_id)
    return fleet, truck, case


def fleet_truck_case_active(fleet_id, truck_id, case_id):
    fleet, truck, case = fleet_truck_case(fleet_id, truck_id, case_id)
    check_fleet_active(fleet)
    return fleet, truck, case


ALL_ROLES = ["FleetManager", "UptimeCoordinator", "DealerAdvisor",
             "PartsManager", "WarrantyAdmin", "SupplierManager"]


# ---------------------------------------------------------------------------
# Clock / Ops
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def set_clock():
    authenticate(ALL_ROLES)
    b = require_fields(body(), ["to_iso8601"])
    dt = parse_dt(b["to_iso8601"], "to_iso8601")
    db.clock = dt
    return success_object({"current_utc": iso(db.clock)})


@app.post("/_ops/run")
def run_ops():
    authenticate(["UptimeCoordinator"])
    with db.lock:
        idx, fleets_processed = svc.ops_run()
    return success_object({"ops_run_index": idx, "fleets_processed": fleets_processed})


# ---------------------------------------------------------------------------
# Fleets
# ---------------------------------------------------------------------------

@app.post("/fleets")
def create_fleet():
    # Bootstrap exemption: FleetManager is entity-backed by Fleet, but the
    # first fleet cannot exist before this call — the actor-not-found check
    # is skipped for this endpoint only.
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        from helpers import err_missing_header
        raise err_missing_header()
    if role != "FleetManager":
        if role not in {"FleetManager", "UptimeCoordinator", "DealerAdvisor",
                        "PartsManager", "WarrantyAdmin", "SupplierManager"}:
            from helpers import err_missing_header
            raise err_missing_header()
        from helpers import err_forbidden
        raise err_forbidden()
    b = require_fields(body(), ["fleet_name", "home_region"])
    with db.lock:
        f = new_entity()
        f.update({
            "fleet_name": opt_str(b["fleet_name"], "fleet_name"),
            "home_region": opt_str(b["home_region"], "home_region"),
            "reliability_score": 1000,
            "total_downtime_hours": 0,
            "open_case_count": 0,
            "fleet_status": "ACTIVE",
        })
        db.fleets[f["id"]] = f
    return success_object(fleet_out(f), 201)


@app.get("/fleets")
def list_fleets():
    authenticate(ALL_ROLES)
    limit, offset = get_pagination()
    rows = list(db.fleets.values())
    page, total = paginate(rows, limit, offset)
    return success_list([fleet_out(f) for f in page], total, limit, offset)


@app.get("/fleets/<fleetId>")
def get_fleet(fleetId):
    authenticate(ALL_ROLES)
    f = resolve_fleet(fleetId)
    return success_object(fleet_out(f))


@app.put("/fleets/<fleetId>")
def update_fleet(fleetId):
    authenticate(["FleetManager"])
    f = resolve_fleet(fleetId)
    b = body()
    if "fleet_name" in b and b["fleet_name"] is not None:
        f["fleet_name"] = opt_str(b["fleet_name"], "fleet_name")
    if "home_region" in b and b["home_region"] is not None:
        f["home_region"] = opt_str(b["home_region"], "home_region")
    touch(f)
    return success_object(fleet_out(f))


@app.post("/fleets/<fleetId>/suspend")
def suspend_fleet(fleetId):
    authenticate(["FleetManager"])
    f = resolve_fleet(fleetId)
    if f["fleet_status"] != "ACTIVE":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Fleet is not ACTIVE")
    f["fleet_status"] = "SUSPENDED"
    touch(f)
    return success_object(fleet_out(f))


@app.post("/fleets/<fleetId>/reactivate")
def reactivate_fleet(fleetId):
    authenticate(["FleetManager"])
    f = resolve_fleet(fleetId)
    if f["fleet_status"] != "SUSPENDED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Fleet is not SUSPENDED")
    f["fleet_status"] = "ACTIVE"
    touch(f)
    return success_object(fleet_out(f))


# ---------------------------------------------------------------------------
# Trucks
# ---------------------------------------------------------------------------

@app.post("/fleets/<fleetId>/trucks")
def create_truck(fleetId):
    authenticate(["FleetManager"])
    fleet = resolve_fleet(fleetId)
    check_fleet_active(fleet)
    b = require_fields(body(), ["vin", "model_code", "in_service_on",
                                "odometer_miles", "base_warranty_until_miles",
                                "base_warranty_until_on"])
    vin = opt_str(b["vin"], "vin")
    if len(vin) != 17:
        raise api_err("ERR_INVALID_REQUEST", "vin must be 17 characters")
    for t in db.trucks.values():
        if t["vin"] == vin:
            raise api_err("ERR_DUPLICATE_IDENTIFIER", "VIN uniqueness violation")
    in_service_dt = parse_dt(b["in_service_on"], "in_service_on")
    warranty_on_dt = parse_dt(b["base_warranty_until_on"], "base_warranty_until_on")
    odo = req_int(b, "odometer_miles", 0)
    warranty_miles = req_int(b, "base_warranty_until_miles", 0)
    with db.lock:
        t = new_entity()
        t.update({
            "fleet_id": fleet["id"],
            "vin": vin,
            "model_code": opt_str(b["model_code"], "model_code"),
            "in_service_on": iso(in_service_dt),
            "in_service_on_dt": in_service_dt,
            "odometer_miles": odo,
            "base_warranty_until_miles": warranty_miles,
            "base_warranty_until_on": iso(warranty_on_dt),
            "base_warranty_until_on_dt": warranty_on_dt,
            "truck_status": "IN_SERVICE",
            "open_case_count": 0,
            "repeat_repair_flag": False,
        })
        db.trucks[t["id"]] = t
    return success_object(truck_out(t), 201)


@app.get("/fleets/<fleetId>/trucks")
def list_trucks_in_fleet(fleetId):
    authenticate(["FleetManager", "UptimeCoordinator", "DealerAdvisor",
                  "PartsManager", "WarrantyAdmin"])
    fleet = resolve_fleet(fleetId)
    limit, offset = get_pagination()
    rows = [t for t in db.trucks.values() if t["fleet_id"] == fleet["id"]]
    rows = apply_filter(rows, "truck_status")
    rows = apply_filter(rows, "model_code")
    page, total = paginate(rows, limit, offset)
    return success_list([truck_out(t) for t in page], total, limit, offset)


@app.get("/fleets/<fleetId>/trucks/<truckId>")
def get_truck(fleetId, truckId):
    authenticate(ALL_ROLES)
    fleet = resolve_fleet(fleetId)
    t = resolve_truck(fleet, truckId)
    return success_object(truck_out(t))


@app.put("/fleets/<fleetId>/trucks/<truckId>")
def update_truck(fleetId, truckId):
    authenticate(["FleetManager"])
    fleet = resolve_fleet(fleetId)
    check_fleet_active(fleet)
    t = resolve_truck(fleet, truckId)
    b = body()
    if "odometer_miles" in b and b["odometer_miles"] is not None:
        new_odo = opt_int(b["odometer_miles"], "odometer_miles", 0)
        if new_odo < t["odometer_miles"]:
            raise api_err("ERR_ODOMETER_REGRESSION", "odometer_miles lower than current value")
        t["odometer_miles"] = new_odo
    if "model_code" in b and b["model_code"] is not None:
        t["model_code"] = opt_str(b["model_code"], "model_code")
    touch(t)
    return success_object(truck_out(t))


@app.post("/fleets/<fleetId>/trucks/<truckId>/decommission")
def decommission_truck(fleetId, truckId):
    authenticate(["FleetManager"])
    fleet = resolve_fleet(fleetId)
    check_fleet_active(fleet)
    t = resolve_truck(fleet, truckId)
    if t["truck_status"] == "DECOMMISSIONED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Truck already DECOMMISSIONED")
    if t["open_case_count"] != 0:
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "Truck has open cases; cannot decommission")
    t["truck_status"] = "DECOMMISSIONED"
    touch(t)
    # Cancel ACTIVE coverage contracts with proration
    for c in db.coverage_contracts.values():
        if c["truck_id"] == t["id"] and c["contract_status"] == "ACTIVE":
            c["contract_status"] = "CANCELLED"
            c["prorated_credit_cents"] = svc.coverage_proration(c, t, db.now())
            touch(c)
    # Exempt OPEN campaign completions on this truck
    for cc in db.campaign_completions.values():
        if cc["truck_id"] == t["id"] and cc["completion_status"] == "OPEN":
            cc["completion_status"] = "EXEMPTED"
            cc["exemption_reason"] = "TRUCK_DECOMMISSIONED"
            touch(cc)
            svc.refresh_campaign_pct(db.campaigns[cc["campaign_id"]])
    return success_object(truck_out(t))


# ---------------------------------------------------------------------------
# Fault Events
# ---------------------------------------------------------------------------

@app.post("/fleets/<fleetId>/trucks/<truckId>/fault-events")
def create_fault_event(fleetId, truckId):
    authenticate(["UptimeCoordinator"])
    fleet = resolve_fleet(fleetId)
    check_fleet_active(fleet)
    truck = resolve_truck(fleet, truckId)
    b = require_fields(body(), ["fault_code", "severity", "recommended_action",
                                "occurred_at"])
    severity = req_enum(b, "severity", {"INFO", "WARNING", "CRITICAL"})
    action = req_enum(b, "recommended_action",
                      {"MONITOR", "SCHEDULE_SERVICE", "STOP_IMMEDIATELY"})
    occurred_dt = parse_dt(b["occurred_at"], "occurred_at")
    if occurred_dt > db.now():
        raise api_err("ERR_INVALID_REQUEST", "occurred_at must be <= current clock")
    with db.lock:
        eid = str(uuid.uuid4())
        e = {
            "id": eid,
            "created_at": iso(db.now()),
            "created_at_dt": db.now(),
            "truck_id": truck["id"],
            "fault_code": opt_str(b["fault_code"], "fault_code"),
            "severity": severity,
            "recommended_action": action,
            "occurred_at": iso(occurred_dt),
            "occurred_at_dt": occurred_dt,
            "event_status": "UNLINKED",
        }
        db.fault_events[eid] = e
    return success_object(fault_event_out(e), 201)


@app.get("/fleets/<fleetId>/trucks/<truckId>/fault-events")
def list_fault_events(fleetId, truckId):
    authenticate(["UptimeCoordinator", "FleetManager", "DealerAdvisor", "WarrantyAdmin"])
    fleet = resolve_fleet(fleetId)
    truck = resolve_truck(fleet, truckId)
    limit, offset = get_pagination()
    rows = [e for e in db.fault_events.values() if e["truck_id"] == truck["id"]]
    rows = apply_filter(rows, "event_status")
    rows = apply_filter(rows, "severity")
    page, total = paginate(rows, limit, offset)
    return success_list([fault_event_out(e) for e in page], total, limit, offset)


@app.post("/fleets/<fleetId>/trucks/<truckId>/fault-events/<faultEventId>/dismiss")
def dismiss_fault_event(fleetId, truckId, faultEventId):
    authenticate(["UptimeCoordinator"])
    fleet = resolve_fleet(fleetId)
    check_fleet_active(fleet)
    truck = resolve_truck(fleet, truckId)
    e = resolve_fault_event(truck, faultEventId)
    if e["event_status"] != "UNLINKED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "FaultEvent is not UNLINKED")
    e["event_status"] = "DISMISSED"
    return success_object(fault_event_out(e))


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

@app.post("/fleets/<fleetId>/trucks/<truckId>/cases")
def create_case(fleetId, truckId):
    authenticate(["UptimeCoordinator"])
    fleet = resolve_fleet(fleetId)
    check_fleet_active(fleet)
    truck = resolve_truck(fleet, truckId)
    if truck["truck_status"] == "DECOMMISSIONED":
        raise api_err("ERR_TRUCK_DECOMMISSIONED", "Truck is DECOMMISSIONED")
    b = require_fields(body(), ["fault_code"])
    fault_code = opt_str(b["fault_code"], "fault_code")
    fault_event = None
    fe_id = b.get("fault_event_id")
    if fe_id is not None:
        fault_event = resolve_fault_event(truck, fe_id)
        if fault_event["event_status"] != "UNLINKED":
            raise api_err("ERR_INVALID_STATE_TRANSITION", "FaultEvent is not UNLINKED")
        if (fault_event["severity"] == "CRITICAL"
                and fault_event["recommended_action"] == "STOP_IMMEDIATELY"):
            if fault_event["occurred_at_dt"] < db.now() - timedelta(minutes=30):
                raise api_err("ERR_CRITICAL_FAULT_WINDOW_LAPSED",
                              "CRITICAL/STOP_IMMEDIATELY fault older than 30 minutes")
    with db.lock:
        c = new_entity()
        now = db.now()
        c.update({
            "truck_id": truck["id"],
            "fleet_id": fleet["id"],
            "dealer_id": None,
            "opened_from_fault_event_id": fe_id,
            "case_status": "OPEN",
            "fault_code": fault_code,
            "severity_at_open": fault_event["severity"] if fault_event else None,
            "opened_at": iso(now),
            "opened_at_dt": now,
            "closed_at": None,
            "closed_at_dt": None,
            "downtime_hours": 0.00,
            "diagnostic_minutes_authorized": 0,
            "expedite_count": 0,
        })
        db.cases[c["id"]] = c
        if fault_event:
            fault_event["event_status"] = "LINKED"
        truck["open_case_count"] += 1
        touch(truck)
        fleet["open_case_count"] += 1
        touch(fleet)
    return success_object(case_out(c), 201)


@app.get("/fleets/<fleetId>/trucks/<truckId>/cases")
def list_cases(fleetId, truckId):
    authenticate(ALL_ROLES)
    fleet = resolve_fleet(fleetId)
    truck = resolve_truck(fleet, truckId)
    limit, offset = get_pagination()
    rows = [c for c in db.cases.values() if c["truck_id"] == truck["id"]]
    rows = apply_filter(rows, "case_status")
    page, total = paginate(rows, limit, offset)
    return success_list([case_out(c) for c in page], total, limit, offset)


@app.get("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>")
def get_case(fleetId, truckId, caseId):
    authenticate(ALL_ROLES)
    _, _, case = fleet_truck_case(fleetId, truckId, caseId)
    return success_object(case_out(case))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/triage")
def triage_case(fleetId, truckId, caseId):
    authenticate(["UptimeCoordinator"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    if case["case_status"] != "OPEN":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Case is not OPEN")
    case["case_status"] = "TRIAGE"
    touch(case)
    return success_object(case_out(case))


def intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/schedule")
def schedule_case(fleetId, truckId, caseId):
    authenticate(["UptimeCoordinator"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    b = require_fields(body(), ["dealer_id", "bay_id", "scheduled_start_at",
                                "scheduled_end_at", "expected_truck_version"])
    if case["case_status"] != "TRIAGE":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Case is not TRIAGE")
    dealer = resolve_dealer(opt_str(b["dealer_id"], "dealer_id"))
    bay = resolve_bay(dealer, opt_str(b["bay_id"], "bay_id"))
    start_dt = parse_dt(b["scheduled_start_at"], "scheduled_start_at")
    end_dt = parse_dt(b["scheduled_end_at"], "scheduled_end_at")

    # OCC (against Truck version)
    expected = opt_int(b["expected_truck_version"], "expected_truck_version")
    if expected != truck["version"]:
        raise api_err("ERR_STALE_VERSION", "expected_truck_version does not match current truck version")

    # Window validity
    if end_dt <= start_dt or (end_dt - start_dt) < timedelta(minutes=30):
        raise api_err("ERR_INVALID_WORK_ORDER_WINDOW",
                      "WorkOrder window invalid: end must be > start and duration >= 30 minutes")

    # Bay-time check (priority 9 before dealer availability priority 10).
    # "AVAILABLE for the requested window": a bay flagged DOWN (or
    # DECOMMISSIONED) is never available; RESERVED/IN_USE bays remain
    # available for non-overlapping windows — exclusivity is enforced by the
    # half-open interval overlap check against AUTHORIZED/IN_PROGRESS work
    # orders below.
    if bay["bay_status"] in ("DOWN", "DECOMMISSIONED"):
        raise api_err("ERR_BAY_TIME_CONFLICT", "ServiceBay is not AVAILABLE")
    for wo in db.work_orders.values():
        if wo.get("bay_id") != bay["id"]:
            continue
        if wo["work_order_status"] not in ("AUTHORIZED", "IN_PROGRESS"):
            continue
        if intervals_overlap(start_dt, end_dt, wo["scheduled_start_at_dt"],
                             wo["scheduled_end_at_dt"]):
            raise api_err("ERR_BAY_TIME_CONFLICT",
                          "ServiceBay has an overlapping AUTHORIZED/IN_PROGRESS WorkOrder")

    # Dealer availability
    if dealer["dealer_status"] != "ACTIVE":
        raise api_err("ERR_DEALER_NOT_AVAILABLE", "Dealer is not ACTIVE")
    if dealer["region"] != fleet["home_region"] and not b.get("allow_cross_region"):
        raise api_err("ERR_DEALER_NOT_AVAILABLE",
                      "Dealer region does not match fleet home_region")

    with db.lock:
        case["case_status"] = "SCHEDULED"
        case["dealer_id"] = dealer["id"]
        touch(case)
        touch(truck)  # OCC write on Truck

        wo = new_entity()
        wo.update({
            "case_id": case["id"],
            "dealer_id": dealer["id"],
            "bay_id": bay["id"],
            "scheduled_start_at": iso(start_dt),
            "scheduled_start_at_dt": start_dt,
            "scheduled_end_at": iso(end_dt),
            "scheduled_end_at_dt": end_dt,
            "work_order_status": "DRAFT",
            "diagnostic_minutes_authorized": 0,
            "labor_minutes_actual": 0,
            "repair_outcome": None,
        })
        db.work_orders[wo["id"]] = wo

        bay["bay_status"] = "RESERVED"
        touch(bay)
        svc.refresh_dealer_derived(dealer)
        touch(dealer)
    return success_object(case_out(case))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/start-service")
def start_service(fleetId, truckId, caseId):
    authenticate(["DealerAdvisor"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    if case["case_status"] != "SCHEDULED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Case is not SCHEDULED")
    wos = [w for w in db.work_orders.values()
           if w["case_id"] == case["id"] and w["work_order_status"] == "AUTHORIZED"]
    if not wos:
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "No AUTHORIZED WorkOrder on this case")
    wo = sorted(wos, key=lambda w: w["created_at"])[0]
    bay = db.bays.get(wo["bay_id"])
    if not bay or bay["bay_status"] != "RESERVED":
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "ServiceBay is not RESERVED for this work order")
    case["case_status"] = "IN_SERVICE"
    touch(case)
    wo["work_order_status"] = "IN_PROGRESS"
    touch(wo)
    bay["bay_status"] = "IN_USE"
    touch(bay)
    if truck["truck_status"] == "IN_SERVICE":
        truck["truck_status"] = "DOWN"
        touch(truck)
    svc.refresh_dealer_derived(db.dealers[case["dealer_id"]])
    touch(db.dealers[case["dealer_id"]])
    return success_object(case_out(case))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/request-close")
def request_close(fleetId, truckId, caseId):
    authenticate(["DealerAdvisor"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    if case["case_status"] != "IN_SERVICE":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Case is not IN_SERVICE")
    for wo in db.work_orders.values():
        if wo["case_id"] == case["id"] and wo["work_order_status"] not in ("COMPLETED", "CANCELLED"):
            raise api_err("ERR_INVALID_STATE_TRANSITION",
                          "WorkOrder on case not COMPLETED or CANCELLED")
    for po in db.part_orders.values():
        if po["case_id"] == case["id"] and po["part_order_status"] not in ("INSTALLED", "CANCELLED"):
            raise api_err("ERR_INVALID_STATE_TRANSITION",
                          "PartOrder on case not INSTALLED or CANCELLED")
    case["case_status"] = "PENDING_CLOSE"
    touch(case)
    return success_object(case_out(case))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/reopen-service")
def reopen_service(fleetId, truckId, caseId):
    authenticate(["UptimeCoordinator"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    if case["case_status"] != "PENDING_CLOSE":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Case is not PENDING_CLOSE")
    case["case_status"] = "IN_SERVICE"
    touch(case)
    # Bay back to IN_USE if it was AVAILABLE
    for wo in db.work_orders.values():
        if wo["case_id"] == case["id"] and wo.get("bay_id"):
            bay = db.bays.get(wo["bay_id"])
            if bay and bay["bay_status"] == "AVAILABLE":
                bay["bay_status"] = "IN_USE"
                touch(bay)
            break
    return success_object(case_out(case))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/close")
def close_case(fleetId, truckId, caseId):
    authenticate(["UptimeCoordinator"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    if case["case_status"] != "PENDING_CLOSE":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Case is not PENDING_CLOSE")
    for cl in db.claims.values():
        if cl["case_id"] == case["id"] and cl["submission_status"] in ("SUBMITTED", "UNDER_REVIEW"):
            raise api_err("ERR_CASE_HAS_OPEN_CLAIM",
                          "Case close blocked by claim in SUBMITTED or UNDER_REVIEW")
    with db.lock:
        svc.close_case_effects(case)
    return success_object(case_out(case))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/cancel")
def cancel_case(fleetId, truckId, caseId):
    authenticate(["UptimeCoordinator"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    if case["case_status"] not in ("OPEN", "TRIAGE", "SCHEDULED"):
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "Case must be OPEN, TRIAGE, or SCHEDULED to cancel")
    with db.lock:
        svc.cancel_case_effects(case)
    return success_object(case_out(case))


# ---------------------------------------------------------------------------
# Work Orders
# ---------------------------------------------------------------------------

@app.get("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/work-orders")
def list_work_orders(fleetId, truckId, caseId):
    authenticate(["UptimeCoordinator", "FleetManager", "DealerAdvisor", "WarrantyAdmin"])
    _, _, case = fleet_truck_case(fleetId, truckId, caseId)
    limit, offset = get_pagination()
    rows = [w for w in db.work_orders.values() if w["case_id"] == case["id"]]
    page, total = paginate(rows, limit, offset)
    return success_list([work_order_out(w) for w in page], total, limit, offset)


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/work-orders/<workOrderId>/authorize")
def authorize_work_order(fleetId, truckId, caseId, workOrderId):
    authenticate(["UptimeCoordinator"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    wo = resolve_work_order(case, workOrderId)
    b = require_fields(body(), ["diagnostic_minutes_authorized"])
    minutes = req_int(b, "diagnostic_minutes_authorized")
    if minutes <= 0:
        raise api_err("ERR_INVALID_REQUEST",
                      "diagnostic_minutes_authorized must be > 0")
    if wo["work_order_status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "WorkOrder is not DRAFT")
    if case["case_status"] != "SCHEDULED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Case is not SCHEDULED")
    wo["work_order_status"] = "AUTHORIZED"
    wo["diagnostic_minutes_authorized"] = minutes
    touch(wo)
    case["diagnostic_minutes_authorized"] += minutes
    touch(case)
    return success_object(work_order_out(wo))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/work-orders/<workOrderId>/complete")
def complete_work_order(fleetId, truckId, caseId, workOrderId):
    authenticate(["DealerAdvisor"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    wo = resolve_work_order(case, workOrderId)
    b = require_fields(body(), ["labor_minutes_actual", "repair_outcome"])
    labor = req_int(b, "labor_minutes_actual", 0)
    outcome = req_enum(b, "repair_outcome", {"FIXED", "NOT_FIXED", "PARTIAL"})
    if wo["work_order_status"] != "IN_PROGRESS":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "WorkOrder is not IN_PROGRESS")
    wo["work_order_status"] = "COMPLETED"
    wo["labor_minutes_actual"] = labor
    wo["repair_outcome"] = outcome
    touch(wo)
    if outcome == "NOT_FIXED":
        svc.record_penalty(fleet["id"], "not_fixed", svc.NOT_FIXED_PENALTY)
        touch(fleet)
    if outcome != "FIXED":
        svc.evaluate_repeat_repair(truck, case["fault_code"])
        touch(truck)
    return success_object(work_order_out(wo))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/work-orders/<workOrderId>/cancel")
def cancel_work_order(fleetId, truckId, caseId, workOrderId):
    authenticate(["UptimeCoordinator"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    wo = resolve_work_order(case, workOrderId)
    if wo["work_order_status"] not in ("DRAFT", "AUTHORIZED"):
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "WorkOrder must be DRAFT or AUTHORIZED to cancel")
    was_authorized = wo["work_order_status"] == "AUTHORIZED"
    wo["work_order_status"] = "CANCELLED"
    touch(wo)
    if wo.get("bay_id"):
        bay = db.bays.get(wo["bay_id"])
        if bay and bay["bay_status"] == "RESERVED":
            bay["bay_status"] = "AVAILABLE"
            touch(bay)
    if was_authorized and wo["diagnostic_minutes_authorized"]:
        case["diagnostic_minutes_authorized"] -= wo["diagnostic_minutes_authorized"]
        touch(case)
    return success_object(work_order_out(wo))


# ---------------------------------------------------------------------------
# Part Orders
# ---------------------------------------------------------------------------

@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/part-orders")
def create_part_order(fleetId, truckId, caseId):
    authenticate(["PartsManager"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    b = require_fields(body(), ["part_number", "quantity",
                                "part_weight_kg_per_unit", "part_cost_cents"])
    if case["case_status"] != "IN_SERVICE":
        raise api_err("ERR_CASE_NOT_AWAITING_PART",
                      "PartOrder creation requires Case in IN_SERVICE state")
    quantity = req_int(b, "quantity", 1)
    weight = opt_num(b["part_weight_kg_per_unit"], "part_weight_kg_per_unit")
    if weight is None or weight < 0:
        raise api_err("ERR_INVALID_REQUEST", "part_weight_kg_per_unit must be >= 0")
    cost = req_int(b, "part_cost_cents", 0)
    with db.lock:
        p = new_entity()
        p.update({
            "case_id": case["id"],
            "part_number": opt_str(b["part_number"], "part_number"),
            "quantity": quantity,
            "part_weight_kg_per_unit": float(weight),
            "part_cost_cents": cost,
            "expedite_decision": "PENDING_EVAL",
            "expedite_cost_cents": 0,
            "downtime_cost_cents": 0,
            "part_order_status": "PENDING",
        })
        db.part_orders[p["id"]] = p
        case["case_status"] = "AWAITING_PART"
        touch(case)
    return success_object(part_order_out(p), 201)


@app.get("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/part-orders")
def list_part_orders(fleetId, truckId, caseId):
    authenticate(["UptimeCoordinator", "FleetManager", "DealerAdvisor",
                  "PartsManager", "WarrantyAdmin"])
    _, _, case = fleet_truck_case(fleetId, truckId, caseId)
    limit, offset = get_pagination()
    rows = [p for p in db.part_orders.values() if p["case_id"] == case["id"]]
    page, total = paginate(rows, limit, offset)
    return success_list([part_order_out(p) for p in page], total, limit, offset)


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/part-orders/<partOrderId>/evaluate-expedite")
def evaluate_expedite(fleetId, truckId, caseId, partOrderId):
    authenticate(["PartsManager"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    po = resolve_part_order(case, partOrderId)
    b = require_fields(body(), ["dealer_repair_hours_est",
                                "downtime_rate_cents_per_hour", "distance_band"])
    band = req_enum(b, "distance_band",
                    {"INTRA_REGION", "CROSS_COUNTRY", "INTERNATIONAL"})
    hours_est = opt_num(b["dealer_repair_hours_est"], "dealer_repair_hours_est")
    rate = req_int(b, "downtime_rate_cents_per_hour", 0)
    overnight, standard, weight = svc.expedite_freight_cost(
        po["quantity"], po["part_weight_kg_per_unit"], band)
    decision, cost, downtime = svc.expedite_decision_calc(hours_est, rate,
                                                          overnight, standard)
    prev = po["expedite_decision"]
    po["expedite_decision"] = decision
    po["expedite_cost_cents"] = cost
    po["downtime_cost_cents"] = downtime
    touch(po)
    if decision == "EXPEDITE_OVERNIGHT" and prev != "EXPEDITE_OVERNIGHT":
        case["expedite_count"] += 1
        touch(case)
    elif prev == "EXPEDITE_OVERNIGHT" and decision != "EXPEDITE_OVERNIGHT":
        case["expedite_count"] = max(0, case["expedite_count"] - 1)
        touch(case)
    return success_object(part_order_out(po))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/part-orders/<partOrderId>/ship")
def ship_part_order(fleetId, truckId, caseId, partOrderId):
    authenticate(["PartsManager"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    po = resolve_part_order(case, partOrderId)
    if po["part_order_status"] != "PENDING":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "PartOrder is not PENDING")
    if po["expedite_decision"] not in ("EXPEDITE_OVERNIGHT", "EXPEDITE_STANDARD"):
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "PartOrder expedite_decision not approved for shipping")
    po["part_order_status"] = "SHIPPED"
    touch(po)
    return success_object(part_order_out(po))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/part-orders/<partOrderId>/receive")
def receive_part_order(fleetId, truckId, caseId, partOrderId):
    authenticate(["DealerAdvisor"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    po = resolve_part_order(case, partOrderId)
    if po["part_order_status"] != "SHIPPED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "PartOrder is not SHIPPED")
    po["part_order_status"] = "RECEIVED"
    touch(po)
    return success_object(part_order_out(po))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/part-orders/<partOrderId>/install")
def install_part_order(fleetId, truckId, caseId, partOrderId):
    authenticate(["DealerAdvisor"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    po = resolve_part_order(case, partOrderId)
    if po["part_order_status"] != "RECEIVED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "PartOrder is not RECEIVED")
    if case["case_status"] not in ("IN_SERVICE", "AWAITING_PART"):
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "Case is not IN_SERVICE or AWAITING_PART")
    po["part_order_status"] = "INSTALLED"
    touch(po)
    svc.maybe_back_in_service(case)
    return success_object(part_order_out(po))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/part-orders/<partOrderId>/cancel")
def cancel_part_order(fleetId, truckId, caseId, partOrderId):
    authenticate(["PartsManager"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    po = resolve_part_order(case, partOrderId)
    if po["part_order_status"] != "PENDING":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "PartOrder is not PENDING")
    if po.get("expedite_decision") == "EXPEDITE_OVERNIGHT":
        case["expedite_count"] = max(0, case["expedite_count"] - 1)
        touch(case)
    po["part_order_status"] = "CANCELLED"
    touch(po)
    svc.maybe_back_in_service(case)
    return success_object(part_order_out(po))


# ---------------------------------------------------------------------------
# Warranty Claims
# ---------------------------------------------------------------------------

@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims")
def create_claim(fleetId, truckId, caseId):
    authenticate(["WarrantyAdmin"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    b = require_fields(body(), ["claim_type", "labor_minutes_claimed",
                                "parts_claimed_cents"])
    claim_type = req_enum(b, "claim_type",
                          {"BASE_WARRANTY", "EXTENDED_COVERAGE", "CAMPAIGN", "GOODWILL"})
    labor_minutes = req_int(b, "labor_minutes_claimed", 0)
    parts_cents = req_int(b, "parts_claimed_cents", 0)
    rate = 0
    if case.get("dealer_id") and case["dealer_id"] in db.dealers:
        rate = db.dealers[case["dealer_id"]]["hourly_labor_rate_cents"]
    with db.lock:
        c = new_entity()
        c.update({
            "case_id": case["id"],
            "claim_type": claim_type,
            "labor_minutes_claimed": labor_minutes,
            "parts_claimed_cents": parts_cents,
            "labor_rate_cents_per_hour": rate,
            "labor_hours_allowed": 0.0,
            "labor_amount_allowed_cents": 0,
            "parts_amount_allowed_cents": 0,
            "submission_status": "DRAFT",
            "recovery_status": "NOT_INITIATED",
            "recovery_amount_cents": 0,
        })
        db.claims[c["id"]] = c
    return success_object(claim_out(c), 201)


@app.get("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims")
def list_claims(fleetId, truckId, caseId):
    authenticate(["WarrantyAdmin", "UptimeCoordinator", "FleetManager", "SupplierManager"])
    _, _, case = fleet_truck_case(fleetId, truckId, caseId)
    limit, offset = get_pagination()
    rows = [c for c in db.claims.values() if c["case_id"] == case["id"]]
    rows = apply_filter(rows, "submission_status")
    rows = apply_filter(rows, "recovery_status")
    page, total = paginate(rows, limit, offset)
    return success_list([claim_out(c) for c in page], total, limit, offset)


@app.get("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>")
def get_claim(fleetId, truckId, caseId, claimId):
    authenticate(["WarrantyAdmin", "UptimeCoordinator", "FleetManager",
                  "SupplierManager", "DealerAdvisor"])
    _, _, case = fleet_truck_case(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    return success_object(claim_out(claim))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/submit")
def submit_claim(fleetId, truckId, caseId, claimId):
    authenticate(["WarrantyAdmin"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    b = require_fields(body(), ["expected_case_version"])
    if claim["submission_status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Claim is not DRAFT")
    if case["case_status"] not in ("IN_SERVICE", "AWAITING_PART",
                                   "PENDING_CLOSE", "CLOSED"):
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "Case state does not permit claim submission")
    expected = opt_int(b["expected_case_version"], "expected_case_version")
    if expected != case["version"]:
        raise api_err("ERR_STALE_VERSION",
                      "expected_case_version does not match current case version")
    hours = svc.labor_time_standard(case["fault_code"], claim["claim_type"])
    max_minutes = Decimal(str(hours)) * Decimal(60)
    if Decimal(claim["labor_minutes_claimed"]) > max_minutes:
        raise api_err("ERR_LABOR_MINUTES_EXCEED_STANDARD",
                      "labor_minutes_claimed exceeds labor time standard")
    claim["labor_hours_allowed"] = hours
    claim["labor_amount_allowed_cents"] = svc.compute_labor_amount_cents(
        hours, claim["labor_rate_cents_per_hour"])
    claim["parts_amount_allowed_cents"] = svc.parts_allowance(claim, truck)
    claim["submission_status"] = "SUBMITTED"
    touch(claim)
    touch(case)  # OCC write on Case
    return success_object(claim_out(claim))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/begin-review")
def begin_review(fleetId, truckId, caseId, claimId):
    authenticate(["WarrantyAdmin"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    if claim["submission_status"] != "SUBMITTED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Claim is not SUBMITTED")
    claim["submission_status"] = "UNDER_REVIEW"
    touch(claim)
    return success_object(claim_out(claim))


def create_part_return_for_claim(claim, case):
    # part_number matching an installed part order on the case
    installed = [p for p in db.part_orders.values()
                 if p["case_id"] == case["id"] and p["part_order_status"] == "INSTALLED"]
    part_number = installed[0]["part_number"] if installed else None
    window = 30 if claim["claim_type"] == "BASE_WARRANTY" else 45
    pr = new_entity()
    pr.update({
        "claim_id": claim["id"],
        "part_number": part_number,
        "return_window_days": window,
        "shipped_at": None,
        "received_at": None,
        "part_return_status": "REQUESTED",
        "inspection_disposition": None,
        "created_at_dt": db.now(),
    })
    db.part_returns[pr["id"]] = pr
    claim["recovery_status"] = "PART_RETURN_REQUESTED"
    touch(claim)


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/approve")
def approve_claim(fleetId, truckId, caseId, claimId):
    authenticate(["WarrantyAdmin"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    b = body()
    if claim["submission_status"] != "UNDER_REVIEW":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Claim is not UNDER_REVIEW")
    partial_labor = opt_int(b.get("partial_labor_amount_allowed_cents"),
                            "partial_labor_amount_allowed_cents", 0)
    partial_parts = opt_int(b.get("partial_parts_amount_allowed_cents"),
                            "partial_parts_amount_allowed_cents", 0)
    partial = False
    if partial_labor is not None and partial_labor < claim["labor_amount_allowed_cents"]:
        claim["labor_amount_allowed_cents"] = partial_labor
        partial = True
    if partial_parts is not None and partial_parts < claim["parts_amount_allowed_cents"]:
        claim["parts_amount_allowed_cents"] = partial_parts
        partial = True
    claim["submission_status"] = "PARTIAL_APPROVED" if partial else "APPROVED"
    touch(claim)
    if claim["claim_type"] in ("BASE_WARRANTY", "CAMPAIGN"):
        create_part_return_for_claim(claim, case)
    return success_object(claim_out(claim))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/deny")
def deny_claim(fleetId, truckId, caseId, claimId):
    authenticate(["WarrantyAdmin"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    if claim["submission_status"] != "UNDER_REVIEW":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Claim is not UNDER_REVIEW")
    claim["submission_status"] = "DENIED"
    touch(claim)
    for pr in db.part_returns.values():
        if pr["claim_id"] == claim["id"] and pr["part_return_status"] == "REQUESTED":
            pr["part_return_status"] = "LATE_REJECTED"
            touch(pr)
            claim["recovery_status"] = "RECOVERY_DENIED"
            touch(claim)
    return success_object(claim_out(claim))


# ---------------------------------------------------------------------------
# Part Returns
# ---------------------------------------------------------------------------

@app.get("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/part-returns")
def list_part_returns(fleetId, truckId, caseId, claimId):
    authenticate(["WarrantyAdmin", "SupplierManager", "DealerAdvisor"])
    _, _, case = fleet_truck_case(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    limit, offset = get_pagination()
    rows = [p for p in db.part_returns.values() if p["claim_id"] == claim["id"]]
    page, total = paginate(rows, limit, offset)
    return success_list([part_return_out(p) for p in page], total, limit, offset)


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/part-returns/<partReturnId>/ship")
def ship_part_return(fleetId, truckId, caseId, claimId, partReturnId):
    authenticate(["DealerAdvisor"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    pr = resolve_part_return(claim, partReturnId)
    if pr["part_return_status"] != "REQUESTED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "PartReturn is not REQUESTED")
    deadline = pr["created_at_dt"] + timedelta(days=pr["return_window_days"])
    if db.now() > deadline:
        raise api_err("ERR_RETURN_WINDOW_LAPSED",
                      "PartReturn ship attempt beyond return_window_days")
    pr["part_return_status"] = "IN_TRANSIT"
    pr["shipped_at"] = iso(db.now())
    touch(pr)
    claim["recovery_status"] = "PART_IN_TRANSIT"
    touch(claim)
    return success_object(part_return_out(pr))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/part-returns/<partReturnId>/receive")
def receive_part_return(fleetId, truckId, caseId, claimId, partReturnId):
    authenticate(["SupplierManager"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    pr = resolve_part_return(claim, partReturnId)
    if pr["part_return_status"] != "IN_TRANSIT":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "PartReturn is not IN_TRANSIT")
    pr["part_return_status"] = "RECEIVED"
    pr["received_at"] = iso(db.now())
    touch(pr)
    claim["recovery_status"] = "PART_RECEIVED"
    touch(claim)
    return success_object(part_return_out(pr))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/part-returns/<partReturnId>/inspect")
def inspect_part_return(fleetId, truckId, caseId, claimId, partReturnId):
    authenticate(["SupplierManager"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    pr = resolve_part_return(claim, partReturnId)
    b = require_fields(body(), ["inspection_disposition"])
    disposition = req_enum(b, "inspection_disposition", {"OK", "FAILED"})
    if pr["part_return_status"] != "RECEIVED":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "PartReturn is not RECEIVED")
    pr["inspection_disposition"] = disposition
    if disposition == "OK":
        pr["part_return_status"] = "INSPECTED_OK"
    else:
        pr["part_return_status"] = "INSPECTED_FAILED"
        claim["recovery_status"] = "RECOVERY_DENIED"
        touch(claim)
    touch(pr)
    return success_object(part_return_out(pr))


# ---------------------------------------------------------------------------
# Supplier Recoveries
# ---------------------------------------------------------------------------

@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/recoveries")
def create_recovery(fleetId, truckId, caseId, claimId):
    authenticate(["SupplierManager"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    b = require_fields(body(), ["part_return_id", "supplier_id", "claimed_amount_cents"])
    pr = resolve_part_return(claim, opt_str(b["part_return_id"], "part_return_id"))
    claimed = req_int(b, "claimed_amount_cents", 0)
    if pr["part_return_status"] != "INSPECTED_OK":
        raise api_err("ERR_RECOVERY_CLAIM_EXCEEDS_ALLOWANCE",
                      "PartReturn is not INSPECTED_OK")
    if claimed > claim["parts_amount_allowed_cents"]:
        raise api_err("ERR_RECOVERY_CLAIM_EXCEEDS_ALLOWANCE",
                      "claimed_amount_cents exceeds parts_amount_allowed_cents")
    for r in db.recoveries.values():
        if r.get("part_return_id") == pr["id"]:
            raise api_err("ERR_INVALID_STATE_TRANSITION",
                          "A recovery already exists for this part return")
    with db.lock:
        r = new_entity()
        r.update({
            "claim_id": claim["id"],
            "part_return_id": pr["id"],
            "supplier_id": opt_str(b["supplier_id"], "supplier_id"),
            "claimed_amount_cents": claimed,
            "paid_amount_cents": 0,
            "recovery_status": "FILED",
        })
        db.recoveries[r["id"]] = r
        claim["recovery_status"] = "RECOVERY_FILED"
        touch(claim)
    return success_object(recovery_out(r), 201)


@app.get("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/recoveries")
def list_recoveries(fleetId, truckId, caseId, claimId):
    authenticate(["SupplierManager", "WarrantyAdmin"])
    _, _, case = fleet_truck_case(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    limit, offset = get_pagination()
    rows = [r for r in db.recoveries.values() if r["claim_id"] == claim["id"]]
    page, total = paginate(rows, limit, offset)
    return success_list([recovery_out(r) for r in page], total, limit, offset)


def _recovery_transition(fleetId, truckId, caseId, claimId, recoveryId,
                         allowed_from, to_status):
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    rec = resolve_recovery(claim, recoveryId)
    if rec["recovery_status"] not in allowed_from:
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      f"Recovery is not in {sorted(allowed_from)}")
    rec["recovery_status"] = to_status
    touch(rec)
    return claim, rec


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/recoveries/<recoveryId>/dispute")
def dispute_recovery(fleetId, truckId, caseId, claimId, recoveryId):
    authenticate(["SupplierManager"])
    _, rec = _recovery_transition(fleetId, truckId, caseId, claimId, recoveryId,
                                  {"FILED"}, "UNDER_DISPUTE")
    return success_object(recovery_out(rec))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/recoveries/<recoveryId>/refile")
def refile_recovery(fleetId, truckId, caseId, claimId, recoveryId):
    authenticate(["SupplierManager"])
    _, rec = _recovery_transition(fleetId, truckId, caseId, claimId, recoveryId,
                                  {"UNDER_DISPUTE"}, "FILED")
    return success_object(recovery_out(rec))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/recoveries/<recoveryId>/mark-paid")
def mark_paid_recovery(fleetId, truckId, caseId, claimId, recoveryId):
    authenticate(["SupplierManager"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    rec = resolve_recovery(claim, recoveryId)
    b = require_fields(body(), ["paid_amount_cents"])
    paid = req_int(b, "paid_amount_cents", 0)
    if rec["recovery_status"] not in ("FILED", "UNDER_DISPUTE"):
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "Recovery is not FILED or UNDER_DISPUTE")
    if paid > rec["claimed_amount_cents"]:
        raise api_err("ERR_RECOVERY_OVERPAID",
                      "paid_amount_cents exceeds claimed_amount_cents")
    rec["paid_amount_cents"] = paid
    rec["recovery_status"] = "PAID"
    touch(rec)
    claim["recovery_amount_cents"] += paid
    claim["recovery_status"] = "RECOVERY_PAID"
    touch(claim)
    return success_object(recovery_out(rec))


@app.post("/fleets/<fleetId>/trucks/<truckId>/cases/<caseId>/claims/<claimId>/recoveries/<recoveryId>/deny")
def deny_recovery(fleetId, truckId, caseId, claimId, recoveryId):
    authenticate(["SupplierManager"])
    fleet, truck, case = fleet_truck_case_active(fleetId, truckId, caseId)
    claim = resolve_claim(case, claimId)
    rec = resolve_recovery(claim, recoveryId)
    if rec["recovery_status"] not in ("FILED", "UNDER_DISPUTE"):
        raise api_err("ERR_INVALID_STATE_TRANSITION",
                      "Recovery is not FILED or UNDER_DISPUTE")
    rec["recovery_status"] = "DENIED"
    touch(rec)
    claim["recovery_status"] = "RECOVERY_DENIED"
    touch(claim)
    return success_object(recovery_out(rec))


# ---------------------------------------------------------------------------
# Dealers / Bays
# ---------------------------------------------------------------------------

@app.post("/dealers")
def create_dealer():
    authenticate(["FleetManager"])
    b = require_fields(body(), ["dealer_name", "region", "hourly_labor_rate_cents"])
    rate = req_int(b, "hourly_labor_rate_cents")
    if rate <= 0:
        raise api_err("ERR_INVALID_REQUEST", "hourly_labor_rate_cents must be > 0")
    with db.lock:
        d = new_entity()
        d.update({
            "dealer_name": opt_str(b["dealer_name"], "dealer_name"),
            "region": opt_str(b["region"], "region"),
            "hourly_labor_rate_cents": rate,
            "dealer_status": "ACTIVE",
            "bay_count": 0,
            "active_case_count": 0,
        })
        db.dealers[d["id"]] = d
    return success_object(dealer_out(d), 201)


@app.get("/dealers")
def list_dealers():
    authenticate(["FleetManager", "UptimeCoordinator", "DealerAdvisor", "PartsManager"])
    limit, offset = get_pagination()
    rows = list(db.dealers.values())
    rows = apply_filter(rows, "region")
    rows = apply_filter(rows, "dealer_status")
    page, total = paginate(rows, limit, offset)
    return success_list([dealer_out(d) for d in page], total, limit, offset)


@app.get("/dealers/<dealerId>")
def get_dealer(dealerId):
    authenticate(["FleetManager", "UptimeCoordinator", "DealerAdvisor",
                  "PartsManager", "WarrantyAdmin"])
    d = resolve_dealer(dealerId)
    return success_object(dealer_out(d))


@app.post("/dealers/<dealerId>/bays")
def create_bay(dealerId):
    actor = authenticate(["DealerAdvisor"])
    dealer = resolve_dealer(dealerId)
    # PRD §2.1: DealerAdvisor ownership — X-User-ID is the acting Dealer's id;
    # the bay being created references that Dealer via dealer_id.
    if actor.user_id != dealer["id"]:
        raise err_forbidden()
    b = require_fields(body(), ["bay_code"])
    with db.lock:
        bay = new_entity()
        bay.update({
            "dealer_id": dealer["id"],
            "bay_code": opt_str(b["bay_code"], "bay_code"),
            "bay_status": "AVAILABLE",
        })
        db.bays[bay["id"]] = bay
        svc.refresh_dealer_derived(dealer)
        touch(dealer)
    return success_object(bay_out(bay), 201)


@app.get("/dealers/<dealerId>/bays")
def list_bays(dealerId):
    authenticate(["DealerAdvisor", "UptimeCoordinator", "PartsManager"])
    dealer = resolve_dealer(dealerId)
    limit, offset = get_pagination()
    rows = [b for b in db.bays.values() if b["dealer_id"] == dealer["id"]]
    rows = apply_filter(rows, "bay_status")
    page, total = paginate(rows, limit, offset)
    return success_list([bay_out(b) for b in page], total, limit, offset)


@app.post("/dealers/<dealerId>/bays/<bayId>/mark-down")
def mark_bay_down(dealerId, bayId):
    authenticate(["DealerAdvisor"])
    dealer = resolve_dealer(dealerId)
    bay = resolve_bay(dealer, bayId)
    if bay["bay_status"] != "AVAILABLE":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Bay is not AVAILABLE")
    bay["bay_status"] = "DOWN"
    touch(bay)
    return success_object(bay_out(bay))


@app.post("/dealers/<dealerId>/bays/<bayId>/mark-available")
def mark_bay_available(dealerId, bayId):
    authenticate(["DealerAdvisor"])
    dealer = resolve_dealer(dealerId)
    bay = resolve_bay(dealer, bayId)
    if bay["bay_status"] != "DOWN":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Bay is not DOWN")
    bay["bay_status"] = "AVAILABLE"
    touch(bay)
    return success_object(bay_out(bay))


# ---------------------------------------------------------------------------
# Coverage Contracts
# ---------------------------------------------------------------------------

@app.post("/fleets/<fleetId>/trucks/<truckId>/coverage-contracts")
def create_contract(fleetId, truckId):
    authenticate(["FleetManager"])
    fleet = resolve_fleet(fleetId)
    check_fleet_active(fleet)
    truck = resolve_truck(fleet, truckId)
    if truck["truck_status"] == "DECOMMISSIONED":
        raise api_err("ERR_TRUCK_DECOMMISSIONED", "Truck is DECOMMISSIONED")
    b = require_fields(body(), ["contract_type", "starts_on", "ends_on",
                                "max_miles", "premium_cents"])
    ctype = req_enum(b, "contract_type",
                     {"EXTENDED_POWERTRAIN", "EXTENDED_AFTERTREATMENT", "EXTENDED_FULL"})
    starts_dt = parse_dt(b["starts_on"], "starts_on")
    ends_dt = parse_dt(b["ends_on"], "ends_on")
    max_miles = req_int(b, "max_miles", 0)
    premium = req_int(b, "premium_cents", 0)
    if not (starts_dt < ends_dt) or starts_dt < truck["in_service_on_dt"]:
        raise api_err("ERR_INVALID_COVERAGE_WINDOW",
                      "CoverageContract window invalid")
    with db.lock:
        c = new_entity()
        c.update({
            "truck_id": truck["id"],
            "contract_type": ctype,
            "starts_on": iso(starts_dt),
            "starts_on_dt": starts_dt,
            "ends_on": iso(ends_dt),
            "ends_on_dt": ends_dt,
            "max_miles": max_miles,
            "premium_cents": premium,
            "contract_status": "ACTIVE",
            "prorated_credit_cents": 0,
            "odometer_at_start_miles": truck["odometer_miles"],
        })
        db.coverage_contracts[c["id"]] = c
    return success_object(contract_out(c), 201)


@app.get("/fleets/<fleetId>/trucks/<truckId>/coverage-contracts")
def list_contracts(fleetId, truckId):
    authenticate(["FleetManager", "WarrantyAdmin"])
    fleet = resolve_fleet(fleetId)
    truck = resolve_truck(fleet, truckId)
    limit, offset = get_pagination()
    rows = [c for c in db.coverage_contracts.values() if c["truck_id"] == truck["id"]]
    rows = apply_filter(rows, "contract_status")
    page, total = paginate(rows, limit, offset)
    return success_list([contract_out(c) for c in page], total, limit, offset)


@app.post("/fleets/<fleetId>/trucks/<truckId>/coverage-contracts/<contractId>/cancel")
def cancel_contract(fleetId, truckId, contractId):
    authenticate(["FleetManager"])
    fleet = resolve_fleet(fleetId)
    check_fleet_active(fleet)
    truck = resolve_truck(fleet, truckId)
    contract = resolve_contract(truck, contractId)
    if contract["contract_status"] != "ACTIVE":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Contract is not ACTIVE")
    contract["contract_status"] = "CANCELLED"
    contract["prorated_credit_cents"] = svc.coverage_proration(contract, truck, db.now())
    touch(contract)
    return success_object(contract_out(contract))


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

@app.post("/campaigns")
def create_campaign():
    authenticate(["UptimeCoordinator"])
    b = require_fields(body(), ["campaign_code", "campaign_kind",
                                "affected_model_codes", "fault_code",
                                "opens_on", "closes_on"])
    code = opt_str(b["campaign_code"], "campaign_code")
    for c in db.campaigns.values():
        if c["campaign_code"] == code:
            raise api_err("ERR_DUPLICATE_IDENTIFIER", "campaign_code uniqueness violation")
    kind = req_enum(b, "campaign_kind", {"RECALL", "SERVICE_CAMPAIGN"})
    models = b["affected_model_codes"]
    opens_dt = parse_dt(b["opens_on"], "opens_on")
    closes_dt = parse_dt(b["closes_on"], "closes_on")
    if (not isinstance(models, list) or not models
            or not all(isinstance(m, str) for m in models)
            or closes_dt <= opens_dt):
        raise api_err("ERR_INVALID_CAMPAIGN_WINDOW", "Campaign window invalid")
    with db.lock:
        c = new_entity()
        c.update({
            "campaign_code": code,
            "campaign_kind": kind,
            "affected_model_codes": models,
            "fault_code": opt_str(b["fault_code"], "fault_code"),
            "opens_on": iso(opens_dt),
            "opens_on_dt": opens_dt,
            "closes_on": iso(closes_dt),
            "closes_on_dt": closes_dt,
            "campaign_status": "OPEN",
            "completion_pct": 0.0,
            "overdue_count": 0,
        })
        db.campaigns[c["id"]] = c
        # Fan out completion rows
        for t in db.trucks.values():
            if t["model_code"] in models and t["in_service_on_dt"] <= closes_dt:
                cc = new_entity()
                cc.update({
                    "campaign_id": c["id"],
                    "truck_id": t["id"],
                    "case_id": None,
                    "completion_status": "OPEN",
                    "exemption_reason": None,
                })
                db.campaign_completions[cc["id"]] = cc
    return success_object(campaign_out(c), 201)


@app.get("/campaigns")
def list_campaigns():
    authenticate(["UptimeCoordinator", "FleetManager", "WarrantyAdmin"])
    limit, offset = get_pagination()
    rows = list(db.campaigns.values())
    rows = apply_filter(rows, "campaign_status")
    rows = apply_filter(rows, "campaign_kind")
    page, total = paginate(rows, limit, offset)
    return success_list([campaign_out(c) for c in page], total, limit, offset)


@app.get("/campaigns/<campaignId>")
def get_campaign(campaignId):
    authenticate(["UptimeCoordinator", "FleetManager", "WarrantyAdmin", "SupplierManager"])
    c = resolve_campaign(campaignId)
    return success_object(campaign_out(c))


@app.post("/campaigns/<campaignId>/close")
def close_campaign(campaignId):
    authenticate(["UptimeCoordinator"])
    c = resolve_campaign(campaignId)
    b = require_fields(body(), ["expected_campaign_version"])
    if c["campaign_status"] != "OPEN":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Campaign is not OPEN")
    expected = opt_int(b["expected_campaign_version"], "expected_campaign_version")
    if expected != c["version"]:
        raise api_err("ERR_STALE_VERSION",
                      "expected_campaign_version does not match current campaign version")
    grace_end = c["closes_on_dt"] + timedelta(days=90)
    if not (Decimal(str(c["completion_pct"])) >= Decimal("95.00")
            or db.now() > grace_end):
        raise api_err("ERR_CAMPAIGN_NOT_CLOSABLE",
                      "Campaign close attempted before completion >= 95.00 or grace expiry")
    c["campaign_status"] = "CLOSED"
    touch(c)
    return success_object(campaign_out(c))


# ---------------------------------------------------------------------------
# Campaign Completions
# ---------------------------------------------------------------------------

@app.get("/campaigns/<campaignId>/completions")
def list_completions(campaignId):
    authenticate(["UptimeCoordinator", "FleetManager", "WarrantyAdmin"])
    c = resolve_campaign(campaignId)
    limit, offset = get_pagination()
    rows = [cc for cc in db.campaign_completions.values() if cc["campaign_id"] == c["id"]]
    rows = apply_filter(rows, "completion_status")
    rows = apply_filter(rows, "truck_id")
    page, total = paginate(rows, limit, offset)
    return success_list([completion_out(cc) for cc in page], total, limit, offset)


@app.post("/campaigns/<campaignId>/completions/<completionId>/schedule")
def schedule_completion(campaignId, completionId):
    authenticate(["UptimeCoordinator"])
    campaign = resolve_campaign(campaignId)
    cc = resolve_completion(campaign, completionId)
    b = require_fields(body(), ["case_id"])
    case = db.cases.get(opt_str(b["case_id"], "case_id"))
    if not case:
        raise api_err("ERR_CASE_NOT_FOUND", "Case id does not exist")
    if cc["completion_status"] != "OPEN":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Completion row is not OPEN")
    if (case["fault_code"] != campaign["fault_code"]
            or case["truck_id"] != cc["truck_id"]):
        raise api_err("ERR_CAMPAIGN_COMPLETION_MISMATCH",
                      "Case truck or fault_code does not match completion row")
    if case["case_status"] not in ("TRIAGE", "SCHEDULED", "IN_SERVICE", "AWAITING_PART"):
        raise api_err("ERR_CAMPAIGN_COMPLETION_MISMATCH",
                      "Case state does not permit completion scheduling")
    cc["completion_status"] = "SCHEDULED"
    cc["case_id"] = case["id"]
    touch(cc)
    return success_object(completion_out(cc))


@app.post("/campaigns/<campaignId>/completions/<completionId>/exempt")
def exempt_completion(campaignId, completionId):
    authenticate(["UptimeCoordinator"])
    campaign = resolve_campaign(campaignId)
    cc = resolve_completion(campaign, completionId)
    b = require_fields(body(), ["exemption_reason"])
    if cc["completion_status"] != "OPEN":
        raise api_err("ERR_INVALID_STATE_TRANSITION", "Completion row is not OPEN")
    cc["completion_status"] = "EXEMPTED"
    cc["exemption_reason"] = opt_str(b["exemption_reason"], "exemption_reason")
    touch(cc)
    svc.refresh_campaign_pct(campaign)
    return success_object(completion_out(cc))


# ---------------------------------------------------------------------------
# Reliability Reports (fleet-nested)
# ---------------------------------------------------------------------------

@app.get("/fleets/<fleetId>/reliability-reports")
def list_fleet_reports(fleetId):
    authenticate(["FleetManager", "UptimeCoordinator", "WarrantyAdmin"])
    fleet = resolve_fleet(fleetId)
    limit, offset = get_pagination()
    rows = [r for r in db.reliability_reports.values() if r["fleet_id"] == fleet["id"]]
    fidx = request.args.get("from_ops_run_index")
    tidx = request.args.get("to_ops_run_index")
    if fidx is not None:
        try:
            fidx_i = int(fidx)
        except ValueError:
            raise api_err("ERR_INVALID_REQUEST", "from_ops_run_index must be an integer")
        rows = [r for r in rows if r["ops_run_index"] >= fidx_i]
    if tidx is not None:
        try:
            tidx_i = int(tidx)
        except ValueError:
            raise api_err("ERR_INVALID_REQUEST", "to_ops_run_index must be an integer")
        rows = [r for r in rows if r["ops_run_index"] <= tidx_i]
    page, total = paginate(rows, limit, offset)
    return success_list([report_out(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Cross-aggregate top-level GETs
# ---------------------------------------------------------------------------

def apply_filter(rows, field):
    v = request.args.get(field)
    if v is not None:
        rows = [r for r in rows if str(r.get(field)) == v]
    return rows


def top_list(collection, out, roles, filters):
    authenticate(roles)
    limit, offset = get_pagination()
    rows = list(getattr(db, collection).values())
    for f in filters:
        rows = apply_filter(rows, f)
    page, total = paginate(rows, limit, offset)
    return success_list([out(r) for r in page], total, limit, offset)


@app.get("/trucks/<truckId>")
def top_get_truck(truckId):
    authenticate(ALL_ROLES)
    t = db.trucks.get(truckId)
    if not t:
        raise api_err("ERR_TRUCK_NOT_FOUND", "Truck id does not exist")
    return success_object(truck_out(t))


@app.get("/trucks")
def top_list_trucks():
    return top_list("trucks", truck_out, ALL_ROLES,
                    ["fleet_id", "truck_status", "model_code"])


@app.get("/cases/<caseId>")
def top_get_case(caseId):
    authenticate(ALL_ROLES)
    c = db.cases.get(caseId)
    if not c:
        raise api_err("ERR_CASE_NOT_FOUND", "Case id does not exist")
    return success_object(case_out(c))


@app.get("/cases")
def top_list_cases():
    return top_list("cases", case_out, ALL_ROLES,
                    ["fleet_id", "truck_id", "dealer_id",
                     "opened_from_fault_event_id", "case_status"])


@app.get("/work-orders/<workOrderId>")
def top_get_work_order(workOrderId):
    authenticate(["FleetManager", "UptimeCoordinator", "WarrantyAdmin", "DealerAdvisor"])
    w = db.work_orders.get(workOrderId)
    if not w:
        raise api_err("ERR_WORK_ORDER_NOT_FOUND", "WorkOrder id does not exist")
    return success_object(work_order_out(w))


@app.get("/work-orders")
def top_list_work_orders():
    return top_list("work_orders", work_order_out,
                    ["FleetManager", "UptimeCoordinator", "WarrantyAdmin", "DealerAdvisor"],
                    ["case_id", "dealer_id", "bay_id", "work_order_status"])


@app.get("/part-orders/<partOrderId>")
def top_get_part_order(partOrderId):
    authenticate(["FleetManager", "UptimeCoordinator", "WarrantyAdmin",
                  "DealerAdvisor", "PartsManager"])
    p = db.part_orders.get(partOrderId)
    if not p:
        raise api_err("ERR_PART_ORDER_NOT_FOUND", "PartOrder id does not exist")
    return success_object(part_order_out(p))


@app.get("/part-orders")
def top_list_part_orders():
    return top_list("part_orders", part_order_out,
                    ["FleetManager", "UptimeCoordinator", "WarrantyAdmin",
                     "DealerAdvisor", "PartsManager"],
                    ["case_id", "part_order_status", "expedite_decision"])


@app.get("/claims/<claimId>")
def top_get_claim(claimId):
    authenticate(["FleetManager", "UptimeCoordinator", "WarrantyAdmin", "SupplierManager"])
    c = db.claims.get(claimId)
    if not c:
        raise api_err("ERR_CLAIM_NOT_FOUND", "WarrantyClaim id does not exist")
    return success_object(claim_out(c))


@app.get("/claims")
def top_list_claims():
    return top_list("claims", claim_out,
                    ["FleetManager", "UptimeCoordinator", "WarrantyAdmin", "SupplierManager"],
                    ["case_id", "submission_status", "recovery_status", "claim_type"])


@app.get("/part-returns/<partReturnId>")
def top_get_part_return(partReturnId):
    authenticate(["WarrantyAdmin", "SupplierManager", "DealerAdvisor"])
    p = db.part_returns.get(partReturnId)
    if not p:
        raise api_err("ERR_PART_RETURN_NOT_FOUND", "PartReturn id does not exist")
    return success_object(part_return_out(p))


@app.get("/part-returns")
def top_list_part_returns():
    return top_list("part_returns", part_return_out,
                    ["WarrantyAdmin", "SupplierManager", "DealerAdvisor"],
                    ["claim_id", "part_return_status"])


@app.get("/recoveries/<recoveryId>")
def top_get_recovery(recoveryId):
    authenticate(["SupplierManager", "WarrantyAdmin"])
    r = db.recoveries.get(recoveryId)
    if not r:
        raise api_err("ERR_RECOVERY_NOT_FOUND", "SupplierRecovery id does not exist")
    return success_object(recovery_out(r))


@app.get("/recoveries")
def top_list_recoveries():
    return top_list("recoveries", recovery_out,
                    ["SupplierManager", "WarrantyAdmin"],
                    ["claim_id", "part_return_id", "recovery_status"])


@app.get("/coverage-contracts/<contractId>")
def top_get_contract(contractId):
    authenticate(["FleetManager", "WarrantyAdmin", "UptimeCoordinator"])
    c = db.coverage_contracts.get(contractId)
    if not c:
        raise api_err("ERR_COVERAGE_CONTRACT_NOT_FOUND", "CoverageContract id does not exist")
    return success_object(contract_out(c))


@app.get("/coverage-contracts")
def top_list_contracts():
    return top_list("coverage_contracts", contract_out,
                    ["FleetManager", "WarrantyAdmin", "UptimeCoordinator"],
                    ["truck_id", "contract_status", "contract_type"])


@app.get("/fault-events/<faultEventId>")
def top_get_fault_event(faultEventId):
    authenticate(["UptimeCoordinator", "FleetManager", "DealerAdvisor", "WarrantyAdmin"])
    e = db.fault_events.get(faultEventId)
    if not e:
        raise api_err("ERR_FAULT_EVENT_NOT_FOUND", "FaultEvent id does not exist")
    return success_object(fault_event_out(e))


@app.get("/fault-events")
def top_list_fault_events():
    return top_list("fault_events", fault_event_out,
                    ["UptimeCoordinator", "FleetManager", "DealerAdvisor", "WarrantyAdmin"],
                    ["truck_id", "event_status", "severity"])


@app.get("/campaign-completions/<completionId>")
def top_get_completion(completionId):
    authenticate(["UptimeCoordinator", "FleetManager", "WarrantyAdmin"])
    c = db.campaign_completions.get(completionId)
    if not c:
        raise api_err("ERR_CAMPAIGN_COMPLETION_NOT_FOUND",
                      "CampaignCompletion id does not exist")
    return success_object(completion_out(c))


@app.get("/campaign-completions")
def top_list_completions():
    return top_list("campaign_completions", completion_out,
                    ["UptimeCoordinator", "FleetManager", "WarrantyAdmin"],
                    ["campaign_id", "truck_id", "case_id", "completion_status"])


@app.get("/bays/<bayId>")
def top_get_bay(bayId):
    authenticate(["FleetManager", "UptimeCoordinator", "DealerAdvisor", "PartsManager"])
    b = db.bays.get(bayId)
    if not b:
        raise api_err("ERR_BAY_NOT_FOUND", "ServiceBay id does not exist")
    return success_object(bay_out(b))


@app.get("/bays")
def top_list_bays():
    return top_list("bays", bay_out,
                    ["FleetManager", "UptimeCoordinator", "DealerAdvisor", "PartsManager"],
                    ["dealer_id", "bay_status"])


@app.get("/reliability-reports/<reportId>")
def top_get_report(reportId):
    authenticate(["FleetManager", "UptimeCoordinator", "WarrantyAdmin"])
    r = db.reliability_reports.get(reportId)
    if not r:
        raise api_err("ERR_INVALID_REQUEST", "ReliabilityReport id does not exist")
    return success_object(report_out(r))


@app.get("/reliability-reports")
def top_list_reports():
    return top_list("reliability_reports", report_out,
                    ["FleetManager", "UptimeCoordinator", "WarrantyAdmin"],
                    ["fleet_id"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
