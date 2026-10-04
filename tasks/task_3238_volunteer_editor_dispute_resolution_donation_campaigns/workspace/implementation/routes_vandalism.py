"""Vandalism report moderation routes."""
from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_INVALID_STATE
from helpers import list_response, lookup, touch
from middleware import require_roles
from response import success_object
from services import recompute_rollback_eligible

bp = Blueprint("vandalism", __name__)


@bp.get("/wiki/vandalism-reports")
def list_reports():
    require_roles("VolunteerEditor", "Administrator", "PlatformAdmin")
    return list_response(db.vandalism_reports, filters={
        "revision_id": request.args.get("revision_id"),
        "reporter_id": request.args.get("reporter_id"),
        "status": request.args.get("status"),
    })


@bp.get("/wiki/vandalism-reports/<reportId>")
def get_report(reportId):
    require_roles("VolunteerEditor", "Administrator")
    return success_object(lookup(db.vandalism_reports, reportId,
                                 "Vandalism report"))


def _moderate(reportId, new_status):
    require_roles("Administrator")
    report = lookup(db.vandalism_reports, reportId, "Vandalism report")
    if report["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a PENDING report can be moderated", 409)
    report["status"] = new_status
    touch(report, bump_version=False)
    rev = db.revisions.get(report["revision_id"])
    if rev is not None:
        editor = db.editors.get(rev["editor_id"])
        if editor is not None:
            recompute_rollback_eligible(editor)
            touch(editor)
    return success_object(report)


@bp.post("/wiki/vandalism-reports/<reportId>/confirm")
def confirm_report(reportId):
    return _moderate(reportId, "CONFIRMED")


@bp.post("/wiki/vandalism-reports/<reportId>/dismiss")
def dismiss_report(reportId):
    return _moderate(reportId, "DISMISSED")
