"""Booking field maintenance: staffing, certification, region and the calendar.

The busiest guard set in the service business, where the precedence ladder decides
which of several simultaneous defects the caller is told about.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    SERVICE_MANAGER,
    ApiErrorId,
    api_client,
    create_pm_visit_payload,
    read_contract,
    read_visit,
    seed_field_engineer,
    setup_accepted_machine,
    setup_active_contract,
    setup_reference_data,
)

SILVER_TERM = {
    "tier": "SILVER",
    "start_date": "2026-08-01",
    "end_date": "2027-07-31",
    "pm_visits_included": 2,
    "goodwill_budget_initial_cents": 500_000,
}


def _covered_machine(**contract_overrides):
    env = setup_accepted_machine(setup_reference_data(line={}))
    return setup_active_contract(env, contract_overrides=dict(SILVER_TERM, **contract_overrides))


def _book(env, engineer_id=None, **overrides):
    payload = create_pm_visit_payload(env["contract"]["id"], **overrides)
    if engineer_id is not None:
        payload["field_engineer_id"] = engineer_id
    return api_client.create_pm_visit(payload, SERVICE_MANAGER)


def _visit_count(env):
    _rows, meta = validate_paginated(
        api_client.list_pm_visits(
            SERVICE_MANAGER, params={"service_contract_id": env["contract"]["id"]}
        )
    )
    return meta["total_count"]


def test_the_wrong_certification_is_reported_ahead_of_the_wrong_region():
    """One booking breaks two rules at once — an engineer certified on the wrong family
    and posted to the wrong region — and the safety gate is the one the caller hears
    about.

    PRD: "Rungs 32 through 36 are the safety gates that protect the OEM's test and
    service integrity:"

    Design: Difficulty/priority_pair_validation_conflict/pm_visit_certification_outranks_region_mismatch_returns_422
    """
    env = _covered_machine()
    wrong_on_both = seed_field_engineer(
        full_name="Otto Braun",
        region_code="EU",
        certifications=["CAPPER"],
        travel_buffer_minutes=45,
    )

    response = _book(
        env,
        engineer_id=wrong_on_both["id"],
        visit_type="PM",
        start_ts="2026-08-10T08:00:00.000Z",
        end_ts="2026-08-10T12:00:00.000Z",
    )

    error = validate_error(response, ApiErrorId.ERR_ENGINEER_NOT_CERTIFIED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_ENGINEER_REGION_MISMATCH.value
    assert _visit_count(env) == 0
    assert read_contract(env["contract"]["id"])["pm_visits_used"] == 0


def test_the_region_mismatch_was_masked_and_surfaces_once_certification_is_fixed():
    """Repairing only the certification, and leaving the engineer in the wrong region,
    shows the referential rung was live all along underneath the safety gate.

    PRD: "Rungs 55 through 58 are the referential cross-checks —
    `ERR_TRIAL_ORDER_MISMATCH` when engineering an order,
    `ERR_ENGINEER_REGION_MISMATCH` when booking a maintenance visit,
    `ERR_CONTRACT_MACHINE_MISMATCH` when opening a warranty claim, and
    `ERR_MACHINE_ORDER_CUSTOMER_MISMATCH` when recording an installation."

    Design: Difficulty/priority_pair_validation_conflict/pm_visit_certification_outranks_region_mismatch_returns_422
    """
    env = _covered_machine()
    certified_but_foreign = seed_field_engineer(
        full_name="Otto Braun",
        region_code="EU",
        certifications=["FILLER"],
        travel_buffer_minutes=45,
    )

    response = _book(
        env,
        engineer_id=certified_but_foreign["id"],
        visit_type="PM",
        start_ts="2026-08-10T08:00:00.000Z",
        end_ts="2026-08-10T12:00:00.000Z",
    )

    validate_error(response, ApiErrorId.ERR_ENGINEER_REGION_MISMATCH.value, 422)
    assert _visit_count(env) == 0


def test_an_engineer_on_leave_cannot_be_sent_to_site():
    """Certification and region are both right, so availability is the only defect the
    booking can be reporting.

    PRD: "`ERR_ENGINEER_ON_LEAVE` — the nominated engineer's `status` is `AVAILABLE`;
    guards booking a maintenance visit."

    Design: Corner/errors/pm_visit_create_for_engineer_on_leave_returns_409_engineer_on_leave
    """
    env = _covered_machine(goodwill_budget_initial_cents=350_000)
    engineer = seed_field_engineer()
    validate_success(api_client.field_engineer_leave(engineer["id"], ADMIN))

    response = _book(
        env,
        engineer_id=engineer["id"],
        visit_type="PM",
        start_ts="2026-08-10T08:00:00.000Z",
        end_ts="2026-08-10T12:00:00.000Z",
    )

    validate_error(response, ApiErrorId.ERR_ENGINEER_ON_LEAVE.value, 409)
    assert validate_success(api_client.get_field_engineer(engineer["id"], SERVICE_MANAGER))[
        "status"
    ] == "ON_LEAVE"
    assert read_contract(env["contract"]["id"])["pm_visits_used"] == 0
    assert _visit_count(env) == 0


def test_an_on_site_preventive_visit_may_not_be_left_unmanned():
    """The engineer field is optional in the schema and mandatory for on-site work, so
    omitting it is a business refusal rather than a shape violation.

    PRD: "The staffing gates follow from the visit type: a `PM` or `CORRECTIVE` visit
    is on-site work and requires a non-null `field_engineer_id`
    (`ERR_ENGINEER_REQUIRED`), whereas a `REMOTE_DIAGNOSTIC` visit is booked with no
    engineer at all and instead requires the covered machine's
    `remote_diagnostics_enabled` to be true (`ERR_REMOTE_DIAGNOSTICS_DISABLED`)."

    Design: Corner/errors/pm_visit_create_pm_without_engineer_returns_422_engineer_required
    """
    env = _covered_machine(goodwill_budget_initial_cents=350_000)

    response = _book(
        env,
        visit_type="PM",
        start_ts="2026-08-10T08:00:00.000Z",
        end_ts="2026-08-10T12:00:00.000Z",
    )

    validate_error(response, ApiErrorId.ERR_ENGINEER_REQUIRED.value, 422)
    assert read_contract(env["contract"]["id"])["pm_visits_used"] == 0
    assert _visit_count(env) == 0


def test_a_remote_session_is_refused_on_a_machine_that_streams_no_telemetry():
    """No engineer is needed for remote work, so the only thing that can stop this
    booking is the asset's own telemetry flag.

    PRD: "The staffing gates follow from the visit type: a `PM` or `CORRECTIVE` visit
    is on-site work and requires a non-null `field_engineer_id`
    (`ERR_ENGINEER_REQUIRED`), whereas a `REMOTE_DIAGNOSTIC` visit is booked with no
    engineer at all and instead requires the covered machine's
    `remote_diagnostics_enabled` to be true (`ERR_REMOTE_DIAGNOSTICS_DISABLED`)."

    Design: Corner/errors/remote_diagnostic_visit_on_disabled_machine_returns_422_remote_diagnostics_disabled
    """
    env = setup_accepted_machine(
        setup_reference_data(line={}), machine_overrides={"remote_diagnostics_enabled": False}
    )
    env = setup_active_contract(
        env, contract_overrides=dict(SILVER_TERM, goodwill_budget_initial_cents=350_000)
    )

    response = _book(
        env,
        visit_type="REMOTE_DIAGNOSTIC",
        start_ts="2026-08-10T08:00:00.000Z",
        end_ts="2026-08-10T09:00:00.000Z",
    )

    validate_error(response, ApiErrorId.ERR_REMOTE_DIAGNOSTICS_DISABLED.value, 422)
    assert env["machine"]["remote_diagnostics_enabled"] is False
    assert _visit_count(env) == 0


def test_a_visit_five_days_past_the_final_covered_day_is_outside_the_term():
    """The contract is ACTIVE and every staffing rule is satisfied, so coverage dates
    are the sole reason the booking is refused.

    PRD: "Both `start_ts` and `end_ts` must fall within the span that begins at the
    very first instant of the contract's `start_date` and ends at the last millisecond
    of its `end_date` — that is, from midnight UTC on the start date through
    23:59:59.999 UTC on the end date."

    Design: Corner/errors/pm_visit_outside_contract_term_returns_422_visit_outside_contract_term
    """
    env = _covered_machine(end_date="2026-12-31", goodwill_budget_initial_cents=350_000)
    engineer = seed_field_engineer()

    response = _book(
        env,
        engineer_id=engineer["id"],
        visit_type="PM",
        start_ts="2027-01-05T08:00:00.000Z",
        end_ts="2027-01-05T12:00:00.000Z",
    )

    validate_error(response, ApiErrorId.ERR_VISIT_OUTSIDE_CONTRACT_TERM.value, 422)
    assert read_contract(env["contract"]["id"])["pm_visits_used"] == 0

    accepted = _book(
        env,
        engineer_id=engineer["id"],
        visit_type="PM",
        start_ts="2026-12-31T08:00:00.000Z",
        end_ts="2026-12-31T12:00:00.000Z",
    )

    data = validate_success(accepted, 201)
    assert data["status"] == "SCHEDULED"
    assert read_contract(env["contract"]["id"])["pm_visits_used"] == 1


def test_a_visit_starting_at_the_exact_instant_an_earlier_one_ends_double_books():
    """The engineer's diary is a closed interval with no buffer applied, so back-to-back
    windows that merely touch at 12:00:00.000Z are still a collision.

    PRD: "The candidate collides with an incumbent when the candidate's `start_ts` is
    at or before the incumbent's `end_ts` **and** the incumbent's `start_ts` is at or
    before the candidate's `end_ts`; a visit starting at exactly the instant an
    incumbent ends therefore collides and is refused with
    `ERR_ENGINEER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/engineer_visit_touching_endpoint_collides_closed_interval_returns_409
    """
    env = _covered_machine()
    engineer = seed_field_engineer(
        full_name="Dana Reyes",
        region_code="NA",
        certifications=["FILLER"],
        travel_buffer_minutes=60,
    )
    first = validate_success(
        _book(
            env,
            engineer_id=engineer["id"],
            visit_type="PM",
            start_ts="2026-08-10T08:00:00.000Z",
            end_ts="2026-08-10T12:00:00.000Z",
        ),
        201,
    )

    response = _book(
        env,
        engineer_id=engineer["id"],
        visit_type="PM",
        start_ts="2026-08-10T12:00:00.000Z",
        end_ts="2026-08-10T16:00:00.000Z",
    )

    validate_error(response, ApiErrorId.ERR_ENGINEER_DOUBLE_BOOKED.value, 409)
    incumbent = read_visit(first["id"])
    assert incumbent["status"] == "SCHEDULED"
    assert incumbent["billable"] is False
    assert read_contract(env["contract"]["id"])["pm_visits_used"] == 1
    _rows, meta = validate_paginated(
        api_client.list_pm_visits(
            SERVICE_MANAGER, params={"field_engineer_id": engineer["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_one_millisecond_of_daylight_is_enough_to_clear_the_engineers_diary():
    """Shifting the candidate a single millisecond later ends the overlap, so the
    refusal really is decided at millisecond granularity rather than by the calendar
    day or the travel buffer.

    PRD: "Comparisons are made at millisecond precision."

    Design: Difficulty/resource_temporal_overlap/engineer_visit_touching_endpoint_collides_closed_interval_returns_409
    """
    env = _covered_machine()
    engineer = seed_field_engineer(
        full_name="Dana Reyes",
        region_code="NA",
        certifications=["FILLER"],
        travel_buffer_minutes=60,
    )
    validate_success(
        _book(
            env,
            engineer_id=engineer["id"],
            visit_type="PM",
            start_ts="2026-08-10T08:00:00.000Z",
            end_ts="2026-08-10T12:00:00.000Z",
        ),
        201,
    )

    data = validate_success(
        _book(
            env,
            engineer_id=engineer["id"],
            visit_type="PM",
            start_ts="2026-08-10T12:00:00.001Z",
            end_ts="2026-08-10T16:00:00.000Z",
        ),
        201,
    )

    assert data["status"] == "SCHEDULED"
    assert data["field_engineer_id"] == engineer["id"]
    assert read_contract(env["contract"]["id"])["pm_visits_used"] == 2
    _rows, meta = validate_paginated(
        api_client.list_pm_visits(
            SERVICE_MANAGER, params={"field_engineer_id": engineer["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_visit_read_with_unknown_id_reports_the_visit_not_found_code():
    """The service diary reports the visit's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each with
    HTTP 404."

    Design: Corner/errors/pm_visit_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_pm_visit(
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc", SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_PM_VISIT_NOT_FOUND.value, 404)
