"""Routes: compliance certificates."""
from flask import Blueprint, request
from db import DB, stamp_new, touch
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_referential,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate
from services.core import domestic_content_pct

bp = Blueprint("certificates", __name__)

VARIANTS = {"COST_BASED", "COMPONENT_COUNT"}


@bp.post("/api/bus-units/<busUnitId>/compliance-certificates")
def issue_certificate(busUnitId):
    require_roles("ComplianceOfficer")
    bus = DB.buses.get(busUnitId)
    if bus is None:
        raise err_not_found("BusUnit not found")
    if bus["status"] not in ("ENGINEERED", "IN_PRODUCTION", "BUILT"):
        raise err_invalid_state("Bus status does not permit certificate issuance")
    body = get_body()
    variant = body.get("variant")
    if variant is None:
        raise err_invalid_request("Missing required field: variant")
    if variant not in VARIANTS:
        raise err_invalid_request("Unknown variant")
    issued_by = body.get("issued_by")
    if issued_by is None:
        raise err_invalid_request("Missing required field: issued_by")
    threshold = body.get("threshold_pct", 70)
    # Domestic content calc over the bus's parts kit.
    kit = None
    for k in DB.kits.values():
        if k["bus_unit_id"] == busUnitId:
            kit = k
            break
    if kit is None:
        raise err_referential("Bus has no parts kit")
    for cid in kit["component_ids"]:
        if cid not in DB.components:
            raise err_referential(f"Unknown component id: {cid}")
    pct = domestic_content_pct(kit, variant)
    # Supersede prior ISSUED cert for this bus.
    for c in DB.certificates.values():
        if c["bus_unit_id"] == busUnitId and c["status"] == "ISSUED":
            c["status"] = "SUPERSEDED"
            touch(c)
    rec = {
        "bus_unit_id": busUnitId,
        "domestic_content_pct": pct,
        "threshold_pct": threshold,
        "variant": variant,
        "issued_by": issued_by,
        "status": "ISSUED",
    }
    stamp_new(rec)
    DB.certificates[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/bus-units/<busUnitId>/compliance-certificates")
def list_certificates(busUnitId):
    require_roles("PlatformAdmin", "ComplianceOfficer", "Auditor")
    if busUnitId not in DB.buses:
        raise err_not_found("BusUnit not found")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [c for c in DB.certificates.values() if c["bus_unit_id"] == busUnitId]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(c) for c in window], limit, offset, total)


@bp.post("/api/compliance-certificates/<complianceCertificateId>/revoke")
def revoke_certificate(complianceCertificateId):
    require_roles("ComplianceOfficer")
    c = DB.certificates.get(complianceCertificateId)
    if c is None:
        raise err_not_found("ComplianceCertificate not found")
    if c["status"] != "ISSUED":
        raise err_invalid_state("Certificate is not ISSUED")
    bus = DB.buses.get(c["bus_unit_id"])
    if bus is not None:
        contract_id = bus["contract_id"]
        for a in DB.audits.values():
            if (
                a["contract_id"] == contract_id
                and a["audit_type"] == "POST_DELIVERY"
                and a["status"] == "COMPLETED"
                and a.get("result") == "PASS"
            ):
                raise err_invalid_state("Bus has a COMPLETED PASS POST_DELIVERY audit")
    c["status"] = "REVOKED"
    touch(c)
    return success_obj(public(c))
