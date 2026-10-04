"""Org, revenue declaration, tier assessment, ledger routes."""
from flask import Blueprint

from db import db
from errors import raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_TIER_FEATURE_NOT_ALLOWED, ERR_DUPLICATE_PERIOD, ERR_ORG_SUSPENDED, ERR_STALE_VERSION
from helpers import (
    ok, ok_list, body, new_common, new_id, now_iso, parse_period,
    require_non_neg_int,
)
from middleware import authenticate, authorize, get_org_or_404, check_org_ownership
from services_calc import (
    tier_determination, _signal_tier, recompute_effective_tier,
    compute_standing, compute_migration_status, org_balance_due,
    sync_org_balance,
)

bp = Blueprint("orgs", __name__)

TIER_CODES = {"PERSONAL", "EDUCATION", "PRO", "ENTERPRISE"}


def org_view(org):
    """Org with computed fields refreshed."""
    org["org_standing"] = compute_standing(org)
    org["migration_status"] = "MIGRATED" if _is_migrated(org["id"]) else compute_migration_status(org)
    org["balance_due_cents"] = org_balance_due(org["id"])
    return org


def _is_migrated(org_id):
    for a in db.migration_assessments.values():
        if a["org_id"] == org_id and a["assessment_status"] == "COMPLETED":
            return True
    return False


@bp.route("/orgs", methods=["POST"])
def create_org():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    b = body()
    legal_name = b.get("legal_name")
    contact_email = b.get("contact_email")
    declared = b.get("declared_tier_code")
    if not isinstance(legal_name, str) or not isinstance(contact_email, str):
        raise_err(ERR_VALIDATION, "legal_name and contact_email are required strings")
    if declared not in TIER_CODES:
        raise_err(ERR_VALIDATION, "declared_tier_code invalid")
    education_verified = b.get("education_verified", False)
    if not isinstance(education_verified, bool):
        raise_err(ERR_VALIDATION, "education_verified must be a boolean")
    if declared == "EDUCATION" and not education_verified:
        raise_err(ERR_TIER_FEATURE_NOT_ALLOWED, "EDUCATION tier requires education verification")
    ent = new_common()
    ent.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "education_verified": education_verified,
        "declared_tier_code": declared,
        "effective_tier_code": declared,
        "org_standing": "GOOD",
        "trust_score": 80,
        "migration_status": "NONE",
        "balance_due_cents": 0,
        "marketplace_credit_cents": 0,
        "audit_suggestion": None,
    })
    db.orgs[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/orgs/<oid>", methods=["GET"])
def get_org(oid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"})
    check_org_ownership(role, uid, oid)
    org = get_org_or_404(oid)
    return ok(org_view(org))


@bp.route("/orgs/<oid>/revenue-declarations", methods=["POST"])
def create_declaration(oid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner", "PlatformAdmin"})
    check_org_ownership(role, uid, oid)
    org = get_org_or_404(oid)
    if org["org_standing"] == "SUSPENDED" or _is_migrated(oid):
        raise_err(ERR_ORG_SUSPENDED, "Org suspended or migrated")
    b = body()
    period = b.get("period_month")
    if not parse_period(period):
        raise_err(ERR_VALIDATION, "period_month must be YYYY-MM")
    gross = require_non_neg_int(b.get("gross_revenue_cents"), "gross_revenue_cents")
    funding = require_non_neg_int(b.get("funding_received_cents"), "funding_received_cents")
    for d in db.revenue_declarations.values():
        if d["org_id"] == oid and d["period_month"] == period:
            raise_err(ERR_DUPLICATE_PERIOD, "Declaration already filed for this period")
    ent = {
        "id": new_id(),
        "created_at": now_iso(),
        "org_id": oid,
        "period_month": period,
        "gross_revenue_cents": gross,
        "funding_received_cents": funding,
        "declared_at": now_iso(),
    }
    db.revenue_declarations[ent["id"]] = ent
    # Tier determination recompute (actual variant drives effective tier)
    recompute_effective_tier(org)
    # Audit suggestion on annualized breach of current tier ceiling
    figs = tier_determination(org)
    from services_calc import active_tier_config
    cfg = active_tier_config(org["effective_tier_code"])
    if cfg is not None and cfg["revenue_ceiling_cents"] != 0:
        if figs["annualized_revenue_cents"] > cfg["revenue_ceiling_cents"]:
            org["audit_suggestion"] = "REVENUE_CEILING_BREACH"
    compute_standing(org)
    return ok(ent, 201)


@bp.route("/orgs/<oid>/revenue-declarations", methods=["GET"])
def list_declarations(oid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"})
    check_org_ownership(role, uid, oid)
    get_org_or_404(oid)
    items = [d for d in db.revenue_declarations.values() if d["org_id"] == oid]
    items.sort(key=lambda d: (d["period_month"], d["declared_at"]))
    return ok_list(items)


@bp.route("/orgs/<oid>/tier-assessment", methods=["GET"])
def tier_assessment(oid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"})
    check_org_ownership(role, uid, oid)
    org = get_org_or_404(oid)
    figs = tier_determination(org)
    from services_calc import effective_tier_from_variant
    t_actual = effective_tier_from_variant(org, "actual")
    t_annual = effective_tier_from_variant(org, "annualized")
    return ok({
        "org_id": oid,
        "actual_ttm_revenue_cents": figs["actual_ttm_revenue_cents"],
        "annualized_revenue_cents": figs["annualized_revenue_cents"],
        "lifetime_funding_cents": figs["lifetime_funding_cents"],
        "months_declared": figs["months_declared"],
        "tier_by_actual": t_actual,
        "tier_by_annualized": t_annual,
        "effective_tier_code": org["effective_tier_code"],
    })


@bp.route("/orgs/<oid>/ledger", methods=["GET"])
def org_ledger(oid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"})
    check_org_ownership(role, uid, oid)
    org = get_org_or_404(oid)
    invoiced = 0
    paid = 0
    waived = 0
    for inv in db.invoices.values():
        proj = db.projects.get(inv["project_id"])
        if not proj or proj["org_id"] != oid:
            continue
        if inv["assessment_status"] == "VOIDED":
            continue
        invoiced += inv["final_amount_cents"]
        paid += inv["paid_cents"]
        waived += inv["waived_cents"]
    sync_org_balance(org)
    return ok({
        "org_id": oid,
        "invoiced_cents": invoiced,
        "paid_cents": paid,
        "waived_cents": waived,
        "balance_due_cents": org["balance_due_cents"],
    })
