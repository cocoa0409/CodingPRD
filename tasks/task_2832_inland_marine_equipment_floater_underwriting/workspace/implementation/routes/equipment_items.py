from flask import Blueprint, request

import cascades
import rating
import store
import views
from common import (API_PREFIX, body, clock_now, envelope_list, envelope_object,
                    fail, paginate, parse_pagination, require)

bp = Blueprint("equipment_items", __name__)

ITEM = "/equipment-items/<item_id>"

ON_RISK_STATES = ("RATED", "ACTIVE")


def _item(item_id):
    return store.find(store.equipment_items, item_id, "ERR_EQUIPMENT_ITEM_NOT_FOUND")


@bp.get(API_PREFIX + "/equipment-items")
def list_items():
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Actuary")
    limit, offset = parse_pagination()
    rows = store.order(list(store.equipment_items.values()))
    for field in ("coverage_part_id", "assigned_jobsite_id", "applied_rate_rule_id",
                  "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    page, total = paginate(rows, limit, offset)
    return envelope_list([views.item_view(r) for r in page], limit, offset, total)


@bp.get(API_PREFIX + ITEM)
def get_item(item_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster", "Policyholder")
    item = _item(item_id)
    return envelope_object(views.item_view(item), 200)


@bp.post(API_PREFIX + ITEM + "/assign-jobsite")
def assign_jobsite(item_id):
    require("Underwriter")
    item = _item(item_id)
    b = body()
    raw = b.get("jobsite_id")
    jobsite = store.jobsites.get(raw) if isinstance(raw, str) else None
    if jobsite is None:
        fail("ERR_JOBSITE_NOT_FOUND", "Jobsite %s does not exist" % (raw,))
    if item["status"] not in ON_RISK_STATES:
        fail("ERR_ITEM_ALREADY_OFF_RISK", "Item is %s" % item["status"])
    part = store.coverage_parts[item["coverage_part_id"]]
    policy = store.policies[part["policy_id"]]
    candidate = dict(item)
    candidate["assigned_jobsite_id"] = jobsite["id"]
    cascades.check_geo_tracking(candidate, policy, jobsite)
    before = item["rated_premium_cents"] or 0
    item["assigned_jobsite_id"] = jobsite["id"]
    outcome = rating.rate_equipment_item(item, policy)
    rating.apply_rating(item, outcome)
    rating.recompute_part(part)
    rating.reroll_policy(policy)
    delta = (item["rated_premium_cents"] or 0) - before
    # PRD 3.3: re-siting books its endorsement only while the policy is IN_FORCE.
    cascades.prorated_entry(policy, delta,
                            "Endorsement: re-sited equipment item %s" % item["id"],
                            statuses=("IN_FORCE",))
    return envelope_object(views.item_view(item), 200)


@bp.post(API_PREFIX + ITEM + "/activate")
def activate_item(item_id):
    require("Underwriter")
    item = _item(item_id)
    if item["status"] != "RATED":
        fail("ERR_ITEM_ALREADY_OFF_RISK", "Item is %s" % item["status"])
    part = store.coverage_parts[item["coverage_part_id"]]
    if part["status"] == "VOID":
        fail("ERR_PART_VOID", "Coverage part is VOID")
    policy = store.policies[part["policy_id"]]
    if policy["status"] != "IN_FORCE":
        fail("ERR_POLICY_NOT_IN_FORCE", "Policy is %s" % policy["status"])
    item["status"] = "ACTIVE"
    store.touch(item)
    return envelope_object(views.item_view(item), 200)


@bp.delete(API_PREFIX + ITEM)
def remove_item(item_id):
    require("Underwriter")
    item = _item(item_id)
    if item["status"] not in ON_RISK_STATES:
        fail("ERR_ITEM_ALREADY_OFF_RISK", "Item is %s" % item["status"])
    part = store.coverage_parts[item["coverage_part_id"]]
    policy = store.policies[part["policy_id"]]
    if policy["status"] not in rating.MUTABLE_POLICY_STATUSES:
        fail("ERR_POLICY_NOT_MUTABLE", "Policy is %s" % policy["status"])
    returned = item["rated_premium_cents"] or 0
    item["status"] = "REMOVED"
    item["removed_at"] = clock_now()
    store.touch(item)
    rating.recompute_part(part)
    rating.reroll_policy(policy)
    cascades.prorated_entry(policy, -returned,
                            "Endorsement: removed equipment item %s" % item["id"])
    return envelope_object(views.item_view(item), 200)
