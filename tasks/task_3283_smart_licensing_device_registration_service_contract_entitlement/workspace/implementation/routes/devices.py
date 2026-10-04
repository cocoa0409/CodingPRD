"""Routes: devices, usage reports, license assignments."""
from flask import Blueprint

import store
from errors import ApiError
from helpers import (Actor, authorize_resource, body, req_dt, req_int, req_str,
                     require_row)
from respond import paginate, success
from serializers import serialize
from services import bump, make_row, now, recompute_pool

bp = Blueprint("devices", __name__)


def _va_of(device):
    return store.DB["virtual_accounts"].get(device["virtual_account_id"])


def _acct_of_va(va):
    return store.DB["smart_accounts"].get(va["smart_account_id"]) if va else None


def _eol_in_effect(product_family):
    for m in store.DB["milestones"].values():
        if (m["product_family"] == product_family
                and m["milestone_type"] == "END_OF_LIFE"
                and m["effective_date"] <= now()):
            return True
    return False


@bp.post("/api/devices")
def create_device():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    b = body()
    virtual_account_id = req_str(b, "virtual_account_id")
    va = require_row("virtual_accounts", virtual_account_id)
    serial_number = req_str(b, "serial_number")
    product_family = req_str(b, "product_family")
    authorize_resource(actor, "virtual_account", va, scope_needed="LICENSING", write=True)
    for d in store.DB["devices"].values():
        if d["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE", "serial_number must be globally unique")
    row = make_row()
    row.update({
        "virtual_account_id": virtual_account_id,
        "serial_number": serial_number,
        "product_family": product_family,
        "registration_state": "PENDING",
        "registered_at": None,
        "last_sync_at": None,
    })
    store.DB["devices"][row["id"]] = row
    return success(serialize(row, "device"), 201)


@bp.get("/api/devices/<did>")
def get_device(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager", "LogisticsAgent")
    row = require_row("devices", did)
    authorize_resource(actor, "device", row, write=False)
    return success(serialize(row, "device"), 200)


@bp.post("/api/devices/<did>/activate")
def activate_device(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("devices", did)
    authorize_resource(actor, "device", row, scope_needed="LICENSING", write=True)
    if row["registration_state"] not in ("PENDING", "DEREGISTERED"):
        raise ApiError("ERR_INVALID_STATE")
    va = _va_of(row)
    acct = _acct_of_va(va)
    if va is None or va["status"] != "ACTIVE" or acct is None or acct["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    if acct["compliance_posture"] == "NON_COMPLIANT":
        raise ApiError("ERR_ACCOUNT_NON_COMPLIANT")
    if _eol_in_effect(row["product_family"]):
        raise ApiError("ERR_PRODUCT_END_OF_LIFE")
    row["registration_state"] = "REGISTERED"
    row["registered_at"] = now()
    row["last_sync_at"] = now()
    bump(row)
    return success(serialize(row, "device"), 200)


@bp.post("/api/devices/<did>/deregister")
def deregister_device(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("devices", did)
    authorize_resource(actor, "device", row, scope_needed="LICENSING", write=True)
    if row["registration_state"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE")
    from services import NON_TERMINAL_RMA
    for c in store.DB["rma_cases"].values():
        if c["device_id"] == did and c["status"] in NON_TERMINAL_RMA:
            raise ApiError("ERR_INVALID_STATE", "device has a non-terminal RMA case")
    touched_pools = []
    for a in store.DB["assignments"].values():
        if a["device_id"] == did and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            bump(a)
            pool = store.DB["license_pools"].get(a["license_pool_id"])
            if pool is not None and pool["id"] not in touched_pools:
                touched_pools.append(pool["id"])
    for pid in touched_pools:
        recompute_pool(store.DB["license_pools"][pid])
    row["registration_state"] = "DEREGISTERED"
    bump(row)
    return success(serialize(row, "device"), 200)


@bp.post("/api/devices/<did>/retire")
def retire_device(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("devices", did)
    authorize_resource(actor, "device", row, scope_needed="LICENSING", write=True)
    if row["registration_state"] != "DEREGISTERED":
        raise ApiError("ERR_INVALID_STATE")
    for cov in store.DB["contract_coverages"].values():
        if cov["device_id"] == did and cov["status"] == "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "device has an ACTIVE coverage")
    row["registration_state"] = "RETIRED"
    bump(row)
    return success(serialize(row, "device"), 200)


@bp.get("/api/devices/<did>/assignments")
def list_device_assignments(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("devices", did)
    authorize_resource(actor, "device", row, write=False)
    rows = sorted([a for a in store.DB["assignments"].values()
                   if a["device_id"] == did], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "assignment") for r in page], 200, meta)


@bp.get("/api/devices/<did>/usage-reports")
def list_device_reports(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("devices", did)
    authorize_resource(actor, "device", row, write=False)
    rows = sorted([r for r in store.DB["usage_reports"].values()
                   if r["device_id"] == did], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "usage_report") for r in page], 200, meta)


@bp.get("/api/devices/<did>/coverages")
def list_device_coverages(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("devices", did)
    authorize_resource(actor, "device", row, write=False)
    rows = sorted([c for c in store.DB["contract_coverages"].values()
                   if c["device_id"] == did], key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "contract_coverage") for r in page], 200, meta)


@bp.get("/api/devices/<did>/rma-cases")
def list_device_rmas(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager", "LogisticsAgent")
    row = require_row("devices", did)
    authorize_resource(actor, "device", row, write=False)
    from services import refresh_rma_sla
    rows = sorted([c for c in store.DB["rma_cases"].values()
                   if c["device_id"] == did], key=lambda r: r["created_at"])
    for c in rows:
        refresh_rma_sla(c)
    page, meta = paginate(rows)
    return success([serialize(r, "rma_case") for r in page], 200, meta)


@bp.post("/api/devices/<did>/usage-reports")
def submit_usage_report(did):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("devices", did)
    b = body()
    reported_at = req_dt(b, "reported_at")
    lines = b.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ApiError("ERR_INVALID_REQUEST", "lines must be a non-empty array")
    norm_lines = []
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each line must be an object")
        pid = line.get("license_pool_id")
        qty = line.get("quantity")
        if not isinstance(pid, str) or not pid:
            raise ApiError("ERR_INVALID_REQUEST", "line.license_pool_id is required")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            raise ApiError("ERR_INVALID_REQUEST", "line.quantity must be a non-negative integer")
        norm_lines.append({"license_pool_id": pid, "quantity": qty})
    authorize_resource(actor, "device", row, scope_needed="LICENSING", write=True)
    if row["registration_state"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", "usage reports are accepted only from REGISTERED devices")
    # Every line's pool must exist and belong to the device's virtual account.
    for line in norm_lines:
        pool = store.DB["license_pools"].get(line["license_pool_id"])
        if pool is None:
            raise ApiError("ERR_NOT_FOUND", "line license_pool_id not found")
        if pool["virtual_account_id"] != row["virtual_account_id"]:
            raise ApiError("ERR_REPORT_POOL_MISMATCH")
    # Staleness: strictly older than last accepted report -> REJECTED.
    last_accepted = None
    for rep in store.DB["usage_reports"].values():
        if rep["device_id"] == did and rep["status"] == "ACCEPTED":
            if last_accepted is None or rep["reported_at"] > last_accepted:
                last_accepted = rep["reported_at"]
    report = make_row(with_version=False)
    report.update({
        "device_id": did,
        "reported_at": reported_at,
        "lines": norm_lines,
        "status": "ACCEPTED",
        "rejection_reason": None,
    })
    if last_accepted is not None and reported_at < last_accepted:
        report["status"] = "REJECTED"
        report["rejection_reason"] = "ERR_STALE_REPORT"
        store.DB["usage_reports"][report["id"]] = report
        raise ApiError("ERR_STALE_REPORT")
    store.DB["usage_reports"][report["id"]] = report
    row["last_sync_at"] = now()
    bump(row)
    touched = {line["license_pool_id"] for line in norm_lines}
    for pid in touched:
        recompute_pool(store.DB["license_pools"][pid])
    return success(serialize(report, "usage_report"), 201)


# ------------------------------------------------------- license assignments

@bp.post("/api/license-assignments")
def create_assignment():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    b = body()
    device_id = req_str(b, "device_id")
    dev = require_row("devices", device_id)
    license_pool_id = req_str(b, "license_pool_id")
    pool = require_row("license_pools", license_pool_id)
    quantity = req_int(b, "quantity")
    if quantity < 1:
        raise ApiError("ERR_INVALID_QUANTITY", "quantity must be >= 1")
    authorize_resource(actor, "device", dev, scope_needed="LICENSING", write=True)
    if dev["registration_state"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", "assignments require a REGISTERED device")
    if pool["virtual_account_id"] != dev["virtual_account_id"]:
        raise ApiError("ERR_INVALID_REQUEST", "pool must belong to the device's virtual account")
    row = make_row()
    row.update({
        "device_id": device_id,
        "license_pool_id": license_pool_id,
        "quantity": quantity,
        "status": "ACTIVE",
        "assigned_at": now(),
    })
    store.DB["assignments"][row["id"]] = row
    recompute_pool(pool)
    return success(serialize(row, "assignment"), 201)


@bp.post("/api/license-assignments/<aid>/release")
def release_assignment(aid):
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    row = require_row("assignments", aid)
    authorize_resource(actor, "assignment", row, scope_needed="LICENSING", write=True)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "RELEASED"
    bump(row)
    pool = store.DB["license_pools"].get(row["license_pool_id"])
    if pool is not None:
        recompute_pool(pool)
    return success(serialize(row, "assignment"), 200)


# ------------------------------------------------------ lifecycle milestones

@bp.post("/api/lifecycle-milestones")
def create_milestone():
    actor = Actor()
    actor.require_roles("PlatformAdmin")
    b = body()
    product_family = req_str(b, "product_family")
    from helpers import req_enum
    milestone_type = req_enum(b, "milestone_type", {"END_OF_SALE", "END_OF_LIFE", "END_OF_SUPPORT"})
    effective_date = req_dt(b, "effective_date")
    row = make_row(with_version=False)
    row.update({
        "product_family": product_family,
        "milestone_type": milestone_type,
        "effective_date": effective_date,
    })
    store.DB["milestones"][row["id"]] = row
    return success(serialize(row, "milestone"), 201)


@bp.get("/api/lifecycle-milestones")
def list_milestones():
    actor = Actor()
    actor.require_roles("PlatformAdmin", "AccountAdmin", "PartnerManager")
    from flask import request
    rows = list(store.DB["milestones"].values())
    pf = request.args.get("product_family")
    if pf:
        rows = [m for m in rows if m["product_family"] == pf]
    rows = sorted(rows, key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r, "milestone") for r in page], 200, meta)
