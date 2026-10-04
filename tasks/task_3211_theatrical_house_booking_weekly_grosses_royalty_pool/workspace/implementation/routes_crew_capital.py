"""Crew assignments and capital projects."""
from flask import Blueprint

import errors as E
import services as S
from db import STORE
from middleware import require_roles
from response import (new_common, ok_object, require_field, require_int,
                      parse_dt, fmt_dt, now_ts, touch, get_json_body)

bp = Blueprint("crew_capital", __name__)


# ------------------------------------------------------------- crew

@bp.post("/theatres/bookings/<bid>/crew-assignments")
def create_crew_assignment(bid):
    require_roles("HouseManager")
    booking = STORE.bookings.get(bid)
    if not booking:
        raise E.not_found("Booking not found")
    body = get_json_body()
    crew_size = require_int(require_field(body, "crew_size"), "crew_size")
    theatre = STORE.theatres.get(booking["theatre_id"])
    if crew_size < S.UNION_MIN_CREW[theatre["size_class"]]:
        raise E.union_min_crew()
    rec = new_common()
    rec.update({"booking_id": bid, "crew_size": crew_size, "engaged_at": now_ts()})
    STORE.crew_assignments[rec["id"]] = rec
    return ok_object(rec, 201)


# ------------------------------------------------------------- capital projects

def _get_project_or_404(pid):
    p = STORE.capital_projects.get(pid)
    if not p:
        raise E.not_found("Capital project not found")
    return p


def _held_bookings_in_window(project):
    from services import loadout_done_dt
    ws = parse_dt(project["window_start"], "window_start")
    we = parse_dt(project["window_end"], "window_end")
    out = []
    for b in STORE.bookings.values():
        if b["status"] != "MAINTENANCE_HOLD" or b["theatre_id"] != project["theatre_id"]:
            continue
        lo = loadout_done_dt(b)
        if ws <= lo < we:
            out.append(b)
    return out


@bp.post("/theatres/houses/<tid>/capital-projects")
def create_project(tid):
    require_roles("HouseManager")
    theatre = STORE.theatres.get(tid)
    if not theatre:
        raise E.not_found("Theatre not found")
    body = get_json_body()
    description = require_field(body, "description")
    ws = parse_dt(require_field(body, "window_start"), "window_start")
    we = parse_dt(require_field(body, "window_end"), "window_end")
    if we <= ws:
        raise E.invalid_request("window_end must be > window_start")
    rec = new_common()
    rec.update({"theatre_id": tid, "description": description,
                "window_start": fmt_dt(ws), "window_end": fmt_dt(we),
                "status": "SCHEDULED"})
    STORE.capital_projects[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/theatres/capital-projects/<pid>")
def get_project(pid):
    require_roles("HouseManager", "CompanyRep")
    return ok_object(_get_project_or_404(pid))


@bp.post("/theatres/capital-projects/<pid>/complete")
def complete_project(pid):
    require_roles("HouseManager")
    project = _get_project_or_404(pid)
    if project["status"] != "SCHEDULED":
        raise E.already_terminal("Only a SCHEDULED capital project can be completed")
    project["status"] = "COMPLETED"
    touch(project)
    S.release_held_bookings(project)
    return ok_object(project)


@bp.post("/theatres/capital-projects/<pid>/cancel")
def cancel_project(pid):
    require_roles("HouseManager")
    project = _get_project_or_404(pid)
    if project["status"] != "SCHEDULED":
        raise E.already_terminal("Only a SCHEDULED capital project can be cancelled")
    if _held_bookings_in_window(project):
        raise E.capital_project_in_use()
    project["status"] = "CANCELLED"
    touch(project)
    return ok_object(project)
