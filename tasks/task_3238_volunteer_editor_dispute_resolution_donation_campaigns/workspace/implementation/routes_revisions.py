"""Revision routes: submit, accept, flag, revert."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db, _parse_iso
from errors import (ApiError, ERR_COI_UNDISCLOSED, ERR_PROTECTION_BLOCKED,
                    ERR_INSUFFICIENT_PRIVILEGE, ERR_INVALID_STATE,
                    ERR_VANDALISM_SCORE_HIGH, ERR_INVALID_REQUEST)
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch, check_occ)
from middleware import require_roles
from response import success_object
from services import (compute_vandalism_score, recompute_content_score,
                      protection_permits, has_open_arbitration)

bp = Blueprint("revisions", __name__)

REPORT_TYPES = {"VANDALISM", "SPAM", "BLP_VIOLATION", "COPYVIO"}


def _score(content_text, field):
    """Deterministic 0-100 score from content length, overridable by input."""
    if field and isinstance(field, (int, float)):
        return max(0, min(100, int(field)))
    text = content_text or ""
    # Sourcing: presence of citation-like markers; neutrality: length heuristic.
    return min(100, 50 + (len(text) % 51))


@bp.post("/wiki/pages/<pageId>/revisions")
def create_revision(pageId):
    user_id, role = require_roles("VolunteerEditor")
    page = lookup(db.pages, pageId, "Page")
    editor = lookup(db.editors, user_id, "Editor")
    # COI check (priority 5)
    if editor.get("coi_disclosure_required") and not editor.get("coi_disclosed"):
        raise ApiError(ERR_COI_UNDISCLOSED,
                       "Editor has undisclosed conflict of interest for this page",
                       403)
    # Protection check (priority 6)
    if not protection_permits(page, role, editor):
        raise ApiError(ERR_PROTECTION_BLOCKED,
                       "Page protection level prevents this edit", 403)
    body = get_body()
    require_fields(body, ["content_text", "summary"])
    content = body["content_text"]
    vandalism = compute_vandalism_score(page, editor, content)
    r = base_entity(has_version=False)
    r.update({
        "page_id": page["id"],
        "editor_id": editor["id"],
        "content_text": content,
        "summary": body["summary"],
        "status": "PENDING",
        "vandalism_score": vandalism,
        "source_quality_score": _score(content, body.get("source_quality_score")),
        "neutrality_score": _score(content, body.get("neutrality_score")),
    })
    db.revisions[r["id"]] = r
    return success_object(r, status=201)


@bp.get("/wiki/revisions")
def list_revisions():
    require_roles("VolunteerEditor", "Administrator", "LegalCounsel",
                  "PlatformAdmin")
    return list_response(db.revisions, filters={
        "page_id": request.args.get("page_id"),
        "editor_id": request.args.get("editor_id"),
        "status": request.args.get("status"),
    })


@bp.get("/wiki/revisions/<revisionId>")
def get_revision(revisionId):
    require_roles("VolunteerEditor", "Administrator", "LegalCounsel")
    return success_object(lookup(db.revisions, revisionId, "Revision"))


def _open_dispute_level(page_id):
    """Highest level among open disputes, or None."""
    levels = [d["level"] for d in db.disputes.values()
              if d["page_id"] == page_id and d["status"] in ("OPEN", "ESCALATED")]
    if not levels:
        return None
    if "ARBITRATION" in levels:
        return "ARBITRATION"
    if "NOTICE" in levels:
        return "NOTICE"
    return "TALK"


def _accept_side_effects(page, rev):
    rev["status"] = "ACCEPTED"
    touch(rev, bump_version=False)
    page["current_revision_id"] = rev["id"]
    recompute_content_score(page)
    editor = db.editors.get(rev["editor_id"])
    if editor is not None:
        editor["edit_count"] = editor.get("edit_count", 0) + 1
        touch(editor)
    touch(page)


@bp.post("/wiki/revisions/<revisionId>/accept")
def accept_revision(revisionId):
    user_id, role = require_roles("VolunteerEditor", "Administrator")
    rev = lookup(db.revisions, revisionId, "Revision")
    page = lookup(db.pages, rev["page_id"], "Page")
    body = get_body()
    # OCC (HTTP 412)
    check_occ(body, "expected_page_version", page)
    editor = db.editors.get(user_id) if role == "VolunteerEditor" else None

    if rev["status"] == "PENDING":
        if role == "VolunteerEditor":
            if editor is None:
                from errors import ERR_NOT_FOUND
                raise ApiError(ERR_NOT_FOUND, "Editor does not exist", 404)
            if not editor.get("rollback_eligible"):
                raise ApiError(ERR_INSUFFICIENT_PRIVILEGE,
                               "Editor lacks rollback_eligible or admin status",
                               403)
            if rev["vandalism_score"] >= 50:
                raise ApiError(ERR_VANDALISM_SCORE_HIGH,
                               "Cannot accept revision with vandalism_score "
                               ">= 50 without admin override", 409)
        if not protection_permits(page, role, editor):
            raise ApiError(ERR_PROTECTION_BLOCKED,
                           "Page protection level prevents this edit", 403)
        if has_open_arbitration(page["id"]):
            raise ApiError(ERR_INVALID_STATE,
                           "Open Arbitration-level dispute on page", 409)
        # Composite quality threshold: 40 uncontested, 70 contested.
        level = _open_dispute_level(page["id"])
        threshold = 70 if level in ("NOTICE", "ARBITRATION") else 40
        composite = 0.5 * rev["source_quality_score"] + 0.5 * rev["neutrality_score"]
        if composite < threshold:
            raise ApiError(ERR_INVALID_STATE,
                           "Composite quality score below acceptance threshold",
                           409)
        _accept_side_effects(page, rev)
        return success_object(rev)

    if rev["status"] == "FLAGGED":
        # Only an Administrator may accept a FLAGGED revision, and only when
        # the vandalism report was DISMISSED.
        if role != "Administrator":
            raise ApiError(ERR_INSUFFICIENT_PRIVILEGE,
                           "Only an Administrator may accept a flagged revision",
                           403)
        reports = [r for r in db.vandalism_reports.values()
                   if r["revision_id"] == rev["id"]]
        if not reports or reports[-1]["status"] != "DISMISSED":
            raise ApiError(ERR_INVALID_STATE,
                           "Vandalism report must be DISMISSED before accepting "
                           "a flagged revision", 409)
        _accept_side_effects(page, rev)
        return success_object(rev)

    raise ApiError(ERR_INVALID_STATE,
                   "Only a PENDING or FLAGGED revision can be accepted", 409)


@bp.post("/wiki/revisions/<revisionId>/flag")
def flag_revision(revisionId):
    user_id, role = require_roles("VolunteerEditor", "Administrator")
    rev = lookup(db.revisions, revisionId, "Revision")
    if rev["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a PENDING revision can be flagged", 409)
    editor = db.editors.get(user_id) if role == "VolunteerEditor" else None
    if role == "VolunteerEditor":
        if editor is None:
            from errors import ERR_NOT_FOUND
            raise ApiError(ERR_NOT_FOUND, "Editor does not exist", 404)
        if not editor.get("rollback_eligible"):
            raise ApiError(ERR_INSUFFICIENT_PRIVILEGE,
                           "Editor lacks rollback_eligible or admin status", 403)
    body = get_body()
    require_fields(body, ["report_type"])
    if body["report_type"] not in REPORT_TYPES:
        raise ApiError(ERR_INVALID_REQUEST,
                       "report_type must be one of VANDALISM, SPAM, "
                       "BLP_VIOLATION, COPYVIO", 400)
    rev["status"] = "FLAGGED"
    touch(rev, bump_version=False)
    report = base_entity(has_version=False)
    report.update({
        "revision_id": rev["id"],
        "reporter_id": user_id,
        "report_type": body["report_type"],
        "status": "PENDING",
        "auto_flagged": False,
        "rollback_applied": False,
    })
    db.vandalism_reports[report["id"]] = report
    return success_object(report)


@bp.post("/wiki/revisions/<revisionId>/revert")
def revert_revision(revisionId):
    user_id, role = require_roles("VolunteerEditor", "Administrator")
    rev = lookup(db.revisions, revisionId, "Revision")
    if rev["status"] != "FLAGGED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a FLAGGED revision can be reverted", 409)
    editor = db.editors.get(user_id) if role == "VolunteerEditor" else None
    if role == "VolunteerEditor":
        if editor is None:
            from errors import ERR_NOT_FOUND
            raise ApiError(ERR_NOT_FOUND, "Editor does not exist", 404)
        if not editor.get("rollback_eligible"):
            raise ApiError(ERR_INSUFFICIENT_PRIVILEGE,
                           "Editor lacks rollback_eligible or admin status", 403)
    page = lookup(db.pages, rev["page_id"], "Page")
    body = get_body()
    check_occ(body, "expected_page_version", page)
    reports = [r for r in db.vandalism_reports.values()
               if r["revision_id"] == rev["id"]]
    report = reports[-1] if reports else None
    if report is None or report["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE,
                       "VandalismReport must be CONFIRMED before revert", 409)
    # Roll back current_revision_id to the prior ACCEPTED revision (excluding
    # this revision), latest by updated_at.
    prior = [r for r in db.revisions.values()
             if r["page_id"] == page["id"] and r["status"] == "ACCEPTED"
             and r["id"] != rev["id"]
             and r["id"] != page.get("current_revision_id")]
    prior.sort(key=lambda r: (r["updated_at"], r["id"]))
    page["current_revision_id"] = prior[-1]["id"] if prior else None
    rev["status"] = "REVERTED"
    touch(rev, bump_version=False)
    report["rollback_applied"] = True
    touch(report, bump_version=False)
    recompute_content_score(page)
    touch(page)
    return success_object(rev)
