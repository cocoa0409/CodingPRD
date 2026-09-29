"""Project and MaterialPackage endpoints (PRD 3.1)."""

from flask import Blueprint, request

import calc
import domain
import serial
from auth import authorize
from domain import INDEX_CODES
from envelope import created, ok, paginated
from errors import ApiError
from shapes import Field, validate
from store import ordered, store

bp = Blueprint("projects", __name__)

PROJECT_FIELDS = [
    Field("name", "string", required=True, min_len=1, max_len=200),
    Field("contract_number", "string", required=True, min_len=1, max_len=40),
    Field("owner_name", "string", required=True),
    Field("schedule_data_date", "datetime", required=True),
    Field("escalation_contingency_budget", "number", required=True,
          exclusive_minimum=0, max_dp=2),
]

PACKAGE_FIELDS = [
    Field("project_id", "string", required=True),
    Field("scope_code", "string", required=True, min_len=1, max_len=40),
    Field("description", "string", required=True),
    Field("commodity_index_code", "enum", required=True, choices=INDEX_CODES),
    Field("estimated_cost", "number", required=True, exclusive_minimum=0, max_dp=2),
    Field("required_onsite_date", "datetime", required=True),
    Field("fabrication_duration_days", "int", required=True, minimum=0, maximum=720),
    Field("delivery_transit_days", "int", required=True, minimum=0, maximum=365),
    Field("submittal_review_days", "int", minimum=0, maximum=180, default=21),
]

PACKAGE_PATCH_FIELDS = [
    Field("required_onsite_date", "datetime"),
    Field("fabrication_duration_days", "int", minimum=0, maximum=720),
    Field("delivery_transit_days", "int", minimum=0, maximum=365),
    Field("submittal_review_days", "int", minimum=0, maximum=180),
    Field("estimated_cost", "number", exclusive_minimum=0, max_dp=2),
]


@bp.post("/procurement/projects")
@authorize("BuyoutManager", "ProjectExecutive")
def create_project():
    body = validate(PROJECT_FIELDS)
    row = store.new_row()
    row.update(body)
    store.projects[row["id"]] = row
    return created(serial.project(row))


@bp.get("/procurement/projects/<project_id>")
@authorize("BuyoutManager", "ProjectExecutive", "OwnerRep")
def read_project(project_id):
    row = domain.get_project(project_id)
    return ok(serial.project(row))


@bp.post("/procurement/material-packages")
@authorize("BuyoutManager")
def create_package():
    body = validate(PACKAGE_FIELDS)
    project = domain.get_project(body["project_id"])
    for existing in store.packages.values():
        if (existing["project_id"] == project["id"]
                and existing["scope_code"] == body["scope_code"]):
            raise ApiError("ERR_DUPLICATE_SCOPE_CODE")
    row = store.new_row()
    row.update(body)
    row["baseline_estimated_cost"] = body["estimated_cost"]
    row["baseline_fabrication_duration_days"] = body["fabrication_duration_days"]
    row["status"] = "IDENTIFIED"
    store.packages[row["id"]] = row
    return created(serial.package(row))


@bp.get("/procurement/material-packages/<package_id>")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def read_package(package_id):
    row = domain.get_package(package_id)
    return ok(serial.package(row))


@bp.get("/procurement/material-packages")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_packages():
    args = request.args
    project_id = domain.string_filter(args, "project_id")
    status = domain.string_filter(args, "status")
    band = domain.string_filter(args, "rff_risk_band")
    long_lead = domain.bool_filter(args, "is_long_lead")
    rows = []
    for row in ordered(list(store.packages.values())):
        if project_id is not None and row["project_id"] != project_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if long_lead is not None and calc.package_is_long_lead(row) != long_lead:
            continue
        if band is not None:
            if calc.package_risk_band(calc.package_float_days(row)) != band:
                continue
        rows.append(row)
    return paginated(rows, serial.package)


@bp.patch("/procurement/material-packages/<package_id>")
@authorize("BuyoutManager")
def patch_package(package_id):
    body = validate(PACKAGE_PATCH_FIELDS)
    row = domain.get_package(package_id)
    for key, value in body.items():
        row[key] = value
    row["baseline_estimated_cost"] = row["estimated_cost"]
    row["baseline_fabrication_duration_days"] = row["fabrication_duration_days"]
    store.touch(row)
    return ok(serial.package(row))
