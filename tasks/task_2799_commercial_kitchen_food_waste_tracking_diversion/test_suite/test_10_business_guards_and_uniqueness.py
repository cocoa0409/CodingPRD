"""Channel contracts, pickup capacity, the donation posture gate and every uniqueness key.

Every test in this module drives the service from an empty database with the logical
clock at its process-start value, and builds each precondition through the public API.
"""

from test_helpers import (
    ApiErrorId,
    assert_consignment,
    assert_corporate_rollup,
    assert_hauler_ticket,
    assert_shift,
    assert_tracking_station,
    factories,
    fixtures,
    make_corporate_lead_headers,
    make_hauler_operator_headers,
    make_platform_admin_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHaulerChannelContract:
    """A consignment may only ride a channel the collecting organisation is contracted for."""

    def test_consignment_channel_outside_the_haulers_channel_list_is_rejected(self, api):
        """A donation consignment on a compost-only hauler is refused; compost on the same hauler opens.

        PRD Coverage: "The requested `channel` must be listed in the hauler's `channels`, or the
        request is refused with `ERR_HAULER_CHANNEL_UNSUPPORTED`."

        Design: Corner/validations/consignment_channel_outside_the_haulers_channel_list_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        hauler = fixtures.create_hauler(channels=["COMPOST"])
        headers = make_site_sustainability_manager_headers(site["id"])

        uncontracted = factories.create_consignment_payload(
            site["id"],
            hauler["id"],
            channel="DONATION",
            pickup_window_start="2026-08-02T09:00:00Z",
            pickup_window_end="2026-08-02T11:00:00Z",
        )
        validate_error(
            api.create_consignment(uncontracted, headers),
            ApiErrorId.HAULER_CHANNEL_UNSUPPORTED.value,
        )

        contracted = factories.create_consignment_payload(
            site["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-08-02T09:00:00Z",
            pickup_window_end="2026-08-02T11:00:00Z",
        )
        consignment = validate_success(api.create_consignment(contracted, headers), 201)
        assert_consignment(consignment)
        assert consignment["logistics_status"] == "DRAFT"
        assert consignment["settlement_status"] == "UNBILLED"


class TestStagingCapacityGuard:
    """Per-pickup weight capacity is enforced at staging, not at line insertion."""

    def test_staging_more_grams_than_the_hauler_capacity_is_rejected(self, api):
        """An over-capacity line is accepted and only the staging attempt fails.

        PRD Coverage: "It requires `line_count` to be at least 1, refusing an empty consignment with
        `ERR_CONSIGNMENT_EMPTY`, and requires `staged_weight_grams` not to exceed the hauler's
        `capacity_kg_per_pickup` converted to grams by multiplying by 1000 — an over-capacity load is
        refused with `ERR_HAULER_CAPACITY_EXCEEDED`."

        Design: Corner/validations/staging_more_grams_than_the_hauler_capacity_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        world = fixtures.site_with_one_capture(
            entry_overrides={"weight_grams": 2000, "captured_at": "2026-08-01T10:00:00Z"}
        )
        site_id = world["site"]["id"]
        hauler = fixtures.create_hauler(channels=["COMPOST"], capacity_kg_per_pickup=1)
        consignment = fixtures.open_consignment(
            site_id,
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-08-02T09:00:00Z",
            pickup_window_end="2026-08-02T11:00:00Z",
        )
        headers = make_site_sustainability_manager_headers(site_id)

        line_payload = factories.create_consignment_line_payload(consignment["id"], world["entry"]["id"], 1500)
        validate_success(api.create_consignment_line(line_payload, headers), 201)
        assert fixtures.read_consignment(consignment["id"])["staged_weight_grams"] == 1500

        validate_error(
            api.stage_consignment(consignment["id"], headers),
            ApiErrorId.HAULER_CAPACITY_EXCEEDED.value,
        )
        assert fixtures.read_consignment(consignment["id"])["logistics_status"] == "DRAFT"


class TestDonationPostureGate:
    """The donation block on staging keys on an ESCALATED posture and on nothing weaker."""

    def _site_with_donation_load(self, api, open_a_second_shift):
        """Build a donation-eligible load at one site, optionally raising a second shift's alerts."""
        fixtures.set_clock("2026-08-01T20:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type()
        am_shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)
        am_entry = fixtures.capture_entry(
            station["id"],
            am_shift["id"],
            food_type["id"],
            weight_grams=6000,
            loss_reason="OVERPRODUCTION",
            captured_at="2026-08-01T10:00:00Z",
        )
        if open_a_second_shift:
            pm_shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="PM", meals_served=250)
            fixtures.capture_entry(
                station["id"],
                pm_shift["id"],
                food_type["id"],
                weight_grams=5000,
                loss_reason="OVERPRODUCTION",
                captured_at="2026-08-01T18:00:00Z",
            )
        hauler = fixtures.create_approved_hauler(
            name="Food Rescue", channels=["DONATION"], stop_fee_cents=1200
        )
        consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="DONATION",
            pickup_window_start="2026-08-02T09:00:00Z",
            pickup_window_end="2026-08-02T11:00:00Z",
        )
        fixtures.add_line(site["id"], consignment["id"], am_entry["id"], 400)
        return {"site": site, "consignment": consignment}

    def test_escalated_coaching_posture_blocks_staging_a_donation_consignment(self, api):
        """Four open coaching alerts escalate the kitchen and stop the donation load leaving.

        PRD Coverage: "A `DONATION` consignment may not be staged while its site's
        `coaching_posture` is `ESCALATED`, which is refused with
        `ERR_SITE_POSTURE_BLOCKS_DONATION`: a kitchen with three or more unresolved coaching alerts
        has not earned the right to hand food to the public."
        "`coaching_posture` is derived purely from that count — `MONITORING` when the count is
        exactly 0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every count in
        between"

        Design: Corner/validations/escalated_coaching_posture_blocks_staging_a_donation_consignment
        """
        world = self._site_with_donation_load(api, open_a_second_shift=True)
        site_id = world["site"]["id"]
        consignment_id = world["consignment"]["id"]

        _, alert_meta = validate_paginated(api.list_alerts(make_platform_admin_headers(), site_id=site_id))
        assert alert_meta["total_count"] == 4
        site = fixtures.read_site(site_id)
        assert site["open_alert_count"] == 4
        assert site["coaching_posture"] == "ESCALATED"

        validate_error(
            api.stage_consignment(consignment_id, make_site_sustainability_manager_headers(site_id)),
            ApiErrorId.SITE_POSTURE_BLOCKS_DONATION.value,
        )
        held = fixtures.read_consignment(consignment_id)
        assert held["logistics_status"] == "DRAFT"
        assert held["line_count"] == 1

    def test_donation_staging_passes_while_the_posture_is_only_intervention(self, api):
        """The same donation load stages at two open alerts, because only ESCALATED blocks it.

        PRD Coverage: "`coaching_posture` is derived purely from that count — `MONITORING` when the
        count is exactly 0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every
        count in between"
        "On success `staged_at` is stamped with the current logical clock, `staged_weight_grams` is
        frozen for the later ticket variance comparison, no further line may be added or deleted, and
        `version` is incremented by 1."

        Design: Corner/validations/donation_staging_passes_while_the_posture_is_only_intervention
        """
        world = self._site_with_donation_load(api, open_a_second_shift=False)
        site_id = world["site"]["id"]

        site = fixtures.read_site(site_id)
        assert site["open_alert_count"] == 2
        assert site["coaching_posture"] == "INTERVENTION"

        response = api.stage_consignment(
            world["consignment"]["id"], make_site_sustainability_manager_headers(site_id)
        )
        staged = validate_success(response, 200)
        assert_consignment(staged)
        assert staged["logistics_status"] == "STAGED"
        assert staged["staged_weight_grams"] == 400
        assert staged["settlement_status"] == "UNBILLED"


class TestTicketHaulerConsistency:
    """A weigh ticket's hauler is both the scoping subject and a referential constraint."""

    def test_ticket_carrying_the_submitting_haulers_own_id_on_a_foreign_consignment_is_rejected(self, api):
        """Naming one's own ticket book on somebody else's load is a referential failure, not a scope one.

        PRD Coverage: "An optional `hauler_id` asserts which ticket book the ticket was torn from;
        when omitted it defaults to the referenced consignment's `hauler_id`, and when supplied it
        must equal that value, with a mismatch refused as `ERR_TICKET_HAULER_MISMATCH`."
        "On weigh-ticket submission the compared value is the ticket's own `hauler_id` — the one
        supplied in the body, or, when the body omits it, the value defaulted from the referenced
        consignment."

        Design: Corner/validations/ticket_carrying_the_submitting_haulers_own_id_on_a_foreign_consignment_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        world = fixtures.dispatched_consignment(
            allocated_weight_grams=400,
            entry_overrides={"captured_at": "2026-08-01T10:00:00Z"},
            consignment_overrides={
                "pickup_window_start": "2026-08-02T09:00:00Z",
                "pickup_window_end": "2026-08-02T11:00:00Z",
            },
        )
        consignment_id = world["consignment"]["id"]
        foreign_hauler = fixtures.create_approved_hauler(
            name="Blue Haul", rate_cents_per_tonne=49000, stop_fee_cents=1500
        )
        headers = make_hauler_operator_headers(foreign_hauler["id"])

        own_book = factories.create_hauler_ticket_payload(
            consignment_id,
            400,
            ticket_number="TN-9",
            ticket_date="2026-08-02",
            hauler_id=foreign_hauler["id"],
        )
        validate_error(api.create_hauler_ticket(own_book, headers), ApiErrorId.TICKET_HAULER_MISMATCH.value)

        defaulted = factories.create_hauler_ticket_payload(
            consignment_id, 400, ticket_number="TN-9", ticket_date="2026-08-02"
        )
        validate_error(api.create_hauler_ticket(defaulted, headers), ApiErrorId.HAULER_SCOPE_VIOLATION.value)

        assert fixtures.read_consignment(consignment_id)["settlement_status"] == "UNBILLED"


class TestScopedAndGlobalUniquenessKeys:
    """Each duplicate key has its own error, and the scoped keys behave unlike the global ones."""

    def test_duplicate_site_code_is_rejected(self, api):
        """A second kitchen reusing an existing short code collides under any name and region.

        PRD Coverage: "A second site claiming an existing `site_code` is refused with
        `ERR_DUPLICATE_SITE_CODE`."

        Design: Corner/validations/duplicate_site_code_is_rejected
        """
        fixtures.create_site(name="Harbor Kitchen", site_code="HK-01", region_code="NE")

        colliding = factories.create_site_payload(
            name="Harbor Kitchen Annex", site_code="HK-01", region_code="SW"
        )
        validate_error(
            api.create_site(colliding, make_platform_admin_headers()),
            ApiErrorId.DUPLICATE_SITE_CODE.value,
        )

        _, meta = validate_paginated(api.list_sites(make_platform_admin_headers()))
        assert meta["total_count"] == 1

    def test_station_code_is_unique_within_a_site_but_reusable_across_sites(self, api):
        """The same terminal code collides inside one kitchen and is legal at another.

        PRD Coverage: "a `station_code` printed on the terminal that must be unique among that site's
        stations — a collision is refused with `ERR_DUPLICATE_STATION_CODE`"
        "Three optional inputs complete the profile: `tare_grams`, the container tare the scale
        firmware subtracts before a capture is posted, which must be zero or greater and defaults to
        0; `capture_lock_seconds`, the length in seconds of the station occupation interval that each
        capture creates, which must be at least 0 and at most 600 and defaults to 30; and `status`,
        which defaults to `ACTIVE`."

        Design: Corner/validations/station_code_is_unique_within_a_site_but_reusable_across_sites
        """
        site_a = fixtures.create_site(name="Harbor Kitchen", site_code="HK-01")
        site_b = fixtures.create_site(name="Hillside Kitchen", site_code="HK-02")
        fixtures.create_station(site_a["id"], station_code="PREP-1", station_kind="PREP")
        headers = make_platform_admin_headers()

        colliding = factories.create_tracking_station_payload(
            site_a["id"], station_code="PREP-1", station_kind="HOT_LINE"
        )
        validate_error(
            api.create_tracking_station(colliding, headers),
            ApiErrorId.DUPLICATE_STATION_CODE.value,
        )

        elsewhere = factories.create_tracking_station_payload(
            site_b["id"], station_code="PREP-1", station_kind="PREP"
        )
        station = validate_success(api.create_tracking_station(elsewhere, headers), 201)
        assert_tracking_station(station)
        assert station["status"] == "ACTIVE"
        assert station["tare_grams"] == 0
        assert station["capture_lock_seconds"] == 30

        _, meta = validate_paginated(api.list_tracking_stations(headers, site_id=site_a["id"]))
        assert meta["total_count"] == 1

    def test_duplicate_shift_for_the_same_site_date_and_code_is_rejected(self, api):
        """A second AM period on one date collides while a PM period on that date is accepted.

        PRD Coverage: "The combination of `site_id`, `shift_date` and `shift_code` is unique; a second
        attempt at the same triple is refused with `ERR_DUPLICATE_SHIFT`."

        Design: Corner/validations/duplicate_shift_for_the_same_site_date_and_code_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)
        headers = make_shift_lead_headers()

        colliding = factories.create_shift_payload(
            site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=300
        )
        validate_error(api.create_shift(colliding, headers), ApiErrorId.DUPLICATE_SHIFT.value)

        distinct = factories.create_shift_payload(
            site["id"], shift_date="2026-08-01", shift_code="PM", meals_served=300
        )
        shift = validate_success(api.create_shift(distinct, headers), 201)
        assert_shift(shift)
        assert shift["status"] == "OPEN"
        assert shift["shift_waste_grams"] == 0

        _, meta = validate_paginated(
            api.list_shifts(make_platform_admin_headers(), site_id=site["id"], shift_date="2026-08-01")
        )
        assert meta["total_count"] == 2

    def test_global_name_and_code_uniqueness_holds_for_food_types_recipes_and_haulers(self, api):
        """Three catalog entities share one uniqueness rule and answer with three distinct errors.

        PRD Coverage: "A food type carries a `name` that must be globally unique — a duplicate is
        refused with `ERR_DUPLICATE_FOOD_TYPE_NAME`"
        "A recipe is created with a globally unique `recipe_code` — a duplicate is refused with
        `ERR_DUPLICATE_RECIPE_CODE`"
        "A hauler or recipient organisation is registered by a `PlatformAdmin` with a globally unique
        `name`, refused on collision with `ERR_DUPLICATE_HAULER_NAME`"

        Design: Corner/validations/global_name_and_code_uniqueness_holds_for_food_types_recipes_and_haulers
        """
        headers = make_platform_admin_headers()
        fixtures.create_food_type(name="Chicken Breast")
        fixtures.create_recipe(
            ingredients=[factories.recipe_ingredient("Stock Base", 2.0, 500, 0.00)],
            recipe_code="STK-PLN",
            name="Plain Stock",
        )
        fixtures.create_hauler(name="Green Haul", channels=["COMPOST"])

        duplicate_food_type = factories.create_food_type_payload(
            name="Chicken Breast",
            category="PRODUCE",
            default_cost_per_kg_cents=210,
            donation_eligible=False,
            animal_feed_eligible=True,
            compostable=True,
        )
        validate_error(
            api.create_food_type(duplicate_food_type, headers),
            ApiErrorId.DUPLICATE_FOOD_TYPE_NAME.value,
        )

        duplicate_recipe = factories.create_recipe_payload(
            ingredients=[factories.recipe_ingredient("Roasted Bones", 3.0, 300, 0.10)],
            recipe_code="STK-PLN",
            name="Rich Stock",
        )
        validate_error(api.create_recipe(duplicate_recipe, headers), ApiErrorId.DUPLICATE_RECIPE_CODE.value)

        duplicate_hauler = factories.create_hauler_payload(
            name="Green Haul",
            channels=["ANIMAL_FEED"],
            rate_cents_per_tonne=41000,
            stop_fee_cents=900,
            capacity_kg_per_pickup=300,
        )
        validate_error(api.create_hauler(duplicate_hauler, headers), ApiErrorId.DUPLICATE_HAULER_NAME.value)

        for listing in (api.list_food_types(headers), api.list_recipes(headers), api.list_haulers(headers)):
            _, meta = validate_paginated(listing)
            assert meta["total_count"] == 1

    def test_duplicate_ticket_number_for_the_same_hauler_is_rejected(self, api):
        """One hauler cannot reuse a ticket number on a second, entirely separate consignment.

        PRD Coverage: "the combination of `hauler_id` and `ticket_number` must be unique, and a
        reused number is refused with `ERR_DUPLICATE_TICKET_NUMBER`"

        Design: Corner/validations/duplicate_ticket_number_for_the_same_hauler_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        world = fixtures.dispatched_consignment(
            allocated_weight_grams=400,
            entry_overrides={"weight_grams": 2000, "captured_at": "2026-08-01T10:00:00Z"},
            consignment_overrides={
                "pickup_window_start": "2026-08-02T09:00:00Z",
                "pickup_window_end": "2026-08-02T11:00:00Z",
            },
        )
        site_id = world["site"]["id"]
        hauler_id = world["hauler"]["id"]
        second = fixtures.open_consignment(
            site_id,
            hauler_id,
            channel="COMPOST",
            pickup_window_start="2026-08-02T13:00:00Z",
            pickup_window_end="2026-08-02T15:00:00Z",
        )
        fixtures.add_line(site_id, second["id"], world["entry"]["id"], 400)
        fixtures.stage_consignment(site_id, second["id"])
        fixtures.dispatch_consignment(site_id, second["id"])
        fixtures.submit_ticket(hauler_id, world["consignment"]["id"], 400, ticket_number="TN-1",
                               ticket_date="2026-08-02")
        headers = make_hauler_operator_headers(hauler_id)

        reused = factories.create_hauler_ticket_payload(
            second["id"], 400, ticket_number="TN-1", ticket_date="2026-08-02"
        )
        validate_error(api.create_hauler_ticket(reused, headers), ApiErrorId.DUPLICATE_TICKET_NUMBER.value)

        _, meta = validate_paginated(api.list_hauler_tickets(make_platform_admin_headers(), hauler_id=hauler_id))
        assert meta["total_count"] == 1

        fresh = factories.create_hauler_ticket_payload(
            second["id"], 400, ticket_number="TN-2", ticket_date="2026-08-02"
        )
        ticket = validate_success(api.create_hauler_ticket(fresh, headers), 201)
        assert_hauler_ticket(ticket)
        assert ticket["status"] == "SUBMITTED"


class TestRollupScopeDistinctness:
    """A corporate rollup's site list must be pairwise distinct.

    A repeated site would double-count its grams into every corporate aggregate.
    """

    def test_repeating_a_site_inside_a_rollup_scope_is_rejected(self, api):
        """The same kitchen listed twice is refused; the deduplicated scope is prepared.

        PRD Coverage: "it must hold at least one element, every element must be an existing site,
        order is irrelevant, and a repeated site is refused with `ERR_DUPLICATE_SITE_IN_SCOPE`"

        Design: Corner/validations/repeating_a_site_inside_a_rollup_scope_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site_a = fixtures.create_site(name="Harbor Kitchen", site_code="HK-01")
        site_b = fixtures.create_site(name="Hillside Kitchen", site_code="HK-02")
        headers = make_corporate_lead_headers()

        repeated = factories.create_rollup_payload(
            [site_a["id"], site_b["id"], site_a["id"]],
            period_start="2026-08-01",
            period_end="2026-08-01",
        )
        validate_error(api.create_rollup(repeated, headers), ApiErrorId.DUPLICATE_SITE_IN_SCOPE.value)

        distinct = factories.create_rollup_payload(
            [site_a["id"], site_b["id"]],
            period_start="2026-08-01",
            period_end="2026-08-01",
        )
        rollup = validate_success(api.create_rollup(distinct, headers), 201)
        assert_corporate_rollup(rollup)
        assert rollup["in_scope_site_count"] == 2
