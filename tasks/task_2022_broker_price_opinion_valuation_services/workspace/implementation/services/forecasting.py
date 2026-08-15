"""Volume forecast (scaffold 1.3 'volume_forecast', PRD 3.8).

Volume-weighted moving average over the trailing 3 calendar months of
COMPLETED orders in the same state. Window = [first day of (forecast_month -
3 months), first day of forecast_month). Weights: month-1 -> 3, month-2 -> 2,
month-3 -> 1. predicted = round_half_up((3*c1 + 2*c2 + c3) / 6).
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db

MODEL_VERSION = "VWMA-3m-v1"


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)


def _shift_month(year: int, month: int, delta: int):
    """Shift (year, month) backwards by delta months (delta >= 0)."""
    idx = year * 12 + (month - 1) - delta
    return idx // 12, idx % 12 + 1


def compute_predicted_order_count(state_code: str, forecast_month: str) -> int:
    fy, fm = (int(part) for part in forecast_month.split("-"))
    window_end = _month_start(fy, fm)
    y3, m3 = _shift_month(fy, fm, 3)
    window_start = _month_start(y3, m3)

    bounds = []
    for delta in (1, 2, 3):
        yy, mm = _shift_month(fy, fm, delta)
        start = _month_start(yy, mm)
        yy2, mm2 = _shift_month(fy, fm, delta - 1)
        end = _month_start(yy2, mm2)
        bounds.append((start, end))

    counts = [0, 0, 0]  # c1, c2, c3
    for order in db.orders.values():
        if order["fulfillment_status"] != "COMPLETED" or order["completed_at"] is None:
            continue
        completed_at = order["completed_at"]
        if not (window_start <= completed_at < window_end):
            continue
        prop = db.properties.get(order["property_id"])
        if prop is None or prop["state_code"] != state_code:
            continue
        for i, (start, end) in enumerate(bounds):
            if start <= completed_at < end:
                counts[i] += 1
                break

    c1, c2, c3 = counts
    raw = Decimal(3 * c1 + 2 * c2 + 1 * c3) / Decimal(6)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
