"""Entity shapes: envelopes, defaults, server-owned fields and referential errors."""

import pytest

from test_helpers import (
    COMPLIANCE,
    CONTRACTS,
    PLANT,
    QUALITY,
    SALES,
    TX_BID_CONFIG,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_append_only_fields,
    assert_bus_model,
    assert_common_fields,
    assert_envelope_meta,
    assert_pagination_meta,
    assert_response_type,
    assert_state_spec_profile,
    bid_payload,
    bid_revision_payload,
    bus_model_payload,
    create_bus_model,
    create_solicitation,
    diesel_package_payload,
    read_bid,
    setup_tx_catalogue,
    spec_profile_payload,
    type_a_mini_model_payload,
    type_c_alt_model_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The Texas equipment level on the base body: eight-lamp system, crossing arm and
# crossview mirrors over 71 seats and five exits.
TX_BID_PRICE_CENTS = 14_641_571
# The same bid with one seat added, re-priced at round one.
TX_ROUND_ONE_PRICE_CENTS = 14_676_890

NOT_FOUND_READS = [
    ("get_state_spec_profile", COMPLIANCE, ApiErrorId.ERR_SPEC_PROFILE_NOT_FOUND),
    ("get_bus_model", COMPLIANCE, ApiErrorId.ERR_BUS_MODEL_NOT_FOUND),
    ("get_propulsion_package", COMPLIANCE, ApiErrorId.ERR_PROPULSION_PACKAGE_NOT_FOUND),
    ("get_solicitation", SALES, ApiErrorId.ERR_SOLICITATION_NOT_FOUND),
    ("get_bid", SALES, ApiErrorId.ERR_BID_NOT_FOUND),
    ("get_contract_order", CONTRACTS, ApiErrorId.ERR_CONTRACT_ORDER_NOT_FOUND),
    ("get_production_line", PLANT, ApiErrorId.ERR_PRODUCTION_LINE_NOT_FOUND),
    ("get_build_slot", PLANT, ApiErrorId.ERR_BUILD_SLOT_NOT_FOUND),
    ("get_bus_unit", PLANT, ApiErrorId.ERR_BUS_UNIT_NOT_FOUND),
    ("get_test_bay", QUALITY, ApiErrorId.ERR_TEST_BAY_NOT_FOUND),
    ("get_quality_test", QUALITY, ApiErrorId.ERR_QUALITY_TEST_NOT_FOUND),
    ("get_dealer", CONTRACTS, ApiErrorId.ERR_DEALER_NOT_FOUND),
    ("get_recall_campaign", COMPLIANCE, ApiErrorId.ERR_RECALL_CAMPAIGN_NOT_FOUND),
    ("get_remedy_task", COMPLIANCE, ApiErrorId.ERR_REMEDY_TASK_NOT_FOUND),
]


class TestCatalogueCreationAndRetrieval:
    """A registered body reads back exactly as it was written."""

    def test_a_created_bus_model_comes_back_fully_populated(self):
        """The create response carries the envelope, every input echoed and the
        common system fields at version 1.

        PRD: "An operation that brings a new resource into existence returns **201
        Created** with that new resource in `data`".
        PRD: "`version`, an integer that begins at 1 when the record is created and
        increments by exactly 1 on every mutation."

        Design: Corner/entities/bus_model_creation_returns_populated_row_in_success_envelope
        """
        response = api_client.create_bus_model(bus_model_payload(), COMPLIANCE)
        data = validate_success(response, 201)
        assert_envelope_meta(response.json())
        assert_response_type(response, "object")
        assert_bus_model(data)
        assert_common_fields(data, expected_version=1)

        assert data["model_code"] == "TYPE_C_CONV"
        assert data["body_class"] == "TYPE_C"
        assert data["base_seat_capacity"] == 71
        assert data["base_emergency_exit_count"] == 5
        assert data["base_price_cents"] == 12_750_000
        assert data["body_joint_strength_kn"] == 58.0
        assert data["max_battery_bays"] == 6
        assert data["curb_weight_lb"] == 21_500

    def test_any_role_reads_the_model_back_unchanged(self):
        """A read by a role that could never have created the row returns the same
        values and does not move the version.

        PRD: "every read endpoint in the system is open to all of them, and every
        write endpoint is restricted."

        Design: Corner/entities/bus_model_retrieval_by_id_matches_the_created_row
        """
        created = create_bus_model()
        response = api_client.get_bus_model(created["id"], PLANT)
        data = validate_success(response)
        assert_response_type(response, "object")

        assert data["model_code"] == "TYPE_C_CONV"
        assert data["base_price_cents"] == 12_750_000
        assert data["body_joint_strength_kn"] == 58.0
        assert data["version"] == 1
        assert data["id"] == created["id"]
        assert data["created_at"] == created["created_at"]


class TestRequestShapeFailures:
    """A malformed request is rejected before any business rule is consulted, and
    it writes nothing."""

    def test_a_missing_curb_weight_is_a_shape_failure(self):
        """The curb weight feeds the rollover minimum and is required, so omitting
        it is refused and no row is created.

        PRD: "Request shape — every required input field present; every field of
        its declared type; every enum value within its declared set ...
        `ERR_INVALID_REQUEST` (400), on every endpoint."

        Design: Corner/entities/bus_model_create_missing_required_curb_weight_is_invalid_request
        """
        payload = bus_model_payload()
        del payload["curb_weight_lb"]

        response = api_client.create_bus_model(payload, COMPLIANCE)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        assert_response_type(response, "error")
        assert_envelope_meta(response.json())

        _, meta = validate_paginated(api_client.list_bus_models(COMPLIANCE))
        assert meta["total_count"] == 0

    def test_an_out_of_range_enum_and_an_out_of_range_fraction_are_both_refused(self):
        """A propulsion type outside the declared set and a derate fraction of one
        are both shape failures rather than domain errors.

        PRD: "Percentage and rate inputs preserve the precision they were supplied
        with: `cold_weather_derate_pct` and `reserve_floor_pct` are fractions of one
        carried to four decimal places, each at least 0 and strictly less than 1."

        Design: Corner/entities/propulsion_package_create_with_invalid_enum_propulsion_type_rejected
        """
        model = create_bus_model()

        bad_enum = diesel_package_payload(
            model["id"], package_code="HYD-01", propulsion_type="HYDROGEN"
        )
        validate_error(
            api_client.create_propulsion_package(bad_enum, COMPLIANCE),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        bad_fraction = diesel_package_payload(
            model["id"], package_code="DSL-BAD", cold_weather_derate_pct=1.0
        )
        validate_error(
            api_client.create_propulsion_package(bad_fraction, COMPLIANCE),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        _, meta = validate_paginated(api_client.list_propulsion_packages(COMPLIANCE))
        assert meta["total_count"] == 0


class TestServerOwnedFieldsAndDefaults:
    """What the client may state and what the server decides are different sets."""

    def test_a_profile_with_only_its_mandates_materialises_every_default(self):
        """A state that legislates no extras gets four false safety flags, standard
        mirrors, flat terrain and a draft status.

        PRD: "A profile is created in `DRAFT`, with `published_at` and
        `superseded_by_profile_id` both empty".

        Design: Corner/entities/state_spec_profile_defaults_applied_when_optional_flags_omitted
        """
        response = api_client.create_state_spec_profile(
            spec_profile_payload(), COMPLIANCE
        )
        data = validate_success(response, 201)
        assert_state_spec_profile(data)

        assert data["status"] == "DRAFT"
        assert data["published_at"] in (None, "")
        assert data["superseded_by_profile_id"] in (None, "")
        assert data["requires_eight_lamp_system"] is False
        assert data["requires_crossing_arm"] is False
        assert data["requires_lap_shoulder_belts"] is False
        assert data["requires_rollover_protection"] is False
        assert data["requires_joint_strength_test"] is False
        assert data["required_mirror_config"] == "STANDARD"
        assert data["terrain_class"] == "FLAT"
        assert data["min_seat_capacity"] == 24
        assert data["min_emergency_exit_count"] == 3
        assert data["min_joint_strength_kn"] == 35.0
        assert data["required_route_range_mi"] == 300.0

    def test_posted_status_round_and_price_are_all_ignored_on_a_bid(self):
        """A client that states the bid's own lifecycle fields is overruled: the bid
        opens in draft at round zero with the price the server computed.

        PRD: "`provisional_unit_price_cents` is the bid's own price for one bus,
        computed at creation and recomputed on every revision".
        PRD: "`evaluated_spec_profile_id` records the profile the verdict was
        computed against".

        Design: Corner/entities/bid_system_fields_are_server_owned_and_client_extra_field_ignored
        """
        catalogue = setup_tx_catalogue()
        solicitation = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-TX-090",
            required_delivery_date="2026-10-05",
            price_cap_cents_per_unit=20_000_000,
        )
        payload = bid_payload(
            solicitation["id"],
            catalogue["model"]["id"],
            catalogue["package"]["id"],
            status="AWARDED",
            revision_round=7,
            provisional_unit_price_cents=1,
            submitted_by_user_id="sales-99",
            **TX_BID_CONFIG,
        )

        data = validate_success(api_client.create_bid(payload, SALES), 201)
        assert data["status"] == "DRAFT"
        assert data["revision_round"] == 0
        assert data["provisional_unit_price_cents"] == TX_BID_PRICE_CENTS
        assert data["submitted_at"] in (None, "")
        assert data["submitted_by_user_id"] in (None, "")
        assert data["evaluated_spec_profile_id"] == catalogue["profile"]["id"]
        assert data["version"] == 1


class TestLookupsAndListings:
    """Unknown identifiers name the entity that was missing, and filters narrow the
    population before a page is cut from it."""

    @pytest.mark.parametrize("method_name,headers,error_id", NOT_FOUND_READS)
    def test_each_collection_reports_its_own_not_found_code(
        self, method_name, headers, error_id
    ):
        """The same syntactically valid unknown identifier reports a different code
        on each collection.

        PRD: "The profile named by the path exists: `ERR_SPEC_PROFILE_NOT_FOUND`
        (404)".

        Design: Corner/entities/unknown_ids_on_every_get_by_id_return_entity_specific_not_found
        """
        response = getattr(api_client, method_name)(NON_EXISTENT_UUID, headers)
        validate_error(response, error_id.value, 404)
        assert_response_type(response, "error")

    def test_the_body_class_filter_narrows_the_population_before_the_page(self):
        """Two Type C bodies and one Type A body: a filtered second page returns one
        row out of a total of two, not out of three.

        PRD: "`total_count` is the number of records matching the request's filters
        before pagination is applied and `has_more` indicates whether records remain
        beyond the current page. Filter parameters narrow the matched set before
        `total_count` is computed."

        Design: Corner/entities/bus_model_listing_filters_by_body_class_and_paginates
        """
        create_bus_model()
        second_type_c = create_bus_model(type_c_alt_model_payload())
        type_a = create_bus_model(type_a_mini_model_payload())

        rows, meta = validate_paginated(
            api_client.list_bus_models(
                SALES, {"body_class": "TYPE_C", "limit": 1, "offset": 1}
            )
        )
        assert_pagination_meta(meta, limit=1, offset=1, total_count=2, has_more=False)
        assert len(rows) == 1
        assert rows[0]["id"] == second_type_c["id"]
        assert rows[0]["id"] != type_a["id"]

        every, all_meta = validate_paginated(api_client.list_bus_models(SALES))
        assert_pagination_meta(all_meta, limit=10, offset=0, total_count=3,
                              has_more=False)
        assert len(every) == 3

    def test_an_appended_revision_is_frozen_when_the_next_round_supersedes_it(self):
        """Round one keeps its seat count and its price after round two lands, while
        the parent bid moves on.

        PRD: "A `BidRevision` is an immutable event record and carries only `id` and
        `created_at` — it has neither `updated_at` nor `version`."
        PRD: "The one field of a revision that changes after creation,
        `is_superseded`, is flipped by the arrival of a later round on the same bid".

        Design: Corner/entities/bid_revision_snapshots_are_immutable_once_superseded
        """
        catalogue = setup_tx_catalogue()
        solicitation = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-TX-091",
            buyer_name="Katy ISD",
            unit_count=3,
            price_cap_cents_per_unit=20_000_000,
        )
        config = dict(TX_BID_CONFIG)
        config["unit_count"] = 3
        bid = validate_success(
            api_client.create_bid(
                bid_payload(
                    solicitation["id"],
                    catalogue["model"]["id"],
                    catalogue["package"]["id"],
                    **config,
                ),
                SALES,
            ),
            201,
        )

        round_config = dict(TX_BID_CONFIG)
        round_config.pop("offered_seat_capacity")
        first = validate_success(
            api_client.create_bid_revision(
                bid["id"],
                bid_revision_payload(
                    bid["version"], offered_seat_capacity=72, note="round 1",
                    **round_config,
                ),
                SALES,
            ),
            201,
        )
        assert_append_only_fields(first)
        assert first["unit_price_cents"] == TX_ROUND_ONE_PRICE_CENTS

        second = validate_success(
            api_client.create_bid_revision(
                bid["id"],
                bid_revision_payload(
                    read_bid(bid["id"])["version"], offered_seat_capacity=73,
                    note="round 2", **round_config,
                ),
                SALES,
            ),
            201,
        )

        rows, meta = validate_paginated(
            api_client.list_bid_revisions(bid["id"], SALES)
        )
        assert meta["total_count"] == 3
        assert [row["round_index"] for row in rows] == [0, 1, 2]
        frozen = next(row for row in rows if row["id"] == first["id"])
        assert frozen["offered_seat_capacity"] == 72
        assert frozen["unit_price_cents"] == TX_ROUND_ONE_PRICE_CENTS
        assert frozen["is_superseded"] is True
        assert frozen["round_index"] == 1
        latest = next(row for row in rows if row["id"] == second["id"])
        assert latest["is_superseded"] is False
        assert latest["round_index"] == 2
        assert read_bid(bid["id"])["offered_seat_capacity"] == 73


class TestReferentialIntegrity:
    """Existence is checked per identifier field, and it outranks every business
    rule."""

    def test_each_bogus_foreign_key_names_its_own_entity(self):
        """One bid body reports three different codes depending on which identifier
        is unknown, and none of the attempts writes a row.

        PRD: "The solicitation named in the request body exists:
        `ERR_SOLICITATION_NOT_FOUND` (404)".

        Design: Corner/entities/bid_create_with_unknown_foreign_keys_reports_the_owning_entity_not_found
        """
        catalogue = setup_tx_catalogue()
        solicitation = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-TX-092",
            buyer_name="Frisco ISD",
            price_cap_cents_per_unit=20_000_000,
        )
        model_id = catalogue["model"]["id"]
        package_id = catalogue["package"]["id"]

        cases = [
            (
                bid_payload(NON_EXISTENT_UUID, model_id, package_id, **TX_BID_CONFIG),
                ApiErrorId.ERR_SOLICITATION_NOT_FOUND,
            ),
            (
                bid_payload(
                    solicitation["id"], NON_EXISTENT_UUID, package_id, **TX_BID_CONFIG
                ),
                ApiErrorId.ERR_BUS_MODEL_NOT_FOUND,
            ),
            (
                bid_payload(
                    solicitation["id"], model_id, NON_EXISTENT_UUID, **TX_BID_CONFIG
                ),
                ApiErrorId.ERR_PROPULSION_PACKAGE_NOT_FOUND,
            ),
        ]
        for payload, error_id in cases:
            validate_error(
                api_client.create_bid(payload, SALES), error_id.value, 404
            )

        _, meta = validate_paginated(
            api_client.list_bids(SALES, {"solicitation_id": solicitation["id"]})
        )
        assert meta["total_count"] == 0

    def test_every_operation_under_an_unknown_bid_reports_the_parent(self):
        """The revisions listing, the submit and the send-back all fail on the
        parent's absence rather than on a state or version check.

        PRD: "The bid named by the path exists: `ERR_BID_NOT_FOUND` (404), on
        reading a bid, listing or appending its revisions, submitting it, requesting
        a revision of it and awarding it."

        Design: Corner/entities/bid_revisions_on_unknown_parent_bid_return_bid_not_found
        """
        validate_error(
            api_client.list_bid_revisions(NON_EXISTENT_UUID, SALES),
            ApiErrorId.ERR_BID_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.submit_bid(NON_EXISTENT_UUID, SALES),
            ApiErrorId.ERR_BID_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.request_bid_revision(NON_EXISTENT_UUID, CONTRACTS),
            ApiErrorId.ERR_BID_NOT_FOUND.value,
            404,
        )
        _, meta = validate_paginated(api_client.list_bids(SALES))
        assert meta["total_count"] == 0
