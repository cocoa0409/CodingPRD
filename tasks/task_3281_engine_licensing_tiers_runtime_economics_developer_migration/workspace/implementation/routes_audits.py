"""Audit case routes with conversion cascade and appeals."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_APPEAL_EXHAUSTED,
)
from helpers import (
    ok, ok_list, body, new_common, touch, current_date,
    months_between_period,
)
from middleware import (
    authenticate, authorize, get_org_or_404, check_org_ownership,
    ERR_FORBIDDEN_ORG,
)
from services_calc import (
    TIER_RANK, active_tier_config, compute_standing, compute_runtime_fee,
    tier_determination, sync_org_balance,
)

bp = Blueprint("audits", __name__)

READ_ROLES = {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"}
TRIGGERS = {"REVENUE_CEILING_BREACH", "EDUCATION_ELIGIBILITY", "MANUAL"}
OPEN_STATES = ("OPENED", "EVIDENCE_REQUESTED", "APPEALED")


@bp.route("/orgs/<oid>/audit-cases", methods=["POST"])
def create_case(oid):
    uid, role = authenticate()
    authorize(role, {"Auditor", "PlatformAdmin"})
    get_org_or_404(oid)
    b = body()
    reason = b.get("trigger_reason")
    if reason not in TRIGGERS:
        raise_err(ERR_VALIDATION, "trigger_reason invalid")
    ent = new_common()
    ent.update({
        "org_id": oid,
        "trigger_reason": reason,
        "case_status": "OPENED",
        "resolved_tier_code": None,
        "back_bill_cents": 0,
        "appeal_count": 0,
        "pre_conversion_tier": None,
    })
    db.audit_cases[ent["id"]] = ent
    org = db.orgs[oid]
    compute_standing(org)
    return ok(ent, 201)


@bp.route("/orgs/<oid>/audit-cases", methods=["GET"])
def list_cases(oid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    check_org_ownership(role, uid, oid)
    get_org_or_404(oid)
    items = [c for c in db.audit_cases.values() if c["org_id"] == oid]
    items.sort(key=lambda c: c["created_at"])
    cs = request.args.get("case_status")
    if cs:
        items = [c for c in items if c["case_status"] == cs]
    return ok_list(items)


def _get_case(cid):
    c = db.audit_cases.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, "Audit case not found")
    return c


@bp.route("/audit-cases/<cid>/request-evidence", methods=["POST"])
def request_evidence(cid):
    uid, role = authenticate()
    authorize(role, {"Auditor"})
    c = _get_case(cid)
    if c["case_status"] != "OPENED":
        raise_err(ERR_INVALID_STATE, "Case must be OPENED")
    c["case_status"] = "EVIDENCE_REQUESTED"
    touch(c)
    compute_standing(db.orgs[c["org_id"]])
    return ok(c)


def _conversion_cascade(case, org, new_tier):
    """CONVERT cascade: tier bump, trust -= 15, back-bill, invoice re-rate."""
    old_tier = org["effective_tier_code"]
    case["pre_conversion_tier"] = old_tier
    org["effective_tier_code"] = new_tier
    org["trust_score"] = max(0, org["trust_score"] - 15)
    touch(org)
    # Back-bill computation
    new_cfg = active_tier_config(new_tier)
    old_cfg = active_tier_config(old_tier)
    back_bill = 0
    if new_cfg is not None and old_cfg is not None:
        decls = sorted(
            [d for d in db.revenue_declarations.values() if d["org_id"] == org["id"]],
            key=lambda d: (d["period_month"], d["declared_at"]),
        )
        breach_period = None
        if old_cfg["revenue_ceiling_cents"] != 0:
            for i in range(len(decls)):
                window = decls[:i + 1]
                months = len(set(d["period_month"] for d in window))
                ttm = sum(d["gross_revenue_cents"] for d in window[-12:])
                if months < 12:
                    from decimal import Decimal, ROUND_HALF_UP
                    eff = int((Decimal(ttm) / Decimal(months) * Decimal(12)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if months else 0
                else:
                    eff = ttm
                if eff > old_cfg["revenue_ceiling_cents"]:
                    breach_period = window[-1]["period_month"]
                    break
        if breach_period is not None:
            months_since = months_between_period(breach_period, current_date())
        else:
            months_since = 0
        purchased = sum(
            s["purchased_seats"] for s in db.seat_subscriptions.values()
            if s["org_id"] == org["id"] and s["subscription_status"] in ("ACTIVE", "EXHAUSTED")
        )
        shortfall = max(0, new_cfg["seat_minimum"] - purchased)
        back_bill = shortfall * new_cfg["seat_overage_cents"] * months_since
    case["back_bill_cents"] = back_bill
    # Re-rate open PROVISIONAL invoices under new tier constants
    for inv in db.invoices.values():
        proj = db.projects.get(inv["project_id"])
        if not proj or proj["org_id"] != org["id"]:
            continue
        if inv["assessment_status"] == "PROVISIONAL":
            report = db.install_reports.get(inv["report_id"])
            billable = report["billable_installs"] if report else 0
            amount, _label = compute_runtime_fee(proj, org, billable, "provisional")
            inv["provisional_amount_cents"] = amount
            inv["fee_schedule_label"] = "CONVERTED"
            touch(inv)
    sync_org_balance(org)
    compute_standing(org)


def _reversal_cascade(case, org):
    """CLEAR after APPEALED: restore tier, trust += 15, re-rate CONVERTED invoices back."""
    prior = case.get("pre_conversion_tier")
    if prior:
        org["effective_tier_code"] = prior
    org["trust_score"] = min(100, org["trust_score"] + 15)
    touch(org)
    case["back_bill_cents"] = 0
    for inv in db.invoices.values():
        proj = db.projects.get(inv["project_id"])
        if not proj or proj["org_id"] != org["id"]:
            continue
        if inv["assessment_status"] == "PROVISIONAL" and inv.get("fee_schedule_label") == "CONVERTED":
            report = db.install_reports.get(inv["report_id"])
            billable = report["billable_installs"] if report else 0
            amount, label = compute_runtime_fee(proj, org, billable, "provisional")
            inv["provisional_amount_cents"] = amount
            inv["fee_schedule_label"] = label
            touch(inv)
    sync_org_balance(org)
    compute_standing(org)


@bp.route("/audit-cases/<cid>/resolve", methods=["POST"])
def resolve_case(cid):
    uid, role = authenticate()
    authorize(role, {"Auditor"})
    c = _get_case(cid)
    b = body()
    outcome = b.get("outcome")
    if outcome not in ("CLEAR", "CONVERT"):
        raise_err(ERR_VALIDATION, "outcome must be CLEAR or CONVERT")
    org = get_org_or_404(c["org_id"])
    if c["case_status"] == "EVIDENCE_REQUESTED":
        if outcome == "CLEAR":
            c["case_status"] = "CLEARED"
            touch(c)
            compute_standing(org)
            return ok(c)
        # CONVERT
        resolved = b.get("resolved_tier_code")
        if resolved not in TIER_RANK:
            raise_err(ERR_VALIDATION, "resolved_tier_code invalid")
        if TIER_RANK[resolved] <= TIER_RANK[org["effective_tier_code"]]:
            raise_err(ERR_VALIDATION, "resolved_tier_code must be strictly higher than current effective tier")
        c["case_status"] = "CONVERTED"
        c["resolved_tier_code"] = resolved
        touch(c)
        _conversion_cascade(c, org, resolved)
        return ok(c)
    if c["case_status"] == "APPEALED":
        if outcome == "CLEAR":
            c["case_status"] = "CLEARED"
            touch(c)
            _reversal_cascade(c, org)
            return ok(c)
        # CONVERT: appeal denied, conversion stands
        c["case_status"] = "CONVERTED"
        touch(c)
        return ok(c)
    raise_err(ERR_INVALID_STATE, "Case must be EVIDENCE_REQUESTED or APPEALED to resolve")


@bp.route("/audit-cases/<cid>/appeal", methods=["POST"])
def appeal_case(cid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    c = _get_case(cid)
    if uid != c["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your audit case")
    if c["case_status"] != "CONVERTED" or c.get("appeal_count", 0) >= 2:
        raise_err(ERR_APPEAL_EXHAUSTED, "Appeal not available")
    c["case_status"] = "APPEALED"
    c["appeal_count"] = c.get("appeal_count", 0) + 1
    touch(c)
    compute_standing(db.orgs[c["org_id"]])
    return ok(c)
