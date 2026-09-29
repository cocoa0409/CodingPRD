"""Vendor applications and the district integration attestation (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("applications", __name__)


@bp.post("/applications")
def register_application():
    auth.actor("PrivacyOfficeAdmin", "VendorLiaison")
    data = validate.body([
        F("vendor_id", "str"),
        F("name", "str", lo=1, hi=200, nonblank=True),
        F("category", "enum", members=set(logic.APPLICATION_CATEGORIES)),
        F("grade_band_low", "int", lo=0, hi=12),
        F("grade_band_high", "int", lo=0, hi=12),
        F("sso_protocol", "enum", members=set(logic.SSO_PROTOCOLS)),
        F("accessibility_conformance_level", "enum", members=set(logic.ACCESSIBILITY_LEVELS)),
        F("vpat_on_file", "bool", required=False),
    ])
    validate.grade_band(data, "grade_band_low", "grade_band_high")
    vendor = auth.need("vendor", data["vendor_id"])

    row = store.new_row({
        "vendor_id": vendor["id"],
        "name": data["name"],
        "category": data["category"],
        "grade_band_low": data["grade_band_low"],
        "grade_band_high": data["grade_band_high"],
        "sso_protocol": data["sso_protocol"],
        "sso_verified": False,
        "accessibility_conformance_level": data["accessibility_conformance_level"],
        "vpat_on_file": data.get("vpat_on_file", False),
        "status": "CANDIDATE",
        "catalog_visibility": "HIDDEN",
        # Fixed once from the category and never recomputed (PRD 3.1).
        "max_permitted_tier": logic.application_max_permitted_tier(data["category"]),
        "exposed_sensitivity_points": Decimal("0.00"),
    })
    store.applications[row["id"]] = row
    return envelope.created(serialize.application(row))


@bp.get("/applications")
def list_applications():
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison", "Teacher")
    filters = envelope.query_filters({
        "vendor_id": None,
        "status": set(logic.APPLICATION_STATUSES),
        "category": set(logic.APPLICATION_CATEGORIES),
        "catalog_visibility": set(logic.VISIBILITIES),
    })
    rows = list(store.applications.values())
    for key in ("vendor_id", "status", "category", "catalog_visibility"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    return envelope.paged(store.ordered(rows), serialize.application)


@bp.get("/applications/<application_id>")
def read_application(application_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison", "Teacher")
    return envelope.ok(serialize.application(auth.need("application", application_id)))


@bp.post("/applications/<application_id>/attest-integration")
def attest_integration(application_id):
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([
        F("sso_verified", "bool"),
        F("accessibility_conformance_level", "enum", required=False,
          members=set(logic.ACCESSIBILITY_LEVELS)),
        F("vpat_on_file", "bool", required=False),
    ])
    row = auth.need("application", application_id)
    # Rung 20: only a BLOCKED application refuses to re-attest (PRD 3.1).
    if row["status"] == "BLOCKED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")

    row["sso_verified"] = data["sso_verified"]
    if "accessibility_conformance_level" in data:
        row["accessibility_conformance_level"] = data["accessibility_conformance_level"]
    if "vpat_on_file" in data:
        row["vpat_on_file"] = data["vpat_on_file"]
    # Every attestation advances the version, stale-token bait for reauthorization.
    store.bump(row)
    return envelope.ok(serialize.application(row))
