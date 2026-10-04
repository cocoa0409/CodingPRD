"""Difficulty queue A — cross_entity_state_dependency across three entity pairs.

Each instance makes a previously-valid request fail purely because a *different*
entity moved, proving the dependency crosses the pair rather than staying local.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_site,
    create_region,
    create_market,
    create_route,
    create_contractor,
    create_delivery_route,
    create_stop,
    create_edition,
    create_title_closure,
    get_contractor,
    get_print_route,
    plan_transfer,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]


def test_a_closing_receiving_site_makes_the_identical_transfer_fail():
    """PRD §3.2: "It is accepted only while the market is `active`, while the
    receiving site is `active` and not already committed to another market's
    in-flight transfer".
    PRD §2.6: "A request whose path names several resources is resolved strictly
    from left to right".

    Design: Difficulty/cross_entity_state_dependency/market_transfer_requires_active_print_site
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site_kot = create_site(hub["id"])
    site_ced = create_site(hub["id"], code="CED", press_units=1,
                           allocation_method="PROPORTIONAL")
    region = create_region(hub["id"])
    market = create_market(region["id"], guaranteed_floor_copies=8000,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30,
                           single_copy_market_rule="carrier")
    create_route(site_kot["id"], market["id"])
    create_route(site_ced["id"], market["id"], transit_minutes=150)

    version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    planned = validate_success(
        api.plan_market_transfer(
            market["id"],
            {"receiving_print_site_id": site_kot["id"], "expected_hub_version": version},
            PRINT_OPS),
        200,
    )
    assert planned["status"] == "consolidation_planned"

    # Closing the untouched sibling site is what breaks the next request.
    closed = validate_success(api.plan_site_closure(site_ced["id"], PRINT_OPS), 200)
    assert closed["status"] == "closing"

    # A fresh market in the same hub now cannot plan onto the closing site.
    other = create_market(region["id"], name="Fallow", weighted_demand_units=6000,
                          guaranteed_floor_copies=0,
                          publication_deadline_utc="05:30",
                          on_time_margin_minutes=30,
                          single_copy_market_rule="carrier")
    version2 = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    response = api.plan_market_transfer(
        other["id"],
        {"receiving_print_site_id": site_ced["id"], "expected_hub_version": version2},
        PRINT_OPS,
    )

    error = validate_error(response, "ERR_SITE_NOT_RECEIVING")
    assert response.status_code == 422
    assert error["error_id"] == "ERR_SITE_NOT_RECEIVING"
    assert validate_success(
        api.get_print_market(other["id"], PRINT_OPS), 200)["status"] == "active"


def test_an_active_receiving_site_keeps_the_identical_transfer_legal():
    """PRD §3.2: "It is accepted only while the market is `active`, while the
    receiving site is `active` and not already committed to another market's
    in-flight transfer".
    PRD §3.2: "On success the market's `selected_print_route_id` points at the
    chosen route, that route becomes `committed`, the market's status becomes
    `consolidation_planned`".

    Design: Difficulty/cross_entity_state_dependency/market_transfer_requires_active_print_site
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site_kot = create_site(hub["id"])
    site_ced = create_site(hub["id"], code="CED", press_units=1,
                           allocation_method="PROPORTIONAL")
    region = create_region(hub["id"])
    market = create_market(region["id"], guaranteed_floor_copies=8000,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30,
                           single_copy_market_rule="carrier")
    create_route(site_kot["id"], market["id"])
    ced_route = create_route(site_ced["id"], market["id"], transit_minutes=150)

    assert validate_success(
        api.get_print_site(site_ced["id"], PRINT_OPS), 200)["status"] == "active"

    version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    planned = validate_success(
        api.plan_market_transfer(
            market["id"],
            {"receiving_print_site_id": site_ced["id"], "expected_hub_version": version},
            PRINT_OPS),
        200,
    )

    assert planned["status"] == "consolidation_planned"
    assert planned["selected_print_route_id"] == ced_route["id"]
    assert planned["route_selection_status"] == "current"
    assert validate_success(
        api.get_print_route(ced_route["id"], PRINT_OPS), 200)["status"] == "committed"


def test_the_hubs_ratio_gate_blocks_a_title_notice_it_previously_allowed():
    """PRD §3.9: "Publishing the statutory notice moves it to `notice_published`,
    and it is one of the operations the legal-notice gate holds".
    PRD §3.9: "Because that floor is exactly the ratio gate of §2.9, a hub that has
    lost too many markets off time cannot publish a closure notice until the ratio
    recovers."

    Design: Difficulty/cross_entity_state_dependency/title_closure_publication_requires_hub_ratio_compliance
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub(min_on_time_ratio_pct=90)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=0,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    create_edition(market["id"], site["id"], slug="2026-09-21", page_count=8,
                   requested_print_run_copies=1000)
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    title = create_title_closure(hub["id"])
    # The transfer is planned after the edition so the edition carries a ready
    # time; the ratio gate is only satisfiable once is_on_time is derived (§2.9).
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    assert validate_success(
        api.get_hub_compliance(hub["id"], TEST_USERS["auditor_headers"]), 200
    )["is_legal_notice_ratio_compliant"] is True, (
        "the standalone market's edition must be on time before the notice goes out"
    )

    published = validate_success(api.publish_title_notice(title["id"], PRINT_OPS), 200)
    assert published["status"] == "notice_published"
    assert validate_success(
        api.get_hub_compliance(hub["id"], TEST_USERS["auditor_headers"]), 200
    )["is_legal_notice_ratio_compliant"] is True, (
        "the standalone market's delivery stop must be active for it to count on time"
    )

    # Terminating the only stop takes the market off time, so the ratio fails.
    validate_success(api.terminate_stop(stop["id"], DELIVERY), 200)
    refreshed = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)
    assert refreshed["legal_notice_block"] is True, (
        "removing the hub's only on-time market must set the block"
    )

    second = create_title_closure(hub["id"], title_code="RIV-GAZETTE")
    response = api.publish_title_notice(second["id"], PRINT_OPS)

    error = validate_error(response, "ERR_LEGAL_NOTICE_HOLD")
    assert response.status_code == 422
    assert error["error_id"] == "ERR_LEGAL_NOTICE_HOLD"


def test_a_restored_ratio_lets_the_same_notice_publish_again():
    """PRD §3.9: "A published closure can be halted: suspending it to `suspended`
    requires the hub's `legal_notice_block` to be true, and resuming it back to
    `notice_published` requires that block to be false."
    PRD §3.9: "a hub that has lost too many markets off time cannot publish a
    closure notice until the ratio recovers."

    Design: Difficulty/cross_entity_state_dependency/title_closure_publication_requires_hub_ratio_compliance
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub(min_on_time_ratio_pct=90)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    markets = []
    for i in range(1, 3):
        markets.append(create_market(
            region["id"], name=f"M{i:02d}", weighted_demand_units=6000,
            publication_deadline_utc="05:30", on_time_margin_minutes=30,
            guaranteed_floor_copies=0, single_copy_market_rule="carrier"))
    # Each market needs its own site: planning onto a site that already carries an
    # in-flight transfer is refused, and §2.9 needs both markets derivably on time.
    for idx, market in enumerate(markets, start=1):
        extra_site = create_site(hub["id"], code="M%dSITE" % idx,
                                 max_concurrent_departures=2)
        create_route(extra_site["id"], market["id"])
        create_edition(market["id"], extra_site["id"], slug="2026-09-21",
                       page_count=8, requested_print_run_copies=1000)
        plan_transfer(market["id"], extra_site["id"], hub_id=hub["id"])
    # A third market parked on its own site keeps the gate satisfiable while the
    # pausable subject market carries the triggering stop.
    keeper_site = create_site(hub["id"], code="KEEPER", max_concurrent_departures=3)
    keeper = create_market(region["id"], name="M03", weighted_demand_units=6000,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=0,
                           single_copy_market_rule="carrier")
    create_route(keeper_site["id"], keeper["id"])
    create_edition(keeper["id"], keeper_site["id"], slug="2026-09-21",
                   page_count=8, requested_print_run_copies=1000)
    plan_transfer(keeper["id"], keeper_site["id"], hub_id=hub["id"])

    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], markets[0]["id"])
    # §3.4: a pause is only admitted while the logical date sits inside the stop's
    # declared window, and a resume only once the date is strictly past it.
    stop = create_stop(delivery_route["id"], markets[0]["id"], stop_code="S1",
                       pause_start_date="2026-09-25",
                       pause_end_date="2026-10-02")
    title = create_title_closure(hub["id"])

    assert validate_success(
        api.publish_title_notice(title["id"], PRINT_OPS), 200)["status"] == "notice_published"

    # Pausing the stop takes its market off time and trips the hub-wide block.
    validate_success(api.pause_stop(stop["id"], DELIVERY), 200)
    assert validate_success(
        api.get_hub(hub["id"], PRINT_OPS), 200)["legal_notice_block"] is True
    suspended = validate_success(
        api.suspend_title_closure(title["id"], PRINT_OPS), 200)
    assert suspended["status"] == "suspended", (
        "a halted closure requires the block to be true"
    )
    assert validate_success(
        api.get_hub(hub["id"], PRINT_OPS), 200)["legal_notice_block"] is True

    # Resuming first, then restoring the ratio, lets the closure come back.
    api.set_current_utc({"current_utc": "2026-10-03T00:00:00Z"}, ADMIN)
    validate_success(api.resume_stop(stop["id"], DELIVERY), 200)
    restored = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)
    assert restored["legal_notice_block"] is False, (
        "a resumed stop clears the block again"
    )
    resumed = validate_success(api.resume_title_closure(title["id"], PRINT_OPS), 200)
    assert resumed["status"] == "notice_published"


def test_termination_is_blocked_while_a_sibling_route_is_still_prepared():
    """PRD §3.3: "Termination is terminal: it requires the contractor to be `active`
    or `suspended` and to have no route still `prepared`."
    PRD §3.3: "Advancing a route from `prepared` to `contract_active` requires the
    route's contractor to be `active`".

    Design: Difficulty/cross_entity_state_dependency/contractor_termination_requires_no_prepared_route
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=0,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    contractor = create_contractor(hub["id"])
    route_r1 = create_delivery_route(contractor["id"], market["id"],
                                     route_code="R1")
    other = create_market(region["id"], name="Fallow", weighted_demand_units=6000,
                          guaranteed_floor_copies=0,
                          publication_deadline_utc="05:30",
                          on_time_margin_minutes=30,
                          single_copy_market_rule="carrier")
    route_r2 = create_delivery_route(contractor["id"], other["id"],
                                     route_code="R2")

    create_edition(market["id"], site["id"], slug="2026-09-20", page_count=12,
                   requested_print_run_copies=28000)
    r1_after = validate_success(
        api.cost_run(route_r1["id"], {"run_date": "2026-09-20"}, DELIVERY), 200)
    r2_after = validate_success(
        api.get_delivery_route(route_r2["id"], DELIVERY), 200)

    assert r1_after["status"] == "contract_active", (
        f"a costed route advances to contract_active, got {r1_after['status']}"
    )
    assert r2_after["status"] == "prepared", (
        f"a route whose market carries no edition stays prepared, got {r2_after['status']}"
    )

    response = api.terminate_contractor(contractor["id"], DELIVERY)
    error = validate_error(response, "ERR_INVALID_STATE")
    assert response.status_code == 409
    assert error["error_id"] == "ERR_INVALID_STATE"


def test_the_boundary_sits_on_the_sibling_edge_not_on_the_whole_record():
    """PRD §3.3: "A route begins `prepared`."
    PRD §3.3: "reinstating a `terminated` contractor, or creating a new route under
    it, is refused with `ERR_CONTRACTOR_TERMINAL` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/contractor_termination_requires_no_prepared_route
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=0,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    contractor = create_contractor(hub["id"])
    create_delivery_route(contractor["id"], market["id"], route_code="R1")

    # A single prepared route is enough to block termination.
    blocked = api.terminate_contractor(contractor["id"], DELIVERY)
    assert blocked.status_code == 409
    assert blocked.json()["data"]["error_id"] == "ERR_INVALID_STATE"
    still_active = validate_success(
        api.get_contractor(contractor["id"], DELIVERY), 200)
    assert still_active["status"] == "active", (
        "the refused termination must leave the contractor untouched"
    )

    # Driving that same route to contract_active unblocks the termination.
    create_edition(market["id"], site["id"], slug="2026-09-20", page_count=12,
                   requested_print_run_copies=28000)
    advanced = validate_success(
        api.cost_run(
            validate_success(
                api.list_contractor_routes(contractor["id"], DELIVERY), 200)[0]["id"],
            {"run_date": "2026-09-20"}, DELIVERY),
        200)
    assert advanced["status"] == "contract_active"

    allowed = validate_success(api.terminate_contractor(contractor["id"], DELIVERY), 200)
    assert allowed["status"] == "terminated", (
        "with no route left prepared the same termination must be accepted"
    )