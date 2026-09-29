"""Endpoint surfaces: create-read-list round trips, link checks, pure reads, actions."""

from test_helpers import (
    COMPLIANCE,
    PLANT,
    SALES,
    TX_BID_CONFIG,
    ApiErrorId,
    api_client,
    assert_bid,
    assert_common_fields,
    assert_envelope_meta,
    assert_line_ledger,
    assert_pagination_meta,
    assert_production_line,
    assert_response_type,
    assert_test_bay,
    bid_payload,
    create_bay,
    create_bus_model,
    create_line,
    create_profile,
    create_propulsion_package,
    create_solicitation,
    diesel_package_payload,
    electric_package_payload,
    nv_profile_payload,
    read_line,
    set_clock,
    tx_profile_payload,
    type_d_transit_model_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The Texas equipment level on the conventional body and the diesel package.
TX_BID_PRICE_CENTS = 14_641_571
# The same body on the 155 kWh electric package with lighting but no mirrors.
NV_ELECTRIC_PRICE_CENTS = 28_556_995
# The PRD's worked range example, on rolling terrain.
NOMINAL_RANGE_MI = 147
DERATED_RANGE_MI = 79.7
LATER_CLOCK = "2026-11-01T00:00:00Z"


class TestTestBayRegistrySurface:
    """A registry with no update verb: create, read by id, list filtered."""

    def test_the_three_bodies_of_one_bay_agree_field_for_field(self):
        """The 201 body, the by-id body and the row inside a filtered page describe
        the same bay identically, including the order of its test-type list.

        PRD: "Verification happens in **Test Bays**, registered by the
        `PlantScheduler` with a `bay_code` unique across bays, the `plant_code` of the
        plant they sit in, a non-empty `supported_test_types` list drawn from `BRAKE`,
        `EMERGENCY_EXIT`, `ELECTRICAL`, `JOINT_STRENGTH` and `ROLLOVER`, and a
        `max_concurrent_electrical` of at least 1".

        Design: Corner/endpoints/test_bay_create_read_and_filtered_listing_round_trip
        """
        supported = ["BRAKE", "EMERGENCY_EXIT", "ELECTRICAL"]
        response = api_client.create_test_bay(
            {
                "bay_code": "TB-1",
                "plant_code": "PLANT-A",
                "supported_test_types": supported,
                "max_concurrent_electrical": 2,
            },
            PLANT,
        )
        created = validate_success(response, 201)
        assert_response_type(response, "object")
        assert_envelope_meta(response.json())
        assert_test_bay(created)
        assert_common_fields(created, expected_version=1)
        assert created["bay_code"] == "TB-1"
        assert created["plant_code"] == "PLANT-A"
        assert created["max_concurrent_electrical"] == 2
        # The list keeps the order it was supplied in rather than a sorted order.
        assert created["supported_test_types"] == supported

        by_id = validate_success(api_client.get_test_bay(created["id"], PLANT))
        assert by_id == created

        rows, _ = validate_paginated(
            api_client.list_test_bays(PLANT, {"plant_code": "PLANT-A"})
        )
        assert len(rows) == 1
        assert rows[0] == created

    def test_the_plant_filter_narrows_the_population_the_page_is_cut_from(self):
        """Two bays in one plant and one in another: the filtered listing totals two
        and its second page holds exactly the second bay.

        PRD: "Bays may be listed filtered by `plant_code`."
        PRD: "`total_count` is the number of records matching the request's filters
        before pagination is applied and `has_more` indicates whether records remain
        beyond the current page."

        Design: Corner/endpoints/test_bay_create_read_and_filtered_listing_round_trip
        """
        first = create_bay(
            bay_code="TB-1", supported_test_types=["BRAKE", "EMERGENCY_EXIT",
                                                   "ELECTRICAL"],
            max_concurrent_electrical=2,
        )
        second = create_bay(
            bay_code="TB-2", supported_test_types=["JOINT_STRENGTH", "ROLLOVER"],
            max_concurrent_electrical=1,
        )
        elsewhere = create_bay(
            bay_code="TB-3", plant_code="PLANT-B",
            supported_test_types=["BRAKE"], max_concurrent_electrical=1,
        )

        rows, meta = validate_paginated(
            api_client.list_test_bays(PLANT, {"plant_code": "PLANT-A"})
        )
        assert_pagination_meta(meta, limit=10, offset=0, total_count=2, has_more=False)
        assert {row["id"] for row in rows} == {first["id"], second["id"]}
        assert elsewhere["id"] not in {row["id"] for row in rows}

        page, page_meta = validate_paginated(
            api_client.list_test_bays(
                PLANT, {"plant_code": "PLANT-A", "limit": 1, "offset": 1}
            )
        )
        assert_pagination_meta(page_meta, limit=1, offset=1, total_count=2,
                               has_more=False)
        assert len(page) == 1
        assert page[0]["id"] == second["id"]
        assert page[0]["supported_test_types"] == ["JOINT_STRENGTH", "ROLLOVER"]

        every, all_meta = validate_paginated(api_client.list_test_bays(PLANT))
        assert all_meta["total_count"] == 3


class TestBidDraftLinkChecks:
    """Two different cross-links, checked at two different moments."""

    def test_the_pack_count_is_checked_at_registration_and_the_model_at_draft(self):
        """Nine battery packs are refused against an eight-bay body while eight are
        accepted, and a package quoted on a body it does not name is refused as an
        incompatibility rather than as a missing record.

        PRD: "Registering an electric package whose `battery_pack_count` exceeds the
        target model's `max_battery_bays` is refused with
        `ERR_BATTERY_BAY_CAPACITY_EXCEEDED`."
        PRD: "The chosen package must name the chosen model in its
        `compatible_bus_model_id` — a mismatch is refused with
        `ERR_PROPULSION_MODEL_INCOMPATIBLE`".

        Design: Corner/endpoints/bid_creation_links_package_to_model_and_battery_packs_to_bays
        """
        conventional = create_bus_model()
        transit = create_bus_model(type_d_transit_model_payload())
        diesel = create_propulsion_package(diesel_package_payload(conventional["id"]))
        profile = create_profile(tx_profile_payload(), publish=True)
        solicitation = create_solicitation(
            profile["id"],
            solicitation_code="SOL-TX-120",
            buyer_name="Garland ISD",
            price_cap_cents_per_unit=40_000_000,
        )

        overfull = electric_package_payload(
            transit["id"], package_code="ELEC-BIG", battery_pack_count=9
        )
        validate_error(
            api_client.create_propulsion_package(overfull, COMPLIANCE),
            ApiErrorId.ERR_BATTERY_BAY_CAPACITY_EXCEEDED.value,
            422,
        )
        _, package_meta = validate_paginated(
            api_client.list_propulsion_packages(COMPLIANCE)
        )
        assert package_meta["total_count"] == 1

        # Eight packs into eight bays: the ceiling is inclusive.
        exact = electric_package_payload(
            transit["id"], package_code="ELEC-BIG", battery_pack_count=8
        )
        fitted = validate_success(
            api_client.create_propulsion_package(exact, COMPLIANCE), 201
        )
        assert fitted["battery_pack_count"] == 8

        mismatched = bid_payload(
            solicitation["id"], transit["id"], diesel["id"],
            **dict(TX_BID_CONFIG, offered_seat_capacity=84,
                   offered_emergency_exit_count=6),
        )
        validate_error(
            api_client.create_bid(mismatched, SALES),
            ApiErrorId.ERR_PROPULSION_MODEL_INCOMPATIBLE.value,
            422,
        )
        _, bid_meta = validate_paginated(api_client.list_bids(SALES))
        assert bid_meta["total_count"] == 0

        matched = validate_success(
            api_client.create_bid(
                bid_payload(
                    solicitation["id"], conventional["id"], diesel["id"],
                    **TX_BID_CONFIG,
                ),
                SALES,
            ),
            201,
        )
        assert_bid(matched)
        assert matched["bus_model_id"] == conventional["id"]
        assert matched["propulsion_package_id"] == diesel["id"]
        assert matched["provisional_unit_price_cents"] == TX_BID_PRICE_CENTS


class TestReadsAreFreeOfSideEffects:
    """Every derived figure is present in the creating response and frozen by it."""

    def _bid_priced_on_rolling_nevada_terrain(self) -> dict:
        """The PRD's worked electric package quoted into a two-bus Nevada
        solicitation whose profile mandates the lighting items."""
        model = create_bus_model()
        package = create_propulsion_package(electric_package_payload(model["id"]))
        profile = create_profile(
            nv_profile_payload(
                requires_eight_lamp_system=True,
                requires_crossing_arm=True,
                terrain_class="ROLLING",
            ),
            publish=True,
        )
        solicitation = create_solicitation(
            profile["id"],
            solicitation_code="SOL-NV-121",
            buyer_name="Washoe County SD",
            unit_count=2,
            price_cap_cents_per_unit=40_000_000,
        )
        return {
            "model": model, "package": package, "profile": profile,
            "solicitation": solicitation,
        }

    def test_a_read_returns_the_stored_figures_and_a_clock_move_changes_none_of_them(
        self,
    ):
        """The draft response already carries range, price and verdict; two reads
        either side of a two-month clock jump return exactly the same body, with the
        same version and the same modification stamp.

        PRD: "Retrieval endpoints never recompute anything — reading an order returns
        the posture and damages figure last written by a business transition, not a
        fresh evaluation against the current clock."
        PRD: "Its effective consumption is 1.425 kilowatt-hours per mile and its
        available energy is 122.76 kilowatt-hours, so on `ROLLING` terrain its route
        range is `79.7` miles".

        Design: Corner/endpoints/reads_return_computed_fields_without_recomputing_or_mutating
        """
        scenario = self._bid_priced_on_rolling_nevada_terrain()
        drafted = validate_success(
            api_client.create_bid(
                bid_payload(
                    scenario["solicitation"]["id"],
                    scenario["model"]["id"],
                    scenario["package"]["id"],
                    unit_count=2,
                    offered_eight_lamp_system=True,
                    offered_crossing_arm=True,
                ),
                SALES,
            ),
            201,
        )
        assert drafted["nominal_range_mi"] == NOMINAL_RANGE_MI
        assert drafted["derated_route_range_mi"] == DERATED_RANGE_MI
        assert drafted["provisional_unit_price_cents"] == NV_ELECTRIC_PRICE_CENTS
        assert drafted["spec_compliance_status"] == "CONFORMING"
        assert drafted["exception_count"] == 0
        assert drafted["unmet_mandatory_items"] == []
        assert drafted["version"] == 1

        first_response = api_client.get_bid(drafted["id"], SALES)
        first = validate_success(first_response)
        assert_response_type(first_response, "object")
        assert first == drafted

        set_clock(LATER_CLOCK)
        second_response = api_client.get_bid(drafted["id"], SALES)
        second = validate_success(second_response)
        # A clock two months on recomputes nothing and mutates nothing.
        assert second == drafted
        assert second["version"] == 1
        assert second["updated_at"] == drafted["updated_at"]
        assert second["derated_route_range_mi"] == DERATED_RANGE_MI

        # Each read is nonetheless its own correlated request.
        assert_envelope_meta(first_response.json())
        assert_envelope_meta(second_response.json())
        assert (
            first_response.json()["meta"]["api_request_id"]
            != second_response.json()["meta"]["api_request_id"]
        )


class TestLineStatusAction:
    """One endpoint, two directions, and a version that moves on each of them."""

    def test_taking_the_line_down_and_bringing_it_back_up_bumps_the_version_twice(self):
        """The same action drives the line down and back up, each call returning 200
        and the next version, while the booking ledger never moves.

        PRD: "Taking a line down and bringing it back up are the same operation with a
        different `status` in the payload."
        PRD: "Either transition increments the line's `version` by 1."

        Design: Corner/endpoints/line_status_action_toggles_state_and_bumps_the_occ_version
        """
        line = create_line()
        assert line["status"] == "RUNNING"
        assert line["version"] == 1
        assert_line_ledger(line, 0)

        down_response = api_client.set_production_line_status(
            line["id"], "DOWN_FOR_MAINTENANCE", PLANT
        )
        down = validate_success(down_response, 200)
        assert_production_line(down)
        assert down["status"] == "DOWN_FOR_MAINTENANCE"
        assert down["version"] == 2
        assert_line_ledger(down, 0)

        up = validate_success(
            api_client.set_production_line_status(line["id"], "RUNNING", PLANT), 200
        )
        assert up["status"] == "RUNNING"
        assert up["version"] == 3
        assert_line_ledger(up, 0)

        # The read agrees with the last action body and adds no version of its own.
        after = read_line(line["id"])
        assert after["status"] == "RUNNING"
        assert after["version"] == 3
        assert_line_ledger(after, 0)
        assert after["updated_at"] == up["updated_at"]
