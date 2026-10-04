"""Product safety containment: recall tracing and hold release."""

import store
from services import ledger
from services.loads import reject_bid

MIN_HOLD_LBS = 500


def _matches(recall, scope):
    donor_wide = scope == "DONOR_WIDE"
    category_scope = scope == "CATEGORY"
    matched = []
    for load in store.ordered(store.loads.values()):
        if load["donor_agreement_id"] != recall["donor_agreement_id"]:
            continue
        if load["status"] == "CANCELLED":
            continue
        if donor_wide:
            matched.append(load)
        elif category_scope:
            if load["product_category"] == recall["product_category"]:
                matched.append(load)
        elif load["lot_code"] == recall["lot_code"]:
            matched.append(load)
    return matched


def _hold_reason(scope):
    if scope == "DONOR_WIDE":
        return "DONOR_WIDE_TRACE"
    if scope == "CATEGORY":
        return "CATEGORY_MATCH"
    return "LOT_MATCH"


def active_holds_of(recall_id):
    return [h for h in store.ordered(store.holds.values())
            if h["recall_id"] == recall_id and h["hold_status"] == "ACTIVE"]


def held_lbs_of(recall_id):
    total = 0
    for hold in active_holds_of(recall_id):
        load = store.loads.get(hold["load_id"])
        if load is not None:
            total += int(load["weight_lbs"])
    return total


def trace(recall, scope=None):
    """Match loads, place holds, recall delivered product, reject live bids."""
    matched = _matches(recall, scope)
    recall["traced_load_count"] = len(matched)
    reason = _hold_reason(scope)

    for load in matched:
        if load["status"] == "DELIVERED":
            if load["safety_status"] != "RECALLED":
                load["safety_status"] = "RECALLED"
                store.touch(load)
            continue
        if int(load["weight_lbs"]) < MIN_HOLD_LBS:
            continue

        hold = store.new_append_only(
            recall_id=recall["id"],
            load_id=load["id"],
            hold_status="ACTIVE",
            hold_reason=reason,
        )
        store.insert("holds", hold)

        if load["safety_status"] == "CLEAR":
            load["safety_status"] = "HELD"
            store.touch(load)

        if load["status"] == "BIDDING":
            for bid in store.ordered(store.bids.values()):
                if bid["load_id"] != load["id"] or bid["bid_status"] != "SUBMITTED":
                    continue
                member = store.members.get(bid["member_id"])
                if member is not None:
                    reject_bid(bid, member, "LOAD_SAFETY_HOLD")

    recall["held_lbs"] = held_lbs_of(recall["id"])
    recall["recall_status"] = "TRACING"
    store.touch(recall)
    return recall


def resolve(recall):
    """Release every ACTIVE hold and clear loads with no other open hold."""
    holds = active_holds_of(recall["id"])
    affected = [h["load_id"] for h in holds]
    for hold in holds:
        hold["hold_status"] = "RELEASED"

    for load_id in affected:
        load = store.loads.get(load_id)
        if load is None or load["safety_status"] != "HELD":
            continue
        if any(h["hold_status"] == "ACTIVE" and h["load_id"] == load_id
               for h in store.holds.values()):
            continue
        load["safety_status"] = "CLEAR"
        store.touch(load)

    recall["held_lbs"] = 0
    recall["recall_status"] = "RESOLVED"
    store.touch(recall)
    return recall
