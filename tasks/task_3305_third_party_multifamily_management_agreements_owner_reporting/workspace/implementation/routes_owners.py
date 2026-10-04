"""Routes: Owners, Properties, ManagementAgreements."""

from flask import Blueprint

import calc
from db import db, new_id, now_iso, get_clock
from errors import (
    agreement_not_active,
    invalid_request,
    invalid_state_transition,
    open_claims_block_exit,
    owner_not_active,
    pending_owner_decision,
    stale_version,
)
from middleware import (
    get_or_404,
    opt_int,
    opt_num,
    opt_str,
    req_int,
    req_iso,
    req_num,
    req_str,
    require_roles,
)
from response import body, ok_object, paginate

bp = Blueprint("owners", __name__)

ALL_ROLES = ("PortfolioManager", "PropertyAccountant", "OwnerRep", "RevenueAnalyst", "RiskOfficer")


# ---------- serialization ----------

def owner_out(o):
    return dict(o)


def property_out(p):
    return dict(p)


def agreement_out(a):
    return dict(a)


# ---------- Owners ----------

@bp.post("/mgmt/owners")
def create_owner():
    require_roles("PortfolioManager")
    data = body()
    legal_name = req_str(data, "legal_name")
    dom = opt_int(data, "distribution_day_of_month", 10)
    if dom is None:
        dom = 10
    if not (1 <= dom <= 28):
        raise invalid_request("distribution_day_of_month must be between 1 and 28")
    now = now_iso()
    o = {
        "id": new_id(),
        "legal_name": legal_name,
        "distribution_day_of_month": dom,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.owners[o["id"]] = o
    return ok_object(owner_out(o), status=201)


@bp.get("/mgmt/owners/<ownerId>")
def get_owner(ownerId):
    require_roles(*ALL_ROLES)
    o = get_or_404(db.owners, ownerId)
    return ok_object(owner_out(o))


@bp.get("/mgmt/owners")
def list_owners():
    require_roles(*ALL_ROLES)
    status = opt_str_from_args("status")
    items = sorted(db.owners.values(), key=lambda x: (x["created_at"], x["id"]))
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return paginate([owner_out(o) for o in items])


def opt_str_from_args(name):
    from flask import request
    v = request.args.get(name)
    return v if v is not None else None


# ---------- Properties ----------

@bp.post("/mgmt/owners/<ownerId>/properties")
def create_property(ownerId):
    require_roles("PortfolioManager")
    get_or_404(db.owners, ownerId)
    data = body()
    name = req_str(data, "name")
    unit_count = req_int(data, "unit_count")
    if unit_count < 0:
        raise invalid_request("unit_count must be non-negative")
    now = now_iso()
    p = {
        "id": new_id(),
        "owner_id": ownerId,
        "name": name,
        "unit_count": unit_count,
        "management_posture": "UNMANAGED",
        "disposition_listed_at": None,
        "status": "OPEN",
        "cash_available_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.properties[p["id"]] = p
    return ok_object(property_out(p), status=201)


@bp.get("/mgmt/properties/<propertyId>")
def get_property(propertyId):
    require_roles(*ALL_ROLES)
    p = get_or_404(db.properties, propertyId)
    return ok_object(property_out(p))


@bp.get("/mgmt/properties")
def list_properties():
    require_roles(*ALL_ROLES)
    owner_id = opt_str_from_args("owner_id")
    posture = opt_str_from_args("management_posture")
    items = sorted(db.properties.values(), key=lambda x: (x["created_at"], x["id"]))
    if owner_id is not None:
        items = [p for p in items if p["owner_id"] == owner_id]
    if posture is not None:
        items = [p for p in items if p["management_posture"] == posture]
    return paginate([property_out(p) for p in items])


@bp.post("/mgmt/properties/<propertyId>/list_for_disposition")
def list_for_disposition(propertyId):
    require_roles("OwnerRep")
    p = get_or_404(db.properties, propertyId)
    if p["management_posture"] != "MANAGED":
        raise invalid_state_transition("Property must be MANAGED to list for disposition")
    p["disposition_listed_at"] = now_iso()
    p["updated_at"] = now_iso()
    p["version"] += 1
    return ok_object(property_out(p))


@bp.post("/mgmt/properties/<propertyId>/complete_disposition")
def complete_disposition(propertyId):
    require_roles("OwnerRep")
    p = get_or_404(db.properties, propertyId)
    if p["disposition_listed_at"] is None:
        raise invalid_state_transition("Property is not listed for disposition")
    agmts = [
        a for a in db.agreements.values()
        if a.get("property_id") == p["id"]
        and a["status"] == "TERMINATION_PENDING"
        and a.get("terminated_reason") == "DISPOSITION"
    ]
    if not agmts:
        raise invalid_state_transition(
            "Requires ManagementAgreement in TERMINATION_PENDING with reason DISPOSITION"
        )
    agmt = sorted(agmts, key=lambda a: a["created_at"])[-1]
    now = now_iso()
    p["status"] = "CLOSED"
    p["management_posture"] = "DISPOSED"
    p["updated_at"] = now
    p["version"] += 1
    # Disposition shortcut: agreement TERMINATION_PENDING -> TERMINATED immediately
    agmt["status"] = "TERMINATED"
    agmt["updated_at"] = now
    agmt["version"] += 1
    # Cascade: ASSIGNED_TO_MANAGER vendor contracts -> TERMINATED
    for vc in db.vendor_contracts.values():
        if vc["property_id"] == p["id"] and vc["assignment_status"] == "ASSIGNED_TO_MANAGER":
            vc["assignment_status"] = "TERMINATED"
            vc["updated_at"] = now
            vc["version"] += 1
    return ok_object(property_out(p))


# ---------- Agreements ----------

@bp.post("/mgmt/owners/<ownerId>/agreements")
def create_agreement(ownerId):
    require_roles("PortfolioManager")
    get_or_404(db.owners, ownerId)
    data = body()
    property_id = req_str(data, "property_id")
    get_or_404(db.properties, property_id)
    base_fee_pct = req_num(data, "base_fee_pct")
    minimum_monthly_fee_cents = req_int(data, "minimum_monthly_fee_cents")
    incentive_threshold_egi_cents = req_int(data, "incentive_threshold_egi_cents")
    incentive_tier1_rate = req_num(data, "incentive_tier1_rate")
    noi_hurdle_pct = opt_num(data, "noi_hurdle_pct", 0.08)
    incentive_noi_share_pct = opt_num(data, "incentive_noi_share_pct", 0.20)
    tail_months = opt_int(data, "tail_months", 3)
    tail_rate_pct = opt_num(data, "tail_rate_pct", 0.50)
    effective_date = req_iso(data, "effective_date")
    term_end_date = req_iso(data, "term_end_date")
    if term_end_date <= effective_date:
        raise invalid_request("term_end_date must be after effective_date")
    if minimum_monthly_fee_cents < 0 or incentive_threshold_egi_cents < 0:
        raise invalid_request("fee/threshold amounts must be non-negative")
    now = now_iso()
    a = {
        "id": new_id(),
        "owner_id": ownerId,
        "property_id": property_id,
        "base_fee_pct": base_fee_pct,
        "minimum_monthly_fee_cents": minimum_monthly_fee_cents,
        "incentive_threshold_egi_cents": incentive_threshold_egi_cents,
        "incentive_tier1_rate": incentive_tier1_rate,
        "noi_hurdle_pct": noi_hurdle_pct,
        "incentive_noi_share_pct": incentive_noi_share_pct,
        "tail_months": tail_months,
        "tail_rate_pct": tail_rate_pct,
        "effective_date": data["effective_date"],
        "term_end_date": data["term_end_date"],
        "status": "DRAFT",
        "terminated_reason": None,
        "termination_fee_tail_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.agreements[a["id"]] = a
    return ok_object(agreement_out(a), status=201)


@bp.get("/mgmt/agreements/<agreementId>")
def get_agreement(agreementId):
    require_roles(*ALL_ROLES)
    a = get_or_404(db.agreements, agreementId)
    return ok_object(agreement_out(a))


@bp.get("/mgmt/agreements")
def list_agreements():
    require_roles(*ALL_ROLES)
    owner_id = opt_str_from_args("owner_id")
    property_id = opt_str_from_args("property_id")
    status = opt_str_from_args("status")
    items = sorted(db.agreements.values(), key=lambda x: (x["created_at"], x["id"]))
    if owner_id is not None:
        items = [a for a in items if a["owner_id"] == owner_id]
    if property_id is not None:
        items = [a for a in items if a.get("property_id") == property_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate([agreement_out(a) for a in items])


@bp.post("/mgmt/agreements/<agreementId>/activate")
def activate_agreement(agreementId):
    require_roles("PortfolioManager")
    a = get_or_404(db.agreements, agreementId)
    if a["status"] != "DRAFT":
        raise invalid_state_transition("Agreement must be DRAFT to activate")
    # OCC + owner-active preconditions (per §3.2 ordering)
    owner = db.owners.get(a["owner_id"])
    data = body()
    expected = data.get("expected_agreement_version")
    if owner is None or owner["status"] != "ACTIVE":
        raise owner_not_active()
    if expected is None or expected != a["version"]:
        raise stale_version()
    a["status"] = "ACTIVE"
    a["updated_at"] = now_iso()
    a["version"] += 1
    return ok_object(agreement_out(a))


@bp.post("/mgmt/agreements/<agreementId>/suspend")
def suspend_agreement(agreementId):
    require_roles("PortfolioManager")
    a = get_or_404(db.agreements, agreementId)
    if a["status"] != "ACTIVE":
        raise invalid_state_transition("Agreement must be ACTIVE to suspend")
    # Precondition: no Budget in SUBMITTED for the property
    for b in db.budgets.values():
        if b["property_id"] == a["property_id"] and b["status"] == "SUBMITTED":
            raise pending_owner_decision()
    now = now_iso()
    a["status"] = "SUSPENDED"
    a["updated_at"] = now
    a["version"] += 1
    # Cascade: all ACTIVE StaffPosition rows for the property -> INACTIVE,
    # flag them so resume restores exactly these.
    for s in db.staff.values():
        if s["property_id"] == a["property_id"] and s["status"] == "ACTIVE":
            s["status"] = "INACTIVE"
            s["_inactive_by_suspension"] = True
            s["updated_at"] = now
            s["version"] += 1
    return ok_object(agreement_out(a))


@bp.post("/mgmt/agreements/<agreementId>/resume")
def resume_agreement(agreementId):
    require_roles("PortfolioManager")
    a = get_or_404(db.agreements, agreementId)
    if a["status"] != "SUSPENDED":
        raise invalid_state_transition("Agreement must be SUSPENDED to resume")
    now = now_iso()
    a["status"] = "ACTIVE"
    a["updated_at"] = now
    a["version"] += 1
    for s in db.staff.values():
        if (
            s["property_id"] == a["property_id"]
            and s["status"] == "INACTIVE"
            and s.pop("_inactive_by_suspension", False)
        ):
            s["status"] = "ACTIVE"
            s["updated_at"] = now
            s["version"] += 1
    return ok_object(agreement_out(a))


@bp.post("/mgmt/agreements/<agreementId>/terminate")
def terminate_agreement(agreementId):
    require_roles("OwnerRep")
    a = get_or_404(db.agreements, agreementId)
    if a["status"] != "ACTIVE":
        raise invalid_state_transition("Agreement must be ACTIVE to terminate")
    data = body()
    reason = data.get("terminated_reason")
    if reason is None:
        raise invalid_request("terminated_reason is required")
    if reason not in ("CONVENIENCE", "CAUSE", "DISPOSITION", "EXPIRY"):
        raise invalid_request("terminated_reason must be one of CONVENIENCE|CAUSE|DISPOSITION|EXPIRY")
    prop = db.properties.get(a["property_id"])
    if prop is None or prop["management_posture"] != "MANAGED":
        raise invalid_state_transition("Property must be MANAGED to terminate")
    now = now_iso()
    a["terminated_reason"] = reason
    if reason in ("CONVENIENCE", "DISPOSITION"):
        a["termination_fee_tail_cents"] = calc.fee_tail_cents(a)
    else:
        a["termination_fee_tail_cents"] = 0
    a["status"] = "TERMINATION_PENDING"
    a["updated_at"] = now
    a["version"] += 1
    prop["management_posture"] = "TRANSITIONING_OUT"
    prop["updated_at"] = now
    prop["version"] += 1
    return ok_object(agreement_out(a))


@bp.post("/mgmt/agreements/<agreementId>/complete_termination")
def complete_termination(agreementId):
    require_roles("PortfolioManager")
    a = get_or_404(db.agreements, agreementId)
    if a["status"] != "TERMINATION_PENDING":
        raise invalid_state_transition("Agreement must be TERMINATION_PENDING to complete")
    prop = db.properties.get(a["property_id"])
    pid = a["property_id"]
    # Preconditions per §3.7: onboarding obligations terminal
    for ob in db.onboardings.values():
        if ob["property_id"] == pid and ob["status"] not in ("ACTIVATED", "ABORTED"):
            raise invalid_state_transition("Non-terminal onboarding obligations remain")
    # Open claims block exit
    for c in db.claims.values():
        if c["property_id"] == pid and c["status"] in ("OPEN", "UNDER_REVIEW"):
            raise open_claims_block_exit()
    # Tail invoiced precondition
    tail = a.get("termination_fee_tail_cents", 0)
    if tail > 0:
        invoiced = any(
            e for e in db.ledger.values()
            if e["property_id"] == pid
            and e["status"] == "POSTED"
            and e["kind"] == "EXPENSE"
            and e["amount_cents"] == tail
        )
        if not invoiced:
            raise invalid_state_transition("Termination fee tail has not been invoiced")
    now = now_iso()
    a["status"] = "TERMINATED"
    a["updated_at"] = now
    a["version"] += 1
    if prop is not None:
        if a.get("terminated_reason") == "DISPOSITION" and prop["status"] == "CLOSED":
            prop["management_posture"] = "DISPOSED"
        else:
            prop["management_posture"] = "UNMANAGED"
        prop["updated_at"] = now
        prop["version"] += 1
    for vc in db.vendor_contracts.values():
        if vc["property_id"] == pid and vc["assignment_status"] == "ASSIGNED_TO_MANAGER":
            vc["assignment_status"] = "TERMINATED"
            vc["updated_at"] = now
            vc["version"] += 1
    return ok_object(agreement_out(a))
