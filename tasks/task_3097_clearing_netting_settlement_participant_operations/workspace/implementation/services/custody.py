"""Corporate actions and book-entry custody servicing.

Calculation `custody_position_servicing` (SCAFFOLD section 1.3):
  SPLIT           adjustment = trunc_toward_zero(qty * num / den)
  REVERSE_SPLIT   adjustment = -trunc_toward_zero(qty * (num - den) / num)
  CASH_DIVIDEND   adjustment = 0; cash = new_settled_quantity * rate
The per-share entitlement is formed on the quantity leg first and truncated
toward zero before any cash leg is computed. Targets are visited in created_at
ASC order, tie-broken by the owning participant's legal_name ASC.
"""

from decimal import Decimal, ROUND_DOWN

from db import db, new_record, touch
from errors import (
    api_error,
    ERR_ACTION_NOT_EFFECTIVE,
    ERR_INVALID_STATE,
    ERR_SHORT_POSITION_ADJUSTMENT,
)
from lookups import windows_of_security

ACTION_TYPES = ("SPLIT", "REVERSE_SPLIT", "CASH_DIVIDEND")


def trunc_toward_zero(numerator, denominator):
    """Integer division truncated toward zero."""
    if denominator == 0:
        return 0
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_DOWN))


def _serviced_windows(action):
    return [
        window
        for window in windows_of_security(action["security_id"])
        if window["settlement_date"] >= action["effective_date"]
    ]


def _window_for(net_position):
    return db.settlement_windows.get(net_position["window_id"])


def guard_apply(action):
    """The three gates, in the order PRD 3.8 states them."""
    if action["status"] != "ANNOUNCED":
        raise api_error(ERR_INVALID_STATE)

    for window in windows_of_security(action["security_id"]):
        if window["settlement_date"] < action["effective_date"]:
            raise api_error(ERR_ACTION_NOT_EFFECTIVE)

    for net_position in db.net_positions.values():
        if net_position["security_id"] != action["security_id"]:
            continue
        if net_position["net_quantity"] < 0:
            raise api_error(ERR_SHORT_POSITION_ADJUSTMENT)


def adjustments(action, quantity):
    if action["action_type"] == "SPLIT":
        adjustment = trunc_toward_zero(
            quantity * action["ratio_numerator"], action["ratio_denominator"]
        )
        return adjustment, 0
    if action["action_type"] == "REVERSE_SPLIT":
        adjustment = -trunc_toward_zero(
            quantity * (action["ratio_numerator"] - action["ratio_denominator"]),
            action["ratio_numerator"],
        )
        return adjustment, 0
    # CASH_DIVIDEND: the cash leg is keyed on the already-adjusted quantity.
    new_quantity = quantity
    return 0, new_quantity * action["cash_rate_cents_per_unit"]


def serviced_targets(action):
    """Custody positions and net positions, in the pinned servicing order."""
    targets = []
    for account in db.custody_accounts.values():
        participant = db.participants.get(account["participant_id"])
        for position in account["positions"]:
            if position["security_id"] != action["security_id"]:
                continue
            targets.append(
                (
                    position["created_at"],
                    participant["legal_name"] if participant else "",
                    account,
                    position,
                )
            )
    net_targets = []
    for net_position in db.net_positions.values():
        if net_position["security_id"] != action["security_id"]:
            continue
        window = _window_for(net_position)
        if window is None:
            continue
        if window["settlement_date"] < action["effective_date"]:
            continue
        participant = db.participants.get(net_position["participant_id"])
        net_targets.append(
            (
                net_position["created_at"],
                participant["legal_name"] if participant else "",
                net_position,
            )
        )
    targets.sort(key=lambda item: (item[0], item[1]))
    net_targets.sort(key=lambda item: (item[0], item[1]))
    return targets, net_targets


def apply_action(action):
    guard_apply(action)
    custody_targets, net_targets = serviced_targets(action)

    for _created, _name, account, position in custody_targets:
        adjustment, cash = adjustments(action, position["settled_quantity"])
        position["_prior_settled_quantity"] = position["settled_quantity"]
        position["_prior_action_id"] = position["last_corporate_action_applied_id"]
        position["settled_quantity"] = position["settled_quantity"] + adjustment
        position["last_corporate_action_applied_id"] = action["id"]
        position["_applied_cash_cents"] = cash
        position["_applied_action_id"] = action["id"]

    for _created, _name, net_position in net_targets:
        adjustment, cash = adjustments(action, net_position["net_quantity"])
        net_position["_prior_net_quantity"] = net_position["net_quantity"]
        net_position["_prior_cash_delta"] = net_position["cash_delta_cents"]
        net_position["_prior_action_id"] = net_position.get("last_corporate_action_applied_id")
        net_position["net_quantity"] = net_position["net_quantity"] + adjustment
        # PRD 3.8: the cash adjustment rides on the settled quantity and is
        # written to the position's cash leg — a cash dividend pays the holder
        # of the position, so the delta survives both the explicit apply and
        # the settlement-pass servicing.
        net_position["cash_delta_cents"] = net_position["cash_delta_cents"] + cash
        net_position["last_corporate_action_applied_id"] = action["id"]
        touch(net_position)

    action["applied_at"] = db.now_iso()
    action["status"] = "APPLIED"
    touch(action)
    return action


def reverse_action(action):
    if action["status"] != "APPLIED":
        raise api_error(ERR_INVALID_STATE)

    for account in db.custody_accounts.values():
        for position in account["positions"]:
            if position.get("_applied_action_id") != action["id"]:
                continue
            if "_prior_settled_quantity" in position:
                position["settled_quantity"] = position.pop("_prior_settled_quantity")
            position["last_corporate_action_applied_id"] = position.pop(
                "_prior_action_id", None
            )
            position.pop("_applied_cash_cents", None)
            position.pop("_applied_action_id", None)

    for net_position in db.net_positions.values():
        if "_prior_net_quantity" not in net_position:
            continue
        if net_position.get("last_corporate_action_applied_id") != action["id"]:
            continue
        net_position["net_quantity"] = net_position.pop("_prior_net_quantity")
        # PRD 3.8: reversal restores the pre-application quantity, so the
        # serviced cash leg is removed with it — a cash dividend's addition
        # must not survive the reversal of the action that made it.
        net_position["cash_delta_cents"] = net_position.pop("_prior_cash_delta")
        net_position["last_corporate_action_applied_id"] = net_position.pop(
            "_prior_action_id", None
        )
        touch(net_position)

    action["status"] = "REVERSED"
    touch(action)
    return action


def apply_on_settle(window):
    """Settlement pass: service every applied action on the window's security."""
    for action in db.corporate_actions.values():
        if action["security_id"] != window["security_id"]:
            continue
        if action["status"] != "APPLIED":
            continue
        if action["effective_date"] > window["settlement_date"]:
            continue
        for account in db.custody_accounts.values():
            for position in account["positions"]:
                if position["security_id"] != action["security_id"]:
                    continue
                if position.get("_applied_action_id") == action["id"]:
                    continue
                adjustment, cash = adjustments(action, position["settled_quantity"])
                position["_prior_settled_quantity"] = position["settled_quantity"]
                position["_prior_action_id"] = position["last_corporate_action_applied_id"]
                position["settled_quantity"] = position["settled_quantity"] + adjustment
                position["last_corporate_action_applied_id"] = action["id"]
                position["_applied_cash_cents"] = cash
                position["_applied_action_id"] = action["id"]
        for net_position in db.net_positions.values():
            window_row = _window_for(net_position)
            if window_row is None or window_row["id"] != window["id"]:
                continue
            if net_position["security_id"] != action["security_id"]:
                continue
            if net_position.get("last_corporate_action_applied_id") == action["id"]:
                continue
            if "_prior_net_quantity" in net_position:
                continue
            adjustment, cash = adjustments(action, net_position["net_quantity"])
            net_position["_prior_net_quantity"] = net_position["net_quantity"]
            net_position["_prior_cash_delta"] = net_position["cash_delta_cents"]
            net_position["_prior_action_id"] = net_position.get(
                "last_corporate_action_applied_id"
            )
            net_position["net_quantity"] = net_position["net_quantity"] + adjustment
            net_position["cash_delta_cents"] = net_position["cash_delta_cents"] + cash
            net_position["last_corporate_action_applied_id"] = action["id"]
            touch(net_position)


def create_action(security_id, action_type, numerator, denominator, cash_rate,
                  effective_date):
    record = new_record(
        security_id=security_id,
        action_type=action_type,
        ratio_numerator=numerator,
        ratio_denominator=denominator,
        cash_rate_cents_per_unit=cash_rate,
        effective_date=effective_date,
        status="ANNOUNCED",
        applied_at=None,
    )
    db.corporate_actions[record["id"]] = record
    return record