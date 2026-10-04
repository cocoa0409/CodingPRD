"""Closed-loop dispute lifecycle (PRD §3.7).

The network holds both the issuer and the acquirer role, so a lost first round
may be re-represented; `representment_stage` runs on its own axis, independent
of `dispute_status`.
"""

from datetime import timedelta
from decimal import Decimal

from clock import parse_iso
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NO_RISK_STATE,
    ERR_RESPOND_AMOUNT_TOO_LOW,
    ApiError,
)
from services import pricing, risk

RESPONSE_WINDOW_DAYS = 30
MERCHANT_SHARE_BPS = 4000
POINTS_PER_DOLLAR = 1


def settle_auto_acceptances(store):
    """The response clock: an unanswered OPEN dispute reaches its deadline and
    moves to AUTO_ACCEPTED on its own."""
    now = store.clock.now()
    for dispute in store.disputes.values():
        if dispute["dispute_status"] != "OPEN":
            continue
        occurred = parse_iso(dispute.get("occurred_at"))
        if occurred is None:
            continue
        if now >= occurred + timedelta(days=RESPONSE_WINDOW_DAYS):
            dispute["dispute_status"] = "AUTO_ACCEPTED"
            dispute["version"] = dispute["version"] + 1
            dispute["updated_at"] = now
            risk.recompute(store, store.risk_state_for(dispute["original_merchant_id"]))


def respond(store, dispute, caller):
    if caller.user_id != dispute["original_merchant_id"]:
        raise ApiError(ERR_FORBIDDEN)
    if dispute["amount_cents"] < 50000:
        raise ApiError(ERR_RESPOND_AMOUNT_TOO_LOW)
    if dispute["dispute_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    dispute["dispute_status"] = "MERCHANT_RESPONDED"
    dispute["version"] = dispute["version"] + 1
    dispute["updated_at"] = store.clock.now()
    return dispute


def withdraw(store, dispute, caller):
    if caller.user_id != dispute["cardmember_id"]:
        raise ApiError(ERR_FORBIDDEN)
    if dispute["dispute_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    dispute["dispute_status"] = "WITHDRAWN"
    dispute["version"] = dispute["version"] + 1
    dispute["updated_at"] = store.clock.now()
    risk.recompute(store, store.risk_state_for(dispute["original_merchant_id"]))
    return dispute


def resolve(store, dispute, outcome, caller):
    """Adjudicate a responded or auto-accepted dispute.

    `outcome` names one of WON, LOST, LOST_WITH_MEMBER_CREDIT or
    MERCHANT_WIN_CARDMEMBER_CREDIT; the branch the dispute sits on determines
    which of them is reachable.
    """
    del caller  # the adjudicating operator's identity is not compared to a row
    status = dispute["dispute_status"]
    if outcome == "WON":
        if status != "MERCHANT_RESPONDED":
            raise ApiError(ERR_INVALID_STATE)
    elif outcome in ("LOST", "LOST_WITH_MEMBER_CREDIT"):
        if status not in ("MERCHANT_RESPONDED", "AUTO_ACCEPTED"):
            raise ApiError(ERR_INVALID_STATE)
    elif outcome == "MERCHANT_WIN_CARDMEMBER_CREDIT":
        if status != "MERCHANT_RESPONDED":
            raise ApiError(ERR_INVALID_STATE)
    else:
        raise ApiError(ERR_INVALID_STATE)

    network_credit = outcome in ("LOST_WITH_MEMBER_CREDIT", "MERCHANT_WIN_CARDMEMBER_CREDIT")
    against_merchant = outcome in ("LOST", "LOST_WITH_MEMBER_CREDIT")

    if outcome == "WON":
        _resolve_won(store, dispute, network_credit)
    else:
        _resolve_lost(store, dispute, network_credit, against_merchant)

    dispute["network_settled_cents"] = dispute["network_settled_cents"] - dispute["amount_cents"]
    dispute["version"] = dispute["version"] + 1
    dispute["updated_at"] = store.clock.now()
    risk.recompute_all(store)
    return dispute


def _resolve_won(store, dispute, network_credit):
    original_id = dispute["original_merchant_id"]
    final_id = dispute["final_merchant_id"]

    # Liability is transferred from the originating merchant to the final
    # merchant.  The reservation itself is unchanged -- the chargeback still
    # exists -- but the merchant of record moves to final_merchant_id, which is
    # what reseats the derived rolling counts.
    dispute["dispute_status"] = "WON"

    if original_id != final_id:
        _require_risk_state(store, final_id)

    if network_credit:
        member = store.cardmembers.get(dispute["cardmember_id"])
        if member is not None:
            points = _dispute_outcome_points(dispute["amount_cents"], against_merchant=False)
            member["reward_points_balance"] = member["reward_points_balance"] + points
            member["version"] = member["version"] + 1
            member["updated_at"] = store.clock.now()


def _resolve_lost(store, dispute, network_credit, against_merchant):
    final_id = dispute["final_merchant_id"]
    _require_risk_state(store, final_id)

    dispute["dispute_status"] = "LOST"
    dispute["chargeback_count_reserved"] = 1

    # The re-presentment axis: a first-round loss opens a round, a second-round
    # loss closes it.
    stage = dispute["representment_stage"]
    if stage == "NONE":
        dispute["representment_stage"] = "FIRST_ROUND"
    elif stage == "FIRST_ROUND":
        dispute["representment_stage"] = "CLOSED"

    if network_credit:
        member = store.cardmembers.get(dispute["cardmember_id"])
        if member is not None:
            points = _dispute_outcome_points(dispute["amount_cents"], against_merchant)
            member["reward_points_balance"] = member["reward_points_balance"] + points
            member["version"] = member["version"] + 1
            member["updated_at"] = store.clock.now()


def _require_risk_state(store, merchant_id):
    if store.risk_state_for(merchant_id) is None:
        raise ApiError(ERR_NO_RISK_STATE)


def _dispute_outcome_points(amount_cents, against_merchant):
    """The pinned evaluation order.

    step 1: the gross resolution is rounded half up, one point per dollar;
    step 2: the merchant share is the amount times MERCHANT_SHARE_BPS over ten
            thousand -- a cents figure -- taken down to the same point scale and
            rounded half up, when the dispute was adjudicated against the
            merchant;
    step 3: the net is the resolution points less the merchant share;
    step 4: the member is credited the net but never a negative figure.

    Rounding the net directly -- applying the complement of the share to the
    amount and rounding once -- is the forbidden order and drifts by one point
    for amounts such as 60050 cents (361 points against the merchant versus 360).
    """
    resolution_points = pricing.round_half_up(
        Decimal(amount_cents) * Decimal(POINTS_PER_DOLLAR) / Decimal(100))
    merchant_share_points = (
        pricing.round_half_up(Decimal(amount_cents) * Decimal(MERCHANT_SHARE_BPS)
                              / Decimal(10000) / Decimal(100))
        if against_merchant else 0
    )
    net_points = resolution_points - merchant_share_points
    return max(0, net_points)