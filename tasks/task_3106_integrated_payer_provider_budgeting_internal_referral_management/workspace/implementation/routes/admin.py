"""Administrative and test-driving endpoints."""

from flask import Blueprint, jsonify

from clock import CLOCK
from constants import ROLE_PLATFORM_ADMIN
from domain import (
    get_member,
    get_quality_metric,
    recompute_member_capitation,
    recompute_region_aggregates,
    touch,
)
from errors import raise_error
from response import success
from routes._common import payload, principal, require_field, single_response

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    principal((ROLE_PLATFORM_ADMIN,))
    body = payload()
    CLOCK.set(require_field(body, "to_iso8601"))
    return jsonify(success({}))


@bp.post("/_inject/member-risk-score")
def inject_member_risk_score():
    principal((ROLE_PLATFORM_ADMIN,))
    body = payload()
    member = get_member(require_field(body, "member_id"))
    member["risk_score"] = require_field(body, "risk_score")
    # Only the forward variant moves: the persisted capitation_rate_cents and
    # the region's premium_revenue_cents are deliberately left untouched
    # (PRD 3.7), so the settled margin is unchanged.
    recompute_region_aggregates(member["region_id"], bump_version=False)
    return single_response("members", member)


@bp.patch("/_outcome-targets/<metric_id>")
def set_outcome_targets(metric_id):
    principal((ROLE_PLATFORM_ADMIN,))
    metric = get_quality_metric(metric_id)
    body = payload()
    if body.get("measured_value") is not None:
        metric["measured_value"] = body["measured_value"]
    if body.get("weighted_component_score") is not None:
        metric["weighted_component_score"] = body["weighted_component_score"]
    touch(metric)
    return single_response("quality_metrics", metric)


_ = (recompute_member_capitation, raise_error)