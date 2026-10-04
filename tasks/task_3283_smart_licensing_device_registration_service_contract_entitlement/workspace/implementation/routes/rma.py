"""Routes: RMA cases with branch-aware logistics transitions."""
from datetime import timedelta

from flask import Blueprint

import store
from errors import ApiError
from helpers import Actor, authorize_resource, body, req_str, require_row
from respond import paginate, success
from serializers import serialize
from services import (ADVANCE_4H_SECONDS, ADVANCE_NBD_SECONDS,
                      DEPOT_RETURN_WINDOW_DAYS, bump, make_row, now,
                      refresh_rma_sla)

bp = Blueprint("rma", __name__)


def _contract_of(case_or_cov):
    cov = store.DB["contract_coverages"].get(case_or_cov["contract_coverage_id"] if "contract_coverage_id" in case_or_cov else case_or_cov["id"])
    return store.DB["service_contracts"].get(cov["service_contract_id"]) if cov else None


@bp.post("/api/rma-cases")
def create_rma():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    b = body()
    contract_coverage_id = req_str(b, "contract_coverage_id")
    cov = require_row("contract_coverages", contract_coverage_id)
    failure_description = req_str(b, "failure_description")
    authorize_resource(actor, "contract_coverage", cov, scope_needed="SERVICE_CONTRACTS", write=True)
    contract = store.DB["service_contracts"].get(cov["service_contract_id"])
    if (cov["status"] != "ACTIVE" or contract is None or contract["status"] != "ACTIVE"
            or not (contract["start_date"] <= now() < contract["end_date"])
            or contract["support_tier"] not in ("SOFTWARE_HARDWARE", "FULL")):
        raise ApiError("ERR_NO_ACTIVE_COVERAGE")
    row = make_row()
    level = contract["service_level"]
    if level == "ADVANCE_4H":
        ship_by = now() + timedelta(seconds=ADVANCE_4H_SECONDS)
    elif level == "ADVANCE_NBD":
        ship_by = now() + timedelta(seconds=ADVANCE_NBD_SECONDS)
    else:
        ship_by = None
    row.update({
        "contract_coverage_id": contract_coverage_id,
        "device_id": cov["device_id"],
        "failure_description": failure_description,
        "status": "OPENED",
        "ship_by": ship_by,
        "opened_at": now(),
        "delivered_at": None,
        "sla_breached": False,
    })
    store.DB["rma_cases"][row["id"]] = row
    return success(serialize(row, "rma_case"), 201)


@bp.get("/api/rma-cases/<rid>")
def get_rma(rid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager", "LogisticsAgent")
    row = require_row("rma_cases", rid)
    authorize_resource(actor, "rma_case", row, write=False)
    refresh_rma_sla(row)
    return success(serialize(row, "rma_case"), 200)


@bp.post("/api/rma-cases/<rid>/ship-replacement")
def ship_replacement(rid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "LogisticsAgent")
    row = require_row("rma_cases", rid)
    contract = _contract_of(row)
    level = contract["service_level"] if contract else None
    if row["status"] == "OPENED":
        if level not in ("ADVANCE_NBD", "ADVANCE_4H"):
            raise ApiError("ERR_RMA_BRANCH_VIOLATION")
        row["status"] = "REPLACEMENT_SHIPPED"
        if row["ship_by"] is not None and now() > row["ship_by"]:
            row["sla_breached"] = True
    elif row["status"] == "DEFECTIVE_RETURNED":
        if level != "DEPOT_RETURN":
            raise ApiError("ERR_RMA_BRANCH_VIOLATION")
        row["status"] = "REPLACEMENT_SHIPPED"
    else:
        raise ApiError("ERR_INVALID_STATE")
    bump(row)
    return success(serialize(row, "rma_case"), 200)


@bp.post("/api/rma-cases/<rid>/confirm-delivery")
def confirm_delivery(rid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "LogisticsAgent")
    row = require_row("rma_cases", rid)
    if row["status"] != "REPLACEMENT_SHIPPED":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "REPLACEMENT_DELIVERED"
    row["delivered_at"] = now()
    bump(row)
    return success(serialize(row, "rma_case"), 200)


@bp.post("/api/rma-cases/<rid>/receive-defective")
def receive_defective(rid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "LogisticsAgent")
    row = require_row("rma_cases", rid)
    contract = _contract_of(row)
    level = contract["service_level"] if contract else None
    if row["status"] == "OPENED":
        if level != "DEPOT_RETURN":
            raise ApiError("ERR_RMA_BRANCH_VIOLATION")
        row["status"] = "DEFECTIVE_RETURNED"
    elif row["status"] == "REPLACEMENT_DELIVERED":
        if level not in ("ADVANCE_NBD", "ADVANCE_4H"):
            raise ApiError("ERR_RMA_BRANCH_VIOLATION")
        if row.get("delivered_at") is not None:
            deadline = row["delivered_at"] + timedelta(days=DEPOT_RETURN_WINDOW_DAYS)
            if now() > deadline:
                row["sla_breached"] = True
        row["status"] = "DEFECTIVE_RETURNED"
    else:
        raise ApiError("ERR_INVALID_STATE")
    bump(row)
    return success(serialize(row, "rma_case"), 200)


@bp.post("/api/rma-cases/<rid>/close")
def close_rma(rid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "LogisticsAgent")
    row = require_row("rma_cases", rid)
    if row["status"] != "DEFECTIVE_RETURNED" or row.get("delivered_at") is None:
        raise ApiError("ERR_INVALID_STATE", "close requires DEFECTIVE_RETURNED after delivery")
    row["status"] = "CLOSED"
    bump(row)
    return success(serialize(row, "rma_case"), 200)


@bp.post("/api/rma-cases/<rid>/cancel")
def cancel_rma(rid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("rma_cases", rid)
    authorize_resource(actor, "rma_case", row, scope_needed="SERVICE_CONTRACTS", write=True)
    if row["status"] != "OPENED":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "CANCELLED"
    bump(row)
    return success(serialize(row, "rma_case"), 200)
