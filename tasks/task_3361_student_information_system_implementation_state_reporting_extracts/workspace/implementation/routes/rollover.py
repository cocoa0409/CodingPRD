"""RolloverRun endpoints: create (supersede + OCC on District.version),
list, get, execute (full promotion/graduation/archival cascade), compensate
(reverses the cascade per rollover_conservation)."""
from flask import Blueprint, request

from db import new_id, stamp_new, store, touch
from errors import ApiError
from middleware import READERS, auth_context, require_role
from response import ok_list, ok_obj, page_of, pagination_args
from services.calc import create_enrollment_record, next_grade
from services.serializers import run_out
from validators import body, req_int, req_str

bp = Blueprint("rollover_runs", __name__)


def _get_run_or_404(rid):
    r = store["rollover_runs"].get(rid)
    if not r:
        raise ApiError("ERR_ROLLOVER_RUN_NOT_FOUND", 404,
                       "No rollover run with the given id")
    return r


@bp.post("/sis/rollover-runs")
def create_run():
    _uid, role = auth_context()
    data = body()
    district_id = req_str(data, "district_id")
    source_id = req_str(data, "source_school_year_id")
    target_id = req_str(data, "target_school_year_id")
    expected_version = req_int(data, "expected_district_version")
    if source_id == target_id:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "target_school_year_id must differ from source_school_year_id")
    require_role(role, {"DistrictAdmin"})
    district = store["districts"].get(district_id)
    if not district:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "district_id does not reference an existing district")
    source = store["school_years"].get(source_id)
    if not source:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "source_school_year_id does not reference an existing school year")
    target = store["school_years"].get(target_id)
    if not target:
        raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422,
                       "target_school_year_id does not reference an existing school year")
    if (source["district_id"] != district_id
            or target["district_id"] != district_id):
        raise ApiError("ERR_DISTRICT_MISMATCH", 422,
                       "source/target school year belongs to a different district")
    # OCC: the client's view of the district's run lineage must be current.
    if expected_version != district["version"]:
        raise ApiError("ERR_STALE_DISTRICT_VERSION", 412,
                       "expected_district_version does not match the district's current version")
    # Creating a run supersedes any still-PENDING run of the same district.
    for r in store["rollover_runs"].values():
        if r["district_id"] == district_id and r["status"] == "PENDING":
            r["status"] = "SUPERSEDED"
            touch(r)
    r = {"id": new_id(), "district_id": district_id,
         "source_school_year_id": source_id,
         "target_school_year_id": target_id,
         "status": "PENDING", "promoted_count": 0, "graduated_count": 0,
         "archived_student_count": 0,
         "_undo": None}
    stamp_new(r)
    store["rollover_runs"][r["id"]] = r
    touch(district)
    return ok_obj(run_out(r), 201)


@bp.get("/sis/rollover-runs")
def list_runs():
    _uid, role = auth_context()
    require_role(role, READERS)
    limit, offset = pagination_args()
    district_id = request.args.get("district_id")
    source_id = request.args.get("source_school_year_id")
    target_id = request.args.get("target_school_year_id")
    status = request.args.get("status")
    items = [r for r in store["rollover_runs"].values()
             if (district_id is None or r["district_id"] == district_id)
             and (source_id is None or r["source_school_year_id"] == source_id)
             and (target_id is None or r["target_school_year_id"] == target_id)
             and (status is None or r["status"] == status)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = page_of(items, limit, offset)
    return ok_list([run_out(r) for r in page], total, limit, offset)


@bp.get("/sis/rollover-runs/<rid>")
def get_run(rid):
    _uid, role = auth_context()
    require_role(role, READERS)
    return ok_obj(run_out(_get_run_or_404(rid)))


@bp.post("/sis/rollover-runs/<rid>/execute")
def execute_run(rid):
    _uid, role = auth_context()
    require_role(role, {"DistrictAdmin"})
    r = _get_run_or_404(rid)
    if r["status"] != "PENDING":
        raise ApiError("ERR_ROLLOVER_NOT_PENDING", 409,
                       "Execute requires run PENDING")
    source = store["school_years"].get(r["source_school_year_id"])
    if not source or source["status"] != "CLOSED_FOR_REPORTING":
        raise ApiError("ERR_SOURCE_YEAR_NOT_CLOSED", 409,
                       "Rollover execute requires source year CLOSED_FOR_REPORTING")
    target = store["school_years"].get(r["target_school_year_id"])
    if not target or target["status"] != "OPEN":
        raise ApiError("ERR_TARGET_YEAR_NOT_OPEN", 409,
                       "Rollover execute requires target year OPEN")
    district = store["districts"].get(r["district_id"])
    if not district or district["status"] != "LIVE":
        raise ApiError("ERR_DISTRICT_NOT_LIVE", 409,
                       "Rollover execute requires district LIVE")
    for other in store["rollover_runs"].values():
        if (other["id"] != r["id"]
                and other["source_school_year_id"] == r["source_school_year_id"]
                and other["status"] == "COMMITTED"):
            raise ApiError("ERR_ROLLOVER_ALREADY_COMMITTED", 409,
                           "Another COMMITTED run already exists for the source year")

    undo = {"completed_enrollments": [], "graduated_students": [],
            "archived_students": [], "revoked_accounts": [],
            "created_enrollments": [], "locked_sections": []}
    promoted = graduated = archived = 0

    # Cascade 1-3: complete every ACTIVE source-year enrollment; grade 12
    # graduates (revoking portal accounts), lower grades promote into the
    # target year.
    actives = [e for e in store["enrollments"].values()
               if e["school_year_id"] == source["id"]
               and e["lifecycle"] == "ACTIVE"]
    actives.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for e in actives:
        e["lifecycle"] = "COMPLETED"
        touch(e)
        undo["completed_enrollments"].append(e["id"])
        student = store["students"].get(e["student_id"])
        if not student:
            continue
        if e["grade_level"] == "12":
            graduated += 1
            if student["status"] == "ENROLLED":
                student["status"] = "GRADUATED"
                touch(student)
                undo["graduated_students"].append(student["id"])
            for pa in store["portal_accounts"].values():
                if (pa["student_id"] == student["id"]
                        and pa["status"] in ("INVITED", "ACTIVE")):
                    pa["status"] = "REVOKED"
                    touch(pa)
                    undo["revoked_accounts"].append(pa["id"])
        else:
            promoted += 1
            ne = create_enrollment_record(
                student["id"], target, next_grade(e["grade_level"]),
                target["start_date"])
            undo["created_enrollments"].append(ne["id"])

    # Cascade 4: archive INACTIVE students of the district holding no ACTIVE
    # enrollment in the source year.
    for st in list(store["students"].values()):
        if st["district_id"] != r["district_id"] or st["status"] != "INACTIVE":
            continue
        has_active_source = any(
            e["student_id"] == st["id"]
            and e["school_year_id"] == source["id"]
            and e["lifecycle"] == "ACTIVE"
            for e in store["enrollments"].values())
        if not has_active_source:
            st["status"] = "ARCHIVED"
            touch(st)
            archived += 1
            undo["archived_students"].append(st["id"])

    # The source year rolls over; its COMMITTED sections lock.
    source["status"] = "ROLLED_OVER"
    touch(source)
    for sec in store["sections"].values():
        if (sec["school_year_id"] == source["id"]
                and sec["status"] == "COMMITTED"):
            sec["status"] = "LOCKED"
            touch(sec)
            undo["locked_sections"].append(sec["id"])

    r["status"] = "COMMITTED"
    r["promoted_count"] = promoted
    r["graduated_count"] = graduated
    r["archived_student_count"] = archived
    r["_undo"] = undo
    touch(r)
    touch(district)
    return ok_obj(run_out(r))


@bp.post("/sis/rollover-runs/<rid>/compensate")
def compensate_run(rid):
    _uid, role = auth_context()
    require_role(role, {"DistrictAdmin"})
    r = _get_run_or_404(rid)
    if r["status"] != "COMMITTED":
        raise ApiError("ERR_ROLLOVER_NOT_COMMITTED", 409,
                       "Compensate requires run COMMITTED")
    undo = r.get("_undo") or {}
    district = store["districts"].get(r["district_id"])

    # Reverse each arm of the execute cascade.
    for eid in undo.get("created_enrollments", []):
        store["enrollments"].pop(eid, None)
    for eid in undo.get("completed_enrollments", []):
        e = store["enrollments"].get(eid)
        if e and e["lifecycle"] == "COMPLETED":
            e["lifecycle"] = "ACTIVE"  # exit_date unchanged
            touch(e)
    for sid in undo.get("graduated_students", []):
        st = store["students"].get(sid)
        if st and st["status"] == "GRADUATED":
            st["status"] = "ENROLLED"
            touch(st)
    for sid in undo.get("archived_students", []):
        st = store["students"].get(sid)
        if st and st["status"] == "ARCHIVED":
            st["status"] = "INACTIVE"
            touch(st)
    for pid in undo.get("revoked_accounts", []):
        pa = store["portal_accounts"].get(pid)
        if pa and pa["status"] == "REVOKED":
            pa["status"] = "ACTIVE"
            touch(pa)
    source = store["school_years"].get(r["source_school_year_id"])
    if source and source["status"] == "ROLLED_OVER":
        source["status"] = "CLOSED_FOR_REPORTING"
        touch(source)
    for secid in undo.get("locked_sections", []):
        sec = store["sections"].get(secid)
        if sec and sec["status"] == "LOCKED":
            sec["status"] = "COMMITTED"
            touch(sec)

    r["status"] = "COMPENSATED"
    r["promoted_count"] = 0
    r["graduated_count"] = 0
    r["archived_student_count"] = 0
    touch(r)
    if district:
        touch(district)
    return ok_obj(run_out(r))
