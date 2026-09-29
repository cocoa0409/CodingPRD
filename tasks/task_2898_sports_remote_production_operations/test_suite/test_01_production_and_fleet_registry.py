"""Production opening, the truck registry, the logical clock and the list surface.

Every test starts against an empty database with the logical clock at its
startup value and builds its own preconditions through the shared helpers.
"""

from test_helpers import (
    assert_created_at_ascending,
    assert_identity_fields,
    assert_instant_equals,
    assert_labor_ledger,
    assert_pagination_meta,
    assert_production,
    assert_readiness,
    assert_status,
    assert_truck,
    assert_versioned_row,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    CANONICAL_EVENT,
    CLOCK_EPOCH_STAMP,
    UNKNOWN_UUIDS,
)
from test_helpers.factories import (
    create_crew_call_payload,
    create_production_payload,
    create_truck_payload,
)
from test_helpers.fixtures import (
    assign_truck,
    new_crew_member,
    new_production,
    new_truck,
    read_production,
)


# ---------------------------------------------------------------------------
# Opening a production
# ---------------------------------------------------------------------------
def test_new_production_opens_at_planned_with_an_empty_labor_ledger(api, pm_headers):
    """A production created from the nine declared inputs materialises its stage,
    version, labor ledger and tier-derived gate counts without the caller supplying any.

    PRD: "A newly opened production sits at `PLANNED`."
    PRD: "At creation the labor ledger opens empty: `labor_committed_cents` is 0 and `labor_available_cents` therefore equals the full `labor_budget_total_cents`."
    PRD: "`truck_id` and `wrapped_by_user_id` both start null."
    PRD: "`required_crew_positions` — the count of *accepted* crew calls a certified crew component demands — is 12 for a `TIER_1` event, 4 for a `TIER_2` event and 2 for a `TIER_3` event."
    PRD: "`required_validated_preps` — the count of validated show-system preparations the provisioning conditions demand — is 3 for `TIER_1`, 2 for `TIER_2` and 1 for `TIER_3`."
    Design: Corner/entities/production_creation_returns_declared_defaults_and_zeroed_derived_fields
    """
    response = api.create_production(create_production_payload(), pm_headers)
    production = validate_success(response, 201)

    assert_production(production)
    assert_versioned_row(production, expected_version=1)
    assert_status(production, "PLANNED", "production stage")
    assert production["truck_id"] is None, "truck_id starts null"
    assert production["wrapped_by_user_id"] is None, "wrapped_by_user_id starts null"
    assert_labor_ledger(
        production,
        committed=0,
        available=CANONICAL_EVENT["labor_budget_total_cents"],
    )
    assert production["required_crew_positions"] == 2, (
        "required_crew_positions is 2 for a TIER_3 event"
    )
    assert production["required_validated_preps"] == 1, (
        "required_validated_preps is 1 for a TIER_3 event"
    )
    assert_instant_equals(
        production["created_at"], CLOCK_EPOCH_STAMP, "production.created_at"
    )


def test_new_production_zeroes_both_readiness_variants_and_the_settlement_fields(
    api, pm_headers
):
    """A fresh production scores 0.00 on both readiness variants and opens its
    settlement fields at zero, because no evidence and no settlement yet exist.

    PRD: "Both readiness figures, `readiness_score_preflight` and `readiness_score_certified`, are computed immediately and both start at 0 because no evidence yet exists."
    PRD: "`labor_variance_cents`, `settlement_total_cents` and `overrun_fee_cents` all start at 0 and stay at 0 until settlement writes them."
    Design: Corner/entities/production_creation_returns_declared_defaults_and_zeroed_derived_fields
    """
    production = validate_success(
        api.create_production(create_production_payload(), pm_headers), 201
    )

    assert_readiness(production, preflight=0.0, certified=0.0)
    assert production["labor_variance_cents"] == 0, "labor_variance_cents starts at 0"
    assert production["settlement_total_cents"] == 0, (
        "settlement_total_cents starts at 0"
    )
    assert production["overrun_fee_cents"] == 0, "overrun_fee_cents starts at 0"


def test_production_with_an_out_of_enum_roof_type_is_refused_at_the_schema_rung(
    api, pm_headers
):
    """`venue_roof_type` is a closed enum, so a value outside it is a malformed
    request and no production row is created.

    PRD: "The payload fixes the whole envelope at once: the `event_tier` of the broadcast (`TIER_1`, `TIER_2` or `TIER_3`), the `league_code` of the league whose operations department will co-sign rehearsal and blocking, the `venue_name` the remote originates from, the `venue_power_capacity_amps` the building can supply to the broadcast compound, the `venue_roof_type` recorded for weather-contingency planning (`OPEN`, `DOMED` or `RETRACTABLE`), the hard `venue_curfew_utc` past which the building must be dark, the `scheduled_start_utc` first-pitch or tip air instant, the `scheduled_end_utc` scheduled off-air instant, and the `labor_budget_total_cents` authorized for crew labor on this remote in cents."
    PRD: "3. **Request schema** — every required field present, types correct, enum values in range, integers within their declared bounds (`camera_channel_capacity` at least 1, `cable_run_feet` at least 1, `requested_mbps` at least 1, `duration_minutes` at least 1, `labor_budget_total_cents` at least 0, `limit` between 1 and 100 inclusive, `offset` at least 0), datetimes well-formed ISO 8601 instants, `truck_code` unique across all trucks, the remaining integer bounds respected (`venue_power_capacity_amps` at least 1, `capacity_mbps` at least 1, `service_interval_hours` at least 1, `max_concurrent_consumers` at least 1, `hourly_rate_cents` at least 1, `replay_channel_count` at least 1 when present, `offer_rate_cents` at least 1 when present, `engine_hours_since_service` at least 0, `power_draw_amps` at least 0, `guard_band_minutes` at least 0, `fiber_drops_required` at least 0, `latency_ms` at least 0, `camera_blocking_positions_cleared` at least 0) and `certified_tiers` supplied as a non-empty array, `offer_rate_cents` required when the referenced crew member's `employment_type` is `FREELANCE` and forbidden when it is `STAFF`, `replay_channel_count` required when `system_kind` is `REPLAY` and forbidden otherwise, and `venue_curfew_utc` strictly later than `scheduled_end_utc`: `ERR_INVALID_REQUEST`."
    Design: Corner/entities/production_enum_and_curfew_order_constraints_rejected
    """
    response = api.create_production(
        create_production_payload(venue_roof_type="GLASS"), pm_headers
    )
    validate_error(response, "ERR_INVALID_REQUEST")

    rows, meta = validate_paginated(api.list_productions(pm_headers))
    assert meta["total_count"] == 0, "a shape rejection creates no production row"
    assert rows == []


def test_production_curfew_not_later_than_scheduled_end_is_refused_as_schema(
    api, pm_headers
):
    """A curfew at or before the scheduled off-air instant is a schema violation,
    not a curfew-exceeded business error.

    PRD: "Two of those relationships are checked as schema: `scheduled_end_utc` must be strictly later than `scheduled_start_utc`, and `venue_curfew_utc` must be strictly later than `scheduled_end_utc`."
    PRD: "A rejected request returns exactly one error: the surviving violation with the **lowest** priority number in the ordering below."
    Design: Corner/entities/production_enum_and_curfew_order_constraints_rejected
    """
    response = api.create_production(
        create_production_payload(venue_curfew_utc="2026-08-15T21:00:00Z"), pm_headers
    )
    validate_error(response, "ERR_INVALID_REQUEST")

    _rows, meta = validate_paginated(api.list_productions(pm_headers))
    assert meta["total_count"] == 0, "a shape rejection creates no production row"


# ---------------------------------------------------------------------------
# The truck registry
# ---------------------------------------------------------------------------
def test_truck_engine_hour_fields_fall_back_to_zero_and_five_hundred(api, pm_headers):
    """A truck registered without either engine-hour field takes both declared
    defaults, derives its hours to service from them, and stands at AVAILABLE.

    PRD: "Two engine-hour fields may be supplied and both have defaults: `engine_hours_since_service`, the generator and engine hours accumulated since the last completed service, defaults to 0 and may never be negative, and `service_interval_hours`, the interval at which the unit must go into the shop, defaults to 500 and must be at least 1."
    PRD: "`last_service_completed_at` starts null and stays null until the first service is closed out."
    PRD: "A newly registered truck stands at `AVAILABLE`, and its lifecycle runs among `AVAILABLE`, `ASSIGNED`, `IN_TRANSIT` and `IN_MAINTENANCE` with no terminal state — trucks are never retired by this API."
    Design: Corner/entities/truck_optional_engine_hour_fields_take_declared_defaults
    """
    payload = create_truck_payload()
    assert "engine_hours_since_service" not in payload
    assert "service_interval_hours" not in payload

    truck = validate_success(api.create_truck(payload, pm_headers), 201)

    assert_truck(truck)
    assert_versioned_row(truck, expected_version=1)
    assert_status(truck, "AVAILABLE", "truck status")
    assert truck["engine_hours_since_service"] == 0, (
        "engine_hours_since_service defaults to 0"
    )
    assert truck["service_interval_hours"] == 500, (
        "service_interval_hours defaults to 500"
    )
    assert truck["hours_to_service"] == 500, "500 less 0 is 500"
    assert truck["last_service_completed_at"] is None, (
        "last_service_completed_at starts null"
    )


def test_truck_hours_to_service_goes_negative_once_the_unit_is_overdue(
    api, pm_headers
):
    """When the supplied engine hours have passed the interval the derived hours to
    service is negative rather than clamped at zero.

    PRD: "From those two the server maintains `hours_to_service`, which is simply `service_interval_hours` less `engine_hours_since_service` and which may reach zero or go negative once the truck is overdue."
    Design: Corner/entities/truck_optional_engine_hour_fields_take_declared_defaults
    """
    truck = validate_success(
        api.create_truck(
            create_truck_payload(
                engine_hours_since_service=620, service_interval_hours=500
            ),
            pm_headers,
        ),
        201,
    )

    assert truck["engine_hours_since_service"] == 620
    assert truck["service_interval_hours"] == 500
    assert truck["hours_to_service"] == -120, "500 less 620 is -120, not clamped"


def test_truck_listing_pages_and_reports_the_prefilter_total_count(api, pm_headers):
    """A status-filtered fleet listing applies the requested window while
    total_count still counts every row matching the filter.

    PRD: "The fleet can be listed with optional `status` and `tier_rating` filters."
    PRD: "For list responses the `meta` object carries `limit` and `offset` as applied, `total_count` giving the number of rows matching the filter before the page window is taken, and `has_more` indicating whether rows remain after the current page."
    Design: Corner/entities/truck_listing_filters_by_status_and_paginates
    """
    new_truck(api, pm_headers, truck_code="TRK-01")
    new_truck(api, pm_headers, truck_code="TRK-02")
    new_truck(api, pm_headers, truck_code="TRK-03", tier_rating="TIER_1")

    rows, meta = validate_paginated(
        api.list_trucks(pm_headers, params={"status": "AVAILABLE", "limit": 2})
    )
    assert len(rows) == 2, "the page window is applied"
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)
    assert [row["truck_code"] for row in rows] == ["TRK-01", "TRK-02"]

    tail_rows, tail_meta = validate_paginated(
        api.list_trucks(
            pm_headers, params={"status": "AVAILABLE", "limit": 2, "offset": 2}
        )
    )
    assert [row["truck_code"] for row in tail_rows] == ["TRK-03"]
    assert_pagination_meta(tail_meta, limit=2, offset=2, total_count=3, has_more=False)


def test_truck_listing_tier_rating_filter_narrows_the_fleet(api, pm_headers):
    """The tier_rating filter returns only the trucks rated at that tier and the
    omitted limit falls back to its declared default.

    PRD: "The fleet can be listed with optional `status` and `tier_rating` filters."
    PRD: "`limit` controls page size: it defaults to 10 when omitted, may be no smaller than 1 and no larger than 100."
    Design: Corner/entities/truck_listing_filters_by_status_and_paginates
    """
    new_truck(api, pm_headers, truck_code="TRK-01")
    new_truck(api, pm_headers, truck_code="TRK-02")
    premium = new_truck(
        api, pm_headers, truck_code="TRK-03", tier_rating="TIER_1",
        camera_channel_capacity=24, power_draw_amps=200, home_base_code="ATL",
    )

    rows, meta = validate_paginated(
        api.list_trucks(pm_headers, params={"tier_rating": "TIER_1"})
    )
    assert [row["id"] for row in rows] == [premium["id"]]
    assert_pagination_meta(meta, limit=10, offset=0, total_count=1, has_more=False)


def test_crew_member_read_with_an_unknown_id_returns_the_crew_member_not_found_error(
    api, pm_headers
):
    """Reading a crew member that does not exist names the crew-member rung of the
    ladder, and carries an explanatory message alongside the identifier.

    PRD: "9. **Existence of the referenced crew member**, whether named by the path or by a body `crew_member_id`: `ERR_CREW_MEMBER_NOT_FOUND`."
    PRD: "The `message` provides a human-readable explanation of what went wrong."
    Design: Corner/entities/crew_member_get_with_unknown_id_returns_not_found
    """
    hired = new_crew_member(api, pm_headers)
    assert_identity_fields(hired)

    error = validate_error(
        api.get_crew_member(UNKNOWN_UUIDS["crew_member"], pm_headers),
        "ERR_CREW_MEMBER_NOT_FOUND",
    )
    assert isinstance(error.get("message"), str) and error["message"], (
        "the error body carries a human-readable message"
    )


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
def test_moving_the_clock_governs_every_subsequently_minted_created_at(
    api, pm_headers, td_headers
):
    """Rows minted before the clock is set carry the startup instant and rows minted
    afterwards carry the instant the clock was moved to.

    PRD: "The clock's value at server startup is exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time before the clock is first set."
    PRD: "An administrative test-driving capability, open to `ProductionManager`, `TechnicalDirector`, `LeagueOperations` and `UnionSteward` alike, moves the clock to a supplied `to_iso8601` instant; a malformed instant is refused with `ERR_INVALID_TIME_WINDOW` (HTTP 422)."
    Design: Corner/endpoints/clock_endpoint_sets_the_logical_time_used_for_every_stamp
    """
    before = new_truck(api, pm_headers, truck_code="TRK-01")
    assert_instant_equals(before["created_at"], CLOCK_EPOCH_STAMP, "truck.created_at")

    validate_success(api.set_clock("2026-08-05T09:30:00Z", td_headers), 200)

    after = new_truck(api, pm_headers, truck_code="TRK-02")
    assert_instant_equals(
        after["created_at"], "2026-08-05T09:30:00.000Z", "truck.created_at"
    )
    production = new_production(api, pm_headers)
    assert_instant_equals(
        production["created_at"], "2026-08-05T09:30:00.000Z", "production.created_at"
    )


def test_malformed_clock_instant_is_refused_and_leaves_the_clock_where_it_was(
    api, pm_headers, td_headers
):
    """A clock move whose instant is not a well-formed ISO 8601 value is refused as an
    invalid time window, and the clock still reads its startup value afterwards.

    PRD: "An administrative test-driving capability, open to `ProductionManager`, `TechnicalDirector`, `LeagueOperations` and `UnionSteward` alike, moves the clock to a supplied `to_iso8601` instant; a malformed instant is refused with `ERR_INVALID_TIME_WINDOW` (HTTP 422)."
    PRD: "The clock's value at server startup is exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time before the clock is first set."
    Design: Corner/endpoints/clock_endpoint_sets_the_logical_time_used_for_every_stamp
    """
    validate_error(
        api.set_clock_raw({"to_iso8601": "2026-08-05 09:30 PST"}, td_headers),
        "ERR_INVALID_TIME_WINDOW",
    )

    truck = new_truck(api, pm_headers, truck_code="TRK-09")
    assert_instant_equals(
        truck["created_at"], CLOCK_EPOCH_STAMP, "truck.created_at after a refused move"
    )


# ---------------------------------------------------------------------------
# The production list surface
# ---------------------------------------------------------------------------
def test_production_listing_filters_by_truck_and_by_tier_and_composes_the_two(
    api, pm_headers
):
    """Each declared production filter narrows the list on its own, and supplying two
    that select disjoint rows returns an empty page rather than their union.

    PRD: "The list view can be narrowed by `truck_id` to see everything a given truck is holding, by `status` to see everything at a given stage, and by `event_tier`."
    PRD: "For list responses the `meta` object carries `limit` and `offset` as applied, `total_count` giving the number of rows matching the filter before the page window is taken, and `has_more` indicating whether rows remain after the current page."
    Design: Corner/endpoints/production_listing_filters_compose_across_truck_and_tier
    """
    truck = new_truck(api, pm_headers, truck_code="TRK-01")
    held = new_production(api, pm_headers)
    top_tier = new_production(api, pm_headers, event_tier="TIER_1")
    new_production(api, pm_headers, event_tier="TIER_2")

    assign_truck(api, held["id"], truck["id"])
    assert read_production(api, held["id"])["truck_id"] == truck["id"]

    by_truck, by_truck_meta = validate_paginated(
        api.list_productions(pm_headers, params={"truck_id": truck["id"]})
    )
    assert [row["id"] for row in by_truck] == [held["id"]]
    assert_pagination_meta(by_truck_meta, total_count=1, has_more=False)

    by_tier, by_tier_meta = validate_paginated(
        api.list_productions(pm_headers, params={"event_tier": "TIER_1"})
    )
    assert [row["id"] for row in by_tier] == [top_tier["id"]]
    assert_pagination_meta(by_tier_meta, total_count=1, has_more=False)

    composed, composed_meta = validate_paginated(
        api.list_productions(
            pm_headers, params={"truck_id": truck["id"], "event_tier": "TIER_1"}
        )
    )
    assert composed == [], "the two filters are conjunctive, not a union"
    assert_pagination_meta(composed_meta, total_count=0, has_more=False)


def test_production_status_filter_pages_in_created_at_order(api, pm_headers):
    """A status-filtered production page is windowed but still ordered by creation and
    still reports the whole filtered total.

    PRD: "The list view can be narrowed by `truck_id` to see everything a given truck is holding, by `status` to see everything at a given stage, and by `event_tier`."
    PRD: "Unless a subsection states otherwise, every list endpoint returns its rows ordered by `created_at` ascending, so pagination is stable as new rows are appended."
    Design: Corner/endpoints/production_listing_filters_compose_across_truck_and_tier
    """
    first = new_production(api, pm_headers, venue_name="Arena One")
    second = new_production(api, pm_headers, venue_name="Arena Two")
    third = new_production(api, pm_headers, venue_name="Arena Three")

    head, head_meta = validate_paginated(
        api.list_productions(pm_headers, params={"status": "PLANNED", "limit": 2})
    )
    assert [row["id"] for row in head] == [first["id"], second["id"]]
    assert_created_at_ascending(head)
    assert_pagination_meta(head_meta, limit=2, offset=0, total_count=3, has_more=True)

    tail, tail_meta = validate_paginated(
        api.list_productions(
            pm_headers, params={"status": "PLANNED", "limit": 2, "offset": 2}
        )
    )
    assert [row["id"] for row in tail] == [third["id"]]
    assert_pagination_meta(tail_meta, limit=2, offset=2, total_count=3, has_more=False)


# ---------------------------------------------------------------------------
# Offering a call without its call time
# ---------------------------------------------------------------------------
def test_crew_call_without_a_call_time_is_refused_and_writes_nothing(api, pm_headers):
    """`call_time_utc` is one of the call's required inputs, so omitting it is a
    malformed request that creates no call and leaves the production untouched.

    PRD: "Offering a call names the `production_id`, the `crew_member_id`, the `call_time_utc` at which the member is called to the compound, the `scheduled_release_utc` at which they are expected to be released, an optional `offer_rate_cents`, and `expected_production_version`."
    PRD: "3. **Request schema** — every required field present, types correct, enum values in range, integers within their declared bounds (`camera_channel_capacity` at least 1, `cable_run_feet` at least 1, `requested_mbps` at least 1, `duration_minutes` at least 1, `labor_budget_total_cents` at least 0, `limit` between 1 and 100 inclusive, `offset` at least 0), datetimes well-formed ISO 8601 instants, `truck_code` unique across all trucks, the remaining integer bounds respected (`venue_power_capacity_amps` at least 1, `capacity_mbps` at least 1, `service_interval_hours` at least 1, `max_concurrent_consumers` at least 1, `hourly_rate_cents` at least 1, `replay_channel_count` at least 1 when present, `offer_rate_cents` at least 1 when present, `engine_hours_since_service` at least 0, `power_draw_amps` at least 0, `guard_band_minutes` at least 0, `fiber_drops_required` at least 0, `latency_ms` at least 0, `camera_blocking_positions_cleared` at least 0) and `certified_tiers` supplied as a non-empty array, `offer_rate_cents` required when the referenced crew member's `employment_type` is `FREELANCE` and forbidden when it is `STAFF`, `replay_channel_count` required when `system_kind` is `REPLAY` and forbidden otherwise, and `venue_curfew_utc` strictly later than `scheduled_end_utc`: `ERR_INVALID_REQUEST`."
    Design: Corner/entities/crew_call_missing_required_call_time_rejected
    """
    production = new_production(api, pm_headers)
    member = new_crew_member(api, pm_headers)

    payload = create_crew_call_payload(
        production["id"], member["id"], production["version"]
    )
    del payload["call_time_utc"]

    validate_error(api.create_crew_call(payload, pm_headers), "ERR_INVALID_REQUEST")

    _rows, meta = validate_paginated(api.list_crew_calls(pm_headers))
    assert meta["total_count"] == 0, "a refused offer creates no crew call row"
    after = read_production(api, production["id"])
    assert after["version"] == production["version"], (
        "a refused offer does not bump the production version"
    )
    assert_labor_ledger(
        after, committed=0, available=CANONICAL_EVENT["labor_budget_total_cents"]
    )


# ---------------------------------------------------------------------------
# Pagination bounds
# ---------------------------------------------------------------------------
def test_limit_outside_one_through_one_hundred_is_refused_rather_than_clamped(
    api, pm_headers
):
    """A page size above the ceiling or below the floor is a malformed request, and
    the ceiling itself is still accepted.

    PRD: "`limit` controls page size: it defaults to 10 when omitted, may be no smaller than 1 and no larger than 100."
    PRD: "A `limit` outside the range of 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped."
    Design: Corner/errors/pagination_bounds_outside_their_range_rejected
    """
    new_production(api, pm_headers)

    validate_error(
        api.list_productions(pm_headers, params={"limit": 101}), "ERR_INVALID_REQUEST"
    )
    validate_error(
        api.list_productions(pm_headers, params={"limit": 0}), "ERR_INVALID_REQUEST"
    )
    validate_error(
        api.list_trucks(pm_headers, params={"limit": 101}), "ERR_INVALID_REQUEST"
    )

    rows, meta = validate_paginated(
        api.list_productions(pm_headers, params={"limit": 100})
    )
    assert len(rows) == 1
    assert_pagination_meta(meta, limit=100, offset=0, total_count=1, has_more=False)


def test_negative_offset_is_refused_while_a_zero_offset_is_accepted(api, pm_headers):
    """A negative page offset is malformed, and the smallest legal offset still works.

    PRD: "A `limit` outside the range of 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped."
    PRD: "`offset` controls the starting position: it defaults to 0 and may be no smaller than 0."
    Design: Corner/errors/pagination_bounds_outside_their_range_rejected
    """
    new_truck(api, pm_headers, truck_code="TRK-01")

    validate_error(
        api.list_trucks(pm_headers, params={"offset": -1}), "ERR_INVALID_REQUEST"
    )
    validate_error(
        api.list_productions(pm_headers, params={"offset": -5}), "ERR_INVALID_REQUEST"
    )

    rows, meta = validate_paginated(api.list_trucks(pm_headers, params={"offset": 0}))
    assert len(rows) == 1
    assert_pagination_meta(meta, limit=10, offset=0, total_count=1, has_more=False)


# ---------------------------------------------------------------------------
# Entity-specific not-found errors
# ---------------------------------------------------------------------------
def test_unknown_top_level_ids_return_each_entity_own_not_found_error(api, pm_headers, td_headers):
    """Reading a production, a truck or a venue survey by an id that was never minted
    returns that entity's own not-found identifier, not a shared generic one.

    PRD: "4. **Existence of the referenced production**, whether named by the path or by a body `production_id`: `ERR_PRODUCTION_NOT_FOUND`."
    PRD: "5. **Existence of the referenced truck**, whether named by the path or by a body `truck_id`: `ERR_TRUCK_NOT_FOUND`."
    PRD: "6. **Existence of the referenced venue survey**: `ERR_SURVEY_NOT_FOUND`."
    Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found
    """
    validate_error(
        api.get_production(UNKNOWN_UUIDS["production"], pm_headers),
        "ERR_PRODUCTION_NOT_FOUND",
    )
    validate_error(
        api.get_truck(UNKNOWN_UUIDS["truck"], pm_headers), "ERR_TRUCK_NOT_FOUND"
    )
    validate_error(
        api.get_venue_survey(UNKNOWN_UUIDS["survey"], td_headers),
        "ERR_SURVEY_NOT_FOUND",
    )


def test_unknown_subresource_parent_reports_the_parent_not_found_error(api, td_headers):
    """A camera-plot listing under a survey id that does not exist is answered with the
    survey's not-found error, because the parent is resolved before the child segment.

    PRD: "If the parent named by the first path segment does not exist, the response is that parent's not-found error — `ERR_PRODUCTION_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND` or `ERR_SHOW_NOT_FOUND` as appropriate — and the child segment is never examined."
    Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found
    """
    validate_error(
        api.list_camera_positions(UNKNOWN_UUIDS["survey"], td_headers),
        "ERR_SURVEY_NOT_FOUND",
    )
    validate_error(
        api.list_production_venue_surveys(UNKNOWN_UUIDS["production"], td_headers),
        "ERR_PRODUCTION_NOT_FOUND",
    )


def test_unknown_operational_child_ids_return_their_own_not_found_errors(
    api, pm_headers, td_headers
):
    """Path bookings, crew calls, data feeds, system preps and rehearsals each answer an
    unknown identifier with their own rung of the not-found ladder.

    PRD: "8. **Existence of the referenced path booking**: `ERR_BOOKING_NOT_FOUND`."
    PRD: "10. **Existence of the referenced crew call**: `ERR_CREW_CALL_NOT_FOUND`."
    PRD: "11. **Existence of the referenced data feed**, whether named by the path or by a body `data_feed_id`: `ERR_FEED_NOT_FOUND`."
    PRD: "12. **Existence of the referenced system prep**: `ERR_PREP_NOT_FOUND`."
    PRD: "13. **Existence of the referenced rehearsal**: `ERR_REHEARSAL_NOT_FOUND`."
    Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found
    """
    validate_error(
        api.get_path_booking(UNKNOWN_UUIDS["booking"], td_headers),
        "ERR_BOOKING_NOT_FOUND",
    )
    validate_error(
        api.get_crew_call(UNKNOWN_UUIDS["crew_call"], pm_headers),
        "ERR_CREW_CALL_NOT_FOUND",
    )
    validate_error(
        api.get_data_feed(UNKNOWN_UUIDS["feed"], td_headers), "ERR_FEED_NOT_FOUND"
    )
    validate_error(
        api.get_system_prep(UNKNOWN_UUIDS["prep"], td_headers), "ERR_PREP_NOT_FOUND"
    )
    validate_error(
        api.get_rehearsal(UNKNOWN_UUIDS["rehearsal"], td_headers),
        "ERR_REHEARSAL_NOT_FOUND",
    )
