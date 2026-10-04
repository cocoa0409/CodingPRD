"""Dairy farm program enrollments (PRD section 3.3).

blended_score = round_half_up(0.5*env_practice_score + 0.5*welfare_practice_score).
Assessment is allowed from ENROLLED and from ASSESSED (re-assessment self-loop
that deliberately does not recompute existing payments).
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from auth import authenticate, authorize
from db import STORE, new_resource, public, touch
from envelope import ok
from errors import fail
from validate import get_body, req_int, req_str

bp = Blueprint("farms", __name__)


def get_enrollment(eid):
    e = STORE["enrollments"].get(eid)
    if e is None:
        fail("ERR_ENROLLMENT_NOT_FOUND", "Enrollment id does not exist")
    return e


@bp.post("/enrollments")
def create_enrollment():
    _, role = authenticate()
    authorize(role, ("DairyProgramManager",))
    body = get_body()
    farm_name = req_str(body, "farm_name")
    region = req_str(body, "region")
    herd_size = req_int(body, "herd_size", 0)
    season_year = req_int(body, "season_year")
    baseline = req_int(body, "baseline_volume_liters", 0)
    r = new_resource()
    r.update({
        "farm_name": farm_name,
        "region": region,
        "herd_size": herd_size,
        "season_year": season_year,
        "baseline_volume_liters": baseline,
        "env_practice_score": None,
        "welfare_practice_score": None,
        "blended_score": None,
        "status": "ENROLLED",
        "total_approved_cents": 0,
    })
    STORE["enrollments"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/enrollments/<eid>")
def read_enrollment(eid):
    _, role = authenticate()
    authorize(role, ("DairyProgramManager", "ParentOpsController"))
    return ok(public(get_enrollment(eid)))


@bp.post("/enrollments/<eid>/assess")
def assess_enrollment(eid):
    _, role = authenticate()
    authorize(role, ("DairyProgramManager",))
    e = get_enrollment(eid)
    body = get_body()
    env_score = req_int(body, "env_practice_score", 0, 100)
    welfare_score = req_int(body, "welfare_practice_score", 0, 100)
    blended = int((Decimal("0.5") * env_score
                   + Decimal("0.5") * welfare_score).quantize(
                       Decimal("1"), rounding=ROUND_HALF_UP))
    e["env_practice_score"] = env_score
    e["welfare_practice_score"] = welfare_score
    e["blended_score"] = blended
    e["status"] = "ASSESSED"
    touch(e)
    return ok(public(e))
