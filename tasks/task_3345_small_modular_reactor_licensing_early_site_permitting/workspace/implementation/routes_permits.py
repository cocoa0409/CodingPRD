"""Site permit and public hearing routes."""
from flask import Blueprint, request

from errors import (ApiError, ERR_DCA_NOT_CERTIFIED, ERR_HEARING_IN_PAST,
                    ERR_HEARING_WINDOW, ERR_INVALID_STATE)
from rbac import require_role
from store import (DB, apply_pagination, base_record, get_clock, iso_ms,
                   paginate_args, parse_iso, serialize, sort_by_created,
                   success_list, success_object, touch)
from validation import get_or_404, json_body, v_enum, v_iso, v_str

bp = Blueprint("permits", __name__, url_prefix="/licensing")


def _invalid(msg):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def run_hearing_expiry_sweep():
    """Cancel any SCHEDULED hearing whose scheduled_at has passed.

    Strictly-after only: at the exact scheduled instant the hearing must
    survive so that mark-held ("at or after scheduled_at") can succeed and
    contend/cancel can be rejected with ERR_HEARING_WINDOW (PRD section 3.6:
    "Once the clock reaches scheduled_at, the applicant marks it held").
    """
    clock = get_clock()
    for h in DB["public_hearing"].values():
        if h["status"] == "SCHEDULED":
            sched = parse_iso(h["scheduled_at"])
            if clock > sched:
                h["status"] = "CANCELLED"
                touch(h)


@bp.post("/site-permits")
def create_permit():
    require_role("SitePermitApplicant")
    body = json_body()
    permit_type = v_enum(body, "permit_type", ("ESP", "COL"))
    dca_id = v_str(body, "dca_id")
    site_name = v_str(body, "site_name")
    dca = get_or_404("dca", dca_id)
    if permit_type == "COL" and dca["status"] != "CERTIFIED":
        raise ApiError(ERR_DCA_NOT_CERTIFIED, 422,
                       "COL requires a CERTIFIED application")
    if permit_type == "ESP":
        epz = dca["epz_radius_deterministic_miles"]
    else:
        epz = dca["epz_radius_selected_miles"]
    permit = base_record("site_permit", {
        "permit_type": permit_type,
        "dca_id": dca_id,
        "site_name": site_name,
        "epz_radius_miles": epz,
        "status": "DRAFT",
    })
    DB["site_permit"][permit["id"]] = permit
    return success_object(serialize(permit), status=201)


@bp.get("/site-permits")
def list_permits():
    require_role()
    items = list(DB["site_permit"].values())
    for param in ("dca_id", "permit_type", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [p for p in items if p[param] == val]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(p) for p in page], total, limit, offset)


@bp.get("/site-permits/<id>")
def get_permit(id):
    require_role()
    return success_object(serialize(get_or_404("site_permit", id)))


@bp.post("/site-permits/<id>/submit")
def submit_permit(id):
    require_role("SitePermitApplicant")
    permit = get_or_404("site_permit", id)
    if permit["status"] != "DRAFT":
        raise _invalid("permit is not DRAFT")
    dca = get_or_404("dca", permit["dca_id"])
    if dca["status"] == "WITHDRAWN":
        raise _invalid("referenced application is WITHDRAWN")
    permit["status"] = "ENVIRONMENTAL_REVIEW"
    touch(permit)
    return success_object(serialize(permit))


@bp.post("/site-permits/<id>/advance-to-hearings")
def advance_to_hearings(id):
    require_role("SitePermitApplicant")
    permit = get_or_404("site_permit", id)
    if permit["status"] != "ENVIRONMENTAL_REVIEW":
        raise _invalid("permit is not ENVIRONMENTAL_REVIEW")
    if any(h["permit_id"] == id and h["status"] == "SCHEDULED"
           for h in DB["public_hearing"].values()):
        raise _invalid("a SCHEDULED hearing is outstanding")
    permit["status"] = "HEARINGS"
    touch(permit)
    return success_object(serialize(permit))


@bp.post("/site-permits/<id>/grant")
def grant_permit(id):
    require_role("SitePermitApplicant")
    permit = get_or_404("site_permit", id)
    if permit["status"] != "HEARINGS":
        raise _invalid("permit is not HEARINGS")
    hearings = [h for h in DB["public_hearing"].values() if h["permit_id"] == id]
    if not hearings:
        raise _invalid("no hearings exist")
    if any(h["status"] != "HELD" for h in hearings):
        raise _invalid("every hearing must be HELD")
    permit["status"] = "GRANTED"
    touch(permit)
    return success_object(serialize(permit))


@bp.post("/site-permits/<id>/deny")
def deny_permit(id):
    require_role("SitePermitApplicant")
    permit = get_or_404("site_permit", id)
    if permit["status"] not in ("ENVIRONMENTAL_REVIEW", "HEARINGS"):
        raise _invalid("permit cannot be denied from its current state")
    permit["status"] = "DENIED"
    touch(permit)
    return success_object(serialize(permit))


# ---------------------------------------------------------------------------
# Public hearings
# ---------------------------------------------------------------------------
@bp.post("/site-permits/<id>/hearings")
def schedule_hearing(id):
    require_role("SitePermitApplicant")
    permit = get_or_404("site_permit", id)
    if permit["status"] != "HEARINGS":
        raise _invalid("permit is not HEARINGS")
    body = json_body()
    scheduled_at = v_iso(body, "scheduled_at")
    location = v_str(body, "location")
    if not (get_clock() < scheduled_at):
        raise ApiError(ERR_HEARING_IN_PAST, 422, "scheduled_at must be strictly in the future")
    hearing = base_record("public_hearing", {
        "permit_id": id,
        "scheduled_at": iso_ms(scheduled_at),
        "location": location,
        "status": "SCHEDULED",
    })
    DB["public_hearing"][hearing["id"]] = hearing
    return success_object(serialize(hearing), status=201)


@bp.get("/public-hearings")
def list_hearings():
    require_role()
    items = list(DB["public_hearing"].values())
    permit_id = request.args.get("permit_id")
    if permit_id is not None:
        items = [h for h in items if h["permit_id"] == permit_id]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(h) for h in page], total, limit, offset)


@bp.get("/public-hearings/<id>")
def get_hearing(id):
    require_role()
    return success_object(serialize(get_or_404("public_hearing", id)))


@bp.post("/public-hearings/<id>/mark-held")
def mark_held(id):
    require_role("SitePermitApplicant")
    hearing = get_or_404("public_hearing", id)
    if hearing["status"] != "SCHEDULED":
        raise _invalid("hearing is not SCHEDULED")
    sched = parse_iso(hearing["scheduled_at"])
    if not (get_clock() >= sched):
        raise ApiError(ERR_HEARING_WINDOW, 422,
                       "mark-held requires the clock at or after scheduled_at")
    hearing["status"] = "HELD"
    touch(hearing)
    return success_object(serialize(hearing))


@bp.post("/public-hearings/<id>/contend")
def contend_hearing(id):
    require_role("PublicIntervenor")
    hearing = get_or_404("public_hearing", id)
    if hearing["status"] != "SCHEDULED":
        raise _invalid("hearing is not SCHEDULED")
    sched = parse_iso(hearing["scheduled_at"])
    if not (get_clock() < sched):
        raise ApiError(ERR_HEARING_WINDOW, 422,
                       "contention requires the clock strictly before scheduled_at")
    hearing["status"] = "CONTENDED"
    touch(hearing)
    # cascade: parent permit in HEARINGS regresses
    permit = DB["site_permit"].get(hearing["permit_id"])
    if permit is not None and permit["status"] == "HEARINGS":
        permit["status"] = "ENVIRONMENTAL_REVIEW"
        touch(permit)
    return success_object(serialize(hearing))


@bp.post("/public-hearings/<id>/cancel")
def cancel_hearing(id):
    require_role("SitePermitApplicant")
    hearing = get_or_404("public_hearing", id)
    if hearing["status"] != "SCHEDULED":
        raise _invalid("hearing is not SCHEDULED")
    sched = parse_iso(hearing["scheduled_at"])
    if not (get_clock() < sched):
        raise ApiError(ERR_HEARING_WINDOW, 422,
                       "cancellation requires the clock strictly before scheduled_at")
    hearing["status"] = "CANCELLED"
    touch(hearing)
    return success_object(serialize(hearing))


@bp.post("/public-hearings/<id>/reschedule")
def reschedule_hearing(id):
    require_role("SitePermitApplicant")
    hearing = get_or_404("public_hearing", id)
    if hearing["status"] != "CONTENDED":
        raise _invalid("hearing is not CONTENDED")
    body = json_body()
    scheduled_at = v_iso(body, "scheduled_at")
    if not (get_clock() < scheduled_at):
        raise ApiError(ERR_HEARING_IN_PAST, 422, "scheduled_at must be strictly in the future")
    hearing["scheduled_at"] = iso_ms(scheduled_at)
    hearing["status"] = "SCHEDULED"
    touch(hearing)
    return success_object(serialize(hearing))
