"""Small request-shaping helpers shared by the route modules."""

from common import LOCAL_TIME_RE, coerce_discount
from errors import ApiError
from guards import (
    require_daily_capacity,
    require_distinct,
    require_market_share,
    require_owner_patron,
    require_per_order_limit,
    require_production_active,
    require_queue_position_absent,
    require_released_allocation,
    require_run_free,
    require_seat_free,
)

__all__ = [
    "discount",
    "valid_local_time",
    "require_occ",
    "require_daily_capacity",
    "require_distinct",
    "require_market_share",
    "require_owner_patron",
    "require_per_order_limit",
    "require_production_active",
    "require_queue_position_absent",
    "require_released_allocation",
    "require_run_free",
    "require_seat_free",
]


def discount(raw):
    """Read a discount fraction; whole percents are folded into a fraction."""
    if raw is None:
        return None
    value = coerce_discount(raw)
    if value is None:
        return None
    if value < 0:
        return None
    return value


def valid_local_time(raw):
    if raw is None:
        return False
    return bool(LOCAL_TIME_RE.match(str(raw).strip()))


def require_occ(payload, field, row):
    """Fifth rung, part one: a stale declaration is refused before anything else."""
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if field not in payload or payload.get(field) is None:
        return
    if str(payload.get(field)) != str(row.get("version")):
        raise ApiError("ERR_STALE_VERSION")