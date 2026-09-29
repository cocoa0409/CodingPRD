"""Shared side-effect machinery: ledger endorsements and cascade re-rating."""
import datetime

import rating
import store
import views
from common import clock_date, clock_now, fail


def prorated_entry(policy, base_cents, memo, statuses=("IN_FORCE", "SUSPENDED"),
                   unconditional=False):
    """Book the prorated endorsement movement for a premium delta."""
    if not unconditional and policy["status"] not in statuses:
        return None
    amount = rating.endorsement_prorated_amount(policy, abs(base_cents))
    if amount == 0:
        return None
    if base_cents >= 0:
        return store.append_entry(policy["id"], "ENDORSEMENT_PREMIUM", amount, memo)
    return store.append_entry(policy["id"], "ENDORSEMENT_RETURN", -amount, memo)


# --------------------------------------------------------------------------
# Grade-A theft-control guard
# --------------------------------------------------------------------------
def check_geo_tracking(item, policy, jobsite, tier=None):
    """ERR_GEO_TRACKING_REQUIRED: a grade-A unit on a weakly secured site must
    carry a geo-tracker."""
    if jobsite is None:
        return
    effective_tier = tier if tier is not None else jobsite["security_tier"]
    if item["geo_tracker_installed"]:
        return
    if effective_tier not in ("TIER_0", "TIER_1"):
        return
    age = rating.age_years_at_rating(item["model_year"])
    rule = rating.select_rate_rule(item["equipment_type"], jobsite["territory_code"],
                                   age, required=False)
    if rule is None:
        return
    if rule["theft_hazard_grade"] == "A":
        fail("ERR_GEO_TRACKING_REQUIRED",
             "Grade A equipment on a %s jobsite requires a geo-tracker" % effective_tier)


# --------------------------------------------------------------------------
# Jobsite-driven re-rating cascade
# --------------------------------------------------------------------------
def rerate_items_on_jobsite(jobsite, statuses=("IN_FORCE", "SUSPENDED")):
    parts = {}
    policies = {}
    for item in store.order(list(store.equipment_items.values())):
        if item.get("assigned_jobsite_id") != jobsite["id"]:
            continue
        if item["status"] not in rating.ON_SCHEDULE_STATUSES:
            continue
        part = store.coverage_parts.get(item["coverage_part_id"])
        if part is None:
            continue
        policy = store.policies.get(part["policy_id"])
        if policy is None:
            continue
        if policy["status"] in ("DECLINED", "CANCELLED"):
            # The schedule of a declined or cancelled file is off risk; the
            # release cascade has nothing left to re-develop there.
            continue
        outcome = rating.rate_equipment_item(item, policy, required=False)
        if outcome is None:
            continue
        before = item["rated_premium_cents"] or 0
        rating.apply_rating(item, outcome)
        delta = (item["rated_premium_cents"] or 0) - before
        parts[part["id"]] = part
        entry = policies.setdefault(policy["id"], [policy, 0])
        entry[1] += delta
    for part in parts.values():
        rating.recompute_part(part)
    for policy, delta in policies.values():
        rating.reroll_policy(policy)
        if delta != 0:
            prorated_entry(policy, delta,
                           "Re-rating after jobsite security change", statuses)


def floater_left_live_set(floater):
    """Decrement the jobsite's live floater count and run the release cascade."""
    jobsite = store.jobsites.get(floater["jobsite_id"])
    if jobsite is None:
        return
    store.touch(jobsite)
    if views.active_floater_count(jobsite) == 0 and jobsite["status"] == "SURVEYED":
        jobsite["status"] = "RELEASED"
        store.touch(jobsite)
        rerate_items_on_jobsite(jobsite)


# --------------------------------------------------------------------------
# Policy-level cascades
# --------------------------------------------------------------------------
def void_parts_and_floaters(policy, trigger):
    """Shared by referral decline and cancellation."""
    departing = []
    for part in store.parts_of_policy(policy["id"]):
        for floater in store.floaters_of_part(part["id"]):
            if floater["status"] in ("PENDING", "ACTIVE"):
                floater["status"] = "VOIDED"
                floater["termination_trigger"] = trigger
                # PRD 3.6: a VOIDED floater carries unearned_return_cents zero
                # because the policy-level cancellation return already handled
                # that premium.  No termination_date is recorded.
                floater["unearned_return_cents"] = 0
                store.touch(floater)
                departing.append(floater)
    for part in store.parts_of_policy(policy["id"]):
        if part["status"] == "ACTIVE":
            part["status"] = "VOID"
            store.touch(part)
    for floater in departing:
        floater_left_live_set(floater)


def expire_policies_and_floaters():
    """Run after the logical clock moves.  Returns (policy_ids, floater_ids)."""
    today = clock_date()
    expired_policies = []
    for policy in store.order(list(store.policies.values())):
        if policy["status"] in ("IN_FORCE", "SUSPENDED") and today >= policy["expiration_date"]:
            policy["status"] = "EXPIRED"
            store.touch(policy)
            expired_policies.append(policy)
    expired_policy_ids = {p["id"] for p in expired_policies}
    expired_floaters = []
    for floater in store.order(list(store.installation_floaters.values())):
        if floater["status"] != "ACTIVE":
            continue
        part = store.coverage_parts.get(floater["coverage_part_id"])
        policy_id = part["policy_id"] if part else None
        if today > floater["coverage_end_date"] or policy_id in expired_policy_ids:
            floater["status"] = "EXPIRED"
            rating.apply_floater_termination(floater, "EXPIRY",
                                             floater["coverage_end_date"])
            store.touch(floater)
            expired_floaters.append(floater)
    touched_parts = {}
    for floater in expired_floaters:
        floater_left_live_set(floater)
        part = store.coverage_parts.get(floater["coverage_part_id"])
        if part is not None:
            touched_parts[part["id"]] = part
    for part in touched_parts.values():
        rating.recompute_part(part)
        policy = store.policies.get(part["policy_id"])
        if policy is not None:
            rating.reroll_policy(policy)
    return ([p["id"] for p in expired_policies], [f["id"] for f in expired_floaters])


def cure_delinquency(policy):
    """If no DELINQUENT report remains on any coverage part of the policy and the
    policy is SUSPENDED, the policy returns SUSPENDED -> IN_FORCE."""
    if policy["status"] != "SUSPENDED":
        return False
    for part in store.parts_of_policy(policy["id"]):
        for report in store.reports_of_part(part["id"]):
            if report["status"] == "DELINQUENT":
                return False
    policy["status"] = "IN_FORCE"
    store.touch(policy)
    return True
