"""Deprecation timelines, the sunset cascade and rescission (PRD 3.8)."""

from flask import Blueprint

import calc
import errors
from auth import DESIGN_SYSTEM_LEAD, require_roles
from entities import get_component, get_plan, plan_json
from errors import fail
from responses import created, ok
from routes.common import respond_list
from store import days_between, iso, sort_created_asc, store
from validation import (body, opt_string, pagination, query_enum, req_bool,
                        req_datetime, req_string)

bp = Blueprint("deprecation", __name__, url_prefix="/design-system")

PLAN_STATES = ("DRAFT", "ANNOUNCED", "SUNSET", "REMOVED", "RESCINDED")


@bp.post("/components/<component_id>/deprecation-plans")
@require_roles(DESIGN_SYSTEM_LEAD)
def create_plan(component_id):
    payload = body()
    announced_at = req_datetime(payload, "announced_at")
    sunset_at = req_datetime(payload, "sunset_at")
    removal_at = req_datetime(payload, "removal_at")
    replacement_id = opt_string(payload, "replacement_component_id", 1, 200)
    guide_url = opt_string(payload, "migration_guide_url", 1, 500)
    if not (announced_at < sunset_at < removal_at):
        fail(errors.ERR_INVALID_REQUEST,
             "'announced_at' must precede 'sunset_at', which must precede 'removal_at'.")
    if replacement_id is not None and replacement_id == component_id:
        fail(errors.ERR_INVALID_REQUEST,
             "The replacement component must differ from the deprecated component.")

    component = get_component(component_id)
    if replacement_id is not None:
        get_component(replacement_id)

    required_days = calc.required_notice_days(component)
    actual_days = days_between(announced_at, sunset_at)
    if actual_days < required_days:
        fail(errors.ERR_DEPRECATION_NOTICE_TOO_SHORT,
             "The plan serves %d of the %d required notice days."
             % (actual_days, required_days))
    if days_between(sunset_at, removal_at) < 30:
        fail(errors.ERR_DEPRECATION_NOTICE_TOO_SHORT,
             "At least 30 whole days must separate 'sunset_at' and 'removal_at'.")

    for existing in store.plans.values():
        if existing["component_id"] != component["id"]:
            continue
        if existing["state"] not in ("DRAFT", "ANNOUNCED", "SUNSET"):
            continue
        if announced_at < existing["_removal_dt"] and \
                existing["_announced_dt"] < removal_at:
            fail(errors.ERR_DEPRECATION_WINDOW_OVERLAP,
                 "The plan's window overlaps an existing plan of this component.")

    row = store.new_row()
    row.update({
        "component_id": component["id"],
        "replacement_component_id": replacement_id,
        "announced_at": iso(announced_at),
        "sunset_at": iso(sunset_at),
        "removal_at": iso(removal_at),
        "migration_guide_url": guide_url,
        "migration_guide_state": "DRAFT" if guide_url is not None else "MISSING",
        "required_notice_days": required_days,
        "actual_notice_days": actual_days,
        "state": "DRAFT",
        "blocked_dependent_count": 0,
        "rescinded_at": None,
        "_announced_dt": announced_at,
        "_sunset_dt": sunset_at,
        "_removal_dt": removal_at,
    })
    store.plans[row["id"]] = row
    return created(plan_json(row))


@bp.get("/components/<component_id>/deprecation-plans")
@require_roles()
def list_plans(component_id):
    limit, offset = pagination()
    state = query_enum("state", PLAN_STATES)
    component = get_component(component_id)
    rows = [p for p in store.plans.values() if p["component_id"] == component["id"]]
    if state is not None:
        rows = [p for p in rows if p["state"] == state]
    return respond_list(sort_created_asc(rows), plan_json, limit, offset)


@bp.post("/deprecation-plans/<plan_id>/migration-guide")
@require_roles(DESIGN_SYSTEM_LEAD)
def attach_migration_guide(plan_id):
    payload = body()
    guide_url = req_string(payload, "migration_guide_url", 1, 500)
    publish = req_bool(payload, "publish")

    plan = get_plan(plan_id)
    component = store.components[plan["component_id"]]

    if plan["state"] != "DRAFT":
        fail(errors.ERR_INVALID_DEPRECATION_PLAN_STATE,
             "Only a DRAFT plan accepts a migration guide.")
    if component["lifecycle_state"] != "ACTIVE":
        fail(errors.ERR_INVALID_DEPRECATION_PLAN_STATE,
             "The component's lifecycle state is not ACTIVE.")
    if component["maturity_level"] == "STABLE" and not publish:
        fail(errors.ERR_MIGRATION_GUIDE_REQUIRED,
             "A STABLE component may not be announced without a published guide.")

    plan["migration_guide_url"] = guide_url
    if publish:
        plan["migration_guide_state"] = "PUBLISHED"
        plan["state"] = "ANNOUNCED"
        component["lifecycle_state"] = "DEPRECATION_ANNOUNCED"
        store.touch(component)
    else:
        plan["migration_guide_state"] = "DRAFT"
    store.touch(plan)
    return ok(plan_json(plan))


@bp.post("/deprecation-plans/<plan_id>/advance")
@require_roles(DESIGN_SYSTEM_LEAD)
def advance_plan(plan_id):
    plan = get_plan(plan_id)
    component = store.components[plan["component_id"]]

    if plan["state"] not in ("ANNOUNCED", "SUNSET"):
        fail(errors.ERR_INVALID_DEPRECATION_PLAN_STATE,
             "A plan in %s cannot be advanced." % plan["state"])

    if plan["state"] == "ANNOUNCED":
        if plan["migration_guide_state"] != "PUBLISHED":
            fail(errors.ERR_MIGRATION_GUIDE_REQUIRED,
                 "The migration guide must be PUBLISHED before sunset.")
        if store.now < plan["_sunset_dt"]:
            fail(errors.ERR_DEPRECATION_ADVANCE_NOT_DUE,
                 "The logical clock has not reached 'sunset_at'.")
        _sunset_cascade(plan, component)
    else:
        if store.now < plan["_removal_dt"]:
            fail(errors.ERR_DEPRECATION_ADVANCE_NOT_DUE,
                 "The logical clock has not reached 'removal_at'.")
        _removal_cascade(plan, component)

    store.touch(plan)
    return ok(plan_json(plan))


def _sunset_cascade(plan, component):
    """Three hops, each caused by the one before it; one bump per touched row."""
    plan["state"] = "SUNSET"

    # Hop 1 -- the component's lifecycle dimension moves.
    component["lifecycle_state"] = "SUNSET"
    store.touch(component)

    # Hop 2 -- fires because hop 1 changed lifecycle_state.
    consumers = []
    flipped = []
    for edge in calc.incoming_edges(component["id"]):
        if edge["compatibility_state"] != "COMPATIBLE":
            continue
        edge["compatibility_state"] = "SUNSET_PROVIDER"
        store.touch(edge)
        flipped.append(edge["id"])
        consumer = store.components.get(edge["consumer_component_id"])
        if consumer is not None and consumer not in consumers:
            consumers.append(consumer)

    for consumer in consumers:
        calc.recompute_blocked_dependency_count(consumer)
    plan["blocked_dependent_count"] = len(consumers)
    plan["_sunset_flipped_edge_ids"] = flipped

    # Hop 3 -- fires because hop 2 raised those consumers' blocked_dependency_count.
    for consumer in consumers:
        if consumer["maturity_level"] == "STABLE":
            consumer["maturity_level"] = "BETA"
            consumer["maturity_demotion_reason"] = "UPSTREAM_SUNSET"
        store.touch(consumer)


def _removal_cascade(plan, component):
    plan["state"] = "REMOVED"
    component["lifecycle_state"] = "REMOVED"

    teams = []
    for impl in calc.component_impls(component["id"]):
        if impl["status"] in ("PLANNED", "SHIPPED", "BLOCKED"):
            was_blocked = impl["status"] == "BLOCKED"
            impl["status"] = "RETIRED"
            store.touch(impl)
            if was_blocked and component["owning_team_id"] not in teams:
                teams.append(component["owning_team_id"])

    component["shipped_platform_count"] = 0
    component["coverage_state"] = "NONE"
    store.touch(component)

    for team_id in teams:
        team = store.teams.get(team_id)
        if team is not None:
            calc.recompute_team_blocked_impls(team)
            store.touch(team, bump=False)


@bp.post("/deprecation-plans/<plan_id>/rescind")
@require_roles(DESIGN_SYSTEM_LEAD)
def rescind_plan(plan_id):
    payload = body()
    req_string(payload, "reason", 1, 2000)

    plan = get_plan(plan_id)
    component = store.components[plan["component_id"]]

    if plan["state"] not in ("ANNOUNCED", "SUNSET"):
        fail(errors.ERR_INVALID_DEPRECATION_PLAN_STATE,
             "A plan in %s cannot be rescinded." % plan["state"])

    from_sunset = plan["state"] == "SUNSET"
    plan["state"] = "RESCINDED"
    plan["rescinded_at"] = store.now_iso
    component["lifecycle_state"] = "ACTIVE"

    if from_sunset:
        consumers = []
        for edge in calc.incoming_edges(component["id"]):
            if edge["compatibility_state"] != "SUNSET_PROVIDER":
                continue
            edge["compatibility_state"] = "COMPATIBLE"
            store.touch(edge)
            consumer = store.components.get(edge["consumer_component_id"])
            if consumer is not None and consumer not in consumers:
                consumers.append(consumer)
        for consumer in consumers:
            calc.recompute_blocked_dependency_count(consumer)
            store.touch(consumer)
        plan["blocked_dependent_count"] = 0

    store.touch(component)
    store.touch(plan)
    return ok(plan_json(plan))
