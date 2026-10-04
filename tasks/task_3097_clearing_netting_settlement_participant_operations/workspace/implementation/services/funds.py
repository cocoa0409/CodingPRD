"""Clearing-fund sizing.

Calculation `clearing_fund_scaling_and_cap` (SCAFFOLD section 1.3):

  open_risk_cents = abs( SUM over settled LOCKED_IN trades of the participant on
                         the fund's security of (BUY ? +qty*price : -qty*price) )
  net_capital_floor_cents = participant.required_min_net_capital_cents when
                            financial_standard_status == FAIL, else 0
  volatility_multiplier_bps = 15000 when security.current_volatility_bps > 2500
                              else 10000
  stacked_cents = round_half_up(open_risk_cents * multiplier_bps / 10000, 0)
  stacked_cents = max(250000, min(stacked_cents, 50000000))
  component_amount_cents = max(stacked_cents, net_capital_floor_cents)

The rounding is applied once, immediately after the multiply and before either
clamp; MIN_COMPONENT is applied before MAX_COMPONENT; the net-capital floor is
applied last.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db
from lookups import components_of_fund, is_settled_trade

VOLATILITY_ELEVATED_BPS = 2500
MULTIPLIER_ELEVATED_BPS = 15000
MULTIPLIER_BASE_BPS = 10000
MIN_COMPONENT_CENTS = 250000
MAX_COMPONENT_CENTS = 50000000


def open_risk_cents(participant_id, security_id):
    total = 0
    for trade in db.trade_submissions.values():
        if trade["participant_id"] != participant_id:
            continue
        if trade["security_id"] != security_id:
            continue
        if not is_settled_trade(trade):
            continue
        gross = trade["quantity"] * trade["trade_price_cents"]
        total += gross if trade["side"] == "BUY" else -gross
    return abs(total)


def component_amount_for(participant, security):
    risk = open_risk_cents(participant["id"], security["id"])
    if participant["financial_standard_status"] == "FAIL":
        net_capital_floor_cents = participant["required_min_net_capital_cents"] or 0
    else:
        net_capital_floor_cents = 0
    if security["current_volatility_bps"] > VOLATILITY_ELEVATED_BPS:
        multiplier_bps = MULTIPLIER_ELEVATED_BPS
    else:
        multiplier_bps = MULTIPLIER_BASE_BPS
    rounded = (
        Decimal(risk) * Decimal(multiplier_bps) / Decimal(10000)
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    stacked = int(rounded)
    stacked = max(MIN_COMPONENT_CENTS, min(stacked, MAX_COMPONENT_CENTS))
    return max(stacked, net_capital_floor_cents), stacked, net_capital_floor_cents


def sized_participants(fund):
    return [
        p for p in db.participants.values()
        if p["membership_status"] == "ACTIVE"
        and p["participant_class"] == fund["participant_class"]
    ]


def latest_component(fund_id, participant_id):
    rows = [
        comp for comp in components_of_fund(fund_id)
        if comp["participant_id"] == participant_id
    ]
    if not rows:
        return None
    rows.sort(key=lambda comp: (comp["created_at"], comp["id"]))
    return rows[-1]


def next_generation(fund_id):
    generations = [comp["generation"] for comp in components_of_fund(fund_id)]
    return (max(generations) + 1) if generations else 1


def refresh_fund_totals(fund):
    """Recompute the fund's read-only aggregates from its component rows."""
    components = components_of_fund(fund["id"])
    fund["fund_balance_cents"] = sum(
        comp["component_balance_cents"] for comp in components if comp["status"] != "RELEASED"
    )
    total = 0
    participants = {}
    for comp in components:
        participants.setdefault(comp["participant_id"], []).append(comp)
    for rows in participants.values():
        rows.sort(key=lambda comp: (comp["created_at"], comp["id"]))
        total += rows[-1]["component_amount_cents"]
    fund["total_component_cents"] = total
    fund["experiences_deficit"] = any(
        rows[-1]["component_balance_cents"] < 0 for rows in participants.values()
    )
    return fund


def refresh_totals_for_class(participant_class):
    """PRD 3.9: re-aggregate every fund whose sizing population changed."""
    for fund in db.clearing_funds.values():
        if fund["participant_class"] == participant_class:
            refresh_fund_totals(fund)