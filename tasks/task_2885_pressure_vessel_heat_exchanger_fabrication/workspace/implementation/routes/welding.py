"""Welding procedures, welder continuity and the production weld map."""

from flask import Blueprint

import db
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from services import calc, derive

bp = Blueprint("welding", __name__)

PROCESSES = ("SMAW", "GTAW", "SAW", "FCAW")
POSITIONS = ("1G", "2G", "3G", "4G", "5G", "6G")
JOINT_CATEGORIES = ("A", "B", "C", "D")
JOINT_TYPES = ("BUTT", "CORNER", "FILLET")


# ---------------------------------------------------------------------------
# Welding procedure specifications (PRD 3.5)
# ---------------------------------------------------------------------------

@bp.post("/wps")
@guard(["WeldingEngineer"])
def create_wps(ctx):
    body = validation.body()
    wps_number = validation.string_field(body, "wps_number")
    process = validation.enum_field(body, "process", PROCESSES)
    p_number = validation.int_field(body, "base_metal_p_number")
    if p_number not in (1, 8):
        fail("ERR_INVALID_REQUEST", "base_metal_p_number must be 1 or 8.")
    filler = validation.int_field(body, "filler_f_number", minimum=1, maximum=6)
    thickness_min = validation.decimal_field(body, "thickness_min_in", scale=4,
                                            exclusive_min=0)
    thickness_max = validation.decimal_field(body, "thickness_max_in", scale=4)
    if thickness_max <= thickness_min:
        fail("ERR_INVALID_REQUEST",
             "thickness_max_in must be strictly greater than thickness_min_in.")
    position = validation.enum_field(body, "position", POSITIONS)
    pwht_required = validation.bool_field(body, "pwht_required")
    preheat_min_f = validation.decimal_field(body, "preheat_min_f", minimum=32)
    pqr_number = validation.string_field(body, "supporting_pqr_number")

    for other in db.all_of("wps"):
        if other["wps_number"] == wps_number:
            fail("ERR_DUPLICATE_WPS_NUMBER",
                 "Procedure %s already exists." % wps_number)

    record = db.insert("wps", {
        "wps_number": wps_number,
        "process": process,
        "base_metal_p_number": p_number,
        "filler_f_number": filler,
        "thickness_min_in": thickness_min,
        "thickness_max_in": thickness_max,
        "position": position,
        "pwht_required": pwht_required,
        "preheat_min_f": preheat_min_f,
        "supporting_pqr_number": pqr_number,
        "status": "DRAFT",
    })
    return common.created("wps", record)


@bp.get("/wps/<wps_id>")
@guard(ALL_ROLES)
def get_wps(ctx, wps_id):
    return common.one("wps", common.must_exist("wps", wps_id))


@bp.get("/wps")
@guard(ALL_ROLES)
def list_wps(ctx):
    return common.listing("wps", ["process", "status"])


@bp.post("/wps/<wps_id>/qualify")
@guard(["WeldingEngineer"])
def qualify_wps(ctx, wps_id):
    procedure = common.must_exist("wps", wps_id)
    if procedure["status"] != "DRAFT":
        fail("ERR_INVALID_WPS_STATE", "Only a DRAFT procedure may be qualified.")
    if not procedure["supporting_pqr_number"].strip():
        fail("ERR_INVALID_REQUEST",
             "The procedure carries no supporting PQR number.")
    db.mutate(procedure, {"status": "QUALIFIED"})
    return common.one("wps", procedure)


# ---------------------------------------------------------------------------
# Welder qualifications and continuity (PRD 3.5)
# ---------------------------------------------------------------------------

@bp.post("/welder-qualifications")
@guard(["WeldingEngineer"])
def create_qualification(ctx):
    body = validation.body()
    welder_stamp = validation.string_field(body, "welder_stamp")
    welder_name = validation.string_field(body, "welder_name")
    wps_id = validation.string_field(body, "wps_id")
    position = validation.enum_field(body, "position_qualified", POSITIONS)
    thickness_max = validation.decimal_field(body, "thickness_range_max_in", scale=4,
                                             exclusive_min=0)
    qualified_on = validation.date_field(body, "qualified_on")

    if db.get("wps", wps_id) is None:
        fail("ERR_WPS_NOT_FOUND", "No procedure carries id %s." % wps_id)
    for other in db.all_of("qualifications"):
        if other["welder_stamp"] == welder_stamp and other["wps_id"] == wps_id:
            fail("ERR_DUPLICATE_WELDER_QUALIFICATION",
                 "Welder %s already holds a qualification on this procedure."
                 % welder_stamp)

    record = db.insert("qualifications", {
        "welder_stamp": welder_stamp,
        "welder_name": welder_name,
        "wps_id": wps_id,
        "position_qualified": position,
        "thickness_range_max_in": thickness_max,
        "qualified_on": db.iso_date(qualified_on),
        "last_continuity_date": db.iso_date(qualified_on),
        "days_since_continuity": 0,
        "status": "QUALIFIED",
    })
    record["days_since_continuity"] = derive.qualification_days(record)
    record["status"] = derive.qualification_status(record)
    return common.created("qualifications", record)


@bp.get("/welder-qualifications/<qualification_id>")
@guard(ALL_ROLES)
def get_qualification(ctx, qualification_id):
    return common.one("qualifications",
                      common.must_exist("qualifications", qualification_id))


@bp.get("/welder-qualifications")
@guard(ALL_ROLES)
def list_qualifications(ctx):
    return common.listing("qualifications", ["wps_id", "welder_stamp", "status"],
                          derived_getters={"status": derive.qualification_status})


@bp.post("/welder-qualifications/<qualification_id>/continuity-logs")
@guard(["WeldingEngineer"])
def log_continuity(ctx, qualification_id):
    body = validation.body()
    continuity_date = validation.date_field(body, "continuity_date")
    process = validation.enum_field(body, "process", PROCESSES)

    qual = common.must_exist("qualifications", qualification_id)
    logged = continuity_date
    if logged > db.clock_today():
        fail("ERR_INVALID_REQUEST",
             "continuity_date may not be later than the current logical date.")
    if logged <= calc.parse_date(qual["last_continuity_date"]):
        fail("ERR_INVALID_REQUEST",
             "continuity_date must be later than the recorded continuity date.")
    procedure = db.get("wps", qual["wps_id"])
    if procedure is None or process != procedure["process"]:
        fail("ERR_INVALID_REQUEST",
             "process must equal the process of the cited procedure.")

    probe = dict(qual)
    probe["last_continuity_date"] = db.iso_date(continuity_date)
    db.mutate(qual, {
        "last_continuity_date": db.iso_date(continuity_date),
        "days_since_continuity": derive.qualification_days(probe),
        "status": derive.qualification_status(probe),
    })
    return common.one("qualifications", qual)


# ---------------------------------------------------------------------------
# The weld map (PRD 3.5)
# ---------------------------------------------------------------------------

def covering_nonconformance(weld):
    """The nonconformance raised against the joint this joint repairs."""
    parent_id = weld.get("repair_of_weld_id")
    if parent_id is None:
        return None
    covering = None
    for ncr in derive.children("nonconformances", "weld_id", parent_id):
        covering = ncr
    return covering


@bp.post("/vessel-jobs/<job_id>/production-welds")
@guard(["WeldingEngineer"])
def create_weld(ctx, job_id):
    body = validation.body()
    weld_number = validation.string_field(body, "weld_number")
    joint_category = validation.enum_field(body, "joint_category", JOINT_CATEGORIES)
    joint_type = validation.enum_field(body, "joint_type", JOINT_TYPES)
    thickness = validation.decimal_field(body, "thickness_in", scale=4, exclusive_min=0)
    wps_id = validation.string_field(body, "wps_id")
    part_a_id = validation.string_field(body, "part_a_id")
    part_b_id = validation.string_field(body, "part_b_id", required=False, default=None)

    job = common.must_exist("jobs", job_id)
    procedure = db.get("wps", wps_id)
    if procedure is None:
        fail("ERR_WPS_NOT_FOUND", "No procedure carries id %s." % wps_id)
    part_a = db.get("parts", part_a_id)
    if part_a is None:
        fail("ERR_PART_NOT_FOUND", "No piece carries id %s." % part_a_id)
    part_b = None
    if part_b_id is not None:
        part_b = db.get("parts", part_b_id)
        if part_b is None:
            fail("ERR_PART_NOT_FOUND", "No piece carries id %s." % part_b_id)

    # PRD 3.5: the two adequacy checks run before any state check on the job.
    if procedure["status"] != "QUALIFIED":
        fail("ERR_WPS_NOT_QUALIFIED",
             "Procedure %s is not QUALIFIED." % procedure["wps_number"])
    if (thickness < procedure["thickness_min_in"]
            or thickness > procedure["thickness_max_in"]):
        fail("ERR_THICKNESS_OUTSIDE_WPS_RANGE",
             "%s in falls outside the qualified window of %s."
             % (thickness, procedure["wps_number"]))
    if job["status"] not in ("FAB_PLANNING", "FABRICATION"):
        fail("ERR_INVALID_JOB_STATE",
             "Weld-map planning needs the job in FAB_PLANNING or FABRICATION.")
    for piece in (part_a, part_b):
        if piece is not None and piece["job_id"] != job_id:
            fail("ERR_PART_NOT_IN_JOB",
                 "Piece %s belongs to another job." % piece["part_mark"])
    for other in derive.job_welds(job_id):
        if other["weld_number"] == weld_number:
            fail("ERR_DUPLICATE_WELD_NUMBER",
                 "Joint %s is already on this weld map." % weld_number)

    record = db.insert("welds", {
        "job_id": job_id,
        "weld_number": weld_number,
        "joint_category": joint_category,
        "joint_type": joint_type,
        "thickness_in": thickness,
        "wps_id": wps_id,
        "part_a_id": part_a_id,
        "part_b_id": part_b_id,
        "welder_qualification_id": None,
        "repair_of_weld_id": None,
        "repair_generation": 0,
        "pwht_batch_id": None,
        "welded_at": None,
        "fab_status": "PLANNED",
        "nde_status": "NOT_PLANNED",
        "pwht_status": "PENDING" if procedure["pwht_required"] else "NOT_REQUIRED",
        "required_volumetric_pct": 0,
        "volumetric_method": None,
        "required_surface_method": None,
    })
    coverage, method, surface = derive.resolve_weld_examination(record, job)
    record["required_volumetric_pct"] = coverage
    record["volumetric_method"] = method
    record["required_surface_method"] = surface

    derive.recompute_job(job)
    derive.sync_job_reports(job)
    return common.created("welds", record)


@bp.get("/production-welds/<weld_id>")
@guard(ALL_ROLES)
def get_weld(ctx, weld_id):
    return common.one("welds", common.must_exist("welds", weld_id))


@bp.get("/production-welds")
@guard(ALL_ROLES)
def list_welds(ctx):
    return common.listing("welds", [
        "job_id", "wps_id", "part_a_id", "part_b_id", "welder_qualification_id",
        "repair_of_weld_id", "pwht_batch_id", "joint_category", "fab_status",
        "nde_status", "pwht_status",
    ])


@bp.post("/production-welds/<weld_id>/complete")
@guard(["WeldingEngineer"])
def complete_weld(ctx, weld_id):
    body = validation.body()
    qualification_id = validation.string_field(body, "welder_qualification_id")
    welded_at = validation.instant_field(body, "welded_at")

    weld = common.must_exist("welds", weld_id)
    qual = db.get("qualifications", qualification_id)
    if qual is None:
        fail("ERR_QUALIFICATION_NOT_FOUND",
             "No welder qualification carries id %s." % qualification_id)
    if weld["fab_status"] != "PLANNED":
        fail("ERR_INVALID_WELD_STATE", "Only a PLANNED joint may be completed.")

    job = db.get("jobs", weld["job_id"])
    admitted = job["status"] == "FABRICATION"
    if not admitted and job["status"] == "NDE_HOLD":
        covering = covering_nonconformance(weld)
        admitted = covering is not None and covering["disposition"] == "REPAIR"
    if not admitted:
        fail("ERR_INVALID_JOB_STATE",
             "Weld completion needs the job in FABRICATION.")

    procedure = db.get("wps", weld["wps_id"])
    if procedure["status"] != "QUALIFIED":
        fail("ERR_WPS_NOT_QUALIFIED",
             "Procedure %s is no longer QUALIFIED." % procedure["wps_number"])
    if derive.qualification_status(qual) != "QUALIFIED":
        fail("ERR_WELDER_NOT_QUALIFIED",
             "Welder %s has lapsed on continuity." % qual["welder_stamp"])
    if qual["wps_id"] != weld["wps_id"]:
        fail("ERR_QUALIFICATION_WPS_MISMATCH",
             "The qualification cited is against another procedure.")
    if weld["thickness_in"] > qual["thickness_range_max_in"]:
        fail("ERR_THICKNESS_OUTSIDE_QUALIFICATION",
             "%s in exceeds the welder's qualified ceiling." % weld["thickness_in"])
    for key in ("part_a_id", "part_b_id"):
        piece = db.get("parts", weld.get(key))
        if piece is not None and piece["status"] != "ISSUED":
            fail("ERR_PART_SCRAPPED",
                 "Piece %s has been scrapped." % piece["part_mark"])

    db.mutate(weld, {"fab_status": "WELDED",
                     "welder_qualification_id": qualification_id,
                     "welded_at": db.iso_instant(welded_at)})
    derive.recompute_job(job)
    derive.sync_job_reports(job)
    return common.one("welds", weld)
