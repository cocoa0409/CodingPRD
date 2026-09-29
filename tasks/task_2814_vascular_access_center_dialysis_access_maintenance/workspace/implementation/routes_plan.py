"""Conversion planning, maturation follow-up and infection surveillance.
PRD section 3.9.
"""
import math

from flask import Blueprint, request

import calc
from core import (
    ApiError, authenticate, base_record, db, envelope_object, filter_bool,
    filter_equals, get_body, list_response, must_get, now_str, opt_id,
    parse_dt, public, req_date, req_dt, req_enum, req_id, req_int, req_num,
    req_str, touch,
)

bp = Blueprint("plan", __name__)

TARGET_ACCESS_TYPES = ("AVF", "AVG")
EVENT_TYPES = ("ACCESS_SITE_INFECTION", "BACTEREMIA")
CONVERTIBLE_TARGET_STATUSES = ("PLANNED", "PLACED", "MATURING")


# ---------------------------------------------------------------------------
# Conversion plans
# ---------------------------------------------------------------------------
@bp.post("/access-conversion-plans")
def create_plan():
    authenticate(("AccessCoordinator", "CenterAdmin"))
    body = get_body()
    patient_id = req_id(body, "patient_id")
    from_access_id = req_id(body, "from_access_id")
    target_access_type = req_enum(body, "target_access_type", TARGET_ACCESS_TYPES)
    target_conversion_date = req_date(body, "target_conversion_date")
    expected_access_version = req_int(body, "expected_access_version")
    target_access_id = opt_id(body, "target_access_id")

    must_get(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    from_access = must_get(db.accesses, from_access_id, "ERR_ACCESS_NOT_FOUND")
    if target_access_id is not None:
        must_get(db.accesses, target_access_id, "ERR_ACCESS_NOT_FOUND")

    # Rung 9: optimistic concurrency on the source access.
    if expected_access_version != from_access["version"]:
        raise ApiError("ERR_STALE_ACCESS_VERSION")

    superseded = [p for p in db.plans.values()
                  if p["from_access_id"] == from_access_id and p["status"] == "DRAFT"]

    plan = base_record()
    plan.update({
        "patient_id": patient_id,
        "from_access_id": from_access_id,
        "target_access_id": target_access_id,
        "target_access_type": target_access_type,
        "target_conversion_date": target_conversion_date,
        "status": "DRAFT",
        "maturation_check_count": 0,
        "readiness_met": False,
        "readiness_failure_reasons": [],
        "last_check_at": None,
        "last_diameter_mm": None,
        "last_flow_ml_min": None,
        "last_depth_mm": None,
        "days_since_placement": None,
        "converted_at": None,
    })
    db.plans[plan["id"]] = plan

    for prior in calc.seq_sorted(superseded):
        prior["status"] = "ABANDONED"
        touch(prior)

    return envelope_object(public(plan)), 201


@bp.post("/access-conversion-plans/<plan_id>/activate")
def activate_plan(plan_id):
    authenticate(("AccessCoordinator", "CenterAdmin"))
    plan = must_get(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")

    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_STATE_INVALID")

    # Rung 26: conversion must be clinically indicated.
    from_access = db.accesses.get(plan["from_access_id"])
    indicated = False
    if from_access is not None:
        if from_access["access_type"] == "TUNNELED_CATHETER":
            indicated = True
        elif from_access["intervention_burden_score"] >= calc.CONVERSION_BURDEN_MIN:
            indicated = True
    if not indicated:
        raise ApiError("ERR_CONVERSION_NOT_INDICATED")

    # Rung 27: target-access convertibility.
    target = db.accesses.get(plan["target_access_id"]) if plan["target_access_id"] else None
    if target is None or target["status"] not in CONVERTIBLE_TARGET_STATUSES:
        raise ApiError("ERR_TARGET_ACCESS_NOT_CONVERTIBLE")

    plan["status"] = "ACTIVE"
    touch(plan)

    target["predecessor_access_id"] = plan["from_access_id"]
    touch(target)

    return envelope_object(public(plan)), 200


@bp.post("/access-conversion-plans/<plan_id>/maturation-checks")
def file_maturation_check(plan_id):
    authenticate(("Interventionalist", "AccessCoordinator"))
    plan = must_get(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    body = get_body()
    diameter_mm = req_num(body, "diameter_mm", minimum=0)
    flow_ml_min = req_num(body, "flow_ml_min", minimum=0)
    depth_mm = req_num(body, "depth_mm", minimum=0)

    if plan["status"] in ("DRAFT", "CONVERTED", "ABANDONED"):
        raise ApiError("ERR_PLAN_STATE_INVALID")

    # Rung 27: target-access convertibility.
    target = db.accesses.get(plan["target_access_id"]) if plan["target_access_id"] else None
    if target is None or target["status"] not in CONVERTIBLE_TARGET_STATUSES:
        raise ApiError("ERR_TARGET_ACCESS_NOT_CONVERTIBLE")

    ready, reasons, days = calc.evaluate_maturation(target, diameter_mm, flow_ml_min, depth_mm)

    plan["maturation_check_count"] += 1
    plan["last_check_at"] = now_str()
    plan["last_diameter_mm"] = diameter_mm
    plan["last_flow_ml_min"] = flow_ml_min
    plan["last_depth_mm"] = depth_mm
    plan["days_since_placement"] = days
    plan["readiness_met"] = ready
    plan["readiness_failure_reasons"] = reasons

    if not ready and plan["status"] == "ACTIVE":
        plan["status"] = "MATURATION_HOLD"
    elif ready and plan["status"] == "MATURATION_HOLD":
        plan["status"] = "ACTIVE"
    touch(plan)

    return envelope_object(public(plan)), 200


@bp.get("/access-conversion-plans/<plan_id>")
def get_plan(plan_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist"))
    plan = must_get(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    return envelope_object(public(plan)), 200


@bp.get("/access-conversion-plans")
def list_plans():
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist"))
    rows = list(db.plans.values())
    rows = filter_equals(rows, "patient_id", request.args.get("patient_id"))
    rows = filter_equals(rows, "from_access_id", request.args.get("from_access_id"))
    rows = filter_equals(rows, "target_access_id", request.args.get("target_access_id"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return list_response(calc.seq_sorted(rows))


# ---------------------------------------------------------------------------
# Infection events
# ---------------------------------------------------------------------------
@bp.post("/infection-events")
def create_infection_event():
    authenticate(("Interventionalist", "AccessCoordinator", "CenterAdmin"))
    body = get_body()
    procedure_id = req_id(body, "procedure_id")
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    organism = req_str(body, "organism")
    onset_raw, onset_dt = req_dt(body, "onset_at")

    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    if procedure["clinical_status"] != "DISCHARGED":
        raise ApiError("ERR_PROCEDURE_TERMINAL")

    discharged_at = parse_dt(procedure["discharged_at"])
    elapsed = (onset_dt - discharged_at).total_seconds()
    days_post_procedure = int(math.floor(elapsed / 86400.0))
    attributable = 0 <= days_post_procedure <= calc.ATTRIBUTION_WINDOW_DAYS

    event = base_record()
    event.update({
        "procedure_id": procedure_id,
        "access_id": procedure["access_id"],
        "event_type": event_type,
        "organism": organism,
        "onset_at": onset_raw,
        "days_post_procedure": days_post_procedure,
        "attributable": attributable,
    })
    db.infections[event["id"]] = event

    if attributable:
        access = db.accesses.get(procedure["access_id"])
        if access is not None:
            access["attributable_infection_count"] += 1
            access["intervention_burden_score"] = calc.burden_score(access)
            touch(access)
            if (access["attributable_infection_count"] >= calc.INFECTION_DYSFUNCTION_THRESHOLD
                    and access["status"] == "IN_USE"):
                access["status"] = "DYSFUNCTIONAL"
                touch(access)

    return envelope_object(public(event)), 201


@bp.get("/infection-events/<event_id>")
def get_infection_event(event_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist"))
    event = must_get(db.infections, event_id, "ERR_INFECTION_EVENT_NOT_FOUND")
    return envelope_object(public(event)), 200


@bp.get("/infection-events")
def list_infection_events():
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist"))
    rows = list(db.infections.values())
    rows = filter_equals(rows, "access_id", request.args.get("access_id"))
    rows = filter_equals(rows, "procedure_id", request.args.get("procedure_id"))
    rows = filter_bool(rows, "attributable", request.args.get("attributable"))
    rows.sort(key=lambda e: (parse_dt(e["onset_at"]), e["created_at"], e["_seq"]))
    return list_response(rows)
