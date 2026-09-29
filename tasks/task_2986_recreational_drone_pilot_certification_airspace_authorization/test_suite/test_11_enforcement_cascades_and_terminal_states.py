"""Transitive enforcement cascades, initial states and terminal-state lockdown.

One operator action here routinely rewrites rows four levels away, and the interest
is in exactly how far the propagation reaches: a suspension walks pilot to airframe
to authorization to flight, an accident filing walks report to flight to policy to a
future flight, and each stops precisely where the contract says it stops. The rest of
the module pins the states rows are born in and the refusals terminal rows must give.
"""

from test_helpers import (
    AIRSPACE_AUTHORITY_ID,
    COMPLIANCE_OFFICER,
    HTTP_STATUS_CODES,
    ApiErrorId,
    AuthorizationStatus,
    BroadcastProtocol,
    CertificationStatus,
    CoverageStatus,
    FlightStatus,
    InjuryLevel,
    InvestigationStatus,
    ModuleStatus,
    OperationCategory,
    OperatorCategory,
    PilotStatus,
    PreflightResult,
    RegistrationStatus,
    ReportStatus,
    RestrictionStatus,
    SystemCancellationReason,
    SystemGroundingReason,
    ZoneClassCode,
    assert_coverage_ledger_conservation,
    assert_instant_equals,
    get_success_data,
    make_pilot_headers,
    set_clock,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    completion_payload,
    flight_payload,
    grounding_payload,
    module_payload,
    revocation_payload,
    suspension_payload,
)
from test_helpers.fixtures import (
    clear_flight_for_launch,
    create_active_policy,
    create_aircraft,
    create_approved_authorization,
    create_certified_pilot,
    create_controlled_zone,
    create_filed_policy,
    create_filed_report,
    create_pilot,
    create_planned_flight,
    create_registered_aircraft,
    create_tfr,
    create_zone,
    read_pilot,
    read_policy,
    read_zone,
)

CASCADE_SETUP_DAY = "2026-08-05T00:00:00Z"
AUTH_WINDOW_START = "2026-08-20T09:00:00Z"
AUTH_WINDOW_END = "2026-08-20T12:00:00Z"
CONTROLLED_FLIGHT_START = "2026-08-20T09:30:00Z"
CONTROLLED_FLIGHT_END = "2026-08-20T10:30:00Z"
OPEN_ZONE_FLIGHT_START = "2026-08-21T09:00:00Z"
OPEN_ZONE_FLIGHT_END = "2026-08-21T10:00:00Z"

SUSPENSION_REASON = "Unreported airspace incursion during a compliance audit."


def _authorized_operation_scene(
    api,
    zone_class_code=ZoneClassCode.D.value,
    coverage_limit_cents=5000000,
    operation_category=OperationCategory.COMMERCIAL.value,
    with_spare_airframe=False,
    with_open_zone_flight=False,
):
    """A certified operator holding one approved slot and one flight that depends on it.

    Everything the cascade will walk is built once here: the airframe the pilot owns,
    the controlled zone whose slot the approval took, and the planned flight that cites
    the approval. The optional extras are the controls — an airframe never registered
    and a sibling flight in uncontrolled airspace that cites nothing at all.
    """
    set_clock(api, CASCADE_SETUP_DAY, headers=COMPLIANCE_OFFICER)
    pilot = create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=CASCADE_SETUP_DAY
    )
    aircraft = create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    spare_aircraft = None
    if with_spare_airframe:
        spare_aircraft = create_aircraft(
            api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
        )
    policy = create_active_policy(
        api,
        pilot["id"],
        coverage_limit_cents=coverage_limit_cents,
        deductible_cents=50000,
    )
    controlled_zone = create_controlled_zone(
        api,
        class_code=zone_class_code,
        class_ceiling_ft=700,
        max_concurrent_authorizations=2,
        structure_relief_eligible=False,
    )
    authorization = create_approved_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        controlled_zone["id"],
        AUTH_WINDOW_START,
        AUTH_WINDOW_END,
        requested_ceiling_ft=400,
    )
    controlled_flight = create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        controlled_zone["id"],
        CONTROLLED_FLIGHT_START,
        CONTROLLED_FLIGHT_END,
        operation_category=operation_category,
        planned_max_altitude_ft=380,
        authorization_id=authorization["id"],
    )
    open_zone = None
    open_zone_flight = None
    if with_open_zone_flight:
        open_zone = create_zone(
            api,
            class_code=ZoneClassCode.G.value,
            class_ceiling_ft=400,
            requires_authorization=False,
            max_concurrent_authorizations=2,
        )
        open_zone_flight = create_planned_flight(
            api,
            pilot["id"],
            aircraft["id"],
            open_zone["id"],
            OPEN_ZONE_FLIGHT_START,
            OPEN_ZONE_FLIGHT_END,
            operation_category=operation_category,
            planned_max_altitude_ft=380,
        )
    return {
        "pilot": pilot,
        "aircraft": aircraft,
        "spare_aircraft": spare_aircraft,
        "policy": policy,
        "controlled_zone": controlled_zone,
        "authorization": authorization,
        "controlled_flight": controlled_flight,
        "open_zone": open_zone,
        "open_zone_flight": open_zone_flight,
        "pilot_headers": make_pilot_headers(pilot["id"]),
    }


def test_suspending_the_pilot_grounds_revokes_and_cancels_in_one_call(api):
    """PRD §2.8: "The pilot moves to `SUSPENDED` and `suspension_reason` is recorded; because the pilot is suspended, every airframe they own whose `registration_status` is `REGISTERED` moves to `GROUNDED` with `grounding_reason` set to `OWNER_SUSPENDED`; because each of those airframes is now grounded, every airspace authorization bound to one of them whose `status` is `APPROVED` or `ACTIVE` moves to `REVOKED`, and each such revocation decrements that zone's `reserved_slot_count` by 1 and increments the zone's `version` by 1; and because those authorizations are revoked, every flight citing one of them whose `status` is `PLANNED` or `PREFLIGHT_CLEARED` moves to `CANCELLED` with `cancellation_reason` set to `AUTHORIZATION_REVOKED`."
    PRD §2.8: "A single operator action in this service routinely mutates rows several levels away from the one addressed, and the propagation is transitive: each link fires *because the previous link mutated something*, not because the original caller asked for it."
    PRD §2.10: "A zone's `reserved_slot_count` must at all times equal the number of airspace authorizations on that zone whose `status` is `APPROVED` or `ACTIVE`."
    PRD §2.2: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Difficulty/transitive_cascade/pilot_suspension_cascades_through_aircraft_authorization_to_flight
    """
    scene = _authorized_operation_scene(api)
    zone_id = scene["controlled_zone"]["id"]

    assert scene["authorization"]["granted_ceiling_ft"] == 400, (
        "a commercial operator over a zone with no structure relief is capped at 400 "
        f"feet, got {scene['authorization']['granted_ceiling_ft']}"
    )
    before_zone = read_zone(api, zone_id)
    assert before_zone["reserved_slot_count"] == 1, (
        "the approval holds exactly one slot before the suspension, got "
        f"{before_zone['reserved_slot_count']}"
    )
    pilot_version_before = read_pilot(api, scene["pilot"]["id"])["version"]

    suspended = get_success_data(
        api.suspend_pilot(
            scene["pilot"]["id"],
            suspension_payload(SUSPENSION_REASON),
            headers=COMPLIANCE_OFFICER,
        )
    )
    assert suspended["status"] == PilotStatus.SUSPENDED.value, (
        f"the addressed pilot is the first link, got {suspended['status']}"
    )
    assert suspended["suspension_reason"] == SUSPENSION_REASON, (
        f"the supplied reason is recorded, got {suspended['suspension_reason']!r}"
    )
    assert suspended["version"] == pilot_version_before + 1, (
        "one mutation of the pilot row means exactly one version step, expected "
        f"{pilot_version_before + 1}, got {suspended['version']}"
    )

    grounded = get_success_data(
        api.get_aircraft(scene["aircraft"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert grounded["registration_status"] == RegistrationStatus.GROUNDED.value, (
        "the owner's suspension grounds the registered airframe, got "
        f"{grounded['registration_status']}"
    )
    assert grounded["grounding_reason"] == SystemGroundingReason.OWNER_SUSPENDED.value, (
        f"the service writes its own reason, got {grounded['grounding_reason']!r}"
    )

    revoked = get_success_data(
        api.get_authorization(scene["authorization"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert revoked["status"] == AuthorizationStatus.REVOKED.value, (
        "the grounded airframe's live authorization is revoked, got "
        f"{revoked['status']}"
    )
    after_zone = read_zone(api, zone_id)
    assert after_zone["reserved_slot_count"] == 0, (
        "revocation returns the slot, expected 0, got "
        f"{after_zone['reserved_slot_count']}"
    )
    assert after_zone["version"] == before_zone["version"] + 1, (
        "releasing the slot is one mutation of the zone, expected "
        f"{before_zone['version'] + 1}, got {after_zone['version']}"
    )

    cancelled = get_success_data(
        api.get_flight(scene["controlled_flight"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert cancelled["status"] == FlightStatus.CANCELLED.value, (
        "the flight that cited the revoked authorization is the fourth link, got "
        f"{cancelled['status']}"
    )
    assert cancelled["cancellation_reason"] == (
        SystemCancellationReason.AUTHORIZATION_REVOKED.value
    ), (
        "the cascade writes its own fixed reason, got "
        f"{cancelled['cancellation_reason']!r}"
    )


def test_the_suspension_cascade_spares_unregistered_airframes_and_is_never_undone(api):
    """PRD §2.8: "What the cascade deliberately leaves alone matters as much as what it touches: flights already `COMPLETED` or `IN_PROGRESS` are untouched, authorizations already `DENIED`, `CONSUMED`, `REVOKED` or `EXPIRED` are untouched, and airframes still in `PENDING_REGISTRATION` are untouched."
    PRD §2.8: "Cascades are one-way. Reinstating a suspended pilot does not return their grounded airframes to service — each airframe must be individually returned. Returning an airframe to service does not resurrect the authorizations that were revoked when it was grounded."
    PRD §3.9: "On success the pilot returns to `CERTIFIED`, `suspension_reason` is cleared to null, `risk_score` is recomputed from the definition above, and the pilot's `version` is incremented."
    PRD §3.6: "The three ledger figures are always definitionally derived, never incrementally patched."

    Design: Difficulty/transitive_cascade/pilot_suspension_cascades_through_aircraft_authorization_to_flight
    """
    scene = _authorized_operation_scene(api, with_spare_airframe=True)
    get_success_data(
        api.suspend_pilot(
            scene["pilot"]["id"],
            suspension_payload(SUSPENSION_REASON),
            headers=COMPLIANCE_OFFICER,
        )
    )

    spare = get_success_data(
        api.get_aircraft(scene["spare_aircraft"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert spare["registration_status"] == (
        RegistrationStatus.PENDING_REGISTRATION.value
    ), (
        "an airframe that was never registered is outside the cascade's reach, got "
        f"{spare['registration_status']}"
    )
    assert spare["grounding_reason"] is None, (
        f"an untouched airframe keeps a null grounding reason, got {spare['grounding_reason']!r}"
    )

    policy = read_policy(api, scene["policy"]["id"])
    assert policy["coverage_status"] == CoverageStatus.ACTIVE.value, (
        "no accident report exists, so the money ledger is untouched by an enforcement "
        f"action, got {policy['coverage_status']}"
    )
    assert policy["remaining_coverage_cents"] == 5000000, (
        "with no reserves and no settlements the whole limit remains, expected 5000000, "
        f"got {policy['remaining_coverage_cents']}"
    )

    reinstated = get_success_data(
        api.reinstate_pilot(scene["pilot"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert reinstated["status"] == PilotStatus.CERTIFIED.value, (
        f"reinstatement returns the pilot to CERTIFIED, got {reinstated['status']}"
    )
    assert reinstated["suspension_reason"] is None, (
        f"the recorded reason is cleared, got {reinstated['suspension_reason']!r}"
    )

    still_grounded = get_success_data(
        api.get_aircraft(scene["aircraft"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert still_grounded["registration_status"] == RegistrationStatus.GROUNDED.value, (
        "a grounded airframe must be returned to service individually, got "
        f"{still_grounded['registration_status']}"
    )
    still_revoked = get_success_data(
        api.get_authorization(scene["authorization"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert still_revoked["status"] == AuthorizationStatus.REVOKED.value, (
        f"a revoked authorization is never resurrected, got {still_revoked['status']}"
    )
    still_cancelled = get_success_data(
        api.get_flight(scene["controlled_flight"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert still_cancelled["status"] == FlightStatus.CANCELLED.value, (
        f"a cancelled flight is never resurrected, got {still_cancelled['status']}"
    )
    assert read_zone(api, scene["controlled_zone"]["id"])["reserved_slot_count"] == 0, (
        "the released slot is not re-taken by the reinstatement, expected 0 slots held"
    )


def test_the_suspension_cascade_stops_at_a_flight_that_cites_no_authorization(api):
    """PRD §2.8: "and because those authorizations are revoked, every flight citing one of them whose `status` is `PLANNED` or `PREFLIGHT_CLEARED` moves to `CANCELLED` with `cancellation_reason` set to `AUTHORIZATION_REVOKED`."
    PRD §2.8: "because each of those airframes is now grounded, every airspace authorization bound to one of them whose `status` is `APPROVED` or `ACTIVE` moves to `REVOKED`, and each such revocation decrements that zone's `reserved_slot_count` by 1 and increments the zone's `version` by 1"
    PRD §3.5: "A new zone starts with `reserved_slot_count` 0 and `version` 1."
    PRD §2.10: "A zone's `reserved_slot_count` must at all times equal the number of airspace authorizations on that zone whose `status` is `APPROVED` or `ACTIVE`."

    Design: Corner/state_machines/suspension_cascade_reaches_only_flights_whose_authorization_was_revoked
    """
    scene = _authorized_operation_scene(
        api,
        zone_class_code=ZoneClassCode.C.value,
        coverage_limit_cents=2000000,
        operation_category=OperationCategory.RECREATIONAL.value,
        with_open_zone_flight=True,
    )
    open_zone_before = read_zone(api, scene["open_zone"]["id"])
    assert open_zone_before["reserved_slot_count"] == 0, (
        "no authorization was ever approved over the uncontrolled zone, got "
        f"{open_zone_before['reserved_slot_count']}"
    )

    suspended = get_success_data(
        api.suspend_pilot(
            scene["pilot"]["id"],
            suspension_payload(SUSPENSION_REASON),
            headers=COMPLIANCE_OFFICER,
        )
    )
    assert suspended["status"] == PilotStatus.SUSPENDED.value, (
        f"the trigger must land, got {suspended['status']}"
    )

    grounded = get_success_data(
        api.get_aircraft(scene["aircraft"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert grounded["registration_status"] == RegistrationStatus.GROUNDED.value, (
        f"both flights name this airframe, and it is grounded, got {grounded['registration_status']}"
    )
    assert get_success_data(
        api.get_authorization(scene["authorization"]["id"], headers=COMPLIANCE_OFFICER)
    )["status"] == AuthorizationStatus.REVOKED.value, (
        "the controlled-zone authorization is revoked by the grounding"
    )
    assert read_zone(api, scene["controlled_zone"]["id"])["reserved_slot_count"] == 0, (
        "the revocation returns the controlled zone's slot"
    )

    cancelled = get_success_data(
        api.get_flight(scene["controlled_flight"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert cancelled["status"] == FlightStatus.CANCELLED.value, (
        "the flight citing the revoked authorization is cancelled, got "
        f"{cancelled['status']}"
    )
    assert cancelled["cancellation_reason"] == (
        SystemCancellationReason.AUTHORIZATION_REVOKED.value
    ), (
        f"the cascade names the revocation, got {cancelled['cancellation_reason']!r}"
    )

    survivor = get_success_data(
        api.get_flight(scene["open_zone_flight"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert survivor["status"] == FlightStatus.PLANNED.value, (
        "the uncontrolled-zone flight cites no authorization, so the last link never "
        f"reaches it, got {survivor['status']}"
    )
    assert survivor["cancellation_reason"] is None, (
        f"an uncancelled flight has no reason recorded, got {survivor['cancellation_reason']!r}"
    )

    open_zone_after = read_zone(api, scene["open_zone"]["id"])
    assert open_zone_after["reserved_slot_count"] == 0, (
        "the uncontrolled zone never held a slot to release, got "
        f"{open_zone_after['reserved_slot_count']}"
    )
    assert open_zone_after["version"] == open_zone_before["version"], (
        "no link of the cascade touches the uncontrolled zone, so its version is "
        f"unchanged, expected {open_zone_before['version']}, got {open_zone_after['version']}"
    )


INCIDENT_FLIGHT_START = "2026-08-10T09:00:00Z"
INCIDENT_FLIGHT_END = "2026-08-10T10:00:00Z"
FUTURE_FLIGHT_START = "2026-08-25T09:00:00Z"
FUTURE_FLIGHT_END = "2026-08-25T10:00:00Z"
FILING_DAY = "2026-08-11T00:00:00Z"
INCIDENT_OCCURRED_AT = "2026-08-10T09:45:00Z"


def _thinly_covered_operator_with_a_flown_incident(api):
    """A commercial operator on a two-million-cent policy with one mission still to fly.

    The first mission has landed with an incident aboard, so a report can be filed
    against an instant inside its window; the second is still `PLANNED` a fortnight
    out and is the row the money link of the cascade will reach.
    """
    set_clock(api, CASCADE_SETUP_DAY, headers=COMPLIANCE_OFFICER)
    pilot = create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=CASCADE_SETUP_DAY
    )
    aircraft = create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=1500
    )
    zone = create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=400,
        requires_authorization=False,
        max_concurrent_authorizations=3,
    )
    policy = create_active_policy(
        api, pilot["id"], coverage_limit_cents=2000000, deductible_cents=50000
    )
    pilot_headers = make_pilot_headers(pilot["id"])
    flown_flight = create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        INCIDENT_FLIGHT_START,
        INCIDENT_FLIGHT_END,
        operation_category=OperationCategory.COMMERCIAL.value,
        planned_max_altitude_ft=380,
    )
    future_flight = create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        FUTURE_FLIGHT_START,
        FUTURE_FLIGHT_END,
        operation_category=OperationCategory.COMMERCIAL.value,
        planned_max_altitude_ft=390,
    )
    check = clear_flight_for_launch(api, flown_flight)
    assert check["result"] == PreflightResult.PASSED.value, (
        f"setup expected a PASSED pre-flight sweep, got {check['result']} with "
        f"findings {check['blocking_findings']}"
    )
    set_clock(api, INCIDENT_FLIGHT_START, headers=COMPLIANCE_OFFICER)
    get_success_data(api.launch_flight(flown_flight["id"], headers=pilot_headers))
    get_success_data(
        api.complete_flight(
            flown_flight["id"],
            completion_payload(
                INCIDENT_FLIGHT_END,
                max_altitude_reached_ft=360,
                incident_occurred=True,
                incident_summary="Propeller shed a blade over open farmland on descent.",
            ),
            headers=pilot_headers,
        )
    )
    set_clock(api, FILING_DAY, headers=COMPLIANCE_OFFICER)
    return {
        "pilot": pilot,
        "aircraft": aircraft,
        "zone": zone,
        "policy": policy,
        "flown_flight": flown_flight,
        "future_flight": future_flight,
        "pilot_headers": pilot_headers,
    }


def test_filing_opens_the_investigation_erodes_the_cover_and_cancels_the_next_mission(api):
    """PRD §2.8: "The report is created; because the report exists, the named flight's `investigation_status` moves from `NONE` to `OPEN` while its operational `status` is left exactly as it was; because the report holds a provisional reserve, the covering policy's `open_reserved_cents_total` rises and its `remaining_coverage_cents` falls by that reserve, bumping the policy's `version`; and because the policy's remaining cover may now be too thin for commercial work, a policy that drops below the commercial minimum moves from `ACTIVE` to `INSUFFICIENT`, which in turn cancels every `PLANNED` commercial flight covered by that policy with `cancellation_reason` set to `COVERAGE_INSUFFICIENT`."
    PRD §3.8: "Select the injury reserve from the `injury_level` — 0 cents for `NONE`, 250000 cents for `MINOR`, 1500000 cents for `SERIOUS`. Multiply the `reported_property_damage_cents` by 1.25 and round half-up to whole cents, then add the injury reserve; that sum is the raw reserve."
    PRD §3.6: "When a filing pushes the recomputed `remaining_coverage_cents` below 1000000 cents, an `ACTIVE` policy moves to `INSUFFICIENT` and every commercial flight in `PLANNED` that named the policy as its cover is cancelled (§2.8)."
    PRD §2.10: "A policy's `coverage_limit_cents` must at all times equal the sum of its `remaining_coverage_cents`, its `open_reserved_cents_total` and its `settled_cents_total`, where `open_reserved_cents_total` is the sum of `reserved_cents` over the accident reports against that policy whose `status` is `FILED`, `INVESTIGATING` or `REMEDIATION_REQUIRED`, and `settled_cents_total` is the sum of `settlement_cents` over the reports against that policy whose `status` is `CLOSED`."

    Design: Difficulty/transitive_cascade/accident_filing_cascades_through_investigation_and_coverage_to_future_flight
    """
    scene = _thinly_covered_operator_with_a_flown_incident(api)
    assert scene["future_flight"]["covering_policy_id"] == scene["policy"]["id"], (
        "setup expected the still-planned commercial mission to name the two-million "
        f"policy as its cover, got {scene['future_flight']['covering_policy_id']!r}"
    )

    report = create_filed_report(
        api,
        scene["flown_flight"],
        INCIDENT_OCCURRED_AT,
        injury_level=InjuryLevel.MINOR.value,
        reported_property_damage_cents=800000,
    )
    assert report["status"] == ReportStatus.FILED.value, (
        f"the filing is the first link, got {report['status']}"
    )
    assert report["reserved_cents"] == 1250000, (
        "the raw reserve is the minor-injury figure plus the damage inflated by a "
        f"quarter, expected 1250000, got {report['reserved_cents']}"
    )

    flown = get_success_data(
        api.get_flight(scene["flown_flight"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert flown["investigation_status"] == InvestigationStatus.OPEN.value, (
        "the named flight's investigation dimension opens, got "
        f"{flown['investigation_status']}"
    )
    assert flown["status"] == FlightStatus.COMPLETED.value, (
        "the operational status is left exactly as it was, got "
        f"{flown['status']}"
    )

    policy = read_policy(api, scene["policy"]["id"])
    assert policy["open_reserved_cents_total"] == 1250000, (
        "the reserve is held open against the cover, expected 1250000, got "
        f"{policy['open_reserved_cents_total']}"
    )
    assert policy["remaining_coverage_cents"] == 750000, (
        "the remaining cover falls by exactly the reserve, expected 750000, got "
        f"{policy['remaining_coverage_cents']}"
    )
    assert policy["coverage_status"] == CoverageStatus.INSUFFICIENT.value, (
        "cover of 750000 cents is below the commercial minimum, got "
        f"{policy['coverage_status']}"
    )
    assert policy["version"] > scene["policy"]["version"], (
        "the erosion mutates the policy row, so its version must advance past "
        f"{scene['policy']['version']}, got {policy['version']}"
    )
    assert_coverage_ledger_conservation(api, scene["policy"]["id"], COMPLIANCE_OFFICER)

    cancelled = get_success_data(
        api.get_flight(scene["future_flight"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert cancelled["status"] == FlightStatus.CANCELLED.value, (
        "the under-covered commercial mission is the fourth link, got "
        f"{cancelled['status']}"
    )
    assert cancelled["cancellation_reason"] == (
        SystemCancellationReason.COVERAGE_INSUFFICIENT.value
    ), (
        "the money link writes its own fixed reason, got "
        f"{cancelled['cancellation_reason']!r}"
    )


REPLACEMENT_FLIGHT_START = "2026-09-01T09:00:00Z"
REPLACEMENT_FLIGHT_END = "2026-09-01T10:00:00Z"


def test_the_filing_cascade_stops_at_the_money_and_bars_the_next_commercial_plan(api):
    """PRD §3.8: "Filing immediately takes a **provisional reserve** against the covering policy: a hold, not a payment."
    PRD §3.6: "Policies in `PENDING_VERIFICATION`, `REJECTED`, `INSUFFICIENT` or `EXPIRED` are excluded outright, and any policy whose `effective_until` has already passed is first moved to `EXPIRED` and thereby drops out of the candidate set."
    PRD §3.6: "When no candidate survives, the flight is refused, and which of three errors is returned is pinned by the ladder of §2.11 rather than by the selector: `ERR_INSURANCE_NOT_ACTIVE` when the pilot has no `ACTIVE` policy at all; `ERR_INDEMNIFICATION_NOT_ACCEPTED` when an `ACTIVE` policy does cover the window but its `indemnification_clause_accepted` is false; and `ERR_INSURANCE_COVERAGE_INSUFFICIENT` when an `ACTIVE`, indemnified policy covers the window but its `remaining_coverage_cents` is below 1000000 cents."
    PRD §2.11: "**Commercial insurance presence**, on `POST /drone-ops/flights` and `POST /drone-ops/airspace-authorizations`: the pilot holds a policy in `coverage_status` `ACTIVE` spanning the requested window — otherwise `ERR_INSURANCE_NOT_ACTIVE` (402)."

    Design: Difficulty/transitive_cascade/accident_filing_cascades_through_investigation_and_coverage_to_future_flight
    """
    scene = _thinly_covered_operator_with_a_flown_incident(api)
    report = create_filed_report(
        api,
        scene["flown_flight"],
        INCIDENT_OCCURRED_AT,
        injury_level=InjuryLevel.MINOR.value,
        reported_property_damage_cents=800000,
    )

    assert report["settlement_cents"] is None, (
        "a hold is not a payment, so nothing is settled at filing, got "
        f"{report['settlement_cents']!r}"
    )
    policy = read_policy(api, scene["policy"]["id"])
    assert policy["settled_cents_total"] == 0, (
        f"no money has been paid out, expected 0, got {policy['settled_cents_total']}"
    )
    assert policy["coverage_status"] == CoverageStatus.INSUFFICIENT.value, (
        f"setup expected the erosion to demote the cover, got {policy['coverage_status']}"
    )

    pilot = read_pilot(api, scene["pilot"]["id"])
    assert pilot["status"] == PilotStatus.CERTIFIED.value, (
        "this cascade walks the report, the flight and the money, never the "
        f"certificate, got {pilot['status']}"
    )
    airframe = get_success_data(
        api.get_aircraft(scene["aircraft"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert airframe["registration_status"] == RegistrationStatus.REGISTERED.value, (
        "no link of this cascade grounds an airframe, got "
        f"{airframe['registration_status']}"
    )

    refused = api.create_flight(
        flight_payload(
            scene["pilot"]["id"],
            scene["aircraft"]["id"],
            scene["zone"]["id"],
            REPLACEMENT_FLIGHT_START,
            REPLACEMENT_FLIGHT_END,
            operation_category=OperationCategory.COMMERCIAL.value,
            planned_max_altitude_ft=380,
        ),
        headers=scene["pilot_headers"],
    )
    validate_error(
        refused,
        ApiErrorId.INSURANCE_NOT_ACTIVE.value,
        HTTP_STATUS_CODES[ApiErrorId.INSURANCE_NOT_ACTIVE.value],
    )


ENROLMENT_DAY = "2026-08-02T00:00:00Z"
RESTRICTION_FROM = "2026-08-04T00:00:00Z"
RESTRICTION_UNTIL = "2026-08-05T00:00:00Z"


def _one_row_of_every_kind(api):
    """One freshly created row of each kind, all minted at the same instant.

    Nothing here is driven forward: the pilot is only enrolled, the airframe only
    declared, the module only attached, the policy only filed, and the zone and its
    restriction only published, so every row is still in the state it was born in.
    """
    set_clock(api, ENROLMENT_DAY, headers=COMPLIANCE_OFFICER)
    pilot = create_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = create_aircraft(
        api, pilot["id"], takeoff_weight_g=1200, max_altitude_ft=1500
    )
    module = get_success_data(
        api.create_remote_id_module(
            aircraft["id"],
            module_payload(
                broadcast_protocol=BroadcastProtocol.BLUETOOTH_LE.value,
                firmware_version="2.0.0",
            ),
            headers=make_pilot_headers(pilot["id"]),
        ),
        201,
    )
    policy = create_filed_policy(
        api, pilot["id"], coverage_limit_cents=3000000, deductible_cents=50000
    )
    zone = create_zone(
        api,
        class_code=ZoneClassCode.C.value,
        class_ceiling_ft=600,
        requires_authorization=True,
        max_concurrent_authorizations=4,
    )
    restriction = create_tfr(
        api,
        zone["id"],
        RESTRICTION_FROM,
        RESTRICTION_UNTIL,
        max_permitted_altitude_ft=0,
    )
    return {
        "pilot": pilot,
        "aircraft": aircraft,
        "module": module,
        "policy": policy,
        "zone": zone,
        "restriction": restriction,
    }


def test_every_freshly_created_row_lands_in_its_declared_opening_state(api):
    """PRD §3.1: "The new pilot lands in `UNCERTIFIED` with no certificate and no currency: `certified_at` is null, `currency_expires_at` is null, `suspension_reason` is null, and the three derived counters `risk_score`, `knowledge_attempt_count` and `open_waiver_count` all start at 0."
    PRD §3.3: "The airframe begins in `PENDING_REGISTRATION` with `registration_number` null and `grounding_reason` null."
    PRD §3.3: "The module is created in `UNVERIFIED` with `verified_at`, `verified_until` and `failure_reason` all null."
    PRD §3.6: "Filing grants nothing: the policy is created in `PENDING_VERIFICATION` with all three ledger figures — `open_reserved_cents_total`, `settled_cents_total` and `remaining_coverage_cents` — at 0, so an unverified policy covers no flight even if its limit is enormous."
    PRD §3.4: "A new zone starts with `reserved_slot_count` 0 and `version` 1."
    PRD §3.4: "A restriction is created in `ACTIVE` with `published_by_user_id` set to the publishing operator's `X-User-ID`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    rows = _one_row_of_every_kind(api)

    pilot = rows["pilot"]
    assert pilot["status"] == PilotStatus.UNCERTIFIED.value, (
        f"enrolment grants no certificate, got {pilot['status']}"
    )
    assert pilot["certified_at"] is None, (
        f"an uncertified pilot has no certification instant, got {pilot['certified_at']!r}"
    )
    assert pilot["currency_expires_at"] is None, (
        f"there is nothing yet for currency to govern, got {pilot['currency_expires_at']!r}"
    )
    assert pilot["suspension_reason"] is None, (
        f"nothing has been held against the operator, got {pilot['suspension_reason']!r}"
    )
    assert (
        pilot["risk_score"] == 0
        and pilot["knowledge_attempt_count"] == 0
        and pilot["open_waiver_count"] == 0
    ), (
        "all three derived counters start at 0, got risk "
        f"{pilot['risk_score']}, attempts {pilot['knowledge_attempt_count']}, "
        f"open waivers {pilot['open_waiver_count']}"
    )

    aircraft = rows["aircraft"]
    assert aircraft["registration_status"] == (
        RegistrationStatus.PENDING_REGISTRATION.value
    ), (
        f"declaring an airframe does not register it, got {aircraft['registration_status']}"
    )
    assert aircraft["registration_number"] is None, (
        f"no marking is issued before registration, got {aircraft['registration_number']!r}"
    )
    assert aircraft["grounding_reason"] is None, (
        f"an unregistered airframe was never grounded, got {aircraft['grounding_reason']!r}"
    )

    module = rows["module"]
    assert module["status"] == ModuleStatus.UNVERIFIED.value, (
        f"attaching a module adjudicates nothing, got {module['status']}"
    )
    assert (
        module["verified_at"] is None
        and module["verified_until"] is None
        and module["failure_reason"] is None
    ), (
        "an unadjudicated module carries no verdict, got verified_at "
        f"{module['verified_at']!r}, verified_until {module['verified_until']!r}, "
        f"failure_reason {module['failure_reason']!r}"
    )

    policy = rows["policy"]
    assert policy["coverage_status"] == CoverageStatus.PENDING_VERIFICATION.value, (
        f"filing grants no cover, got {policy['coverage_status']}"
    )
    assert policy["coverage_limit_cents"] == 3000000, (
        "the filed limit is recorded as declared, expected 3000000, got "
        f"{policy['coverage_limit_cents']}"
    )
    assert (
        policy["open_reserved_cents_total"] == 0
        and policy["settled_cents_total"] == 0
        and policy["remaining_coverage_cents"] == 0
    ), (
        "all three ledger figures start at 0 however large the limit, got open "
        f"{policy['open_reserved_cents_total']}, settled {policy['settled_cents_total']}, "
        f"remaining {policy['remaining_coverage_cents']}"
    )

    zone = rows["zone"]
    assert zone["reserved_slot_count"] == 0, (
        f"a new zone holds no slots, got {zone['reserved_slot_count']}"
    )
    assert zone["requires_authorization"] is True, (
        "the published zone is controlled airspace as declared, got "
        f"{zone['requires_authorization']!r}"
    )

    restriction = rows["restriction"]
    assert restriction["status"] == RestrictionStatus.ACTIVE.value, (
        f"a published restriction bites immediately, got {restriction['status']}"
    )
    assert restriction["published_by_user_id"] == AIRSPACE_AUTHORITY_ID, (
        "the publishing operator's identity is recorded, expected "
        f"{AIRSPACE_AUTHORITY_ID}, got {restriction['published_by_user_id']!r}"
    )
    assert restriction["max_permitted_altitude_ft"] == 0, (
        "a restriction that names an altitude cap keeps the declared figure, expected "
        f"0, got {restriction['max_permitted_altitude_ft']!r}"
    )


def test_every_freshly_created_row_opens_at_version_one_and_the_clocks_instant(api):
    """PRD §2.2: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."
    PRD §2.2: "Every resource also carries a `created_at`, the ISO 8601 UTC instant of creation taken from the logical clock."
    PRD §3.4: "A new zone starts with `reserved_slot_count` 0 and `version` 1."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    rows = _one_row_of_every_kind(api)

    for label in ("pilot", "aircraft", "module", "policy", "zone", "restriction"):
        row = rows[label]
        assert row["version"] == 1, (
            f"an unmutated {label} row is still at its opening version, expected 1, "
            f"got {row['version']}"
        )
        assert_instant_equals(
            row["created_at"], ENROLMENT_DAY, f"{label} created_at"
        )
        assert_instant_equals(
            row["updated_at"], ENROLMENT_DAY, f"{label} updated_at"
        )


REVOCATION_DAY = "2026-08-15T00:00:00Z"
REVOCATION_REASON = "Repeated operation inside a published restriction."


def _revoked_operator(api):
    """An operator taken all the way to the terminal state, airframe and all.

    Revocation is only reachable through suspension, so the pilot is suspended first
    and the airframe therefore passes through `GROUNDED` on its way out.
    """
    set_clock(api, REVOCATION_DAY, headers=COMPLIANCE_OFFICER)
    pilot = create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=REVOCATION_DAY
    )
    aircraft = create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=700
    )
    get_success_data(
        api.suspend_pilot(
            pilot["id"], suspension_payload(SUSPENSION_REASON), headers=COMPLIANCE_OFFICER
        )
    )
    revoked = get_success_data(
        api.revoke_pilot(
            pilot["id"],
            revocation_payload(REVOCATION_REASON),
            headers=COMPLIANCE_OFFICER,
        )
    )
    assert revoked["status"] == PilotStatus.REVOKED.value, (
        f"setup expected the terminal state, got {revoked['status']}"
    )
    return {"pilot": pilot, "aircraft": aircraft, "revoked": revoked}


def test_a_revoked_operator_refuses_reinstatement_suspension_revocation_and_review(api):
    """PRD §3.9: "It takes a `suspension_reason`, which overwrites whatever reason the suspension recorded, and moves the pilot to `REVOKED`, which is terminal."
    PRD §3.9: "Note that revocation reaches airframes still in `PENDING_REGISTRATION`, which the suspension cascade leaves alone, and that no transition anywhere returns a pilot from `REVOKED`."
    PRD §3.9: "Reinstatement lifts the suspension and is admissible only from `SUSPENDED`."
    PRD §3.2: "A review on a pilot who is neither `CERTIFIED` nor `LAPSED` is refused with `ERR_PILOT_INVALID_STATE`."
    PRD §2.11: "**Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."
    PRD §2.2: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/a_revoked_pilot_rejects_every_further_transition
    """
    scene = _revoked_operator(api)
    pilot_id = scene["pilot"]["id"]
    terminal_version = scene["revoked"]["version"]
    expected_status = HTTP_STATUS_CODES[ApiErrorId.PILOT_INVALID_STATE.value]

    validate_error(
        api.reinstate_pilot(pilot_id, headers=COMPLIANCE_OFFICER),
        ApiErrorId.PILOT_INVALID_STATE.value,
        expected_status,
    )
    validate_error(
        api.suspend_pilot(
            pilot_id, suspension_payload("A second hold on a closed file."), headers=COMPLIANCE_OFFICER
        ),
        ApiErrorId.PILOT_INVALID_STATE.value,
        expected_status,
    )
    validate_error(
        api.revoke_pilot(
            pilot_id,
            revocation_payload("A second revocation of the same privileges."),
            headers=COMPLIANCE_OFFICER,
        ),
        ApiErrorId.PILOT_INVALID_STATE.value,
        expected_status,
    )
    validate_error(
        api.currency_review(pilot_id, headers=COMPLIANCE_OFFICER),
        ApiErrorId.PILOT_INVALID_STATE.value,
        expected_status,
    )

    final = read_pilot(api, pilot_id)
    assert final["status"] == PilotStatus.REVOKED.value, (
        f"four refusals leave the terminal state untouched, got {final['status']}"
    )
    assert final["version"] == terminal_version, (
        "a refused transition mutates nothing, so the version does not move, expected "
        f"{terminal_version}, got {final['version']}"
    )
    assert final["suspension_reason"] == REVOCATION_REASON, (
        "the reason recorded by the revocation survives the refused calls, expected "
        f"{REVOCATION_REASON!r}, got {final['suspension_reason']!r}"
    )


def test_a_revoked_operators_holdings_are_terminal_too(api):
    """PRD §3.9: "It then terminates everything the pilot holds, in the order fixed by §2.8: every certification of theirs in `ACTIVE`, `SUPERSEDED` or `EXPIRED` becomes `REVOKED`; every airframe of theirs in `PENDING_REGISTRATION`, `REGISTERED` or `GROUNDED` becomes `DEREGISTERED` with `grounding_reason` set to `OWNER_REVOKED`; and every waiver of theirs in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `CLEARED` or `APPROVED` becomes `REVOKED`."
    PRD §3.3: "`DEREGISTERED` is reachable from all three of `PENDING_REGISTRATION`, `REGISTERED` and `GROUNDED`, is written only by the system when the owning pilot is revoked, records `grounding_reason` as `OWNER_REVOKED`, and is terminal."
    PRD §3.3: "Return-to-service moves the airframe back from `GROUNDED` to `REGISTERED`, clears `grounding_reason` to null, and re-runs both registration gates — owner not suspended or revoked, and remote-ID compliance re-checked — so an airframe whose module expired while it sat grounded cannot fly again until the module is re-verified."
    PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "**Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."
    PRD §2.11: "**Pilot suspension gate**, on `POST /drone-ops/aircraft`, `POST /drone-ops/aircraft/{id}/register`, `POST /drone-ops/aircraft/{id}/return-to-service`, `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/waivers`, `POST /drone-ops/flights` and `POST /drone-ops/flights/{id}/launch`: the acting or target pilot's `status` is neither `SUSPENDED` nor `REVOKED` — otherwise `ERR_PILOT_SUSPENDED` (409)."

    Design: Corner/state_machines/a_revoked_pilot_rejects_every_further_transition
    """
    scene = _revoked_operator(api)

    airframe = get_success_data(
        api.get_aircraft(scene["aircraft"]["id"], headers=COMPLIANCE_OFFICER)
    )
    assert airframe["registration_status"] == RegistrationStatus.DEREGISTERED.value, (
        "the revocation deregisters the holding outright, got "
        f"{airframe['registration_status']}"
    )
    assert airframe["grounding_reason"] == SystemGroundingReason.OWNER_REVOKED.value, (
        "the system overwrites the grounding reason with its own, got "
        f"{airframe['grounding_reason']!r}"
    )

    certificates, meta = validate_paginated(
        api.list_certifications(
            params={"pilot_id": scene["pilot"]["id"], "limit": 100},
            headers=COMPLIANCE_OFFICER,
        )
    )
    assert meta["total_count"] == 1, (
        f"the operator was certified exactly once, got {meta['total_count']}"
    )
    assert certificates[0]["status"] == CertificationStatus.REVOKED.value, (
        f"the certificate is revoked with its holder, got {certificates[0]['status']}"
    )

    validate_error(
        api.return_aircraft_to_service(
            scene["aircraft"]["id"], headers=COMPLIANCE_OFFICER
        ),
        ApiErrorId.AIRCRAFT_INVALID_STATE.value,
        HTTP_STATUS_CODES[ApiErrorId.AIRCRAFT_INVALID_STATE.value],
    )


REGISTRATION_DAY = "2026-08-20T00:00:00Z"
FIRST_GROUNDING_REASON = "Motor bearing replacement."
SECOND_GROUNDING_REASON = "Overwritten reason."


def _lightweight_airframe_awaiting_registration(api):
    """A sub-250-gram airframe whose owner has only just been enrolled.

    The weight keeps the airframe out of the broadcast-module requirement, so the
    registration hop has nothing to satisfy but the owner's own standing.
    """
    set_clock(api, REGISTRATION_DAY, headers=COMPLIANCE_OFFICER)
    pilot = create_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = create_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=600
    )
    assert aircraft["version"] == 1, (
        f"setup expected an unmutated airframe row, got version {aircraft['version']}"
    )
    return {"pilot": pilot, "aircraft": aircraft}


def test_registering_an_already_registered_airframe_is_refused_not_reissued(api):
    """PRD §3.3: "Registration is a `ComplianceOfficer` act and takes no request body: the service assigns the `registration_number` itself, a non-null marking unique across all airframes, and moves the airframe from `PENDING_REGISTRATION` to `REGISTERED`."
    PRD §2.11: "**Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."
    PRD §2.2: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/repeating_a_completed_transition_is_rejected_rather_than_ignored
    """
    scene = _lightweight_airframe_awaiting_registration(api)
    aircraft_id = scene["aircraft"]["id"]

    registered = get_success_data(
        api.register_aircraft(aircraft_id, headers=COMPLIANCE_OFFICER)
    )
    assert registered["registration_status"] == RegistrationStatus.REGISTERED.value, (
        f"the first registration lands, got {registered['registration_status']}"
    )
    assert registered["registration_number"] is not None, (
        "the service mints the marking itself, got a null registration_number"
    )
    assert registered["version"] == 2, (
        f"registration is one mutation of the airframe, expected 2, got {registered['version']}"
    )

    validate_error(
        api.register_aircraft(aircraft_id, headers=COMPLIANCE_OFFICER),
        ApiErrorId.AIRCRAFT_INVALID_STATE.value,
        HTTP_STATUS_CODES[ApiErrorId.AIRCRAFT_INVALID_STATE.value],
    )

    after = get_success_data(api.get_aircraft(aircraft_id, headers=COMPLIANCE_OFFICER))
    assert after["registration_number"] == registered["registration_number"], (
        "the refusal reissues nothing, expected the marking "
        f"{registered['registration_number']!r}, got {after['registration_number']!r}"
    )
    assert after["version"] == registered["version"], (
        "a refused repeat is not a silent no-op on the version either, expected "
        f"{registered['version']}, got {after['version']}"
    )


def test_grounding_an_already_grounded_airframe_is_refused_not_overwritten(api):
    """PRD §3.3: "Grounding takes a `grounding_reason` and moves a `REGISTERED` airframe to `GROUNDED`, and it is deliberately destructive downstream: every airspace authorization bound to that airframe in `APPROVED` or `ACTIVE` is revoked, each revocation releasing a zone slot, and every planned or preflight-cleared flight that cited a revoked authorization is cancelled."
    PRD §2.11: "**Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."
    PRD §2.2: "`updated_at` is refreshed to the current instant on every mutation of that row, and `version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/repeating_a_completed_transition_is_rejected_rather_than_ignored
    """
    scene = _lightweight_airframe_awaiting_registration(api)
    aircraft_id = scene["aircraft"]["id"]
    get_success_data(api.register_aircraft(aircraft_id, headers=COMPLIANCE_OFFICER))

    grounded = get_success_data(
        api.ground_aircraft(
            aircraft_id,
            grounding_payload(FIRST_GROUNDING_REASON),
            headers=COMPLIANCE_OFFICER,
        )
    )
    assert grounded["registration_status"] == RegistrationStatus.GROUNDED.value, (
        f"the first grounding lands, got {grounded['registration_status']}"
    )
    assert grounded["grounding_reason"] == FIRST_GROUNDING_REASON, (
        f"the caller's own text is recorded, got {grounded['grounding_reason']!r}"
    )

    validate_error(
        api.ground_aircraft(
            aircraft_id,
            grounding_payload(SECOND_GROUNDING_REASON),
            headers=COMPLIANCE_OFFICER,
        ),
        ApiErrorId.AIRCRAFT_INVALID_STATE.value,
        HTTP_STATUS_CODES[ApiErrorId.AIRCRAFT_INVALID_STATE.value],
    )

    after = get_success_data(api.get_aircraft(aircraft_id, headers=COMPLIANCE_OFFICER))
    assert after["grounding_reason"] == FIRST_GROUNDING_REASON, (
        "the refused repeat does not overwrite the recorded reason, expected "
        f"{FIRST_GROUNDING_REASON!r}, got {after['grounding_reason']!r}"
    )
    assert after["version"] == 3, (
        "creation, registration and grounding are the only three mutations of this "
        f"airframe, expected version 3, got {after['version']}"
    )
