"""Stale-read guards, re-derived counters and the immediacy of every side effect."""

from test_helpers import (
    COMPLIANCE,
    CONTRACTS,
    PLANT,
    QUALITY,
    SALES,
    TX_BID_CONFIG,
    ApiErrorId,
    api_client,
    assert_bid,
    assert_bid_revision,
    assert_build_slot,
    assert_common_fields,
    assert_dealer,
    assert_kit_pool_conserved,
    assert_line_ledger,
    assert_order_posture,
    assert_production_line,
    bid_payload,
    bid_revision_payload,
    build_slot_payload,
    ca_profile_payload,
    cancel_task,
    complete_task,
    create_bid,
    create_bus_model,
    create_campaign,
    create_dealer,
    create_legacy_unit,
    create_line,
    create_profile,
    create_propulsion_package,
    create_solicitation,
    electric_package_payload,
    launch_campaign,
    list_tasks,
    plan_slot,
    read_bid,
    read_campaign,
    read_dealer,
    read_line,
    read_order,
    read_slot,
    read_unit,
    set_clock,
    setup_order_with_units,
    setup_tx_catalogue,
    validate_error,
    validate_paginated,
    validate_success,
)

AUGUST_CLOCK = "2026-08-15T00:00:00Z"
SEPTEMBER_CLOCK = "2026-09-01T00:00:00Z"
# The Texas configuration with crossview mirrors, and the same bid one mirror down.
TX_CROSSVIEW_PRICE_CENTS = 14_641_571
TX_STANDARD_MIRROR_PRICE_CENTS = 14_582_808
# A 78-seat belted electric bid: 29,983,775 of line items and 712,116 of prep fees.
CA_ELECTRIC_PRICE_CENTS = 30_695_891
NOMINAL_RANGE_MI = 147
# 122.76 kWh of available energy at 1.425 kWh per mile is 86.147 miles, and that
# over the 1.18 mountain terrain factor is 73.006, truncated to one digit.
MOUNTAIN_ROUTE_RANGE_MI = 73.0


class TestBidRevisionStaleVersionGuard:
    """One observed version, two revisions: the second is authored on a fiction."""

    def test_the_replayed_bid_version_is_refused_and_changes_nothing(self):
        """A revision appended on the version the client last saw succeeds and moves
        the bid on; the second revision replaying that same version is refused as
        stale, and the retry on the fresh version lands as the next round.

        PRD: "Appending a revision round to a bid requires `expected_bid_version`,
        carrying the `version` of the parent `Bid` as the client last observed it. If
        that value does not equal the bid's current `version`, the request is rejected
        with `ERR_STALE_BID_VERSION` (HTTP 412)."
        PRD: "every earlier revision of that bid — including the round-zero snapshot —
        has `is_superseded` set to true; the bid's `revision_round` is set to the new
        round index; the bid's own offered configuration fields are overwritten from
        the revision".

        Design: Corner/cross_cutting_complexity_layers/bid_revision_rejects_a_stale_expected_bid_version
        """
        set_clock(AUGUST_CLOCK)
        catalogue = setup_tx_catalogue()
        solicitation = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-TX-124",
            price_cap_cents_per_unit=40_000_000,
        )
        bid = create_bid(
            solicitation["id"], catalogue["model"]["id"], catalogue["package"]["id"],
            **TX_BID_CONFIG,
        )
        assert_bid(bid)
        assert bid["version"] == 1
        assert bid["revision_round"] == 0
        assert bid["provisional_unit_price_cents"] == TX_CROSSVIEW_PRICE_CENTS
        assert bid["spec_compliance_status"] == "CONFORMING"

        value_engineered = validate_success(
            api_client.create_bid_revision(
                bid["id"],
                bid_revision_payload(
                    1,
                    **dict(TX_BID_CONFIG, offered_mirror_config="STANDARD"),
                    note="value-engineered mirrors",
                ),
                SALES,
            ),
            201,
        )
        assert_bid_revision(value_engineered)
        assert value_engineered["bid_id"] == bid["id"]
        assert value_engineered["round_index"] == 1
        assert value_engineered["is_superseded"] is False
        assert value_engineered["note"] == "value-engineered mirrors"
        # Dropping the crossview mirror removes 57,400 of options and 1,363 of prep fee.
        assert value_engineered["unit_price_cents"] == TX_STANDARD_MIRROR_PRICE_CENTS

        # The client's view of the offered configuration is now a round behind.
        validate_error(
            api_client.create_bid_revision(
                bid["id"],
                bid_revision_payload(
                    1, **dict(TX_BID_CONFIG, offered_mirror_config="CROSSVIEW_HEATED")
                ),
                SALES,
            ),
            ApiErrorId.ERR_STALE_BID_VERSION.value,
            412,
        )

        after_first = read_bid(bid["id"])
        assert after_first["version"] == 2
        assert after_first["revision_round"] == 1
        assert after_first["offered_mirror_config"] == "STANDARD"
        assert after_first["provisional_unit_price_cents"] == (
            TX_STANDARD_MIRROR_PRICE_CENTS
        )
        # The mirror shortfall is an exceptable item, so the bid stays submittable.
        assert after_first["spec_compliance_status"] == "EXCEPTIONS_TAKEN"
        assert after_first["exception_count"] == 1
        assert after_first["unmet_mandatory_items"] == []

        restored = validate_success(
            api_client.create_bid_revision(
                bid["id"], bid_revision_payload(2, **TX_BID_CONFIG), SALES
            ),
            201,
        )
        assert restored["round_index"] == 2
        assert restored["is_superseded"] is False
        assert restored["unit_price_cents"] == TX_CROSSVIEW_PRICE_CENTS

        superseded, superseded_meta = validate_paginated(
            api_client.list_bid_revisions(bid["id"], SALES, {"is_superseded": "true"})
        )
        # The refused round left no trace: only rounds zero and one were ever laid down.
        assert superseded_meta["total_count"] == 2
        assert [row["round_index"] for row in superseded] == [0, 1]
        assert superseded[0]["offered_mirror_config"] == "CROSSVIEW"
        assert superseded[0]["unit_price_cents"] == TX_CROSSVIEW_PRICE_CENTS
        assert superseded[1]["offered_mirror_config"] == "STANDARD"

        every, every_meta = validate_paginated(
            api_client.list_bid_revisions(bid["id"], SALES)
        )
        assert every_meta["total_count"] == 3
        assert [row["round_index"] for row in every] == [0, 1, 2]

        final = read_bid(bid["id"])
        assert final["version"] == 3
        assert final["revision_round"] == 2
        assert final["offered_mirror_config"] == "CROSSVIEW"
        assert final["provisional_unit_price_cents"] == TX_CROSSVIEW_PRICE_CENTS
        assert final["spec_compliance_status"] == "CONFORMING"
        assert final["exception_count"] == 0


class TestSlotCreationStaleLineVersionGuard:
    """Every write to the line invalidates the occupancy picture, free window or not."""

    def test_the_replayed_line_version_is_refused_ahead_of_the_calendar_rules(self):
        """A slot planned on the observed version succeeds and moves the line on; the
        replay is refused although its window is free and adjacent-legal, a commit
        invalidates the next observation too, and only once the guard is satisfied is
        the body-class rule reached.

        PRD: "Planning a build slot requires `expected_production_line_version`,
        carrying the `version` of the parent `ProductionLine` as the client last
        observed it. If that value does not equal the line's current `version`, the
        request is rejected with `ERR_STALE_LINE_VERSION` (HTTP 412)."
        PRD: "A slot request is authored against an observed occupancy picture — the
        line's `committed_slot_days`, the windows already booked on it, and its running
        status — and once the line's `version` has moved, that picture is stale even
        when the requested window itself is still free."

        Design: Corner/cross_cutting_complexity_layers/slot_creation_rejects_a_stale_expected_production_line_version
        """
        scenario = setup_order_with_units(
            setup_tx_catalogue(),
            vin_list=["1TXDSL0000001001", "1TXDSL0000001002"],
            solicitation_overrides={
                "solicitation_code": "SOL-TX-125",
                "required_delivery_date": "2026-12-01",
                "price_cap_cents_per_unit": 40_000_000,
            },
        )
        first_unit, second_unit = scenario["units"]
        line = create_line()
        transit_only = create_line(
            line_code="L-D1", supported_body_classes=["TYPE_D"]
        )
        assert line["version"] == 1
        assert transit_only["version"] == 1
        assert_line_ledger(line, 0)

        booked_window = validate_success(
            api_client.create_build_slot(
                build_slot_payload(
                    1, line["id"], first_unit["id"], "2026-09-07", "2026-09-14"
                ),
                PLANT,
            ),
            201,
        )
        assert_build_slot(booked_window)
        assert booked_window["status"] == "PLANNED"
        assert booked_window["slot_days"] == 7
        assert booked_window["propulsion_type"] == "DIESEL"

        # A free window, back-to-back with a diesel neighbour, well inside the horizon.
        validate_error(
            api_client.create_build_slot(
                build_slot_payload(
                    1, line["id"], second_unit["id"], "2026-09-14", "2026-09-21"
                ),
                PLANT,
            ),
            ApiErrorId.ERR_STALE_LINE_VERSION.value,
            412,
        )

        after_plan = read_line(line["id"])
        assert after_plan["version"] == 2
        assert_line_ledger(after_plan, 0)
        _, planned_meta = validate_paginated(
            api_client.list_build_slots(PLANT, {"production_line_id": line["id"]})
        )
        assert planned_meta["total_count"] == 1

        retried = validate_success(
            api_client.create_build_slot(
                build_slot_payload(
                    2, line["id"], second_unit["id"], "2026-09-14", "2026-09-21"
                ),
                PLANT,
            ),
            201,
        )
        assert retried["slot_days"] == 7
        assert read_line(line["id"])["version"] == 3

        committed = validate_success(
            api_client.commit_build_slot(booked_window["id"], PLANT)
        )
        assert committed["status"] == "COMMITTED"
        after_commit = read_line(line["id"])
        # Two creates and a commit: three writes above the version the client held.
        assert after_commit["version"] == 4
        assert_line_ledger(after_commit, 7)

        validate_error(
            api_client.create_build_slot(
                build_slot_payload(
                    2, line["id"], second_unit["id"], "2026-10-05", "2026-10-08"
                ),
                PLANT,
            ),
            ApiErrorId.ERR_STALE_LINE_VERSION.value,
            412,
        )

        # Its own version is current, so the request reaches the compatibility rule.
        validate_error(
            api_client.create_build_slot(
                build_slot_payload(
                    1, transit_only["id"], second_unit["id"], "2026-10-05", "2026-10-08"
                ),
                PLANT,
            ),
            ApiErrorId.ERR_BODY_CLASS_UNSUPPORTED.value,
            422,
        )

        assert_production_line(read_line(transit_only["id"]))
        assert read_line(transit_only["id"])["version"] == 1
        assert_line_ledger(read_line(transit_only["id"]), 0)
        _, final_meta = validate_paginated(api_client.list_build_slots(PLANT))
        assert final_meta["total_count"] == 2
        assert read_slot(retried["id"])["status"] == "PLANNED"


class TestDealerCountersAreRederivedFromTheirSources:
    """One bus, two campaigns: the exposure figure counts buses, never tasks."""

    def _one_bus_swept_into_two_campaigns(self) -> dict:
        """A Texas dealer holding a single historical diesel bus, with two drafted
        campaigns whose windows both cover that bus's delivery."""
        set_clock(SEPTEMBER_CLOCK)
        catalogue = setup_tx_catalogue()
        dealer = create_dealer(
            dealer_code="D-TX", licensed_state_codes=["TX"],
            training_capacity_per_month=12,
        )
        assert_dealer(dealer)
        assert dealer["delivered_unit_count"] == 0
        assert dealer["open_recall_unit_count"] == 0
        assert dealer["certification_standing"] == "GOOD"

        bus = create_legacy_unit(
            dealer["id"], catalogue["model"]["id"], catalogue["package"]["id"],
            catalogue["profile"]["id"], "1TXDSL0000001101", "2026-05-10T00:00:00Z",
        )
        assert read_dealer(dealer["id"])["delivered_unit_count"] == 1

        brakes = create_campaign(
            catalogue["model"]["id"], campaign_code="RC-A",
            defect_category="BRAKE_LINE_CORROSION", kits_per_unit=1, total_kits=2,
        )
        wiring = create_campaign(
            catalogue["model"]["id"], campaign_code="RC-B",
            defect_category="WIRING_HARNESS", kits_per_unit=1, total_kits=2,
        )
        return {
            "catalogue": catalogue, "dealer": dealer, "bus": bus,
            "brakes": brakes, "wiring": wiring,
        }

    def test_two_live_tasks_on_one_bus_leave_the_exposure_figure_at_one(self):
        """Both campaigns sweep the same bus and both open a task on it, yet the
        dealer reports one open bus and keeps good standing where a task-counting
        figure would have crossed the restriction threshold.

        PRD: "A dealer's `open_recall_unit_count` is the number of *distinct* buses on
        which that dealer holds a task in `status` `OPEN` or `IN_PROGRESS`; `COMPLETED`
        and `CANCELLED` tasks do not count, and two campaigns' tasks on the same bus
        contribute 1, not 2."
        PRD: "A bus whose `service_status` is already `RECALL_OPEN` from another
        campaign is still included: one bus may carry tasks from several campaigns at
        once."

        Design: Corner/cross_cutting_complexity_layers/dealer_counters_are_recomputed_from_their_sources_by_distinct_unit
        """
        scenario = self._one_bus_swept_into_two_campaigns()
        dealer_id = scenario["dealer"]["id"]

        first_launch = launch_campaign(scenario["brakes"]["id"])
        assert first_launch["affected_unit_count"] == 1
        assert first_launch["reserved_kits"] == 1
        assert first_launch["available_kits"] == 1
        assert first_launch["escalated_task_count"] == 0
        assert_kit_pool_conserved(first_launch)

        after_first = read_dealer(dealer_id)
        assert after_first["open_recall_unit_count"] == 1
        assert after_first["certification_standing"] == "GOOD"
        assert after_first["delivered_unit_count"] == 1

        second_launch = launch_campaign(scenario["wiring"]["id"])
        assert second_launch["affected_unit_count"] == 1
        assert second_launch["reserved_kits"] == 1
        assert second_launch["escalated_task_count"] == 0

        after_second = read_dealer(dealer_id)
        # One bus, two obligations, one unit of exposure.
        assert after_second["open_recall_unit_count"] == 1
        assert after_second["certification_standing"] == "GOOD"

        rows, meta = validate_paginated(
            api_client.list_remedy_tasks(
                COMPLIANCE, {"dealer_id": dealer_id, "status": "OPEN"}
            )
        )
        assert meta["total_count"] == 2
        assert {row["bus_unit_id"] for row in rows} == {scenario["bus"]["id"]}
        assert {row["recall_campaign_id"] for row in rows} == {
            scenario["brakes"]["id"], scenario["wiring"]["id"]
        }
        for row in rows:
            assert row["escalation_level"] == "DEALER_DIRECTED"
            assert row["kits_reserved"] == 1
        assert read_unit(scenario["bus"]["id"])["service_status"] == "RECALL_OPEN"

    def test_the_counters_fall_back_on_closure_and_rise_again_on_a_new_delivery(self):
        """Completing one task leaves the exposure at one while the other is live,
        cancelling the second clears it and returns the kit, and a further historical
        import lifts the delivered count without touching the exposure.

        PRD: "The figures are recomputed at exactly four points: campaign launch,
        remedy-task completion, remedy-task cancellation, and bus delivery."
        PRD: "The bus's `service_status` returns to `RECALL_CLOSED` if it has a
        `COMPLETED` task and to `NONE` if it does not, so cancelling the only task a
        clean bus ever had leaves no trace on it."

        Design: Corner/cross_cutting_complexity_layers/dealer_counters_are_recomputed_from_their_sources_by_distinct_unit
        """
        scenario = self._one_bus_swept_into_two_campaigns()
        dealer_id = scenario["dealer"]["id"]
        bus_id = scenario["bus"]["id"]
        launch_campaign(scenario["brakes"]["id"])
        launch_campaign(scenario["wiring"]["id"])

        brake_task = list_tasks(recall_campaign_id=scenario["brakes"]["id"])[0]
        wiring_task = list_tasks(recall_campaign_id=scenario["wiring"]["id"])[0]

        finished = complete_task(brake_task["id"], dealer_id)
        assert finished["status"] == "COMPLETED"
        brake_campaign = read_campaign(scenario["brakes"]["id"])
        assert brake_campaign["consumed_kits"] == 1
        assert brake_campaign["reserved_kits"] == 0
        assert brake_campaign["available_kits"] == 1
        assert brake_campaign["status"] == "COMPLETED"

        mid_way = read_dealer(dealer_id)
        # The second campaign's task is still live on the same bus.
        assert mid_way["open_recall_unit_count"] == 1
        assert mid_way["certification_standing"] == "GOOD"
        assert read_unit(bus_id)["service_status"] == "RECALL_OPEN"

        cancelled = cancel_task(wiring_task["id"])
        assert cancelled["status"] == "CANCELLED"
        wiring_campaign = read_campaign(scenario["wiring"]["id"])
        assert wiring_campaign["reserved_kits"] == 0
        assert wiring_campaign["available_kits"] == 2
        assert wiring_campaign["consumed_kits"] == 0
        assert wiring_campaign["status"] == "COMPLETED"
        assert_kit_pool_conserved(wiring_campaign)

        cleared = read_dealer(dealer_id)
        assert cleared["open_recall_unit_count"] == 0
        assert cleared["certification_standing"] == "GOOD"
        assert cleared["delivered_unit_count"] == 1
        # A completed task on the bus survives the cancellation of the other one.
        assert read_unit(bus_id)["service_status"] == "RECALL_CLOSED"

        create_legacy_unit(
            dealer_id, scenario["catalogue"]["model"]["id"],
            scenario["catalogue"]["package"]["id"],
            scenario["catalogue"]["profile"]["id"],
            "1TXDSL0000001102", "2026-06-02T00:00:00Z",
        )
        grown = read_dealer(dealer_id)
        # Re-derived from the source rows, not incremented from the previous figure.
        assert grown["delivered_unit_count"] == 2
        assert grown["open_recall_unit_count"] == 0
        assert grown["certification_standing"] == "GOOD"
        assert len(list_tasks(dealer_id=dealer_id)) == 2


class TestComputedFieldsInTheCreatingResponse:
    """Nothing is deferred: the 201 body is the whole evaluation."""

    def test_the_draft_body_already_carries_price_range_joint_strength_and_verdict(self):
        """A deliberately short-range, under-exited electric bid returns every derived
        figure in its own creation response, and a read by another role and a filtered
        listing reproduce that body exactly.

        PRD: "Drafting a bid runs four computations in one breath.
        `offered_joint_strength_kn` becomes the model's `body_joint_strength_kn` plus a
        rollover bonus of 9.5 kilonewtons when rollover reinforcement is offered, and
        the model's figure unchanged when it is not."
        PRD: "The verdict in `spec_compliance_status` is `NONCONFORMING` whenever
        `unmet_mandatory_items` is non-empty, `EXCEPTIONS_TAKEN` when that list is empty
        and `exception_count` is at least 1, and `CONFORMING` when the list is empty and
        the count is zero."

        Design: Corner/consistency_model/computed_fields_are_present_in_the_creating_response_itself
        """
        model = create_bus_model()
        package = create_propulsion_package(electric_package_payload(model["id"]))
        profile = create_profile(
            ca_profile_payload(
                min_emergency_exit_count=7,
                min_joint_strength_kn=62.0,
                required_route_range_mi=120.0,
                terrain_class="MOUNTAIN",
            ),
            publish=True,
        )
        solicitation = create_solicitation(
            profile["id"],
            solicitation_code="SOL-CA-126",
            buyer_type="COOPERATIVE",
            buyer_name="CA Schools Cooperative",
            required_delivery_date="2027-01-15",
            price_cap_cents_per_unit=60_000_000,
        )

        drafted = validate_success(
            api_client.create_bid(
                bid_payload(
                    solicitation["id"], model["id"], package["id"],
                    offered_seat_capacity=78,
                    offered_emergency_exit_count=6,
                    offered_mirror_config="CROSSVIEW_HEATED",
                    offered_lap_shoulder_belts=True,
                    offered_eight_lamp_system=True,
                    offered_crossing_arm=True,
                    offered_rollover_reinforcement=False,
                ),
                SALES,
            ),
            201,
        )
        assert_bid(drafted)
        assert_common_fields(drafted, expected_version=1)
        assert drafted["status"] == "DRAFT"
        assert drafted["revision_round"] == 0
        assert drafted["evaluated_spec_profile_id"] == profile["id"]
        # No rollover reinforcement offered, so the body carries no joint bonus.
        assert drafted["offered_joint_strength_kn"] == 58.0
        assert drafted["nominal_range_mi"] == NOMINAL_RANGE_MI
        assert drafted["derated_route_range_mi"] == MOUNTAIN_ROUTE_RANGE_MI
        assert drafted["provisional_unit_price_cents"] == CA_ELECTRIC_PRICE_CENTS
        assert drafted["spec_compliance_status"] == "NONCONFORMING"
        assert drafted["unmet_mandatory_items"] == [
            "joint_strength", "rollover_protection", "route_range", "emergency_exits"
        ]
        # Every exceptable item is satisfied: nonconformance is not exception-carrying.
        assert drafted["exception_count"] == 0

        read_back = validate_success(api_client.get_bid(drafted["id"], CONTRACTS))
        assert read_back == drafted

        rows, meta = validate_paginated(
            api_client.list_bids(CONTRACTS, {"solicitation_id": solicitation["id"]})
        )
        assert meta["total_count"] == 1
        # There is no lag window in which a derived field is absent or stale.
        assert rows[0] == drafted


class TestTransitionSideEffectsAreImmediatelyReadable:
    """One commit writes four aggregates, all of them readable on the next request."""

    def test_the_commit_is_visible_in_the_slot_the_bus_the_line_and_the_order(self):
        """The commit response reports the booking, and the reads that follow it show
        the bus slotted, the line's ledger charged with a fresh version, and the owning
        order's posture recomputed — with no intervening refresh of any kind.

        PRD: "On success the slot moves `PLANNED → COMMITTED`, the line's
        `committed_slot_days` increases by exactly the slot's `slot_days` and the line's
        `version` increments by 1, the bus moves `PLANNED → SLOTTED`, and the owning
        contract order recomputes `at_risk_unit_count` and `delivery_posture`."
        PRD: "Every bus carries **three independent status dimensions**, and a
        transition in one never implies a transition in another except through an
        explicitly stated side effect."

        Design: Corner/consistency_model/transition_side_effects_are_visible_to_the_immediately_following_read
        """
        scenario = setup_order_with_units(
            setup_tx_catalogue(),
            vin_list=["1TXDSL0000001201"],
            solicitation_overrides={
                "solicitation_code": "SOL-TX-127",
                "required_delivery_date": "2026-12-01",
                "price_cap_cents_per_unit": 40_000_000,
            },
        )
        order_id = scenario["order"]["id"]
        unit = scenario["units"][0]
        line = create_line()
        slot = plan_slot(line["id"], unit["id"], "2026-09-07", "2026-09-14")
        assert slot["status"] == "PLANNED"
        assert slot["slot_days"] == 7
        assert_line_ledger(read_line(line["id"]), 0)
        assert read_line(line["id"])["version"] == 2
        # Ninety-one days to the promise, so the unbooked bus is not yet at risk.
        assert_order_posture(read_order(order_id), "ON_TRACK", 1, damages=0)

        committed = validate_success(api_client.commit_build_slot(slot["id"], PLANT))
        assert_build_slot(committed)
        assert committed["status"] == "COMMITTED"
        assert committed["slot_days"] == 7

        moved = read_unit(unit["id"])
        assert moved["production_status"] == "SLOTTED"
        # The compliance and service dimensions were not along for the ride.
        assert moved["certification_status"] == "PENDING"
        assert moved["service_status"] == "NONE"
        assert moved["driver_training_status"] == "PENDING"

        charged = validate_success(api_client.get_production_line(line["id"], QUALITY))
        assert_production_line(charged)
        assert_line_ledger(charged, 7)
        assert charged["version"] == 3
        assert charged["status"] == "RUNNING"

        recomputed = read_order(order_id)
        assert_order_posture(recomputed, "ON_TRACK", 0, damages=0)
        assert recomputed["created_unit_count"] == 1
        assert recomputed["delivered_unit_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_build_slots(
                PLANT, {"production_line_id": line["id"], "status": "COMMITTED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == slot["id"]
        assert read_slot(slot["id"])["status"] == "COMMITTED"
