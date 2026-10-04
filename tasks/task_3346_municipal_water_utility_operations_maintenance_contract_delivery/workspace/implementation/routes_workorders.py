"""Work order endpoints — PRD 3.6."""
from datetime import timedelta

import calc
import services
from core import (ApiError, DB, apply, arg, body, create, dec, endpoint, field,
                  g, get, now, now_iso, ordered, own, paginate, parse_dt, public,
                  set_status, str_field)

WORK_TYPES = ("PREVENTIVE", "CORRECTIVE", "EMERGENCY", "INSPECTION")
CLOSURE_NARRATIVE_MIN = 40
REPORTAGE_DAYS = 5
BACKDATE_LIMIT_DAYS = 7
CAPITAL_SERVICE_FRACTION = "0.6"


def work_order_or_404(work_order_id):
    return get("work_orders", work_order_id, "ERR_WORK_ORDER_NOT_FOUND")


def load(work_order_id):
    work_order = work_order_or_404(work_order_id)
    own(work_order)
    return work_order


def mutable(work_order):
    if work_order["status"] == "CLOSED":
        raise ApiError("ERR_CLOSED_WORK_ORDER_IMMUTABLE")
    if work_order["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def work_orders_of(contract_id=None, asset_id=None, status=None, work_type=None):
    out = []
    for work_order in DB["work_orders"].values():
        if contract_id is not None and work_order["contract_id"] != contract_id:
            continue
        if asset_id is not None and work_order["asset_id"] != asset_id:
            continue
        if status is not None and work_order["status"] != status:
            continue
        if work_type is not None and work_order["work_type"] != work_type:
            continue
        out.append(work_order)
    return out


def _new_work_order(asset, work_type, estimated_cost):
    work_order = create("work_orders",
                        asset_id=asset["id"],
                        contract_id=asset["contract_id"],
                        work_type=work_type,
                        expense_class="PENDING_CLASSIFICATION",
                        estimated_cost_cents=int(estimated_cost),
                        actual_cost_cents=0,
                        cost_variance_cents=0,
                        documentation_complete=False,
                        submitted_to_municipality_at=None,
                        status="DRAFT")
    apply(work_order, expense_class=calc.expense_class(work_order, asset))
    return work_order


def _validate_creation(data):
    work_type = str_field(data, "work_type")
    if work_type not in WORK_TYPES:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown work_type.")
    try:
        estimated = int(field(data, "estimated_cost_cents"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "estimated_cost_cents must be an integer.")
    if estimated < 0:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "estimated_cost_cents must be zero or greater.")
    return work_type, estimated


# --------------------------------------------------------------------------
# creation / listing
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>/work-orders", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_contract_work_orders(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    items = work_orders_of(contract_id=contract["id"], asset_id=arg("asset_id"),
                           status=arg("status"), work_type=arg("work_type"))
    return paginate(ordered(items))


@endpoint("/contracts/<id>/work-orders", ["POST"], ["OperatorAdmin"], status=201)
def ingest_work_order(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    data = body()
    asset = get("assets", str_field(data, "asset_id"), "ERR_ASSET_NOT_FOUND")
    work_type, estimated = _validate_creation(data)
    if data.get("reported_at") is not None:
        reported = parse_dt(data["reported_at"])
        if now() - reported > timedelta(days=BACKDATE_LIMIT_DAYS):
            raise ApiError("ERR_BACKDATED_RECORD_REJECTED")
    if asset["contract_id"] != contract["id"]:
        raise ApiError("ERR_ASSET_CONTRACT_MISMATCH")
    return _new_work_order(asset, work_type, estimated)


@endpoint("/assets/<id>/work-orders", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_asset_work_orders(id):
    asset = get("assets", id, "ERR_ASSET_NOT_FOUND")
    own(asset)
    items = work_orders_of(asset_id=asset["id"], status=arg("status"), work_type=arg("work_type"))
    return paginate(ordered(items))


@endpoint("/assets/<id>/work-orders", ["POST"], ["OperatorAdmin"], status=201)
def raise_work_order(id):
    asset = get("assets", id, "ERR_ASSET_NOT_FOUND")
    own(asset)
    work_type, estimated = _validate_creation(body())
    return _new_work_order(asset, work_type, estimated)


@endpoint("/work-orders/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_work_order(id):
    return load(id)


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------
@endpoint("/work-orders/<id>/schedule", ["POST"], ["OperatorAdmin"])
def schedule_work_order(id):
    work_order = load(id)
    mutable(work_order)
    if work_order["status"] != "DRAFT":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    if int(work_order.get("estimated_cost_cents") or 0) <= 0:
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    contract = DB["contracts"][work_order["contract_id"]]
    if contract["status"] not in ("MOBILIZING", "OPERATING", "UNDER_REVIEW", "RENEWED"):
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    asset = DB["assets"].get(work_order["asset_id"])
    if asset is not None:
        apply(work_order, expense_class=calc.expense_class(work_order, asset))
    set_status(work_order, "SCHEDULED")
    return work_order


@endpoint("/work-orders/<id>/start", ["POST"], ["OperatorAdmin"])
def start_work_order(id):
    work_order = load(id)
    mutable(work_order)
    if work_order["status"] != "SCHEDULED":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    if work_order["expense_class"] == "REJECTED_AS_CAPITAL":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    asset = DB["assets"].get(work_order["asset_id"])
    if asset is not None and calc.capital_expense_class(work_order["expense_class"]):
        age_days = (now() - _install_instant(asset)).total_seconds() / 86400.0
        required = dec(CAPITAL_SERVICE_FRACTION) * dec(asset["useful_life_years"]) * 365
        if dec(age_days) < required:
            raise ApiError("ERR_CAPITAL_THRESHOLD_NOT_MET")
    set_status(work_order, "IN_PROGRESS")
    return work_order


def _install_instant(asset):
    from datetime import datetime, timezone
    return datetime(int(asset["install_year"]), 1, 1, tzinfo=timezone.utc)


@endpoint("/work-orders/<id>/pause", ["POST"], ["OperatorAdmin"])
def pause_work_order(id):
    work_order = load(id)
    mutable(work_order)
    if work_order["status"] != "IN_PROGRESS":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    str_field(body(), "pause_reason")
    set_status(work_order, "PAUSED")
    return work_order


@endpoint("/work-orders/<id>/resume", ["POST"], ["OperatorAdmin"])
def resume_work_order(id):
    work_order = load(id)
    mutable(work_order)
    if work_order["status"] not in ("PAUSED", "AWAITING_PARTS"):
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    set_status(work_order, "IN_PROGRESS")
    return work_order


@endpoint("/work-orders/<id>/await-parts", ["POST"], ["OperatorAdmin"])
def await_parts(id):
    work_order = load(id)
    mutable(work_order)
    if work_order["status"] != "IN_PROGRESS":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    contract = DB["contracts"][work_order["contract_id"]]
    if contract["status"] != "OPERATING":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    if int(work_order.get("actual_cost_cents") or 0) <= 0:
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    variance = int(work_order["actual_cost_cents"]) - int(work_order["estimated_cost_cents"])
    set_status(work_order, "AWAITING_PARTS", cost_variance_cents=variance)
    return work_order


@endpoint("/work-orders/<id>/complete", ["POST"], ["OperatorAdmin"])
def complete_work_order(id):
    work_order = load(id)
    mutable(work_order)
    if work_order["status"] not in ("IN_PROGRESS", "PAUSED", "RETURNED"):
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    data = body()
    narrative = data.get("closure_narrative")
    labour = data.get("labour_hours")
    materials = data.get("materials_cents")
    documented = bool(narrative) and len(str(narrative)) >= CLOSURE_NARRATIVE_MIN \
        and labour is not None and materials is not None
    if not documented:
        apply(work_order, documentation_complete=False)
        raise ApiError("ERR_WORK_ORDER_DOCUMENTATION_INCOMPLETE", extra=public(work_order))
    actual = calc.work_order_cost(labour, materials)
    variance = actual - int(work_order["estimated_cost_cents"])
    set_status(work_order, "COMPLETED",
               actual_cost_cents=actual,
               cost_variance_cents=variance,
               documentation_complete=True,
               _completed_by=g.actor_id)
    return work_order


@endpoint("/work-orders/<id>/verify", ["POST"], ["MunicipalityAdmin"])
def verify_work_order(id):
    work_order = load(id)
    mutable(work_order)
    if work_order["status"] != "COMPLETED":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    if not work_order.get("documentation_complete"):
        raise ApiError("ERR_WORK_ORDER_DOCUMENTATION_INCOMPLETE", extra=public(work_order))
    if work_order.get("_completed_by") and work_order["_completed_by"] == g.actor_id:
        raise ApiError("ERR_CROSS_TENANT_DENIED")
    delta = dec(field(body(), "condition_delta"))
    set_status(work_order, "VERIFIED", submitted_to_municipality_at=now_iso())
    asset = DB["assets"].get(work_order["asset_id"])
    if asset is not None:
        services.set_condition(asset, dec(asset.get("condition_score") or 0) + delta)
        if asset["status"] == "IN_SERVICE" and calc.condition_below(asset.get("condition_score"), 40.0):
            services.flag_asset(asset)
    return work_order


@endpoint("/work-orders/<id>/return", ["POST"], ["MunicipalityAdmin"])
def return_work_order(id):
    work_order = load(id)
    mutable(work_order)
    data = body()
    str_field(data, "return_reason")
    if work_order["status"] == "COMPLETED":
        if not (not work_order.get("documentation_complete")
                or work_order["expense_class"] == "PENDING_CLASSIFICATION"):
            raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
        set_status(work_order, "RETURNED", actual_cost_cents=0, cost_variance_cents=0)
    elif work_order["status"] == "VERIFIED":
        set_status(work_order, "RETURNED", documentation_complete=False)
    else:
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    return work_order


@endpoint("/work-orders/<id>/close", ["POST"], ["MunicipalityAdmin"])
def close_work_order(id):
    work_order = load(id)
    mutable(work_order)
    if work_order["status"] != "VERIFIED":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    submitted = parse_dt(work_order.get("submitted_to_municipality_at"))
    if submitted is None or now() <= submitted + timedelta(days=REPORTAGE_DAYS):
        raise ApiError("ERR_REPORTAGE_PERIOD_OPEN")
    if work_order["expense_class"] == "PENDING_CLASSIFICATION":
        raise ApiError("ERR_EXPENSE_CLASS_UNRESOLVED")
    set_status(work_order, "CLOSED")
    return work_order


@endpoint("/work-orders/<id>/cancel", ["POST"], ["OperatorAdmin", "MunicipalityAdmin"])
def cancel_work_order(id):
    work_order = load(id)
    mutable(work_order)
    status = work_order["status"]
    if status == "DRAFT":
        if g.actor_role != "OperatorAdmin":
            raise ApiError("ERR_ROLE_FORBIDDEN")
        set_status(work_order, "CANCELLED")
    elif status == "SCHEDULED":
        if g.actor_role != "MunicipalityAdmin":
            raise ApiError("ERR_ROLE_FORBIDDEN")
        str_field(body(), "cancel_reason")
        if int(work_order.get("actual_cost_cents") or 0) != 0 or work_order.get("documentation_complete"):
            raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
        set_status(work_order, "CANCELLED")
    else:
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    return work_order
