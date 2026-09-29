"""Entity-shape claims: echoed fields, declared defaults, server-owned fields and the
computed fields a creation derives.
"""

from test_helpers import (
    BASE_SCORE,
    DEFAULT_CLOCK,
    DEFAULT_LIMIT,
    MISSING_PROJECT_ID,
    NETWORK_MANAGER,
    NON_EXISTENT_UUID,
    PROGRAM_ADMIN,
    PROJECT_COORDINATOR,
    SERVICE_MANAGER,
    ApiErrorId,
    BackgroundCheckResult,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    MeasurementStatus,
    PermitPolicy,
    PermitResponsibleParty,
    PermitStatus,
    ScorecardEventSource,
    ScorecardEventType,
    SubfloorCondition,
    TradeCode,
    UnitOfMeasure,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_score,
    assert_units,
    assert_version,
    assert_versioned_entity,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

QUOTED = 196673
DEPOSIT = 59002


def test_a_new_service_category_echoes_every_field_it_was_given(api):
    """The catalogue entry comes back complete, at version 1, with both timestamps on
    the logical clock.

    PRD 2.4: "Most resources additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of that row — and `version`, an integer
    that starts at 1 when the row is created and increases by exactly 1 on every
    mutation of that row, including mutations performed by a cascade the caller did not
    directly request."

    Design: Corner/entities/service_category_creation_echoes_every_declared_field_at_201
    """
    payload = f.measured_category_payload()
    category = validate_success(
        api.create_service_category(payload, PROGRAM_ADMIN), 201)

    assert category["code"] == "FLOOR-LVP"
    assert category["name"] == "LVP Flooring Install"
    assert category["trade_code"] == TradeCode.FLOORING
    assert category["unit_of_measure"] == UnitOfMeasure.SQFT
    assert_money(category["base_labor_rate_cents_per_unit"], 425,
                 "base_labor_rate_cents_per_unit")
    assert_units(category["minimum_billable_units"], 150.00,
                 "minimum_billable_units")
    assert category["measurement_required"] is True
    assert category["measurement_validity_days"] == 45
    assert category["permit_policy"] == PermitPolicy.BY_JURISDICTION
    assert category["deposit_pct"] == 0.30
    assert category["status"] == "ACTIVE"

    assert_versioned_entity(category, "ServiceCategory")
    assert_version(category, 1, "ServiceCategory")
    assert_instant(category["created_at"], DEFAULT_CLOCK, "created_at")
    assert_instant(category["updated_at"], DEFAULT_CLOCK, "updated_at")


def test_a_jurisdiction_body_of_required_fields_only_takes_its_defaults(api):
    """Six required settings in, seven documented defaults out.

    PRD 3.1: "`inspection_lead_days` is the minimum number of whole days between the
    logical clock and a booked inspection start, must be at least zero and defaults to
    3. `max_concurrent_inspections` caps how many projects in this jurisdiction may hold
    overlapping inspection slots, must be at least 1 and defaults to 2."

    Design: Corner/entities/jurisdiction_omitted_optionals_take_their_declared_defaults
    """
    jurisdiction = validate_success(
        api.create_jurisdiction(
            {
                "code": "METRO-09",
                "name": "Bare County",
                "permit_required_trades": [TradeCode.FLOORING],
                "permit_responsible_party": PermitResponsibleParty.RETAILER,
                "inspection_required": False,
                "min_liability_coverage_cents": 100000000,
            },
            PROGRAM_ADMIN),
        201)

    assert jurisdiction["permit_unit_threshold"] == 0
    assert jurisdiction["inspection_lead_days"] == 3
    assert jurisdiction["max_concurrent_inspections"] == 2
    assert jurisdiction["background_check_recency_days"] == 365
    assert jurisdiction["license_required"] is True
    assert jurisdiction["labor_complexity_multiplier"] == 1.00
    assert jurisdiction["status"] == "ACTIVE"
    assert jurisdiction["permit_required_trades"] == [TradeCode.FLOORING]
    assert_version(jurisdiction, 1, "Jurisdiction")


def test_a_service_category_body_of_required_fields_only_takes_its_defaults(api):
    """A different entity's default set: the four omitted policy switches.

    PRD 3.1: "`measurement_validity_days` is how long a completed measurement remains
    usable for scheduling, counted from the measurement's `completed_at`; it must be at
    least 1 and defaults to 45 when the caller omits it. `permit_policy` decides how
    permit necessity is settled and is one of `NEVER`, `ALWAYS` or `BY_JURISDICTION`,
    defaulting to `BY_JURISDICTION`."

    Design: Corner/entities/service_category_omitted_optionals_take_their_declared_defaults
    """
    category = validate_success(
        api.create_service_category(
            {
                "code": "FLOOR-BARE",
                "name": "Bare Flooring Install",
                "trade_code": TradeCode.FLOORING,
                "unit_of_measure": UnitOfMeasure.SQFT,
                "base_labor_rate_cents_per_unit": 425,
                "minimum_billable_units": 150.00,
                "measurement_required": False,
            },
            PROGRAM_ADMIN),
        201)

    assert category["measurement_validity_days"] == 45
    assert category["permit_policy"] == PermitPolicy.BY_JURISDICTION
    assert category["deposit_pct"] == 0.30
    assert category["status"] == "ACTIVE"
    assert category["measurement_required"] is False
    assert_version(category, 1, "ServiceCategory")


def test_a_newly_recruited_firm_opens_on_the_programme_baseline(api):
    """Every scorecard and capacity field on a new firm is server-owned: the client
    supplies five facts and the server writes the rest.

    PRD 3.2: "A newly recruited firm lands in network status `APPLIED` with
    `background_check_result` of `NONE`, `background_check_completed_at` null,
    `committed_minutes`, `verified_credential_count`, `rolling_event_count`,
    `rolling_no_show_count` and `completed_project_count` all zero, `quality_score`,
    `timeliness_score`, `satisfaction_score`, `composite_score` and
    `lifetime_composite_score` all at the programme baseline of 85.00, `removal_eligible`
    false, and `probation_started_at`, `removed_at` and `removal_reason` all null."

    Design: Corner/entities/installer_system_and_computed_fields_are_server_set_with_client_input_ignored
    """
    installer = validate_success(
        api.create_installer(f.installer_payload(), NETWORK_MANAGER), 201)

    assert installer["status"] == InstallerStatus.APPLIED
    assert installer["committed_minutes"] == 0
    assert installer["verified_credential_count"] == 0
    assert installer["rolling_event_count"] == 0
    assert installer["rolling_no_show_count"] == 0
    assert installer["completed_project_count"] == 0
    assert installer["removal_eligible"] is False
    assert installer["background_check_result"] == BackgroundCheckResult.NONE
    assert installer["background_check_completed_at"] is None
    assert installer["probation_started_at"] is None
    assert installer["removed_at"] is None
    assert installer["removal_reason"] is None
    for field in ("quality_score", "timeliness_score", "satisfaction_score",
                  "composite_score", "lifetime_composite_score"):
        assert_score(installer[field], BASE_SCORE, field)

    # The two client-owned facts are stored as supplied.
    assert_money(installer["liability_coverage_cents"], 200000000,
                 "liability_coverage_cents")
    assert_instant(installer["insurance_expires_on"], "2027-06-30T00:00:00.000Z",
                   "insurance_expires_on")


def test_selling_a_project_derives_its_money_and_permit_fields(api):
    """Four computed fields come out of the category and jurisdiction rows in one
    request, and the household's project counter moves with them.

    PRD 3.3: "It sets `deposit_required_cents` to the frozen quote multiplied by the
    category's `deposit_pct`, rounded half up to whole cents, and freezes that
    alongside."

    Design: Corner/entities/project_creation_derives_every_computed_money_and_permit_field
    """
    base = fx.program_baseline(api, f.measured_category_payload(),
                               f.jurisdiction_payload())
    project = validate_success(
        api.create_project(
            f.project_payload(base["customer"]["id"], base["category"]["id"],
                              base["jurisdiction"]["id"], estimated_units=420.00),
            PROJECT_COORDINATOR),
        201)

    assert_units(project["effective_units"], 420.00, "effective_units")
    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")
    assert_money(project["deposit_required_cents"], DEPOSIT,
                 "deposit_required_cents")
    assert project["permit_responsibility"] == PermitResponsibleParty.RETAILER
    assert_project_dimensions(project,
                              fulfillment=FulfillmentStatus.MEASURE_PENDING,
                              financial=FinancialStatus.QUOTED,
                              permit=PermitStatus.PENDING_APPLICATION)
    for bucket in ("deposit_paid_cents", "deposit_held_cents",
                   "deposit_applied_cents", "deposit_refunded_cents",
                   "deposit_forfeited_cents"):
        assert_money(project[bucket], 0, bucket)
    assert project["final_labor_cents"] is None
    assert_money(project["total_due_cents"], 0, "total_due_cents")
    assert_money(project["balance_due_cents"], 0, "balance_due_cents")

    customer = get_success_data(
        api.get_customer(base["customer"]["id"], PROJECT_COORDINATOR))
    assert customer["project_count"] == 1


def test_reading_a_completed_measurement_returns_the_stored_row(api):
    """The read replays what completion wrote, including the clock-stamped
    `completed_at` rather than the appointment's `scheduled_at`.

        PRD 3.4: "Completion performs, in one request: the appointment moves
    `SCHEDULED → COMPLETED` and `completed_at` is stamped with the current
    logical-clock value, which is the instant from which measurement freshness
    is later counted; `variance_pct` is computed as the absolute difference
    between `measured_units` and the project's `estimated_units`, divided by
    `estimated_units`, multiplied by one hundred and rounded half up to two
    decimal places; `change_order_triggered` is set true when `variance_pct` is
    10.00 or greater and false otherwise; the project's `effective_units` is
    overwritten with `measured_units` — note that `estimated_units` itself is
    never overwritten, because `variance_pct` must remain reproducible; the
    permit determination of §3.5 is re-run against the new `effective_units`,
    so `permit_status` may flip in either direction between `NOT_REQUIRED` and
    `PENDING_APPLICATION`; and the project's `version` increments."

    Design: Corner/entities/completed_measurement_retrieval_returns_the_stored_row
    """
    base = fx.program_baseline(api, f.measured_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    booked = get_success_data(
        api.create_measurement(
            project["id"],
            f.measurement_payload("2026-08-05T09:00:00.000Z", "Ivy Nakamura"),
            PROJECT_COORDINATOR)
    )
    fx.complete_measurement(api, booked["id"], 420.00,
                            subfloor_condition=SubfloorCondition.MINOR,
                            obstruction_count=2, stair_flight_count=1,
                            access_notes="Side gate access only")

    measurement = get_success_data(api.get_measurement(booked["id"],
                                                       PROJECT_COORDINATOR))
    assert measurement["project_id"] == project["id"]
    assert measurement["technician_name"] == "Ivy Nakamura"
    assert_instant(measurement["scheduled_at"], "2026-08-05T09:00:00.000Z",
                   "scheduled_at")
    assert measurement["status"] == MeasurementStatus.COMPLETED
    assert_instant(measurement["completed_at"], DEFAULT_CLOCK, "completed_at")
    assert_units(measurement["measured_units"], 420.00, "measured_units")
    assert measurement["subfloor_condition"] == SubfloorCondition.MINOR
    assert measurement["obstruction_count"] == 2
    assert measurement["stair_flight_count"] == 1
    assert_score(measurement["variance_pct"], 0.00, "variance_pct")
    assert measurement["change_order_triggered"] is False
    assert measurement["voided_reason"] is None

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED)
    assert_units(after["effective_units"], 420.00, "effective_units")


def test_the_category_listing_pages_report_the_full_match_count(api):
    """Two pages of two over three rows: `total_count` counts matches before the window,
    `has_more` reports whether rows remain, and an uncapped call takes the default page
    size.

    PRD 2.3: "List responses carry `response_type` of `"array"`, place the rows in
    `data`, and populate four pagination fields inside `meta`: `limit` and `offset` echo
    the effective values used for the page, `total_count` reports how many rows match the
    filters before the page window is applied, and `has_more` is true when rows remain
    beyond the current window."

    Design: Corner/entities/service_category_listing_paginates_with_total_count_and_has_more
    """
    stored = {
        fx.create_category(api, f.measured_category_payload())["id"],
        fx.create_category(api, f.service_category_payload())["id"],
        fx.create_category(api, f.quick_category_payload())["id"],
    }
    assert len(stored) == 3

    first_rows, first_meta = validate_paginated(
        api.list_service_categories(PROJECT_COORDINATOR,
                                    {"limit": 2, "offset": 0}))
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_rows, second_meta = validate_paginated(
        api.list_service_categories(PROJECT_COORDINATOR,
                                    {"limit": 2, "offset": 2}))
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    first_ids = {row["id"] for row in first_rows}
    second_ids = {row["id"] for row in second_rows}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == stored


def test_a_filtered_category_listing_takes_the_default_window(api):
    """Asking for no window at all applies limit 10 and offset 0, which is wide enough
    to hold every matching row.

    PRD 2.3: "`limit` controls page size: its default is 10, its minimum accepted value
    is 1 and its maximum accepted value is 100."

    Design: Corner/entities/service_category_listing_paginates_with_total_count_and_has_more
    """
    for payload in (f.measured_category_payload(), f.service_category_payload(),
                    f.quick_category_payload()):
        fx.create_category(api, payload)

    rows, meta = validate_paginated(
        api.list_service_categories(PROJECT_COORDINATOR,
                                    {"trade_code": TradeCode.FLOORING,
                                     "status": "ACTIVE"}))
    assert meta["limit"] == DEFAULT_LIMIT
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 3
    assert {row["code"] for row in rows} == {"FLOOR-LVP", "FLOOR-DIRECT",
                                             "FLOOR-QUICK"}


def test_reading_a_project_that_was_never_created_is_a_not_found(api):
    """A well-formed identifier that resolves to no row is refused on the path lookup,
    and the failed read creates nothing.

    PRD 2.8 rank 6: "Every identifier appearing in the URL path resolves to a stored row,
    checked left to right — otherwise that entity's not-found code (404)."

    Design: Corner/entities/unknown_project_id_returns_project_not_found
    """
    body = validate_error(api.get_project(MISSING_PROJECT_ID, PROJECT_COORDINATOR),
                          ApiErrorId.PROJECT_NOT_FOUND)
    assert isinstance(body["message"], str) and body["message"].strip()

    _, meta = validate_paginated(api.list_projects(PROJECT_COORDINATOR))
    assert meta["total_count"] == 0


def test_a_project_body_missing_two_required_fields_is_refused(api):
    """Every foreign key in the body is valid, so the only fault is the two omissions —
    and they are caught before the household counter moves.

    PRD 2.8 rank 3: "Every required field of the endpoint's input is present and
    non-null — otherwise `ERR_MISSING_REQUIRED_FIELD` (422)."

    Design: Corner/entities/project_create_missing_required_fields_returns_missing_required_field
    """
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    validate_error(
        api.create_project(
            {
                "customer_id": base["customer"]["id"],
                "service_category_id": base["category"]["id"],
                "jurisdiction_id": base["jurisdiction"]["id"],
                "site_address": "18 Larch Way",
            },
            PROJECT_COORDINATOR),
        ApiErrorId.MISSING_REQUIRED_FIELD,
    )

    _, meta = validate_paginated(api.list_projects(PROJECT_COORDINATOR))
    assert meta["total_count"] == 0
    customer = get_success_data(
        api.get_customer(base["customer"]["id"], PROJECT_COORDINATOR))
    assert customer["project_count"] == 0


def test_a_bad_enum_and_a_negative_minimum_answer_differently(api):
    """Enum membership is a type failure while a negative quantity is a range failure, so
    the same entity yields two different identifiers.

    PRD 2.8 rank 4: "Every supplied field has its declared type, every enum value is a
    member of its declared set, every money field is a JSON integer rather than a string
    or a float, and every instant is an ISO 8601 UTC string with exactly three fractional
    digits — otherwise `ERR_INVALID_FIELD_TYPE` (422)."

    Design: Corner/entities/service_category_bad_enum_and_negative_minimum_are_rejected
    """
    validate_error(
        api.create_service_category(
            {
                "code": "FLOOR-BAD1",
                "name": "Bad Trade",
                "trade_code": "PLUMBING",
                "unit_of_measure": UnitOfMeasure.SQFT,
                "base_labor_rate_cents_per_unit": 425,
                "minimum_billable_units": 150.00,
                "measurement_required": False,
            },
            PROGRAM_ADMIN),
        ApiErrorId.INVALID_FIELD_TYPE,
    )
    validate_error(
        api.create_service_category(
            {
                "code": "FLOOR-BAD2",
                "name": "Bad Minimum",
                "trade_code": TradeCode.FLOORING,
                "unit_of_measure": UnitOfMeasure.SQFT,
                "base_labor_rate_cents_per_unit": 425,
                "minimum_billable_units": -5.00,
                "measurement_required": False,
            },
            PROGRAM_ADMIN),
        ApiErrorId.FIELD_OUT_OF_RANGE,
    )

    _, meta = validate_paginated(api.list_service_categories(PROGRAM_ADMIN))
    assert meta["total_count"] == 0


def test_a_filed_scorecard_event_carries_no_version_and_never_changes(api):
    """The ledger row exposes `id` and `created_at` but neither `version` nor
    `updated_at`, and appending a second event leaves the first row's three deltas
    exactly as written.

    PRD 2.4: "`ScorecardEvent` is the one exception: it is an immutable ledger row that
    carries only `id` and `created_at`."

    Design: Corner/entities/scorecard_event_is_immutable_with_no_version_field_and_no_update_endpoint
    """
    installer = validate_success(
        api.create_installer(f.installer_payload(), NETWORK_MANAGER), 201)
    first = validate_success(
        api.create_scorecard_event(
            installer["id"],
            f.scorecard_event_payload(ScorecardEventType.PUNCH_MAJOR,
                                      "2026-07-20T00:00:00.000Z"),
            SERVICE_MANAGER),
        201)

    assert "version" not in first
    assert "updated_at" not in first
    assert first["installer_id"] == installer["id"]
    assert first["event_type"] == ScorecardEventType.PUNCH_MAJOR
    assert first["source"] == ScorecardEventSource.MANUAL
    assert_score(first["quality_delta"], -8.00, "quality_delta")
    assert_score(first["timeliness_delta"], -2.00, "timeliness_delta")
    assert_score(first["satisfaction_delta"], -4.00, "satisfaction_delta")
    assert_instant(first["created_at"], DEFAULT_CLOCK, "created_at")

    second = validate_success(
        api.create_scorecard_event(
            installer["id"],
            f.csat_event_payload(5, "2026-07-22T00:00:00.000Z"),
            SERVICE_MANAGER),
        201)
    assert_score(second["satisfaction_delta"], 10.00, "satisfaction_delta")
    assert_score(second["quality_delta"], 0.00, "quality_delta")
    assert_score(second["timeliness_delta"], 0.00, "timeliness_delta")

    rows, meta = validate_paginated(
        api.list_installer_scorecard_events(installer["id"], SERVICE_MANAGER,
                                            {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    replayed = {row["id"]: row for row in rows}
    assert_score(replayed[first["id"]]["quality_delta"], -8.00,
                 "the first event's quality_delta after the append")
    for row in rows:
        assert "version" not in row
        assert "updated_at" not in row


def test_a_credential_naming_an_unstored_jurisdiction_is_a_not_found(api):
    """A body foreign key is validated as a stored reference, so no credential row is
    written and the firm does not leave APPLIED.

    PRD 2.8 rank 7: "Every foreign-key identifier in the request body resolves to a
    stored row, checked in the field order the endpoint declares — otherwise that
    entity's not-found code (404)."

    Design: Corner/entities/credential_naming_an_unknown_jurisdiction_returns_jurisdiction_not_found
    """
    installer = validate_success(
        api.create_installer(f.installer_payload(), NETWORK_MANAGER), 201)

    validate_error(
        api.create_credential(installer["id"],
                              f.credential_payload(NON_EXISTENT_UUID),
                              NETWORK_MANAGER),
        ApiErrorId.JURISDICTION_NOT_FOUND,
    )

    _, meta = validate_paginated(
        api.list_installer_credentials(installer["id"], NETWORK_MANAGER))
    assert meta["total_count"] == 0
    after = fx.read_installer(api, installer["id"])
    assert after["status"] == InstallerStatus.APPLIED
    assert after["verified_credential_count"] == 0
    assert_version(after, installer["version"], "installer")
