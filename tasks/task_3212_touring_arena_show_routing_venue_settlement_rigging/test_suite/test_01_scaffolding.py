"""Instance scaffolding tests: tour/venue/avail/engagement creation, reads, pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_engagement,
    create_engagement_payload,
    create_tour_payload,
    create_venue_payload,
    setup_confirmed_engagement,
    setup_held_engagement,
    setup_tour_and_venue,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["tour_manager_headers"]
VB = TEST_USERS["venue_booker_headers"]
LS = TEST_USERS["labor_steward_headers"]
BOM = TEST_USERS["box_office_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]


class TestTourCreation:
    def test_tour_create_returns_system_fields_and_defaults(self):
        """PRD §3.1: "A new tour is born in `PLANNING` status with its fiscal
        counters zeroed: `total_gross_cents` starts at 0,
        `total_settlement_due_cents` starts at 0, and `open_engagement_count`
        starts at 0."
        PRD §3.1: "Two optional policy knobs ride on creation:
        `market_cooldown_days`, the minimum number of days that must pass before
        the same venue may host this tour again (defaulting to 180 when omitted),
        and `royalty_reserve_pct`, the fraction of gross ticket sales the promoter
        reserves against license royalty obligations (defaulting to 0.0, meaning
        uncapped withholding)."

        Design: Corner/entities/tour_create_returns_system_fields_and_defaults
        """
        from test_helpers import set_clock

        set_clock()
        payload = create_tour_payload()
        payload.pop("market_cooldown_days")
        payload.pop("royalty_reserve_pct")
        resp = api_client.create_tour(payload, TM)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PLANNING"
        assert data["version"] == 1
        assert data["market_cooldown_days"] == 180
        assert data["royalty_reserve_pct"] == 0.0
        assert data["total_gross_cents"] == 0
        assert data["total_settlement_due_cents"] == 0
        assert data["open_engagement_count"] == 0

    def test_tour_get_unknown_id_returns_not_found(self):
        """PRD §2.8: "The first missing resource produces the 404 for that
        resource — `ERR_TOUR_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`,
        `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_AVAIL_NOT_FOUND`, `ERR_POINT_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_LABOR_CALL_NOT_FOUND`,
        `ERR_TRUCK_MOVE_NOT_FOUND`, `ERR_TICKET_SCALE_NOT_FOUND`,
        `ERR_SETTLEMENT_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND` — and validation stops there."

        Design: Corner/entities/tour_get_unknown_id_returns_not_found
        """
        resp = api_client.get_tour("00000000-0000-4000-8000-000000000001", TM)
        validate_error(resp, ApiErrorId.ERR_TOUR_NOT_FOUND)


class TestVenueCreation:
    def test_venue_create_with_invalid_union_rule_set_returns_invalid_request(self):
        """PRD §3.2: "the venue's `union_rule_set` — one of exactly `IATSE`,
        `TEAMSTERS`, or `NON_UNION`, which drives every labor-call minimum for
        engagements in that building"
        PRD §2.9: "required-field presence and basic shape of every input field,
        reported as `ERR_INVALID_REQUEST` (HTTP 400) when nothing earlier has
        fired."

        Design: Corner/entities/venue_create_with_invalid_union_rule_set_returns_invalid_request
        """
        payload = create_venue_payload(union_rule_set="GUILD")
        resp = api_client.create_venue(payload, VB)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTicketScalePagination:
    def test_ticket_scales_list_paginates_with_total_count_and_has_more(self):
        """PRD §2.3: "List responses embed four pagination fields in `meta`:
        `limit` and `offset` echoing the effective request values, `total_count`
        giving the total number of matching records, and `has_more` indicating
        whether additional records exist beyond the returned page."

        Design: Corner/entities/ticket_scales_list_paginates_with_total_count_and_has_more
        """
        from test_helpers import create_ticket_scale

        ctx = setup_confirmed_engagement()
        for label, rank in (("A", 1), ("B", 2), ("C", 3)):
            create_ticket_scale(ctx, tier_label=label, tier_rank=rank)

        resp = api_client.list_ticket_scales(
            ctx["tour"]["id"], ctx["engagement"]["id"], BOM,
            params={"limit": 2, "offset": 0},
        )
        rows, meta = validate_paginated(resp)
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        resp = api_client.list_ticket_scales(
            ctx["tour"]["id"], ctx["engagement"]["id"], BOM,
            params={"limit": 2, "offset": 2},
        )
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestEngagementInitialState:
    def test_engagement_confirm_initial_state_is_hold(self):
        """PRD §3.3: "A successful create lands the engagement in `HOLD`, flips
        the target avail `OPEN → HELD` with `held_for_engagement_id` pointing at
        the new engagement (advancing the avail's `version` by 1 — which is
        exactly what a competing holder's `expected_avail_version` will collide
        with), increments the tour's `open_engagement_count` by 1, and stamps
        `hold_expires_at` as the engagement's `created_at` plus 72 hours."

        Design: Corner/state_machines/engagement_confirm_initial_state_is_hold
        """
        from datetime import datetime, timedelta, timezone

        ctx = setup_held_engagement()
        eng = ctx["engagement"]
        assert eng["status"] == "HOLD"
        created = datetime.fromisoformat(eng["created_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(eng["hold_expires_at"].replace("Z", "+00:00"))
        assert expires - created == timedelta(hours=72)


class TestEngagementRead:
    def test_get_engagement_returns_full_field_set(self):
        """PRD §2.4: "Every persisted resource carries an `id` field: a
        server-minted UUID with no type prefix, assigned at creation. Every
        resource also carries `created_at`, an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created, and
        `updated_at`, an ISO 8601 UTC timestamp of the same format refreshed on
        every mutation. Every resource carries a `version` integer that starts
        at its initial value at creation and increments by 1 on every mutation
        of that resource — including mutations caused by cascading side effects
        from operations on related resources."
        PRD §3.3: "stamps `hold_expires_at` as the engagement's `created_at`
        plus 72 hours."

        Design: Corner/endpoints/get_engagement_returns_full_field_set
        """
        ctx = setup_held_engagement()
        resp = api_client.get_engagement(
            ctx["tour"]["id"], ctx["engagement"]["id"], TM
        )
        data = validate_success(resp)
        assert_engagement(data)
        assert data["tour_id"] == ctx["tour"]["id"]
        assert data["venue_id"] == ctx["venue"]["id"]
        assert data["date_avail_id"] == ctx["avail"]["id"]
        assert data["deal_type"] == "FLAT_RENT"
        assert "hold_expires_at" in data
        assert "market_overlap_flag" in data
