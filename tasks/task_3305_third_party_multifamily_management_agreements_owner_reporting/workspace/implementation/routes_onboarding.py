"""Routes: OnboardingTransitions, Residents, VendorContracts."""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import (
    agreement_not_active,
    invalid_request,
    invalid_state_transition,
    no_resident_data,
    vendor_contracts_pending,
)
from middleware import (
    get_or_404,
    opt_int,
    opt_str,
    req_int,
    req_iso,
    req_str,
    require_roles,
)
from response import body, ok_object, paginate

bp = Blueprint("onboarding", __name__)

OB_GET_ROLES = ("PortfolioManager", "PropertyAccountant", "OwnerRep", "RiskOfficer")
VC_GET_ROLES = ("PortfolioManager", "PropertyAccountant", "OwnerRep")


def ob_out(o):
    return dict(o)


def resident_out(r):
    return dict(r)


def vc_out(v):
    return dict(v)


def _arg(name):
    return request.args.get(name)


# ---------- Onboarding ----------

@bp.post("/mgmt/properties/<propertyId>/onboardings")
def create_onboarding(propertyId):
    require_roles("PortfolioManager", "PropertyAccountant")
    prop = get_or_404(db.properties, propertyId)
    data = body()
    prior_manager_name = req_str(data, "prior_manager_name")
    takeover = req_iso(data, "takeover_date")
    deposits = opt_int(data, "deposits_received_cents", 0)
    prepaid = opt_int(data, "prepaid_rent_cents", 0)
    delinquency = opt_int(data, "delinquency_cents", 0)
    for v in (deposits, prepaid, delinquency):
        if v is None or v < 0:
            raise invalid_request("Onboarding amounts must be non-negative")
    now = now_iso()
    o = {
        "id": new_id(),
        "property_id": propertyId,
        "prior_manager_name": prior_manager_name,
        "takeover_date": data["takeover_date"],
        "status": "INTAKE",
        "deposits_received_cents": deposits,
        "prepaid_rent_cents": prepaid,
        "delinquency_cents": delinquency,
        "net_position_cents": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.onboardings[o["id"]] = o
    prop["management_posture"] = "ONBOARDING"
    prop["updated_at"] = now
    prop["version"] += 1
    return ok_object(ob_out(o), status=201)


@bp.get("/mgmt/onboardings/<onboardingId>")
def get_onboarding(onboardingId):
    require_roles(*OB_GET_ROLES)
    o = get_or_404(db.onboardings, onboardingId)
    return ok_object(ob_out(o))


@bp.get("/mgmt/properties/<propertyId>/onboardings")
def list_onboardings_for_property(propertyId):
    require_roles(*OB_GET_ROLES)
    get_or_404(db.properties, propertyId)
    items = sorted(
        (o for o in db.onboardings.values() if o["property_id"] == propertyId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    return paginate([ob_out(o) for o in items])


@bp.get("/mgmt/onboardings")
def list_onboardings():
    require_roles(*OB_GET_ROLES)
    property_id = _arg("property_id")
    status = _arg("status")
    items = sorted(db.onboardings.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [o for o in items if o["property_id"] == property_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return paginate([ob_out(o) for o in items])


@bp.post("/mgmt/onboardings/<onboardingId>/verify_resident_data")
def verify_resident_data(onboardingId):
    require_roles("PropertyAccountant")
    o = get_or_404(db.onboardings, onboardingId)
    if o["status"] != "INTAKE":
        raise invalid_state_transition("Onboarding must be INTAKE to verify resident data")
    has_resident = any(
        r for r in db.residents.values() if r["property_id"] == o["property_id"]
    )
    if not has_resident:
        raise no_resident_data()
    o["status"] = "DATA_VERIFIED"
    o["updated_at"] = now_iso()
    o["version"] += 1
    return ok_object(ob_out(o))


@bp.post("/mgmt/onboardings/<onboardingId>/import_ledger")
def import_ledger(onboardingId):
    require_roles("PropertyAccountant")
    o = get_or_404(db.onboardings, onboardingId)
    if o["status"] != "DATA_VERIFIED":
        raise invalid_state_transition("Onboarding must be DATA_VERIFIED to import ledger")
    data = body()
    deposits = req_int(data, "deposits_received_cents")
    prepaid = req_int(data, "prepaid_rent_cents")
    delinquency = req_int(data, "delinquency_cents")
    for v in (deposits, prepaid, delinquency):
        if v < 0:
            raise invalid_request("Onboarding amounts must be non-negative")
    now = now_iso()
    o["deposits_received_cents"] = deposits
    o["prepaid_rent_cents"] = prepaid
    o["delinquency_cents"] = delinquency
    o["net_position_cents"] = deposits + prepaid - delinquency
    o["status"] = "LEDGER_IMPORTED"
    o["updated_at"] = now
    o["version"] += 1
    # Balancing ledger entries as of takeover_date: deposits/prepaid import as
    # credits (negative), delinquency as charges (positive). EXPENSE-kind-free:
    # use RECOVERY credits for funds received and RENT charges for delinquency.
    takeover_month = o["takeover_date"][:7]
    entries = []
    if deposits:
        entries.append(("RECOVERY", -deposits))
    if prepaid:
        entries.append(("RECOVERY", -prepaid))
    if delinquency:
        entries.append(("RENT", delinquency))
    for kind, amount in entries:
        e = {
            "id": new_id(),
            "property_id": o["property_id"],
            "resident_id": None,
            "kind": kind,
            "amount_cents": amount,
            "accrual_month": takeover_month,
            "collected_month": takeover_month,
            "status": "POSTED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.ledger[e["id"]] = e
        prop = db.properties[o["property_id"]]
        prop["cash_available_cents"] = prop.get("cash_available_cents", 0) - amount
    return ok_object(ob_out(o))


@bp.post("/mgmt/onboardings/<onboardingId>/begin_vendor_review")
def begin_vendor_review(onboardingId):
    require_roles("PropertyAccountant")
    o = get_or_404(db.onboardings, onboardingId)
    if o["status"] != "LEDGER_IMPORTED":
        raise invalid_state_transition("Onboarding must be LEDGER_IMPORTED to begin vendor review")
    o["status"] = "VENDOR_REVIEW"
    o["updated_at"] = now_iso()
    o["version"] += 1
    return ok_object(ob_out(o))


@bp.post("/mgmt/onboardings/<onboardingId>/complete_vendor_review")
def complete_vendor_review(onboardingId):
    require_roles("PropertyAccountant")
    o = get_or_404(db.onboardings, onboardingId)
    if o["status"] != "VENDOR_REVIEW":
        raise invalid_state_transition("Onboarding must be VENDOR_REVIEW to complete vendor review")
    pending = any(
        vc for vc in db.vendor_contracts.values()
        if vc["property_id"] == o["property_id"] and vc["assignment_status"] == "PENDING"
    )
    if pending:
        raise vendor_contracts_pending()
    o["status"] = "READY"
    o["updated_at"] = now_iso()
    o["version"] += 1
    return ok_object(ob_out(o))


@bp.post("/mgmt/onboardings/<onboardingId>/activate")
def activate_onboarding(onboardingId):
    require_roles("PortfolioManager")
    o = get_or_404(db.onboardings, onboardingId)
    if o["status"] != "READY":
        raise invalid_state_transition("Onboarding must be READY to activate")
    agmts = [
        a for a in db.agreements.values()
        if a.get("property_id") == o["property_id"] and a["status"] == "ACTIVE"
    ]
    if not agmts:
        raise agreement_not_active()
    now = now_iso()
    o["status"] = "ACTIVATED"
    o["updated_at"] = now
    o["version"] += 1
    prop = db.properties[o["property_id"]]
    prop["management_posture"] = "MANAGED"
    prop["updated_at"] = now
    prop["version"] += 1
    return ok_object(ob_out(o))


@bp.post("/mgmt/onboardings/<onboardingId>/abort")
def abort_onboarding(onboardingId):
    require_roles("PortfolioManager")
    o = get_or_404(db.onboardings, onboardingId)
    if o["status"] != "INTAKE":
        raise invalid_state_transition("Onboarding can be aborted only from INTAKE")
    now = now_iso()
    o["status"] = "ABORTED"
    o["updated_at"] = now
    o["version"] += 1
    prop = db.properties[o["property_id"]]
    prop["management_posture"] = "UNMANAGED"
    prop["updated_at"] = now
    prop["version"] += 1
    return ok_object(ob_out(o))


# ---------- Residents ----------

@bp.post("/mgmt/properties/<propertyId>/residents")
def create_resident(propertyId):
    require_roles("PropertyAccountant")
    get_or_404(db.properties, propertyId)
    data = body()
    unit_label = req_str(data, "unit_label")
    full_name = req_str(data, "full_name")
    lease_end = req_iso(data, "lease_end_date")
    now = now_iso()
    r = {
        "id": new_id(),
        "property_id": propertyId,
        "unit_label": unit_label,
        "full_name": full_name,
        "lease_end_date": data["lease_end_date"],
        "lease_status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.residents[r["id"]] = r
    return ok_object(resident_out(r), status=201)


@bp.get("/mgmt/residents/<residentId>")
def get_resident(residentId):
    require_roles(*OB_GET_ROLES)
    r = get_or_404(db.residents, residentId)
    return ok_object(resident_out(r))


@bp.get("/mgmt/properties/<propertyId>/residents")
def list_residents_for_property(propertyId):
    require_roles(*OB_GET_ROLES)
    get_or_404(db.properties, propertyId)
    lease_status = _arg("lease_status")
    items = sorted(
        (r for r in db.residents.values() if r["property_id"] == propertyId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    if lease_status is not None:
        items = [r for r in items if r["lease_status"] == lease_status]
    return paginate([resident_out(r) for r in items])


@bp.get("/mgmt/residents")
def list_residents():
    require_roles(*OB_GET_ROLES)
    property_id = _arg("property_id")
    lease_status = _arg("lease_status")
    items = sorted(db.residents.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [r for r in items if r["property_id"] == property_id]
    if lease_status is not None:
        items = [r for r in items if r["lease_status"] == lease_status]
    return paginate([resident_out(r) for r in items])


# ---------- Vendor Contracts ----------

@bp.post("/mgmt/properties/<propertyId>/vendor-contracts")
def create_vendor_contract(propertyId):
    require_roles("PropertyAccountant")
    get_or_404(db.properties, propertyId)
    data = body()
    vendor_name = req_str(data, "vendor_name")
    service_type = req_str(data, "service_type")
    monthly_cost = req_int(data, "monthly_cost_cents")
    if monthly_cost < 0:
        raise invalid_request("monthly_cost_cents must be non-negative")
    start = req_iso(data, "start_date")
    end = req_iso(data, "end_date")
    if start >= end:
        raise invalid_request("start_date must be before end_date")
    now = now_iso()
    v = {
        "id": new_id(),
        "property_id": propertyId,
        "vendor_name": vendor_name,
        "service_type": service_type,
        "monthly_cost_cents": monthly_cost,
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "assignment_status": "PENDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.vendor_contracts[v["id"]] = v
    return ok_object(vc_out(v), status=201)


@bp.get("/mgmt/vendor-contracts/<vendorContractId>")
def get_vendor_contract(vendorContractId):
    require_roles(*VC_GET_ROLES)
    v = get_or_404(db.vendor_contracts, vendorContractId)
    return ok_object(vc_out(v))


@bp.get("/mgmt/properties/<propertyId>/vendor-contracts")
def list_vendor_contracts_for_property(propertyId):
    require_roles(*VC_GET_ROLES)
    get_or_404(db.properties, propertyId)
    status = _arg("assignment_status")
    items = sorted(
        (v for v in db.vendor_contracts.values() if v["property_id"] == propertyId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    if status is not None:
        items = [v for v in items if v["assignment_status"] == status]
    return paginate([vc_out(v) for v in items])


@bp.get("/mgmt/vendor-contracts")
def list_vendor_contracts():
    require_roles(*VC_GET_ROLES)
    property_id = _arg("property_id")
    status = _arg("assignment_status")
    items = sorted(db.vendor_contracts.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [v for v in items if v["property_id"] == property_id]
    if status is not None:
        items = [v for v in items if v["assignment_status"] == status]
    return paginate([vc_out(v) for v in items])


@bp.post("/mgmt/vendor-contracts/<vendorContractId>/resolve")
def resolve_vendor_contract(vendorContractId):
    require_roles("PropertyAccountant")
    v = get_or_404(db.vendor_contracts, vendorContractId)
    if v["assignment_status"] != "PENDING":
        raise invalid_state_transition("Only PENDING contracts can be resolved")
    data = body()
    resolution = data.get("resolution")
    if resolution not in ("ASSUMED", "ASSIGNED_TO_MANAGER", "TERMINATED"):
        raise invalid_request("resolution must be one of ASSUMED|ASSIGNED_TO_MANAGER|TERMINATED")
    v["assignment_status"] = resolution
    v["updated_at"] = now_iso()
    v["version"] += 1
    return ok_object(vc_out(v))
