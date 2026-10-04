"""Office routes: create, get, list, close; retention report compute/list; reconcile."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from store import db
from response import ok, ok_list, ApiError, err_not_found, err_invalid_request
from helpers import new_record, touch, paginate, sort_by_created, recompute_trust, reevaluate, valid_month, first_of_month, next_month_start
from clock import now, fmt, parse
from calculations import rhu_div
import views

bp = Blueprint("offices", __name__)


def get_office_or_404(office_id):
    o = db["offices"].get(office_id)
    if not o:
        raise err_not_found("Office not found")
    return o


@bp.route("/offices", methods=["POST"])
def create_office():
    require_roles("FranchiseeOwner")
    body = request.get_json(silent=True) or {}
    name = body.get("office_name")
    market = body.get("market_code")
    target = body.get("recruiting_target_agents")
    if not isinstance(name, str) or not name:
        raise err_invalid_request("office_name is required")
    if not isinstance(market, str) or not market:
        raise err_invalid_request("market_code is required")
    if not isinstance(target, int) or isinstance(target, bool) or target < 1:
        raise err_invalid_request("recruiting_target_agents must be >= 1")
    rec = new_record()
    rec.update({
        "office_name": name,
        "market_code": market,
        "status": "ACTIVE",
        "recruiting_target_agents": target,
        "active_agent_count": 0,
        "trust_balance_cents": 0,
        "closed_at": None,
    })
    db["offices"][rec["id"]] = rec
    return ok(views.office_view(rec), 201)


@bp.route("/offices/<officeId>", methods=["GET"])
def get_office(officeId):
    require_roles(*ALL_ROLES)
    reevaluate()
    o = get_office_or_404(officeId)
    recompute_trust(o)
    return ok(views.office_view(o))


@bp.route("/offices", methods=["GET"])
def list_offices():
    require_roles("FranchiseeOwner", "BrokerOfRecord", "ManagingBroker",
                  "TrustAccountant", "ComplianceAuditor", "PlatformAdmin")
    reevaluate()
    items = list(db["offices"].values())
    args = request.args
    if args.get("market_code") is not None:
        items = [o for o in items if o["market_code"] == args.get("market_code")]
    if args.get("status") is not None:
        items = [o for o in items if o["status"] == args.get("status")]
    if args.get("office_id") is not None:
        items = [o for o in items if o["id"] == args.get("office_id")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.office_view(o) for o in page], total, limit, offset)


@bp.route("/offices/<officeId>/close", methods=["POST"])
def close_office(officeId):
    require_roles("FranchiseeOwner")
    o = get_office_or_404(officeId)
    if o["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Office already closed")
    active = [a for a in db["agents"].values() if a["office_id"] == o["id"] and a["status"] == "ACTIVE"]
    if active:
        raise ApiError("ERR_OFFICE_NOT_EMPTY", 409, "Office still has ACTIVE agents")
    n = now()
    o["status"] = "CLOSED"
    o["closed_at"] = fmt(n)
    # cascade: TERMINATION_PENDING agents -> TERMINATED
    for a in db["agents"].values():
        if a["office_id"] == o["id"] and a["status"] == "TERMINATION_PENDING":
            a["status"] = "TERMINATED"
            a["terminated_at"] = fmt(n)
            touch(a)
    # cascade: open invoices -> COLLECTIONS
    for inv in db["invoices"].values():
        if inv["office_id"] == o["id"] and inv["status"] in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
            inv["status"] = "COLLECTIONS"
            touch(inv)
    o["active_agent_count"] = sum(
        1 for a in db["agents"].values() if a["office_id"] == o["id"] and a["status"] == "ACTIVE"
    )
    touch(o)
    recompute_trust(o)
    return ok(views.office_view(o))


# ---------------------------------------------------------------------------
# Retention reports
# ---------------------------------------------------------------------------

def _compute_report(office, period_month, variant):
    ms = first_of_month(period_month)
    nms = next_month_start(period_month)
    agents = [a for a in db["agents"].values() if a["office_id"] == office["id"]]

    def onboarded(a):
        v = a.get("onboarded_at")
        return parse(v) if v else None

    def terminated(a):
        v = a.get("terminated_at")
        return parse(v) if v else None

    if variant == "COHORT":
        cohort = [a for a in agents if (ob := onboarded(a)) is not None and ms <= ob < nms]
        headcount_start = len(cohort)
        headcount_end = sum(1 for a in cohort if (t := terminated(a)) is None or t >= nms)
    else:
        headcount_start = sum(
            1 for a in agents
            if (ob := onboarded(a)) is not None and ob < ms
            and ((t := terminated(a)) is None or t >= ms)
        )
        headcount_end = sum(
            1 for a in agents
            if (ob := onboarded(a)) is not None and ob < nms
            and ((t := terminated(a)) is None or t >= nms)
        )
    if headcount_start == 0:
        raise ApiError("ERR_NO_RETENTION_BASELINE", 422, "No retention baseline for period")
    retention_bps = rhu_div(headcount_end * 10000, headcount_start)
    churned = headcount_start - headcount_end
    return headcount_start, headcount_end, retention_bps, churned


@bp.route("/offices/<officeId>/retention-reports/compute", methods=["POST"])
def compute_retention(officeId):
    require_roles("FranchiseeOwner", "BrokerOfRecord")
    o = get_office_or_404(officeId)
    body = request.get_json(silent=True) or {}
    period_month = body.get("period_month")
    if not valid_month(period_month):
        raise err_invalid_request("period_month must be YYYY-MM")
    variant = body.get("report_variant", "CHURN")
    if variant not in ("CHURN", "COHORT"):
        raise err_invalid_request("report_variant must be CHURN or COHORT")
    # archive prior COMPUTED reports for same office+period
    for r in db["reports"].values():
        if r["office_id"] == o["id"] and r["period_month"] == period_month and r["status"] == "COMPUTED":
            r["status"] = "ARCHIVED"
            touch(r)
    hs, he, rbps, churned = _compute_report(o, period_month, variant)
    rec = new_record()
    rec.update({
        "office_id": o["id"],
        "period_month": period_month,
        "headcount_start": hs,
        "headcount_end": he,
        "retention_bps": rbps,
        "churned_agent_count": churned,
        "report_variant": variant,
        "status": "COMPUTED",
    })
    db["reports"][rec["id"]] = rec
    return ok(views.report_view(rec), 201)


@bp.route("/offices/<officeId>/retention-reports", methods=["GET"])
def list_office_reports(officeId):
    require_roles("FranchiseeOwner", "BrokerOfRecord", "ManagingBroker",
                  "TrustAccountant", "ComplianceAuditor", "PlatformAdmin")
    get_office_or_404(officeId)
    items = [r for r in db["reports"].values() if r["office_id"] == officeId]
    args = request.args
    if args.get("period_month") is not None:
        items = [r for r in items if r["period_month"] == args.get("period_month")]
    if args.get("status") is not None:
        items = [r for r in items if r["status"] == args.get("status")]
    if args.get("office_id") is not None:
        items = [r for r in items if r["office_id"] == args.get("office_id")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.report_view(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

@bp.route("/offices/<officeId>/reconcile", methods=["POST"])
def reconcile_office(officeId):
    require_roles("TrustAccountant")
    o = get_office_or_404(officeId)
    for e in db["entries"].values():
        if e["office_id"] != o["id"]:
            continue
        if e["status"] in ("AGENT_PAYABLE", "REFERRAL_PAYABLE"):
            e["status"] = "DISBURSED"
            touch(e)
        elif e["status"] == "OFFICE_FEE_ACCRUED":
            e["status"] = "RECONCILED"
            touch(e)
    touch(o)
    recompute_trust(o)
    return ok(views.office_view(o))
