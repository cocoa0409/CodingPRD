"""Providers and the provider caseload view (PRD sections 3.1 and 3.8)."""
from flask import Blueprint

from db import base_row, db, touch
from middleware import endpoint
from response import object_response
from routes.common import matches, paged
from services import calc, derive, rules
from validation import (
    INTAKE_POSTURE,
    PROVIDER_DISCIPLINE,
    PROVIDER_STATUS,
    SERVICE_POSTURE,
    body,
    opt_enum,
    opt_int,
    opt_lang_list,
    present,
    q_enum,
    q_str,
    req_enum,
    req_str,
)

bp = Blueprint("providers", __name__)

READ_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "Evaluator",
    "PlacementAdministrator",
    "DistrictAdmin",
)
LIST_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "PlacementAdministrator",
    "DistrictAdmin",
)


@bp.post("/providers")
@endpoint("DistrictAdmin")
def create_provider():
    data = body()
    row = base_row()
    row.update(
        {
            "full_name": req_str(data, "full_name"),
            "discipline": req_enum(data, "discipline", PROVIDER_DISCIPLINE),
            "home_region_code": req_str(data, "home_region_code", max_len=20),
            "languages": opt_lang_list(data, "languages", ["en"]),
            "max_weekly_service_minutes": opt_int(
                data, "max_weekly_service_minutes", 1500, minimum=0, multiple_of=5
            ),
            "max_evaluation_caseload": opt_int(
                data, "max_evaluation_caseload", 12, minimum=0
            ),
            "max_weekly_interpreter_assignments": opt_int(
                data, "max_weekly_interpreter_assignments", 0, minimum=0
            ),
            "status": opt_enum(data, "status", PROVIDER_STATUS, "ACTIVE"),
        }
    )
    db.providers[row["id"]] = row
    return object_response(derive.provider_out(row), 201)


@bp.patch("/providers/<provider_id>")
@endpoint("DistrictAdmin")
def update_provider(provider_id):
    data = body()
    status = opt_enum(data, "status", PROVIDER_STATUS)
    languages = opt_lang_list(data, "languages")
    max_minutes = opt_int(data, "max_weekly_service_minutes", minimum=0, multiple_of=5)
    max_caseload = opt_int(data, "max_evaluation_caseload", minimum=0)
    max_interpreter = opt_int(data, "max_weekly_interpreter_assignments", minimum=0)

    row = rules.fetch("providers", provider_id)
    if status is not None:
        row["status"] = status
    if languages is not None:
        row["languages"] = languages
    if max_minutes is not None:
        row["max_weekly_service_minutes"] = max_minutes
    if max_caseload is not None:
        row["max_evaluation_caseload"] = max_caseload
    if max_interpreter is not None:
        row["max_weekly_interpreter_assignments"] = max_interpreter
    touch(row)
    return object_response(derive.provider_out(row))


@bp.get("/providers/<provider_id>")
@endpoint(*READ_ROLES)
def get_provider(provider_id):
    return object_response(derive.provider_out(rules.fetch("providers", provider_id)))


@bp.get("/providers")
@endpoint(*LIST_ROLES)
def list_providers():
    discipline = q_enum("discipline", PROVIDER_DISCIPLINE)
    region = q_str("home_region_code")
    service_posture = q_enum("service_capacity_posture", SERVICE_POSTURE)
    intake_posture = q_enum("evaluation_intake_posture", INTAKE_POSTURE)
    status = q_enum("status", PROVIDER_STATUS)

    rows = []
    for row in db.providers.values():
        if not matches(row, "discipline", discipline):
            continue
        if not matches(row, "home_region_code", region):
            continue
        if not matches(row, "status", status):
            continue
        minutes = derive.provider_capacity(row)
        posture = calc.service_capacity_posture(
            minutes["assigned_weekly_service_minutes"], row["max_weekly_service_minutes"]
        )
        if service_posture is not None and posture != service_posture:
            continue
        intake = calc.evaluation_intake_posture(
            derive.provider_active_evaluation_count(row["id"]),
            row["max_evaluation_caseload"],
        )
        if intake_posture is not None and intake != intake_posture:
            continue
        rows.append(row)
    return paged(rows, derive.provider_out)


@bp.get("/providers/<provider_id>/caseload")
@endpoint(*LIST_ROLES)
def provider_caseload(provider_id):
    row = rules.fetch("providers", provider_id)
    projected = derive.provider_capacity(row, calc.COUNTED_PLAN_STATES_PROJECTED)
    committed = derive.provider_capacity(row, calc.COUNTED_PLAN_STATES_COMMITTED)
    assigned = projected["assigned_weekly_service_minutes"]
    maximum = row["max_weekly_service_minutes"]
    active = derive.provider_active_evaluation_count(row["id"])
    return object_response(
        {
            "provider_id": row["id"],
            "direct_weekly_service_minutes": projected["direct_weekly_service_minutes"],
            "distinct_site_count": projected["distinct_site_count"],
            "travel_tier_pct": calc.as_number(projected["travel_tier_pct"]),
            "travel_overhead_minutes": projected["travel_overhead_minutes"],
            "assigned_weekly_service_minutes": assigned,
            "committed_weekly_minutes": committed["assigned_weekly_service_minutes"],
            "max_weekly_service_minutes": maximum,
            "utilization": calc.as_number(calc.utilization(assigned, maximum)),
            "service_capacity_posture": calc.service_capacity_posture(assigned, maximum),
            "active_evaluation_count": active,
            "max_evaluation_caseload": row["max_evaluation_caseload"],
            "evaluation_intake_posture": calc.evaluation_intake_posture(
                active, row["max_evaluation_caseload"]
            ),
            "assigned_interpreter_assignment_count": derive.provider_interpreter_count(
                row["id"]
            ),
        }
    )
