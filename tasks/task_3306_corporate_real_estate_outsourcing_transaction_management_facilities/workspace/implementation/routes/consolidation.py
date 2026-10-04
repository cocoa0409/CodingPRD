"""ConsolidationProject routes."""
from core import auth, calc, domain
from core.db import DB, dec, new_common, serialize, touch
from core.errors import ApiError
from core.response import ok

from routes.registry import body, lookup, paginated_ok, req, route, validate

OP_ONLY = ["OccupancyPlanner"]
OP_ROLES = ["AccountExecutive", "OccupancyPlanner", "GovernanceManager"]


def _assigned_sites(project):
    sites = [s for s in DB.rows("facility_sites")
             if s.get("consolidation_project_id") == project["id"]]
    return sorted(sites, key=lambda s: (s.get("created_at"), s.get("site_name") or ""))


@route("POST", "/api/consolidation-projects", "create_consolidation_project", OP_ONLY, 201)
def create_consolidation_project():
    data = validate(body(), [req("account_id"), req("project_name"),
                             req("planned_sqft_reduction"), req("cost_inflation_factor"),
                             req("per_site_rates"), req("per_site_sqft_reductions")])
    account = lookup("accounts", data.get("account_id"), "account")
    domain.lifecycle_gate(account, "create_consolidation_project")
    planned = data["planned_sqft_reduction"]
    if isinstance(planned, bool) or not isinstance(planned, int) or planned <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "planned_sqft_reduction must be strictly positive.")
    factor = dec(data["cost_inflation_factor"])
    if factor < 1:
        raise ApiError("ERR_INVALID_REQUEST", "cost_inflation_factor must be at least 1.0.")
    if not isinstance(data["per_site_rates"], list):
        raise ApiError("ERR_INVALID_REQUEST", "per_site_rates must be an array.")
    if not isinstance(data["per_site_sqft_reductions"], list):
        raise ApiError("ERR_INVALID_REQUEST", "per_site_sqft_reductions must be an array.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "project_name": data["project_name"],
        "project_state": "PLANNED",
        "planned_sqft_reduction": planned,
        "approved_sqft_reduction": 0,
        "realized_sqft_reduction": 0,
        "savings_estimate_cents": 0,
        "savings_finalized_cents": 0,
        "cost_inflation_factor": factor,
        "per_site_rates": data["per_site_rates"],
        "per_site_sqft_reductions": data["per_site_sqft_reductions"],
    })
    DB.insert("consolidation_projects", obj)
    return ok(serialize(obj), 201)


@route("GET", "/api/consolidation-projects", "list_consolidation_projects", OP_ROLES)
def list_consolidation_projects():
    rows = DB.ordered("consolidation_projects")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    return paginated_ok(rows)


@route("GET", "/api/consolidation-projects/<project_id>", "get_consolidation_project",
       OP_ROLES)
def get_consolidation_project(project_id):
    return ok(serialize(lookup("consolidation_projects", project_id, "consolidation project")))


@route("POST", "/api/consolidation-projects/<project_id>/submit",
       "submit_consolidation_project", OP_ONLY)
def submit_consolidation_project(project_id):
    project = lookup("consolidation_projects", project_id, "consolidation project")
    account = lookup("accounts", project.get("account_id"), "account")
    if project.get("project_state") != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "Only a PLANNED project may be submitted.")
    domain.lifecycle_gate(account, "create_consolidation_project")
    project["project_state"] = "IN_REVIEW"
    project["savings_estimate_cents"] = calc.consolidation_savings_estimate(
        project, "provisional")
    touch(project)
    return ok(serialize(project))


@route("POST", "/api/consolidation-projects/<project_id>/approve",
       "approve_consolidation_project", ["ApprovalAuthority"])
def approve_consolidation_project(project_id):
    project = lookup("consolidation_projects", project_id, "consolidation project")
    account = lookup("accounts", project.get("account_id"), "account")
    if project.get("project_state") != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_REVIEW project may be approved.")
    user_id = __import__("flask").request.headers.get("X-User-ID")
    found = [a for a in DB.children("account_assignments", account["id"])
             if a.get("assignment_role") == "APPROVAL_AUTHORITY"]
    if not found:
        raise ApiError("ERR_UNAUTHORIZED",
                       "No APPROVAL_AUTHORITY assignment exists for this account.")
    if user_id is not None and not any(
            a.get("id") == user_id or a.get("assignee_name") == user_id for a in found):
        raise ApiError("ERR_UNAUTHORIZED",
                       "No APPROVAL_AUTHORITY assignment on this account matches X-User-ID.")
    project["project_state"] = "APPROVED"
    project["approved_sqft_reduction"] = project.get("planned_sqft_reduction") or 0
    project["savings_estimate_cents"] = calc.consolidation_savings_estimate(
        project, "provisional")
    touch(project)
    return ok(serialize(project))


@route("POST", "/api/consolidation-projects/<project_id>/start-execution",
       "start_consolidation_execution", OP_ONLY)
def start_consolidation_execution(project_id):
    project = lookup("consolidation_projects", project_id, "consolidation project")
    account = lookup("accounts", project.get("account_id"), "account")
    sites = _assigned_sites(project)
    if project.get("project_state") != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED project may start execution.")
    ready = all(s.get("vacancy_state") in ("CONSOLIDATING", "DISPOSED") for s in sites)
    if not ready:
        raise ApiError("ERR_INVALID_STATE",
                       "Every assigned site must be CONSOLIDATING or DISPOSED.")
    domain.cooling_off_gate(account["id"])
    total = sum(int(s.get("sqft_reduction") or 0) for s in sites)
    if total != int(project.get("approved_sqft_reduction") or 0):
        raise ApiError("ERR_SQFT_MISMATCH",
                       "The assigned sites' reductions do not equal the approved reduction.")
    project["project_state"] = "IN_EXECUTION"
    project["savings_finalized_cents"] = calc.consolidation_savings_estimate(project, "final")
    project["realized_sqft_reduction"] = total
    touch(project)
    for site in sites:
        site["vacancy_state"] = "DISPOSED"
        touch(site)
    account["portfolio_leased_sqft"] = calc.portfolio_leased_sqft(account["id"])
    touch(account)
    return ok(serialize(project))


@route("POST", "/api/consolidation-projects/<project_id>/return-to-planning",
       "return_consolidation_to_planning", OP_ONLY)
def return_consolidation_to_planning(project_id):
    project = lookup("consolidation_projects", project_id, "consolidation project")
    if project.get("project_state") != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_REVIEW project may be replanned.")
    project["project_state"] = "PLANNED"
    project["savings_estimate_cents"] = 0
    touch(project)
    return ok(serialize(project))


@route("POST", "/api/consolidation-projects/<project_id>/cancel",
       "cancel_consolidation_project", OP_ONLY)
def cancel_consolidation_project(project_id):
    project = lookup("consolidation_projects", project_id, "consolidation project")
    if project.get("project_state") not in ("PLANNED", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PLANNED or IN_REVIEW project may be cancelled.")
    project["project_state"] = "CANCELLED"
    project["savings_estimate_cents"] = 0
    touch(project)
    return ok(serialize(project))