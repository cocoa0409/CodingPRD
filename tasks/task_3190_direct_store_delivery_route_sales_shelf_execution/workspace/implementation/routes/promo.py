"""Promotional agreements and promo executions."""

from datetime import date

from flask import Blueprint, request

import db as store
from errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_INVALID_STATE,
    ERR_PENDING_EXECUTION_EXISTS,
    ERR_PROMO_WINDOW_OVERLAP,
    ERR_ROUTE_DAY_NOT_IN_PROGRESS,
    ERR_STALE_VERSION,
    ERR_STORE_NOT_ACTIVE,
    ERR_STORE_SCOPE_VIOLATION,
    ERR_VALIDATION,
    err,
)
from helpers import (
    auth,
    body,
    filter_sort_page,
    get,
    new_record,
    opt_str,
    req_date,
    req_enum,
    req_field,
    req_int,
    req_str,
    require_role,
    touch,
)
from response import list_response, success

bp = Blueprint("promo", __name__)


# ---------------------------------------------------------------------------
# promo agreements
# ---------------------------------------------------------------------------

@bp.post("/dsd/promo-agreements")
def create_agreement():
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    data = body()
    store_id = req_str(data, "store_id")
    product_id = req_str(data, "product_id")
    window_start = req_date(data, "window_start")
    window_end = req_date(data, "window_end")
    display_type = req_enum(data, "display_type", ("ENDCAP", "AISLE", "DUMP_BIN", "COUNTER"))
    rebate = req_int(data, "rebate_cents")
    st = get("stores", store_id)
    get("products", product_id)
    if rebate < 0:
        raise err(ERR_VALIDATION, "rebate_cents must be >= 0")
    if date.fromisoformat(window_end) <= date.fromisoformat(window_start):
        raise err(ERR_VALIDATION, "window_end must be after window_start")
    if st["status"] != "ACTIVE":
        raise err(ERR_STORE_NOT_ACTIVE, "Store is not ACTIVE")
    # half-open window overlap against SCHEDULED/ACTIVE/COMPLETED for same store+product
    for other in store.db["promo_agreements"].values():
        if (
            other["store_id"] == store_id
            and other["product_id"] == product_id
            and other["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED")
            and other["window_start"] < window_end
            and window_start < other["window_end"]
        ):
            raise err(ERR_PROMO_WINDOW_OVERLAP, "Agreement window overlaps an existing agreement")
    rec = new_record()
    rec.update(
        store_id=store_id,
        product_id=product_id,
        window_start=window_start,
        window_end=window_end,
        display_type=display_type,
        rebate_cents=rebate,
        status="SCHEDULED",
    )
    store.db["promo_agreements"][rec["id"]] = rec
    return success(rec, 201)


@bp.get("/dsd/promo-agreements/<agreementId>")
def get_agreement(agreementId):
    auth()
    return success(get("promo_agreements", agreementId), 200)


@bp.get("/dsd/promo-agreements")
def list_agreements():
    auth()
    items, limit, offset, total = filter_sort_page(
        "promo_agreements",
        {
            "store_id": request.args.get("store_id"),
            "product_id": request.args.get("product_id"),
            "status": request.args.get("status"),
        },
    )
    return list_response(items, limit, offset, total)


@bp.post("/dsd/promo-agreements/<agreementId>/activate")
def activate_agreement(agreementId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("promo_agreements", agreementId)
    if rec["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Agreement is not SCHEDULED")
    clock_date = store.clock.date()
    if not (
        date.fromisoformat(rec["window_start"])
        <= clock_date
        < date.fromisoformat(rec["window_end"])
    ):
        raise err(ERR_AGREEMENT_NOT_ACTIVE, "Logical clock is outside the agreement window")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(rec, 200)


@bp.post("/dsd/promo-agreements/<agreementId>/breach")
def breach_agreement(agreementId):
    uid, role = auth()
    require_role(role, "RouteSupervisor")
    rec = get("promo_agreements", agreementId)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Agreement is not ACTIVE")
    rec["status"] = "BREACHED"
    touch(rec)
    return success(rec, 200)


# ---------------------------------------------------------------------------
# promo executions
# ---------------------------------------------------------------------------

@bp.post("/dsd/promo-executions")
def create_promo_execution():
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    data = body()
    agreement_id = req_str(data, "agreement_id")
    route_day_id = req_str(data, "route_day_id")
    photo_url = req_str(data, "photo_url")
    agreement = get("promo_agreements", agreement_id)
    day = get("route_days", route_day_id)
    expected = data.get("expected_promo_agreement_version")
    if expected is not None and expected != agreement["version"]:
        raise err(ERR_STALE_VERSION, "Agreement version has advanced")
    if agreement["status"] != "ACTIVE":
        raise err(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE")
    if day["status"] != "IN_PROGRESS":
        raise err(ERR_ROUTE_DAY_NOT_IN_PROGRESS, "Route day is not IN_PROGRESS")
    for ex in store.db["promo_executions"].values():
        if ex["agreement_id"] == agreement_id and ex["status"] == "SUBMITTED":
            raise err(ERR_PENDING_EXECUTION_EXISTS, "A SUBMITTED execution already exists")
    rec = new_record()
    rec.update(
        agreement_id=agreement_id,
        route_day_id=route_day_id,
        photo_url=photo_url,
        built_by_user_id=uid,
        verified_by_user_id=None,
        reject_reason=None,
        status="SUBMITTED",
    )
    store.db["promo_executions"][rec["id"]] = rec
    touch(agreement)
    return success(rec, 201)


@bp.get("/dsd/promo-executions/<execId>")
def get_promo_execution(execId):
    auth()
    return success(get("promo_executions", execId), 200)


@bp.get("/dsd/promo-executions")
def list_promo_executions():
    auth()
    items, limit, offset, total = filter_sort_page(
        "promo_executions",
        {
            "agreement_id": request.args.get("agreement_id"),
            "route_day_id": request.args.get("route_day_id"),
        },
    )
    return list_response(items, limit, offset, total)


def _check_verifier_scope(uid, role, agreement):
    if role == "StoreManager" and uid != agreement["store_id"]:
        raise err(ERR_STORE_SCOPE_VIOLATION, "Store manager is not scoped to this store")


@bp.post("/dsd/promo-executions/<execId>/verify")
def verify_promo_execution(execId):
    uid, role = auth()
    require_role(role, "StoreManager", "RouteSupervisor")
    rec = get("promo_executions", execId)
    agreement = get("promo_agreements", rec["agreement_id"])
    _check_verifier_scope(uid, role, agreement)
    if rec["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Execution is not SUBMITTED")
    if agreement["status"] != "ACTIVE":
        raise err(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE")
    rec["status"] = "VERIFIED"
    rec["verified_by_user_id"] = uid
    touch(rec)
    agreement["status"] = "COMPLETED"
    touch(agreement)
    st = get("stores", agreement["store_id"])
    st["promo_rebate_balance_cents"] += agreement["rebate_cents"]
    touch(st)
    return success(rec, 200)


@bp.post("/dsd/promo-executions/<execId>/reject")
def reject_promo_execution(execId):
    uid, role = auth()
    require_role(role, "StoreManager", "RouteSupervisor")
    rec = get("promo_executions", execId)
    agreement = get("promo_agreements", rec["agreement_id"])
    _check_verifier_scope(uid, role, agreement)
    if rec["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Execution is not SUBMITTED")
    data = body()
    reason = opt_str(data, "reject_reason")
    if not reason:
        raise err(ERR_VALIDATION, "reject_reason is required")
    rec["status"] = "REJECTED"
    rec["reject_reason"] = reason
    rec["verified_by_user_id"] = uid
    touch(rec)
    return success(rec, 200)
