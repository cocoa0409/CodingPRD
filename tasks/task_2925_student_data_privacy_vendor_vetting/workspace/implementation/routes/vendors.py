"""Vendor registry, district-wide suspension and reinstatement (PRD 3.1, 3.9)."""
from decimal import Decimal

from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("vendors", __name__)


@bp.post("/vendors")
def register_vendor():
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([
        F("legal_name", "str", lo=1, hi=200, nonblank=True),
        F("hq_country_code", "country"),
        F("breach_notification_hours", "int", lo=1, hi=720),
        F("data_deletion_days", "int", lo=1, hi=3650),
        F("signed_state_addendum", "bool", required=False),
        F("subprocessor_disclosure_complete", "bool", required=False),
    ])
    vendor = store.new_row({
        "legal_name": data["legal_name"],
        "hq_country_code": data["hq_country_code"],
        "breach_notification_hours": data["breach_notification_hours"],
        "data_deletion_days": data["data_deletion_days"],
        "signed_state_addendum": data.get("signed_state_addendum", False),
        "subprocessor_disclosure_complete": data.get("subprocessor_disclosure_complete", False),
        "status": "REGISTERED",
        "risk_score": Decimal("0.00"),
        "reauthorization_risk_score": Decimal("0.00"),
        "open_incident_count": 0,
        "flagged_subprocessor_count": 0,
        "suspended_at": None,
        "privacy_posture": "CLEAR",
    })
    store.vendors[vendor["id"]] = vendor
    # Score and posture are computed immediately, score first (PRD 2.10).
    vendor["risk_score"] = logic.vendor_risk_score(vendor, "live")
    vendor["privacy_posture"] = logic.vendor_privacy_posture(vendor)
    return envelope.created(serialize.vendor(vendor))


@bp.get("/vendors")
def list_vendors():
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst")
    filters = envelope.query_filters({
        "status": set(logic.VENDOR_STATUSES),
        "privacy_posture": set(logic.POSTURES),
    })
    rows = list(store.vendors.values())
    if "status" in filters:
        rows = [r for r in rows if r["status"] == filters["status"]]
    if "privacy_posture" in filters:
        rows = [r for r in rows if r["privacy_posture"] == filters["privacy_posture"]]
    return envelope.paged(store.ordered(rows), serialize.vendor)


@bp.get("/vendors/<vendor_id>")
def read_vendor(vendor_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison", "Teacher")
    return envelope.ok(serialize.vendor(auth.need("vendor", vendor_id)))


@bp.post("/vendors/<vendor_id>/suspend")
def suspend_vendor(vendor_id):
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([F("reason", "str")])
    vendor = auth.need("vendor", vendor_id)
    if vendor["status"] not in ("APPROVED", "CONDITIONAL"):
        raise ApiError("ERR_VENDOR_STATE_INVALID")

    now = store.clock()
    vendor["_pre_suspension_status"] = vendor["status"]
    vendor["_suspension_reason"] = data["reason"]
    vendor["status"] = "SUSPENDED"
    vendor["suspended_at"] = now

    touched_apps = set()
    for entry in logic.vendor_entries(vendor["id"]):
        if entry["status"] in logic.VISIBLE_STATUSES:
            entry["hold_restored_from"] = entry["status"]
            entry["status"] = "SUSPENDED_HOLD"
            store.bump(entry)
            touched_apps.add(entry["application_id"])

    for app_id in touched_apps:
        logic.recompute_application_visibility(store.applications[app_id])

    logic.recompute_vendor(vendor)
    return envelope.ok(serialize.vendor(vendor))


@bp.post("/vendors/<vendor_id>/reinstate")
def reinstate_vendor(vendor_id):
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([F("note", "str", required=False)])
    vendor = auth.need("vendor", vendor_id)
    if vendor["status"] != "SUSPENDED":
        raise ApiError("ERR_VENDOR_STATE_INVALID")

    vendor["status"] = vendor.get("_pre_suspension_status") or "APPROVED"
    vendor["suspended_at"] = None
    if "note" in data:
        vendor["_reinstatement_note"] = data["note"]

    # Posture is re-evaluated first: the held entries come back only when the
    # vendor has actually left FROZEN (PRD 3.9).
    vendor["risk_score"] = logic.vendor_risk_score(vendor, "live")
    posture = logic.vendor_privacy_posture(vendor)
    vendor["privacy_posture"] = posture

    touched_apps = set()
    if posture != "FROZEN":
        now = store.clock()
        for entry in logic.vendor_entries(vendor["id"]):
            if entry["status"] != "SUSPENDED_HOLD":
                continue
            if now < entry["reauthorization_due_at"]:
                entry["status"] = "PUBLISHED"
            elif now < entry["expires_at"]:
                entry["status"] = "EXPIRING_SOON"
            else:
                entry["status"] = "EXPIRED"
            entry["hold_restored_from"] = None
            store.bump(entry)
            touched_apps.add(entry["application_id"])

    for app_id in touched_apps:
        logic.recompute_application_visibility(store.applications[app_id])

    logic.recompute_vendor(vendor)
    return envelope.ok(serialize.vendor(vendor))
