"""Facilities, vendors, the representative roster, credentials and the clock
(PRD 3.1, 3.2, 2.4).
"""
import re

from flask import Blueprint

import calc
import cascades
import db
from db import store
from envelope import respond_object
from errors import ApiError
from reqval import (
    authenticate,
    pagination_params,
    query_enum,
    query_string,
    read_body,
    require_ordered,
)
from routes import common
from timeutil import add_days, fmt_instant

bp = Blueprint("core", __name__, url_prefix="/vendor-access")

FACILITY_CODE_RE = re.compile(r"^[A-Z0-9-]{1,16}$")


# --------------------------------------------------------------- Facility
@bp.post("/facilities")
def register_facility():
    authenticate(("ComplianceAdmin", "CredentialingOfficer"))
    body = read_body()
    name = body.string("name")
    code = body.string("code")
    if not FACILITY_CODE_RE.match(code):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'code' must be 1-16 characters of uppercase letters, digits and hyphens.",
        )
    spd_turnaround_hours = body.integer("spd_turnaround_hours", minimum=0)
    spd_bay_count = body.integer("spd_bay_count", minimum=1)
    badge_lead_minutes = body.integer(
        "badge_lead_minutes", required=False, default=60, minimum=0
    )
    badge_grace_minutes = body.integer(
        "badge_grace_minutes", required=False, default=30, minimum=0
    )
    restricted_escort_required = body.boolean(
        "restricted_escort_required", required=False, default=True
    )

    for existing in store.facilities.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_FACILITY_CODE")

    row = db.stamp_common(
        {
            "name": name,
            "code": code,
            "spd_turnaround_hours": spd_turnaround_hours,
            "spd_bay_count": spd_bay_count,
            "badge_lead_minutes": badge_lead_minutes,
            "badge_grace_minutes": badge_grace_minutes,
            "restricted_escort_required": restricted_escort_required,
        }
    )
    store.facilities[row["id"]] = row
    return common.created(row)


@bp.get("/facilities/<row_id>")
def read_facility(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.facility(row_id))


# ----------------------------------------------------------------- Vendor
@bp.post("/vendors")
def enrol_vendor():
    authenticate(("ComplianceAdmin", "CredentialingOfficer"))
    body = read_body()
    legal_name = body.string("legal_name")
    vendor_code = body.string("vendor_code")

    for existing in store.vendors.values():
        if existing["vendor_code"] == vendor_code:
            raise ApiError("ERR_DUPLICATE_VENDOR_CODE")

    row = db.stamp_common(
        {
            "legal_name": legal_name,
            "vendor_code": vendor_code,
            "provisional_compliance_score": db.BASE_SCORE,
            "adjudicated_compliance_score": db.BASE_SCORE,
            "scorecard_tier": "TIER_PLATINUM",
            "compliance_status": "IN_GOOD_STANDING",
            "access_quota_in_effect": db.BASE_QUOTA,
            "authorizations_used_epoch": 0,
            "late_fee_balance_cents": 0,
            "open_pir_count": 0,
            "last_sweep_epoch": 0,
            # Frozen sweep inputs to the compliance score (PRD 3.8): the lapsed
            # representative count and the over-utilization penalty are
            # refreshed only inside the sweep's rescoring phase.
            "_lapsed_rep_count_at_last_sweep": 0,
            "_overage_penalty_at_last_sweep": 0,
        }
    )
    store.vendors[row["id"]] = row
    return common.created(row)


@bp.get("/vendors/<row_id>")
def read_vendor(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.vendor(row_id))


@bp.get("/vendors/<row_id>/scorecard")
def read_scorecard(row_id):
    user_id, role = authenticate(("CredentialingOfficer", "ComplianceAdmin", "VendorAdmin"))
    vendor = common.vendor(row_id)
    common.require_vendor_scope(role, user_id, vendor["id"])

    incidents = calc.incidents_of_vendor(vendor["id"])
    ratio = calc.compute_utilization_ratio(
        vendor["authorizations_used_epoch"], vendor["access_quota_in_effect"]
    )
    data = {
        "vendor_id": vendor["id"],
        "provisional_compliance_score": vendor["provisional_compliance_score"],
        "adjudicated_compliance_score": vendor["adjudicated_compliance_score"],
        "scorecard_tier": vendor["scorecard_tier"],
        "compliance_status": vendor["compliance_status"],
        "access_quota_in_effect": vendor["access_quota_in_effect"],
        "authorizations_used_epoch": vendor["authorizations_used_epoch"],
        "utilization_ratio": float(ratio),
        "late_fee_balance_cents": vendor["late_fee_balance_cents"],
        "lapsed_rep_count": calc.compute_lapsed_rep_count(vendor["id"]),
        "substantiated_incident_count": len(
            [i for i in incidents if i["adjudicated_outcome"] == "SUBSTANTIATED"]
        ),
        "open_incident_count": len(
            [i for i in incidents if i["status"] in db.INCIDENT_OPEN_STATUSES]
        ),
        "late_delivery_count": calc.compute_late_delivery_count(vendor["id"]),
        "last_sweep_epoch": vendor["last_sweep_epoch"],
    }
    return respond_object(data, 200)


# -------------------------------------------------------------- VendorRep
@bp.post("/vendor-reps")
def register_vendor_rep():
    authenticate(("VendorAdmin", "CredentialingOfficer"))
    body = read_body()
    vendor_id = body.string("vendor_id")
    full_name = body.string("full_name")
    email = body.string("email")

    common.vendor(vendor_id)
    for existing in store.vendor_reps.values():
        if existing["email"] == email:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field 'email' must be unique across every representative.",
            )

    row = db.stamp_common(
        {
            "vendor_id": vendor_id,
            "full_name": full_name,
            "email": email,
            "access_status": "PENDING_CREDENTIALING",
            "credential_posture": "INCOMPLETE",
            "suspension_reason": "NONE",
            "ever_credentialed": False,
            "open_authorization_count": 0,
            "revoked_by_user_id": None,
            "revoked_at_utc": None,
            "reinstated_at_utc": None,
        }
    )
    store.vendor_reps[row["id"]] = row
    return common.created(row)


@bp.get("/vendor-reps/<row_id>")
def read_vendor_rep(row_id):
    authenticate(common.ALL_ROLES)
    return common.ok(common.vendor_rep(row_id))


@bp.get("/vendor-reps")
def list_vendor_reps():
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    vendor_id = query_string("vendor_id")
    access_status = query_enum("access_status", db.REP_ACCESS_STATUSES)
    credential_posture = query_enum("credential_posture", db.REP_POSTURES)
    rows = [
        row
        for row in store.vendor_reps.values()
        if common.matches(row, "vendor_id", vendor_id)
        and common.matches(row, "access_status", access_status)
        and common.matches(row, "credential_posture", credential_posture)
    ]
    return common.listing(rows, limit, offset)


@bp.post("/vendor-reps/<row_id>/revoke-access")
def revoke_rep_access(row_id):
    user_id, _role = authenticate(("CredentialingOfficer", "ComplianceAdmin"))
    body = read_body()
    body.string("reason")
    rep = common.vendor_rep(row_id)

    # Admissible from PENDING_CREDENTIALING, CREDENTIALED and SUSPENDED: the
    # only precondition is that the representative is not already REVOKED.
    if rep["access_status"] == "REVOKED":
        raise ApiError("ERR_REP_ACCESS_REVOKED")

    was_credentialed = rep["access_status"] == "CREDENTIALED"
    rep["access_status"] = "REVOKED"
    rep["revoked_by_user_id"] = user_id
    rep["revoked_at_utc"] = db.now_str()
    cascades.mark_rep(rep)

    # Only a CREDENTIALED representative may be holding live authorizations.
    if was_credentialed:
        cascades.rep_access_cascade(rep, "REP_REVOKED")

    cascades.flush()
    return common.ok(rep)


@bp.get("/vendor-reps/<row_id>/credentials")
def list_rep_credentials(row_id):
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    credential_type = query_enum("credential_type", db.CREDENTIAL_TYPES)
    status = query_enum("status", db.CREDENTIAL_STATUSES)
    rep = common.vendor_rep(row_id)
    rows = [
        row
        for row in calc.credentials_of_rep(rep["id"])
        if common.matches(row, "credential_type", credential_type)
        and common.matches(row, "status", status)
    ]
    return common.listing(rows, limit, offset)


@bp.get("/vendor-reps/<row_id>/access-appeals")
def list_rep_appeals(row_id):
    authenticate(common.ALL_ROLES)
    limit, offset = pagination_params()
    status = query_enum("status", db.APPEAL_STATUSES)
    rep = common.vendor_rep(row_id)
    rows = [
        row for row in calc.appeals_of_rep(rep["id"]) if common.matches(row, "status", status)
    ]
    return common.listing(rows, limit, offset)


# ------------------------------------------------------------- Credential
@bp.post("/credentials")
def attest_credential():
    authenticate(("VendorAdmin", "VendorRepUser", "CredentialingOfficer"))
    body = read_body()
    vendor_rep_id = body.string("vendor_rep_id")
    credential_type = body.enum("credential_type", db.CREDENTIAL_TYPES)
    issued_raw, issued = body.instant("issued_at_utc")
    expires_raw, expires = body.instant("expires_at_utc")
    document_reference = body.string("document_reference")

    # Rung 4: the expiry must fall strictly after the issue instant.
    require_ordered(issued, expires)

    rep = common.vendor_rep(vendor_rep_id)
    if rep["access_status"] == "REVOKED":
        raise ApiError("ERR_REP_ACCESS_REVOKED")

    for existing in calc.credentials_of_rep(rep["id"]):
        if existing["credential_type"] == credential_type and existing["status"] in (
            "PENDING_VERIFICATION",
            "VERIFIED",
            "EXPIRING_SOON",
        ):
            raise ApiError("ERR_DUPLICATE_CREDENTIAL")

    row = db.stamp_common(
        {
            "vendor_rep_id": rep["id"],
            "credential_type": credential_type,
            "issued_at_utc": issued_raw,
            "expires_at_utc": expires_raw,
            "document_reference": document_reference,
            "status": "PENDING_VERIFICATION",
            "verified_by_user_id": None,
            "verified_at_utc": None,
            "rejection_reason": None,
        }
    )
    store.credentials[row["id"]] = row
    # A pending attestation covers nothing, so credential_posture is left
    # exactly as it was.
    return common.created(row)


@bp.post("/credentials/<row_id>/decide")
def decide_credential(row_id):
    user_id, _role = authenticate(("CredentialingOfficer",))
    body = read_body()
    decision = body.enum("decision", ("VERIFY", "REJECT"))
    rejection_reason = body.string("rejection_reason", required=False)

    credential = common.credential(row_id)
    if credential["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_CREDENTIAL_NOT_PENDING")

    if decision == "VERIFY":
        credential["status"] = "VERIFIED"
        credential["verified_by_user_id"] = user_id
        credential["verified_at_utc"] = db.now_str()
    else:
        credential["status"] = "REJECTED"
        credential["rejection_reason"] = rejection_reason
    cascades.mark(credential)

    rep = store.vendor_reps.get(credential["vendor_rep_id"])
    if rep is not None:
        posture = cascades.recompute_posture(rep)
        if decision == "VERIFY" and posture in ("COMPLIANT", "EXPIRING_SOON"):
            if rep["access_status"] == "PENDING_CREDENTIALING":
                rep["access_status"] = "CREDENTIALED"
                rep["suspension_reason"] = "NONE"
                cascades.mark_rep(rep)
            elif (
                rep["access_status"] == "SUSPENDED"
                and rep["suspension_reason"] == "CREDENTIAL_LAPSED"
            ):
                rep["access_status"] = "CREDENTIALED"
                rep["suspension_reason"] = "NONE"
                rep["reinstated_at_utc"] = db.now_str()
                cascades.mark_rep(rep)

    cascades.flush()
    return common.ok(credential)


# ------------------------------------------------------- the logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(common.ALL_ROLES)
    body = read_body()
    _raw, parsed = body.instant("current_utc")
    store.clock = parsed
    # Setting the clock performs no state transitions of its own.
    return respond_object({"current_utc": db.now_str()}, 200)
