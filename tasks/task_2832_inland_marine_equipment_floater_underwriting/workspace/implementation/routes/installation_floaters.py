from flask import Blueprint, request

import cascades
import rating
import store
import views
from common import (API_PREFIX, body, envelope_list, envelope_object, fail,
                    get_date, get_enum, paginate, parse_pagination, require)

bp = Blueprint("installation_floaters", __name__)

FLOATER = "/installation-floaters/<floater_id>"


def _floater(floater_id):
    return store.find(store.installation_floaters, floater_id,
                      "ERR_INSTALLATION_FLOATER_NOT_FOUND")


@bp.get(API_PREFIX + "/installation-floaters")
def list_floaters():
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster")
    limit, offset = parse_pagination()
    rows = store.order(list(store.installation_floaters.values()))
    for field in ("coverage_part_id", "jobsite_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.floater_view(r) for r in page], limit, offset, total)


@bp.get(API_PREFIX + FLOATER)
def get_floater(floater_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    floater = _floater(floater_id)
    return envelope_object(views.floater_view(floater), 200)


@bp.post(API_PREFIX + FLOATER + "/activate")
def activate_floater(floater_id):
    require("Underwriter")
    floater = _floater(floater_id)
    if floater["status"] != "PENDING":
        fail("ERR_FLOATER_NOT_IN_REQUIRED_STATE", "Floater is %s" % floater["status"])
    part = store.coverage_parts[floater["coverage_part_id"]]
    policy = store.policies[part["policy_id"]]
    if policy["status"] != "IN_FORCE":
        fail("ERR_POLICY_NOT_IN_FORCE", "Policy is %s" % policy["status"])
    jobsite = store.jobsites.get(floater["jobsite_id"])
    if (jobsite is None or jobsite["status"] != "SURVEYED"
            or jobsite["security_tier"] == "TIER_0"):
        fail("ERR_JOBSITE_SECURITY_INSUFFICIENT",
             "The jobsite must be SURVEYED above TIER_0")
    available = views.aggregate_available(part)
    if floater["installed_value_limit_cents"] > available:
        fail("ERR_FLOATER_LIMIT_EXCEEDS_PART_AGGREGATE",
             "installed_value_limit_cents exceeds the remaining part aggregate %s"
             % available)
    floater["status"] = "ACTIVE"
    store.touch(floater)
    # The premium is not recomputed: a re-survey between creation and activation
    # does not re-price the floater.
    return envelope_object(views.floater_view(floater), 200)


@bp.post(API_PREFIX + FLOATER + "/terminate")
def terminate_floater(floater_id):
    require("Underwriter")
    floater = _floater(floater_id)
    b = body()
    reason = get_enum(b, "termination_reason", ("ACCEPTANCE", "OCCUPANCY"))
    termination_date = get_date(b, "termination_date")
    if floater["status"] != "ACTIVE":
        fail("ERR_FLOATER_NOT_IN_REQUIRED_STATE", "Floater is %s" % floater["status"])
    if not (floater["coverage_start_date"] <= termination_date
            <= floater["coverage_end_date"]):
        fail("ERR_TERMINATION_DATE_OUTSIDE_COVERAGE",
             "termination_date must lie inside the floater's coverage interval")
    part = store.coverage_parts[floater["coverage_part_id"]]
    policy = store.policies[part["policy_id"]]
    earned, unearned = rating.apply_floater_termination(floater, reason,
                                                       termination_date)
    floater["status"] = ("TERMINATED_ACCEPTANCE" if reason == "ACCEPTANCE"
                         else "TERMINATED_OCCUPANCY")
    store.touch(floater)
    if reason == "ACCEPTANCE":
        if unearned:
            store.append_entry(policy["id"], "ENDORSEMENT_RETURN", -unearned,
                               "Unearned return on installation floater %s"
                               % floater["id"])
    else:
        policy["occupancy_termination_count"] = (
            policy["occupancy_termination_count"] + 1)
        store.touch(policy)
    rating.recompute_part(part)
    rating.reroll_policy(policy)
    cascades.floater_left_live_set(floater)
    return envelope_object(views.floater_view(floater), 200)
