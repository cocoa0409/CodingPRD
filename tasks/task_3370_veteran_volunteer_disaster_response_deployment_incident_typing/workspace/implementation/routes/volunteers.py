"""Volunteer endpoints: register, get, readiness transitions / availability updates."""
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain
from constants import SKILLS, READINESS_STATUSES

bp = Blueprint("volunteers", __name__)

VOL_READ_ROLES = ("SystemAdmin", "SafetyOfficer", "OperationsLead",
                  "IncidentCommander", "TrainingDirector", "Volunteer")


@bp.post("/vdr/volunteers")
def create_volunteer():
    body = V.get_body()
    V.check_unknown(body, {"full_name", "email", "home_region", "skills",
                           "availability_windows", "instructor_certified"})
    full_name = V.req_str(body, "full_name")
    email = V.req_str(body, "email")
    home_region = V.req_str(body, "home_region")
    skills = V.req_list_enum(body, "skills", SKILLS)
    windows = V.opt_windows(body, "availability_windows", [])
    instructor = V.opt_bool(body, "instructor_certified", False)
    auth.require_roles("SystemAdmin")
    for existing in db.store["volunteers"].values():
        if existing["email"] == email:
            errors.validation("email must be unique across volunteers")
    vol = db.mint("volunteers", {
        "full_name": full_name,
        "email": email,
        "home_region": home_region,
        "skills": skills,
        "availability_windows": windows,
        "instructor_certified": instructor,
        "readiness_status": "REGISTERED",
        "operational_readiness_score": 0,
        "readiness_score": 0,
        "fatigue_hours": 0,
    })
    return envelope.ok(domain.public(vol), 201)


@bp.get("/vdr/volunteers/<vid>")
def get_volunteer(vid):
    uid, role = auth.require_roles(*VOL_READ_ROLES)
    vol = db.get("volunteers", vid)
    if vol is None:
        errors.volunteer_not_found()
    if role == "Volunteer" and uid != vid:
        errors.unauthorized("a Volunteer may only read their own record")
    return envelope.ok(domain.public(vol))


@bp.patch("/vdr/volunteers/<vid>")
def patch_volunteer(vid):
    body = V.get_body()
    V.check_unknown(body, {"readiness_status", "availability_windows"})
    readiness = V.opt_enum(body, "readiness_status", READINESS_STATUSES)
    has_windows = "availability_windows" in body
    windows = V.opt_windows(body, "availability_windows", None) if has_windows else None
    if readiness is None and not has_windows:
        errors.validation("no updatable field supplied")
    uid, role = auth.require_roles("SafetyOfficer", "Volunteer")
    if role == "Volunteer":
        if uid != vid:
            errors.unauthorized("a Volunteer may only update their own record")
        if readiness is not None:
            errors.unauthorized("readiness transitions are restricted to SafetyOfficer")
    else:  # SafetyOfficer
        if has_windows:
            errors.unauthorized("availability updates are restricted to the volunteer")
        if readiness is None:
            errors.validation("readiness_status is required")
    vol = db.get("volunteers", vid)
    if vol is None:
        errors.volunteer_not_found()
    if role == "Volunteer":
        vol["availability_windows"] = windows
        db.touch(vol)
        return envelope.ok(domain.public(vol))
    return _readiness_transition(vol, readiness)


def _readiness_transition(vol, target):
    cur = vol["readiness_status"]
    if (cur, target) == ("REGISTERED", "VETTED"):
        if not vol["full_name"] or not vol["email"] or not vol["home_region"] or not vol["skills"]:
            errors.validation("record incomplete: full_name, email, home_region and at least one skill are required")
        vol["readiness_status"] = "VETTED"
        db.touch(vol)
    elif (cur, target) == ("VETTED", "DEPLOYABLE"):
        if len(domain.verified_kinds(vol["id"])) < 1:
            errors.invalid_state("volunteer holds no VERIFIED certification")
        vol["readiness_status"] = "DEPLOYABLE"
        domain.recompute_readiness(vol)
        db.touch(vol)
    elif (cur, target) == ("DEPLOYABLE", "SUSPENDED"):
        vol["readiness_status"] = "SUSPENDED"
        db.touch(vol)
    elif (cur, target) == ("SUSPENDED", "DEPLOYABLE"):
        if domain.open_wellness_checks_for_volunteer(vol["id"]):
            errors.err("ERR_OPEN_WELLNESS_CHECKS", 409,
                       "open wellness checks block reinstatement")
        if len(domain.verified_kinds(vol["id"])) < 1:
            errors.err("ERR_OPEN_WELLNESS_CHECKS", 409,
                       "volunteer holds no VERIFIED certification")
        vol["readiness_status"] = "DEPLOYABLE"
        domain.recompute_readiness(vol)
        db.touch(vol)
    elif target == "INACTIVE" and cur in ("VETTED", "SUSPENDED"):
        active = [d for d in db.store["deployments"].values()
                  if d["volunteer_id"] == vol["id"]
                  and d["status"] in ("OFFERED", "ACCEPTED", "ON_SITE", "SAFETY_HOLD")]
        if active:
            errors.invalid_state("volunteer has active deployments")
        vol["readiness_status"] = "INACTIVE"
        db.touch(vol)
    else:
        errors.invalid_state(
            "cannot transition readiness_status from %s to %s" % (cur, target))
    return envelope.ok(domain.public(vol))
