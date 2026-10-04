"""ImportAlert placement and AlertPetition processing (PRD section 3.7).

ImportAlert: ACTIVE -> LIFTED (petition-approval cascade). AlertPetition:
EVIDENCE_REVIEW -> EVIDENCE_REVIEW (submit-evidence) | APPROVED | DENIED
(adjudicate). Segregation of duties: the alert's creator may never adjudicate
a petition against it.
"""
from flask import Blueprint

import db
import serialize
import services
from auth import require_roles, ALL_ROLES
from envelope import ok, ok_list, json_body
from errors import ApiError
from pagination import page_params, paginate

bp = Blueprint("alerts", __name__)


def _get_alert_or_404(alert_id):
    a = db.alerts.get(alert_id)
    if a is None:
        raise ApiError("ERR_IMPORT_ALERT_NOT_FOUND")
    return a


def _get_petition_or_404(petition_id):
    p = db.petitions.get(petition_id)
    if p is None:
        raise ApiError("ERR_ALERT_PETITION_NOT_FOUND")
    return p


@bp.post("/registry/import-alerts")
@require_roles("ComplianceOfficer")
def create_import_alert(caller_id, caller_role):
    body = json_body()
    # Tier 12: scope-field consistency.
    scope_type = body.get("scope_type")
    if scope_type not in ("FIRM", "COUNTRY_PRODUCT"):
        raise ApiError("ERR_INVALID_REQUEST", "scope_type must be FIRM or COUNTRY_PRODUCT")
    facility_id = body.get("facility_id")
    country_code = body.get("country_code")
    product_code = body.get("product_code")
    if scope_type == "FIRM":
        if not isinstance(facility_id, str) or not facility_id:
            raise ApiError("ERR_INVALID_REQUEST", "facility_id is required for FIRM scope")
        if country_code is not None or product_code is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "country_code and product_code are forbidden for FIRM scope",
            )
    else:
        if not isinstance(country_code, str) or not country_code:
            raise ApiError("ERR_INVALID_REQUEST", "country_code is required for COUNTRY_PRODUCT scope")
        if not isinstance(product_code, str) or not product_code:
            raise ApiError("ERR_INVALID_REQUEST", "product_code is required for COUNTRY_PRODUCT scope")
        if facility_id is not None:
            raise ApiError("ERR_INVALID_REQUEST", "facility_id is forbidden for COUNTRY_PRODUCT scope")
    reason = body.get("reason")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise ApiError("ERR_INVALID_REQUEST", "reason must be a string")

    now = db.now()
    a = db.new_common()
    a.update(
        {
            "scope_type": scope_type,
            "facility_id": facility_id if scope_type == "FIRM" else None,
            "country_code": country_code if scope_type == "COUNTRY_PRODUCT" else None,
            "product_code": product_code if scope_type == "COUNTRY_PRODUCT" else None,
            "reason": reason,
            "status": "ACTIVE",
            "created_by_user_id": caller_id,
            "lifted_at": None,
        }
    )
    db.alerts[a["id"]] = a
    # Cascade: detain every matching entry still in PENDING disposition
    # (already-terminal or already-detained entries are untouched).
    for e in sorted(db.entries.values(), key=db.sort_key):
        if e["disposition_status"] != "PENDING":
            continue
        if services.alert_matches_entry(a, e):
            services.detain_entry(e, a["id"], now)
    return ok(serialize.alert(a), 201)


@bp.get("/registry/import-alerts/<aid>")
@require_roles(*ALL_ROLES)
def get_import_alert(aid, caller_id, caller_role):
    return ok(serialize.alert(_get_alert_or_404(aid)))


@bp.get("/registry/import-alerts")
@require_roles(*ALL_ROLES)
def list_import_alerts(caller_id, caller_role):
    limit, offset = page_params()
    items = list(db.alerts.values())
    from flask import request

    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    scope_type = request.args.get("scope_type")
    if facility_id is not None:
        items = [a for a in items if a["facility_id"] == facility_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if scope_type is not None:
        items = [a for a in items if a["scope_type"] == scope_type]
    items.sort(key=db.sort_key)
    total, page = paginate(items, limit, offset)
    return ok_list([serialize.alert(a) for a in page], total, limit, offset)


@bp.post("/registry/import-alerts/<aid>/petitions")
@require_roles("FacilityOwner")
def create_petition(aid, caller_id, caller_role):
    # Tier 4: existence.
    a = _get_alert_or_404(aid)
    # Tier 5: the alert must be ACTIVE.
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_IMPORT_ALERT_NOT_ACTIVE")
    # Tier 8: the filer must lie inside the alert scope.
    if not services.filer_in_scope(a, caller_id):
        raise ApiError("ERR_ALERT_SCOPE_MISMATCH")
    body = json_body()
    expected = body.get("expected_import_alert_version", services.MISSING)
    # Tier 10: OCC on the alert version.
    if (
        expected is not services.MISSING
        and services.is_int(expected)
        and expected != a["version"]
    ):
        raise ApiError("ERR_STALE_VERSION")
    # Tier 12: the OCC field is required; evidence_links must be a list.
    if expected is services.MISSING or not services.is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", "expected_import_alert_version is required")
    evidence_links = body.get("evidence_links")
    if not isinstance(evidence_links, list):
        raise ApiError("ERR_INVALID_REQUEST", "evidence_links must be an array")

    now = db.now()
    p = db.new_common()
    p.update(
        {
            "alert_id": a["id"],
            "filed_by_facility_id": caller_id,
            "evidence_links": list(evidence_links),
            "status": "EVIDENCE_REVIEW",
            "consecutive_compliant_count": None,
        }
    )
    db.petitions[p["id"]] = p
    # Filing a petition increments the ALERT's version by 1 (PRD 3.7).
    db.touch(a, now)
    return ok(serialize.petition(p), 201)


@bp.get("/registry/import-alerts/<aid>/petitions")
@require_roles(*ALL_ROLES)
def list_alert_petitions(aid, caller_id, caller_role):
    _get_alert_or_404(aid)
    limit, offset = page_params()
    items = sorted(
        (p for p in db.petitions.values() if p["alert_id"] == aid), key=db.sort_key
    )
    total, page = paginate(items, limit, offset)
    return ok_list([serialize.petition(p) for p in page], total, limit, offset)


@bp.get("/registry/facilities/<fid>/petitions")
@require_roles(*ALL_ROLES)
def list_facility_petitions(fid, caller_id, caller_role):
    if fid not in db.facilities:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    limit, offset = page_params()
    items = sorted(
        (p for p in db.petitions.values() if p["filed_by_facility_id"] == fid),
        key=db.sort_key,
    )
    total, page = paginate(items, limit, offset)
    return ok_list([serialize.petition(p) for p in page], total, limit, offset)


@bp.post("/registry/alert-petitions/<pid>/submit-evidence")
@require_roles("FacilityOwner")
def submit_evidence(pid, caller_id, caller_role):
    # Tier 4: existence.
    p = _get_petition_or_404(pid)
    # Tier 3: ownership — the filing facility.
    if p["filed_by_facility_id"] != caller_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    # Tier 5: only while EVIDENCE_REVIEW.
    if p["status"] != "EVIDENCE_REVIEW":
        raise ApiError("ERR_PETITION_NOT_REVIEWABLE")
    # Tier 12: evidence_links must be a list.
    evidence_links = json_body().get("evidence_links")
    if not isinstance(evidence_links, list):
        raise ApiError("ERR_INVALID_REQUEST", "evidence_links must be an array")
    p["evidence_links"].extend(evidence_links)
    db.touch(p)
    return ok(serialize.petition(p))


@bp.post("/registry/alert-petitions/<pid>/adjudicate")
@require_roles("ComplianceOfficer")
def adjudicate_petition(pid, caller_id, caller_role):
    # Tier 4: existence.
    p = _get_petition_or_404(pid)
    # Tier 5: only while EVIDENCE_REVIEW.
    if p["status"] != "EVIDENCE_REVIEW":
        raise ApiError("ERR_PETITION_NOT_REVIEWABLE")
    a = db.alerts[p["alert_id"]]
    # Tier 9: segregation of duties.
    if caller_id == a["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    decision = json_body().get("decision")
    streak = services.compliance_streak(a)
    # Tier 11: approval sufficiency (evaluated only for APPROVE).
    if decision == "APPROVE":
        if streak < services.REQUIRED_STREAK or len(p["evidence_links"]) == 0:
            raise ApiError("ERR_INSUFFICIENT_COMPLIANT_SHIPMENTS")
    # Tier 12: decision must be APPROVE or DENY.
    if decision not in ("APPROVE", "DENY"):
        raise ApiError("ERR_INVALID_REQUEST", "decision must be APPROVE or DENY")

    now = db.now()
    # The computed streak is stored whatever the outcome.
    p["consecutive_compliant_count"] = streak
    if decision == "APPROVE":
        p["status"] = "APPROVED"
        db.touch(p, now)
        # Lift the alert and release its remaining detentions.
        a["status"] = "LIFTED"
        a["lifted_at"] = now
        db.touch(a, now)
        for e in sorted(db.entries.values(), key=db.sort_key):
            if e["detained_under_alert_id"] == a["id"] and e["disposition_status"] == "DETAINED":
                services.release_detained(e, now)
    else:
        p["status"] = "DENIED"
        db.touch(p, now)
    return ok(serialize.petition(p))
