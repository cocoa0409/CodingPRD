"""Irrigation projects on the separate dealer channel."""
from flask import Blueprint

import calculations as calc
import clock
import helpers
from helpers import as_int, as_str, auth, body, fail, ok, req, require_role, identity_entity
import storage
from storage import STORES, new_record, public, sort_created, touch

bp = Blueprint("irrigation", __name__)

READ_ROLES = ("CorporateAdmin", "IrrigationDealer", "CourseManager")
LIVE_WINDOW_STATES = ("DESIGN_SUBMITTED", "APPROVED", "INSTALLED")

_TRANSITIONS = {
    ("BRIEF", "DESIGN_SUBMITTED"): "IrrigationDealer",
    ("DESIGN_SUBMITTED", "BRIEF"): "IrrigationDealer",
    ("DESIGN_SUBMITTED", "APPROVED"): "CourseManager",
    ("APPROVED", "INSTALLED"): "IrrigationDealer",
    ("INSTALLED", "COMMISSIONED"): "IrrigationDealer",
    ("BRIEF", "CANCELLED"): "IrrigationDealer",
    ("DESIGN_SUBMITTED", "CANCELLED"): "IrrigationDealer",
}


def _half_open_overlap(s1, e1, s2, e2):
    """Half-open [start, end) intersection; adjacency (end == start) allowed."""
    return s1 < e2 and s2 < e1


@bp.post("/irrigation-projects")
def create_project():
    role, uid = auth()
    require_role(role, ("IrrigationDealer",))
    dealer = identity_entity(role, uid)
    b = body()
    course_id = as_str(req(b, "course_id"), "course_id")
    helpers.get_or_404("courses", course_id, "course")
    acreage = as_int(req(b, "acreage"), "acreage")
    if acreage < 0:
        fail("ERR_INVALID_REQUEST", "acreage must be >= 0")
    zone_count = as_int(req(b, "zone_count"), "zone_count")
    if zone_count < 0:
        fail("ERR_INVALID_REQUEST", "zone_count must be >= 0")
    if dealer["channel"] != "IRRIGATION":
        fail("ERR_WRONG_CHANNEL", "irrigation projects require the IRRIGATION channel")
    if dealer["status"] == "TERMINATED":
        fail("ERR_DISTRIBUTOR_NOT_ACTIVE", "terminated distributor is read-only")
    rec = new_record("projects", {
        "dealer_id": uid,
        "course_id": course_id,
        "acreage": acreage,
        "zone_count": zone_count,
        "controller_model_id": None,
        "controllers_required": None,
        "design_fee_cents": None,
        "water_budget_gpd": None,
        "install_window_start": None,
        "install_window_end": None,
        "pinned_config_version": None,
        "controller_program_version": None,
        "status": "BRIEF",
        "_win_start": None,
        "_win_end": None,
    })
    return ok(public(rec), 201)


@bp.get("/irrigation-projects/<pid>")
def get_project(pid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    p = helpers.get_or_404("projects", pid, "project")
    return ok(public(p))


@bp.get("/irrigation-projects")
def list_projects():
    role, uid = auth()
    require_role(role, READ_ROLES)
    recs = helpers.apply_filters(sort_created(STORES["projects"].values()), {
        "dealer_id": "dealer_id",
        "course_id": "course_id",
        "status": "status",
        "controller_model_id": "controller_model_id",
    })
    return helpers.paginate(recs)


@bp.post("/irrigation-projects/<pid>/transition")
def transition_project(pid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    if role in ("IrrigationDealer", "CourseManager"):
        identity_entity(role, uid)
    p = helpers.get_or_404("projects", pid, "project")
    if role == "IrrigationDealer" and p["dealer_id"] != uid:
        fail("ERR_FORBIDDEN_OWNERSHIP", "project belongs to another dealer")
    if role == "CourseManager" and p["course_id"] != uid:
        fail("ERR_FORBIDDEN_OWNERSHIP", "project belongs to another course")
    b = body()
    to = as_str(req(b, "to"), "to")
    controller = None
    win_start = win_end = None
    win_start_raw = win_end_raw = None
    program_version = None
    if to == "DESIGN_SUBMITTED":
        controller_id = as_str(req(b, "controller_model_id"), "controller_model_id")
        controller = helpers.get_or_404("models", controller_id, "controller model")
        win_start_raw = as_str(req(b, "install_window_start"), "install_window_start")
        win_end_raw = as_str(req(b, "install_window_end"), "install_window_end")
        win_start = helpers.as_date(win_start_raw, "install_window_start")
        win_end = helpers.as_date(win_end_raw, "install_window_end")
        if not (win_start < win_end):
            fail("ERR_INVALID_REQUEST", "install_window_start must be strictly before install_window_end")
    elif to == "COMMISSIONED":
        program_version = as_str(req(b, "controller_program_version"), "controller_program_version")
    key = (p["status"], to)
    if key not in _TRANSITIONS:
        fail("ERR_INVALID_STATE", "project cannot move from " + p["status"] + " to " + str(to))
    if role != _TRANSITIONS[key]:
        fail("ERR_UNAUTHORIZED", "role " + role + " may not drive project to " + to)

    if key == ("BRIEF", "DESIGN_SUBMITTED"):
        # P10 temporal: window still in the future, then half-open non-overlap.
        if not (win_end > clock.today()):
            fail("ERR_WINDOW_IN_PAST", "install_window_end is not after the current logical date")
        for sib in STORES["projects"].values():
            if sib["course_id"] != p["course_id"] or sib["id"] == p["id"]:
                continue
            if sib["status"] in LIVE_WINDOW_STATES and sib["_win_start"] is not None:
                if _half_open_overlap(win_start, win_end, sib["_win_start"], sib["_win_end"]):
                    fail("ERR_WINDOW_OVERLAP", "install window overlaps a sibling project window")
        # P11 live controller reference.
        if controller["category"] != "IRRIGATION_CONTROLLER" or controller["lifecycle_status"] != "CATALOG_ACTIVE":
            fail("ERR_MODEL_DISCONTINUED", "controller model is not a CATALOG_ACTIVE IRRIGATION_CONTROLLER")
        course = STORES["courses"][p["course_id"]]
        spec = calc.irrigation_design_spec(p["acreage"], p["zone_count"], course["turf_profile"])
        p["controllers_required"] = spec["controllers_required"]
        p["design_fee_cents"] = spec["design_fee_cents"]
        p["water_budget_gpd"] = spec["water_budget_gpd"]
        p["controller_model_id"] = controller["id"]
        p["install_window_start"] = win_start_raw
        p["install_window_end"] = win_end_raw
        p["_win_start"] = win_start
        p["_win_end"] = win_end

    elif key == ("DESIGN_SUBMITTED", "BRIEF"):
        # Revision loop: design fields cleared for a fresh submission.
        p["controller_model_id"] = None
        p["controllers_required"] = None
        p["design_fee_cents"] = None
        p["water_budget_gpd"] = None
        p["install_window_start"] = None
        p["install_window_end"] = None
        p["_win_start"] = None
        p["_win_end"] = None

    elif key == ("DESIGN_SUBMITTED", "APPROVED"):
        controller = STORES["models"][p["controller_model_id"]]
        if controller["lifecycle_status"] != "CATALOG_ACTIVE":
            fail("ERR_STALE_REFERENCE", "pinned controller model has left CATALOG_ACTIVE")
        p["pinned_config_version"] = controller["version"]

    elif key == ("APPROVED", "INSTALLED"):
        if clock.today() < p["_win_start"]:
            fail("ERR_LEASE_NOT_STARTED", "current logical date is before install_window_start")

    elif key == ("INSTALLED", "COMMISSIONED"):
        p["controller_program_version"] = program_version

    p["status"] = to
    touch(p)
    return ok(public(p))
