"""The declared endpoint surface of the catalogue and the read-your-write
visibility of the cascades: which verbs each resource really exposes, which
writes move which ledgers, and how immediately those movements become readable.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_settlement_preview,
    assert_sponsor,
    assert_sponsorship_activation,
)
from test_helpers.constants import CANONICAL_CLOCK_UTC, TEST_DEFAULTS
from test_helpers.factories import (
    build_activation_payload,
    build_contingency_action_payload,
    build_reschedule_payload,
    build_sales_batch_payload,
    build_sponsor_payload,
)
from test_helpers.fixtures import (
    announce_booking,
    booking_version,
    cancel_activation,
    confirm_activation,
    create_activation,
    create_sponsor,
    get_activation,
    get_booking,
    get_edition,
    get_stage,
    get_ticket_scale,
    prepare_completed_advance,
    record_sales_batch,
    set_clock,
    settlement_preview,
    setup_accepted_booking,
    setup_announced_booking,
    setup_base_world,
    setup_scaled_booking,
    setup_sent_offer,
)
from test_helpers.test_users import (
    BOX_OFFICE_MANAGER_HEADERS,
    FAIR_OPERATIONS_DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SETTLEMENT_CONTROLLER_HEADERS,
    SPONSORSHIP_DIRECTOR_HEADERS,
    TALENT_BUYER_HEADERS,
)

# One reserved GOLD tier priced so that the show's gross potential clears the
# high-demand sponsorship threshold: 6295 cents of face value on 2000 seats.
GOLD_TIER = {
    "seating_type": "RESERVED",
    "tier_name": "GOLD",
    "face_price_cents": 6295,
    "allotment_seats": 2000,
    "bundled_with_gate_admission": False,
    "facility_fee_cents": 400,
}


class TestEndpointSurface:
    """The verbs the catalogue declares for each resource, and nothing more."""

    def test_sponsor_is_created_and_read_back_field_for_field(self):
        """A sponsor is registered with a company name, a trade category and an
        exclusivity tier, and reading one back by identifier returns exactly that
        sponsor. The catalogue offers no sponsor list, so the only way to
        enumerate a sponsor's work is the activation reverse lookup.

        "registers the sponsor itself with a company `name`, a trade `category`"

        Design: Corner/endpoints/sponsor_surface_is_create_and_read_only
        """
        set_clock(CANONICAL_CLOCK_UTC)

        first_payload = build_sponsor_payload(
            name="Ridgeline Motors",
            category="AUTOMOTIVE",
            exclusivity_tier="PRESENTING",
        )
        second_payload = build_sponsor_payload(
            name="Prairie Cola",
            category="BEVERAGE",
            exclusivity_tier="SUPPORTING",
        )
        first = validate_success(
            api_client.create_sponsor(first_payload, SPONSORSHIP_DIRECTOR_HEADERS),
            expected_status=201,
        )
        second = validate_success(
            api_client.create_sponsor(second_payload, SPONSORSHIP_DIRECTOR_HEADERS),
            expected_status=201,
        )

        read_first = validate_success(
            api_client.get_sponsor(first["id"], SPONSORSHIP_DIRECTOR_HEADERS)
        )
        assert_sponsor(read_first)
        assert read_first["id"] == first["id"]
        assert read_first["name"] == "Ridgeline Motors"
        assert read_first["category"] == "AUTOMOTIVE"
        assert read_first["exclusivity_tier"] == "PRESENTING"
        assert read_first["version"] == 1
        assert read_first["created_at"] == CANONICAL_CLOCK_UTC
        assert read_first["updated_at"] == CANONICAL_CLOCK_UTC

        # The path identifier selects the record: the second read must not
        # hand back the first sponsor.
        read_second = validate_success(
            api_client.get_sponsor(second["id"], SETTLEMENT_CONTROLLER_HEADERS)
        )
        assert_sponsor(read_second)
        assert read_second["id"] == second["id"]
        assert read_second["name"] == "Prairie Cola"
        assert read_second["category"] == "BEVERAGE"
        assert read_second["exclusivity_tier"] == "SUPPORTING"

        activations, meta = validate_paginated(
            api_client.list_sponsorship_activations(
                SPONSORSHIP_DIRECTOR_HEADERS, {"sponsor_id": first["id"]}
            )
        )
        assert activations == []
        assert meta["total_count"] == 0

    def test_reschedule_moves_the_coordinates_and_leaves_the_hold_ledger_alone(self):
        """Rescheduling is the still-unannounced booking's self-loop: the show
        date and both occupation instants are overwritten and the booking's
        version increments, but the slot has only shifted inside the same stage,
        so the stage's slot ledger and the edition's open-stage count do not move.

        "The stage's `held_show_count` does not move, because the slot has shifted within the same stage"

        Design: Corner/endpoints/reschedule_moves_coordinates_without_moving_the_hold_ledger
        """
        world = setup_base_world()
        scenario = setup_accepted_booking(
            world, radius_miles=0, radius_days_before=0, radius_days_after=0
        )
        booking = scenario["booking"]

        stage_before = get_stage(world["stage"]["id"])
        edition_before = get_edition(world["edition"]["id"])
        assert stage_before["held_show_count"] == 1
        assert stage_before["booking_posture"] == "OPEN"
        version_before = booking_version(booking["id"])

        payload = build_reschedule_payload(
            "2026-08-24", "2026-08-24T14:00:00.000Z", "2026-08-24T23:00:00.000Z"
        )
        rescheduled = validate_success(
            api_client.reschedule_show_booking(
                booking["id"], payload, FAIR_OPERATIONS_DIRECTOR_HEADERS
            )
        )
        assert rescheduled["id"] == booking["id"]
        assert rescheduled["show_date"] == "2026-08-24"
        assert rescheduled["load_in_start_utc"] == "2026-08-24T14:00:00.000Z"
        assert rescheduled["load_out_end_utc"] == "2026-08-24T23:00:00.000Z"
        assert rescheduled["booking_status"] == "DATE_HELD"
        assert rescheduled["ticketing_status"] == "SCALED_PENDING"
        assert rescheduled["version"] == version_before + 1

        stage_after = get_stage(world["stage"]["id"])
        assert stage_after["held_show_count"] == 1
        assert stage_after["booking_posture"] == "OPEN"
        edition_after = get_edition(world["edition"]["id"])
        assert edition_after["open_stage_count"] == edition_before["open_stage_count"]

        # The contract keeps the date it was signed on; the booking owns the
        # coordinates once it exists.
        offer_after = validate_success(
            api_client.get_offer(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
        )
        assert offer_after["target_show_date"] == TEST_DEFAULTS["TARGET_SHOW_DATE"]
        assert offer_after["status"] == "ACCEPTED"

    def test_activation_is_reachable_from_the_sponsor_and_from_the_show(self):
        """An activation names two independent parents in one body, and each
        unresolvable identifier reports its own not-found code. Once created, the
        row is discoverable from either side of the junction, and the status filter
        composes on top of the parent filter.

        "a `sponsor_id` that identifies no sponsor yields `ERR_SPONSOR_NOT_FOUND`"
        "Activations are listable with optional filters on `sponsor_id`, on `booking_id`, on `rights` and on `status`"

        Design: Corner/endpoints/activation_is_reachable_from_both_of_its_parents
        """
        scenario = setup_scaled_booking(scale_overrides=dict(GOLD_TIER))
        booking = get_booking(scenario["booking"]["id"])
        assert booking["gross_potential_cents"] == 11866075

        motors = create_sponsor(
            name="Ridgeline Motors",
            category="AUTOMOTIVE",
            exclusivity_tier="SUPPORTING",
        )
        cola = create_sponsor(
            name="Prairie Cola", category="BEVERAGE", exclusivity_tier="SUPPORTING"
        )

        unknown_sponsor_payload = build_activation_payload(
            NON_EXISTENT_UUID,
            booking["id"],
            booking_version(booking["id"]),
            rights="SIGNAGE",
            base_fee_cents=1_000_000,
            exclusivity_category="AUTOMOTIVE",
        )
        validate_error(
            api_client.create_sponsorship_activation(
                unknown_sponsor_payload, SPONSORSHIP_DIRECTOR_HEADERS
            ),
            ApiErrorId.ERR_SPONSOR_NOT_FOUND.value,
        )

        unknown_booking_payload = build_activation_payload(
            motors["id"],
            NON_EXISTENT_UUID,
            booking_version(booking["id"]),
            rights="SIGNAGE",
            base_fee_cents=1_000_000,
            exclusivity_category="AUTOMOTIVE",
        )
        validate_error(
            api_client.create_sponsorship_activation(
                unknown_booking_payload, SPONSORSHIP_DIRECTOR_HEADERS
            ),
            ApiErrorId.ERR_SHOW_BOOKING_NOT_FOUND.value,
        )

        motors_activation = validate_success(
            api_client.create_sponsorship_activation(
                build_activation_payload(
                    motors["id"],
                    booking["id"],
                    booking_version(booking["id"]),
                    rights="SIGNAGE",
                    base_fee_cents=1_000_000,
                    exclusivity_category="AUTOMOTIVE",
                ),
                SPONSORSHIP_DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert_sponsorship_activation(motors_activation)
        assert motors_activation["status"] == "PROPOSED"
        assert motors_activation["make_good_credit_cents"] == 0

        cola_activation = validate_success(
            api_client.create_sponsorship_activation(
                build_activation_payload(
                    cola["id"],
                    booking["id"],
                    booking_version(booking["id"]),
                    rights="SAMPLING",
                    base_fee_cents=400_000,
                    exclusivity_category="BEVERAGE",
                ),
                SPONSORSHIP_DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert cola_activation["status"] == "PROPOSED"
        assert cola_activation["make_good_credit_cents"] == 0

        by_sponsor, sponsor_meta = validate_paginated(
            api_client.list_sponsorship_activations(
                SPONSORSHIP_DIRECTOR_HEADERS, {"sponsor_id": motors["id"]}
            )
        )
        assert sponsor_meta["total_count"] == 1
        assert [record["id"] for record in by_sponsor] == [motors_activation["id"]]

        by_booking, booking_meta = validate_paginated(
            api_client.list_sponsorship_activations(
                TALENT_BUYER_HEADERS, {"booking_id": booking["id"]}
            )
        )
        assert booking_meta["total_count"] == 2
        assert {record["id"] for record in by_booking} == {
            motors_activation["id"],
            cola_activation["id"],
        }

        # The filters compose, and a merely proposed package is not a confirmed one.
        confirmed, confirmed_meta = validate_paginated(
            api_client.list_sponsorship_activations(
                TALENT_BUYER_HEADERS,
                {"booking_id": booking["id"], "status": "CONFIRMED"},
            )
        )
        assert confirmed == []
        assert confirmed_meta["total_count"] == 0

        cola_read = validate_success(
            api_client.get_sponsorship_activation(
                cola_activation["id"], SETTLEMENT_CONTROLLER_HEADERS
            )
        )
        assert cola_read["net_fee_cents"] == 440000

    def test_settlement_preview_computes_the_waterfall_and_persists_nothing(self):
        """The preview runs the same three computations the submission runs and
        answers with the eleven money figures plus the basis that produced them,
        while creating no settlement and touching no booking.

        "It persists nothing: no settlement is created, no booking is touched, no version moves."

        Design: Corner/endpoints/settlement_preview_is_a_pure_computed_read
        """
        scenario = setup_announced_booking(
            scale_overrides=dict(GOLD_TIER),
            doors_time_utc="2026-08-22T18:00:00.000Z",
        )
        record_sales_batch(
            scenario["ticket_scale"]["id"], batch_kind="SALE", quantity=1800, channel="ONLINE"
        )
        booking_before = get_booking(scenario["booking"]["id"])

        final_preview = settlement_preview(
            booking_before["id"],
            {"basis": "FINAL", "merch_gross_cents": 900000, "merch_seller": "ARTIST"},
            SETTLEMENT_CONTROLLER_HEADERS,
        )
        assert_settlement_preview(final_preview)
        assert "id" not in final_preview
        assert "version" not in final_preview
        assert final_preview["adjusted_gross_cents"] == 10679468
        assert final_preview["net_pool_cents"] == 7741968
        assert final_preview["total_artist_settlement_cents"] == 13220000

        # Every batch was recorded before doors, so the pre-doors count agrees
        # with the final count on this fixture.
        provisional_preview = settlement_preview(
            booking_before["id"],
            {"basis": "PROVISIONAL", "merch_gross_cents": 0, "merch_seller": "VENUE"},
            TALENT_BUYER_HEADERS,
        )
        assert_settlement_preview(provisional_preview)
        assert provisional_preview["adjusted_gross_cents"] == 10679468
        assert provisional_preview["merch_hall_fee_cents"] == 25000
        assert provisional_preview["merch_artist_share_cents"] == -25000

        default_preview = settlement_preview(
            booking_before["id"], None, SETTLEMENT_CONTROLLER_HEADERS
        )
        assert_settlement_preview(default_preview)
        assert default_preview["merch_hall_fee_cents"] == 25000

        settlements, settlement_meta = validate_paginated(
            api_client.list_settlements(
                SETTLEMENT_CONTROLLER_HEADERS, {"booking_id": booking_before["id"]}
            )
        )
        assert settlements == []
        assert settlement_meta["total_count"] == 0

        booking_after = get_booking(booking_before["id"])
        assert booking_after["version"] == booking_before["version"]
        assert booking_after["booking_status"] == "ANNOUNCED"
        assert booking_after["updated_at"] == booking_before["updated_at"]

    def test_sales_batches_are_admitted_only_while_the_show_is_on_sale(self):
        """Box-office movement is gated on the owning show's box-office
        dimension, not on the price tier's own status: the identical batch is
        refused while the show is merely scaled, admitted once the announcement
        has put it on sale, and refused again once a cancellation has pushed it
        into refunding.

        "sale and refund batches become writable; in every other box-office status an attempt to record one is refused"

        Design: Corner/endpoints/sales_batches_are_writable_only_while_on_sale
        """
        scenario = setup_scaled_booking(scale_overrides=dict(GOLD_TIER))
        prepare_completed_advance(scenario)
        booking_id = scenario["booking"]["id"]
        scale_id = scenario["ticket_scale"]["id"]

        assert get_booking(booking_id)["ticketing_status"] == "SCALED"
        batch_payload = build_sales_batch_payload(
            batch_kind="SALE", quantity=100, channel="ONLINE"
        )
        validate_error(
            api_client.create_sales_batch(
                scale_id, batch_payload, BOX_OFFICE_MANAGER_HEADERS
            ),
            ApiErrorId.ERR_INVALID_TICKETING_STATE.value,
        )

        announced = announce_booking(booking_id, "2026-08-22T18:00:00.000Z")
        assert announced["ticketing_status"] == "ON_SALE"

        # Nothing about the request changed; only the show's box-office state did.
        validate_success(
            api_client.create_sales_batch(
                scale_id, batch_payload, BOX_OFFICE_MANAGER_HEADERS
            ),
            expected_status=201,
        )

        action = validate_success(
            api_client.create_contingency_action(
                booking_id,
                build_contingency_action_payload(
                    booking_version(booking_id),
                    action_type="CANCEL",
                    reason_code="SEVERE_WEATHER",
                    refund_policy="FULL_REFUND",
                ),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert action["refund_liability_cents"] == 669500
        cancelled_booking = get_booking(booking_id)
        assert cancelled_booking["booking_status"] == "CANCELLED"
        assert cancelled_booking["ticketing_status"] == "REFUNDING"

        validate_error(
            api_client.create_sales_batch(
                scale_id, batch_payload, BOX_OFFICE_MANAGER_HEADERS
            ),
            ApiErrorId.ERR_INVALID_TICKETING_STATE.value,
        )

        batches, batch_meta = validate_paginated(
            api_client.list_sales_batches(scale_id, BOX_OFFICE_MANAGER_HEADERS)
        )
        assert batch_meta["total_count"] == 1
        assert len(batches) == 1

        scale = get_ticket_scale(scale_id)
        assert scale["sold_seats"] == 100
        assert scale["available_seats"] == 1900
        assert scale["status"] == "REFUND_DUE"


class TestConsistencyModel:
    """Every cascade is readable at its reconciled value in the very next read."""

    def test_accept_cascade_is_visible_in_its_response_and_in_the_next_read(self):
        """Acceptance writes across the offer, the stage, the edition and three
        cascade-born records, and each of those effects is already reconciled for
        the request that follows. The conversion is slot-neutral: the offer hold
        counted while the offer sat sent is replaced one-for-one by the booking hold.

        "they are always readable at their reconciled value immediately after the request that changed them returns"
        "so `held_show_count` is unchanged and `booking_posture` does not flip"

        Design: Corner/consistency_model/accept_cascade_is_visible_in_its_own_response_and_in_the_very_next_read
        """
        scenario = setup_sent_offer()
        stage_id = scenario["stage"]["id"]
        edition_id = scenario["edition"]["id"]

        stage_before = get_stage(stage_id)
        edition_before = get_edition(edition_id)
        assert stage_before["held_show_count"] == 1
        assert stage_before["booking_posture"] == "OPEN"
        assert edition_before["committed_guarantee_total_cents"] == 12500000
        assert edition_before["open_stage_count"] == 1

        accept_response = api_client.accept_offer(
            scenario["offer"]["id"], scenario["agent_headers"]
        )
        accepted = validate_success(accept_response)
        assert accept_response.json()["response_type"] == "object"
        assert accepted["status"] == "ACCEPTED"
        assert accepted["agreed_guarantee_cents"] == 12500000

        booking_response = api_client.list_show_bookings(
            FAIR_OPERATIONS_DIRECTOR_HEADERS, {"offer_id": scenario["offer"]["id"]}
        )
        bookings, booking_meta = validate_paginated(booking_response)
        assert booking_response.json()["response_type"] == "array"
        assert booking_meta["total_count"] == 1
        booking = bookings[0]
        assert_common_fields(booking)
        assert booking["booking_status"] == "DATE_HELD"
        assert booking["ticketing_status"] == "SCALED_PENDING"

        advances, advance_meta = validate_paginated(
            api_client.list_production_advances(
                PRODUCTION_MANAGER_HEADERS, {"booking_id": booking["id"]}
            )
        )
        assert advance_meta["total_count"] == 1
        assert advances[0]["status"] == "ADVANCE_PENDING"

        rider_items, rider_meta = validate_paginated(
            api_client.list_rider_items(advances[0]["id"], PRODUCTION_MANAGER_HEADERS)
        )
        assert rider_meta["total_count"] == 1
        seed = rider_items[0]
        assert seed["category"] == "STAGING"
        assert seed["description"] == TEST_DEFAULTS["SEED_RIDER_DESCRIPTION"]
        assert seed["is_critical"] is True
        assert seed["requested_cost_cents"] == 0
        assert seed["status"] == "REQUESTED"

        stage_after = get_stage(stage_id)
        assert stage_after["held_show_count"] == 1
        assert stage_after["booking_posture"] == "OPEN"
        edition_after = get_edition(edition_id)
        assert edition_after["committed_guarantee_total_cents"] == 12500000
        assert edition_after["open_stage_count"] == 1

    def test_activation_confirm_and_cancel_move_show_revenue_in_the_same_request(self):
        """Confirming an activation books its net fee into the show's sponsorship
        revenue inside the same request, and cancelling it from confirmed restores
        that figure exactly while booking the make-good credit. The fee itself is
        priced once, at creation, and is never re-derived.

        "recomputes the booking's `sponsorship_revenue_cents` as the sum of `net_fee_cents` across the booking's activations"
        "cancelling sets the activation's `make_good_credit_cents` to its `net_fee_cents`"

        Design: Corner/consistency_model/activation_confirm_and_cancel_move_show_revenue_in_the_same_request
        """
        scenario = setup_announced_booking(
            scale_overrides=dict(GOLD_TIER),
            doors_time_utc="2026-08-22T18:00:00.000Z",
        )
        booking_id = scenario["booking"]["id"]
        assert get_booking(booking_id)["gross_potential_cents"] == 11866075

        sponsor = create_sponsor(
            name="Ridgeline Motors",
            category="AUTOMOTIVE",
            exclusivity_tier="SUPPORTING",
        )
        activation = create_activation(
            sponsor["id"],
            booking_id,
            rights="SIGNAGE",
            base_fee_cents=1_000_000,
            exclusivity_category="AUTOMOTIVE",
        )
        assert activation["net_fee_cents"] == 1100000

        # A merely proposed package contributes nothing to the show's pool.
        assert get_booking(booking_id)["sponsorship_revenue_cents"] == 0

        confirmed = confirm_activation(activation["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert get_booking(booking_id)["sponsorship_revenue_cents"] == 1100000

        preview = settlement_preview(booking_id, None, TALENT_BUYER_HEADERS)
        assert preview["sponsorship_offset_cents"] == 275000

        cancelled = cancel_activation(activation["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["make_good_credit_cents"] == 1100000
        assert get_booking(booking_id)["sponsorship_revenue_cents"] == 0

        assert get_activation(activation["id"])["net_fee_cents"] == 1100000
