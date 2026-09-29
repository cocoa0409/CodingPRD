"""Insurance cover, the covering-policy selector and the fiscal gates.

Covers the dependency an authorization request has on the state of the pilot's
policy row, the order in which the safety and fiscal refusals answer one request,
the inclusive one-million-cent coverage floor, the chain of three insurance
refusals as cover is filled in a layer at a time, the system-written link from a
flight to its covering policy and onward to an accident report, and the
selector's ranking, tie-break and expiry side effect.
"""

from test_helpers import (
    MIN_COMMERCIAL_COVERAGE_CENTS,
    ApiErrorId,
    AuthorizationStatus,
    Clock,
    CoverageStatus,
    FlightStatus,
    InjuryLevel,
    OperationCategory,
    OperatorCategory,
    PilotStatus,
    ReportStatus,
    assert_accident_report,
    assert_authorization,
    assert_coverage_ledger_conservation,
    assert_flight,
    assert_pilot,
    assert_policy,
    factories,
    fixtures,
    make_pilot_headers,
    parse_instant,
    shift_days,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_authorization_is_refused_while_the_policy_is_unverified(api, compliance_officer):
    """PRD §3.6: "Filing grants nothing: the policy is created in `PENDING_VERIFICATION` with all three ledger figures — `open_reserved_cents_total`, `settled_cents_total` and `remaining_coverage_cents` — at 0, so an unverified policy covers no flight even if its limit is enormous."
    PRD §2.11: "**Commercial insurance presence**, on `POST /drone-ops/flights` and `POST /drone-ops/airspace-authorizations`: the pilot holds a policy in `coverage_status` `ACTIVE` spanning the requested window — otherwise `ERR_INSURANCE_NOT_ACTIVE` (402). This rung is evaluated for commercial flights and for authorization requests lodged by pilots whose `operator_category` is `COMMERCIAL`."

    Design: Difficulty/cross_entity_state_dependency/authorization_request_depends_on_insurance_policy_state
    """
    clock = Clock(api)
    clock.set("2026-08-05T00:00:00Z")
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    assert_pilot(
        pilot,
        status=PilotStatus.CERTIFIED.value,
        operator_category=OperatorCategory.COMMERCIAL.value,
    )
    aircraft = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_controlled_zone(api)

    policy = fixtures.create_filed_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=5000000,
        deductible_cents=50000,
    )
    assert_policy(
        policy,
        coverage_status=CoverageStatus.PENDING_VERIFICATION.value,
        coverage_limit_cents=5000000,
        remaining_coverage_cents=0,
        open_reserved_cents_total=0,
        settled_cents_total=0,
    )

    refusal = api.create_authorization(
        factories.authorization_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            fixtures.zone_version(api, zone["id"]),
            "2026-08-20T09:00:00Z",
            "2026-08-20T11:00:00Z",
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(refusal, ApiErrorId.INSURANCE_NOT_ACTIVE.value, 402)

    rows, _ = validate_paginated(
        api.list_authorizations(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert rows == [], (
        f"a request refused on the insurance rung must leave no authorization row, got {rows}"
    )
    assert_policy(
        fixtures.read_policy(api, policy["id"]),
        coverage_status=CoverageStatus.PENDING_VERIFICATION.value,
        remaining_coverage_cents=0,
        version=1,
    )


def test_verifying_the_same_policy_active_admits_the_identical_request(api, compliance_officer):
    """PRD §3.6: "Activation opens the ledger: `remaining_coverage_cents` becomes `coverage_limit_cents` less `open_reserved_cents_total` less `settled_cents_total`, which for a fresh policy is the full limit."
    PRD §2.11: "**Commercial insurance presence**, on `POST /drone-ops/flights` and `POST /drone-ops/airspace-authorizations`: the pilot holds a policy in `coverage_status` `ACTIVE` spanning the requested window — otherwise `ERR_INSURANCE_NOT_ACTIVE` (402). This rung is evaluated for commercial flights and for authorization requests lodged by pilots whose `operator_category` is `COMMERCIAL`."
    PRD §3.4: "The request is created in `REQUESTED` with `granted_ceiling_ft`, `approved_by_user_id`, `decided_at` and `denial_reason` all null, and — this is the point of the design — **no slot is reserved at request time**."

    Design: Difficulty/cross_entity_state_dependency/authorization_request_depends_on_insurance_policy_state
    """
    clock = Clock(api)
    clock.set("2026-08-05T00:00:00Z")
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_controlled_zone(api)
    policy = fixtures.create_filed_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=5000000,
        deductible_cents=50000,
    )

    request_payload = factories.authorization_payload(
        pilot["id"],
        aircraft["id"],
        zone["id"],
        fixtures.zone_version(api, zone["id"]),
        "2026-08-20T09:00:00Z",
        "2026-08-20T11:00:00Z",
    )
    validate_error(
        api.create_authorization(request_payload, headers=make_pilot_headers(pilot["id"])),
        ApiErrorId.INSURANCE_NOT_ACTIVE.value,
        402,
    )

    activated = validate_success(
        api.verify_policy(
            policy["id"], factories.activate_policy_payload(), headers=compliance_officer
        )
    )
    assert_policy(
        activated,
        coverage_status=CoverageStatus.ACTIVE.value,
        remaining_coverage_cents=5000000,
        open_reserved_cents_total=0,
        settled_cents_total=0,
    )

    accepted = validate_success(
        api.create_authorization(request_payload, headers=make_pilot_headers(pilot["id"])), 201
    )
    assert_authorization(
        accepted,
        pilot_id=pilot["id"],
        aircraft_id=aircraft["id"],
        zone_id=zone["id"],
        status=AuthorizationStatus.REQUESTED.value,
        requested_ceiling_ft=400,
        window_start="2026-08-20T09:00:00Z",
        window_end="2026-08-20T11:00:00Z",
        granted_ceiling_ft=None,
        approved_by_user_id=None,
        decided_at=None,
        denial_reason=None,
    )
    assert fixtures.read_zone(api, zone["id"])["reserved_slot_count"] == 0, (
        "a request reserves no zone slot, so the count must still be 0"
    )


def test_currency_lapse_answers_before_the_insurance_gate_on_an_authorization(
    api, compliance_officer
):
    """PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "**Currency gate**, on `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/flights` and `POST /drone-ops/flights/{id}/launch`: the pilot's recomputed `currency_expires_at` is strictly after the current instant, and on flight creation strictly after the flight's `planned_end` as well. A `CERTIFIED` pilot found lapsed here is first transitioned to `LAPSED` and the call is then rejected with `ERR_PILOT_CURRENCY_LAPSED` (409)."
    PRD §2.11: "**Commercial insurance presence**, on `POST /drone-ops/flights` and `POST /drone-ops/airspace-authorizations`: the pilot holds a policy in `coverage_status` `ACTIVE` spanning the requested window — otherwise `ERR_INSURANCE_NOT_ACTIVE` (402). This rung is evaluated for commercial flights and for authorization requests lodged by pilots whose `operator_category` is `COMMERCIAL`."
    PRD §3.2: "The **recency expiry** is a recency anchor advanced by 90 days, where the recency anchor is the pilot's `last_completed_flight_end` when the pilot has ever completed a flight, and the certificate's `issued_at` when they have not."

    Design: Difficulty/priority_pair_validation_conflict/authorization_currency_safety_error_precedes_insurance_fiscal_error
    """
    clock = Clock(api)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    assert_pilot(pilot, status=PilotStatus.CERTIFIED.value)
    assert pilot["currency_expires_at"] == shift_days(pilot["certified_at"], 90), (
        "a commercial operator who has never flown is current only until 90 days past issuance, "
        f"got {pilot['currency_expires_at']} from certification at {pilot['certified_at']}"
    )
    aircraft = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_controlled_zone(api)

    policies, _ = validate_paginated(
        api.list_policies(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert policies == [], f"the pilot must start with no insurance cover at all, got {policies}"

    clock.set("2026-10-31T00:00:00Z")
    refusal = api.create_authorization(
        factories.authorization_payload(
            pilot["id"],
            aircraft["id"],
            zone["id"],
            fixtures.zone_version(api, zone["id"]),
            "2026-11-07T09:00:00Z",
            "2026-11-07T11:00:00Z",
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(refusal, ApiErrorId.PILOT_CURRENCY_LAPSED.value, 409)


def test_the_currency_refusal_demotes_the_pilot_and_leaves_the_policy_untouched(
    api, compliance_officer
):
    """PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "**Certification gate**, on `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/waivers/{id}/submit`, `POST /drone-ops/flights`, `POST /drone-ops/flights/{id}/launch` and `POST /drone-ops/airspace-authorizations/{id}/decide`: the pilot's `status` is `CERTIFIED` — otherwise `ERR_PILOT_NOT_CERTIFIED` (409)."
    PRD §2.11: "**Currency gate**, on `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/flights` and `POST /drone-ops/flights/{id}/launch`: the pilot's recomputed `currency_expires_at` is strictly after the current instant, and on flight creation strictly after the flight's `planned_end` as well. A `CERTIFIED` pilot found lapsed here is first transitioned to `LAPSED` and the call is then rejected with `ERR_PILOT_CURRENCY_LAPSED` (409)."
    PRD §3.6: "Filing grants nothing: the policy is created in `PENDING_VERIFICATION` with all three ledger figures — `open_reserved_cents_total`, `settled_cents_total` and `remaining_coverage_cents` — at 0, so an unverified policy covers no flight even if its limit is enormous."

    Design: Difficulty/priority_pair_validation_conflict/authorization_currency_safety_error_precedes_insurance_fiscal_error
    """
    clock = Clock(api)
    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_controlled_zone(api)
    policy = fixtures.create_filed_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=5000000,
        deductible_cents=50000,
    )

    clock.set("2026-10-31T00:00:00Z")
    request_payload = factories.authorization_payload(
        pilot["id"],
        aircraft["id"],
        zone["id"],
        fixtures.zone_version(api, zone["id"]),
        "2026-11-07T09:00:00Z",
        "2026-11-07T11:00:00Z",
    )
    validate_error(
        api.create_authorization(request_payload, headers=make_pilot_headers(pilot["id"])),
        ApiErrorId.PILOT_CURRENCY_LAPSED.value,
        409,
    )

    demoted = fixtures.read_pilot(api, pilot["id"])
    assert_pilot(demoted, status=PilotStatus.LAPSED.value)
    assert demoted["version"] > pilot["version"], (
        "the demotion to LAPSED is a mutation of the pilot row, so its version must advance, "
        f"got {demoted['version']} against {pilot['version']}"
    )
    assert_policy(
        fixtures.read_policy(api, policy["id"]),
        coverage_status=CoverageStatus.PENDING_VERIFICATION.value,
        remaining_coverage_cents=0,
        open_reserved_cents_total=0,
        settled_cents_total=0,
        version=1,
    )

    repeated = api.create_authorization(
        request_payload, headers=make_pilot_headers(pilot["id"])
    )
    validate_error(repeated, ApiErrorId.PILOT_NOT_CERTIFIED.value, 409)

    still_unverified, _ = validate_paginated(
        api.list_policies(
            params={"pilot_id": pilot["id"], "coverage_status": CoverageStatus.ACTIVE.value},
            headers=compliance_officer,
        )
    )
    assert still_unverified == [], (
        f"no policy was ever verified, so the ACTIVE filter must be empty, got {still_unverified}"
    )


def test_cover_eroded_to_exactly_the_commercial_floor_still_covers_a_new_flight(
    api, compliance_officer
):
    """PRD §3.6: "The selector runs over the flight's pilot's policies and keeps a policy as a candidate only when *all* of the following hold: its `coverage_status` is `ACTIVE`; its `indemnification_clause_accepted` is true; its `effective_from` is at or before the flight's `planned_start`; its `effective_until` is strictly after the flight's `planned_end`; and its `remaining_coverage_cents` is at least 1000000 cents."
    PRD §3.6: "When a filing pushes the recomputed `remaining_coverage_cents` below 1000000 cents, an `ACTIVE` policy moves to `INSUFFICIENT` and every commercial flight in `PLANNED` that named the policy as its cover is cancelled (§2.8)."
    PRD §3.8: "Multiply the `reported_property_damage_cents` by 1.25 and round half-up to whole cents, then add the injury reserve; that sum is the raw reserve."
    PRD §3.8: "The report's `reserved_cents` is the lesser of the policy's `remaining_coverage_cents` and that raw reserve — so a reserve can never exceed the cover actually left."

    Design: Corner/calculations/commercial_coverage_floor_is_inclusive_at_one_million_cents
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    first_airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    second_airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_zone(api)
    policy = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=2000000,
        deductible_cents=50000,
    )
    assert_policy(
        policy,
        coverage_status=CoverageStatus.ACTIVE.value,
        remaining_coverage_cents=2000000,
    )

    flying = fixtures.create_in_progress_flight(
        api,
        pilot["id"],
        first_airframe["id"],
        zone["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        operation_category=OperationCategory.COMMERCIAL.value,
    )
    assert_flight(
        flying,
        status=FlightStatus.IN_PROGRESS.value,
        covering_policy_id=policy["id"],
    )

    # A reported 800000 cents inflates by a quarter to exactly the one-million-cent floor.
    report = fixtures.create_filed_report(
        api,
        flying,
        occurred_at=flying["actual_start"],
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=800000,
    )
    assert_accident_report(
        report,
        policy_id=policy["id"],
        status=ReportStatus.FILED.value,
        reserved_cents=MIN_COMMERCIAL_COVERAGE_CENTS,
        remediation_round=0,
    )

    at_the_floor = fixtures.read_policy(api, policy["id"])
    assert_policy(
        at_the_floor,
        coverage_status=CoverageStatus.ACTIVE.value,
        remaining_coverage_cents=MIN_COMMERCIAL_COVERAGE_CENTS,
        open_reserved_cents_total=MIN_COMMERCIAL_COVERAGE_CENTS,
        settled_cents_total=0,
    )
    assert_coverage_ledger_conservation(api, policy["id"], compliance_officer)

    covered = fixtures.create_planned_flight(
        api,
        pilot["id"],
        second_airframe["id"],
        zone["id"],
        "2026-08-06T09:00:00Z",
        "2026-08-06T10:00:00Z",
        operation_category=OperationCategory.COMMERCIAL.value,
    )
    assert_flight(
        covered,
        status=FlightStatus.PLANNED.value,
        covering_policy_id=policy["id"],
    )


def test_cover_eroded_one_cent_below_the_floor_stops_covering_new_flights(
    api, compliance_officer
):
    """PRD §3.6: "When a filing pushes the recomputed `remaining_coverage_cents` below 1000000 cents, an `ACTIVE` policy moves to `INSUFFICIENT` and every commercial flight in `PLANNED` that named the policy as its cover is cancelled (§2.8)."
    PRD §3.6: "Policies in `PENDING_VERIFICATION`, `REJECTED`, `INSUFFICIENT` or `EXPIRED` are excluded outright, and any policy whose `effective_until` has already passed is first moved to `EXPIRED` and thereby drops out of the candidate set."
    PRD §3.6: "When no candidate survives, the flight is refused, and which of three errors is returned is pinned by the ladder of §2.11 rather than by the selector: `ERR_INSURANCE_NOT_ACTIVE` when the pilot has no `ACTIVE` policy at all; `ERR_INDEMNIFICATION_NOT_ACCEPTED` when an `ACTIVE` policy does cover the window but its `indemnification_clause_accepted` is false; and `ERR_INSURANCE_COVERAGE_INSUFFICIENT` when an `ACTIVE`, indemnified policy covers the window but its `remaining_coverage_cents` is below 1000000 cents."
    PRD §3.8: "Multiply the `reported_property_damage_cents` by 1.25 and round half-up to whole cents, then add the injury reserve; that sum is the raw reserve."

    Design: Corner/calculations/commercial_coverage_floor_is_inclusive_at_one_million_cents
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    first_airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    second_airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_zone(api)
    policy = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=2000000,
        deductible_cents=50000,
    )

    flying = fixtures.create_in_progress_flight(
        api,
        pilot["id"],
        first_airframe["id"],
        zone["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        operation_category=OperationCategory.COMMERCIAL.value,
    )

    # A reported 800001 cents inflates to 1000001, one cent past the floor.
    report = fixtures.create_filed_report(
        api,
        flying,
        occurred_at=flying["actual_start"],
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=800001,
    )
    assert_accident_report(
        report, policy_id=policy["id"], reserved_cents=MIN_COMMERCIAL_COVERAGE_CENTS + 1
    )

    below_the_floor = fixtures.read_policy(api, policy["id"])
    assert_policy(
        below_the_floor,
        coverage_status=CoverageStatus.INSUFFICIENT.value,
        remaining_coverage_cents=MIN_COMMERCIAL_COVERAGE_CENTS - 1,
        open_reserved_cents_total=MIN_COMMERCIAL_COVERAGE_CENTS + 1,
        settled_cents_total=0,
    )
    assert_coverage_ledger_conservation(api, policy["id"], compliance_officer)

    refusal = api.create_flight(
        factories.flight_payload(
            pilot["id"],
            second_airframe["id"],
            zone["id"],
            "2026-08-06T09:00:00Z",
            "2026-08-06T10:00:00Z",
            operation_category=OperationCategory.COMMERCIAL.value,
        ),
        headers=make_pilot_headers(pilot["id"]),
    )
    validate_error(refusal, ApiErrorId.INSURANCE_NOT_ACTIVE.value, 402)

    assert_flight(
        validate_success(
            api.get_flight(flying["id"], headers=make_pilot_headers(pilot["id"]))
        ),
        status=FlightStatus.IN_PROGRESS.value,
        covering_policy_id=policy["id"],
    )


def test_the_fiscal_gates_answer_in_ladder_order_as_cover_is_filled_in(api, compliance_officer):
    """PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "**Commercial insurance presence**, on `POST /drone-ops/flights` and `POST /drone-ops/airspace-authorizations`: the pilot holds a policy in `coverage_status` `ACTIVE` spanning the requested window — otherwise `ERR_INSURANCE_NOT_ACTIVE` (402). This rung is evaluated for commercial flights and for authorization requests lodged by pilots whose `operator_category` is `COMMERCIAL`."
    PRD §2.11: "**Client indemnification**, on `POST /drone-ops/flights` only: the covering policy's `indemnification_clause_accepted` is true — otherwise `ERR_INDEMNIFICATION_NOT_ACCEPTED` (422)."
    PRD §3.6: "When no candidate survives, the flight is refused, and which of three errors is returned is pinned by the ladder of §2.11 rather than by the selector: `ERR_INSURANCE_NOT_ACTIVE` when the pilot has no `ACTIVE` policy at all; `ERR_INDEMNIFICATION_NOT_ACCEPTED` when an `ACTIVE` policy does cover the window but its `indemnification_clause_accepted` is false; and `ERR_INSURANCE_COVERAGE_INSUFFICIENT` when an `ACTIVE`, indemnified policy covers the window but its `remaining_coverage_cents` is below 1000000 cents."

    Design: Corner/validations/fiscal_gates_answer_in_priority_order_as_each_is_satisfied
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_zone(api)
    flight_request = factories.flight_payload(
        pilot["id"],
        airframe["id"],
        zone["id"],
        "2026-08-10T09:00:00Z",
        "2026-08-10T10:00:00Z",
        operation_category=OperationCategory.COMMERCIAL.value,
    )

    validate_error(
        api.create_flight(flight_request, headers=make_pilot_headers(pilot["id"])),
        ApiErrorId.INSURANCE_NOT_ACTIVE.value,
        402,
    )

    unindemnified = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=5000000,
        deductible_cents=50000,
        indemnification_clause_accepted=False,
    )
    assert_policy(
        unindemnified,
        coverage_status=CoverageStatus.ACTIVE.value,
        indemnification_clause_accepted=False,
        remaining_coverage_cents=5000000,
    )
    validate_error(
        api.create_flight(flight_request, headers=make_pilot_headers(pilot["id"])),
        ApiErrorId.INDEMNIFICATION_NOT_ACCEPTED.value,
        422,
    )

    indemnified = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=3000000,
        deductible_cents=50000,
        indemnification_clause_accepted=True,
    )
    flight = validate_success(
        api.create_flight(flight_request, headers=make_pilot_headers(pilot["id"])), 201
    )
    assert_flight(
        flight,
        status=FlightStatus.PLANNED.value,
        operation_category=OperationCategory.COMMERCIAL.value,
        covering_policy_id=indemnified["id"],
    )
    assert flight["covering_policy_id"] != unindemnified["id"], (
        "the larger policy never accepted the indemnification clause, so it is not a candidate "
        "however much cover it carries"
    )

    rows, meta = validate_paginated(
        api.list_flights(params={"pilot_id": pilot["id"]}, headers=compliance_officer)
    )
    assert [row["id"] for row in rows] == [flight["id"]], (
        f"only the admitted request may have created a flight row, got {rows}"
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one flight row, got {meta['total_count']}"
    )


def test_the_presence_rung_answers_before_the_indemnification_rung(api, compliance_officer):
    """PRD §2.11: "The service evaluates checks in the fixed order below — a strictly lower rung always wins, and the first rung that fails determines both the `error_id` and the HTTP status."
    PRD §2.11: "**Commercial insurance presence**, on `POST /drone-ops/flights` and `POST /drone-ops/airspace-authorizations`: the pilot holds a policy in `coverage_status` `ACTIVE` spanning the requested window — otherwise `ERR_INSURANCE_NOT_ACTIVE` (402). This rung is evaluated for commercial flights and for authorization requests lodged by pilots whose `operator_category` is `COMMERCIAL`."
    PRD §2.11: "**Client indemnification**, on `POST /drone-ops/flights` only: the covering policy's `indemnification_clause_accepted` is true — otherwise `ERR_INDEMNIFICATION_NOT_ACCEPTED` (422)."
    PRD §3.6: "Filing grants nothing: the policy is created in `PENDING_VERIFICATION` with all three ledger figures — `open_reserved_cents_total`, `settled_cents_total` and `remaining_coverage_cents` — at 0, so an unverified policy covers no flight even if its limit is enormous."

    Design: Corner/validations/fiscal_gates_answer_in_priority_order_as_each_is_satisfied
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_zone(api)
    policy = fixtures.create_filed_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=5000000,
        deductible_cents=50000,
        indemnification_clause_accepted=False,
    )
    flight_request = factories.flight_payload(
        pilot["id"],
        airframe["id"],
        zone["id"],
        "2026-08-10T09:00:00Z",
        "2026-08-10T10:00:00Z",
        operation_category=OperationCategory.COMMERCIAL.value,
    )

    validate_error(
        api.create_flight(flight_request, headers=make_pilot_headers(pilot["id"])),
        ApiErrorId.INSURANCE_NOT_ACTIVE.value,
        402,
    )

    activated = validate_success(
        api.verify_policy(
            policy["id"], factories.activate_policy_payload(), headers=compliance_officer
        )
    )
    assert_policy(
        activated,
        coverage_status=CoverageStatus.ACTIVE.value,
        indemnification_clause_accepted=False,
        remaining_coverage_cents=5000000,
    )

    validate_error(
        api.create_flight(flight_request, headers=make_pilot_headers(pilot["id"])),
        ApiErrorId.INDEMNIFICATION_NOT_ACCEPTED.value,
        422,
    )


def test_the_covering_policy_link_is_queryable_from_the_flight_list(api, compliance_officer):
    """PRD §3.7: "For a `COMMERCIAL` operation, creation finally selects the covering policy and writes `covering_policy_id` (§3.6); for a `RECREATIONAL` operation it stays null."
    PRD §3.6: "Among the survivors the selector takes the policy with the **greatest** `remaining_coverage_cents`, breaking a tie on `created_at` ascending and never on `id`, and writes that policy's `id` into the flight's `covering_policy_id`."
    PRD §2.3: "Filters offered on a list endpoint narrow the result set before pagination is applied. The pilot roster filters on `status` and `operator_category`; knowledge tests on `pilot_id` and `status`; certifications on `pilot_id`, `originating_test_id`, `supersedes_certification_id` and `status`; airframes on `owner_pilot_id` and `registration_status`; broadcast modules on `aircraft_id` and `status`; zones on `class_code`; restrictions on `zone_id` and `status`; authorizations on `pilot_id`, `aircraft_id`, `zone_id`, `waiver_id` and `status`; waivers on `pilot_id`, `aircraft_id`, `waiver_type` and `status`; safety cases on `waiver_id` and `review_status`; policies on `pilot_id` and `coverage_status`; flights on `pilot_id`, `aircraft_id`, `zone_id`, `authorization_id`, `waiver_id`, `covering_policy_id`, `status` and `investigation_status`; and accident reports on `flight_id`, `policy_id` and `status`."

    Design: Corner/endpoints/covering_policy_link_is_navigable_and_propagates_to_the_report
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_zone(api)
    thinner_cover = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=1500000,
        deductible_cents=50000,
    )
    deeper_cover = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=2000000,
        deductible_cents=50000,
    )

    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        airframe["id"],
        zone["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        operation_category=OperationCategory.COMMERCIAL.value,
    )
    assert_flight(
        flight,
        status=FlightStatus.PLANNED.value,
        covering_policy_id=deeper_cover["id"],
    )

    matched, meta = validate_paginated(
        api.list_flights(
            params={"covering_policy_id": deeper_cover["id"]}, headers=compliance_officer
        )
    )
    assert [row["id"] for row in matched] == [flight["id"]], (
        f"the covering policy must be a usable flight filter, got {matched}"
    )
    assert meta["total_count"] == 1, (
        f"expected one flight under the covering policy, got {meta['total_count']}"
    )

    unmatched, _ = validate_paginated(
        api.list_flights(
            params={"covering_policy_id": thinner_cover["id"]}, headers=compliance_officer
        )
    )
    assert unmatched == [], (
        f"the policy that lost the selection covers no flight, got {unmatched}"
    )


def test_the_accident_report_copies_the_flights_covering_policy(
    api, compliance_officer, investigation_officer
):
    """PRD §3.8: "Its `policy_id` is **copied** from the flight's `covering_policy_id` at filing and is null when the flight had no covering policy; the copy is deliberate, so that later reselection on the flight cannot move an accident's cover."
    PRD §3.8: "Select the injury reserve from the `injury_level` — 0 cents for `NONE`, 250000 cents for `MINOR`, 1500000 cents for `SERIOUS`."
    PRD §3.8: "Multiply the `reported_property_damage_cents` by 1.25 and round half-up to whole cents, then add the injury reserve; that sum is the raw reserve."
    PRD §2.10: "A policy's `coverage_limit_cents` must at all times equal the sum of its `remaining_coverage_cents`, its `open_reserved_cents_total` and its `settled_cents_total`, where `open_reserved_cents_total` is the sum of `reserved_cents` over the accident reports against that policy whose `status` is `FILED`, `INVESTIGATING` or `REMEDIATION_REQUIRED`, and `settled_cents_total` is the sum of `settlement_cents` over the reports against that policy whose `status` is `CLOSED`."
    PRD §2.3: "Filters offered on a list endpoint narrow the result set before pagination is applied. The pilot roster filters on `status` and `operator_category`; knowledge tests on `pilot_id` and `status`; certifications on `pilot_id`, `originating_test_id`, `supersedes_certification_id` and `status`; airframes on `owner_pilot_id` and `registration_status`; broadcast modules on `aircraft_id` and `status`; zones on `class_code`; restrictions on `zone_id` and `status`; authorizations on `pilot_id`, `aircraft_id`, `zone_id`, `waiver_id` and `status`; waivers on `pilot_id`, `aircraft_id`, `waiver_type` and `status`; safety cases on `waiver_id` and `review_status`; policies on `pilot_id` and `coverage_status`; flights on `pilot_id`, `aircraft_id`, `zone_id`, `authorization_id`, `waiver_id`, `covering_policy_id`, `status` and `investigation_status`; and accident reports on `flight_id`, `policy_id` and `status`."

    Design: Corner/endpoints/covering_policy_link_is_navigable_and_propagates_to_the_report
    """
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_zone(api)
    policy = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=2000000,
        deductible_cents=50000,
    )

    flying = fixtures.create_in_progress_flight(
        api,
        pilot["id"],
        airframe["id"],
        zone["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        operation_category=OperationCategory.COMMERCIAL.value,
    )
    assert_flight(flying, covering_policy_id=policy["id"])

    report = fixtures.create_filed_report(
        api,
        flying,
        occurred_at=flying["actual_start"],
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=100000,
    )
    assert_accident_report(
        report,
        flight_id=flying["id"],
        policy_id=policy["id"],
        status=ReportStatus.FILED.value,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=100000,
        reserved_cents=125000,
        settlement_cents=None,
    )

    assert_policy(
        fixtures.read_policy(api, policy["id"]),
        coverage_status=CoverageStatus.ACTIVE.value,
        open_reserved_cents_total=125000,
        settled_cents_total=0,
        remaining_coverage_cents=1875000,
    )
    assert_coverage_ledger_conservation(api, policy["id"], compliance_officer)

    by_policy, meta = validate_paginated(
        api.list_accident_reports(
            params={"policy_id": policy["id"]}, headers=investigation_officer
        )
    )
    assert [row["id"] for row in by_policy] == [report["id"]], (
        f"the copied policy must be a usable accident-report filter, got {by_policy}"
    )
    assert meta["total_count"] == 1, (
        f"expected one report against the policy, got {meta['total_count']}"
    )


def test_the_selector_breaks_a_remaining_cover_tie_on_created_at(api, compliance_officer):
    """PRD §3.6: "Among the survivors the selector takes the policy with the **greatest** `remaining_coverage_cents`, breaking a tie on `created_at` ascending and never on `id`, and writes that policy's `id` into the flight's `covering_policy_id`."
    PRD §3.6: "The selector runs over the flight's pilot's policies and keeps a policy as a candidate only when *all* of the following hold: its `coverage_status` is `ACTIVE`; its `indemnification_clause_accepted` is true; its `effective_from` is at or before the flight's `planned_start`; its `effective_until` is strictly after the flight's `planned_end`; and its `remaining_coverage_cents` is at least 1000000 cents."
    PRD §2.5: "Every resource also carries a `created_at`, the ISO 8601 UTC instant of creation taken from the logical clock."

    Design: Corner/cross_cutting_complexity_layers/covering_policy_selector_breaks_ties_by_created_at_and_drops_the_expired_candidate
    """
    clock = Clock(api)
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_zone(api)

    filed_first = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=1200000,
        deductible_cents=50000,
    )
    clock.advance_days(1)
    filed_second = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=1200000,
        deductible_cents=50000,
    )
    assert parse_instant(filed_first["created_at"]) < parse_instant(filed_second["created_at"]), (
        "the clock advanced between the two filings, so their creation instants must differ; "
        f"got {filed_first['created_at']} and {filed_second['created_at']}"
    )
    for policy in (filed_first, filed_second):
        assert_policy(
            policy,
            coverage_status=CoverageStatus.ACTIVE.value,
            remaining_coverage_cents=1200000,
        )

    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        airframe["id"],
        zone["id"],
        "2026-10-01T09:00:00Z",
        "2026-10-01T10:00:00Z",
        operation_category=OperationCategory.COMMERCIAL.value,
    )
    assert_flight(
        flight,
        status=FlightStatus.PLANNED.value,
        covering_policy_id=filed_first["id"],
    )
    assert flight["covering_policy_id"] != filed_second["id"], (
        "with cover exactly tied the earlier creation instant wins, never the identifier"
    )

    both, meta = validate_paginated(
        api.list_policies(
            params={"pilot_id": pilot["id"], "coverage_status": CoverageStatus.ACTIVE.value},
            headers=compliance_officer,
        )
    )
    assert [row["id"] for row in both] == [filed_first["id"], filed_second["id"]], (
        f"the losing policy is untouched and both stay ACTIVE, got {both}"
    )
    assert meta["total_count"] == 2, f"expected two active policies, got {meta['total_count']}"


def test_the_selector_drops_the_expired_candidate_before_ranking_on_cover(
    api, compliance_officer
):
    """PRD §3.6: "Policies in `PENDING_VERIFICATION`, `REJECTED`, `INSUFFICIENT` or `EXPIRED` are excluded outright, and any policy whose `effective_until` has already passed is first moved to `EXPIRED` and thereby drops out of the candidate set."
    PRD §3.6: "Among the survivors the selector takes the policy with the **greatest** `remaining_coverage_cents`, breaking a tie on `created_at` ascending and never on `id`, and writes that policy's `id` into the flight's `covering_policy_id`."
    PRD §3.6: "The choice is deliberately greedy on remaining cover, not on limit and not on recency, so a large policy that has been eroded by an open accident reserve loses to a smaller untouched one."

    Design: Corner/cross_cutting_complexity_layers/covering_policy_selector_breaks_ties_by_created_at_and_drops_the_expired_candidate
    """
    clock = Clock(api)
    pilot = fixtures.create_certified_pilot(api, OperatorCategory.COMMERCIAL.value)
    airframe = fixtures.create_registered_aircraft(api, pilot["id"])
    zone = fixtures.create_zone(api)

    short_cover = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2026-09-01T00:00:00Z",
        coverage_limit_cents=1500000,
        deductible_cents=50000,
    )
    filed_first = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=1200000,
        deductible_cents=50000,
    )
    clock.advance_days(1)
    filed_second = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_until="2027-08-01T00:00:00Z",
        coverage_limit_cents=1200000,
        deductible_cents=50000,
    )

    clock.set("2026-09-15T00:00:00Z")
    deepest_cover = fixtures.create_active_policy(
        api,
        pilot["id"],
        effective_from="2026-09-01T00:00:00Z",
        effective_until="2027-09-01T00:00:00Z",
        coverage_limit_cents=1800000,
        deductible_cents=50000,
    )

    flight = fixtures.create_planned_flight(
        api,
        pilot["id"],
        airframe["id"],
        zone["id"],
        "2026-10-01T09:00:00Z",
        "2026-10-01T10:00:00Z",
        operation_category=OperationCategory.COMMERCIAL.value,
    )
    assert_flight(
        flight,
        status=FlightStatus.PLANNED.value,
        covering_policy_id=deepest_cover["id"],
    )
    assert flight["covering_policy_id"] != short_cover["id"], (
        "the policy with the deepest cover had already run out of window and cannot be selected"
    )

    assert_policy(
        fixtures.read_policy(api, short_cover["id"]),
        coverage_status=CoverageStatus.EXPIRED.value,
        remaining_coverage_cents=1500000,
    )
    for tied in (filed_first, filed_second):
        assert_policy(
            fixtures.read_policy(api, tied["id"]),
            coverage_status=CoverageStatus.ACTIVE.value,
            remaining_coverage_cents=1200000,
        )

    survivors, _ = validate_paginated(
        api.list_policies(
            params={"pilot_id": pilot["id"], "coverage_status": CoverageStatus.EXPIRED.value},
            headers=compliance_officer,
        )
    )
    assert [row["id"] for row in survivors] == [short_cover["id"]], (
        f"only the out-of-window policy may have been expired, got {survivors}"
    )
