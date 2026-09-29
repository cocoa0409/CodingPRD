"""PurchaseCommitment endpoints (PRD 3.5, 3.6)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import serial
from auth import authorize
from calc import MAX_BUYOUT_OVERRUN_PCT
from domain import POSTURES
from envelope import created, ok, paginated
from errors import ApiError
from shapes import Field, validate
from store import ordered, store
from util import D, q2

bp = Blueprint("commitments", __name__)

COMMITMENT_FIELDS = [
    Field("quote_id", "string", required=True),
    Field("po_number", "string", required=True, min_len=1, max_len=40),
    Field("expected_project_version", "int", required=True, minimum=0),
    Field("escalation_agreement_id", "string", nullable=True, default=None),
    Field("is_early_buyout", "bool", default=False),
]

POSTURE_FIELDS = [
    Field("to_posture", "enum", required=True, choices=POSTURES),
]

CANCEL_FIELDS = [
    Field("cancellation_reason", "string", required=True),
]

MANUAL_POSTURE_EDGES = (
    ("SCHEDULED", "RELEASED_FOR_FAB"),
    ("RELEASED_FOR_FAB", "FABRICATING"),
    ("FABRICATING", "STORED_OFFSITE"),
    ("FABRICATING", "DELIVERED"),
    ("STORED_OFFSITE", "DELIVERED"),
    ("STORAGE_NONCOMPLIANT", "STORED_OFFSITE"),
)


@bp.post("/procurement/purchase-commitments")
@authorize("BuyoutManager")
def create_commitment():
    body = validate(COMMITMENT_FIELDS)
    quote = domain.get_quote(body["quote_id"])
    agreement = None
    if body["escalation_agreement_id"] is not None:
        agreement = domain.get_agreement(body["escalation_agreement_id"])
    pkg = store.packages[quote["material_package_id"]]
    project = domain.project_of_package(pkg)
    if body["expected_project_version"] != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    if quote["status"] != "OPEN":
        raise ApiError("ERR_QUOTE_NOT_OPEN")
    if agreement is not None:
        if agreement["status"] not in ("PROPOSED", "COUNTERED", "EXECUTED"):
            raise ApiError("ERR_AGREEMENT_NOT_ATTACHABLE")
        if agreement["quote_id"] != quote["id"]:
            raise ApiError("ERR_AGREEMENT_QUOTE_MISMATCH")
    supplier = store.suppliers[quote["supplier_id"]]
    if calc.supplier_exposure(supplier, forward=False)[1] == "HIGH":
        raise ApiError("ERR_SUPPLIER_EXPOSURE_TOO_HIGH")
    for existing in store.commitments.values():
        if existing["po_number"] == body["po_number"]:
            raise ApiError("ERR_DUPLICATE_PO_NUMBER")
    if domain.live_commitment_on_package(pkg["id"]) is not None:
        raise ApiError("ERR_PACKAGE_ALREADY_COMMITTED")
    ceiling = D(pkg["estimated_cost"]) * (
        Decimal("1") + MAX_BUYOUT_OVERRUN_PCT / Decimal("100")
    )
    if D(quote["base_price"]) > ceiling:
        raise ApiError("ERR_BUYOUT_OVERRUN_EXCEEDED")

    row = store.new_row()
    row["quote_id"] = quote["id"]
    row["material_package_id"] = pkg["id"]
    row["escalation_agreement_id"] = body["escalation_agreement_id"]
    row["po_number"] = body["po_number"]
    row["committed_base_cost"] = quote["base_price"]
    row["is_early_buyout"] = body["is_early_buyout"]
    row["commitment_status"] = "PENDING"
    row["delivery_posture"] = "SCHEDULED"
    row["released_for_fab_at"] = None
    row["delivered_at"] = None
    row["escalation_variant"] = "NONE"
    row["escalation_accrued"] = q2(0)
    row["escalation_index_period"] = None
    row["cancellation_reason"] = None
    store.commitments[row["id"]] = row
    if pkg["status"] in ("IDENTIFIED", "SOURCING", "SOURCING_STALLED"):
        pkg["status"] = "BOUGHT_OUT"
        store.touch(pkg)
    domain.bump_project_version(project)
    return created(serial.commitment(row))


@bp.get("/procurement/purchase-commitments/<commitment_id>")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def read_commitment(commitment_id):
    row = domain.get_commitment(commitment_id)
    return ok(serial.commitment(row))


@bp.get("/procurement/purchase-commitments")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_commitments():
    args = request.args
    package_id = domain.string_filter(args, "material_package_id")
    quote_id = domain.string_filter(args, "quote_id")
    agreement_id = domain.string_filter(args, "escalation_agreement_id")
    status = domain.string_filter(args, "commitment_status")
    posture = domain.string_filter(args, "delivery_posture")
    rows = []
    for row in ordered(list(store.commitments.values())):
        if package_id is not None and row["material_package_id"] != package_id:
            continue
        if quote_id is not None and row["quote_id"] != quote_id:
            continue
        if agreement_id is not None and row["escalation_agreement_id"] != agreement_id:
            continue
        if status is not None and row["commitment_status"] != status:
            continue
        if posture is not None and row["delivery_posture"] != posture:
            continue
        rows.append(row)
    return paginated(rows, serial.commitment)


@bp.post("/procurement/purchase-commitments/<commitment_id>/commit")
@authorize("ProjectExecutive")
def commit_commitment(commitment_id):
    validate([])
    row = domain.get_commitment(commitment_id)
    if row["commitment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    quote = store.quotes[row["quote_id"]]
    if quote["status"] != "OPEN" or store.clock >= quote["expires_at"]:
        raise ApiError("ERR_QUOTE_NOT_OPEN")
    if row["escalation_agreement_id"] is not None:
        agreement = store.agreements[row["escalation_agreement_id"]]
        if agreement["status"] != "EXECUTED":
            raise ApiError("ERR_ESCALATION_NOT_EXECUTED")
    supplier = store.suppliers[quote["supplier_id"]]
    if supplier["status"] != "ACTIVE":
        raise ApiError("ERR_SUPPLIER_NOT_ACTIVE")

    row["commitment_status"] = "COMMITTED"
    store.touch(row)
    quote["status"] = "CONVERTED"
    store.touch(quote)
    domain.bump_project_version(domain.project_of_commitment(row))
    return ok(serial.commitment(row))


@bp.post("/procurement/purchase-commitments/<commitment_id>/delivery-posture")
@authorize("BuyoutManager")
def move_posture(commitment_id):
    body = validate(POSTURE_FIELDS)
    row = domain.get_commitment(commitment_id)
    target = body["to_posture"]
    current = row["delivery_posture"]
    if row["commitment_status"] != "COMMITTED":
        raise ApiError("ERR_INVALID_POSTURE_TRANSITION")
    if (current, target) not in MANUAL_POSTURE_EDGES:
        raise ApiError("ERR_INVALID_POSTURE_TRANSITION")
    if current == "FABRICATING" and target == "DELIVERED" and row["is_early_buyout"]:
        raise ApiError("ERR_STORAGE_STEP_REQUIRED")

    if target == "STORED_OFFSITE":
        if domain.active_documented_arrangement(row["id"]) is None:
            raise ApiError("ERR_STORAGE_NOT_DOCUMENTED")
        row["delivery_posture"] = target
        store.touch(row)
        return ok(serial.commitment(row))

    if target == "FABRICATING":
        row["delivery_posture"] = target
        store.touch(row)
        return ok(serial.commitment(row))

    if target == "RELEASED_FOR_FAB":
        amount, period = domain.recognise_escalation(row, "PROVISIONAL")
        project = domain.project_of_commitment(row)
        remaining = calc.project_rollups(project)["escalation_contingency_remaining"]
        if amount > remaining:
            raise ApiError("ERR_CONTINGENCY_EXCEEDED")
        row["delivery_posture"] = target
        row["released_for_fab_at"] = store.clock
        if row["escalation_agreement_id"] is not None:
            row["escalation_variant"] = "PROVISIONAL"
            row["escalation_accrued"] = amount
            row["escalation_index_period"] = period
        store.touch(row)
        domain.bump_project_version(project)
        return ok(serial.commitment(row))

    # target == DELIVERED
    amount, period = domain.recognise_escalation(row, "FINAL")
    project = domain.project_of_commitment(row)
    row["delivery_posture"] = "DELIVERED"
    row["delivered_at"] = store.clock
    if row["escalation_agreement_id"] is not None:
        row["escalation_variant"] = "FINAL"
        row["escalation_accrued"] = amount
        row["escalation_index_period"] = period
    row["commitment_status"] = "CLOSED"
    store.touch(row)
    pkg = domain.package_of_commitment(row)
    if pkg["status"] == "BOUGHT_OUT":
        pkg["status"] = "CLOSED"
        store.touch(pkg)
    for arrangement in domain.arrangements_of_commitment(row["id"]):
        if arrangement["status"] == "ACTIVE":
            arrangement["status"] = "RELEASED"
            arrangement["carrying_cost_frozen_at"] = store.clock
            store.touch(arrangement)
    domain.bump_project_version(project)
    return ok(serial.commitment(row))


@bp.post("/procurement/purchase-commitments/<commitment_id>/cancel")
@authorize("ProjectExecutive")
def cancel_commitment(commitment_id):
    body = validate(CANCEL_FIELDS)
    row = domain.get_commitment(commitment_id)
    if row["commitment_status"] not in ("PENDING", "COMMITTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if row["commitment_status"] == "COMMITTED":
        if row["delivery_posture"] not in ("SCHEDULED", "RELEASED_FOR_FAB"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    was_committed = row["commitment_status"] == "COMMITTED"
    row["commitment_status"] = "CANCELLED"
    row["cancellation_reason"] = body["cancellation_reason"]
    row["escalation_accrued"] = q2(0)
    row["escalation_variant"] = "NONE"
    row["escalation_index_period"] = None
    row["released_for_fab_at"] = None
    row["delivery_posture"] = "SCHEDULED"
    store.touch(row)

    quote = store.quotes[row["quote_id"]]
    if was_committed and quote["status"] == "CONVERTED":
        quote["status"] = "OPEN" if store.clock < quote["expires_at"] else "EXPIRED"
        store.touch(quote)

    domain.release_package_from_bought_out(domain.package_of_commitment(row))
    domain.bump_project_version(domain.project_of_commitment(row))
    return ok(serial.commitment(row))
