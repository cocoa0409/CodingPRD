"""Bank connections and transactions."""
from flask import Blueprint
import db
import services
from auth import require_role, require_company_scope, active_grant
from errors import (ok, ok_list, invalid_state, not_writable,
                    conn_not_authorizable, consent_expired, conn_already_exists,
                    txn_locked, invalid_request, not_found, forbidden_role,
                    ApiError)
from helpers import (body_json, req_str, req_int, get_or_404, paginate,
                     sort_by_created, filter_items, company_subscription,
                     parse_dt_field)
import serializers

bp = Blueprint("bank", __name__, url_prefix="/api/companies/<company_id>")

WRITABLE_LIFECYCLES = ("TRIAL", "ACTIVE", "PAST_DUE", "REACTIVATED")
AUTHORIZE_LIFECYCLES = ("TRIAL", "ACTIVE", "PAST_DUE", "REACTIVATED")
REAUTH_LIFECYCLES = ("ACTIVE", "REACTIVATED", "PAST_DUE")


def _sub(company_id):
    get_or_404("ClientCompany", company_id)
    sub = company_subscription(company_id)
    if sub is None:
        not_found("Subscription not found")
    return sub


def _gate_writable(sub):
    if sub["lifecycle_status"] not in WRITABLE_LIFECYCLES:
        not_writable()


def _get_conn(company_id, bid):
    get_or_404("ClientCompany", company_id)
    conn = get_or_404("BankConnection", bid)
    if conn["company_id"] != company_id:
        not_found("Connection not in company")
    return conn


def _check_txn_lock(txn):
    if txn.get("reconciled_in_id"):
        txn_locked()


def _actor_can_txn(role, identity, company_id):
    """CompanyUser STANDARD+ or AccountantUser with FULL_BOOKKEEPING."""
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
        if identity.get("permission_level") in ("REPORTS_ONLY", "TIME_TRACKING"):
            forbidden_role()
    else:
        active_grant(identity, company_id, ("FULL_BOOKKEEPING",))


def _admin_only(identity):
    if identity is None or identity.get("permission_level") not in ("PRIMARY_ADMIN", "COMPANY_ADMIN"):
        forbidden_role()


@bp.post("/bank_connections")
def create_connection(company_id):
    role, identity = require_role(["CompanyUser"])
    sub = _sub(company_id)
    require_company_scope(identity, company_id)
    _gate_writable(sub)
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    institution = req_str(data, "institution_name")
    mask = req_str(data, "external_account_mask")
    consent = parse_dt_field(data, "consent_expires_at")
    for c in db.TABLES["BankConnection"].values():
        if (c["company_id"] == company_id
                and c["institution_name"] == institution
                and c["external_account_mask"] == mask
                and c["connection_status"] not in ("DISCONNECTED", "REVOKED")):
            conn_already_exists()
    rec = {
        "company_id": company_id,
        "institution_name": institution,
        "external_account_mask": mask,
        "connection_status": "PENDING_AUTH",
        "last_sync_at": None,
        "consent_expires_at": db.fmt(consent),
    }
    db.stamp_common(rec)
    db.TABLES["BankConnection"][rec["id"]] = rec
    return ok(serializers.serialize_bank_connection(rec), status=201)


@bp.get("/bank_connections")
def list_connections(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [c for c in db.TABLES["BankConnection"].values() if c["company_id"] == company_id]
    items = filter_items(items, [("connection_status", "connection_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_bank_connection(c) for c in page],
                   limit, offset, total)


@bp.get("/bank_connections/<bid>")
def get_connection(company_id, bid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    conn = _get_conn(company_id, bid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_bank_connection(conn))


@bp.post("/bank_connections/<bid>/authorize")
def authorize_connection(company_id, bid):
    role, identity = require_role(["CompanyUser"])
    sub = _sub(company_id)
    require_company_scope(identity, company_id)
    _admin_only(identity)
    _gate_writable(sub)
    conn = _get_conn(company_id, bid)
    if conn["connection_status"] != "PENDING_AUTH":
        conn_not_authorizable()
    exp = db.parse_iso(conn.get("consent_expires_at"))
    if exp is None or db.now() >= exp:
        consent_expired()
    conn["connection_status"] = "ACTIVE"
    conn["last_sync_at"] = db.fmt(db.now())
    db.touch(conn)
    return ok(serializers.serialize_bank_connection(conn))


@bp.post("/bank_connections/<bid>/reauthorize")
def reauthorize_connection(company_id, bid):
    role, identity = require_role(["CompanyUser"])
    sub = _sub(company_id)
    require_company_scope(identity, company_id)
    _admin_only(identity)
    if sub["lifecycle_status"] not in REAUTH_LIFECYCLES:
        invalid_state("Subscription not in a reauthorizable state")
    conn = _get_conn(company_id, bid)
    if conn["connection_status"] != "STALE":
        conn_not_authorizable()
    data = body_json()
    consent = parse_dt_field(data, "consent_expires_at")
    if db.now() >= consent:
        consent_expired()
    conn["connection_status"] = "ACTIVE"
    conn["consent_expires_at"] = db.fmt(consent)
    db.touch(conn)
    return ok(serializers.serialize_bank_connection(conn))


@bp.post("/bank_connections/<bid>/disconnect")
def disconnect_connection(company_id, bid):
    role, identity = require_role(["CompanyUser"])
    sub = _sub(company_id)
    require_company_scope(identity, company_id)
    if identity.get("permission_level") != "PRIMARY_ADMIN":
        from errors import needs_primary_admin
        needs_primary_admin()
    conn = _get_conn(company_id, bid)
    if conn["connection_status"] not in ("PENDING_AUTH", "ACTIVE", "STALE"):
        invalid_state("Connection not disconnectable")
    conn["connection_status"] = "DISCONNECTED"
    db.touch(conn)
    return ok(serializers.serialize_bank_connection(conn))


@bp.post("/bank_connections/<bid>/revoke")
def revoke_connection(company_id, bid):
    role, identity = require_role(["CompanyUser"])
    sub = _sub(company_id)
    require_company_scope(identity, company_id)
    if identity.get("permission_level") != "PRIMARY_ADMIN":
        from errors import needs_primary_admin
        needs_primary_admin()
    conn = _get_conn(company_id, bid)
    if conn["connection_status"] not in ("DISCONNECTED", "STALE"):
        invalid_state("Connection not revocable")
    conn["connection_status"] = "REVOKED"
    db.touch(conn)
    return ok(serializers.serialize_bank_connection(conn))


@bp.post("/bank_connections/<bid>/transactions")
def ingest_transaction(company_id, bid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser"])
    sub = _sub(company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    conn = _get_conn(company_id, bid)
    if conn["connection_status"] != "ACTIVE":
        invalid_state("Connection not ACTIVE; ingestion halted")
    data = body_json()
    posted_at = parse_dt_field(data, "posted_at")
    amount = req_int(data, "amount_cents")
    payee = req_str(data, "payee_raw")
    rec = {
        "bank_connection_id": conn["id"],
        "posted_at": db.fmt(posted_at),
        "amount_cents": amount,
        "payee_raw": payee,
        "category_id": None,
        "matched_rule_id": None,
        "txn_status": "UNCATEGORIZED",
        "reconciled_in_id": None,
    }
    db.stamp_common(rec)
    # Rule path gated on feature_bank_rules
    plan = db.TABLES["SubscriptionPlan"].get(sub["plan_id"])
    if plan is not None and plan.get("feature_bank_rules"):
        services.apply_rule_selector(company_id, rec)
    db.TABLES["BankTransaction"][rec["id"]] = rec
    # refresh recon projections
    for r in db.TABLES["Reconciliation"].values():
        if r["bank_connection_id"] == conn["id"] and r["recon_status"] in ("DRAFT", "IN_PROGRESS"):
            services.recon_recompute(r)
    return ok(serializers.serialize_bank_transaction(rec), status=201)


@bp.get("/bank_connections/<bid>/transactions")
def list_conn_transactions(company_id, bid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    conn = _get_conn(company_id, bid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [t for t in db.TABLES["BankTransaction"].values()
             if t["bank_connection_id"] == bid]
    items = filter_items(items, [("txn_status", "txn_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_bank_transaction(t) for t in page],
                   limit, offset, total)


@bp.get("/bank_transactions")
def list_transactions(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    conn_ids = {c["id"] for c in db.TABLES["BankConnection"].values()
                if c["company_id"] == company_id}
    items = [t for t in db.TABLES["BankTransaction"].values()
             if t["bank_connection_id"] in conn_ids]
    items = filter_items(items, [("bank_connection_id", "bank_connection_id"),
                                 ("txn_status", "txn_status"),
                                 ("category_id", "category_id")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_bank_transaction(t) for t in page],
                   limit, offset, total)


def _get_txn(company_id, tid):
    get_or_404("ClientCompany", company_id)
    txn = get_or_404("BankTransaction", tid)
    conn = db.TABLES["BankConnection"].get(txn["bank_connection_id"])
    if conn is None or conn["company_id"] != company_id:
        not_found("Transaction not in company")
    return txn


@bp.get("/bank_transactions/<tid>")
def get_transaction(company_id, tid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    txn = _get_txn(company_id, tid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_bank_transaction(txn))


def _refresh_recons(company_id, txn):
    for r in db.TABLES["Reconciliation"].values():
        if (r["company_id"] == company_id
                and r["bank_connection_id"] == txn["bank_connection_id"]
                and r["recon_status"] in ("DRAFT", "IN_PROGRESS")):
            services.recon_recompute(r)


@bp.post("/bank_transactions/<tid>/categorize")
def categorize_txn(company_id, tid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    txn = _get_txn(company_id, tid)
    _actor_can_txn(role, identity, company_id)
    data = body_json()
    category_id = req_str(data, "category_id")
    cat = db.TABLES["Category"].get(category_id)
    if cat is None or cat["company_id"] != company_id:
        not_found("Category not found")
    _check_txn_lock(txn)
    if txn["txn_status"] != "UNCATEGORIZED":
        invalid_state("Transaction not UNCATEGORIZED")
    txn["txn_status"] = "CATEGORIZED"
    txn["category_id"] = category_id
    txn["matched_rule_id"] = None
    db.touch(txn)
    _refresh_recons(company_id, txn)
    return ok(serializers.serialize_bank_transaction(txn))


@bp.post("/bank_transactions/<tid>/accept_suggestion")
def accept_suggestion(company_id, tid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    txn = _get_txn(company_id, tid)
    _actor_can_txn(role, identity, company_id)
    _check_txn_lock(txn)
    if txn["txn_status"] != "RULE_SUGGESTED":
        invalid_state("Transaction not RULE_SUGGESTED")
    rule = db.TABLES["CategorizationRule"].get(txn.get("matched_rule_id"))
    txn["txn_status"] = "CATEGORIZED"
    txn["category_id"] = rule["assign_category_id"] if rule else None
    db.touch(txn)
    _refresh_recons(company_id, txn)
    return ok(serializers.serialize_bank_transaction(txn))


@bp.post("/bank_transactions/<tid>/reject_suggestion")
def reject_suggestion(company_id, tid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    txn = _get_txn(company_id, tid)
    _actor_can_txn(role, identity, company_id)
    _check_txn_lock(txn)
    if txn["txn_status"] != "RULE_SUGGESTED":
        invalid_state("Transaction not RULE_SUGGESTED")
    txn["txn_status"] = "UNCATEGORIZED"
    txn["category_id"] = None
    txn["matched_rule_id"] = None
    db.touch(txn)
    _refresh_recons(company_id, txn)
    return ok(serializers.serialize_bank_transaction(txn))


@bp.post("/bank_transactions/<tid>/uncategorize")
def uncategorize_txn(company_id, tid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    txn = _get_txn(company_id, tid)
    _actor_can_txn(role, identity, company_id)
    _check_txn_lock(txn)
    if txn["txn_status"] != "CATEGORIZED":
        invalid_state("Transaction not CATEGORIZED")
    txn["txn_status"] = "UNCATEGORIZED"
    txn["category_id"] = None
    txn["matched_rule_id"] = None
    db.touch(txn)
    _refresh_recons(company_id, txn)
    return ok(serializers.serialize_bank_transaction(txn))


@bp.post("/bank_transactions/<tid>/exclude")
def exclude_txn(company_id, tid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    txn = _get_txn(company_id, tid)
    _actor_can_txn(role, identity, company_id)
    _check_txn_lock(txn)
    if txn["txn_status"] not in ("UNCATEGORIZED", "RULE_SUGGESTED", "CATEGORIZED"):
        invalid_state("Transaction not excludable")
    txn["txn_status"] = "EXCLUDED"
    db.touch(txn)
    _refresh_recons(company_id, txn)
    return ok(serializers.serialize_bank_transaction(txn))


@bp.post("/bank_transactions/<tid>/unexclude")
def unexclude_txn(company_id, tid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    txn = _get_txn(company_id, tid)
    _actor_can_txn(role, identity, company_id)
    if txn["txn_status"] != "EXCLUDED":
        invalid_state("Transaction not EXCLUDED")
    txn["txn_status"] = "UNCATEGORIZED"
    db.touch(txn)
    _refresh_recons(company_id, txn)
    return ok(serializers.serialize_bank_transaction(txn))
