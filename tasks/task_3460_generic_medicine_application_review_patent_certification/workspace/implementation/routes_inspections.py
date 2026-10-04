"""Facility inspections: scheduling, half-open overlap, outcomes (PRD 3.6)."""
from flask import Blueprint, request

from auth import ALL_ROLES, auth, require_role
from clock import add_months, parse_date, today
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import inspection
from state import STORE, create_entity, get, touch
from validate import body, opt_enum, req_date, req_enum, req_str

bp = Blueprint("inspections", __name__)

OUTCOMES = ("PASSED", "FAILED", "WAIVED", "CANCELLED")


@bp.post("/generic-drug-review/facility-inspections")
def create_inspection():
    _uid, role = auth()
    require_role(role, ["RegulatoryReviewer"])
    b = body()
    # Body-referenced ids in input declaration order: facility_id, application_id.
    fid = b.get("facility_id")
    if isinstance(fid, str) and get("facilities", fid) is None:
        fail("ERR_FACILITY_NOT_FOUND", "Manufacturing facility id does not exist")
    aid = b.get("application_id")
    if isinstance(aid, str) and get("applications", aid) is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    fid = req_str(b, "facility_id")
    aid = req_str(b, "application_id")
    opt_enum(b, "inspection_type", ("PRE_APPROVAL",), "PRE_APPROVAL")
    start = req_date(b, "scheduled_start_date")
    end = req_date(b, "scheduled_end_date")
    if end < start:
        fail("ERR_INVALID_REQUEST",
             "scheduled_end_date must be on or after scheduled_start_date")
    # Priority 12: half-open [start, end) overlap against the facility's
    # SCHEDULED inspections; adjacency is allowed; terminal outcomes never block.
    for i in STORE["inspections"].values():
        if i["facility_id"] != fid or i["status"] != "SCHEDULED":
            continue
        ex_start = parse_date(i["scheduled_start_date"])
        ex_end = parse_date(i["scheduled_end_date"])
        if start < ex_end and ex_start < end:
            fail("ERR_INSPECTION_OVERLAP",
                 "Inspection window collides with another SCHEDULED "
                 "inspection of the same facility")
    # Priority 20: the facility must belong to the application's applicant.
    facility = get("facilities", fid)
    app = get("applications", aid)
    if facility["applicant_id"] != app["applicant_id"]:
        fail("ERR_FACILITY_APPLICATION_MISMATCH",
             "The facility belongs to a different applicant than the application")
    ent = create_entity("inspections", {
        "facility_id": fid,
        "application_id": aid,
        "inspection_type": "PRE_APPROVAL",
        "scheduled_start_date": start.isoformat(),
        "scheduled_end_date": end.isoformat(),
        "status": "SCHEDULED",
        "outcome_date": None,
    })
    return success_object(inspection(ent), 201)


@bp.get("/generic-drug-review/facility-inspections/<ins_id>")
def get_inspection(ins_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    ent = get("inspections", ins_id)
    if ent is None:
        fail("ERR_INSPECTION_NOT_FOUND", "Facility inspection id does not exist")
    return success_object(inspection(ent))


@bp.get("/generic-drug-review/facility-inspections")
def list_inspections():
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    items = list(STORE["inspections"].values())
    f_fac = request.args.get("facility_id")
    f_app = request.args.get("application_id")
    f_status = request.args.get("status")
    if f_fac is not None:
        items = [i for i in items if i["facility_id"] == f_fac]
    if f_app is not None:
        items = [i for i in items if i["application_id"] == f_app]
    if f_status is not None:
        items = [i for i in items if i["status"] == f_status]
    return success_list([inspection(i) for i in sort_default(items)])


@bp.post("/generic-drug-review/facility-inspections/<ins_id>/record-outcome")
def record_outcome(ins_id):
    _uid, role = auth()
    require_role(role, ["FacilityInspector"])
    ent = get("inspections", ins_id)
    if ent is None:
        fail("ERR_INSPECTION_NOT_FOUND", "Facility inspection id does not exist")
    b = body()
    outcome = req_enum(b, "outcome", OUTCOMES)
    if ent["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE",
             "An outcome can only be recorded on a SCHEDULED inspection")
    t = today()
    if outcome == "WAIVED":
        # Domestic only, with another PASSED inspection of the same facility
        # whose outcome_date is within the prior 24 calendar months.
        facility = get("facilities", ent["facility_id"])
        cutoff = add_months(t, -24)
        prior_pass = any(
            i["facility_id"] == ent["facility_id"]
            and i["id"] != ent["id"]
            and i["status"] == "PASSED"
            and i["outcome_date"] is not None
            and parse_date(i["outcome_date"]) >= cutoff
            for i in STORE["inspections"].values()
        )
        if facility["is_foreign"] or not prior_pass:
            fail("ERR_FOREIGN_FACILITY_WAIVER",
                 "WAIVED requires a domestic facility with a PASSED inspection "
                 "within the prior 24 months")
    ent["status"] = outcome
    ent["outcome_date"] = t.isoformat()
    touch(ent)
    return success_object(inspection(ent))
