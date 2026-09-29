"""Flight planning, airframe separation and the immutable pre-flight check record.

Covers the closed-interval turnaround buffer on flight creation, the declared
planning defaults, the append-only pre-flight check log, ownership across the
flight's reference graph, paging over the flight collection, the fully compliant
commercial mission, and a restriction published after clearance.
"""

from test_helpers import (
    ApiErrorId,
    BlockingFinding,
    FlightStatus,
    InvestigationStatus,
    OperationCategory,
    OperatorCategory,
    PreflightResult,
    RestrictionStatus,
    ZoneClassCode,
    AuthorizationStatus,
    COMPLIANCE_OFFICER,
    AIRSPACE_AUTHORITY,
    NON_EXISTENT_UUID,
    assert_flight,
    assert_pagination_meta,
    assert_preflight_check,
    assert_instant_equals,
    assert_no_version_fields,
    factories,
    fixtures,
    make_pilot_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


TURNAROUND_CLOCK = "2026-08-05T00:00:00Z"
TURNAROUND_DAY = "2026-08-20"


def _turnaround_setup(api):
    """A commercial operator, a sub-250 g registered airframe and an uncontrolled zone."""
    fixtures.set_clock(api, TURNAROUND_CLOCK)
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=800
    )
    zone = fixtures.create_zone(
        api, class_code=ZoneClassCode.G.value, class_ceiling_ft=400, requires_authorization=False
    )
    existing = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        f"{TURNAROUND_DAY}T09:00:00Z",
        f"{TURNAROUND_DAY}T10:00:00Z",
        planned_max_altitude_ft=380,
    )
    return pilot, aircraft, zone, existing


def test_planning_refuses_a_thirty_minute_gap_behind_the_same_airframe(api):
    """PRD §3.7: "Pad the candidate's window by 30 minutes on each end: the padded start is `planned_start` less 30 minutes and the padded end is `planned_end` plus 30 minutes."
    PRD §3.7: "The candidate conflicts when some other flight on the same `aircraft_id`, whose `status` is `PLANNED`, `PREFLIGHT_CLEARED` or `IN_PROGRESS`, has a `planned_start` at or before the padded end **and** a `planned_end` at or after the padded start."
    PRD §3.7: "Both comparisons are inclusive, so touching endpoints *do* collide: a gap of exactly 30 minutes between two flights of the same airframe conflicts and is refused with `ERR_AIRCRAFT_SCHEDULE_CONFLICT`, while a gap of 31 minutes is clear."

    Design: Difficulty/resource_temporal_overlap/aircraft_turnaround_closed_interval_thirty_minute_gap_collides
    """
    pilot, aircraft, zone, existing = _turnaround_setup(api)

    response = api.create_flight(
        factories.flight_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            f"{TURNAROUND_DAY}T10:30:00Z",
            f"{TURNAROUND_DAY}T11:00:00Z",
            planned_max_altitude_ft=380,
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(response, ApiErrorId.AIRCRAFT_SCHEDULE_CONFLICT.value, 409)

    rows, meta = validate_paginated(
        api.list_flights({"pilot_id": pilot["id"]}, headers=COMPLIANCE_OFFICER)
    )
    assert meta["total_count"] == 1, (
        f"the refused candidate must not create a flight row; total_count is {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [existing["id"]], (
        f"only the original flight may survive the refusal, got {[r['id'] for r in rows]}"
    )


def test_planning_accepts_a_thirty_one_minute_gap_behind_the_same_airframe(api):
    """PRD §3.7: "Both comparisons are inclusive, so touching endpoints *do* collide: a gap of exactly 30 minutes between two flights of the same airframe conflicts and is refused with `ERR_AIRCRAFT_SCHEDULE_CONFLICT`, while a gap of 31 minutes is clear."
    PRD §3.7: "The flight is created in `PLANNED` with `investigation_status` `NONE`, `logged_minutes` 0, `altitude_exceedance` false, and `actual_start`, `actual_end`, `max_altitude_reached_ft`, `incident_occurred`, `incident_summary` and `cancellation_reason` all null."

    Design: Difficulty/resource_temporal_overlap/aircraft_turnaround_closed_interval_thirty_minute_gap_collides
    """
    pilot, aircraft, zone, existing = _turnaround_setup(api)

    second = validate_success(
        api.create_flight(
            factories.flight_payload(
                pilot["id"],
                aircraft["id"],
                zone["id"],
                f"{TURNAROUND_DAY}T10:31:00Z",
                f"{TURNAROUND_DAY}T11:00:00Z",
                planned_max_altitude_ft=380,
            ),
            headers=make_pilot_headers(pilot["id"]),
        ),
        201,
    )
    assert_flight(
        second,
        status=FlightStatus.PLANNED.value,
        aircraft_id=aircraft["id"],
        planned_start=f"{TURNAROUND_DAY}T10:31:00Z",
    )

    _, meta = validate_paginated(
        api.list_flights({"aircraft_id": aircraft["id"]}, headers=COMPLIANCE_OFFICER)
    )
    assert meta["total_count"] == 2, (
        f"a 31-minute gap is clear, so the airframe holds two live plans; got {meta['total_count']}"
    )
    assert second["id"] != existing["id"], "the accepted candidate is a distinct flight row"


def test_the_turnaround_buffer_bites_ahead_of_the_existing_flight_too(api):
    """PRD §3.7: "Pad the candidate's window by 30 minutes on each end: the padded start is `planned_start` less 30 minutes and the padded end is `planned_end` plus 30 minutes."
    PRD §2.11: "**Airframe turnaround**, on `POST /drone-ops/flights` only: no other live flight on the same airframe collides with the candidate window once that window is padded on both ends — otherwise `ERR_AIRCRAFT_SCHEDULE_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/aircraft_turnaround_closed_interval_thirty_minute_gap_collides
    """
    pilot, aircraft, zone, _existing = _turnaround_setup(api)

    response = api.create_flight(
        factories.flight_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            f"{TURNAROUND_DAY}T07:30:00Z",
            f"{TURNAROUND_DAY}T08:30:00Z",
            planned_max_altitude_ft=380,
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(response, ApiErrorId.AIRCRAFT_SCHEDULE_CONFLICT.value, 409)

    _, meta = validate_paginated(
        api.list_flights({"aircraft_id": aircraft["id"]}, headers=COMPLIANCE_OFFICER)
    )
    assert meta["total_count"] == 1, (
        f"a candidate ending 30 minutes before the existing start is refused; got {meta['total_count']}"
    )


DEFAULTS_CLOCK = "2026-08-05T00:00:00Z"
DEFAULTS_START = "2026-08-21T09:00:00Z"
DEFAULTS_END = "2026-08-21T10:00:00Z"


def _uncontrolled_operation(api, clock_at):
    """A certified commercial operator, a sub-250 g airframe and an uncontrolled class G zone."""
    fixtures.set_clock(api, clock_at)
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_zone(
        api, class_code=ZoneClassCode.G.value, class_ceiling_ft=400, requires_authorization=False
    )
    return pilot, aircraft, zone


def test_flight_creation_applies_the_declared_planning_defaults(api):
    """PRD §3.7: "The flight is created in `PLANNED` with `investigation_status` `NONE`, `logged_minutes` 0, `altitude_exceedance` false, and `actual_start`, `actual_end`, `max_altitude_reached_ft`, `incident_occurred`, `incident_summary` and `cancellation_reason` all null."
    PRD §3.7: "Planning carries `pilot_id`, `aircraft_id`, `zone_id`, optionally an `authorization_id` and a `waiver_id`, an `operation_category` of `RECREATIONAL` or `COMMERCIAL`, a `planned_start` and `planned_end`, a `planned_max_altitude_ft` (integer 1 to 2000), a `launch_latitude` (decimal degrees, -90.0 to 90.0) and `launch_longitude` (decimal degrees, -180.0 to 180.0), and the three special-operation flags `over_people`, `night_operation` and `beyond_visual_line_of_sight`, each defaulting to false."
    PRD §3.7: "For a `COMMERCIAL` operation, creation finally selects the covering policy and writes `covering_policy_id` (§3.6); for a `RECREATIONAL` operation it stays null."

    Design: Corner/entities/flight_creation_applies_the_declared_field_defaults
    """
    pilot, aircraft, zone = _uncontrolled_operation(api, DEFAULTS_CLOCK)

    flight = validate_success(
        api.create_flight(
            factories.flight_payload(
                pilot["id"],
                aircraft["id"],
                zone["id"],
                DEFAULTS_START,
                DEFAULTS_END,
                OperationCategory.RECREATIONAL.value,
                planned_max_altitude_ft=380,
            ),
            headers=make_pilot_headers(pilot["id"]),
        ),
        201,
    )

    assert_flight(
        flight,
        status=FlightStatus.PLANNED.value,
        investigation_status=InvestigationStatus.NONE.value,
        logged_minutes=0,
        altitude_exceedance=False,
        over_people=False,
        night_operation=False,
        beyond_visual_line_of_sight=False,
    )
    for field in (
        "actual_start",
        "actual_end",
        "max_altitude_reached_ft",
        "incident_occurred",
        "incident_summary",
        "cancellation_reason",
        "covering_policy_id",
    ):
        assert flight[field] is None, (
            f"a freshly planned flight must leave {field} null, got {flight[field]!r}"
        )
    assert flight["version"] == 1, f"a new flight starts at version 1, got {flight['version']}"


def test_a_preflight_check_with_no_body_acknowledges_nothing_and_passes(api):
    """PRD §3.7: "The pre-flight check accepts an optional `acknowledged_tfr_ids` array — the restriction ids the pilot declares awareness of, defaulting to an empty array — and appends an **immutable** check record to the flight."
    PRD §3.7: "The check's `result` is `PASSED` exactly when `blocking_findings` is empty, and `FAILED` otherwise."
    PRD §3.7: "The `effective_ceiling_ft` is the cited authorization's `granted_ceiling_ft` when the flight names an `authorization_id`, and 400 feet otherwise."

    Design: Corner/entities/flight_creation_applies_the_declared_field_defaults
    """
    pilot, aircraft, zone = _uncontrolled_operation(api, DEFAULTS_CLOCK)
    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        DEFAULTS_START,
        DEFAULTS_END,
        planned_max_altitude_ft=380,
    )

    check = validate_success(
        api.preflight_check(flight["id"], {}, headers=make_pilot_headers(pilot["id"])), 201
    )
    assert_preflight_check(
        check,
        flight_id=flight["id"],
        result=PreflightResult.PASSED.value,
        airspace_class_code=ZoneClassCode.G.value,
        effective_ceiling_ft=400,
    )
    assert check["acknowledged_tfr_ids"] == [], (
        f"an omitted acknowledged_tfr_ids defaults to an empty array, got {check['acknowledged_tfr_ids']!r}"
    )
    assert check["blocking_findings"] == [], (
        f"a clear sweep records no findings, got {check['blocking_findings']!r}"
    )


IMMUTABLE_CLOCK = "2026-08-05T00:00:00Z"
IMMUTABLE_START = "2026-08-22T09:00:00Z"
IMMUTABLE_END = "2026-08-22T10:00:00Z"
IMMUTABLE_BAN_FROM = "2026-08-22T08:00:00Z"
IMMUTABLE_BAN_UNTIL = "2026-08-22T12:00:00Z"


def _banned_flight(api):
    """A planned flight whose zone carries an overlapping total-ban restriction."""
    pilot, aircraft, zone = _uncontrolled_operation(api, IMMUTABLE_CLOCK)
    restriction = fixtures.create_tfr(
        api,
        zone["id"],
        IMMUTABLE_BAN_FROM,
        IMMUTABLE_BAN_UNTIL,
        max_permitted_altitude_ft=None,
    )
    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        IMMUTABLE_START,
        IMMUTABLE_END,
        planned_max_altitude_ft=380,
    )
    return pilot, flight, restriction


def test_a_failed_preflight_check_is_recorded_without_updated_at_or_version(api):
    """PRD §2.5: "A pre-flight check record is an immutable audit artefact: once appended it is never modified, so it carries only `id` and `created_at`."
    PRD §2.5: "It has no `updated_at` field and no `version` field at all, and neither key appears in its representation."
    PRD §3.7: "A `FAILED` check is **not** an error response — it is a recorded advisory returned with a success status: the flight stays in `PLANNED`, the flight's `version` is deliberately *not* incremented, and the pilot may fix the cause and re-check as often as they like, each attempt appending another immutable record."
    PRD §3.4: "The distinction the optional field draws is the important one: a restriction that names a `max_permitted_altitude_ft` is a partial restriction — flying below that altitude remains permitted once the pilot has acknowledged the restriction — whereas **omitting** it (leaving it null) declares a total ban that no acknowledgement can ever clear."

    Design: Corner/entities/preflight_check_rows_are_immutable_and_carry_no_version_field
    """
    pilot, flight, restriction = _banned_flight(api)
    pilot_view = make_pilot_headers(pilot["id"])

    check = validate_success(api.preflight_check(flight["id"], {}, headers=pilot_view), 201)
    assert_preflight_check(check, flight_id=flight["id"], result=PreflightResult.FAILED.value)
    assert_no_version_fields(check, "preflight_check")
    assert check["blocking_findings"] == [
        BlockingFinding.TFR_TOTAL_BAN.value,
        BlockingFinding.TFR_UNACKNOWLEDGED.value,
    ], (
        "an unacknowledged total ban contributes both codes, sorted ascending; got "
        f"{check['blocking_findings']!r}"
    )
    assert check["active_tfr_ids"] == [restriction["id"]], (
        f"the overlapping ACTIVE restriction must be listed, got {check['active_tfr_ids']!r}"
    )

    after = validate_success(api.get_flight(flight["id"], headers=pilot_view))
    assert_flight(after, status=FlightStatus.PLANNED.value, version=flight["version"])


def test_re_checking_appends_a_second_row_and_leaves_the_first_untouched(api):
    """PRD §3.7: "A `PASSED` check moves the flight from `PLANNED` to `PREFLIGHT_CLEARED` and increments the flight's `version`."
    PRD §3.4: "The authority may lift an `ACTIVE` restriction ahead of its `effective_until`, moving it to `LIFTED`; and a restriction whose `effective_until` is at or before the current instant is lazily moved to `EXPIRED` when a preflight check or a launch reads it."
    PRD §3.7: "A check record is the only record in the service with no `updated_at` and no `version`, because nothing ever amends it (§2.5), and the only way to read one is to list the checks of its flight."

    Design: Corner/entities/preflight_check_rows_are_immutable_and_carry_no_version_field
    """
    pilot, flight, restriction = _banned_flight(api)
    pilot_view = make_pilot_headers(pilot["id"])

    first = validate_success(api.preflight_check(flight["id"], {}, headers=pilot_view), 201)
    assert first["result"] == PreflightResult.FAILED.value, (
        f"the total ban must fail the first sweep, got {first['result']}"
    )

    lifted = validate_success(api.lift_tfr(restriction["id"], {}, headers=AIRSPACE_AUTHORITY))
    assert lifted["status"] == RestrictionStatus.LIFTED.value, (
        f"lifting moves the restriction to LIFTED, got {lifted['status']}"
    )

    second = validate_success(api.preflight_check(flight["id"], {}, headers=pilot_view), 201)
    assert second["result"] == PreflightResult.PASSED.value, (
        f"with the ban lifted the sweep clears, got findings {second['blocking_findings']!r}"
    )
    assert second["id"] != first["id"], "a re-check appends a new record rather than amending one"

    cleared = validate_success(api.get_flight(flight["id"], headers=pilot_view))
    assert_flight(cleared, status=FlightStatus.PREFLIGHT_CLEARED.value)
    assert cleared["version"] > flight["version"], (
        f"a PASSED check increments the flight version, got {cleared['version']}"
    )

    rows, meta = validate_paginated(
        api.list_preflight_checks(flight["id"], headers=COMPLIANCE_OFFICER)
    )
    assert meta["total_count"] == 2, (
        f"both sweeps must survive as separate rows, got total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"], "the checks list is ordered by created_at ascending"
    assert rows[0]["result"] == PreflightResult.FAILED.value, (
        f"the historical row is append-only and stays FAILED, got {rows[0]['result']}"
    )
    for row in rows:
        assert_no_version_fields(row, "preflight_check")


GRAPH_CLOCK = "2026-08-05T00:00:00Z"
GRAPH_START = "2026-08-23T09:00:00Z"
GRAPH_END = "2026-08-23T10:00:00Z"


def _two_operators(api):
    """Two certified commercial operators, each owning one registered airframe, one zone."""
    fixtures.set_clock(api, GRAPH_CLOCK)
    pilot_a = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    pilot_b = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft_a = fixtures.create_registered_aircraft(
        api, pilot_a["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    aircraft_b = fixtures.create_registered_aircraft(
        api, pilot_b["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_zone(
        api, class_code=ZoneClassCode.G.value, class_ceiling_ft=400, requires_authorization=False
    )
    return pilot_a, pilot_b, aircraft_a, aircraft_b, zone


def _assert_no_flights_for(api, pilot_id):
    _, meta = validate_paginated(
        api.list_flights({"pilot_id": pilot_id}, headers=COMPLIANCE_OFFICER)
    )
    assert meta["total_count"] == 0, (
        f"a refused plan leaves no flight row for pilot {pilot_id}, got {meta['total_count']}"
    )


def test_a_flight_may_not_cite_another_pilots_registered_airframe(api):
    """PRD §2.1: "Concretely, that means `Aircraft.owner_pilot_id` for an airframe, the `owner_pilot_id` of the parent airframe for a broadcast module, `Waiver.pilot_id` for a waiver and the parent waiver's pilot for a safety case, `AirspaceAuthorization.pilot_id` for an authorization, `Flight.pilot_id` for a flight and its pre-flight checks, and the pilot of the referenced flight for an accident report or an insurance policy."
    PRD §2.1: "A mismatch on either the addressed resource or the submitted body is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."
    PRD §3.7: "Creation runs the full eligibility ladder of §2.11 — the pilot must be `CERTIFIED`, current, and not suspended; the airframe must be `REGISTERED`, not grounded, and owned by the flying pilot; each raised special-operation flag must be backed by an `APPROVED` waiver of the matching `waiver_type` cited in `waiver_id` and still valid past `planned_end`; controlled airspace must be backed by an `APPROVED` authorization covering the planned window; and `planned_max_altitude_ft` must sit inside the ceilings."

    Design: Corner/entities/flight_cannot_cite_another_pilots_airframe_across_the_reference_graph
    """
    pilot_a, pilot_b, _aircraft_a, aircraft_b, zone = _two_operators(api)

    response = api.create_flight(
        factories.flight_payload(
            pilot_a["id"],
            aircraft_b["id"],
            zone["id"],
            GRAPH_START,
            GRAPH_END,
            planned_max_altitude_ft=380,
        ),
        headers=make_pilot_headers(pilot_a["id"]),
    )
    validate_error(response, ApiErrorId.OWNERSHIP_VIOLATION.value, 403)
    _assert_no_flights_for(api, pilot_a["id"])
    _assert_no_flights_for(api, pilot_b["id"])


def test_a_body_pilot_id_that_differs_from_the_caller_is_refused(api):
    """PRD §2.11: "**Pilot ownership**, on every endpoint a `Pilot` may call: `X-User-ID` equals the owning pilot of the addressed resource and equals any `pilot_id` or `owner_pilot_id` in the body — otherwise `ERR_OWNERSHIP_VIOLATION` (403)."

    Design: Corner/entities/flight_cannot_cite_another_pilots_airframe_across_the_reference_graph
    """
    pilot_a, pilot_b, _aircraft_a, aircraft_b, zone = _two_operators(api)

    response = api.create_flight(
        factories.flight_payload(
            pilot_b["id"],
            aircraft_b["id"],
            zone["id"],
            GRAPH_START,
            GRAPH_END,
            planned_max_altitude_ft=380,
        ),
        headers=make_pilot_headers(pilot_a["id"]),
    )
    validate_error(response, ApiErrorId.OWNERSHIP_VIOLATION.value, 403)
    _assert_no_flights_for(api, pilot_a["id"])
    _assert_no_flights_for(api, pilot_b["id"])


def test_an_unresolvable_airframe_reference_is_a_not_found_rather_than_an_ownership_breach(api):
    """PRD §2.11: "**Body reference existence**, on every creating endpoint carrying references: `pilot_id`, `owner_pilot_id`, `aircraft_id`, `zone_id`, `authorization_id`, `waiver_id` and `flight_id` each resolve, with the code naming the unresolved entity — for example `ERR_AIRCRAFT_NOT_FOUND` (404)."
    PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."

    Design: Corner/entities/flight_cannot_cite_another_pilots_airframe_across_the_reference_graph
    """
    pilot_a, pilot_b, _aircraft_a, _aircraft_b, zone = _two_operators(api)

    response = api.create_flight(
        factories.flight_payload(
            pilot_a["id"],
            NON_EXISTENT_UUID,
            zone["id"],
            GRAPH_START,
            GRAPH_END,
            planned_max_altitude_ft=380,
        ),
        headers=make_pilot_headers(pilot_a["id"]),
    )
    validate_error(response, ApiErrorId.AIRCRAFT_NOT_FOUND.value, 404)
    _assert_no_flights_for(api, pilot_a["id"])
    _assert_no_flights_for(api, pilot_b["id"])


PAGING_CLOCK = "2026-08-05T00:00:00Z"
PAGING_DAY = "2026-08-24"
PAGING_WINDOWS = (("09:00:00", "10:00:00"), ("11:00:00", "12:00:00"), ("13:00:00", "14:00:00"))


def _three_planned_flights(api):
    """Three plans on one airframe, spaced so the 30-minute turnaround buffer never bites."""
    fixtures.set_clock(api, PAGING_CLOCK)
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=400,
        requires_authorization=False,
        max_concurrent_authorizations=3,
    )
    flights = [
        fixtures.create_planned_flight(
            api,
            pilot["id"],
            aircraft["id"],
            zone["id"],
            f"{PAGING_DAY}T{start}Z",
            f"{PAGING_DAY}T{end}Z",
            planned_max_altitude_ft=380,
        )
        for start, end in PAGING_WINDOWS
    ]
    return pilot, flights


def test_the_flight_list_pages_with_a_total_count_over_the_whole_filtered_set(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` is true exactly when records remain beyond the current window."
    PRD §2.3: "`offset` is the number of records to skip before the page begins: it defaults to 0 and may not be negative."

    Design: Corner/entities/list_flights_paginates_with_limit_offset_total_count_and_has_more
    """
    pilot, flights = _three_planned_flights(api)
    every_id = {flight["id"] for flight in flights}

    first_rows, first_meta = validate_paginated(
        api.list_flights(
            {"pilot_id": pilot["id"], "limit": 2, "offset": 0}, headers=COMPLIANCE_OFFICER
        )
    )
    assert len(first_rows) == 2, f"a limit of 2 returns two rows, got {len(first_rows)}"
    assert_pagination_meta(first_meta, 2, 0, 3)

    second_rows, second_meta = validate_paginated(
        api.list_flights(
            {"pilot_id": pilot["id"], "limit": 2, "offset": 2}, headers=COMPLIANCE_OFFICER
        )
    )
    assert len(second_rows) == 1, f"the tail page holds the last row, got {len(second_rows)}"
    assert_pagination_meta(second_meta, 2, 2, 3)

    first_page_ids = [row["id"] for row in first_rows]
    second_page_ids = [row["id"] for row in second_rows]
    assert not set(first_page_ids) & set(second_page_ids), (
        f"no flight may repeat across pages, got {first_page_ids} then {second_page_ids}"
    )
    assert set(first_page_ids) | set(second_page_ids) == every_id, (
        f"the two pages together cover every flight, got {first_page_ids + second_page_ids}"
    )


def test_a_zero_limit_on_the_flight_list_is_a_malformed_request(api):
    """PRD §2.3: "`limit` caps the number of records returned: it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "A `limit` outside the range 1 to 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/list_flights_paginates_with_limit_offset_total_count_and_has_more
    """
    pilot, _flights = _three_planned_flights(api)

    response = api.list_flights(
        {"pilot_id": pilot["id"], "limit": 0}, headers=COMPLIANCE_OFFICER
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)


COMPLIANT_CLOCK = "2026-10-01T00:00:00Z"
COMPLIANT_MODULE_UNTIL = "2027-10-01T00:00:00Z"
COMPLIANT_POLICY_UNTIL = "2027-10-01T00:00:00Z"
COMPLIANT_AUTH_FROM = "2026-10-05T08:00:00Z"
COMPLIANT_AUTH_UNTIL = "2026-10-05T12:00:00Z"
COMPLIANT_START = "2026-10-05T09:00:00Z"
COMPLIANT_END = "2026-10-05T10:00:00Z"


def _compliant_commercial_mission(api):
    """A commercial operator with cover, a heavy verified airframe and an approved slot."""
    fixtures.set_clock(api, COMPLIANT_CLOCK)
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = fixtures.create_registered_aircraft(
        api,
        pilot["id"],
        takeoff_weight_g=900,
        max_altitude_ft=1200,
        module_verified_until=COMPLIANT_MODULE_UNTIL,
    )
    policy = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from=COMPLIANT_CLOCK,
        effective_until=COMPLIANT_POLICY_UNTIL,
        coverage_limit_cents=2000000,
        deductible_cents=100000,
        indemnification_clause_accepted=True,
    )
    zone = fixtures.create_zone(
        api,
        class_code=ZoneClassCode.C.value,
        class_ceiling_ft=700,
        requires_authorization=True,
        max_concurrent_authorizations=2,
    )
    authorization = fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        COMPLIANT_AUTH_FROM,
        COMPLIANT_AUTH_UNTIL,
        requested_ceiling_ft=400,
    )
    return pilot, aircraft, policy, zone, authorization


def test_a_fully_compliant_commercial_plan_selects_its_cover_and_ceiling(api):
    """PRD §3.4: "Fourth, the four are combined: relief is the **greater** of the waiver cap and the category cap, and the granted ceiling is the **least** of the `requested_ceiling_ft`, the class cap, the airframe cap, and that relief figure."
    PRD §3.6: "Among the survivors the selector takes the policy with the **greatest** `remaining_coverage_cents`, breaking a tie on `created_at` ascending and never on `id`, and writes that policy's `id` into the flight's `covering_policy_id`."
    PRD §2.11: "**Authorization window containment**, on `POST /drone-ops/flights` only: the flight's `planned_start` is at or after the authorization's `window_start` and its `planned_end` is strictly before the authorization's `window_end` — otherwise `ERR_AUTHORIZATION_WINDOW_MISMATCH` (422)."

    Design: Corner/validations/a_fully_compliant_commercial_flight_clears_every_gate
    """
    pilot, aircraft, policy, zone, authorization = _compliant_commercial_mission(api)

    assert authorization["granted_ceiling_ft"] == 400, (
        "the granted ceiling is the least of the request, the class cap, the airframe cap and "
        f"the relief figure, expected 400 but got {authorization['granted_ceiling_ft']}"
    )

    flight = validate_success(
        api.create_flight(
            factories.flight_payload(
                pilot["id"],
                aircraft["id"],
                zone["id"],
                COMPLIANT_START,
                COMPLIANT_END,
                OperationCategory.COMMERCIAL.value,
                planned_max_altitude_ft=380,
                authorization_id=authorization["id"],
            ),
            headers=make_pilot_headers(pilot["id"]),
        ),
        201,
    )
    assert_flight(
        flight,
        status=FlightStatus.PLANNED.value,
        operation_category=OperationCategory.COMMERCIAL.value,
        covering_policy_id=policy["id"],
        planned_max_altitude_ft=380,
    )
    assert fixtures.read_zone(api, zone["id"])["reserved_slot_count"] == 1, (
        "the approved authorization holds exactly one of the zone's concurrent slots"
    )


def test_a_fully_compliant_commercial_mission_clears_and_launches(api):
    """PRD §3.7: "The `effective_ceiling_ft` is the cited authorization's `granted_ceiling_ft` when the flight names an `authorization_id`, and 400 feet otherwise."
    PRD §3.7: "The check's `result` is `PASSED` exactly when `blocking_findings` is empty, and `FAILED` otherwise."
    PRD §3.7: "On success the flight moves from `PREFLIGHT_CLEARED` to `IN_PROGRESS`, `actual_start` is set to the current instant, and the cited authorization moves from `APPROVED` to `ACTIVE`, keeping its zone slot."

    Design: Corner/validations/a_fully_compliant_commercial_flight_clears_every_gate
    """
    pilot, aircraft, _policy, zone, authorization = _compliant_commercial_mission(api)
    pilot_view = make_pilot_headers(pilot["id"])
    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        COMPLIANT_START,
        COMPLIANT_END,
        OperationCategory.COMMERCIAL.value,
        planned_max_altitude_ft=380,
        authorization_id=authorization["id"],
    )

    fixtures.set_clock(api, COMPLIANT_START)

    check = validate_success(api.preflight_check(flight["id"], {}, headers=pilot_view), 201)
    assert_preflight_check(
        check,
        result=PreflightResult.PASSED.value,
        airspace_class_code=ZoneClassCode.C.value,
        effective_ceiling_ft=400,
    )
    assert check["blocking_findings"] == [], (
        f"a compliant mission clears every gate, got {check['blocking_findings']!r}"
    )

    launched = validate_success(api.launch_flight(flight["id"], headers=pilot_view))
    assert_flight(launched, status=FlightStatus.IN_PROGRESS.value)
    assert_instant_equals(launched["actual_start"], COMPLIANT_START, "flight.actual_start")

    after = validate_success(api.get_authorization(authorization["id"], headers=AIRSPACE_AUTHORITY))
    assert after["status"] == AuthorizationStatus.ACTIVE.value, (
        f"launching moves the cited authorization to ACTIVE, got {after['status']}"
    )
    assert fixtures.read_zone(api, zone["id"])["reserved_slot_count"] == 1, (
        "an ACTIVE authorization keeps the zone slot it held while APPROVED"
    )


OVERTAKEN_CLOCK = "2026-09-01T00:00:00Z"
OVERTAKEN_START = "2026-09-10T09:00:00Z"
OVERTAKEN_END = "2026-09-10T10:00:00Z"
OVERLAP_BAN_FROM = "2026-09-10T09:30:00Z"
OVERLAP_BAN_UNTIL = "2026-09-10T11:00:00Z"


def _cleared_recreational_flight(api):
    """A recreational flight cleared while its zone carried no restriction at all."""
    fixtures.set_clock(api, OVERTAKEN_CLOCK)
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.RECREATIONAL.value)
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=400,
        requires_authorization=False,
        max_concurrent_authorizations=2,
    )
    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        OVERTAKEN_START,
        OVERTAKEN_END,
        planned_max_altitude_ft=380,
    )
    check = validate_success(
        api.preflight_check(flight["id"], {}, headers=make_pilot_headers(pilot["id"])), 201
    )
    return pilot, zone, flight, check


def test_a_total_ban_published_after_clearance_refuses_the_launch(api):
    """PRD §2.11: "**Restriction gate**, on `POST /drone-ops/flights/{id}/launch` only: for every restriction on the flight's zone whose `status` is `ACTIVE` and whose window overlaps the flight's planned window, the restriction must be non-blocking — its `max_permitted_altitude_ft` is not null **and** the flight's `planned_max_altitude_ft` is at most that cap."
    PRD §2.11: "A blocking restriction yields `ERR_TFR_ACTIVE` (422)."
    PRD §3.7: "A flight is planned, checked, launched and completed, and each of those four steps re-tests eligibility against the clock as it stands at that moment."

    Design: Corner/validations/a_restriction_published_after_clearance_blocks_the_launch_until_lifted
    """
    pilot, zone, flight, check = _cleared_recreational_flight(api)
    pilot_view = make_pilot_headers(pilot["id"])
    assert check["result"] == PreflightResult.PASSED.value, (
        f"the clearance predates every restriction, got findings {check['blocking_findings']!r}"
    )

    fixtures.create_tfr(
        api, zone["id"], OVERLAP_BAN_FROM, OVERLAP_BAN_UNTIL, max_permitted_altitude_ft=None
    )
    fixtures.set_clock(api, OVERTAKEN_START)

    response = api.launch_flight(flight["id"], headers=pilot_view)
    validate_error(response, ApiErrorId.TFR_ACTIVE.value, 422)

    held = validate_success(api.get_flight(flight["id"], headers=pilot_view))
    assert_flight(held, status=FlightStatus.PREFLIGHT_CLEARED.value)


def test_lifting_the_blocking_restriction_re_opens_the_launch(api):
    """PRD §3.4: "Lifting a restriction does not resurrect the flights it blocked — it only stops new preflight checks from reporting it."
    PRD §2.11: "**Restriction gate**, on `POST /drone-ops/flights/{id}/launch` only: for every restriction on the flight's zone whose `status` is `ACTIVE` and whose window overlaps the flight's planned window, the restriction must be non-blocking — its `max_permitted_altitude_ft` is not null **and** the flight's `planned_max_altitude_ft` is at most that cap."
    PRD §3.7: "On success the flight moves from `PREFLIGHT_CLEARED` to `IN_PROGRESS`, `actual_start` is set to the current instant, and the cited authorization moves from `APPROVED` to `ACTIVE`, keeping its zone slot."

    Design: Corner/validations/a_restriction_published_after_clearance_blocks_the_launch_until_lifted
    """
    pilot, zone, flight, _check = _cleared_recreational_flight(api)
    pilot_view = make_pilot_headers(pilot["id"])
    restriction = fixtures.create_tfr(
        api, zone["id"], OVERLAP_BAN_FROM, OVERLAP_BAN_UNTIL, max_permitted_altitude_ft=None
    )
    fixtures.set_clock(api, OVERTAKEN_START)
    validate_error(
        api.launch_flight(flight["id"], headers=pilot_view), ApiErrorId.TFR_ACTIVE.value, 422
    )

    lifted = validate_success(api.lift_tfr(restriction["id"], {}, headers=AIRSPACE_AUTHORITY))
    assert lifted["status"] == RestrictionStatus.LIFTED.value, (
        f"the authority may lift an ACTIVE restriction, got {lifted['status']}"
    )

    launched = validate_success(api.launch_flight(flight["id"], headers=pilot_view))
    assert_flight(launched, status=FlightStatus.IN_PROGRESS.value)
    assert_instant_equals(launched["actual_start"], OVERTAKEN_START, "flight.actual_start")


def test_a_restriction_published_with_no_altitude_cap_reads_back_as_a_total_ban(api):
    """PRD §3.4: "The distinction the optional field draws is the important one: a restriction that names a `max_permitted_altitude_ft` is a partial restriction — flying below that altitude remains permitted once the pilot has acknowledged the restriction — whereas **omitting** it (leaving it null) declares a total ban that no acknowledgement can ever clear."
    PRD §3.7: "`active_tfr_ids` holds the ids of the restrictions on the flight's zone that are still `ACTIVE` and whose half-open window overlaps the flight's window, ordered by the restriction's `created_at` ascending."

    Design: Corner/validations/a_restriction_published_after_clearance_blocks_the_launch_until_lifted
    """
    _pilot, zone, _flight, check = _cleared_recreational_flight(api)
    assert check["active_tfr_ids"] == [], (
        f"no restriction existed at clearance time, got {check['active_tfr_ids']!r}"
    )

    restriction = fixtures.create_tfr(
        api, zone["id"], OVERLAP_BAN_FROM, OVERLAP_BAN_UNTIL, max_permitted_altitude_ft=None
    )
    assert restriction["max_permitted_altitude_ft"] is None, (
        "an omitted max_permitted_altitude_ft is a total ban and reads back null, got "
        f"{restriction['max_permitted_altitude_ft']!r}"
    )
    assert restriction["status"] == RestrictionStatus.ACTIVE.value, (
        f"a new restriction is created in ACTIVE, got {restriction['status']}"
    )
