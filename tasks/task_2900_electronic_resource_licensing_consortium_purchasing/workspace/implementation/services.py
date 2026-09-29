"""Shared side-effect engines: the committed-spend ledger, the access-health
cascade, settled re-pricing, the signing cascade and the clock sweeps."""

import calc
import store


# --------------------------------------------------------------------------- #
# committed-spend ledger and member standing (PRD 2.10)
# --------------------------------------------------------------------------- #
def derive_standing(member):
    if member["annual_committed_cents"] > member["budget_ceiling_cents"]:
        return "OVER_COMMITTED"
    return "IN_GOOD_STANDING"


def apply_ledger_delta(member, delta):
    """Move a member's ledger by `delta` cents and re-derive standing.
    Returns True when the member flipped into OVER_COMMITTED."""
    was_over = member["standing"] == "OVER_COMMITTED"
    total = member["annual_committed_cents"] + delta
    changes = {"annual_committed_cents": total}
    changes["standing"] = "OVER_COMMITTED" if total > member["budget_ceiling_cents"] else "IN_GOOD_STANDING"
    store.mutate(member, changes)
    return (not was_over) and changes["standing"] == "OVER_COMMITTED"


def withdraw_draft_trials(member_id):
    """Hop four of the signing cascade: an OVER_COMMITTED flip withdraws every
    DRAFT trial of that member and leaves every other trial untouched."""
    for trial in store.sort_rows(list(store.trials.values())):
        if trial["member_id"] == member_id and trial["status"] == "DRAFT":
            store.mutate(trial, {"status": "WITHDRAWN"})


# --------------------------------------------------------------------------- #
# trial feedback counters
# --------------------------------------------------------------------------- #
def trial_feedback_rows(trial_id):
    return [r for r in store.feedback_entries.values() if r["trial_id"] == trial_id]


def trial_counters(trial_id):
    rows = trial_feedback_rows(trial_id)
    groups = set(r["stakeholder_group"] for r in rows)
    return len(rows), len(groups)


# --------------------------------------------------------------------------- #
# commitment helpers
# --------------------------------------------------------------------------- #
def commitments_of_product(product_id, statuses=None):
    rows = [c for c in store.commitments.values() if c["product_id"] == product_id]
    if statuses is not None:
        rows = [c for c in rows if c["status"] in statuses]
    return store.sort_rows(rows)


def commitments_of_subscription(subscription_id, statuses=None):
    rows = [c for c in store.commitments.values() if c.get("subscription_id") == subscription_id]
    if statuses is not None:
        rows = [c for c in rows if c["status"] in statuses]
    return store.sort_rows(rows)


def settled_participant_count(product_id):
    return len(commitments_of_product(product_id, ("CONFIRMED",)))


def reprice_confirmed_commitments(subscription):
    """The settled variant runs again on renewal, restructure and revert
    execution; each member's ledger moves by that member's own price delta."""
    product = store.products[subscription["product_id"]]
    count = settled_participant_count(product["id"])
    for commitment in commitments_of_subscription(subscription["id"], ("CONFIRMED",)):
        member = store.members[commitment["member_id"]]
        price, discount, participants = calc.member_tier_price_cents(member, product, count)
        old = commitment.get("tier_price_cents") or 0
        store.mutate(commitment, {
            "tier_price_cents": price,
            "applied_discount_pct": discount,
            "participant_count_at_pricing": participants,
        })
        delta = price - old
        if delta != 0:
            apply_ledger_delta(member, delta)


# --------------------------------------------------------------------------- #
# access-health cascade (PRD 3.6)
# --------------------------------------------------------------------------- #
def refresh_voting_offers(subscription):
    """Hop four of the reopen cascade: every VOTING decision on this
    subscription has its offer recomputed."""
    product = store.products[subscription["product_id"]]
    for decision in store.sort_rows(list(store.renewal_decisions.values())):
        if decision["subscription_id"] != subscription["id"] or decision["status"] != "VOTING":
            continue
        offer = calc.renewal_offer_price(subscription, decision, product)
        store.mutate(decision, {
            "sla_credit_applied_cents": offer["sla_credit_applied_cents"],
            "offer_price_cents": offer["offer_price_cents"],
        })


def accrue_sla_credit(subscription):
    """Hops three and four: a DEGRADED entry accrues an SLA credit while the
    newly incremented degrade_count is within the event cap, and the credit
    movement refreshes the offers members are voting on right now."""
    new_count = subscription["degrade_count"] + 1
    changes = {"degrade_count": new_count}
    if new_count <= calc.SLA_CREDIT_MAX_EVENTS:
        accrual = calc.rhu_int(
            calc.dec(subscription["negotiated_price_cents"]) * calc.SLA_CREDIT_PCT_PER_EVENT / calc.dec(100)
        )
        changes["sla_credit_cents"] = subscription["sla_credit_cents"] + accrual
    else:
        accrual = 0
    store.mutate(subscription, changes)
    if accrual:
        refresh_voting_offers(subscription)


def recompute_access_health(subscription, trigger):
    """`trigger` is 'incident' for a report or a reopen, 'resolve' for a
    resolution. Degradation only fires on the former, restoration only on the
    latter, and the two thresholds differ in inclusivity."""
    score = calc.access_health_score(subscription["id"])
    store.mutate(subscription, {"access_health_score": score})
    if trigger == "incident":
        if score < calc.DEGRADE_THRESHOLD and subscription["access_status"] == "CONFIGURED":
            store.mutate(subscription, {"access_status": "DEGRADED"})
            accrue_sla_credit(subscription)
    elif trigger == "resolve":
        if score >= calc.DEGRADE_THRESHOLD and subscription["access_status"] == "DEGRADED":
            store.mutate(subscription, {"access_status": "CONFIGURED"})


# --------------------------------------------------------------------------- #
# the signing cascade (PRD 3.5)
# --------------------------------------------------------------------------- #
def sign_negotiation(negotiation, product, activation_start_date):
    store.mutate(negotiation, {"status": "SIGNED"})

    # hop one - the subscription
    subscription = store.new_row({
        "negotiation_id": negotiation["id"],
        "product_id": product["id"],
        "contract_status": "PENDING_ACTIVATION",
        "access_status": "UNCONFIGURED",
        "term_start": negotiation["target_term_start"],
        "term_end": negotiation["target_term_end"],
        "activation_start_date": activation_start_date,
        "negotiated_price_cents": negotiation["agreed_price_cents"],
        "entitled_title_count": product["title_count"],
        "perpetual_access_mode": negotiation["granted_perpetual_access"],
        "access_health_score": 100,
        "degrade_count": 0,
        "sla_credit_cents": 0,
        "notice_deadline_date": calc.add_days(
            negotiation["target_term_end"], -product["cancellation_notice_days"]
        ),
        "renewal_term_count": 0,
    })
    store.subscriptions[subscription["id"]] = subscription

    # hop two - confirm every pledge on the product, then price the whole pass
    pledged = commitments_of_product(product["id"], ("PLEDGED",))
    for commitment in pledged:
        commitment["subscription_id"] = subscription["id"]
        commitment["status"] = "CONFIRMED"
    count = settled_participant_count(product["id"])
    flipped = []
    for commitment in pledged:
        member = store.members[commitment["member_id"]]
        price, discount, participants = calc.member_tier_price_cents(member, product, count)
        commitment["tier_price_cents"] = price
        commitment["applied_discount_pct"] = discount
        commitment["participant_count_at_pricing"] = participants
        store.touch(commitment)
        # hop three - the member ledger
        if apply_ledger_delta(member, price):
            flipped.append(member["id"])

    # hop four - an OVER_COMMITTED flip withdraws that member's DRAFT trials
    for member_id in flipped:
        withdraw_draft_trials(member_id)

    return subscription


# --------------------------------------------------------------------------- #
# cancellation execution money unwind (PRD 3.9)
# --------------------------------------------------------------------------- #
def release_commitments(subscription):
    for commitment in commitments_of_subscription(subscription["id"], ("CONFIRMED",)):
        member = store.members[commitment["member_id"]]
        price = commitment.get("tier_price_cents") or 0
        store.mutate(commitment, {"status": "RELEASED"})
        apply_ledger_delta(member, -price)


# --------------------------------------------------------------------------- #
# the logical clock sweeps (PRD 3.5)
# --------------------------------------------------------------------------- #
def sweep_subscriptions():
    """Activation first, expiry second, both in created_at ascending order."""
    clock_date = store.clock_date()
    activated = []
    expired = []
    for subscription in store.sort_rows(list(store.subscriptions.values())):
        if subscription["contract_status"] == "PENDING_ACTIVATION" \
                and subscription["activation_start_date"] <= clock_date:
            store.mutate(subscription, {"contract_status": "ACTIVE"})
            activated.append(subscription["id"])
    for subscription in store.sort_rows(list(store.subscriptions.values())):
        if subscription["contract_status"] == "ACTIVE" and subscription["term_end"] < clock_date:
            changes = {"contract_status": "EXPIRED"}
            if subscription["perpetual_access_mode"] == "NONE":
                changes["access_status"] = "SUSPENDED"
            else:
                changes["access_status"] = "POST_CANCELLATION"
            store.mutate(subscription, changes)
            expired.append(subscription["id"])
    return activated, expired
