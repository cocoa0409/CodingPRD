"""
Composite setup helpers — editions, dispatch/deliver/correct, and the
savings-and-edition chains used by the cascade fixtures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import create_edition_payload
from .test_users import PRINT_OPS
from .constants import CLOCK_2026_09_30


# ─── Edition lifecycle actions ───────────────────────────────────────

def get_edition(edition_id):
    """Read one edition."""
    return get_success_data(api_client.get_edition(edition_id, PRINT_OPS))


def dispatch_edition(edition_id):
    """Dispatch an edition from its press run."""
    return get_success_data(api_client.dispatch_edition(edition_id, PRINT_OPS))


def dispatch_edition_response(edition_id):
    """Dispatch an edition and return the raw Response (for error paths)."""
    return api_client.dispatch_edition(edition_id, PRINT_OPS)


def revert_edition_to_digital(edition_id):
    """Revert a late edition to digital-only delivery."""
    return get_success_data(api_client.revert_edition_to_digital(edition_id, PRINT_OPS))


def revert_edition_to_digital_response(edition_id):
    """Revert an edition and return the raw Response."""
    return api_client.revert_edition_to_digital(edition_id, PRINT_OPS)


def deliver_edition(edition_id):
    """Record that a dispatched edition reached its market."""
    return get_success_data(api_client.deliver_edition(edition_id, PRINT_OPS))


def deliver_edition_response(edition_id):
    """Record delivery and return the raw Response."""
    return api_client.deliver_edition(edition_id, PRINT_OPS)


def correct_edition(edition_id):
    """Open a correction on a delivered edition carrying legal notices."""
    return get_success_data(api_client.correct_edition(edition_id, PRINT_OPS))


def correct_edition_response(edition_id):
    """Open a correction and return the raw Response."""
    return api_client.correct_edition(edition_id, PRINT_OPS)


def list_site_editions(site_id):
    """List the editions printed by a site."""
    return get_success_data(api_client.list_site_editions(site_id, PRINT_OPS))


def list_market_editions(market_id):
    """List a market's editions."""
    return get_success_data(api_client.list_market_editions(market_id, PRINT_OPS))


# ─── Dispatch-path builders ──────────────────────────────────────────

def create_late_edition(market_id, site_id, slug="2026-09-21", page_count=12,
                        requested_copies=40000, late_sports=True,
                        legal_notice_count=0):
    """Create an edition that is late against the pinned 05:30 deadline.

    Returns the edition dict (status in_production). Dispatch it to reach
    late_dispatch.
    """
    return get_success_data(api_client.create_edition(
        market_id,
        create_edition_payload(
            site_id,
            slug=slug,
            page_count=page_count,
            requested_print_run_copies=requested_copies,
            late_sports_engineering_flag=late_sports,
            legal_notice_count=legal_notice_count,
        ),
        PRINT_OPS))


def create_on_time_edition(market_id, site_id, slug="2026-09-21",
                           requested_copies=40000, legal_notice_count=0):
    """Create an 8-page edition that still clears the pinned deadline."""
    return get_success_data(api_client.create_edition(
        market_id,
        create_edition_payload(
            site_id,
            slug=slug,
            page_count=8,
            requested_print_run_copies=requested_copies,
            late_sports_engineering_flag=False,
            legal_notice_count=legal_notice_count,
        ),
        PRINT_OPS))


def setup_delivered_edition(market_id, site_id, slug="2026-09-21",
                            page_count=12, requested_copies=40000,
                            late_sports=False, legal_notice_count=0):
    """Create + dispatch + deliver an edition. Returns the delivered edition.

    An on-time edition reaches on_time_dispatch directly; a late one takes the
    late_dispatch path first, which is what the correction and penalty tests need.
    """
    edition = get_success_data(api_client.create_edition(
        market_id,
        create_edition_payload(
            site_id,
            slug=slug,
            page_count=page_count,
            requested_print_run_copies=requested_copies,
            late_sports_engineering_flag=late_sports,
            legal_notice_count=legal_notice_count,
        ),
        PRINT_OPS))
    edition = get_success_data(api_client.dispatch_edition(edition["id"], PRINT_OPS))
    edition = get_success_data(api_client.deliver_edition(edition["id"], PRINT_OPS))
    return edition


# ─── Site savings-window + closure chains ────────────────────────────

def setup_site_with_savings_window(observed_days=15, charge_cents=10000,
                                   zero_days=13, clock=CLOCK_2026_09_30,
                                   site_overrides=None):
    """Clock + hub + site KOT with a seeded savings window.

    The pinned window: 15 observed days at 10000 cents plus recorded zero days,
    which yields annualized 480000.00 / realized 330000.00 / divergence 150000.00.
    Returns (hub, site).
    """
    from .fixtures import create_hub_with_clock, create_site

    hub = create_hub_with_clock(clock)
    site = create_site(hub["id"], **(site_overrides or {}))
    day = 1
    for _ in range(observed_days):
        get_success_data(api_client.record_print_volume(
            {"print_site_id": site["id"], "day": f"2026-09-{day:02d}",
             "charge_cents": charge_cents}, PRINT_OPS))
        day += 1
    for _ in range(zero_days):
        get_success_data(api_client.record_print_volume(
            {"print_site_id": site["id"], "day": f"2026-09-{day:02d}",
             "charge_cents": 0}, PRINT_OPS))
        day += 1
    return hub, get_success_data(api_client.get_print_site(site["id"], PRINT_OPS))


def setup_site_planned_for_closure(clock=CLOCK_2026_09_30, market_overrides=None,
                                   route_overrides=None, site_overrides=None):
    """Chain through a succeeded plan-transfer, ready for a site closure.

    Returns (hub, site, region, market, route).
    """
    from .fixtures_market import setup_market_planned_on_site
    return setup_market_planned_on_site(
        clock=clock,
        market_overrides=market_overrides,
        route_overrides=route_overrides,
    )


def setup_hub_ready_for_suspension(clock=CLOCK_2026_09_30,
                                   market_overrides=None,
                                   route_overrides=None):
    """Hub with one market withdrawn and its route drained, ready for a close.

    Withdrawing the only market orphans the site's routes through the cascade
    that termination seeds. Returns (hub, site, region, market, route, contractor,
    delivery_route, stop).
    """
    from .fixtures_market import setup_market_with_cascade_chain, plan_transfer

    hub, site, region, market, route, contractor, delivery_route, stop = (
        setup_market_with_cascade_chain(
            market_overrides=market_overrides,
            route_overrides=route_overrides,
            clock=clock,
        ))
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    get_success_data(api_client.terminate_contractor(contractor["id"], PRINT_OPS))
    return hub, site, region, market, route, contractor, delivery_route, stop