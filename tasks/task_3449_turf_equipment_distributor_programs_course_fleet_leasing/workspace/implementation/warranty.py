"""Warranty claims: filing gates, adjudication, dispute loop, settlement."""
from flask import Blueprint

import calculations as calc
import clock
import helpers
from helpers import as_int, as_number, as_str, auth, body, fail, ok, req, require_role, identity_entity
import storage
from storage import STORES, new_record, public, sort_created, touch

bp = Blueprint("warranty", __name__)

READ_ROLES = ("CorporateAdmin", "DistributorManager")

_TRANSITIONS = {
    ("SUBMITTED", "UNDER_REVIEW"): "CorporateAdmin",
    ("UNDER_REVIEW", "APPROVED"): "CorporateAdmin",
    ("UNDER_REVIEW", "PARTIAL_APPROVED"): "CorporateAdmin",
    ("UNDER_REVIEW", "DENIED"): "CorporateAdmin",
    ("DENIED", "DISPUTED"): "DistributorManager",
    ("PARTIAL_APPROVED", "DISPUTED"): "DistributorManager",
    ("DISPUTED", "UNDER_REVIEW"): "CorporateAdmin",
    ("APPROVED", "PAID"): "CorporateAdmin",
    ("PARTIAL_APPROVED", "PAID"): "CorporateAdmin",
}


@bp.post("/warranty-claims")
def create_claim():
    role, uid = auth()
    require_role(role, ("DistributorManager",))
    d = identity_entity(role, uid)
    b = body()
    # Reference resolution follows the canonical type order: technician (2nd)
    # resolves before unit (8th).
    technician_id = as_str(req(b, "technician_id"), "technician_id")
    tech = helpers.get_or_404("technicians", technician_id, "technician")
    lease_unit_id = as_str(req(b, "lease_unit_id"), "lease_unit_id")
    unit = helpers.get_or_404("units", lease_unit_id, "lease unit")
    labor_hours = as_number(req(b, "labor_hours"), "labor_hours")
    if not (labor_hours > 0):
        fail("ERR_INVALID_REQUEST", "labor_hours must be greater than 0")
    parts_cost = as_int(req(b, "parts_cost_cents"), "parts_cost_cents")
    if parts_cost < 0:
        fail("ERR_INVALID_REQUEST", "parts_cost_cents must be >= 0")
    if unit["status"] != "IN_SERVICE":
        fail("ERR_INVALID_STATE", "warranty claims may be filed only for an IN_SERVICE unit")
    lease = STORES["leases"][unit["lease_id"]]
    # P9 territory integrity: technician and unit's lease must both belong to
    # the acting distributor.
    if tech["distributor_id"] != uid or lease["distributor_id"] != uid:
        fail("ERR_TERRITORY_MISMATCH", "technician or unit belongs to another distributor")
    # P10 coverage window: unit age from delivered_at within factory_warranty_months.
    model = STORES["models"][unit["model_id"]]
    delivered_dt = clock.parse_iso(unit["delivered_at"])
    if clock.now() > clock.add_months(delivered_dt, model["factory_warranty_months"]):
        fail("ERR_WARRANTY_EXPIRED", "unit age exceeds the factory warranty window")
    # P11 certified technician.
    if tech["cert_status"] != "CERT_ACTIVE":
        fail("ERR_TECHNICIAN_CERT_INVALID", "technician is not CERT_ACTIVE")
    if d["status"] == "TERMINATED":
        fail("ERR_DISTRIBUTOR_NOT_ACTIVE", "terminated distributor is read-only")
    claimed, allowance = calc.claim_labor_pair(labor_hours, d, model)
    rec = new_record("claims", {
        "distributor_id": uid,
        "lease_unit_id": lease_unit_id,
        "technician_id": technician_id,
        "labor_hours": labor_hours,
        "parts_cost_cents": parts_cost,
        "claimed_labor_cents": claimed,
        "factory_allowance_cents": allowance,
        "approved_labor_hours": None,
        "adjudicated_labor_cents": None,
        "parts_reimbursed_cents": None,
        "payable_total_cents": None,
        "paid_at": None,
        "status": "SUBMITTED",
        "_paid_dt": None,
    })
    return ok(public(rec), 201)


@bp.get("/warranty-claims/<cid>")
def get_claim(cid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    c = helpers.get_or_404("claims", cid, "claim")
    return ok(public(c))


@bp.get("/warranty-claims")
def list_claims():
    role, uid = auth()
    require_role(role, READ_ROLES)
    recs = helpers.apply_filters(sort_created(STORES["claims"].values()), {
        "distributor_id": "distributor_id",
        "lease_unit_id": "lease_unit_id",
        "technician_id": "technician_id",
        "status": "status",
    })
    return helpers.paginate(recs)


@bp.post("/warranty-claims/<cid>/transition")
def transition_claim(cid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    if role == "DistributorManager":
        identity_entity(role, uid)
    c = helpers.get_or_404("claims", cid, "claim")
    if role == "DistributorManager" and c["distributor_id"] != uid:
        fail("ERR_FORBIDDEN_OWNERSHIP", "claim belongs to another distributor")
    b = body()
    to = as_str(req(b, "to"), "to")
    expected = as_int(req(b, "expected_claim_version"), "expected_claim_version")
    approved_hours = None
    if to == "PARTIAL_APPROVED":
        approved_hours = as_number(req(b, "approved_labor_hours"), "approved_labor_hours")
        if not (approved_hours > 0 and approved_hours < c["labor_hours"]):
            fail("ERR_INVALID_REQUEST", "approved_labor_hours must be > 0 and < labor_hours")
    key = (c["status"], to)
    if key not in _TRANSITIONS:
        fail("ERR_INVALID_STATE", "claim cannot move from " + c["status"] + " to " + str(to))
    if role != _TRANSITIONS[key]:
        fail("ERR_UNAUTHORIZED", "role " + role + " may not drive claim to " + to)
    # P8: claim optimistic concurrency.
    if expected != c["version"]:
        fail("ERR_STALE_CLAIM_VERSION", "expected_claim_version does not match the claim version")

    if to in ("APPROVED", "PARTIAL_APPROVED"):
        d = STORES["distributors"][c["distributor_id"]]
        unit = STORES["units"][c["lease_unit_id"]]
        model = STORES["models"][unit["model_id"]]
        effective = c["labor_hours"] if to == "APPROVED" else approved_hours
        result = calc.warranty_adjudication(c, d, model, effective)
        c["approved_labor_hours"] = approved_hours if to == "PARTIAL_APPROVED" else None
        c["adjudicated_labor_cents"] = result["adjudicated_labor_cents"]
        c["parts_reimbursed_cents"] = result["parts_reimbursed_cents"]
        c["payable_total_cents"] = result["payable_total_cents"]

    elif to == "PAID":
        d = STORES["distributors"][c["distributor_id"]]
        # P13 fiscal ceiling: calendar-year paid total plus this payable must
        # not exceed the distributor's annual claim cap.
        if calc.claims_paid_ytd(d["id"]) + c["payable_total_cents"] > d["annual_claim_cap_cents"]:
            fail("ERR_CLAIM_CAP_EXCEEDED", "payment would exceed the annual claim cap")
        c["paid_at"] = clock.stamp()
        c["_paid_dt"] = clock.now()
        d["service_credit_balance_cents"] += c["payable_total_cents"]

    c["status"] = to
    touch(c)
    return ok(public(c))
