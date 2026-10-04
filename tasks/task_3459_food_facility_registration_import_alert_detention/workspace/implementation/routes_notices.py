"""Prior notice filing and amendment (PRD section 3.3).

PriorNotice state machine: CONFIRMED -> SUPERSEDED (amend), CONFIRMED ->
CONSUMED (entry creation), CONFIRMED -> COMPROMISED (inspection-refusal
cascade link 3). All three successor states are terminal.
"""
from flask import Blueprint, request

import db
import serialize
import services
from auth import require_roles, ALL_ROLES
from envelope import ok, ok_list, json_body
from errors import ApiError
from pagination import page_params, paginate

bp = Blueprint("prior_notices", __name__)

RISK_CLASSES = ("LOW", "STANDARD", "HIGH")
TRANSPORT_MODES = ("VESSEL", "AIR", "RAIL", "ROAD")


def _validate_notice_shape(body):
    """Tier 12 for the full prior-notice data element set."""
    facility_id = body.get("facility_id")
    importer_id = body.get("importer_id")
    product_code = body.get("product_code")
    port_code = body.get("port_code")
    if not isinstance(importer_id, str) or not importer_id:
        raise ApiError("ERR_INVALID_REQUEST", "importer_id is required")
    if not isinstance(facility_id, str) or not facility_id:
        raise ApiError("ERR_INVALID_REQUEST", "facility_id is required")
    if not isinstance(product_code, str) or not product_code:
        raise ApiError("ERR_INVALID_REQUEST", "product_code is required")
    if body.get("product_risk_class") not in RISK_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST", "product_risk_class must be LOW, STANDARD, or HIGH")
    if body.get("transport_mode") not in TRANSPORT_MODES:
        raise ApiError("ERR_INVALID_REQUEST", "transport_mode must be VESSEL, AIR, RAIL, or ROAD")
    if db.parse_dt(body.get("arrival_eta")) is None:
        raise ApiError("ERR_INVALID_REQUEST", "arrival_eta must be an ISO-8601 datetime")
    declared_units = body.get("declared_units")
    if not services.is_int(declared_units) or declared_units <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "declared_units must be an integer greater than 0")
    unit_value_cents = body.get("unit_value_cents")
    if not services.is_int(unit_value_cents) or unit_value_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_value_cents must be an integer >= 0")
    if not isinstance(port_code, str) or not port_code:
        raise ApiError("ERR_INVALID_REQUEST", "port_code is required")


@bp.post("/registry/prior-notices")
@require_roles("Importer")
def create_prior_notice(caller_id, caller_role):
    body = json_body()
    importer_id = body.get("importer_id")
    facility_id = body.get("facility_id")
    # Tier 3: ownership — body importer_id must equal the caller.
    if importer_id is not None and importer_id != caller_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    # Tier 4: existence of referenced principals (facility, then importer).
    facility = db.facilities.get(facility_id) if isinstance(facility_id, str) else None
    if facility_id is not None and facility is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    importer = db.importers.get(importer_id) if isinstance(importer_id, str) else None
    if importer_id is not None and importer is None:
        raise ApiError("ERR_IMPORTER_NOT_FOUND")
    # Tier 5: importer standing gate.
    if importer is not None and importer["standing"] == "REVOKED":
        raise ApiError("ERR_IMPORTER_REVOKED")
    # Tier 6: registration gate.
    if facility is not None and facility["registration_status"] != "REGISTERED":
        raise ApiError("ERR_REGISTRATION_NOT_ACTIVE")
    # Tier 7: initial-variant lead-time window.
    arrival_eta = db.parse_dt(body.get("arrival_eta"))
    transport_mode = body.get("transport_mode")
    if arrival_eta is not None and transport_mode in TRANSPORT_MODES:
        services.check_notice_window(arrival_eta, transport_mode, amendment=False)
    # Tier 12: request shape.
    _validate_notice_shape(body)

    p = db.new_common()
    p.update(
        {
            "importer_id": importer_id,
            "facility_id": facility_id,
            "product_code": body["product_code"],
            "product_risk_class": body["product_risk_class"],
            "transport_mode": transport_mode,
            "arrival_eta": arrival_eta,
            "declared_units": body["declared_units"],
            "unit_value_cents": body["unit_value_cents"],
            "port_code": body["port_code"],
            "status": "CONFIRMED",
            "is_amendment": False,
            "parent_pn_id": None,
        }
    )
    db.prior_notices[p["id"]] = p
    return ok(serialize.prior_notice(p), 201)


@bp.get("/registry/prior-notices/<pnid>")
@require_roles(*ALL_ROLES)
def get_prior_notice(pnid, caller_id, caller_role):
    p = db.prior_notices.get(pnid)
    if p is None:
        raise ApiError("ERR_PRIOR_NOTICE_NOT_FOUND")
    return ok(serialize.prior_notice(p))


@bp.get("/registry/prior-notices")
@require_roles(*ALL_ROLES)
def list_prior_notices(caller_id, caller_role):
    limit, offset = page_params()
    items = list(db.prior_notices.values())
    facility_id = request.args.get("facility_id")
    importer_id = request.args.get("importer_id")
    status = request.args.get("status")
    parent_pn_id = request.args.get("parent_pn_id")
    if facility_id is not None:
        items = [p for p in items if p["facility_id"] == facility_id]
    if importer_id is not None:
        items = [p for p in items if p["importer_id"] == importer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if parent_pn_id is not None:
        items = [p for p in items if p["parent_pn_id"] == parent_pn_id]
    items.sort(key=db.sort_key)
    total, page = paginate(items, limit, offset)
    return ok_list([serialize.prior_notice(p) for p in page], total, limit, offset)


@bp.post("/registry/prior-notices/<pnid>/amend")
@require_roles("Importer")
def amend_prior_notice(pnid, caller_id, caller_role):
    # Tier 4: existence.
    p = db.prior_notices.get(pnid)
    if p is None:
        raise ApiError("ERR_PRIOR_NOTICE_NOT_FOUND")
    # Tier 3: ownership — the notice's importer.
    if p["importer_id"] != caller_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    # Tier 5: only a CONFIRMED notice may be amended.
    if p["status"] != "CONFIRMED":
        raise ApiError("ERR_PN_NOT_CONFIRMED")
    body = json_body()
    # Tier 7: amendment-variant lead-time window on the fresh arrival_eta.
    arrival_eta = db.parse_dt(body.get("arrival_eta"))
    if arrival_eta is not None:
        services.check_notice_window(arrival_eta, p["transport_mode"], amendment=True)
    # Tier 12: arrival_eta is always carried; optional replacements validated.
    if arrival_eta is None:
        raise ApiError("ERR_INVALID_REQUEST", "arrival_eta is required and must be an ISO-8601 datetime")
    declared_units = body.get("declared_units", p["declared_units"])
    if not services.is_int(declared_units) or declared_units <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "declared_units must be an integer greater than 0")
    unit_value_cents = body.get("unit_value_cents", p["unit_value_cents"])
    if not services.is_int(unit_value_cents) or unit_value_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_value_cents must be an integer >= 0")
    port_code = body.get("port_code", p["port_code"])
    if not isinstance(port_code, str) or not port_code:
        raise ApiError("ERR_INVALID_REQUEST", "port_code must be a non-empty string")

    # Supersede the original; create the amendment notice inheriting the rest.
    now = db.now()
    p["status"] = "SUPERSEDED"
    db.touch(p, now)
    new_p = db.new_common()
    new_p.update(
        {
            "importer_id": p["importer_id"],
            "facility_id": p["facility_id"],
            "product_code": p["product_code"],
            "product_risk_class": p["product_risk_class"],
            "transport_mode": p["transport_mode"],
            "arrival_eta": arrival_eta,
            "declared_units": declared_units,
            "unit_value_cents": unit_value_cents,
            "port_code": port_code,
            "status": "CONFIRMED",
            "is_amendment": True,
            "parent_pn_id": p["id"],
        }
    )
    db.prior_notices[new_p["id"]] = new_p
    return ok(serialize.prior_notice(new_p), 201)
