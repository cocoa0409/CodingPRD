"""Corner queue B — section: consistency_model.

Immediate consistency of a derived field, and the withdrawn market's row staying
readable rather than being deleted.
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
    terminate_contractor,
    withdraw_market,
    plan_transfer,
    hub_version,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_01, CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_immediate_consistency_of_transfer_cost_after_plan_transfer():
    """PRD §3.2: "On success the market's `selected_print_route_id` points at the
    chosen route, that route becomes `committed`, the market's status becomes
    `consolidation_planned`, its `route_selection_status` becomes `current`, its
    transfer ledger is computed".
    PRD §2.5: "Derived quantities — a site's `capacity_remaining_copies`, a
    market's `net_print_site_transfer_cost_cents`, an edition's `minutes_late` —
    are ordinary field mutations: recomputing one refreshes `updated_at` and bumps
    `version` on the row that holds it."

    Design: Corner/consistency_model/immediate_consistency_of_transfer_cost_after_plan_transfer
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], name="Riverton",
                           guaranteed_floor_copies=8000)
    create_route(site["id"], market["id"])

    edition = create_edition(market["id"], site["id"], slug="2026-09-21",
                             page_count=12, requested_print_run_copies=40000)
    assert edition["allocated_print_run_copies"] == 40000

    version = hub_version(hub["id"])
    response = api.plan_market_transfer(
        market["id"],
        {"receiving_print_site_id": site["id"], "expected_hub_version": version},
        PRINT_OPS,
    )
    planned = validate_success(response, 200)

    assert planned["print_site_transfer_cost_cents"] == pytest.approx(92.00, abs=0.01), (
        f"the response itself must carry the recomputed cost, got "
        f"{planned['print_site_transfer_cost_cents']}"
    )
    assert planned["net_print_site_transfer_cost_cents"] == pytest.approx(92.00, abs=0.01)

    reread = validate_success(api.get_print_market(market["id"], PRINT_OPS), 200)
    assert reread["print_site_transfer_cost_cents"] == planned["print_site_transfer_cost_cents"], (
        "the derived field must not lag behind the write that produced it"
    )
    assert reread["net_print_site_transfer_cost_cents"] == planned["net_print_site_transfer_cost_cents"]


def test_soft_deleted_withdrawn_markets_stay_listable_when_requested():
    """PRD §3.2: "A market leaves the print graph only by withdrawal".
    PRD §2.9: "markets whose status is `withdrawn` are excluded from both the
    numerator and the denominator, because they no longer receive print."

    Design: Corner/consistency_model/soft_deleted_withdrawn_markets_stay_listable_when_requested
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    riverton = create_market(region["id"], name="Riverton",
                             guaranteed_floor_copies=8000)
    fallow = create_market(region["id"], name="Fallow", weighted_demand_units=6000,
                           guaranteed_floor_copies=8000)
    assert fallow["name"] == "Fallow"
    create_route(site["id"], riverton["id"])
    create_edition(riverton["id"], site["id"], slug="2026-09-21", page_count=12,
                   requested_print_run_copies=40000)
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], riverton["id"])
    create_stop(delivery_route["id"], riverton["id"], stop_code="S1")

    plan_transfer(riverton["id"], site["id"], hub_id=hub["id"])
    validate_success(api.plan_site_closure(site["id"], PRINT_OPS), 200)
    terminate_contractor(contractor["id"])
    withdraw_market(riverton["id"])

    withdrawn_page = api.list_print_markets(
        AUDITOR, {"region_id": region["id"], "status": "withdrawn"})
    withdrawn_rows, withdrawn_meta = validate_paginated(withdrawn_page)
    assert withdrawn_meta["total_count"] == 1
    assert len(withdrawn_rows) == 1
    assert withdrawn_rows[0]["name"] == "Riverton"
    assert withdrawn_rows[0]["status"] == "withdrawn"

    active_page = api.list_print_markets(
        AUDITOR, {"region_id": region["id"], "status": "active"})
    active_rows, active_meta = validate_paginated(active_page)
    assert active_meta["total_count"] == 1
    assert len(active_rows) == 1
    assert active_rows[0]["name"] == "Fallow", (
        "the withdrawn market is excluded from an active-only filter"
    )

    by_id = validate_success(api.get_print_market(riverton["id"], AUDITOR), 200)
    assert by_id["id"] == riverton["id"], (
        "the withdrawn row is never deleted, so it stays readable by id"
    )
    assert by_id["status"] == "withdrawn"