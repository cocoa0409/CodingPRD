"""PRD 3.1 project opening, PRD 3.7 summary read and PRD 3.8 occupancy declaration."""

from flask import Blueprint, request

import calc
import lookup
import rollups
import serial
from auth import (ALL_ROLES, CERTIFIER, CLIENT, DESIGN_ENGINEER, MANUFACTURER_AGENT,
                  PROJECT_MANAGER, require)
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import D, base_record, db, r2, touch
from validation import Field, body, no_body

projects_bp = Blueprint("projects", __name__)

SITE_CODE_PATTERN = r"^[A-Z]{2,4}[0-9]{1,2}$"
IDENTIFIER_SCHEMES = ("TIA_606_CLASS_1", "TIA_606_CLASS_2")
WARRANTY_PROGRAMS = ("NONE", "STANDARD_15Y", "EXTENDED_25Y")
WARRANTY_STATUSES = ("NOT_ELIGIBLE", "ELIGIBLE", "SUBMITTED", "REGISTERED",
                     "REJECTED", "REVOKED")
OCCUPANCY_STATUSES = ("PRE_OCCUPANCY", "OCCUPIED")


@projects_bp.route("/cabling/projects", methods=["POST"])
@require(PROJECT_MANAGER)
def open_project():
    values = body([
        Field("name", "string", min_len=1, max_len=120),
        Field("site_code", "string", pattern=SITE_CODE_PATTERN),
        Field("plenum_ceiling", "bool"),
        Field("identifier_scheme", "enum", enum=IDENTIFIER_SCHEMES),
        Field("warranty_program", "enum", required=False, default="STANDARD_15Y",
              enum=WARRANTY_PROGRAMS),
        Field("mac_budget_cents", "integer", required=False, default=500000, minimum=0),
    ])
    project = base_record()
    project.update({
        "name": values["name"],
        "site_code": values["site_code"],
        "plenum_ceiling": values["plenum_ceiling"],
        "identifier_scheme": values["identifier_scheme"],
        "warranty_program": values["warranty_program"],
        "mac_budget_cents": values["mac_budget_cents"],
        "occupancy_status": "PRE_OCCUPANCY",
        "total_link_count": 0,
        "certified_link_count": 0,
        "failed_link_count": 0,
        "completeness_pct_strict": r2(0),
        "completeness_pct_provisional": r2(0),
        "warranty_status": "NOT_ELIGIBLE",
        "as_built_cost_cents": 0,
        "consumed_mac_cents": 0,
    })
    db.projects[project["id"]] = project
    return created(serial.public(project))


@projects_bp.route("/cabling/projects/<project_id>", methods=["GET"])
@require(*ALL_ROLES)
def read_project(project_id):
    return ok(serial.public(lookup.project(project_id)))


@projects_bp.route("/cabling/projects", methods=["GET"])
@require(PROJECT_MANAGER, DESIGN_ENGINEER, MANUFACTURER_AGENT)
def list_projects():
    site_code = request.args.get("site_code")
    warranty_status = enum_filter(request.args, "warranty_status", WARRANTY_STATUSES)
    occupancy_status = enum_filter(request.args, "occupancy_status", OCCUPANCY_STATUSES)
    rows = []
    for project in db.projects.values():
        if site_code is not None and project["site_code"] != site_code:
            continue
        if warranty_status is not None and project["warranty_status"] != warranty_status:
            continue
        if occupancy_status is not None and project["occupancy_status"] != occupancy_status:
            continue
        rows.append(project)
    return paginate(rows, request.args, serial.public)


@projects_bp.route("/cabling/projects/<project_id>/occupancy", methods=["POST"])
@require(PROJECT_MANAGER)
def declare_occupancy(project_id):
    values = body([Field("occupancy_status", "enum", enum=("OCCUPIED",))])
    project = lookup.project(project_id)
    if project["occupancy_status"] != "PRE_OCCUPANCY":
        raise ApiError("ERR_INVALID_PROJECT_STATE",
                       "Occupancy has already been declared on this project.")
    ceiling = [c for c in rollups.project_coordinations(project_id)
               if c["trade"] == "CEILING"]
    if any(c["coordination_state"] != "RELEASED" for c in ceiling):
        raise ApiError("ERR_TRADE_NOT_COORDINATED",
                       "Every CEILING coordination of the project must be RELEASED.")
    if D(project["completeness_pct_strict"]) < calc.OCCUPANCY_READINESS_PCT:
        raise ApiError("ERR_OCCUPANCY_READINESS_NOT_MET",
                       "completeness_pct_strict must be at least 90.00 to declare occupancy.")
    project["occupancy_status"] = values["occupancy_status"]
    touch(project)
    return ok(serial.public(project))


@projects_bp.route("/cabling/projects/<project_id>/certification-summary",
                   methods=["GET"])
@require(PROJECT_MANAGER, DESIGN_ENGINEER, CERTIFIER, MANUFACTURER_AGENT, CLIENT)
def read_certification_summary(project_id):
    project = lookup.project(project_id)
    return ok(serial.certification_summary(project))
