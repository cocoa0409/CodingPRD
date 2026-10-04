"""Service authorizations and deliveries: windows, OCC and unit accounting."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, set_clock,
    create_client, create_service_authorization_payload, create_service_delivery_payload,
    walk_screen_to_eligible, activate_enrollment, authorize_units, record_delivery,
    document_delivery, list_enrollments_for, list_authorizations_for,
    list_deliveries_for_authorization, setup_landscape, setup_active_enrollment,
    setup_frozen_grant, refresh_authorization, ApiErrorId, PROGRAM, COMPLIANCE,
)


def test_service_delivery_sequence_no_is_server_assigned_and_monotonic():
    """PRD §3.6: "The server assigns the delivery a `sequence_no` from its own
    counter — a strictly increasing integer starting at 1 that is never reused
    and never derived from the row's `id`".
    PRD §3.6: "The delivery begins in `DRAFT` status with `documentation_status`
    of `INCOMPLETE`, its `gross_cost_cents` is set to the number of units
    delivered multiplied by the per-unit rate".

    Design: Corner/entities/service_delivery_sequence_no_is_server_assigned_and_monotonic
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_enrollment(authorize=True,
                                  authorization_overrides={
                                      "authorized_units": 10, "unit_rate_cents": 5000,
                                      "period_start": "2026-09-01T00:00:00Z",
                                      "period_end": "2026-10-01T00:00:00Z"})
    first = record_delivery(ctx["authorization"]["id"], ctx["grant"]["id"],
                            ctx["client"]["id"], ctx["authorization"]["version"],
                            units_delivered=2, unit_rate_cents=5000,
                            service_date="2026-09-02T01:00:00Z")
    # The first delivery advanced the authorization's version (§3.6), so the
    # second must carry the freshly re-read value as its expected version.
    second = record_delivery(ctx["authorization"]["id"], ctx["grant"]["id"],
                             ctx["client"]["id"],
                             refresh_authorization(ctx["authorization"]["id"])["version"],
                             units_delivered=1, unit_rate_cents=5000,
                             service_date="2026-09-02T02:00:00Z")

    assert first["sequence_no"] == 1, "the counter starts at 1"
    assert second["sequence_no"] == 2, "the counter is strictly increasing"
    assert first["sequence_no"] != first["id"]
    assert second["sequence_no"] != second["id"]
    assert first["status"] == "DRAFT"
    assert first["documentation_status"] == "INCOMPLETE"
    assert first["gross_cost_cents"] == 10000


def test_service_authorization_creation_activates_and_advances_enrollment_version():
    """PRD §3.6: "A successful authorization begins in `ACTIVE` status with
    `units_delivered` at 0, and it increments the enrollment's `version` by one."
    PRD §3.6: "The usable window is given by `period_start`, the first instant
    the authorization is usable and inclusive, and `period_end`, the last
    instant it is usable and exclusive".

    Design: Corner/endpoints/service_authorization_creation_activates_and_advances_enrollment_version
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_enrollment()
    observed = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))

    resp = api_client.create_service_authorization(
        create_service_authorization_payload(
            ctx["enrollment"]["id"], ctx["grant"]["id"], observed["version"],
            authorized_units=10, unit_rate_cents=5000,
            period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
        ),
        PROGRAM,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["units_delivered"] == 0
    assert data["period_end"] == "2026-10-01T00:00:00.000Z"
    assert data["authorized_units"] == 10

    after = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    assert after["version"] == observed["version"] + 1


def test_zero_unit_delivery_rejected_after_occ_check_passes():
    """PRD §3.6: "`units_delivered` is constrained to zero or greater as a
    value, but a delivery created with zero units is never billable and is
    refused at creation with `ERR_ZERO_UNITS` (HTTP 422)."

    Design: Corner/validations/zero_unit_delivery_rejected_after_occ_check_passes
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_enrollment(authorize=True,
                                  authorization_overrides={
                                      "authorized_units": 10, "unit_rate_cents": 5000,
                                      "period_start": "2026-09-01T00:00:00Z",
                                      "period_end": "2026-10-01T00:00:00Z"})

    resp = api_client.create_service_delivery(
        create_service_delivery_payload(
            ctx["authorization"]["id"], ctx["grant"]["id"], ctx["client"]["id"],
            ctx["authorization"]["version"],
            units_delivered=0, unit_rate_cents=5000,
            service_date="2026-09-02T00:00:00Z",
        ),
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_ZERO_UNITS)

    assert list_deliveries_for_authorization(ctx["authorization"]["id"]) == []
    authorization = get_success_data(
        api_client.get_service_authorization(ctx["authorization"]["id"], PROGRAM))
    assert authorization["units_delivered"] == 0
    assert authorization["status"] == "ACTIVE"


def test_delivery_against_expired_authorization_rejected():
    """PRD §3.6: "The enrollment behind the authorization must hold at least one
    authorization in `ACTIVE` status covering the current logical clock, or the
    request is refused with `ERR_NO_ACTIVE_AUTHORIZATION` (HTTP 409)."
    PRD §3.5: "Exiting from `ACTIVE` or from `SUSPENDED` also expires the
    enrollment's authorizations: every `ServiceAuthorization` row belonging to
    that enrollment whose status is `ACTIVE` is set to `EXPIRED`".

    Design: Corner/validations/delivery_against_expired_authorization_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_enrollment(authorize=True,
                                  authorization_overrides={
                                      "authorized_units": 10, "unit_rate_cents": 5000,
                                      "period_start": "2026-09-01T00:00:00Z",
                                      "period_end": "2026-10-01T00:00:00Z"})
    api_client.exit_enrollment(ctx["enrollment"]["id"], {"exit_reason": "COMPLETED"}, PROGRAM)

    authorization = get_success_data(
        api_client.get_service_authorization(ctx["authorization"]["id"], PROGRAM))
    assert authorization["status"] == "EXPIRED", "the exit side effect expired the authorization"

    resp = api_client.create_service_delivery(
        create_service_delivery_payload(
            ctx["authorization"]["id"], ctx["grant"]["id"], ctx["client"]["id"],
            authorization["version"],
            units_delivered=1, unit_rate_cents=5000,
            service_date="2026-09-02T00:00:00Z",
        ),
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AUTHORIZATION)
    assert list_deliveries_for_authorization(ctx["authorization"]["id"]) == []


def test_authorization_half_open_interval_permits_touching_endpoints():
    """PRD §3.6: "Because the intervals are half-open, an existing authorization
    whose `period_end` exactly equals the new `period_start` is not an overlap
    and is permitted; anything closer than that is refused with
    `ERR_AUTHORIZATION_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/authorization_half_open_interval_permits_touching_endpoints
    """
    set_clock("2026-10-02T00:00:00Z")
    ctx = setup_active_enrollment(authorize=True,
                                  authorization_overrides={
                                      "authorized_units": 20, "unit_rate_cents": 4500,
                                      "period_start": "2026-09-01T00:00:00Z",
                                      "period_end": "2027-09-01T00:00:00Z"})

    observed = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    touching = api_client.create_service_authorization(
        create_service_authorization_payload(
            ctx["enrollment"]["id"], ctx["grant"]["id"], observed["version"],
            authorized_units=10, unit_rate_cents=4500,
            period_start="2027-09-01T00:00:00Z", period_end="2028-03-01T00:00:00Z",
        ),
        PROGRAM,
    )
    accepted = validate_success(touching, expected_status=201)
    assert accepted["period_start"] == "2027-09-01T00:00:00.000Z"

    observed2 = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    overlapping = api_client.create_service_authorization(
        create_service_authorization_payload(
            ctx["enrollment"]["id"], ctx["grant"]["id"], observed2["version"],
            authorized_units=10, unit_rate_cents=4500,
            period_start="2027-08-31T00:00:00Z", period_end="2027-12-31T00:00:00Z",
        ),
        PROGRAM,
    )
    validate_error(overlapping, ApiErrorId.ERR_AUTHORIZATION_PERIOD_OVERLAP)

    rows = list_authorizations_for(ctx["enrollment"]["id"])
    assert len(rows) == 2, "the refused request created no row"
    assert rows[0]["id"] == ctx["authorization"]["id"]
    assert rows[1]["id"] == accepted["id"]


def test_stale_enrollment_version_rejects_authorization_creation():
    """PRD §2.9: "Authorizing a block of service units requires the request to
    carry `expected_enrollment_version`, and that value must equal the target
    enrollment's current `version`."
    PRD §2.9: "When the supplied value does not match the parent's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/stale_enrollment_version_rejects_authorization_creation
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_enrollment()
    observed = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    observed_version = observed["version"]

    authorize_units(ctx["enrollment"]["id"], ctx["grant"]["id"], observed_version,
                    authorized_units=10, unit_rate_cents=5000)

    resp = api_client.create_service_authorization(
        create_service_authorization_payload(
            ctx["enrollment"]["id"], ctx["grant"]["id"], observed_version,
            service_code="CLINICAL_COUNSELING_HOUR",
            authorized_units=5, unit_rate_cents=8000,
            period_start="2026-10-01T00:00:00Z", period_end="2026-11-01T00:00:00Z",
        ),
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    rows = list_authorizations_for(ctx["enrollment"]["id"])
    assert len(rows) == 1
    after = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], PROGRAM))
    assert after["version"] == observed_version + 1, "the refused call changed nothing"


def test_stale_authorization_version_rejects_delivery_creation():
    """PRD §2.9: "Recording a service delivery requires the request to carry
    `expected_service_authorization_version`, and that value must equal the
    target authorization's current `version`."
    PRD §2.9: "In both cases the field is non-optional: a request that omits it
    does not fall back to an unchecked write."

    Design: Corner/cross_cutting_complexity_layers/stale_authorization_version_rejects_delivery_creation
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_enrollment(authorize=True,
                                  authorization_overrides={
                                      "authorized_units": 10, "unit_rate_cents": 5000,
                                      "period_start": "2026-09-01T00:00:00Z",
                                      "period_end": "2026-10-01T00:00:00Z"})
    observed_version = ctx["authorization"]["version"]

    record_delivery(ctx["authorization"]["id"], ctx["grant"]["id"], ctx["client"]["id"],
                    observed_version, units_delivered=1, unit_rate_cents=5000,
                    service_date="2026-09-02T01:00:00Z")

    resp = api_client.create_service_delivery(
        create_service_delivery_payload(
            ctx["authorization"]["id"], ctx["grant"]["id"], ctx["client"]["id"],
            observed_version,
            units_delivered=1, unit_rate_cents=5000,
            service_date="2026-09-02T02:00:00Z",
        ),
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    assert len(list_deliveries_for_authorization(ctx["authorization"]["id"])) == 1
    authorization = get_success_data(
        api_client.get_service_authorization(ctx["authorization"]["id"], PROGRAM))
    assert authorization["units_delivered"] == 0, "the refused call consumed nothing"


def test_authorization_exhausts_exactly_at_authorized_units_and_refuses_further_draws():
    """PRD §3.6: "an authorization that has consumed all of its authorized units
    becomes `EXHAUSTED`."
    PRD §3.6: "The enrollment behind the authorization must hold at least one
    authorization in `ACTIVE` status covering the current logical clock, or the
    request is refused with `ERR_NO_ACTIVE_AUTHORIZATION` (HTTP 409)."

    Design: Corner/cross_cutting_complexity_layers/authorization_exhausts_exactly_at_authorized_units_and_refuses_further_draws
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_enrollment(authorize=True,
                                  authorization_overrides={
                                      "authorized_units": 2, "unit_rate_cents": 5000,
                                      "period_start": "2026-09-01T00:00:00Z",
                                      "period_end": "2026-10-01T00:00:00Z"})
    delivery = record_delivery(ctx["authorization"]["id"], ctx["grant"]["id"],
                               ctx["client"]["id"], ctx["authorization"]["version"],
                               units_delivered=2, unit_rate_cents=5000,
                               service_date="2026-09-02T01:00:00Z")
    document_delivery(delivery["id"])

    authorization = get_success_data(
        api_client.get_service_authorization(ctx["authorization"]["id"], PROGRAM))
    assert authorization["status"] == "EXHAUSTED", "the last unit exhausted the authorization"
    assert authorization["units_delivered"] == 2

    resp = api_client.create_service_delivery(
        create_service_delivery_payload(
            ctx["authorization"]["id"], ctx["grant"]["id"], ctx["client"]["id"],
            authorization["version"],
            units_delivered=1, unit_rate_cents=5000,
            service_date="2026-09-02T02:00:00Z",
        ),
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AUTHORIZATION)
    assert len(list_deliveries_for_authorization(ctx["authorization"]["id"])) == 1


def test_frozen_grant_state_check_outranks_zero_unit_fiscal_check():
    """PRD §2.10: "A request that trips a priority 4 state check and a priority
    8 fiscal check answers with the priority 4 error, and the fiscal problem is
    never mentioned."
    PRD §2.10: "`ERR_GRANT_FROZEN` (HTTP 409) fires when the governing grant is
    at posture `FROZEN`, and it guards six operations".
    PRD §2.10: "Priority 8 is business fiscal and covers `ERR_ZERO_UNITS`
    (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/frozen_grant_state_check_outranks_zero_unit_fiscal_check
    """
    ctx = setup_frozen_grant(
        units_delivered=1, unit_rate_cents=1000,
        grant_overrides={"total_award_cents": 1000, "admin_rate_pct": 0.10},
        authorization_overrides={"authorized_units": 5, "unit_rate_cents": 1000,
                                 "period_start": "2026-09-01T00:00:00Z",
                                 "period_end": "2026-11-01T00:00:00Z"},
        clock="2026-10-02T00:00:00Z",
    )
    assert ctx["grant"]["status"] == "FROZEN"

    resp = api_client.create_service_delivery(
        create_service_delivery_payload(
            ctx["authorization"]["id"], ctx["grant"]["id"], ctx["client"]["id"],
            ctx["authorization"]["version"],
            units_delivered=0, unit_rate_cents=1000,
            service_date="2026-10-03T00:00:00Z",
        ),
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_FROZEN)
    assert len(list_deliveries_for_authorization(ctx["authorization"]["id"])) == 1, (
        "the refused call created no delivery"
    )
