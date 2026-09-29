"""OffsiteStorageArrangement and StorageDocument endpoints (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import serial
from auth import authorize, current_role, current_user_id
from calc import HANDLING_BUFFER_DAYS
from domain import DOC_TYPES
from envelope import created, ok, paginated
from errors import ApiError
from shapes import Field, validate
from store import ordered, store
from util import D, add_days

bp = Blueprint("storage", __name__)

ARRANGEMENT_FIELDS = [
    Field("purchase_commitment_id", "string", required=True),
    Field("warehouse_name", "string", required=True, min_len=1, max_len=120),
    Field("warehouse_address", "string", required=True),
    Field("stored_value", "number", required=True, exclusive_minimum=0, max_dp=2),
    Field("monthly_storage_rate_pct", "number", required=True, exclusive_minimum=0,
          maximum=5, max_dp=4),
    Field("stored_from", "datetime", required=True),
    Field("planned_release_date", "datetime", required=True),
]

DOCUMENT_FIELDS = [
    Field("doc_type", "enum", required=True, choices=DOC_TYPES),
    Field("reference_number", "string", required=True, min_len=1, max_len=60),
    Field("effective_date", "datetime", required=True),
    Field("expires_at", "datetime", required=True),
    Field("coverage_amount", "number", minimum=0, max_dp=2, default=Decimal("0")),
    Field("verified", "bool", default=False),
]

REVOKE_FIELDS = [
    Field("revocation_reason", "string", required=True),
]

LIVE_ARRANGEMENT_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED")


def _window_conflict(warehouse_name, start, end):
    """Closed intervals, each inflated by the handling buffer at both ends."""
    new_start = add_days(start, -HANDLING_BUFFER_DAYS)
    new_end = add_days(end, HANDLING_BUFFER_DAYS)
    for row in ordered(list(store.arrangements.values())):
        if row["warehouse_name"] != warehouse_name:
            continue
        if row["status"] not in LIVE_ARRANGEMENT_STATUSES:
            continue
        other_start = add_days(row["stored_from"], -HANDLING_BUFFER_DAYS)
        other_end = add_days(row["planned_release_date"], HANDLING_BUFFER_DAYS)
        if new_start <= other_end and other_start <= new_end:
            return True
    return False


@bp.post("/procurement/storage-arrangements")
@authorize("BuyoutManager")
def create_arrangement():
    body = validate(ARRANGEMENT_FIELDS)
    commitment = domain.get_commitment(body["purchase_commitment_id"])
    if commitment["commitment_status"] != "COMMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if commitment["delivery_posture"] not in ("RELEASED_FOR_FAB", "FABRICATING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    released_at = commitment["released_for_fab_at"]
    if released_at is not None and body["stored_from"] < released_at:
        raise ApiError("ERR_STORAGE_WINDOW_INVALID")
    if body["planned_release_date"] <= body["stored_from"]:
        raise ApiError("ERR_STORAGE_WINDOW_INVALID")
    if _window_conflict(
        body["warehouse_name"], body["stored_from"], body["planned_release_date"]
    ):
        raise ApiError("ERR_WAREHOUSE_WINDOW_CONFLICT")
    if D(body["stored_value"]) > D(commitment["committed_base_cost"]):
        raise ApiError("ERR_STORED_VALUE_EXCEEDS_COMMITMENT")

    row = store.new_row()
    row.update(body)
    row["carrying_cost_frozen_at"] = None
    row["status"] = "DRAFT"
    store.arrangements[row["id"]] = row
    return created(serial.arrangement(row))


@bp.get("/procurement/storage-arrangements/<arrangement_id>")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def read_arrangement(arrangement_id):
    row = domain.get_arrangement(arrangement_id)
    return ok(serial.arrangement(row))


@bp.get("/procurement/storage-arrangements")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_arrangements():
    args = request.args
    commitment_id = domain.string_filter(args, "purchase_commitment_id")
    status = domain.string_filter(args, "status")
    doc_status = domain.string_filter(args, "documentation_status")
    warehouse = domain.string_filter(args, "warehouse_name")
    rows = []
    for row in ordered(list(store.arrangements.values())):
        if commitment_id is not None and row["purchase_commitment_id"] != commitment_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if warehouse is not None and row["warehouse_name"] != warehouse:
            continue
        if doc_status is not None:
            if calc.documentation_completeness(row)[1] != doc_status:
                continue
        rows.append(row)
    return paginated(rows, serial.arrangement)


@bp.post("/procurement/storage-arrangements/<arrangement_id>/documents")
@authorize("BuyoutManager", "SupplierRep")
def file_document(arrangement_id):
    body = validate(DOCUMENT_FIELDS)
    arrangement = domain.get_arrangement(arrangement_id)
    commitment = domain.commitment_of_arrangement(arrangement)
    if current_role() == "SupplierRep":
        supplier = domain.supplier_of_commitment(commitment)
        if current_user_id() != supplier["id"]:
            raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
    if body["doc_type"] == "INSURANCE_CERTIFICATE":
        if D(body["coverage_amount"]) < D(arrangement["stored_value"]):
            raise ApiError("ERR_INSURANCE_COVERAGE_INSUFFICIENT")
    if body["expires_at"] <= body["effective_date"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "expires_at must be strictly after effective_date"
        )

    row = store.new_row()
    row.update(body)
    row["storage_arrangement_id"] = arrangement["id"]
    row["revoked"] = False
    row["revoked_at"] = None
    row["revocation_reason"] = None
    store.documents[row["id"]] = row
    domain.refresh_arrangement_status(arrangement)
    return created(serial.document(row))


@bp.get("/procurement/storage-arrangements/<arrangement_id>/documents")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_documents(arrangement_id):
    arrangement = domain.get_arrangement(arrangement_id)
    args = request.args
    doc_type = domain.string_filter(args, "doc_type")
    revoked = domain.bool_filter(args, "revoked")
    rows = []
    for row in ordered(list(store.documents.values())):
        if row["storage_arrangement_id"] != arrangement["id"]:
            continue
        if doc_type is not None and row["doc_type"] != doc_type:
            continue
        if revoked is not None and row["revoked"] != revoked:
            continue
        rows.append(row)
    return paginated(rows, serial.document)


@bp.post("/procurement/storage-documents/<document_id>/revoke")
@authorize("BuyoutManager")
def revoke_document(document_id):
    body = validate(REVOKE_FIELDS)
    row = domain.get_document(document_id)
    row["revoked"] = True
    row["revoked_at"] = store.clock
    row["revocation_reason"] = body["revocation_reason"]
    store.touch(row)

    arrangement = store.arrangements[row["storage_arrangement_id"]]
    domain.refresh_arrangement_status(arrangement)
    if calc.documentation_completeness(arrangement)[1] == "INCOMPLETE":
        commitment = domain.commitment_of_arrangement(arrangement)
        if commitment["delivery_posture"] == "STORED_OFFSITE":
            commitment["delivery_posture"] = "STORAGE_NONCOMPLIANT"
            store.touch(commitment)
    return ok(serial.document(row))
