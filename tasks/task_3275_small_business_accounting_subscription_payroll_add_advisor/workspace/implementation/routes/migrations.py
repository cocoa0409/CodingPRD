"""Migration jobs."""
from flask import Blueprint
import db
import services
from auth import require_role, require_company_scope
from errors import (ok, ok_list, invalid_state, not_writable,
                    migration_in_flight, migration_not_cancellable, not_found,
                    invalid_request)
from helpers import (body_json, req_str, req_int, get_or_404, paginate,
                     sort_by_created, enum_check, filter_items,
                     company_subscription)
import serializers

bp = Blueprint("migrations", __name__, url_prefix="/api/companies/<company_id>")

SOURCE_PRODUCTS = ("DESKTOP_PRO", "DESKTOP_PREMIER", "DESKTOP_ENTERPRISE")
OUTCOMES = ("CLEAN", "WITH_LIMITATIONS", "FAILED")


@bp.post("/migration_jobs")
def create_migration(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    sub = company_subscription(company_id)
    if sub is not None and sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        not_writable()
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    source = enum_check(req_str(data, "source_product"), SOURCE_PRODUCTS, "source_product")
    for m in db.TABLES["MigrationJob"].values():
        if m["company_id"] == company_id and m["migration_status"] in ("QUEUED", "CONVERTING"):
            migration_in_flight()
    rec = {
        "company_id": company_id,
        "source_product": source,
        "source_file_size_bytes": req_int(data, "source_file_size_bytes"),
        "target_list_entries": req_int(data, "target_list_entries"),
        "migration_status": "QUEUED",
        "limitation_codes": [],
    }
    db.stamp_common(rec)
    db.TABLES["MigrationJob"][rec["id"]] = rec
    return ok(serializers.serialize_migration_job(rec), status=201)


@bp.get("/migration_jobs")
def list_migrations(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [m for m in db.TABLES["MigrationJob"].values() if m["company_id"] == company_id]
    items = filter_items(items, [("migration_status", "migration_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_migration_job(m) for m in page],
                   limit, offset, total)


def _get_migration(company_id, mid):
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("MigrationJob", mid)
    if rec["company_id"] != company_id:
        not_found("MigrationJob not in company")
    return rec


@bp.get("/migration_jobs/<mid>")
def get_migration(company_id, mid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    rec = _get_migration(company_id, mid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_migration_job(rec))


@bp.post("/migration_jobs/<mid>/start")
def start_migration(company_id, mid):
    require_role(["PlatformAdmin"])
    rec = _get_migration(company_id, mid)
    if rec["migration_status"] != "QUEUED":
        invalid_state("Migration not QUEUED")
    rec["migration_status"] = "CONVERTING"
    db.touch(rec)
    return ok(serializers.serialize_migration_job(rec))


@bp.post("/migration_jobs/<mid>/complete")
def complete_migration(company_id, mid):
    require_role(["PlatformAdmin"])
    rec = _get_migration(company_id, mid)
    if rec["migration_status"] != "CONVERTING":
        invalid_state("Migration not CONVERTING")
    data = body_json()
    outcome = enum_check(req_str(data, "outcome"), OUTCOMES, "outcome")
    if outcome == "CLEAN":
        # validate clean legitimacy; otherwise treat as invalid transition
        sub = company_subscription(company_id)
        plan = db.TABLES["SubscriptionPlan"].get(sub["plan_id"]) if sub else None
        if rec["target_list_entries"] > services.LIST_LIMIT:
            invalid_state("List entries exceed ceiling; cannot complete CLEAN")
        if rec["source_product"] == "DESKTOP_ENTERPRISE" and \
                (plan is None or not plan.get("feature_multi_currency")):
            invalid_state("Enterprise source requires multi-currency target plan")
        rec["migration_status"] = "COMPLETED_CLEAN"
    elif outcome == "WITH_LIMITATIONS":
        sub = company_subscription(company_id)
        plan = db.TABLES["SubscriptionPlan"].get(sub["plan_id"]) if sub else None
        codes = []
        addon_exists = any(
            p["subscription_id"] == sub["id"] for p in db.TABLES["PayrollAddon"].values()
        ) if sub else False
        if addon_exists:
            codes.append("PAYROLL_NOT_MIGRATED")
        if plan is None or not plan.get("feature_multi_currency"):
            codes.append("MULTI_CURRENCY_NOT_MIGRATED")
        if rec["target_list_entries"] > services.LIST_LIMIT:
            codes.append("LIST_LIMIT_EXCEEDED_PARTIAL")
        rec["limitation_codes"] = codes
        rec["migration_status"] = "COMPLETED_WITH_LIMITATIONS"
    else:
        rec["migration_status"] = "FAILED"
    db.touch(rec)
    return ok(serializers.serialize_migration_job(rec))


@bp.post("/migration_jobs/<mid>/cancel")
def cancel_migration(company_id, mid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser"])
    rec = _get_migration(company_id, mid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    if rec["migration_status"] not in ("QUEUED", "CONVERTING"):
        migration_not_cancellable()
    rec["migration_status"] = "CANCELLED"
    db.touch(rec)
    return ok(serializers.serialize_migration_job(rec))
