"""Inclusive boundaries: a route range at the tenth, a recall window at its endpoint."""

from test_helpers import (
    CLOCK_START_UTC,
    COMPLIANCE,
    PLANT,
    ApiErrorId,
    api_client,
    award_bid,
    close_solicitation,
    create_bid,
    create_bus_model,
    create_campaign,
    create_profile,
    create_propulsion_package,
    create_solicitation,
    electric_package_payload,
    list_tasks,
    mint_unit,
    read_bid,
    read_campaign,
    read_dealer,
    read_order,
    read_unit,
    setup_dealer_with_legacy_units,
    setup_tx_catalogue,
    spec_profile_payload,
    submit_bid,
    validate_error,
    validate_success,
)

# 122.76 available kilowatt-hours over an effective 1.425 per mile, divided by the
# 1.08 rolling terrain factor, truncated at the first decimal place.
ROLLING_ELECTRIC_RANGE_MI = 79.7
ELECTRIC_NOMINAL_RANGE_MI = 147


def _rolling_profile_payload(state_code: str, required_route_range_mi: float) -> dict:
    """A profile on rolling terrain whose only demanding mandate is route range."""
    return spec_profile_payload(
        state_code=state_code,
        min_seat_capacity=71,
        min_emergency_exit_count=5,
        min_joint_strength_kn=55.0,
        required_route_range_mi=required_route_range_mi,
        terrain_class="ROLLING",
    )


class TestRouteRangeInclusiveBoundaryAtOneDecimal:
    """A derated route range of exactly 79.7 miles clears a 79.7 mile requirement
    and fails a 79.8 mile one."""

    def _two_awards_on_one_electric_package(self) -> dict:
        """One electric body sold into two states: one demanding exactly the range
        it delivers, one whose requirement is re-legislated upward before award."""
        model = create_bus_model()
        package = create_propulsion_package(electric_package_payload(model["id"]))
        exact = create_profile(_rolling_profile_payload("NY", 79.7))
        lenient = create_profile(_rolling_profile_payload("CT", 79.6))

        bids = {}
        solicitations = {}
        for key, profile, code in (
            ("exact", exact, "SOL-NY-001"),
            ("lenient", lenient, "SOL-CT-001"),
        ):
            solicitation = create_solicitation(
                profile["id"],
                solicitation_code=code,
                buyer_name="Regional Transportation Authority",
                unit_count=1,
                required_delivery_date="2026-12-01",
            )
            bid = create_bid(solicitation["id"], model["id"], package["id"])
            solicitations[key] = solicitation
            bids[key] = submit_bid(bid["id"])

        # Connecticut raises its floor by one tenth of a mile before either award.
        stricter = create_profile(_rolling_profile_payload("CT", 79.8))

        orders = {}
        for key in ("exact", "lenient"):
            close_solicitation(solicitations[key]["id"])
            orders[key] = award_bid(bids[key]["id"], "2026-12-01")
        return {
            "model": model,
            "package": package,
            "exact_profile": exact,
            "lenient_profile": lenient,
            "stricter_profile": stricter,
            "bids": bids,
            "orders": orders,
        }

    def test_a_range_equal_to_the_requirement_mints_a_bus(self):
        """The truncated figure of 79.7 miles satisfies a 79.7 mile requirement
        because every route-range boundary is inclusive.

        PRD: "A value computed as 79.789 miles is reported as `79.7`, not `79.8`,
        and because every route-range gate in the system compares against that
        reported figure with an inclusive boundary, the difference between
        truncating and rounding is the difference between a conforming and a
        nonconforming bus."

        Design: Difficulty/boundary_precision_check/route_range_inclusive_boundary_at_one_decimal_place
        """
        scenario = self._two_awards_on_one_electric_package()
        bid = read_bid(scenario["bids"]["exact"]["id"])
        assert bid["derated_route_range_mi"] == ROLLING_ELECTRIC_RANGE_MI
        assert bid["nominal_range_mi"] == ELECTRIC_NOMINAL_RANGE_MI
        assert bid["spec_compliance_status"] == "CONFORMING"
        assert bid["unmet_mandatory_items"] == []

        unit = mint_unit(scenario["orders"]["exact"]["id"], "1NYELE0000000001")
        assert unit["derated_route_range_mi"] == ROLLING_ELECTRIC_RANGE_MI
        assert unit["nominal_range_mi"] == ELECTRIC_NOMINAL_RANGE_MI
        assert unit["registration_state_code"] == "NY"
        assert unit["production_status"] == "PLANNED"
        assert read_order(scenario["orders"]["exact"]["id"])["created_unit_count"] == 1

    def test_one_tenth_more_requirement_is_re_gated_at_mint_and_not_at_award(self):
        """The award accepts a bid whose range no longer clears the newly published
        floor, and the shortfall of a single tenth surfaces on the mint instead.

        PRD: "The award deliberately does **not** re-gate engineering conformance
        against the award-time profile."
        PRD: "the bus's derated route range must be at least the profile's
        `required_route_range_mi`, or the mint is refused with
        `ERR_ROUTE_RANGE_INSUFFICIENT`".

        Design: Difficulty/boundary_precision_check/route_range_inclusive_boundary_at_one_decimal_place
        """
        scenario = self._two_awards_on_one_electric_package()
        order = scenario["orders"]["lenient"]
        # The bid conformed against the 79.6 mile text it was evaluated under.
        assert scenario["bids"]["lenient"]["spec_compliance_status"] == "CONFORMING"
        assert (
            scenario["bids"]["lenient"]["evaluated_spec_profile_id"]
            == scenario["lenient_profile"]["id"]
        )
        # The award still succeeded and carried the order onto the newer text.
        assert order["spec_profile_id"] == scenario["stricter_profile"]["id"]
        assert order["status"] == "ACTIVE"

        refused = api_client.mint_bus_unit(order["id"], "1CTELE0000000001", PLANT)
        validate_error(refused, ApiErrorId.ERR_ROUTE_RANGE_INSUFFICIENT.value)
        assert read_order(order["id"])["created_unit_count"] == 0


class TestRecallWindowClosedOnTheDeliveryDate:
    """A recall's delivery window includes both endpoints, so one day decides
    whether a bus is swept in."""

    def _fleet_delivered_on_the_first_of_august(self) -> dict:
        """A Texas dealer holding a single bus delivered exactly on 2026-08-01, with
        two campaigns whose windows end either side of that date."""
        scenario = setup_dealer_with_legacy_units(
            setup_tx_catalogue(),
            deliveries=[("1TXDSL0000008801", "2026-08-01T00:00:00Z")],
            dealer_overrides={
                "dealer_code": "D-TX-02",
                "dealer_name": "Panhandle Bus Center",
                "licensed_state_codes": ["TX"],
                "training_capacity_per_month": 12,
            },
            clock=CLOCK_START_UTC,
        )
        model_id = scenario["model"]["id"]
        window = {"build_window_start": "2026-01-01", "kits_per_unit": 1,
                  "total_kits": 3}
        scenario["campaign_before"] = create_campaign(
            model_id, campaign_code="RC-EDGE-A",
            build_window_end="2026-07-31", **window
        )
        scenario["campaign_inclusive"] = create_campaign(
            model_id, campaign_code="RC-EDGE-B",
            build_window_end="2026-08-01", **window
        )
        return scenario

    def test_a_window_ending_the_day_before_delivery_sweeps_nothing(self):
        """A bus delivered the day after the window closes is out of scope, so the
        launch is refused and the campaign keeps every kit it stocked.

        PRD: "both endpoints are in scope, so a bus delivered exactly on the
        window's last day is covered and one delivered the next day is not".
        PRD: "the scope to yield at least one bus, otherwise
        `ERR_NO_AFFECTED_UNITS`".

        Design: Difficulty/boundary_precision_check/recall_build_window_closed_endpoint_on_delivery_date
        """
        scenario = self._fleet_delivered_on_the_first_of_august()
        campaign = scenario["campaign_before"]
        assert campaign["status"] == "DRAFT"
        assert campaign["available_kits"] == 3

        refused = api_client.launch_recall_campaign(campaign["id"], COMPLIANCE)
        validate_error(refused, ApiErrorId.ERR_NO_AFFECTED_UNITS.value)

        after = read_campaign(campaign["id"])
        assert after["status"] == "DRAFT"
        assert after["launched_at"] in (None, "")
        assert after["affected_unit_count"] == 0
        assert after["reserved_kits"] == 0
        assert after["available_kits"] == 3
        assert list_tasks(recall_campaign_id=campaign["id"]) == []
        assert read_unit(scenario["legacy_units"][0]["id"])["service_status"] == "NONE"

    def test_a_window_ending_on_the_delivery_date_covers_the_bus(self):
        """Extending the window by exactly one day brings the same bus into scope
        and opens one remedy task against it.

        PRD: "whose `delivered_at` date falls on or after `build_window_start` and
        on or before `build_window_end` — both endpoints are in scope".
        PRD: "Standing follows from the count alone: `SUSPENDED` at 4 or more open
        buses, `RESTRICTED` at 2 or 3, `GOOD` below 2."

        Design: Difficulty/boundary_precision_check/recall_build_window_closed_endpoint_on_delivery_date
        """
        scenario = self._fleet_delivered_on_the_first_of_august()
        campaign = scenario["campaign_inclusive"]

        launched = validate_success(
            api_client.launch_recall_campaign(campaign["id"], COMPLIANCE)
        )
        assert launched["status"] == "LAUNCHED"
        assert launched["affected_unit_count"] == 1
        assert launched["reserved_kits"] == 1
        assert launched["consumed_kits"] == 0
        assert launched["available_kits"] == 2
        assert launched["escalated_task_count"] == 0
        assert launched["kit_shortfall_count"] == 0

        tasks = list_tasks(recall_campaign_id=campaign["id"])
        assert len(tasks) == 1
        assert tasks[0]["status"] == "OPEN"
        assert tasks[0]["escalation_level"] == "DEALER_DIRECTED"
        assert tasks[0]["kits_reserved"] == 1
        assert tasks[0]["bus_unit_id"] == scenario["legacy_units"][0]["id"]

        assert read_unit(scenario["legacy_units"][0]["id"])["service_status"] == "RECALL_OPEN"
        dealer = read_dealer(scenario["dealer"]["id"])
        assert dealer["open_recall_unit_count"] == 1
        assert dealer["certification_standing"] == "GOOD"
        # The campaign that stopped one day short is untouched by this launch.
        assert read_campaign(scenario["campaign_before"]["id"])["status"] == "DRAFT"
