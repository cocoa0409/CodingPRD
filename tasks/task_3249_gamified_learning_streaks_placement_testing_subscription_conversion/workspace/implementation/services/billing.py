"""Subscriptions, plan tiers, family seats and the billing lifecycle."""

from datetime import timedelta

import core
import middleware as mw
import serialize
from core import ApiError
from db import STORE
from runtime import CLOCK
from services import calc, common


def seats_used(subscription):
    return len(
        [
            m
            for m in STORE.family_memberships.values()
            if m["subscription_id"] == subscription["id"]
            and m["status"] in ("INVITED", "ACTIVE")
        ]
    )


def limits_removed(subscription):
    return bool(subscription["status"] == "ACTIVE" and subscription["plan_code"] != "FREE")


def refresh_limits(subscription):
    subscription["limits_removed"] = limits_removed(subscription)


def create_subscription(body, actor):
    learner_id = core.as_str(core.get_field(body, "learner_id"), "learner_id")
    mw.check_learner_param(actor, learner_id)
    mw.own(actor, learner_id)
    learner = common.learner_or_404(learner_id)
    plan_code = core.enum_check(core.get_field(body, "plan_code"), core.VALID_PLAN_CODES, "plan_code")
    seats_total = core.as_int(core.get_field(body, "seats_total"), "seats_total")
    auto_renew = core.as_bool(core.get_field(body, "auto_renew"), "auto_renew")

    if plan_code not in ("PLUS_FAMILY", "CERTIFICATION_ELITE"):
        raise ApiError(core.ERR_INVALID_REQUEST, "plan_code must be a paid plan.")
    if seats_total < 1:
        raise ApiError(core.ERR_INVALID_REQUEST, "seats_total must be at least 1.")
    active = [
        s
        for s in STORE.subscriptions.values()
        if s["learner_id"] == learner_id and s["status"] == "ACTIVE"
    ]
    if active:
        raise ApiError(core.ERR_INVALID_REQUEST, "The learner already holds an active subscription.")

    now = CLOCK.get()
    target = None
    for subscription in STORE.subscriptions.values():
        if subscription["learner_id"] == learner_id and subscription["status"] in ("FREE", "EXPIRED"):
            target = subscription
            break
    if target is None:
        target = {
            "id": core.new_id(),
            "learner_id": learner_id,
            "created_at": core.to_iso(now),
            "version": 1,
        }
        STORE.subscriptions[target["id"]] = target

    target["plan_code"] = plan_code
    target["seats_total"] = seats_total
    target["auto_renew"] = auto_renew
    target["status"] = "ACTIVE"
    target["current_period_end"] = core.to_iso(now + timedelta(days=core.PERIOD_DAYS))
    target["updated_at"] = core.to_iso(now)
    if target.get("version") != 1 or "created_at" not in target:
        target["version"] = int(target.get("version", 1)) + 1
    refresh_limits(target)

    for membership in STORE.family_memberships.values():
        if membership["subscription_id"] == target["id"] and membership["status"] == "INVITED":
            membership["status"] = "ACTIVE"
            common.touch(membership, CLOCK)
            member = STORE.learners.get(membership["member_learner_id"])
            if member is not None:
                calc.heart_and_energy(member, CLOCK, persist=True)
                common.recompute_scored_tier_for_learner(member["id"])

    learner["program_tier"] = plan_code
    calc.heart_and_energy(learner, CLOCK, persist=True)
    common.touch(learner, CLOCK)
    return target


def update_subscription(subscription_id, body, actor):
    subscription = common.subscription_or_404(subscription_id)
    mw.own(actor, subscription["learner_id"])
    learner = common.learner_or_404(subscription["learner_id"])

    guard = core.as_int(
        core.get_field(body, "expected_subscription_version"), "expected_subscription_version"
    )
    if guard != int(subscription["version"]):
        raise ApiError(core.ERR_STALE_VERSION)

    add_seat = None
    if core.has_field(body, "add_seat_learner_id"):
        add_seat = core.as_str(body["add_seat_learner_id"], "add_seat_learner_id")
    remove_seat = None
    if core.has_field(body, "remove_seat_learner_id"):
        remove_seat = core.as_str(body["remove_seat_learner_id"], "remove_seat_learner_id")
    offer_id = None
    if core.has_field(body, "offer_id"):
        offer_id = core.as_str(body["offer_id"], "offer_id")
    cancel = False
    if core.has_field(body, "cancel"):
        cancel = core.as_bool(body["cancel"], "cancel")

    # priority 11: a seat may only be added to an ACTIVE subscription
    if add_seat is not None and subscription["status"] != "ACTIVE":
        raise ApiError(core.ERR_SUBSCRIPTION_INACTIVE)
    # priority 24: seat quota
    if add_seat is not None and seats_used(subscription) >= int(subscription["seats_total"]):
        raise ApiError(core.ERR_SEAT_QUOTA_EXCEEDED)
    # priority 27: offer redemption gate
    redemption_offer = None
    if offer_id is not None:
        redemption_offer = STORE.engagement_offers.get(offer_id)
        if redemption_offer is None:
            raise ApiError(core.ERR_OFFER_NOT_REDEEMABLE)
        if redemption_offer["learner_id"] != subscription["learner_id"]:
            raise ApiError(core.ERR_UNAUTHORIZED)
        if redemption_offer["status"] != "ISSUED":
            raise ApiError(core.ERR_OFFER_NOT_REDEEMABLE)
        if subscription["plan_code"] not in ("PLUS_FAMILY", "CERTIFICATION_ELITE"):
            raise ApiError(core.ERR_OFFER_NOT_REDEEMABLE)
        if CLOCK.get() > core.parse_iso8601(redemption_offer["expires_at"]):
            raise ApiError(core.ERR_OFFER_NOT_REDEEMABLE)

    affected = set()

    if core.has_field(body, "plan_code"):
        subscription["plan_code"] = core.enum_check(
            body["plan_code"], core.VALID_PLAN_CODES, "plan_code"
        )
    if core.has_field(body, "auto_renew"):
        subscription["auto_renew"] = core.as_bool(body["auto_renew"], "auto_renew")

    if redemption_offer is not None:
        subscription["discount_pct"] = calc.discount_percent(
            learner, redemption_offer["milestone_code"], subscription
        )
        subscription["_total_due_cents"] = calc._total_due_cents(
            subscription["discount_pct"], subscription["seats_total"]
        )
        redemption_offer["status"] = "REDEEMED"
        common.touch(redemption_offer, CLOCK)
        if subscription["status"] in ("FREE",):
            subscription["status"] = "ACTIVE"
            subscription["current_period_end"] = core.to_iso(
                CLOCK.get() + timedelta(days=core.PERIOD_DAYS)
            )

    if add_seat is not None:
        member = common.learner_or_404(add_seat)
        existing = [
            m
            for m in STORE.family_memberships.values()
            if m["subscription_id"] == subscription["id"]
            and m["member_learner_id"] == add_seat
            and m["status"] in ("INVITED", "ACTIVE")
        ]
        if not existing:
            membership = {
                "id": core.new_id(),
                "subscription_id": subscription["id"],
                "member_learner_id": add_seat,
                "seat_role": "MEMBER",
                "status": "ACTIVE",
                "invited_at": core.to_iso(CLOCK.get()),
                "created_at": core.to_iso(CLOCK.get()),
                "updated_at": core.to_iso(CLOCK.get()),
                "version": 1,
            }
            STORE.family_memberships[membership["id"]] = membership
        affected.add(add_seat)
        calc.heart_and_energy(member, CLOCK, persist=True)
        common.recompute_scored_tier_for_learner(add_seat)

    # priority 24: the seat quota also guards a direct seat removal from a
    # non-owner (the model rows are owned by the subscription's learner)
    if remove_seat is not None:
        found = False
        for membership in list(STORE.family_memberships.values()):
            if (
                membership["subscription_id"] == subscription["id"]
                and membership["member_learner_id"] == remove_seat
            ):
                if membership["status"] in ("INVITED", "ACTIVE"):
                    membership["status"] = "REMOVED"
                    common.touch(membership, CLOCK)
                    found = True
                    affected.add(remove_seat)
        if not found and subscription["status"] not in ("FREE", "EXPIRED") and not found:
            raise ApiError(core.ERR_UNAUTHORIZED)
        common.recompute_scored_tier_for_learner(remove_seat)

    if cancel:
        subscription["auto_renew"] = False
        for membership in list(STORE.family_memberships.values()):
            if membership["subscription_id"] == subscription["id"] and membership["status"] == "ACTIVE":
                membership["status"] = "REMOVED"
                common.touch(membership, CLOCK)
                affected.add(membership["member_learner_id"])

    # ACTIVE -> FREE when the period has lapsed without auto-renewal
    if (
        subscription["status"] == "ACTIVE"
        and not subscription["auto_renew"]
        and subscription["current_period_end"] is not None
        and CLOCK.get() >= core.parse_iso8601(subscription["current_period_end"])
    ):
        subscription["status"] = "FREE"
        learner["program_tier"] = "FREE"
        for membership in list(STORE.family_memberships.values()):
            if membership["subscription_id"] == subscription["id"] and membership["status"] == "ACTIVE":
                membership["status"] = "REMOVED"
                common.touch(membership, CLOCK)
                affected.add(membership["member_learner_id"])

    # IN_GRACE -> ACTIVE, extending the period (PRD 3.5)
    if subscription["status"] == "IN_GRACE" and subscription["auto_renew"]:
        subscription["status"] = "ACTIVE"
        subscription["current_period_end"] = core.to_iso(
            CLOCK.get() + timedelta(days=core.PERIOD_DAYS)
        )

    refresh_limits(subscription)
    common.touch(subscription, CLOCK)
    calc.heart_and_energy(learner, CLOCK, persist=True)
    common.touch(learner, CLOCK)
    for member_id in affected:
        member = STORE.learners.get(member_id)
        if member is not None:
            calc.heart_and_energy(member, CLOCK, persist=True)
            common.touch(member, CLOCK)
    return subscription


def subscription_renewal(clock):
    """SUBSCRIPTION_RENEWAL: ACTIVE past period end -> IN_GRACE; IN_GRACE past
    the grace window -> EXPIRED with its full cascade."""
    for subscription in list(STORE.subscriptions.values()):
        end = subscription.get("current_period_end")
        if end is None:
            continue
        end_dt = core.parse_iso8601(end)
        if subscription["status"] == "ACTIVE" and subscription["auto_renew"]:
            if clock.get() >= end_dt:
                subscription["status"] = "IN_GRACE"
                refresh_limits(subscription)
                common.touch(subscription, clock)
        elif subscription["status"] == "IN_GRACE":
            if clock.get() >= end_dt + timedelta(days=core.GRACE_DAYS):
                subscription["status"] = "EXPIRED"
                subscription["limits_removed"] = False
                owner = STORE.learners.get(subscription["learner_id"])
                if owner is not None:
                    owner["program_tier"] = "FREE"
                for membership in list(STORE.family_memberships.values()):
                    if membership["subscription_id"] == subscription["id"] and membership["status"] == "ACTIVE":
                        membership["status"] = "REMOVED"
                        common.touch(membership, clock)
                        member = STORE.learners.get(membership["member_learner_id"])
                        if member is not None:
                            calc.heart_and_energy(member, clock, persist=True)
                            common.touch(member, clock)
                for offer in STORE.engagement_offers.values():
                    if offer["status"] == "ISSUED":
                        owner = STORE.learners.get(offer["learner_id"])
                        if owner is not None:
                            offer["status"] = "EXPIRED"
                            common.touch(offer, clock)
                common.touch(subscription, clock)


def payment_outcome(body):
    subscription_id = core.as_str(core.get_field(body, "subscription_id"), "subscription_id")
    outcome = core.as_str(core.get_field(body, "outcome"), "outcome")
    subscription = common.subscription_or_404(subscription_id)
    if outcome == "SUCCEEDED" and subscription["status"] == "IN_GRACE":
        subscription["status"] = "ACTIVE"
        subscription["current_period_end"] = core.to_iso(
            CLOCK.get() + timedelta(days=core.PERIOD_DAYS)
        )
        refresh_limits(subscription)
        common.touch(subscription, CLOCK)
    return subscription


def inject_gems(body):
    learner_id = core.as_str(core.get_field(body, "learner_id"), "learner_id")
    gems = core.as_int(core.get_field(body, "gems"), "gems")
    learner = common.learner_or_404(learner_id)
    learner["gems_balance"] = int(learner["gems_balance"]) + gems
    common.touch(learner, CLOCK)
    return learner