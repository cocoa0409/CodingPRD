"""System participations and connection certifications (PRD section 3.2)."""
from flask import Blueprint, request

import serialize
import state
import store
import validation as v
from errors import err
from response import ok, ok_list

bp = Blueprint("certification", __name__, url_prefix="/driver-exchange")

SYSTEMS = {"POINTER_NETWORK", "COMMERCIAL_DRIVER_NETWORK", "TITLE_NETWORK"}
CERT_RESULTS = {"PASSED", "FAILED"}


@bp.post("/system-participations")
def create_participation():
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    jurisdiction_id = v.req_string(data, "jurisdiction_id")
    system = v.req_enum(data, "system", SYSTEMS)
    if jurisdiction_id != user_id:
        raise err("ERR_JURISDICTION_OWNERSHIP_MISMATCH",
                  "a registrar may only enroll its own jurisdiction")
    jurisdiction = store.db.jurisdictions.get(jurisdiction_id)
    if jurisdiction is None:
        raise err("ERR_JURISDICTION_NOT_FOUND",
                  "no jurisdiction with id %s" % jurisdiction_id)
    if jurisdiction["membership_status"] not in ("APPLIED", "ACTIVE"):
        raise err("ERR_INVALID_STATE",
                  "enrollment requires membership APPLIED or ACTIVE")
    for p in store.db.participations.values():
        if p["jurisdiction_id"] == jurisdiction_id and p["system"] == system:
            raise err("ERR_PARTICIPATION_ALREADY_EXISTS",
                      "a participation for this jurisdiction and system already exists")
    participation = {
        "id": store.new_id(),
        "jurisdiction_id": jurisdiction_id,
        "system": system,
        "status": "ENROLLING",
        "granted_at": None,
        "suspended_at": None,
    }
    store.stamp(participation)
    store.db.participations[participation["id"]] = participation
    return ok(serialize.participation(participation), 201)


@bp.post("/system-participations/<pid>/grant-certification")
def grant_certification(pid):
    """AssociationAdmin-only (segregation of duties with the engineer).
    Rung-6 sub-order: jurisdiction activity first, then the resource arc,
    then the latest-completed-certification gate."""
    _, role = v.auth_context()
    v.require_role(role, {"AssociationAdmin"})
    participation = store.db.participations.get(pid)
    if participation is None:
        raise err("ERR_PARTICIPATION_NOT_FOUND",
                  "no system participation with id %s" % pid)
    jurisdiction = store.db.jurisdictions.get(participation["jurisdiction_id"])
    if jurisdiction is not None and jurisdiction["membership_status"] == "WITHDRAWN":
        raise err("ERR_JURISDICTION_NOT_ACTIVE",
                  "grant requires the parent jurisdiction not be WITHDRAWN")
    if participation["status"] != "TESTING":
        raise err("ERR_INVALID_STATE",
                  "grant-certification requires a TESTING participation")
    latest = None
    for c in store.db.certifications.values():
        if c["participation_id"] != pid or c["status"] not in CERT_RESULTS:
            continue
        key = (store.parse_datetime(c["window_start"]), c["_seq"])
        if latest is None or key > latest[0]:
            latest = (key, c)
    if latest is None or latest[1]["status"] != "PASSED":
        raise err("ERR_GRANT_REQUIRES_PASSED_CERTIFICATION",
                  "the most recent completed certification must be PASSED")
    participation["status"] = "CERTIFIED"
    participation["granted_at"] = store.now_iso()
    store.touch(participation)
    if jurisdiction is not None:
        state.recompute_certified_count(jurisdiction)
        store.touch(jurisdiction)
    return ok(serialize.participation(participation))


@bp.post("/connection-certifications")
def create_certification():
    """Schedule a certification test window. Windows are half-open
    [start, end): adjacency is allowed, any positive overlap among the
    participation's SCHEDULED certifications is rejected. The first
    scheduling moves the participation ENROLLING -> TESTING."""
    _, role = v.auth_context()
    v.require_role(role, {"CertificationEngineer"})
    data = v.body()
    participation_id = v.req_string(data, "participation_id")
    window_start = v.req_datetime(data, "window_start")
    window_end = v.req_datetime(data, "window_end")
    participation = store.db.participations.get(participation_id)
    if participation is None:
        raise err("ERR_PARTICIPATION_NOT_FOUND",
                  "no system participation with id %s" % participation_id)
    if not window_end > window_start:
        raise err("ERR_INVALID_WINDOW",
                  "window_end must be strictly after window_start")
    for c in store.db.certifications.values():
        if c["participation_id"] != participation_id or c["status"] != "SCHEDULED":
            continue
        existing_start = store.parse_datetime(c["window_start"])
        existing_end = store.parse_datetime(c["window_end"])
        if window_start < existing_end and existing_start < window_end:
            raise err("ERR_CERT_WINDOW_OVERLAP",
                      "the window overlaps an existing SCHEDULED certification")
    certification = {
        "id": store.new_id(),
        "participation_id": participation_id,
        "window_start": store.format_datetime(window_start),
        "window_end": store.format_datetime(window_end),
        "status": "SCHEDULED",
        "score": None,
        "completed_at": None,
    }
    store.stamp(certification)
    store.db.certifications[certification["id"]] = certification
    if participation["status"] == "ENROLLING":
        participation["status"] = "TESTING"
        store.touch(participation)
    return ok(serialize.certification(certification), 201)


@bp.get("/connection-certifications/<cid>")
def get_certification(cid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    certification = store.db.certifications.get(cid)
    if certification is None:
        raise err("ERR_CERTIFICATION_NOT_FOUND",
                  "no connection certification with id %s" % cid)
    return ok(serialize.certification(certification))


@bp.get("/connection-certifications")
def list_certifications():
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    participation_id = request.args.get("participation_id")
    items = list(store.db.certifications.values())
    if participation_id is not None:
        items = [c for c in items if c["participation_id"] == participation_id]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.certification(c) for c in page], limit, offset, total)


@bp.post("/connection-certifications/<cid>/complete")
def complete_certification(cid):
    """Completion is only valid while the logical clock sits inside
    [window_start, window_end): exactly window_start is inside, exactly
    window_end is outside."""
    _, role = v.auth_context()
    v.require_role(role, {"CertificationEngineer"})
    data = v.body()
    result = v.req_enum(data, "result", CERT_RESULTS)
    score = v.opt_int(data, "score", 0, 100)
    certification = store.db.certifications.get(cid)
    if certification is None:
        raise err("ERR_CERTIFICATION_NOT_FOUND",
                  "no connection certification with id %s" % cid)
    if certification["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "the certification is no longer SCHEDULED")
    now = store.now()
    if not (store.parse_datetime(certification["window_start"]) <= now
            < store.parse_datetime(certification["window_end"])):
        raise err("ERR_OUTSIDE_TEST_WINDOW",
                  "the logical clock is outside the certification window")
    certification["status"] = result
    certification["score"] = score
    certification["completed_at"] = store.now_iso()
    store.touch(certification)
    return ok(serialize.certification(certification))
