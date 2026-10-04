"""Routes: emergency events, prepositioned modules, valuation snapshots, distribution reports."""
from decimal import Decimal

from flask import request

from common import (
    ApiError, DONORS, LOTS, SITES, SHIPMENTS, DECISIONS, LINES, EVENTS, MODULES,
    SNAPSHOTS, REPORTS, REQUESTS, LOCK,
    require_roles, body, ok, ok_list,
    req_str, req_int, req_list, parse_dt,
    stamp_new, bump, sorted_items, get_or_404,
    event_json, module_json, snapshot_json, report_json, money2, clock,
)

INTENDED_USES = {"PRIMARY_CARE", "TRAUMA", "CHOLERA", "MATERNAL", "COLD_CHAIN_VACCINE"}
EVENT_GET_ONE_ROLES = ("EmergencyManager", "AllocationOfficer", "ComplianceOfficer",
                       "PlatformAdmin", "SiteCoordinator")
EVENT_LIST_ROLES = ("EmergencyManager", "AllocationOfficer", "ComplianceOfficer", "PlatformAdmin")
MODULE_ROLES = ("EmergencyManager", "PlatformAdmin", "ComplianceOfficer")
SNAPSHOT_ROLES = ("DonorReportingOfficer", "ComplianceOfficer", "PlatformAdmin")
REPORT_ROLES = ("SiteCoordinator", "ComplianceOfficer", "DonorReportingOfficer", "PlatformAdmin")


def register(app):

    # ---------------------------------------------------------- emergency events
    @app.post("/medicine-relief/emergency-events")
    def create_event():
        require_roles("EmergencyManager")
        b = body()
        severity = req_int(b, "severity")
        if severity < 1 or severity > 5:
            raise ApiError("ERR_INVALID_REQUEST", 400, "severity must be between 1 and 5")
        codes = req_list(b, "affected_country_codes")
        if any(not isinstance(c, str) for c in codes):
            raise ApiError("ERR_INVALID_REQUEST", 400, "affected_country_codes must be an array of strings")
        surge_raw = req_str(b, "surge_window_ends_at")
        surge_dt = parse_dt(surge_raw)
        ev = {
            "event_name": req_str(b, "event_name"),
            "severity": severity,
            "affected_country_codes": codes,
            "declared_at": clock(),
            "surge_window_ends_at": surge_dt,
            "status": "DECLARED",
        }
        with LOCK:
            stamp_new(ev)
            EVENTS[ev["id"]] = ev
            return ok(event_json(ev), 201)

    @app.get("/medicine-relief/emergency-events/<event_id>")
    def get_event(event_id):
        require_roles(*EVENT_GET_ONE_ROLES)
        with LOCK:
            return ok(event_json(get_or_404(EVENTS, event_id, "EmergencyEvent")))

    @app.get("/medicine-relief/emergency-events")
    def list_events():
        require_roles(*EVENT_LIST_ROLES)
        status = request.args.get("status")
        severity = request.args.get("severity")
        with LOCK:
            items = [e for e in sorted_items(EVENTS)
                     if (status is None or e["status"] == status)
                     and (severity is None or str(e["severity"]) == severity)]
            return ok_list([event_json(e) for e in items])

    @app.post("/medicine-relief/emergency-events/<event_id>/activate")
    def activate_event(event_id):
        require_roles("EmergencyManager")
        with LOCK:
            ev = get_or_404(EVENTS, event_id, "EmergencyEvent")
            if ev["status"] != "DECLARED":
                raise ApiError("ERR_INVALID_STATE", 409, "Event is not DECLARED")
            ev["status"] = "ACTIVE"
            bump(ev)
            return ok(event_json(ev))

    @app.post("/medicine-relief/emergency-events/<event_id>/close")
    def close_event(event_id):
        require_roles("EmergencyManager")
        with LOCK:
            ev = get_or_404(EVENTS, event_id, "EmergencyEvent")
            if ev["status"] != "STAND_DOWN":
                raise ApiError("ERR_INVALID_STATE", 409, "Event is not STAND_DOWN")
            terminal = {"REJECTED", "CANCELLED"}
            for req in REQUESTS.values():
                if req["emergency_event_id"] == ev["id"] and req["status"] not in terminal:
                    raise ApiError("ERR_INVALID_STATE", 409,
                                   "Not all referencing allocation requests are in a terminal status")
            ev["status"] = "CLOSED"
            bump(ev)
            return ok(event_json(ev))

    # ----------------------------------------------------- prepositioned modules
    @app.post("/medicine-relief/prepositioned-modules")
    def create_module():
        require_roles("EmergencyManager", "PlatformAdmin")
        b = body()
        mod = {
            "module_code": req_str(b, "module_code"),
            "intended_use": req_str(b, "intended_use"),
            "holding_country_code": req_str(b, "holding_country_code"),
            "quantity_on_hand": 0,
            "reserved_for_event_id": None,
            "status": "AVAILABLE",
        }
        if mod["intended_use"] not in INTENDED_USES:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           f"intended_use must be one of {sorted(INTENDED_USES)}")
        with LOCK:
            stamp_new(mod)
            MODULES[mod["id"]] = mod
            return ok(module_json(mod), 201)

    @app.get("/medicine-relief/prepositioned-modules/<module_id>")
    def get_module(module_id):
        require_roles(*MODULE_ROLES)
        with LOCK:
            return ok(module_json(get_or_404(MODULES, module_id, "PrepositionedModule")))

    @app.get("/medicine-relief/prepositioned-modules")
    def list_modules():
        require_roles(*MODULE_ROLES)
        status = request.args.get("status")
        iu = request.args.get("intended_use")
        hc = request.args.get("holding_country_code")
        rid = request.args.get("reserved_for_event_id")
        with LOCK:
            items = [m for m in sorted_items(MODULES)
                     if (status is None or m["status"] == status)
                     and (iu is None or m["intended_use"] == iu)
                     and (hc is None or m["holding_country_code"] == hc)
                     and (rid is None or m["reserved_for_event_id"] == rid)]
            return ok_list([module_json(m) for m in items])

    @app.post("/medicine-relief/prepositioned-modules/<module_id>/reserve")
    def reserve_module(module_id):
        require_roles("EmergencyManager")
        b = body()
        event_id = req_str(b, "event_id")
        with LOCK:
            mod = get_or_404(MODULES, module_id, "PrepositionedModule")
            ev = EVENTS.get(event_id)
            if ev is None:
                raise ApiError("ERR_NOT_FOUND", 404, f"EmergencyEvent not found: {event_id}")
            if mod["status"] != "AVAILABLE":
                raise ApiError("ERR_INVALID_STATE", 409, "Module is not AVAILABLE")
            if ev["status"] != "ACTIVE":
                raise ApiError("ERR_EMERGENCY_NOT_ACTIVE", 409, "Event is not ACTIVE")
            if mod["holding_country_code"] not in ev["affected_country_codes"] \
                    and ev["severity"] < 4:
                raise ApiError("ERR_MODULE_OUT_OF_REGION", 422,
                               "Module is out of region and event severity is below 4")
            mod["status"] = "RESERVED"
            mod["reserved_for_event_id"] = ev["id"]
            bump(mod)
            return ok(module_json(mod))

    @app.post("/medicine-relief/prepositioned-modules/<module_id>/deploy")
    def deploy_module(module_id):
        require_roles("EmergencyManager")
        with LOCK:
            mod = get_or_404(MODULES, module_id, "PrepositionedModule")
            if mod["status"] != "RESERVED":
                raise ApiError("ERR_INVALID_STATE", 409, "Module is not RESERVED")
            ev = EVENTS.get(mod["reserved_for_event_id"])
            if ev is None or ev["status"] != "ACTIVE":
                raise ApiError("ERR_EMERGENCY_NOT_ACTIVE", 409, "Event is not ACTIVE")
            mod["status"] = "DEPLOYED"
            bump(mod)
            return ok(module_json(mod))

    @app.post("/medicine-relief/prepositioned-modules/<module_id>/consume")
    def consume_module(module_id):
        require_roles("EmergencyManager")
        with LOCK:
            mod = get_or_404(MODULES, module_id, "PrepositionedModule")
            if mod["status"] != "DEPLOYED":
                raise ApiError("ERR_INVALID_STATE", 409, "Module is not DEPLOYED")
            ev = EVENTS.get(mod["reserved_for_event_id"])
            if ev is None or ev["status"] not in ("ACTIVE", "STAND_DOWN"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Event must be ACTIVE or STAND_DOWN to consume the module")
            mod["status"] = "CONSUMED"
            mod["quantity_on_hand"] = 0
            bump(mod)
            return ok(module_json(mod))

    # ------------------------------------------------------- valuation snapshots
    @app.post("/medicine-relief/valuation-snapshots")
    def create_snapshot():
        require_roles(*SNAPSHOT_ROLES)
        b = body()
        donor_id = req_str(b, "donor_id")
        period = req_str(b, "snapshot_period")
        method = req_str(b, "method")
        if method not in ("ACQUISITION_COST", "WHOLESALE_REFERENCE"):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "method must be ACQUISITION_COST or WHOLESALE_REFERENCE")
        with LOCK:
            get_or_404(DONORS, donor_id, "ManufacturerDonor")
            total = Decimal("0")
            count = 0
            for lot in LOTS.values():
                if lot["donor_id"] != donor_id:
                    continue
                if lot["lot_posture"] == "RECALLED":
                    continue
                if lot["intake_recorded_at"].strftime("%Y-%m") != period:
                    continue
                unit = lot["unit_acquisition_value_usd"] if method == "ACQUISITION_COST" \
                    else lot["unit_wholesale_value_usd"]
                total += money2(Decimal(lot["quantity_received"]) * Decimal(str(unit)))
                count += 1
            snap = {
                "snapshot_period": period,
                "donor_id": donor_id,
                "method": method,
                "total_value_usd": float(total),
                "lot_count": count,
                "generated_at": clock(),
            }
            stamp_new(snap)
            SNAPSHOTS[snap["id"]] = snap
            return ok(snapshot_json(snap), 201)

    @app.get("/medicine-relief/valuation-snapshots/<snapshot_id>")
    def get_snapshot(snapshot_id):
        require_roles(*SNAPSHOT_ROLES)
        with LOCK:
            return ok(snapshot_json(get_or_404(SNAPSHOTS, snapshot_id, "ValuationSnapshot")))

    @app.get("/medicine-relief/valuation-snapshots")
    def list_snapshots():
        require_roles(*SNAPSHOT_ROLES)
        donor_id = request.args.get("donor_id")
        period = request.args.get("snapshot_period")
        method = request.args.get("method")
        with LOCK:
            items = [s for s in sorted_items(SNAPSHOTS)
                     if (donor_id is None or s["donor_id"] == donor_id)
                     and (period is None or s["snapshot_period"] == period)
                     and (method is None or s["method"] == method)]
            return ok_list([snapshot_json(s) for s in items])

    # ----------------------------------------------------- distribution reports
    @app.post("/medicine-relief/distribution-reports")
    def create_report():
        uid, _ = require_roles("SiteCoordinator")
        b = body()
        site_id = req_str(b, "site_id")
        shipment_id = req_str(b, "shipment_id")
        reporting_period = req_str(b, "reporting_period")
        units_distributed = req_int(b, "units_distributed")
        patients_reached = req_int(b, "patients_reached")
        wastage_units = req_int(b, "wastage_units")
        with LOCK:
            get_or_404(SITES, site_id, "RecipientSite")
            sh = get_or_404(SHIPMENTS, shipment_id, "Shipment")
            if uid != site_id:
                raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                               "Only the site's coordinator may file its distribution report")
            if sh["status"] != "DELIVERED":
                raise ApiError("ERR_INVALID_STATE", 409, "Shipment is not DELIVERED")
            rep = {
                "site_id": site_id,
                "shipment_id": shipment_id,
                "reporting_period": reporting_period,
                "units_distributed": units_distributed,
                "patients_reached": patients_reached,
                "wastage_units": wastage_units,
                "submitted_by_user_id": uid,
                "status": "DRAFT",
                "reviewed_by_user_id": None,
            }
            stamp_new(rep)
            REPORTS[rep["id"]] = rep
            return ok(report_json(rep), 201)

    @app.get("/medicine-relief/distribution-reports/<report_id>")
    def get_report(report_id):
        require_roles(*REPORT_ROLES)
        with LOCK:
            return ok(report_json(get_or_404(REPORTS, report_id, "DistributionReport")))

    @app.get("/medicine-relief/distribution-reports")
    def list_reports():
        require_roles(*REPORT_ROLES)
        site_id = request.args.get("site_id")
        shipment_id = request.args.get("shipment_id")
        status = request.args.get("status")
        period = request.args.get("reporting_period")
        with LOCK:
            items = [r for r in sorted_items(REPORTS)
                     if (site_id is None or r["site_id"] == site_id)
                     and (shipment_id is None or r["shipment_id"] == shipment_id)
                     and (status is None or r["status"] == status)
                     and (period is None or r["reporting_period"] == period)]
            return ok_list([report_json(r) for r in items])

    @app.post("/medicine-relief/distribution-reports/<report_id>/submit")
    def submit_report(report_id):
        uid, _ = require_roles("SiteCoordinator")
        with LOCK:
            rep = get_or_404(REPORTS, report_id, "DistributionReport")
            if uid != rep["site_id"]:
                raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                               "Only the site's coordinator may submit this report")
            if rep["status"] != "DRAFT":
                raise ApiError("ERR_INVALID_STATE", 409, "Report is not DRAFT")
            sh = SHIPMENTS.get(rep["shipment_id"])
            delivered_qty = 0
            if sh is not None:
                for line in LINES.values():
                    if line["decision_id"] == sh["allocation_decision_id"] \
                            and line["status"] == "DELIVERED":
                        delivered_qty += line["quantity"]
            previously_reported = sum(
                r["units_distributed"] + r["wastage_units"]
                for r in REPORTS.values()
                if r["shipment_id"] == rep["shipment_id"]
                and r["id"] != rep["id"]
                and r["status"] in ("SUBMITTED", "ACCEPTED")
            )
            if rep["units_distributed"] + rep["wastage_units"] + previously_reported > delivered_qty:
                raise ApiError("ERR_OVERREPORTED", 422,
                               "Cumulative reported units exceed the shipment's delivered quantity")
            rep["status"] = "SUBMITTED"
            bump(rep)
            return ok(report_json(rep))

    @app.post("/medicine-relief/distribution-reports/<report_id>/accept")
    def accept_report(report_id):
        uid, _ = require_roles("ComplianceOfficer")
        with LOCK:
            rep = get_or_404(REPORTS, report_id, "DistributionReport")
            if rep["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", 409, "Report is not SUBMITTED")
            if uid == rep["submitted_by_user_id"]:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                               "Reviewer must differ from the submitting user")
            rep["status"] = "ACCEPTED"
            rep["reviewed_by_user_id"] = uid
            bump(rep)
            return ok(report_json(rep))

    @app.post("/medicine-relief/distribution-reports/<report_id>/reject")
    def reject_report(report_id):
        uid, _ = require_roles("ComplianceOfficer")
        b = body()
        from common import opt_str
        opt_str(b, "reason")
        with LOCK:
            rep = get_or_404(REPORTS, report_id, "DistributionReport")
            if rep["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", 409, "Report is not SUBMITTED")
            if uid == rep["submitted_by_user_id"]:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                               "Reviewer must differ from the submitting user")
            rep["status"] = "REJECTED"
            rep["reviewed_by_user_id"] = uid
            bump(rep)
            return ok(report_json(rep))
