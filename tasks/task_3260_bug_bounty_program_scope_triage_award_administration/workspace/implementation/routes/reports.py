"""Report endpoints: submission, list/read, triage, provide-info, validate."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PROGRAM_NOT_ACTIVE, ERR_SCOPE_VERSION_REQUIRED,
    ERR_RESEARCHER_SUSPENDED, ERR_RESEARCHER_BANNED, ERR_OUT_OF_SCOPE,
    ERR_INVITATION_REQUIRED, ERR_DUPLICATE_OF_INVALID,
)
from helpers import (
    base_entity, touch, get_body, require_fields, reject_unknown_fields,
    parse_pagination,
)
from middleware import require_roles, check_researcher_owner
from response import success_object, success_list
from serializers import report_out
from services import reputation as rep_svc
from services import calculations as calc

bp = Blueprint("reports", __name__)

VULN_CLASSES = {"XSS", "SQLI", "CSRF", "SSRF", "AUTHZ", "RCE", "OTHER"}
CREATE_FIELDS = {"program_id", "asset_id", "title", "description", "vulnerability_class"}
TRIAGE_FIELDS = {"action", "duplicate_of_id", "note"}
TRIAGE_ACTIONS = {
    "TRIAGE", "REQUEST_INFO", "MARK_DUPLICATE", "MARK_NOT_APPLICABLE",
    "MARK_INFORMATIVE", "REOPEN",
}
PROVIDE_INFO_FIELDS = {"info"}
VALIDATE_FIELDS = {"impact", "exploitability", "affected_scope"}


def _get_report(rid):
    r = db.reports.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"Report {rid} not found")
    return r


def _effective_scope_version(program_id, at):
    for v in db.scope_versions.values():
        if v["program_id"] != program_id:
            continue
        ef = clock.parse_iso(v["effective_from"])
        et = v.get("effective_to")
        if ef <= at and (et is None or at < clock.parse_iso(et)):
            return v
    return None


@bp.route("/api/reports", methods=["POST"])
def submit_report():
    user_id, role = require_roles({"Researcher"})
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    require_fields(body, ["program_id", "asset_id", "title", "description",
                          "vulnerability_class"])
    program = db.programs.get(body["program_id"])
    if program is None:
        raise_err(ERR_NOT_FOUND, f"Program {body['program_id']} not found")
    asset = db.assets.get(body["asset_id"])
    if asset is None:
        raise_err(ERR_NOT_FOUND, f"Asset {body['asset_id']} not found")
    if body["vulnerability_class"] not in VULN_CLASSES:
        raise_err(ERR_INVALID_REQUEST, "Invalid vulnerability_class")
    researcher = db.researchers.get(user_id)
    if researcher is None:
        raise_err(ERR_NOT_FOUND, f"Researcher {user_id} not found")
    if program["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Program is not ACTIVE")
    if researcher["status"] == "SUSPENDED":
        raise_err(ERR_RESEARCHER_SUSPENDED, "SUSPENDED researcher may not submit reports")
    if researcher["status"] == "BANNED":
        raise_err(ERR_RESEARCHER_BANNED, "BANNED researcher may not submit reports")
    now = clock.now()
    sv = _effective_scope_version(program["id"], now)
    if sv is None:
        raise_err(ERR_SCOPE_VERSION_REQUIRED, "No scope version effective at submission")
    if (
        asset["program_id"] != program["id"]
        or asset["status"] != "ACTIVE"
        or asset["id"] not in sv["in_scope_asset_ids"]
    ):
        raise_err(ERR_OUT_OF_SCOPE, "Asset is out of scope for this program")
    if program["visibility"] == "PRIVATE":
        accepted = any(
            i["program_id"] == program["id"]
            and i["researcher_id"] == researcher["id"]
            and i["status"] == "ACCEPTED"
            for i in db.invitations.values()
        )
        if not accepted:
            raise_err(ERR_INVITATION_REQUIRED, "An ACCEPTED invitation is required")
    r = base_entity()
    r.update(
        {
            "program_id": program["id"],
            "asset_id": asset["id"],
            "researcher_id": researcher["id"],
            "duplicate_of_id": None,
            "scope_version_id": sv["id"],
            "title": body["title"],
            "description": body["description"],
            "vulnerability_class": body["vulnerability_class"],
            "status": "NEW",
            "impact": None,
            "exploitability": None,
            "affected_scope": None,
            "severity_score_base": None,
            "severity_score_adjusted": None,
            "severity_final": None,
            "tier_at_validation": None,
            "is_first_validated_report": None,
            "submitted_at": clock.iso(now),
            "first_response_at": None,
            "triaged_at": None,
            "validated_at": None,
            "resolved_at": None,
            "response_due_at": clock.iso(
                now + timedelta(hours=program["response_sla_hours"])
            ),
            "resolution_due_at": None,
        }
    )
    db.reports[r["id"]] = r
    return success_object(report_out(r), 201)


@bp.route("/api/reports/<report_id>", methods=["GET"])
def read_report(report_id):
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    return success_object(report_out(_get_report(report_id)))


@bp.route("/api/reports", methods=["GET"])
def list_reports():
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    limit, offset = parse_pagination(request.args)
    items = list(db.reports.values())
    for f in ("program_id", "researcher_id", "asset_id", "status",
              "duplicate_of_id", "scope_version_id"):
        val = request.args.get(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    items.sort(key=lambda r: r["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([report_out(r) for r in page], limit, offset, total)


def _rep_delta(researcher, delta, kind):
    rep_svc.apply_delta(researcher, delta, kind)
    touch(researcher)


@bp.route("/api/reports/<report_id>/triage", methods=["POST"])
def triage_report(report_id):
    require_roles({"Triager"})
    rep = _get_report(report_id)
    body = get_body()
    reject_unknown_fields(body, TRIAGE_FIELDS)
    require_fields(body, ["action"])
    action = body["action"]
    if action not in TRIAGE_ACTIONS:
        raise_err(ERR_INVALID_REQUEST, "Invalid triage action")
    researcher = db.researchers.get(rep["researcher_id"])
    now = clock.now()
    st = rep["status"]

    if action == "TRIAGE":
        if st != "NEW":
            raise_err(ERR_INVALID_STATE, f"Cannot TRIAGE report in {st}")
        rep["status"] = "TRIAGED"
        if rep["first_response_at"] is None:
            rep["first_response_at"] = clock.iso(now)
        rep["triaged_at"] = clock.iso(now)
    elif action == "REQUEST_INFO":
        if st != "TRIAGED":
            raise_err(ERR_INVALID_STATE, f"Cannot REQUEST_INFO report in {st}")
        rep["status"] = "NEEDS_INFO"
        rep["triaged_at"] = clock.iso(now)
    elif action == "MARK_DUPLICATE":
        if st not in ("NEW", "TRIAGED", "NEEDS_INFO", "VALIDATED"):
            raise_err(ERR_INVALID_STATE, f"Cannot MARK_DUPLICATE report in {st}")
        anchor_id = body.get("duplicate_of_id")
        if not anchor_id:
            raise_err(ERR_DUPLICATE_OF_INVALID, "duplicate_of_id is required")
        anchor = db.reports.get(anchor_id)
        if (
            anchor is None
            or anchor["id"] == rep["id"]
            or anchor["program_id"] != rep["program_id"]
            or anchor["vulnerability_class"] != rep["vulnerability_class"]
            or anchor["status"] not in ("VALIDATED", "RESOLVED")
        ):
            raise_err(ERR_DUPLICATE_OF_INVALID, "Invalid duplicate anchor")
        rep["status"] = "DUPLICATE"
        rep["duplicate_of_id"] = anchor["id"]
        if rep["first_response_at"] is None:
            rep["first_response_at"] = clock.iso(now)
        rep["triaged_at"] = clock.iso(now)
        if researcher:
            _rep_delta(researcher, -10, "duplicate")
    elif action == "MARK_NOT_APPLICABLE":
        if st not in ("NEW", "TRIAGED", "NEEDS_INFO"):
            raise_err(ERR_INVALID_STATE, f"Cannot MARK_NOT_APPLICABLE report in {st}")
        rep["status"] = "NOT_APPLICABLE"
        if rep["first_response_at"] is None:
            rep["first_response_at"] = clock.iso(now)
        rep["triaged_at"] = clock.iso(now)
        if researcher:
            _rep_delta(researcher, -15, "not_applicable")
    elif action == "MARK_INFORMATIVE":
        if st not in ("NEW", "TRIAGED"):
            raise_err(ERR_INVALID_STATE, f"Cannot MARK_INFORMATIVE report in {st}")
        rep["status"] = "INFORMATIVE"
        if rep["first_response_at"] is None:
            rep["first_response_at"] = clock.iso(now)
        rep["triaged_at"] = clock.iso(now)
        if researcher:
            _rep_delta(researcher, 2, "informative")
    elif action == "REOPEN":
        if st not in ("DUPLICATE", "NOT_APPLICABLE"):
            raise_err(ERR_INVALID_STATE, f"Cannot REOPEN report in {st}")
        prior = st
        rep["status"] = "TRIAGED"
        rep["duplicate_of_id"] = None
        rep["triaged_at"] = clock.iso(now)
        if researcher:
            _rep_delta(researcher, 10 if prior == "DUPLICATE" else 15, "reopen")
    touch(rep)
    return success_object(report_out(rep))


@bp.route("/api/reports/<report_id>/provide-info", methods=["POST"])
def provide_info(report_id):
    user_id, role = require_roles({"Researcher"})
    rep = _get_report(report_id)
    check_researcher_owner(user_id, role, rep["researcher_id"])
    body = get_body()
    reject_unknown_fields(body, PROVIDE_INFO_FIELDS)
    require_fields(body, ["info"])
    researcher = db.researchers.get(rep["researcher_id"])
    if researcher and researcher["status"] == "BANNED":
        raise_err(ERR_RESEARCHER_BANNED, "BANNED researcher may not provide info")
    if rep["status"] != "NEEDS_INFO":
        raise_err(ERR_INVALID_STATE, f"Report is {rep['status']}, not NEEDS_INFO")
    rep["status"] = "TRIAGED"
    rep["triaged_at"] = clock.iso_now()
    touch(rep)
    return success_object(report_out(rep))


@bp.route("/api/reports/<report_id>/validate", methods=["POST"])
def validate_report(report_id):
    require_roles({"Triager"})
    rep = _get_report(report_id)
    body = get_body()
    reject_unknown_fields(body, VALIDATE_FIELDS)
    require_fields(body, ["impact", "exploitability", "affected_scope"])
    for f in ("impact", "exploitability", "affected_scope"):
        v = body[f]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 10:
            raise_err(ERR_INVALID_REQUEST, f"{f} must be an integer 0-10")
    if rep["status"] != "TRIAGED":
        raise_err(ERR_INVALID_STATE, f"Cannot validate report in {rep['status']}")
    program = db.programs[rep["program_id"]]
    asset = db.assets[rep["asset_id"]]
    researcher = db.researchers[rep["researcher_id"]]
    rep_svc.refresh_reputation(researcher)

    base, adjusted, final = calc.severity_score(
        body["impact"], body["exploitability"], body["affected_scope"],
        asset["criticality"], program["exposure_modifier"],
    )
    rep["impact"] = body["impact"]
    rep["exploitability"] = body["exploitability"]
    rep["affected_scope"] = body["affected_scope"]
    rep["severity_score_base"] = base
    rep["severity_score_adjusted"] = adjusted
    rep["severity_final"] = final
    rep["tier_at_validation"] = researcher["tier"]
    prior = any(
        r["researcher_id"] == researcher["id"]
        and r["program_id"] == program["id"]
        and r["status"] in ("VALIDATED", "RESOLVED")
        and r["id"] != rep["id"]
        for r in db.reports.values()
    )
    rep["is_first_validated_report"] = not prior
    now = clock.now()
    rep["status"] = "VALIDATED"
    rep["validated_at"] = clock.iso(now)
    rep["resolution_due_at"] = clock.iso(
        now + timedelta(days=program["resolution_sla_days"])
    )
    touch(rep)
    return success_object(report_out(rep))
