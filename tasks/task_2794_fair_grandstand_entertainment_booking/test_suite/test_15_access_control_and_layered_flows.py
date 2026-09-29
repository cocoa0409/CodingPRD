"""Role-based access control across the seven declared roles, and the layers that
ride on top of it: the version tokens guarding the booking and offer writes, the
all-or-nothing weather cascade, and the derived ledgers recomputed from base rows.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CANONICAL_CLOCK_UTC
from test_helpers.test_users import (
    BOX_OFFICE_MANAGER_HEADERS,
    FAIR_OPERATIONS_DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SETTLEMENT_CONTROLLER_HEADERS,
    SPONSORSHIP_DIRECTOR_HEADERS,
    TALENT_BUYER_ALT_HEADERS,
    TALENT_BUYER_HEADERS,
    make_headers,
    make_talent_agent_headers,
)
from test_helpers.types import UserRole

# A second controller identity, so that an approval can be issued by somebody
# other than the operator who submitted the settlement.
CONTROLLER_NINE_HEADERS = make_headers(
    "controller-09", UserRole.SETTLEMENT_CONTROLLER.value
)

# One human wearing both hats: the buyer identity that opens and submits the
# settlement is the same identity that later tries to approve it.
DUAL_HAT_BUYER_HEADERS = make_headers("dual-hat-07", UserRole.TALENT_BUYER.value)
DUAL_HAT_CONTROLLER_HEADERS = make_headers(
    "dual-hat-07", UserRole.SETTLEMENT_CONTROLLER.value
)

SHOW_CONCLUDED_CLOCK_UTC = "2026-08-22T23:00:00.000Z"


class TestRoleBasedAccessControl:
    """Which role may write what, which reads are shared, and the one arc on the
    settlement that is constrained by separation of duties."""

    def test_each_role_performs_its_own_exclusive_writes_end_to_end(self):
        """One act is carried from an empty database to an approved settlement with
        every write issued by the role that owns it: the director runs the fair, the
        buyer the offer surface, the agent the agent half of the negotiation, the
        production manager the advance, the box office the price structure and the
        batches, the sponsorship director the activation and the controller the
        approval. "A `ProductionManager` runs the production advance, adding rider
        lines, ruling them and closing the advance."

        Design: Corner/rbac/every_role_can_perform_its_own_exclusive_writes_end_to_end
        """
        validate_success(
            api_client.set_clock(CANONICAL_CLOCK_UTC, FAIR_OPERATIONS_DIRECTOR_HEADERS)
        )

        edition = validate_success(
            api_client.create_fair_edition(
                factories.build_fair_edition_payload(), FAIR_OPERATIONS_DIRECTOR_HEADERS
            ),
            expected_status=201,
        )
        stage = validate_success(
            api_client.create_stage(
                factories.build_stage_payload(edition["id"]),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        agent = validate_success(
            api_client.create_talent_agent(
                factories.build_talent_agent_payload(), TALENT_BUYER_HEADERS
            ),
            expected_status=201,
        )
        agent_headers = make_talent_agent_headers(agent["user_id"])
        artist = validate_success(
            api_client.create_artist(
                factories.build_artist_payload(agent["id"]), TALENT_BUYER_HEADERS
            ),
            expected_status=201,
        )
        sponsor = validate_success(
            api_client.create_sponsor(
                factories.build_sponsor_payload(
                    name="Ridgeline Motors",
                    category="AUTOMOTIVE",
                    exclusivity_tier="SUPPORTING",
                ),
                SPONSORSHIP_DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )

        offer = validate_success(
            api_client.create_offer(
                factories.build_offer_payload(
                    edition["id"], artist["id"], stage["id"]
                ),
                TALENT_BUYER_HEADERS,
            ),
            expected_status=201,
        )
        offer = validate_success(api_client.send_offer(offer["id"], TALENT_BUYER_HEADERS))
        offer = validate_success(
            api_client.counter_offer(
                offer["id"],
                factories.build_counter_payload(
                    13_000_000, note="Needs bus call money"
                ),
                agent_headers,
            )
        )
        as_read_by_buyer = validate_success(
            api_client.get_offer(offer["id"], TALENT_BUYER_HEADERS)
        )
        offer = validate_success(
            api_client.revise_offer(
                offer["id"],
                factories.build_revise_payload(
                    as_read_by_buyer["version"],
                    12_500_000,
                    backend_breakeven_cents=6_000_000,
                    note="Best and final",
                ),
                TALENT_BUYER_HEADERS,
            )
        )
        offer = validate_success(api_client.accept_offer(offer["id"], agent_headers))
        assert offer["status"] == "ACCEPTED"
        assert offer["round_count"] == 3

        bookings, _ = validate_paginated(
            api_client.list_show_bookings(TALENT_BUYER_HEADERS, {"offer_id": offer["id"]})
        )
        booking = bookings[0]
        advances, _ = validate_paginated(
            api_client.list_production_advances(
                PRODUCTION_MANAGER_HEADERS, {"booking_id": booking["id"]}
            )
        )
        advance = advances[0]

        lighting_line = validate_success(
            api_client.create_rider_item(
                advance["id"],
                factories.build_rider_item_payload(
                    category="LIGHTING", description="House wash only"
                ),
                PRODUCTION_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        seed_lines, _ = validate_paginated(
            api_client.list_rider_items(
                advance["id"], PRODUCTION_MANAGER_HEADERS, {"category": "STAGING"}
            )
        )
        validate_success(
            api_client.rule_rider_item(
                seed_lines[0]["id"],
                factories.build_rider_ruling_payload("APPROVED"),
                PRODUCTION_MANAGER_HEADERS,
            )
        )
        validate_success(
            api_client.rule_rider_item(
                lighting_line["id"],
                factories.build_rider_ruling_payload("APPROVED"),
                PRODUCTION_MANAGER_HEADERS,
            )
        )
        advance = validate_success(
            api_client.complete_production_advance(
                advance["id"], PRODUCTION_MANAGER_HEADERS
            )
        )
        assert advance["status"] == "ADVANCE_COMPLETE"

        as_read_by_box_office = validate_success(
            api_client.get_show_booking(booking["id"], BOX_OFFICE_MANAGER_HEADERS)
        )
        scale = validate_success(
            api_client.create_ticket_scale(
                booking["id"],
                factories.build_ticket_scale_payload(
                    as_read_by_box_office["version"],
                    allotment_seats=2000,
                    facility_fee_cents=400,
                ),
                BOX_OFFICE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        booking = validate_success(
            api_client.announce_show_booking(
                booking["id"],
                factories.build_announce_payload(),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
            )
        )
        assert booking["booking_status"] == "ANNOUNCED"

        as_read_by_sponsorship = validate_success(
            api_client.get_show_booking(booking["id"], SPONSORSHIP_DIRECTOR_HEADERS)
        )
        activation = validate_success(
            api_client.create_sponsorship_activation(
                factories.build_activation_payload(
                    sponsor["id"],
                    booking["id"],
                    as_read_by_sponsorship["version"],
                    rights="SIGNAGE",
                    base_fee_cents=1_000_000,
                    exclusivity_category="AUTOMOTIVE",
                ),
                SPONSORSHIP_DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        activation = validate_success(
            api_client.confirm_sponsorship_activation(
                activation["id"], SPONSORSHIP_DIRECTOR_HEADERS
            )
        )
        assert activation["status"] == "CONFIRMED"

        validate_success(
            api_client.create_sales_batch(
                scale["id"],
                factories.build_sales_batch_payload(quantity=1800),
                BOX_OFFICE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        scale = validate_success(
            api_client.get_ticket_scale(scale["id"], BOX_OFFICE_MANAGER_HEADERS)
        )
        assert scale["sold_seats"] == 1800

        validate_success(
            api_client.set_clock(
                SHOW_CONCLUDED_CLOCK_UTC, FAIR_OPERATIONS_DIRECTOR_HEADERS
            )
        )
        booking = validate_success(
            api_client.mark_show_booking_performed(
                booking["id"], FAIR_OPERATIONS_DIRECTOR_HEADERS
            )
        )
        assert booking["booking_status"] == "PERFORMED"

        settlement = validate_success(
            api_client.create_settlement(
                booking["id"],
                factories.build_settlement_payload(
                    merch_gross_cents=0, merch_seller="ARTIST"
                ),
                TALENT_BUYER_HEADERS,
            ),
            expected_status=201,
        )
        settlement = validate_success(
            api_client.submit_settlement(settlement["id"], TALENT_BUYER_HEADERS)
        )
        settlement = validate_success(
            api_client.approve_settlement(settlement["id"], CONTROLLER_NINE_HEADERS)
        )
        assert settlement["status"] == "APPROVED"
        assert settlement["submitted_by_user_id"] == "buyer-01"
        assert settlement["approved_by_user_id"] == "controller-09"

    def test_a_role_reaching_into_another_roles_exclusive_write_is_refused(self):
        """Each probe below is a well-formed identity attempting a write that belongs
        exclusively to a different role, on a target that exists and is in a state
        that would admit the action from its owner. "If the headers are well formed
        but the named role is not among the roles the target operation admits, the
        request is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/roles_cannot_cross_into_another_roles_exclusive_write
        """
        scenario = fixtures.setup_performed_booking(
            scale_overrides={"allotment_seats": 2000, "facility_fee_cents": 400},
            sales=[{"quantity": 1800}],
        )
        settlement = fixtures.setup_submitted_settlement(scenario)
        offer_id = scenario["offer"]["id"]
        seed_line_id = scenario["seed_rider_item"]["id"]
        scale_id = scenario["ticket_scale"]["id"]
        agent_headers = scenario["agent_headers"]
        forbidden = ApiErrorId.ERR_FORBIDDEN_ROLE.value

        # The agent reads the whole offer surface but owns none of the buyer's edges.
        validate_error(api_client.send_offer(offer_id, agent_headers), forbidden)
        validate_error(api_client.withdraw_offer(offer_id, agent_headers), forbidden)
        # Acceptance is the agent's move alone, so the buyer cannot self-accept.
        validate_error(api_client.accept_offer(offer_id, TALENT_BUYER_HEADERS), forbidden)
        # A second buyer identity is still the wrong role for approval.
        validate_error(
            api_client.approve_settlement(settlement["id"], TALENT_BUYER_ALT_HEADERS),
            forbidden,
        )
        validate_error(
            api_client.submit_settlement(settlement["id"], CONTROLLER_NINE_HEADERS),
            forbidden,
        )
        validate_error(
            api_client.rule_rider_item(
                seed_line_id,
                factories.build_rider_ruling_payload("DENIED"),
                SPONSORSHIP_DIRECTOR_HEADERS,
            ),
            forbidden,
        )
        validate_error(
            api_client.create_sponsor(
                factories.build_sponsor_payload(
                    name="Interloper Foods", category="QSR"
                ),
                PRODUCTION_MANAGER_HEADERS,
            ),
            forbidden,
        )
        # Even the director who owns the calendar cannot touch the box-office ledger.
        validate_error(
            api_client.create_sales_batch(
                scale_id,
                factories.build_sales_batch_payload(quantity=5, channel="PHONE"),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
            ),
            forbidden,
        )

        # None of the refused writes left a mark.
        assert fixtures.get_rider_item(seed_line_id)["status"] == "APPROVED"
        assert fixtures.get_settlement(settlement["id"])["status"] == "PENDING_APPROVAL"

        # The reads those same roles are admitted to still answer.
        validate_success(api_client.get_offer(offer_id, agent_headers))
        validate_success(api_client.get_settlement(settlement["id"], agent_headers))
        scale = validate_success(
            api_client.get_ticket_scale(scale_id, BOX_OFFICE_MANAGER_HEADERS)
        )
        assert scale["sold_seats"] == 1800

    @pytest.mark.parametrize(
        "read_call, excluded_headers, admitted_headers, not_found_error",
        [
            (
                lambda headers: api_client.get_sponsor(NON_EXISTENT_UUID, headers),
                TALENT_BUYER_HEADERS,
                SPONSORSHIP_DIRECTOR_HEADERS,
                ApiErrorId.ERR_SPONSOR_NOT_FOUND.value,
            ),
            (
                lambda headers: api_client.get_settlement_preview(
                    NON_EXISTENT_UUID, headers
                ),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
                SETTLEMENT_CONTROLLER_HEADERS,
                ApiErrorId.ERR_SHOW_BOOKING_NOT_FOUND.value,
            ),
            (
                lambda headers: api_client.get_buying_strategy_report(
                    NON_EXISTENT_UUID, headers
                ),
                SETTLEMENT_CONTROLLER_HEADERS,
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
                ApiErrorId.ERR_FAIR_EDITION_NOT_FOUND.value,
            ),
        ],
        ids=["sponsor_detail", "settlement_preview", "buying_strategy_report"],
    )
    def test_a_read_closed_to_a_role_is_forbidden_where_an_admitted_role_is_not_found(
        self, read_call, excluded_headers, admitted_headers, not_found_error
    ):
        """Most reads are open to every role, but three are not, and on those three
        the role check is what answers first: the same missing identifier draws a
        role refusal from the excluded role and a not-found from an admitted one.
        "Role authorization — `X-User-Role` listed among the roles the target
        operation admits (`ERR_FORBIDDEN_ROLE`, 403). Applies to every operation."

        Design: Corner/rbac/shared_read_surface_is_wide_but_carries_three_named_exceptions
        """
        fixtures.set_clock()

        validate_error(
            read_call(excluded_headers), ApiErrorId.ERR_FORBIDDEN_ROLE.value
        )
        validate_error(read_call(admitted_headers), not_found_error)

    def test_the_wide_read_surface_and_the_clock_answer_every_admitted_role(self):
        """The roster listing is narrower than the booking listing, and the clock is
        open to everybody, so an agent and a box-office manager both get answers where
        a controller does not. "any of the seven roles may move it by supplying a
        `current_utc` instant to the clock-setting capability"

        Design: Corner/rbac/shared_read_surface_is_wide_but_carries_three_named_exceptions
        """
        fixtures.set_clock()
        agent = fixtures.create_agent()
        agent_headers = make_talent_agent_headers(agent["user_id"])

        validate_error(
            api_client.list_artists(SETTLEMENT_CONTROLLER_HEADERS),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        )
        _, roster_meta = validate_paginated(api_client.list_artists(agent_headers))
        assert roster_meta["total_count"] == 0

        for headers in (PRODUCTION_MANAGER_HEADERS, BOX_OFFICE_MANAGER_HEADERS):
            _, booking_meta = validate_paginated(api_client.list_show_bookings(headers))
            assert booking_meta["total_count"] == 0

        validate_success(
            api_client.set_clock("2026-08-02T00:00:00.000Z", BOX_OFFICE_MANAGER_HEADERS)
        )

    def test_the_submitter_is_refused_on_approval_but_admitted_on_rejection(self):
        """One controller identity that also submitted the settlement may bounce it
        back but may never sign it off, and re-submitting restamps the same submitter
        so the refusal repeats. "the approving user's identifier must differ from the
        settlement's `submitted_by_user_id`, and a self-approval is refused with
        `ERR_SEGREGATION_OF_DUTIES`"

        Design: Corner/rbac/settlement_submitter_cannot_approve_but_may_be_the_rejecter
        """
        scenario = fixtures.setup_performed_booking(
            scale_overrides={"allotment_seats": 2000, "facility_fee_cents": 400},
            sales=[{"quantity": 1800}],
        )
        settlement = validate_success(
            api_client.create_settlement(
                scenario["booking"]["id"],
                factories.build_settlement_payload(),
                DUAL_HAT_BUYER_HEADERS,
            ),
            expected_status=201,
        )
        settlement = validate_success(
            api_client.submit_settlement(settlement["id"], DUAL_HAT_BUYER_HEADERS)
        )
        assert settlement["status"] == "PENDING_APPROVAL"
        assert settlement["submitted_by_user_id"] == "dual-hat-07"

        validate_error(
            api_client.approve_settlement(settlement["id"], DUAL_HAT_CONTROLLER_HEADERS),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

        # The same human is free to reject: rejection carries no duties constraint.
        rejected = validate_success(
            api_client.reject_settlement(
                settlement["id"],
                factories.build_settlement_rejection_payload("EXPENSE_UNSUPPORTED"),
                DUAL_HAT_CONTROLLER_HEADERS,
            )
        )
        assert rejected["status"] == "DRAFT"
        assert rejected["rejection_reason_code"] == "EXPENSE_UNSUPPORTED"
        assert rejected["revision_count"] == 1
        assert rejected["submitted_by_user_id"] is None

        resubmitted = validate_success(
            api_client.submit_settlement(settlement["id"], DUAL_HAT_BUYER_HEADERS)
        )
        assert resubmitted["submitted_by_user_id"] == "dual-hat-07"
        validate_error(
            api_client.approve_settlement(settlement["id"], DUAL_HAT_CONTROLLER_HEADERS),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

        approved = validate_success(
            api_client.approve_settlement(settlement["id"], CONTROLLER_NINE_HEADERS)
        )
        assert approved["status"] == "APPROVED"
        assert approved["submitted_by_user_id"] == "dual-hat-07"
        assert approved["approved_by_user_id"] == "controller-09"


class TestLayeredBookingAndNegotiationFlows:
    """The version tokens on the booking and offer writes, the all-or-nothing
    contingency cascade, and the derived counters that follow their base rows."""

    def test_a_superseded_booking_token_is_refused_on_all_three_booking_writes(self):
        """A price tier, an activation and a contingency decision each echo the
        booking version, and each refusal leaves the booking exactly as it was, so
        re-reading and re-issuing lands the write. "Several price tiers legitimately
        coexist on one booking, so nothing in the state machine rejects a second tier"

        Design: Corner/cross_cutting_complexity_layers/show_booking_occ_token_guards_all_three_of_its_write_endpoints
        """
        stale = ApiErrorId.ERR_STALE_SHOW_BOOKING_VERSION.value
        scenario = fixtures.setup_accepted_booking()
        booking_id = scenario["booking"]["id"]

        # Scaling: the token read before the first tier is spent by that tier.
        pre_scale_version = fixtures.booking_version(booking_id)
        fixtures.add_ticket_scale(
            booking_id, allotment_seats=2000, facility_fee_cents=400
        )
        after_gold_version = fixtures.booking_version(booking_id)
        assert after_gold_version > pre_scale_version

        lawn_payload = factories.build_ticket_scale_payload(
            pre_scale_version,
            seating_type="GENERAL_ADMISSION",
            tier_name="LAWN",
            face_price_cents=3950,
            allotment_seats=6000,
        )
        validate_error(
            api_client.create_ticket_scale(
                booking_id, lawn_payload, BOX_OFFICE_MANAGER_HEADERS
            ),
            stale,
        )
        assert fixtures.booking_version(booking_id) == after_gold_version

        lawn_payload["expected_show_booking_version"] = after_gold_version
        validate_success(
            api_client.create_ticket_scale(
                booking_id, lawn_payload, BOX_OFFICE_MANAGER_HEADERS
            ),
            expected_status=201,
        )

        fixtures.prepare_completed_advance(scenario)
        fixtures.announce_booking(booking_id)

        # Sponsorship: confirming the first package supersedes the token.
        signage_sponsor = fixtures.create_sponsor(
            name="Ridgeline Motors",
            category="AUTOMOTIVE",
            exclusivity_tier="SUPPORTING",
        )
        sampling_sponsor = fixtures.create_sponsor(
            name="Cascade Cola", category="BEVERAGE", exclusivity_tier="SUPPORTING"
        )
        pre_activation_version = fixtures.booking_version(booking_id)
        signage = validate_success(
            api_client.create_sponsorship_activation(
                factories.build_activation_payload(
                    signage_sponsor["id"],
                    booking_id,
                    pre_activation_version,
                    rights="SIGNAGE",
                    base_fee_cents=1_000_000,
                    exclusivity_category="AUTOMOTIVE",
                ),
                SPONSORSHIP_DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        fixtures.confirm_activation(signage["id"])
        after_signage_version = fixtures.booking_version(booking_id)
        assert after_signage_version > pre_activation_version

        sampling_payload = factories.build_activation_payload(
            sampling_sponsor["id"],
            booking_id,
            pre_activation_version,
            rights="SAMPLING",
            base_fee_cents=800_000,
            exclusivity_category="BEVERAGE",
        )
        validate_error(
            api_client.create_sponsorship_activation(
                sampling_payload, SPONSORSHIP_DIRECTOR_HEADERS
            ),
            stale,
        )
        assert fixtures.booking_version(booking_id) == after_signage_version

        sampling_payload["expected_show_booking_version"] = after_signage_version
        sampling = validate_success(
            api_client.create_sponsorship_activation(
                sampling_payload, SPONSORSHIP_DIRECTOR_HEADERS
            ),
            expected_status=201,
        )
        assert sampling["net_fee_cents"] == 880000

        fixtures.confirm_activation(sampling["id"])
        after_sampling_version = fixtures.booking_version(booking_id)
        assert after_sampling_version > after_signage_version

        # Weather: the token read before the second confirmation is now stale.
        postpone_payload = factories.build_contingency_action_payload(
            after_signage_version,
            action_type="POSTPONE",
            reason_code="SEVERE_WEATHER",
            refund_policy="RAIN_CHECK",
            replacement_show_date="2026-08-26",
        )
        validate_error(
            api_client.create_contingency_action(
                booking_id, postpone_payload, FAIR_OPERATIONS_DIRECTOR_HEADERS
            ),
            stale,
        )
        assert fixtures.booking_version(booking_id) == after_sampling_version

        postpone_payload["expected_show_booking_version"] = after_sampling_version
        validate_success(
            api_client.create_contingency_action(
                booking_id, postpone_payload, FAIR_OPERATIONS_DIRECTOR_HEADERS
            ),
            expected_status=201,
        )
        assert fixtures.get_booking(booking_id)["booking_status"] == "POSTPONED"

        # Every refused write left the record count alone: two tiers, two packages.
        _, scale_meta = validate_paginated(
            api_client.list_ticket_scales(booking_id, BOX_OFFICE_MANAGER_HEADERS)
        )
        assert scale_meta["total_count"] == 2
        _, activation_meta = validate_paginated(
            api_client.list_sponsorship_activations(
                SPONSORSHIP_DIRECTOR_HEADERS, {"booking_id": booking_id}
            )
        )
        assert activation_meta["total_count"] == 2

    def test_a_revise_written_against_a_pre_counter_offer_view_is_refused_as_stale(self):
        """The buyer read the offer before sending it, the agent countered in the
        meantime, and the revise carrying that pre-counter version is refused even
        though the offer's status would admit a revise. "omitting the field is a
        schema failure refused with `ERR_INVALID_REQUEST`, and supplying a value that
        does not equal the parent's current `version` is a stale-read failure refused
        with HTTP 412"

        Design: Corner/cross_cutting_complexity_layers/offer_occ_token_refuses_a_revise_written_against_a_pre_counter_view
        """
        scenario = fixtures.setup_draft_offer(
            offered_guarantee_cents=12_000_000, backend_breakeven_cents=6_000_000
        )
        offer_id = scenario["offer"]["id"]
        pre_send_version = scenario["offer"]["version"]

        validate_success(api_client.send_offer(offer_id, TALENT_BUYER_HEADERS))
        validate_success(
            api_client.counter_offer(
                offer_id,
                factories.build_counter_payload(
                    13_000_000, note="Bus and truck costs are up"
                ),
                scenario["agent_headers"],
            )
        )

        stale_payload = factories.build_revise_payload(
            pre_send_version,
            12_500_000,
            backend_breakeven_cents=6_000_000,
            note="Meeting in the middle",
        )
        validate_error(
            api_client.revise_offer(offer_id, stale_payload, TALENT_BUYER_HEADERS),
            ApiErrorId.ERR_STALE_OFFER_VERSION.value,
        )

        held = fixtures.get_offer(offer_id)
        assert held["status"] == "COUNTERED"
        assert held["offered_guarantee_cents"] == 12_000_000
        assert held["countered_guarantee_cents"] == 13_000_000
        assert held["round_count"] == 2
        _, refused_round_meta = validate_paginated(
            api_client.list_offer_rounds(offer_id, TALENT_BUYER_HEADERS)
        )
        assert refused_round_meta["total_count"] == 2
        assert (
            fixtures.get_edition(scenario["edition"]["id"])[
                "committed_guarantee_total_cents"
            ]
            == 12_000_000
        )

        fresh_payload = factories.build_revise_payload(
            held["version"],
            12_500_000,
            backend_breakeven_cents=6_000_000,
            note="Meeting in the middle",
        )
        revised = validate_success(
            api_client.revise_offer(offer_id, fresh_payload, TALENT_BUYER_HEADERS)
        )
        assert revised["status"] == "SENT"
        assert revised["offered_guarantee_cents"] == 12_500_000
        assert revised["countered_guarantee_cents"] is None
        assert revised["round_count"] == 3
        _, revised_round_meta = validate_paginated(
            api_client.list_offer_rounds(offer_id, TALENT_BUYER_HEADERS)
        )
        assert revised_round_meta["total_count"] == 3
        assert (
            fixtures.get_edition(scenario["edition"]["id"])[
                "committed_guarantee_total_cents"
            ]
            == 12_500_000
        )

    def test_a_refused_cancellation_leaves_no_half_finished_cascade(self):
        """The cancellation is refused because the fair cannot fund the refunds, and
        nothing beneath the show moves; the postponement the operator records instead
        then lands in full. "The edition's `refund_liability_committed_cents` plus the
        candidate action's `refund_liability_cents` must not exceed the edition's
        `refund_reserve_cents`"

        Design: Corner/cross_cutting_complexity_layers/a_refused_cancellation_leaves_no_half_finished_cascade
        """
        world = fixtures.setup_base_world(
            edition_overrides={"refund_reserve_cents": 1_000_000}
        )
        scenario = fixtures.setup_accepted_booking(world)
        booking_id = scenario["booking"]["id"]
        advance_id = scenario["advance"]["id"]
        stage_id = world["stage"]["id"]

        sound_line = fixtures.add_rider_item(
            advance_id,
            category="SOUND",
            description="Supplemental delay towers",
            requested_cost_cents=2_000_000,
            artist_recoupable=True,
        )
        fixtures.rule_rider_item(scenario["seed_rider_item"]["id"], "APPROVED")
        fixtures.rule_rider_item(sound_line["id"], "APPROVED")
        assert fixtures.complete_advance(advance_id)["status"] == "ADVANCE_COMPLETE"

        scale = fixtures.add_ticket_scale(
            booking_id, allotment_seats=2000, facility_fee_cents=400
        )
        fixtures.announce_booking(booking_id)
        activation = fixtures.setup_confirmed_activation(
            scenario,
            sponsor_overrides={
                "name": "Ridgeline Motors",
                "category": "AUTOMOTIVE",
                "exclusivity_tier": "SUPPORTING",
            },
            rights="SIGNAGE",
            base_fee_cents=1_000_000,
            exclusivity_category="AUTOMOTIVE",
        )
        fixtures.record_sales_batch(scale["id"], quantity=500)

        held_show_count_before = fixtures.get_stage(stage_id)["held_show_count"]
        token = fixtures.booking_version(booking_id)
        validate_error(
            api_client.create_contingency_action(
                booking_id,
                factories.build_contingency_action_payload(
                    token,
                    action_type="CANCEL",
                    reason_code="SEVERE_WEATHER",
                    refund_policy="FULL_REFUND",
                ),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
            ),
            ApiErrorId.ERR_REFUND_RESERVE_EXCEEDED.value,
        )

        # Booking, tier, sponsorship, advance and rider lines are all as they were.
        untouched = fixtures.get_booking(booking_id)
        assert untouched["booking_status"] == "ANNOUNCED"
        assert untouched["ticketing_status"] == "ON_SALE"
        assert untouched["refund_liability_cents"] == 0
        assert untouched["recoupable_production_cost_cents"] == 2_000_000
        assert untouched["sponsorship_revenue_cents"] == 1_100_000
        assert untouched["version"] == token
        assert fixtures.get_ticket_scale(scale["id"])["sold_seats"] == 500
        still_confirmed = fixtures.get_activation(activation["id"])
        assert still_confirmed["status"] == "CONFIRMED"
        assert still_confirmed["make_good_credit_cents"] == 0
        held_advance = fixtures.get_advance(advance_id)
        assert held_advance["status"] == "ADVANCE_COMPLETE"
        assert held_advance["approved_rider_cost_cents"] == 2_000_000
        assert held_advance["recoupable_rider_cost_cents"] == 2_000_000
        for item in fixtures.list_rider_items(advance_id):
            assert item["status"] == "APPROVED"
        assert (
            fixtures.get_edition(world["edition"]["id"])[
                "refund_liability_committed_cents"
            ]
            == 0
        )
        assert not fixtures.list_contingency_actions(booking_id)

        # The postponement the fair can afford lands with the whole cascade.
        action = validate_success(
            api_client.create_contingency_action(
                booking_id,
                factories.build_contingency_action_payload(
                    token,
                    action_type="POSTPONE",
                    reason_code="SEVERE_WEATHER",
                    refund_policy="RAIN_CHECK",
                    replacement_show_date="2026-08-26",
                ),
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert action["refund_liability_cents"] == 0

        postponed = fixtures.get_booking(booking_id)
        assert postponed["booking_status"] == "POSTPONED"
        assert postponed["ticketing_status"] == "SALES_CLOSED"
        assert postponed["refund_liability_cents"] == 0
        assert postponed["recoupable_production_cost_cents"] == 0
        assert postponed["sponsorship_revenue_cents"] == 0

        cancelled_activation = fixtures.get_activation(activation["id"])
        assert cancelled_activation["status"] == "CANCELLED"
        assert cancelled_activation["make_good_credit_cents"] == 1_100_000

        voided_advance = fixtures.get_advance(advance_id)
        assert voided_advance["status"] == "ADVANCE_CANCELLED"
        assert voided_advance["approved_rider_cost_cents"] == 0
        assert voided_advance["recoupable_rider_cost_cents"] == 0
        assert voided_advance["denied_item_count"] == 0
        assert voided_advance["blocked_reason_code"] is None
        voided_lines = fixtures.list_rider_items(advance_id)
        assert len(voided_lines) == 2
        for item in voided_lines:
            assert item["status"] == "VOIDED"
            assert item["approved_cost_cents"] == 0

        replacements, replacement_meta = validate_paginated(
            api_client.list_show_bookings(
                FAIR_OPERATIONS_DIRECTOR_HEADERS,
                {"postponed_from_booking_id": booking_id},
            )
        )
        assert replacement_meta["total_count"] == 1
        replacement = replacements[0]
        assert replacement["show_date"] == "2026-08-26"
        assert replacement["booking_status"] == "DATE_HELD"
        assert replacement["ticketing_status"] == "SCALED_PENDING"
        assert replacement["agreed_guarantee_cents"] == postponed["agreed_guarantee_cents"]

        new_advances, new_advance_meta = validate_paginated(
            api_client.list_production_advances(
                PRODUCTION_MANAGER_HEADERS, {"booking_id": replacement["id"]}
            )
        )
        assert new_advance_meta["total_count"] == 1
        assert new_advances[0]["status"] == "ADVANCE_PENDING"
        seed_lines = fixtures.list_rider_items(new_advances[0]["id"])
        assert len(seed_lines) == 1
        assert seed_lines[0]["category"] == "STAGING"
        assert seed_lines[0]["status"] == "REQUESTED"
        assert seed_lines[0]["is_critical"] is True
        assert seed_lines[0]["requested_cost_cents"] == 0

        # The slot ledger nets out flat: the replacement takes the released hold.
        assert fixtures.get_stage(stage_id)["held_show_count"] == held_show_count_before

    def test_roster_round_and_encumbrance_counters_track_their_base_rows(self):
        """Two acts on one agent, two offers on one edition, and the three counters
        that summarise them move only when a base row moves: the roster size, the
        negotiation round count and the standing encumbrance. "they are never written
        by a client, they are recomputed in full from the current rows every time a
        triggering event fires"

        Design: Corner/cross_cutting_complexity_layers/derived_counters_and_aggregates_track_their_base_rows_exactly
        """
        fixtures.set_clock()
        edition = fixtures.create_edition()
        stage = fixtures.create_stage(edition["id"])
        agent = fixtures.create_agent()
        agent_headers = make_talent_agent_headers(agent["user_id"])

        headliner = fixtures.create_artist(agent["id"])
        assert fixtures.get_agent(agent["id"])["roster_artist_count"] == 1
        support = fixtures.create_artist(
            agent["id"],
            name="Neon Skyline",
            genre="ROCK",
            audience_segment="YOUNG_ADULT",
            base_draw_score=41.00,
        )
        assert fixtures.get_agent(agent["id"])["roster_artist_count"] == 2

        headline_offer = fixtures.create_offer(
            edition["id"],
            headliner["id"],
            stage["id"],
            offered_guarantee_cents=500_000,
            backend_breakeven_cents=0,
        )
        # A drafted offer encumbers nothing and has no rounds behind it.
        assert fixtures.get_edition(edition["id"])["committed_guarantee_total_cents"] == 0
        assert headline_offer["round_count"] == 0

        sent = validate_success(
            api_client.send_offer(headline_offer["id"], TALENT_BUYER_HEADERS)
        )
        assert sent["round_count"] == 1
        assert len(fixtures.list_offer_rounds(headline_offer["id"])) == 1
        assert (
            fixtures.get_edition(edition["id"])["committed_guarantee_total_cents"]
            == 500_000
        )

        countered = validate_success(
            api_client.counter_offer(
                headline_offer["id"],
                factories.build_counter_payload(
                    600_000, note="Add a production allowance"
                ),
                agent_headers,
            )
        )
        assert countered["round_count"] == 2
        # A counter is the agent's ask, so the buyer's encumbrance does not move.
        assert (
            fixtures.get_edition(edition["id"])["committed_guarantee_total_cents"]
            == 500_000
        )

        support_offer = fixtures.create_offer(
            edition["id"],
            support["id"],
            stage["id"],
            offered_guarantee_cents=700_000,
            backend_breakeven_cents=0,
            target_show_date="2026-08-24",
            load_in_start_utc="2026-08-24T14:00:00.000Z",
            load_out_end_utc="2026-08-24T23:00:00.000Z",
        )
        validate_success(api_client.send_offer(support_offer["id"], TALENT_BUYER_HEADERS))
        assert (
            fixtures.get_edition(edition["id"])["committed_guarantee_total_cents"]
            == 1_200_000
        )
        validate_success(api_client.decline_offer(support_offer["id"], agent_headers))
        assert (
            fixtures.get_edition(edition["id"])["committed_guarantee_total_cents"]
            == 500_000
        )

        revised = validate_success(
            api_client.revise_offer(
                headline_offer["id"],
                factories.build_revise_payload(
                    fixtures.offer_version(headline_offer["id"]),
                    550_000,
                    backend_breakeven_cents=0,
                    note="Split the difference",
                ),
                TALENT_BUYER_HEADERS,
            )
        )
        assert revised["round_count"] == 3
        assert len(fixtures.list_offer_rounds(headline_offer["id"])) == 3
        assert (
            fixtures.get_edition(edition["id"])["committed_guarantee_total_cents"]
            == 550_000
        )

        accepted = validate_success(
            api_client.accept_offer(headline_offer["id"], agent_headers)
        )
        assert accepted["agreed_guarantee_cents"] == 550_000
        assert accepted["round_count"] == 3
        # The contribution now comes from the agreed figure, at the same amount.
        assert (
            fixtures.get_edition(edition["id"])["committed_guarantee_total_cents"]
            == 550_000
        )

    def test_booking_gross_potential_sums_the_rounded_tier_lines(self):
        """Three price tiers of different seating types are added to one show, and the
        booking's gross potential is the running sum of the tiers' own rounded line
        amounts, with the facility fee excluded from all of them. "each tier's line
        amount is rounded to whole cents first and the rounded line amounts are then
        added together"

        Design: Corner/cross_cutting_complexity_layers/derived_counters_and_aggregates_track_their_base_rows_exactly
        """
        scenario = fixtures.setup_accepted_booking()
        booking_id = scenario["booking"]["id"]

        gold = fixtures.add_ticket_scale(
            booking_id, allotment_seats=2000, facility_fee_cents=400
        )
        assert gold["scale_gross_potential_cents"] == 11866075
        assert fixtures.get_booking(booking_id)["gross_potential_cents"] == 11866075

        lawn = fixtures.add_ticket_scale(
            booking_id,
            seating_type="GENERAL_ADMISSION",
            tier_name="LAWN",
            face_price_cents=3950,
            allotment_seats=6000,
        )
        assert lawn["scale_gross_potential_cents"] == 22337250
        assert fixtures.get_booking(booking_id)["gross_potential_cents"] == 34203325

        silver = fixtures.add_ticket_scale(
            booking_id,
            tier_name="SILVER",
            face_price_cents=4000,
            allotment_seats=1000,
        )
        assert silver["scale_gross_potential_cents"] == 3770000
        assert fixtures.get_booking(booking_id)["gross_potential_cents"] == 37973325
