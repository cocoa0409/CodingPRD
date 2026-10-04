"""§3.8 Cadence: Skips, Auto-Skips, Pauses and Cancellation."""

import clock
import common
import rules
import store
from common import ApiError


def subscription_of(subscription_id):
    row = store.SUBSCRIPTIONS.get(subscription_id)
    if row is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404,
                       "No Subscription exists with the given id.")
    return row


def skip(subscription):
    if subscription["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACTIVE subscription can be skipped.")
    # §3.8: a skip is admitted only while the recorded skipped_cycle_index is
    # less than the current serving cycle index plus four.
    recorded = subscription.get("skipped_cycle_index")
    if recorded is not None and recorded >= subscription["serving_cycle_index"] + 4:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A skip may not be recorded that far beyond the cycle served.")
    subscription["status"] = "SKIPPED"
    subscription["skipped_cycle_index"] = subscription["serving_cycle_index"] + 1
    subscription["skipped_on"] = clock.now_iso()
    store.touch(subscription)
    return subscription


def pause(subscription):
    if subscription["status"] not in ("ACTIVE", "SKIPPED", "AUTO_SKIPPED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The subscription is not in a state that admits a pause.")
    if subscription["pause_count"] >= common.MAX_PAUSE_HOPS:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The subscription has exhausted its pause hops.")
    subscription["pause_count"] += 1
    subscription["paused_at"] = clock.now_iso()
    subscription["status"] = "PAUSED"
    store.touch(subscription)
    return subscription


def resume(subscription):
    if subscription["status"] == "PAUSED":
        resumed_at = subscription.get("resumed_at")
        if resumed_at is not None and clock.now() <= clock.parse_instant(resumed_at):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "The same instant cannot resume the same subscription twice.")
        subscription["status"] = "ACTIVE"
        subscription["resumed_at"] = clock.now_iso()
        subscription["paused_at"] = None
        subscription["skipped_cycle_index"] = None
        store.touch(subscription)
        return subscription
    if subscription["status"] == "SKIPPED":
        _require_skip_arrived(subscription)
        subscription["status"] = "ACTIVE"
        subscription["skipped_cycle_index"] = None
        subscription["skipped_on"] = None
        store.touch(subscription)
        return subscription
    if subscription["status"] == "AUTO_SKIPPED":
        _require_skip_arrived(subscription)
        subscription["status"] = "ACTIVE"
        subscription["skipped_cycle_index"] = None
        store.touch(subscription)
        return subscription
    raise ApiError("ERR_INVALID_STATE", 409,
                   "The subscription is not in a state that admits a resume.")


def cancel(subscription, reason):
    if subscription["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "The subscription is already cancelled.")
    for order in store.BOX_ORDERS.values():
        if order["subscription_id"] == subscription["id"] and order["status"] == "BUILDING":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "A build is in flight and cannot be abandoned.")
    subscription["status"] = "CANCELLED"
    subscription["cancellation_reason"] = reason
    store.touch(subscription)
    for order in store.BOX_ORDERS.values():
        if order["subscription_id"] == subscription["id"] and order["status"] == "DRAFT":
            order["status"] = "ABANDONED"
            store.touch(order)
    return subscription


def tick_clock():
    """§3.8: the two automatic returns fire when the clock reaches the skip.

    A SKIPPED row clears both ``skipped_cycle_index`` and ``skipped_on``; an
    AUTO_SKIPPED row clears only the cycle index.
    """
    for subscription in store.SUBSCRIPTIONS.values():
        if not _skip_arrived(subscription):
            continue
        if subscription["status"] == "SKIPPED":
            subscription["status"] = "ACTIVE"
            subscription["skipped_cycle_index"] = None
            subscription["skipped_on"] = None
            store.touch(subscription)
        elif subscription["status"] == "AUTO_SKIPPED":
            subscription["status"] = "ACTIVE"
            subscription["skipped_cycle_index"] = None
            store.touch(subscription)


def _require_skip_arrived(subscription):
    skipped = subscription.get("skipped_cycle_index")
    if skipped is None:
        return
    start = rules.start_of_service_cycle(subscription, skipped)
    if clock.now() < start:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The logical clock has not reached the start of the skipped cycle.")


def _skip_arrived(subscription):
    skipped = subscription.get("skipped_cycle_index")
    if skipped is None:
        return True
    return clock.now() >= rules.start_of_service_cycle(subscription, skipped)


def order_created_against(subscription):
    """§3.8: a PAUSED subscription returns to ACTIVE when a new order names it."""
    previous = subscription["status"]
    if previous == "PAUSED":
        subscription["status"] = "ACTIVE"
        subscription["paused_at"] = None
        store.touch(subscription)
    elif previous == "AUTO_SKIPPED":
        subscription["status"] = "ACTIVE"
        subscription["skipped_cycle_index"] = None
        store.touch(subscription)
    return previous