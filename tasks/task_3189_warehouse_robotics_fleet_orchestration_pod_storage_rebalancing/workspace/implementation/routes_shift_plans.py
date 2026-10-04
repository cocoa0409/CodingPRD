"""Shift plans blueprint."""

from flask import Blueprint, request

import errors
from calculations import throughput_projection
from cascades import entity_out
from db import store
from middleware import require_roles
from models import base_entity, get_or_404, req_int
from models import require_field
from response import success_object

bp = Blueprint("shift_plans", __name__)

READ_ROLES = {"FleetAdmin", "FlowController"}


@bp.route("/shift-plans", methods=["POST"])
def create_shift_plan():
    require_roles({"FleetAdmin"})
    body = request.get_json(silent=True) or {}
    plan_date = require_field(body, "plan_date")
    if not isinstance(plan_date, str):
        raise errors.validation("plan_date must be a string")
    # Shape: YYYY-MM-DD.
    import re

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", plan_date):
        raise errors.validation("plan_date must be YYYY-MM-DD")
    for p in store.shift_plans.values():
        if p["plan_date"] == plan_date:
            raise errors.validation(f"plan_date already exists: {plan_date}")
    staffed_pickers = req_int(body, "staffed_pickers", minimum=0)
    planned_units = req_int(body, "planned_units", minimum=0)
    plan = base_entity()
    plan.update(
        {
            "plan_date": plan_date,
            "staffed_pickers": staffed_pickers,
            "planned_units": planned_units,
            "projected_units": 0,
            "feasible": False,
        }
    )
    store.shift_plans[plan["id"]] = plan
    projected, feasible = throughput_projection(plan)
    plan["projected_units"] = projected
    plan["feasible"] = feasible
    return success_object(entity_out(plan), status=201)


@bp.route("/shift-plans/<plan_id>", methods=["GET"])
def get_shift_plan(plan_id):
    require_roles(READ_ROLES)
    plan = get_or_404(store.shift_plans, plan_id, "shift plan")
    return success_object(entity_out(plan))
