"""Programme configuration: the service catalogue and the jurisdiction policy table."""
from decimal import Decimal

from flask import Blueprint

import envelope
import fields
import store
from errors import ApiError
from fields import A, B, E, I, N, S, T, auth, body, need, pagination, validate

bp = Blueprint("config", __name__)

READ_ROLES = fields.ALL_ROLES

CATEGORY_CREATE = [
    S("code", maxlen=32),
    S("name", maxlen=120),
    E("trade_code", fields.TRADE_CODES),
    E("unit_of_measure", fields.UNITS_OF_MEASURE),
    I("base_labor_rate_cents_per_unit", minimum=1),
    N("minimum_billable_units", minimum=0),
    B("measurement_required"),
    I("measurement_validity_days", required=False, minimum=1),
    E("permit_policy", fields.PERMIT_POLICIES, required=False),
    N("deposit_pct", required=False, gt=0, maximum=1),
    E("status", fields.CATEGORY_STATUSES, required=False),
]

CATEGORY_PATCH = [
    S("name", required=False, maxlen=120),
    I("base_labor_rate_cents_per_unit", required=False, minimum=1),
    N("minimum_billable_units", required=False, minimum=0),
    I("measurement_validity_days", required=False, minimum=1),
    E("permit_policy", fields.PERMIT_POLICIES, required=False),
    N("deposit_pct", required=False, gt=0, maximum=1),
    E("status", fields.CATEGORY_STATUSES, required=False),
]

JURISDICTION_CREATE = [
    S("code", maxlen=16),
    S("name", maxlen=120),
    A("permit_required_trades", enum=fields.TRADE_CODES),
    E("permit_responsible_party", fields.RESPONSIBLE_PARTIES),
    B("inspection_required"),
    I("min_liability_coverage_cents", minimum=0),
    N("permit_unit_threshold", required=False, minimum=0, decimals=None),
    I("inspection_lead_days", required=False, minimum=0),
    I("max_concurrent_inspections", required=False, minimum=1),
    I("background_check_recency_days", required=False, minimum=1),
    B("license_required", required=False),
    N("labor_complexity_multiplier", required=False, gt=0),
    E("status", fields.JURISDICTION_STATUSES, required=False),
]

JURISDICTION_PATCH = [
    S("name", required=False, maxlen=120),
    A("permit_required_trades", required=False, enum=fields.TRADE_CODES),
    N("permit_unit_threshold", required=False, minimum=0, decimals=None),
    E("permit_responsible_party", fields.RESPONSIBLE_PARTIES, required=False),
    B("inspection_required", required=False),
    I("inspection_lead_days", required=False, minimum=0),
    I("max_concurrent_inspections", required=False, minimum=1),
    I("background_check_recency_days", required=False, minimum=1),
    I("min_liability_coverage_cents", required=False, minimum=0),
    B("license_required", required=False),
    N("labor_complexity_multiplier", required=False, gt=0),
    E("status", fields.JURISDICTION_STATUSES, required=False),
]


@bp.post("/service-categories")
def create_service_category():
    auth(["ProgramAdmin"])
    data = validate(body(), CATEGORY_CREATE)
    for existing in store.all_rows("service_categories"):
        if existing["code"] == data["code"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    row = {
        "code": data["code"],
        "name": data["name"],
        "trade_code": data["trade_code"],
        "unit_of_measure": data["unit_of_measure"],
        "base_labor_rate_cents_per_unit": data["base_labor_rate_cents_per_unit"],
        "minimum_billable_units": data["minimum_billable_units"],
        "measurement_required": data["measurement_required"],
        "measurement_validity_days": data.get("measurement_validity_days", 45),
        "permit_policy": data.get("permit_policy", "BY_JURISDICTION"),
        "deposit_pct": data.get("deposit_pct", Decimal("0.30")),
        "status": data.get("status", "ACTIVE"),
    }
    store.insert("service_categories", row)
    return envelope.obj(row, 201)


@bp.get("/service-categories")
def list_service_categories():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("service_categories")
    rows = fields.filter_eq(rows, "status", fields.arg("status"))
    rows = fields.filter_eq(rows, "trade_code", fields.arg("trade_code"))
    return envelope.collection(envelope.order_created_desc_id_asc(rows), limit, offset)


@bp.get("/service-categories/<row_id>")
def get_service_category(row_id):
    auth(READ_ROLES)
    return envelope.obj(need("service_categories", row_id))


@bp.patch("/service-categories/<row_id>")
def patch_service_category(row_id):
    auth(["ProgramAdmin"])
    data = validate(body(), CATEGORY_PATCH)
    row = need("service_categories", row_id)
    for spec in CATEGORY_PATCH:
        if spec.name in data:
            row[spec.name] = data[spec.name]
    store.touch(row)
    return envelope.obj(row)


@bp.post("/jurisdictions")
def create_jurisdiction():
    auth(["ProgramAdmin"])
    data = validate(body(), JURISDICTION_CREATE)
    for existing in store.all_rows("jurisdictions"):
        if existing["code"] == data["code"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    row = {
        "code": data["code"],
        "name": data["name"],
        "permit_required_trades": list(data["permit_required_trades"]),
        "permit_unit_threshold": data.get("permit_unit_threshold", Decimal("0")),
        "permit_responsible_party": data["permit_responsible_party"],
        "inspection_required": data["inspection_required"],
        "inspection_lead_days": data.get("inspection_lead_days", 3),
        "max_concurrent_inspections": data.get("max_concurrent_inspections", 2),
        "background_check_recency_days": data.get("background_check_recency_days", 365),
        "min_liability_coverage_cents": data["min_liability_coverage_cents"],
        "license_required": data.get("license_required", True),
        "labor_complexity_multiplier": data.get("labor_complexity_multiplier", Decimal("1.00")),
        "status": data.get("status", "ACTIVE"),
    }
    store.insert("jurisdictions", row)
    return envelope.obj(row, 201)


@bp.get("/jurisdictions")
def list_jurisdictions():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("jurisdictions")
    rows = fields.filter_eq(rows, "status", fields.arg("status"))
    rows = fields.filter_eq(rows, "permit_responsible_party",
                            fields.arg("permit_responsible_party"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/jurisdictions/<row_id>")
def get_jurisdiction(row_id):
    auth(READ_ROLES)
    return envelope.obj(need("jurisdictions", row_id))


@bp.patch("/jurisdictions/<row_id>")
def patch_jurisdiction(row_id):
    auth(["ProgramAdmin"])
    data = validate(body(), JURISDICTION_PATCH)
    row = need("jurisdictions", row_id)
    for spec in JURISDICTION_PATCH:
        if spec.name in data:
            row[spec.name] = data[spec.name]
    store.touch(row)
    return envelope.obj(row)
