"""Breadth of the error catalogue, and the filters each collection declares.

Every not-found code, every uniqueness code, the repeat-action state codes and the
malformed-interval code are triggered here from the shortest path that reaches them,
alongside the operator-category and airframe eligibility gates and the declared
filters of the nine collections queried through their own list endpoints.
"""

import pytest

from test_helpers import (
    AIRSPACE_AUTHORITY,
    COMPLIANCE_OFFICER,
    AirRiskClass,
    ApiErrorId,
    AuthorizationStatus,
    BroadcastProtocol,
    CoverageStatus,
    FlightStatus,
    KnowledgeTestStatus,
    ModuleStatus,
    OperationCategory,
    OperatorCategory,
    PilotStatus,
    RegistrationStatus,
    RestrictionStatus,
    SafetyCaseReviewStatus,
    TestCode,
    WaiverStatus,
    WaiverType,
    ZoneClassCode,
    assert_instant_equals,
    assert_pagination_meta,
    factories,
    fixtures,
    get_success_data,
    make_pilot_headers,
    validate_error,
    validate_paginated,
)

# Syntactically valid identifiers that name no row in a freshly started service.
UNKNOWN_PILOT_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_KNOWLEDGE_TEST_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_CERTIFICATION_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_AIRCRAFT_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_MODULE_ID = "00000000-0000-4000-8000-000000000005"
UNKNOWN_ZONE_ID = "00000000-0000-4000-8000-000000000006"
UNKNOWN_AUTHORIZATION_ID = "00000000-0000-4000-8000-000000000007"
UNKNOWN_WAIVER_ID = "00000000-0000-4000-8000-000000000008"
UNKNOWN_SAFETY_CASE_ID = "00000000-0000-4000-8000-000000000009"
UNKNOWN_POLICY_ID = "00000000-0000-4000-8000-000000000010"
UNKNOWN_FLIGHT_ID = "00000000-0000-4000-8000-000000000011"
UNKNOWN_REPORT_ID = "00000000-0000-4000-8000-000000000012"
UNKNOWN_TFR_ID = "00000000-0000-4000-8000-000000000013"

# (reader method on the client, unknown identifier, the code that entity owns).
NOT_FOUND_READS = [
    pytest.param("get_pilot", UNKNOWN_PILOT_ID, ApiErrorId.PILOT_NOT_FOUND.value, id="pilot"),
    pytest.param(
        "get_knowledge_test",
        UNKNOWN_KNOWLEDGE_TEST_ID,
        ApiErrorId.KNOWLEDGE_TEST_NOT_FOUND.value,
        id="knowledge_test",
    ),
    pytest.param(
        "get_certification",
        UNKNOWN_CERTIFICATION_ID,
        ApiErrorId.CERTIFICATION_NOT_FOUND.value,
        id="certification",
    ),
    pytest.param(
        "get_aircraft", UNKNOWN_AIRCRAFT_ID, ApiErrorId.AIRCRAFT_NOT_FOUND.value, id="aircraft"
    ),
    pytest.param(
        "get_remote_id_module", UNKNOWN_MODULE_ID, ApiErrorId.MODULE_NOT_FOUND.value, id="module"
    ),
    pytest.param("get_zone", UNKNOWN_ZONE_ID, ApiErrorId.ZONE_NOT_FOUND.value, id="zone"),
    pytest.param(
        "get_authorization",
        UNKNOWN_AUTHORIZATION_ID,
        ApiErrorId.AUTHORIZATION_NOT_FOUND.value,
        id="authorization",
    ),
    pytest.param("get_waiver", UNKNOWN_WAIVER_ID, ApiErrorId.WAIVER_NOT_FOUND.value, id="waiver"),
    pytest.param(
        "get_safety_case",
        UNKNOWN_SAFETY_CASE_ID,
        ApiErrorId.SAFETY_CASE_NOT_FOUND.value,
        id="safety_case",
    ),
    pytest.param("get_policy", UNKNOWN_POLICY_ID, ApiErrorId.POLICY_NOT_FOUND.value, id="policy"),
    pytest.param("get_flight", UNKNOWN_FLIGHT_ID, ApiErrorId.FLIGHT_NOT_FOUND.value, id="flight"),
    pytest.param(
        "get_accident_report",
        UNKNOWN_REPORT_ID,
        ApiErrorId.REPORT_NOT_FOUND.value,
        id="accident_report",
    ),
    pytest.param("get_tfr", UNKNOWN_TFR_ID, ApiErrorId.TFR_NOT_FOUND.value, id="tfr"),
]


@pytest.mark.parametrize("reader,unknown_id,expected_error_id", NOT_FOUND_READS)
def test_an_unknown_path_id_answers_with_that_entitys_own_not_found_code(
    api, compliance_officer, reader, unknown_id, expected_error_id
):
    """PRD §2.6: "Identifiers embedded in a request path are resolved strictly left to right, and the first segment that fails to resolve determines the error."
    PRD §2.6: "Each entity has its own dedicated code, all of them HTTP 404: `ERR_PILOT_NOT_FOUND`, `ERR_KNOWLEDGE_TEST_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_AIRCRAFT_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_SAFETY_CASE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_FLIGHT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND` and `ERR_TFR_NOT_FOUND`."

    Design: Corner/errors/every_not_found_error_id_is_triggerable_with_an_unknown_id
    """
    response = getattr(api, reader)(unknown_id, headers=compliance_officer)
    error = validate_error(response, expected_error_id, 404)
    assert error["error_id"] == expected_error_id, (
        f"expected {expected_error_id} for an unknown id, got {error['error_id']}"
    )


def test_a_nested_path_reports_the_parent_before_the_nested_identifier(api, compliance_officer):
    """PRD §2.6: "A request that names a pilot and then a nested resource under that pilot fails with the pilot's not-found code before the nested identifier is examined at all."
    PRD §2.11: "6. **Path existence**, on every endpoint carrying a path id: each id resolves, left to right, with the code naming the entity of the failing segment as catalogued in §2.6 — for example `ERR_PILOT_NOT_FOUND` (404)."

    Design: Corner/errors/every_not_found_error_id_is_triggerable_with_an_unknown_id
    """
    response = api.schedule_knowledge_test(
        UNKNOWN_PILOT_ID,
        factories.knowledge_test_payload(TestCode.TRUST_RECREATIONAL.value),
        headers=compliance_officer,
    )
    validate_error(response, ApiErrorId.PILOT_NOT_FOUND.value, 404)


def test_an_unresolvable_body_reference_names_the_entity_it_could_not_find(
    api, compliance_officer, airspace_authority
):
    """PRD §2.6: "The same catalogue governs references supplied in a request body."
    PRD §2.6: "Every reference a payload carries — `pilot_id`, `owner_pilot_id`, `aircraft_id`, `zone_id`, `authorization_id`, `waiver_id`, `flight_id`, and each id listed in `acknowledged_tfr_ids` — must resolve to an existing row, and an unresolvable reference returns the code naming the entity that could not be found."

    Design: Corner/errors/every_not_found_error_id_is_triggerable_with_an_unknown_id
    """
    airframe_response = api.create_aircraft(
        factories.aircraft_payload(UNKNOWN_PILOT_ID), headers=compliance_officer
    )
    validate_error(airframe_response, ApiErrorId.PILOT_NOT_FOUND.value, 404)

    restriction_response = api.create_tfr(
        factories.tfr_payload(
            UNKNOWN_ZONE_ID, "2026-08-15T00:00:00Z", "2026-08-16T00:00:00Z"
        ),
        headers=airspace_authority,
    )
    validate_error(restriction_response, ApiErrorId.ZONE_NOT_FOUND.value, 404)


def _duplicate_pilot_email(api):
    """The same address in a different case, which the registry compares case-insensitively."""
    get_success_data(
        api.create_pilot(
            factories.pilot_payload(
                OperatorCategory.RECREATIONAL.value, email="Repeat.Case@example.com"
            ),
            headers=COMPLIANCE_OFFICER,
        ),
        201,
    )
    return api.create_pilot(
        factories.pilot_payload(
            OperatorCategory.COMMERCIAL.value, email="repeat.case@EXAMPLE.COM"
        ),
        headers=COMPLIANCE_OFFICER,
    )


def _duplicate_aircraft_serial(api):
    """The same airframe serial twice under one owner."""
    pilot = fixtures.create_pilot(api)
    serial = factories.unique_serial("AF")
    fixtures.create_aircraft(api, pilot["id"], serial_number=serial)
    return api.create_aircraft(
        factories.aircraft_payload(pilot["id"], serial_number=serial),
        headers=make_pilot_headers(pilot["id"]),
    )


def _duplicate_module_serial(api):
    """The same module serial twice on one airframe."""
    pilot = fixtures.create_pilot(api)
    airframe = fixtures.create_aircraft(api, pilot["id"])
    owner_headers = make_pilot_headers(pilot["id"])
    module_serial = factories.unique_serial("RID")
    get_success_data(
        api.create_remote_id_module(
            airframe["id"],
            factories.module_payload(module_serial=module_serial),
            headers=owner_headers,
        ),
        201,
    )
    return api.create_remote_id_module(
        airframe["id"],
        factories.module_payload(module_serial=module_serial),
        headers=owner_headers,
    )


def _duplicate_zone_designator(api):
    """The same designator twice, anywhere in the airspace registry."""
    designator = factories.unique_designator()
    fixtures.create_zone(api, designator=designator)
    return api.create_zone(
        factories.zone_payload(designator=designator), headers=AIRSPACE_AUTHORITY
    )


def _duplicate_policy_number(api):
    """The same policy number twice for one pilot."""
    pilot = fixtures.create_pilot(api)
    policy_number = factories.unique_policy_number()
    fixtures.create_filed_policy(api, pilot["id"], policy_number=policy_number)
    return api.create_policy(
        factories.policy_payload(
            pilot["id"],
            "2026-08-01T00:00:00Z",
            fixtures.FAR_FUTURE,
            policy_number=policy_number,
        ),
        headers=make_pilot_headers(pilot["id"]),
    )


UNIQUENESS_PROBES = [
    pytest.param(
        _duplicate_pilot_email, ApiErrorId.DUPLICATE_PILOT_EMAIL.value, id="pilot_email"
    ),
    pytest.param(
        _duplicate_aircraft_serial,
        ApiErrorId.DUPLICATE_AIRCRAFT_SERIAL.value,
        id="aircraft_serial",
    ),
    pytest.param(
        _duplicate_module_serial, ApiErrorId.DUPLICATE_MODULE_SERIAL.value, id="module_serial"
    ),
    pytest.param(
        _duplicate_zone_designator,
        ApiErrorId.DUPLICATE_ZONE_DESIGNATOR.value,
        id="zone_designator",
    ),
    pytest.param(
        _duplicate_policy_number, ApiErrorId.DUPLICATE_POLICY_NUMBER.value, id="policy_number"
    ),
]


@pytest.mark.parametrize("build_duplicate,expected_error_id", UNIQUENESS_PROBES)
def test_each_uniqueness_constraint_reports_its_own_duplicate_code(
    api, build_duplicate, expected_error_id
):
    """PRD §2.11: "10. **Uniqueness**, each with its own code, all HTTP 409: `email` unique across all pilots (`ERR_DUPLICATE_PILOT_EMAIL`) on `POST /drone-ops/pilots`; `serial_number` unique within `owner_pilot_id` (`ERR_DUPLICATE_AIRCRAFT_SERIAL`) on `POST /drone-ops/aircraft`; `module_serial` unique within `aircraft_id` (`ERR_DUPLICATE_MODULE_SERIAL`) on `POST /drone-ops/aircraft/{id}/remote-id-modules`; `designator` unique across all zones (`ERR_DUPLICATE_ZONE_DESIGNATOR`) on `POST /drone-ops/airspace-zones`; and `policy_number` unique within `pilot_id` (`ERR_DUPLICATE_POLICY_NUMBER`) on `POST /drone-ops/insurance-policies`."

    Design: Corner/errors/every_uniqueness_error_id_is_triggerable_and_scoped_as_declared
    """
    response = build_duplicate(api)

    validate_error(response, expected_error_id, 409)


def test_a_parent_scoped_uniqueness_value_is_free_under_a_different_parent(api):
    """PRD §2.11: "10. **Uniqueness**, each with its own code, all HTTP 409: `email` unique across all pilots (`ERR_DUPLICATE_PILOT_EMAIL`) on `POST /drone-ops/pilots`; `serial_number` unique within `owner_pilot_id` (`ERR_DUPLICATE_AIRCRAFT_SERIAL`) on `POST /drone-ops/aircraft`; `module_serial` unique within `aircraft_id` (`ERR_DUPLICATE_MODULE_SERIAL`) on `POST /drone-ops/aircraft/{id}/remote-id-modules`; `designator` unique across all zones (`ERR_DUPLICATE_ZONE_DESIGNATOR`) on `POST /drone-ops/airspace-zones`; and `policy_number` unique within `pilot_id` (`ERR_DUPLICATE_POLICY_NUMBER`) on `POST /drone-ops/insurance-policies`."

    Design: Corner/errors/every_uniqueness_error_id_is_triggerable_and_scoped_as_declared
    """
    owner = fixtures.create_pilot(api)
    other_owner = fixtures.create_pilot(api)

    serial = factories.unique_serial("AF")
    owned = fixtures.create_aircraft(api, owner["id"], serial_number=serial)
    other_owned = fixtures.create_aircraft(api, other_owner["id"], serial_number=serial)
    assert owned["id"] != other_owned["id"], "two owners may each hold the same serial"
    assert owned["serial_number"] == other_owned["serial_number"] == serial, (
        f"both airframes must keep the serial {serial}"
    )

    module_serial = factories.unique_serial("RID")
    first_module = get_success_data(
        api.create_remote_id_module(
            owned["id"],
            factories.module_payload(module_serial=module_serial),
            headers=make_pilot_headers(owner["id"]),
        ),
        201,
    )
    second_module = get_success_data(
        api.create_remote_id_module(
            other_owned["id"],
            factories.module_payload(module_serial=module_serial),
            headers=make_pilot_headers(other_owner["id"]),
        ),
        201,
    )
    assert first_module["id"] != second_module["id"], (
        "module_serial is scoped to one airframe, so a second airframe may reuse it"
    )

    policy_number = factories.unique_policy_number()
    first_policy = fixtures.create_filed_policy(api, owner["id"], policy_number=policy_number)
    second_policy = fixtures.create_filed_policy(
        api, other_owner["id"], policy_number=policy_number
    )
    assert first_policy["id"] != second_policy["id"], (
        "policy_number is scoped to one pilot, so a second pilot may reuse it"
    )


def test_a_globally_unique_value_is_refused_everywhere_and_stores_nothing(
    api, compliance_officer, airspace_authority
):
    """PRD §2.11: "10. **Uniqueness**, each with its own code, all HTTP 409: `email` unique across all pilots (`ERR_DUPLICATE_PILOT_EMAIL`) on `POST /drone-ops/pilots`; `serial_number` unique within `owner_pilot_id` (`ERR_DUPLICATE_AIRCRAFT_SERIAL`) on `POST /drone-ops/aircraft`; `module_serial` unique within `aircraft_id` (`ERR_DUPLICATE_MODULE_SERIAL`) on `POST /drone-ops/aircraft/{id}/remote-id-modules`; `designator` unique across all zones (`ERR_DUPLICATE_ZONE_DESIGNATOR`) on `POST /drone-ops/airspace-zones`; and `policy_number` unique within `pilot_id` (`ERR_DUPLICATE_POLICY_NUMBER`) on `POST /drone-ops/insurance-policies`."
    PRD §3.1: "A `ComplianceOfficer` creates a pilot record by supplying the operator's `full_name` (1 to 120 characters, not blank), an `email` (which must contain an `@` and is unique across all pilots, compared case-insensitively), and the `operator_category` that fixes the rule set the operator will fly under — either `RECREATIONAL` or `COMMERCIAL`."

    Design: Corner/errors/every_uniqueness_error_id_is_triggerable_and_scoped_as_declared
    """
    designator = factories.unique_designator()
    zone = fixtures.create_zone(api, designator=designator)
    refused_zone = api.create_zone(
        factories.zone_payload(
            ZoneClassCode.D.value, 700, True, 2, designator=designator
        ),
        headers=airspace_authority,
    )
    validate_error(refused_zone, ApiErrorId.DUPLICATE_ZONE_DESIGNATOR.value, 409)

    zones, zone_meta = validate_paginated(api.list_zones(headers=airspace_authority))
    assert zone_meta["total_count"] == 1, (
        f"the refused zone must not be stored; expected 1 zone, got {zone_meta['total_count']}"
    )
    assert [row["id"] for row in zones] == [zone["id"]], (
        f"expected only {zone['id']} in the registry, got {[row['id'] for row in zones]}"
    )

    email = "single.registry@example.com"
    pilot = get_success_data(
        api.create_pilot(
            factories.pilot_payload(OperatorCategory.RECREATIONAL.value, email=email),
            headers=compliance_officer,
        ),
        201,
    )
    refused_pilot = api.create_pilot(
        factories.pilot_payload(OperatorCategory.COMMERCIAL.value, email=email.upper()),
        headers=compliance_officer,
    )
    validate_error(refused_pilot, ApiErrorId.DUPLICATE_PILOT_EMAIL.value, 409)

    pilots, pilot_meta = validate_paginated(api.list_pilots(headers=compliance_officer))
    assert pilot_meta["total_count"] == 1, (
        f"the refused pilot must not be stored; expected 1 pilot, got "
        f"{pilot_meta['total_count']}"
    )
    assert pilots[0]["id"] == pilot["id"], (
        f"expected only {pilot['id']} on the roster, got {pilots[0]['id']}"
    )


def _regrade_a_graded_test(api):
    """A sitting already graded once; both grading destinations are terminal."""
    pilot = fixtures.create_pilot(api)
    test = fixtures.schedule_and_pass_knowledge_test(api, pilot)
    return api.grade_knowledge_test(
        test["id"], factories.grade_payload(100), headers=COMPLIANCE_OFFICER
    )


def _reverify_an_active_policy(api):
    """A policy already adjudicated out of PENDING_VERIFICATION."""
    pilot = fixtures.create_pilot(api)
    policy = fixtures.create_active_policy(api, pilot["id"])
    return api.verify_policy(
        policy["id"], factories.activate_policy_payload(), headers=COMPLIANCE_OFFICER
    )


def _recancel_a_cancelled_flight(api):
    """A flight already cancelled out of PLANNED."""
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.RECREATIONAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"], 249, 900)
    zone = fixtures.create_zone(api)
    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        airframe["id"],
        zone["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T10:00:00Z",
    )
    owner_headers = make_pilot_headers(pilot["id"])
    cancelled = get_success_data(
        api.cancel_flight(flight["id"], factories.cancellation_payload(), headers=owner_headers)
    )
    assert cancelled["status"] == FlightStatus.CANCELLED.value, (
        f"the first cancellation must land in CANCELLED, got {cancelled['status']}"
    )
    return api.cancel_flight(
        flight["id"], factories.cancellation_payload(), headers=owner_headers
    )


def _relift_a_lifted_restriction(api):
    """A restriction already lifted out of ACTIVE."""
    zone = fixtures.create_zone(api)
    restriction = fixtures.create_tfr(
        api, zone["id"], "2026-08-15T00:00:00Z", "2026-08-16T00:00:00Z", 200
    )
    lifted = get_success_data(api.lift_tfr(restriction["id"], headers=AIRSPACE_AUTHORITY))
    assert lifted["status"] == RestrictionStatus.LIFTED.value, (
        f"the first lift must land in LIFTED, got {lifted['status']}"
    )
    return api.lift_tfr(restriction["id"], headers=AIRSPACE_AUTHORITY)


REPEAT_PROBES = [
    pytest.param(_regrade_a_graded_test, ApiErrorId.TEST_ALREADY_GRADED.value, id="regrade_test"),
    pytest.param(
        _reverify_an_active_policy, ApiErrorId.POLICY_INVALID_STATE.value, id="reverify_policy"
    ),
    pytest.param(
        _recancel_a_cancelled_flight, ApiErrorId.FLIGHT_INVALID_STATE.value, id="recancel_flight"
    ),
    pytest.param(
        _relift_a_lifted_restriction, ApiErrorId.TFR_INVALID_STATE.value, id="relift_restriction"
    ),
]


def _zero_length_restriction_window(api):
    """`effective_until` equal to `effective_from` rather than strictly after it."""
    zone = fixtures.create_zone(api)
    return api.create_tfr(
        factories.tfr_payload(zone["id"], "2026-08-15T00:00:00Z", "2026-08-15T00:00:00Z", 300),
        headers=AIRSPACE_AUTHORITY,
    )


def _reversed_policy_period(api):
    """A period of cover that ends more than a year before it begins."""
    pilot = fixtures.create_pilot(api)
    return api.create_policy(
        factories.policy_payload(pilot["id"], "2027-08-01T00:00:00Z", "2026-09-01T00:00:00Z"),
        headers=make_pilot_headers(pilot["id"]),
    )


def _past_dated_flight_window(api):
    """A well-ordered window that nonetheless opens before the current instant."""
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.RECREATIONAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"], 249, 900)
    zone = fixtures.create_zone(api)
    fixtures.set_clock(api, "2026-08-12T00:00:00Z")
    return api.create_flight(
        factories.flight_payload(
            pilot["id"],
            airframe["id"],
            zone["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T10:00:00Z",
        ),
        headers=make_pilot_headers(pilot["id"]),
    )


MALFORMED_WINDOWS = [
    pytest.param(_zero_length_restriction_window, id="zero_length_restriction"),
    pytest.param(_reversed_policy_period, id="reversed_policy_period"),
    pytest.param(_past_dated_flight_window, id="past_dated_flight"),
]


@pytest.mark.parametrize("repeat_the_action,expected_error_id", REPEAT_PROBES)
def test_a_repeated_terminal_action_is_refused_with_that_entitys_state_code(
    api, repeat_the_action, expected_error_id
):
    """PRD §2.11: "13. **Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."
    PRD §3.1: "Either way `graded_at` is set to the current instant and both destinations are terminal, so a second grading attempt on the same sitting is refused with `ERR_TEST_ALREADY_GRADED`."
    PRD §3.6: "A `ComplianceOfficer` adjudicates the filing with an `outcome` of `ACTIVE` or `REJECTED`, and only from `PENDING_VERIFICATION`."
    PRD §3.7: "Cancellation carries a `cancellation_reason` and is admissible from `PLANNED` or `PREFLIGHT_CLEARED`."
    PRD §3.4: "The authority may lift an `ACTIVE` restriction ahead of its `effective_until`, moving it to `LIFTED`; and a restriction whose `effective_until` is at or before the current instant is lazily moved to `EXPIRED` when a preflight check or a launch reads it."
    PRD §3.4: "Both `LIFTED` and `EXPIRED` are terminal."

    Design: Corner/errors/repeat_actions_and_malformed_windows_are_rejected_with_their_own_codes
    """
    response = repeat_the_action(api)

    validate_error(response, expected_error_id, 409)


def test_the_logical_clock_refuses_a_target_at_or_before_its_current_value(
    api, compliance_officer
):
    """PRD §2.4: "An operator role advances the clock by supplying a target instant in the `to_iso8601` field; the response reports the two values `current_utc` (the clock after the move) and `previous_utc` (the clock before it)."
    PRD §2.4: "The clock is monotonic and forward-only: a target instant that is at or before the present clock value is rejected with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 409), so the supplied instant must be strictly later than the current one."
    PRD §2.11: "38. **Clock monotonicity**, on `POST /drone-ops/_clock/set_current_utc` only: `to_iso8601` is strictly later than the current clock value — otherwise `ERR_CLOCK_REWIND_FORBIDDEN` (409)."

    Design: Corner/errors/repeat_actions_and_malformed_windows_are_rejected_with_their_own_codes
    """
    moved = get_success_data(api.set_clock("2026-08-12T00:00:00Z", headers=compliance_officer))
    assert_instant_equals(moved["current_utc"], "2026-08-12T00:00:00Z", "current_utc after a move")
    assert_instant_equals(
        moved["previous_utc"], "2026-08-01T00:00:00Z", "previous_utc after the first move"
    )

    repeated = api.set_clock("2026-08-12T00:00:00Z", headers=compliance_officer)
    validate_error(repeated, ApiErrorId.CLOCK_REWIND_FORBIDDEN.value, 409)

    rewound = api.set_clock("2026-08-11T23:59:59Z", headers=compliance_officer)
    validate_error(rewound, ApiErrorId.CLOCK_REWIND_FORBIDDEN.value, 409)

    forward = get_success_data(api.set_clock("2026-08-12T00:00:01Z", headers=compliance_officer))
    assert_instant_equals(
        forward["previous_utc"],
        "2026-08-12T00:00:00Z",
        "previous_utc proves the refused targets never moved the clock",
    )


@pytest.mark.parametrize("build_malformed_window", MALFORMED_WINDOWS)
def test_a_malformed_interval_is_an_invalid_window_and_not_a_shape_error(
    api, build_malformed_window
):
    """PRD §2.11: "8. **Interval ordering**, on `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/flights`, `POST /drone-ops/insurance-policies` and `POST /drone-ops/tfrs`: `window_end` strictly after `window_start`, `planned_end` strictly after `planned_start`, `effective_until` strictly after `effective_from`, and on flight creation `planned_start` at or after the current instant — otherwise `ERR_INVALID_WINDOW` (400)."
    PRD §3.7: "The planned window is a **closed** interval — both `planned_start` and `planned_end` are inclusive — and `planned_end` must be strictly after `planned_start`, while `planned_start` must be at or after the current instant, so no flight may be filed into the past."

    Design: Corner/errors/repeat_actions_and_malformed_windows_are_rejected_with_their_own_codes
    """
    response = build_malformed_window(api)

    error = validate_error(response, ApiErrorId.INVALID_WINDOW.value, 400)
    assert error["error_id"] != ApiErrorId.INVALID_REQUEST.value, (
        "an ill-ordered interval is its own rung and must not be reported as a shape error"
    )


def test_a_recreational_operator_may_not_file_a_commercial_flight(api):
    """PRD §2.11: "27. **Rule-set distinction**, on `POST /drone-ops/flights` and `POST /drone-ops/pilots/{id}/knowledge-tests`: a flight whose `operation_category` is `COMMERCIAL` requires a pilot whose `operator_category` is `COMMERCIAL`; a pilot whose `operator_category` is `RECREATIONAL` may sit only the `TRUST_RECREATIONAL` exam and may fly only `RECREATIONAL` operations. A breach yields `ERR_RECREATIONAL_OPERATION_FORBIDDEN` (403)."

    Design: Corner/errors/category_and_airframe_eligibility_gates_are_triggerable
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.RECREATIONAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"], 249, 900)
    zone = fixtures.create_zone(api)
    owner_headers = make_pilot_headers(pilot["id"])
    assert pilot["operator_category"] == OperatorCategory.RECREATIONAL.value, (
        f"the probe needs a recreational operator, got {pilot['operator_category']}"
    )

    refused = api.create_flight(
        factories.flight_payload(
            pilot["id"],
            airframe["id"],
            zone["id"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T10:00:00Z",
            OperationCategory.COMMERCIAL.value,
        ),
        headers=owner_headers,
    )
    validate_error(refused, ApiErrorId.RECREATIONAL_OPERATION_FORBIDDEN.value, 403)

    accepted = get_success_data(
        api.create_flight(
            factories.flight_payload(
                pilot["id"],
                airframe["id"],
                zone["id"],
                "2026-08-20T09:00:00Z",
                "2026-08-20T10:00:00Z",
                OperationCategory.RECREATIONAL.value,
            ),
            headers=owner_headers,
        ),
        201,
    )
    assert accepted["operation_category"] == OperationCategory.RECREATIONAL.value, (
        "the identical window is flyable as a recreational operation, so the refusal above "
        f"was the rule set and not the window; got {accepted['operation_category']}"
    )


def test_a_recreational_operator_may_not_sit_the_commercial_exam(api, compliance_officer):
    """PRD §2.11: "27. **Rule-set distinction**, on `POST /drone-ops/flights` and `POST /drone-ops/pilots/{id}/knowledge-tests`: a flight whose `operation_category` is `COMMERCIAL` requires a pilot whose `operator_category` is `COMMERCIAL`; a pilot whose `operator_category` is `RECREATIONAL` may sit only the `TRUST_RECREATIONAL` exam and may fly only `RECREATIONAL` operations. A breach yields `ERR_RECREATIONAL_OPERATION_FORBIDDEN` (403)."
    PRD §3.1: "A `ComplianceOfficer` creates a pilot record by supplying the operator's `full_name` (1 to 120 characters, not blank), an `email` (which must contain an `@` and is unique across all pilots, compared case-insensitively), and the `operator_category` that fixes the rule set the operator will fly under — either `RECREATIONAL` or `COMMERCIAL`."

    Design: Corner/errors/category_and_airframe_eligibility_gates_are_triggerable
    """
    pilot = fixtures.create_pilot(api, OperatorCategory.RECREATIONAL.value)

    refused = api.schedule_knowledge_test(
        pilot["id"],
        factories.knowledge_test_payload(TestCode.PART107_COMMERCIAL.value),
        headers=compliance_officer,
    )
    validate_error(refused, ApiErrorId.RECREATIONAL_OPERATION_FORBIDDEN.value, 403)

    accepted = get_success_data(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(TestCode.TRUST_RECREATIONAL.value),
            headers=compliance_officer,
        ),
        201,
    )
    assert accepted["test_code"] == TestCode.TRUST_RECREATIONAL.value, (
        f"the permitted exam must be booked, got {accepted['test_code']}"
    )

    sittings, meta = validate_paginated(
        api.list_knowledge_tests(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 1, (
        f"the refused booking must leave no sitting behind; expected 1, got "
        f"{meta['total_count']}"
    )
    assert sittings[0]["id"] == accepted["id"], (
        f"expected only {accepted['id']} on the pilot's record, got {sittings[0]['id']}"
    )


def test_the_registration_and_grounding_gates_each_answer_with_their_own_code(
    api, compliance_officer
):
    """PRD §2.11: "18. **Registration gate**, on `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/flights`, `POST /drone-ops/flights/{id}/launch` and `POST /drone-ops/airspace-authorizations/{id}/decide`: the airframe's `registration_status` is `REGISTERED`; `PENDING_REGISTRATION` and `DEREGISTERED` airframes are rejected with `ERR_AIRCRAFT_NOT_REGISTERED` (409)."
    PRD §2.11: "19. **Grounding gate**, on `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/flights` and `POST /drone-ops/flights/{id}/launch`: the airframe's `registration_status` is not `GROUNDED` — otherwise `ERR_AIRCRAFT_GROUNDED` (409)."
    PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."

    Design: Corner/errors/category_and_airframe_eligibility_gates_are_triggerable
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.RECREATIONAL.value)
    zone = fixtures.create_zone(api)
    owner_headers = make_pilot_headers(pilot["id"])

    unregistered = fixtures.create_aircraft(api, pilot["id"], 249, 900)
    grounded = fixtures.create_grounded_aircraft(
        api, pilot["id"], "Rotor inspection", takeoff_weight_g=249, max_altitude_ft=900
    )
    registered = fixtures.create_registered_aircraft(api, pilot["id"], 249, 900)
    assert unregistered["registration_status"] == RegistrationStatus.PENDING_REGISTRATION.value, (
        f"expected PENDING_REGISTRATION, got {unregistered['registration_status']}"
    )
    assert grounded["registration_status"] == RegistrationStatus.GROUNDED.value, (
        f"expected GROUNDED, got {grounded['registration_status']}"
    )
    assert registered["registration_status"] == RegistrationStatus.REGISTERED.value, (
        f"expected REGISTERED, got {registered['registration_status']}"
    )

    def plan_with(aircraft_id):
        return api.create_flight(
            factories.flight_payload(
                pilot["id"],
                aircraft_id,
                zone["id"],
                "2026-08-20T09:00:00Z",
                "2026-08-20T10:00:00Z",
            ),
            headers=owner_headers,
        )

    validate_error(
        plan_with(unregistered["id"]), ApiErrorId.AIRCRAFT_NOT_REGISTERED.value, 409
    )
    validate_error(plan_with(grounded["id"]), ApiErrorId.AIRCRAFT_GROUNDED.value, 409)

    flown = get_success_data(plan_with(registered["id"]), 201)
    assert flown["aircraft_id"] == registered["id"], (
        "the identical body on a REGISTERED airframe is accepted, so both refusals above "
        f"were the airframe's own state; got {flown['aircraft_id']}"
    )


def test_a_suspended_owner_blocks_the_flight_before_the_airframe_gates(api, compliance_officer):
    """PRD §2.11: "15. **Pilot suspension gate**, on `POST /drone-ops/aircraft`, `POST /drone-ops/aircraft/{id}/register`, `POST /drone-ops/aircraft/{id}/return-to-service`, `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/waivers`, `POST /drone-ops/flights` and `POST /drone-ops/flights/{id}/launch`: the acting or target pilot's `status` is neither `SUSPENDED` nor `REVOKED` — otherwise `ERR_PILOT_SUSPENDED` (409)."
    PRD §2.11: "19. **Grounding gate**, on `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/flights` and `POST /drone-ops/flights/{id}/launch`: the airframe's `registration_status` is not `GROUNDED` — otherwise `ERR_AIRCRAFT_GROUNDED` (409)."
    PRD §3.9: "Either way the pilot moves to `SUSPENDED` and the depth-four cascade of §2.8 fires: the pilot's registered airframes are grounded, the live authorizations on those airframes are revoked with their zone slots released, and the planned or preflight-cleared flights depending on those authorizations are cancelled."
    PRD §3.9: "A suspended pilot can do nothing that requires certification: every gate that demands `CERTIFIED` refuses them, and `ERR_PILOT_SUSPENDED` is the refusal the ladder of §2.11 reaches first."

    Design: Corner/errors/category_and_airframe_eligibility_gates_are_triggerable
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.RECREATIONAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"], 249, 900)
    zone = fixtures.create_zone(api)

    suspended = get_success_data(
        api.suspend_pilot(
            pilot["id"],
            factories.suspension_payload("Enforcement audit of the operator"),
            headers=compliance_officer,
        )
    )
    assert suspended["status"] == PilotStatus.SUSPENDED.value, (
        f"expected SUSPENDED, got {suspended['status']}"
    )
    cascaded = get_success_data(api.get_aircraft(airframe["id"], headers=compliance_officer))
    assert cascaded["registration_status"] == RegistrationStatus.GROUNDED.value, (
        f"the suspension cascade must ground the airframe, got "
        f"{cascaded['registration_status']}"
    )

    refused = api.create_flight(
        factories.flight_payload(
            pilot["id"],
            airframe["id"],
            zone["id"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T10:00:00Z",
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(refused, ApiErrorId.PILOT_SUSPENDED.value, 409)

    flights, meta = validate_paginated(
        api.list_flights(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 0, (
        f"the refused plan must leave no flight row; expected 0, got {meta['total_count']}"
    )
    assert flights == [], f"expected an empty flight collection, got {flights}"


LISTING_CLOCK = "2026-08-10T00:00:00Z"
LISTING_MODULE_VALID_UNTIL = "2027-08-10T00:00:00Z"
LISTING_WINDOW_START = "2026-08-20T08:00:00Z"
LISTING_WINDOW_END = "2026-08-20T12:00:00Z"


def _listing_world(api):
    """One matching row per collection, plus a second pilot that must never match.

    The second pilot is `COMMERCIAL` and still `UNCERTIFIED` and owns nothing, so a
    roster filter that ORed its two facets instead of ANDing them would return two rows.
    """
    fixtures.set_clock(api, LISTING_CLOCK)

    pilot = fixtures.create_pilot(api, OperatorCategory.RECREATIONAL.value)
    sitting = fixtures.schedule_and_pass_knowledge_test(api, pilot, LISTING_CLOCK)
    pilot = fixtures.read_pilot(api, pilot["id"])
    other_pilot = fixtures.create_pilot(api, OperatorCategory.COMMERCIAL.value)

    filed_airframe = fixtures.create_aircraft(api, pilot["id"], 300, 900)
    module = fixtures.create_verified_module(
        api,
        filed_airframe,
        LISTING_MODULE_VALID_UNTIL,
        broadcast_protocol=BroadcastProtocol.BLUETOOTH_LE.value,
    )
    airframe = get_success_data(
        api.register_aircraft(filed_airframe["id"], headers=COMPLIANCE_OFFICER)
    )

    zone = fixtures.create_controlled_zone(
        api,
        class_code=ZoneClassCode.D.value,
        class_ceiling_ft=700,
        max_concurrent_authorizations=2,
    )
    authorization = fixtures.create_requested_authorization(
        api,
        pilot["id"],
        airframe["id"],
        zone["id"],
        LISTING_WINDOW_START,
        LISTING_WINDOW_END,
        400,
    )
    waiver = fixtures.create_draft_waiver(
        api, pilot["id"], airframe["id"], WaiverType.NIGHT.value, 400
    )
    safety_case = fixtures.attach_safety_case(api, waiver, 2, AirRiskClass.ARC_B.value)
    policy = fixtures.create_active_policy(
        api, pilot["id"], LISTING_CLOCK, LISTING_MODULE_VALID_UNTIL, 1500000, 25000
    )

    return {
        "pilot": pilot,
        "other_pilot": other_pilot,
        "sitting": sitting,
        "filed_airframe": filed_airframe,
        "airframe": airframe,
        "module": module,
        "zone": zone,
        "authorization": authorization,
        "waiver": waiver,
        "safety_case": safety_case,
        "policy": policy,
    }


def test_each_collection_answers_every_filter_it_declares(
    api, compliance_officer, airspace_authority, safety_reviewer
):
    """PRD §2.3: "Filters offered on a list endpoint narrow the result set before pagination is applied."
    PRD §2.3: "The pilot roster filters on `status` and `operator_category`; knowledge tests on `pilot_id` and `status`; certifications on `pilot_id`, `originating_test_id`, `supersedes_certification_id` and `status`; airframes on `owner_pilot_id` and `registration_status`; broadcast modules on `aircraft_id` and `status`; zones on `class_code`; restrictions on `zone_id` and `status`; authorizations on `pilot_id`, `aircraft_id`, `zone_id`, `waiver_id` and `status`; waivers on `pilot_id`, `aircraft_id`, `waiver_type` and `status`; safety cases on `waiver_id` and `review_status`; policies on `pilot_id` and `coverage_status`; flights on `pilot_id`, `aircraft_id`, `zone_id`, `authorization_id`, `waiver_id`, `covering_policy_id`, `status` and `investigation_status`; and accident reports on `flight_id`, `policy_id` and `status`."
    PRD §2.3: "`limit` caps the number of records returned: it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "`offset` is the number of records to skip before the page begins: it defaults to 0 and may not be negative."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` is true exactly when records remain beyond the current window."
    PRD §3.3: "At creation the service computes `remote_id_required` once and never again: it is true exactly when `takeoff_weight_g` is **strictly greater** than 250 grams."

    Design: Corner/endpoints/every_collection_endpoint_answers_its_declared_filters
    """
    world = _listing_world(api)
    assert world["filed_airframe"]["remote_id_required"] is True, (
        "a 300 g airframe is above the 250 g threshold, so the fixture is only reachable "
        "through the remote-ID path"
    )
    assert world["module"]["status"] == ModuleStatus.VERIFIED.value, (
        f"expected a VERIFIED module, got {world['module']['status']}"
    )
    assert world["airframe"]["registration_status"] == RegistrationStatus.REGISTERED.value, (
        f"expected REGISTERED, got {world['airframe']['registration_status']}"
    )

    queries = [
        (
            api.list_pilots,
            {
                "status": PilotStatus.CERTIFIED.value,
                "operator_category": OperatorCategory.RECREATIONAL.value,
                "limit": 10,
                "offset": 0,
            },
            compliance_officer,
            world["pilot"]["id"],
        ),
        (
            api.list_knowledge_tests,
            {"pilot_id": world["pilot"]["id"], "status": KnowledgeTestStatus.PASSED.value},
            compliance_officer,
            world["sitting"]["id"],
        ),
        (
            api.list_aircraft,
            {
                "owner_pilot_id": world["pilot"]["id"],
                "registration_status": RegistrationStatus.REGISTERED.value,
            },
            compliance_officer,
            world["airframe"]["id"],
        ),
        (
            api.list_remote_id_modules,
            {"aircraft_id": world["airframe"]["id"], "status": ModuleStatus.VERIFIED.value},
            airspace_authority,
            world["module"]["id"],
        ),
        (
            api.list_zones,
            {"class_code": ZoneClassCode.D.value},
            airspace_authority,
            world["zone"]["id"],
        ),
        (
            api.list_authorizations,
            {
                "pilot_id": world["pilot"]["id"],
                "aircraft_id": world["airframe"]["id"],
                "zone_id": world["zone"]["id"],
                "status": AuthorizationStatus.REQUESTED.value,
            },
            airspace_authority,
            world["authorization"]["id"],
        ),
        (
            api.list_waivers,
            {
                "pilot_id": world["pilot"]["id"],
                "aircraft_id": world["airframe"]["id"],
                "waiver_type": WaiverType.NIGHT.value,
                "status": WaiverStatus.DRAFT.value,
            },
            compliance_officer,
            world["waiver"]["id"],
        ),
        (
            api.list_safety_cases,
            {
                "waiver_id": world["waiver"]["id"],
                "review_status": SafetyCaseReviewStatus.PENDING.value,
            },
            safety_reviewer,
            world["safety_case"]["id"],
        ),
        (
            api.list_policies,
            {"pilot_id": world["pilot"]["id"], "coverage_status": CoverageStatus.ACTIVE.value},
            compliance_officer,
            world["policy"]["id"],
        ),
    ]

    for lister, params, headers, expected_id in queries:
        rows, meta = validate_paginated(lister(params=params, headers=headers))
        assert_pagination_meta(meta, 10, 0, 1)
        assert [row["id"] for row in rows] == [expected_id], (
            f"{lister.__name__} with {params} must return exactly [{expected_id}], got "
            f"{[row['id'] for row in rows]}"
        )


def test_a_single_wrong_filter_facet_empties_the_collection_without_erroring(
    api, compliance_officer, airspace_authority, safety_reviewer
):
    """PRD §2.3: "Filters offered on a list endpoint narrow the result set before pagination is applied."
    PRD §2.3: "The pilot roster filters on `status` and `operator_category`; knowledge tests on `pilot_id` and `status`; certifications on `pilot_id`, `originating_test_id`, `supersedes_certification_id` and `status`; airframes on `owner_pilot_id` and `registration_status`; broadcast modules on `aircraft_id` and `status`; zones on `class_code`; restrictions on `zone_id` and `status`; authorizations on `pilot_id`, `aircraft_id`, `zone_id`, `waiver_id` and `status`; waivers on `pilot_id`, `aircraft_id`, `waiver_type` and `status`; safety cases on `waiver_id` and `review_status`; policies on `pilot_id` and `coverage_status`; flights on `pilot_id`, `aircraft_id`, `zone_id`, `authorization_id`, `waiver_id`, `covering_policy_id`, `status` and `investigation_status`; and accident reports on `flight_id`, `policy_id` and `status`."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` is true exactly when records remain beyond the current window."

    Design: Corner/endpoints/every_collection_endpoint_answers_its_declared_filters
    """
    world = _listing_world(api)

    misses = [
        (api.list_pilots, {"status": PilotStatus.SUSPENDED.value}, compliance_officer),
        (
            api.list_knowledge_tests,
            {"pilot_id": world["other_pilot"]["id"]},
            compliance_officer,
        ),
        (
            api.list_aircraft,
            {"registration_status": RegistrationStatus.GROUNDED.value},
            compliance_officer,
        ),
        (api.list_remote_id_modules, {"status": ModuleStatus.EXPIRED.value}, airspace_authority),
        (api.list_zones, {"class_code": ZoneClassCode.G.value}, airspace_authority),
        (
            api.list_authorizations,
            {"status": AuthorizationStatus.APPROVED.value},
            airspace_authority,
        ),
        (api.list_waivers, {"status": WaiverStatus.APPROVED.value}, compliance_officer),
        (
            api.list_safety_cases,
            {"review_status": SafetyCaseReviewStatus.CLEARED.value},
            safety_reviewer,
        ),
        (api.list_policies, {"coverage_status": CoverageStatus.EXPIRED.value}, compliance_officer),
    ]

    for lister, params, headers in misses:
        rows, meta = validate_paginated(lister(params=params, headers=headers))
        assert_pagination_meta(meta, 10, 0, 0)
        assert rows == [], (
            f"{lister.__name__} with {params} matches nothing the fixture built, so the page "
            f"must be empty rather than an error; got {rows}"
        )
