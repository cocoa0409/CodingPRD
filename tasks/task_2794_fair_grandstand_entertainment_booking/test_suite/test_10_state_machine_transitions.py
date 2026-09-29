"""State-machine behaviour of the booking spine.

Covers the initial states stamped by the acceptance cascade, the reject/resubmit
arc of a settlement, the clock precondition and side effects of marking a show
performed, the terminal lockdown of a withdrawn offer and of a completed
production advance, and the ledger roll-ups that ride on box-office, rider and
sponsorship transitions.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.factories import (
    build_contingency_action_payload,
    build_counter_payload,
    build_offer_payload,
    build_reschedule_payload,
    build_rider_ruling_payload,
    build_sales_batch_payload,
    build_settlement_rejection_payload,
)
from test_helpers.test_users import (
    BOX_OFFICE_MANAGER_HEADERS,
    FAIR_OPERATIONS_DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SETTLEMENT_CONTROLLER_HEADERS,
    SPONSORSHIP_DIRECTOR_HEADERS,
    TALENT_BUYER_HEADERS,
    make_headers,
)
from test_helpers.types import UserRole

# ---------------------------------------------------------------------------
# The grandstand price structure used throughout: one reserved tier and, where a
# second tier is needed, one lawn tier drawn from the general-admission pool.
# ---------------------------------------------------------------------------
GOLD_SCALE = {
    "seating_type": "RESERVED",
    "tier_name": "GOLD",
    "face_price_cents": 6295,
    "allotment_seats": 2000,
    "bundled_with_gate_admission": False,
    "facility_fee_cents": 400,
}
GOLD_SCALE_GROSS_POTENTIAL_CENTS = 11866075

LAWN_SCALE = {
    "seating_type": "GENERAL_ADMISSION",
    "tier_name": "LAWN",
    "face_price_cents": 3950,
    "allotment_seats": 2100,
    "bundled_with_gate_admission": False,
    "facility_fee_cents": 0,
}
LAWN_SCALE_GROSS_POTENTIAL_CENTS = 7818038

BOOKING_GROSS_POTENTIAL_CENTS = 19684113

DOORS_UTC = "2026-08-22T18:00:00.000Z"
JUST_BEFORE_LOAD_OUT_UTC = "2026-08-22T22:59:59.999Z"
LOAD_OUT_END_UTC = TEST_DEFAULTS["LOAD_OUT_END_UTC"]
AFTER_LOAD_OUT_UTC = "2026-08-22T23:30:00.000Z"

SPONSOR = {
    "name": "Prairie Cola",
    "category": "BEVERAGE",
    "exclusivity_tier": "SUPPORTING",
}
ACTIVATION_BASE_FEE_CENTS = 1000000
ACTIVATION_NET_FEE_CENTS = 1100000


class TestAcceptanceCascadeInitialStates:
    """Every row born of an accepted offer lands on its declared initial state."""

    def test_cascade_booking_starts_date_held_and_scaled_pending_with_zero_ledgers(self):
        """Acceptance materialises a show booking on both of its declared starting
        states, with its gates-open and announcement instants still unset and all
        five of its derived money and attendance ledgers at zero.

        "Its contractual dimension `booking_status` starts at `DATE_HELD` and its box-office dimension `ticketing_status` starts at `SCALED_PENDING`"

        Design: Corner/state_machines/accept_cascade_stamps_declared_initial_states
        """
        scenario = fixtures.setup_accepted_booking()

        booking = fixtures.get_booking(scenario["booking"]["id"])
        assertions.assert_show_booking(booking)
        assert booking["booking_status"] == "DATE_HELD"
        assert booking["ticketing_status"] == "SCALED_PENDING"
        assert booking["doors_time_utc"] is None
        assert booking["announced_at_utc"] is None
        assert booking["postponed_from_booking_id"] is None
        assert booking["gross_potential_cents"] == 0
        assert booking["paid_attendance"] == 0
        assert booking["sponsorship_revenue_cents"] == 0
        assert booking["refund_liability_cents"] == 0
        assert booking["recoupable_production_cost_cents"] == 0

    def test_cascade_creates_one_pending_advance_and_one_seed_staging_line(self):
        """The production advance born beneath the booking starts pending with all
        three of its cost ledgers at zero, and the seed staging line it carries is
        a critical, zero-cost request awaiting a ruling.

        "carrying the booking's identifier as its `booking_id` and starting in status `ADVANCE_PENDING`"

        Design: Corner/state_machines/accept_cascade_stamps_declared_initial_states
        """
        scenario = fixtures.setup_accepted_booking()

        advances, advance_meta = validate_paginated(
            api_client.list_production_advances(
                PRODUCTION_MANAGER_HEADERS, {"booking_id": scenario["booking"]["id"]}
            )
        )
        assert advance_meta["total_count"] == 1
        advance = advances[0]
        assertions.assert_production_advance(advance)
        assert advance["status"] == "ADVANCE_PENDING"
        assert advance["approved_rider_cost_cents"] == 0
        assert advance["recoupable_rider_cost_cents"] == 0
        assert advance["denied_item_count"] == 0
        assert advance["blocked_reason_code"] is None

        staging_lines, line_meta = validate_paginated(
            api_client.list_rider_items(
                advance["id"], PRODUCTION_MANAGER_HEADERS, {"category": "STAGING"}
            )
        )
        assert line_meta["total_count"] == 1
        seed = staging_lines[0]
        assertions.assert_rider_item(seed)
        assert seed["status"] == "REQUESTED"
        assert seed["is_critical"] is True
        assert seed["requested_cost_cents"] == 0
        assert seed["approved_cost_cents"] == 0
        assert seed["artist_recoupable"] is False

    def test_freshly_drafted_offer_starts_in_draft_with_no_rounds_and_no_send_stamps(
        self,
    ):
        """A newly drafted offer is inert alongside an already accepted one: it
        reads as a draft, no negotiation round has been logged against it, and the
        send and expiry instants are still unwritten.

        "It returns HTTP 201 with `status` at `DRAFT`, `round_count` at 0 and `radius_waiver_granted` at false"

        Design: Corner/state_machines/accept_cascade_stamps_declared_initial_states
        """
        world = fixtures.setup_base_world()
        fixtures.setup_accepted_booking(world)

        payload = build_offer_payload(
            world["edition"]["id"],
            world["artist"]["id"],
            world["stage"]["id"],
            deal_type="GUARANTEE_PLUS_BACKEND",
            offered_guarantee_cents=500000,
            target_show_date="2026-08-26",
            load_in_start_utc="2026-08-26T14:00:00.000Z",
            load_out_end_utc="2026-08-26T23:00:00.000Z",
        )
        drafted = validate_success(
            api_client.create_offer(payload, TALENT_BUYER_HEADERS), expected_status=201
        )

        assertions.assert_offer(drafted)
        assert drafted["status"] == "DRAFT"
        assert drafted["round_count"] == 0
        assert drafted["sent_at_utc"] is None
        assert drafted["expires_at_utc"] is None
        assert drafted["radius_waiver_granted"] is False
        assert drafted["countered_guarantee_cents"] is None
        assert drafted["agreed_guarantee_cents"] is None


class TestSettlementRejectionArc:
    """A rejected settlement falls back to draft and can climb back up."""

    def test_rejection_returns_to_draft_and_resubmission_re_enters_pending_approval(
        self,
    ):
        """Rejecting a submitted settlement drops it back to draft, counts the
        revision and forgets who submitted it, and the next submission stamps the
        new submitter without counting a second revision.

        "Rejection increments `revision_count`, records the `rejection_reason_code`, clears `submitted_by_user_id` back to null so the next submission stamps its own submitter"

        Design: Corner/state_machines/settlement_reject_then_resubmit_re_enters_pending_approval
        """
        scenario = fixtures.setup_performed_booking(
            scale_overrides=GOLD_SCALE,
            doors_time_utc=DOORS_UTC,
            sales=[{"batch_kind": "SALE", "quantity": 1800, "channel": "ONLINE"}],
        )
        settlement = fixtures.setup_submitted_settlement(
            scenario, merch_gross_cents=900000, merch_seller="ARTIST"
        )
        assertions.assert_settlement(settlement)
        assert settlement["status"] == "PENDING_APPROVAL"
        assert settlement["revision_count"] == 0
        assert settlement["submitted_by_user_id"] == "buyer-01"
        submitted_version = settlement["version"]

        rejected = validate_success(
            api_client.reject_settlement(
                settlement["id"],
                build_settlement_rejection_payload("GROSS_MISMATCH"),
                SETTLEMENT_CONTROLLER_HEADERS,
            )
        )
        assert rejected["status"] == "DRAFT"

        after_rejection = fixtures.get_settlement(settlement["id"])
        assert after_rejection["status"] == "DRAFT"
        assert after_rejection["revision_count"] == 1
        assert after_rejection["rejection_reason_code"] == "GROSS_MISMATCH"
        assert after_rejection["submitted_by_user_id"] is None
        assert after_rejection["approved_by_user_id"] is None
        assert after_rejection["version"] > submitted_version

        resubmitted = validate_success(
            api_client.submit_settlement(
                settlement["id"],
                make_headers("buyer-07", UserRole.TALENT_BUYER.value),
            )
        )
        assert resubmitted["status"] == "PENDING_APPROVAL"

        after_resubmission = fixtures.get_settlement(settlement["id"])
        assert after_resubmission["status"] == "PENDING_APPROVAL"
        assert after_resubmission["revision_count"] == 1
        assert after_resubmission["submitted_by_user_id"] == "buyer-07"
        assert after_resubmission["approved_by_user_id"] is None
        assert after_resubmission["version"] > after_rejection["version"]


class TestMarkPerformedClockPrecondition:
    """The conclusion of a show is a clock fact, boundary included."""

    def test_mark_performed_refused_a_millisecond_early_and_admitted_on_the_boundary(
        self,
    ):
        """A show cannot be declared performed while the load-out window is still
        running, and the booking is left untouched by the refusal; the very instant
        load-out ends, the same request succeeds.

        "it requires the logical clock to read at or after the booking's `load_out_end_utc`"

        Design: Corner/state_machines/mark_performed_precondition_clock_before_load_out_end
        """
        scenario = fixtures.setup_announced_booking(
            scale_overrides=GOLD_SCALE, doors_time_utc=DOORS_UTC
        )
        booking_id = scenario["booking"]["id"]
        version_before = scenario["booking"]["version"]

        fixtures.set_clock(JUST_BEFORE_LOAD_OUT_UTC)
        validate_error(
            api_client.mark_show_booking_performed(
                booking_id, FAIR_OPERATIONS_DIRECTOR_HEADERS
            ),
            ApiErrorId.ERR_SHOW_NOT_YET_CONCLUDED.value,
        )
        untouched = fixtures.get_booking(booking_id)
        assert untouched["booking_status"] == "ANNOUNCED"
        assert untouched["ticketing_status"] == "ON_SALE"
        assert untouched["version"] == version_before

        fixtures.set_clock(LOAD_OUT_END_UTC)
        performed = validate_success(
            api_client.mark_show_booking_performed(
                booking_id, FAIR_OPERATIONS_DIRECTOR_HEADERS
            )
        )
        assert performed["booking_status"] == "PERFORMED"
        assert performed["ticketing_status"] == "SALES_CLOSED"
        assert performed["version"] > version_before


class TestMarkPerformedConsequences:
    """Marking a show performed lands its four consequences together."""

    def test_mark_performed_closes_both_price_tiers_and_fulfils_the_confirmed_activation(
        self,
    ):
        """Concluding a two-tier show closes the box-office dimension, shuts every
        tier, promotes the confirmed rights package to fulfilled without disturbing
        the revenue it already contributed, and leaves the stage's slot count as it
        was.

        "On success the booking moves `ANNOUNCED → PERFORMED` and four consequences land together"

        Design: Corner/state_machines/mark_performed_closes_every_scale_and_fulfils_confirmed_activation
        """
        scenario = fixtures.setup_scaled_booking(scale_overrides=GOLD_SCALE)
        booking_id = scenario["booking"]["id"]
        assert (
            scenario["ticket_scale"]["scale_gross_potential_cents"]
            == GOLD_SCALE_GROSS_POTENTIAL_CENTS
        )
        lawn = fixtures.add_ticket_scale(booking_id, **LAWN_SCALE)
        assert lawn["scale_gross_potential_cents"] == LAWN_SCALE_GROSS_POTENTIAL_CENTS

        fixtures.prepare_completed_advance(scenario)
        activation = fixtures.setup_confirmed_activation(
            scenario,
            sponsor_overrides=SPONSOR,
            rights="SIGNAGE",
            base_fee_cents=ACTIVATION_BASE_FEE_CENTS,
            exclusivity_category="BEVERAGE",
        )
        assert activation["status"] == "CONFIRMED"
        assert activation["net_fee_cents"] == ACTIVATION_NET_FEE_CENTS

        fixtures.announce_booking(booking_id, DOORS_UTC)
        fixtures.set_clock(AFTER_LOAD_OUT_UTC)
        performed = validate_success(
            api_client.mark_show_booking_performed(
                booking_id, FAIR_OPERATIONS_DIRECTOR_HEADERS
            )
        )
        assert performed["booking_status"] == "PERFORMED"
        assert performed["ticketing_status"] == "SALES_CLOSED"
        assert performed["gross_potential_cents"] == BOOKING_GROSS_POTENTIAL_CENTS
        assert performed["sponsorship_revenue_cents"] == ACTIVATION_NET_FEE_CENTS

        scales, scale_meta = validate_paginated(
            api_client.list_ticket_scales(booking_id, BOX_OFFICE_MANAGER_HEADERS)
        )
        assert scale_meta["total_count"] == 2
        for scale in scales:
            assertions.assert_ticket_scale(scale)
            assert scale["status"] == "CLOSED"

        fulfilled = fixtures.get_activation(activation["id"])
        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["net_fee_cents"] == ACTIVATION_NET_FEE_CENTS
        assert fulfilled["make_good_credit_cents"] == 0

        stage = fixtures.get_stage(scenario["stage"]["id"])
        assert stage["held_show_count"] == 1
        assert stage["booking_posture"] == "OPEN"
        assertions.assert_stage_posture(stage)

    def test_mark_performed_fulfils_the_confirmed_package_and_leaves_the_proposed_one(
        self,
    ):
        """When a show concludes carrying one confirmed and one merely proposed
        rights package, only the confirmed one advances; the proposed one keeps its
        status and its zero make-good, and the revenue figure does not move.

        "every `CONFIRMED` activation on it advances `CONFIRMED → FULFILLED` and the booking's `sponsorship_revenue_cents` is unchanged by that move"

        Design: Corner/state_machines/mark_performed_fulfils_confirmed_and_leaves_proposed_untouched
        """
        scenario = fixtures.setup_scaled_booking(scale_overrides=GOLD_SCALE)
        booking_id = scenario["booking"]["id"]
        fixtures.prepare_completed_advance(scenario)

        sponsor = fixtures.create_sponsor(**SPONSOR)
        signage = fixtures.create_activation(
            sponsor["id"],
            booking_id,
            rights="SIGNAGE",
            base_fee_cents=ACTIVATION_BASE_FEE_CENTS,
            exclusivity_category="BEVERAGE",
        )
        sampling = fixtures.create_activation(
            sponsor["id"],
            booking_id,
            rights="SAMPLING",
            base_fee_cents=ACTIVATION_BASE_FEE_CENTS,
            exclusivity_category="BEVERAGE",
        )
        fixtures.confirm_activation(signage["id"])
        assert sampling["status"] == "PROPOSED"

        fixtures.announce_booking(booking_id, DOORS_UTC)
        fixtures.set_clock(AFTER_LOAD_OUT_UTC)
        performed = validate_success(
            api_client.mark_show_booking_performed(
                booking_id, FAIR_OPERATIONS_DIRECTOR_HEADERS
            )
        )
        assert performed["booking_status"] == "PERFORMED"
        assert performed["sponsorship_revenue_cents"] == ACTIVATION_NET_FEE_CENTS

        assert fixtures.get_activation(signage["id"])["status"] == "FULFILLED"
        still_proposed = fixtures.get_activation(sampling["id"])
        assert still_proposed["status"] == "PROPOSED"
        assert still_proposed["make_good_credit_cents"] == 0

        activations, activation_meta = validate_paginated(
            api_client.list_sponsorship_activations(
                SPONSORSHIP_DIRECTOR_HEADERS, {"booking_id": booking_id}
            )
        )
        assert activation_meta["total_count"] == 2
        assert fixtures.get_booking(booking_id)["sponsorship_revenue_cents"] == (
            ACTIVATION_NET_FEE_CENTS
        )


class TestRescheduleSelfLoop:
    """The date self-loop is available only before the show is announced."""

    def test_reschedule_succeeds_before_announcement_and_is_refused_after_it(self):
        """A held date can be moved freely, but once the show has been announced and
        gone on sale the same move is refused and the booking keeps the coordinates
        the successful reschedule gave it.

        "it is refused with `ERR_INVALID_BOOKING_STATE` once the booking has reached `ANNOUNCED`"

        Design: Corner/state_machines/reschedule_after_announce_rejected
        """
        scenario = fixtures.setup_scaled_booking(scale_overrides=GOLD_SCALE)
        booking_id = scenario["booking"]["id"]
        fixtures.prepare_completed_advance(scenario)

        moved = validate_success(
            api_client.reschedule_show_booking(
                booking_id,
                build_reschedule_payload(
                    "2026-08-24",
                    "2026-08-24T14:00:00.000Z",
                    "2026-08-24T23:00:00.000Z",
                ),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
            )
        )
        assert moved["booking_status"] == "DATE_HELD"
        assert moved["show_date"] == "2026-08-24"

        announced = fixtures.announce_booking(booking_id, "2026-08-24T18:00:00.000Z")
        assert announced["booking_status"] == "ANNOUNCED"
        assert announced["ticketing_status"] == "ON_SALE"

        validate_error(
            api_client.reschedule_show_booking(
                booking_id,
                build_reschedule_payload(
                    "2026-08-26",
                    "2026-08-26T14:00:00.000Z",
                    "2026-08-26T23:00:00.000Z",
                ),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_BOOKING_STATE.value,
        )

        final = fixtures.get_booking(booking_id)
        assert final["booking_status"] == "ANNOUNCED"
        assert final["show_date"] == "2026-08-24"
        assert final["load_in_start_utc"] == "2026-08-24T14:00:00.000Z"
        assert final["load_out_end_utc"] == "2026-08-24T23:00:00.000Z"
        assert final["version"] == announced["version"]


class TestWithdrawnOfferIsTerminal:
    """A withdrawn offer admits no trigger at all."""

    @pytest.mark.parametrize("trigger", ["send", "counter", "accept", "withdraw"])
    def test_every_trigger_against_a_withdrawn_offer_is_refused(self, trigger):
        """Once an offer has been withdrawn, sending, countering, accepting and
        withdrawing it again are all refused, and the offer keeps both its terminal
        status and its version.

        "The four terminal statuses — `ACCEPTED`, `DECLINED`, `WITHDRAWN` and `EXPIRED` — admit no trigger whatsoever"

        Design: Corner/state_machines/withdrawn_offer_cannot_be_sent_countered_or_accepted
        """
        scenario = fixtures.setup_sent_offer()
        offer_id = scenario["offer"]["id"]

        withdrawn = validate_success(
            api_client.withdraw_offer(offer_id, TALENT_BUYER_HEADERS)
        )
        assert withdrawn["status"] == "WITHDRAWN"
        version_after_withdrawal = withdrawn["version"]

        if trigger == "send":
            response = api_client.send_offer(offer_id, TALENT_BUYER_HEADERS)
        elif trigger == "counter":
            response = api_client.counter_offer(
                offer_id, build_counter_payload(13000000), scenario["agent_headers"]
            )
        elif trigger == "accept":
            response = api_client.accept_offer(offer_id, scenario["agent_headers"])
        else:
            response = api_client.withdraw_offer(offer_id, TALENT_BUYER_HEADERS)
        validate_error(response, ApiErrorId.ERR_INVALID_OFFER_STATE.value)

        unchanged = fixtures.get_offer(offer_id)
        assert unchanged["status"] == "WITHDRAWN"
        assert unchanged["version"] == version_after_withdrawal
        assert unchanged["agreed_guarantee_cents"] is None

    def test_refused_acceptance_of_a_withdrawn_offer_materialises_no_show_booking(self):
        """The acceptance cascade never runs for a withdrawn offer: no show booking
        is created on its behalf, because the trigger is refused outright rather
        than half-applied.

        "Three records are then created in a chain, none of which appears in the response body"

        Design: Corner/state_machines/withdrawn_offer_cannot_be_sent_countered_or_accepted
        """
        scenario = fixtures.setup_sent_offer()
        offer_id = scenario["offer"]["id"]

        validate_success(api_client.withdraw_offer(offer_id, TALENT_BUYER_HEADERS))
        validate_error(
            api_client.accept_offer(offer_id, scenario["agent_headers"]),
            ApiErrorId.ERR_INVALID_OFFER_STATE.value,
        )

        bookings, booking_meta = validate_paginated(
            api_client.list_show_bookings(
                FAIR_OPERATIONS_DIRECTOR_HEADERS, {"offer_id": offer_id}
            )
        )
        assert booking_meta["total_count"] == 0
        assert bookings == []


class TestCompletedAdvanceIsTerminal:
    """A closed production advance admits no second closure."""

    def test_second_completion_is_refused_and_applies_no_cost_twice(self):
        """Closing an advance a second time is refused, and the recoupable cost it
        already published to the booking is not doubled by the attempt.

        "`ADVANCE_COMPLETE` and `ADVANCE_CANCELLED` are terminal and admit no further action; any attempt against them, or a closure attempted from a status other than `ADVANCE_IN_REVIEW`, is refused with `ERR_INVALID_ADVANCE_STATE`"

        Design: Corner/state_machines/second_complete_on_completed_advance_rejected
        """
        scenario = fixtures.setup_accepted_booking()
        advance_id = scenario["advance"]["id"]
        booking_id = scenario["booking"]["id"]

        sound = fixtures.add_rider_item(
            advance_id,
            category="SOUND",
            description="Supplemental line array",
            requested_cost_cents=120000,
            is_critical=False,
            artist_recoupable=True,
        )
        fixtures.rule_rider_item(scenario["seed_rider_item"]["id"], "APPROVED")
        fixtures.rule_rider_item(sound["id"], "APPROVED")

        completed = validate_success(
            api_client.complete_production_advance(advance_id, PRODUCTION_MANAGER_HEADERS)
        )
        assertions.assert_production_advance(completed)
        assert completed["status"] == "ADVANCE_COMPLETE"
        assert completed["approved_rider_cost_cents"] == 120000
        assert completed["recoupable_rider_cost_cents"] == 120000

        validate_error(
            api_client.complete_production_advance(
                advance_id, PRODUCTION_MANAGER_HEADERS
            ),
            ApiErrorId.ERR_INVALID_ADVANCE_STATE.value,
        )

        advance = fixtures.get_advance(advance_id)
        assert advance["status"] == "ADVANCE_COMPLETE"
        assert advance["version"] == completed["version"]
        assert advance["approved_rider_cost_cents"] == 120000
        assert advance["recoupable_rider_cost_cents"] == 120000
        assert (
            fixtures.get_booking(booking_id)["recoupable_production_cost_cents"]
            == 120000
        )


class TestRiderRulingLedgers:
    """Rulings keep the recoupable subtotal distinct from the approved total."""

    def test_rulings_sync_the_advance_totals_and_the_booking_mirror(self):
        """Approving a recoupable line raises both advance totals and the booking's
        mirror together, while approving a non-recoupable line raises only the
        approved total and leaves the recoupable figures where they were.

        "`recoupable_rider_cost_cents` is the same sum narrowed to those lines whose `artist_recoupable` reads true"

        Design: Corner/state_machines/rider_ruling_syncs_advance_and_booking_recoupment_ledgers
        """
        scenario = fixtures.setup_accepted_booking()
        advance_id = scenario["advance"]["id"]
        booking_id = scenario["booking"]["id"]

        sound = fixtures.add_rider_item(
            advance_id,
            category="SOUND",
            description="Supplemental line array",
            requested_cost_cents=120000,
            is_critical=False,
            artist_recoupable=True,
        )
        hospitality = fixtures.add_rider_item(
            advance_id,
            category="HOSPITALITY",
            description="Dressing room catering",
            requested_cost_cents=50000,
            is_critical=False,
            artist_recoupable=False,
        )

        ruled_sound = validate_success(
            api_client.rule_rider_item(
                sound["id"],
                build_rider_ruling_payload("APPROVED"),
                PRODUCTION_MANAGER_HEADERS,
            )
        )
        assertions.assert_rider_item(ruled_sound)
        assert ruled_sound["status"] == "APPROVED"
        assert ruled_sound["approved_cost_cents"] == 120000

        after_sound = fixtures.get_advance(advance_id)
        assert after_sound["status"] == "ADVANCE_IN_REVIEW"
        assert after_sound["approved_rider_cost_cents"] == 120000
        assert after_sound["recoupable_rider_cost_cents"] == 120000
        assert after_sound["denied_item_count"] == 0
        assert (
            fixtures.get_booking(booking_id)["recoupable_production_cost_cents"]
            == 120000
        )

        validate_success(
            api_client.rule_rider_item(
                hospitality["id"],
                build_rider_ruling_payload("APPROVED"),
                PRODUCTION_MANAGER_HEADERS,
            )
        )

        after_hospitality = fixtures.get_advance(advance_id)
        assert after_hospitality["approved_rider_cost_cents"] == 170000
        assert after_hospitality["recoupable_rider_cost_cents"] == 120000
        assert after_hospitality["denied_item_count"] == 0
        assert (
            fixtures.get_booking(booking_id)["recoupable_production_cost_cents"]
            == 120000
        )


class TestBoxOfficeRollUp:
    """Sale batches bubble up to tier counts and to the booking's attendance."""

    def test_sale_batches_recompute_tier_counts_and_booking_paid_attendance(self):
        """Two sale batches on a single tier roll up into its sold and available
        counts and into the booking's paid attendance, while the tier's capacity
        figure is untouched by the selling.

        "The tier's `sold_seats` is recomputed as the sum of the `quantity` values of its `SALE` batches less the sum of the `quantity` values of its `REFUND` batches"

        Design: Corner/state_machines/sale_batches_bubble_up_to_scale_counts_and_paid_attendance
        """
        scenario = fixtures.setup_announced_booking(
            scale_overrides=GOLD_SCALE, doors_time_utc=DOORS_UTC
        )
        scale_id = scenario["ticket_scale"]["id"]

        before = fixtures.get_ticket_scale(scale_id)
        assert before["status"] == "ON_SALE_ELIGIBLE"
        assert before["sold_seats"] == 0
        assert before["available_seats"] == 2000
        assert fixtures.get_booking(scenario["booking"]["id"])["paid_attendance"] == 0

        online = validate_success(
            api_client.create_sales_batch(
                scale_id,
                build_sales_batch_payload("SALE", 300, "ONLINE"),
                BOX_OFFICE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assertions.assert_ticket_sale_batch(online)
        assert online["counts_toward_paid_attendance"] is True

        window = validate_success(
            api_client.create_sales_batch(
                scale_id,
                build_sales_batch_payload("SALE", 200, "BOX_OFFICE"),
                BOX_OFFICE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert window["counts_toward_paid_attendance"] is True

        after = fixtures.get_ticket_scale(scale_id)
        assert after["sold_seats"] == 500
        assert after["available_seats"] == 1500
        assert after["scale_gross_potential_cents"] == GOLD_SCALE_GROSS_POTENTIAL_CENTS
        assertions.assert_seat_identity(after)

        booking = fixtures.get_booking(scenario["booking"]["id"])
        assert booking["paid_attendance"] == 500
        assert booking["gross_potential_cents"] == GOLD_SCALE_GROSS_POTENTIAL_CENTS

        batches, batch_meta = validate_paginated(
            api_client.list_sales_batches(scale_id, BOX_OFFICE_MANAGER_HEADERS)
        )
        assert batch_meta["total_count"] == 2


class TestActivationTransitionsAndRevenue:
    """Confirmation publishes sponsorship revenue; cancellation withdraws it."""

    def test_confirming_an_activation_writes_sponsorship_revenue_onto_the_booking(self):
        """A proposed rights package contributes nothing; confirming it publishes its
        net fee to the booking's sponsorship revenue and bumps the booking's version,
        leaving the capacity-based potential untouched.

        "recomputes the booking's `sponsorship_revenue_cents` as the sum of `net_fee_cents` across the booking's activations whose status is `CONFIRMED` or `FULFILLED`"

        Design: Corner/state_machines/activation_confirm_updates_booking_sponsorship_revenue
        """
        scenario = fixtures.setup_scaled_booking(scale_overrides=GOLD_SCALE)
        booking_id = scenario["booking"]["id"]

        sponsor = fixtures.create_sponsor(**SPONSOR)
        activation = fixtures.create_activation(
            sponsor["id"],
            booking_id,
            rights="SIGNAGE",
            base_fee_cents=ACTIVATION_BASE_FEE_CENTS,
            exclusivity_category="BEVERAGE",
        )
        assertions.assert_sponsorship_activation(activation)
        assert activation["status"] == "PROPOSED"

        before = fixtures.get_booking(booking_id)
        assert before["sponsorship_revenue_cents"] == 0

        confirmed = validate_success(
            api_client.confirm_sponsorship_activation(
                activation["id"], SPONSORSHIP_DIRECTOR_HEADERS
            )
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["net_fee_cents"] == ACTIVATION_NET_FEE_CENTS
        assert confirmed["make_good_credit_cents"] == 0

        after = fixtures.get_booking(booking_id)
        assert after["sponsorship_revenue_cents"] == ACTIVATION_NET_FEE_CENTS
        assert after["version"] > before["version"]
        assert after["gross_potential_cents"] == GOLD_SCALE_GROSS_POTENTIAL_CENTS

    def test_cancelling_a_confirmed_package_credits_a_make_good_but_a_proposed_one_does_not(
        self,
    ):
        """Cancelling a confirmed rights package withdraws its fee from the booking's
        sponsorship revenue and compensates the sponsor with a make-good equal to
        that fee, whereas cancelling a package that never left proposal credits
        nothing.

        "From `CONFIRMED`, cancelling sets the activation's `make_good_credit_cents` to its `net_fee_cents`"

        Design: Corner/state_machines/cancel_confirmed_activation_compensates_with_make_good_credit
        """
        scenario = fixtures.setup_scaled_booking(scale_overrides=GOLD_SCALE)
        booking_id = scenario["booking"]["id"]

        sponsor = fixtures.create_sponsor(**SPONSOR)
        signage = fixtures.create_activation(
            sponsor["id"],
            booking_id,
            rights="SIGNAGE",
            base_fee_cents=ACTIVATION_BASE_FEE_CENTS,
            exclusivity_category="BEVERAGE",
        )
        sampling = fixtures.create_activation(
            sponsor["id"],
            booking_id,
            rights="SAMPLING",
            base_fee_cents=ACTIVATION_BASE_FEE_CENTS,
            exclusivity_category="BEVERAGE",
        )
        fixtures.confirm_activation(signage["id"])
        assert (
            fixtures.get_booking(booking_id)["sponsorship_revenue_cents"]
            == ACTIVATION_NET_FEE_CENTS
        )

        cancelled_confirmed = validate_success(
            api_client.cancel_sponsorship_activation(
                signage["id"], SPONSORSHIP_DIRECTOR_HEADERS
            )
        )
        assert cancelled_confirmed["status"] == "CANCELLED"
        assert cancelled_confirmed["net_fee_cents"] == ACTIVATION_NET_FEE_CENTS
        assert cancelled_confirmed["make_good_credit_cents"] == ACTIVATION_NET_FEE_CENTS
        assert fixtures.get_booking(booking_id)["sponsorship_revenue_cents"] == 0

        cancelled_proposed = validate_success(
            api_client.cancel_sponsorship_activation(
                sampling["id"], SPONSORSHIP_DIRECTOR_HEADERS
            )
        )
        assert cancelled_proposed["status"] == "CANCELLED"
        assert cancelled_proposed["make_good_credit_cents"] == 0
        assert fixtures.get_booking(booking_id)["sponsorship_revenue_cents"] == 0


class TestCancellationWithNothingOwed:
    """With no units sold there is nothing to refund, so refunding self-closes."""

    def test_cancelling_a_show_with_no_sales_closes_refunding_straight_to_refunded(self):
        """Cancelling an announced show before doors on which nothing has been sold
        owes patrons nothing, so the box-office dimension skips straight past
        refunding, every tier is marked refund-due and the advance is cancelled.

        "when the computed `refund_liability_cents` is 0, nothing is owed to patrons, so the box-office dimension closes immediately and moves `REFUNDING → REFUNDED`"

        Design: Corner/state_machines/cancel_with_zero_sold_units_auto_closes_refunding_to_refunded
        """
        scenario = fixtures.setup_announced_booking(
            scale_overrides=GOLD_SCALE, doors_time_utc=DOORS_UTC
        )
        booking_id = scenario["booking"]["id"]

        action = validate_success(
            api_client.create_contingency_action(
                booking_id,
                build_contingency_action_payload(
                    fixtures.booking_version(booking_id),
                    action_type="CANCEL",
                    reason_code="SEVERE_WEATHER",
                    refund_policy="FULL_REFUND",
                ),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        assertions.assert_contingency_action(action)
        assert action["action_type"] == "CANCEL"
        assert action["pre_doors"] is True
        assert action["refund_liability_cents"] == 0
        assert action["replacement_show_date"] is None

        booking = fixtures.get_booking(booking_id)
        assert booking["booking_status"] == "CANCELLED"
        assert booking["ticketing_status"] == "REFUNDED"
        assert booking["refund_liability_cents"] == 0

        scales, scale_meta = validate_paginated(
            api_client.list_ticket_scales(booking_id, BOX_OFFICE_MANAGER_HEADERS)
        )
        assert scale_meta["total_count"] == 1
        assert scales[0]["status"] == "REFUND_DUE"

        edition = fixtures.get_edition(scenario["edition"]["id"])
        assert edition["refund_liability_committed_cents"] == 0
        assert (
            fixtures.get_advance(scenario["advance"]["id"])["status"]
            == "ADVANCE_CANCELLED"
        )
