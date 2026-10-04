"""Epoch share-grant allocation (PRD 3.2) — waterfall allocation."""

from fractions import Fraction

import clock
import store

EPOCH_POOL_SHARES = 100000
BASE_SHARES_PER_1000 = 120
ACTIVITY_SHARES_PER_10K_LBS = 15
PROBATION_WEIGHT_PCT = 50

FORWARD_LOOKING_STATUSES = ("AWARDED", "IN_TRANSIT", "DELIVERED")


def _load_epoch_stamp(load, forward_looking):
    """When the load's poundage belongs to an epoch, and how many pounds."""
    if load["status"] == "DELIVERED":
        return load.get("delivered_at") or load["updated_at"], load.get("delivered_lbs") or 0
    if forward_looking and load["status"] in ("AWARDED", "IN_TRANSIT"):
        stamp = load.get("dispatched_at") or load.get("awarded_at") or load["updated_at"]
        return stamp, load["weight_lbs"]
    return None, 0


def prior_epoch_pounds(member_id, prior_epoch, forward_looking):
    total = 0
    for load in store.loads.values():
        if load.get("awarded_member_id") != member_id:
            continue
        if not forward_looking and load["status"] != "DELIVERED":
            continue
        if forward_looking and load["status"] not in FORWARD_LOOKING_STATUSES:
            continue
        stamp, pounds = _load_epoch_stamp(load, forward_looking)
        if stamp is None or pounds <= 0:
            continue
        if clock.epoch_of(stamp) == prior_epoch:
            total += pounds
    return total


def eligible_members():
    return [m for m in store.ordered(store.members.values())
            if m["certification_status"] in ("CERTIFIED", "PROBATION")]


def _demand(member, prior_epoch, forward_looking):
    base = (int(member["food_insecure_population"]) // 1000) * BASE_SHARES_PER_1000
    pounds = prior_epoch_pounds(member["id"], prior_epoch, forward_looking)
    activity = (pounds // 10000) * ACTIVITY_SHARES_PER_10K_LBS
    weight = 100 if member["certification_status"] == "CERTIFIED" else PROBATION_WEIGHT_PCT
    return ((base + activity) * weight) // 100


def compute_epoch_grants(prior_epoch, forward_looking):
    """Return {member_id: shares} for one epoch, computed from frozen pre-grant state."""
    members = eligible_members()
    demands = [(m, _demand(m, prior_epoch, forward_looking)) for m in members]
    total_demand = sum(d for _, d in demands)
    grants = {m["id"]: 0 for m, _ in demands}
    if total_demand <= 0:
        return grants

    remainders = []
    for member, demand in demands:
        numerator = EPOCH_POOL_SHARES * demand
        grants[member["id"]] = numerator // total_demand
        remainders.append((Fraction(numerator % total_demand, total_demand),
                           member["created_at"], member["_seq"], member["id"]))

    residual = EPOCH_POOL_SHARES - sum(grants.values())
    if residual > 0:
        # One frozen pass: fractional part DESC, member.created_at ASC, never by id.
        remainders.sort(key=lambda item: (-item[0], item[1], item[2]))
        for index in range(residual):
            grants[remainders[index % len(remainders)][3]] += 1
    return grants
