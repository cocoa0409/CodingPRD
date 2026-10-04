"""Certification test runs (PRD §3.3): scheduling, results, review, invalidation."""
from flask import Blueprint

import calculations
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_num, f_enum, f_dt, get_or_404,
    envelope_ok, new_entity, touch, ser,
)

bp = Blueprint("test_runs", __name__)

TEST_TYPES = ("FTP", "RMC", "SET", "NTE")


@bp.post("/emissions/engine-families/<familyId>/test-runs")
def create_test_run(familyId):
    auth(("CertificationEngineer",))
    b = body()
    test_type = f_enum(b, "test_type", TEST_TYPES)
    lab_code = f_str(b, "lab_code")
    start = f_dt(b, "scheduled_start")
    end = f_dt(b, "scheduled_end")
    if not (end > start):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "scheduled_end must be strictly after scheduled_start")
    fam = get_or_404(store.families, familyId, "EngineFamily")
    if fam["certification_status"] not in ("TESTING", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Test runs schedule only while the family is TESTING or UNDER_REVIEW")
    if calculations.lab_window_conflict(lab_code, start, end):
        raise ApiError("ERR_LAB_WINDOW_OVERLAP", 409,
                       "Half-open window overlaps another SCHEDULED/COMPLETED run in this lab")
    ent = new_entity()
    ent.update({
        "engine_family_id": fam["id"],
        "test_type": test_type,
        "lab_code": lab_code,
        "scheduled_start": start,
        "scheduled_end": end,
        "measured_nox_g_per_bhp_hr": None,
        "measured_pm_g_per_bhp_hr": None,
        "deterioration_factor": 1.0,
        "adjusted_nox_g_per_bhp_hr": None,
        "adjusted_pm_g_per_bhp_hr": None,
        "result": "UNRECORDED",
        "status": "SCHEDULED",
        "reviewed_by_user_id": None,
        "invalidated_reason": None,
    })
    store.test_runs[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/test-runs/<rid>")
def get_test_run(rid):
    auth(ANY)
    ent = get_or_404(store.test_runs, rid, "CertificationTestRun")
    return envelope_ok(ser(ent), 200)


@bp.post("/emissions/test-runs/<rid>/record-results")
def record_results(rid):
    auth(("CertificationEngineer",))
    b = body()
    measured_nox = f_num(b, "measured_nox_g_per_bhp_hr")
    measured_pm = f_num(b, "measured_pm_g_per_bhp_hr")
    df = f_num(b, "deterioration_factor")
    run = get_or_404(store.test_runs, rid, "CertificationTestRun")
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "record-results requires SCHEDULED")
    fam = store.families.get(run["engine_family_id"])
    std = store.standards.get(fam["regulation_standard_id"]) if fam else None
    adj_nox, adj_pm, result = calculations.emissions_result(
        measured_nox, measured_pm, df,
        std["nox_limit_g_per_bhp_hr"], std["pm_limit_g_per_bhp_hr"])
    run["measured_nox_g_per_bhp_hr"] = measured_nox
    run["measured_pm_g_per_bhp_hr"] = measured_pm
    run["deterioration_factor"] = df
    run["adjusted_nox_g_per_bhp_hr"] = adj_nox
    run["adjusted_pm_g_per_bhp_hr"] = adj_pm
    run["result"] = result
    run["status"] = "COMPLETED"
    touch(run)
    return envelope_ok(ser(run), 200)


@bp.post("/emissions/test-runs/<rid>/review")
def review_test_run(rid):
    uid, _ = auth(("RegulatoryOfficer",))
    b = body()
    decision = f_enum(b, "decision", ("ACCEPT", "REJECT"))
    run = get_or_404(store.test_runs, rid, "CertificationTestRun")
    if run["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "review requires COMPLETED")
    if decision == "ACCEPT":
        if run["result"] != "PASS":
            raise ApiError("ERR_TEST_RESULT_NOT_PASS", 409,
                           "Cannot ACCEPT a run whose result is not PASS")
        run["status"] = "ACCEPTED"
    else:
        run["status"] = "REJECTED"
    run["reviewed_by_user_id"] = uid
    touch(run)
    return envelope_ok(ser(run), 200)


@bp.post("/emissions/test-runs/<rid>/invalidate")
def invalidate_test_run(rid):
    auth(("RegulatoryOfficer",))
    b = body()
    reason = f_str(b, "reason")
    run = get_or_404(store.test_runs, rid, "CertificationTestRun")
    if run["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "invalidate requires ACCEPTED")
    run["status"] = "INVALIDATED"
    run["invalidated_reason"] = reason
    touch(run)
    return envelope_ok(ser(run), 200)
