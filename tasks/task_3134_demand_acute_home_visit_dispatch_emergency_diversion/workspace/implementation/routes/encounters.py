"""On-site encounters, diagnostic orders, dispositions, facility transports."""
import db
import helpers as H
import services as S
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_ENCOUNTER_INVALID_STATE,
    ERR_ENCOUNTER_HAS_ORDERS, ERR_UNRESOLVED_DIAGNOSTICS, ERR_FORMULARY_CAP_EXCEEDED,
    ERR_PREAUTH_REQUIRED, ERR_RESULT_REQUIRED, ERR_AMEND_NO_CHANGE, ERR_SOD_VIOLATION,
    ERR_FACILITY_REQUIRED, ERR_RATIONALE_TOO_SHORT, ERR_TRANSPORT_INVALID_STATE,
)
from middleware import require_roles
from response import success_object, success_list

ENC_LIST_ROLES = {"PlatformAdmin", "Dispatcher", "TriageNurse", "AdvancedPracticeProvider"}
ENC_GET_ROLES = ENC_LIST_ROLES | {"SupervisingPhysician"}
ORDER_READ_ROLES = {"PlatformAdmin", "AdvancedPracticeProvider", "FieldTechnician",
                    "SupervisingPhysician", "BillingSpecialist"}
DECISION_READ_ROLES = {"PlatformAdmin", "TriageNurse", "AdvancedPracticeProvider"}
TRANSPORT_READ_ROLES = {"PlatformAdmin", "Dispatcher", "TriageNurse"}

ORDER_KINDS = {"POCT", "IMAGING", "IV_INFUSION"}
DISPOSITIONS = {"DISCHARGE_HOME", "ESCALATE_TO_FACILITY"}
TRANSPORT_MODES = {"GROUND_AMBULANCE", "PRIVATE_VEHICLE", "WHEELCHAIR_VAN"}
RESOLVED_ORDER_STATES = {"RESULTED", "VERIFIED", "AMENDED", "CANCELLED"}
IV_CAP_STATES = {"ORDERED", "COLLECTED", "RESULTED", "VERIFIED", "AMENDED"}


def _get_encounter(eid):
    enc = db.STORES["encounters"].get(eid)
    if enc is None:
        raise_err(ERR_NOT_FOUND, "encounter not found")
    return enc


def _get_order(oid):
    order = db.STORES["diagnostic_orders"].get(oid)
    if order is None:
        raise_err(ERR_NOT_FOUND, "diagnostic order not found")
    return order


def register(app):

    # ---------------- Encounters ----------------
    @app.get("/dh/encounters")
    def list_encounters():
        require_roles(ENC_LIST_ROLES)
        with db.lock():
            S.run_system_sweeps()
            page, total, limit, offset = H.list_response(
                list(db.STORES["encounters"].values()),
                filters={
                    "visit_request_id": H.request.args.get("visit_request_id"),
                    "dispatch_assignment_id": H.request.args.get("dispatch_assignment_id"),
                    "status": H.request.args.get("status"),
                },
            )
        return success_list(page, total, limit, offset)

    @app.get("/dh/encounters/<eid>")
    def get_encounter(eid):
        require_roles(ENC_GET_ROLES)
        with db.lock():
            S.run_system_sweeps()
            enc = _get_encounter(eid)
        return success_object(enc)

    @app.get("/dh/encounters/<eid>/diagnostic-orders")
    def list_encounter_orders(eid):
        require_roles(ORDER_READ_ROLES)
        with db.lock():
            S.run_system_sweeps()
            _get_encounter(eid)
            items = [o for o in db.STORES["diagnostic_orders"].values() if o["encounter_id"] == eid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.post("/dh/encounters/<eid>/diagnostic-orders")
    def create_diagnostic_order(eid):
        require_roles({"AdvancedPracticeProvider"})
        body = H.get_json_body()
        order_kind = H.require(body, "order_kind", "string", enum=ORDER_KINDS)
        code = H.require(body, "code", "string")
        units = H.require(body, "units", "integer")
        if units < 1:
            raise_err(ERR_INVALID_REQUEST, "units must be at least 1")
        preauth_obtained = H.optional(body, "physician_preauth_obtained", False, ftype="boolean")
        preauth_by = H.optional(body, "physician_preauth_by", None)
        if preauth_by is not None:
            H.check_type("physician_preauth_by", preauth_by, "string")
        # preauth_by required iff preauth_obtained
        if preauth_obtained and not preauth_by:
            raise_err(ERR_PREAUTH_REQUIRED, "physician_preauth_by required when preauth obtained")
        with db.lock():
            S.run_system_sweeps()
            enc = _get_encounter(eid)
            if enc["status"] not in ("STARTED", "DIAGNOSTICS"):
                raise_err(ERR_ENCOUNTER_INVALID_STATE,
                          "encounter must be STARTED or DIAGNOSTICS to accept orders")
            vr = db.STORES["visit_requests"].get(enc["visit_request_id"])
            entry = None
            if order_kind == "IV_INFUSION":
                entry = S.formulary_entry_for_order(vr, enc, code)
                if entry is not None:
                    # Cap check (priority 17) BEFORE preauth check (priority 18).
                    existing_units = sum(
                        o["units"] for o in S.orders_for_encounter(eid)
                        if o["order_kind"] == "IV_INFUSION" and o["code"] == code
                        and o["status"] in IV_CAP_STATES
                    )
                    if existing_units + units > entry["max_units_per_visit"]:
                        raise_err(ERR_FORMULARY_CAP_EXCEEDED,
                                  "per-visit formulary cap exceeded for this drug")
                    if entry.get("requires_physician_preauth"):
                        da = db.STORES["dispatch_assignments"].get(enc["dispatch_assignment_id"])
                        team = db.STORES["care_teams"].get(da["care_team_id"]) if da else None
                        expected_md = team["supervising_physician_user_id"] if team else None
                        if not preauth_obtained or preauth_by != expected_md:
                            raise_err(ERR_PREAUTH_REQUIRED,
                                      "supervising physician pre-authorization required")
            order = H.new_entity()
            order.update({
                "encounter_id": eid,
                "order_kind": order_kind,
                "code": code,
                "units": units,
                "result_value": None,
                "physician_preauth_obtained": preauth_obtained,
                "physician_preauth_by": preauth_by,
                "unit_price_cents": None,
                "line_amount_cents": None,
                "status": "ORDERED",
                "resulted_by": None,
            })
            db.STORES["diagnostic_orders"][order["id"]] = order
            if enc["status"] == "STARTED":
                enc["status"] = "DIAGNOSTICS"
                H.touch(enc)
        return success_object(order, 201)

    @app.post("/dh/encounters/<eid>/begin-disposition-review")
    def begin_disposition_review(eid):
        require_roles({"AdvancedPracticeProvider"})
        with db.lock():
            S.run_system_sweeps()
            enc = _get_encounter(eid)
            if enc["status"] not in ("STARTED", "DIAGNOSTICS"):
                raise_err(ERR_ENCOUNTER_INVALID_STATE,
                          "encounter must be STARTED or DIAGNOSTICS")
            for order in S.orders_for_encounter(eid):
                if order["status"] not in RESOLVED_ORDER_STATES:
                    raise_err(ERR_UNRESOLVED_DIAGNOSTICS,
                              "all diagnostic orders must be resolved before disposition review")
            enc["status"] = "DISPOSITION_REVIEW"
            H.touch(enc)
        return success_object(enc)

    @app.post("/dh/encounters/<eid>/disposition-decisions")
    def create_disposition_decision(eid):
        require_roles({"AdvancedPracticeProvider"})
        body = H.get_json_body()
        disposition = H.require(body, "disposition", "string", enum=DISPOSITIONS)
        rationale = H.require(body, "rationale", "string")
        if len(rationale) < 20:
            raise_err(ERR_RATIONALE_TOO_SHORT, "rationale must be at least 20 characters")
        receiving_facility_id = H.optional(body, "receiving_facility_id", None)
        if receiving_facility_id is not None:
            H.check_type("receiving_facility_id", receiving_facility_id, "string")
        transport_mode = H.optional(body, "transport_mode", None)
        if transport_mode is not None:
            H.check_type("transport_mode", transport_mode, "string")
            if transport_mode not in TRANSPORT_MODES:
                raise_err(ERR_INVALID_REQUEST, "invalid transport_mode")
        if disposition == "ESCALATE_TO_FACILITY" and not receiving_facility_id:
            raise_err(ERR_FACILITY_REQUIRED, "receiving_facility_id required for escalation")
        with db.lock():
            S.run_system_sweeps()
            enc = _get_encounter(eid)
            if enc["status"] != "DISPOSITION_REVIEW":
                raise_err(ERR_ENCOUNTER_INVALID_STATE,
                          "encounter must be in DISPOSITION_REVIEW")
            vr = db.STORES["visit_requests"].get(enc["visit_request_id"])
            decision = H.new_entity()
            decision.update({
                "encounter_id": eid,
                "visit_request_id": vr["id"],
                "disposition": disposition,
                "rationale": rationale,
                "receiving_facility_id": receiving_facility_id,
                "decided_at": H.logical_now_str(),
                "transport_mode": transport_mode,
            })
            db.STORES["disposition_decisions"][decision["id"]] = decision
            S.disposition_cascade(enc, decision)
        return success_object(decision, 201)

    @app.post("/dh/encounters/<eid>/abort")
    def abort_encounter(eid):
        require_roles({"AdvancedPracticeProvider"})
        with db.lock():
            S.run_system_sweeps()
            enc = _get_encounter(eid)
            if enc["status"] != "STARTED":
                raise_err(ERR_ENCOUNTER_INVALID_STATE, "encounter must be STARTED to abort")
            if S.orders_for_encounter(eid):
                raise_err(ERR_ENCOUNTER_HAS_ORDERS,
                          "cannot abort an encounter with diagnostic orders")
            enc["ended_at"] = H.logical_now_str()
            enc["status"] = "ABORTED"
            H.touch(enc)
            da = db.STORES["dispatch_assignments"].get(enc["dispatch_assignment_id"])
            if da is not None:
                S.complete_dispatch(da["id"])
            vr = db.STORES["visit_requests"].get(enc["visit_request_id"])
            vr["status"] = "TRIAGED"
            vr["assigned_care_team_id"] = None
            vr["sla_deadline_at"] = None
            vr["sla_breached"] = False
            H.touch(vr)
        return success_object(enc)

    @app.get("/dh/encounters/<eid>/disposition-decisions")
    def list_encounter_decisions(eid):
        require_roles(DECISION_READ_ROLES)
        with db.lock():
            S.run_system_sweeps()
            _get_encounter(eid)
            items = [d for d in db.STORES["disposition_decisions"].values()
                     if d["encounter_id"] == eid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    # ---------------- Diagnostic orders ----------------
    @app.get("/dh/diagnostic-orders/<oid>")
    def get_order(oid):
        require_roles(ORDER_READ_ROLES)
        with db.lock():
            S.run_system_sweeps()
            order = _get_order(oid)
        return success_object(order)

    @app.post("/dh/diagnostic-orders/<oid>/collect")
    def collect_order(oid):
        require_roles({"FieldTechnician"})
        with db.lock():
            S.run_system_sweeps()
            order = _get_order(oid)
            if order["status"] != "ORDERED":
                raise_err(ERR_INVALID_REQUEST_STATE(), "order is not ORDERED")
            order["status"] = "COLLECTED"
            H.touch(order)
        return success_object(order)

    @app.post("/dh/diagnostic-orders/<oid>/result")
    def result_order(oid):
        user_id, _ = require_roles({"FieldTechnician"})
        body = H.get_json_body()
        if "result_value" not in body or body["result_value"] is None:
            raise_err(ERR_RESULT_REQUIRED, "result_value is required")
        result_value = body["result_value"]
        H.check_type("result_value", result_value, "string")
        with db.lock():
            S.run_system_sweeps()
            order = _get_order(oid)
            if order["status"] not in ("COLLECTED", "AMENDED"):
                raise_err(ERR_INVALID_REQUEST_STATE(),
                          "order must be COLLECTED or AMENDED to result")
            enc = db.STORES["encounters"].get(order["encounter_id"])
            vr = db.STORES["visit_requests"].get(enc["visit_request_id"])
            if order["order_kind"] == "IV_INFUSION":
                entry = S.formulary_entry_for_order(vr, enc, order["code"])
                if entry is not None:
                    order["unit_price_cents"] = entry["unit_price_cents"]
            else:
                order["unit_price_cents"] = S.list_price_for_code(order["code"])
            order["result_value"] = result_value
            order["status"] = "RESULTED"
            order["resulted_by"] = user_id
            order["line_amount_cents"] = S.line_amount(order)
            H.touch(order)
            S.recompute_claim_for_visit(vr["id"])
        return success_object(order)

    @app.post("/dh/diagnostic-orders/<oid>/verify")
    def verify_order(oid):
        user_id, _ = require_roles({"SupervisingPhysician"})
        with db.lock():
            S.run_system_sweeps()
            order = _get_order(oid)
            if order["status"] != "RESULTED":
                raise_err(ERR_INVALID_REQUEST_STATE(), "order is not RESULTED")
            if order.get("resulted_by") is not None and order["resulted_by"] == user_id:
                raise_err(ERR_SOD_VIOLATION,
                          "verifier must differ from the user who resulted the order")
            order["status"] = "VERIFIED"
            H.touch(order)
            enc = db.STORES["encounters"].get(order["encounter_id"])
            S.recompute_claim_for_visit(enc["visit_request_id"])
        return success_object(order)

    @app.post("/dh/diagnostic-orders/<oid>/amend")
    def amend_order(oid):
        user_id, _ = require_roles({"FieldTechnician"})
        body = H.get_json_body()
        if "result_value" not in body or body["result_value"] is None:
            raise_err(ERR_RESULT_REQUIRED, "result_value is required")
        result_value = body["result_value"]
        H.check_type("result_value", result_value, "string")
        with db.lock():
            S.run_system_sweeps()
            order = _get_order(oid)
            if order["status"] != "RESULTED":
                raise_err(ERR_INVALID_REQUEST_STATE(), "order is not RESULTED")
            if result_value == order.get("result_value"):
                raise_err(ERR_AMEND_NO_CHANGE, "new result_value is identical to current")
            order["result_value"] = result_value
            order["status"] = "AMENDED"
            H.touch(order)
            enc = db.STORES["encounters"].get(order["encounter_id"])
            S.recompute_claim_for_visit(enc["visit_request_id"])
        return success_object(order)

    @app.post("/dh/diagnostic-orders/<oid>/cancel")
    def cancel_order(oid):
        require_roles({"AdvancedPracticeProvider"})
        with db.lock():
            S.run_system_sweeps()
            order = _get_order(oid)
            if order["status"] != "ORDERED":
                raise_err(ERR_INVALID_REQUEST_STATE(), "order is not ORDERED")
            order["status"] = "CANCELLED"
            H.touch(order)
            enc = db.STORES["encounters"].get(order["encounter_id"])
            S.recompute_claim_for_visit(enc["visit_request_id"])
        return success_object(order)

    @app.get("/dh/diagnostic-orders/<oid>/claim-lines")
    def list_order_claim_lines(oid):
        require_roles({"PlatformAdmin", "BillingSpecialist", "PayerAdjudicator"})
        with db.lock():
            S.run_system_sweeps()
            _get_order(oid)
            items = [l for l in db.STORES["claim_lines"].values()
                     if l.get("ref_diagnostic_order_id") == oid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    # ---------------- Disposition decisions / facility transports ----------------
    @app.get("/dh/disposition-decisions/<did>")
    def get_decision(did):
        require_roles(DECISION_READ_ROLES)
        with db.lock():
            S.run_system_sweeps()
            d = db.STORES["disposition_decisions"].get(did)
            if d is None:
                raise_err(ERR_NOT_FOUND, "disposition decision not found")
        return success_object(d)

    @app.get("/dh/disposition-decisions/<did>/facility-transport")
    def get_decision_transport(did):
        require_roles(TRANSPORT_READ_ROLES)
        with db.lock():
            S.run_system_sweeps()
            d = db.STORES["disposition_decisions"].get(did)
            if d is None:
                raise_err(ERR_NOT_FOUND, "disposition decision not found")
            items = [t for t in db.STORES["facility_transports"].values()
                     if t["disposition_decision_id"] == did]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.post("/dh/facility-transports/<tid>/mark-arrived")
    def mark_transport_arrived(tid):
        require_roles({"Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            t = db.STORES["facility_transports"].get(tid)
            if t is None:
                raise_err(ERR_NOT_FOUND, "facility transport not found")
            if t["status"] != "DISPATCHED":
                raise_err(ERR_TRANSPORT_INVALID_STATE, "transport is not DISPATCHED")
            t["status"] = "ARRIVED_AT_FACILITY"
            t["arrived_at_facility_at"] = H.logical_now_str()
            H.touch(t)
            vr = db.STORES["visit_requests"].get(t["visit_request_id"])
            if vr is not None and vr["status"] == "ESCALATED_TRANSPORT":
                vr["status"] = "CLAIM_DRAFT"
                H.touch(vr)
        return success_object(t)

    @app.post("/dh/facility-transports/<tid>/cancel")
    def cancel_transport(tid):
        require_roles({"Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            t = db.STORES["facility_transports"].get(tid)
            if t is None:
                raise_err(ERR_NOT_FOUND, "facility transport not found")
            if t["status"] != "DISPATCHED":
                raise_err(ERR_TRANSPORT_INVALID_STATE, "transport is not DISPATCHED")
            t["status"] = "CANCELLED"
            H.touch(t)
            vr = db.STORES["visit_requests"].get(t["visit_request_id"])
            if vr is not None and vr["status"] == "ESCALATED_TRANSPORT":
                vr["status"] = "ON_SCENE"
                H.touch(vr)
        return success_object(t)


def ERR_INVALID_REQUEST_STATE():
    """There is no DiagnosticOrder-specific state error id in the catalog; the
    generic encounter state code is used for order state mismatches."""
    from errors import ERR_ENCOUNTER_INVALID_STATE
    return ERR_ENCOUNTER_INVALID_STATE
