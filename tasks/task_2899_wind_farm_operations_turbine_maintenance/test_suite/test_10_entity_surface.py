"""The declared entity surface: openings, defaults, rollups, reads and listings."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers.assertions import (
    assert_common_fields,
    assert_envelope_meta,
    assert_error_envelope_is_minimal,
    assert_farm_buckets,
    assert_millisecond_precision,
    assert_page,
    assert_single_read_omits_pagination,
    assert_total_count,
    assert_turbine_dimensions,
    assert_two_dp,
    assert_version_unchanged,
)
from test_helpers.constants import (
    AVAILABILITY_DECOMMISSIONED,
    AVAILABILITY_ONLINE,
    CERT_CRANE_BANKSMAN,
    CERT_GWO_BASIC,
    COMPONENT_GEARBOX,
    CREW_AVAILABLE,
    CURTAILMENT_FORCED_STOP,
    CURTAILMENT_UNCONSTRAINED,
    PATH_CRANE_LIFT,
    REPLACEMENT_CRANE_RESERVED,
    WORK_TYPE_MAJOR_COMPONENT,
)
from test_helpers.factories import (
    crew_payload,
    curtailment_payload,
    farm_payload,
    replacement_payload,
    turbine_payload,
    weather_window_payload,
    work_order_payload,
)
from test_helpers.fixtures import (
    create_crew,
    create_farm,
    create_model,
    create_turbine,
    read_farm,
    read_replacement,
    read_spare_part,
    read_turbine,
    read_work_order,
    setup_junction_graph,
    setup_levied_read_back_site,
    setup_three_turbine_farm,
    setup_two_model_farm,
)
from test_helpers.test_users import (
    make_commercial_headers,
    make_control_room_headers,
    make_planner_headers,
    make_site_admin_headers,
)


def test_a_commissioned_turbine_opens_every_declared_field_at_its_declared_value(api):
    """Eighteen system and computed fields, each at the opening the contract names.

    The contract states: "Commissioning a turbine places it on a farm — the farm is
    taken from the creation path, and the turbine's `wind_farm_id` is set from that
    segment rather than from the body."  Of the openings it states: "Commissioning sets
    `availability_state` to `ONLINE` and `curtailment_state` to `UNCONSTRAINED`, sets
    `active_curtailment_count` to 0 and `effective_power_limit_kw` to the model's
    `rated_power_kw`, computes the three service-due figures described in the next
    subsection, increments the farm's `turbine_count` by 1 and adds the model's
    `rated_power_kw` to the farm's `installed_capacity_kw`."  It continues: "Two
    counters may optionally be seeded at commissioning: `operating_hours`, the
    cumulative operating hours which otherwise starts at 0 and thereafter is advanced
    only by SCADA telemetry, and `last_service_operating_hours`, the operating-hours
    reading recorded at the most recent completed scheduled service, which otherwise
    also starts at 0."  And: "The turbine's remaining counters begin at their zero
    values: `active_fault_code` is null, `remote_reset_count_24h` is 0,
    `reset_window_start_utc` is null until the first remote reset, and
    `period_actual_energy_kwh`, `period_potential_energy_kwh`,
    `counted_downtime_hours_period` and `cumulative_lost_energy_kwh` are all 0."  Of the
    derived figures it states: "`service_due_operating_hours` is the turbine's
    `last_service_operating_hours` plus the model's `service_interval_hours`."  And:
    "`service_due_flag` is true when the turbine's `operating_hours` has reached or
    passed `service_due_operating_hours`, using an at-or-above comparison."  And:
    "Endpoints that bring a new resource into existence answer with HTTP 201; every
    other successful call — state transitions, telemetry posts, amendments, retrievals
    and list reads — answers with HTTP 200."

    Design: Corner/entities/turbine_creation_returns_every_declared_field_with_its_system_defaults_at_201
    """
    farm = create_farm(
        api,
        name="Elk Basin",
        region_code="MT-E",
        grid_operator_code="NWMT",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )
    model = create_model(api, model_code="V150-4.2", rated_power_kw=4200)

    response = api.create_turbine(
        farm["id"],
        turbine_payload(
            model["id"],
            asset_tag="T-07",
            commissioning_date="2024-03-15",
            expected_kwh_per_hour=2000,
        ),
        make_site_admin_headers(),
    )
    turbine = validate_success(response, 201)
    assert_envelope_meta(response)
    assert_common_fields(turbine, expected_version=1)

    assert turbine["wind_farm_id"] == farm["id"]
    assert turbine["turbine_model_id"] == model["id"]
    assert_turbine_dimensions(
        turbine,
        availability_state=AVAILABILITY_ONLINE,
        curtailment_state=CURTAILMENT_UNCONSTRAINED,
    )

    assert_two_dp(turbine["operating_hours"], 0, "turbine.operating_hours")
    assert_two_dp(
        turbine["last_service_operating_hours"], 0, "turbine.last_service_operating_hours"
    )
    assert_two_dp(
        turbine["service_due_operating_hours"], 4000, "turbine.service_due_operating_hours"
    )
    assert turbine["service_due_flag"] is False
    assert turbine["service_interval_breached"] is False

    assert turbine["active_fault_code"] is None
    assert turbine["remote_reset_count_24h"] == 0
    assert turbine["reset_window_start_utc"] is None

    assert turbine["active_curtailment_count"] == 0
    assert turbine["effective_power_limit_kw"] == 4200

    assert_two_dp(turbine["period_actual_energy_kwh"], 0, "turbine.period_actual_energy_kwh")
    assert_two_dp(
        turbine["period_potential_energy_kwh"], 0, "turbine.period_potential_energy_kwh"
    )
    assert_two_dp(
        turbine["counted_downtime_hours_period"], 0, "turbine.counted_downtime_hours_period"
    )
    assert_two_dp(
        turbine["cumulative_lost_energy_kwh"], 0, "turbine.cumulative_lost_energy_kwh"
    )

    parent = read_farm(api, farm["id"])
    assert parent["turbine_count"] == 1
    assert parent["installed_capacity_kw"] == 4200


def test_two_reads_return_the_stored_rows_inside_the_success_envelope(api):
    """The persisted values come back unchanged, wrapped, and without page controls.

    The contract states: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."  It continues: "The `api_request_timestamp`
    is a server-generated ISO 8601 UTC timestamp with three fractional digits."  Of a
    single read it states: "Single-resource reads omit those four fields from `meta`."
    Of the two levy percentages it states: "Both are optional on the creation request;
    when `road_levy_pct` is omitted it defaults to 2.5, and when `community_levy_pct` is
    omitted it defaults to 1.5."  Of the version counter it states: "A read never
    advances `version`."  And of the rollups: "`turbine_count` is the count of the
    farm's turbines whose `availability_state` is anything other than `DECOMMISSIONED`,
    and `installed_capacity_kw` is the sum of `rated_power_kw` over that same set of
    turbines — both recomputed whenever a turbine joins or leaves service."

    Design: Corner/entities/farm_and_turbine_reads_return_exactly_the_stored_row
    """
    site = setup_levied_read_back_site(api)

    farm_response = api.get_farm(site["farm"]["id"], make_commercial_headers())
    assert_envelope_meta(farm_response)
    farm = assert_single_read_omits_pagination(farm_response)
    assert farm_response.status_code == 200

    assert_two_dp(farm["road_levy_pct"], 3.25, "farm.road_levy_pct")
    assert_two_dp(farm["community_levy_pct"], 0.75, "farm.community_levy_pct")
    assert farm["landowner_budget_cap_cents"] == 250000000
    assert farm["turbine_count"] == 1
    assert farm["installed_capacity_kw"] == 4200
    assert_version_unchanged(farm, read_farm(api, site["farm"]["id"]))

    turbine_response = api.get_turbine(site["turbine"]["id"], make_control_room_headers())
    assert_envelope_meta(turbine_response)
    turbine = assert_single_read_omits_pagination(turbine_response)
    assert turbine_response.status_code == 200

    assert turbine["asset_tag"] == "T-07"
    assert turbine["expected_kwh_per_hour"] == 2000
    assert turbine["version"] == 1
    assert turbine["commissioning_date"] == "2024-03-15"
    assert_version_unchanged(site["turbine"], turbine)


def test_the_turbine_listing_reports_the_filtered_total_and_the_continuation_flag(api):
    """Three rows, a two-row window, and a filter that matches nothing.

    The contract states: "`limit` controls page size: it defaults to 10 when omitted,
    its minimum accepted value is 1 and its maximum accepted value is 100."  Of the
    listing metadata it states: "The `meta` object of a list response carries `limit`,
    `offset`, `total_count` and `has_more`, where `total_count` is the number of rows
    matching the filters before the page window is applied and `has_more` is true
    exactly when rows remain beyond the current page."  Of ordering it states: "List
    results are ordered by `created_at` ascending unless a subsection below states
    otherwise for a specific collection."  And of combining filters: "Filters named on a
    list endpoint combine conjunctively — a request naming both a farm filter and a
    state filter returns only the rows matching both."

    Design: Corner/entities/turbine_listing_defaults_to_ten_rows_then_honours_limit_offset_and_state_filters
    """
    site = setup_three_turbine_farm(api)
    farm_id = site["farm"]["id"]
    headers = make_planner_headers()

    unpaged = api.list_turbines(headers, wind_farm_id=farm_id)
    assert_envelope_meta(unpaged, response_type="array")
    rows = assert_page(unpaged, 3, 3, False)
    assert {row["asset_tag"] for row in rows} == {"T-01", "T-02", "T-03"}
    assert unpaged.json()["meta"]["limit"] == 10
    assert unpaged.json()["meta"]["offset"] == 0

    first_page = api.list_turbines(headers, wind_farm_id=farm_id, limit=2, offset=0)
    page_one = assert_page(first_page, 2, 3, True)
    assert first_page.json()["meta"]["limit"] == 2
    assert first_page.json()["meta"]["offset"] == 0

    second_page = api.list_turbines(headers, wind_farm_id=farm_id, limit=2, offset=2)
    page_two = assert_page(second_page, 1, 3, False)
    assert second_page.json()["meta"]["offset"] == 2

    windowed = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(windowed)) == 3
    assert set(windowed) == {row["id"] for row in rows}

    filtered = api.list_turbines(
        headers, wind_farm_id=farm_id, curtailment_state=CURTAILMENT_FORCED_STOP
    )
    assert filtered.status_code == 200
    assert_page(filtered, 0, 0, False)


def test_an_unknown_turbine_path_segment_uses_the_turbine_specific_not_found_code(api):
    """The dedicated code wins over the generic path-resource one, at 404.

    The contract states: "Path identifiers resolve strictly left to right, and the first
    segment that fails to resolve determines the error."  It continues: "Four collections
    have dedicated not-found identifiers: a farm identifier that does not resolve yields
    `ERR_FARM_NOT_FOUND`, a turbine identifier yields `ERR_TURBINE_NOT_FOUND`, a
    work-order identifier yields `ERR_WORK_ORDER_NOT_FOUND`, and a fault-event identifier
    yields `ERR_FAULT_EVENT_NOT_FOUND`."  And: "All five carry HTTP 404."  Of the error
    body it states: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."  And: "The `message` provides a human-readable explanation of
    what went wrong."  And: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/turbine_get_with_an_unknown_uuid_returns_turbine_not_found
    """
    response = api.get_turbine(NON_EXISTENT_UUID, make_control_room_headers())
    validate_error(response, "ERR_TURBINE_NOT_FOUND", 404)
    assert_error_envelope_is_minimal(response)

    body = response.json()
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip() != ""
    assert body["meta"]["api_request_id"].startswith("req_")


def test_a_crew_registered_without_certifications_is_refused_and_stores_nothing(api):
    """The array is a required input, so its absence is a shape failure, not an empty list.

    The contract states: "A crew is registered with the `wind_farm_id` of the site it
    belongs to, a `crew_code` unique within that farm, a `technician_count` of at least
    1, and a non-empty `certifications` array drawn from `GWO_BASIC`, `ROPE_ACCESS`,
    `HV_SWITCHING`, `CRANE_BANKSMAN` and `BLADE_COMPOSITE`."  Of the shape rung it
    states: "**Request shape.** The body must parse as JSON; every required input field
    must be present and non-null; every enum-typed field must carry a declared member;
    every numeric field must fall inside its declared range; every timestamp must be a
    valid ISO-8601 instant with a `Z` offset; and on every interval field pair the end
    bound must be strictly after the start bound."  It continues: "Any violation yields
    `ERR_INVALID_REQUEST`."  And: "A rejected request writes nothing at all — no counter
    moves, no `version` advances, no partial cascade survives."

    Design: Corner/entities/crew_create_missing_required_certifications_returns_invalid_request
    """
    farm = create_farm(
        api,
        name="Elk Basin",
        region_code="MT-E",
        grid_operator_code="NWMT",
        road_levy_pct=2.5,
        community_levy_pct=1.5,
        landowner_budget_cap_cents=500000000,
    )

    payload = crew_payload(
        farm["id"],
        crew_code="C-DELTA",
        technician_count=3,
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=24,
        hourly_rate_cents=90000,
    )
    payload.pop("certifications")

    refused = api.create_crew(payload, make_site_admin_headers())
    validate_error(refused, "ERR_INVALID_REQUEST", 400)

    assert_total_count(api.list_crews(make_site_admin_headers(), wind_farm_id=farm["id"]), 0)


def test_three_omitted_inputs_on_three_entities_fall_back_to_their_declared_defaults(api):
    """Levies, opening hour readings and crew status all default, and the derivation runs.

    The contract states: "Both are optional on the creation request; when
    `road_levy_pct` is omitted it defaults to 2.5, and when `community_levy_pct` is
    omitted it defaults to 1.5."  Of the turbine's two seedable counters it states: "Two
    counters may optionally be seeded at commissioning: `operating_hours`, the cumulative
    operating hours which otherwise starts at 0 and thereafter is advanced only by SCADA
    telemetry, and `last_service_operating_hours`, the operating-hours reading recorded
    at the most recent completed scheduled service, which otherwise also starts at 0."
    Of the derived figure it states: "`service_due_operating_hours` is the turbine's
    `last_service_operating_hours` plus the model's `service_interval_hours`."  And of
    the crew: "The crew's `status` may optionally be supplied at registration and
    defaults to `AVAILABLE`; only `AVAILABLE` and `OFF_ROTATION` are accepted as input
    values."

    Design: Corner/entities/farm_levies_and_turbine_hour_counters_fall_back_to_declared_defaults
    """
    model = create_model(api, model_code="V150-4.2", service_interval_hours=4000)

    farm = validate_success(
        api.create_farm(
            farm_payload(
                name="Elk Basin",
                region_code="MT-E",
                grid_operator_code="NWMT",
                landowner_budget_cap_cents=500000000,
            ),
            make_site_admin_headers(),
        ),
        201,
    )
    assert_two_dp(farm["road_levy_pct"], 2.5, "farm.road_levy_pct")
    assert_two_dp(farm["community_levy_pct"], 1.5, "farm.community_levy_pct")

    turbine = create_turbine(
        api,
        farm["id"],
        model["id"],
        asset_tag="T-01",
        commissioning_date="2024-03-15",
        expected_kwh_per_hour=2000,
    )
    assert_two_dp(turbine["operating_hours"], 0, "turbine.operating_hours")
    assert_two_dp(
        turbine["last_service_operating_hours"], 0, "turbine.last_service_operating_hours"
    )
    assert_two_dp(
        turbine["service_due_operating_hours"], 4000, "turbine.service_due_operating_hours"
    )

    crew = create_crew(
        api,
        farm["id"],
        crew_code="C-DELTA",
        technician_count=3,
        certifications=[CERT_GWO_BASIC],
        max_work_wind_speed_ms=14.0,
        daily_hours_capacity=24,
        hourly_rate_cents=90000,
    )
    assert crew["status"] == CREW_AVAILABLE


def test_both_farm_rollups_are_recomputed_from_the_live_turbine_set_on_a_decommission(api):
    """Two differently rated models sum to 7000, then fall to 4200 with no refresh call.

    The contract states: "`turbine_count` is the count of the farm's turbines whose
    `availability_state` is anything other than `DECOMMISSIONED`, and
    `installed_capacity_kw` is the sum of `rated_power_kw` over that same set of turbines
    — both recomputed whenever a turbine joins or leaves service."  Of the retirement it
    states: "Retiring a turbine is a `SiteAdmin` action that carries a
    `decommission_reason` and drives the availability dimension `ONLINE →
    DECOMMISSIONED`."  It continues: "It then decrements the farm's `turbine_count` by 1
    and subtracts the model's `rated_power_kw` from the farm's `installed_capacity_kw`,
    and from that moment the turbine is excluded from every availability denominator and
    from every landowner metered-energy sum."

    Design: Corner/entities/farm_turbine_count_and_installed_capacity_are_computed_from_the_live_turbine_set
    """
    site = setup_two_model_farm(api)

    before = read_farm(api, site["farm"]["id"])
    assert before["turbine_count"] == 2
    assert before["installed_capacity_kw"] == 7000

    retired = validate_success(
        api.decommission_turbine(
            site["t2"]["id"], "gearbox beyond economic repair", make_site_admin_headers()
        )
    )
    assert_turbine_dimensions(retired, availability_state=AVAILABILITY_DECOMMISSIONED)

    after = read_farm(api, site["farm"]["id"])
    assert after["turbine_count"] == 1
    assert after["installed_capacity_kw"] == 4200

    survivor = read_turbine(api, site["t1"]["id"])
    assert_turbine_dimensions(survivor, availability_state=AVAILABILITY_ONLINE)
    assert_version_unchanged(site["t1"], survivor)


def test_a_farm_create_supplying_system_fields_discards_every_one_of_them(api):
    """The identifier, the insertion instant, the version and the ledger are all server-owned.

    The contract states: "Every resource carries a server-minted `id` that is a UUID
    string with no type prefix, and a `created_at` timestamp recording when the row was
    inserted."  It continues: "Clients never supply `id` and never supply `created_at`."
    Of the timestamp format it states: "Timestamps are ISO 8601 in UTC with exactly three
    fractional-second digits, for example `2026-08-01T00:00:00.000Z`."  Of the version
    counter it states: "`updated_at` is refreshed on every mutation of the row, and
    `version` starts at 1 when the row is created and increments by exactly 1 on every
    mutation of that row, including mutations that reach the row by cascade from an
    operation that named a different resource."  And of the opening ledger: "A newly
    registered farm starts every derived and accumulating figure at zero: `turbine_count`
    and `installed_capacity_kw` at 0, and each of `landowner_payable_cents`,
    `road_maintenance_reserve_cents`, `community_fund_balance_cents`,
    `maintenance_spend_cents` and `opex_accrued_cents` at 0."

    Design: Corner/entities/farm_create_system_fields_input_ignored
    """
    supplied_id = "99999999-8888-7777-6666-555555555555"
    response = api.create_farm(
        farm_payload(
            name="Elk Basin",
            region_code="MT-E",
            grid_operator_code="NWMT",
            landowner_budget_cap_cents=500000000,
            id=supplied_id,
            created_at="2000-01-01T00:00:00.000Z",
            version=47,
            opex_accrued_cents=123456,
        ),
        make_site_admin_headers(),
    )
    farm = validate_success(response, 201)

    assert farm["id"] != supplied_id
    assert_common_fields(farm, expected_version=1)
    assert farm["created_at"] != "2000-01-01T00:00:00.000Z"
    assert_millisecond_precision(farm["created_at"])
    assert_millisecond_precision(farm["updated_at"])

    assert farm["turbine_count"] == 0
    assert farm["installed_capacity_kw"] == 0
    assert_farm_buckets(
        farm,
        opex_accrued_cents=0,
        landowner_payable_cents=0,
        road_maintenance_reserve_cents=0,
        community_fund_balance_cents=0,
        maintenance_spend_cents=0,
    )
    assert_farm_buckets(read_farm(api, farm["id"]), opex_accrued_cents=0)


def test_an_equal_bound_interval_and_an_undeclared_enum_are_both_refused_before_any_write(api):
    """Shape rules fire before the overlap search and before the version comparison.

    The contract states: "On every one of these pairs the end bound must be strictly
    after the start bound; a request violating that is rejected with
    `ERR_INVALID_REQUEST`."  Of the shape rung it states: "**Request shape.** The body
    must parse as JSON; every required input field must be present and non-null; every
    enum-typed field must carry a declared member; every numeric field must fall inside
    its declared range; every timestamp must be a valid ISO-8601 instant with a `Z`
    offset; and on every interval field pair the end bound must be strictly after the
    start bound."  Of the curtailment reason it states: "A `ControlRoomOperator` issues an
    order against a turbine with a `reason` of `GRID`, `NOISE`, `ICING` or `WILDLIFE`, an
    inclusive `start_utc`, an exclusive `end_utc` strictly after it, a `power_limit_kw` of
    at least 0 giving the power cap while the order is in force, and a
    `deemed_kwh_per_hour` of at least 0 giving the deemed generation rate used for
    landowner royalty."  And of a refusal: "A rejected request writes nothing at all — no
    counter moves, no `version` advances, no partial cascade survives."

    Design: Corner/entities/weather_window_create_rejects_a_non_strict_interval_and_an_undeclared_enum
    """
    site = setup_levied_read_back_site(api)
    turbine_id = site["turbine"]["id"]
    before = read_turbine(api, turbine_id)

    equal_bounds = api.create_weather_window(
        weather_window_payload(
            site["farm"]["id"],
            start_utc="2026-08-10T06:00:00Z",
            end_utc="2026-08-10T06:00:00Z",
            forecast_wind_speed_ms=8.0,
            forecast_gust_ms=11.0,
            icing_risk=False,
        ),
        make_planner_headers(),
    )
    validate_error(equal_bounds, "ERR_INVALID_REQUEST", 400)

    undeclared_reason = api.create_curtailment_order(
        turbine_id,
        curtailment_payload(
            before["version"],
            reason="MAINTENANCE",
            start_utc="2026-08-01T00:00:00Z",
            end_utc="2026-08-01T06:00:00Z",
            power_limit_kw=1500,
            deemed_kwh_per_hour=500,
        ),
        make_control_room_headers(),
    )
    validate_error(undeclared_reason, "ERR_INVALID_REQUEST", 400)

    assert_version_unchanged(before, read_turbine(api, turbine_id))
    assert_total_count(
        api.list_weather_windows(make_planner_headers(), wind_farm_id=site["farm"]["id"]), 0
    )
    assert_total_count(
        api.list_curtailment_orders(make_control_room_headers(), turbine_id=turbine_id), 0
    )


def test_an_unknown_farm_in_the_creation_path_reports_the_farm_specific_code(api):
    """The path segment is resolved first, so a valid body reference cannot rescue it.

    The contract states: "Path identifiers resolve strictly left to right, and the first
    segment that fails to resolve determines the error."  It continues: "Four collections
    have dedicated not-found identifiers: a farm identifier that does not resolve yields
    `ERR_FARM_NOT_FOUND`, a turbine identifier yields `ERR_TURBINE_NOT_FOUND`, a
    work-order identifier yields `ERR_WORK_ORDER_NOT_FOUND`, and a fault-event identifier
    yields `ERR_FAULT_EVENT_NOT_FOUND`."  And: "Foreign-key identifiers supplied inside a
    request body are resolved after every path segment has resolved, and a body identifier
    that names no existing row yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."  And:
    "Commissioning a turbine places it on a farm — the farm is taken from the creation
    path, and the turbine's `wind_farm_id` is set from that segment rather than from the
    body."

    Design: Corner/entities/turbine_create_under_an_unknown_farm_returns_farm_not_found
    """
    model = create_model(api, model_code="V150-4.2")

    refused = api.create_turbine(
        NON_EXISTENT_UUID,
        turbine_payload(
            model["id"],
            asset_tag="T-01",
            commissioning_date="2024-03-15",
            expected_kwh_per_hour=2000,
        ),
        make_site_admin_headers(),
    )
    validate_error(refused, "ERR_FARM_NOT_FOUND", 404)
    assert_error_envelope_is_minimal(refused)

    assert_total_count(api.list_turbines(make_site_admin_headers()), 0)


def test_an_unknown_body_turbine_reference_reports_the_generic_reference_code(api):
    """The same missing UUID reads differently in a body than in a path segment.

    The contract states: "Foreign-key identifiers supplied inside a request body are
    resolved after every path segment has resolved, and a body identifier that names no
    existing row yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."  It continues: "This covers
    `turbine_id`, `turbine_model_id`, `fault_code_rule_id`, `crew_id`,
    `weather_window_id`, `spare_part_id`, `crane_mobilization_id`, `blade_damage_id`,
    `fault_event_id` and `parent_work_order_id`."  Of the ordering it states: "When a
    single request violates more than one rule, the response must carry the error
    belonging to the earliest rung of the ladder below."  And of the refusal: "A rejected
    request writes nothing at all — no counter moves, no `version` advances, no partial
    cascade survives."

    Design: Corner/entities/work_order_create_with_an_unknown_body_turbine_id_returns_reference_not_found
    """
    refused = api.create_work_order(
        work_order_payload(
            NON_EXISTENT_UUID,
            work_type=WORK_TYPE_MAJOR_COMPONENT,
            required_certification=CERT_CRANE_BANKSMAN,
            estimated_hours=8,
        ),
        make_planner_headers(),
    )
    validate_error(refused, "ERR_REFERENCE_NOT_FOUND", 404)
    assert_error_envelope_is_minimal(refused)

    assert_total_count(api.list_work_orders(make_planner_headers()), 0)


def test_the_replacement_junction_is_reachable_in_reverse_through_all_three_filters(api):
    """A work order, a stock line and a crane slot, each found from the junction row.

    The contract states: "The body names the `work_order_id` of the `MAJOR_COMPONENT`
    order it executes under, the `spare_part_id` of the stock line the unit is drawn from,
    the `component_type` being replaced — `GEARBOX`, `BLADE` or `GENERATOR` — an
    `estimated_lift_hours` of at least 0 giving the crane hours the lift is expected to
    occupy, and `uptower_labor_hours`, the additional crew hours booked if the up-tower
    branch is later taken, which must be greater than 0 when supplied."  Of the
    reservation it states: "A successful reservation sets `execution_path` to
    `CRANE_LIFT`, stores the `crane_mobilization_id`, moves the mobilization `REQUESTED →
    MOBILIZED` if it was still `REQUESTED`, increments its `reserved_replacement_count` by
    1, and reprices the whole mobilization."  Of planning it states: "Planning creates the
    replacement in `state` `PLANNED` with `execution_path` null, `crane_mobilization_id`
    null and `allocated_crane_cost_cents` at 0, and moves exactly one unit from the part's
    `quantity_on_hand` into its `quantity_reserved` — leaving `total_units_accounted`
    unchanged — then re-derives the part's `status` and `procurement_flag` from the reduced
    on-hand balance."  Of the self-reference it states: "`parent_work_order_id` is always
    optional and links this order to an earlier one as follow-up work — a major-component
    order raised out of an earlier inspection typically carries it."  And of filtering:
    "Filters named on a list endpoint combine conjunctively — a request naming both a farm
    filter and a state filter returns only the rows matching both."

    Design: Corner/entities/component_replacement_junction_resolves_all_three_of_its_foreign_keys
    """
    site = setup_junction_graph(api)
    headers = make_planner_headers()
    parent_id = site["wo_parent"]["id"]

    # A MAJOR_COMPONENT follow-up carries no mandatory link of its own, so it is the
    # work type that isolates `parent_work_order_id`; PRD 3.3 makes `blade_damage_id`
    # required on a BLADE_REPAIR order, which would confound the self-reference.
    child = validate_success(
        api.create_work_order(
            work_order_payload(
                site["t1"]["id"],
                work_type=WORK_TYPE_MAJOR_COMPONENT,
                required_certification=CERT_GWO_BASIC,
                estimated_hours=6,
                parent_work_order_id=parent_id,
            ),
            headers,
        ),
        201,
    )
    assert child["parent_work_order_id"] == parent_id
    assert read_work_order(api, parent_id)["parent_work_order_id"] is None

    replacement = validate_success(
        api.create_component_replacement(
            replacement_payload(
                parent_id,
                site["part"]["id"],
                component_type=COMPONENT_GEARBOX,
                estimated_lift_hours=8,
            ),
            headers,
        ),
        201,
    )
    assert replacement["work_order_id"] == parent_id
    assert replacement["spare_part_id"] == site["part"]["id"]
    assert replacement["crane_mobilization_id"] is None

    validate_success(api.reserve_crane(replacement["id"], site["crane"]["id"], headers))
    reserved = read_replacement(api, replacement["id"])
    assert reserved["state"] == REPLACEMENT_CRANE_RESERVED
    assert reserved["execution_path"] == PATH_CRANE_LIFT
    assert reserved["crane_mobilization_id"] == site["crane"]["id"]

    by_order = assert_page(
        api.list_component_replacements(headers, work_order_id=parent_id), 1, 1, False
    )
    assert by_order[0]["id"] == replacement["id"]
    by_part = assert_page(
        api.list_component_replacements(headers, spare_part_id=site["part"]["id"]), 1, 1, False
    )
    assert by_part[0]["id"] == replacement["id"]
    by_crane = assert_page(
        api.list_component_replacements(headers, crane_mobilization_id=site["crane"]["id"]),
        1,
        1,
        False,
    )
    assert by_crane[0]["id"] == replacement["id"]

    children = assert_page(
        api.list_work_orders(headers, parent_work_order_id=parent_id), 1, 1, False
    )
    assert children[0]["id"] == child["id"]
    assert parent_id not in [row["id"] for row in children]

    part = read_spare_part(api, site["part"]["id"])
    assert part["quantity_on_hand"] == 1
    assert part["quantity_reserved"] == 1
    assert part["quantity_consumed"] == 0
    assert part["total_units_accounted"] == 2
