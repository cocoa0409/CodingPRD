"""EnergyBaseline (retro-commissioning) endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, ROLE_CX_AUTHORITY, authenticate, body_json, db, fail, new_row, num, ok,
    ok_list, paginate, public, q, sorted_rows, touch, v_enum, v_number, v_string,
)
from finders import get_baseline, get_project

bp = Blueprint("baselines", __name__)


@bp.post("/energy-baselines")
def create_baseline():
    authenticate([ROLE_CX_AUTHORITY])
    body = body_json()
    project_id = v_string(body, "project_id")
    measure_code = v_string(body, "measure_code")
    baseline_kwh = v_number(body, "baseline_kwh", exclusive_minimum=0)
    baseline_hdd = v_number(body, "baseline_hdd", exclusive_minimum=0)
    stipulated_kwh_per_hour = v_number(body, "stipulated_kwh_per_hour", minimum=0)
    operating_hours = v_number(body, "operating_hours", minimum=0)

    project = get_project(project_id)

    if project["project_type"] != "RETRO_COMMISSIONING":
        fail("ERR_RETRO_ONLY",
             "Energy baselines may only be recorded on RETRO_COMMISSIONING engagements.")

    row = new_row(db.baselines, {
        "project_id": project_id,
        "measure_code": measure_code,
        "baseline_kwh": baseline_kwh,
        "baseline_hdd": baseline_hdd,
        "stipulated_kwh_per_hour": stipulated_kwh_per_hour,
        "operating_hours": operating_hours,
        "post_kwh": None,
        "post_hdd": None,
        "deemed_savings_kwh": None,
        "measured_savings_kwh": None,
        "certified_savings_kwh": None,
        "certified_variant": None,
        "status": "BASELINE_SET",
    })
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/energy-baselines")
def list_baselines():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.baselines.values()))
    for param in ("project_id", "status"):
        value = q(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/energy-baselines/<baseline_id>")
def read_baseline(baseline_id):
    authenticate(ALL_ROLES)
    return ok(public(get_baseline(baseline_id)))


@bp.post("/energy-baselines/<baseline_id>/post-period")
def post_period(baseline_id):
    authenticate([ROLE_CX_AUTHORITY])
    row = get_baseline(baseline_id)
    body = body_json()
    post_kwh = v_number(body, "post_kwh")
    post_hdd = v_number(body, "post_hdd")

    if row["status"] != "BASELINE_SET":
        fail("ERR_INVALID_STATE", "Only a BASELINE_SET measure may record a post period.")

    row["post_kwh"] = post_kwh
    row["post_hdd"] = post_hdd
    row["deemed_savings_kwh"] = num(calc.compute_deemed_savings(row))
    row["measured_savings_kwh"] = num(calc.compute_measured_savings(row, post_kwh, post_hdd))
    row["status"] = "POST_PERIOD_RECORDED"
    touch(row)
    services.reconcile()
    return ok(public(row))


@bp.post("/energy-baselines/<baseline_id>/certify-savings")
def certify_savings(baseline_id):
    authenticate([ROLE_CX_AUTHORITY])
    row = get_baseline(baseline_id)
    body = body_json()
    variant = v_enum(body, "variant", calc.SAVINGS_VARIANTS)

    if row["status"] != "POST_PERIOD_RECORDED":
        fail("ERR_INVALID_STATE",
             "Only a POST_PERIOD_RECORDED measure may be certified.")

    project = db.projects.get(row["project_id"])
    if project["certification_target"] == "ENHANCED" and variant != "MEASURED":
        fail("ERR_VARIANT_NOT_PERMITTED",
             "An ENHANCED certification target accepts only the MEASURED variant.")

    row["certified_variant"] = variant
    row["certified_savings_kwh"] = (
        row["deemed_savings_kwh"] if variant == "DEEMED" else row["measured_savings_kwh"]
    )
    row["status"] = "CERTIFIED"
    touch(row)
    services.reconcile()
    return ok(public(row))
