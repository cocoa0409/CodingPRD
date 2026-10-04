"""Safety Analysis Report sections and RAI dialogue routes."""
from flask import Blueprint, request

from calc import recompute_open_rais
from errors import (ApiError, ERR_DUPLICATE, ERR_INVALID_STATE,
                    ERR_SAR_SECTION_UNKNOWN, ERR_SELF_ACCEPT_FORBIDDEN)
from rbac import get_user_id, require_role
from store import (DB, apply_pagination, base_record, get_clock, iso_ms,
                   paginate_args, serialize, sort_by_created, success_list,
                   success_object, touch)
from validation import (get_or_404, json_body, not_found, v_int, v_iso, v_str)

bp = Blueprint("sar_rai", __name__, url_prefix="/licensing")


def _invalid(msg):
    return ApiError(ERR_INVALID_STATE, 409, msg)


@bp.post("/dcas/<dca_id>/sars")
def create_sar(dca_id):
    require_role("DcaApplicant")
    dca = get_or_404("dca", dca_id)
    body = json_body()
    section_code = v_str(body, "section_code")
    revision = v_int(body, "revision_number", minimum=0)
    for s in DB["sar"].values():
        if s["dca_id"] == dca_id and s["section_code"] == section_code \
                and s["revision_number"] == revision:
            raise ApiError(ERR_DUPLICATE, 409, "section+revision already exists")
    sar = base_record("sar", {
        "dca_id": dca_id,
        "section_code": section_code,
        "revision_number": revision,
        "status": "SUBMITTED",
        "open_rais": 0,
    })
    DB["sar"][sar["id"]] = sar
    return success_object(serialize(sar), status=201)


@bp.get("/sars")
def list_sars():
    require_role()
    items = [s for s in DB["sar"].values()]
    dca_id = request.args.get("dca_id")
    if dca_id is not None:
        items = [s for s in items if s["dca_id"] == dca_id]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(s) for s in page], total, limit, offset)


@bp.get("/sars/<id>")
def get_sar(id):
    require_role()
    return success_object(serialize(get_or_404("sar", id)))


@bp.post("/sars/<id>/review")
def review_sar(id):
    require_role("NrcReviewer")
    sar = get_or_404("sar", id)
    if sar["status"] != "SUBMITTED":
        raise _invalid("section is not SUBMITTED")
    sar["status"] = "UNDER_REVIEW"
    touch(sar)
    return success_object(serialize(sar))


@bp.post("/sars/<id>/advance")
def advance_sar(id):
    require_role("NrcReviewer")
    sar = get_or_404("sar", id)
    if sar["status"] != "UNDER_REVIEW":
        raise _invalid("section is not UNDER_REVIEW")
    recompute_open_rais(sar["dca_id"], sar["section_code"])
    if sar["open_rais"] != 0:
        raise _invalid("section has open RAIs")
    sar["status"] = "READY_FOR_PHASE_ADVANCE"
    touch(sar)
    return success_object(serialize(sar))


# ---------------------------------------------------------------------------
# RAIs
# ---------------------------------------------------------------------------
@bp.post("/dcas/<dca_id>/rais")
def create_rai(dca_id):
    user_id, _ = require_role("NrcReviewer")
    get_or_404("dca", dca_id)
    body = json_body()
    section_code = v_str(body, "sar_section_code")
    question = v_str(body, "question_text")
    due = v_iso(body, "due_date")
    sar = next((s for s in DB["sar"].values()
                if s["dca_id"] == dca_id and s["section_code"] == section_code), None)
    if sar is None:
        raise ApiError(ERR_SAR_SECTION_UNKNOWN, 422,
                       "no section with that code on this application")
    rai = base_record("rai", {
        "dca_id": dca_id,
        "sar_section_code": section_code,
        "question_text": question,
        "due_date": iso_ms(due),
        "status": "OPEN",
        "response_text": None,
        "responded_at": None,
        "late_response": False,
        "authored_by_user_id": user_id,
    })
    DB["rai"][rai["id"]] = rai
    recompute_open_rais(dca_id, section_code)
    return success_object(serialize(rai), status=201)


@bp.get("/rais")
def list_rais():
    require_role()
    items = list(DB["rai"].values())
    dca_id = request.args.get("dca_id")
    if dca_id is not None:
        items = [r for r in items if r["dca_id"] == dca_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.get("/rais/<id>")
def get_rai(id):
    require_role()
    return success_object(serialize(get_or_404("rai", id)))


@bp.post("/rais/<id>/respond")
def respond_rai(id):
    require_role("DcaApplicant")
    rai = get_or_404("rai", id)
    if rai["status"] not in ("OPEN", "REOPENED"):
        raise _invalid("RAI is not open for response")
    body = json_body()
    response_text = v_str(body, "response_text")
    now = get_clock()
    due = rai["due_date"]
    from store import parse_iso
    due_dt = parse_iso(due) if isinstance(due, str) else due
    rai["response_text"] = response_text
    rai["responded_at"] = iso_ms(now)
    rai["late_response"] = bool(now > due_dt)
    rai["status"] = "RESPONSE_SUBMITTED"
    touch(rai)
    recompute_open_rais(rai["dca_id"], rai["sar_section_code"])
    return success_object(serialize(rai))


@bp.post("/rais/<id>/accept")
def accept_rai(id):
    user_id, _ = require_role("NrcReviewer")
    rai = get_or_404("rai", id)
    if rai["status"] != "RESPONSE_SUBMITTED":
        raise _invalid("RAI has no submitted response")
    if user_id is not None and user_id == rai.get("authored_by_user_id"):
        raise ApiError(ERR_SELF_ACCEPT_FORBIDDEN, 403,
                       "author may not accept own RAI")
    rai["status"] = "ACCEPTED"
    touch(rai)
    recompute_open_rais(rai["dca_id"], rai["sar_section_code"])
    return success_object(serialize(rai))


@bp.post("/rais/<id>/reopen")
def reopen_rai(id):
    require_role("NrcReviewer")
    rai = get_or_404("rai", id)
    if rai["status"] != "RESPONSE_SUBMITTED":
        raise _invalid("RAI has no submitted response")
    rai["status"] = "REOPENED"
    touch(rai)
    # regression cascade: READY parent section falls back; bubbles to DCA version
    sar = next((s for s in DB["sar"].values()
                if s["dca_id"] == rai["dca_id"]
                and s["section_code"] == rai["sar_section_code"]), None)
    if sar is not None and sar["status"] == "READY_FOR_PHASE_ADVANCE":
        sar["status"] = "UNDER_REVIEW"
        touch(sar)
        dca = DB["dca"].get(rai["dca_id"])
        if dca is not None:
            touch(dca)
    recompute_open_rais(rai["dca_id"], rai["sar_section_code"])
    return success_object(serialize(rai))


@bp.post("/rais/<id>/supersede")
def supersede_rai(id):
    require_role("NrcReviewer")
    rai = get_or_404("rai", id)
    if rai["status"] not in ("OPEN", "REOPENED"):
        raise _invalid("RAI cannot be superseded from its current state")
    rai["status"] = "SUPERSEDED"
    touch(rai)
    recompute_open_rais(rai["dca_id"], rai["sar_section_code"])
    return success_object(serialize(rai))
