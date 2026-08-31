"""Episode lifecycle: admission, readmission bundle, readiness, revert,
cancellation, discharge and throughput reporting (PRD 3.2, 3.8, 3.9)."""

from flask import Blueprint

import calc
import cascade
import derive
from envelope import created, filter_eq, list_response, ok
from errors import ApiError
from store import base_row, db, ordered, parse_dt, touch
from validate import (ADMISSION_TYPES, DISPOSITIONS, REVERT_REASON_CODES,
                      actor, body, opt_bool, present, req_dt, req_enum,
                      req_num, req_str, require_roles)

bp = Blueprint("episodes", __name__)

PLACEMENT_DISPOSITIONS = {"SNF", "IRF", "LTACH", "HOME_WITH_HH"}


@bp.post("/episodes")
def create_episode():
    require_roles("CaseManager")
    b = body()
    patient_id = req_str(b, "patient_id")
    admission_type = req_enum(b, "admission_type", ADMISSION_TYPES)
    drg_code = req_str(b, "drg_code")
    gmlos = req_num(b, "drg_gmlos_days", exclusive_min=0)
    attending_unit = req_str(b, "attending_unit")
    admitted_raw, admitted_dt = req_dt(b, "admitted_at")
    derive.get_patient(patient_id)
    if admitted_dt > db.now():
        raise ApiError("ERR_INVALID_INTERVAL", "admitted_at may not be later than the clock")
    row = base_row()
    row.update({
        "patient_id": patient_id,
        "admission_type": admission_type,
        "drg_code": drg_code,
        "drg_gmlos_days": gmlos,
        "attending_unit": attending_unit,
        "admitted_at": admitted_raw,
        "assigned_case_manager_id": actor(),
        "case_status": "ADMITTED",
        "discharge_disposition": None,
        "pcp_followup_booked": False,
        "med_reconciliation_completed": False,
        "tcm_call_scheduled": False,
        "home_monitoring_enrolled": False,
        "marked_ready_by_user_id": None,
        "marked_ready_at": None,
        "discharged_at": None,
        "_ever_ready": False,
    })
    db.episodes[row["id"]] = row
    return created(derive.ser_episode(row))


@bp.get("/episodes/<eid>")
def read_episode(eid):
    require_roles("CaseManager", "UtilizationReviewNurse", "DischargeCoordinator",
                  "PlatformAdmin")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    return ok(derive.ser_episode(episode))


@bp.get("/episodes")
def list_episodes():
    require_roles("CaseManager", "UtilizationReviewNurse", "PlatformAdmin")
    rows = ordered(db.episodes.values())
    for row in rows:
        derive.sweep_episode(row)
    rows = filter_eq(rows, "patient_id", "patient_id")
    rows = filter_eq(rows, "case_status", "case_status")
    return list_response(rows, derive.ser_episode)


@bp.post("/episodes/<eid>/readmission-bundle")
def readmission_bundle(eid):
    require_roles("CaseManager")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    b = body()
    flags = ("pcp_followup_booked", "med_reconciliation_completed",
             "tcm_call_scheduled", "home_monitoring_enrolled")
    supplied = {}
    for flag in flags:
        value = opt_bool(b, flag, None)
        if value is not None:
            supplied[flag] = value
    for flag, value in supplied.items():
        episode[flag] = value
    cascade.advance_to_planning(episode)
    touch(episode)
    return ok(derive.ser_episode(episode))


@bp.post("/episodes/<eid>/mark-ready")
def mark_ready(eid):
    require_roles("CaseManager")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    b = body()
    disposition = req_enum(b, "discharge_disposition", DISPOSITIONS)

    # Preconditions, in the order pinned by PRD 3.8.
    if episode["case_status"] != "PLANNING":
        raise ApiError("ERR_INVALID_EPISODE_STATE", "episode is not in PLANNING")
    if derive.barrier_posture(episode) == "ESCALATED":
        raise ApiError("ERR_ESCALATED_POSTURE", "barrier posture is ESCALATED")
    for barrier in derive.barriers_of(episode["id"]):
        if barrier["status"] in ("OPEN", "MITIGATING"):
            raise ApiError("ERR_BARRIER_UNRESOLVED", "an unresolved barrier remains")
    _score, pre_band, _variant = derive.episode_risk(episode)
    if not calc.bundle_complete(episode, pre_band):
        raise ApiError("ERR_READMISSION_BUNDLE_INCOMPLETE",
                       "the readmission intervention bundle is incomplete")
    if disposition in PLACEMENT_DISPOSITIONS:
        placed = [r for r in derive.referrals_of(episode["id"]) if r["status"] == "PLACED"]
        if not placed:
            raise ApiError("ERR_PLACEMENT_NOT_CONFIRMED", "no PLACED referral on this episode")

    episode["discharge_disposition"] = disposition
    episode["marked_ready_by_user_id"] = actor()
    episode["marked_ready_at"] = db.now_iso()
    episode["case_status"] = "READY_FOR_DISCHARGE"
    episode["_ever_ready"] = True
    touch(episode)
    return ok(derive.ser_episode(episode))


@bp.post("/episodes/<eid>/revert-to-planning")
def revert_to_planning(eid):
    require_roles("CaseManager", "UtilizationReviewNurse")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    b = body()
    reason_code = req_enum(b, "reason_code", REVERT_REASON_CODES)
    if reason_code == "PATIENT_LEFT_AMA":
        if episode["case_status"] not in ("ADMITTED", "SCREENED", "PLANNING",
                                          "READY_FOR_DISCHARGE"):
            raise ApiError("ERR_INVALID_EPISODE_STATE", "episode may not be cancelled")
        cascade.cancel_episode(episode)
    else:
        if episode["case_status"] != "READY_FOR_DISCHARGE":
            raise ApiError("ERR_INVALID_EPISODE_STATE",
                           "episode is not READY_FOR_DISCHARGE")
        cascade.revert_to_planning(episode, reason_code=reason_code)
    return ok(derive.ser_episode(episode))


@bp.post("/episodes/<eid>/discharge")
def discharge(eid):
    require_roles("DischargeCoordinator")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    if episode["case_status"] != "READY_FOR_DISCHARGE":
        raise ApiError("ERR_INVALID_EPISODE_STATE", "episode is not READY_FOR_DISCHARGE")
    if derive.barrier_posture(episode) == "ESCALATED":
        raise ApiError("ERR_ESCALATED_POSTURE", "barrier posture is ESCALATED")
    if actor() == episode.get("marked_ready_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the discharging operator must differ from the one who marked ready")
    for order in derive.orders_of(episode["id"]):
        if order["status"] == "REQUESTED":
            raise ApiError("ERR_LOGISTICS_NOT_CONFIRMED",
                           "a logistics order is still REQUESTED")
    cascade.discharge_episode(episode)
    return ok(derive.ser_episode(episode))


@bp.get("/episodes/<eid>/throughput")
def throughput(eid):
    require_roles("PlatformAdmin", "CaseManager", "UtilizationReviewNurse")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    metrics = derive.throughput_metrics(episode)
    return ok({
        "los_hours": metrics["los_hours"],
        "avoidable_delay_hours": metrics["avoidable_delay_hours"],
        "adjusted_los_hours": metrics["adjusted_los_hours"],
        "expected_los_hours": metrics["expected_los_hours"],
        "observed_expected_ratio": metrics["observed_expected_ratio"],
        "throughput_grade": metrics["throughput_grade"],
        "current_risk_score": metrics["current_risk_score"],
        "current_risk_band": metrics["current_risk_band"],
        "barriers_ever_opened_count": derive.barriers_ever_opened_count(episode),
    })
