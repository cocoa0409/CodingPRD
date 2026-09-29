"""Airframe creation, registration, and the broadcast module that gates flight.

Every test builds its own pilot and airframe from an empty datastore: the harness
restarts the service before each test, so the logical clock always opens at its
startup value and is only ever driven forward from there.
"""

from test_helpers import (
    CLOCK_STARTUP_UTC,
    OMIT,
    ApiErrorId,
    BroadcastProtocol,
    FlightStatus,
    ModuleOutcome,
    ModuleStatus,
    OperatorCategory,
    PreflightResult,
    RegistrationStatus,
    assert_aircraft,
    assert_flight,
    assert_module,
    constants,
    factories,
    fixtures,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_INSTANT = "2026-08-05T00:00:00Z"
MODULE_VALID_UNTIL = "2026-08-15T00:00:00Z"
STALE_INSTANT = "2026-08-16T00:00:00Z"
PLANNED_START = "2026-08-16T10:00:00Z"
PLANNED_END = "2026-08-16T11:00:00Z"
RENEWED_VALID_UNTIL = "2026-09-01T00:00:00Z"


def test_creating_an_airframe_without_a_takeoff_weight_is_a_body_shape_error(
    api, compliance_officer, pilot_headers
):
    """PRD §3.3: "An airframe is created against its owner: the request carries `owner_pilot_id`, a `model` (1 to 80 characters, not blank), a `serial_number` (1 to 40 characters, unique within that owner — two different pilots may hold the same manufacturer serial, the same pilot may not), a `takeoff_weight_g` (integer 1 to 25000) and a `max_altitude_ft` (integer 1 to 5000, the manufacturer's altitude limit)."
    PRD §3.3: "At creation the service computes `remote_id_required` once and never again: it is true exactly when `takeoff_weight_g` is **strictly greater** than 250 grams."
    PRD §2.11: "7. **Body shape**, on every endpoint: all required fields present, every enum value inside its declared member set, every integer inside its declared range, every string non-blank, arrays well-formed, and `limit` within 1 to 100 with `offset` not negative — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_aircraft_without_takeoff_weight_is_rejected_as_invalid_request
    """
    pilot = fixtures.create_pilot(api, OperatorCategory.RECREATIONAL.value)
    owner = pilot_headers(pilot["id"])

    rejected = api.create_aircraft(
        factories.aircraft_payload(pilot["id"], takeoff_weight_g=OMIT, max_altitude_ft=400),
        headers=owner,
    )

    validate_error(rejected, ApiErrorId.INVALID_REQUEST.value, 400)
    _, meta = validate_paginated(
        api.list_aircraft(params={"owner_pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 0, (
        "a rejected creation must not persist an airframe, got "
        f"{meta['total_count']} rows for the owner"
    )


def test_creating_an_airframe_with_a_whitespace_only_model_is_a_body_shape_error(
    api, compliance_officer, pilot_headers
):
    """PRD §3.3: "An airframe is created against its owner: the request carries `owner_pilot_id`, a `model` (1 to 80 characters, not blank), a `serial_number` (1 to 40 characters, unique within that owner — two different pilots may hold the same manufacturer serial, the same pilot may not), a `takeoff_weight_g` (integer 1 to 25000) and a `max_altitude_ft` (integer 1 to 5000, the manufacturer's altitude limit)."
    PRD §2.11: "7. **Body shape**, on every endpoint: all required fields present, every enum value inside its declared member set, every integer inside its declared range, every string non-blank, arrays well-formed, and `limit` within 1 to 100 with `offset` not negative — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_aircraft_without_takeoff_weight_is_rejected_as_invalid_request
    """
    pilot = fixtures.create_pilot(api, OperatorCategory.RECREATIONAL.value)
    owner = pilot_headers(pilot["id"])

    rejected = api.create_aircraft(
        factories.aircraft_payload(
            pilot["id"], takeoff_weight_g=900, max_altitude_ft=400, model="   "
        ),
        headers=owner,
    )

    validate_error(rejected, ApiErrorId.INVALID_REQUEST.value, 400)
    _, meta = validate_paginated(
        api.list_aircraft(params={"owner_pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 0, (
        "a blank model is not a 1 to 80 character string, so nothing may persist, got "
        f"{meta['total_count']} rows for the owner"
    )


def test_registering_an_exempt_airframe_mints_a_registration_number(
    api, compliance_officer
):
    """PRD §3.3: "The airframe begins in `PENDING_REGISTRATION` with `registration_number` null and `grounding_reason` null."
    PRD §3.3: "Registration is a `ComplianceOfficer` act and takes no request body: the service assigns the `registration_number` itself, a non-null marking unique across all airframes, and moves the airframe from `PENDING_REGISTRATION` to `REGISTERED`."
    PRD §3.3: "An airframe of exactly 250 grams is exempt and may be registered and launched with no broadcast module attached at all; an airframe of 251 grams is not."
    PRD §2.5: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/register_moves_an_airframe_from_pending_registration_to_registered
    """
    pilot = fixtures.create_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = fixtures.create_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=800
    )
    assert_aircraft(
        aircraft,
        registration_status=RegistrationStatus.PENDING_REGISTRATION.value,
        registration_number=None,
        grounding_reason=None,
        remote_id_required=False,
    )

    registered = validate_success(
        api.register_aircraft(aircraft["id"], headers=compliance_officer)
    )

    assert_aircraft(
        registered,
        registration_status=RegistrationStatus.REGISTERED.value,
        remote_id_required=False,
        grounding_reason=None,
        version=aircraft["version"] + 1,
        updated_at=CLOCK_STARTUP_UTC,
    )
    assert isinstance(registered["registration_number"], str), (
        "the service mints the registration marking itself, got "
        f"{registered['registration_number']!r}"
    )
    assert registered["registration_number"].strip(), (
        f"the minted marking is non-blank, got {registered['registration_number']!r}"
    )
    _, meta = validate_paginated(
        api.list_remote_id_modules(
            params={"aircraft_id": aircraft["id"]}, headers=compliance_officer
        )
    )
    assert meta["total_count"] == 0, (
        "an exempt airframe registers with no broadcast module at all, got "
        f"{meta['total_count']} module rows"
    )


def _airframe_with_an_unverified_module(api, owner_builder):
    """A 900 g airframe still in PENDING_REGISTRATION carrying one UNVERIFIED module."""
    pilot = fixtures.create_pilot(api, OperatorCategory.COMMERCIAL.value)
    owner = owner_builder(pilot["id"])
    aircraft = fixtures.create_aircraft(
        api, pilot["id"], takeoff_weight_g=900, max_altitude_ft=800
    )
    module = validate_success(
        api.create_remote_id_module(
            aircraft["id"], factories.module_payload(module_serial="MOD-0001"), headers=owner
        ),
        201,
    )
    return aircraft, module, owner


def test_adjudicating_a_module_that_was_never_submitted_is_refused(
    api, compliance_officer, pilot_headers
):
    """PRD §3.3: "The module is created in `UNVERIFIED` with `verified_at`, `verified_until` and `failure_reason` all null."
    PRD §3.3: "Adjudication is admissible only from `VERIFICATION_PENDING`."
    PRD §2.11: "13. **Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."

    Design: Corner/state_machines/module_verification_enforces_its_from_state_precondition
    """
    aircraft, module, _ = _airframe_with_an_unverified_module(api, pilot_headers)
    assert_aircraft(aircraft, remote_id_required=True)
    assert_module(
        module,
        status=ModuleStatus.UNVERIFIED.value,
        verified_at=None,
        verified_until=None,
        failure_reason=None,
    )

    refused = api.verify_remote_id_module(
        module["id"],
        factories.module_verify_payload(
            ModuleOutcome.VERIFIED.value, verified_until=MODULE_VALID_UNTIL
        ),
        headers=compliance_officer,
    )

    validate_error(refused, ApiErrorId.MODULE_INVALID_STATE.value, 409)
    assert_module(
        validate_success(api.get_remote_id_module(module["id"], headers=compliance_officer)),
        status=ModuleStatus.UNVERIFIED.value,
        verified_at=None,
        verified_until=None,
    )


def test_adjudicating_a_module_again_after_a_rejection_is_refused(
    api, compliance_officer, pilot_headers
):
    """PRD §3.3: "Submission is accepted from `UNVERIFIED`, from `VERIFICATION_FAILED` and from `EXPIRED`, and always lands in `VERIFICATION_PENDING`, overwriting any previous `broadcast_sample_ref` and clearing `failure_reason` back to null."
    PRD §3.3: "An outcome of `FAILED` requires `failure_reason` to be supplied; it moves the module to `VERIFICATION_FAILED`, stores the reason, and leaves both `verified_at` and `verified_until` null."
    PRD §3.3: "Adjudication is admissible only from `VERIFICATION_PENDING`."
    PRD §2.11: "20. **Remote-ID presence**, on `POST /drone-ops/aircraft/{id}/register`, `POST /drone-ops/aircraft/{id}/return-to-service` and `POST /drone-ops/flights/{id}/launch`: when the airframe's `remote_id_required` is true, at least one of its broadcast modules is in `VERIFIED`. A module sitting in `UNVERIFIED`, `VERIFICATION_PENDING` or `VERIFICATION_FAILED`, or the absence of any module row, fails here with `ERR_REMOTE_ID_NOT_VERIFIED` (422)."

    Design: Corner/state_machines/module_verification_enforces_its_from_state_precondition
    """
    aircraft, module, owner = _airframe_with_an_unverified_module(api, pilot_headers)
    rejection_reason = "Broadcast sample lacked a serial field."

    submitted = validate_success(
        api.submit_module_verification(
            module["id"],
            factories.module_submission_payload(broadcast_sample_ref="SAMPLE-A"),
            headers=owner,
        )
    )
    assert_module(
        submitted,
        status=ModuleStatus.VERIFICATION_PENDING.value,
        broadcast_sample_ref="SAMPLE-A",
    )

    failed = validate_success(
        api.verify_remote_id_module(
            module["id"],
            factories.module_verify_payload(
                ModuleOutcome.FAILED.value, failure_reason=rejection_reason
            ),
            headers=compliance_officer,
        )
    )
    assert_module(
        failed,
        status=ModuleStatus.VERIFICATION_FAILED.value,
        failure_reason=rejection_reason,
        verified_at=None,
        verified_until=None,
    )

    refused = api.verify_remote_id_module(
        module["id"],
        factories.module_verify_payload(
            ModuleOutcome.VERIFIED.value, verified_until=MODULE_VALID_UNTIL
        ),
        headers=compliance_officer,
    )

    validate_error(refused, ApiErrorId.MODULE_INVALID_STATE.value, 409)
    assert_module(
        validate_success(api.get_remote_id_module(module["id"], headers=compliance_officer)),
        status=ModuleStatus.VERIFICATION_FAILED.value,
        verified_at=None,
        verified_until=None,
    )
    validate_error(
        api.register_aircraft(aircraft["id"], headers=compliance_officer),
        ApiErrorId.REMOTE_ID_NOT_VERIFIED.value,
        422,
    )


def _three_airframes_around_the_weight_threshold(api, headers):
    """One certified commercial owner and airframes one gram either side of the threshold."""
    set_clock(api, SETUP_INSTANT, headers=headers)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=SETUP_INSTANT
    )
    weights = (
        constants.REMOTE_ID_EXEMPT_WEIGHT_G - 1,
        constants.REMOTE_ID_EXEMPT_WEIGHT_G,
        constants.REMOTE_ID_REQUIRED_WEIGHT_G,
    )
    return pilot, [
        fixtures.create_aircraft(api, pilot["id"], takeoff_weight_g=w, max_altitude_ft=400)
        for w in weights
    ]


def test_the_remote_id_requirement_exempts_exactly_the_threshold_weight(
    api, compliance_officer
):
    """PRD §3.3: "At creation the service computes `remote_id_required` once and never again: it is true exactly when `takeoff_weight_g` is **strictly greater** than 250 grams."
    PRD §3.3: "An airframe of exactly 250 grams is exempt and may be registered and launched with no broadcast module attached at all; an airframe of 251 grams is not."
    PRD §3.3: "Registration is a `ComplianceOfficer` act and takes no request body: the service assigns the `registration_number` itself, a non-null marking unique across all airframes, and moves the airframe from `PENDING_REGISTRATION` to `REGISTERED`."

    Design: Difficulty/boundary_precision_check/remote_id_weight_threshold_250_grams_exempt_251_grams_requires_module
    """
    _, (under, at_threshold, over) = _three_airframes_around_the_weight_threshold(
        api, compliance_officer
    )

    assert_aircraft(under, remote_id_required=False)
    assert_aircraft(at_threshold, remote_id_required=False)
    assert_aircraft(over, remote_id_required=True)

    for exempt in (under, at_threshold):
        registered = validate_success(
            api.register_aircraft(exempt["id"], headers=compliance_officer)
        )
        assert_aircraft(
            registered, registration_status=RegistrationStatus.REGISTERED.value
        )
        assert registered["registration_number"], (
            "an exempt airframe still receives a marking, got "
            f"{registered['registration_number']!r} at "
            f"{exempt['takeoff_weight_g']} g"
        )
        _, meta = validate_paginated(
            api.list_remote_id_modules(
                params={"aircraft_id": exempt["id"]}, headers=compliance_officer
            )
        )
        assert meta["total_count"] == 0, (
            "no broadcast module participated in the exempt registration at "
            f"{exempt['takeoff_weight_g']} g, got {meta['total_count']} module rows"
        )


def test_one_gram_over_the_threshold_cannot_register_without_a_verified_module(
    api, compliance_officer
):
    """PRD §3.3: "An airframe of exactly 250 grams is exempt and may be registered and launched with no broadcast module attached at all; an airframe of 251 grams is not."
    PRD §3.3: "An airframe with `remote_id_required` true and no module at all is refused with `ERR_REMOTE_ID_NOT_VERIFIED`."
    PRD §2.11: "20. **Remote-ID presence**, on `POST /drone-ops/aircraft/{id}/register`, `POST /drone-ops/aircraft/{id}/return-to-service` and `POST /drone-ops/flights/{id}/launch`: when the airframe's `remote_id_required` is true, at least one of its broadcast modules is in `VERIFIED`. A module sitting in `UNVERIFIED`, `VERIFICATION_PENDING` or `VERIFICATION_FAILED`, or the absence of any module row, fails here with `ERR_REMOTE_ID_NOT_VERIFIED` (422)."

    Design: Difficulty/boundary_precision_check/remote_id_weight_threshold_250_grams_exempt_251_grams_requires_module
    """
    _, (_, _, over) = _three_airframes_around_the_weight_threshold(api, compliance_officer)
    assert over["takeoff_weight_g"] == constants.REMOTE_ID_WEIGHT_THRESHOLD_G + 1, (
        "the probe sits one gram over the threshold, got "
        f"{over['takeoff_weight_g']} g against a threshold of "
        f"{constants.REMOTE_ID_WEIGHT_THRESHOLD_G} g"
    )

    refused = api.register_aircraft(over["id"], headers=compliance_officer)

    validate_error(refused, ApiErrorId.REMOTE_ID_NOT_VERIFIED.value, 422)
    assert_aircraft(
        validate_success(api.get_aircraft(over["id"], headers=compliance_officer)),
        registration_status=RegistrationStatus.PENDING_REGISTRATION.value,
        registration_number=None,
        remote_id_required=True,
    )


def _registered_airframe_with_a_lapsing_module(api, headers, owner_builder, protocol):
    """A REGISTERED 900 g airframe whose only broadcast module lapses at MODULE_VALID_UNTIL."""
    set_clock(api, SETUP_INSTANT, headers=headers)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=SETUP_INSTANT
    )
    owner = owner_builder(pilot["id"])
    aircraft = fixtures.create_aircraft(
        api, pilot["id"], takeoff_weight_g=900, max_altitude_ft=1000
    )
    module = fixtures.create_verified_module(
        api, aircraft, verified_until=MODULE_VALID_UNTIL, broadcast_protocol=protocol
    )
    registered = validate_success(
        api.register_aircraft(aircraft["id"], headers=headers)
    )
    zone = fixtures.create_zone(api, class_ceiling_ft=400, max_concurrent_authorizations=2)
    return pilot, registered, module, zone, owner


def test_launch_is_refused_when_the_broadcast_verification_has_gone_stale(
    api, compliance_officer, pilot_headers
):
    """PRD §2.11: "21. **Remote-ID validity**, on the same three endpoints as rung 20: the `VERIFIED` module's `verified_until` is strictly after the current instant. A module found stale here is first transitioned from `VERIFIED` to `EXPIRED` and the call is then rejected with `ERR_REMOTE_ID_EXPIRED` (422)."
    PRD §3.3: "Separately and lazily, a module in `VERIFIED` whose `verified_until` is at or before the current instant is moved to `EXPIRED` at the moment a preflight check or a launch reads it (§2.8) — the expiry is discovered, not scheduled."
    PRD §3.7: "A `PASSED` check moves the flight from `PLANNED` to `PREFLIGHT_CLEARED` and increments the flight's `version`."
    PRD §3.7: "The lazy transitions run first here too, so a launch that fails on a stale gate still leaves the stale row correctly transitioned."

    Design: Difficulty/cross_entity_state_dependency/flight_launch_depends_on_remote_id_module_state
    """
    pilot, aircraft, module, zone, owner = _registered_airframe_with_a_lapsing_module(
        api, compliance_officer, pilot_headers, BroadcastProtocol.WIFI_NAN.value
    )
    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        PLANNED_START,
        PLANNED_END,
        planned_max_altitude_ft=380,
    )
    check = fixtures.clear_flight_for_launch(api, flight)
    assert check["result"] == PreflightResult.PASSED.value, (
        "the module was still live at check time, so the sweep must pass, got findings "
        f"{check['blocking_findings']}"
    )
    set_clock(api, PLANNED_START, headers=compliance_officer)

    refused = api.launch_flight(flight["id"], headers=owner)

    validate_error(refused, ApiErrorId.REMOTE_ID_EXPIRED.value, 422)
    assert_module(
        validate_success(api.get_remote_id_module(module["id"], headers=compliance_officer)),
        status=ModuleStatus.EXPIRED.value,
        verified_until=MODULE_VALID_UNTIL,
    )
    assert_flight(
        validate_success(api.get_flight(flight["id"], headers=owner)),
        status=FlightStatus.PREFLIGHT_CLEARED.value,
        actual_start=None,
    )
    assert_aircraft(
        validate_success(api.get_aircraft(aircraft["id"], headers=compliance_officer)),
        registration_status=RegistrationStatus.REGISTERED.value,
        remote_id_required=True,
    )


def test_re_verifying_the_module_lets_the_untouched_flight_launch(
    api, compliance_officer, pilot_headers
):
    """PRD §3.3: "Submission is accepted from `UNVERIFIED`, from `VERIFICATION_FAILED` and from `EXPIRED`, and always lands in `VERIFICATION_PENDING`, overwriting any previous `broadcast_sample_ref` and clearing `failure_reason` back to null."
    PRD §3.3: "An outcome of `VERIFIED` requires `verified_until` to be supplied and to be strictly after the current instant; it moves the module to `VERIFIED`, sets `verified_at` to the current instant, stores `verified_until`, and clears `failure_reason`."
    PRD §3.7: "On success the flight moves from `PREFLIGHT_CLEARED` to `IN_PROGRESS`, `actual_start` is set to the current instant, and the cited authorization moves from `APPROVED` to `ACTIVE`, keeping its zone slot."
    PRD §2.11: "21. **Remote-ID validity**, on the same three endpoints as rung 20: the `VERIFIED` module's `verified_until` is strictly after the current instant. A module found stale here is first transitioned from `VERIFIED` to `EXPIRED` and the call is then rejected with `ERR_REMOTE_ID_EXPIRED` (422)."

    Design: Difficulty/cross_entity_state_dependency/flight_launch_depends_on_remote_id_module_state
    """
    pilot, aircraft, module, zone, owner = _registered_airframe_with_a_lapsing_module(
        api, compliance_officer, pilot_headers, BroadcastProtocol.WIFI_NAN.value
    )
    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        PLANNED_START,
        PLANNED_END,
        planned_max_altitude_ft=380,
    )
    fixtures.clear_flight_for_launch(api, flight)
    set_clock(api, PLANNED_START, headers=compliance_officer)
    validate_error(
        api.launch_flight(flight["id"], headers=owner),
        ApiErrorId.REMOTE_ID_EXPIRED.value,
        422,
    )

    resubmitted = validate_success(
        api.submit_module_verification(
            module["id"],
            factories.module_submission_payload(broadcast_sample_ref="sample-renewed"),
            headers=owner,
        )
    )
    reverified = validate_success(
        api.verify_remote_id_module(
            module["id"],
            factories.module_verify_payload(
                ModuleOutcome.VERIFIED.value, verified_until=RENEWED_VALID_UNTIL
            ),
            headers=compliance_officer,
        )
    )
    launched = validate_success(api.launch_flight(flight["id"], headers=owner))

    assert_module(resubmitted, status=ModuleStatus.VERIFICATION_PENDING.value)
    assert_module(
        reverified,
        status=ModuleStatus.VERIFIED.value,
        verified_at=PLANNED_START,
        verified_until=RENEWED_VALID_UNTIL,
        failure_reason=None,
    )
    assert_flight(
        launched,
        status=FlightStatus.IN_PROGRESS.value,
        actual_start=PLANNED_START,
    )
    assert_aircraft(
        validate_success(api.get_aircraft(aircraft["id"], headers=compliance_officer)),
        registration_status=RegistrationStatus.REGISTERED.value,
    )


def _unchecked_flight_on_an_airframe_whose_module_has_lapsed(api, headers, owner_builder):
    """A flight still in PLANNED, filed after its airframe's broadcast module lapsed."""
    pilot, aircraft, module, zone, owner = _registered_airframe_with_a_lapsing_module(
        api, headers, owner_builder, BroadcastProtocol.BLUETOOTH_LE.value
    )
    set_clock(api, STALE_INSTANT, headers=headers)
    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        PLANNED_START,
        PLANNED_END,
        planned_max_altitude_ft=380,
    )
    return aircraft, module, flight, owner


def test_launching_an_unchecked_flight_reports_the_clearance_gate_not_the_stale_module(
    api, compliance_officer, pilot_headers
):
    """PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "14. **Pre-flight clearance**, on `POST /drone-ops/flights/{id}/launch` only: the flight's `status` is `PREFLIGHT_CLEARED`. A flight still in `PLANNED` — whether because its most recent check failed or because it has never been checked — is rejected here with `ERR_PREFLIGHT_NOT_CLEARED` (409)."
    PRD §2.11: "21. **Remote-ID validity**, on the same three endpoints as rung 20: the `VERIFIED` module's `verified_until` is strictly after the current instant. A module found stale here is first transitioned from `VERIFIED` to `EXPIRED` and the call is then rejected with `ERR_REMOTE_ID_EXPIRED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/launch_state_error_precedes_remote_id_safety_error_and_leaves_module_verified
    """
    aircraft, module, flight, owner = _unchecked_flight_on_an_airframe_whose_module_has_lapsed(
        api, compliance_officer, pilot_headers
    )

    refused = api.launch_flight(flight["id"], headers=owner)

    rejection = validate_error(refused, ApiErrorId.PREFLIGHT_NOT_CLEARED.value, 409)
    assert rejection["error_id"] != ApiErrorId.REMOTE_ID_EXPIRED.value, (
        "the clearance rung sits below the remote-id validity rung, so the stale broadcast "
        f"module must not decide the verdict, got {rejection['error_id']}"
    )
    assert refused.status_code != 422, (
        "the lower rung also owns the HTTP status, so a 422 would mean the safety rung was "
        f"evaluated first, got {refused.status_code}"
    )


def test_the_pre_empted_launch_leaves_the_stale_module_still_verified(
    api, compliance_officer, pilot_headers
):
    """PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "21. **Remote-ID validity**, on the same three endpoints as rung 20: the `VERIFIED` module's `verified_until` is strictly after the current instant. A module found stale here is first transitioned from `VERIFIED` to `EXPIRED` and the call is then rejected with `ERR_REMOTE_ID_EXPIRED` (422)."
    PRD §3.7: "That record carries `flight_id` from the path, a `checked_at` instant, a `result` of `PASSED` or `FAILED`, a `blocking_findings` array, an `active_tfr_ids` array, the `acknowledged_tfr_ids` as submitted, an `airspace_class_code` snapshotting the zone's `class_code` at check time, and an `effective_ceiling_ft`."

    Design: Difficulty/priority_pair_validation_conflict/launch_state_error_precedes_remote_id_safety_error_and_leaves_module_verified
    """
    aircraft, module, flight, owner = _unchecked_flight_on_an_airframe_whose_module_has_lapsed(
        api, compliance_officer, pilot_headers
    )
    validate_error(
        api.launch_flight(flight["id"], headers=owner),
        ApiErrorId.PREFLIGHT_NOT_CLEARED.value,
        409,
    )

    assert_module(
        validate_success(api.get_remote_id_module(module["id"], headers=compliance_officer)),
        status=ModuleStatus.VERIFIED.value,
        verified_until=MODULE_VALID_UNTIL,
        broadcast_protocol=BroadcastProtocol.BLUETOOTH_LE.value,
    )
    assert_flight(
        validate_success(api.get_flight(flight["id"], headers=owner)),
        status=FlightStatus.PLANNED.value,
        actual_start=None,
    )
    checks, checks_meta = validate_paginated(
        api.list_preflight_checks(flight["id"], headers=owner)
    )
    assert checks == [], f"a refused launch must append no check record, got {checks}"
    assert checks_meta["total_count"] == 0, (
        f"expected no pre-flight check rows for the flight, got {checks_meta['total_count']}"
    )
    assert_aircraft(
        validate_success(api.get_aircraft(aircraft["id"], headers=compliance_officer)),
        remote_id_required=True,
        registration_status=RegistrationStatus.REGISTERED.value,
    )
