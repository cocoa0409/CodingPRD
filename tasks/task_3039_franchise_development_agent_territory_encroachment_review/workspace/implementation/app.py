"""Franchise Development Agent Territory & Encroachment Review API."""
import os
from datetime import timedelta

from flask import Flask, jsonify, request

import core
from core import (
    ApiError, DB, apply_lazy, bad, body, caller, clock_now, clock_set, err,
    forbid, get_or_404, make_entity, ok_list, ok_object, paginate, parse_dt,
    req_dt, req_enum, req_field, req_int, req_num, req_str, require_roles,
    touch,
)
import services as svc

app = Flask(__name__)


@app.before_request
def _lazy():
    apply_lazy()


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify(core.error_body(e.error_id, e.message)), e.http_status


@app.errorhandler(404)
def _nf(e):
    return jsonify(core.error_body("ERR_INVALID_REQUEST", "Resource not found")), 404


@app.errorhandler(405)
def _na(e):
    return jsonify(core.error_body("ERR_INVALID_REQUEST", "Method not allowed")), 405


@app.errorhandler(500)
def _ise(e):
    return jsonify(core.error_body("ERR_INVALID_REQUEST", "Internal server error")), 500


def invalid_state(message="Resource is not in a valid state for this transition"):
    raise err("ERR_INVALID_STATE", 409, message)


# ===========================================================================
# Platform / logical clock
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    data = body()
    dt = parse_dt(data.get("to_iso8601"))
    if dt is None:
        bad("to_iso8601 must be an ISO-8601 datetime")
    clock_set(dt)
    apply_lazy()
    return ok_object({})


# ===========================================================================
# Territories
# ===========================================================================
@app.post("/territories")
def create_territory():
    require_roles("FranchisorOps")
    data = body()
    code = req_str(data, "code")
    region = req_str(data, "region")
    royalty = req_num(data, "royalty_rate_pct")
    if royalty < 0:
        bad("royalty_rate_pct must be non-negative")
    quota = req_int(data, "development_quota_stores")
    if quota < 0:
        bad("development_quota_stores must be non-negative")
    t = make_entity("territory")
    t.update({"code": code, "region": region, "royalty_rate_pct": royalty,
              "development_quota_stores": quota, "assigned_agent_id": None,
              "status": "UNASSIGNED"})
    DB["territories"][t["id"]] = t
    return ok_object(svc.ser_territory(t), 201)


@app.get("/territories/<tid>")
def get_territory(tid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    t = get_or_404("territories", tid, "ERR_TERRITORY_NOT_FOUND")
    return ok_object(svc.ser_territory(t))


@app.get("/territories")
def list_territories():
    require_roles("FranchisorOps", "DevelopmentAgent")
    items = list(DB["territories"].values())
    status = request.args.get("status")
    agent = request.args.get("assigned_agent_id")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if agent is not None:
        items = [t for t in items if t["assigned_agent_id"] == agent]
    return paginate(items, svc.ser_territory)


def _assign_agent_side_effects(t, agent):
    t["assigned_agent_id"] = agent["id"]
    t["status"] = "ASSIGNED"
    touch(t)
    svc.resume_territory_applications(t["id"])


@app.post("/territories/<tid>/assign-agent")
def assign_agent(tid):
    require_roles("FranchisorOps")
    t = get_or_404("territories", tid, "ERR_TERRITORY_NOT_FOUND")
    data = body()
    agent_id = req_field(data, "agent_id")
    agent = get_or_404("agents", agent_id, "ERR_AGENT_NOT_FOUND")
    if agent["status"] != "ACTIVE":
        raise err("ERR_AGENT_NOT_ACTIVE", 422, "Development agent is not ACTIVE")
    if t["status"] == "UNASSIGNED":
        _assign_agent_side_effects(t, agent)
    elif t["status"] == "REASSIGNMENT_PENDING":
        if agent["id"] == t["assigned_agent_id"]:
            invalid_state("New agent must differ from the previously assigned agent")
        _assign_agent_side_effects(t, agent)
    else:
        invalid_state("Territory is not UNASSIGNED or REASSIGNMENT_PENDING")
    return ok_object(svc.ser_territory(t))


@app.post("/territories/<tid>/initiate-reassignment")
def initiate_reassignment(tid):
    require_roles("FranchisorOps")
    t = get_or_404("territories", tid, "ERR_TERRITORY_NOT_FOUND")
    if t["status"] != "ASSIGNED":
        invalid_state("Territory is not ASSIGNED")
    agent = DB["agents"].get(t["assigned_agent_id"])
    if agent is None or agent["status"] != "UNDERPERFORMING":
        raise err("ERR_AGENT_NOT_ACTIVE", 422,
                  "Assigned agent is not UNDERPERFORMING")
    t["status"] = "REASSIGNMENT_PENDING"
    touch(t)
    svc.suspend_territory_applications(t["id"])
    return ok_object(svc.ser_territory(t))


@app.get("/territories/<tid>/stores")
def territory_stores(tid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    get_or_404("territories", tid, "ERR_TERRITORY_NOT_FOUND")
    items = [s for s in DB["stores"].values() if s["territory_id"] == tid]
    return paginate(items, svc.ser_store)


@app.get("/territories/<tid>/site-applications")
def territory_applications(tid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    get_or_404("territories", tid, "ERR_TERRITORY_NOT_FOUND")
    items = [a for a in DB["site_applications"].values() if a["territory_id"] == tid]
    return paginate(items, svc.ser_application)


@app.get("/territories/<tid>/fee-statements")
def territory_statements(tid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    get_or_404("territories", tid, "ERR_TERRITORY_NOT_FOUND")
    items = [f for f in DB["fee_statements"].values() if f["territory_id"] == tid]
    return paginate(items, svc.ser_statement)


# ===========================================================================
# Development Agents
# ===========================================================================
@app.post("/development-agents")
def create_agent():
    require_roles("FranchisorOps")
    data = body()
    legal_name = req_str(data, "legal_name")
    contact_email = req_str(data, "contact_email")
    start = req_dt(data, "agreement_start")
    end = req_dt(data, "agreement_end")
    a = make_entity("agent")
    a.update({"legal_name": legal_name, "contact_email": contact_email,
              "agreement_start": start, "agreement_end": end,
              "status": "ACTIVE", "underperformance_strikes": 0})
    DB["agents"][a["id"]] = a
    return ok_object(svc.ser_agent(a), 201)


@app.get("/development-agents/<aid>")
def get_agent(aid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    a = get_or_404("agents", aid, "ERR_AGENT_NOT_FOUND")
    return ok_object(svc.ser_agent(a))


@app.post("/development-agents/<aid>/flag-underperformance")
def flag_underperformance(aid):
    require_roles("FranchisorOps")
    a = get_or_404("agents", aid, "ERR_AGENT_NOT_FOUND")
    if a["status"] == "ACTIVE":
        a["underperformance_strikes"] += 1
        a["status"] = "UNDER_REVIEW"
        touch(a)
    elif a["status"] == "UNDER_REVIEW":
        a["underperformance_strikes"] += 1
        a["status"] = "UNDERPERFORMING"
        touch(a)
        # Cascade hop 1: territories -> REASSIGNMENT_PENDING
        for t in DB["territories"].values():
            if t["assigned_agent_id"] == a["id"] and t["status"] == "ASSIGNED":
                t["status"] = "REASSIGNMENT_PENDING"
                touch(t)
                # Cascade hops 2/3
                svc.suspend_territory_applications(t["id"])
    else:
        invalid_state("Agent is not ACTIVE or UNDER_REVIEW")
    return ok_object(svc.ser_agent(a))


@app.post("/development-agents/<aid>/clear-review")
def clear_review(aid):
    require_roles("FranchisorOps")
    a = get_or_404("agents", aid, "ERR_AGENT_NOT_FOUND")
    if a["status"] != "UNDER_REVIEW":
        invalid_state("Agent is not UNDER_REVIEW")
    a["status"] = "ACTIVE"
    touch(a)
    return ok_object(svc.ser_agent(a))


@app.post("/development-agents/<aid>/terminate")
def terminate_agent(aid):
    require_roles("FranchisorOps")
    a = get_or_404("agents", aid, "ERR_AGENT_NOT_FOUND")
    if a["status"] != "UNDERPERFORMING":
        invalid_state("Agent is not UNDERPERFORMING")
    still_assigned = any(
        t["assigned_agent_id"] == a["id"] and t["status"] == "ASSIGNED"
        for t in DB["territories"].values())
    if still_assigned:
        invalid_state("Territories remain ASSIGNED to this agent")
    a["status"] = "TERMINATED"
    touch(a)
    return ok_object(svc.ser_agent(a))


@app.get("/development-agents/<aid>/territories")
def agent_territories(aid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    get_or_404("agents", aid, "ERR_AGENT_NOT_FOUND")
    items = [t for t in DB["territories"].values() if t["assigned_agent_id"] == aid]
    return paginate(items, svc.ser_territory)


@app.get("/development-agents/<aid>/fee-statements")
def agent_statements(aid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    get_or_404("agents", aid, "ERR_AGENT_NOT_FOUND")
    items = [f for f in DB["fee_statements"].values()
             if f["development_agent_id"] == aid]
    return paginate(items, svc.ser_statement)


# ===========================================================================
# Franchisees
# ===========================================================================
@app.post("/franchisees")
def create_franchisee():
    require_roles("FranchisorOps")
    data = body()
    legal_name = req_str(data, "legal_name")
    contact_email = req_str(data, "contact_email")
    f = make_entity("franchisee")
    f.update({"legal_name": legal_name, "contact_email": contact_email,
              "status": "PROSPECT"})
    DB["franchisees"][f["id"]] = f
    return ok_object(svc.ser_franchisee(f), 201)


@app.get("/franchisees/<fid>")
def get_franchisee(fid):
    require_roles("FranchisorOps", "Franchisee")
    f = get_or_404("franchisees", fid, "ERR_FRANCHISEE_NOT_FOUND")
    return ok_object(svc.ser_franchisee(f))


@app.get("/franchisees/<fid>/stores")
def franchisee_stores(fid):
    require_roles("FranchisorOps", "Franchisee")
    get_or_404("franchisees", fid, "ERR_FRANCHISEE_NOT_FOUND")
    items = [s for s in DB["stores"].values() if s["franchisee_id"] == fid]
    return paginate(items, svc.ser_store)


@app.get("/franchisees/<fid>/training-enrollments")
def franchisee_enrollments(fid):
    require_roles("FranchisorOps", "Franchisee")
    get_or_404("franchisees", fid, "ERR_FRANCHISEE_NOT_FOUND")
    items = [e for e in DB["enrollments"].values() if e["franchisee_id"] == fid]
    return paginate(items, svc.ser_enrollment)


@app.get("/franchisees/<fid>/transfer-requests")
def franchisee_transfers(fid):
    require_roles("FranchisorOps", "Franchisee")
    get_or_404("franchisees", fid, "ERR_FRANCHISEE_NOT_FOUND")
    items = [t for t in DB["transfer_requests"].values()
             if t["seller_franchisee_id"] == fid or t["buyer_franchisee_id"] == fid]
    return paginate(items, svc.ser_transfer)


@app.get("/franchisees/<fid>/site-applications")
def franchisee_applications(fid):
    require_roles("FranchisorOps", "Franchisee", "DevelopmentAgent")
    get_or_404("franchisees", fid, "ERR_FRANCHISEE_NOT_FOUND")
    items = [a for a in DB["site_applications"].values()
             if a["applicant_franchisee_id"] == fid]
    return paginate(items, svc.ser_application)


@app.get("/franchisees/<fid>/promotion-votes")
def franchisee_votes(fid):
    require_roles("FranchisorOps", "Franchisee")
    get_or_404("franchisees", fid, "ERR_FRANCHISEE_NOT_FOUND")
    items = [v for v in DB["votes"].values() if v["franchisee_id"] == fid]
    return paginate(items, svc.ser_vote)


# ===========================================================================
# Stores
# ===========================================================================
@app.post("/stores")
def create_store():
    require_roles("FranchisorOps")
    data = body()
    store_number = req_str(data, "store_number")
    territory_id = req_field(data, "territory_id")
    get_or_404("territories", territory_id, "ERR_TERRITORY_NOT_FOUND")
    franchisee_id = req_field(data, "franchisee_id")
    get_or_404("franchisees", franchisee_id, "ERR_FRANCHISEE_NOT_FOUND")
    address = req_str(data, "address")
    geo_lat = req_num(data, "geo_lat")
    geo_lng = req_num(data, "geo_lng")
    opened_on = req_dt(data, "opened_on")
    est = req_int(data, "estimated_weekly_sales_cents")
    act = req_int(data, "actual_avg_weekly_sales_cents")
    s = make_entity("store")
    s.update({"store_number": store_number, "territory_id": territory_id,
              "franchisee_id": franchisee_id, "address": address,
              "geo_lat": geo_lat, "geo_lng": geo_lng, "opened_on": opened_on,
              "estimated_weekly_sales_cents": est,
              "actual_avg_weekly_sales_cents": act,
              "status": "OPEN", "consecutive_failed_inspections": 0,
              "source_site_application_id": None})
    DB["stores"][s["id"]] = s
    svc.franchisee_activate_if_prospect(franchisee_id)
    return ok_object(svc.ser_store(s), 201)


@app.get("/stores/<sid>")
def get_store(sid):
    require_roles("FranchisorOps", "DevelopmentAgent", "Franchisee")
    s = get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    return ok_object(svc.ser_store(s))


@app.post("/stores/<sid>/open")
def open_store(sid):
    require_roles("FranchisorOps")
    s = get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    if s["status"] != "PIPELINE":
        invalid_state("Store is not PIPELINE")
    s["status"] = "OPEN"
    touch(s)
    svc.franchisee_activate_if_prospect(s["franchisee_id"])
    return ok_object(svc.ser_store(s))


@app.post("/stores/<sid>/terminate")
def terminate_store_ep(sid):
    require_roles("FranchisorOps")
    s = get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    if s["status"] != "TERMINATION_PENDING":
        invalid_state("Store is not TERMINATION_PENDING")
    svc.terminate_store(s)
    return ok_object(svc.ser_store(s))


@app.get("/stores/<sid>/site-applications")
def store_applications(sid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    items = [a for a in DB["site_applications"].values() if a["store_id"] == sid]
    return paginate(items, svc.ser_application)


@app.get("/stores/<sid>/protests")
def store_protests(sid):
    require_roles("FranchisorOps", "DevelopmentAgent", "Franchisee")
    get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    items = [p for p in DB["protests"].values() if p["protesting_store_id"] == sid]
    return paginate(items, svc.ser_protest)


@app.get("/stores/<sid>/transfer-requests")
def store_transfers(sid):
    require_roles("FranchisorOps", "Franchisee")
    get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    items = [t for t in DB["transfer_requests"].values() if t["store_id"] == sid]
    return paginate(items, svc.ser_transfer)


@app.get("/stores/<sid>/remodel-mandates")
def store_mandates(sid):
    require_roles("FranchisorOps", "DevelopmentAgent", "Franchisee")
    get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    items = [m for m in DB["mandates"].values() if m["store_id"] == sid]
    return paginate(items, svc.ser_mandate)


@app.get("/stores/<sid>/inspections")
def store_inspections(sid):
    require_roles("FranchisorOps", "Inspector")
    get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    items = [i for i in DB["inspections"].values() if i["store_id"] == sid]
    return paginate(items, svc.ser_inspection)


@app.get("/stores/<sid>/promotion-votes")
def store_votes(sid):
    require_roles("FranchisorOps", "Franchisee")
    get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    items = [v for v in DB["votes"].values() if v["store_id"] == sid]
    return paginate(items, svc.ser_vote)


@app.get("/stores/<sid>/funding-disputes")
def store_disputes(sid):
    require_roles("FranchisorOps", "Franchisee")
    get_or_404("stores", sid, "ERR_STORE_NOT_FOUND")
    items = [d for d in DB["disputes"].values() if d["store_id"] == sid]
    return paginate(items, svc.ser_dispute)


# ===========================================================================
# Site Applications
# ===========================================================================
def _require_territory_agent(uid, territory):
    if territory["assigned_agent_id"] != uid:
        forbid("Caller is not the assigned agent of the territory")


@app.post("/site-applications")
def create_site_application():
    uid, _ = require_roles("DevelopmentAgent")
    data = body()
    territory_id = req_field(data, "territory_id")
    t = get_or_404("territories", territory_id, "ERR_TERRITORY_NOT_FOUND")
    _require_territory_agent(uid, t)
    applicant_id = req_field(data, "applicant_franchisee_id")
    get_or_404("franchisees", applicant_id, "ERR_FRANCHISEE_NOT_FOUND")
    address = req_str(data, "proposed_address")
    lat = req_num(data, "proposed_lat")
    lng = req_num(data, "proposed_lng")
    open_date = req_dt(data, "proposed_open_date")
    expected = req_field(data, "expected_territory_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        bad("expected_territory_version must be an integer")
    if t["version"] != expected:
        raise err("ERR_STALE_VERSION", 412,
                  "expected_territory_version does not match the territory's current version")
    ap = make_entity("application")
    ap.update({"territory_id": territory_id,
               "applicant_franchisee_id": applicant_id,
               "proposed_address": address, "proposed_lat": lat,
               "proposed_lng": lng, "proposed_open_date": open_date,
               "store_id": None, "status": "DRAFT", "revision_count": 0,
               "approved_on": None})
    DB["site_applications"][ap["id"]] = ap
    touch(t)  # the create consumes capacity: territory version advances
    return ok_object(svc.ser_application(ap), 201)


@app.get("/site-applications/<aid>")
def get_site_application(aid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    ap = get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    return ok_object(svc.ser_application(ap))


@app.post("/site-applications/<aid>/submit")
def submit_application(aid):
    uid, _ = require_roles("DevelopmentAgent")
    ap = get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    t = DB["territories"].get(ap["territory_id"])
    if t is not None:
        _require_territory_agent(uid, t)
    if ap["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        invalid_state("Application is not DRAFT or REVISION_REQUESTED")
    if ap["status"] == "DRAFT" and (t is None or t["status"] != "ASSIGNED"):
        raise err("ERR_TERRITORY_UNASSIGNED", 422,
                  "Territory is not ASSIGNED")
    if ap["status"] == "REVISION_REQUESTED":
        ap["revision_count"] += 1
        svc.void_provisional_studies(ap["id"], also_final=True)
    ap["status"] = "SUBMITTED"
    touch(ap)
    return ok_object(svc.ser_application(ap))


@app.post("/site-applications/<aid>/request-revision")
def request_revision(aid):
    require_roles("FranchisorOps")
    ap = get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    body()  # optional revision_notes
    if ap["status"] != "IMPACT_REVIEW":
        invalid_state("Application is not IMPACT_REVIEW")
    ap["status"] = "REVISION_REQUESTED"
    touch(ap)
    return ok_object(svc.ser_application(ap))


@app.post("/site-applications/<aid>/approve")
def approve_application(aid):
    require_roles("FranchisorOps")
    ap = get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    if ap["status"] != "IMPACT_REVIEW":
        invalid_state("Application is not IMPACT_REVIEW")
    study = next((s for s in DB["impact_studies"].values()
                  if s["site_application_id"] == ap["id"]
                  and s["status"] in ("PROVISIONAL", "FINAL")), None)
    if study is None or study["status"] != "FINAL":
        raise err("ERR_IMPACT_STUDY_NOT_FINAL", 422,
                  "Site approval requires a FINAL impact study")
    ap["status"] = "APPROVED"
    ap["approved_on"] = clock_now()
    # Create PIPELINE store
    s = make_entity("store")
    s.update({"store_number": None, "territory_id": ap["territory_id"],
              "franchisee_id": ap["applicant_franchisee_id"],
              "address": ap["proposed_address"],
              "geo_lat": ap["proposed_lat"], "geo_lng": ap["proposed_lng"],
              "opened_on": ap["proposed_open_date"],
              "estimated_weekly_sales_cents": 0,
              "actual_avg_weekly_sales_cents": 0,
              "status": "PIPELINE", "consecutive_failed_inspections": 0,
              "source_site_application_id": ap["id"]})
    DB["stores"][s["id"]] = s
    ap["store_id"] = s["id"]
    touch(ap)
    return ok_object(svc.ser_application(ap))


@app.post("/site-applications/<aid>/reject")
def reject_application(aid):
    require_roles("FranchisorOps")
    ap = get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    body()  # optional reason
    if ap["status"] != "IMPACT_REVIEW":
        invalid_state("Application is not IMPACT_REVIEW")
    ap["status"] = "REJECTED"
    touch(ap)
    svc.void_provisional_studies(ap["id"], also_final=True)
    return ok_object(svc.ser_application(ap))


@app.post("/site-applications/<aid>/withdraw")
def withdraw_application(aid):
    uid, _ = require_roles("DevelopmentAgent")
    ap = get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    t = DB["territories"].get(ap["territory_id"])
    if t is not None:
        _require_territory_agent(uid, t)
    if ap["status"] not in ("DRAFT", "SUBMITTED", "IMPACT_REVIEW",
                            "REVISION_REQUESTED", "APPROVED"):
        invalid_state("Application cannot be withdrawn from its current state")
    was_approved = ap["status"] == "APPROVED"
    ap["status"] = "WITHDRAWN"
    touch(ap)
    svc.void_provisional_studies(ap["id"], also_final=True)
    if was_approved and ap["store_id"]:
        store = DB["stores"].get(ap["store_id"])
        if store is not None and store["status"] == "PIPELINE":
            svc.terminate_store(store)
    return ok_object(svc.ser_application(ap))


@app.get("/site-applications/<aid>/stores")
def application_stores(aid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    items = [s for s in DB["stores"].values()
             if s["source_site_application_id"] == aid]
    return paginate(items, svc.ser_store)


@app.get("/site-applications/<aid>/protests")
def application_protests(aid):
    require_roles("FranchisorOps", "DevelopmentAgent", "Franchisee")
    get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    items = [p for p in DB["protests"].values()
             if p["site_application_id"] == aid]
    return paginate(items, svc.ser_protest)


# ===========================================================================
# Impact Studies
# ===========================================================================
@app.post("/site-applications/<aid>/impact-studies")
def create_impact_study(aid):
    require_roles("FranchisorOps")
    ap = get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    data = body()
    radius = req_num(data, "radius_miles")
    if radius <= 0:
        bad("radius_miles must be positive")
    if ap["status"] != "SUBMITTED":
        invalid_state("Application is not SUBMITTED")
    live = any(s["site_application_id"] == ap["id"] and
               s["status"] in ("PROVISIONAL", "FINAL")
               for s in DB["impact_studies"].values())
    if live:
        invalid_state("An impact study already exists for this application")
    st = make_entity("impact_study")
    st.update({"site_application_id": ap["id"], "radius_miles": radius,
               "affected_store_count": 0, "provisional_impact_cents": 0.0,
               "final_impact_cents": None, "status": "PROVISIONAL"})
    DB["impact_studies"][st["id"]] = st
    affected, total = svc.compute_impact(st, "provisional")
    st["affected_store_count"] = affected
    st["provisional_impact_cents"] = total
    ap["status"] = "IMPACT_REVIEW"
    touch(ap)
    return ok_object(svc.ser_impact_study(st), 201)


@app.get("/site-applications/<aid>/impact-studies")
def application_studies(aid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    get_or_404("site_applications", aid, "ERR_SITE_APPLICATION_NOT_FOUND")
    items = [s for s in DB["impact_studies"].values()
             if s["site_application_id"] == aid]
    return paginate(items, svc.ser_impact_study)


@app.get("/impact-studies/<sid>")
def get_impact_study(sid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    st = get_or_404("impact_studies", sid, "ERR_IMPACT_STUDY_NOT_FOUND")
    return ok_object(svc.ser_impact_study(st))


@app.post("/impact-studies/<sid>/finalize")
def finalize_impact_study(sid):
    require_roles("FranchisorOps")
    st = get_or_404("impact_studies", sid, "ERR_IMPACT_STUDY_NOT_FOUND")
    if st["status"] != "PROVISIONAL":
        invalid_state("Impact study is not PROVISIONAL")
    st["status"] = "FINAL"
    _, total = svc.compute_impact(st, "final")
    st["final_impact_cents"] = total
    touch(st)
    return ok_object(svc.ser_impact_study(st))


# ===========================================================================
# Protests
# ===========================================================================
PROTEST_NON_TERMINAL = ("FILED", "UNDER_REVIEW", "MEDIATION",
                        "MEDIATION_FAILED", "ESCALATED")


@app.post("/protests")
def create_protest():
    uid, _ = require_roles("Franchisee")
    data = body()
    ap_id = req_field(data, "site_application_id")
    ap = get_or_404("site_applications", ap_id, "ERR_SITE_APPLICATION_NOT_FOUND")
    store_id = req_field(data, "protesting_store_id")
    store = get_or_404("stores", store_id, "ERR_STORE_NOT_FOUND")
    grounds = req_str(data, "grounds")
    # entity-backed ownership
    if store["franchisee_id"] != uid:
        forbid("Caller does not own the protesting store")
    # state validity: a protest requires an APPROVED application (§3.3)
    if ap["status"] != "APPROVED":
        invalid_state("Site application is not APPROVED")
    if store["status"] != "OPEN" or store["territory_id"] != ap["territory_id"]:
        raise err("ERR_STORE_NOT_OPEN", 422,
                  "Protesting store must be OPEN and in the same territory")
    if ap["approved_on"] is None or \
            clock_now() > ap["approved_on"] + timedelta(days=30):
        raise err("ERR_PROTEST_WINDOW_EXPIRED", 422,
                  "Protest filed more than 30 days after approval")
    dup = any(p["site_application_id"] == ap["id"]
              and p["protesting_store_id"] == store["id"]
              and p["status"] in PROTEST_NON_TERMINAL
              for p in DB["protests"].values())
    if dup:
        raise err("ERR_PROTEST_ALREADY_FILED", 409,
                  "A non-terminal protest already exists for this store and application")
    p = make_entity("protest")
    p.update({"site_application_id": ap["id"],
              "protesting_store_id": store["id"],
              "protesting_franchisee_id": store["franchisee_id"],
              "grounds": grounds, "filed_on": clock_now(),
              "mediator_ref": None, "mediation_deadline": None,
              "resolution": None, "status": "FILED"})
    DB["protests"][p["id"]] = p
    ap["status"] = "PROTESTED"
    touch(ap)
    return ok_object(svc.ser_protest(p), 201)


@app.get("/protests/<pid>")
def get_protest(pid):
    require_roles("FranchisorOps", "DevelopmentAgent", "Franchisee", "Mediator")
    p = get_or_404("protests", pid, "ERR_PROTEST_NOT_FOUND")
    return ok_object(svc.ser_protest(p))


@app.get("/protests")
def list_protests():
    require_roles("FranchisorOps", "Mediator")
    items = list(DB["protests"].values())
    fid = request.args.get("protesting_franchisee_id")
    status = request.args.get("status")
    if fid is not None:
        items = [p for p in items if p["protesting_franchisee_id"] == fid]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, svc.ser_protest)


@app.post("/protests/<pid>/begin-review")
def begin_review(pid):
    require_roles("FranchisorOps")
    p = get_or_404("protests", pid, "ERR_PROTEST_NOT_FOUND")
    if p["status"] != "FILED":
        invalid_state("Protest is not FILED")
    p["status"] = "UNDER_REVIEW"
    touch(p)
    return ok_object(svc.ser_protest(p))


@app.post("/protests/<pid>/send-to-mediation")
def send_to_mediation(pid):
    require_roles("FranchisorOps")
    p = get_or_404("protests", pid, "ERR_PROTEST_NOT_FOUND")
    data = body()
    mediator_ref = req_str(data, "mediator_ref")
    deadline = req_dt(data, "mediation_deadline")
    if p["status"] != "UNDER_REVIEW":
        invalid_state("Protest is not UNDER_REVIEW")
    p["status"] = "MEDIATION"
    p["mediator_ref"] = mediator_ref
    p["mediation_deadline"] = deadline
    touch(p)
    return ok_object(svc.ser_protest(p))


@app.post("/protests/<pid>/record-mediation-outcome")
def record_mediation_outcome(pid):
    uid, _ = require_roles("Mediator")
    p = get_or_404("protests", pid, "ERR_PROTEST_NOT_FOUND")
    if p["mediator_ref"] != uid:
        forbid("Only the assigned mediator may record the mediation outcome")
    data = body()
    outcome = req_enum(data, "outcome", {"UPHELD", "REJECTED", "FAILED"})
    if p["status"] != "MEDIATION":
        invalid_state("Protest is not MEDIATION")
    if p["mediation_deadline"] is not None and \
            clock_now() > p["mediation_deadline"]:
        raise err("ERR_MEDIATION_DEADLINE_PASSED", 422,
                  "Mediation outcome recorded after the deadline")
    if outcome == "FAILED":
        p["status"] = "MEDIATION_FAILED"
        touch(p)
    else:
        svc.finalize_protest_resolution(p, outcome)
    return ok_object(svc.ser_protest(p))


@app.post("/protests/<pid>/resolve")
def resolve_protest(pid):
    uid, _ = require_roles("FranchisorOps")
    p = get_or_404("protests", pid, "ERR_PROTEST_NOT_FOUND")
    if p["mediator_ref"] is not None and p["mediator_ref"] == uid:
        forbid("The mediator may not resolve the protest")
    data = body()
    resolution = req_enum(data, "resolution", {"UPHELD", "REJECTED"})
    if p["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        invalid_state("Protest is not UNDER_REVIEW or ESCALATED")
    svc.finalize_protest_resolution(p, resolution)
    return ok_object(svc.ser_protest(p))


@app.post("/protests/<pid>/escalate")
def escalate_protest(pid):
    uid, _ = require_roles("Franchisee")
    p = get_or_404("protests", pid, "ERR_PROTEST_NOT_FOUND")
    if p["status"] != "MEDIATION_FAILED":
        invalid_state("Protest is not MEDIATION_FAILED")
    if p["protesting_franchisee_id"] != uid:
        forbid("Caller does not own the protesting store")
    p["status"] = "ESCALATED"
    touch(p)
    return ok_object(svc.ser_protest(p))


# ===========================================================================
# Transfer Requests
# ===========================================================================
TRANSFER_PROGRAM = "TRANSFER_BUYER"


def _buyer_enrollment(buyer_id, statuses):
    for e in DB["enrollments"].values():
        if e["franchisee_id"] == buyer_id and \
                e["program_code"] == TRANSFER_PROGRAM and \
                e["status"] in statuses:
            return e
    return None


@app.post("/transfer-requests")
def create_transfer():
    uid, _ = require_roles("Franchisee")
    data = body()
    store_id = req_field(data, "store_id")
    store = get_or_404("stores", store_id, "ERR_STORE_NOT_FOUND")
    if store["franchisee_id"] != uid:
        forbid("Caller does not own the store")
    buyer_id = req_field(data, "buyer_franchisee_id")
    get_or_404("franchisees", buyer_id, "ERR_FRANCHISEE_NOT_FOUND")
    sale_price = req_int(data, "sale_price_cents")
    if sale_price < 0:
        bad("sale_price_cents must be non-negative")
    expected = req_field(data, "expected_store_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        bad("expected_store_version must be an integer")
    if store["version"] != expected:
        raise err("ERR_STALE_VERSION", 412,
                  "expected_store_version does not match the store's current version")
    fee = svc.compute_transfer_fee(sale_price, store["opened_on"], clock_now())
    tr = make_entity("transfer_request")
    tr.update({"store_id": store["id"],
               "seller_franchisee_id": store["franchisee_id"],
               "buyer_franchisee_id": buyer_id,
               "sale_price_cents": sale_price,
               "transfer_fee_cents": fee,
               "status": "PENDING"})
    DB["transfer_requests"][tr["id"]] = tr
    touch(store)  # the create supersedes prior pending sale: store version advances
    return ok_object(svc.ser_transfer(tr), 201)


@app.get("/transfer-requests/<tid>")
def get_transfer(tid):
    require_roles("FranchisorOps", "Franchisee")
    tr = get_or_404("transfer_requests", tid, "ERR_TRANSFER_REQUEST_NOT_FOUND")
    return ok_object(svc.ser_transfer(tr))


@app.post("/transfer-requests/<tid>/advance-to-training")
def advance_to_training(tid):
    require_roles("FranchisorOps")
    tr = get_or_404("transfer_requests", tid, "ERR_TRANSFER_REQUEST_NOT_FOUND")
    if tr["status"] != "PENDING":
        invalid_state("Transfer request is not PENDING")
    enroll = _buyer_enrollment(tr["buyer_franchisee_id"],
                               {"ENROLLED", "COMPLETED"})
    if enroll is None:
        raise err("ERR_BUYER_TRAINING_INCOMPLETE", 422,
                  "Buyer lacks an ENROLLED or COMPLETED TRANSFER_BUYER enrollment")
    if enroll["status"] == "COMPLETED":
        tr["status"] = "PENDING_APPROVAL"
    else:
        tr["status"] = "BUYER_TRAINING"
    touch(tr)
    return ok_object(svc.ser_transfer(tr))


@app.post("/transfer-requests/<tid>/approve")
def approve_transfer(tid):
    require_roles("FranchisorOps")
    tr = get_or_404("transfer_requests", tid, "ERR_TRANSFER_REQUEST_NOT_FOUND")
    if tr["status"] != "PENDING_APPROVAL":
        invalid_state("Transfer request is not PENDING_APPROVAL")
    enroll = _buyer_enrollment(tr["buyer_franchisee_id"], {"COMPLETED"})
    if enroll is None:
        raise err("ERR_BUYER_TRAINING_INCOMPLETE", 422,
                  "Buyer lacks a COMPLETED TRANSFER_BUYER enrollment")
    store = DB["stores"].get(tr["store_id"])
    if store is not None and store["status"] in ("TERMINATION_PENDING", "TERMINATED"):
        raise err("ERR_STORE_NOT_TRANSFERABLE", 422,
                  "Store is TERMINATION_PENDING or TERMINATED")
    tr["status"] = "APPROVED"
    touch(tr)
    return ok_object(svc.ser_transfer(tr))


@app.post("/transfer-requests/<tid>/reject")
def reject_transfer(tid):
    require_roles("FranchisorOps")
    tr = get_or_404("transfer_requests", tid, "ERR_TRANSFER_REQUEST_NOT_FOUND")
    body()  # optional reason
    if tr["status"] != "PENDING_APPROVAL":
        invalid_state("Transfer request is not PENDING_APPROVAL")
    tr["status"] = "REJECTED"
    touch(tr)
    return ok_object(svc.ser_transfer(tr))


@app.post("/transfer-requests/<tid>/complete")
def complete_transfer(tid):
    require_roles("FranchisorOps")
    tr = get_or_404("transfer_requests", tid, "ERR_TRANSFER_REQUEST_NOT_FOUND")
    if tr["status"] != "APPROVED":
        invalid_state("Transfer request is not APPROVED")
    store = DB["stores"].get(tr["store_id"])
    if store is not None and store["status"] in ("TERMINATION_PENDING", "TERMINATED"):
        raise err("ERR_STORE_NOT_TRANSFERABLE", 422,
                  "Store is TERMINATION_PENDING or TERMINATED")
    tr["status"] = "COMPLETED"
    touch(tr)
    if store is not None:
        store["franchisee_id"] = tr["buyer_franchisee_id"]
        touch(store)
        svc.franchisee_activate_if_prospect(tr["buyer_franchisee_id"])
    return ok_object(svc.ser_transfer(tr))


@app.post("/transfer-requests/<tid>/cancel")
def cancel_transfer(tid):
    uid, _ = require_roles("Franchisee")
    tr = get_or_404("transfer_requests", tid, "ERR_TRANSFER_REQUEST_NOT_FOUND")
    if tr["status"] not in ("PENDING", "BUYER_TRAINING", "PENDING_APPROVAL"):
        invalid_state("Transfer request cannot be cancelled from its current state")
    if tr["seller_franchisee_id"] != uid:
        forbid("Caller is not the seller of record")
    tr["status"] = "CANCELLED"
    touch(tr)
    return ok_object(svc.ser_transfer(tr))


# ===========================================================================
# Training Enrollments
# ===========================================================================
@app.post("/training-enrollments")
def create_enrollment():
    require_roles("FranchisorOps")
    data = body()
    fid = req_field(data, "franchisee_id")
    get_or_404("franchisees", fid, "ERR_FRANCHISEE_NOT_FOUND")
    program_code = req_str(data, "program_code")
    expires_on = req_dt(data, "expires_on")
    e = make_entity("enrollment")
    e.update({"franchisee_id": fid, "program_code": program_code,
              "expires_on": expires_on, "score": None,
              "completed_on": None, "status": "ENROLLED"})
    DB["enrollments"][e["id"]] = e
    return ok_object(svc.ser_enrollment(e), 201)


@app.get("/training-enrollments/<eid>")
def get_enrollment(eid):
    require_roles("FranchisorOps", "Franchisee")
    e = get_or_404("enrollments", eid, "ERR_ENROLLMENT_NOT_FOUND")
    return ok_object(svc.ser_enrollment(e))


@app.post("/training-enrollments/<eid>/record-result")
def record_result(eid):
    require_roles("FranchisorOps")
    e = get_or_404("enrollments", eid, "ERR_ENROLLMENT_NOT_FOUND")
    data = body()
    score = req_num(data, "score")
    if score < 0 or score > 100:
        bad("score must be between 0 and 100")
    if e["status"] != "ENROLLED":
        invalid_state("Enrollment is not ENROLLED")
    e["score"] = score
    if score >= 80:
        if clock_now() > e["expires_on"]:
            # Expiry applied lazily on read; explicit result after expiry fails it
            e["status"] = "EXPIRED"
            touch(e)
            _cascade_training_outcome(e, completed=False)
            return ok_object(svc.ser_enrollment(e))
        e["status"] = "COMPLETED"
        e["completed_on"] = clock_now()
        touch(e)
        _cascade_training_outcome(e, completed=True)
    else:
        e["status"] = "FAILED"
        touch(e)
        _cascade_training_outcome(e, completed=False)
    return ok_object(svc.ser_enrollment(e))


def _cascade_training_outcome(enrollment, completed):
    for tr in DB["transfer_requests"].values():
        if tr["buyer_franchisee_id"] == enrollment["franchisee_id"] and \
                tr["status"] == "BUYER_TRAINING":
            tr["status"] = "PENDING_APPROVAL" if completed else "PENDING"
            touch(tr)


# ===========================================================================
# Remodel Mandates
# ===========================================================================
@app.post("/remodel-mandates")
def create_mandate():
    require_roles("FranchisorOps")
    data = body()
    store_id = req_field(data, "store_id")
    store = get_or_404("stores", store_id, "ERR_STORE_NOT_FOUND")
    due_by = req_dt(data, "due_by")
    financing = req_enum(data, "financing_option",
                         {"SELF_FINANCED", "DA_LOAN", "FRANCHISOR_DEFERRAL"})
    cost = req_int(data, "estimated_cost_cents")
    if cost < 0:
        bad("estimated_cost_cents must be non-negative")
    if financing == "DA_LOAN":
        t = DB["territories"].get(store["territory_id"])
        agent = DB["agents"].get(t["assigned_agent_id"]) if t else None
        if agent is None or agent["status"] != "ACTIVE":
            raise err("ERR_AGENT_NOT_ACTIVE", 422,
                      "DA_LOAN financing requires an ACTIVE assigned agent")
    m = make_entity("mandate")
    m.update({"store_id": store["id"], "due_by": due_by,
              "financing_option": financing, "estimated_cost_cents": cost,
              "closure_start": None, "closure_end": None,
              "downtime_days": None, "downtime_charge_cents": 0,
              "status": "ISSUED"})
    DB["mandates"][m["id"]] = m
    return ok_object(svc.ser_mandate(m), 201)


@app.get("/remodel-mandates/<mid>")
def get_mandate(mid):
    require_roles("FranchisorOps", "DevelopmentAgent", "Franchisee")
    m = get_or_404("mandates", mid, "ERR_MANDATE_NOT_FOUND")
    return ok_object(svc.ser_mandate(m))


def _check_closure_rules(store, new_start, new_end, exclude_id):
    for m in DB["mandates"].values():
        if m["store_id"] != store["id"] or m["id"] == exclude_id:
            continue
        if m["status"] in ("SCHEDULED", "IN_PROGRESS") and \
                m["closure_start"] is not None and m["closure_end"] is not None:
            # half-open interval intersection
            if new_start < m["closure_end"] and m["closure_start"] < new_end:
                raise err("ERR_CLOSURE_WINDOW_OVERLAP", 422,
                          "Closure window intersects another scheduled closure")
        if m["closure_end"] is not None:
            if new_start < m["closure_end"] + timedelta(days=7):
                raise err("ERR_CLOSURE_BUFFER_VIOLATION", 422,
                          "closure_start is less than 7 days after a prior closure_end")


@app.post("/remodel-mandates/<mid>/schedule")
def schedule_mandate(mid):
    uid, _ = require_roles("DevelopmentAgent")
    m = get_or_404("mandates", mid, "ERR_MANDATE_NOT_FOUND")
    store = DB["stores"].get(m["store_id"])
    t = DB["territories"].get(store["territory_id"]) if store else None
    if t is not None and t["assigned_agent_id"] != uid:
        forbid("Caller is not the assigned agent of the store's territory")
    data = body()
    cs = req_dt(data, "closure_start")
    ce = req_dt(data, "closure_end")
    if ce <= cs:
        bad("closure_end must be after closure_start")
    if m["status"] not in ("ISSUED", "OVERDUE"):
        invalid_state("Mandate is not ISSUED or OVERDUE")
    if store is None or store["status"] != "OPEN":
        raise err("ERR_STORE_NOT_OPEN", 422, "Store is not OPEN")
    _check_closure_rules(store, cs, ce, m["id"])
    m["closure_start"] = cs
    m["closure_end"] = ce
    m["downtime_days"] = (ce - cs).days
    m["status"] = "SCHEDULED"
    touch(m)
    return ok_object(svc.ser_mandate(m))


@app.post("/remodel-mandates/<mid>/begin")
def begin_mandate(mid):
    uid, _ = require_roles("Franchisee")
    m = get_or_404("mandates", mid, "ERR_MANDATE_NOT_FOUND")
    store = DB["stores"].get(m["store_id"])
    if store is not None and store["franchisee_id"] != uid:
        forbid("Caller does not own the store")
    if m["status"] != "SCHEDULED":
        invalid_state("Mandate is not SCHEDULED")
    now = clock_now()
    if now < m["closure_start"] or now >= m["closure_end"]:
        raise err("ERR_INVALID_STATE", 409,
                  "Logical clock is outside the closure window")
    m["status"] = "IN_PROGRESS"
    touch(m)
    if store is not None and store["status"] == "OPEN":
        store["status"] = "CLOSED_FOR_REMODEL"
        touch(store)
    return ok_object(svc.ser_mandate(m))


@app.post("/remodel-mandates/<mid>/complete")
def complete_mandate(mid):
    uid, _ = require_roles("Franchisee")
    m = get_or_404("mandates", mid, "ERR_MANDATE_NOT_FOUND")
    store = DB["stores"].get(m["store_id"])
    if store is not None and store["franchisee_id"] != uid:
        forbid("Caller does not own the store")
    if m["status"] != "IN_PROGRESS":
        invalid_state("Mandate is not IN_PROGRESS")
    m["status"] = "COMPLETED"
    m["downtime_charge_cents"] = svc.compute_downtime_charge(m)
    touch(m)
    if store is not None and store["status"] == "CLOSED_FOR_REMODEL":
        store["status"] = "OPEN"
        touch(store)
    return ok_object(svc.ser_mandate(m))


@app.post("/remodel-mandates/<mid>/waive")
def waive_mandate(mid):
    require_roles("FranchisorOps")
    m = get_or_404("mandates", mid, "ERR_MANDATE_NOT_FOUND")
    if m["status"] not in ("ISSUED", "SCHEDULED", "OVERDUE"):
        invalid_state("Mandate cannot be waived from its current state")
    m["status"] = "WAIVED"
    touch(m)
    return ok_object(svc.ser_mandate(m))


# ===========================================================================
# Inspections
# ===========================================================================
@app.post("/inspections")
def create_inspection():
    require_roles("FranchisorOps")
    data = body()
    store_id = req_field(data, "store_id")
    get_or_404("stores", store_id, "ERR_STORE_NOT_FOUND")
    scheduled_on = req_dt(data, "scheduled_on")
    inspector_ref = req_str(data, "inspector_ref")
    i = make_entity("inspection")
    i.update({"store_id": store_id, "inspector_ref": inspector_ref,
              "scheduled_on": scheduled_on, "food_safety_score": None,
              "cleanliness_score": None, "operations_score": None,
              "critical_violations": None, "final_score": None,
              "outcome": None, "status": "SCHEDULED"})
    DB["inspections"][i["id"]] = i
    return ok_object(svc.ser_inspection(i), 201)


@app.get("/inspections/<iid>")
def get_inspection(iid):
    require_roles("FranchisorOps", "Inspector")
    i = get_or_404("inspections", iid, "ERR_INSPECTION_NOT_FOUND")
    return ok_object(svc.ser_inspection(i))


def _score_field(data, name):
    v = req_num(data, name)
    if v < 0 or v > 100:
        bad(f"{name} must be between 0 and 100")
    return v


@app.post("/inspections/<iid>/record-findings")
def record_findings(iid):
    uid, _ = require_roles("Inspector")
    i = get_or_404("inspections", iid, "ERR_INSPECTION_NOT_FOUND")
    if i["inspector_ref"] != uid:
        forbid("Only the assigned inspector may record findings")
    data = body()
    fs = _score_field(data, "food_safety_score")
    cs = _score_field(data, "cleanliness_score")
    os_ = _score_field(data, "operations_score")
    cv = req_int(data, "critical_violations")
    if cv < 0:
        bad("critical_violations must be non-negative")
    if i["status"] != "SCHEDULED":
        invalid_state("Inspection is not SCHEDULED")
    store = DB["stores"].get(i["store_id"])
    if store is not None and store["status"] == "TERMINATED":
        invalid_state("Store is TERMINATED")
    i["food_safety_score"] = fs
    i["cleanliness_score"] = cs
    i["operations_score"] = os_
    i["critical_violations"] = cv
    i["final_score"] = svc.compute_final_score(i)
    i["status"] = "CONDUCTED"
    touch(i)
    return ok_object(svc.ser_inspection(i))


@app.post("/inspections/<iid>/finalize")
def finalize_inspection(iid):
    uid, _ = require_roles("FranchisorOps")
    i = get_or_404("inspections", iid, "ERR_INSPECTION_NOT_FOUND")
    if i["inspector_ref"] == uid:
        forbid("The inspector of record may not finalize the inspection")
    if i["status"] != "CONDUCTED":
        invalid_state("Inspection is not CONDUCTED")
    if i["critical_violations"] >= 3:
        outcome = "FAIL_CRITICAL"
    elif i["final_score"] >= 60.0:
        outcome = "PASS"
    else:
        outcome = "FAIL"
    i["outcome"] = outcome
    i["status"] = "FINALIZED"
    touch(i)
    store = DB["stores"].get(i["store_id"])
    if store is not None:
        _apply_inspection_outcome(store, outcome)
    return ok_object(svc.ser_inspection(i))


def _apply_inspection_outcome(store, outcome):
    if outcome == "FAIL" and store["status"] == "OPEN" and \
            store["consecutive_failed_inspections"] == 0:
        store["consecutive_failed_inspections"] += 1
        store["status"] = "PROBATION"
        touch(store)
        svc.cancel_inflight_transfers(store["id"])
    elif outcome == "PASS" and store["status"] == "PROBATION":
        store["consecutive_failed_inspections"] = 0
        store["status"] = "OPEN"
        touch(store)
    elif outcome == "FAIL_CRITICAL" or \
            (outcome == "FAIL" and store["consecutive_failed_inspections"] >= 1):
        if store["status"] in ("OPEN", "PROBATION"):
            store["consecutive_failed_inspections"] += 1
            store["status"] = "TERMINATION_PENDING"
            touch(store)
            svc.cancel_inflight_transfers(store["id"])
            for other in DB["inspections"].values():
                if other["store_id"] == store["id"] and \
                        other["status"] == "SCHEDULED":
                    other["status"] = "VOID"
                    touch(other)


# ===========================================================================
# Promotions and Votes
# ===========================================================================
@app.post("/promotions")
def create_promotion():
    require_roles("FranchisorOps")
    data = body()
    name = req_str(data, "name")
    voting_open = req_dt(data, "voting_open")
    voting_close = req_dt(data, "voting_close")
    active_start = req_dt(data, "active_start")
    active_end = req_dt(data, "active_end")
    base_cost = req_int(data, "base_cost_per_store_cents")
    if base_cost < 0:
        bad("base_cost_per_store_cents must be non-negative")
    p = make_entity("promotion")
    p.update({"name": name, "voting_open": voting_open,
              "voting_close": voting_close, "active_start": active_start,
              "active_end": active_end,
              "base_cost_per_store_cents": base_cost,
              "eligible_voter_count": 0, "votes_for": 0, "votes_against": 0,
              "votes_abstain": 0, "participating_store_count": 0,
              "store_share_cents": None, "total_pool_cents": None,
              "status": "PROPOSED"})
    DB["promotions"][p["id"]] = p
    return ok_object(svc.ser_promotion(p), 201)


@app.get("/promotions/<pid>")
def get_promotion(pid):
    require_roles("FranchisorOps", "DevelopmentAgent", "Franchisee")
    p = get_or_404("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    return ok_object(svc.ser_promotion(p))


@app.post("/promotions/<pid>/open-voting")
def open_voting(pid):
    require_roles("FranchisorOps")
    p = get_or_404("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    if p["status"] != "PROPOSED":
        invalid_state("Promotion is not PROPOSED")
    now = clock_now()
    if now < p["voting_open"] or now >= p["voting_close"]:
        raise err("ERR_VOTING_CLOSED", 422,
                  "Logical clock is outside the voting window")
    p["status"] = "VOTING"
    touch(p)
    return ok_object(svc.ser_promotion(p))


@app.post("/promotions/<pid>/close-voting")
def close_voting(pid):
    require_roles("FranchisorOps")
    p = get_or_404("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    data = body()
    force_reject = bool(data.get("force_reject", False))
    if p["status"] != "VOTING":
        invalid_state("Promotion is not VOTING")
    now = clock_now()
    if now < p["voting_close"]:
        raise err("ERR_VOTING_CLOSED", 422,
                  "Logical clock has not reached voting_close")
    svc.recompute_vote_tallies(p)
    eligible = sum(1 for s in DB["stores"].values()
                   if s["status"] in ("OPEN", "CLOSED_FOR_REMODEL"))
    p["eligible_voter_count"] = eligible
    quorum = (p["votes_for"] * 3 >= 2 * eligible) and \
             ((p["votes_for"] + p["votes_against"] + p["votes_abstain"]) * 2 >= eligible)
    if not quorum:
        if force_reject:
            p["status"] = "REJECTED"
            touch(p)
            return ok_object(svc.ser_promotion(p))
        raise err("ERR_QUORUM_NOT_MET", 422,
                  "Quorum not met and force_reject not set")
    # Funding allocation in pinned order
    n = p["votes_for"]
    p["participating_store_count"] = n
    if n >= 12:
        subsidy = "0.15"
    elif n >= 6:
        subsidy = "0.10"
    else:
        subsidy = "0.05"
    share = svc.round0(p["base_cost_per_store_cents"] * (1 - float(subsidy)))
    p["store_share_cents"] = share
    p["total_pool_cents"] = n * share
    p["status"] = "APPROVED"
    touch(p)
    return ok_object(svc.ser_promotion(p))


def _participating_store_ids(promotion_id):
    return {v["store_id"] for v in DB["votes"].values()
            if v["promotion_id"] == promotion_id and not v["retracted"]
            and v["ballot"] == "FOR"}


@app.post("/promotions/<pid>/activate")
def activate_promotion(pid):
    require_roles("FranchisorOps")
    p = get_or_404("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    if p["status"] != "APPROVED":
        invalid_state("Promotion is not APPROVED")
    now = clock_now()
    if now < p["active_start"]:
        raise err("ERR_INVALID_STATE", 409,
                  "Logical clock has not reached active_start")
    participating = _participating_store_ids(p["id"])
    territories = {DB["stores"][sid]["territory_id"] for sid in participating
                   if sid in DB["stores"]}
    for tid in territories:
        others = 0
        for q in DB["promotions"].values():
            if q["id"] == p["id"] or q["status"] != "ACTIVE":
                continue
            # overlap of [active_start, active_end)
            if q["active_start"] < p["active_end"] and \
                    p["active_start"] < q["active_end"]:
                q_stores = _participating_store_ids(q["id"])
                q_ters = {DB["stores"][sid]["territory_id"]
                          for sid in q_stores if sid in DB["stores"]}
                if tid in q_ters:
                    others += 1
        if others >= 2:
            raise err("ERR_PROMOTION_OVERLAP_EXCEEDED", 422,
                      "Territory already has 2 overlapping ACTIVE promotions")
    p["status"] = "ACTIVE"
    touch(p)
    return ok_object(svc.ser_promotion(p))


@app.post("/promotions/<pid>/close")
def close_promotion(pid):
    require_roles("FranchisorOps")
    p = get_or_404("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    if p["status"] != "ACTIVE":
        invalid_state("Promotion is not ACTIVE")
    now = clock_now()
    if now < p["active_end"]:
        raise err("ERR_INVALID_STATE", 409,
                  "Logical clock has not reached active_end")
    open_disputes = any(d["promotion_id"] == p["id"] and d["status"] == "OPEN"
                        for d in DB["disputes"].values())
    if open_disputes:
        invalid_state("An OPEN funding dispute blocks closure")
    p["status"] = "CLOSED"
    touch(p)
    return ok_object(svc.ser_promotion(p))


@app.get("/promotions/<pid>/votes")
def promotion_votes(pid):
    require_roles("FranchisorOps", "DevelopmentAgent", "Franchisee")
    get_or_404("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    items = [v for v in DB["votes"].values() if v["promotion_id"] == pid]
    return paginate(items, svc.ser_vote)


@app.get("/promotions/<pid>/funding-disputes")
def promotion_disputes(pid):
    require_roles("FranchisorOps", "DevelopmentAgent", "Franchisee")
    get_or_404("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    items = [d for d in DB["disputes"].values() if d["promotion_id"] == pid]
    return paginate(items, svc.ser_dispute)


@app.post("/promotions/<pid>/votes")
def cast_vote(pid):
    uid, _ = require_roles("Franchisee")
    p = get_or_404("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    data = body()
    store_id = req_field(data, "store_id")
    store = get_or_404("stores", store_id, "ERR_STORE_NOT_FOUND")
    ballot = req_enum(data, "ballot", {"FOR", "AGAINST", "ABSTAIN"})
    if store["franchisee_id"] != uid:
        forbid("Caller does not own the store")
    if p["status"] != "VOTING":
        invalid_state("Promotion is not VOTING")
    if store["status"] not in ("OPEN", "CLOSED_FOR_REMODEL"):
        raise err("ERR_STORE_NOT_OPEN", 422,
                  "Store must be OPEN or CLOSED_FOR_REMODEL")
    now = clock_now()
    if now < p["voting_open"] or now >= p["voting_close"]:
        raise err("ERR_VOTING_CLOSED", 422,
                  "Logical clock is outside the voting window")
    live = any(v["promotion_id"] == p["id"] and v["store_id"] == store["id"]
               and not v["retracted"] for v in DB["votes"].values())
    if live:
        raise err("ERR_ALREADY_VOTED", 409,
                  "A live ballot already exists for this store and promotion")
    v = make_entity("vote")
    v.update({"promotion_id": p["id"], "store_id": store["id"],
              "franchisee_id": store["franchisee_id"], "ballot": ballot,
              "retracted": False})
    DB["votes"][v["id"]] = v
    svc.recompute_vote_tallies(p)
    touch(p)
    return ok_object(svc.ser_vote(v), 201)


@app.get("/promotion-votes/<vid>")
def get_vote(vid):
    require_roles("FranchisorOps", "Franchisee")
    v = get_or_404("votes", vid, "ERR_VOTE_NOT_FOUND")
    return ok_object(svc.ser_vote(v))


@app.post("/promotion-votes/<vid>/retract")
def retract_vote(vid):
    uid, _ = require_roles("Franchisee")
    v = get_or_404("votes", vid, "ERR_VOTE_NOT_FOUND")
    if v["franchisee_id"] != uid:
        forbid("Caller does not own the voting store")
    if v["retracted"]:
        invalid_state("Vote is already retracted")
    p = DB["promotions"].get(v["promotion_id"])
    now = clock_now()
    if p is not None:
        if now < p["voting_open"] or now >= p["voting_close"]:
            raise err("ERR_VOTING_CLOSED", 422,
                      "Logical clock is outside the voting window")
    v["retracted"] = True
    touch(v)
    if p is not None:
        svc.recompute_vote_tallies(p)
        touch(p)
    return ok_object(svc.ser_vote(v))


# ===========================================================================
# Funding Disputes
# ===========================================================================
@app.post("/funding-disputes")
def create_dispute():
    uid, _ = require_roles("Franchisee")
    data = body()
    promotion_id = req_field(data, "promotion_id")
    p = get_or_404("promotions", promotion_id, "ERR_PROMOTION_NOT_FOUND")
    store_id = req_field(data, "store_id")
    store = get_or_404("stores", store_id, "ERR_STORE_NOT_FOUND")
    amount = req_int(data, "disputed_amount_cents")
    reason = req_str(data, "reason")
    if store["franchisee_id"] != uid:
        forbid("Caller does not own the store")
    if p["status"] != "ACTIVE":
        raise err("ERR_PROMOTION_NOT_ACTIVE", 422,
                  "Promotion is not ACTIVE")
    if store["id"] not in _participating_store_ids(p["id"]):
        raise err("ERR_STORE_NOT_OPEN", 422,
                  "Store did not participate in the promotion")
    if p["store_share_cents"] is None or amount != p["store_share_cents"]:
        raise err("ERR_DISPUTE_AMOUNT_MISMATCH", 422,
                  "disputed_amount_cents does not equal store_share_cents")
    d = make_entity("dispute")
    d.update({"promotion_id": p["id"], "store_id": store["id"],
              "disputed_amount_cents": amount, "reason": reason,
              "resolution": None, "status": "OPEN"})
    DB["disputes"][d["id"]] = d
    return ok_object(svc.ser_dispute(d), 201)


@app.get("/funding-disputes/<did>")
def get_dispute(did):
    require_roles("FranchisorOps", "Franchisee")
    d = get_or_404("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    return ok_object(svc.ser_dispute(d))


DISPUTE_RESOLUTIONS = {
    "DA_ABSORBS": "RESOLVED_DA_ABSORBS",
    "FRANCHISEE_PAYS": "RESOLVED_FRANCHISEE_PAYS",
    "FRANCHISOR_ABSORBS": "RESOLVED_FRANCHISOR_ABSORBS",
}


@app.post("/funding-disputes/<did>/resolve")
def resolve_dispute(did):
    require_roles("FranchisorOps")
    d = get_or_404("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    data = body()
    resolution = req_enum(data, "resolution", set(DISPUTE_RESOLUTIONS.keys()))
    if d["status"] != "OPEN":
        invalid_state("Dispute is not OPEN")
    d["resolution"] = resolution
    d["status"] = DISPUTE_RESOLUTIONS[resolution]
    touch(d)
    return ok_object(svc.ser_dispute(d))


# ===========================================================================
# Fee Statements
# ===========================================================================
@app.post("/fee-statements/generate")
def generate_statement():
    require_roles("FranchisorOps")
    data = body()
    agent_id = req_field(data, "development_agent_id")
    agent = get_or_404("agents", agent_id, "ERR_AGENT_NOT_FOUND")
    territory_id = req_field(data, "territory_id")
    t = get_or_404("territories", territory_id, "ERR_TERRITORY_NOT_FOUND")
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    if t["assigned_agent_id"] != agent["id"]:
        raise err("ERR_TERRITORY_UNASSIGNED", 422,
                  "Territory is not assigned to the named agent")
    # Overlap: non-settled statement for same agent+territory
    for f in DB["fee_statements"].values():
        if f["development_agent_id"] == agent["id"] and \
                f["territory_id"] == t["id"] and f["status"] != "SETTLED":
            if period_start < f["period_end"] and f["period_start"] < period_end:
                raise err("ERR_FISCAL_PERIOD_OVERLAP", 409,
                          "A non-settled fee statement overlaps the requested period")
    # Whole-week period validation
    if period_end <= period_start:
        bad("period_end must be after period_start")
    total_seconds = (period_end - period_start).total_seconds()
    week_seconds = 7 * 86400
    if total_seconds % week_seconds != 0:
        bad("Statement period must be a whole number of weeks")
    gross, da_share, franchisor_share = svc.compute_fee_split(
        t, period_start, period_end, "PROVISIONAL_ESTIMATE")
    f = make_entity("fee_statement")
    f.update({"development_agent_id": agent["id"], "territory_id": t["id"],
              "period_start": period_start, "period_end": period_end,
              "gross_fees_cents": gross, "da_share_cents": da_share,
              "franchisor_share_cents": franchisor_share,
              "variant": "PROVISIONAL_ESTIMATE", "status": "PROVISIONAL"})
    DB["fee_statements"][f["id"]] = f
    return ok_object(svc.ser_statement(f), 201)


@app.get("/fee-statements/<fid>")
def get_statement(fid):
    require_roles("FranchisorOps", "DevelopmentAgent")
    f = get_or_404("fee_statements", fid, "ERR_STATEMENT_NOT_FOUND")
    return ok_object(svc.ser_statement(f))


@app.post("/fee-statements/<fid>/finalize")
def finalize_statement(fid):
    require_roles("FranchisorOps")
    f = get_or_404("fee_statements", fid, "ERR_STATEMENT_NOT_FOUND")
    if f["status"] != "PROVISIONAL":
        invalid_state("Statement is not PROVISIONAL")
    t = DB["territories"].get(f["territory_id"])
    gross, da_share, franchisor_share = svc.compute_fee_split(
        t, f["period_start"], f["period_end"], "FINAL_RECONCILIATION")
    f["gross_fees_cents"] = gross
    f["da_share_cents"] = da_share
    f["franchisor_share_cents"] = franchisor_share
    f["variant"] = "FINAL_RECONCILIATION"
    f["status"] = "FINALIZED"
    touch(f)
    return ok_object(svc.ser_statement(f))


@app.post("/fee-statements/<fid>/settle")
def settle_statement(fid):
    require_roles("FranchisorOps")
    f = get_or_404("fee_statements", fid, "ERR_STATEMENT_NOT_FOUND")
    if f["status"] != "FINALIZED":
        invalid_state("Statement is not FINALIZED")
    if f["da_share_cents"] + f["franchisor_share_cents"] != f["gross_fees_cents"]:
        invalid_state("Fee conservation invariant violated")
    f["status"] = "SETTLED"
    touch(f)
    return ok_object(svc.ser_statement(f))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
