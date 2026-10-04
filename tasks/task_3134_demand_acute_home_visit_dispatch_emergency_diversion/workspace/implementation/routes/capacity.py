"""Care teams and vehicle shifts."""
import db
import helpers as H
import services as S
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_TEAM_INVALID_STATE, ERR_TEAM_HAS_ACTIVE_DISPATCH,
    ERR_SHIFT_WINDOW_INVALID, ERR_SHIFT_OVERLAP, ERR_SHIFT_WINDOW_NOT_OPEN,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success_object, success_list

TEAM_LIST_ROLES = {"PlatformAdmin", "Dispatcher", "TriageNurse"}
TEAM_GET_ROLES = {"PlatformAdmin", "Dispatcher", "TriageNurse", "AdvancedPracticeProvider"}
SHIFT_ROLES = {"PlatformAdmin", "Dispatcher"}


def register(app):

    # ---------------- Care teams ----------------
    @app.post("/dh/care-teams")
    def create_care_team():
        require_roles({"Dispatcher"})
        body = H.get_json_body()
        market_id = H.require(body, "market_id", "string", fk_store="markets")
        app_user_id = H.require(body, "app_user_id", "string")
        tech_user_id = H.require(body, "tech_user_id", "string")
        physician_id = H.require(body, "supervising_physician_user_id", "string")
        skill_tags = H.require(body, "skill_tags", "array")
        for tag in skill_tags:
            if tag not in S.SKILL_TAGS:
                raise_err(ERR_INVALID_REQUEST, f"unknown skill tag: {tag}")
        with db.lock():
            S.run_system_sweeps()
            team = H.new_entity()
            team.update({
                "market_id": market_id,
                "app_user_id": app_user_id,
                "tech_user_id": tech_user_id,
                "supervising_physician_user_id": physician_id,
                "skill_tags": list(skill_tags),
                "status": "ROSTERED",
                "active_dispatch_count": 0,
            })
            db.STORES["care_teams"][team["id"]] = team
        return success_object(team, 201)

    @app.get("/dh/care-teams")
    def list_care_teams():
        require_roles(TEAM_LIST_ROLES)
        with db.lock():
            S.run_system_sweeps()
            page, total, limit, offset = H.list_response(
                list(db.STORES["care_teams"].values()),
                filters={
                    "market_id": H.request.args.get("market_id"),
                    "status": H.request.args.get("status"),
                },
            )
        return success_list(page, total, limit, offset)

    @app.get("/dh/care-teams/<tid>")
    def get_care_team(tid):
        require_roles(TEAM_GET_ROLES)
        with db.lock():
            S.run_system_sweeps()
            team = db.STORES["care_teams"].get(tid)
            if team is None:
                raise_err(ERR_NOT_FOUND, "care team not found")
        return success_object(team)

    @app.post("/dh/care-teams/<tid>/go-available")
    def go_available(tid):
        require_roles({"Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            team = db.STORES["care_teams"].get(tid)
            if team is None:
                raise_err(ERR_NOT_FOUND, "care team not found")
            if team["status"] != "ROSTERED":
                raise_err(ERR_TEAM_INVALID_STATE, "team is not ROSTERED")
            team["status"] = "AVAILABLE"
            H.touch(team)
        return success_object(team)

    @app.post("/dh/care-teams/<tid>/go-off-duty")
    def go_off_duty(tid):
        require_roles({"Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            team = db.STORES["care_teams"].get(tid)
            if team is None:
                raise_err(ERR_NOT_FOUND, "care team not found")
            if team["status"] != "AVAILABLE":
                raise_err(ERR_TEAM_INVALID_STATE, "team is not AVAILABLE")
            if team.get("active_dispatch_count", 0) != 0:
                raise_err(ERR_TEAM_HAS_ACTIVE_DISPATCH, "team has active dispatch work")
            team["status"] = "OFF_DUTY"
            H.touch(team)
        return success_object(team)

    # ---------------- Vehicle shifts ----------------
    @app.post("/dh/vehicle-shifts")
    def create_vehicle_shift():
        require_roles({"Dispatcher"})
        body = H.get_json_body()
        care_team_id = H.require(body, "care_team_id", "string", fk_store="care_teams")
        market_id = H.require(body, "market_id", "string", fk_store="markets")
        vehicle_plate = H.require(body, "vehicle_plate", "string")
        window_start = H.require(body, "window_start", "datetime")
        window_end = H.require(body, "window_end", "datetime")
        start = H.parse_dt(window_start)
        end = H.parse_dt(window_end)
        if end <= start:
            raise_err(ERR_SHIFT_WINDOW_INVALID, "window_end must be after window_start")
        with db.lock():
            S.run_system_sweeps()
            for s in db.STORES["vehicle_shifts"].values():
                if s["care_team_id"] == care_team_id and s["status"] != "CANCELLED":
                    s_start = H.parse_dt(s["window_start"])
                    s_end = H.parse_dt(s["window_end"])
                    if s_start < end and start < s_end:
                        raise_err(ERR_SHIFT_OVERLAP, "shift window overlaps an existing shift")
            shift = H.new_entity()
            shift.update({
                "care_team_id": care_team_id,
                "market_id": market_id,
                "vehicle_plate": vehicle_plate,
                "window_start": window_start,
                "window_end": window_end,
                "status": "SCHEDULED",
                "overtime_minutes": 0,
                "shift_premium_cents": 0,
            })
            db.STORES["vehicle_shifts"][shift["id"]] = shift
        return success_object(shift, 201)

    @app.get("/dh/vehicle-shifts")
    def list_vehicle_shifts():
        require_roles(SHIFT_ROLES)
        with db.lock():
            S.run_system_sweeps()
            page, total, limit, offset = H.list_response(
                list(db.STORES["vehicle_shifts"].values()),
                filters={
                    "care_team_id": H.request.args.get("care_team_id"),
                    "market_id": H.request.args.get("market_id"),
                    "status": H.request.args.get("status"),
                },
            )
        return success_list(page, total, limit, offset)

    @app.get("/dh/vehicle-shifts/<sid>")
    def get_vehicle_shift(sid):
        require_roles(SHIFT_ROLES)
        with db.lock():
            S.run_system_sweeps()
            shift = db.STORES["vehicle_shifts"].get(sid)
            if shift is None:
                raise_err(ERR_NOT_FOUND, "vehicle shift not found")
        return success_object(shift)

    @app.post("/dh/vehicle-shifts/<sid>/start")
    def start_shift(sid):
        require_roles({"Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            shift = db.STORES["vehicle_shifts"].get(sid)
            if shift is None:
                raise_err(ERR_NOT_FOUND, "vehicle shift not found")
            if shift["status"] != "SCHEDULED":
                raise_err(ERR_TEAM_INVALID_STATE, "shift is not SCHEDULED")
            now = H.logical_now()
            if not (H.parse_dt(shift["window_start"]) <= now < H.parse_dt(shift["window_end"])):
                raise_err(ERR_SHIFT_WINDOW_NOT_OPEN, "logical clock outside shift window")
            shift["status"] = "ACTIVE"
            H.touch(shift)
        return success_object(shift)

    @app.post("/dh/vehicle-shifts/<sid>/extend")
    def extend_shift(sid):
        require_roles({"Dispatcher"})
        body = H.get_json_body()
        new_end_raw = H.require(body, "new_window_end", "datetime")
        new_end = H.parse_dt(new_end_raw)
        with db.lock():
            S.run_system_sweeps()
            shift = db.STORES["vehicle_shifts"].get(sid)
            if shift is None:
                raise_err(ERR_NOT_FOUND, "vehicle shift not found")
            if shift["status"] != "ACTIVE":
                raise_err(ERR_TEAM_INVALID_STATE, "shift is not ACTIVE")
            if new_end <= H.parse_dt(shift["window_end"]):
                raise_err(ERR_INVALID_REQUEST, "new_window_end must be later than current window_end")
            shift["window_end"] = new_end_raw
            shift["status"] = "EXTENDED"
            H.touch(shift)
        return success_object(shift)

    @app.post("/dh/vehicle-shifts/<sid>/close")
    def close_shift(sid):
        require_roles({"Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            shift = db.STORES["vehicle_shifts"].get(sid)
            if shift is None:
                raise_err(ERR_NOT_FOUND, "vehicle shift not found")
            if shift["status"] not in ("ACTIVE", "EXTENDED"):
                raise_err(ERR_TEAM_INVALID_STATE, "shift is not ACTIVE or EXTENDED")
            team = db.STORES["care_teams"].get(shift["care_team_id"])
            if team is not None and team.get("active_dispatch_count", 0) > 0:
                raise_err(ERR_TEAM_HAS_ACTIVE_DISPATCH, "team has active dispatch work")
            now = H.logical_now()
            end = H.parse_dt(shift["window_end"])
            overtime = max(0, int((now - end).total_seconds() // 60))
            shift["overtime_minutes"] = overtime
            shift["shift_premium_cents"] = overtime * 75
            shift["status"] = "CLOSED"
            H.touch(shift)
        return success_object(shift)

    @app.post("/dh/vehicle-shifts/<sid>/cancel")
    def cancel_shift(sid):
        require_roles({"Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            shift = db.STORES["vehicle_shifts"].get(sid)
            if shift is None:
                raise_err(ERR_NOT_FOUND, "vehicle shift not found")
            if shift["status"] != "SCHEDULED":
                raise_err(ERR_TEAM_INVALID_STATE, "shift is not SCHEDULED")
            shift["status"] = "CANCELLED"
            H.touch(shift)
        return success_object(shift)
