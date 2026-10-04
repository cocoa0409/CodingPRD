"""ResellerOrders and ComplianceAudits routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_invalid_request,
    err_not_found,
    err_reference_not_found,
    err_invalid_state,
    err_no_reseller,
    err_reseller_suspended,
    err_identity_mismatch,
    err_seat_capacity,
)
from helpers import (
    make_record,
    touch,
    require_fields,
    require_enum,
    require_int,
    refresh_org,
    org_over_allocated,
    RESELLER_DISCOUNT,
    TIER_PRIORITY,
)
from middleware import get_identity, require_role, resolve_identity, require_org_scope
from response import success_object, success_list, paginate

bp = Blueprint("orders_audits", __name__)


# ---------------- reseller orders ----------------

@bp.post("/licensing/reseller-orders")
def create_reseller_order():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["org_id", "plan_id", "seats", "region"])
    org = db["organizations"].get(payload["org_id"])
    if org is None:
        raise err_reference_not_found("org_id does not exist")
    require_org_scope(identity, org["id"])
    plan = db["plans"].get(payload["plan_id"])
    if plan is None:
        raise err_reference_not_found("plan_id does not exist")
    seats = require_int(payload, "seats", minimum=1)
    require_enum(payload, "region", {"NA", "EMEA", "APAC", "LATAM"})
    if plan["seat_limit"] != -1 and seats > plan["seat_limit"]:
        raise err_seat_capacity("seats exceed plan seat_limit")
    candidates = [
        r for r in db["resellers"].values()
        if r["status"] == "ACTIVE" and r["region"] == payload["region"]
    ]
    if not candidates:
        raise err_no_reseller()
    open_counts = {r["id"]: 0 for r in candidates}
    for order in db["reseller_orders"].values():
        if order["status"] == "ROUTED" and order.get("reseller_id") in open_counts:
            open_counts[order["reseller_id"]] += 1
    candidates.sort(key=lambda r: r["created_at"])
    candidates.sort(key=lambda r: open_counts[r["id"]])
    candidates.sort(key=lambda r: -TIER_PRIORITY[r["tier"]])
    winner = candidates[0]
    rec = make_record({
        "reseller_id": winner["id"],
        "org_id": org["id"],
        "plan_id": plan["id"],
        "seats": seats,
        "region": payload["region"],
        "status": "ROUTED",
        "discount_pct": RESELLER_DISCOUNT[winner["tier"]],
    })
    db["reseller_orders"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/reseller-orders")
def list_reseller_orders():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "ResellerAgent", "OrgAdmin"])
    resolve_identity(identity)
    items = list(db["reseller_orders"].values())
    if identity.role == "ResellerAgent":
        items = [o for o in items if o.get("reseller_id") == identity.user_id]
    elif identity.role == "OrgAdmin" and identity.admin:
        items = [o for o in items if o["org_id"] == identity.admin["org_id"]]
    for key in ("reseller_id", "org_id", "plan_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [o for o in items if str(o.get(key)) == v]
    items.sort(key=lambda o: o["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/reseller-orders/<oid>")
def get_reseller_order(oid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "ResellerAgent", "OrgAdmin"])
    resolve_identity(identity)
    order = db["reseller_orders"].get(oid)
    if order is None:
        raise err_not_found("ResellerOrder not found")
    if identity.role == "ResellerAgent" and order.get("reseller_id") != identity.user_id:
        raise err_identity_mismatch("Order not routed to caller's reseller")
    if identity.role == "OrgAdmin":
        require_org_scope(identity, order["org_id"])
    return success_object(order)


@bp.post("/licensing/reseller-orders/<oid>/fulfill")
def fulfill_reseller_order(oid):
    identity = get_identity()
    require_role(identity, ["ResellerAgent"])
    resolve_identity(identity)
    order = db["reseller_orders"].get(oid)
    if order is None:
        raise err_not_found("ResellerOrder not found")
    if order.get("reseller_id") != identity.user_id:
        raise err_identity_mismatch("Order not routed to caller's reseller")
    if order["status"] != "ROUTED":
        raise err_invalid_state("Order is not ROUTED")
    reseller = db["resellers"].get(order["reseller_id"])
    if reseller is None or reseller["status"] != "ACTIVE":
        raise err_reseller_suspended()
    org = db["organizations"].get(order["org_id"])
    if org is None or org["status"] != "ACTIVE":
        raise err_invalid_state("Organization is not ACTIVE")
    order["status"] = "FULFILLED"
    touch(order)
    sub = make_record({
        "org_id": order["org_id"],
        "plan_id": order["plan_id"],
        "reseller_id": order["reseller_id"],
        "status": "PENDING_PAYMENT",
        "seats_purchased": order["seats"],
        "seats_assigned": 0,
        "commitment_start": None,
        "commitment_months": 0,
        "months_elapsed": 0,
        "monthly_charge_cents": 0,
    })
    db["subscriptions"][sub["id"]] = sub
    return success_object(order)


@bp.post("/licensing/reseller-orders/<oid>/reject")
def reject_reseller_order(oid):
    identity = get_identity()
    require_role(identity, ["ResellerAgent"])
    resolve_identity(identity)
    order = db["reseller_orders"].get(oid)
    if order is None:
        raise err_not_found("ResellerOrder not found")
    if order.get("reseller_id") != identity.user_id:
        raise err_identity_mismatch("Order not routed to caller's reseller")
    if order["status"] != "ROUTED":
        raise err_invalid_state("Order is not ROUTED")
    order["status"] = "REJECTED"
    touch(order)
    return success_object(order)


@bp.post("/licensing/reseller-orders/<oid>/cancel")
def cancel_reseller_order(oid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    order = db["reseller_orders"].get(oid)
    if order is None:
        raise err_not_found("ResellerOrder not found")
    if order["status"] != "ROUTED":
        raise err_invalid_state("Order is not ROUTED")
    order["status"] = "CANCELLED"
    touch(order)
    return success_object(order)


# ---------------- compliance audits ----------------

@bp.post("/licensing/compliance-audits")
def create_audit():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["org_id", "opened_by_admin_id"])
    org = db["organizations"].get(payload["org_id"])
    if org is None:
        raise err_reference_not_found("org_id does not exist")
    if payload["opened_by_admin_id"] not in db["admins"]:
        raise err_reference_not_found("opened_by_admin_id does not exist")
    rec = make_record({
        "org_id": org["id"],
        "opened_by_admin_id": payload["opened_by_admin_id"],
        "status": "OPEN",
        "over_allocated_seats": org_over_allocated(org["id"]),
        "findings_count": 0,
    })
    db["compliance_audits"][rec["id"]] = rec
    refresh_org(org["id"])
    return success_object(rec, 201)


@bp.get("/licensing/compliance-audits")
def list_audits():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    items = list(db["compliance_audits"].values())
    if identity.role == "OrgAdmin" and identity.admin:
        items = [a for a in items if a["org_id"] == identity.admin["org_id"]]
    for key in ("org_id", "opened_by_admin_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if str(a.get(key)) == v]
    items.sort(key=lambda a: a["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/compliance-audits/<aid>")
def get_audit(aid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    audit = db["compliance_audits"].get(aid)
    if audit is None:
        raise err_not_found("ComplianceAudit not found")
    require_org_scope(identity, audit["org_id"])
    return success_object(audit)


@bp.post("/licensing/compliance-audits/<aid>/raise-findings")
def raise_findings(aid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    audit = db["compliance_audits"].get(aid)
    if audit is None:
        raise err_not_found("ComplianceAudit not found")
    payload = request.get_json(silent=True)
    require_fields(payload, ["findings_count"])
    findings = require_int(payload, "findings_count", minimum=0)
    if audit["status"] != "OPEN":
        raise err_invalid_state("Audit is not OPEN")
    audit["over_allocated_seats"] = org_over_allocated(audit["org_id"])
    audit["findings_count"] = findings
    if audit["over_allocated_seats"] <= 0 and findings <= 0:
        raise err_invalid_state("No findings to raise")
    audit["status"] = "FINDINGS_RAISED"
    touch(audit)
    refresh_org(audit["org_id"])
    return success_object(audit)


@bp.post("/licensing/compliance-audits/<aid>/remediate")
def remediate_audit(aid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    audit = db["compliance_audits"].get(aid)
    if audit is None:
        raise err_not_found("ComplianceAudit not found")
    if audit["status"] != "FINDINGS_RAISED":
        raise err_invalid_state("Audit is not FINDINGS_RAISED")
    for sub in db["subscriptions"].values():
        if sub["org_id"] == audit["org_id"] and sub["seats_assigned"] > sub["seats_purchased"]:
            raise err_invalid_state("Over-allocation not resolved")
    audit["status"] = "REMEDIATED"
    audit["over_allocated_seats"] = org_over_allocated(audit["org_id"])
    touch(audit)
    refresh_org(audit["org_id"])
    return success_object(audit)


@bp.post("/licensing/compliance-audits/<aid>/close")
def close_audit(aid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    audit = db["compliance_audits"].get(aid)
    if audit is None:
        raise err_not_found("ComplianceAudit not found")
    if audit["status"] == "OPEN":
        if audit["findings_count"] != 0:
            raise err_invalid_state("Cannot close OPEN audit with findings")
    elif audit["status"] == "REMEDIATED":
        pass
    else:
        raise err_invalid_state("Audit cannot be closed from current state")
    audit["status"] = "CLOSED"
    touch(audit)
    refresh_org(audit["org_id"])
    return success_object(audit)
