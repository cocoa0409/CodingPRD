"""Site control instrument routes."""
import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_string, req_enum, req_number, req_iso,
    success_obj, success_arr, pagination_args, paginate, now_common, touch,
    iso_from_epoch,
)
from serializers import sci_view
from logic import get_project, get_sci

READ_ROLES = ["DeveloperAdmin", "TaxCounsel", "Auditor", "PlatformAdmin"]


def register(app):

    @app.post("/api/projects/<pid>/site-control-instruments")
    def create_sci(pid):
        require_auth(["DeveloperAdmin"])
        get_project(pid)
        body = payload()
        parcel_id = req_string(body, "parcel_id")
        instrument_type = req_enum(body, "instrument_type", {"LAND_OPTION", "EASEMENT"})
        start = req_iso(body, "start_date")
        end = req_iso(body, "end_date")
        price = req_number(body, "exercise_price_usd")
        if end <= start:
            raise_err("ERR_VALIDATION", "end_date must be strictly greater than start_date")
        sid = db.new_id()
        s = {
            "id": sid,
            "project_id": pid,
            "parcel_id": parcel_id,
            "instrument_type": instrument_type,
            "start_date": iso_from_epoch(start),
            "end_date": iso_from_epoch(end),
            "_start_epoch": start,
            "_end_epoch": end,
            "exercise_price_usd": float(price),
            "status": "DRAFT",
        }
        now_common(s)
        db.site_control_instruments[sid] = s
        return success_obj(sci_view(s), 201)

    @app.get("/api/projects/<pid>/site-control-instruments")
    def list_sci(pid):
        require_auth(READ_ROLES)
        get_project(pid)
        limit, offset = pagination_args()
        items = sorted(
            [s for s in db.site_control_instruments.values() if s["project_id"] == pid],
            key=lambda s: (s["created_at"], s["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr([sci_view(s) for s in page], limit, offset, total)

    @app.get("/api/site-control-instruments/<sid>")
    def get_sci_route(sid):
        require_auth(READ_ROLES)
        s = get_sci(sid)
        return success_obj(sci_view(s))

    @app.post("/api/site-control-instruments/<sid>/transitions")
    def sci_transition(sid):
        require_auth(["DeveloperAdmin"])
        s = get_sci(sid)
        body = payload()
        to = req_enum(body, "to", {"EXECUTED", "EXERCISED", "RECORDED", "EXPIRED", "TERMINATED"})
        cur = s["status"]
        valid = {
            ("DRAFT", "EXECUTED"),
            ("EXECUTED", "EXERCISED"),
            ("EXERCISED", "RECORDED"),
            ("EXECUTED", "TERMINATED"),
            ("EXERCISED", "TERMINATED"),
        }
        if (cur, to) not in valid:
            raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to {to}")

        if to == "EXECUTED":
            # Parcel overlap check: half-open [start, end); adjacency is not overlap
            for other in db.site_control_instruments.values():
                if other["id"] == sid:
                    continue
                if other["parcel_id"] != s["parcel_id"]:
                    continue
                if other["status"] not in ("EXECUTED", "EXERCISED", "RECORDED"):
                    continue
                if other["_start_epoch"] < s["_end_epoch"] and s["_start_epoch"] < other["_end_epoch"]:
                    raise_err("ERR_PARCEL_OVERLAP",
                              "Overlapping active instrument on the same parcel")
            s["status"] = "EXECUTED"
            touch(s)
            return success_obj(sci_view(s))

        if to == "EXERCISED":
            if db.clock_now() > s["_end_epoch"]:
                s["status"] = "EXPIRED"
                touch(s)
                raise_err("ERR_OPTION_WINDOW_LAPSED",
                          "Exercise attempted after end_date; instrument expired")
            s["status"] = "EXERCISED"
            touch(s)
            return success_obj(sci_view(s))

        if to == "RECORDED":
            s["status"] = "RECORDED"
            touch(s)
            return success_obj(sci_view(s))

        if to == "TERMINATED":
            s["status"] = "TERMINATED"
            touch(s)
            if cur == "EXERCISED":
                project = db.projects.get(s["project_id"])
                if project is not None and project["status"] == "SITE_SECURED":
                    remaining = any(
                        x["project_id"] == project["id"] and x["id"] != sid
                        and x["status"] in ("EXERCISED", "RECORDED")
                        for x in db.site_control_instruments.values()
                    )
                    if not remaining:
                        project["status"] = "PROSPECT"
                        touch(project)
            return success_obj(sci_view(s))

        raise_err("ERR_INVALID_STATE", f"Unsupported transition to {to}")
