"""DonatedLoad lifecycle cascades and the bid ranking selector."""

from decimal import Decimal, ROUND_FLOOR

import clock
import store
from errors import ERR_SUBSIDY_POOL_EXHAUSTED, fail
from services import freight, ledger, members

SHARES_SCORE_MULTIPLIER = 100
SELF_TRANSPORT_BONUS = 40
PROBATION_PENALTY = 25
DISTANCE_PENALTY_PER_100_MILES = 2
TRANSPORT_BONUS = {"NATIONAL": 30, "REGIONAL": 20, "LOCAL": 10, "NONE": 0}

PROBATION_FLOOR_SHARES = 50
ACTIVITY_BONUS_PER_10K_LBS = 15


def storage_fits(member, load):
    if load["storage_type"] in ("REFRIGERATED", "FROZEN"):
        return int(member["refrigerated_capacity_lbs"]) >= int(load["weight_lbs"])
    return int(member["storage_capacity_lbs"]) >= int(load["weight_lbs"])


def bid_score(bid, member, load):
    return (bid["shares_offered"] * SHARES_SCORE_MULTIPLIER
            + (SELF_TRANSPORT_BONUS if bid["can_self_transport"] else 0)
            + TRANSPORT_BONUS.get(member["transport_ability"], 0)
            - (int(load["distance_miles"]) // 100) * DISTANCE_PENALTY_PER_100_MILES
            - (PROBATION_PENALTY if member["certification_status"] == "PROBATION" else 0))


def candidates(load):
    """The selector's candidate set (PRD 3.5 eligibility predicate)."""
    result = []
    for bid in store.ordered(store.bids.values()):
        if bid["load_id"] != load["id"] or bid["bid_status"] != "SUBMITTED":
            continue
        member = store.members.get(bid["member_id"])
        if member is None:
            continue
        if member["certification_status"] not in ("CERTIFIED", "PROBATION"):
            continue
        if member["share_balance"] < bid["shares_offered"]:
            continue
        if not storage_fits(member, load):
            continue
        result.append((bid, member))
    return result


def select_winner(pool, load, ranking_basis):
    if ranking_basis == "PREFERENCE_FIRST":
        def key(item):
            bid, member = item
            return (bid["preference_rank"], -bid_score(bid, member, load),
                    bid["created_at"], bid["_seq"], member["created_at"], member["_seq"])
    else:
        def key(item):
            bid, member = item
            return (-bid_score(bid, member, load), bid["created_at"], bid["_seq"],
                    member["created_at"], member["_seq"])
    return min(pool, key=key)


def reject_bid(bid, member, reason):
    """Bid -> REJECTED with a release entry for the held shares."""
    bid["bid_status"] = "REJECTED"
    bid["rejection_reason"] = reason
    store.touch(bid)
    ledger.append_entry(member, "BID_RELEASE", bid["shares_offered"], reference_id=bid["id"])


def create_bid(member, load, shares_offered, preference_rank, can_self_transport):
    prior_rounds = sum(1 for b in store.bids.values()
                       if b["load_id"] == load["id"] and b["member_id"] == member["id"])
    bid = store.new_record(
        load_id=load["id"],
        member_id=member["id"],
        shares_offered=shares_offered,
        preference_rank=preference_rank,
        can_self_transport=can_self_transport,
        bid_status="SUBMITTED",
        rejection_reason=None,
        submitted_round=prior_rounds + 1,
    )
    store.insert("bids", bid)
    ledger.append_entry(member, "BID_HOLD", -shares_offered, reference_id=bid["id"])
    store.touch(load)
    return bid


def withdraw_bid(bid, member):
    bid["bid_status"] = "WITHDRAWN"
    bid["rejection_reason"] = "WITHDRAWN_BY_MEMBER"
    store.touch(bid)
    ledger.append_entry(member, "BID_RELEASE", bid["shares_offered"], reference_id=bid["id"])
    return bid


def award_load(load, ranking_basis=None):
    """Run the selector and execute the full award cascade (PRD 3.5.1)."""
    pool = candidates(load)
    winner_bid, winner_member = select_winner(pool, load, ranking_basis)

    winner_bid["bid_status"] = "AWARDED"
    store.touch(winner_bid)
    load["awarded_bid_id"] = winner_bid["id"]
    load["awarded_member_id"] = winner_member["id"]

    # HOP 1b: every other SUBMITTED bid on the load loses, candidate or not.
    for bid in store.ordered(store.bids.values()):
        if (bid["load_id"] == load["id"] and bid["id"] != winner_bid["id"]
                and bid["bid_status"] == "SUBMITTED"):
            member = store.members.get(bid["member_id"])
            if member is not None:
                reject_bid(bid, member, "LOSING_BID")

    ledger.append_entry(winner_member, "BID_RELEASE", winner_bid["shares_offered"],
                        reference_id=winner_bid["id"])
    ledger.append_entry(winner_member, "AWARD_DEBIT", -winner_bid["shares_offered"],
                        reference_id=winner_bid["id"])

    if (winner_member["share_balance"] < PROBATION_FLOOR_SHARES
            and winner_member["certification_status"] == "CERTIFIED"):
        members.set_posture(winner_member, "PROBATION")
        members.withdraw_submitted_bids(winner_member, "MEMBER_PROBATION")

    load["freight_estimate_cents"] = freight.base_cents(load, 0)
    load["freight_decision"] = "PENDING"
    load["freight_subsidy_cents"] = 0
    load["member_freight_due_cents"] = load["freight_estimate_cents"]
    load["status"] = "AWARDED"
    load["awarded_at"] = clock.now()
    store.touch(load)
    return load


def _unwind_award(load, bid, member):
    """AWARDED -> BIDDING compensation for a declined freight decision."""
    bid["bid_status"] = "REJECTED"
    bid["rejection_reason"] = "FREIGHT_DECLINED"
    store.touch(bid)
    ledger.append_entry(member, "AWARD_REFUND", bid["shares_offered"], reference_id=bid["id"])
    load["awarded_bid_id"] = None
    load["awarded_member_id"] = None
    load["freight_decision"] = "PENDING"
    load["freight_subsidy_cents"] = 0
    load["member_freight_due_cents"] = 0
    load["status"] = "BIDDING"
    store.touch(load)
    return load


def record_freight_decision(load, decision, detour_miles=0):
    bid = store.bids.get(load.get("awarded_bid_id"))
    member = store.members.get(load.get("awarded_member_id"))
    agreement = store.agreements.get(load["donor_agreement_id"])
    can_self = bool(bid["can_self_transport"]) if bid else False

    if decision == "DECLINED":
        if not can_self:
            return _unwind_award(load, bid, member)
        load["freight_estimate_cents"] = freight.base_cents(load, detour_miles)
        load["freight_subsidy_cents"] = 0
        load["member_freight_due_cents"] = load["freight_estimate_cents"]
        load["freight_decision"] = "DECLINED"
        store.touch(load)
        return load

    pool_remaining = freight.pool_remaining(agreement)
    if not can_self and pool_remaining < freight.MIN_SUBSIDY_CENTS:
        fail(ERR_SUBSIDY_POOL_EXHAUSTED,
             "the agreement's remaining freight subsidy pool is below the minimum grantable subsidy")

    subsidy, base, due = freight.compute_subsidy(
        load, member, can_self, detour_miles, pool_remaining)
    if not can_self and subsidy == 0:
        return _unwind_award(load, bid, member)

    load["freight_estimate_cents"] = base
    load["freight_subsidy_cents"] = subsidy
    load["member_freight_due_cents"] = due
    load["freight_decision"] = "COVERED"
    store.touch(load)
    if subsidy > 0:
        agreement["freight_subsidy_used_cents"] = (
            int(agreement["freight_subsidy_used_cents"]) + subsidy)
        store.touch(agreement)
    return load


def cancel_load(load):
    for bid in list(store.ordered(store.bids.values())):
        if bid["load_id"] != load["id"] or bid["bid_status"] != "SUBMITTED":
            continue
        member = store.members.get(bid["member_id"])
        if member is not None:
            reject_bid(bid, member, "LOAD_CANCELLED")
    load["status"] = "CANCELLED"
    store.touch(load)
    return load


def dispatch_load(load, window_start, window_end):
    load["delivery_window_start"] = window_start
    load["delivery_window_end"] = window_end
    load["status"] = "IN_TRANSIT"
    load["dispatched_at"] = clock.now()
    store.touch(load)
    return load


def deliver_load(load):
    agreement = store.agreements.get(load["donor_agreement_id"])
    delivered = int(load["weight_lbs"])
    factor = agreement["meal_equivalency_factor"]
    load["delivered_lbs"] = delivered
    load["meal_equivalent"] = int(
        (Decimal(delivered) / Decimal(str(factor))).to_integral_value(rounding=ROUND_FLOOR))
    load["delivered_at"] = clock.now()
    member = store.members.get(load.get("awarded_member_id"))
    if member is not None:
        ledger.append_entry(member, "ACTIVITY_BONUS",
                            (delivered // 10000) * ACTIVITY_BONUS_PER_10K_LBS,
                            reference_id=load["id"])
    load["status"] = "DELIVERED"
    store.touch(load)
    return load
