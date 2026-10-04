"""Developer guarantees: recording them and drawing against them."""

from flask import Blueprint, request

import calc
import clock
import errors
import response
import state
import store
import validate

bp = Blueprint("guarantees", __name__)

READ_GUARANTEES = ("AssetManager", "ComplianceOfficer", "Underwriter", "Investor", "PlatformAdmin")
WRITE_GUARANTEES = ("AssetManager", "Underwriter")
TYPES = ("OPERATING_DEFICIT", "RECAPTURE", "COMPLETION")


@bp.get("/projects/<project_id>/guarantees")
def list_guarantees(project_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_GUARANTEES)
    project = validate.get_project(project_id)
    if role == "Investor" and not validate.investor_holds_fund(user_id, project["fund_id"]):
        errors.fail(errors.ERR_FORBIDDEN_SCOPE,
                    "An Investor may read only projects of funds it subscribes to.")
    rows = store.listing(store.guarantees, {"project_id": project_id,
                                            "guarantee_type": request.args.get("guarantee_type"),
                                            "status": request.args.get("status")})
    limit, offset = response.pagination_args(request)
    window, meta = response.paginate(rows, limit, offset)
    return response.array([store.public(g) for g in window], 200, meta)


@bp.post("/projects/<project_id>/guarantees")
def create_guarantee(project_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, WRITE_GUARANTEES)
    payload = validate.body(request)
    guarantee_type = validate.in_enum(validate.as_string(payload, "guarantee_type"), TYPES,
                                      "guarantee_type")
    amount = validate.non_negative(validate.as_int(payload, "guaranteed_amount_cents"),
                                   "guaranteed_amount_cents")
    recapture_pct = validate.non_negative(validate.as_number(payload, "recapture_pct"),
                                          "recapture_pct")
    start = validate.as_datetime(payload, "coverage_start_date")
    end = validate.as_datetime(payload, "coverage_end_date")
    if clock._parse(start) >= clock._parse(end):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "coverage_start_date must be strictly before coverage_end_date.")

    project = validate.get_project(project_id)
    developer = validate.get_developer(project["developer_id"])

    # tier 7 — the sponsor safeguard.
    current_exposure = state.developer_exposure_cents(developer["id"])
    deeply_experienced = (int(developer["sponsor_experience_months"]) >= calc.EXPERIENCE_MONTHS_MIN
                          and int(developer["projects_completed"]) >= calc.PROJECTS_COMPLETED_MIN)
    if current_exposure + amount > int(developer["net_worth_cents"]) and not deeply_experienced:
        errors.fail(errors.ERR_GUARANTEE_EXPOSURE_EXCEEDED,
                    "The guarantee would push exposure above the developer's net worth.")

    # tier 8 — coverage windows of the same project and type must not overlap.
    new_start = clock._parse(start)
    new_end = clock._parse(end)
    for other in state.guarantees_of_project(project_id):
        if other["guarantee_type"] != guarantee_type or other["status"] == "RELEASED":
            continue
        other_start = clock._parse(other["coverage_start_date"])
        other_end = clock._parse(other["coverage_end_date"])
        if new_start < other_end and other_start < new_end:
            errors.fail(errors.ERR_COVERAGE_WINDOW_OVERLAP,
                        "An overlapping guarantee already covers this project and type.")

    guarantee = store.create(store.guarantees, {
        "project_id": project["id"],
        "guarantee_type": guarantee_type,
        "guaranteed_amount_cents": amount,
        "recapture_pct": recapture_pct,
        "coverage_start_date": start,
        "coverage_end_date": end,
        "drawn_amount_cents": 0,
        "remaining_capacity_cents": amount,
        "status": "ACTIVE",
    })
    store.touch(project)
    state.recompute_developer(developer["id"])
    return response.ok(store.public(guarantee), 201)


@bp.post("/guarantees/<guarantee_id>/draw")
def draw_guarantee(guarantee_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("AssetManager",))
    payload = validate.body(request)
    requested = validate.non_negative(validate.as_int(payload, "requested_amount_cents"),
                                      "requested_amount_cents")

    guarantee = validate.get_guarantee(guarantee_id)
    project = validate.get_project(guarantee["project_id"])
    developer = validate.get_developer(project["developer_id"])
    fund = validate.get_fund(project["fund_id"])

    if guarantee["status"] == "RELEASED":
        errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE, "A released guarantee cannot be drawn.")

    if requested == 0:
        # Reinstatement: the guarantee must still have capacity to absorb a later call.
        if int(guarantee["remaining_capacity_cents"]) <= 0:
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The guarantee has no remaining capacity.")
        if guarantee["status"] == "DRAWN":
            guarantee["status"] = "ACTIVE"
            store.touch(guarantee)
        state.recompute_developer(developer["id"])
        return response.ok(store.public(guarantee), 200)

    if int(guarantee["drawn_amount_cents"]) >= int(guarantee["guaranteed_amount_cents"]):
        errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                    "The guarantee is drawn to its full amount.")

    # tier 6 — the guarantee-type gating conditions.
    if guarantee["guarantee_type"] == "OPERATING_DEFICIT":
        if int(project["operating_deficit_cents"]) <= 0:
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The project carries no operating deficit.")
        _, _, _, developer_covered = calc.operating_deficit_coverage(project, developer)
        if developer_covered:
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The developer can cover the deficit from liquid assets.")
    elif guarantee["guarantee_type"] == "RECAPTURE":
        if not any(r["status"] in ("NONCOMPLIANT", "ESCALATED")
                   for r in state.reviews_of_project(project["id"])):
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The project has no noncompliant or escalated review.")
    elif guarantee["guarantee_type"] == "COMPLETION":
        if not any(r["status"] == "ESCALATED" for r in state.reviews_of_project(project["id"])):
            errors.fail(errors.ERR_PROJECT_NOT_COMMITTABLE,
                        "The project has no escalated review.")

    capacity = int(guarantee["remaining_capacity_cents"])
    guarantee["drawn_amount_cents"] = int(guarantee["drawn_amount_cents"]) + min(requested, capacity)
    guarantee["remaining_capacity_cents"] = max(
        0, int(guarantee["guaranteed_amount_cents"]) - int(guarantee["drawn_amount_cents"]))
    guarantee["status"] = "DRAWN"
    store.touch(guarantee)

    if guarantee["guarantee_type"] == "RECAPTURE":
        state.distress_project(project["id"])
    state.recompute_developer(developer["id"])
    state.recompute_fund(fund["id"])
    state.recompute_project(project["id"])
    return response.ok(store.public(guarantee), 200)
