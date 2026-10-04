"""Editor routes: registration, profile, lifecycle, COI disclosure."""
from datetime import timedelta

from flask import Blueprint

from db import db, _parse_iso
from errors import (ApiError, ERR_INVALID_STATE,
                    ERR_EDITOR_HAS_OPEN_ARBITRATION, ERR_NOT_FOUND)
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch)
from middleware import require_roles
from response import success_object
from services import recompute_rollback_eligible, confirmed_reports

bp = Blueprint("editors", __name__)


def _open_arbitration_as_initiator(editor_id):
    return any(d for d in db.disputes.values()
               if d["initiator_id"] == editor_id
               and d["level"] == "ARBITRATION"
               and d["status"] in ("OPEN", "ESCALATED"))


@bp.post("/wiki/editors")
def create_editor():
    require_roles("Anonymous")
    body = get_body()
    require_fields(body, ["username", "email"])
    e = base_entity()
    e.update({
        "username": body["username"],
        "email": body["email"],
        "account_status": "ACTIVE",
        "rollback_eligible": True,
        "coi_disclosure_required": bool(body.get("coi_disclosure_required", False)),
        "coi_disclosed": bool(body.get("coi_disclosed", False)),
        "edit_count": 0,
    })
    db.editors[e["id"]] = e
    return success_object(e, status=201)


@bp.get("/wiki/editors")
def list_editors():
    require_roles("VolunteerEditor", "Administrator", "LegalCounsel", "PlatformAdmin")
    return list_response(db.editors,
                         filters={"account_status": _q("account_status")})


@bp.get("/wiki/editors/<editorId>")
def get_editor(editorId):
    require_roles("VolunteerEditor", "Administrator", "LegalCounsel")
    e = lookup(db.editors, editorId, "Editor")
    # PRD 3.6: "Rollback eligibility is true exactly when the editor has zero
    # confirmed vandalism reports in the last ninety days." The window is a
    # function of the current time, so the value is recomputed on read.
    recompute_rollback_eligible(e)
    return success_object(e)


@bp.post("/wiki/editors/<editorId>/suspend")
def suspend_editor(editorId):
    require_roles("Administrator")
    e = lookup(db.editors, editorId, "Editor")
    if e["account_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an ACTIVE editor can be suspended", 409)
    e["account_status"] = "SUSPENDED"
    e["rollback_eligible"] = False
    e["suspended_at"] = db.now_iso()
    for rev in db.revisions.values():
        if rev["editor_id"] == e["id"] and rev["status"] == "PENDING":
            rev["status"] = "FLAGGED"
            touch(rev, bump_version=False)
    touch(e)
    return success_object(e)


@bp.post("/wiki/editors/<editorId>/reinstate")
def reinstate_editor(editorId):
    require_roles("Administrator")
    e = lookup(db.editors, editorId, "Editor")
    if e["account_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a SUSPENDED editor can be reinstated", 409)
    if db.now() - _parse_iso(e["suspended_at"]) < timedelta(days=7):
        raise ApiError(ERR_INVALID_STATE,
                       "At least 7 days must elapse since suspension", 409)
    if _open_arbitration_as_initiator(e["id"]):
        raise ApiError(ERR_EDITOR_HAS_OPEN_ARBITRATION,
                       "Editor has open Arbitration-level dispute", 409)
    e["account_status"] = "ACTIVE"
    recompute_rollback_eligible(e)
    touch(e)
    return success_object(e)


@bp.post("/wiki/editors/<editorId>/block")
def block_editor(editorId):
    require_roles("Administrator")
    e = lookup(db.editors, editorId, "Editor")
    if e["account_status"] == "BLOCKED":
        raise ApiError(ERR_INVALID_STATE, "Editor is already BLOCKED", 409)
    if _open_arbitration_as_initiator(e["id"]):
        raise ApiError(ERR_EDITOR_HAS_OPEN_ARBITRATION,
                       "Cannot block editor with open Arbitration disputes "
                       "as initiator", 409)
    e["account_status"] = "BLOCKED"
    # PRD 3.1: blocking "flags all pending revisions"; PRD 3.2 defines flagging
    # as transitioning the revision to FLAGGED and creating a VandalismReport.
    for rev in db.revisions.values():
        if rev["editor_id"] == e["id"] and rev["status"] == "PENDING":
            rev["status"] = "FLAGGED"
            touch(rev, bump_version=False)
            report = base_entity(has_version=False)
            report.update({
                "revision_id": rev["id"],
                "reporter_id": None,
                "report_type": "VANDALISM",
                "status": "PENDING",
                "auto_flagged": True,
                "rollback_applied": False,
            })
            db.vandalism_reports[report["id"]] = report
    closed_pages = set()
    for d in db.disputes.values():
        if d["initiator_id"] == e["id"] and d["status"] in ("OPEN", "ESCALATED"):
            d["status"] = "CLOSED"
            touch(d)
            closed_pages.add(d["page_id"])
    # PRD 3.4: closure "applies the same dispute_level recalculation" — the
    # page's dispute_level is derived from remaining open disputes.
    from services import recompute_dispute_level
    for pid in closed_pages:
        page = db.pages.get(pid)
        if page is not None:
            recompute_dispute_level(page)
            touch(page)
    touch(e)
    return success_object(e)


@bp.post("/wiki/editors/<editorId>/disclose-coi")
def disclose_coi(editorId):
    user_id, _role = require_roles("VolunteerEditor")
    e = lookup(db.editors, editorId, "Editor")
    if user_id != e["id"]:
        from errors import ERR_UNAUTHORIZED
        raise ApiError(ERR_UNAUTHORIZED,
                       "Editors may only file their own COI disclosure", 403)
    body = get_body()
    require_fields(body, ["disclosure_text"])
    e["coi_disclosed"] = True
    touch(e)
    return success_object(e)


def _q(name):
    from flask import request
    return request.args.get(name)
