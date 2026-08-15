"""Department CRUD (§3.6)."""
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import not_found, invalid_request
from services.common import (
    now_iso, require_fields, parse_int, parse_pagination, sort_by_created_at,
    paginate,
)

bp = Blueprint("departments", __name__)


def dept_view(d):
    return {k: d[k] for k in ("id", "name", "code", "adjustment_pool_cents",
                              "committed_pool_cents", "projected_payroll_cents",
                              "created_at", "updated_at", "version")}


@bp.route("/comp/departments", methods=["POST"])
def create_department():
    require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["name", "code", "adjustment_pool_cents"])
    name = body["name"]
    if not isinstance(name, str) or not name:
        raise invalid_request("name must be a non-empty string")
    code = body["code"]
    if not isinstance(code, str) or not code:
        raise invalid_request("code must be a non-empty string")
    for d in store.departments.values():
        if d["code"] == code:
            raise invalid_request("code already taken")
    pool = parse_int(body["adjustment_pool_cents"], "adjustment_pool_cents", minimum=0)
    now = now_iso()
    d = {"id": new_id(), "name": name, "code": code,
         "adjustment_pool_cents": pool, "committed_pool_cents": 0,
         "projected_payroll_cents": 0,
         "created_at": now, "updated_at": now, "version": 1}
    store.departments[d["id"]] = d
    return success_object(dept_view(d), 201)


@bp.route("/comp/departments", methods=["GET"])
def list_departments():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = sort_by_created_at(list(store.departments.values()))
    page, total = paginate(rows, limit, offset)
    return success_list([dept_view(d) for d in page], limit, offset, total)


@bp.route("/comp/departments/<did>", methods=["GET"])
def get_department(did):
    get_auth()
    d = store.departments.get(did)
    if d is None:
        raise not_found("department not found")
    return success_object(dept_view(d))
