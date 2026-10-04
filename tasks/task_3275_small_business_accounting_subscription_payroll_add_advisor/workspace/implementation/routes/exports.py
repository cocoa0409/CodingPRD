"""Export requests."""
from datetime import timedelta
from flask import Blueprint
import db
from auth import require_role, require_company_scope, active_grant
from errors import (ok, ok_list, invalid_state, export_not_downloadable,
                    export_requires_primary, window_expired, not_found,
                    forbidden_role, invalid_request, ApiError)
from helpers import (body_json, req_str, get_or_404, paginate, sort_by_created,
                     enum_check, filter_items)
import serializers

bp = Blueprint("exports", __name__, url_prefix="/api/companies/<company_id>")

FORMATS = ("CSV", "XLSX", "QBO_BACKUP")
SCOPES = ("TRANSACTIONS_ONLY", "FULL_LEDGER", "PAYROLL_RECORDS")


@bp.post("/exports")
def create_export(company_id):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    req_user_id = req_str(data, "requested_by_user_id")
    req_user = db.TABLES["CompanyUser"].get(req_user_id)
    if req_user is None or req_user["company_id"] != company_id:
        not_found("requested_by_user_id not found")
    fmt = enum_check(req_str(data, "format"), FORMATS, "format")
    scope = enum_check(req_str(data, "scope"), SCOPES, "scope")
    # Exports allowed in ACTIVE and CANCELLED_READ_ONLY alike — but not PURGED.
    company = db.TABLES["ClientCompany"].get(company_id)
    if company.get("company_status") == "PURGED":
        invalid_state("Company purged")
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
        if scope == "FULL_LEDGER" and identity.get("permission_level") != "PRIMARY_ADMIN":
            export_requires_primary()
    else:
        grant = active_grant(identity, company_id,
                             ("FULL_BOOKKEEPING", "REPORTS_READ_ONLY"))
        if scope == "FULL_LEDGER":
            export_requires_primary()
    rec = {
        "company_id": company_id,
        "requested_by_user_id": req_user_id,
        "format": fmt,
        "scope": scope,
        "export_status": "PENDING",
        "ready_at": None,
        "download_expires_at": None,
    }
    db.stamp_common(rec)
    db.TABLES["ExportRequest"][rec["id"]] = rec
    return ok(serializers.serialize_export_request(rec), status=201)


@bp.get("/exports")
def list_exports(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [e for e in db.TABLES["ExportRequest"].values() if e["company_id"] == company_id]
    items = filter_items(items, [("export_status", "export_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_export_request(e) for e in page],
                   limit, offset, total)


def _get_export(company_id, eid):
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("ExportRequest", eid)
    if rec["company_id"] != company_id:
        not_found("Export not in company")
    return rec


@bp.get("/exports/<eid>")
def get_export(company_id, eid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    rec = _get_export(company_id, eid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_export_request(rec))


@bp.post("/exports/<eid>/mark_ready")
def mark_ready(company_id, eid):
    require_role(["PlatformAdmin"])
    rec = _get_export(company_id, eid)
    if rec["export_status"] != "PENDING":
        invalid_state("Export not PENDING")
    now = db.now()
    rec["export_status"] = "READY"
    rec["ready_at"] = db.fmt(now)
    rec["download_expires_at"] = db.fmt(now + timedelta(days=30))
    db.touch(rec)
    return ok(serializers.serialize_export_request(rec))


@bp.post("/exports/<eid>/download")
def download_export(company_id, eid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    rec = _get_export(company_id, eid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
        if identity.get("permission_level") != "PRIMARY_ADMIN":
            from errors import needs_primary_admin
            needs_primary_admin()
    else:
        active_grant(identity, company_id, ("FULL_BOOKKEEPING",))
    if rec["export_status"] != "READY":
        export_not_downloadable()
    exp = db.parse_iso(rec.get("download_expires_at"))
    if exp is not None and db.now() >= exp:
        window_expired()
    rec["export_status"] = "DOWNLOADED"
    db.touch(rec)
    return ok(serializers.serialize_export_request(rec))
