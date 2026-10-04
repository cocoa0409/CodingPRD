"""Serialisation to JSON with the exchange's canonical timestamp format."""
from datetime import datetime

import clock

MONEY_FIELDS = {
    "compensation_earned_cents", "escrow_balance_cents", "base_fee_cents",
    "pay_rate_cents", "final_pay_period_income_cents", "annualized_income_cents",
    "fee_charged_cents", "gross_amount_cents", "unit_rate_cents", "gross_accrued_cents",
    "adjusted_cents", "waived_cents", "paid_cents", "settlement_budget_cents",
    "waiver_budget_cents", "settled_gross_cents", "settled_net_cents", "reverted_cents",
    "amount_cents",
}


def ts(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = clock.parse_iso(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def out(obj):
    if isinstance(obj, list):
        return [out(item) for item in obj]
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key.startswith("_"):
                continue
            if isinstance(value, datetime):
                result[key] = ts(value)
            elif isinstance(value, dict):
                result[key] = out(value)
            elif isinstance(value, list):
                result[key] = out(value)
            else:
                result[key] = value
        return result
    return obj


def public_summary(obj):
    """Compact representation of an entity inside a nested payload block."""
    return out(obj)