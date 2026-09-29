"""Airspace zones, the ceiling propagation on approval, and the gates a flight
meets when it enters controlled airspace.

Every scenario builds its own zone, airframe and pilot: the harness restarts the
service before each test, so nothing here may assume a pre-existing row.
"""

import pytest

from test_helpers import (
    AIRSPACE_AUTHORITY_ID,
    COMPLIANCE_OFFICER,
    DEFAULT_EFFECTIVE_CEILING_FT,
    AirRiskClass,
    ApiErrorId,
    AuthorizationStatus,
    FlightStatus,
    OperatorCategory,
    WaiverStatus,
    WaiverType,
    ZoneClassCode,
    assert_authorization,
    assert_instant_equals,
    assert_zone,
    assert_zone_slot_conservation,
    factories,
    fixtures,
    make_pilot_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_INSTANT = "2026-08-05T00:00:00Z"
POLICY_END = "2027-08-05T00:00:00Z"


def _relief_zone_scenario(api):
    """A commercial operator, a 249 g airframe capped at 900 ft, a class D zone
    with a 700 ft ceiling that is structure-relief eligible, and an APPROVED
    BVLOS waiver granting 1000 ft."""
    set_clock(api, SETUP_INSTANT, headers=COMPLIANCE_OFFICER)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=SETUP_INSTANT
    )
    fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from=SETUP_INSTANT,
        effective_until=POLICY_END,
        coverage_limit_cents=8000000,
        deductible_cents=0,
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_controlled_zone(
        api,
        class_code=ZoneClassCode.D.value,
        class_ceiling_ft=700,
        max_concurrent_authorizations=2,
        structure_relief_eligible=True,
    )
    waiver = fixtures.create_approved_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        waiver_type=WaiverType.BVLOS.value,
        requested_ceiling_ft=1000,
        granted_ceiling_ft=1000,
        ground_risk_class=2,
        air_risk_class=AirRiskClass.ARC_B.value,
    )
    return pilot, aircraft, zone, waiver


def test_granted_ceiling_stops_at_the_commercial_structure_relief_cap(api, airspace_authority):
    """PRD §3.4: "First, two hard caps: the **class cap** is the zone's `class_ceiling_ft`, and the **airframe cap** is the airframe's `max_altitude_ft`."
    PRD §3.4: "Third, the **category cap**, which branches on the pilot's rule set: for a `RECREATIONAL` operator it is 400 feet flat, ignoring the zone's relief flag entirely; for a `COMMERCIAL` operator it is 600 feet when the zone's `structure_relief_eligible` is true and 400 feet when it is false."
    PRD §3.4: "Fourth, the four are combined: relief is the **greater** of the waiver cap and the category cap, and the granted ceiling is the **least** of the `requested_ceiling_ft`, the class cap, the airframe cap, and that relief figure."
    PRD §3.4: "Approval also sets `approved_by_user_id` to the deciding operator's `X-User-ID` and `decided_at` to the current instant, increments the zone's `reserved_slot_count` by one and the zone's `version` by one."

    Design: Difficulty/combinatorial_formula/authorization_ceiling_nested_min_max_over_four_competing_caps
    """
    pilot, aircraft, zone, _waiver = _relief_zone_scenario(api)

    authorization = fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T11:00:00Z",
        requested_ceiling_ft=700,
    )

    assert_authorization(
        authorization,
        status=AuthorizationStatus.APPROVED.value,
        requested_ceiling_ft=700,
        granted_ceiling_ft=600,
        approved_by_user_id=AIRSPACE_AUTHORITY_ID,
        decided_at=SETUP_INSTANT,
    )
    assert authorization["granted_ceiling_ft"] == 600, (
        "with no waiver cited the relief figure is the 600 ft commercial structure-relief cap, "
        f"so the least of 700, 700, 900 and 600 is 600; got {authorization['granted_ceiling_ft']}"
    )
    zone_after = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert zone_after["reserved_slot_count"] == 1, (
        f"one approval holds one slot, got {zone_after['reserved_slot_count']}"
    )
    assert zone_after["version"] > zone["version"], (
        f"approval increments the zone version; was {zone['version']}, now {zone_after['version']}"
    )


def test_cited_waiver_lifts_the_relief_figure_up_to_the_class_cap(api, airspace_authority):
    """PRD §3.4: "First, two hard caps: the **class cap** is the zone's `class_ceiling_ft`, and the **airframe cap** is the airframe's `max_altitude_ft`."
    PRD §3.4: "Second, the **waiver cap**: if the authorization named a `waiver_id`, and that waiver's `status` is `APPROVED`, and that waiver's `valid_until` is strictly after the authorization's `window_end`, then the waiver cap is that waiver's `granted_ceiling_ft`; in every other case — no waiver cited, a waiver that is not `APPROVED`, or a waiver whose validity expires at or before the window ends — the waiver cap is 400 feet."
    PRD §3.4: "Fourth, the four are combined: relief is the **greater** of the waiver cap and the category cap, and the granted ceiling is the **least** of the `requested_ceiling_ft`, the class cap, the airframe cap, and that relief figure."

    Design: Difficulty/combinatorial_formula/authorization_ceiling_nested_min_max_over_four_competing_caps
    """
    pilot, aircraft, zone, waiver = _relief_zone_scenario(api)

    authorization = fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-21T09:00:00Z",
        "2026-08-21T11:00:00Z",
        requested_ceiling_ft=700,
        waiver_id=waiver["id"],
    )

    assert_authorization(
        authorization,
        status=AuthorizationStatus.APPROVED.value,
        waiver_id=waiver["id"],
        requested_ceiling_ft=700,
        granted_ceiling_ft=700,
    )
    assert authorization["granted_ceiling_ft"] == 700, (
        "the 1000 ft waiver cap beats the 600 ft category cap, so relief is 1000 and the zone's "
        f"700 ft class cap becomes the binding constraint; got {authorization['granted_ceiling_ft']}"
    )
    assert_zone_slot_conservation(api, zone["id"], airspace_authority)


def test_a_modest_request_binds_below_every_cap(api, airspace_authority):
    """PRD §3.4: "Fourth, the four are combined: relief is the **greater** of the waiver cap and the category cap, and the granted ceiling is the **least** of the `requested_ceiling_ft`, the class cap, the airframe cap, and that relief figure."
    PRD §3.4: "Approval also sets `approved_by_user_id` to the deciding operator's `X-User-ID` and `decided_at` to the current instant, increments the zone's `reserved_slot_count` by one and the zone's `version` by one."

    Design: Difficulty/combinatorial_formula/authorization_ceiling_nested_min_max_over_four_competing_caps
    """
    pilot, aircraft, zone, waiver = _relief_zone_scenario(api)

    authorization = fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-22T09:00:00Z",
        "2026-08-22T11:00:00Z",
        requested_ceiling_ft=550,
        waiver_id=waiver["id"],
    )

    assert authorization["granted_ceiling_ft"] == 550, (
        "with caps of 700, 900 and 1000 the 550 ft request is itself the least figure; got "
        f"{authorization['granted_ceiling_ft']}"
    )
    assert_instant_equals(
        authorization["decided_at"], SETUP_INSTANT, "decided_at on the approved authorization"
    )
    assert authorization["approved_by_user_id"] == AIRSPACE_AUTHORITY_ID, (
        "approval records the deciding operator's user id, got "
        f"{authorization['approved_by_user_id']}"
    )
    zone_after = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert zone_after["reserved_slot_count"] == 1, (
        f"the single approval holds one slot, got {zone_after['reserved_slot_count']}"
    )


def _single_slot_zone_scenario(api):
    """A certified recreational pilot, a registered airframe and a class C zone
    that admits exactly one overlapping authorization at a time."""
    set_clock(api, SETUP_INSTANT, headers=COMPLIANCE_OFFICER)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.RECREATIONAL.value, scheduled_at=SETUP_INSTANT
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_controlled_zone(
        api,
        class_code=ZoneClassCode.C.value,
        class_ceiling_ft=700,
        max_concurrent_authorizations=1,
    )
    return pilot, aircraft, zone


def test_touching_windows_both_win_a_slot_in_a_single_slot_zone(api, airspace_authority):
    """PRD §3.4: "Capacity is measured over the requested window rather than over the zone as a whole: the service counts the zone's *other* authorizations — same `zone_id`, different `id` — whose `status` is `APPROVED` or `ACTIVE` and whose window overlaps the candidate's, where overlap means the existing `window_start` is strictly before the candidate's `window_end` **and** the existing `window_end` is strictly before neither, that is strictly after the candidate's `window_start`."
    PRD §3.4: "Because the comparison is strictly half-open, two windows that merely touch — one ending at exactly the instant the other begins — do not collide and may both be approved even in a zone of capacity 1."

    Design: Difficulty/resource_temporal_overlap/zone_capacity_half_open_windows_touching_authorizations_do_not_collide
    """
    pilot, aircraft, zone = _single_slot_zone_scenario(api)

    morning = fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T11:00:00Z",
    )
    midday = fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T11:00:00Z",
        "2026-08-20T13:00:00Z",
    )

    assert morning["status"] == AuthorizationStatus.APPROVED.value, (
        f"the first window must be approved, got {morning['status']}"
    )
    assert midday["status"] == AuthorizationStatus.APPROVED.value, (
        "a window beginning at the exact instant the first one ends does not overlap it, so it is "
        f"approvable in a capacity-1 zone; got {midday['status']}"
    )
    zone_after = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert zone_after["reserved_slot_count"] == 2, (
        "both touching authorizations hold a slot even though the zone admits one overlapping "
        f"authorization, got {zone_after['reserved_slot_count']}"
    )


def test_a_window_straddling_both_neighbours_is_refused_for_capacity(api, airspace_authority):
    """PRD §3.4: "Approval is permitted only while that count is strictly less than the zone's `max_concurrent_authorizations`; at or above it the decision is refused with `ERR_ZONE_CAPACITY_EXCEEDED`."
    PRD §3.4: "Rows in `REQUESTED`, `DENIED`, `CONSUMED`, `REVOKED` and `EXPIRED` are excluded from the count entirely."

    Design: Difficulty/resource_temporal_overlap/zone_capacity_half_open_windows_touching_authorizations_do_not_collide
    """
    pilot, aircraft, zone = _single_slot_zone_scenario(api)

    fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T11:00:00Z",
    )
    fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T11:00:00Z",
        "2026-08-20T13:00:00Z",
    )
    straddling = fixtures.create_requested_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T10:30:00Z",
        "2026-08-20T12:00:00Z",
    )
    assert straddling["status"] == AuthorizationStatus.REQUESTED.value, (
        f"a third request is still lodged without a slot, got {straddling['status']}"
    )

    response = api.decide_authorization(
        straddling["id"], factories.approve_authorization_payload(), headers=airspace_authority
    )
    validate_error(response, ApiErrorId.ZONE_CAPACITY_EXCEEDED, 409)

    refused = validate_success(api.get_authorization(straddling["id"], headers=airspace_authority))
    assert refused["status"] == AuthorizationStatus.REQUESTED.value, (
        f"the refused decision leaves the row in REQUESTED, got {refused['status']}"
    )
    assert refused["granted_ceiling_ft"] is None, (
        f"no ceiling is granted by a refused decision, got {refused['granted_ceiling_ft']}"
    )
    zone_after = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert zone_after["reserved_slot_count"] == 2, (
        "the refused decision reserves nothing, so the count stays at the two touching "
        f"authorizations, got {zone_after['reserved_slot_count']}"
    )


def test_published_zone_reads_back_exactly_as_declared(api, airspace_authority):
    """PRD §3.4: "An `AirspaceAuthority` publishes a zone with a globally unique `designator` (1 to 30 characters), a `class_code` drawn from `B`, `C`, `D`, `E` and `G`, a `class_ceiling_ft` (integer 100 to 2000) that is the hard regulatory ceiling for that airspace, a `requires_authorization` flag that marks the airspace as controlled, a `max_concurrent_authorizations` capacity (integer 1 to 20), and an optional `structure_relief_eligible` flag that defaults to false."
    PRD §3.4: "A new zone starts with `reserved_slot_count` 0 and `version` 1."
    PRD §2.5: "Every resource also carries a `created_at`, the ISO 8601 UTC instant of creation taken from the logical clock."

    Design: Corner/entities/get_airspace_zone_returns_the_stored_representation
    """
    set_clock(api, "2026-08-02T00:00:00Z", headers=COMPLIANCE_OFFICER)
    payload = factories.zone_payload(
        class_code=ZoneClassCode.D.value,
        class_ceiling_ft=500,
        requires_authorization=True,
        max_concurrent_authorizations=4,
    )
    created = validate_success(api.create_zone(payload, headers=airspace_authority), 201)

    fetched = validate_success(api.get_zone(created["id"], headers=airspace_authority))

    assert_zone(
        fetched,
        designator=payload["designator"],
        class_code=ZoneClassCode.D.value,
        class_ceiling_ft=500,
        requires_authorization=True,
        max_concurrent_authorizations=4,
        structure_relief_eligible=False,
        reserved_slot_count=0,
        version=1,
    )
    assert fetched["id"] == created["id"], (
        f"the read must address the created zone, got {fetched['id']} for {created['id']}"
    )
    assert fetched["structure_relief_eligible"] is False, (
        "an omitted relief flag defaults to false, got "
        f"{fetched['structure_relief_eligible']!r}"
    )
    assert_instant_equals(fetched["created_at"], "2026-08-02T00:00:00Z", "zone created_at")


def test_takeoff_weight_above_the_declared_ceiling_is_rejected(api, compliance_officer):
    """PRD §3.3: "An airframe is created against its owner: the request carries `owner_pilot_id`, a `model` (1 to 80 characters, not blank), a `serial_number` (1 to 40 characters, unique within that owner — two different pilots may hold the same manufacturer serial, the same pilot may not), a `takeoff_weight_g` (integer 1 to 25000) and a `max_altitude_ft` (integer 1 to 5000, the manufacturer's altitude limit)."
    PRD §2.11: "7. **Body shape**, on every endpoint: all required fields present, every enum value inside its declared member set, every integer inside its declared range, every string non-blank, arrays well-formed, and `limit` within 1 to 100 with `offset` not negative — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/out_of_range_and_out_of_enum_values_are_rejected_on_creation
    """
    pilot = fixtures.create_pilot(api)
    headers = make_pilot_headers(pilot["id"])

    response = api.create_aircraft(
        factories.aircraft_payload(pilot["id"], takeoff_weight_g=25001), headers=headers
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    records, meta = validate_paginated(
        api.list_aircraft(params={"owner_pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 0, (
        f"the refused airframe must not be stored, list reports {meta['total_count']}"
    )
    assert records == [], f"expected no airframe rows, got {records}"


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_code", "F"),
        ("class_ceiling_ft", 2400),
        ("max_concurrent_authorizations", 21),
    ],
)
def test_zone_declaration_outside_the_declared_domain_is_rejected(
    api, airspace_authority, field, value
):
    """PRD §3.4: "An `AirspaceAuthority` publishes a zone with a globally unique `designator` (1 to 30 characters), a `class_code` drawn from `B`, `C`, `D`, `E` and `G`, a `class_ceiling_ft` (integer 100 to 2000) that is the hard regulatory ceiling for that airspace, a `requires_authorization` flag that marks the airspace as controlled, a `max_concurrent_authorizations` capacity (integer 1 to 20), and an optional `structure_relief_eligible` flag that defaults to false."
    PRD §2.11: "7. **Body shape**, on every endpoint: all required fields present, every enum value inside its declared member set, every integer inside its declared range, every string non-blank, arrays well-formed, and `limit` within 1 to 100 with `offset` not negative — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/out_of_range_and_out_of_enum_values_are_rejected_on_creation
    """
    payload = factories.zone_payload(**{field: value})

    response = api.create_zone(payload, headers=airspace_authority)
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    records, meta = validate_paginated(api.list_zones(headers=airspace_authority))
    assert meta["total_count"] == 0, (
        f"a zone refused on {field} must not be stored, list reports {meta['total_count']}"
    )
    assert records == [], f"expected no zone rows, got {records}"


def _ceiling_probe_scenario(api, airframe_max_altitude_ft):
    """A certified recreational pilot over a class D zone with a 700 ft ceiling,
    flying an airframe whose own limit the caller chooses."""
    set_clock(api, SETUP_INSTANT, headers=COMPLIANCE_OFFICER)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.RECREATIONAL.value, scheduled_at=SETUP_INSTANT
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=airframe_max_altitude_ft
    )
    zone = fixtures.create_controlled_zone(
        api,
        class_code=ZoneClassCode.D.value,
        class_ceiling_ft=700,
        max_concurrent_authorizations=3,
    )
    return pilot, aircraft, zone


def test_request_above_the_zone_class_ceiling_is_refused(api, airspace_authority):
    """PRD §3.4: "A `requested_ceiling_ft` greater than the lesser of the zone's `class_ceiling_ft` and the airframe's `max_altitude_ft` is refused with `ERR_ALTITUDE_CEILING_EXCEEDED`."
    PRD §2.11: "26. **Altitude ceiling**, on `POST /drone-ops/airspace-authorizations` and `POST /drone-ops/flights`: on an authorization request, `requested_ceiling_ft` is at most the smaller of the zone's `class_ceiling_ft` and the airframe's `max_altitude_ft`; on flight creation, `planned_max_altitude_ft` is at most the flight's effective ceiling, which is the cited authorization's `granted_ceiling_ft` when an `authorization_id` is supplied and 400 feet otherwise."

    Design: Corner/validations/requested_ceiling_above_either_hard_cap_returns_the_declared_error
    """
    pilot, aircraft, zone = _ceiling_probe_scenario(api, airframe_max_altitude_ft=900)

    response = api.create_authorization(
        factories.authorization_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            zone["version"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T11:00:00Z",
            requested_ceiling_ft=800,
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(response, ApiErrorId.ALTITUDE_CEILING_EXCEEDED, 422)

    _records, meta = validate_paginated(
        api.list_authorizations(params={"zone_id": zone["id"]}, headers=airspace_authority)
    )
    assert meta["total_count"] == 0, (
        f"the refused request must not be lodged, list reports {meta['total_count']}"
    )
    zone_after = fixtures.read_zone(api, zone["id"], headers=airspace_authority)
    assert zone_after["version"] == zone["version"], (
        f"a refused request leaves the zone version at {zone['version']}, got "
        f"{zone_after['version']}"
    )
    assert zone_after["reserved_slot_count"] == 0, (
        f"nothing is reserved by a refused request, got {zone_after['reserved_slot_count']}"
    )


def test_request_above_the_airframe_limit_is_refused(api, airspace_authority):
    """PRD §3.4: "A `requested_ceiling_ft` greater than the lesser of the zone's `class_ceiling_ft` and the airframe's `max_altitude_ft` is refused with `ERR_ALTITUDE_CEILING_EXCEEDED`."
    PRD §2.11: "26. **Altitude ceiling**, on `POST /drone-ops/airspace-authorizations` and `POST /drone-ops/flights`: on an authorization request, `requested_ceiling_ft` is at most the smaller of the zone's `class_ceiling_ft` and the airframe's `max_altitude_ft`; on flight creation, `planned_max_altitude_ft` is at most the flight's effective ceiling, which is the cited authorization's `granted_ceiling_ft` when an `authorization_id` is supplied and 400 feet otherwise."

    Design: Corner/validations/requested_ceiling_above_either_hard_cap_returns_the_declared_error
    """
    pilot, aircraft, zone = _ceiling_probe_scenario(api, airframe_max_altitude_ft=600)

    response = api.create_authorization(
        factories.authorization_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            zone["version"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T11:00:00Z",
            requested_ceiling_ft=650,
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(response, ApiErrorId.ALTITUDE_CEILING_EXCEEDED, 422)

    accepted = fixtures.create_requested_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T11:00:00Z",
        requested_ceiling_ft=600,
    )
    assert accepted["status"] == AuthorizationStatus.REQUESTED.value, (
        "a request exactly at the airframe limit is inside the lesser of the two hard caps, got "
        f"{accepted['status']}"
    )
    assert accepted["requested_ceiling_ft"] == 600, (
        f"the accepted request stores its asked-for ceiling, got {accepted['requested_ceiling_ft']}"
    )


FLIGHT_START = "2026-08-20T09:00:00Z"
FLIGHT_END = "2026-08-20T10:00:00Z"


def _flying_pilot_scenario(api):
    """A certified recreational pilot with a registered sub-250 g airframe."""
    set_clock(api, SETUP_INSTANT, headers=COMPLIANCE_OFFICER)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.RECREATIONAL.value, scheduled_at=SETUP_INSTANT
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    return pilot, aircraft


def test_uncontrolled_zone_needs_no_authorization_to_plan_a_flight(api, compliance_officer):
    """PRD §2.11: "24. **Controlled-airspace gate**, on `POST /drone-ops/flights` only: when the zone's `requires_authorization` is true, `authorization_id` must be supplied and must reference an authorization in `status` `APPROVED` whose `pilot_id`, `aircraft_id` and `zone_id` all match the flight's — otherwise `ERR_AUTHORIZATION_REQUIRED` (422)."
    PRD §3.7: "The flight is created in `PLANNED` with `investigation_status` `NONE`, `logged_minutes` 0, `altitude_exceedance` false, and `actual_start`, `actual_end`, `max_altitude_reached_ft`, `incident_occurred`, `incident_summary` and `cancellation_reason` all null."

    Design: Corner/validations/authorization_is_demanded_only_where_the_zone_declares_it
    """
    pilot, aircraft = _flying_pilot_scenario(api)
    open_zone = fixtures.create_zone(
        api, class_code=ZoneClassCode.E.value, class_ceiling_ft=1200, requires_authorization=False
    )

    flight = validate_success(
        api.create_flight(
            factories.flight_payload(
                pilot["id"],
                aircraft["id"],
                open_zone["id"],
                FLIGHT_START,
                FLIGHT_END,
                planned_max_altitude_ft=380,
            ),
            headers=make_pilot_headers(pilot["id"]),
        ),
        201,
    )

    assert flight["status"] == FlightStatus.PLANNED.value, (
        f"a flight over uncontrolled airspace plans without an authorization, got {flight['status']}"
    )
    assert flight["zone_id"] == open_zone["id"], (
        f"the flight must sit over the requested zone, got {flight['zone_id']}"
    )
    _records, meta = validate_paginated(
        api.list_flights(params={"zone_id": open_zone["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 1, (
        f"exactly the one planned flight is stored, list reports {meta['total_count']}"
    )


def test_controlled_zone_refuses_an_unauthorized_flight(api, compliance_officer):
    """PRD §2.11: "24. **Controlled-airspace gate**, on `POST /drone-ops/flights` only: when the zone's `requires_authorization` is true, `authorization_id` must be supplied and must reference an authorization in `status` `APPROVED` whose `pilot_id`, `aircraft_id` and `zone_id` all match the flight's — otherwise `ERR_AUTHORIZATION_REQUIRED` (422)."

    Design: Corner/validations/authorization_is_demanded_only_where_the_zone_declares_it
    """
    pilot, aircraft = _flying_pilot_scenario(api)
    controlled_zone = fixtures.create_controlled_zone(
        api, class_code=ZoneClassCode.C.value, class_ceiling_ft=1200
    )

    response = api.create_flight(
        factories.flight_payload(
            pilot["id"],
            aircraft["id"],
            controlled_zone["id"],
            FLIGHT_START,
            FLIGHT_END,
            planned_max_altitude_ft=380,
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(response, ApiErrorId.AUTHORIZATION_REQUIRED, 422)

    _records, meta = validate_paginated(
        api.list_flights(params={"zone_id": controlled_zone["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 0, (
        f"the refused flight must not be stored, list reports {meta['total_count']}"
    )


def test_controlled_zone_accepts_the_flight_that_cites_its_authorization(api, compliance_officer):
    """PRD §2.11: "24. **Controlled-airspace gate**, on `POST /drone-ops/flights` only: when the zone's `requires_authorization` is true, `authorization_id` must be supplied and must reference an authorization in `status` `APPROVED` whose `pilot_id`, `aircraft_id` and `zone_id` all match the flight's — otherwise `ERR_AUTHORIZATION_REQUIRED` (422)."
    PRD §3.7: "The flight is created in `PLANNED` with `investigation_status` `NONE`, `logged_minutes` 0, `altitude_exceedance` false, and `actual_start`, `actual_end`, `max_altitude_reached_ft`, `incident_occurred`, `incident_summary` and `cancellation_reason` all null."

    Design: Corner/validations/authorization_is_demanded_only_where_the_zone_declares_it
    """
    pilot, aircraft = _flying_pilot_scenario(api)
    controlled_zone = fixtures.create_controlled_zone(
        api, class_code=ZoneClassCode.C.value, class_ceiling_ft=1200
    )
    authorization = fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        controlled_zone["id"],
        "2026-08-20T08:00:00Z",
        "2026-08-20T12:00:00Z",
    )

    flight = validate_success(
        api.create_flight(
            factories.flight_payload(
                pilot["id"],
                aircraft["id"],
                controlled_zone["id"],
                FLIGHT_START,
                FLIGHT_END,
                planned_max_altitude_ft=380,
                authorization_id=authorization["id"],
            ),
            headers=make_pilot_headers(pilot["id"]),
        ),
        201,
    )

    assert flight["status"] == FlightStatus.PLANNED.value, (
        f"an authorized flight over controlled airspace plans, got {flight['status']}"
    )
    assert flight["authorization_id"] == authorization["id"], (
        f"the flight must cite its authorization, got {flight['authorization_id']}"
    )
    assert flight["investigation_status"] == "NONE", (
        f"a new flight carries no investigation, got {flight['investigation_status']}"
    )
    _records, meta = validate_paginated(
        api.list_flights(
            params={"authorization_id": authorization["id"]}, headers=compliance_officer
        )
    )
    assert meta["total_count"] == 1, (
        f"the authorization covers exactly the one flight, list reports {meta['total_count']}"
    )


def _authorized_window_scenario(api):
    """A recreational operation cleared into class D airspace between 08:00 and
    12:00, granted the flat 400 ft recreational ceiling."""
    pilot, aircraft = _flying_pilot_scenario(api)
    zone = fixtures.create_controlled_zone(
        api,
        class_code=ZoneClassCode.D.value,
        class_ceiling_ft=700,
        max_concurrent_authorizations=2,
    )
    authorization = fixtures.create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T08:00:00Z",
        "2026-08-20T12:00:00Z",
        requested_ceiling_ft=500,
    )
    assert authorization["granted_ceiling_ft"] == DEFAULT_EFFECTIVE_CEILING_FT, (
        "a recreational operator is capped at the flat 400 ft figure, got "
        f"{authorization['granted_ceiling_ft']}"
    )
    return pilot, aircraft, zone, authorization


@pytest.mark.parametrize(
    "planned_start,planned_end",
    [
        ("2026-08-20T07:30:00Z", "2026-08-20T09:00:00Z"),
        ("2026-08-20T09:00:00Z", "2026-08-20T12:00:00Z"),
    ],
)
def test_flight_outside_the_authorized_window_is_refused(
    api, compliance_officer, planned_start, planned_end
):
    """PRD §2.11: "25. **Authorization window containment**, on `POST /drone-ops/flights` only: the flight's `planned_start` is at or after the authorization's `window_start` and its `planned_end` is strictly before the authorization's `window_end` — otherwise `ERR_AUTHORIZATION_WINDOW_MISMATCH` (422)."

    Design: Corner/errors/authorization_containment_and_waiver_prerequisite_codes_are_triggerable
    """
    pilot, aircraft, zone, authorization = _authorized_window_scenario(api)

    response = api.create_flight(
        factories.flight_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            planned_start,
            planned_end,
            planned_max_altitude_ft=380,
            authorization_id=authorization["id"],
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(response, ApiErrorId.AUTHORIZATION_WINDOW_MISMATCH, 422)

    _records, meta = validate_paginated(
        api.list_flights(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 0, (
        f"a flight outside its authorized window is not stored, list reports {meta['total_count']}"
    )


def test_flight_above_the_granted_ceiling_is_refused(api, compliance_officer):
    """PRD §2.11: "26. **Altitude ceiling**, on `POST /drone-ops/airspace-authorizations` and `POST /drone-ops/flights`: on an authorization request, `requested_ceiling_ft` is at most the smaller of the zone's `class_ceiling_ft` and the airframe's `max_altitude_ft`; on flight creation, `planned_max_altitude_ft` is at most the flight's effective ceiling, which is the cited authorization's `granted_ceiling_ft` when an `authorization_id` is supplied and 400 feet otherwise."

    Design: Corner/errors/authorization_containment_and_waiver_prerequisite_codes_are_triggerable
    """
    pilot, aircraft, zone, authorization = _authorized_window_scenario(api)

    response = api.create_flight(
        factories.flight_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            FLIGHT_START,
            FLIGHT_END,
            planned_max_altitude_ft=420,
            authorization_id=authorization["id"],
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(response, ApiErrorId.ALTITUDE_CEILING_EXCEEDED, 422)

    _records, meta = validate_paginated(
        api.list_flights(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 0, (
        f"a flight above its granted ceiling is not stored, list reports {meta['total_count']}"
    )


def test_night_operation_backed_only_by_a_draft_application_is_refused(api, compliance_officer):
    """PRD §2.11: "23. **Special-operation waiver gate**, on `POST /drone-ops/flights` only: when exactly one of `over_people`, `night_operation` or `beyond_visual_line_of_sight` is true, `waiver_id` must be supplied and must reference a waiver of the matching `waiver_type` in `status` `APPROVED`, belonging to the same `pilot_id` and `aircraft_id`, whose `valid_until` is strictly after `planned_end` — otherwise `ERR_WAIVER_REQUIRED` (422)."

    Design: Corner/errors/authorization_containment_and_waiver_prerequisite_codes_are_triggerable
    """
    pilot, aircraft, zone, authorization = _authorized_window_scenario(api)
    draft = fixtures.create_draft_waiver(
        api, pilot["id"], aircraft["id"], waiver_type=WaiverType.NIGHT.value
    )
    assert draft["status"] == WaiverStatus.DRAFT.value, (
        f"the application opens in DRAFT, got {draft['status']}"
    )

    response = api.create_flight(
        factories.flight_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            FLIGHT_START,
            FLIGHT_END,
            planned_max_altitude_ft=380,
            authorization_id=authorization["id"],
            waiver_id=draft["id"],
            night_operation=True,
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(response, ApiErrorId.WAIVER_REQUIRED, 422)

    _records, meta = validate_paginated(
        api.list_flights(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 0, (
        "a night operation behind an unapproved application is not stored, list reports "
        f"{meta['total_count']}"
    )


def test_submitting_a_waiver_without_a_safety_case_is_refused(api, compliance_officer):
    """PRD §3.5: "Submission requires the pilot to be `CERTIFIED` — a lapsed or suspended pilot cannot push an application forward, which is the cross-entity guard that keeps waiver review tied to live certification — and requires at least one safety case to exist for the waiver, otherwise the submission is refused with `ERR_SAFETY_CASE_MISSING`."
    PRD §2.11: "30. **Safety case presence**, on `POST /drone-ops/waivers/{id}/submit` only: at least one safety case is attached to the waiver — otherwise `ERR_SAFETY_CASE_MISSING` (422)."

    Design: Corner/errors/authorization_containment_and_waiver_prerequisite_codes_are_triggerable
    """
    pilot, aircraft = _flying_pilot_scenario(api)
    draft = fixtures.create_draft_waiver(
        api, pilot["id"], aircraft["id"], waiver_type=WaiverType.NIGHT.value
    )

    response = api.submit_waiver(draft["id"], headers=make_pilot_headers(pilot["id"]))
    validate_error(response, ApiErrorId.SAFETY_CASE_MISSING, 422)

    unchanged = validate_success(api.get_waiver(draft["id"], headers=compliance_officer))
    assert unchanged["status"] == WaiverStatus.DRAFT.value, (
        f"the refused submission leaves the application in DRAFT, got {unchanged['status']}"
    )


def test_flight_inside_the_window_and_at_the_granted_ceiling_is_accepted(api, compliance_officer):
    """PRD §2.11: "25. **Authorization window containment**, on `POST /drone-ops/flights` only: the flight's `planned_start` is at or after the authorization's `window_start` and its `planned_end` is strictly before the authorization's `window_end` — otherwise `ERR_AUTHORIZATION_WINDOW_MISMATCH` (422)."
    PRD §2.11: "26. **Altitude ceiling**, on `POST /drone-ops/airspace-authorizations` and `POST /drone-ops/flights`: on an authorization request, `requested_ceiling_ft` is at most the smaller of the zone's `class_ceiling_ft` and the airframe's `max_altitude_ft`; on flight creation, `planned_max_altitude_ft` is at most the flight's effective ceiling, which is the cited authorization's `granted_ceiling_ft` when an `authorization_id` is supplied and 400 feet otherwise."

    Design: Corner/errors/authorization_containment_and_waiver_prerequisite_codes_are_triggerable
    """
    pilot, aircraft, zone, authorization = _authorized_window_scenario(api)

    flight = validate_success(
        api.create_flight(
            factories.flight_payload(
                pilot["id"],
                aircraft["id"],
                zone["id"],
                "2026-08-20T08:00:00Z",
                "2026-08-20T11:59:59Z",
                planned_max_altitude_ft=DEFAULT_EFFECTIVE_CEILING_FT,
                authorization_id=authorization["id"],
            ),
            headers=make_pilot_headers(pilot["id"]),
        ),
        201,
    )

    assert flight["status"] == FlightStatus.PLANNED.value, (
        "a window starting exactly at the authorization's start and ending strictly before its end "
        f"is admissible, got {flight['status']}"
    )
    assert flight["planned_max_altitude_ft"] == DEFAULT_EFFECTIVE_CEILING_FT, (
        "planning exactly at the granted ceiling is admissible, got "
        f"{flight['planned_max_altitude_ft']}"
    )
    _records, meta = validate_paginated(
        api.list_flights(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 1, (
        f"the accepted flight is stored exactly once, list reports {meta['total_count']}"
    )
