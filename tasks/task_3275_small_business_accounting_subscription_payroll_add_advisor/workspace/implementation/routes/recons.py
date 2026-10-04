"""Reconciliations."""
from flask import Blueprint
import db
import services
from auth import require_role, require_company_scope, active_grant
from errors import (ok, ok_list, invalid_state, not_writable, recon_overlap,
                    recon_not_zero, not_found, forbidden_role)
from helpers import (body_json, req_str, req_int, get_or_404, paginate,
                     sort_by_created, filter_items, company_subscription,
                     parse_dt_field)
import serializers

bp = Blueprint("recons", __name__, url_prefix="/api/companies/<company_id>")


def _actor(role, identity, company_id):
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
        if identity.get("permission_level") in ("REPORTS_ONLY", "TIME_TRACKING"):
            forbidden_role()
    else:
        active_grant(identity, company_id, ("FULL_BOOKKEEPING",))


def _overlap_check(company_id, conn_id, start, end, exclude_id=None):
    for r in db.TABLES["Reconciliation"].values():
        if r["company_id"] != company_id or r["bank_connection_id"] != conn_id:
            continue
        if r["recon_status"] not in ("IN_PROGRESS", "COMPLETED"):
            continue
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        rs = db.parse_iso(r["statement_period_start"])
        re_ = db.parse_iso(r["statement_period_end"])
        # closed intervals: overlap iff start <= re_ AND rs <= end
        if start <= re_ and rs <= end:
            recon_overlap()


@bp.post("/reconciliations")
def create_recon(company_id):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    _actor(role, identity, company_id)
    sub = company_subscription(company_id)
    if sub is not None and sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        not_writable()
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    conn_id = req_str(data, "bank_connection_id")
    conn = db.TABLES["BankConnection"].get(conn_id)
    if conn is None or conn["company_id"] != company_id:
        not_found("BankConnection not found")
    start = parse_dt_field(data, "statement_period_start")
    end = parse_dt_field(data, "statement_period_end")
    ending = req_int(data, "statement_ending_balance_cents")
    _overlap_check(company_id, conn_id, start, end)
    # beginning balance from most recent COMPLETED recon on this connection
    prior = [r for r in db.TABLES["Reconciliation"].values()
             if r["bank_connection_id"] == conn_id and r["recon_status"] == "COMPLETED"]
    beginning = 0
    if prior:
        prior.sort(key=lambda r: r.get("completed_at") or "")
        beginning = prior[-1]["statement_ending_balance_cents"]
    rec = {
        "company_id": company_id,
        "bank_connection_id": conn_id,
        "statement_period_start": db.fmt(start),
        "statement_period_end": db.fmt(end),
        "statement_ending_balance_cents": ending,
        "beginning_balance_cents": beginning,
        "cleared_cents": 0,
        "difference_cents": 0,
        "recon_status": "DRAFT",
        "completed_at": None,
    }
    db.stamp_common(rec)
    db.TABLES["Reconciliation"][rec["id"]] = rec
    services.recon_recompute(rec)
    return ok(serializers.serialize_reconciliation(rec), status=201)


@bp.get("/reconciliations")
def list_recons(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [r for r in db.TABLES["Reconciliation"].values() if r["company_id"] == company_id]
    items = filter_items(items, [("recon_status", "recon_status"),
                                 ("bank_connection_id", "bank_connection_id")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_reconciliation(r) for r in page],
                   limit, offset, total)


def _get_recon(company_id, rid):
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("Reconciliation", rid)
    if rec["company_id"] != company_id:
        not_found("Reconciliation not in company")
    return rec


@bp.get("/reconciliations/<rid>")
def get_recon(company_id, rid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    rec = _get_recon(company_id, rid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    services.recon_recompute(rec)
    return ok(serializers.serialize_reconciliation(rec))


@bp.post("/reconciliations/<rid>/start")
def start_recon(company_id, rid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    rec = _get_recon(company_id, rid)
    _actor(role, identity, company_id)
    if rec["recon_status"] != "DRAFT":
        invalid_state("Reconciliation not DRAFT")
    start = db.parse_iso(rec["statement_period_start"])
    end = db.parse_iso(rec["statement_period_end"])
    _overlap_check(company_id, rec["bank_connection_id"], start, end, exclude_id=rid)
    rec["recon_status"] = "IN_PROGRESS"
    db.touch(rec)
    services.recon_recompute(rec)
    return ok(serializers.serialize_reconciliation(rec))


@bp.post("/reconciliations/<rid>/complete")
def complete_recon(company_id, rid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    rec = _get_recon(company_id, rid)
    _actor(role, identity, company_id)
    if rec["recon_status"] != "IN_PROGRESS":
        invalid_state("Reconciliation not IN_PROGRESS")
    services.recon_recompute(rec, projected=False)
    if rec["difference_cents"] != 0:
        recon_not_zero()
    rec["recon_status"] = "COMPLETED"
    rec["completed_at"] = db.fmt(db.now())
    db.touch(rec)
    start = db.parse_iso(rec["statement_period_start"])
    end = db.parse_iso(rec["statement_period_end"])
    for txn in db.TABLES["BankTransaction"].values():
        if txn["bank_connection_id"] != rec["bank_connection_id"]:
            continue
        if txn["txn_status"] != "CATEGORIZED":
            continue
        posted = db.parse_iso(txn["posted_at"])
        if posted is not None and start.date() <= posted.date() <= end.date():
            txn["txn_status"] = "MATCHED_RECONCILED"
            txn["reconciled_in_id"] = rec["id"]
            db.touch(txn)
    return ok(serializers.serialize_reconciliation(rec))


@bp.post("/reconciliations/<rid>/abandon")
def abandon_recon(company_id, rid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    rec = _get_recon(company_id, rid)
    _actor(role, identity, company_id)
    if rec["recon_status"] != "IN_PROGRESS":
        invalid_state("Reconciliation not IN_PROGRESS")
    rec["recon_status"] = "DRAFT"
    rec["cleared_cents"] = 0
    services.recon_recompute(rec)
    db.touch(rec)
    return ok(serializers.serialize_reconciliation(rec))
