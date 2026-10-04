"""Restart cost schedule (PRD 3.6): ESTIMATED and ACTUAL variants."""
import math
from decimal import Decimal

from constants import RESTART_CLASS_SCHEDULE, RESTART_CREW_COST_PER_DAY
from util import D


def whole_days_between(earlier, later):
    """Whole calendar days: floor of the hour difference / 24."""
    return math.floor((later - earlier).total_seconds() / 86400)


def estimated_cost(cost_class, capacity_tpd, planned_idle_days):
    """ESTIMATED variant: forward-looking, excludes restart crew cost."""
    sched = RESTART_CLASS_SCHEDULE[cost_class]
    return (
        Decimal(sched["base"])
        + Decimal(sched["per_tpd"]) * D(capacity_tpd)
        + Decimal(sched["per_idle_day"]) * planned_idle_days
    )


def actual_cost(cost_class, capacity_tpd, realized_idle_days, realized_restart_days):
    """ACTUAL variant: realized timestamps plus crew cost per restart day."""
    sched = RESTART_CLASS_SCHEDULE[cost_class]
    return (
        Decimal(sched["base"])
        + Decimal(sched["per_tpd"]) * D(capacity_tpd)
        + Decimal(sched["per_idle_day"]) * realized_idle_days
        + Decimal(RESTART_CREW_COST_PER_DAY) * realized_restart_days
    )
