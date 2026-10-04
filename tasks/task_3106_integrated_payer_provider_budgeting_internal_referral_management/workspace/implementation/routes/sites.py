"""CareSite, Department and Provider endpoints."""

from flask import Blueprint

from constants import (
    ROLE_ACCESS_SCHEDULER,
    ROLE_REGIONAL_FINANCE_OFFICER,
)
from db import STORE
from domain import (
    enforce_posture_gate,
    get_care_site,
    get_department,
    get_provider,
    get_region,
    latest_budget_for,
    new_record,
    recompute_provider_panel,
    recompute_region_aggregates,
    recompute_region_providers,
    run_posture_ladder,
    staffing_and_facility_of,
    store_row,
    touch,
)
from errors import (
    ERR_BUDGET_FISCAL_LINE_EXCEEDED,
    ERR_FTE_BUDGET_EXCEEDED,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_VOLUME_COMPONENT_NOT_PERMITTED,
    raise_error,
)
from routes._common import (
    READERS,
    arg,
    filter_rows,
    list_response,
    optional_field,
    payload,
    principal,
    require_field,
    single_response,
    truthy,
)

bp = Blueprint("sites", __name__)

SITE_READERS = READERS


@bp.post("/regions/<region_id>/care-sites")
def create_care_site(region_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    get_region(region_id)
    enforce_posture_gate(region_id)
    body = payload()
    row = new_record(
        region_id=region_id,
        site_name=require_field(body, "site_name"),
        site_type=require_field(body, "site_type"),
        licensed_beds=require_field(body, "licensed_beds"),
        staffing_fte_budget=require_field(body, "staffing_fte_budget"),
        staffing_fte_filled=0,
        facility_investment_budget_cents=require_field(
            body, "facility_investment_budget_cents"),
        facility_investment_spent_cents=0,
    )
    store_row("care_sites", row)
    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("care_sites", row, 201)


@bp.get("/regions/<region_id>/care-sites")
def list_region_care_sites(region_id):
    principal(SITE_READERS)
    get_region(region_id)
    rows = [s for s in STORE.care_sites.values() if s.get("region_id") == region_id]
    rows = filter_rows(rows, site_type=arg("site_type"))
    return list_response("care_sites", rows)


@bp.get("/care-sites")
def list_care_sites():
    principal(SITE_READERS)
    rows = list(STORE.care_sites.values())
    rows = filter_rows(rows, region_id=arg("region_id"), site_type=arg("site_type"))
    return list_response("care_sites", rows)


@bp.get("/care-sites/<site_id>")
def get_one_care_site(site_id):
    principal(SITE_READERS)
    return single_response("care_sites", get_care_site(site_id))


@bp.post("/care-sites/<site_id>/staffing")
def set_staffing(site_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    site = get_care_site(site_id)
    region_id = site["region_id"]
    enforce_posture_gate(region_id)
    body = payload()
    filled = require_field(body, "staffing_fte_filled")

    if float(filled) > float(site.get("staffing_fte_budget") or 0):
        raise_error(ERR_FTE_BUDGET_EXCEEDED)

    site["staffing_fte_filled"] = filled
    touch(site)

    budget = latest_budget_for(region_id)
    if budget is not None:
        line = int(budget.get("staffing_budget_cents") or 0)
        if staffing_and_facility_of(region_id) > line:
            raise_error(ERR_BUDGET_FISCAL_LINE_EXCEEDED)

    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("care_sites", site)


# --------------------------------------------------------------- Department

@bp.post("/care-sites/<site_id>/departments")
def create_department(site_id):
    principal((ROLE_ACCESS_SCHEDULER,))
    site = get_care_site(site_id)
    region_id = site["region_id"]
    enforce_posture_gate(region_id)
    body = payload()
    row = new_record(
        care_site_id=site_id,
        region_id=region_id,
        specialty=require_field(body, "specialty"),
        appointment_slots_budgeted=require_field(body, "appointment_slots_budgeted"),
        appointment_slots_committed=0,
        wait_threshold_days=optional_field(body, "wait_threshold_days", 14),
        accepting_internal_referrals=True,
        status="OPEN",
    )
    store_row("departments", row)
    recompute_region_aggregates(region_id, bump_version=False)
    return single_response("departments", row, 201)


@bp.get("/care-sites/<site_id>/departments")
def list_site_departments(site_id):
    principal(SITE_READERS)
    get_care_site(site_id)
    rows = [d for d in STORE.departments.values() if d.get("care_site_id") == site_id]
    rows = filter_rows(rows, specialty=arg("specialty"), status=arg("status"))
    accepting = arg("accepting_internal_referrals")
    if accepting is not None:
        wanted = truthy(accepting)
        rows = [r for r in rows if bool(r.get("accepting_internal_referrals")) == wanted]
    return list_response("departments", rows)


@bp.get("/departments")
def list_departments():
    principal(SITE_READERS)
    rows = list(STORE.departments.values())
    rows = filter_rows(
        rows,
        care_site_id=arg("care_site_id"),
        region_id=arg("region_id"),
        specialty=arg("specialty"),
    )
    return list_response("departments", rows)


@bp.get("/departments/<department_id>")
def get_one_department(department_id):
    principal(SITE_READERS)
    return single_response("departments", get_department(department_id))


@bp.patch("/departments/<department_id>")
def patch_department(department_id):
    principal((ROLE_ACCESS_SCHEDULER,))
    department = get_department(department_id)
    region_id = department["region_id"]
    enforce_posture_gate(region_id)
    body = payload()

    if "accepting_internal_referrals" in body and body["accepting_internal_referrals"] is not None:
        department["accepting_internal_referrals"] = bool(
            body["accepting_internal_referrals"])
    if "wait_threshold_days" in body and body["wait_threshold_days"] is not None:
        department["wait_threshold_days"] = body["wait_threshold_days"]
    if "status" in body and body["status"] is not None:
        department["status"] = body["status"]
    touch(department)

    recompute_region_aggregates(region_id, bump_version=False)
    return single_response("departments", department)


# ----------------------------------------------------------------- Provider

@bp.post("/care-sites/<site_id>/providers")
def create_provider(site_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    site = get_care_site(site_id)
    region_id = site["region_id"]
    enforce_posture_gate(region_id)
    body = payload()

    if truthy(body.get("volume_linked")):
        raise_error(ERR_VOLUME_COMPONENT_NOT_PERMITTED)

    row = new_record(
        care_site_id=site_id,
        region_id=region_id,
        provider_name=require_field(body, "provider_name"),
        specialty=require_field(body, "specialty"),
        compensation_model=optional_field(
            body, "compensation_model", "PANEL_CAPITATION"),
        base_component_cents=require_field(body, "base_component_cents"),
        panel_size_target=require_field(body, "panel_size_target"),
        panel_size_assigned=0,
        quality_score=0,
        panel_capitation_component_cents=0,
        quality_bonus_cents=0,
        volume_component_cents=0,
        comp_total_cents=0,
        status="ACTIVE",
    )
    store_row("providers", row)
    recompute_region_providers(region_id, bump_versions=False)
    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("providers", row, 201)


@bp.get("/care-sites/<site_id>/providers")
def list_site_providers(site_id):
    principal(SITE_READERS)
    get_care_site(site_id)
    rows = [p for p in STORE.providers.values() if p.get("care_site_id") == site_id]
    rows = filter_rows(rows, specialty=arg("specialty"), status=arg("status"))
    return list_response("providers", rows)


@bp.get("/providers")
def list_providers():
    principal(SITE_READERS)
    rows = list(STORE.providers.values())
    rows = filter_rows(
        rows,
        care_site_id=arg("care_site_id"),
        region_id=arg("region_id"),
        specialty=arg("specialty"),
    )
    return list_response("providers", rows)


@bp.get("/providers/<provider_id>")
def get_one_provider(provider_id):
    actor = principal(SITE_READERS)
    provider = get_provider(provider_id)
    if actor.role == "Provider" and actor.user_id != provider_id:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS)
    return single_response("providers", provider)


@bp.patch("/providers/<provider_id>/compensation-model")
def patch_compensation_model(provider_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    provider = get_provider(provider_id)
    region_id = provider["region_id"]
    body = payload()

    if truthy(body.get("volume_linked")):
        raise_error(ERR_VOLUME_COMPONENT_NOT_PERMITTED)
    enforce_posture_gate(region_id)

    provider["compensation_model"] = require_field(body, "compensation_model")
    provider["base_component_cents"] = require_field(body, "base_component_cents")
    provider["panel_size_target"] = require_field(body, "panel_size_target")
    provider["volume_component_cents"] = 0
    recompute_provider_panel(provider)
    touch(provider)

    recompute_region_providers(region_id, bump_versions=True)
    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("providers", provider)


@bp.post("/provider-compensation-plans")
def draft_compensation_plan():
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    body = payload()
    provider_id = require_field(body, "provider_id")
    get_provider(provider_id)  # 404 when unknown

    plan = new_record(
        provider_id=provider_id,
        base_component_cents=require_field(body, "base_component_cents"),
        panel_size_target=require_field(body, "panel_size_target"),
        bonus_quality_target=require_field(body, "bonus_quality_target"),
        volume_linked=bool(body.get("volume_linked")),
    )
    if plan["volume_linked"]:
        plan["status"] = "REJECTED"
        store_row("compensation_plans", plan)
        raise_error(ERR_VOLUME_COMPONENT_NOT_PERMITTED)
    plan["status"] = "DRAFT"
    store_row("compensation_plans", plan)
    return single_response("compensation_plans", plan, 201)