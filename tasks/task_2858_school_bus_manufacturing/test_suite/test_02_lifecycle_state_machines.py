"""Non-linear lifecycles: independent bus dimensions and the negotiation cycle."""

from test_helpers import (
    COMPLIANCE,
    CONTRACTS,
    SALES,
    TX_BID_CONFIG,
    ApiErrorId,
    api_client,
    assert_same_instant,
    assert_unchanged,
    assert_unit_dimensions,
    bid_revision_payload,
    create_bid,
    create_dealer,
    create_solicitation,
    make_dealer_agent_headers,
    read_bid,
    read_order,
    read_unit,
    setup_tx_catalogue,
    setup_unit_ready_to_certify,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

AWARD_INSTANT = "2026-09-01T00:00:00Z"


def _tx_unit_ready_to_certify(vin: str) -> dict:
    """One Texas bus built, bayed and passed on all three always-required tests,
    against a promise of 2026-10-05."""
    return setup_unit_ready_to_certify(
        setup_tx_catalogue(),
        vin=vin,
        promised_delivery_date="2026-10-05",
        required_delivery_date="2026-10-05",
        solicitation_overrides={"solicitation_code": "SOL-TX-001"},
    )


class TestBusUnitDimensionsMoveIndependently:
    """A bus carries a build phase, a certification verdict, a service state and a
    driver-training flag, and each moves on its own."""

    def test_certification_moves_only_the_certification_dimension(self):
        """Certifying a built bus leaves its build phase at `BUILT` and its service
        state at `NONE`, stamping `certified_at` from the logical clock.

        PRD: "Every bus carries **three independent status dimensions**, and a
        transition in one never implies a transition in another except through an
        explicitly stated side effect."

        Design: Difficulty/non_linear_state_machine/bus_unit_three_dimensions_advance_independently
        """
        scenario = _tx_unit_ready_to_certify("1TXDSL0000000001")
        unit_id = scenario["unit"]["id"]
        before = read_unit(unit_id)
        assert_unit_dimensions(
            before,
            production="BUILT",
            certification="PENDING",
            service="NONE",
            training="PENDING",
        )

        certified = validate_success(api_client.certify_bus_unit(unit_id, COMPLIANCE))
        assert_unit_dimensions(
            certified,
            production="BUILT",
            certification="CERTIFIED",
            service="NONE",
            training="PENDING",
        )
        assert_same_instant(certified["certified_at"], AWARD_INSTANT, "certified_at")
        assert certified["delivered_at"] in (None, "")
        # The engineering figures the bus was minted with are untouched by
        # certification.
        assert certified["joint_strength_kn"] == 58.0
        assert certified["derated_route_range_mi"] == 663.4
        assert_unchanged(before, certified, "vin", "spec_profile_id", "dealer_id")

    def test_dealer_assignment_and_training_touch_neither_build_nor_certification(self):
        """Assigning a dealer sets only `dealer_id`; completing driver training
        sets only `driver_training_status`; delivery then moves the build phase
        alone and fulfils the order.

        PRD: "Assignment sets the bus's `dealer_id` and is not gated on the build
        phase, so a bus may be assigned early in the build and reassigned later as
        long as both gates still hold."
        PRD: "Delivery moves the bus `BUILT → DELIVERED`, which is terminal, and
        sets `delivered_at` to the logical clock instant."

        Design: Difficulty/non_linear_state_machine/bus_unit_three_dimensions_advance_independently
        """
        scenario = _tx_unit_ready_to_certify("1TXDSL0000000002")
        unit_id = scenario["unit"]["id"]
        certified = validate_success(api_client.certify_bus_unit(unit_id, COMPLIANCE))
        dealer = create_dealer()

        assigned = validate_success(
            api_client.assign_dealer(unit_id, dealer["id"], CONTRACTS)
        )
        assert assigned["dealer_id"] == dealer["id"]
        assert_unit_dimensions(
            assigned, production="BUILT", certification="CERTIFIED", training="PENDING"
        )

        trained = validate_success(
            api_client.complete_driver_training(
                unit_id, make_dealer_agent_headers(dealer["id"])
            )
        )
        assert_unit_dimensions(
            trained, production="BUILT", certification="CERTIFIED", training="COMPLETED"
        )
        assert_unchanged(assigned, trained, "production_status", "certification_status")
        assert_same_instant(trained["certified_at"], certified["certified_at"])

        delivered = validate_success(api_client.deliver_bus_unit(unit_id, CONTRACTS))
        assert_unit_dimensions(
            delivered,
            production="DELIVERED",
            certification="CERTIFIED",
            service="NONE",
            training="COMPLETED",
        )
        assert_same_instant(delivered["delivered_at"], AWARD_INSTANT, "delivered_at")

        order = read_order(scenario["order"]["id"])
        assert order["status"] == "FULFILLED"
        assert order["delivered_unit_count"] == 1
        assert order["delivery_posture"] == "ON_TRACK"


class TestNegotiationCycleAndRoundCeiling:
    """A bid may loop draft, submit and send-back three times, and the fourth
    round is refused."""

    def _three_round_bid(self) -> dict:
        """Walk a Texas bid through three negotiation rounds, ending in `DRAFT`."""
        catalogue = setup_tx_catalogue()
        solicitation = create_solicitation(
            catalogue["profile"]["id"],
            solicitation_code="SOL-TX-002",
            unit_count=3,
            required_delivery_date="2026-12-01",
        )
        config = dict(TX_BID_CONFIG)
        config["unit_count"] = 3
        bid = create_bid(
            solicitation["id"],
            catalogue["model"]["id"],
            catalogue["package"]["id"],
            **config,
        )
        for round_index, seats in ((1, 72), (2, 73), (3, 74)):
            current = read_bid(bid["id"])
            payload = bid_revision_payload(
                current["version"],
                offered_seat_capacity=seats,
                offered_emergency_exit_count=5,
                offered_mirror_config="CROSSVIEW",
                offered_eight_lamp_system=True,
                offered_crossing_arm=True,
                note=f"Negotiation round {round_index}.",
            )
            revision = validate_success(
                api_client.create_bid_revision(bid["id"], payload, SALES), 201
            )
            assert revision["round_index"] == round_index
            if round_index < 3:
                submit_bid(bid["id"])
                validate_success(api_client.request_bid_revision(bid["id"], CONTRACTS))
        return {"bid": bid, "solicitation": solicitation}

    def test_the_fourth_round_is_refused_while_the_bid_stays_in_draft(self):
        """Three rounds beyond the initial draft is the ceiling; a fourth append
        draws the round-limit refusal and changes nothing.

        PRD: "it requires that the resulting round index — one above the bid's
        current `revision_round` — not exceed three, since three is the maximum
        number of negotiation rounds a bid may carry beyond its initial draft. A
        fourth round is refused with `ERR_REVISION_ROUND_LIMIT`."

        Design: Difficulty/non_linear_state_machine/bid_revision_cycle_returns_to_draft_until_round_limit
        """
        scenario = self._three_round_bid()
        bid_id = scenario["bid"]["id"]
        before = read_bid(bid_id)
        assert before["revision_round"] == 3
        assert before["status"] == "DRAFT"
        assert before["offered_seat_capacity"] == 74

        refused = api_client.create_bid_revision(
            bid_id,
            bid_revision_payload(
                before["version"],
                offered_seat_capacity=75,
                offered_emergency_exit_count=5,
                offered_mirror_config="CROSSVIEW",
                offered_eight_lamp_system=True,
                offered_crossing_arm=True,
            ),
            SALES,
        )
        validate_error(refused, ApiErrorId.ERR_REVISION_ROUND_LIMIT.value)

        after = read_bid(bid_id)
        assert after["revision_round"] == 3
        assert after["status"] == "DRAFT"
        assert after["offered_seat_capacity"] == 74
        rounds, meta = validate_paginated(
            api_client.list_bid_revisions(bid_id, SALES)
        )
        assert meta["total_count"] == 4

    def test_every_earlier_round_is_superseded_and_the_listing_stays_ordered(self):
        """The round-zero snapshot and rounds one and two are all superseded by
        round three, which is the only live snapshot.

        PRD: "every earlier revision of that bid — including the round-zero
        snapshot — has `is_superseded` set to true".
        PRD: "Revisions of one bid may be listed filtered by `is_superseded`, and
        they come back in ascending `round_index`."

        Design: Difficulty/non_linear_state_machine/bid_revision_cycle_returns_to_draft_until_round_limit
        """
        scenario = self._three_round_bid()
        bid_id = scenario["bid"]["id"]

        rounds, meta = validate_paginated(api_client.list_bid_revisions(bid_id, SALES))
        assert [item["round_index"] for item in rounds] == [0, 1, 2, 3]
        assert [item["is_superseded"] for item in rounds] == [True, True, True, False]
        assert [item["offered_seat_capacity"] for item in rounds] == [71, 72, 73, 74]
        assert meta["total_count"] == 4

        live, live_meta = validate_paginated(
            api_client.list_bid_revisions(bid_id, SALES, {"is_superseded": "false"})
        )
        assert live_meta["total_count"] == 1
        assert live[0]["round_index"] == 3

        bid = read_bid(bid_id)
        assert bid["offered_seat_capacity"] == rounds[3]["offered_seat_capacity"]
        assert bid["provisional_unit_price_cents"] == rounds[3]["unit_price_cents"]
