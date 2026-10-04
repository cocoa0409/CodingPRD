"""Corner queue B — section: state_machines.

Invalid transitions, terminal-state lockdown, initial states and the hub's derived
press posture.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_hub_with_clock,
    create_site,
    create_region,
    create_market,
    create_route,
    create_contractor,
    create_delivery_route,
    create_edition,
    plan_transfer,
    terminate_contractor,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_01, CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]


def test_edition_dispatch_from_delivered_is_rejected_as_invalid_transition():
    """PRD §3.5: "Recording that a dispatched edition reached its market moves it
    from either `late_dispatch` or `on_time_dispatch` to `delivered_market`".
    PRD §2.11: "The cascade is: request shape first, then identity, then
    authorization and segregation of duties, then path existence, then
    body-reference existence, then lifecycle state, then regulatory safety, then
    referential integrity, then business constraints, then temporal rules, and
    finally fiscal ceilings."

    Design: Corner/state_machines/edition_dispatch_from_delivered_is_rejected_as_invalid_transition
    """
    hub, site, region, market, route = _planned_market(CLOCK_2026_09_01)
    # A late dispatch is the only way into `delivered_market` before the market's
    # delivery run completes, so the edition is sized to miss the deadline.
    edition = create_edition(market["id"], site["id"], slug="2026-09-21",
                             page_count=12, requested_print_run_copies=180000,
                             late_sports_engineering_flag=True)
    validate_success(api.dispatch_edition(edition["id"], PRINT_OPS), 200)
    validate_success(api.deliver_edition(edition["id"], PRINT_OPS), 200)

    response = api.dispatch_edition(edition["id"], PRINT_OPS)

    error = validate_error(response, "ERR_INVALID_STATE")
    assert response.status_code == 409
    assert error["error_id"] == "ERR_INVALID_STATE"
    unchanged = validate_success(api.get_edition(edition["id"], PRINT_OPS), 200)
    assert unchanged["status"] == "delivered_market", (
        "the refused dispatch must not move the edition"
    )


def test_delivery_contractor_terminated_is_a_terminal_lockdown():
    """PRD §3.3: "Two refusals guard this area: reinstating a `terminated`
    contractor, or creating a new route under it, is refused with
    `ERR_CONTRACTOR_TERMINAL` (HTTP 409)".
    PRD §3.3: "Termination is terminal: it requires the contractor to be `active`
    or `suspended` and to have no route still `prepared`."

    Design: Corner/state_machines/delivery_contractor_terminated_is_a_terminal_lockdown
    """
    hub, site, region, market, route = _planned_market(CLOCK_2026_09_01)
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    create_edition(market["id"], site["id"], slug="2026-09-20", page_count=12,
                   requested_print_run_copies=28000)
    validate_success(
        api.cost_run(delivery_route["id"], {"run_date": "2026-09-20"}, DELIVERY), 200)

    terminated = validate_success(api.terminate_contractor(contractor["id"], DELIVERY), 200)
    assert terminated["status"] == "terminated"

    response = api.reinstate_contractor(contractor["id"], DELIVERY)

    error = validate_error(response, "ERR_CONTRACTOR_TERMINAL")
    assert response.status_code == 409
    assert error["error_id"] == "ERR_CONTRACTOR_TERMINAL"
    unchanged = validate_success(api.get_contractor(contractor["id"], DELIVERY), 200)
    assert unchanged["status"] == "terminated", (
        "the lockdown is by state, not by action"
    )


def test_new_print_site_starts_in_active_status():
    """PRD §3.1: "A site also declares how many `distinct_shifts_per_night` it runs".
    PRD §3.3: "A route begins `prepared`."
    PRD §3.2: "A new market begins `active` with its `frequency_change_status`
    dimension `none`".

    Design: Corner/state_machines/new_print_site_starts_in_active_status
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], name="Riverton")
    route = create_route(site["id"], market["id"])

    assert site["status"] == "active"
    assert route["status"] == "eligible"
    assert market["status"] == "active"
    assert market["frequency_change_status"] == "none"

    fetched_site = validate_success(api.get_print_site(site["id"], PRINT_OPS), 200)
    fetched_market = validate_success(api.get_print_market(market["id"], PRINT_OPS), 200)
    assert fetched_site["status"] == "active"
    assert fetched_market["status"] == "active"
    assert fetched_market["frequency_change_status"] == "none"


def test_hub_press_posture_is_derived_from_member_sites():
    """PRD §2.10: "It is `OPEN` while no member site is `closing` and none is
    `closed`; it becomes `RESTRICTED` as soon as at least one member site is
    `closing` and not all of them are `closed`".
    PRD §3.1: "marks every market that had selected one of those routes as needing
    reassignment, recomputes those markets' transfer ledger (§3.2), and recomputes
    the hub's `press_posture`, which in the ordinary case becomes `RESTRICTED`."

    Design: Corner/state_machines/hub_press_posture_is_derived_from_member_sites
    """
    hub, site, region, market, route = _planned_market(CLOCK_2026_09_01)
    create_edition(market["id"], site["id"], slug="2026-09-21", page_count=8,
                   requested_print_run_copies=1000)

    before = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)
    assert before["press_posture"] == "OPEN", (
        f"no member site is closing yet, got {before['press_posture']}"
    )

    closed = validate_success(api.plan_site_closure(site["id"], PRINT_OPS), 200)
    after = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)

    assert closed["status"] == "closing"
    assert after["press_posture"] == "RESTRICTED", (
        f"one member site closing with none closed is RESTRICTED, got "
        f"{after['press_posture']}"
    )
    assert after["legal_notice_block"] is False, (
        "the only market is still on time, so no block is set"
    )


def _planned_market(clock):
    hub = create_hub_with_clock(clock)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], guaranteed_floor_copies=8000,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30,
                           single_copy_market_rule="carrier")
    route = create_route(site["id"], market["id"])
    version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    validate_success(
        api.plan_market_transfer(
            market["id"],
            {"receiving_print_site_id": site["id"], "expected_hub_version": version},
            PRINT_OPS),
        200,
    )
    return hub, site, region, market, route