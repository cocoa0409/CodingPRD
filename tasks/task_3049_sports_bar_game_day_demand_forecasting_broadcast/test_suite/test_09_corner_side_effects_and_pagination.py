"""Corner coverage of endpoint side effects, pagination, and immediate
consistency on settlement."""

import pytest

from test_helpers import (
    SERVER_HEADERS,
    VENUE_MANAGER_HEADERS,
    add_order_line,
    create_event,
    create_guest,
    create_open_check,
    create_screen_assignment,
    create_venue,
    create_zone,
    event_payload,
    validate_paginated,
    validate_success,
)


class TestWingCostPatchRecomputesVolatility:
    def test_wing_cost_update_recomputes_the_volatility_score(self, api):
        """PRD §3.1: "From that cost the system derives `volatility_score`: the absolute difference between the current wing cost per pound and the reference cost of 180 cents, divided by 180."
        PRD §3.1: "Whenever a `VenueManager` updates the wing supply cost, `volatility_score` is recomputed, the venue's `updated_at` is refreshed, and the venue's `version` increments."

        Updating the cost from 180 to 230 yields |230 - 180| / 180 = 0.2778
        and bumps the version.

        Design: Corner/endpoints/wing_cost_patch_recomputes_volatility
        """
        venue = create_venue()
        assert venue["wing_cost_cents_per_lb"] == 180
        assert venue["volatility_score"] == pytest.approx(0.0)

        updated = validate_success(
            api.update_wing_cost(
                venue["id"], {"wing_cost_cents_per_lb": 230}, VENUE_MANAGER_HEADERS
            )
        )

        assert updated["volatility_score"] == pytest.approx(50 / 180)
        assert updated["version"] == venue["version"] + 1

    def test_wing_cost_update_to_the_reference_cost_zeroes_volatility(self, api):
        """PRD §3.1: "From that cost the system derives `volatility_score`: the absolute difference between the current wing cost per pound and the reference cost of 180 cents, divided by 180."

        Moving back down to the 180-cent reference cost returns the
        volatility score to exactly zero.

        Design: Corner/endpoints/wing_cost_patch_recomputes_volatility
        """
        venue = create_venue(wing_cost_cents_per_lb=250)
        updated = validate_success(
            api.update_wing_cost(
                venue["id"], {"wing_cost_cents_per_lb": 180}, VENUE_MANAGER_HEADERS
            )
        )

        assert updated["volatility_score"] == pytest.approx(0.0)


class TestEventCancelRemovesScreenAssignments:
    def test_cancel_recomputes_the_zone_to_open_with_no_primary(self, api):
        """PRD §3.2: "cancellation is a `Scheduler` action with wide blast radius — every screen assignment referencing the event is removed, every affected zone recomputes its `primary_event_id` and `posture`, and forecasts recompute excluding the event."

        The zone showing the cancelled event drops its primary and returns to
        OPEN.

        Design: Corner/endpoints/event_cancel_removes_screen_assignments
        """
        from test_helpers import SCHEDULER_HEADERS

        venue = create_venue()
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Game",
            expected_attendance=5000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        create_screen_assignment(zone["id"], event["id"])

        validate_success(api.cancel_event(event["id"], SCHEDULER_HEADERS))

        zone_after = validate_success(api.get_zone(zone["id"], VENUE_MANAGER_HEADERS))
        assert zone_after["primary_event_id"] is None
        assert zone_after["posture"] == "OPEN"


class TestPaginationLimitOffset:
    def test_event_listing_pages_by_limit_and_offset(self, api):
        """PRD §2.3: "For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."

        Eleven ingested events paginate into a full first page of ten and a
        second page of one.

        Design: Corner/cross_cutting_complexity_layers/pagination_limit_offset
        """
        from test_helpers import SCHEDULER_HEADERS

        create_venue()
        for i in range(11):
            create_event(title=f"Game {i + 1}", expected_attendance=1000)

        page1, meta1 = validate_paginated(
            api.list_events(SCHEDULER_HEADERS, limit=10, offset=0)
        )
        page2, meta2 = validate_paginated(
            api.list_events(SCHEDULER_HEADERS, limit=10, offset=10)
        )

        assert len(page1) == 10
        assert len(page2) == 1


class TestImmediateConsistencyOnCheckSettle:
    def test_settle_response_carries_the_final_money_figures(self, api):
        """PRD §3.5: "Settlement fixes the check's arithmetic in the staged order of §2.7: per-unit rounding first, per-line rounding second, then tax. On settle, `tax_cents` is the subtotal times 0.05 rounded half-up."
        PRD §3.5: "The `total_cents` is subtotal plus tax plus cover."

        One 20-piece line at the 150-cent base price settles in a single
        response: subtotal 3000, tax 150, total 3150 — no follow-up read is
        needed to observe the final figures.

        Design: Corner/consistency_model/immediate_consistency_on_check_settle
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        check = create_open_check(venue["id"], guest["id"])
        add_order_line(check["id"], kind="TRADITIONAL", portion_count=2)

        settled = validate_success(api.settle_check(check["id"], SERVER_HEADERS))

        assert settled["status"] == "SETTLED"
        assert settled["subtotal_cents"] == 3000
        assert settled["tax_cents"] == 150
        assert settled["total_cents"] == 3150
