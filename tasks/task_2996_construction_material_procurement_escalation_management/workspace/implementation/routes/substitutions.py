"""SubstitutionRequest endpoints (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import serial
from auth import authorize, current_user_id
from calc import MAX_SUBSTITUTION_ROUNDS
from domain import DRIVERS
from envelope import created, ok, paginated
from errors import ApiError
from shapes import Field, validate
from store import ordered, store
from util import D, q2

bp = Blueprint("substitutions", __name__)

DISPOSITIONS = ("APPROVED", "APPROVED_AS_NOTED", "REJECTED", "REVISION_REQUESTED")

SUBSTITUTION_FIELDS = [
    Field("material_package_id", "string", required=True),
    Field("proposed_supplier_id", "string", required=True),
    Field("driver", "enum", required=True, choices=DRIVERS),
    Field("proposed_product", "string", required=True, min_len=1, max_len=200),
    Field("cost_delta", "number", required=True, minimum=-5000000, maximum=5000000,
          max_dp=2),
    Field("schedule_delta_days", "int", required=True, minimum=-180, maximum=180),
    Field("disruption_event_id", "string", nullable=True, default=None),
]

DISPOSITION_FIELDS = [
    Field("disposition", "enum", required=True, choices=DISPOSITIONS),
    Field("engineer_conditions", "string", nullable=True, allow_blank=True),
]

RESUBMIT_FIELDS = [
    Field("proposed_product", "string", required=True, min_len=1, max_len=200),
    Field("cost_delta", "number", required=True, minimum=-5000000, maximum=5000000,
          max_dp=2),
    Field("schedule_delta_days", "int", required=True, minimum=-180, maximum=180),
]

RESCIND_FIELDS = [
    Field("rescission_reason", "string", required=True),
]


def _package_supplier_ids(package_id):
    """Suppliers the package is currently quoted or committed against."""
    ids = set()
    for quote in store.quotes.values():
        if quote["material_package_id"] == package_id:
            ids.add(quote["supplier_id"])
    for commitment in store.commitments.values():
        if commitment["material_package_id"] == package_id:
            ids.add(store.quotes[commitment["quote_id"]]["supplier_id"])
    return ids


def _committed_supplier_ids(package_id):
    ids = set()
    for commitment in store.commitments.values():
        if commitment["material_package_id"] != package_id:
            continue
        if commitment["commitment_status"] not in ("PENDING", "COMMITTED"):
            continue
        ids.add(store.quotes[commitment["quote_id"]]["supplier_id"])
    return ids


def _apply_to_package(pkg, cost_delta, schedule_delta_days):
    pkg["estimated_cost"] = q2(D(pkg["estimated_cost"]) + D(cost_delta))
    pkg["fabrication_duration_days"] = (
        int(pkg["fabrication_duration_days"]) + int(schedule_delta_days)
    )
    store.touch(pkg)


@bp.post("/procurement/substitution-requests")
@authorize("BuyoutManager")
def create_substitution():
    body = validate(SUBSTITUTION_FIELDS)
    pkg = domain.get_package(body["material_package_id"])
    supplier = domain.get_supplier(body["proposed_supplier_id"])
    event = None
    if body["disruption_event_id"] is not None:
        event = domain.get_disruption(body["disruption_event_id"])

    if supplier["id"] in _committed_supplier_ids(pkg["id"]):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "proposed_supplier_id is already committed on this package",
        )
    if body["driver"] == "DISRUPTION_CONTINGENCY":
        if event is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "disruption_event_id is required for DISRUPTION_CONTINGENCY",
            )
        if event["supplier_id"] not in _package_supplier_ids(pkg["id"]):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "the disruption event does not belong to a supplier of this package",
            )
    elif event is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "disruption_event_id may only be supplied with DISRUPTION_CONTINGENCY",
        )

    row = store.new_row()
    row.update(body)
    row["submitted_by_user_id"] = current_user_id()
    row["engineer_conditions"] = None
    row["revision_round"] = 0
    row["applied_cost_delta"] = q2(0)
    row["applied_schedule_delta_days"] = 0
    row["status"] = "SUBMITTED"
    store.substitutions[row["id"]] = row
    return created(serial.substitution(row))


@bp.get("/procurement/substitution-requests/<substitution_id>")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def read_substitution(substitution_id):
    row = domain.get_substitution(substitution_id)
    return ok(serial.substitution(row))


@bp.get("/procurement/substitution-requests")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_substitutions():
    args = request.args
    package_id = domain.string_filter(args, "material_package_id")
    supplier_id = domain.string_filter(args, "proposed_supplier_id")
    event_id = domain.string_filter(args, "disruption_event_id")
    status = domain.string_filter(args, "status")
    rows = []
    for row in ordered(list(store.substitutions.values())):
        if package_id is not None and row["material_package_id"] != package_id:
            continue
        if supplier_id is not None and row["proposed_supplier_id"] != supplier_id:
            continue
        if event_id is not None and row["disruption_event_id"] != event_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paginated(rows, serial.substitution)


@bp.post("/procurement/substitution-requests/<substitution_id>/disposition")
@authorize("DesignEngineer")
def disposition_substitution(substitution_id):
    body = validate(DISPOSITION_FIELDS)
    row = domain.get_substitution(substitution_id)
    disposition = body["disposition"]
    conditions = body.get("engineer_conditions")

    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    pkg = store.packages[row["material_package_id"]]
    approving = disposition in ("APPROVED", "APPROVED_AS_NOTED")
    if approving:
        if pkg["status"] == "CLOSED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        supplier = store.suppliers[row["proposed_supplier_id"]]
        if calc.supplier_exposure(supplier, forward=True)[1] == "HIGH":
            raise ApiError("ERR_SUBSTITUTE_SUPPLIER_EXPOSED")
    if disposition == "APPROVED_AS_NOTED":
        if conditions is None or not conditions.strip():
            raise ApiError("ERR_ENGINEER_CONDITIONS_REQUIRED")
    if disposition == "REVISION_REQUESTED":
        if row["revision_round"] >= MAX_SUBSTITUTION_ROUNDS:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if conditions is not None:
        row["engineer_conditions"] = conditions

    if disposition == "APPROVED":
        row["applied_cost_delta"] = q2(row["cost_delta"])
        row["applied_schedule_delta_days"] = int(row["schedule_delta_days"])
        _apply_to_package(pkg, row["applied_cost_delta"], row["applied_schedule_delta_days"])
    elif disposition == "APPROVED_AS_NOTED":
        row["applied_cost_delta"] = q2(row["cost_delta"])
        row["applied_schedule_delta_days"] = 0
        _apply_to_package(pkg, row["applied_cost_delta"], 0)

    row["status"] = disposition
    store.touch(row)

    if approving and row["driver"] == "DISRUPTION_CONTINGENCY":
        event = store.disruptions.get(row["disruption_event_id"])
        if event is not None and event["status"] == "OPEN":
            event["status"] = "MITIGATED"
            event["mitigated_at"] = store.clock
            store.touch(event)
    return ok(serial.substitution(row))


@bp.post("/procurement/substitution-requests/<substitution_id>/resubmit")
@authorize("BuyoutManager")
def resubmit_substitution(substitution_id):
    body = validate(RESUBMIT_FIELDS)
    row = domain.get_substitution(substitution_id)
    if row["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    row["proposed_product"] = body["proposed_product"]
    row["cost_delta"] = body["cost_delta"]
    row["schedule_delta_days"] = body["schedule_delta_days"]
    row["submitted_by_user_id"] = current_user_id()
    row["revision_round"] = int(row["revision_round"]) + 1
    row["status"] = "SUBMITTED"
    store.touch(row)
    return ok(serial.substitution(row))


@bp.post("/procurement/substitution-requests/<substitution_id>/rescind")
@authorize("BuyoutManager")
def rescind_substitution(substitution_id):
    validate(RESCIND_FIELDS)
    row = domain.get_substitution(substitution_id)
    if row["status"] not in ("APPROVED", "APPROVED_AS_NOTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    pkg = store.packages[row["material_package_id"]]
    if pkg["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    _apply_to_package(
        pkg,
        -D(row["applied_cost_delta"]),
        -int(row["applied_schedule_delta_days"]),
    )
    row["applied_cost_delta"] = q2(0)
    row["applied_schedule_delta_days"] = 0
    row["status"] = "RESCINDED"
    store.touch(row)
    return ok(serial.substitution(row))
