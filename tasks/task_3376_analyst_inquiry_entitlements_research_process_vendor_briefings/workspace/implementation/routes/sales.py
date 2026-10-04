"""SalesRelationship endpoints and the separation register (PRD 3.8)."""

from flask import Blueprint, request

from db import db, serialize
from errors import ApiError, bad_request, invalid_state
from middleware import authenticate, body, enum, optional_str, require_str
from response import ok, ok_list
from services import state
from routes._common import page_of, require_analyst, require_relationship, require_vendor

bp = Blueprint("sales", __name__)

RELATIONSHIP_TYPES = ("SPONSORSHIP", "PAID_ADVISORY", "SPEAKING_FEE")


@bp.post("/research/sales-relationships")
def create_relationship():
    authenticate(["SalesRep", "ComplianceOfficer"])
    data = body()
    analyst_id = require_str(data, "analyst_id")
    vendor_id = require_str(data, "vendor_id")
    relationship_type = enum(
        require_str(data, "relationship_type"), RELATIONSHIP_TYPES, "relationship_type"
    )
    annual_value = data.get("annual_value_cents")
    if isinstance(annual_value, bool) or not isinstance(annual_value, int):
        raise bad_request("annual_value_cents must be an integer.")
    if annual_value < 0:
        raise bad_request("annual_value_cents must be at least 0.")
    expected_version = data.get("expected_analyst_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise bad_request("expected_analyst_version must be an integer.")

    analyst_obj = require_analyst(analyst_id)
    require_vendor(vendor_id)

    if expected_version != analyst_obj.get("version"):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_analyst_version does not match the analyst's current version.",
            412,
        )

    relationship = db.create(
        analyst_id=analyst_id,
        vendor_id=vendor_id,
        relationship_type=relationship_type,
        annual_value_cents=annual_value,
        status="ACTIVE",
        started_at=db.now(),
        terminated_at=None,
    )
    db.sales_relationships[relationship["id"]] = relationship
    state.apply_sales_relationship_cascade(relationship)
    return ok(serialize(relationship), 201)


@bp.get("/research/sales-relationships/<relationship_id>")
def read_relationship(relationship_id):
    authenticate(["ComplianceOfficer", "ResearchDirector", "PlatformAdmin", "SalesRep"])
    return ok(serialize(require_relationship(relationship_id)), 200)


@bp.get("/research/sales-relationships")
def list_relationships():
    authenticate(["ComplianceOfficer", "ResearchDirector", "PlatformAdmin", "SalesRep"])
    items = list(db.sales_relationships.values())
    analyst_id = request.args.get("analyst_id")
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    if analyst_id:
        items = [r for r in items if r.get("analyst_id") == analyst_id]
    if vendor_id:
        items = [r for r in items if r.get("vendor_id") == vendor_id]
    if status:
        items = [r for r in items if r.get("status") == status]
    page, limit, offset, total = page_of(items)
    return ok_list(page, limit, offset, total)


@bp.post("/research/sales-relationships/<relationship_id>/terminate")
def terminate_relationship(relationship_id):
    authenticate(["ComplianceOfficer", "SalesRep"])
    data = body()
    optional_str(data, "termination_reason", "")
    relationship = require_relationship(relationship_id)

    if relationship.get("status") != "ACTIVE":
        raise invalid_state("Only an ACTIVE relationship can be terminated.")

    relationship["status"] = "TERMINATED"
    relationship["terminated_at"] = db.now()
    db.touch(relationship)

    analyst_obj = db.analysts.get(relationship.get("analyst_id"))
    if analyst_obj is not None:
        conflicted = list(analyst_obj.get("conflicted_vendor_ids") or [])
        if relationship.get("vendor_id") in conflicted:
            conflicted.remove(relationship.get("vendor_id"))
        analyst_obj["conflicted_vendor_ids"] = conflicted
        analyst_obj["integrity_flag"] = state.integrity_flag_for(len(conflicted))
        db.touch(analyst_obj)

    vendor_obj = db.vendors.get(relationship.get("vendor_id"))
    if vendor_obj is not None:
        vendor_obj["active_sales_relationship_count"] = max(
            0, vendor_obj.get("active_sales_relationship_count", 0) - 1
        )
        state.recompute_vendor_eligibility(vendor_obj)
        db.touch(vendor_obj)
    return ok(serialize(relationship), 200)
