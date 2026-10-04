"""Utility routes: logical clock, cross-account ops run listing."""
from flask import Blueprint, request

import store
from errors import validation
from response import success_object, success_list
from serializers import ser_opsrun
from util import (
    find_or_404,
    format_iso,
    get_json_body,
    pagination_params,
    parse_iso,
    require_auth,
    sort_by_created,
)

bp = Blueprint("misc", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth(["PlatformAdmin"])
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str):
        raise validation("to_iso8601 must be an ISO 8601 timestamp string")
    try:
        dt = parse_iso(to_iso8601)
    except (ValueError, TypeError):
        raise validation("to_iso8601 must be an ISO 8601 timestamp string")
    store.CLOCK["current_utc"] = format_iso(dt)
    return success_object({"current_utc": store.CLOCK["current_utc"]})


@bp.get("/messaging/ops_runs/<ops_run_id>")
def get_ops_run_alias(ops_run_id):
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    run = find_or_404(store.OPSRUNS, ops_run_id)
    return success_object(ser_opsrun(run))


@bp.get("/messaging/ops_runs")
def list_ops_runs():
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    limit, offset = pagination_params()
    items = list(store.OPSRUNS.values())
    account_filter = request.args.get("account_id")
    if account_filter:
        items = [r for r in items if r["account_id"] == account_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_opsrun(r) for r in page], limit, offset, total)
