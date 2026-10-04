"""Composite setup helpers.

Every helper builds its preconditions from scratch through the platform's own
operations, because each test starts against an empty database. Setup calls use
the lenient success validator so a broken chain reports a clear "Setup failed"
message rather than a confusing assertion failure.
"""
import pytest
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from . import factories as f
from .api_client import api_client

from datetime import datetime, timedelta, timezone


def parse_iso(value):
    """Parse an ISO 8601 instant (tolerating a trailing Z) into naive UTC."""
    text = str(value).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed
from .constants import (
    BASE_CLOCK, BASE_CLOCK_DAY, CLOCK_START, PREV_CLOCK, PREV_CLOCK_DAY,
)
from .test_users import (
    TEST_USERS, make_patron_headers,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["allocations_coordinator_headers"]
CS = TEST_USERS["customer_service_headers"]
FIN = TEST_USERS["financial_ops_headers"]
DESK = TEST_USERS["concierge_desk_staff_headers"]
PRODUCER = TEST_USERS["producer_analyst_headers"]
DEMAND = TEST_USERS["demand_analyst_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Low-level plumbing
# --------------------------------------------------------------------------

def _ok(response, what):
    """Lenient setup unwrap with a domain-labelled failure message."""
    if response.status_code >= 300:
        pytest.fail(
            f"Setup failed: {what} returned {response.status_code} "
            f"{response.text[:400]}"
        )
    return get_success_data(response)


def set_clock(instant):
    """Set the logical clock to a supplied instant."""
    return _ok(api_client.set_clock(instant, ADMIN), f"set clock to {instant}")


def ops_run(instant):
    """Advance to an operational epoch and read back the stage counters."""
    return _ok(api_client.run_ops(instant, ADMIN), f"ops run at {instant}")


def declare_market(market_code="NYC", city="New York",
                   handoff_model="MOBILE_PUSH", desk_code=None,
                   daily_capacity=None):
    payload = f.market_payload(market_code=market_code, city=city,
                               handoff_model=handoff_model)
    if desk_code is not None:
        payload["desk_code"] = desk_code
    if daily_capacity is not None:
        payload["daily_capacity"] = daily_capacity
    return _ok(api_client.create_market(payload, OPS), f"declare market {market_code}")


def register_patron(email=None, display_name="Test Patron", market_code="NYC"):
    payload = f.patron_payload(market_code=market_code, display_name=display_name)
    if email is not None:
        payload["email"] = email
    return _ok(api_client.register_patron(payload), "register patron")


def patron_headers(patron):
    """Ownership-carrying headers for an entity-backed patron."""
    return make_patron_headers(patron["id"])


def register_production(title="Test Play", producer_org="Test Partners",
                        refund_window_hours=720, exchange_fee_cents=300,
                        exchange_allowed=None):
    payload = f.production_payload(
        title=title, producer_org=producer_org,
        refund_window_hours=refund_window_hours,
        exchange_fee_cents=exchange_fee_cents,
    )
    if exchange_allowed is not None:
        payload["exchange_allowed"] = exchange_allowed
    return _ok(api_client.create_production(payload, OPS), "register production")


def activate_production(production):
    return _ok(
        api_client.transition_production(
            production["id"],
            {"to_status": "ACTIVE",
             "expected_production_version": live_production(production)["version"]},
            OPS,
        ),
        "activate production",
    )


def schedule_performance(production, market_code="NYC", venue_name="Test Theatre",
                         starts_at="2026-10-05T19:00:00Z", face_value_cents=10000,
                         total_seat_capacity=30):
    payload = f.performance_payload(
        production["id"], market_code=market_code, venue_name=venue_name,
        starts_at=starts_at, face_value_cents=face_value_cents,
        total_seat_capacity=total_seat_capacity,
    )
    return _ok(api_client.create_performance(payload, OPS), "schedule performance")


def move_performance(performance, to_status):
    return _ok(
        api_client.transition_performance(
            performance["id"],
            {"to_status": to_status,
             "expected_performance_version": live_performance(performance)["version"]},
            OPS,
        ),
        f"move performance to {to_status}",
    )


def add_allocation(performance, **overrides):
    return _ok(
        api_client.create_allocation(performance["id"],
                                     f.allocation_payload(**overrides), COORD),
        "create allocation",
    )


def schedule_allocation(allocation, performance=None):
    """Approve a DRAFT allocation. The version is re-read when it can be named."""
    version = allocation["version"]
    if performance is not None:
        version = live_allocation(performance, allocation)["version"]
    return _ok(
        api_client.schedule_allocation(
            allocation["id"],
            {"expected_allocation_version": version},
            COORD,
        ),
        "schedule allocation",
    )


def release_allocation(allocation, production, performance, epoch=BASE_CLOCK_DAY,
                       advance_days=None):
    """Release the allocation's next unsettled epoch and return that release.

    PRD §3.3: "only the allocation's next unsettled epoch is accepted", so an
    epoch is supplied only when the allocation itself still names it; otherwise
    the epoch the server will accept is taken from the settled epochs already on
    the row. All three OCC versions are re-read live, because a sibling release of
    the same performance moves the production and the performance underneath this
    one. When ``advance_days`` is supplied the logical clock is left that many
    days on, so the allocation's next unsettled epoch is that much further ahead
    of the day just released.
    """
    current = live_allocation(performance, allocation)
    settled = list(current.get("settled_epochs") or [])
    if str(epoch) in [str(item) for item in settled]:
        day = _parse_day(str(settled[-1]) if settled else epoch)
        epoch = (day + timedelta(days=1)).strftime("%Y-%m-%d")
    if advance_days is not None:
        set_clock(_shift_clock(epoch, advance_days))
    return _ok(
        api_client.release_allocation(
            allocation["id"], epoch,
            {"expected_production_version": live_production(production)["version"],
             "expected_performance_version": live_performance(performance)["version"],
             "expected_allocation_version": current["version"]},
            OPS,
        ),
        f"release allocation for {epoch}",
    )


def _parse_day(text):
    from datetime import date

    year, month, day = str(text).split("-")
    return date(int(year), int(month), int(day))


def _shift_clock(epoch, days):
    from datetime import timedelta as _td

    day = _parse_day(epoch) + _td(days=days)
    return "%sT09:00:00Z" % day.strftime("%Y-%m-%d")


def join_queue(performance, allocation, patron):
    return _ok(
        api_client.join_queue(performance["id"],
                              {"allocation_id": allocation["id"]},
                              patron_headers(patron)),
        "join rush queue",
    )


def buy_seats(performance, allocation, patron, quantity=1, idempotency_key=None):
    payload = f.purchase_payload(performance["id"], allocation["id"],
                                 quantity=quantity)
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    return _ok(api_client.create_purchase(payload, patron_headers(patron)),
               "place order")


def settle_purchase(purchase):
    """Authorise a pending order and then settle it.

    PRD §3.9: "A `FinancialOps` operator moves a pending order to `AUTHORIZED`
    and then on to `SETTLED`." The second step is skipped cleanly when the
    purchase's `logistics_status` has already left the authorisation band, because
    the first step is then already the furthest this helper may take it.
    """
    _ok(
        api_client.settle_purchase(
            purchase["id"],
            {"expected_purchase_version": get_purchase(purchase["id"])["version"]},
            FIN,
        ),
        "authorize purchase",
    )
    authorised = get_purchase(purchase["id"])
    if authorised["logistics_status"] not in ("AWAITING_HANDOFF", "REVOKED"):
        return authorised
    return _ok(
        api_client.settle_purchase(
            purchase["id"],
            {"expected_purchase_version": authorised["version"]},
            FIN,
        ),
        "settle purchase",
    )


def deliver_purchase(purchase):
    """Push a purchase's ticket to the patron's phone in a push market."""
    return _ok(
        api_client.deliver_purchase(
            purchase["id"],
            {"expected_purchase_version": get_purchase(purchase["id"])["version"]},
            DEMAND,
        ),
        "deliver purchase",
    )


def get_allocation(performance, allocation_id):
    """Read one allocation back from the performance's allocation collection."""
    rows = _ok(api_client.list_allocations(performance["id"], PRODUCER),
               "list allocations")
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    for row in rows:
        if row.get("id") == allocation_id:
            return row
    pytest.fail(f"Setup failed: allocation {allocation_id} not found in listing")


def get_performance(performance_id):
    return _ok(api_client.get_performance(performance_id, CS), "read performance")


def get_purchase(purchase_id):
    return _ok(api_client.get_purchase(purchase_id, CS), "read purchase")


def live_production(production):
    """Re-read a production so its OCC version is the server's current one."""
    return _ok(api_client.get_production(production["id"], OPS), "read production")


def live_allocation(performance, allocation):
    """Re-read an allocation so its OCC version is the server's current one."""
    return get_allocation(performance, allocation["id"])


def live_performance(performance):
    """Re-read a performance so its OCC version is the server's current one."""
    return get_performance(performance["id"])


def live_entry(performance, entry):
    """Re-read a draw entry so its OCC version is the server's current one."""
    return get_entry(performance, entry["id"])


def live_patron(patron):
    """Re-read a patron so its OCC version is the server's current one."""
    return get_patron(patron)


def get_patron(patron):
    return _ok(api_client.get_patron(patron["id"], CS), "read patron")


# --------------------------------------------------------------------------
# Tier 1 — partnership, performance and allocation progression
# --------------------------------------------------------------------------

def setup_active_performance(handoff_model="MOBILE_PUSH", market_code="NYC",
                             desk_code=None, daily_capacity=None,
                             face_value_cents=10000, total_seat_capacity=30,
                             starts_at=None,
                             refund_window_hours=720, exchange_fee_cents=300,
                             exchange_allowed=True, on_sale=True,
                             clock=BASE_CLOCK):
    """An active partnership with one on-sale performance in a declared market.

    Returns ``(market, production, performance)``.
    """
    set_clock(clock)
    market = declare_market(market_code=market_code, handoff_model=handoff_model,
                            desk_code=desk_code, daily_capacity=daily_capacity)
    production = activate_production(
        register_production(refund_window_hours=refund_window_hours,
                            exchange_fee_cents=exchange_fee_cents,
                            exchange_allowed=exchange_allowed)
    )
    performance = schedule_performance(
        production, market_code=market_code, face_value_cents=face_value_cents,
        total_seat_capacity=total_seat_capacity,
        starts_at=starts_at or "2026-10-05T19:00:00Z",
    )
    if on_sale:
        performance = move_performance(performance, "ONSALE")
    return market, production, performance


def setup_open_performance(handoff_model="MOBILE_PUSH", market_code="NYC",
                           desk_code=None, daily_capacity=None,
                           face_value_cents=10000, total_seat_capacity=30,
                           starts_at="2026-10-05T19:00:00Z", **production_kwargs):
    """A market, an active partnership and a performance left in SCHEDULED."""
    kwargs = dict(
        handoff_model=handoff_model, market_code=market_code,
        desk_code=desk_code, daily_capacity=daily_capacity,
        face_value_cents=face_value_cents,
        total_seat_capacity=total_seat_capacity, starts_at=starts_at,
        on_sale=False,
    )
    kwargs.update(production_kwargs)
    return setup_active_performance(**kwargs)


def setup_scheduled_allocation(handoff_model="MOBILE_PUSH", market_code="NYC",
                               desk_code=None, daily_capacity=None,
                               face_value_cents=10000, total_seat_capacity=30,
                               starts_at="2026-10-05T19:00:00Z", on_sale=True,
                               epoch=BASE_CLOCK_DAY, **allocation_overrides):
    """An on-sale performance carrying one SCHEDULED allocation.

    Returns ``(production, performance, allocation)``.
    """
    market, production, performance = setup_active_performance(
        handoff_model=handoff_model, market_code=market_code,
        desk_code=desk_code, daily_capacity=daily_capacity,
        face_value_cents=face_value_cents,
        total_seat_capacity=total_seat_capacity, starts_at=starts_at,
        on_sale=on_sale,
    )
    allocation = schedule_allocation(
        add_allocation(performance, **allocation_overrides)
    )
    return production, performance, allocation


def setup_released_allocation(handoff_model="MOBILE_PUSH", market_code="NYC",
                              desk_code=None, daily_capacity=None,
                              face_value_cents=10000, total_seat_capacity=30,
                              starts_at="2026-10-05T19:00:00Z",
                              epoch=BASE_CLOCK_DAY, clock=BASE_CLOCK,
                              **allocation_overrides):
    """The base scenario: market, active partnership, on-sale performance and a
    RELEASED allocation for the current epoch.

    Returns ``(production, performance, allocation)``.
    """
    set_clock(clock)
    production, performance, allocation = setup_scheduled_allocation(
        handoff_model=handoff_model, market_code=market_code,
        desk_code=desk_code, daily_capacity=daily_capacity,
        face_value_cents=face_value_cents,
        total_seat_capacity=total_seat_capacity, starts_at=starts_at,
        epoch=epoch, **allocation_overrides,
    )
    allocation = release_allocation(allocation, production, performance, epoch=epoch)
    return production, performance, allocation


def setup_two_released_allocations(handoff_model="MOBILE_PUSH",
                                   daily_quantity=6, per_order_limit=4,
                                   **kwargs):
    """Two RELEASED rush allocations of the same performance.

    Returns ``(production, performance, source, target)``.
    """
    production, performance = setup_active_performance(
        handoff_model=handoff_model, **kwargs
    )[1:]
    source = release_allocation(
        schedule_allocation(add_allocation(performance, daily_quantity=daily_quantity,
                                           per_order_limit=per_order_limit)),
        production, performance,
    )
    target = release_allocation(
        schedule_allocation(add_allocation(performance, daily_quantity=daily_quantity,
                                           per_order_limit=per_order_limit)),
        production, performance,
    )
    return production, performance, source, target


def setup_released_draw_allocation(handoff_model="MOBILE_PUSH",
                                   starts_at="2026-10-05T19:00:00Z",
                                   epoch=BASE_CLOCK_DAY,
                                   **allocation_overrides):
    """A RELEASED DRAW allocation of an on-sale performance.

    Returns ``(production, performance, allocation)``.
    """
    overrides = {
        "ticket_type": "DRAW",
        "daily_quantity": 2,
        "claim_window_minutes": 30,
        "winner_basis_points": 10000,
        "waitlist_multiplier": 2,
        "per_order_limit": 1,
    }
    overrides.update(allocation_overrides)
    return setup_released_allocation(
        handoff_model=handoff_model, starts_at=starts_at, epoch=epoch,
        **overrides,
    )


def setup_scheduled_draw_allocation(**allocation_overrides):
    """A SCHEDULED (not yet released) DRAW allocation of an on-sale performance.

    Returns ``(production, performance, allocation)``.
    """
    overrides = {
        "ticket_type": "DRAW",
        "daily_quantity": 2,
        "claim_window_minutes": 30,
        "winner_basis_points": 10000,
        "waitlist_multiplier": 2,
        "per_order_limit": 1,
    }
    overrides.update(allocation_overrides)
    return setup_scheduled_allocation(**overrides)


# --------------------------------------------------------------------------
# Tier 2 — patron hierarchy and queue admission
# --------------------------------------------------------------------------

def admit_patron(performance, allocation, patron):
    """Admit a patron through the next operational epoch.

    PRD §3.6: an admission is issued by the sweep at an epoch, and the epoch
    instant is the allocation's own release instant, so the patron is admitted
    and the logical clock is left on that same instant.
    """
    join_queue(performance, allocation, patron)
    release_at = allocation.get("release_at") or BASE_CLOCK
    ops_run(release_at)
    set_clock(release_at)


def setup_buyer(performance, allocation, email=None, quantity=1,
                idempotency_key=None):
    """A patron holding a live queue admission, plus one order.

    The queue admission is issued by an operational epoch run at the
    allocation's release instant, so the helper joins, sweeps, and buys with the
    logical clock at an instant at which the release is honoured and the
    admission has not lapsed. Returns ``(patron, purchase)``.
    """
    patron = register_patron(email=email,
                             market_code=performance["market_code"])
    admit_patron(performance, allocation, patron)
    purchase = buy_seats(performance, allocation, patron, quantity=quantity,
                         idempotency_key=idempotency_key)
    return patron, purchase


def setup_admitted_patron(performance, allocation, email=None):
    """A patron holding an ADMITTED position inside its twenty minute window."""
    patron = register_patron(email=email)
    join_queue(performance, allocation, patron)
    ops_run("2026-09-12T09:05:00Z")
    return patron


# --------------------------------------------------------------------------
# Draw entry, execution and claiming
# --------------------------------------------------------------------------

def file_draw_entry(performance, allocation, patron, declaration=None):
    payload = f.draw_entry_payload(allocation["id"])
    if declaration is not None:
        payload["declaration_text"] = declaration
    return _ok(api_client.create_draw_entry(performance["id"], payload,
                                            patron_headers(patron)),
               "file draw entry")


def execute_draw(allocation, performance=None, at=None):
    """Execute a draw. The allocation's OCC version is re-read when it can be named."""
    if at is not None:
        set_clock(at)
    version = allocation["version"]
    if performance is not None:
        version = live_allocation(performance, allocation)["version"]
    return _ok(
        api_client.execute_draw(
            allocation["id"],
            {"expected_allocation_version": version},
            OPS,
        ),
        "execute draw",
    )


def setup_drawn_allocation(performance, allocation, patrons,
                           execute_at="2026-09-12T09:05:00Z"):
    """File one entry per patron in order, then execute the draw once.

    Returns ``(entries, execution)`` where ``entries`` is aligned with
    ``patrons``.
    """
    entries = [file_draw_entry(performance, allocation, patron)
               for patron in patrons]
    execution = execute_draw(allocation, at=execute_at)
    return entries, execution


def claim_entry(performance, allocation, patron, entry, quantity=1):
    return _ok(
        api_client.claim_draw_entry(
            entry["id"],
            {"quantity": quantity,
             "expected_draw_entry_version": live_entry(performance, entry)["version"]},
            patron_headers(patron),
        ),
        "claim drawn win",
    )


def setup_claimed_winner(performance, allocation, patron,
                         execute_at="2026-09-12T09:05:00Z", quantity=1):
    """A single-entrant draw whose only entry wins, then a claim on it.

    Returns ``(entry, claimed_entry, purchase)``.
    """
    entries, _ = setup_drawn_allocation(performance, allocation, [patron],
                                        execute_at=execute_at)
    winning_entry = get_entry(performance, entries[0]["id"])
    claimed_entry = claim_entry(performance, allocation, patron, winning_entry,
                                quantity=quantity)
    return entries[0], claimed_entry, get_purchase(claimed_entry["purchase_id"])


def list_entries(performance):
    """Every draw entry filed against a performance, in one read."""
    data = _ok(api_client.list_draw_entries(performance["id"], CS,
                                            params={"limit": 100}),
               "list draw entries")
    return data.get("data", data) if isinstance(data, dict) else data


def get_entry(performance, entry_id):
    """Read one draw entry back from the performance's entry collection."""
    params = {"limit": 100}
    data = _ok(api_client.list_draw_entries(performance["id"], CS, params=params),
               "list draw entries")
    rows = data.get("data", data) if isinstance(data, dict) else data
    for row in rows:
        if row.get("id") == entry_id:
            return row
    pytest.fail(f"Setup failed: draw entry {entry_id} not found in listing")


# --------------------------------------------------------------------------
# Tier 3 — money movement lifecycles
# --------------------------------------------------------------------------

def open_refund(purchase, patron, reason_code="PATRON_REQUEST"):
    return _ok(
        api_client.create_refund_request(
            purchase["id"],
            {"reason_code": reason_code,
             "expected_purchase_version": get_purchase(purchase["id"])["version"]},
            patron_headers(patron),
        ),
        "open refund request",
    )


def approve_refund(refund, purchase, decision="APPROVE"):
    return _ok(
        api_client.approve_refund(
            refund["id"],
            {"decision": decision,
             "expected_purchase_version": get_purchase(purchase["id"])["version"]},
            CS,
        ),
        f"{decision} refund request",
    )


def settle_refund(refund, purchase):
    return _ok(
        api_client.settle_refund(
            refund["id"],
            {"expected_purchase_version": get_purchase(purchase["id"])["version"]},
            FIN,
        ),
        "settle refund",
    )


def setup_settled_purchase(performance, allocation, patron, quantity=2,
                           idempotency_key=None):
    """A patron with one fully settled order against a RELEASED allocation.

    Returns the settled purchase.
    """
    _, purchase = setup_buyer(performance, allocation, quantity=quantity,
                              idempotency_key=idempotency_key)
    return settle_purchase(purchase)


def setup_refund_ready(purchase):
    """Open and approve a refund so it sits in PROCESSING with money in flight."""
    refund = open_refund(purchase, {"id": purchase["patron_id"]})
    approve_refund(refund, purchase)
    return refund


def open_exchange(purchase, patron, target_allocation, original_amount_cents):
    return _ok(
        api_client.create_exchange_request(
            purchase["id"],
            {"target_allocation_id": target_allocation["id"],
             "original_amount_cents": original_amount_cents,
             "expected_purchase_version": get_purchase(purchase["id"])["version"]},
            patron_headers(patron),
        ),
        "open exchange request",
    )


def quote_exchange(exchange, purchase):
    return _ok(
        api_client.quote_exchange(
            exchange["id"],
            {"expected_purchase_version": get_purchase(purchase["id"])["version"]},
            CS,
        ),
        "quote exchange",
    )


def approve_exchange(exchange, purchase, decision="APPROVE"):
    return _ok(
        api_client.approve_exchange(
            exchange["id"],
            {"decision": decision,
             "expected_purchase_version": get_purchase(purchase["id"])["version"]},
            CS,
        ),
        f"{decision} exchange",
    )


def apply_exchange(exchange, purchase, performance):
    """Apply an approved exchange; both OCC versions are re-read live."""
    return _ok(
        api_client.apply_exchange(
            exchange["id"],
            {"expected_purchase_version": get_purchase(purchase["id"])["version"],
             "expected_performance_version": live_performance(performance)["version"]},
            CS,
        ),
        "apply exchange",
    )


def setup_quoted_exchange(performance, source_allocation, target_allocation,
                          patron, original_amount_cents, quantity=2):
    """A settled order on the source allocation carrying a QUOTED exchange onto
    the target allocation.

    Returns ``(purchase, exchange)`` with the post-quotation state of both.
    """
    purchase = setup_settled_purchase(performance, source_allocation, patron,
                                      quantity=quantity)
    exchange = open_exchange(purchase, patron, target_allocation,
                             original_amount_cents)
    quote_exchange(exchange, purchase)
    return get_purchase(purchase["id"]), exchange


# --------------------------------------------------------------------------
# Desk handoff, blocking and terminal lifecycles
# --------------------------------------------------------------------------

def setup_desk_market(market_code="LDN", city="London", desk_code="LDN-W1",
                      daily_capacity=3, handoff_model="CONCIERGE_DESK",
                      starts_at="2026-10-05T19:00:00Z"):
    """A concierge market with its first desk, an active partnership and an
    on-sale performance carrying one RELEASED allocation.

    Returns ``(market, production, performance, allocation, desk_code)``.
    """
    set_clock(BASE_CLOCK)
    market = declare_market(market_code=market_code, city=city,
                            handoff_model=handoff_model, desk_code=desk_code,
                            daily_capacity=daily_capacity)
    production = activate_production(register_production())
    performance = schedule_performance(production, market_code=market_code,
                                       starts_at=starts_at)
    performance = move_performance(performance, "ONSALE")
    allocation = release_allocation(
        schedule_allocation(add_allocation(performance, per_order_limit=4),
                            performance),
        production, performance,
    )
    return market, production, performance, allocation, desk_code


def setup_saturated_desk(daily_capacity=1, quantity=2):
    """A concierge desk driven to its daily capacity, plus a second settled
    purchase that still needs a handoff.

    Returns ``(verified_purchase, pending_purchase, desk_code)``.
    """
    market, production, performance, allocation, desk_code = setup_desk_market(
        daily_capacity=daily_capacity, handoff_model="CONCIERGE_DESK")
    _, first = setup_buyer(performance, allocation, quantity=quantity,
                           email=f"desk_first_{allocation['id'][:6]}@x.com",
                           idempotency_key="desk-first")
    first = settle_purchase(first)
    _, second = setup_buyer(performance, allocation, quantity=quantity,
                            email=f"desk_second_{allocation['id'][:6]}@x.com",
                            idempotency_key="desk-second")
    second = settle_purchase(second)
    # The verification is the last act, because an operational epoch resets a
    # saturated desk and the buyers' admissions run one.
    create_handoff(first, desk_code, first["handoff_token"])
    return get_purchase(first["id"]), get_purchase(second["id"]), desk_code


def setup_concierge_purchase(quantity=2, market_code="LDN",
                             desk_code="LDN-W1", daily_capacity=3,
                             handoff_model="CONCIERGE_DESK"):
    """A settled concierge purchase carrying a server-issued handoff token.

    ``setup_desk_market`` declares the market it needs itself, so the returned
    market is discarded. Returns ``(purchase, desk_code, patron)``.
    """
    _, production, performance, allocation, desk_code = setup_desk_market(
        market_code=market_code, desk_code=desk_code,
        daily_capacity=daily_capacity, handoff_model=handoff_model,
    )
    patron, purchase = setup_buyer(performance, allocation, quantity=quantity)
    return settle_purchase(purchase), desk_code, patron


def create_handoff(purchase, desk_code, redemption_code, idempotency_key=None):
    payload = f.handoff_payload(purchase["id"], desk_code, redemption_code)
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    return _ok(api_client.create_handoff(payload, DESK), "record desk handoff")


def block_patron(patron):
    return _ok(
        api_client.transition_patron(
            patron["id"],
            {"to_status": "BLOCKED",
             "expected_patron_version": get_patron(patron)["version"]},
            CS,
        ),
        "block patron",
    )


def cancel_performance(performance):
    return _ok(
        api_client.transition_performance(
            performance["id"],
            {"to_status": "CANCELLED",
             "expected_performance_version": live_performance(performance)["version"]},
            OPS,
        ),
        "cancel performance",
    )


def close_performance(performance):
    return _ok(
        api_client.transition_performance(
            performance["id"],
            {"to_status": "CLOSED",
             "expected_performance_version": live_performance(performance)["version"]},
            OPS,
        ),
        "close performance",
    )


def suspend_production(production, reason="PRODUCER_HOLD"):
    return _ok(
        api_client.transition_production(
            production["id"],
            {"to_status": "SUSPENDED", "suspension_reason": reason,
             "expected_production_version": live_production(production)["version"]},
            OPS,
        ),
        "suspend production",
    )


def place_seat_hold(performance, allocation, seat_label,
                    hold_kind="ALLOCATION", origin_ref=None):
    payload = f.seat_hold_payload(allocation["id"], seat_label,
                                  hold_kind=hold_kind)
    if origin_ref is not None:
        payload["origin_ref"] = origin_ref
    return _ok(api_client.create_seat_hold(performance["id"], payload, COORD),
               f"place {hold_kind} hold on {seat_label}")


# --------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# --------------------------------------------------------------------------

def setup_failed_handoff(purchase, desk_code, wrong_code="000000",
                         idempotency_key=None):
    """Record the single permitted failed handoff attempt against a purchase.

    Returns the purchase in its FAILED posture.
    """
    attempt = api_client.create_handoff(
        f.handoff_payload(purchase["id"], desk_code, wrong_code,
                          idempotency_key=idempotency_key),
        DESK,
    )
    if attempt.status_code >= 300:
        assert attempt.json()["data"]["error_id"] == "ERR_HANDOFF_TOKEN_INVALID", (
            f"a wrong token is a recorded failure, got {attempt.text[:300]}"
        )
    return get_purchase(purchase["id"])


def setup_processing_refund(performance, allocation, patron, quantity=2,
                            reason_code="PATRON_REQUEST"):
    """A settled order with a refund approved into PROCESSING.

    Returns ``(purchase, refund)``.
    """
    purchase = setup_settled_purchase(performance, allocation, patron,
                                      quantity=quantity)
    refund = open_refund(purchase, patron, reason_code=reason_code)
    approve_refund(refund, purchase)
    return get_purchase(purchase["id"]), refund


# --------------------------------------------------------------------------
# Tier 5 — finalization and terminal inventory states
# --------------------------------------------------------------------------

def setup_closed_allocation(**kwargs):
    """An allocation driven to its terminal CLOSED state by a cancelled
    performance.

    Returns ``(production, performance, allocation)``.
    """
    production, performance, allocation = setup_released_allocation(**kwargs)
    cancel_performance(performance)
    return production, get_performance(performance["id"]), \
        get_allocation(performance, allocation["id"])


def setup_lapsed_admission(performance, allocation, patron):
    """An admission whose twenty minute window has already passed."""
    position = join_queue(performance, allocation, patron)
    ops_run("2026-09-12T09:05:00Z")
    set_clock("2026-09-12T09:40:00Z")
    ops_run("2026-09-12T09:40:00Z")
    return position


# --------------------------------------------------------------------------
# Composite scenarios behind the depth index's hardest setups
# --------------------------------------------------------------------------

def setup_premium_allocation_with_decoy_purchase(
        face_value_cents=19990, discount_pct=0.05, daily_quantity=11,
        per_order_limit=3, total_seat_capacity=30):
    """A RELEASED RUSH_PREMIUM allocation opening eleven seats on an unsold epoch,
    with one admitted buyer ready to order against it.

    The single-seat order the caller places takes the epoch to ten seats still
    unsold of eleven released — a released-but-off fraction of 0.909, which the
    strict greater-than clears and which contributes 1500 basis points. The order
    book stays at one, so the order-book surcharge does not fire, and the fill
    fraction of 0.09 clears nothing, leaving the released-but-off fraction as the
    only condition in play. Returns
    ``(production, performance, allocation, patron, buyer_headers, orders)``.
    """
    production, performance, allocation = setup_released_allocation(
        face_value_cents=face_value_cents, total_seat_capacity=total_seat_capacity,
        ticket_type="RUSH_PREMIUM", daily_quantity=daily_quantity,
        discount_pct=discount_pct, refundable=True, per_order_limit=per_order_limit,
    )
    buyer = register_patron(email=f"decoy_buyer_{allocation['id'][:8]}@x.com")
    admit_patron(performance, allocation, buyer)
    return production, performance, allocation, buyer, patron_headers(buyer), []


def setup_refund_variant_purchase(face_value_cents=19990, discount_pct=0.15,
                                  quantity=4, per_order_limit=4,
                                  daily_quantity=11):
    """A settled four-ticket order inside the production's refund window.

    RUSH_PREMIUM forestalls a demand surge entirely, so the surcharge the design's
    "surge 2500 bp" step would have applied is zero here. The production's cost
    figures are unaffected by the base each one is derived from. Returns
    ``(production, performance, allocation, patron, purchase)``.
    """
    production, performance, allocation = setup_released_allocation(
        face_value_cents=face_value_cents, ticket_type="RUSH",
        daily_quantity=daily_quantity, discount_pct=discount_pct,
        refundable=True, per_order_limit=per_order_limit,
        starts_at="2026-11-05T19:00:00Z",
    )
    patron = register_patron(email=f"refund_variant_{allocation['id'][:8]}@x.com")
    admit_patron(performance, allocation, patron)
    purchase = buy_seats(performance, allocation, patron, quantity=quantity,
                         idempotency_key=f"refund-variant-{allocation['id'][:8]}")
    purchase = settle_purchase(purchase)
    return production, performance, allocation, patron, purchase


def setup_seven_seat_house_rush(daily_quantity=8, total_seat_capacity=7):
    """A SCHEDULED rush allocation on a house of seven seats, released once.

    The market term is the binding operand of the release ceiling here.
    Returns ``(production, performance, allocation, release_response)``.
    """
    production, performance, allocation = setup_scheduled_allocation(
        total_seat_capacity=total_seat_capacity, face_value_cents=19990,
        daily_quantity=daily_quantity, discount_pct=0.5, refundable=True,
        per_order_limit=2,
    )
    released = release_allocation(allocation, production, performance)
    return production, performance, allocation, released


def setup_four_seat_rush_order(face_value_cents=16770, discount_pct=0.5,
                               daily_quantity=11, per_order_limit=4):
    """A single four-seat order on a released rush allocation, taken while the
    epoch is entirely unsold.

    The opening state is exactly the state the pinned subtotal example describes:
    a face value of 16770 and a discount of 0.5 put the discounted base at 8385,
    which is the unit price the example names, and a RUSH allocation carries no
    demand surge, so the base is charged unchanged. Extending it and discounting
    the product gives the pinned subtotal, while discounting the unit first gives
    the reordered figure two cents higher. Returns
    ``(production, performance, allocation, patron, purchase)``.
    """
    production, performance, allocation = setup_released_allocation(
        face_value_cents=face_value_cents, ticket_type="RUSH",
        daily_quantity=daily_quantity, discount_pct=discount_pct,
        refundable=True, per_order_limit=per_order_limit,
    )
    patron = register_patron(email=f"subtotal_{allocation['id'][:8]}@x.com")
    admit_patron(performance, allocation, patron)
    purchase = buy_seats(performance, allocation, patron, quantity=4,
                         idempotency_key=f"subtotal-{allocation['id'][:8]}")
    return production, performance, allocation, patron, purchase


def setup_three_entrant_draw(daily_quantity=2, waitlist_multiplier=2,
                             claim_window_minutes=30):
    """Three entrants filed in order against a RELEASED DRAW allocation, then
    drawn at 09:05 with an explicit clock move.

    Returns
    ``(production, performance, allocation, patrons, entries, execution)``.
    """
    production, performance, allocation = setup_released_draw_allocation(
        daily_quantity=daily_quantity, waitlist_multiplier=waitlist_multiplier,
        claim_window_minutes=claim_window_minutes,
    )
    patrons = [register_patron(email=f"draw{i}_{allocation['id'][:6]}@x.com")
               for i in range(1, 4)]
    entries = [file_draw_entry(performance, allocation, patron)
               for patron in patrons]
    execution = execute_draw(allocation, at="2026-09-12T09:05:00Z")
    return production, performance, allocation, patrons, entries, execution


def setup_parallel_dimension_purchase(face_value_cents=10000, discount_pct=0.5,
                                      daily_quantity=6, per_order_limit=2):
    """A purchase on a release whose every created seat label the platform
    already holds through a BOX_OFFICE hold.

    Returns ``(production, performance, allocation, patron, purchase)``.
    """
    production, performance, allocation = setup_released_allocation(
        face_value_cents=face_value_cents, ticket_type="RUSH",
        daily_quantity=daily_quantity, discount_pct=discount_pct,
        refundable=True, per_order_limit=per_order_limit,
    )
    for label in ordered_pass_labels(12):
        place_seat_hold(performance, allocation, label, hold_kind="BOX_OFFICE",
                        origin_ref=f"BO-{label}")
    patron = register_patron(email=f"parallel_{allocation['id'][:8]}@x.com",
                             market_code=performance["market_code"])
    admit_patron(performance, allocation, patron)
    purchase = buy_seats(performance, allocation, patron, quantity=2,
                         idempotency_key=f"parallel-{allocation['id'][:8]}")
    return production, performance, allocation, patron, purchase


def setup_suspension_cascade(face_value_cents=10000, daily_quantity=6):
    """An ACTIVE partnership whose RELEASED allocation, held inventory and two
    waiting queue positions are all live when the partnership is suspended.

    Returns ``(production, performance, allocation, hold, positions)``.
    """
    production, performance, allocation = setup_released_allocation(
        face_value_cents=face_value_cents, ticket_type="RUSH",
        daily_quantity=daily_quantity, discount_pct=0.5, refundable=True,
        per_order_limit=2,
    )
    hold = place_seat_hold(performance, allocation, "ORCH-B-4",
                           hold_kind="ALLOCATION")
    patrons = [register_patron(email=f"cascade{i}_{allocation['id'][:6]}@x.com")
               for i in range(1, 3)]
    positions = [join_queue(performance, allocation, patron)
                 for patron in patrons]
    return production, performance, allocation, hold, positions


def setup_single_seat_draw(claim_window_minutes=1):
    """A DRAW allocation granting exactly one seat, entered by one patron and
    drawn. Returns ``(production, performance, allocation, patron, entry)``.
    """
    production, performance, allocation = setup_released_draw_allocation(
        daily_quantity=1, claim_window_minutes=claim_window_minutes,
        waitlist_multiplier=0, per_order_limit=1,
    )
    patron = register_patron(email=f"forfeit_{allocation['id'][:8]}@x.com")
    entry = file_draw_entry(performance, allocation, patron)
    execute_draw(allocation, at="2026-09-12T09:05:00Z")
    return production, performance, allocation, patron, entry


def setup_lapsed_and_live_entries(claim_window_minutes=1):
    """One patron holding two draw entries on the same performance: the first has
    lapsed into a forfeiture, raising the recorded violation that makes a block
    lawful, and the second is still sitting in `ENTERED` for the same allocation's
    sibling draw, so it is the entry a block has left to withdraw.

    Two separate DRAW allocations are needed because the one-entry-per-draw rule
    is per allocation: a patron whose only entry has forfeited cannot file a
    second one against the same draw. Both allocations belong to the one
    performance, which is what the entry endpoint requires.

    Returns ``(production, performance, lapsed_allocation, live_allocation,
    lapsed_patron, lapsed_entry, live_entry)``.
    """
    production, performance, lapsed_allocation = setup_released_draw_allocation(
        daily_quantity=1, claim_window_minutes=claim_window_minutes,
        waitlist_multiplier=0, per_order_limit=1,
    )
    live_allocation = release_allocation(
        schedule_allocation(add_allocation(performance, ticket_type="DRAW",
                                           daily_quantity=1,
                                           claim_window_minutes=claim_window_minutes,
                                           winner_basis_points=10000,
                                           waitlist_multiplier=0,
                                           per_order_limit=1),
                            performance),
        production, performance,
    )
    lapsed = register_patron(email=f"forfeit_{lapsed_allocation['id'][:8]}@x.com")
    entry = file_draw_entry(performance, lapsed_allocation, lapsed)
    execute_draw(lapsed_allocation, performance, at="2026-09-12T09:05:00Z")
    set_clock("2026-09-12T09:10:00Z")
    ops_run("2026-09-12T09:10:00Z")
    live_entry = file_draw_entry(performance, live_allocation, lapsed)
    return (production, performance, lapsed_allocation, live_allocation,
            lapsed, entry, live_entry)


def setup_blocked_draw_entrant(claim_window_minutes=60):
    """A single-entrant draw whose only entrant carries the recorded violation
    that makes a block lawful, so the block cascade may be exercised.

    PRD §3.8: "a patron carrying even one recorded violation is eligible to be
    blocked". The patron's count is raised by a genuine forfeiture before the
    block is attempted, because the violation count is recomputed from the
    patron's entry states and the block transition is gated on it.

    Returns ``(production, performance, allocation, entrant, entry)``.
    """
    production, performance, allocation = setup_released_draw_allocation(
        daily_quantity=1, claim_window_minutes=claim_window_minutes,
        waitlist_multiplier=0, per_order_limit=1,
    )
    entrant = register_patron(email=f"blockcascade_{allocation['id'][:8]}@x.com")
    entry = file_draw_entry(performance, allocation, entrant)
    execute_draw(allocation, at="2026-09-12T09:05:00Z")
    # Reach the notification's claim deadline without running the sweep that would
    # otherwise forfeit the win and record the forfeiture the same way.
    deadline = get_entry(performance, entry["id"])["claim_deadline_at"]
    late = parse_iso(deadline) + timedelta(minutes=5)
    set_clock(late.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    return production, performance, allocation, entrant, entry


def setup_blocked_draw_pool(claim_window_minutes=60):
    """A draw whose only entrant has already been blocked, so the entry the
    block withdrew is the whole entry field.

    Returns ``(production, performance, allocation, entrant, entry)``.
    """
    production, performance, allocation, entrant, entry = setup_blocked_draw_entrant(
        claim_window_minutes=claim_window_minutes
    )
    blocked = block_patron(get_patron(entrant))
    assert blocked["status"] == "BLOCKED", (
        "the entrant's recorded violation makes the block lawful, got "
        f"{blocked['status']}"
    )
    return production, performance, allocation, entrant, entry


def setup_forfeit_raised_violation(claim_window_minutes=1):
    """A draw whose single winner lapses unclaimed, raising that patron's
    recorded violation count to the blocking threshold.

    Returns
    ``(production, performance, allocation, lapsed_patron, unrelated_patron, entry)``.
    """
    production, performance, allocation = setup_released_draw_allocation(
        daily_quantity=1, claim_window_minutes=claim_window_minutes,
        waitlist_multiplier=0, per_order_limit=1,
    )
    lapsed = register_patron(email=f"forfeit_{allocation['id'][:8]}@x.com")
    entry = file_draw_entry(performance, allocation, lapsed)
    execute_draw(allocation, at="2026-09-12T09:05:00Z")
    set_clock("2026-09-12T09:10:00Z")
    ops_run("2026-09-12T09:10:00Z")
    unrelated = register_patron(email=f"unrelated_{allocation['id'][:8]}@x.com")
    return production, performance, allocation, lapsed, unrelated, entry


def setup_adjacent_order_run():
    """A first two-seat order occupying a contiguous run, with a second patron
    admitted and ready to buy the run that immediately follows it.

    Returns ``(production, performance, allocation, first_purchase, second_patron,
    first_seats)``.
    """
    production, performance, allocation, first_buyer, purchase, seats, second, _ = \
        setup_two_hold_blocks()
    return production, performance, allocation, purchase, second, seats


def setup_unknown_performance_id():
    """The identifier used wherever a path segment must resolve to nothing."""
    return "00000000-0000-4000-8000-000000000000"


# --------------------------------------------------------------------------
# Seat label helpers
# --------------------------------------------------------------------------

def ordered_pass_labels(count, prefix="ORCH-A-"):
    """A run of ordered seat labels wide enough for the platform's own holds."""
    return [f"{prefix}{index}" for index in range(count, count * 2)]


def contiguous_labels(start=1, count=2, prefix="ORCH-A-"):
    """A contiguous run of seat labels starting at ``start``."""
    return [f"{prefix}{index}" for index in range(start, start + count)]


def setup_two_settled_orders(face_value_cents=10000, daily_quantity=6,
                             per_order_limit=2):
    """Two patrons who each bought and had delivered a settled order.

    Returns ``(production, performance, allocation, pairs)`` where each pair is
    ``(patron, purchase)``.
    """
    production, performance, allocation = setup_released_allocation(
        face_value_cents=face_value_cents, ticket_type="RUSH",
        daily_quantity=daily_quantity, discount_pct=0.5, refundable=True,
        per_order_limit=per_order_limit,
    )
    first = register_patron(email=f"pair_one_{allocation['id'][:6]}@x.com")
    join_queue(performance, allocation, first)
    ops_run("2026-09-12T09:05:00Z")
    p_one = settle_purchase(buy_seats(performance, allocation, first, quantity=2,
                                      idempotency_key="pair-1"))
    second = register_patron(email=f"pair_two_{allocation['id'][:6]}@x.com")
    join_queue(performance, allocation, second)
    ops_run("2026-09-12T09:10:00Z")
    p_two = settle_purchase(buy_seats(performance, allocation, second, quantity=2,
                                      idempotency_key="pair-2"))
    return production, performance, allocation, [(first, p_one), (second, p_two)]


def setup_stale_release_versions():
    """A SCHEDULED allocation whose live production version differs from the
    version observed before activation advanced the production.

    Returns
    ``(production, performance, allocation, stale_version, live_version)``.
    """
    set_clock(BASE_CLOCK)
    market = declare_market()
    created = register_production()
    observed_version = created["version"]
    production = activate_production(created)
    performance = move_performance(
        schedule_performance(production), "ONSALE")
    allocation = schedule_allocation(add_allocation(performance))
    return production, performance, allocation, observed_version, production["version"]


def setup_stale_target_exchange(source_discount_pct=0.5, target_discount_pct=0.5,
                                quantity=2, starts_at="2026-09-12T20:00:00Z",
                                release_target=True):
    """A settled order on a RELEASED source allocation plus a target allocation
    of the same performance, with an exchange opened against the target and
    still REQUESTED.

    Both allocations are released for the same epoch: an exchange is only
    permitted between two allocations of the same performance, and an approved
    one on an unreleased target moves no seats. The performance starts eleven
    hours after the live clock, so the exchange sits in the production's fee band
    rather than in its free band. The recalled amount is the purchase's own paid
    figure, so the quotation will be permitted. Returns
    ``(production, performance, source, target, patron, purchase, exchange)``.
    """
    set_clock(BASE_CLOCK)
    market = declare_market()
    production = activate_production(
        register_production(exchange_fee_cents=500, exchange_allowed=True))
    performance = move_performance(
        schedule_performance(production, face_value_cents=10000,
                             starts_at=starts_at), "ONSALE")
    source = release_allocation(
        schedule_allocation(add_allocation(performance, daily_quantity=6,
                                           discount_pct=source_discount_pct,
                                           per_order_limit=2)),
        production, performance)
    target = schedule_allocation(add_allocation(
        performance, daily_quantity=6, discount_pct=target_discount_pct,
        per_order_limit=2), performance)
    if release_target:
        target = release_allocation(target, production, performance)
    patron, purchase = setup_buyer(performance, source, quantity=quantity,
                                   email=f"exchange_{source['id'][:8]}@x.com")
    purchase = settle_purchase(purchase)
    exchange = open_exchange(purchase, patron, target, purchase["subtotal_cents"])
    return (production, performance, source, target, patron,
            get_purchase(purchase["id"]), exchange)


def setup_approved_exchange(**kwargs):
    """The same chain walked through quotation and approval.

    Returns ``(production, performance, source, target, patron, purchase, exchange)``
    with the exchange APPROVED and the purchase read back at its live version.
    """
    production, performance, source, target, patron, purchase, exchange = \
        setup_stale_target_exchange(**kwargs)
    quoted = quote_exchange(exchange, purchase)
    approve_exchange(quoted, purchase)
    return (production, performance, source, target, patron,
            get_purchase(purchase["id"]), quoted)


def setup_sibling_market_cap_release(face_value_cents=10000,
                                     total_seat_capacity=25,
                                     first_quantity=6, second_quantity=8):
    """Two rush allocations on a twenty-five seat house. The first has already
    released; the second still waits on the market-wide ceiling.

    Returns ``(production, performance, first, second)``.
    """
    set_clock(BASE_CLOCK)
    market = declare_market()
    production = activate_production(register_production())
    performance = move_performance(
        schedule_performance(production, face_value_cents=face_value_cents,
                             total_seat_capacity=total_seat_capacity),
        "ONSALE")
    first = release_allocation(
        schedule_allocation(add_allocation(performance,
                                           daily_quantity=first_quantity,
                                           per_order_limit=2)),
        production, performance)
    second = schedule_allocation(add_allocation(performance,
                                                daily_quantity=second_quantity,
                                                discount_pct=0.4,
                                                per_order_limit=2))
    return production, performance, first, second


def setup_empty_epoch_then_release(daily_quantity=2):
    """An allocation released on 2026-09-11 with the whole of its grant left
    unsold, then released again a day later — the boundary at which the
    carry-forward operand, being ``daily_quantity`` minus the unsold remainder,
    is exactly zero rather than negative.

    PRD §3.3: "The system computes the difference between `daily_quantity` and the
    `quantity_carried_forward` the allocation brought into the epoch ... and
    floors that difference at zero. A carried-forward remainder larger than the
    daily grant therefore contributes zero rather than a negative candidate."

    Returns ``(production, performance, allocation, zero_cap_release)`` where the
    fourth element is the release response whose ceiling came out at zero.
    """
    set_clock(PREV_CLOCK)
    market = declare_market()
    production = activate_production(register_production())
    performance = move_performance(
        schedule_performance(production), "ONSALE")
    allocation = schedule_allocation(
        add_allocation(performance, daily_quantity=daily_quantity,
                       per_order_limit=daily_quantity),
        performance)
    first = release_allocation(allocation, production, performance,
                               epoch=PREV_CLOCK_DAY)
    assert first["quantity_released_today"] == daily_quantity, (
        "the opening epoch released the producer's whole grant, got "
        f"{first['quantity_released_today']}"
    )
    zero = release_allocation(allocation, production, performance,
                              epoch=BASE_CLOCK_DAY, advance_days=1)
    return production, performance, allocation, zero


def setup_unsold_then_sold_five_seat_epoch(face_value_cents=19990,
                                           total_seat_capacity=100,
                                           daily_quantity=5,
                                           per_order_limit=4):
    """One RUSH_PREMIUM allocation on a hundred seat house, released with
    nothing sold.

    The hundred seat house puts the market term out of the way, so the release
    ceiling is exactly ``daily_quantity``. The caller drives the orders, because
    the quantities that matter are the boundary quantities, and the single
    admitted patron is reused across them. Returns
    ``(production, performance, allocation, patron)``.
    """
    production, performance, allocation = setup_released_allocation(
        face_value_cents=face_value_cents, total_seat_capacity=total_seat_capacity,
        ticket_type="RUSH_PREMIUM", daily_quantity=daily_quantity,
        discount_pct=0.05, refundable=True, per_order_limit=per_order_limit,
    )
    patron = register_patron(email=f"surge_{allocation['id'][:8]}@x.com")
    admit_patron(performance, allocation, patron)
    return production, performance, allocation, patron


def setup_two_hold_blocks(second_buyer_email=None, run_second_order=False):
    """A first two-seat order occupying its own contiguous run on an allocation
    whose earlier labels the box office already holds, plus a second patron
    admitted and ready to buy alongside it.

    The box office holds the first two labels of the house, so the platform's own
    run starts after them; the second patron's order is placed against that same
    run, because that is the run an intersecting order would collide with.

    Returns ``(production, performance, allocation, buyer, purchase, seats,
    second_patron, second_order)`` where ``second_order`` is null unless
    ``run_second_order`` is set.
    """
    production, performance, allocation = setup_released_allocation(
        ticket_type="RUSH", daily_quantity=6, discount_pct=0.5, refundable=True,
        per_order_limit=2,
    )
    for label in contiguous_labels(1, 2, prefix="BOX-"):
        place_seat_hold(performance, allocation, label, hold_kind="BOX_OFFICE",
                        origin_ref=f"BO-{label}")
    buyer, purchase = setup_buyer(performance, allocation, quantity=2,
                                  email=f"block_{allocation['id'][:8]}@x.com",
                                  idempotency_key="block-1")
    purchase = settle_purchase(purchase)
    second = register_patron(email=second_buyer_email
                             or f"block2_{allocation['id'][:8]}@x.com")
    admit_patron(performance, allocation, second)
    second_order = None
    if run_second_order:
        second_order = buy_seats(performance, allocation, second, quantity=2,
                                 idempotency_key="block-2")
    return (production, performance, allocation, buyer, purchase,
            list(purchase["seat_labels"]), second, second_order)


def setup_two_allocation_holds(first_label="ORCH-E-1", second_label="ORCH-E-2"):
    """A STANDARD allocation with two ALLOCATION holds already recorded, ready
    for a box-office reconciliation.

    Returns ``(production, performance, allocation)``.
    """
    production, performance, allocation = setup_released_allocation(
        ticket_type="STANDARD", daily_quantity=4, discount_pct=0,
        refundable=True, per_order_limit=2,
    )
    for label in (first_label, second_label):
        place_seat_hold(performance, allocation, label, hold_kind="ALLOCATION")
    place_seat_hold(performance, allocation, "ORCH-E-3", hold_kind="BOX_OFFICE",
                    origin_ref="BO-E-3")
    return production, performance, allocation


def setup_queue_of_four(daily_quantity=5, capacity_ratio=None):
    """Four patrons in one performance's rush queue against a released cap of
    five. Returns ``(production, performance, allocation, patrons, positions)``.
    """
    production, performance, allocation = setup_released_allocation(
        ticket_type="RUSH", daily_quantity=daily_quantity, discount_pct=0.5,
        refundable=True, per_order_limit=2,
    )
    patrons = [register_patron(email=f"q{i}_{allocation['id'][:6]}@x.com")
               for i in range(1, 5)]
    positions = [join_queue(performance, allocation, patron)
                 for patron in patrons]
    return production, performance, allocation, patrons, positions


def setup_settled_then_sold_out(quantity=3, daily_quantity=8):
    """A settled order on a released rush allocation, with the allocation's
    counters ready for a refund cycle.

    Returns ``(production, performance, allocation, patron, purchase)``.
    """
    production, performance, allocation = setup_released_allocation(
        ticket_type="RUSH", daily_quantity=daily_quantity, discount_pct=0.5,
        refundable=True, per_order_limit=quantity,
    )
    patron = register_patron(email=f"invariant_{allocation['id'][:8]}@x.com")
    admit_patron(performance, allocation, patron)
    purchase = settle_purchase(
        buy_seats(performance, allocation, patron, quantity=quantity,
                  idempotency_key=f"invariant-{allocation['id'][:8]}"))
    return production, performance, allocation, patron, purchase