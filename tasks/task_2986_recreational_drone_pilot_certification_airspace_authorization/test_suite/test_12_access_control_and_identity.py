"""Identity headers, role admissibility and pilot ownership on the Drone Operations Service.

Every request — reads included — carries `X-User-ID` and `X-User-Role`, and the first
three rungs of the validation ladder are header presence, role admissibility and pilot
ownership. The tests below probe each boundary from both sides: the refusal a wrong
principal receives, and the same operation succeeding for the principal who owns it.
"""

import pytest

from test_helpers import (
    AIRSPACE_AUTHORITY,
    AIRSPACE_AUTHORITY_ID,
    COMPLIANCE_OFFICER,
    INVESTIGATION_OFFICER,
    NO_HEADERS,
    SAFETY_REVIEWER,
    SAFETY_REVIEWER_ID,
    WAIVER_APPROVER,
    WAIVER_APPROVER_ID,
    AirRiskClass,
    ApiErrorId,
    AuthorizationStatus,
    FlightStatus,
    InvestigationStatus,
    KnowledgeTestStatus,
    PilotStatus,
    PreflightResult,
    RegistrationStatus,
    ReportStatus,
    RestrictionStatus,
    Role,
    SafetyCaseReviewStatus,
    TestCode,
    WaiverStatus,
    WaiverType,
    ZoneClassCode,
    assert_instant_equals,
    factories,
    fixtures,
    headers_empty_role,
    headers_empty_user_id,
    headers_missing_role,
    headers_missing_user_id,
    make_pilot_headers,
    shift_days,
    validate_error,
    validate_paginated,
    validate_success,
)

# Well-formed identifiers that are deliberately never stored, so that a probe which
# reaches the existence rung would answer a not-found code instead of a role refusal.
UNKNOWN_AUTHORIZATION_ID = "00000000-0000-4000-8000-0000000000a1"
UNKNOWN_KNOWLEDGE_TEST_ID = "00000000-0000-4000-8000-0000000000a2"
UNKNOWN_WAIVER_DECIDE_ID = "00000000-0000-4000-8000-0000000000a3"
UNKNOWN_WAIVER_CLEAR_ID = "00000000-0000-4000-8000-0000000000a4"
UNKNOWN_AIRCRAFT_ID = "00000000-0000-4000-8000-0000000000a5"
UNKNOWN_ZONE_ID = "00000000-0000-4000-8000-0000000000a6"
UNKNOWN_REPORT_ID = "00000000-0000-4000-8000-0000000000a7"
UNKNOWN_PILOT_ID = "00000000-0000-4000-8000-0000000000a8"
UNKNOWN_CERTIFICATION_ID = "00000000-0000-4000-8000-0000000000b4"


# ---------------------------------------------------------------------------
# One probe per role boundary. Every probe aims at an id that was never stored,
# so a service that resolved the path before checking the role would answer a
# not-found code and leak the existence of resources to callers who are not
# admitted to the endpoint at all.
# ---------------------------------------------------------------------------


def _pilot_decides_an_authorization(api, pilot_id):
    return api.decide_authorization(
        UNKNOWN_AUTHORIZATION_ID,
        factories.approve_authorization_payload(),
        headers=make_pilot_headers(pilot_id),
    )


def _airspace_authority_grades_a_knowledge_test(api, pilot_id):
    return api.grade_knowledge_test(
        UNKNOWN_KNOWLEDGE_TEST_ID,
        factories.grade_payload(raw_score=90),
        headers=AIRSPACE_AUTHORITY,
    )


def _safety_reviewer_decides_a_waiver(api, pilot_id):
    return api.decide_waiver(
        UNKNOWN_WAIVER_DECIDE_ID,
        factories.approve_waiver_payload(),
        headers=SAFETY_REVIEWER,
    )


def _waiver_approver_clears_a_safety_case(api, pilot_id):
    return api.clear_waiver_safety_case(
        UNKNOWN_WAIVER_CLEAR_ID,
        factories.clear_safety_case_payload(),
        headers=WAIVER_APPROVER,
    )


def _compliance_officer_files_a_flight(api, pilot_id):
    return api.create_flight(
        factories.flight_payload(
            pilot_id,
            UNKNOWN_AIRCRAFT_ID,
            UNKNOWN_ZONE_ID,
            "2026-08-15T09:00:00Z",
            "2026-08-15T10:00:00Z",
            planned_max_altitude_ft=380,
        ),
        headers=COMPLIANCE_OFFICER,
    )


def _investigation_officer_publishes_a_zone(api, pilot_id):
    return api.create_zone(
        factories.zone_payload(class_ceiling_ft=400, max_concurrent_authorizations=1),
        headers=INVESTIGATION_OFFICER,
    )


def _compliance_officer_closes_an_accident_report(api, pilot_id):
    return api.close_accident_report(
        UNKNOWN_REPORT_ID,
        factories.close_report_payload([factories.damage_line("Airframe", 1000)]),
        headers=COMPLIANCE_OFFICER,
    )


def _safety_reviewer_suspends_a_pilot(api, pilot_id):
    return api.suspend_pilot(
        UNKNOWN_PILOT_ID,
        factories.suspension_payload("Not this role's call to make"),
        headers=SAFETY_REVIEWER,
    )


ROLE_BOUNDARY_PROBES = [
    ("pilot_decides_an_authorization", _pilot_decides_an_authorization),
    ("airspace_authority_grades_a_knowledge_test", _airspace_authority_grades_a_knowledge_test),
    ("safety_reviewer_decides_a_waiver", _safety_reviewer_decides_a_waiver),
    ("waiver_approver_clears_a_safety_case", _waiver_approver_clears_a_safety_case),
    ("compliance_officer_files_a_flight", _compliance_officer_files_a_flight),
    ("investigation_officer_publishes_a_zone", _investigation_officer_publishes_a_zone),
    ("compliance_officer_closes_an_accident_report", _compliance_officer_closes_an_accident_report),
    ("safety_reviewer_suspends_a_pilot", _safety_reviewer_suspends_a_pilot),
]

NOT_FOUND_CODES_THAT_MUST_NOT_LEAK = {
    ApiErrorId.PILOT_NOT_FOUND.value,
    ApiErrorId.KNOWLEDGE_TEST_NOT_FOUND.value,
    ApiErrorId.AIRCRAFT_NOT_FOUND.value,
    ApiErrorId.ZONE_NOT_FOUND.value,
    ApiErrorId.AUTHORIZATION_NOT_FOUND.value,
    ApiErrorId.WAIVER_NOT_FOUND.value,
    ApiErrorId.REPORT_NOT_FOUND.value,
}


@pytest.mark.parametrize(
    "probe",
    [probe for _, probe in ROLE_BOUNDARY_PROBES],
    ids=[name for name, _ in ROLE_BOUNDARY_PROBES],
)
def test_an_operation_reserved_to_one_role_refuses_every_other_role(api, probe):
    """PRD §2.1: "If `X-User-Role` carries a value that is not one of the six roles below, or names a role that is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "2. **Role admissibility**, on every endpoint: `X-User-Role` names one of the six declared roles and that role appears in the endpoint's authorised list — otherwise `ERR_UNAUTHORIZED` (403)."
    PRD §2.11: "6. **Path existence**, on every endpoint carrying a path id: each id resolves, left to right, with the code naming the entity of the failing segment as catalogued in §2.6 — for example `ERR_PILOT_NOT_FOUND` (404)."

    Design: Corner/rbac/each_roles_exclusive_operation_is_unauthorized_for_every_other_role
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    pilot = fixtures.create_pilot(api)

    response = probe(api, pilot["id"])

    body = response.json()
    actual = body.get("data", {}).get("error_id")
    assert actual not in NOT_FOUND_CODES_THAT_MUST_NOT_LEAK, (
        f"role admissibility is rung 2 and path existence is rung 6, so an unauthorised caller "
        f"must not learn whether the referenced row exists, got {actual}"
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED, 403)


def test_a_role_refused_one_endpoint_still_reads_the_shared_pilot_record(api):
    """PRD §2.1: "If `X-User-Role` carries a value that is not one of the six roles below, or names a role that is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.11: "2. **Role admissibility**, on every endpoint: `X-User-Role` names one of the six declared roles and that role appears in the endpoint's authorised list — otherwise `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/each_roles_exclusive_operation_is_unauthorized_for_every_other_role
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    pilot = fixtures.create_pilot(api)

    refused = api.suspend_pilot(
        pilot["id"],
        factories.suspension_payload("Not this role's call to make"),
        headers=SAFETY_REVIEWER,
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED, 403)

    shared_read = validate_success(api.get_pilot(pilot["id"], headers=SAFETY_REVIEWER))
    assert shared_read["status"] == PilotStatus.UNCERTIFIED.value, (
        f"the same role that may not suspend a pilot is on the pilot read's authorised list, "
        f"expected UNCERTIFIED, got {shared_read['status']}"
    )
    assert shared_read["id"] == pilot["id"], (
        f"expected the read to return pilot {pilot['id']}, got {shared_read['id']}"
    )


def test_privileged_writes_refused_on_role_leave_the_datastore_untouched(api):
    """PRD §2.1: "If `X-User-Role` carries a value that is not one of the six roles below, or names a role that is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.5: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/rbac/each_roles_exclusive_operation_is_unauthorized_for_every_other_role
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    pilot = fixtures.create_pilot(api)
    assert pilot["version"] == 1, f"a freshly created pilot starts at version 1, got {pilot['version']}"

    for _name, probe in ROLE_BOUNDARY_PROBES:
        validate_error(probe(api, pilot["id"]), ApiErrorId.UNAUTHORIZED, 403)

    zones, zone_meta = validate_paginated(api.list_zones(headers=AIRSPACE_AUTHORITY))
    assert zone_meta["total_count"] == 0, (
        f"the zone publication was refused on role, so no zone may exist, "
        f"got total_count {zone_meta['total_count']}"
    )
    assert zones == [], f"expected an empty zone collection, got {len(zones)} rows"

    after = fixtures.read_pilot(api, pilot["id"])
    assert after["version"] == 1, (
        f"none of the refused calls mutated the pilot, so its version must still be 1, "
        f"got {after['version']}"
    )
    assert after["status"] == PilotStatus.UNCERTIFIED.value, (
        f"the refused suspension must not have moved the pilot, got {after['status']}"
    )


# ---------------------------------------------------------------------------
# Identity-header shapes that must all fail authentication. A blank value is the
# empty string: it is a legal HTTP header value, so the header really is sent
# present-but-empty rather than quietly dropped.
# ---------------------------------------------------------------------------

BLANK_IDENTITY_HEADERS = {"X-User-ID": "", "X-User-Role": "", "Content-Type": "application/json"}

MALFORMED_IDENTITY_HEADERS = [
    ("empty_user_id", headers_empty_user_id(Role.COMPLIANCE_OFFICER.value)),
    ("empty_role", headers_empty_role("cx-user-1")),
    ("absent_user_id", headers_missing_user_id(Role.COMPLIANCE_OFFICER.value)),
    ("absent_role", headers_missing_role("cx-user-1")),
    ("both_absent", NO_HEADERS),
    ("both_empty", BLANK_IDENTITY_HEADERS),
]


@pytest.mark.parametrize(
    "identity_headers",
    [headers for _, headers in MALFORMED_IDENTITY_HEADERS],
    ids=[name for name, _ in MALFORMED_IDENTITY_HEADERS],
)
def test_a_blank_or_absent_identity_header_fails_authentication(api, identity_headers):
    """PRD §2.1: "If either header is absent, or present but empty or whitespace-only, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."
    PRD §2.11: "1. **Header presence**, on every endpoint: `X-User-Role` and `X-User-ID` are present and are non-empty, non-whitespace strings — otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/blank_or_missing_identity_headers_are_rejected_before_any_other_check
    """
    fixtures.set_clock(api, "2026-08-06T00:00:00Z")
    pilot = fixtures.create_pilot(api)

    response = api.get_pilot(pilot["id"], headers=identity_headers)

    validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)
    message = response.json()["data"]["message"]
    assert isinstance(message, str) and message.strip(), (
        f"the error body must carry a non-empty message, got {message!r}"
    )


def test_an_empty_role_is_an_authentication_failure_not_an_authorization_failure(api):
    """PRD §2.1: "If either header is absent, or present but empty or whitespace-only, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."
    PRD §2.1: "If `X-User-Role` carries a value that is not one of the six roles below, or names a role that is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.11: "1. **Header presence**, on every endpoint: `X-User-Role` and `X-User-ID` are present and are non-empty, non-whitespace strings — otherwise `ERR_UNAUTHENTICATED` (401)."
    PRD §2.11: "2. **Role admissibility**, on every endpoint: `X-User-Role` names one of the six declared roles and that role appears in the endpoint's authorised list — otherwise `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/blank_or_missing_identity_headers_are_rejected_before_any_other_check
    """
    fixtures.set_clock(api, "2026-08-06T00:00:00Z")
    pilot = fixtures.create_pilot(api)

    response = api.get_pilot(pilot["id"], headers=headers_empty_role("cx-user-1"))

    actual = response.json()["data"]["error_id"]
    assert actual != ApiErrorId.UNAUTHORIZED.value, (
        "an empty role is a missing identity at rung 1, not a role that happens to be absent "
        "from the endpoint's authorised list at rung 2"
    )
    validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)


def test_authentication_is_decided_before_the_path_id_is_resolved(api):
    """PRD §2.1: "If either header is absent, or present but empty or whitespace-only, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."
    PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "1. **Header presence**, on every endpoint: `X-User-Role` and `X-User-ID` are present and are non-empty, non-whitespace strings — otherwise `ERR_UNAUTHENTICATED` (401)."
    PRD §2.11: "6. **Path existence**, on every endpoint carrying a path id: each id resolves, left to right, with the code naming the entity of the failing segment as catalogued in §2.6 — for example `ERR_PILOT_NOT_FOUND` (404)."

    Design: Corner/rbac/blank_or_missing_identity_headers_are_rejected_before_any_other_check
    """
    fixtures.set_clock(api, "2026-08-06T00:00:00Z")
    pilot = fixtures.create_pilot(api)

    response = api.get_certification(UNKNOWN_CERTIFICATION_ID, headers=BLANK_IDENTITY_HEADERS)

    actual = response.json()["data"]["error_id"]
    assert actual != ApiErrorId.CERTIFICATION_NOT_FOUND.value, (
        "rung 1 precedes rung 6, so a request with a blank identity must not report that the "
        "addressed certification is missing"
    )
    validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)

    # Every probe above is a read, so the pilot created for the test is still readable
    # with a well-formed identity.
    readable = validate_success(api.get_pilot(pilot["id"], headers=COMPLIANCE_OFFICER))
    assert readable["id"] == pilot["id"], (
        f"expected the same pilot {pilot['id']} to remain readable, got {readable['id']}"
    )


# ---------------------------------------------------------------------------
# Ownership: one pilot owns a registered airframe, a second pilot owns nothing.
# ---------------------------------------------------------------------------

OWNERSHIP_PROBES = [
    "read_another_pilots_airframe",
    "attach_a_module_to_another_pilots_airframe",
    "create_an_airframe_owned_by_another_pilot",
    "file_a_flight_in_another_pilots_name",
]


def _two_pilots_and_one_registered_airframe(api):
    fixtures.set_clock(api, "2026-08-08T00:00:00Z")
    owner = fixtures.create_pilot(api)
    intruder = fixtures.create_pilot(api)
    airframe = fixtures.create_registered_aircraft(api, owner["id"], 249, 900)
    zone = fixtures.create_zone(api, class_code="G", class_ceiling_ft=400)
    return owner, intruder, airframe, zone


def _run_ownership_probe(api, probe, owner, intruder, airframe, zone):
    intruder_headers = make_pilot_headers(intruder["id"])
    if probe == "read_another_pilots_airframe":
        return api.get_aircraft(airframe["id"], headers=intruder_headers)
    if probe == "attach_a_module_to_another_pilots_airframe":
        return api.create_remote_id_module(
            airframe["id"], factories.module_payload(), headers=intruder_headers
        )
    if probe == "create_an_airframe_owned_by_another_pilot":
        return api.create_aircraft(
            factories.aircraft_payload(owner["id"], takeoff_weight_g=249, max_altitude_ft=900),
            headers=intruder_headers,
        )
    return api.create_flight(
        factories.flight_payload(
            owner["id"],
            airframe["id"],
            zone["id"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T10:00:00Z",
            planned_max_altitude_ft=380,
        ),
        headers=intruder_headers,
    )


@pytest.mark.parametrize("probe", OWNERSHIP_PROBES)
def test_a_pilot_cannot_reach_another_pilots_airframe_or_act_in_their_name(api, probe):
    """PRD §2.1: "When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of the acting `Pilot` entity; ownership checks on any resource that references a `Pilot` compare the resource's own pilot reference to `X-User-ID`."
    PRD §2.1: "The same comparison applies to the body: any `pilot_id` or `owner_pilot_id` a pilot supplies in a request payload must equal their own `X-User-ID`."
    PRD §2.1: "A mismatch on either the addressed resource or the submitted body is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."
    PRD §2.11: "3. **Pilot ownership**, on every endpoint a `Pilot` may call: `X-User-ID` equals the owning pilot of the addressed resource and equals any `pilot_id` or `owner_pilot_id` in the body — otherwise `ERR_OWNERSHIP_VIOLATION` (403)."

    Design: Corner/rbac/a_pilot_cannot_reach_another_pilots_airframe_or_file_flights_in_their_name
    """
    owner, intruder, airframe, zone = _two_pilots_and_one_registered_airframe(api)

    response = _run_ownership_probe(api, probe, owner, intruder, airframe, zone)

    validate_error(response, ApiErrorId.OWNERSHIP_VIOLATION, 403)


def test_pilot_ownership_is_decided_before_body_shape_and_certification(api):
    """PRD §2.1: "A mismatch on either the addressed resource or the submitted body is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."
    PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "3. **Pilot ownership**, on every endpoint a `Pilot` may call: `X-User-ID` equals the owning pilot of the addressed resource and equals any `pilot_id` or `owner_pilot_id` in the body — otherwise `ERR_OWNERSHIP_VIOLATION` (403)."
    PRD §2.11: "16. **Certification gate**, on `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/waivers/{id}/submit`, `POST /drone-ops/flights`, `POST /drone-ops/flights/{id}/launch` and `POST /drone-ops/airspace-authorizations/{id}/decide`: the pilot's `status` is `CERTIFIED` — otherwise `ERR_PILOT_NOT_CERTIFIED` (409)."

    Design: Corner/rbac/a_pilot_cannot_reach_another_pilots_airframe_or_file_flights_in_their_name
    """
    owner, intruder, airframe, zone = _two_pilots_and_one_registered_airframe(api)
    assert intruder["status"] == PilotStatus.UNCERTIFIED.value, (
        f"the intruding pilot must be uncertified for this precedence check, "
        f"got {intruder['status']}"
    )

    module_attempt = _run_ownership_probe(
        api, "attach_a_module_to_another_pilots_airframe", owner, intruder, airframe, zone
    )
    module_error = module_attempt.json()["data"]["error_id"]
    assert module_error not in (
        ApiErrorId.INVALID_REQUEST.value,
        ApiErrorId.DUPLICATE_MODULE_SERIAL.value,
    ), (
        f"ownership is resolved through the parent airframe's owner at rung 3, ahead of any "
        f"body check, got {module_error}"
    )
    validate_error(module_attempt, ApiErrorId.OWNERSHIP_VIOLATION, 403)

    flight_attempt = _run_ownership_probe(
        api, "file_a_flight_in_another_pilots_name", owner, intruder, airframe, zone
    )
    flight_error = flight_attempt.json()["data"]["error_id"]
    assert flight_error != ApiErrorId.PILOT_NOT_CERTIFIED.value, (
        "rung 3 precedes rung 16, so an uncertified pilot filing in someone else's name is an "
        "ownership violation rather than a certification failure"
    )
    validate_error(flight_attempt, ApiErrorId.OWNERSHIP_VIOLATION, 403)


def test_ownership_binds_the_pilot_role_only_and_the_refused_writes_persist_nothing(api):
    """PRD §2.1: "When `X-User-Role` is `ComplianceOfficer`, `AirspaceAuthority`, `SafetyReviewer`, `WaiverApprover` or `InvestigationOfficer`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared against any entity's `id`."
    PRD §2.1: "A mismatch on either the addressed resource or the submitted body is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/a_pilot_cannot_reach_another_pilots_airframe_or_file_flights_in_their_name
    """
    owner, intruder, airframe, zone = _two_pilots_and_one_registered_airframe(api)

    for probe in OWNERSHIP_PROBES:
        validate_error(
            _run_ownership_probe(api, probe, owner, intruder, airframe, zone),
            ApiErrorId.OWNERSHIP_VIOLATION,
            403,
        )

    officer_read = validate_success(api.get_aircraft(airframe["id"], headers=COMPLIANCE_OFFICER))
    assert officer_read["registration_status"] == RegistrationStatus.REGISTERED.value, (
        f"an operator identifier is never compared against an entity id, so the officer read "
        f"must succeed, got {officer_read['registration_status']}"
    )

    owner_read = validate_success(
        api.get_aircraft(airframe["id"], headers=make_pilot_headers(owner["id"]))
    )
    assert owner_read["serial_number"] == airframe["serial_number"], (
        f"the owner's own read is unaffected, expected serial {airframe['serial_number']}, "
        f"got {owner_read['serial_number']}"
    )

    modules, module_meta = validate_paginated(
        api.list_remote_id_modules({"aircraft_id": airframe["id"]}, headers=COMPLIANCE_OFFICER)
    )
    assert module_meta["total_count"] == 0, (
        f"the refused module write persisted nothing, got total_count "
        f"{module_meta['total_count']}"
    )
    assert modules == [], f"expected no broadcast modules on the airframe, got {len(modules)}"


def test_every_role_performs_its_own_and_its_shared_operations_across_one_mission(api):
    """PRD §2.1: "The server does record it where a transition says so — `AirspaceAuthorization.approved_by_user_id`, `Waiver.approved_by_user_id`, `SafetyCase.cleared_by_user_id`, `AccidentReport.closed_by_user_id` and `TemporaryFlightRestriction.published_by_user_id` all hold the `X-User-ID` of the operator who performed the step — but those recorded values exist to support segregation of duties, not ownership."
    PRD §3.1: "A score at or above the mark writes `passed` true and moves the sitting from `SCHEDULED` to `PASSED`; a score below the mark writes `passed` false and moves it to `FAILED`."
    PRD §3.3: "Registration is a `ComplianceOfficer` act and takes no request body: the service assigns the `registration_number` itself, a non-null marking unique across all airframes, and moves the airframe from `PENDING_REGISTRATION` to `REGISTERED`."
    PRD §3.4: "A restriction is created in `ACTIVE` with `published_by_user_id` set to the publishing operator's `X-User-ID`."
    PRD §3.5: "Sum the `ground_risk_class`, the air-risk index and the uplift, and cap the total at 6 — the result is the `sail_level`, always an integer from 1 to 6."
    PRD §3.5: "Clearance moves the waiver to `CLEARED` and moves every safety case of the waiver from `PENDING` to `CLEARED`, stamping the reviewer's own `X-User-ID` into `cleared_by_user_id`."
    PRD §3.5: "It moves the waiver to `APPROVED`, stores the granted ceiling, sets `approved_by_user_id` to the approver's `X-User-ID`, and sets `valid_until` to the current instant advanced by 180 whole days with the time-of-day preserved."
    PRD §3.7: "The `effective_ceiling_ft` is the cited authorization's `granted_ceiling_ft` when the flight names an `authorization_id`, and 400 feet otherwise."
    PRD §3.7: "The check's `result` is `PASSED` exactly when `blocking_findings` is empty, and `FAILED` otherwise."
    PRD §3.7: "The service writes all four fields, then computes `logged_minutes` as the whole minutes between `actual_start` and `actual_end`, discarding any part-minute remainder, and computes `altitude_exceedance` as true exactly when `max_altitude_reached_ft` is strictly greater than the flight's effective ceiling — the cited authorization's `granted_ceiling_ft` when the flight names one, and 400 feet otherwise."
    PRD §3.8: "The flight's `investigation_status` is a genuinely parallel dimension: filing moves it from `NONE` to `OPEN` and closure or withdrawal moves it from `OPEN` to `CLOSED`, and **neither ever touches the flight's operational `status`**."
    PRD §3.9: "Then take the raw score as 25 times the incident count, plus 15 times the exceedance count, plus 30 times the open-accident count, plus a lapsed-currency term of 10 when the pilot's `status` is `LAPSED` and 0 otherwise, minus 5 times the clean-flight count."
    PRD §3.9: "Suspension fires when the recomputed `risk_score` reaches 70."

    Design: Corner/rbac/every_role_performs_its_exclusive_and_shared_operations_end_to_end
    """
    certified_at = "2026-09-01T00:00:00Z"
    fixtures.set_clock(api, certified_at)

    # The registrar enrols, examines and certifies.
    pilot = fixtures.create_pilot(api)
    pilot_acting = make_pilot_headers(pilot["id"])
    sitting = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(TestCode.TRUST_RECREATIONAL.value, certified_at),
            headers=COMPLIANCE_OFFICER,
        ),
        201,
    )
    graded = validate_success(
        api.grade_knowledge_test(
            sitting["id"], factories.grade_payload(100), headers=COMPLIANCE_OFFICER
        )
    )
    assert graded["status"] == KnowledgeTestStatus.PASSED.value, (
        f"a recreational sitting graded at the mark of 100 passes, got {graded['status']}"
    )

    # Airframe creation is shared: the pilot files one and the registrar files another.
    airframe = validate_success(
        api.create_aircraft(
            factories.aircraft_payload(pilot["id"], takeoff_weight_g=249, max_altitude_ft=900),
            headers=pilot_acting,
        ),
        201,
    )
    officer_filed_airframe = validate_success(
        api.create_aircraft(
            factories.aircraft_payload(pilot["id"], takeoff_weight_g=249, max_altitude_ft=900),
            headers=COMPLIANCE_OFFICER,
        ),
        201,
    )
    assert officer_filed_airframe["owner_pilot_id"] == pilot["id"], (
        f"the registrar may file an airframe on the pilot's behalf, expected owner "
        f"{pilot['id']}, got {officer_filed_airframe['owner_pilot_id']}"
    )
    assert officer_filed_airframe["id"] != airframe["id"], "the two airframes must be distinct rows"

    registered = validate_success(api.register_aircraft(airframe["id"], headers=COMPLIANCE_OFFICER))
    assert registered["registration_status"] == RegistrationStatus.REGISTERED.value, (
        f"registration moves the airframe to REGISTERED, got {registered['registration_status']}"
    )
    assert registered["registration_number"], (
        f"registration mints a non-null marking, got {registered['registration_number']!r}"
    )

    # The airspace authority publishes the controlled zone.
    zone = fixtures.create_controlled_zone(
        api,
        class_code=ZoneClassCode.D.value,
        class_ceiling_ft=700,
        max_concurrent_authorizations=2,
    )

    # The pilot requests access; only the authority may decide it.
    authorization = validate_success(
        api.create_authorization(
            factories.authorization_payload(
                pilot["id"],
                airframe["id"],
                zone["id"],
                zone["version"],
                "2026-09-10T19:00:00Z",
                "2026-09-10T23:00:00Z",
                requested_ceiling_ft=400,
            ),
            headers=pilot_acting,
        ),
        201,
    )
    assert authorization["status"] == AuthorizationStatus.REQUESTED.value, (
        f"a new request lands in REQUESTED, got {authorization['status']}"
    )
    decided = validate_success(
        api.decide_authorization(
            authorization["id"], factories.approve_authorization_payload(), headers=AIRSPACE_AUTHORITY
        )
    )
    assert decided["status"] == AuthorizationStatus.APPROVED.value, (
        f"the authority's APPROVE moves the request to APPROVED, got {decided['status']}"
    )
    assert decided["granted_ceiling_ft"] == 400, (
        f"a recreational operator is capped at 400 feet, got {decided['granted_ceiling_ft']}"
    )
    assert decided["approved_by_user_id"] == AIRSPACE_AUTHORITY_ID, (
        f"the approver id is stamped from the header rather than supplied in the body, expected "
        f"{AIRSPACE_AUTHORITY_ID}, got {decided['approved_by_user_id']}"
    )

    # The pilot applies for the night waiver; the reviewer reviews it and a different
    # operator decides it.
    waiver = validate_success(
        api.create_waiver(
            factories.waiver_payload(
                pilot["id"],
                airframe["id"],
                fixtures.pilot_version(api, pilot["id"]),
                waiver_type=WaiverType.NIGHT.value,
                requested_ceiling_ft=400,
            ),
            headers=pilot_acting,
        ),
        201,
    )
    assert waiver["status"] == WaiverStatus.DRAFT.value, (
        f"a new application lands in DRAFT, got {waiver['status']}"
    )
    safety_case = validate_success(
        api.create_safety_case(
            waiver["id"],
            factories.safety_case_payload(
                ground_risk_class=2, air_risk_class=AirRiskClass.ARC_B.value
            ),
            headers=pilot_acting,
        ),
        201,
    )
    assert safety_case["sail_level"] == 3, (
        f"ground risk 2 plus the ARC_B index 1 with no beyond-visual-line-of-sight uplift is 3, "
        f"got {safety_case['sail_level']}"
    )

    submitted = validate_success(api.submit_waiver(waiver["id"], headers=pilot_acting))
    assert submitted["status"] == WaiverStatus.SUBMITTED.value, (
        f"submission moves the application to SUBMITTED, got {submitted['status']}"
    )
    under_review = validate_success(api.begin_waiver_review(waiver["id"], headers=SAFETY_REVIEWER))
    assert under_review["status"] == WaiverStatus.UNDER_REVIEW.value, (
        f"the reviewer's first move is UNDER_REVIEW, got {under_review['status']}"
    )
    cleared = validate_success(
        api.clear_waiver_safety_case(
            waiver["id"],
            factories.clear_safety_case_payload(
                reviewer_findings="Cordon and lighting plan accepted."
            ),
            headers=SAFETY_REVIEWER,
        )
    )
    assert cleared["status"] == WaiverStatus.CLEARED.value, (
        f"clearance moves the application to CLEARED, got {cleared['status']}"
    )
    cleared_case = validate_success(api.get_safety_case(safety_case["id"], headers=SAFETY_REVIEWER))
    assert cleared_case["review_status"] == SafetyCaseReviewStatus.CLEARED.value, (
        f"clearance moves every safety case of the waiver to CLEARED, got "
        f"{cleared_case['review_status']}"
    )
    assert cleared_case["cleared_by_user_id"] == SAFETY_REVIEWER_ID, (
        f"the reviewer's own identifier is stamped into cleared_by_user_id, expected "
        f"{SAFETY_REVIEWER_ID}, got {cleared_case['cleared_by_user_id']}"
    )

    approved_waiver = validate_success(
        api.decide_waiver(
            waiver["id"],
            factories.approve_waiver_payload(granted_ceiling_ft=400),
            headers=WAIVER_APPROVER,
        )
    )
    assert approved_waiver["status"] == WaiverStatus.APPROVED.value, (
        f"the approver's APPROVE moves the application to APPROVED, got "
        f"{approved_waiver['status']}"
    )
    assert approved_waiver["approved_by_user_id"] == WAIVER_APPROVER_ID, (
        f"the deciding operator's identifier is stamped from the header, expected "
        f"{WAIVER_APPROVER_ID}, got {approved_waiver['approved_by_user_id']}"
    )
    assert_instant_equals(
        approved_waiver["valid_until"],
        shift_days(certified_at, 180),
        "waiver validity is the deciding instant advanced by 180 whole days",
    )

    # The authority also publishes a restriction well clear of the flight window.
    restriction = validate_success(
        api.create_tfr(
            factories.tfr_payload(zone["id"], "2026-12-01T00:00:00Z", "2026-12-02T00:00:00Z"),
            headers=AIRSPACE_AUTHORITY,
        ),
        201,
    )
    assert restriction["status"] == RestrictionStatus.ACTIVE.value, (
        f"a published restriction starts ACTIVE, got {restriction['status']}"
    )
    assert restriction["published_by_user_id"] == AIRSPACE_AUTHORITY_ID, (
        f"the publisher's identifier is stamped from the header, expected "
        f"{AIRSPACE_AUTHORITY_ID}, got {restriction['published_by_user_id']}"
    )

    # The pilot plans, clears, launches and completes the mission.
    flight = validate_success(
        api.create_flight(
            factories.flight_payload(
                pilot["id"],
                airframe["id"],
                zone["id"],
                "2026-09-10T20:00:00Z",
                "2026-09-10T21:00:00Z",
                planned_max_altitude_ft=380,
                authorization_id=authorization["id"],
                waiver_id=waiver["id"],
                night_operation=True,
            ),
            headers=pilot_acting,
        ),
        201,
    )
    assert flight["status"] == FlightStatus.PLANNED.value, (
        f"a new mission lands in PLANNED, got {flight['status']}"
    )

    fixtures.set_clock(api, "2026-09-10T20:00:00Z")
    check = validate_success(
        api.preflight_check(flight["id"], factories.preflight_check_payload(), headers=pilot_acting),
        201,
    )
    assert check["blocking_findings"] == [], (
        f"every gate is met, so no blocking finding may be recorded, got "
        f"{check['blocking_findings']}"
    )
    assert check["result"] == PreflightResult.PASSED.value, (
        f"an empty blocking_findings array means the check PASSED, got {check['result']}"
    )
    assert check["airspace_class_code"] == ZoneClassCode.D.value, (
        f"the record snapshots the zone's class_code, expected D, got "
        f"{check['airspace_class_code']}"
    )
    assert check["effective_ceiling_ft"] == 400, (
        f"the effective ceiling is the cited authorization's granted ceiling of 400, got "
        f"{check['effective_ceiling_ft']}"
    )

    launched = validate_success(api.launch_flight(flight["id"], headers=pilot_acting))
    assert launched["status"] == FlightStatus.IN_PROGRESS.value, (
        f"a cleared flight launches into IN_PROGRESS, got {launched['status']}"
    )

    fixtures.set_clock(api, "2026-09-10T20:50:00Z")
    completed = validate_success(
        api.complete_flight(
            flight["id"],
            factories.completion_payload(
                "2026-09-10T20:50:00Z",
                max_altitude_reached_ft=370,
                incident_occurred=True,
                incident_summary="Downwash dislodged a roof tile.",
            ),
            headers=pilot_acting,
        )
    )
    assert completed["status"] == FlightStatus.COMPLETED.value, (
        f"completion moves the flight to COMPLETED, got {completed['status']}"
    )
    assert completed["logged_minutes"] == 50, (
        f"the whole minutes between 20:00 and 20:50 are 50, got {completed['logged_minutes']}"
    )
    assert completed["altitude_exceedance"] is False, (
        f"370 feet is not above the effective ceiling of 400, got "
        f"{completed['altitude_exceedance']}"
    )

    # Filing is shared with the pilot role; opening the investigation is not.
    report = validate_success(
        api.create_accident_report(
            factories.accident_report_payload(
                flight["id"],
                "2026-09-10T20:45:00Z",
                injury_level="NONE",
                reported_property_damage_cents=30000,
            ),
            headers=INVESTIGATION_OFFICER,
        ),
        201,
    )
    assert report["status"] == ReportStatus.FILED.value, (
        f"a new report lands in FILED, got {report['status']}"
    )
    investigating = validate_success(
        api.open_investigation(report["id"], headers=INVESTIGATION_OFFICER)
    )
    assert investigating["status"] == ReportStatus.INVESTIGATING.value, (
        f"opening the investigation moves the report to INVESTIGATING, got "
        f"{investigating['status']}"
    )

    # Shared reads are open to roles that never wrote these rows.
    flight_read = validate_success(api.get_flight(flight["id"], headers=AIRSPACE_AUTHORITY))
    assert flight_read["status"] == FlightStatus.COMPLETED.value, (
        f"the investigation dimension never touches the operational status, expected COMPLETED, "
        f"got {flight_read['status']}"
    )
    assert flight_read["investigation_status"] == InvestigationStatus.OPEN.value, (
        f"filing moved the investigation dimension to OPEN, got "
        f"{flight_read['investigation_status']}"
    )
    waiver_read = validate_success(api.get_waiver(waiver["id"], headers=COMPLIANCE_OFFICER))
    assert waiver_read["status"] == WaiverStatus.APPROVED.value, (
        f"the registrar reads a waiver it never decided, expected APPROVED, got "
        f"{waiver_read['status']}"
    )

    # One incident and one open report score 55, which is below the suspension threshold.
    final_pilot = fixtures.read_pilot(api, pilot["id"])
    assert final_pilot["risk_score"] == 55, (
        f"25 for the incident plus 30 for the open accident, with no exceedance and no clean "
        f"flight, is 55, got {final_pilot['risk_score']}"
    )
    assert final_pilot["status"] == PilotStatus.CERTIFIED.value, (
        f"55 is below the threshold of 70, so the pilot is still CERTIFIED, got "
        f"{final_pilot['status']}"
    )
