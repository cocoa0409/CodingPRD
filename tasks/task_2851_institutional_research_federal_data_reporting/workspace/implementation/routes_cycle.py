"""ReportingCycle and FrozenFile routes."""
from datetime import date, timedelta

from flask import Blueprint

from auth import actor, require_roles
from db import (READ_ROLES, SURVEY_DOMAINS, public, stamp_new, store, touch)
from errors import fail
from response import created, filter_eq, ok, paginate
from svc_common import (cohorts_of, components_of, files_of, get_cycle,
                        get_frozen_file)
from svc_cohort import recompute_cohort
from svc_cycle import (bubble_archive, cascade_reopen, cycle_by_code,
                       recompute_ledger, require_not_frozen, require_posture)
from util import parse_date, parse_instant
from validation import (get_body, req_date, req_instant, req_int, req_enum,
                        req_string)

bp = Blueprint("cycles", __name__)


def serialize_cycle(row):
    return public(row)


def serialize_file(row):
    return public(row)


@bp.post("/reporting-cycles")
def create_cycle():
    require_roles("RegistrarOfficer")
    body = get_body()
    cycle_code = req_string(body, "cycle_code", 1, 32)
    collection_year = req_int(body, "collection_year", 2000, 2100)
    census_date = req_date(body, "census_date")
    collection_deadline = req_instant(body, "collection_deadline")
    census_midnight = parse_instant(census_date)
    if parse_instant(collection_deadline) <= census_midnight:
        fail("ERR_INVALID_REQUEST",
             "collection_deadline must be strictly after midnight UTC on census_date")
    if cycle_by_code(cycle_code) is not None:
        fail("ERR_DUPLICATE_CYCLE_CODE", "cycle_code is already in use")
    row = {
        "cycle_code": cycle_code,
        "collection_year": collection_year,
        "census_date": census_date,
        "collection_deadline": collection_deadline,
        "snapshot_posture": "OPEN",
        "census_locked_at": None,
        "frozen_at": None,
        "reopen_count": 0,
        "active_record_count": 0,
        "frozen_file_count": 0,
        "reopen_reason": None,
    }
    stamp_new(row)
    store.cycles[row["id"]] = row
    return created(serialize_cycle(row))


@bp.get("/reporting-cycles/<cycle_id>")
def read_cycle(cycle_id):
    require_roles(*READ_ROLES)
    return ok(serialize_cycle(get_cycle(cycle_id)))


@bp.post("/reporting-cycles/<cycle_id>/census-lock")
def census_lock(cycle_id):
    require_roles("RegistrarOfficer")
    cycle = get_cycle(cycle_id)
    require_posture(cycle, ("OPEN", "REOPENED"))
    active = [f for f in files_of(cycle_id) if f["status"] == "ACTIVE"]
    if not active:
        fail("ERR_NO_ACTIVE_SNAPSHOT", "the cycle has no ACTIVE census extract")
    if store.now().date() < parse_date(cycle["census_date"]):
        fail("ERR_CENSUS_DATE_NOT_REACHED", "the logical clock has not reached census_date")
    cycle["snapshot_posture"] = "CENSUS_LOCKED"
    cycle["census_locked_at"] = store.now_iso()
    for frozen_file in active:
        frozen_file["status"] = "LOCKED"
        touch(frozen_file)
    recompute_ledger(cycle)
    touch(cycle)
    return ok(serialize_cycle(cycle))


@bp.post("/reporting-cycles/<cycle_id>/freeze")
def freeze(cycle_id):
    require_roles("IRDirector")
    cycle = get_cycle(cycle_id)
    require_posture(cycle, ("CENSUS_LOCKED",))
    rows = components_of(cycle_id)
    if not rows or any(c["prep_status"] != "CERTIFIED" for c in rows):
        fail("ERR_COMPONENTS_NOT_READY",
             "every survey component of the cycle must be CERTIFIED")
    cycle["snapshot_posture"] = "FROZEN"
    cycle["frozen_at"] = store.now_iso()
    touch(cycle)
    for cohort in cohorts_of(cycle_id):
        if cohort["status"] != "DRAFT":
            continue
        if (cohort.get("adjusted_count") or 0) < 1:
            continue
        cohort["status"] = "LOCKED"
        cohort["locked_at"] = store.now_iso()
        recompute_cohort(cohort)
        touch(cohort)
    return ok(serialize_cycle(cycle))


@bp.post("/reporting-cycles/<cycle_id>/reopen")
def reopen(cycle_id):
    require_roles("IRDirector")
    body = get_body()
    reason = req_string(body, "reopen_reason", 10, 500)
    cycle = get_cycle(cycle_id)
    require_posture(cycle, ("FROZEN",))
    cycle["snapshot_posture"] = "REOPENED"
    cycle["reopen_count"] = (cycle.get("reopen_count") or 0) + 1
    cycle["reopen_reason"] = reason
    touch(cycle)
    cascade_reopen(cycle)
    return ok(serialize_cycle(cycle))


@bp.post("/reporting-cycles/<cycle_id>/frozen-files")
def register_frozen_file(cycle_id):
    require_roles("RegistrarOfficer")
    body = get_body()
    domain = req_enum(body, "domain", SURVEY_DOMAINS)
    record_count = req_int(body, "record_count", 0, None)
    coverage_start = req_date(body, "coverage_start_date")
    coverage_end = req_date(body, "coverage_end_date")
    checksum = req_string(body, "checksum", 8, 64)
    expected_version = req_int(body, "expected_cycle_version", 0, None)
    cycle = get_cycle(cycle_id)
    require_not_frozen(cycle)
    if cycle["snapshot_posture"] == "CENSUS_LOCKED":
        fail("ERR_CENSUS_LOCKED", "the census snapshot is sealed; reopen the cycle first")
    if expected_version != cycle["version"]:
        fail("ERR_STALE_CYCLE_VERSION", "expected_cycle_version does not match the cycle")

    start = parse_date(coverage_start)
    end = parse_date(coverage_end)
    year_start = date(cycle["collection_year"] - 1, 7, 1)
    year_end = date(cycle["collection_year"], 6, 30)
    if start > end or start < year_start or end > year_end:
        fail("ERR_INVALID_COVERAGE_WINDOW",
             "the coverage window must be ordered and inside the cycle's reporting year")

    peers = [f for f in files_of(cycle_id)
             if f["domain"] == domain and f["status"] in ("ACTIVE", "LOCKED")]
    superseded = None
    for peer in peers:
        if (peer["coverage_start_date"] == coverage_start
                and peer["coverage_end_date"] == coverage_end):
            superseded = peer
            break
    remaining = [p for p in peers if p is not superseded]
    for peer in remaining:
        if start <= parse_date(peer["coverage_end_date"]) \
                and parse_date(peer["coverage_start_date"]) <= end:
            fail("ERR_COVERAGE_WINDOW_OVERLAP",
                 "the coverage window overlaps an existing extract of the same domain")

    row = {
        "cycle_id": cycle_id,
        "supersedes_frozen_file_id": superseded["id"] if superseded else None,
        "domain": domain,
        "record_count": record_count,
        "coverage_start_date": coverage_start,
        "coverage_end_date": coverage_end,
        "checksum": checksum,
        "snapshot_taken_at": store.now_iso(),
        "status": "ACTIVE",
    }
    stamp_new(row)
    store.frozen_files[row["id"]] = row
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
    recompute_ledger(cycle)
    touch(cycle)
    return created(serialize_file(row))


@bp.get("/frozen-files/<frozen_file_id>")
def read_frozen_file(frozen_file_id):
    require_roles(*READ_ROLES)
    return ok(serialize_file(get_frozen_file(frozen_file_id)))


@bp.get("/frozen-files")
def list_frozen_files():
    require_roles(*READ_ROLES)
    rows = sorted(store.frozen_files.values(),
                  key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    rows = filter_eq(rows, {"cycle_id": "cycle_id", "domain": "domain",
                            "status": "status",
                            "supersedes_frozen_file_id": "supersedes_frozen_file_id"})
    return paginate(rows, serialize_file)
