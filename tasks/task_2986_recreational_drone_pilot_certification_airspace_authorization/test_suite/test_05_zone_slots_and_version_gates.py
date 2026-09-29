"""Zone slot bookkeeping, the two optimistic-concurrency gates, the immediate
visibility of derived values, and the restriction lifecycle.

Every scenario builds its own pilot, airframe and zone: the harness restarts the
service before each test, so nothing here may assume a pre-existing row.
"""

from test_helpers import (
    AIRSPACE_AUTHORITY_ID,
    COMPLIANCE_OFFICER,
    AirRiskClass,
    ApiErrorId,
    AuthorizationStatus,
    CurrencyBasis,
    FlightStatus,
    InvestigationStatus,
    OperatorCategory,
    ReportStatus,
    RestrictionStatus,
    WaiverStatus,
    WaiverType,
    ZoneClassCode,
    assert_coverage_ledger_conservation,
    assert_instant_equals,
    assert_pagination_meta,
    assert_tfr,
    assert_zone_slot_conservation,
    factories,
    fixtures,
    make_pilot_headers,
    paginated_ids,
    set_clock,
    shift_days,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_INSTANT = "2026-08-05T00:00:00Z"
POLICY_END = "2027-08-05T00:00:00Z"


def _conservation_scenario(api):
    """A commercial operation over a two-slot class C zone with two lodged
    requests: one on 19 August, one on 20 August."""
    set_clock(api, SETUP_INSTANT, headers=COMPLIANCE_OFFICER)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=SETUP_INSTANT
    )
    fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=5000000,
        deductible_cents=50000,
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_controlled_zone(
        api,
        class_code=ZoneClassCode.C.value,
        class_ceiling_ft=700,
        max_concurrent_authorizations=2,
        structure_relief_eligible=False,
    )
    assert zone["reserved_slot_count"] == 0, (
        f"a new zone opens with no slots taken, got {zone['reserved_slot_count']}"
    )
    first = fixtures.create_requested_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-19T09:00:00Z",
        "2026-08-19T12:00:00Z",
    )
    second = fixtures.create_requested_authorization(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T12:00:00Z",
    )
    return pilot, aircraft, zone, first, second


def test_revoking_an_approval_returns_the_slot_count_exactly(api, airspace_authority):
    """PRD §2.10: "A zone's `reserved_slot_count` must at all times equal the number of airspace authorizations on that zone whose `status` is `APPROVED` or `ACTIVE`."
    PRD §2.10: "Consequently, for any zone and any authorization on it, the slot count after approving and then revoking that authorization equals the slot count before the approval, exactly."
    PRD §3.4: "The authority may revoke an authorization in either `APPROVED` or `ACTIVE`, optionally recording a `denial_reason`; the slot is released, the zone's `version` advances, and every planned or preflight-cleared flight citing the authorization is cancelled — but a flight already `IN_PROGRESS` is left running, since the aircraft is in the air."

    Design: Difficulty/compensating_invariant/zone_slot_conservation_under_revoke_and_under_consume
    """
    _pilot, _aircraft, zone, first, _second = _conservation_scenario(api)
    before = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert before["reserved_slot_count"] == 0, (
        f"two lodged requests reserve nothing, got {before['reserved_slot_count']}"
    )

    approved = validate_success(
        api.decide_authorization(
            first["id"], factories.approve_authorization_payload(), headers=airspace_authority
        )
    )
    assert approved["status"] == AuthorizationStatus.APPROVED.value, (
        f"the decision approves the request, got {approved['status']}"
    )
    after_approve = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert after_approve["reserved_slot_count"] == 1, (
        f"approval takes exactly one slot, got {after_approve['reserved_slot_count']}"
    )
    assert after_approve["version"] > before["version"], (
        f"approval advances the zone version; was {before['version']}, now "
        f"{after_approve['version']}"
    )

    revoked = validate_success(
        api.revoke_authorization(
            first["id"],
            factories.revoke_authorization_payload(
                denial_reason="Airfield works moved into the requested window."
            ),
            headers=airspace_authority,
        )
    )
    assert revoked["status"] == AuthorizationStatus.REVOKED.value, (
        f"the revocation is recorded on the row, got {revoked['status']}"
    )
    after_revoke = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert after_revoke["reserved_slot_count"] == before["reserved_slot_count"], (
        "revoking releases exactly the one slot the approval took, so the count returns to "
        f"{before['reserved_slot_count']}, got {after_revoke['reserved_slot_count']}"
    )
    assert after_revoke["version"] > after_approve["version"], (
        "the count returns but the version only moves forward; was "
        f"{after_approve['version']}, now {after_revoke['version']}"
    )


def test_flying_the_authorization_to_consumption_releases_the_same_slot(api, airspace_authority):
    """PRD §3.4: "Launch moves the authorization from `APPROVED` to `ACTIVE`, admissible only while `window_start` is at or before the current instant and the current instant is strictly before `window_end`; slot occupancy is unchanged, because `APPROVED` and `ACTIVE` both hold a slot."
    PRD §3.4: "Completing the flight moves it from `ACTIVE` to `CONSUMED` and releases the slot, decrementing `reserved_slot_count` and incrementing the zone's `version`."
    PRD §3.7: "The service writes all four fields, then computes `logged_minutes` as the whole minutes between `actual_start` and `actual_end`, discarding any part-minute remainder, and computes `altitude_exceedance` as true exactly when `max_altitude_reached_ft` is strictly greater than the flight's effective ceiling — the cited authorization's `granted_ceiling_ft` when the flight names one, and 400 feet otherwise."

    Design: Difficulty/compensating_invariant/zone_slot_conservation_under_revoke_and_under_consume
    """
    pilot, aircraft, zone, _first, second = _conservation_scenario(api)
    pilot_headers = make_pilot_headers(pilot["id"])

    approved = validate_success(
        api.decide_authorization(
            second["id"], factories.approve_authorization_payload(), headers=airspace_authority
        )
    )
    after_approve = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert after_approve["reserved_slot_count"] == 1, (
        f"approval takes one slot, got {after_approve['reserved_slot_count']}"
    )

    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T09:30:00Z",
        "2026-08-20T10:30:00Z",
        operation_category=OperatorCategory.COMMERCIAL.value,
        planned_max_altitude_ft=380,
        authorization_id=approved["id"],
    )
    check = fixtures.clear_flight_for_launch(api, flight)
    assert check["result"] == "PASSED", (
        f"the pre-flight sweep must clear the flight, findings {check['blocking_findings']}"
    )

    set_clock(api, "2026-08-20T09:30:00Z", headers=COMPLIANCE_OFFICER)
    launched = validate_success(api.launch_flight(flight["id"], headers=pilot_headers))
    assert launched["status"] == FlightStatus.IN_PROGRESS.value, (
        f"a cleared flight inside its window launches, got {launched['status']}"
    )
    in_flight_authorization = validate_success(
        api.get_authorization(approved["id"], headers=airspace_authority)
    )
    assert in_flight_authorization["status"] == AuthorizationStatus.ACTIVE.value, (
        f"launching moves the authorization to ACTIVE, got {in_flight_authorization['status']}"
    )
    in_flight_zone = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert in_flight_zone["reserved_slot_count"] == 1, (
        "an ACTIVE authorization still occupies its slot, so the transition must not decrement; "
        f"got {in_flight_zone['reserved_slot_count']}"
    )

    completed = validate_success(
        api.complete_flight(
            flight["id"],
            factories.completion_payload(
                "2026-08-20T10:30:00Z", max_altitude_reached_ft=375, incident_occurred=False
            ),
            headers=pilot_headers,
        )
    )
    assert completed["status"] == FlightStatus.COMPLETED.value, (
        f"the flight completes, got {completed['status']}"
    )
    assert completed["logged_minutes"] == 60, (
        "the whole minutes between 09:30 and 10:30 are 60, got "
        f"{completed['logged_minutes']}"
    )
    assert completed["altitude_exceedance"] is False, (
        "375 ft is inside the 400 ft granted ceiling, got "
        f"{completed['altitude_exceedance']!r}"
    )
    consumed = validate_success(api.get_authorization(approved["id"], headers=airspace_authority))
    assert consumed["status"] == AuthorizationStatus.CONSUMED.value, (
        f"completion consumes the authorization, got {consumed['status']}"
    )
    final_zone = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert final_zone["reserved_slot_count"] == 0, (
        "the second compensating path releases the same single slot, got "
        f"{final_zone['reserved_slot_count']}"
    )
    assert final_zone["version"] > in_flight_zone["version"], (
        "consumption advances the zone version; was "
        f"{in_flight_zone['version']}, now {final_zone['version']}"
    )


def test_a_second_revocation_cannot_drive_the_slot_count_negative(api, airspace_authority):
    """PRD §2.10: "The count is never negative."
    PRD §2.10: "Approval is the only action that adds a slot, and each approval is undone by exactly one of three mutually exclusive terminations of the same row — revocation, consumption at flight completion, or expiry when the window closes — never by two of them."
    PRD §2.11: "13. **Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."

    Design: Difficulty/compensating_invariant/zone_slot_conservation_under_revoke_and_under_consume
    """
    _pilot, _aircraft, zone, first, _second = _conservation_scenario(api)

    validate_success(
        api.decide_authorization(
            first["id"], factories.approve_authorization_payload(), headers=airspace_authority
        )
    )
    validate_success(
        api.revoke_authorization(
            first["id"], factories.revoke_authorization_payload(), headers=airspace_authority
        )
    )
    after_first_revoke = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert after_first_revoke["reserved_slot_count"] == 0, (
        f"the one approval is undone once, got {after_first_revoke['reserved_slot_count']}"
    )

    response = api.revoke_authorization(
        first["id"], factories.revoke_authorization_payload(), headers=airspace_authority
    )
    validate_error(response, ApiErrorId.AUTHORIZATION_INVALID_STATE, 409)

    after_second_revoke = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert after_second_revoke["reserved_slot_count"] == 0, (
        "a refused second revocation releases nothing a second time, got "
        f"{after_second_revoke['reserved_slot_count']}"
    )
    still_revoked = validate_success(api.get_authorization(first["id"], headers=airspace_authority))
    assert still_revoked["status"] == AuthorizationStatus.REVOKED.value, (
        f"the row stays revoked, got {still_revoked['status']}"
    )


FIRST_WINDOW = ("2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
SECOND_WINDOW = ("2026-08-11T08:00:00Z", "2026-08-11T10:00:00Z")


def _zone_version_scenario(api):
    """A certified recreational pilot over a three-slot class D zone, so capacity
    can never be the reason a request is refused."""
    set_clock(api, SETUP_INSTANT, headers=COMPLIANCE_OFFICER)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.RECREATIONAL.value, scheduled_at=SETUP_INSTANT
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = fixtures.create_controlled_zone(
        api,
        class_code=ZoneClassCode.D.value,
        class_ceiling_ft=700,
        max_concurrent_authorizations=3,
    )
    return pilot, aircraft, zone


def test_request_replayed_on_the_pre_approval_zone_version_is_refused(api, airspace_authority):
    """PRD §2.7: "If it does not equal the zone's current `version`, the request is rejected with `ERR_STALE_ZONE_VERSION` (HTTP 412)."
    PRD §2.7: "Because approvals, revocations, expiries and consumptions all bump the zone, a client that wants to lodge a request must read the zone immediately beforehand."
    PRD §3.4: "The request is created in `REQUESTED` with `granted_ceiling_ft`, `approved_by_user_id`, `decided_at` and `denial_reason` all null, and — this is the point of the design — **no slot is reserved at request time**."

    Design: Corner/cross_cutting_complexity_layers/zone_version_gate_refuses_the_stale_request_and_accepts_the_refreshed_one
    """
    pilot, aircraft, zone = _zone_version_scenario(api)
    pilot_headers = make_pilot_headers(pilot["id"])
    stale_version = zone["version"]

    lodged = validate_success(
        api.create_authorization(
            factories.authorization_payload(
                pilot["id"],
                aircraft["id"],
                zone["id"],
                stale_version,
                FIRST_WINDOW[0],
                FIRST_WINDOW[1],
            ),
            headers=pilot_headers,
        ),
        201,
    )
    assert lodged["status"] == AuthorizationStatus.REQUESTED.value, (
        f"the first request is lodged, got {lodged['status']}"
    )
    after_lodge = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert after_lodge["reserved_slot_count"] == 0, (
        "lodging a request reserves nothing, got "
        f"{after_lodge['reserved_slot_count']}"
    )

    validate_success(
        api.decide_authorization(
            lodged["id"], factories.approve_authorization_payload(), headers=airspace_authority
        )
    )
    after_approve = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert after_approve["version"] > stale_version, (
        f"the approval advanced the zone version past {stale_version}, got "
        f"{after_approve['version']}"
    )

    response = api.create_authorization(
        factories.authorization_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            stale_version,
            SECOND_WINDOW[0],
            SECOND_WINDOW[1],
        ),
        headers=pilot_headers,
    )
    validate_error(response, ApiErrorId.STALE_ZONE_VERSION, 412)

    _records, meta = validate_paginated(
        api.list_authorizations(params={"zone_id": zone["id"]}, headers=airspace_authority)
    )
    assert meta["total_count"] == 1, (
        f"the refused replay left no row behind, list reports {meta['total_count']}"
    )
    unchanged = assert_zone_slot_conservation(api, zone["id"], airspace_authority)
    assert unchanged["version"] == after_approve["version"], (
        f"the refused request bumped nothing; was {after_approve['version']}, now "
        f"{unchanged['version']}"
    )
    assert unchanged["reserved_slot_count"] == 1, (
        "only the approval holds a slot, got "
        f"{unchanged['reserved_slot_count']}"
    )


def test_the_same_request_body_succeeds_once_the_zone_is_re_read(api, airspace_authority):
    """PRD §2.7: "The request body must carry `expected_zone_version` — the field is required, not optional — holding the `version` the client last read from that zone."
    PRD §2.11: "11. **Zone optimistic concurrency**, on `POST /drone-ops/airspace-authorizations` only: `expected_zone_version` equals the zone's current `version` — otherwise `ERR_STALE_ZONE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/zone_version_gate_refuses_the_stale_request_and_accepts_the_refreshed_one
    """
    pilot, aircraft, zone = _zone_version_scenario(api)
    pilot_headers = make_pilot_headers(pilot["id"])
    stale_version = zone["version"]

    lodged = fixtures.create_requested_authorization(
        api, pilot["id"], aircraft["id"], zone["id"], FIRST_WINDOW[0], FIRST_WINDOW[1]
    )
    validate_success(
        api.decide_authorization(
            lodged["id"], factories.approve_authorization_payload(), headers=airspace_authority
        )
    )

    stale_body = factories.authorization_payload(
        pilot["id"],
        aircraft["id"],
        zone["id"],
        stale_version,
        SECOND_WINDOW[0],
        SECOND_WINDOW[1],
    )
    validate_error(
        api.create_authorization(stale_body, headers=pilot_headers),
        ApiErrorId.STALE_ZONE_VERSION,
        412,
    )

    refreshed = fixtures.read_zone(api, zone["id"], headers=airspace_authority)
    refreshed_body = dict(stale_body, expected_zone_version=refreshed["version"])
    accepted = validate_success(
        api.create_authorization(refreshed_body, headers=pilot_headers), 201
    )

    assert accepted["status"] == AuthorizationStatus.REQUESTED.value, (
        f"the identical body succeeds on the refreshed version, got {accepted['status']}"
    )
    assert accepted["requested_ceiling_ft"] == stale_body["requested_ceiling_ft"], (
        "the accepted request keeps the ceiling the refused one asked for, got "
        f"{accepted['requested_ceiling_ft']}"
    )
    assert_instant_equals(accepted["window_start"], SECOND_WINDOW[0], "window_start")
    assert_instant_equals(accepted["window_end"], SECOND_WINDOW[1], "window_end")
    _records, meta = validate_paginated(
        api.list_authorizations(params={"zone_id": zone["id"]}, headers=airspace_authority)
    )
    assert meta["total_count"] == 2, (
        f"exactly the two accepted requests exist, list reports {meta['total_count']}"
    )


def _waiver_applicant_scenario(api):
    """A certified recreational pilot with one registered airframe, ready to file
    special-operation applications."""
    set_clock(api, SETUP_INSTANT, headers=COMPLIANCE_OFFICER)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.RECREATIONAL.value, scheduled_at=SETUP_INSTANT
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    return pilot, aircraft


def test_second_application_on_the_pre_lodge_pilot_version_is_refused(api, compliance_officer):
    """PRD §2.7: "A value that does not equal the pilot's current `version` is rejected with `ERR_STALE_PILOT_VERSION` (HTTP 412)."
    PRD §3.5: "Either way the pilot's `open_waiver_count` is recomputed and the pilot's `version` is incremented, which is what makes the echoed `expected_pilot_version` go stale for any concurrent caller."
    PRD §3.5: "`open_waiver_count` is always the count of that pilot's waivers whose `status` is one of `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `CLEARED` or `APPROVED` — note that `APPROVED` counts as open, so a decision that approves does not reduce the count while a decision that denies does."

    Design: Corner/cross_cutting_complexity_layers/pilot_version_gate_guards_the_waiver_supersede_path
    """
    pilot, aircraft = _waiver_applicant_scenario(api)
    pilot_headers = make_pilot_headers(pilot["id"])
    before = fixtures.read_pilot(api, pilot["id"], headers=compliance_officer)

    night = validate_success(
        api.create_waiver(
            factories.waiver_payload(
                pilot["id"],
                aircraft["id"],
                before["version"],
                WaiverType.NIGHT.value,
                requested_ceiling_ft=400,
            ),
            headers=pilot_headers,
        ),
        201,
    )
    assert night["status"] == WaiverStatus.DRAFT.value, (
        f"the application opens in DRAFT, got {night['status']}"
    )

    stale_body = factories.waiver_payload(
        pilot["id"],
        aircraft["id"],
        before["version"],
        WaiverType.BVLOS.value,
        requested_ceiling_ft=400,
    )
    validate_error(
        api.create_waiver(stale_body, headers=pilot_headers),
        ApiErrorId.STALE_PILOT_VERSION,
        412,
    )

    after = fixtures.read_pilot(api, pilot["id"], headers=compliance_officer)
    assert after["version"] > before["version"], (
        f"lodging an application advances the pilot version past {before['version']}, got "
        f"{after['version']}"
    )
    assert after["open_waiver_count"] == before["open_waiver_count"] + 1, (
        "the DRAFT application is what the stale view was missing, expected "
        f"{before['open_waiver_count'] + 1}, got {after['open_waiver_count']}"
    )

    accepted = validate_success(
        api.create_waiver(
            dict(stale_body, expected_pilot_version=after["version"]), headers=pilot_headers
        ),
        201,
    )
    assert accepted["status"] == WaiverStatus.DRAFT.value, (
        f"the identical body is accepted on the refreshed version, got {accepted['status']}"
    )
    _records, meta = validate_paginated(
        api.list_waivers(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 2, (
        f"the refused replay left no row behind, list reports {meta['total_count']}"
    )


def test_supersede_replayed_on_the_pre_approval_pilot_version_is_refused(
    api, compliance_officer, safety_reviewer, waiver_approver
):
    """PRD §2.7: "Here the stale read is dangerous because creating a waiver of a `waiver_type` the pilot already holds silently supersedes the prior `APPROVED` waiver of that type; a client working from a stale pilot has an out-of-date view of `open_waiver_count` and of which waiver it is about to displace."
    PRD §2.11: "12. **Pilot optimistic concurrency**, on `POST /drone-ops/waivers` only: `expected_pilot_version` equals the pilot's current `version` — otherwise `ERR_STALE_PILOT_VERSION` (412)."
    PRD §3.5: "Sum the `ground_risk_class`, the air-risk index and the uplift, and cap the total at 6 — the result is the `sail_level`, always an integer from 1 to 6."

    Design: Corner/cross_cutting_complexity_layers/pilot_version_gate_guards_the_waiver_supersede_path
    """
    pilot, aircraft = _waiver_applicant_scenario(api)
    pilot_headers = make_pilot_headers(pilot["id"])

    night = fixtures.create_draft_waiver(
        api, pilot["id"], aircraft["id"], WaiverType.NIGHT.value, requested_ceiling_ft=400
    )
    case = fixtures.attach_safety_case(
        api, night, ground_risk_class=2, air_risk_class=AirRiskClass.ARC_B.value
    )
    assert case["sail_level"] == 3, (
        "ground risk 2 plus the ARC_B index 1 plus no beyond-line-of-sight uplift is 3, got "
        f"{case['sail_level']}"
    )
    pre_approval = fixtures.read_pilot(api, pilot["id"], headers=compliance_officer)

    validate_success(api.submit_waiver(night["id"], headers=pilot_headers))
    validate_success(api.begin_waiver_review(night["id"], headers=safety_reviewer))
    validate_success(
        api.clear_waiver_safety_case(
            night["id"], factories.clear_safety_case_payload(), headers=safety_reviewer
        )
    )
    approved = validate_success(
        api.decide_waiver(
            night["id"], factories.approve_waiver_payload(400), headers=waiver_approver
        )
    )
    assert approved["status"] == WaiverStatus.APPROVED.value, (
        f"the review chain runs to approval, got {approved['status']}"
    )

    response = api.create_waiver(
        factories.waiver_payload(
            pilot["id"],
            aircraft["id"],
            pre_approval["version"],
            WaiverType.NIGHT.value,
            requested_ceiling_ft=400,
        ),
        headers=pilot_headers,
    )
    validate_error(response, ApiErrorId.STALE_PILOT_VERSION, 412)

    survivor = validate_success(api.get_waiver(night["id"], headers=compliance_officer))
    assert survivor["status"] == WaiverStatus.APPROVED.value, (
        "a replay on the pre-approval version cannot retire the live approval, got "
        f"{survivor['status']}"
    )
    _records, meta = validate_paginated(
        api.list_waivers(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 1, (
        f"the refused application left no row behind, list reports {meta['total_count']}"
    )


def test_refreshed_pilot_version_performs_the_supersede(api, compliance_officer):
    """PRD §3.5: "Creation also supersedes: if the pilot already holds a waiver in `APPROVED` of the *same* `waiver_type`, that older waiver is moved to `SUPERSEDED`."
    PRD §3.5: "Either outcome recomputes `open_waiver_count` and increments the pilot's `version`."

    Design: Corner/cross_cutting_complexity_layers/pilot_version_gate_guards_the_waiver_supersede_path
    """
    pilot, aircraft = _waiver_applicant_scenario(api)
    approved = fixtures.create_approved_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.NIGHT.value,
        requested_ceiling_ft=400,
        granted_ceiling_ft=400,
        ground_risk_class=2,
        air_risk_class=AirRiskClass.ARC_B.value,
    )
    refreshed = fixtures.read_pilot(api, pilot["id"], headers=compliance_officer)

    replacement = validate_success(
        api.create_waiver(
            factories.waiver_payload(
                pilot["id"],
                aircraft["id"],
                refreshed["version"],
                WaiverType.NIGHT.value,
                requested_ceiling_ft=400,
            ),
            headers=make_pilot_headers(pilot["id"]),
        ),
        201,
    )
    assert replacement["status"] == WaiverStatus.DRAFT.value, (
        f"the refreshed application opens in DRAFT, got {replacement['status']}"
    )

    displaced = validate_success(api.get_waiver(approved["id"], headers=compliance_officer))
    assert displaced["status"] == WaiverStatus.SUPERSEDED.value, (
        "a second application of the same type retires the earlier approval, got "
        f"{displaced['status']}"
    )
    after = fixtures.read_pilot(api, pilot["id"], headers=compliance_officer)
    assert after["version"] > refreshed["version"], (
        f"the supersede advances the pilot version past {refreshed['version']}, got "
        f"{after['version']}"
    )
    assert after["open_waiver_count"] == 1, (
        "only the new DRAFT is open once the earlier approval is superseded, got "
        f"{after['open_waiver_count']}"
    )
    _records, meta = validate_paginated(
        api.list_waivers(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert meta["total_count"] == 2, (
        f"both the superseded and the new application are stored, list reports {meta['total_count']}"
    )


INCIDENT_FLIGHT_END = "2026-08-20T09:50:00Z"


def _incident_flight_scenario(api):
    """A commercial flight over uncontrolled airspace, completed with an incident
    at 09:50 and not yet reported."""
    set_clock(api, SETUP_INSTANT, headers=COMPLIANCE_OFFICER)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=SETUP_INSTANT
    )
    policy = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from=SETUP_INSTANT,
        effective_until=POLICY_END,
        coverage_limit_cents=2000000,
        deductible_cents=0,
    )
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
    pilot_headers = make_pilot_headers(pilot["id"])
    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T10:00:00Z",
        operation_category=OperatorCategory.COMMERCIAL.value,
        planned_max_altitude_ft=380,
    )
    assert flight["covering_policy_id"] == policy["id"], (
        "the only candidate policy must be selected as cover, got "
        f"{flight['covering_policy_id']}"
    )
    set_clock(api, "2026-08-20T09:00:00Z", headers=COMPLIANCE_OFFICER)
    check = fixtures.clear_flight_for_launch(api, flight)
    assert check["result"] == "PASSED", (
        f"the pre-flight sweep must clear the flight, findings {check['blocking_findings']}"
    )
    validate_success(api.launch_flight(flight["id"], headers=pilot_headers))
    set_clock(api, INCIDENT_FLIGHT_END, headers=COMPLIANCE_OFFICER)
    completed = validate_success(
        api.complete_flight(
            flight["id"],
            factories.completion_payload(
                INCIDENT_FLIGHT_END,
                max_altitude_reached_ft=370,
                incident_occurred=True,
                incident_summary="Rotor arm cracked on a hard landing.",
            ),
            headers=pilot_headers,
        )
    )
    assert completed["status"] == FlightStatus.COMPLETED.value, (
        f"the flight completes, got {completed['status']}"
    )
    assert completed["logged_minutes"] == 50, (
        f"the whole minutes between 09:00 and 09:50 are 50, got {completed['logged_minutes']}"
    )
    assert completed["investigation_status"] == InvestigationStatus.NONE.value, (
        "the investigation dimension is untouched until a report exists, got "
        f"{completed['investigation_status']}"
    )
    return pilot, policy, completed


def test_filing_writes_the_reserve_that_the_next_policy_read_reports(api, compliance_officer):
    """PRD §3.8: "Multiply the `reported_property_damage_cents` by 1.25 and round half-up to whole cents, then add the injury reserve; that sum is the raw reserve."
    PRD §3.8: "The report's `reserved_cents` is the lesser of the policy's `remaining_coverage_cents` and that raw reserve — so a reserve can never exceed the cover actually left."
    PRD §2.10: "A policy's `coverage_limit_cents` must at all times equal the sum of its `remaining_coverage_cents`, its `open_reserved_cents_total` and its `settled_cents_total`, where `open_reserved_cents_total` is the sum of `reserved_cents` over the accident reports against that policy whose `status` is `FILED`, `INVESTIGATING` or `REMEDIATION_REQUIRED`, and `settled_cents_total` is the sum of `settlement_cents` over the reports against that policy whose `status` is `CLOSED`."

    Design: Corner/consistency_model/every_derived_value_is_readable_on_the_request_that_follows_the_write
    """
    _pilot, policy, flight = _incident_flight_scenario(api)

    report = fixtures.create_filed_report(
        api,
        flight,
        occurred_at="2026-08-20T09:48:00Z",
        injury_level="NONE",
        reported_property_damage_cents=100000,
    )

    assert report["status"] == ReportStatus.FILED.value, (
        f"the report opens in FILED, got {report['status']}"
    )
    assert report["policy_id"] == policy["id"], (
        f"the flight's cover is copied onto the report, got {report['policy_id']}"
    )
    assert report["reserved_cents"] == 125000, (
        "100000 cents of damage at 1.25 with no injury reserve is 125000 cents, got "
        f"{report['reserved_cents']}"
    )

    ledger = assert_coverage_ledger_conservation(api, policy["id"], compliance_officer)
    assert ledger["open_reserved_cents_total"] == report["reserved_cents"], (
        "the read that follows the write reports exactly the reserve the write returned, "
        f"expected {report['reserved_cents']}, got {ledger['open_reserved_cents_total']}"
    )
    assert ledger["settled_cents_total"] == 0, (
        f"nothing is settled yet, got {ledger['settled_cents_total']}"
    )
    assert ledger["remaining_coverage_cents"] == 1875000, (
        f"2000000 less the 125000 hold leaves 1875000, got {ledger['remaining_coverage_cents']}"
    )
    assert ledger["coverage_status"] == "ACTIVE", (
        f"1875000 cents of cover keeps the policy active, got {ledger['coverage_status']}"
    )


def test_filing_opens_the_parallel_dimension_and_is_queryable_at_once(api, compliance_officer):
    """PRD §3.8: "The flight's `investigation_status` is a genuinely parallel dimension: filing moves it from `NONE` to `OPEN` and closure or withdrawal moves it from `OPEN` to `CLOSED`, and **neither ever touches the flight's operational `status`**."
    PRD §3.8: "Its `policy_id` is **copied** from the flight's `covering_policy_id` at filing and is null when the flight had no covering policy; the copy is deliberate, so that later reselection on the flight cannot move an accident's cover."

    Design: Corner/consistency_model/every_derived_value_is_readable_on_the_request_that_follows_the_write
    """
    _pilot, policy, flight = _incident_flight_scenario(api)

    report = fixtures.create_filed_report(
        api,
        flight,
        occurred_at="2026-08-20T09:48:00Z",
        injury_level="NONE",
        reported_property_damage_cents=100000,
    )

    reread = validate_success(api.get_flight(flight["id"], headers=compliance_officer))
    assert reread["investigation_status"] == InvestigationStatus.OPEN.value, (
        f"filing opens the investigation dimension, got {reread['investigation_status']}"
    )
    assert reread["status"] == FlightStatus.COMPLETED.value, (
        f"the operational status is untouched, got {reread['status']}"
    )

    response = api.list_accident_reports(
        params={"policy_id": policy["id"]}, headers=compliance_officer
    )
    _records, meta = validate_paginated(response)
    assert meta["total_count"] == 1, (
        f"the propagated policy_id is queryable at once, list reports {meta['total_count']}"
    )
    assert paginated_ids(response) == [report["id"]], (
        f"the filtered list returns exactly the filed report, got {paginated_ids(response)}"
    )


def test_the_pilot_projection_agrees_with_the_stored_expiry_at_once(api, compliance_officer):
    """PRD §3.9: "Then take the raw score as 25 times the incident count, plus 15 times the exceedance count, plus 30 times the open-accident count, plus a lapsed-currency term of 10 when the pilot's `status` is `LAPSED` and 0 otherwise, minus 5 times the clean-flight count."
    PRD §3.2: "The **recency expiry** is a recency anchor advanced by 90 days, where the recency anchor is the pilot's `last_completed_flight_end` when the pilot has ever completed a flight, and the certificate's `issued_at` when they have not."
    PRD §3.2: "Under `COMMERCIAL_BASIS`, which applies whenever the `operator_category` is `COMMERCIAL`, both constraints bite and the earlier of the two wins: the projected expiry is the base expiry when the base expiry is the earlier instant, and the recency expiry otherwise."

    Design: Corner/consistency_model/every_derived_value_is_readable_on_the_request_that_follows_the_write
    """
    pilot, _policy, flight = _incident_flight_scenario(api)

    fixtures.create_filed_report(
        api,
        flight,
        occurred_at="2026-08-20T09:48:00Z",
        injury_level="NONE",
        reported_property_damage_cents=100000,
    )

    reread = fixtures.read_pilot(api, pilot["id"], headers=compliance_officer)
    assert reread["risk_score"] == 55, (
        "one incident flight weighs 25 and one open accident weighs 30, with no clean flight to "
        f"decay the score; expected 55, got {reread['risk_score']}"
    )
    assert_instant_equals(
        reread["last_completed_flight_end"], INCIDENT_FLIGHT_END, "last_completed_flight_end"
    )

    projection = validate_success(
        api.get_currency_projection(pilot["id"], headers=compliance_officer)
    )
    assert projection["basis_applied"] == CurrencyBasis.COMMERCIAL_BASIS.value, (
        f"a commercial operator is projected on the commercial basis, got "
        f"{projection['basis_applied']}"
    )
    assert_instant_equals(
        projection["projected_expires_at"],
        shift_days(INCIDENT_FLIGHT_END, 90),
        "projected_expires_at",
    )
    assert_instant_equals(
        projection["projected_expires_at"],
        reread["currency_expires_at"],
        "the projection against the stored expiry",
    )


PARTIAL_RESTRICTION_WINDOW = ("2026-08-10T08:00:00Z", "2026-08-10T20:00:00Z")
TOTAL_BAN_WINDOW = ("2026-08-11T08:00:00Z", "2026-08-11T20:00:00Z")
PARTIAL_RESTRICTION_REASON = "Presidential movement."


def _two_restriction_scenario(api):
    """A partial restriction over an uncontrolled zone and, published second, a
    total ban over a controlled one."""
    set_clock(api, SETUP_INSTANT, headers=COMPLIANCE_OFFICER)
    open_zone = fixtures.create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=400,
        requires_authorization=False,
        max_concurrent_authorizations=2,
    )
    controlled_zone = fixtures.create_controlled_zone(
        api,
        class_code=ZoneClassCode.D.value,
        class_ceiling_ft=500,
        max_concurrent_authorizations=2,
    )
    partial = fixtures.create_tfr(
        api,
        open_zone["id"],
        PARTIAL_RESTRICTION_WINDOW[0],
        PARTIAL_RESTRICTION_WINDOW[1],
        max_permitted_altitude_ft=100,
        reason=PARTIAL_RESTRICTION_REASON,
    )
    total_ban = fixtures.create_tfr(
        api,
        controlled_zone["id"],
        TOTAL_BAN_WINDOW[0],
        TOTAL_BAN_WINDOW[1],
        reason="Air show rehearsal.",
    )
    return open_zone, partial, total_ban


def test_published_restriction_reads_back_with_its_cap_and_publisher(api, compliance_officer):
    """PRD §3.4: "A restriction is created in `ACTIVE` with `published_by_user_id` set to the publishing operator's `X-User-ID`."
    PRD §3.4: "The distinction the optional field draws is the important one: a restriction that names a `max_permitted_altitude_ft` is a partial restriction — flying below that altitude remains permitted once the pilot has acknowledged the restriction — whereas **omitting** it (leaving it null) declares a total ban that no acknowledgement can ever clear."
    PRD §2.1: "The server does record it where a transition says so — `AirspaceAuthorization.approved_by_user_id`, `Waiver.approved_by_user_id`, `SafetyCase.cleared_by_user_id`, `AccidentReport.closed_by_user_id` and `TemporaryFlightRestriction.published_by_user_id` all hold the `X-User-ID` of the operator who performed the step — but those recorded values exist to support segregation of duties, not ownership."

    Design: Corner/endpoints/restriction_create_read_and_filtered_list_round_trip
    """
    open_zone, partial, total_ban = _two_restriction_scenario(api)

    assert_tfr(
        partial,
        zone_id=open_zone["id"],
        reason=PARTIAL_RESTRICTION_REASON,
        status=RestrictionStatus.ACTIVE.value,
        max_permitted_altitude_ft=100,
        published_by_user_id=AIRSPACE_AUTHORITY_ID,
    )
    assert total_ban["max_permitted_altitude_ft"] is None, (
        "a restriction published without an altitude cap is a total ban, got "
        f"{total_ban['max_permitted_altitude_ft']}"
    )

    reread = validate_success(api.get_tfr(partial["id"], headers=compliance_officer))
    assert reread["reason"] == PARTIAL_RESTRICTION_REASON, (
        f"the read echoes the stored reason, got {reread['reason']}"
    )
    assert reread["zone_id"] == open_zone["id"], (
        f"the read echoes the stored zone, got {reread['zone_id']}"
    )
    assert_instant_equals(
        reread["effective_from"], PARTIAL_RESTRICTION_WINDOW[0], "effective_from"
    )
    assert_instant_equals(
        reread["effective_until"], PARTIAL_RESTRICTION_WINDOW[1], "effective_until"
    )


def test_each_declared_restriction_filter_narrows_before_the_page_is_cut(api, airspace_authority):
    """PRD §2.3: "Filters offered on a list endpoint narrow the result set before pagination is applied."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` is true exactly when records remain beyond the current window."
    PRD §2.3: "Every other collection — knowledge tests, certifications, airframes, broadcast modules, airspace zones, temporary flight restrictions, airspace authorizations, waivers, safety cases, insurance policies, flights, pre-flight checks and accident reports — is `created_at` ascending."

    Design: Corner/endpoints/restriction_create_read_and_filtered_list_round_trip
    """
    open_zone, partial, _total_ban = _two_restriction_scenario(api)

    by_zone = api.list_tfrs(params={"zone_id": open_zone["id"]}, headers=airspace_authority)
    _rows, zone_meta = validate_paginated(by_zone)
    assert zone_meta["total_count"] == 1, (
        f"the restriction over the other zone is excluded, got {zone_meta['total_count']}"
    )
    assert paginated_ids(by_zone) == [partial["id"]], (
        f"only the restriction over the named zone is listed, got {paginated_ids(by_zone)}"
    )

    first_page = api.list_tfrs(
        params={"status": RestrictionStatus.ACTIVE.value, "limit": 1, "offset": 0},
        headers=airspace_authority,
    )
    page_rows, page_meta = validate_paginated(first_page)
    assert len(page_rows) == 1, f"a limit of 1 cuts the page to one row, got {len(page_rows)}"
    assert_pagination_meta(page_meta, 1, 0, 2)
    assert page_meta["has_more"] is True, (
        f"a second active restriction remains beyond the window, got {page_meta['has_more']}"
    )
    assert paginated_ids(first_page) == [partial["id"]], (
        "created_at ascending puts the earlier restriction first, got "
        f"{paginated_ids(first_page)}"
    )


def test_lifting_moves_the_restriction_between_the_two_status_pages(api, airspace_authority):
    """PRD §3.4: "The authority may lift an `ACTIVE` restriction ahead of its `effective_until`, moving it to `LIFTED`; and a restriction whose `effective_until` is at or before the current instant is lazily moved to `EXPIRED` when a preflight check or a launch reads it."
    PRD §2.3: "Filters offered on a list endpoint narrow the result set before pagination is applied."

    Design: Corner/endpoints/restriction_create_read_and_filtered_list_round_trip
    """
    _open_zone, partial, total_ban = _two_restriction_scenario(api)

    lifted = validate_success(api.lift_tfr(partial["id"], headers=airspace_authority))
    assert lifted["status"] == RestrictionStatus.LIFTED.value, (
        f"lifting an active restriction lands in LIFTED, got {lifted['status']}"
    )

    lifted_page = api.list_tfrs(
        params={"status": RestrictionStatus.LIFTED.value}, headers=airspace_authority
    )
    _lifted_rows, lifted_meta = validate_paginated(lifted_page)
    assert lifted_meta["total_count"] == 1, (
        f"exactly the lifted restriction answers the LIFTED filter, got {lifted_meta['total_count']}"
    )
    assert paginated_ids(lifted_page) == [partial["id"]], (
        f"the lifted restriction is the one listed, got {paginated_ids(lifted_page)}"
    )

    active_page = api.list_tfrs(
        params={"status": RestrictionStatus.ACTIVE.value}, headers=airspace_authority
    )
    _active_rows, active_meta = validate_paginated(active_page)
    assert active_meta["total_count"] == 1, (
        f"the lifted restriction has left the ACTIVE page, got {active_meta['total_count']}"
    )
    assert paginated_ids(active_page) == [total_ban["id"]], (
        f"only the untouched restriction is still active, got {paginated_ids(active_page)}"
    )
