"""Spend-insight offers: the privacy gate, audience aggregation, pools and payouts."""

from decimal import Decimal

from clock import parse_iso
from errors import (
    ERR_INVALID_STATE,
    ERR_POOL_INSUFFICIENT_RESERVE,
    ERR_PRIVACY_VIOLATION,
    ERR_STALE_VERSION,
    ERR_TEMPORAL_OVERLAP,
    ApiError,
)
from services import pricing

# The privacy quorum.  A single-member audience is never disclosed as an
# individual spend figure, so an audience of one cannot proceed to consent.
AUDIENCE_QUORUM = 1
PROVISIONAL_DIVISOR = 2


def qualifying_members(store, offer):
    """The audience set: ACTIVE members at or above the segment floor."""
    members = [
        member
        for member in store.cardmembers.values()
        if member["member_status"] == "ACTIVE"
        and member["trailing_lowest_month_spend_cents"] >= offer["min_segment_spend_cents"]
    ]
    # The audience is a set, so both figures are order-invariant.  The reporting
    # order pins trailing spend descending and created_at ascending -- never id.
    members.sort(
        key=lambda member: (
            -member["trailing_lowest_month_spend_cents"],
            parse_iso(member["created_at"]),
            member["_seq"],
        )
    )
    return members


def aggregate_audience(store, offer):
    members = qualifying_members(store, offer)
    offer["audience_size"] = len(members)
    offer["aggregated_spend_cents"] = sum(
        member["trailing_lowest_month_spend_cents"] for member in members)
    return offer


def submit_review(store, offer):
    if offer["privacy_state"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE)
    offer["privacy_state"] = "PRIVACY_REVIEW"
    aggregate_audience(store, offer)
    offer["version"] = offer["version"] + 1
    offer["updated_at"] = store.clock.now()
    return offer


def request_consent(store, offer):
    if offer["privacy_state"] != "PRIVACY_REVIEW":
        raise ApiError(ERR_INVALID_STATE)
    if offer["audience_size"] < max(AUDIENCE_QUORUM, 1):
        raise ApiError(ERR_PRIVACY_VIOLATION)
    offer["privacy_state"] = "MERCHANT_CONSENT"
    offer["version"] = offer["version"] + 1
    offer["updated_at"] = store.clock.now()
    return offer


def consent(store, offer, merchant, expected_version, live_start, live_end):
    if offer["privacy_state"] != "MERCHANT_CONSENT":
        raise ApiError(ERR_INVALID_STATE)

    # The funding merchant must be live on the network.
    if merchant["acceptance_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE)

    # OCC: guarded write.  When the field is supplied it must equal the current
    # version, or the merchant is consenting against a superseded offer.
    if expected_version is not None and expected_version != offer["version"]:
        raise ApiError(ERR_STALE_VERSION)

    if live_start is not None and live_end is not None:
        _assert_clearance(store, offer, live_start, live_end)

    offer["privacy_state"] = "LIVE"
    if live_start is not None:
        offer["live_start_utc"] = live_start
    if live_end is not None:
        offer["live_end_utc"] = live_end
    offer["version"] = offer["version"] + 1
    offer["updated_at"] = store.clock.now()
    return offer


def _assert_clearance(store, offer, live_start, live_end):
    """At least one full day of clearance from every existing live window funded
    by the same merchant.  The start bound is inclusive, the end bound exclusive."""
    from datetime import timedelta

    clearance = timedelta(days=1)
    for other in store.offers_for(offer["merchant_id"]):
        if other["id"] == offer["id"]:
            continue
        if other["privacy_state"] != "LIVE":
            continue
        other_start = parse_iso(other.get("live_start_utc"))
        other_end = parse_iso(other.get("live_end_utc"))
        if other_start is None or other_end is None:
            continue
        # The start bound is inclusive and the end bound exclusive (PRD §3.4),
        # and a full day of clearance means a window may open exactly one day
        # after the existing window's end.  Stated on those bounds:
        #   * overlap                    -> always a violation;
        #   * a gap of exactly one day   -> permitted;
        #   * a gap shorter than one day -> violation.
        overlap = live_start < other_end and other_start < live_end
        within_clearance = (
            live_start < other_end + clearance and other_start <= live_end + clearance)
        if overlap or within_clearance:
            raise ApiError(ERR_TEMPORAL_OVERLAP)


def return_to_draft(store, offer):
    if offer["privacy_state"] != "PRIVACY_REVIEW":
        raise ApiError(ERR_INVALID_STATE)
    offer["privacy_state"] = "DRAFT"
    offer["audience_size"] = 0
    offer["aggregated_spend_cents"] = 0
    offer["version"] = offer["version"] + 1
    offer["updated_at"] = store.clock.now()
    return offer


def suspend(store, offer):
    if offer["privacy_state"] != "LIVE":
        raise ApiError(ERR_INVALID_STATE)
    offer["privacy_state"] = "MERCHANT_CONSENT"
    offer["version"] = offer["version"] + 1
    offer["updated_at"] = store.clock.now()
    return offer


# --------------------------------------------------------------------------
# Redemption pools
# --------------------------------------------------------------------------

def create_pool(store, offer, funder, initial_funded_cents):
    if store.pool_for_offer(offer["id"]) is not None:
        raise ApiError(ERR_INVALID_STATE, "This offer already has a redemption pool.")
    pool_id = store.new_id()
    now = store.clock.now()
    pool = {
        "id": pool_id,
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "_seq": store.next_created_seq(),
        "offer_id": offer["id"],
        "funder": funder,
        "initial_funded_cents": initial_funded_cents,
        "balance_cents": initial_funded_cents,
        "topup_total_cents": 0,
        "consumed_total_cents": 0,
    }
    store.offer_redemption_pools[pool_id] = pool
    store.pools_by_offer[offer["id"]] = pool_id
    return pool


def topup_pool(store, pool, amount_cents):
    pool["balance_cents"] = pool["balance_cents"] + amount_cents
    pool["topup_total_cents"] = pool["topup_total_cents"] + amount_cents
    pool["version"] = pool["version"] + 1
    pool["updated_at"] = store.clock.now()
    return pool


# --------------------------------------------------------------------------
# Acceptances and payouts
# --------------------------------------------------------------------------

def accept_offer(store, offer, member, trigger_amount_cents):
    if offer["privacy_state"] != "LIVE":
        raise ApiError(ERR_INVALID_STATE, "No new acceptance may be recorded against this offer.")

    acceptance_id = store.new_id()
    now = store.clock.now()
    amount = (member["trailing_lowest_month_spend_cents"]
              if trigger_amount_cents is None else trigger_amount_cents)
    reward = pricing.apply_bps(amount, offer["reward_bps"])
    acceptance = {
        "id": acceptance_id,
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "_seq": store.next_created_seq(),
        "offer_id": offer["id"],
        "cardmember_id": member["id"],
        "trigger_amount_cents": amount,
        "reward_amount_cents": reward,
        "acceptance_status": "PENDING",
    }
    store.offer_acceptances[acceptance_id] = acceptance
    offer["accepted_count"] = offer["accepted_count"] + 1
    offer["updated_at"] = store.clock.now()
    return acceptance


def approve_acceptance(store, acceptance):
    if acceptance["acceptance_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE)
    offer = store.offers.get(acceptance["offer_id"])
    if offer is None:
        raise ApiError(ERR_INVALID_STATE)
    pool = store.pool_for_offer(offer["id"])
    reward = acceptance["reward_amount_cents"]
    if pool is None or pool["balance_cents"] < reward:
        raise ApiError(ERR_POOL_INSUFFICIENT_RESERVE)
    pool["consumed_total_cents"] = pool["consumed_total_cents"] + reward
    pool["balance_cents"] = pool["balance_cents"] - reward
    pool["version"] = pool["version"] + 1
    pool["updated_at"] = store.clock.now()
    acceptance["acceptance_status"] = "APPROVED"
    acceptance["version"] = acceptance["version"] + 1
    acceptance["updated_at"] = store.clock.now()
    return acceptance


def pay_acceptance(store, acceptance):
    if acceptance["acceptance_status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE)
    acceptance["acceptance_status"] = "PAID"
    acceptance["version"] = acceptance["version"] + 1
    acceptance["updated_at"] = store.clock.now()
    return acceptance


def reverse_acceptance(store, acceptance):
    if acceptance["acceptance_status"] not in ("APPROVED", "PAID"):
        raise ApiError(ERR_INVALID_STATE)
    offer = store.offers.get(acceptance["offer_id"])
    if offer is None:
        raise ApiError(ERR_INVALID_STATE)
    # Reversal must restore exactly what was funded (PRD §3.5): the approval drew
    # the acceptance's frozen `reward_amount_cents` on the pool, so the reversal
    # credits that same figure back.  The provisional rate described alongside
    # the reversal rule is the fallback for a redemption whose frozen backing is
    # unavailable -- it is the offer's reward rate halved with any fraction
    # discarded (`PROVISIONAL_DIVISOR` is two), applied to the pinned trigger
    # amount and rounded half up once.
    reversed_backing = acceptance.get("reward_amount_cents")
    if not isinstance(reversed_backing, int):
        provisional_bps = int(Decimal(offer["reward_bps"]) / Decimal(PROVISIONAL_DIVISOR))
        reversed_backing = pricing.apply_bps(
            acceptance["trigger_amount_cents"], provisional_bps)
    pool = store.pool_for_offer(offer["id"])
    if pool is not None:
        pool["consumed_total_cents"] = pool["consumed_total_cents"] - reversed_backing
        pool["balance_cents"] = pool["balance_cents"] + reversed_backing
        pool["version"] = pool["version"] + 1
        pool["updated_at"] = store.clock.now()
    acceptance["acceptance_status"] = "REVERSED"
    acceptance["version"] = acceptance["version"] + 1
    acceptance["updated_at"] = store.clock.now()
    return acceptance