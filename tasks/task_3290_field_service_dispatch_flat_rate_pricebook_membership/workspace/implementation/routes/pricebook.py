"""Pricebook task revisions (PRD 3.2)."""

from flask import Blueprint, request

from constants import ROLE_DISPATCHER, PLAN_STATUSES, TASK_CATEGORIES, OPTION_TIERS
from common import (body_json, require_roles, require_str, require_int,
                    optional_number, optional_int, enum_field, is_code_string,
                    optional_str)
from constants import clock
import store
import serializers
from errors import invalid_request, not_found
from response import created, object_ok

bp = Blueprint("pricebook", __name__)


def _parse_options(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise invalid_request("options must be an array")
    seen = set()
    parsed = []
    for element in raw:
        if not isinstance(element, dict):
            raise invalid_request("each option must be an object")
        tier = element.get("tier")
        if tier not in OPTION_TIERS:
            raise invalid_request("option tier must be one of GOOD, BETTER, BEST")
        if tier in seen:
            raise invalid_request("a task may carry at most one option per tier")
        seen.add(tier)
        price = element.get("price_cents")
        if price is None or isinstance(price, bool) or not isinstance(price, (int, float)):
            raise invalid_request("an option requires an integer price_cents")
        materials = element.get("included_materials_cents", 0)
        warranty = element.get("warranty_months", 0)
        label = element.get("label", tier)
        parsed.append({
            "tier": tier,
            "label": label,
            "price_cents": int(price),
            "included_materials_cents": int(materials or 0),
            "warranty_months": int(warranty or 0),
        })
    parsed.sort(key=lambda o: ("GOOD", "BETTER", "BEST").index(o["tier"]))
    return parsed


@bp.route("/pricebook/tasks", methods=["POST"])
def create_task():
    require_roles([ROLE_DISPATCHER])
    payload = body_json()
    code = require_str(payload, "code")
    if not is_code_string(code):
        raise invalid_request("code must be uppercase A-Z, 0-9 and dashes")
    category = enum_field(payload, "category", TASK_CATEGORIES, required=True)
    display_name = require_str(payload, "display_name")
    required_skill_code = require_str(payload, "required_skill_code")
    if not is_code_string(required_skill_code):
        raise invalid_request("required_skill_code must be uppercase A-Z, 0-9 and dashes")
    estimated_hours = optional_number(payload, "estimated_hours")
    if estimated_hours is None or float(estimated_hours) <= 0:
        raise invalid_request("estimated_hours must be greater than zero and is required")
    flat_rate_cents = optional_int(payload, "flat_rate_cents")
    if flat_rate_cents is None:
        raise invalid_request("flat_rate_cents is required")
    if flat_rate_cents < 0:
        raise invalid_request("flat_rate_cents must not be negative")
    options = _parse_options(payload.get("options"))
    status = enum_field(payload, "status", PLAN_STATUSES, "DRAFT")

    existing = [t for t in store.pricebook_tasks.values() if t["code"] == code]
    if existing:
        revision = max(int(t["revision"]) for t in existing) + 1
    else:
        revision = 1

    row = store.new_row(
        "PricebookTask",
        code=code,
        revision=revision,
        category=category,
        display_name=display_name,
        required_skill_code=required_skill_code,
        estimated_hours=float(estimated_hours),
        flat_rate_cents=flat_rate_cents,
        status=status,
        published_at_utc=clock.now() if status == "PUBLISHED" else None,
        options=options,
    )
    store.pricebook_tasks[row["id"]] = row
    return created(serializers.pricebook_task(row))


@bp.route("/pricebook/tasks", methods=["GET"])
def list_tasks():
    """Not in the routing table of PRD section 4; provided as an inert read
    over the revision lineage.  Any authenticated role may call it."""
    from common import auth
    from response import read_pagination, paginate, array_ok
    auth()
    limit, offset = read_pagination(request.args)
    items = store.by_created(store.pricebook_tasks)
    code = request.args.get("code")
    status = request.args.get("status")
    if code:
        items = [t for t in items if t["code"] == code]
    if status:
        items = [t for t in items if t["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_ok([serializers.pricebook_task(t) for t in page], limit, offset, total)


@bp.route("/pricebook/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    """Inert read of one revision; not in the routing table of PRD section 4."""
    from common import auth
    auth()
    row = store.pricebook_tasks.get(task_id)
    if row is None:
        raise not_found("pricebook task")
    return object_ok(serializers.pricebook_task(row))