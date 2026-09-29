"""Error identity and rejection order: which of two broken rules names the failure."""

from test_helpers import (
    CLOCK_START_UTC,
    COMPLIANCE,
    CONTRACTS,
    PLANT,
    ApiErrorId,
    api_client,
    assert_bus_unit,
    assert_kit_pool_conserved,
    assert_recall_campaign,
    assert_same_instant,
    bus_model_payload,
    create_campaign,
    create_dealer,
    create_legacy_unit,
    launch_campaign,
    legacy_fleet_record_payload,
    list_tasks,
    read_campaign,
    read_dealer,
    read_order,
    recall_campaign_payload,
    set_clock,
    setup_awarded_order,
    setup_tx_catalogue,
    test_bay_payload,
    type_d_transit_model_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A working date well clear of both the clock floor and the recall windows below.
SEPTEMBER_CLOCK = "2026-09-01T00:00:00Z"
JUST_BEFORE_THE_FLOOR = "2026-07-31T23:59:59Z"


class TestNaturalKeyScopeAndTheClockFloor:
    """One error id shared by six registries, and a floor that is not a rewind rule."""

    def test_two_registries_may_share_a_code_but_one_registry_may_not_repeat_it(self):
        """A bus model and a test bay both coded TB-1 coexist, while a second model
        and a second bay claiming those codes are refused — even when the bay sits in
        another plant.

        PRD: "Six natural keys are unique within their own collection: a model's
        `model_code`, a package's `package_code`, a line's `line_code`, a bay's
        `bay_code`, a dealer's `dealer_code` and a campaign's `campaign_code`. A
        collision on any of them is refused with `ERR_DUPLICATE_CODE`."

        Design: Corner/errors/natural_key_uniqueness_and_the_clock_floor_are_both_enforced
        """
        model = validate_success(
            api_client.create_bus_model(bus_model_payload(model_code="TB-1"),
                                        COMPLIANCE),
            201,
        )
        assert model["model_code"] == "TB-1"

        # The same string in a different collection is not a collision at all.
        bay = validate_success(
            api_client.create_test_bay(
                test_bay_payload(bay_code="TB-1", supported_test_types=["BRAKE"],
                                 max_concurrent_electrical=1),
                PLANT,
            ),
            201,
        )
        assert bay["bay_code"] == "TB-1"

        validate_error(
            api_client.create_bus_model(
                type_d_transit_model_payload(model_code="TB-1"), COMPLIANCE
            ),
            ApiErrorId.ERR_DUPLICATE_CODE.value,
            409,
        )
        # The plant code is no part of the bay's key.
        validate_error(
            api_client.create_test_bay(
                test_bay_payload(
                    bay_code="TB-1", plant_code="PLANT-B",
                    supported_test_types=["ELECTRICAL"], max_concurrent_electrical=1,
                ),
                PLANT,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE.value,
            409,
        )

        _, model_meta = validate_paginated(api_client.list_bus_models(COMPLIANCE))
        assert model_meta["total_count"] == 1
        _, bay_meta = validate_paginated(api_client.list_test_bays(PLANT))
        assert bay_meta["total_count"] == 1

    def test_the_floor_instant_is_accepted_and_a_second_earlier_is_not(self):
        """One second below the startup default is refused, a malformed instant is
        refused by the same code, and the default instant itself is accepted.

        PRD: "The supplied value must be a valid ISO-8601 UTC instant and must not be
        earlier than the startup default `2026-08-01T00:00:00Z`; a malformed or earlier
        value is rejected with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 422)."

        Design: Corner/errors/natural_key_uniqueness_and_the_clock_floor_are_both_enforced
        """
        validate_error(
            api_client.set_clock(JUST_BEFORE_THE_FLOOR, COMPLIANCE),
            ApiErrorId.ERR_CLOCK_REWIND_FORBIDDEN.value,
            422,
        )
        validate_error(
            api_client.set_clock_raw({"current_utc": "the first of August"}, COMPLIANCE),
            ApiErrorId.ERR_CLOCK_REWIND_FORBIDDEN.value,
            422,
        )
        # The floor is inclusive: the boundary instant itself is a legal setting.
        validate_success(api_client.set_clock(CLOCK_START_UTC, COMPLIANCE))
        validate_success(api_client.set_clock(SEPTEMBER_CLOCK, COMPLIANCE))


class TestLegacyImportGuardOrder:
    """Two guards on one endpoint, and a request that trips both of them."""

    def test_licensing_is_reported_before_vin_uniqueness_and_nothing_is_written(self):
        """A duplicate VIN sent to a dealer unlicensed in the bus's registration state
        reports the licensing failure, and a delivery instant in the clock's future is
        refused as a window error.

        PRD: "the `vin` must be unique across all buses, otherwise
        `ERR_VIN_ALREADY_EXISTS`; and the profile's `state_code` must appear in the path
        dealer's `licensed_state_codes`, otherwise `ERR_DEALER_NOT_LICENSED_IN_STATE`."
        PRD: "The checks below form one global ladder; the lowest-numbered applicable
        check wins, and evaluation stops there."

        Design: Corner/errors/legacy_import_checks_licensing_before_vin_uniqueness
        """
        set_clock(SEPTEMBER_CLOCK)
        catalogue = setup_tx_catalogue()
        model_id = catalogue["model"]["id"]
        package_id = catalogue["package"]["id"]
        profile_id = catalogue["profile"]["id"]
        texas = create_dealer(
            dealer_code="D-TX", licensed_state_codes=["TX", "NM"],
            training_capacity_per_month=12,
        )
        nevada = create_dealer(
            dealer_code="D-NV", dealer_name="Silver State Bus",
            licensed_state_codes=["NV"], training_capacity_per_month=6,
        )

        historical = validate_success(
            api_client.create_legacy_fleet_record(
                texas["id"],
                legacy_fleet_record_payload(
                    model_id, package_id, profile_id,
                    "1TXDSL0000000601", "2026-05-10T00:00:00Z",
                ),
                CONTRACTS,
            ),
            201,
        )
        assert_bus_unit(historical)
        assert historical["production_status"] == "DELIVERED"
        assert historical["certification_status"] == "CERTIFIED"
        assert historical["service_status"] == "NONE"
        assert historical["driver_training_status"] == "COMPLETED"
        assert historical["is_legacy_import"] is True
        assert historical["contract_order_id"] in (None, "")
        assert historical["dealer_id"] == texas["id"]
        # The registration state comes from the cited profile, not from the dealer.
        assert historical["registration_state_code"] == "TX"
        assert_same_instant(
            historical["delivered_at"], "2026-05-10T00:00:00Z", "delivered_at"
        )

        repeated = legacy_fleet_record_payload(
            model_id, package_id, profile_id,
            "1TXDSL0000000601", "2026-06-02T00:00:00Z",
        )
        validate_error(
            api_client.create_legacy_fleet_record(texas["id"], repeated, CONTRACTS),
            ApiErrorId.ERR_VIN_ALREADY_EXISTS.value,
            409,
        )
        # Both broken at once: licensing sits above the vin check on the ladder.
        validate_error(
            api_client.create_legacy_fleet_record(nevada["id"], repeated, CONTRACTS),
            ApiErrorId.ERR_DEALER_NOT_LICENSED_IN_STATE.value,
            422,
        )

        validate_error(
            api_client.create_legacy_fleet_record(
                texas["id"],
                legacy_fleet_record_payload(
                    model_id, package_id, profile_id,
                    "1TXDSL0000000602", "2026-11-15T00:00:00Z",
                ),
                CONTRACTS,
            ),
            ApiErrorId.ERR_INVALID_BUILD_WINDOW.value,
            422,
        )

        dealer = read_dealer(texas["id"])
        assert dealer["delivered_unit_count"] == 1
        assert dealer["certification_standing"] == "GOOD"
        assert read_dealer(nevada["id"])["delivered_unit_count"] == 0
        _, unit_meta = validate_paginated(api_client.list_bus_units(CONTRACTS))
        assert unit_meta["total_count"] == 1


class TestMintGuardOrder:
    """A one-bus order refuses its second bus twice, for two different reasons."""

    def test_the_repeated_vin_and_the_exhausted_count_are_told_apart(self):
        """Retrying the mint with the VIN just used reports the duplicate, retrying it
        with a fresh VIN reports the exhausted count, and the order's counter survives
        both.

        PRD: "an order that has already minted its full awarded count refuses further
        buses with `ERR_ORDER_UNIT_COUNT_EXCEEDED`."
        PRD: "`vin` is unique across all buses: `ERR_VIN_ALREADY_EXISTS` (409), on
        minting a bus and recording a legacy fleet record."

        Design: Corner/errors/minting_checks_the_vin_before_the_awarded_unit_count
        """
        scenario = setup_awarded_order(
            setup_tx_catalogue(),
            promised_delivery_date="2026-11-20",
            solicitation_overrides={
                "solicitation_code": "SOL-TX-122",
                "required_delivery_date": "2026-12-01",
                "price_cap_cents_per_unit": 40_000_000,
            },
        )
        order = scenario["order"]
        assert order["unit_count"] == 1
        assert order["created_unit_count"] == 0

        minted = validate_success(
            api_client.mint_bus_unit(order["id"], "1TXDSL0000000701", PLANT), 201
        )
        assert_bus_unit(minted)
        assert minted["production_status"] == "PLANNED"
        assert minted["certification_status"] == "PENDING"
        assert minted["contract_order_id"] == order["id"]
        assert minted["is_legacy_import"] is False
        # The bus is a faithful copy of what was awarded.
        assert minted["seat_capacity"] == order["awarded_seat_capacity"]
        assert minted["emergency_exit_count"] == order["awarded_emergency_exit_count"]
        assert minted["mirror_config"] == order["awarded_mirror_config"]
        assert minted["lap_shoulder_belts"] == order["awarded_lap_shoulder_belts"]
        assert minted["eight_lamp_system"] == order["awarded_eight_lamp_system"]
        assert minted["crossing_arm"] == order["awarded_crossing_arm"]
        assert minted["rollover_reinforcement"] == order["awarded_rollover_reinforcement"]
        assert minted["joint_strength_kn"] == order["awarded_joint_strength_kn"]

        validate_error(
            api_client.mint_bus_unit(order["id"], "1TXDSL0000000701", PLANT),
            ApiErrorId.ERR_VIN_ALREADY_EXISTS.value,
            409,
        )
        validate_error(
            api_client.mint_bus_unit(order["id"], "1TXDSL0000000702", PLANT),
            ApiErrorId.ERR_ORDER_UNIT_COUNT_EXCEEDED.value,
            409,
        )

        after = read_order(order["id"])
        assert after["created_unit_count"] == 1
        assert after["status"] == "ACTIVE"
        _, unit_meta = validate_paginated(api_client.list_bus_units(PLANT))
        assert unit_meta["total_count"] == 1


class TestCampaignDraftAndLaunchGuards:
    """The window is judged on the request; the kit pool is judged on the scope."""

    def test_the_window_is_refused_at_draft_and_the_short_pool_only_at_launch(self):
        """A backward window never becomes a campaign, while an under-stocked campaign
        drafts happily and fails its launch; four kits for two buses at two kits each
        launches at exact equality.

        PRD: "The window is a **closed** date interval and `build_window_end` must fall
        on or after `build_window_start`, otherwise `ERR_INVALID_BUILD_WINDOW`."
        PRD: "the stock to cover the base need, meaning `total_kits` must be at least
        `affected_unit_count` multiplied by `kits_per_unit`, otherwise
        `ERR_INSUFFICIENT_REMEDY_KITS`."

        Design: Corner/errors/campaign_launch_needs_a_forward_window_and_a_sufficient_kit_pool
        """
        set_clock(SEPTEMBER_CLOCK)
        catalogue = setup_tx_catalogue()
        model_id = catalogue["model"]["id"]
        dealer = create_dealer(
            dealer_code="D-TX", licensed_state_codes=["TX"],
            training_capacity_per_month=12,
        )
        for vin, delivered_at in (
            ("1TXDSL0000000801", "2026-05-10T00:00:00Z"),
            ("1TXDSL0000000802", "2026-06-02T00:00:00Z"),
        ):
            create_legacy_unit(
                dealer["id"], model_id, catalogue["package"]["id"],
                catalogue["profile"]["id"], vin, delivered_at,
            )

        backward = recall_campaign_payload(
            model_id, campaign_code="RC-BACKWARD",
            build_window_start="2026-06-30", build_window_end="2026-05-01",
            kits_per_unit=2, total_kits=10,
        )
        validate_error(
            api_client.create_recall_campaign(backward, COMPLIANCE),
            ApiErrorId.ERR_INVALID_BUILD_WINDOW.value,
            422,
        )
        _, campaign_meta = validate_paginated(
            api_client.list_recall_campaigns(COMPLIANCE)
        )
        assert campaign_meta["total_count"] == 0

        short = create_campaign(
            model_id, campaign_code="RC-SHORT",
            build_window_start="2026-05-01", build_window_end="2026-06-30",
            kits_per_unit=2, total_kits=3,
        )
        assert_recall_campaign(short)
        # Scope is not evaluated at draft time, so a short pool is still draftable.
        assert short["status"] == "DRAFT"
        assert short["available_kits"] == 3
        assert short["reserved_kits"] == 0
        assert short["affected_unit_count"] == 0

        validate_error(
            api_client.launch_recall_campaign(short["id"], COMPLIANCE),
            ApiErrorId.ERR_INSUFFICIENT_REMEDY_KITS.value,
            422,
        )

        stocked = create_campaign(
            model_id, campaign_code="RC-OK",
            build_window_start="2026-05-01", build_window_end="2026-06-30",
            kits_per_unit=2, total_kits=4,
        )
        launched = launch_campaign(stocked["id"])
        assert launched["status"] == "LAUNCHED"
        assert launched["affected_unit_count"] == 2
        assert launched["reserved_kits"] == 4
        assert launched["available_kits"] == 0
        # Two open buses restrict the dealer, and each escalation finds the pool empty.
        assert launched["escalated_task_count"] == 2
        assert launched["kit_shortfall_count"] == 2
        assert_kit_pool_conserved(launched)
        assert read_dealer(dealer["id"])["certification_standing"] == "RESTRICTED"

        untouched = read_campaign(short["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["affected_unit_count"] == 0
        assert untouched["reserved_kits"] == 0
        assert untouched["available_kits"] == 3
        assert list_tasks(recall_campaign_id=short["id"]) == []
        assert len(list_tasks(recall_campaign_id=stocked["id"])) == 2
