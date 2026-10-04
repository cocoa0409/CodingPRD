"""PerformanceTest routes: schedule/list/get/record-results/cancel."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from pagination import paginate
from response import success_object, success_list
from services import (active_esa_for_project, measurement_basis_for,
                      evaluate_capacity_test, evaluate_rte_test,
                      auto_augmentation_added_capacity, recompute_projection,
                      recompute_augmentation_count)
from util import new_id, stamp_new, touch, req_enum, parse_iso, to_number

bp = Blueprint("tests", __name__)

TEST_TYPES = {"CAPACITY_TEST", "RTE_TEST"}


def serialize_test(t):
    return dict(t)


def get_test_or_404(tid):
    t = store.tests.get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PerformanceTest not found")
    return t


def _overlaps(s1, e1, s2, e2):
    """Half-open [s,e) overlap: adjacency is allowed."""
    return s1 < e2 and s2 < e1


@bp.route("/performance-tests", methods=["POST"])
@require_roles({"PerformanceEngineer"})
def create_test():
    body = request.get_json(silent=True) or {}
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or project_id not in store.projects:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "project_id does not reference an existing Project")
    project = store.projects[project_id]
    test_type = req_enum(body, "test_type", TEST_TYPES)
    ws_raw = body.get("window_start")
    we_raw = body.get("window_end")
    ws = parse_iso(ws_raw, "window_start")
    we = parse_iso(we_raw, "window_end")
    # structural: window ordering before overlap (both priority 7; ERR_INVALID_WINDOW first)
    if we <= ws:
        raise ApiError("ERR_INVALID_WINDOW", 409, "window_end must be strictly after window_start")
    # cross-entity state: project must have an ESA in EXECUTED or COMPLETED
    if active_esa_for_project(project_id) is None:
        raise ApiError("ERR_NO_ACTIVE_ESA", 409,
                       "Project must have an ESA in EXECUTED or COMPLETED")
    # structural: overlap among non-CANCELLED tests on the same project
    for t in store.tests.values():
        if t["project_id"] == project_id and t["status"] in ("SCHEDULED", "PASSED", "FAILED"):
            ts = parse_iso(t["window_start"], "window_start")
            te = parse_iso(t["window_end"], "window_end")
            if _overlaps(ws, we, ts, te):
                raise ApiError("ERR_TEST_WINDOW_OVERLAP", 409,
                               "Test window overlaps another non-CANCELLED test on this project")
    t = {
        "id": new_id(),
        "project_id": project_id,
        "test_type": test_type,
        "window_start": ws_raw,
        "window_end": we_raw,
        "measurement_basis": measurement_basis_for(project),
        "measured_capacity_mwh": None,
        "aux_load_mwh": None,
        "rte_intervals": None,
        "evaluated_capacity_mwh": None,
        "measured_rte_pct": None,
        "result": None,
        "status": "SCHEDULED",
    }
    stamp_new(t)
    store.tests[t["id"]] = t
    return success_object(serialize_test(t), 201)


@bp.route("/performance-tests", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_tests():
    project_id = request.args.get("project_id")
    items = [t for t in store.tests.values()
             if project_id is None or t["project_id"] == project_id]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_test(t) for t in page], limit, offset, total)


@bp.route("/performance-tests/<tid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_test(tid):
    return success_object(serialize_test(get_test_or_404(tid)))


@bp.route("/performance-tests/<tid>/record-results", methods=["POST"])
@require_roles({"PerformanceEngineer"})
def record_results(tid):
    t = get_test_or_404(tid)
    if t["status"] != "SCHEDULED":
        raise ApiError("ERR_TEST_NOT_SCHEDULED", 409, "Test must be SCHEDULED")
    now = store.clock()
    ws = parse_iso(t["window_start"], "window_start")
    we = parse_iso(t["window_end"], "window_end")
    if not (ws <= now < we):
        raise ApiError("ERR_TEST_WINDOW_NOT_OPEN", 409,
                       "Logical clock must be within [window_start, window_end)")
    project = store.projects.get(t["project_id"])
    esa = active_esa_for_project(t["project_id"])
    if esa is None:
        raise ApiError("ERR_NO_ACTIVE_ESA", 409,
                       "Project must have an ESA in EXECUTED or COMPLETED")

    body = request.get_json(silent=True) or {}
    if t["test_type"] == "CAPACITY_TEST":
        measured = body.get("measured_capacity_mwh")
        aux = body.get("aux_load_mwh", 0)
        if isinstance(measured, bool) or not isinstance(measured, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", 400, "measured_capacity_mwh is required and must be a number")
        if isinstance(aux, bool) or not isinstance(aux, (int, float)) or aux < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "aux_load_mwh must be a non-negative number")
        t["measured_capacity_mwh"] = measured
        t["aux_load_mwh"] = aux
        result, evaluated = evaluate_capacity_test(t, project, esa, measured, aux)
        t["status"] = "PASSED" if result == "PASS" else "FAILED"
        touch(t)
        if result == "FAIL":
            # auto augmentation event: shortfall grossed up, window = [now, now+30d)
            recompute_projection(project)
            added = auto_augmentation_added_capacity(
                esa, project["projected_capacity_mwh"], evaluated)
            window_end = now + timedelta(days=30)
            ev = {
                "id": new_id(),
                "project_id": project["id"],
                "planned_window_start": _fmt(now),
                "planned_window_end": _fmt(window_end),
                "added_capacity_mwh": to_number(added),
                "origin": "AUTO",
                "status": "PLANNED",
            }
            stamp_new(ev)
            store.augmentations[ev["id"]] = ev
            recompute_projection(project)
            recompute_augmentation_count(project)
            touch(project)
    else:  # RTE_TEST
        intervals = body.get("rte_intervals")
        if (not isinstance(intervals, list) or len(intervals) == 0):
            raise ApiError("ERR_INVALID_RTE_INTERVALS", 400,
                           "rte_intervals must be a non-empty list")
        for it in intervals:
            if not isinstance(it, dict):
                raise ApiError("ERR_INVALID_RTE_INTERVALS", 400, "each interval must be an object")
            charge = it.get("charge_mwh")
            discharge = it.get("discharge_mwh")
            if (isinstance(charge, bool) or not isinstance(charge, (int, float)) or charge <= 0):
                raise ApiError("ERR_INVALID_RTE_INTERVALS", 400, "charge_mwh must be > 0")
            if (isinstance(discharge, bool) or not isinstance(discharge, (int, float)) or discharge < 0):
                raise ApiError("ERR_INVALID_RTE_INTERVALS", 400, "discharge_mwh must be >= 0")
        t["rte_intervals"] = intervals
        result = evaluate_rte_test(t, esa, intervals)
        t["status"] = "PASSED" if result == "PASS" else "FAILED"
        touch(t)
    return success_object(serialize_test(t))


@bp.route("/performance-tests/<tid>/cancel", methods=["POST"])
@require_roles({"PerformanceEngineer"})
def cancel_test(tid):
    t = get_test_or_404(tid)
    if t["status"] != "SCHEDULED":
        raise ApiError("ERR_TEST_NOT_SCHEDULED", 409, "Test must be SCHEDULED")
    t["status"] = "CANCELLED"
    touch(t)
    return success_object(serialize_test(t))


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
