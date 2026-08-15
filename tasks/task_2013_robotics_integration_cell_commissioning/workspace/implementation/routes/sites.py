"""CustomerSite and CellProject CRUD endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import children, store
from errors import ApiError, ERR_DUPLICATE_CODE, not_found
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SAFETY_LEAD as SL
from middleware import ROLE_SITE_SUPERVISOR as SS
from middleware import ROLE_SERVICE_MANAGER as SM
from response import success, success_list
from services import calculations as calc
from services.domain import common_fields, compute_forecast, post_ledger_entry, pub, pubs, touch
from validation import as_int, as_num, as_str, body, paginate, pagination, req

bp = Blueprint("sites", __name__)

LIST_ROLES = {FA, PE, SL, SS, SM}


def get_site(site_id):
    site = store.sites.get(site_id)
    if site is None:
        raise not_found("Customer site not found")
    return site


def get_project(project_id):
    project = store.projects.get(project_id)
    if project is None:
        raise not_found("Cell project not found")
    return project


@bp.post("/robotics/integrator-orgs/<org_id>/customer-sites")
def create_site(org_id):
    authenticate({PE})
    if org_id not in store.orgs:
        raise not_found("Integrator org not found")
    b = body()
    site = {
        **common_fields(),
        "integrator_org_id": org_id,
        "site_name": as_str(req(b, "site_name"), "site_name"),
        "plant_tz": as_str(req(b, "plant_tz"), "plant_tz"),
        "shift_windows_per_day": as_int(req(b, "shift_windows_per_day"), "shift_windows_per_day", 1, 3),
    }
    store.sites[site["id"]] = site
    return success(pub(site), 201)


@bp.get("/robotics/integrator-orgs/<org_id>/customer-sites")
def list_sites(org_id):
    authenticate(LIST_ROLES)
    if org_id not in store.orgs:
        raise not_found("Integrator org not found")
    limit, offset = pagination()
    page, total = paginate(children("sites", "integrator_org_id", org_id), limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/customer-sites/<site_id>")
def get_one_site(site_id):
    authenticate()
    return success(pub(get_site(site_id)))


@bp.patch("/robotics/customer-sites/<site_id>")
def update_site(site_id):
    authenticate({PE})
    site = get_site(site_id)
    b = body()
    shift_changed = False
    if "site_name" in b and b["site_name"] is not None:
        site["site_name"] = as_str(b["site_name"], "site_name")
    if "plant_tz" in b and b["plant_tz"] is not None:
        site["plant_tz"] = as_str(b["plant_tz"], "plant_tz")
    if "shift_windows_per_day" in b and b["shift_windows_per_day"] is not None:
        new_shift = as_int(b["shift_windows_per_day"], "shift_windows_per_day", 1, 3)
        if new_shift != site["shift_windows_per_day"]:
            site["shift_windows_per_day"] = new_shift
            shift_changed = True
    touch(site)
    if shift_changed:
        # Re-derive the forecast on every package of every project under this site.
        for project in children("projects", "customer_site_id", site_id):
            for pkg in children("packages", "cell_project_id", project["id"]):
                compute_forecast(pkg, site)
                touch(pkg)
    return success(pub(site))


# ---------------------------------------------------------------- cell projects
@bp.post("/robotics/customer-sites/<site_id>/cell-projects")
def create_project(site_id):
    authenticate({PE})
    site = get_site(site_id)
    b = body()
    # Uniqueness (priority 14) evaluates before generic field checks (priority 18).
    code = b.get("project_code")
    if isinstance(code, str):
        for existing in children("projects", "customer_site_id", site_id):
            if existing["project_code"] == code:
                raise ApiError(ERR_DUPLICATE_CODE, 409,
                               f"project_code '{code}' already exists for this site")
    project_code = as_str(req(b, "project_code"), "project_code")
    contracted_ct = as_num(req(b, "contracted_cycle_time_s"), "contracted_cycle_time_s",
                           min_v=0, min_exclusive=True)
    contract_value = as_int(req(b, "contract_value_cents"), "contract_value_cents", min_v=1)
    guaranteed_oee = as_num(req(b, "guaranteed_oee_pct"), "guaranteed_oee_pct",
                            min_v=50.0, max_v=99.9)
    if "guarantee_window_days" in b and b["guarantee_window_days"] is not None:
        window_days = as_int(b["guarantee_window_days"], "guarantee_window_days", 30, 365)
    else:
        window_days = 90
    project = {
        **common_fields(),
        "customer_site_id": site_id,
        "project_code": project_code,
        "contracted_cycle_time_s": contracted_ct,
        "contract_value_cents": contract_value,
        "status": "DRAFT",
        "hold_reason": None,
        "rework_count": 0,
        "retention_balance_cents": 0,
        "guaranteed_oee_pct": guaranteed_oee,
        "guarantee_window_days": window_days,
        "_prior_status": None,
    }
    store.projects[project["id"]] = project
    # Opening retention story: seed balance and post the WITHHOLD entry (PRD §3.1).
    org = store.orgs[site["integrator_org_id"]]
    total = calc.retention_total_cents(contract_value, org["retention_rate_bps"])
    post_ledger_entry(project, "WITHHOLD", total, project["id"])
    return success(pub(project), 201)


@bp.get("/robotics/customer-sites/<site_id>/cell-projects")
def list_projects(site_id):
    authenticate(LIST_ROLES)
    get_site(site_id)
    limit, offset = pagination()
    items = children("projects", "customer_site_id", site_id)
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/cell-projects/<project_id>")
def get_one_project(project_id):
    authenticate()
    return success(pub(get_project(project_id)))
