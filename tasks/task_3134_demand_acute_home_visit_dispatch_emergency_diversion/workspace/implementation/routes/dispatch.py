"""Dispatch assignments: list/get/accept/reject/cancel/arrive."""
from datetime import timedelta

import db
import helpers as H
import services as S
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_DISPATCH_INVALID_STATE,
    ERR_NOT_ASSIGNED_TEAM_MEMBER, ERR_SHIFT_NOT_OPERATIONAL,
)
from middleware import require_roles
from response import success_object, success_list

DA_LIST_ROLES = {"PlatformAdmin", "Dispatcher", "TriageNurse"}
DA_GET_ROLES = {"PlatformAdmin", "Dispatcher", "TriageNurse", "CareTeamMember"}


def _get_da(da_id):
    da = db.STORES["dispatch_assignments"].get(da_id)
    if da is None:
        raise_err(ERR_NOT_FOUND, "dispatch assignment not found")
    return da


def _check_team_member(user_id, da):
    team = db.STORES["care_teams"].get(da["care_team_id"])
    if team is None:
        raise_err(ERR_NOT_FOUND, "care team not found")
    if user_id not in (team["app_user_id"], team["tech_user_id"]):
        raise_err(ERR_NOT_ASSIGNED_TEAM_MEMBER, "actor is not a member of the assigned care team")
    return team


def register(app):

    @app.get("/dh/dispatch-assignments")
    def list_dispatch_assignments():
        require_roles(DA_LIST_ROLES)
        with db.lock():
            S.run_system_sweeps()
            page, total, limit, offset = H.list_response(
                list(db.STORES["dispatch_assignments"].values()),
                filters={
                    "care_team_id": H.request.args.get("care_team_id"),
                    "vehicle_shift_id": H.request.args.get("vehicle_shift_id"),
                    "visit_request_id": H.request.args.get("visit_request_id"),
                    "status": H.request.args.get("status"),
                },
            )
        return success_list(page, total, limit, offset)

    @app.get("/dh/dispatch-assignments/<da_id>")
    def get_dispatch_assignment(da_id):
        require_roles(DA_GET_ROLES)
        with db.lock():
            S.run_system_sweeps()
            da = _get_da(da_id)
        return success_object(da)

    @app.post("/dh/dispatch-assignments/<da_id>/accept")
    def accept_dispatch(da_id):
        user_id, _ = require_roles({"CareTeamMember"})
        with db.lock():
            S.run_system_sweeps()
            da = _get_da(da_id)
            if da["status"] != "OFFERED":
                raise_err(ERR_DISPATCH_INVALID_STATE, "dispatch is not OFFERED")
            _check_team_member(user_id, da)
            shift = db.STORES["vehicle_shifts"].get(da["vehicle_shift_id"])
            now = H.logical_now()
            if shift is None or not S.shift_operational(shift, now):
                raise_err(ERR_SHIFT_NOT_OPERATIONAL, "vehicle shift is not operational")
            now_str = H.fmt_dt(now)
            da["status"] = "EN_ROUTE"  # composite ACCEPTED -> EN_ROUTE
            da["accepted_at"] = now_str
            H.touch(da)
            vr = db.STORES["visit_requests"].get(da["visit_request_id"])
            market = db.STORES["markets"].get(vr["market_id"])
            window = (market["response_window_minutes_urgent"]
                      if vr.get("acuity_band") == "URGENT"
                      else market["response_window_minutes_standard"])
            vr["assigned_care_team_id"] = da["care_team_id"]
            vr["sla_deadline_at"] = H.fmt_dt(now + timedelta(minutes=window))
            vr["status"] = "EN_ROUTE"
            H.touch(vr)
        return success_object(da)

    @app.post("/dh/dispatch-assignments/<da_id>/reject")
    def reject_dispatch(da_id):
        user_id, _ = require_roles({"CareTeamMember"})
        with db.lock():
            S.run_system_sweeps()
            da = _get_da(da_id)
            if da["status"] != "OFFERED":
                raise_err(ERR_DISPATCH_INVALID_STATE, "dispatch is not OFFERED")
            _check_team_member(user_id, da)
            da["status"] = "REJECTED"
            H.touch(da)
            S.decr_team_dispatch(da["care_team_id"])
            vr = db.STORES["visit_requests"].get(da["visit_request_id"])
            vr["status"] = "TRIAGED"
            H.touch(vr)
            S.clear_assigned_team_if_all_dead(vr)
        return success_object(da)

    @app.post("/dh/dispatch-assignments/<da_id>/cancel")
    def cancel_dispatch(da_id):
        require_roles({"Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            da = _get_da(da_id)
            if da["status"] != "OFFERED":
                raise_err(ERR_DISPATCH_INVALID_STATE, "dispatch is not OFFERED")
            da["status"] = "CANCELLED"
            H.touch(da)
            S.decr_team_dispatch(da["care_team_id"])
            vr = db.STORES["visit_requests"].get(da["visit_request_id"])
            vr["status"] = "TRIAGED"
            H.touch(vr)
            S.clear_assigned_team_if_all_dead(vr)
        return success_object(da)

    @app.post("/dh/dispatch-assignments/<da_id>/arrive")
    def arrive_dispatch(da_id):
        user_id, _ = require_roles({"CareTeamMember"})
        with db.lock():
            S.run_system_sweeps()
            da = _get_da(da_id)
            if da["status"] != "EN_ROUTE":
                raise_err(ERR_DISPATCH_INVALID_STATE, "dispatch is not EN_ROUTE")
            _check_team_member(user_id, da)
            now = H.logical_now()
            now_str = H.fmt_dt(now)
            da["status"] = "ARRIVED"
            H.touch(da)
            vr = db.STORES["visit_requests"].get(da["visit_request_id"])
            encounter = H.new_entity()
            encounter.update({
                "visit_request_id": vr["id"],
                "dispatch_assignment_id": da["id"],
                "started_at": now_str,
                "ended_at": None,
                "status": "STARTED",
            })
            db.STORES["encounters"][encounter["id"]] = encounter
            vr["status"] = "ON_SCENE"
            # SLA latch: strict greater-than; arrival exactly at deadline is not a breach.
            if vr.get("sla_deadline_at") is not None:
                if now > H.parse_dt(vr["sla_deadline_at"]):
                    vr["sla_breached"] = True
            H.touch(vr)
        return success_object(encounter)
