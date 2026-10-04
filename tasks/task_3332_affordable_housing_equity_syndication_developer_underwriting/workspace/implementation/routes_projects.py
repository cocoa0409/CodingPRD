"""Projects: underwriting, commitment and construction milestones."""

from flask import Blueprint, request

import calc
import clock
import errors
import response
import state
import store
import validate

bp = Blueprint("projects", __name__)

READ_PROJECTS = ("Underwriter", "AssetManager", "ComplianceOfficer", "Developer", "PlatformAdmin")
READ_PROJECT = ("Underwriter", "AssetManager", "ComplianceOfficer", "Developer", "Investor",
                "PlatformAdmin")

UNDERWRITING_INPUTS = ("construction_budget_cents", "construction_loan_cents",
                       "operating_pro_forma_noi_cents", "debt_service_cents",
                       "market_study_absorption_score", "sponsor_experience_months",
                       "placed_in_service_deadline")

MILESTONES = ("CONSTRUCTION_START", "CONSTRUCTION_50PCT", "LEASE_UP_50PCT",
              "LEASE_UP_STABILIZED", "PLACED_IN_SERVICE")

DSCR_MIN = 1.15
ABSORPTION_MIN = 0.60
SPONSOR_MONTHS_MIN = 24


def _blank_project_fields():
    return {
        "placed_in_service_at": None,
        "status": "UNDERWRITING",
        "underwriting_stage": "PRELIMINARY",
        "preliminary_equity_cents": 0,
        "final_equity_cents": None,
        "underwritten_equity_cents": 0,
        "dscr": 0.0,
        "operating_deficit_cents": 0,
        "committed_credit_dollars_cents": 0,
        "delivered_credit_dollars_cents": 0,
        "compliance_failure_count": 0,
        "underwritten_gap_cents": 0,
    }


def _investor_may_read_project(investor_id, project):
    return validate.investor_holds_fund(investor_id, project["fund_id"])


@bp.post("/projects")
def create_project():
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("Underwriter",))
    payload = validate.body(request)
    developer_id = validate.as_string(payload, "developer_id")
    fund_id = validate.as_string(payload, "fund_id")
    project_name = validate.as_string(payload, "project_name")
    state_code = validate.as_state_code(payload)
    total_credits = validate.non_negative(validate.as_int(payload, "total_credit_dollars_cents"),
                                          "total_credit_dollars_cents")
    budget = validate.non_negative(validate.as_int(payload, "construction_budget_cents"),
                                   "construction_budget_cents")
    loan = validate.non_negative(validate.as_int(payload, "construction_loan_cents"),
                                 "construction_loan_cents")
    noi = validate.non_negative(validate.as_int(payload, "operating_pro_forma_noi_cents"),
                                "operating_pro_forma_noi_cents")
    debt_service = validate.non_negative(validate.as_int(payload, "debt_service_cents"),
                                         "debt_service_cents")
    absorption = validate.as_absorption(payload)
    months = validate.non_negative(validate.as_int(payload, "sponsor_experience_months"),
                                   "sponsor_experience_months")
    deadline = validate.as_datetime(payload, "placed_in_service_deadline")
    compliance_months = validate.as_int(payload, "compliance_period_months", required_field=False)
    if compliance_months is None:
        compliance_months = 180
    validate.non_negative(compliance_months, "compliance_period_months")

    developer = validate.get_developer(developer_id)
    fund = validate.get_fund(fund_id)

    fields = {
        "developer_id": developer["id"],
        "fund_id": fund["id"],
        "project_name": project_name,
        "state_code": state_code,
        "total_credit_dollars_cents": total_credits,
        "construction_budget_cents": budget,
        "construction_loan_cents": loan,
        "operating_pro_forma_noi_cents": noi,
        "debt_service_cents": debt_service,
        "market_study_absorption_score": absorption,
        "sponsor_experience_months": months,
        "placed_in_service_deadline": deadline,
        "compliance_period_months": compliance_months,
    }
    fields.update(_blank_project_fields())
    project = store.create(store.projects, fields)
    state.recompute_project(project["id"])
    state.recompute_developer(developer["id"])
    return response.ok(store.public(project), 201)


@bp.get("/projects")
def list_projects():
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_PROJECTS)
    filters = {
        "developer_id": request.args.get("developer_id"),
        "fund_id": request.args.get("fund_id"),
        "status": request.args.get("status"),
    }
    rows = store.listing(store.projects, filters)
    if role == "Developer":
        rows = [p for p in rows if p["developer_id"] == user_id]
    limit, offset = response.pagination_args(request)
    window, meta = response.paginate(rows, limit, offset)
    return response.array([store.public(p) for p in window], 200, meta)


@bp.get("/projects/<project_id>")
def read_project(project_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_PROJECT)
    project = validate.get_project(project_id)
    if role == "Developer" and project["developer_id"] != user_id:
        errors.fail(errors.ERR_FORBIDDEN_SCOPE, "A Developer may read only its own projects.")
    if role == "Investor" and not _investor_may_read_project(user_id, project):
        errors.fail(errors.ERR_FORBIDDEN_SCOPE,
                    "An Investor may read only projects of funds it subscribes to.")
    state.recompute_project(project_id)
    return response.ok(store.public(project), 200)


@bp.put("/projects/<project_id>")
def update_project(project_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("Underwriter",))
    payload = validate.body(request)

    underwriting_action = payload.get("underwriting_action")
    if underwriting_action is not None:
        validate.in_enum(underwriting_action, ("FINALIZE",), "underwriting_action")
    allocation_action = payload.get("allocation_action")
    if allocation_action is not None:
        validate.in_enum(allocation_action, ("RESERVE", "RELEASE"), "allocation_action")
    allocation_id = payload.get("allocation_id")

    new_values = {}
    for name in UNDERWRITING_INPUTS:
        if name in payload and payload[name] is not None:
            if name == "market_study_absorption_score":
                new_values[name] = validate.as_absorption(payload, name)
            elif name == "placed_in_service_deadline":
                new_values[name] = validate.as_datetime(payload, name)
            else:
                new_values[name] = validate.non_negative(validate.as_int(payload, name), name)
    expected = validate.as_int(payload, "expected_project_version")

    project = validate.get_project(project_id)

    # tier 4 — a body identifier resolves after every path identifier.
    allocation = None
    if allocation_id is not None:
        allocation = validate.get_child(store.allocations, allocation_id, project_id,
                                        errors.ERR_ALLOCATION_NOT_FOUND)

    # tier 6 — the target allocation must permit the requested move.
    if allocation_action is not None:
        if allocation is None:
            errors.fail(errors.ERR_INVALID_REQUEST,
                        "allocation_id is required with allocation_action.")
        if allocation["status"] not in ("AWARDED", "RESERVED"):
            errors.fail(errors.ERR_INVALID_ALLOCATION_STATE,
                        "The allocation is not AWARDED or RESERVED.")

    # tier 8 — revision band.
    if int(project["version"]) != int(expected):
        errors.fail(errors.ERR_STALE_VERSION, "expected_project_version is not current.")

    version_before = int(project["version"])
    changed = False

    if new_values:
        project.update(new_values)
        if project["status"] == "UNDERWRITING":
            project["underwriting_stage"] = "PRELIMINARY"
            project["final_equity_cents"] = None
        changed = True
        state.recompute_project(project_id)

    if allocation_action == "RESERVE" and allocation["status"] == "AWARDED":
        if _overlaps_other_allocation(project_id, allocation):
            errors.fail(errors.ERR_DUPLICATE_ALLOCATION_PERIOD,
                        "The award interval overlaps another live allocation.")
        allocation["status"] = "RESERVED"
        store.touch(allocation)
        changed = True
    elif allocation_action == "RELEASE" and allocation["status"] == "RESERVED":
        allocation["status"] = "AWARDED"
        store.touch(allocation)
        changed = True

    if underwriting_action == "FINALIZE":
        if (project["market_study_absorption_score"] < ABSORPTION_MIN
                or int(project["construction_budget_cents"]) <= 0
                or int(project["operating_pro_forma_noi_cents"]) <= 0
                or int(project["debt_service_cents"]) <= 0
                or int(project["sponsor_experience_months"]) < SPONSOR_MONTHS_MIN):
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The project does not meet the finalization preconditions.")
        project["underwriting_stage"] = "FINAL"
        changed = True
        state.recompute_project(project_id)

    if changed:
        state.recompute_project(project_id)
        state.recompute_fund(project["fund_id"])
        state.recompute_developer(project["developer_id"])
    if int(project["version"]) == version_before:
        store.touch(project)
    return response.ok(store.public(project), 200)


def _overlaps_other_allocation(project_id, allocation):
    start = clock._parse(allocation["awarded_date"])
    end = clock._parse(allocation["placed_in_service_deadline"])
    for other in state.allocations_of_project(project_id):
        if other["id"] == allocation["id"]:
            continue
        if other["state_agency"] != allocation["state_agency"]:
            continue
        if other["status"] not in ("AWARDED", "RESERVED"):
            continue
        other_start = clock._parse(other["awarded_date"])
        other_end = clock._parse(other["placed_in_service_deadline"])
        if start < other_end and other_start < end:
            return True
    return False


@bp.post("/projects/<project_id>/commit")
def commit_project(project_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("Underwriter",))
    project = validate.get_project(project_id)
    developer = validate.get_developer(project["developer_id"])
    fund = validate.get_fund(project["fund_id"])

    # tier 6 — target state.
    live_allocations = [a for a in state.allocations_of_project(project_id)
                        if a["status"] in ("RESERVED", "AWARDED")]
    if (project["status"] != "UNDERWRITING"
            or project["underwriting_stage"] != "FINAL"
            or not live_allocations
            or float(project["dscr"]) < DSCR_MIN
            or float(project["market_study_absorption_score"]) < ABSORPTION_MIN
            or int(project["sponsor_experience_months"]) < SPONSOR_MONTHS_MIN):
        errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                    "The project is not in a state that permits commitment.")
    if fund["status"] not in ("CLOSING", "CLOSED", "DEPLOYING"):
        errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE, "The fund is not ready to deploy.")
    if clock.now() > clock._parse(project["placed_in_service_deadline"]):
        errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                    "The placed-in-service deadline has passed.")

    # tier 7 — sponsor safeguard.
    state.recompute_developer(developer["id"])
    if developer["status"] != "ELIGIBLE":
        errors.fail(errors.ERR_DEVELOPER_WATCH_BLOCKED,
                    "The developer is on WATCH or SUSPENDED.")

    # tier 8 — posture gate.
    if fund["posture"] == "FROZEN":
        errors.fail(errors.ERR_FUND_POSTURE_FROZEN, "The fund's posture is FROZEN.")

    version_before = int(project["version"])
    project["status"] = "COMMITTED"
    for allocation in live_allocations:
        allocation["status"] = "COMMITTED"
        store.touch(allocation)

    state.recompute_project(project_id)
    state.recompute_fund(fund["id"])
    state.recompute_developer(developer["id"])
    if int(project["version"]) == version_before:
        store.touch(project)
    return response.ok(store.public(project), 200)


def _paid_call(project_id, milestone):
    for call in state.calls_of_project(project_id):
        if call["milestone"] == milestone and call["status"] == "PAID":
            return call
    return None


@bp.post("/projects/<project_id>/milestones")
def record_milestone(project_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("AssetManager", "Underwriter"))
    payload = validate.body(request)
    milestone = validate.in_enum(validate.as_string(payload, "milestone"), MILESTONES, "milestone")

    project = validate.get_project(project_id)
    status = project["status"]
    version_before = int(project["version"])

    if milestone == "CONSTRUCTION_START":
        if status != "COMMITTED" or _paid_call(project_id, "CONSTRUCTION_START") is None:
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The CONSTRUCTION_START call has not been paid.")
        project["status"] = "CONSTRUCTION"
    elif milestone == "LEASE_UP_50PCT":
        if status != "CONSTRUCTION" or _paid_call(project_id, "CONSTRUCTION_50PCT") is None:
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The CONSTRUCTION_50PCT call has not been paid.")
        project["status"] = "LEASE_UP"
    elif milestone == "LEASE_UP_STABILIZED":
        if status != "LEASE_UP" or _paid_call(project_id, "LEASE_UP_50PCT") is None:
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The LEASE_UP_50PCT call has not been paid.")
        project["status"] = "STABILIZED"
    elif milestone == "PLACED_IN_SERVICE":
        if status != "STABILIZED" or _paid_call(project_id, "LEASE_UP_STABILIZED") is None:
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The LEASE_UP_STABILIZED call has not been paid.")
        if clock.now() > clock._parse(project["placed_in_service_deadline"]):
            errors.fail(errors.ERR_PLACED_IN_SERVICE_DEADLINE_PASSED,
                        "The placed-in-service deadline has passed.")
        project["status"] = "COMPLIANCE_PERIOD"
        project["placed_in_service_at"] = clock.now_str()
    else:
        # CONSTRUCTION_50PCT has no project-status edge of its own.
        errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                    "No status transition is defined for that milestone.")

    store.touch(project)
    state.recompute_project(project_id)
    state.recompute_fund(project["fund_id"])
    state.recompute_developer(project["developer_id"])
    if int(project["version"]) == version_before:
        store.touch(project)
    return response.ok(store.public(project), 200)
