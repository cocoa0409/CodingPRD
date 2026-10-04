"""Vendor endpoints (PRD 3.7)."""

from flask import Blueprint

from db import db, serialize
from middleware import authenticate, body, enum, require_str
from response import ok
from routes._common import require_vendor

bp = Blueprint("vendors", __name__)

REGIONS = ("NA", "EMEA", "APAC")
EMPLOYEE_BANDS = ("SMB", "MIDMARKET", "ENTERPRISE")


@bp.post("/research/vendors")
def create_vendor():
    authenticate(["PlatformAdmin", "VendorRep"])
    data = body()
    vendor_name = require_str(data, "vendor_name")
    hq_region = enum(require_str(data, "hq_region"), REGIONS, "hq_region")
    employee_count_band = enum(
        require_str(data, "employee_count_band"), EMPLOYEE_BANDS, "employee_count_band"
    )
    vendor_obj = db.create(
        vendor_name=vendor_name,
        hq_region=hq_region,
        employee_count_band=employee_count_band,
        status="ACTIVE",
        active_sales_relationship_count=0,
        briefing_eligible=False,
        last_briefing_at=None,
    )
    db.vendors[vendor_obj["id"]] = vendor_obj
    return ok(serialize(vendor_obj), 201)


@bp.get("/research/vendors/<vendor_id>")
def read_vendor(vendor_id):
    authenticate([
        "PlatformAdmin",
        "ResearchDirector",
        "ComplianceOfficer",
        "VendorRep",
        "Analyst",
    ])
    return ok(serialize(require_vendor(vendor_id)), 200)
