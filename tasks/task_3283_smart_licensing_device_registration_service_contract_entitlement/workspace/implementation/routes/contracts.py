"""Routes: service contracts and contract coverages."""
from flask import Blueprint

import store
from errors import ApiError
from helpers import (Actor, authorize_resource, body, req_dt, req_enum, req_str,
                     require_row)
from respond import paginate, success
from serializers import serialize
from services import (NON_TERMINAL_RMA, bump, cancel_contract, make_row, now,
                      void_coverage)

bp = Blueprint("contracts", __name__)


def _eos_in_effect(product_family):
    for m in store.DB["milestones"].values():
        if (m["product_family"] == product_family
                and m["milestone_type"] == "END_OF_SUPPORT"
                and m["effective_date"] <= now()):
            return True
    return False


@bp.post("/api/service-contracts")
def create_contract():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    b = body()
    smart_account_id = req_str(b, "smart_account_id")
    acct = require_row("smart_accounts", smart_account_id)
    contract_number = req_str(b, "contract_number")
    service_level = req_enum(b, "service_level", {"DEPOT_RETURN", "ADVANCE_NBD", "ADVANCE_4H"})
    support_tier = req_enum(b, "support_tier", {"SOFTWARE_ONLY", "SOFTWARE_HARDWARE", "FULL"})
    start_date = req_dt(b, "start_date")
    end_date = req_dt(b, "end_date")
    authorize_resource(actor, "smart_account", acct, scope_needed="SERVICE_CONTRACTS", write=True)
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    if end_date <= start_date:
        raise ApiError("ERR_CONTRACT_WINDOW_INVALID", "end_date must be strictly after start_date")
    for c in store.DB["service_contracts"].values():
        if c["contract_number"] == contract_number:
            raise ApiError("ERR_DUPLICATE", "contract_number must be unique")
    row = make_row()
    row.update({
        "smart_account_id": smart_account_id,
        "contract_number": contract_number,
        "service_level": service_level,
        "support_tier": support_tier,
        "start_date": start_date,
        "end_date": end_date,
        "status": "ACTIVE",
    })
    store.DB["service_contracts"][row["id"]] = row
    return success(serialize(row, "service_contract"), 201)


@bp.get("/api/service-contracts/<cid>")
def get_contract(cid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager", "LogisticsAgent")
    row = require_row("service_contracts", cid)
    authorize_resource(actor, "service_contract", row, write=False)
    return success(serialize(row, "service_contract"), 200)


@bp.post("/api/service-contracts/<cid>/cancel")
def cancel_contract_endpoint(cid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin")
    row = require_row("service_contracts", cid)
    if actor.role == "AccountAdmin" and actor.user_id != row["smart_account_id"]:
        raise ApiError("ERR_FORBIDDEN")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    cov_ids = {c["id"] for c in store.DB["contract_coverages"].values()
               if c["service_contract_id"] == cid}
    for c in store.DB["rma_cases"].values():
        if c["contract_coverage_id"] in cov_ids and c["status"] in NON_TERMINAL_RMA:
            raise ApiError("ERR_INVALID_STATE", "contract has non-terminal RMA cases")
    cancel_contract(row)
    return success(serialize(row, "service_contract"), 200)


@bp.get("/api/service-contracts/<cid>/coverages")
def list_contract_coverages(cid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager", "LogisticsAgent")
    row = require_row("service_contracts", cid)
    authorize_resource(actor, "service_contract", row, write=False)
    rows = sorted([c for c in store.DB["contract_coverages"].values()
                   if c["service_contract_id"] == cid], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "contract_coverage") for r in page], 200, meta)


# ------------------------------------------------------------ coverages

@bp.post("/api/contract-coverages")
def create_coverage():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    b = body()
    service_contract_id = req_str(b, "service_contract_id")
    contract = require_row("service_contracts", service_contract_id)
    device_id = req_str(b, "device_id")
    dev = require_row("devices", device_id)
    authorize_resource(actor, "service_contract", contract, scope_needed="SERVICE_CONTRACTS", write=True)
    acct = store.DB["smart_accounts"].get(contract["smart_account_id"])
    if acct is None or acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    if contract["status"] != "ACTIVE" or not (contract["start_date"] <= now() < contract["end_date"]):
        raise ApiError("ERR_CONTRACT_WINDOW_INVALID")
    if _eos_in_effect(dev["product_family"]):
        raise ApiError("ERR_PRODUCT_END_OF_SUPPORT")
    for cov in store.DB["contract_coverages"].values():
        if cov["device_id"] == device_id and cov["status"] == "ACTIVE":
            raise ApiError("ERR_COVERAGE_OVERLAP")
    row = make_row()
    row.update({
        "service_contract_id": service_contract_id,
        "device_id": device_id,
        "status": "ACTIVE",
        "covered_from": now(),
    })
    store.DB["contract_coverages"][row["id"]] = row
    return success(serialize(row, "contract_coverage"), 201)


@bp.get("/api/contract-coverages/<cid>")
def get_coverage(cid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager", "LogisticsAgent")
    row = require_row("contract_coverages", cid)
    authorize_resource(actor, "contract_coverage", row, write=False)
    return success(serialize(row, "contract_coverage"), 200)


@bp.get("/api/contract-coverages/<cid>/rma-cases")
def list_coverage_rmas(cid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager", "LogisticsAgent")
    row = require_row("contract_coverages", cid)
    authorize_resource(actor, "contract_coverage", row, write=False)
    from services import refresh_rma_sla
    rows = sorted([c for c in store.DB["rma_cases"].values()
                   if c["contract_coverage_id"] == cid], key=lambda r: r["created_at"])
    for c in rows:
        refresh_rma_sla(c)
    page, meta = paginate(rows)
    return success([serialize(r, "rma_case") for r in page], 200, meta)


@bp.post("/api/contract-coverages/<cid>/release")
def release_coverage(cid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("contract_coverages", cid)
    authorize_resource(actor, "contract_coverage", row, scope_needed="SERVICE_CONTRACTS", write=True)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    for c in store.DB["rma_cases"].values():
        if c["contract_coverage_id"] == cid and c["status"] in NON_TERMINAL_RMA:
            raise ApiError("ERR_INVALID_STATE", "coverage has non-terminal RMA cases")
    row["status"] = "RELEASED"
    bump(row)
    return success(serialize(row, "contract_coverage"), 200)
