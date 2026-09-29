"""Circulation plans: merge-purge, costing, review, approval, revision, cancel."""

from flask import Blueprint

import validate as v
from db import by_created, db, new_row, now, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    CIRCULATION_DIRECTOR,
    CIRCULATION_PLANNER,
    LIST_BROKER,
    NO_BROKER,
    auth,
)
from response import entity_response, list_response
from services import domain
from routes.config import find_season

bp = Blueprint("plans", __name__)

PLAN_STATUSES = ("DRAFT", "COSTED", "UNDER_REVIEW", "APPROVED", "CANCELLED")
RUN_STATUSES = ("PENDING", "COMPLETED", "FAILED", "SUPERSEDED", "STALE")
CANCELLABLE_PLAN_STATUSES = ("DRAFT", "COSTED", "UNDER_REVIEW", "APPROVED")


def find_plan(plan_id):
    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return plan


def require_editable(plan):
    if plan["status"] not in domain.EDITABLE_PLAN_STATUSES:
        raise ApiError("ERR_PLAN_NOT_EDITABLE")


@bp.post("/circulation-plans")
def create_plan():
    auth(CIRCULATION_PLANNER)
    body = v.json_body()

    season_id = body.get("season_id")
    if isinstance(season_id, str) and season_id.strip() != "":
        if season_id not in db.seasons:
            raise ApiError("ERR_SEASON_NOT_FOUND")

    season_id = v.get_id(body, "season_id")
    if season_id not in db.seasons:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    plan_code = v.get_str(body, "plan_code", min_len=1)
    budget_cents = v.get_int(body, "budget_cents", minimum=1)

    for existing in db.plans.values():
        if existing["season_id"] == season_id and existing["plan_code"] == plan_code:
            raise ApiError("ERR_DUPLICATE_PLAN_CODE")

    row = new_row()
    row.update(
        {
            "season_id": season_id,
            "plan_code": plan_code,
            "budget_cents": budget_cents,
            "status": "DRAFT",
            "revision_round": 0,
            "costed_by_user_id": None,
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "committed_cost_cents": 0,
            "uncommitted_budget_cents": budget_cents,
            "planned_cost_cents": 0,
            "planned_demand_cents": 0,
            "planned_contribution_cents": 0,
        }
    )
    db.plans[row["id"]] = row
    return entity_response(row, 201)


@bp.get("/circulation-plans/<plan_id>")
def read_plan(plan_id):
    auth(*ALL_ROLES)
    return entity_response(find_plan(plan_id))


@bp.get("/seasons/<season_id>/circulation-plans")
def list_season_plans(season_id):
    auth(*ALL_ROLES)
    season = find_season(season_id)
    limit, offset = v.pagination()
    status = v.filter_enum("status", PLAN_STATUSES)
    matching = [p for p in db.plans.values() if p["season_id"] == season["id"]]
    if status is not None:
        matching = [p for p in matching if p["status"] == status]
    matching.sort(key=lambda p: (p["plan_code"], p["created_at"], p["_seq"]))
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/circulation-plans/<plan_id>/profitability")
def read_plan_profitability(plan_id):
    auth(*NO_BROKER)
    plan = find_plan(plan_id)
    # A pure read: no status change and no version increment.
    domain.recompute_plan_rollup(plan)
    return entity_response(plan)


# ---------------------------------------------------------------------------
# Merge-purge runs
# ---------------------------------------------------------------------------


@bp.post("/circulation-plans/<plan_id>/merge-purge-runs")
def create_merge_purge_run(plan_id):
    auth(LIST_BROKER)
    plan = find_plan(plan_id)
    body = v.json_body()

    # Ladder step 4 — every element of input_rental_ids resolves.
    raw_ids = body.get("input_rental_ids")
    if isinstance(raw_ids, list):
        for element in raw_ids:
            if isinstance(element, str) and element not in db.rentals:
                raise ApiError("ERR_RENTAL_NOT_FOUND")

    # Ladder step 5 — schema.
    expected_plan_version = v.get_int(body, "expected_plan_version", minimum=0)
    if raw_ids is None or not isinstance(raw_ids, list):
        v.invalid("Field 'input_rental_ids' must be an array.")
    if len(raw_ids) > 20:
        v.invalid("Field 'input_rental_ids' may not hold more than 20 elements.")
    for element in raw_ids:
        if not isinstance(element, str) or element.strip() == "":
            v.invalid("Every element of 'input_rental_ids' must be an identifier.")
    if len(set(raw_ids)) != len(raw_ids):
        v.invalid("Field 'input_rental_ids' may not repeat an element.")

    # Ladder step 8 — owning plan editable.
    require_editable(plan)

    # Ladder step 10 — optimistic concurrency.
    if expected_plan_version != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION")

    rentals = []
    for rental_id in raw_ids:
        rental = db.rentals.get(rental_id)
        if rental is None or rental["season_id"] != plan["season_id"]:
            raise ApiError("ERR_RENTAL_NOT_FOUND")
        rentals.append(rental)

    # Ladder step 14 — every resolved rental sits in DELIVERED.
    for rental in rentals:
        if rental["status"] != "DELIVERED":
            raise ApiError("ERR_RENTAL_NOT_NETTED")

    figures = domain.compute_merge_purge(plan, rentals)
    post_dedup = figures.pop("_post_dedup")

    row = new_row()
    row.update(
        {
            "circulation_plan_id": plan["id"],
            "input_rental_ids": list(raw_ids),
            "observed_plan_version": expected_plan_version,
            "status": "PENDING",
        }
    )
    row.update(figures)

    if figures["net_mailable_names"] > 0:
        row["status"] = "COMPLETED"
        for rental in rentals:
            rental["net_names_delivered"] = post_dedup[rental["id"]]
            rental["status"] = "NETTED"
            touch(rental)
        for other in by_created(list(db.merge_purge_runs.values())):
            if other["circulation_plan_id"] != plan["id"]:
                continue
            if other["status"] != "COMPLETED":
                continue
            other["status"] = "SUPERSEDED"
            touch(other)
    else:
        row["status"] = "FAILED"

    db.merge_purge_runs[row["id"]] = row
    touch(plan)
    return entity_response(row, 201)


@bp.get("/circulation-plans/<plan_id>/merge-purge-runs")
def list_merge_purge_runs(plan_id):
    auth(*ALL_ROLES)
    plan = find_plan(plan_id)
    limit, offset = v.pagination()
    status = v.filter_enum("status", RUN_STATUSES)
    matching = [
        r for r in db.merge_purge_runs.values() if r["circulation_plan_id"] == plan["id"]
    ]
    if status is not None:
        matching = [r for r in matching if r["status"] == status]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Plan lifecycle
# ---------------------------------------------------------------------------


@bp.post("/circulation-plans/<plan_id>/cost")
def cost_plan(plan_id):
    user_id, _role = auth(CIRCULATION_PLANNER)
    plan = find_plan(plan_id)
    v.json_body()

    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PLAN_STATE")
    live_drops = [
        d for d in domain.drops_of_plan(plan["id"]) if d["production_status"] != "CANCELLED"
    ]
    if not live_drops:
        raise ApiError("ERR_INVALID_PLAN_STATE")
    allocated_anywhere = False
    for drop in live_drops:
        for line in domain.lines_of_drop(drop["id"]):
            if line["status"] == "ALLOCATED":
                allocated_anywhere = True
                break
        if allocated_anywhere:
            break
    if not allocated_anywhere:
        raise ApiError("ERR_INVALID_PLAN_STATE")
    if not domain.plan_has_completed_merge_purge(plan["id"]):
        raise ApiError("ERR_MERGE_PURGE_REQUIRED")

    for drop in domain.drops_of_plan(plan["id"]):
        if drop["production_status"] not in ("PLANNED", "PRESORTED"):
            continue
        domain.recompute_drop_cost(drop, variant="ESTIMATED_POSTAGE")
        domain.recompute_allocated_lines_of_drop(drop)

    domain.recompute_plan_rollup(plan)
    plan["costed_by_user_id"] = user_id
    plan["status"] = "COSTED"
    touch(plan)
    return entity_response(plan)


@bp.post("/circulation-plans/<plan_id>/submit-review")
def submit_plan_for_review(plan_id):
    user_id, _role = auth(CIRCULATION_PLANNER)
    plan = find_plan(plan_id)
    v.json_body()
    if plan["status"] != "COSTED":
        raise ApiError("ERR_INVALID_PLAN_STATE")
    plan["submitted_by_user_id"] = user_id
    plan["status"] = "UNDER_REVIEW"
    touch(plan)
    return entity_response(plan)


@bp.post("/circulation-plans/<plan_id>/request-revision")
def request_plan_revision(plan_id):
    auth(CIRCULATION_DIRECTOR)
    plan = find_plan(plan_id)
    body = v.json_body()
    v.get_optional_text(body, "note")

    if plan["status"] not in ("UNDER_REVIEW", "APPROVED"):
        raise ApiError("ERR_INVALID_PLAN_STATE")

    from_approved = plan["status"] == "APPROVED"
    if from_approved:
        for drop in domain.drops_of_plan(plan["id"]):
            if drop["production_status"] in ("MAILED", "DELIVERED"):
                raise ApiError("ERR_INVALID_PLAN_STATE")

    plan["revision_round"] = plan["revision_round"] + 1
    plan["costed_by_user_id"] = None
    plan["submitted_by_user_id"] = None
    plan["status"] = "DRAFT"

    if from_approved:
        plan["approved_by_user_id"] = None
        for drop in domain.drops_of_plan(plan["id"]):
            if drop["production_status"] != "PRESORTED":
                continue
            for batch in domain.batches_of_drop(drop["id"]):
                del db.batches[batch["id"]]
            drop["production_status"] = "PLANNED"
            drop["postage_total_cents"] = 0
            drop["automation_share_bps"] = 0
            drop["automation_qualified"] = False
            domain.recompute_drop_cost(drop, variant="ESTIMATED_POSTAGE")
            domain.recompute_allocated_lines_of_drop(drop)
            touch(drop)
        domain.recompute_plan_rollup(plan)

    touch(plan)
    return entity_response(plan)


@bp.post("/circulation-plans/<plan_id>/approve")
def approve_plan(plan_id):
    user_id, _role = auth(CIRCULATION_DIRECTOR)
    plan = find_plan(plan_id)
    v.json_body()
    if plan["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PLAN_STATE")
    if user_id == plan["costed_by_user_id"] or user_id == plan["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if plan["planned_contribution_cents"] < 0:
        raise ApiError("ERR_PLAN_CONTRIBUTION_NEGATIVE")
    plan["approved_by_user_id"] = user_id
    plan["status"] = "APPROVED"
    touch(plan)
    return entity_response(plan)


@bp.post("/circulation-plans/<plan_id>/cancel")
def cancel_plan(plan_id):
    auth(CIRCULATION_DIRECTOR)
    plan = find_plan(plan_id)
    body = v.json_body()
    v.get_optional_text(body, "reason")

    if plan["status"] not in CANCELLABLE_PLAN_STATUSES:
        raise ApiError("ERR_INVALID_PLAN_STATE")
    drops = domain.drops_of_plan(plan["id"])
    for drop in drops:
        if drop["production_status"] in ("MAILED", "DELIVERED"):
            raise ApiError("ERR_INVALID_PLAN_STATE")

    for line in domain.lines_of_plan(plan["id"]):
        if line["status"] in domain.LIVE_LINE_STATUSES:
            domain.void_line(line, plan)

    for drop in drops:
        if drop["production_status"] not in ("PLANNED", "PRESORTED"):
            continue
        if drop["production_status"] == "PRESORTED":
            for batch in domain.batches_of_drop(drop["id"]):
                del db.batches[batch["id"]]
        drop["production_status"] = "CANCELLED"
        touch(drop)

    for run in by_created(list(db.merge_purge_runs.values())):
        if run["circulation_plan_id"] != plan["id"]:
            continue
        if run["status"] != "COMPLETED":
            continue
        run["status"] = "SUPERSEDED"
        touch(run)

    domain.recompute_plan_budget(plan)
    domain.recompute_plan_rollup(plan)
    plan["status"] = "CANCELLED"
    touch(plan)
    return entity_response(plan)
