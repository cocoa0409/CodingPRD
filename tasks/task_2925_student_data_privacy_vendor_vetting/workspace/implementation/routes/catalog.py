"""The district catalog: publication, sweep, reauthorization and revocation (PRD 3.7)."""
from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("catalog", __name__)


@bp.post("/catalog-entries")
def publish_entry():
    user_id, role = auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst")
    data = validate.body([
        F("application_id", "str"),
        F("review_id", "str"),
        F("effective_from", "instant"),
        F("expires_at", "instant"),
        F("authorized_grade_band_low", "int", lo=0, hi=12),
        F("authorized_grade_band_high", "int", lo=0, hi=12),
    ])
    validate.grade_band(data, "authorized_grade_band_low", "authorized_grade_band_high")
    if data["expires_at"] <= data["effective_from"]:
        validate.bad("expires_at must be strictly after effective_from.")

    application = auth.need("application", data["application_id"])
    review = auth.need("review", data["review_id"])
    vendor = store.vendors[application["vendor_id"]]

    # Rung 7: the analyst who decided a review does not also publish it.
    if role == "PrivacyAnalyst":
        auth.sod_or_403(user_id != review["decided_by_analyst_id"])

    if vendor["privacy_posture"] == "FROZEN":
        raise ApiError("ERR_VENDOR_POSTURE_FROZEN")
    if vendor["privacy_posture"] not in ("CLEAR", "WATCH"):
        raise ApiError("ERR_VENDOR_POSTURE_BLOCKS_PUBLICATION")
    if not vendor["subprocessor_disclosure_complete"]:
        raise ApiError("ERR_SUBPROCESSOR_DISCLOSURE_INCOMPLETE")
    if (review["status"] not in ("CLEARED", "CONDITIONAL")
            or review["application_id"] != application["id"]):
        raise ApiError("ERR_REVIEW_NOT_CLEARED")
    if logic.window_overlap(application["id"], data["effective_from"], data["expires_at"]):
        raise ApiError("ERR_AUTHORIZATION_WINDOW_OVERLAP")
    if not (application["accessibility_conformance_level"] in ("WCAG21_AA", "WCAG21_AAA")
            and application["vpat_on_file"]):
        raise ApiError("ERR_ACCESSIBILITY_CONFORMANCE_INSUFFICIENT")
    if application["sso_protocol"] == "NONE" or not application["sso_verified"]:
        raise ApiError("ERR_SSO_NOT_VERIFIED")
    if (data["authorized_grade_band_low"] < application["grade_band_low"]
            or data["authorized_grade_band_high"] > application["grade_band_high"]):
        raise ApiError("ERR_GRADE_BAND_OUT_OF_SCOPE")

    row = store.new_row({
        "application_id": application["id"],
        "review_id": review["id"],
        "predecessor_entry_id": None,
        "effective_from": data["effective_from"],
        "expires_at": data["expires_at"],
        "authorized_grade_band_low": data["authorized_grade_band_low"],
        "authorized_grade_band_high": data["authorized_grade_band_high"],
        "reauthorization_due_at": logic.reauthorization_due_at(data["expires_at"]),
        # Snapshot taken at publication and never refreshed (PRD 3.7).
        "published_review_score": review["final_compliance_score"],
        "status": "PUBLISHED",
        "revoked_reason": None,
        "hold_restored_from": None,
    })
    store.catalog_entries[row["id"]] = row
    logic.recompute_application_visibility(application)
    return envelope.created(serialize.catalog_entry(row))


@bp.get("/catalog-entries")
def list_entries():
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison", "Teacher")
    filters = envelope.query_filters({
        "application_id": None,
        "review_id": None,
        "predecessor_entry_id": None,
        "status": set(logic.CATALOG_STATUSES),
    })
    rows = list(store.catalog_entries.values())
    for key in ("application_id", "review_id", "predecessor_entry_id", "status"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    return envelope.paged(store.ordered(rows), serialize.catalog_entry)


@bp.get("/catalog-entries/<entry_id>")
def read_entry(entry_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison", "Teacher")
    return envelope.ok(serialize.catalog_entry(auth.need("entry", entry_id)))


@bp.post("/catalog-entries/<entry_id>/revoke")
def revoke_entry(entry_id):
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([F("revoked_reason", "str")])
    row = auth.need("entry", entry_id)
    if row["status"] not in logic.ACTIVE_WINDOW_STATUSES:
        raise ApiError("ERR_CATALOG_ENTRY_NOT_ACTIVE")

    row["status"] = "REVOKED"
    row["revoked_reason"] = data["revoked_reason"]
    row["hold_restored_from"] = None
    store.bump(row)
    logic.recompute_application_visibility(store.applications[row["application_id"]])
    return envelope.ok(serialize.catalog_entry(row))


@bp.post("/catalog-entries/<entry_id>/reauthorize")
def reauthorize_entry(entry_id):
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([
        F("expires_at", "instant"),
        F("expected_application_version", "int"),
        F("authorized_grade_band_low", "int", required=False, lo=0, hi=12),
        F("authorized_grade_band_high", "int", required=False, lo=0, hi=12),
    ])
    predecessor = auth.need("entry", entry_id)
    application = store.applications[predecessor["application_id"]]
    vendor = store.vendors[application["vendor_id"]]

    low = data.get("authorized_grade_band_low", predecessor["authorized_grade_band_low"])
    high = data.get("authorized_grade_band_high", predecessor["authorized_grade_band_high"])
    if low > high:
        validate.bad("authorized_grade_band_low must not exceed authorized_grade_band_high.")
    # The successor starts exactly where the predecessor ended, so the new expiry
    # must be strictly after it (the catalog shape rule of PRD 2.5).
    effective_from = predecessor["expires_at"]
    if data["expires_at"] <= effective_from:
        validate.bad("expires_at must be strictly after the predecessor's expiry.")

    if predecessor["status"] not in ("EXPIRING_SOON", "EXPIRED"):
        raise ApiError("ERR_CATALOG_ENTRY_NOT_RENEWABLE")
    if data["expected_application_version"] != application["version"]:
        raise ApiError("ERR_STALE_APPLICATION_VERSION")
    if vendor["privacy_posture"] == "FROZEN":
        raise ApiError("ERR_VENDOR_POSTURE_FROZEN")
    if vendor["privacy_posture"] not in ("CLEAR", "WATCH"):
        raise ApiError("ERR_VENDOR_POSTURE_BLOCKS_PUBLICATION")

    review = store.reviews.get(predecessor["review_id"])
    if (review is None
            or review["status"] not in ("CLEARED", "CONDITIONAL")
            or review["application_id"] != application["id"]):
        raise ApiError("ERR_REVIEW_NOT_CLEARED")
    if logic.window_overlap(application["id"], effective_from, data["expires_at"],
                            exclude_ids=(predecessor["id"],)):
        raise ApiError("ERR_AUTHORIZATION_WINDOW_OVERLAP")
    if low < application["grade_band_low"] or high > application["grade_band_high"]:
        raise ApiError("ERR_GRADE_BAND_OUT_OF_SCOPE")

    predecessor["status"] = "SUPERSEDED"
    store.bump(predecessor)

    successor = store.new_row({
        "application_id": application["id"],
        "review_id": predecessor["review_id"],
        "predecessor_entry_id": predecessor["id"],
        "effective_from": effective_from,
        "expires_at": data["expires_at"],
        "authorized_grade_band_low": low,
        "authorized_grade_band_high": high,
        "reauthorization_due_at": logic.reauthorization_due_at(data["expires_at"]),
        "published_review_score": predecessor["published_review_score"],
        "status": "PUBLISHED",
        "revoked_reason": None,
        "hold_restored_from": None,
    })
    store.catalog_entries[successor["id"]] = successor

    logic.recompute_application_visibility(application, force=True)
    logic.recompute_vendor(vendor, reauthorization=True)
    # A transition, not a collection create: PRD 4 pins these at HTTP 200.
    return envelope.ok(serialize.catalog_entry(successor))


@bp.post("/compliance-sweeps")
def run_sweep():
    auth.actor("PrivacyOfficeAdmin")
    validate.body([])
    now = store.clock()

    entries = store.ordered(list(store.catalog_entries.values()))
    evaluated = [e for e in entries if e["status"] in logic.VISIBLE_STATUSES]

    touched_apps = set()
    touched_vendors = set()
    expiring = 0
    expired = 0

    for entry in evaluated:
        if (entry["status"] == "PUBLISHED"
                and entry["reauthorization_due_at"] <= now < entry["expires_at"]):
            entry["status"] = "EXPIRING_SOON"
            store.bump(entry)
            expiring += 1
            touched_apps.add(entry["application_id"])

    for entry in evaluated:
        if entry["status"] in logic.VISIBLE_STATUSES and entry["expires_at"] <= now:
            entry["status"] = "EXPIRED"
            store.bump(entry)
            expired += 1
            touched_apps.add(entry["application_id"])

    overdue = 0
    for incident in store.ordered(list(store.incidents.values())):
        if (incident["notification_status"] == "PENDING"
                and incident["notification_due_at"] < now):
            incident["notification_status"] = "OVERDUE"
            store.bump(incident)
            overdue += 1
            touched_vendors.add(incident["vendor_id"])

    for app_id in touched_apps:
        application = store.applications[app_id]
        logic.recompute_application_visibility(application)
        touched_vendors.add(application["vendor_id"])

    for vendor_id in touched_vendors:
        logic.recompute_vendor(store.vendors[vendor_id])

    return envelope.ok({
        "evaluated_entry_count": len(evaluated),
        "expiring_soon_count": expiring,
        "expired_count": expired,
        "overdue_notification_count": overdue,
        "recomputed_vendor_count": len(touched_vendors),
    })
