"""Regional policy records and the generation-advance capability."""

from flask import Blueprint, request

from db import STORE, add_days, now
from errors import ApiError, ERR_RESOURCE_NOT_FOUND
from middleware import (assert_version_matches, body, new_id, require_version, route,
                        stamp, touch)
from response import created, read_pagination, success, success_list
from serializers import policy as serialize_policy
from calculations import drift_step, rescreen_anchor, _DEFAULTS
from services import common

bp = Blueprint("policies", __name__)

_READ_ROLES = ("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead",
               "SafetyAppealReviewer", "RegulatorLiaison", "BackgroundReviewer")

PERIODICITY_FIELDS = (
    "rollup_window_days", "rollup_threshold", "cluster_watchlist_threshold",
    "cluster_purge_threshold", "rescreen_refresh_days",
    "continuous_monitor_ack_deadline_days", "expedite_appeal_baseline_count",
    "expedite_review_days", "standard_review_days", "appeal_window_days",
    "sd_floor_severity",
)
FREQUENCY_FIELDS = ("sd_floor_enabled", "escalation_enabled")


def get_policy(policy_id):
    policy = STORE.policies.get(policy_id)
    if policy is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such platform policy: %s" % policy_id)
    return policy


@bp.route("/safety/platform-policies", methods=["POST"])
@route("PlatformAdmin")
def create_policy(ident):
    payload = body()
    policy = {}
    for field, default in _DEFAULTS.items():
        value = payload.get(field)
        policy[field] = default if value is None else value
    policy["region_code"] = payload.get("region_code")
    policy["status"] = "PUBLISHED"
    stamp(policy)
    STORE.policies[policy["id"]] = policy

    # Every existing account in the region receives the new record's generation.
    for account in STORE.accounts_in_region(policy.get("region_code")):
        account["policy_generation_index"] = int(policy.get("knob_generation_index", 1))
        touch(account)
    return created(serialize_policy(policy))


@bp.route("/safety/platform-policies", methods=["GET"])
@route(*_READ_ROLES)
def list_policies(ident):
    limit, offset = read_pagination(request.args)
    items = list(STORE.policies.values())
    wanted = request.args.get("region_code")
    if wanted is not None:
        items = [p for p in items if p.get("region_code") == wanted]
    items.sort(key=lambda p: (p.get("created_at"), p.get("id") or ""))
    return success_list([serialize_policy(p) for p in items], limit, offset)


@bp.route("/safety/platform-policies/<policy_id>", methods=["GET"])
@route(*_READ_ROLES)
def get_one_policy(ident, policy_id):
    return success(serialize_policy(get_policy(policy_id)))


@bp.route("/safety/platform-policies/<policy_id>", methods=["PATCH"])
@route("PlatformAdmin")
def patch_policy(ident, policy_id):
    policy = get_policy(policy_id)
    payload = body()
    require_version(payload, "expected_policy_version")
    assert_version_matches(payload, "expected_policy_version", policy, "PlatformPolicy")

    patched = [f for f in payload.keys() if f not in ("expected_policy_version",)]
    touches_periodicity = any(f in PERIODICITY_FIELDS for f in patched)
    touches_frequency = any(f in FREQUENCY_FIELDS for f in patched)

    for field in patched:
        if field in _DEFAULTS or field in ("review_generation_index", "knob_generation_index"):
            policy[field] = payload.get(field)

    if touches_periodicity:
        policy["review_generation_index"] = int(policy.get("review_generation_index", 1)) + 1
        STORE.clock = add_days(now(), 1)
    if touches_frequency:
        policy["knob_generation_index"] = int(policy.get("knob_generation_index", 1)) + 1

    touch(policy)
    _restamp_region(policy)
    return success(serialize_policy(policy))


@bp.route("/safety/config/advance", methods=["POST"])
@route("PlatformAdmin")
def advance(ident):
    payload = body()
    region = payload.get("region_code")
    policy = STORE.policy_for_region(region)
    if policy is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No policy is published for region %s." % region)

    counter = payload.get("advance_counter")
    if counter == "knob_generation_index":
        policy["knob_generation_index"] = int(policy.get("knob_generation_index", 1)) + 1
    else:
        policy["review_generation_index"] = int(policy.get("review_generation_index", 1)) + 1
    touch(policy)

    _restamp_region(policy)
    # Every cluster in the region has its aggregate recomputed and re-stamped.
    from calculations import recompute_cluster_aggregate
    for cluster in STORE.clusters_in_region(region):
        recompute_cluster_aggregate(cluster)
        cluster["cluster_risk_generation_index"] = int(policy.get("knob_generation_index", 1))
        touch(cluster)
    return success(serialize_policy(policy))


def _restamp_region(policy):
    region = policy.get("region_code")
    generation = int(policy.get("knob_generation_index", 1))
    review_generation = int(policy.get("review_generation_index", 1))
    refresh_days = int(policy.get("rescreen_refresh_days", 548))

    for account in STORE.accounts_in_region(region):
        account["policy_generation_index"] = generation
        touch(account)
        # Every member background check is re-anchored against the new interval.
        for check in STORE.account_checks(account.get("id")):
            anchor = rescreen_anchor(account.get("id"))
            if anchor is not None and check.get("check_status") != "COMPLETED":
                check["scheduled_due_at"] = add_days(
                    anchor, (drift_step(review_generation) + 1) * refresh_days)
                touch(check)
        for check in STORE.account_checks(account.get("id")):
            if check.get("check_kind") == "CONTINUOUS_MONITOR" \
                    and check.get("check_status") != "COMPLETED":
                check["monitor_generation"] = review_generation
                touch(check)