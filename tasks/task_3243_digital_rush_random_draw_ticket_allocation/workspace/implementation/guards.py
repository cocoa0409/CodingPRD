"""Shared request guards, in the precedence ladder's order."""

from clock import CLOCK, parse_iso
from db import DB
from errors import ApiError
from services import holds as holds_service


def require_version(payload, field, row, bump_field=None):
    """Fifth rung, part one: OCC runs before every downstream comparison."""
    if field not in payload or payload.get(field) is None:
        return
    expected = payload.get(field)
    current = row.get(bump_field or "version")
    if str(expected) != str(current):
        raise ApiError("ERR_STALE_VERSION")


def require_state(row, allowed, field="status"):
    """Fifth rung, part two: the target row must permit the requested move."""
    if row.get(field) not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def require_not_terminal(row, terminal, field="status"):
    """Fifth rung, part three: a terminal row may not move again."""
    if row.get(field) in terminal:
        raise ApiError("ERR_ALREADY_TERMINAL")


def require_production_active(performance_row):
    """Eighteenth rung: a suspended partnership dispenses no seats."""
    production = DB.get("production", performance_row["production_id"])
    if production is None or production["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCTION_SUSPENDED")


def require_released_allocation(allocation_row, performance_row):
    """Ninth rung: a rush seat cannot be bought or queued for before its release."""
    if allocation_row["status"] != "RELEASED":
        raise ApiError("ERR_RUSH_NOT_RELEASED")
    release_at = allocation_row.get("release_at")
    if release_at is None:
        raise ApiError("ERR_RUSH_NOT_RELEASED")
    if CLOCK.now < parse_iso(release_at):
        raise ApiError("ERR_RUSH_NOT_RELEASED")


def require_seat_free(performance_row, label):
    """Eleventh rung: no non-terminal hold may already carry this label."""
    if holds_service.non_terminal_hold_on_label(performance_row["id"], label) is not None:
        raise ApiError("ERR_SEAT_ALREADY_HELD")


def require_run_free(performance_row, run):
    """Twelfth rung: an order's run must not intersect an existing order's run."""
    if holds_service.run_intersects_existing(performance_row["id"], run):
        raise ApiError("ERR_ORDER_BLOCK_CAPACITY")


def require_daily_capacity(allocation_row, additional_quantity):
    """Fifteenth rung: the day's own ceiling, tested after the market share cap."""
    sold = int(allocation_row.get("quantity_sold_today") or 0)
    cap = int(allocation_row.get("daily_release_cap") or 0)
    if sold + int(additional_quantity) > cap:
        raise ApiError("ERR_ALLOCATION_EXHAUSTED")


def require_per_order_limit(allocation_row, quantity):
    """Sixteenth rung: per-order limits bind only after the epoch cap has passed."""
    limit = int(allocation_row.get("per_order_limit") or 0)
    if int(quantity) > limit:
        raise ApiError("ERR_PER_ORDER_LIMIT_EXCEEDED")


def require_market_share(performance_row, allocation_row, prospective_release):
    """Fourteenth rung: the market-wide discount ceiling binds before the day cap."""
    from services import calc

    market_seats = (
        calc.MARKET_RUSH_SHARE_CAP_BP * int(performance_row["total_seat_capacity"])
    ) // 10000
    others = calc.non_standard_released(
        performance_row["id"], exclude_allocation_id=allocation_row["id"]
    )
    if others + int(prospective_release) > market_seats:
        raise ApiError("ERR_MARKET_SHARE_CAP_EXCEEDED")


def require_equal(actor, recorded, error_id="ERR_SOD_VIOLATION"):
    """Nineteenth rung: the acting operator must differ from the recorded one."""
    if recorded is not None and str(actor) == str(recorded):
        raise ApiError(error_id)


def require_distinct(actor, recorded, error_id="ERR_SOD_VIOLATION"):
    """Segregation of duties: the acting operator must differ from the prior step."""
    if recorded is not None and str(actor) == str(recorded):
        raise ApiError(error_id)


def require_owner_patron(actor_id, resource_patron_id, error_id="ERR_FORBIDDEN"):
    """Ownership: the resource's patron key must equal X-User-ID."""
    if str(actor_id) != str(resource_patron_id):
        raise ApiError(error_id)


def require_patron_active(patron_row):
    if patron_row is None or patron_row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")


def require_duplicate_entry_absent(allocation_id, patron_id):
    """Seventh rung: one non-CANCELLED entry per person per draw."""
    for entry in DB.all("draw_entry"):
        if entry["allocation_id"] != allocation_id:
            continue
        if entry["patron_id"] != patron_id:
            continue
        if entry["status"] != "CANCELLED":
            raise ApiError("ERR_DUPLICATE_DRAW_ENTRY")


def require_queue_position_absent(performance_id, patron_id):
    """Seventeenth rung: one active position per patron per performance."""
    for position in DB.all("queue_position"):
        if position["performance_id"] != performance_id:
            continue
        if position["patron_id"] != patron_id:
            continue
        if position["status"] in ("WAITING", "ADMITTED"):
            raise ApiError("ERR_QUEUE_POSITION_EXISTS")