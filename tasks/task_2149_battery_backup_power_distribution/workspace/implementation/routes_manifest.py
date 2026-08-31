"""Lead disposal manifests: accumulation, submission, filing and rejection."""
from flask import Blueprint

import calc
from common import (
    ApiError, DB, authenticate, f_int, f_str, get_body, must, new_row, now_ts,
    ok, page, public, qp, sort_rows, touch,
)

bp = Blueprint("manifests", __name__, url_prefix="/distribution")

MANIFEST_READERS = ["PlatformAdmin", "WarehouseOperator", "ComplianceOfficer"]


@bp.post("/disposal-manifests")
def create_manifest():
    user_id, role = authenticate(["ComplianceOfficer"])
    body = get_body()
    warehouse_id = f_str(body, "warehouse_id")
    epa_id = f_str(body, "epa_id")
    reporting_period = f_str(body, "reporting_period")
    must("warehouses", warehouse_id)
    row = new_row({
        "warehouse_id": warehouse_id,
        "epa_id": epa_id,
        "reporting_period": reporting_period,
        "created_by_user_id": user_id,
        "filed_by_user_id": None,
        "attached_core_return_count": 0,
        "scrapped_lot_count": 0,
        "core_lead_kg": 0.0,
        "lot_lead_kg": 0.0,
        "total_lead_kg": 0.0,
        "rejection_reason": None,
        "filed_at": None,
        "status": "DRAFT",
    })
    DB.disposal_manifests[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/disposal-manifests/<manifest_id>")
def read_manifest(manifest_id):
    authenticate(MANIFEST_READERS)
    return ok(calc.serialize_manifest(must("disposal_manifests", manifest_id)))


@bp.get("/disposal-manifests")
def list_manifests():
    authenticate(MANIFEST_READERS)
    rows = list(DB.disposal_manifests.values())
    for name in ("warehouse_id", "status"):
        value = qp(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return page(rows, calc.serialize_manifest)


@bp.post("/disposal-manifests/<manifest_id>/attach-core-return")
def attach_core_return(manifest_id):
    authenticate(["ComplianceOfficer"])
    manifest = must("disposal_manifests", manifest_id)
    body = get_body()
    core_return_id = f_str(body, "core_return_id")
    expected_version = f_int(body, "expected_disposal_manifest_version")
    core_return = must("core_returns", core_return_id)

    if expected_version != int(manifest["version"]):
        raise ApiError("ERR_STALE_VERSION", "expected_disposal_manifest_version does not match")
    if manifest["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "manifest is not in DRAFT")
    if core_return["status"] != "CREDITED":
        raise ApiError("ERR_INVALID_STATE", "core return is not CREDITED")

    previous = core_return.get("disposal_manifest_id")
    core_return["disposal_manifest_id"] = manifest_id
    total = calc.manifest_totals(manifest)
    if total > calc.EPA_MANIFEST_MAX_LEAD_KG:
        core_return["disposal_manifest_id"] = previous
        calc.manifest_totals(manifest)
        raise ApiError("ERR_MANIFEST_LEAD_LIMIT_EXCEEDED", "manifest lead ceiling exceeded")

    touch(core_return)
    touch(manifest)
    return ok(calc.serialize_manifest(manifest))


@bp.post("/disposal-manifests/<manifest_id>/submit")
def submit_manifest(manifest_id):
    authenticate(["ComplianceOfficer"])
    manifest = must("disposal_manifests", manifest_id)
    get_body()
    if manifest["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "manifest is not in DRAFT")
    total = calc.manifest_totals(manifest)
    if int(manifest["attached_core_return_count"]) + int(manifest["scrapped_lot_count"]) < 1:
        raise ApiError("ERR_MANIFEST_EMPTY", "manifest carries nothing")
    if total > calc.EPA_MANIFEST_MAX_LEAD_KG:
        raise ApiError("ERR_MANIFEST_LEAD_LIMIT_EXCEEDED", "manifest lead ceiling exceeded")
    manifest["status"] = "SUBMITTED"
    touch(manifest)
    return ok(calc.serialize_manifest(manifest))


@bp.post("/disposal-manifests/<manifest_id>/file")
def file_manifest(manifest_id):
    user_id, role = authenticate(["ComplianceOfficer"])
    manifest = must("disposal_manifests", manifest_id)
    get_body()
    if user_id == manifest["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "the author may not file the manifest")
    if manifest["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "manifest is not SUBMITTED")
    manifest["filed_by_user_id"] = user_id
    manifest["filed_at"] = now_ts()
    manifest["status"] = "FILED"
    touch(manifest)
    return ok(calc.serialize_manifest(manifest))


@bp.post("/disposal-manifests/<manifest_id>/reject")
def reject_manifest(manifest_id):
    authenticate(["ComplianceOfficer", "PlatformAdmin"])
    manifest = must("disposal_manifests", manifest_id)
    body = get_body()
    reason = f_str(body, "rejection_reason")
    if manifest["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "manifest is not SUBMITTED")

    for core_return in sort_rows(list(DB.core_returns.values())):
        if core_return.get("disposal_manifest_id") == manifest_id:
            core_return["disposal_manifest_id"] = None
            touch(core_return)
    for lot in sort_rows(list(DB.inventory_lots.values())):
        if lot.get("scrap_manifest_id") == manifest_id:
            lot["scrap_manifest_id"] = None
            calc.lot_view(lot)
            touch(lot)

    manifest["rejection_reason"] = reason
    manifest["status"] = "DRAFT"
    manifest["attached_core_return_count"] = 0
    manifest["scrapped_lot_count"] = 0
    manifest["core_lead_kg"] = 0.0
    manifest["lot_lead_kg"] = 0.0
    manifest["total_lead_kg"] = 0.0
    touch(manifest)
    return ok(public(manifest))
