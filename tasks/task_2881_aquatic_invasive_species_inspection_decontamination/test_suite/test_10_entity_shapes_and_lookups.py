"""Entity corners: creation echoes, defaults, computed fields, immutability and lookups."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_UTC,
    PROGRAM_ADMIN,
    TRAINING_OFFICER,
    add_watercraft,
    api_client,
    assert_common_fields,
    assert_envelope_meta,
    assert_inspection_record,
    assert_instant_equals,
    assert_station,
    assert_training_record,
    assert_water_body,
    assert_watercraft,
    create_and_open_station,
    create_station,
    create_water_body,
    enroll_inspector,
    fetch_inspector,
    fetch_station_hours,
    inspection_record_payload,
    make_inspector_headers,
    register_watercraft,
    set_clock,
    setup_program,
    station_hours_payload,
    station_payload,
    training_record_payload,
    validate_error,
    validate_paginated,
    validate_success,
    water_body_payload,
    watercraft_payload,
)

UNKNOWN_WATER_BODY_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_WATERCRAFT_ID = "00000000-0000-4000-8000-000000000002"
CLIENT_SUPPLIED_ID = "00000000-0000-4000-8000-000000000009"


class TestWaterBodyCreationAndListing:
    """A registration echoes its declared inputs and invents no history."""

    def test_creation_persists_every_input_and_starts_both_counters_at_zero(self):
        """The two detection counters are 0 and the drainage parent is null.

        PRD: "Registering a water body captures its public `name`, the two-letter
        `state_code` of the state it sits in — exactly two uppercase letters — and
        its physical `water_body_class`, one of `LAKE`, `RESERVOIR`, `RIVER` or
        `CANAL`."  PRD: "Both detection counters, `detection_count` and
        `live_detection_count`, start at 0 and are never written by a client."

        Design: Corner/entities/creation_water_body_persists_inputs_and_zero_counters
        """
        set_clock(DEFAULT_CLOCK_UTC)

        response = api_client.create_water_body(
            water_body_payload(
                name="Flathead Lake", state_code="MT", water_body_class="LAKE",
                risk_tier="HIGH", infestation_status="CLEAN",
            ),
            PROGRAM_ADMIN,
        )

        data = validate_success(response, 201)
        assert data["name"] == "Flathead Lake"
        assert data["state_code"] == "MT"
        assert data["water_body_class"] == "LAKE"
        assert data["risk_tier"] == "HIGH"
        assert data["infestation_status"] == "CLEAN"
        assert data["detection_count"] == 0
        assert data["live_detection_count"] == 0
        assert data["downstream_of_water_body_id"] is None
        assert_water_body(data)
        assert_common_fields(data, "WaterBody")
        body = response.json()
        assert body["response_type"] == "object"
        assert_envelope_meta(body)

    def test_listing_reports_the_filtered_total_and_the_has_more_flag(self):
        """Three rows paginate 2 + 1, and a risk_tier filter narrows the count first.

        PRD: "The `meta` object of a list response carries `limit` (the effective
        page size for this response), `offset` (the effective starting position),
        `total_count` (the number of rows matching the filter before pagination is
        applied), and `has_more` (true when rows remain beyond this page)."  PRD:
        "Filter query parameters narrow the matching set before `total_count` is
        computed, so a filtered list reports the size of the filtered set, not of
        the whole collection."

        Design: Corner/entities/listing_water_bodies_paginates_with_total_count_and_has_more
        """
        set_clock(DEFAULT_CLOCK_UTC)
        create_water_body(name="Flathead Lake", water_body_class="LAKE", risk_tier="HIGH")
        create_water_body(
            name="Hauser Reservoir", water_body_class="RESERVOIR", risk_tier="MODERATE"
        )
        third = create_water_body(
            name="Jefferson River", water_body_class="RIVER", risk_tier="LOW"
        )

        first_page, first_meta = validate_paginated(
            api_client.list_water_bodies(PROGRAM_ADMIN, {"limit": 2, "offset": 0})
        )

        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2 and first_meta["offset"] == 0
        second_page, second_meta = validate_paginated(
            api_client.list_water_bodies(PROGRAM_ADMIN, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        filtered, filtered_meta = validate_paginated(
            api_client.list_water_bodies(PROGRAM_ADMIN, {"risk_tier": "LOW"})
        )
        assert [row["id"] for row in filtered] == [third["id"]]
        assert filtered_meta["total_count"] == 1
        assert filtered_meta["has_more"] is False

    def test_an_unknown_water_body_id_in_the_path_is_a_typed_404(self):
        """The miss reports ERR_WATER_BODY_NOT_FOUND, never an empty 200.

        PRD: "The identifier reported names the *kind* of thing that was missing:
        `ERR_WATER_BODY_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
        `ERR_INSPECTOR_NOT_FOUND`, `ERR_WATERCRAFT_NOT_FOUND`,
        `ERR_INSPECTION_RECORD_NOT_FOUND`, `ERR_DECON_ORDER_NOT_FOUND`,
        `ERR_QUARANTINE_ORDER_NOT_FOUND`, `ERR_DETECTION_REPORT_NOT_FOUND`,
        `ERR_CAMPAIGN_NOT_FOUND` and `ERR_RECIPROCITY_AGREEMENT_NOT_FOUND` — each
        HTTP 404."

        Design: Corner/entities/not_found_water_body_retrieval_returns_err_water_body_not_found
        """
        set_clock(DEFAULT_CLOCK_UTC)

        response = api_client.get_water_body(UNKNOWN_WATER_BODY_ID, PROGRAM_ADMIN)

        error = validate_error(response, ApiErrorId.ERR_WATER_BODY_NOT_FOUND, 404)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip()


class TestWatercraftRegistryShape:
    """The registry mints its own identity and refuses an incomplete declaration."""

    def test_an_unknown_vessel_id_reports_the_vessel_specific_404(self):
        """A populated registry still 404s the unknown id and serves the known one.

        PRD: "Every resource named in the path exists, resolved left to right —
        otherwise the matching 404 from the family listed in §2.6."

        Design: Corner/entities/not_found_watercraft_retrieval_returns_err_watercraft_not_found
        """
        set_clock(DEFAULT_CLOCK_UTC)
        vessel = register_watercraft(registration_number="MT-1001", hull_length_ft=18)

        response = api_client.get_watercraft(UNKNOWN_WATERCRAFT_ID, PROGRAM_ADMIN)

        validate_error(response, ApiErrorId.ERR_WATERCRAFT_NOT_FOUND, 404)
        assert validate_success(
            api_client.get_watercraft(vessel["id"], PROGRAM_ADMIN), 200
        )["id"] == vessel["id"]

    def test_registration_without_a_hull_length_is_rejected_not_defaulted(self):
        """hull_length_ft has no default, so its omission is a 400.

        PRD: "A vessel is registered with its state `registration_number`
        (non-empty, at most 32 characters, and unique across the whole registry — a
        repeat is rejected with `ERR_DUPLICATE_IDENTIFIER`), the two-letter
        `home_state_code` of the state it is registered in, its hull class in
        `vessel_type`, and its `hull_length_ft` in feet, which must be greater than
        zero."

        Design: Corner/entities/required_fields_watercraft_creation_without_hull_length_rejected
        """
        set_clock(DEFAULT_CLOCK_UTC)
        payload = watercraft_payload(registration_number="MT-1002")
        del payload["hull_length_ft"]

        response = api_client.create_watercraft(payload, PROGRAM_ADMIN)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        rows, meta = validate_paginated(
            api_client.list_watercraft(PROGRAM_ADMIN, {"registration_number": "MT-1002"})
        )
        assert rows == [] and meta["total_count"] == 0
        payload["hull_length_ft"] = 18
        accepted = validate_success(
            api_client.create_watercraft(payload, PROGRAM_ADMIN), 201
        )
        assert accepted["registration_number"] == "MT-1002"

    def test_a_client_supplied_identity_and_version_are_ignored(self):
        """The row lives under a server-minted id at the logical clock instant.

        PRD: "Every resource the service persists is identified by `id`, a
        server-minted UUID carrying no type prefix of any kind. Clients never
        supply `id`; a client-supplied `id` in a request body is one of the ignored
        unknown fields described in §2.11."  PRD: "`version`, an integer that
        starts at 1 when the row is created and increments by exactly 1 on each
        mutation of that row."

        Design: Corner/entities/system_fields_watercraft_identity_and_version_input_ignored
        """
        set_clock(DEFAULT_CLOCK_UTC)

        data = validate_success(
            api_client.create_watercraft(
                watercraft_payload(
                    registration_number="MT-1003", hull_length_ft=20,
                    id=CLIENT_SUPPLIED_ID, version=77,
                    created_at="1999-01-01T00:00:00Z",
                ),
                PROGRAM_ADMIN,
            ),
            201,
        )

        assert data["id"] != CLIENT_SUPPLIED_ID
        assert data["version"] == 1
        assert_instant_equals(data["created_at"], DEFAULT_CLOCK_UTC, "created_at")
        assert_watercraft(data)
        validate_error(
            api_client.get_watercraft(CLIENT_SUPPLIED_ID, PROGRAM_ADMIN),
            ApiErrorId.ERR_WATERCRAFT_NOT_FOUND, 404,
        )
        assert validate_success(
            api_client.get_watercraft(data["id"], PROGRAM_ADMIN), 200
        )["registration_number"] == "MT-1003"

    def test_a_bad_enum_member_and_a_zero_hull_length_each_fail_on_their_own(self):
        """vessel_type SAILBOAT and hull_length_ft 0 are separate 400s.

        PRD: "Every required field is present; every supplied value matches its
        declared type and, for enumerated fields, is one of the declared members;
        and every numeric and ordering constraint holds. Specifically: `hours` is
        greater than 0, `standing_water_ml` is at least 0, `decon_bay_count` is at
        least 0, `seal_stock_initial_count` is at least 0, `hull_length_ft` is
        greater than 0, `budget_cents` is greater than 0, `impressions` is at least
        0, `max_seal_age_hours` is greater than 0, `water_temp_f` is greater than
        0, `pressure_psi` is greater than 0, `dwell_seconds` is greater than 0,
        `closes_at` is strictly later than `opens_at`, and `end_at` is strictly
        later than `start_at`."

        Design: Corner/entities/type_constraints_bad_enum_and_out_of_range_number_rejected
        """
        set_clock(DEFAULT_CLOCK_UTC)

        bad_enum = api_client.create_watercraft(
            watercraft_payload(
                registration_number="MT-1004", vessel_type="SAILBOAT", hull_length_ft=18
            ),
            PROGRAM_ADMIN,
        )

        validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST, 400)
        validate_error(
            api_client.create_watercraft(
                watercraft_payload(registration_number="MT-1004", hull_length_ft=0),
                PROGRAM_ADMIN,
            ),
            ApiErrorId.ERR_INVALID_REQUEST, 400,
        )
        rows, meta = validate_paginated(
            api_client.list_watercraft(PROGRAM_ADMIN, {"registration_number": "MT-1004"})
        )
        assert rows == [] and meta["total_count"] == 0
        assert validate_success(
            api_client.create_watercraft(
                watercraft_payload(registration_number="MT-1004", hull_length_ft=18),
                PROGRAM_ADMIN,
            ),
            201,
        )["hull_length_ft"] == 18


UNKNOWN_INSPECTOR_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_STATION_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_VESSEL_ID = "00000000-0000-4000-8000-000000000005"


class TestStationInventoryAndDefaults:
    """A station's ledgers start empty and its optional declarations have defaults."""

    def test_retrieval_reports_the_seeded_seal_stock_and_the_empty_ledgers(self):
        """An opened station reads back stock 3, no circulation and no fees.

        PRD: "`seal_stock_count` is set equal to `seal_stock_initial_count` — the
        same initialisation is applied again at the moment the station first leaves
        `PLANNED`, so the two are always consistent — while
        `seals_in_circulation_count`, `seals_retired_count`,
        `certified_inspector_count`, `collected_fees_cents`, `refunded_fees_cents`
        and `campaign_allocated_cents` all start at 0."  PRD: "The derived flag
        `decon_service_available` starts false, because no certified inspector is
        posted yet."

        Design: Corner/entities/retrieval_station_returns_stored_inventory_and_derived_fields
        """
        set_clock(DEFAULT_CLOCK_UTC)
        water_body = create_water_body(name="Flathead Lake", risk_tier="HIGH")
        station = create_and_open_station(
            water_body["id"], name="Polson Access", mandatory_inspection=True,
            decon_bay_count=2, hot_water_capable=True, seal_stock_initial_count=3,
        )

        data = validate_success(api_client.get_station(station["id"], PROGRAM_ADMIN), 200)

        assert data["status"] == "OPEN"
        assert data["station_type"] == "WATERBODY_ACCESS"
        assert data["water_body_id"] == water_body["id"]
        assert data["corridor_route_code"] is None
        assert data["seal_stock_initial_count"] == 3
        assert data["seal_stock_count"] == 3
        assert data["seals_in_circulation_count"] == 0
        assert data["seals_retired_count"] == 0
        assert data["certified_inspector_count"] == 0
        assert data["decon_service_available"] is False
        assert data["collected_fees_cents"] == 0
        assert data["refunded_fees_cents"] == 0
        assert data["campaign_allocated_cents"] == 0
        assert_station(data)

    def test_every_omitted_optional_declaration_falls_to_its_declared_default(self):
        """A bare water body is MODERATE and CLEAN; a bare station is empty and PLANNED.

        PRD: "Two program judgements are recorded at the same time and may be left
        to their defaults: `risk_tier`, one of `HIGH`, `MODERATE` or `LOW`,
        defaulting to `MODERATE`; and `infestation_status`, one of `CLEAN`,
        `SUSPECT` or `CONFIRMED_INFESTED`, defaulting to `CLEAN`."  PRD: "Beyond
        `name` and the siting pair, station creation accepts four operational
        declarations, all optional: `mandatory_inspection`, false unless stated,
        marking a station where stopping is compulsory rather than voluntary;
        `decon_bay_count`, 0 unless stated, the number of physical decontamination
        bays; `hot_water_capable`, false unless stated, true when the site has a
        hot-water pressure unit; and `seal_stock_initial_count`, 0 unless stated,
        the number of numbered seals physically delivered at commissioning."

        Design: Corner/entities/defaults_station_optional_fields_default_when_omitted
        """
        set_clock(DEFAULT_CLOCK_UTC)
        water_body = create_water_body(name="Canyon Ferry", water_body_class="RESERVOIR")
        assert water_body["risk_tier"] == "MODERATE"
        assert water_body["infestation_status"] == "CLEAN"

        data = validate_success(
            api_client.create_station(
                station_payload(
                    name="Canyon Ferry Access", station_type="WATERBODY_ACCESS",
                    water_body_id=water_body["id"],
                ),
                PROGRAM_ADMIN,
            ),
            201,
        )

        assert data["mandatory_inspection"] is False
        assert data["decon_bay_count"] == 0
        assert data["hot_water_capable"] is False
        assert data["seal_stock_initial_count"] == 0
        assert data["status"] == "PLANNED"
        assert data["corridor_route_code"] is None
        assert data["seal_stock_count"] == 0
        assert data["decon_service_available"] is False

    def test_an_inverted_or_empty_hours_window_is_a_400_not_an_overlap_409(self):
        """closes_at must be strictly later, so neither shape reaches the overlap check.

        PRD: "Operating hours are declared one window at a time, each window naming
        the station in `station_id` and carrying an inclusive `opens_at` and an
        exclusive `closes_at` as ISO 8601 UTC instants with three fractional digits,
        plus an optional `staffing_level` of `SINGLE` or `DOUBLE` that defaults to
        `SINGLE`. `closes_at` must be strictly later than `opens_at`."

        Design: Corner/entities/type_constraints_hours_window_ordering_rejected
        """
        set_clock(DEFAULT_CLOCK_UTC)
        water_body = create_water_body(name="Flathead Lake", risk_tier="HIGH")
        station = create_station(name="Polson Access", water_body_id=water_body["id"])

        inverted = api_client.create_station_hours(
            station["id"],
            station_hours_payload(
                opens_at="2026-09-01T00:00:00Z", closes_at="2026-07-01T00:00:00Z"
            ),
            PROGRAM_ADMIN,
        )

        validate_error(inverted, ApiErrorId.ERR_INVALID_REQUEST, 400)
        validate_error(
            api_client.create_station_hours(
                station["id"],
                station_hours_payload(
                    opens_at="2026-07-01T00:00:00Z", closes_at="2026-07-01T00:00:00Z"
                ),
                PROGRAM_ADMIN,
            ),
            ApiErrorId.ERR_INVALID_REQUEST, 400,
        )
        rows, meta = validate_paginated(
            api_client.list_station_hours(station["id"], PROGRAM_ADMIN)
        )
        assert rows == [] and meta["total_count"] == 0
        assert fetch_station_hours(station["id"]) == []


class TestInspectionRecordCreationShape:
    """A new record derives its own numbers and resolves its own foreign keys."""

    def test_client_supplied_scores_and_fees_are_ignored_not_honored(self):
        """risk_score 99, risk_band EXTREME and total_fee_cents 1 all land at their floors.

        PRD: "Fields the service does not recognise, and fields it derives for
        itself, are silently ignored when a client supplies them rather than being
        rejected."  PRD: "`risk_score`, `advisory_risk_score`, `dry_credit_points`,
        `reciprocity_credit_points`, `inspection_fee_cents`, `decon_fee_cents`,
        `surcharge_cents`, `total_fee_cents`, `fee_refunded_cents` and
        `penalty_cents` all sit at their declared defaults of 0"

        Design: Corner/entities/computed_fields_record_scores_client_input_ignored
        """
        ctx = setup_program(risk_tier="HIGH", infestation_status="CLEAN")
        vessel = add_watercraft(ctx)
        set_clock("2026-08-05T09:00:00Z")

        data = validate_success(
            api_client.create_inspection_record(
                inspection_record_payload(
                    ctx["station"]["id"], vessel["id"], "2026-08-05T09:00:00Z",
                    risk_score=99, risk_band="EXTREME", total_fee_cents=1,
                    inspector_id="someone-else",
                ),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            201,
        )

        assert data["risk_score"] == 0
        assert data["advisory_risk_score"] == 0
        assert data["risk_band"] == "LOW"
        assert data["total_fee_cents"] == 0
        assert data["inspection_fee_cents"] == 0
        assert data["decon_fee_cents"] == 0
        assert data["surcharge_cents"] == 0
        assert data["inspector_id"] == ctx["inspector_a"]["id"]
        assert data["inspection_status"] == "INITIATED"
        assert data["enforcement_status"] == "NONE"
        assert_inspection_record(data)

    def test_each_unresolvable_body_key_reports_the_entity_that_missed(self):
        """An unknown station_id is ERR_STATION_NOT_FOUND, an unknown vessel its own 404.

        PRD: "Every foreign key supplied in a request body must resolve to an
        existing row before any business rule is evaluated: `station_id`,
        `watercraft_id`, `prior_water_body_id`, `home_station_id`,
        `last_water_body_id`, `target_water_body_id`, `inspection_record_id`,
        `downstream_of_water_body_id` and `water_body_id` are all checked this way"

        Design: Corner/entities/foreign_key_references_validated_on_record_creation_not_found
        """
        ctx = setup_program(risk_tier="HIGH", infestation_status="CLEAN")
        vessel = add_watercraft(ctx)
        set_clock("2026-08-05T09:00:00Z")
        headers = make_inspector_headers(ctx["inspector_a"]["id"])

        unknown_station = api_client.create_inspection_record(
            inspection_record_payload(
                UNKNOWN_STATION_ID, vessel["id"], "2026-08-05T09:00:00Z"
            ),
            headers,
        )

        validate_error(unknown_station, ApiErrorId.ERR_STATION_NOT_FOUND, 404)
        validate_error(
            api_client.create_inspection_record(
                inspection_record_payload(
                    ctx["station"]["id"], UNKNOWN_VESSEL_ID, "2026-08-05T09:00:00Z"
                ),
                headers,
            ),
            ApiErrorId.ERR_WATERCRAFT_NOT_FOUND, 404,
        )
        accepted = validate_success(
            api_client.create_inspection_record(
                inspection_record_payload(
                    ctx["station"]["id"], vessel["id"], "2026-08-05T09:00:00Z"
                ),
                headers,
            ),
            201,
        )
        assert accepted["inspection_status"] == "INITIATED"
        rows, meta = validate_paginated(
            api_client.list_inspection_records(
                PROGRAM_ADMIN, {"station_id": ctx["station"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [accepted["id"]]


class TestTrainingRecordIsAnImmutableAuditRow:
    """A logged module carries no revision counter and hangs off a real inspector."""

    def test_a_logged_module_carries_no_version_and_no_updated_at(self):
        """Create and list both omit the two mutation fields.

        PRD: "`TrainingRecord` is the single exception. A training record is an
        immutable audit row: once a module completion is logged it is never edited,
        so a `TrainingRecord` carries only `id` and `created_at`. It has no
        `updated_at` field and no `version` field at all, and there is no operation
        anywhere in the API that updates one."

        Design: Corner/entities/immutability_training_record_exposes_no_version_and_no_update_path
        """
        set_clock(DEFAULT_CLOCK_UTC)
        water_body = create_water_body(name="Flathead Lake", risk_tier="HIGH")
        station = create_station(name="Polson Access", water_body_id=water_body["id"])
        inspector = enroll_inspector(station["id"], full_name="Ada Field")

        data = validate_success(
            api_client.create_training_record(
                inspector["id"],
                training_record_payload(
                    8, True, module_code="AIS-101", completed_at="2026-07-15T12:00:00Z"
                ),
                TRAINING_OFFICER,
            ),
            201,
        )

        assert data["hours"] == 8
        assert data["passed"] is True
        assert_instant_equals(data["completed_at"], "2026-07-15T12:00:00Z", "completed_at")
        assert "version" not in data
        assert "updated_at" not in data
        assert_training_record(data)
        rows, meta = validate_paginated(
            api_client.list_training_records(inspector["id"], TRAINING_OFFICER)
        )
        assert meta["total_count"] == 1 and len(rows) == 1
        assert "version" not in rows[0]
        promoted = fetch_inspector(inspector["id"])
        assert float(promoted["training_hours_total"]) == 8.00
        assert promoted["certification_level"] == "LEVEL_1"

    def test_logging_against_an_unknown_inspector_is_a_parent_404(self):
        """The path parent is resolved first, so nothing leaks onto the real inspector.

        PRD: "Where a path contains more than one identifier, the identifiers are
        resolved strictly left to right, and the first one that resolves to nothing
        determines the error. A request against the hours of a station that does not
        exist therefore fails with `ERR_STATION_NOT_FOUND` (HTTP 404) regardless of
        anything else in the request, and a request against the training records of
        a non-existent inspector fails with `ERR_INSPECTOR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/parent_relationships_training_record_for_unknown_inspector_not_found
        """
        set_clock(DEFAULT_CLOCK_UTC)
        water_body = create_water_body(name="Flathead Lake", risk_tier="HIGH")
        station = create_station(name="Polson Access", water_body_id=water_body["id"])
        inspector = enroll_inspector(station["id"], full_name="Ada Field")

        response = api_client.create_training_record(
            UNKNOWN_INSPECTOR_ID, training_record_payload(8, True, module_code="AIS-101"),
            TRAINING_OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_INSPECTOR_NOT_FOUND, 404)
        rows, meta = validate_paginated(
            api_client.list_training_records(inspector["id"], TRAINING_OFFICER)
        )
        assert rows == [] and meta["total_count"] == 0
        untouched = fetch_inspector(inspector["id"])
        assert float(untouched["training_hours_total"]) == 0
        assert untouched["certification_level"] == "TRAINEE"
