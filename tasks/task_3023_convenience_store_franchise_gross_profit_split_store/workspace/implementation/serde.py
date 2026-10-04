"""Serialization of stored records into JSON-ready dicts.

Money is carried internally as ``Decimal`` cents. Values are emitted as JSON
numbers: an integral amount is rendered as an integer (``500000.00`` -> ``500000``)
so that both ``== 500000`` and ``== 500000.0`` comparisons hold; a fractional
amount is rendered as a float (``140000.00`` stays a float of exactly 140000.0
so ``== 140000.00`` and ``!= 140000`` both remain observable) with the decimal
places declared by the scaffold's rounding discipline.
"""

from decimal import Decimal

import timeutil

# Fields returned as JSON booleans.
BOOL_FIELDS = {
    "cold_chain_certified", "recommended_vendor", "provisional",
}

# Fields returned as datetimes in ISO 8601 UTC with three fractional digits.
DATETIME_FIELDS = {
    "created_at", "updated_at",
    "opened_on", "term_start", "term_end", "period_start", "period_end",
    "drawn_on", "window_start", "window_end",
}

# Fields returned as JSON integers (exact).
INT_FIELDS = {
    "stated_net_worth_cents", "draw_outstanding_cents", "open_shrink_charge_cents",
    "audit_adjusted_net_worth_cents", "version", "monthly_rent_cents",
    "minimum_net_worth_cents", "renewal_window_days", "renewal_eligibility_score",
    "trailing_avg_gross_profit_cents", "transfer_price_cents", "category",
    "line_gross_profit_cents", "amount_cents", "rebate_cents", "book_inventory_cents",
    "physical_inventory_cents", "shrink_cents", "capacity_units", "reserved_units",
    "ordered_units", "delivered_units", "waste_units", "unit_cost_cents",
}


def render(value, field=None):
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, bool):
        return value
    return value


def serialize(obj, fields=None):
    """Render one record as a plain dict in a stable field order."""
    if obj is None:
        return None
    out = {}
    keys = fields if fields is not None else list(obj.keys())
    for key in keys:
        if key not in obj:
            continue
        value = obj[key]
        if key in DATETIME_FIELDS and value is not None:
            out[key] = timeutil.iso_utc(value)
        elif key in BOOL_FIELDS:
            out[key] = bool(value)
        elif isinstance(value, Decimal):
            out[key] = render(value, key)
        elif isinstance(value, int) and not isinstance(value, bool):
            out[key] = value
        else:
            out[key] = value
    return out