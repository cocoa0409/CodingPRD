"""Route handlers: the logical clock and the liveness probe."""

from clock import parse_iso, to_iso
from errors import fail, success_payload
from store import store


def health(ctx):
    """GET /_health — permitted to every declared role and to Anonymous."""
    return success_payload({"status": "ok"}, "object"), 200


def set_clock(ctx):
    """POST /_clock/set_current_utc — the operator-only clock advance."""
    supplied = ctx.text("current_utc")
    instant = parse_iso(supplied)
    if instant is None:
        fail("ERR_INVALID_AMOUNT", "current_utc must be an ISO 8601 instant.")
    store.current_utc = to_iso(instant)

    from cascades import expire_pending_substantiations, rederive_comparisons

    # PRD §3.9: "a PENDING substantiation whose valid_until passes before it is
    # ever enabled is moved to DISABLED by the system without operator
    # involvement" — the clock advance is that system-driven evaluation point.
    expire_pending_substantiations(instant)
    rederive_comparisons(instant)
    return success_payload({"current_utc": store.current_utc}, "object"), 200