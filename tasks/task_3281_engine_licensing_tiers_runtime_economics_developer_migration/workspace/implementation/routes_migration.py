"""Migration assessment routes with buyout settlement and completion gate."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_MIGRATION_BLOCKED, ERR_FORBIDDEN_ORG,
)
from helpers import (
    ok, ok_list, body, new_common, touch, current_date, iso_date_str,
    parse_date, months_between,
)
from middleware import authenticate, authorize, get_org_or_404, check_org_ownership
from services_calc import (
    SEAT_MONTH_CENTS, org_balance_due, sync_org_balance,
)
from routes_orgs import _is_migrated

bp = Blueprint("migration", __name__)

READ_ROLES = {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"}


@bp.route("/orgs/<oid>/migration-assessments", methods=["POST"])
def create_assessment(oid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    check_org_ownership(role, uid, oid)
    org = get_org_or_404(oid)
    b = body()
    target = b.get("target_engine")
    if not isinstance(target, str) or not target:
        raise_err(ERR_VALIDATION, "target_engine is required")
    ent = new_common()
    ent.update({
        "org_id": oid,
        "target_engine": target,
        "assessment_status": "REQUESTED",
        "buyout_quote_cents": 0,
        "cooling_off_until": None,
    })
    db.migration_assessments[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/orgs/<oid>/migration-assessments", methods=["GET"])
def list_assessments(oid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    check_org_ownership(role, uid, oid)
    get_org_or_404(oid)
    items = [a for a in db.migration_assessments.values() if a["org_id"] == oid]
    items.sort(key=lambda a: a["created_at"])
    st = request.args.get("assessment_status")
    if st:
        items = [a for a in items if a["assessment_status"] == st]
    return ok_list(items)


def _remaining_whole_months(coverage_end, today):
    """Whole calendar months until coverage_end; partial month rounds UP."""
    if coverage_end <= today:
        return 0
    months = (coverage_end.year - today.year) * 12 + (coverage_end.month - today.month)
    if coverage_end.day > today.day:
        months += 1
    elif coverage_end.day == today.day:
        pass
    else:
        # coverage_end day < today day: last partial month already counted? partial rounds up
        pass
    if months < 0:
        months = 0
    # If there is any remainder beyond whole months, round up
    # Compute whole months then check residual
    whole = (coverage_end.year - today.year) * 12 + (coverage_end.month - today.month)
    if coverage_end.day < today.day:
        whole -= 1
    if whole < 0:
        whole = 0
    # anchor = today + whole months
    y = today.year + (today.month - 1 + whole) // 12
    m = (today.month - 1 + whole) % 12 + 1
    import calendar
    d = min(today.day, calendar.monthrange(y, m)[1])
    from datetime import date as _date
    anchor = _date(y, m, d)
    if coverage_end > anchor:
        whole += 1
    return whole


def _compute_buyout(org):
    today = current_date()
    outstanding = org_balance_due(org["id"])
    remainder = 0
    for s in db.seat_subscriptions.values():
        if s["org_id"] != org["id"] or s["subscription_status"] not in ("ACTIVE", "EXHAUSTED"):
            continue
        end = parse_date(s["coverage_end"])
        if end is None or end <= today:
            continue
        months = _remaining_whole_months(end, today)
        remainder += s["purchased_seats"] * SEAT_MONTH_CENTS * months
    created = None
    ts = org.get("created_at")
    if ts:
        # created_at is ISO timestamp
        try:
            created = parse_date(ts[:10])
        except Exception:
            created = None
    tenure = months_between(created, today) if created else 0
    base = outstanding + remainder
    if tenure >= 36:
        fee = 0
    elif tenure >= 12:
        fee = int((Decimal("0.10") * Decimal(base)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        fee = int((Decimal("0.25") * Decimal(base)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return base + fee


@bp.route("/migration-assessments/<aid>/advance", methods=["POST"])
def advance_assessment(aid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    a = db.migration_assessments.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Assessment not found")
    if uid != a["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your assessment")
    b = body()
    target = b.get("target")
    if target not in ("EXPORT_READY", "COOLING_OFF", "COMPLETED", "ABANDONED"):
        raise_err(ERR_VALIDATION, "target invalid")
    current = a["assessment_status"]
    org = get_org_or_404(a["org_id"])

    if target == "ABANDONED":
        if current not in ("REQUESTED", "COOLING_OFF"):
            raise_err(ERR_INVALID_STATE, "Cannot abandon from %s" % current)
        a["assessment_status"] = "ABANDONED"
        touch(a)
        return ok(a)

    if target == "EXPORT_READY":
        if current != "REQUESTED":
            raise_err(ERR_INVALID_STATE, "Must be REQUESTED")
        a["buyout_quote_cents"] = _compute_buyout(org)
        a["assessment_status"] = "EXPORT_READY"
        touch(a)
        return ok(a)

    if target == "COOLING_OFF":
        if current != "EXPORT_READY":
            raise_err(ERR_INVALID_STATE, "Must be EXPORT_READY")
        a["cooling_off_until"] = iso_date_str(current_date() + timedelta(days=14))
        a["assessment_status"] = "COOLING_OFF"
        touch(a)
        return ok(a)

    # COMPLETED
    if current != "COOLING_OFF":
        raise_err(ERR_INVALID_STATE, "Must be COOLING_OFF")
    today = current_date()
    cooling_end = parse_date(a["cooling_off_until"])
    if cooling_end is None or today < cooling_end:
        raise_err(ERR_MIGRATION_BLOCKED, "Cooling-off period has not elapsed")
    # All invoices PAID or WAIVED (voided invoices are excluded from blocking)
    for inv in db.invoices.values():
        proj = db.projects.get(inv["project_id"])
        if not proj or proj["org_id"] != org["id"]:
            continue
        if inv["assessment_status"] == "VOIDED":
            continue
        if inv["payment_status"] not in ("PAID", "WAIVED"):
            raise_err(ERR_MIGRATION_BLOCKED, "Outstanding invoices block migration")
    for c in db.audit_cases.values():
        if c["org_id"] == org["id"] and c["case_status"] in ("OPENED", "EVIDENCE_REQUESTED", "APPEALED"):
            raise_err(ERR_MIGRATION_BLOCKED, "Open audit case blocks migration")
    a["assessment_status"] = "COMPLETED"
    touch(a)
    # Cascades: projects -> ARCHIVED, APPROVED listings -> DELISTED
    for p in db.projects.values():
        if p["org_id"] == org["id"] and p["project_status"] in ("DEVELOPMENT", "SHIPPED", "FROZEN"):
            p["project_status"] = "ARCHIVED"
            touch(p)
    for l in db.asset_listings.values():
        if l["creator_org_id"] == org["id"] and l["listing_status"] == "APPROVED":
            l["listing_status"] = "DELISTED"
            touch(l)
    touch(org)
    return ok(a)
