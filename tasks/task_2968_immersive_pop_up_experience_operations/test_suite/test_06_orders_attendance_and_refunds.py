"""Selling the seats: the pinned rounding order, the seat ledger and the refund split."""

from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    api_client,
    assert_guest,
    assert_guest_credit_conserved,
    assert_instant_equals,
    assert_order,
    assert_refund_split_conserved,
    assert_row_inert,
    assert_slot_ledger,
    assert_total_count,
    factories as f,
    fixtures as fx,
    make_guest_headers,
    validate_error,
    validate_object,
    validate_paginated,
    validate_success,
)

VOM = fx.VOM
PRODUCER = fx.PRODUCER
AGENT = fx.AGENT


class TestPerGuestRoundingIsPinned:
    """A price whose two rounding orders differ by two cents on one order."""

    @staticmethod
    def _world():
        """A 7777-cent run, a 40-seat window and a PATRON who books chairs."""
        bundle = fx.run_with_room(base_ticket_price_cents=7777)
        bundle["slot"] = fx.open_slot(
            bundle["run"]["id"], base_capacity=40, wheelchair_positions=4
        )
        bundle["guest"] = fx.create_guest(
            email="pat@example.com", display_name="Pat Osei",
            loyalty_tier="PATRON", accommodation_profile=["WHEELCHAIR"],
        )
        fx.set_clock("2026-08-17T00:00:00Z")
        return bundle

    def test_the_per_guest_price_is_rounded_before_the_party_multiplies(self):
        """Rounding the product instead loses two cents on a party of seven.

        PRD: "`per_guest_after_loyalty_cents` is the unit price reduced by the
        loyalty discount for the guest's tier — 0 percent for `VISITOR`, 5
        percent for `MEMBER`, 12 percent for `PATRON` — rounded half up to whole
        cents. `gross_amount_cents` is that per-guest figure multiplied by
        `party_size`. Multiplying first and rounding the product afterwards
        yields a different number of cents and is forbidden."
        PRD: "`group_discount_cents` is 5 percent of `gross_amount_cents`,
        rounded half up once, but only when `order_type` is `GROUP`"

        Design: Difficulty/combinatorial_formula/order_total_rounds_per_guest_before_multiplying_party
        """
        bundle = self._world()
        slot = bundle["slot"]

        order = validate_object(
            api_client.create_order(
                f.order_payload(
                    slot["id"], bundle["guest"]["id"], party_size=7,
                    order_type="GROUP", wheelchair_party_count=0,
                    sensory_accommodations=[], merch_amount_cents=0,
                ),
                AGENT,
            ),
            201,
        )
        assert_order(order)
        assert order["unit_price_cents"] == 7777
        assert order["per_guest_after_loyalty_cents"] == 6844
        assert order["gross_amount_cents"] == 47908
        assert order["group_discount_cents"] == 2395
        assert order["companion_waiver_cents"] == 0
        assert order["discount_cents"] == 2395
        assert order["net_amount_cents"] == 45513
        assert order["status"] == "PENDING"
        assert order["net_collected_cents"] == 0

        quote = validate_success(
            api_client.get_price_quote(
                slot["id"],
                f.price_quote_params(
                    order_type="GROUP", loyalty_tier="PATRON", party_size=7,
                    wheelchair_party_count=0,
                ),
                AGENT,
            )
        )
        assert quote["lead_days"] == 19
        for field in (
            "unit_price_cents", "per_guest_after_loyalty_cents",
            "gross_amount_cents", "group_discount_cents", "net_amount_cents",
        ):
            assert quote[field] == order[field], field

        assert_slot_ledger(fx.read_slot(slot["id"]), 40, 7, 0, 33)

    def test_the_companion_waiver_covers_one_chair_however_many_were_booked(self):
        """Two wheelchair seats, one free companion, and the waiver joins the discount.

        PRD: "`companion_waiver_cents` is the per-guest figure multiplied by the
        smaller of `wheelchair_party_count` and 1, so exactly one companion
        travels free however many chairs are in the party."
        PRD: "`discount_cents` is the sum of the two, and `net_amount_cents` is
        `gross_amount_cents` less `discount_cents`, floored at 0."

        Design: Difficulty/combinatorial_formula/order_total_rounds_per_guest_before_multiplying_party
        """
        bundle = self._world()
        slot = bundle["slot"]

        order = validate_object(
            api_client.create_order(
                f.order_payload(
                    slot["id"], bundle["guest"]["id"], party_size=7,
                    order_type="GROUP", wheelchair_party_count=2,
                    sensory_accommodations=["WHEELCHAIR"], merch_amount_cents=0,
                ),
                AGENT,
            ),
            201,
        )
        assert_order(order)
        assert order["per_guest_after_loyalty_cents"] == 6844
        assert order["gross_amount_cents"] == 47908
        assert order["group_discount_cents"] == 2395
        assert order["companion_waiver_cents"] == 6844
        assert order["discount_cents"] == 9239
        assert order["net_amount_cents"] == 38669

        after = fx.read_slot(slot["id"])
        assert_slot_ledger(after, 40, 7, 0, 33)
        assert after["wheelchair_sold"] == 0


class TestRefundSplitBeforeTheZeroing:
    """Three writes that look circular: both legs are read off the same field."""

    @staticmethod
    def _confirmed_order():
        """One 35833-cent seat, paid for eleven days before the doors."""
        bundle = fx.selling_world(
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 4},
            guest_overrides={"email": "dana@example.com",
                             "display_name": "Dana Ruiz"},
        )
        fx.set_clock("2026-08-25T00:00:00Z")
        bundle["order"] = fx.confirmed_order(
            bundle["slot"]["id"], bundle["guest"]["id"], party_size=1
        )
        return bundle

    def test_both_legs_come_from_the_collected_amount_the_step_then_zeroes(self):
        """Zeroing first would leave the credit leg at 0 beside a 17917-cent refund.

        PRD: "72 hours or more earns `refund_pct` 1.00, 24 hours or more earns
        0.50, and anything closer earns 0.00. `refunded_cents` is
        `net_collected_cents` multiplied by `refund_pct` rounded half up,
        `credit_issued_cents` is the exact remainder so no cent is lost, and
        `net_collected_cents` is then set to 0."
        PRD: "The seats come back: `sold_capacity` falls by `party_size`,
        `wheelchair_sold` falls by `wheelchair_party_count`,
        `available_capacity` is recomputed, and a `SOLD_OUT` slot returns to
        `OPEN`."

        Design: Difficulty/combinatorial_formula/refund_split_evaluated_before_net_collected_is_zeroed
        """
        bundle = self._confirmed_order()
        order = bundle["order"]
        assert order["net_amount_cents"] == 35833
        assert order["net_collected_cents"] == 35833

        fx.set_clock("2026-09-04T00:00:00Z")
        cancelled = validate_success(
            api_client.cancel_order(
                order["id"], f.cancel_payload("guest illness"), AGENT
            )
        )
        assert cancelled["status"] == "REFUND_DUE"
        assert cancelled["refund_pct"] == 0.50
        assert cancelled["refunded_cents"] == 17917
        assert cancelled["credit_issued_cents"] == 17916
        assert cancelled["refunded_cents"] + cancelled["credit_issued_cents"] == 35833
        assert cancelled["net_collected_cents"] == 0
        assert_refund_split_conserved(cancelled)

        assert_slot_ledger(fx.read_slot(bundle["slot"]["id"]), 40, 0, 0, 40)

    def test_the_credit_leg_reaches_the_guest_only_at_settlement(self):
        """Between the cancel and the settle the balance is still zero.

        PRD: "Settling moves `REFUND_DUE → REFUNDED`, stamps
        `refund_settled_at`, and adds `credit_issued_cents` to the guest's
        `experience_credit_cents`. Only at that moment does the credit actually
        reach the guest."
        PRD: "a guest's `experience_credit_cents` equals the sum of
        `credit_issued_cents` over all of that guest's `REFUNDED` orders."

        Design: Difficulty/combinatorial_formula/refund_split_evaluated_before_net_collected_is_zeroed
        """
        bundle = self._confirmed_order()
        order = bundle["order"]
        guest_id = bundle["guest"]["id"]

        fx.set_clock("2026-09-04T00:00:00Z")
        validate_success(
            api_client.cancel_order(
                order["id"], f.cancel_payload("guest illness"), AGENT
            )
        )
        between = validate_success(api_client.get_guest(guest_id, AGENT))
        assert_guest(between)
        assert between["experience_credit_cents"] == 0

        settled = validate_success(api_client.settle_refund(order["id"], AGENT))
        assert settled["status"] == "REFUNDED"
        assert_instant_equals(settled["refund_settled_at"], "2026-09-04T00:00:00Z")
        assert settled["credit_issued_cents"] == 17916
        assert settled["net_collected_cents"] == 0

        after = validate_success(api_client.get_guest(guest_id, AGENT))
        assert after["experience_credit_cents"] == 17916
        assert_guest_credit_conserved(after, [settled])


class TestRefundLadderEdges:
    """A ladder on exact hours, probed at both of its declared steps."""

    @staticmethod
    def _world():
        """Three identical 64500-cent orders, two guests, one window."""
        bundle = fx.selling_world(
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 4},
            guest_overrides={"email": "ines@example.com",
                             "display_name": "Ines Bloom"},
        )
        bundle["guest_b"] = fx.create_guest(
            email="jonas@example.com", display_name="Jonas Kerr"
        )
        slot_id = bundle["slot"]["id"]
        bundle["order_a"] = fx.confirmed_order(
            slot_id, bundle["guest"]["id"], party_size=2
        )
        bundle["order_b"] = fx.confirmed_order(
            slot_id, bundle["guest"]["id"], party_size=2
        )
        bundle["order_c"] = fx.confirmed_order(
            slot_id, bundle["guest_b"]["id"], party_size=2
        )
        for key in ("order_a", "order_b", "order_c"):
            assert bundle[key]["unit_price_cents"] == 32250
            assert bundle[key]["net_collected_cents"] == 64500
        return bundle

    def test_the_two_edges_are_inside_their_tiers_and_a_minute_later_is_not(self):
        """Exactly 72 and exactly 24 hours still earn their tier; 23:59 earns none.

        PRD: "72 hours or more earns `refund_pct` 1.00, 24 hours or more earns
        0.50, and anything closer earns 0.00."
        PRD: "`credit_issued_cents` is the exact remainder so no cent is lost,
        and `net_collected_cents` is then set to 0."

        Design: Difficulty/boundary_precision_check/refund_ladder_tier_edges_at_exactly_seventytwo_and_twentyfour_hours
        """
        bundle = self._world()

        fx.set_clock("2026-09-02T14:00:00Z")
        full = validate_success(
            api_client.cancel_order(
                bundle["order_a"]["id"],
                f.cancel_payload("exactly 72 hours out"),
                AGENT,
            )
        )
        assert full["refund_pct"] == 1.00
        assert full["refunded_cents"] == 64500
        assert full["credit_issued_cents"] == 0
        assert full["status"] == "REFUND_DUE"
        assert_refund_split_conserved(full)

        fx.set_clock("2026-09-04T14:00:00Z")
        half = validate_success(
            api_client.cancel_order(
                bundle["order_b"]["id"],
                f.cancel_payload("exactly 24 hours out"),
                AGENT,
            )
        )
        assert half["refund_pct"] == 0.50
        assert half["refunded_cents"] == 32250
        assert half["credit_issued_cents"] == 32250
        assert_refund_split_conserved(half)

        fx.set_clock("2026-09-04T14:01:00Z")
        none = validate_success(
            api_client.cancel_order(
                bundle["order_c"]["id"],
                f.cancel_payload("one minute past the 24 hour edge"),
                AGENT,
            )
        )
        assert none["refund_pct"] == 0.00
        assert none["refunded_cents"] == 0
        assert none["credit_issued_cents"] == 64500
        assert_refund_split_conserved(none)

        slot = fx.read_slot(bundle["slot"]["id"])
        assert_slot_ledger(slot, 40, 0, 0, 40)
        assert slot["status"] == "OPEN"

    def test_only_the_settled_refund_lands_on_its_guests_balance(self):
        """Two orders left in REFUND_DUE leave their guest's balance at zero.

        PRD: "Settling the refund is a separate act and it recomputes nothing."
        PRD: "Settling moves `REFUND_DUE → REFUNDED`, stamps
        `refund_settled_at`, and adds `credit_issued_cents` to the guest's
        `experience_credit_cents`."

        Design: Difficulty/boundary_precision_check/refund_ladder_tier_edges_at_exactly_seventytwo_and_twentyfour_hours
        """
        bundle = self._world()

        fx.set_clock("2026-09-02T14:00:00Z")
        validate_success(
            api_client.cancel_order(
                bundle["order_a"]["id"], f.cancel_payload("full tier"), AGENT
            )
        )
        fx.set_clock("2026-09-04T14:00:00Z")
        validate_success(
            api_client.cancel_order(
                bundle["order_b"]["id"], f.cancel_payload("half tier"), AGENT
            )
        )
        fx.set_clock("2026-09-04T14:01:00Z")
        validate_success(
            api_client.cancel_order(
                bundle["order_c"]["id"], f.cancel_payload("zero tier"), AGENT
            )
        )

        settled = validate_success(
            api_client.settle_refund(bundle["order_c"]["id"], AGENT)
        )
        assert settled["status"] == "REFUNDED"
        assert_instant_equals(settled["refund_settled_at"], "2026-09-04T14:01:00Z")

        guest_b = validate_success(
            api_client.get_guest(bundle["guest_b"]["id"], AGENT)
        )
        assert guest_b["experience_credit_cents"] == 64500
        assert_guest_credit_conserved(guest_b, [settled])

        guest_a = validate_success(
            api_client.get_guest(bundle["guest"]["id"], AGENT)
        )
        assert guest_a["experience_credit_cents"] == 0
        unsettled = [
            fx.read_order(bundle["order_a"]["id"]),
            fx.read_order(bundle["order_b"]["id"]),
        ]
        assert [row["status"] for row in unsettled] == ["REFUND_DUE", "REFUND_DUE"]
        assert_guest_credit_conserved(guest_a, unsettled)


class TestNoShowRestrictionBlocksTheNextSale:
    """The blocking state accumulates on the guest, not on the window."""

    @staticmethod
    def _world():
        """Three no-showable seats on one window and a clean second window."""
        bundle = fx.selling_world(
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 4},
            guest_overrides={"email": "kaya@example.com",
                             "display_name": "Kaya Nomura"},
        )
        run_id = bundle["run"]["id"]
        bundle["slot_two"] = fx.open_slot(
            run_id, slot_start_utc="2026-09-12T14:00:00Z",
            slot_end_utc="2026-09-12T14:45:00Z", base_capacity=40,
            wheelchair_positions=4,
        )
        bundle["orders"] = [
            fx.confirmed_order(bundle["slot"]["id"], bundle["guest"]["id"],
                               party_size=1)
            for _ in range(3)
        ]
        return bundle

    def test_the_third_strike_restricts_and_the_second_does_not(self):
        """A forfeited ticket refunds nothing and the cap is inclusive.

        PRD: "an earlier attempt is refused with `ERR_NO_SHOW_TOO_EARLY`; it
        moves the order `CONFIRMED → NO_SHOW`, raises `no_show_strikes` by 1, and
        preserves `net_collected_cents` — a no-show forfeits the ticket and
        refunds nothing."
        PRD: "The strike threshold is cumulative and inclusive: once
        `no_show_strikes` reaches 3 the account moves `ACTIVE → RESTRICTED`, so
        the third strike restricts and the second does not."

        Design: Difficulty/cross_entity_state_dependency/order_creation_blocked_by_the_guests_no_show_restriction
        """
        bundle = self._world()
        guest_id = bundle["guest"]["id"]
        fx.set_clock("2026-09-05T15:01:00Z")

        expected = [(1, "ACTIVE"), (2, "ACTIVE"), (3, "RESTRICTED")]
        for order, (strikes, status) in zip(bundle["orders"], expected):
            marked = validate_success(
                api_client.record_attendance(
                    order["id"], f.attendance_payload("NO_SHOW"), AGENT
                )
            )
            assert marked["status"] == "NO_SHOW"
            assert marked["net_collected_cents"] == 32250
            guest = validate_success(api_client.get_guest(guest_id, AGENT))
            assert guest["no_show_strikes"] == strikes
            assert guest["status"] == status
            assert guest["visit_count"] == 0

    def test_the_restriction_blocks_an_untouched_window_until_reinstatement(self):
        """Nothing about the second window changes between the refusal and the sale.

        PRD: "The guest account must be `ACTIVE`, or the create is refused with
        `ERR_GUEST_RESTRICTED`."
        PRD: "An agent may reinstate a restricted account, moving `RESTRICTED →
        ACTIVE` and resetting `no_show_strikes` to 0; `visit_count` is never
        reset."

        Design: Difficulty/cross_entity_state_dependency/order_creation_blocked_by_the_guests_no_show_restriction
        """
        bundle = self._world()
        guest_id = bundle["guest"]["id"]
        slot_two = bundle["slot_two"]
        fx.set_clock("2026-09-05T15:01:00Z")
        for order in bundle["orders"]:
            validate_success(
                api_client.record_attendance(
                    order["id"], f.attendance_payload("NO_SHOW"), AGENT
                )
            )

        payload = f.order_payload(
            slot_two["id"], guest_id, party_size=1, order_type="SINGLE"
        )
        validate_error(
            api_client.create_order(payload, AGENT),
            ApiErrorId.ERR_GUEST_RESTRICTED.value,
            409,
        )
        refused_view = fx.read_slot(slot_two["id"])
        assert_slot_ledger(refused_view, 40, 0, 0, 40)
        assert_row_inert(slot_two, refused_view)
        assert_total_count(
            api_client.list_orders(AGENT, {"slot_id": slot_two["id"]}), 0
        )

        reinstated = validate_success(api_client.reinstate_guest(guest_id, AGENT))
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["no_show_strikes"] == 0
        assert reinstated["visit_count"] == 0

        order = validate_object(api_client.create_order(payload, AGENT), 201)
        assert order["unit_price_cents"] == 41208
        assert order["net_amount_cents"] == 41208
        confirmed = validate_success(api_client.confirm_order(order["id"], AGENT))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["net_collected_cents"] == 41208
        assert_slot_ledger(fx.read_slot(slot_two["id"]), 40, 0, 1, 39)


class TestGuestMoneyIsConserved:
    """Cash plus credit equals the net of the order, cent for cent."""

    @staticmethod
    def _world():
        """An odd 188727-cent group order and an even 56760-cent single one."""
        bundle = fx.selling_world(
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 4},
            guest_overrides={"email": "lena@example.com",
                             "display_name": "Lena Ott", "loyalty_tier": "PATRON"},
        )
        slot_id = bundle["slot"]["id"]
        guest_id = bundle["guest"]["id"]
        bundle["group"] = fx.confirmed_order(
            slot_id, guest_id, party_size=7, order_type="GROUP",
            merch_amount_cents=12000,
        )
        bundle["single"] = fx.confirmed_order(slot_id, guest_id, party_size=2)
        assert bundle["group"]["net_collected_cents"] == 188727
        assert bundle["single"]["net_collected_cents"] == 56760
        return bundle

    def test_an_odd_net_halves_without_losing_or_duplicating_a_cent(self):
        """94364 plus 94363 is 188727; a symmetric round on both legs is not.

        PRD: "`refunded_cents` is `net_collected_cents` multiplied by
        `refund_pct` rounded half up, `credit_issued_cents` is the exact
        remainder so no cent is lost, and `net_collected_cents` is then set to
        0."
        PRD: "`merch_amount_cents` is never discounted and is not part of
        `net_amount_cents`; it only ever reaches the merchandise leg of the
        royalty accrual."

        Design: Difficulty/compensating_invariant/order_money_splits_into_cash_and_credit_without_loss
        """
        bundle = self._world()
        group = bundle["group"]
        assert group["net_amount_cents"] == 188727
        assert group["merch_amount_cents"] == 12000

        fx.set_clock("2026-09-04T14:00:00Z")
        cancelled = validate_success(
            api_client.cancel_order(
                group["id"], f.cancel_payload("half tier"), AGENT
            )
        )
        assert cancelled["refund_pct"] == 0.50
        assert cancelled["refunded_cents"] == 94364
        assert cancelled["credit_issued_cents"] == 94363
        assert (
            cancelled["refunded_cents"] + cancelled["credit_issued_cents"]
            == 188727
        )
        assert cancelled["net_collected_cents"] == 0
        assert cancelled["merch_amount_cents"] == 12000
        assert_refund_split_conserved(cancelled)

        between = validate_success(
            api_client.get_guest(bundle["guest"]["id"], AGENT)
        )
        assert between["experience_credit_cents"] == 0

        settled = validate_success(api_client.settle_refund(group["id"], AGENT))
        assert settled["status"] == "REFUNDED"
        assert settled["merch_amount_cents"] == 12000
        after = validate_success(
            api_client.get_guest(bundle["guest"]["id"], AGENT)
        )
        assert after["experience_credit_cents"] == 94363

    def test_the_balance_is_the_sum_over_the_settled_refunds_of_that_guest(self):
        """Two refunds of one guest, one at each end of the ladder, add up exactly.

        PRD: "Afterwards `refunded_cents` plus `credit_issued_cents` equals
        `net_amount_cents` for that order, and a guest's
        `experience_credit_cents` equals the sum of `credit_issued_cents` over
        all of that guest's `REFUNDED` orders."

        Design: Difficulty/compensating_invariant/order_money_splits_into_cash_and_credit_without_loss
        """
        bundle = self._world()
        guest_id = bundle["guest"]["id"]

        fx.set_clock("2026-09-04T14:00:00Z")
        validate_success(
            api_client.cancel_order(
                bundle["group"]["id"], f.cancel_payload("half tier"), AGENT
            )
        )
        group = validate_success(
            api_client.settle_refund(bundle["group"]["id"], AGENT)
        )

        fx.set_clock("2026-09-05T13:00:00Z")
        single = validate_success(
            api_client.cancel_order(
                bundle["single"]["id"], f.cancel_payload("zero tier"), AGENT
            )
        )
        assert single["refund_pct"] == 0.00
        assert single["refunded_cents"] == 0
        assert single["credit_issued_cents"] == 56760
        assert_refund_split_conserved(single)

        midway = validate_success(api_client.get_guest(guest_id, AGENT))
        assert midway["experience_credit_cents"] == 94363

        single = validate_success(
            api_client.settle_refund(bundle["single"]["id"], AGENT)
        )
        final = validate_success(api_client.get_guest(guest_id, AGENT))
        assert final["experience_credit_cents"] == 151123
        assert_guest_credit_conserved(final, [group, single])
        for order in (group, single):
            assert (
                order["refunded_cents"] + order["credit_issued_cents"]
                == order["net_amount_cents"]
            )
            assert order["net_collected_cents"] == 0

        assert_slot_ledger(fx.read_slot(bundle["slot"]["id"]), 40, 0, 0, 40)


class TestConfirmationsBubbleIntoTheLedger:
    """The window's status is a function of its ledger, not of its order count."""

    def test_the_flip_fires_on_the_confirmation_that_empties_the_hold(self):
        """Three parties are held then paid for; only the last leaves nothing available.

        A confirmation only moves seats from `held_capacity` into
        `sold_capacity`, so the recomputed `available_capacity` is whatever the
        holds left behind.  Each party is therefore held and confirmed in turn,
        and the window flips exactly on the confirmation whose recomputation
        leaves nothing available.

        PRD: "On success the order moves `PENDING → CONFIRMED`,
        `net_collected_cents` becomes `net_amount_cents`, the seats move from
        `held_capacity` into `sold_capacity`, `wheelchair_sold` rises by
        `wheelchair_party_count`, `available_capacity` is recomputed as
        `released_capacity` less `held_capacity` less `sold_capacity`, and the
        slot moves to `SOLD_OUT` when that leaves nothing available."
        PRD: "it takes its seats as a hold: the slot's `held_capacity` rises by
        `party_size` while `available_capacity` falls by the same amount."
        PRD: "A check-in moves the order `CONFIRMED → CHECKED_IN`, stamps
        `checked_in_at` and raises the guest's `visit_count` by 1."

        Design: Corner/state_machines/order_confirmations_bubble_into_the_slot_ledger_and_flip_it_sold_out
        """
        bundle = fx.selling_world(
            slot_overrides={"base_capacity": 20},
            guest_overrides={"email": "ravi@example.com",
                             "display_name": "Ravi Chandra"},
        )
        slot_id = bundle["slot"]["id"]
        guest_id = bundle["guest"]["id"]

        opening = validate_success(api_client.get_slot(slot_id, PRODUCER))
        assert_slot_ledger(opening, 20, 0, 0, 20)
        assert opening["status"] == "OPEN"

        expected = [
            ({"party_size": 2, "order_type": "SINGLE"}, 64500,
             (20, 2, 0, 18), (20, 0, 2, 18), "OPEN"),
            ({"party_size": 12, "order_type": "GROUP"}, 367650,
             (20, 12, 2, 6), (20, 0, 14, 6), "OPEN"),
            ({"party_size": 6, "order_type": "GROUP"}, 183825,
             (20, 6, 14, 0), (20, 0, 20, 0), "SOLD_OUT"),
        ]
        for shape, collected, held_ledger, sold_ledger, status in expected:
            order = fx.place_order(slot_id, guest_id, **shape)
            on_hold = validate_success(api_client.get_slot(slot_id, PRODUCER))
            assert_slot_ledger(on_hold, *held_ledger)

            confirmed = validate_success(api_client.confirm_order(order["id"], AGENT))
            assert confirmed["status"] == "CONFIRMED"
            assert confirmed["net_collected_cents"] == collected
            slot = validate_success(api_client.get_slot(slot_id, PRODUCER))
            assert_slot_ledger(slot, *sold_ledger)
            assert slot["status"] == status
            assert slot["wheelchair_sold"] == 0
            assert slot["version"] == on_hold["version"] + 1

        guest = validate_success(api_client.get_guest(guest_id, AGENT))
        assert guest["visit_count"] == 0


class TestPendingCancelIsPureCompensation:
    """The pending branch undoes the hold and never runs the refund ladder."""

    def test_the_seats_come_back_once_and_the_money_legs_stay_at_zero(self):
        """A second cancel is refused rather than compensating twice.

        PRD: "A `PENDING` order simply drops its hold: it moves to `CANCELLED`
        with `refund_pct` 0.00 and all three money legs at 0, and the slot's
        `held_capacity` falls by `party_size` while `available_capacity` rises
        again"
        PRD: "a `GROUP` order of five guests earns nothing, and a `SINGLE` order
        never earns it at any size."

        Design: Corner/state_machines/cancelling_a_pending_order_returns_the_held_seats_to_the_window
        """
        bundle = fx.run_with_room()
        slot = fx.open_slot(bundle["run"]["id"], base_capacity=20)
        guest = fx.create_guest(
            email="ola@example.com", display_name="Ola Ferreira",
            loyalty_tier="PATRON",
        )

        order = validate_object(
            api_client.create_order(
                f.order_payload(
                    slot["id"], guest["id"], party_size=5, order_type="GROUP",
                    merch_amount_cents=4000,
                ),
                AGENT,
            ),
            201,
        )
        assert order["unit_price_cents"] == 32250
        assert order["per_guest_after_loyalty_cents"] == 28380
        assert order["gross_amount_cents"] == 141900
        assert order["group_discount_cents"] == 0
        assert order["net_amount_cents"] == 141900
        held = validate_success(api_client.get_slot(slot["id"], PRODUCER))
        assert_slot_ledger(held, 20, 5, 0, 15)
        assert held["status"] == "OPEN"

        cancelled = validate_success(
            api_client.cancel_order(
                order["id"], f.cancel_payload("school trip called off"), AGENT
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_pct"] == 0.00
        assert cancelled["refunded_cents"] == 0
        assert cancelled["credit_issued_cents"] == 0
        assert cancelled["net_collected_cents"] == 0
        assert cancelled["merch_amount_cents"] == 4000

        restored = validate_success(api_client.get_slot(slot["id"], PRODUCER))
        assert_slot_ledger(restored, 20, 0, 0, 20)
        assert restored["status"] == "OPEN"
        guest_after = validate_success(api_client.get_guest(guest["id"], AGENT))
        assert guest_after["experience_credit_cents"] == 0
        assert guest_after["visit_count"] == 0

        validate_error(
            api_client.cancel_order(
                order["id"], f.cancel_payload("double cancellation"), AGENT
            ),
            ApiErrorId.ERR_ORDER_INVALID_STATE.value,
            409,
        )
        assert_row_inert(restored, fx.read_slot(slot["id"]))


class TestAggregateHoldExhaustsTheWindow:
    """Each request is legal alone; the collective hold is what refuses it."""

    def test_the_ceiling_reads_the_live_seats_and_moves_when_a_hold_is_dropped(self):
        """The very party refused at four free seats succeeds once eight come back.

        PRD: "The hold must fit the window: a party larger than the slot's
        `available_capacity` is refused with `ERR_SLOT_CAPACITY_EXCEEDED`."
        PRD: "A new order is `PENDING` with `net_collected_cents`,
        `refunded_cents` and `credit_issued_cents` at 0 and `refund_pct` at 0.00,
        and it takes its seats as a hold: the slot's `held_capacity` rises by
        `party_size` while `available_capacity` falls by the same amount."

        Design: Corner/validations/individually_legal_orders_collectively_exhaust_the_window
        """
        bundle = fx.run_with_room()
        slot = fx.open_slot(bundle["run"]["id"], base_capacity=20)
        guest = fx.create_guest()
        slot_id = slot["id"]

        def party_of(size, order_type="GROUP"):
            return f.order_payload(
                slot_id, guest["id"], party_size=size, order_type=order_type
            )

        first = validate_object(api_client.create_order(party_of(8), AGENT), 201)
        assert_slot_ledger(fx.read_slot(slot_id), 20, 8, 0, 12)
        validate_object(api_client.create_order(party_of(8), AGENT), 201)
        assert_slot_ledger(fx.read_slot(slot_id), 20, 16, 0, 4)

        validate_error(
            api_client.create_order(party_of(8), AGENT),
            ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value,
            409,
        )
        validate_object(
            api_client.create_order(party_of(4, "SINGLE"), AGENT), 201
        )
        validate_error(
            api_client.create_order(party_of(1, "SINGLE"), AGENT),
            ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value,
            409,
        )
        full = fx.read_slot(slot_id)
        assert_slot_ledger(full, 20, 20, 0, 0)
        assert full["status"] == "OPEN"

        validate_success(
            api_client.cancel_order(
                first["id"], f.cancel_payload("coach cancelled"), AGENT
            )
        )
        assert_slot_ledger(fx.read_slot(slot_id), 20, 12, 0, 8)
        validate_object(api_client.create_order(party_of(8), AGENT), 201)
        assert_slot_ledger(fx.read_slot(slot_id), 20, 20, 0, 0)
        assert_total_count(api_client.list_orders(AGENT, {"slot_id": slot_id}), 4)


class TestAccommodationGates:
    """Four gates, four different collections, each armed by its own request."""

    @staticmethod
    def _world():
        """Three rooms that each fail a different accessibility promise."""
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        fx.add_room(run_id, 2, name="Cascade Hall", room_occupancy_cap=30,
                    target_dwell_minutes=12, min_dwell_minutes=4,
                    sensory_intensity_level=3, has_quiet_bypass=True,
                    wheelchair_accessible=False)
        fx.add_room(run_id, 3, name="Signal Room", room_occupancy_cap=20,
                    target_dwell_minutes=16, min_dwell_minutes=6,
                    sensory_intensity_level=4, has_quiet_bypass=False,
                    wheelchair_accessible=True)
        bundle["run"] = fx.read_run(run_id)
        bundle["slot"] = fx.open_slot(run_id, base_capacity=20,
                                      wheelchair_positions=2)
        bundle["slot_b"] = fx.open_slot(
            run_id, slot_start_utc="2026-09-06T14:00:00Z",
            slot_end_utc="2026-09-06T14:45:00Z", base_capacity=20,
            wheelchair_positions=0,
        )
        bundle["guest"] = fx.create_guest(
            email="mira@example.com", display_name="Mira Adeyemi",
            accommodation_profile=["WHEELCHAIR"],
        )
        return bundle

    def test_each_request_is_gated_by_the_collection_its_own_rule_names(self):
        """The inaccessible room, the intense room and the empty roster each refuse once.

        PRD: "A `QUIET_ROUTE` request requires every room whose
        `sensory_intensity_level` is 4 or higher to have `has_quiet_bypass` true,
        or it is refused with `ERR_QUIET_ROUTE_UNAVAILABLE`; rooms rated 1, 2 or
        3 need no bypass. An `ASL_INTERPRETER` request requires at least one
        staff member of the run with status `CLEARED` and `staff_role` of
        `AMBASSADOR`, or it is refused with `ERR_ASL_NOT_STAFFED`.
        `LOW_STIM_HOURS` carries no structural requirement."
        PRD: "Accommodation requests are promises about the physical run, so they
        are checked against its rooms and roster."

        Design: Corner/validations/accommodation_requests_are_gated_by_the_rooms_and_the_roster
        """
        bundle = self._world()
        slot_id = bundle["slot"]["id"]
        guest_id = bundle["guest"]["id"]

        def asking(*accommodations):
            return f.order_payload(
                slot_id, guest_id, party_size=2, order_type="SINGLE",
                sensory_accommodations=list(accommodations),
            )

        validate_error(
            api_client.create_order(asking("WHEELCHAIR"), AGENT),
            ApiErrorId.ERR_WHEELCHAIR_ROUTE_UNAVAILABLE.value,
            409,
        )
        validate_error(
            api_client.create_order(asking("QUIET_ROUTE"), AGENT),
            ApiErrorId.ERR_QUIET_ROUTE_UNAVAILABLE.value,
            409,
        )
        validate_error(
            api_client.create_order(asking("ASL_INTERPRETER"), AGENT),
            ApiErrorId.ERR_ASL_NOT_STAFFED.value,
            409,
        )
        relaxed = validate_object(
            api_client.create_order(asking("LOW_STIM_HOURS"), AGENT), 201
        )
        assert relaxed["sensory_accommodations"] == ["LOW_STIM_HOURS"]

        ambassador = fx.cleared_staff(
            bundle["run"]["id"], "AMBASSADOR", full_name="Dara Vance"
        )
        assert ambassador["status"] == "CLEARED"
        assert ambassador["staff_role"] == "AMBASSADOR"
        signed = validate_object(
            api_client.create_order(asking("ASL_INTERPRETER"), AGENT), 201
        )
        assert signed["sensory_accommodations"] == ["ASL_INTERPRETER"]

    def test_the_position_count_is_a_separate_gate_from_the_route(self):
        """Booking chairs without asking for the route is not route-checked at all.

        PRD: "Independently, the slot's `wheelchair_sold` plus this order's
        `wheelchair_party_count` may not exceed the slot's
        `wheelchair_positions`, or the request is refused with
        `ERR_WHEELCHAIR_POSITIONS_EXHAUSTED`."

        Design: Corner/validations/accommodation_requests_are_gated_by_the_rooms_and_the_roster
        """
        bundle = self._world()
        guest_id = bundle["guest"]["id"]

        booked = validate_object(
            api_client.create_order(
                f.order_payload(
                    bundle["slot"]["id"], guest_id, party_size=2,
                    order_type="SINGLE", wheelchair_party_count=2,
                ),
                AGENT,
            ),
            201,
        )
        assert booked["wheelchair_party_count"] == 2
        assert booked["sensory_accommodations"] == []
        assert fx.read_slot(bundle["slot"]["id"])["wheelchair_sold"] == 0

        validate_error(
            api_client.create_order(
                f.order_payload(
                    bundle["slot_b"]["id"], guest_id, party_size=2,
                    order_type="SINGLE", wheelchair_party_count=1,
                ),
                AGENT,
            ),
            ApiErrorId.ERR_WHEELCHAIR_POSITIONS_EXHAUSTED.value,
            409,
        )


class TestPartySizeRulesByOrderType:
    """One field, three ceilings, and a buyout bound by neither of the other two."""

    def test_the_ceiling_that_applies_depends_on_the_order_type(self):
        """Four is the single maximum, twelve the group one, twenty the buyout's.

        PRD: "for `SINGLE` and `GROUP` it may not exceed the run's
        `max_group_size`, a `SINGLE` order may additionally carry no more than 4
        guests, both refused with `ERR_PARTY_SIZE_ABOVE_GROUP_MAX`; a
        `PRIVATE_BUYOUT` must name a `party_size` exactly equal to the slot's
        `base_capacity`, and anything else is refused with
        `ERR_BUYOUT_PARTY_MISMATCH`."
        PRD: "the slot moves `OPEN → HELD_FOR_BUYOUT`, its `held_capacity`
        becomes the whole `released_capacity`, its `available_capacity` becomes
        0, and `buyout_order_id` records the holding order."

        Design: Corner/validations/party_size_rules_switch_on_the_order_type
        """
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        slot_a = fx.open_slot(run_id, base_capacity=20)
        slot_b = fx.open_slot(
            run_id, slot_start_utc="2026-09-06T14:00:00Z",
            slot_end_utc="2026-09-06T14:45:00Z", base_capacity=20,
        )
        guest = fx.create_guest()

        def order_on(slot_id, size, order_type):
            return f.order_payload(
                slot_id, guest["id"], party_size=size, order_type=order_type
            )

        validate_error(
            api_client.create_order(order_on(slot_a["id"], 5, "SINGLE"), AGENT),
            ApiErrorId.ERR_PARTY_SIZE_ABOVE_GROUP_MAX.value,
            409,
        )
        validate_object(
            api_client.create_order(order_on(slot_a["id"], 4, "SINGLE"), AGENT), 201
        )
        validate_error(
            api_client.create_order(order_on(slot_a["id"], 13, "GROUP"), AGENT),
            ApiErrorId.ERR_PARTY_SIZE_ABOVE_GROUP_MAX.value,
            409,
        )
        validate_object(
            api_client.create_order(order_on(slot_a["id"], 12, "GROUP"), AGENT), 201
        )
        assert_slot_ledger(fx.read_slot(slot_a["id"]), 20, 16, 0, 4)

        validate_error(
            api_client.create_order(
                order_on(slot_b["id"], 19, "PRIVATE_BUYOUT"), AGENT
            ),
            ApiErrorId.ERR_BUYOUT_PARTY_MISMATCH.value,
            409,
        )
        buyout = validate_object(
            api_client.create_order(
                order_on(slot_b["id"], 20, "PRIVATE_BUYOUT"), AGENT
            ),
            201,
        )
        assert buyout["party_size"] == 20

        validate_error(
            api_client.create_order(
                order_on(slot_a["id"], 20, "PRIVATE_BUYOUT"), AGENT
            ),
            ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value,
            409,
        )

        held = validate_success(api_client.get_slot(slot_b["id"], PRODUCER))
        assert_slot_ledger(held, 20, 20, 0, 0)
        assert held["status"] == "HELD_FOR_BUYOUT"
        assert held["buyout_order_id"] == buyout["id"]


class TestAttendanceAndCancellationEdges:
    """Three windows butting up against each other on one admission instant."""

    @staticmethod
    def _world():
        """Four paid parties of two on one twenty-seat window."""
        bundle = fx.selling_world(
            slot_overrides={"base_capacity": 20},
            guest_overrides={"email": "noor@example.com",
                             "display_name": "Noor Haddad"},
        )
        slot_id = bundle["slot"]["id"]
        bundle["orders"] = [
            fx.confirmed_order(slot_id, bundle["guest"]["id"], party_size=2)
            for _ in range(4)
        ]
        return bundle

    def test_the_start_instant_closes_cancellation_and_opens_the_doors(self):
        """One second early the doors are shut, and at the instant itself they open.

        PRD: "a check-in is admissible from `slot_start_utc` up to and including
        15 minutes after `slot_end_utc`, both bounds inclusive, and outside it the
        request is refused with `ERR_CHECKIN_WINDOW_CLOSED`"
        PRD: "A `CONFIRMED` order instead becomes `REFUND_DUE`, and it may only be
        cancelled strictly before `slot_start_utc` — afterwards the request is
        refused with `ERR_CANCEL_WINDOW_CLOSED`."

        Design: Corner/validations/attendance_and_cancellation_windows_hold_at_the_grace_edges
        """
        bundle = self._world()
        first, _second, third, fourth = bundle["orders"]

        fx.set_clock("2026-09-05T13:59:59Z")
        validate_error(
            api_client.record_attendance(
                first["id"], f.attendance_payload("CHECK_IN"), AGENT
            ),
            ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED.value,
            409,
        )
        refunding = validate_success(
            api_client.cancel_order(
                fourth["id"], f.cancel_payload("one minute before the doors"), AGENT
            )
        )
        assert refunding["status"] == "REFUND_DUE"
        assert refunding["refund_pct"] == 0.00

        fx.set_clock("2026-09-05T14:00:00Z")
        validate_error(
            api_client.cancel_order(
                third["id"], f.cancel_payload("at the doors"), AGENT
            ),
            ApiErrorId.ERR_CANCEL_WINDOW_CLOSED.value,
            409,
        )
        assert fx.read_order(third["id"])["status"] == "CONFIRMED"

        admitted = validate_success(
            api_client.record_attendance(
                first["id"], f.attendance_payload("CHECK_IN"), AGENT
            )
        )
        assert admitted["status"] == "CHECKED_IN"
        assert_instant_equals(admitted["checked_in_at"], "2026-09-05T14:00:00Z")

    def test_the_grace_bound_is_the_last_check_in_and_too_early_for_a_no_show(self):
        """One instant is a legal check-in and an illegal no-show at the same time.

        PRD: "an earlier attempt is refused with `ERR_NO_SHOW_TOO_EARLY`; it moves
        the order `CONFIRMED → NO_SHOW`, raises `no_show_strikes` by 1, and
        preserves `net_collected_cents` — a no-show forfeits the ticket and
        refunds nothing."
        PRD: "A check-in moves the order `CONFIRMED → CHECKED_IN`, stamps
        `checked_in_at` and raises the guest's `visit_count` by 1."

        Design: Corner/validations/attendance_and_cancellation_windows_hold_at_the_grace_edges
        """
        bundle = self._world()
        first, second, third, _fourth = bundle["orders"]

        fx.set_clock("2026-09-05T14:00:00Z")
        validate_success(
            api_client.record_attendance(
                first["id"], f.attendance_payload("CHECK_IN"), AGENT
            )
        )

        fx.set_clock("2026-09-05T15:00:00Z")
        late = validate_success(
            api_client.record_attendance(
                second["id"], f.attendance_payload("CHECK_IN"), AGENT
            )
        )
        assert late["status"] == "CHECKED_IN"
        assert_instant_equals(late["checked_in_at"], "2026-09-05T15:00:00Z")
        validate_error(
            api_client.record_attendance(
                third["id"], f.attendance_payload("NO_SHOW"), AGENT
            ),
            ApiErrorId.ERR_NO_SHOW_TOO_EARLY.value,
            409,
        )

        fx.set_clock("2026-09-05T15:00:01Z")
        validate_error(
            api_client.record_attendance(
                third["id"], f.attendance_payload("CHECK_IN"), AGENT
            ),
            ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED.value,
            409,
        )
        missed = validate_success(
            api_client.record_attendance(
                third["id"], f.attendance_payload("NO_SHOW"), AGENT
            )
        )
        assert missed["status"] == "NO_SHOW"
        assert missed["net_collected_cents"] == 64500

        guest = validate_success(
            api_client.get_guest(bundle["guest"]["id"], AGENT)
        )
        assert guest["visit_count"] == 2
        assert guest["no_show_strikes"] == 1
        assert guest["status"] == "ACTIVE"


class TestGuestAccountMergeSemantics:
    """The only PATCH in the API, and the only entity with no collection read."""

    @staticmethod
    def _world():
        """A PEAK window and no guest account yet."""
        bundle = fx.run_with_room()
        bundle["slot"] = fx.open_slot(
            bundle["run"]["id"], slot_start_utc="2026-09-15T14:00:00Z",
            slot_end_utc="2026-09-15T14:45:00Z", pricing_tier="PEAK",
            base_capacity=20, wheelchair_positions=2,
        )
        return bundle

    def test_a_patch_replaces_only_the_fields_it_carries(self):
        """Two partial patches, and the priced order is never repriced by either.

        PRD: "An agent may later replace any of `loyalty_tier`, `display_name`
        and `accommodation_profile`; only the supplied fields change, omitted
        fields keep their stored values, and orders already priced are never
        repriced by a tier change."
        PRD: "A new account is `ACTIVE` with `no_show_strikes`, `visit_count` and
        `experience_credit_cents` at 0."

        Design: Corner/endpoints/guest_account_crud_patches_only_the_fields_it_is_given
        """
        bundle = self._world()
        guest = validate_object(
            api_client.create_guest(
                f.guest_payload(email="mina@example.com",
                                display_name="Mina Ortega"),
                AGENT,
            ),
            201,
        )
        assert_guest(guest)
        assert guest["loyalty_tier"] == "VISITOR"
        assert guest["accommodation_profile"] == []
        assert guest["status"] == "ACTIVE"
        assert guest["no_show_strikes"] == 0
        assert guest["visit_count"] == 0
        assert guest["experience_credit_cents"] == 0
        assert guest["version"] == 1
        assert validate_success(
            api_client.get_guest(guest["id"], PRODUCER)
        ) == guest

        order = validate_object(
            api_client.create_order(
                f.order_payload(bundle["slot"]["id"], guest["id"], party_size=4),
                AGENT,
            ),
            201,
        )
        assert order["unit_price_cents"] == 41925
        assert order["per_guest_after_loyalty_cents"] == 41925
        assert order["gross_amount_cents"] == 167700
        assert order["group_discount_cents"] == 0
        assert order["companion_waiver_cents"] == 0
        assert order["discount_cents"] == 0
        assert order["net_amount_cents"] == 167700

        promoted = validate_success(
            api_client.patch_guest(guest["id"], {"loyalty_tier": "PATRON"}, AGENT)
        )
        assert promoted["loyalty_tier"] == "PATRON"
        assert promoted["display_name"] == "Mina Ortega"
        assert promoted["accommodation_profile"] == []
        assert promoted["email"] == guest["email"]
        assert promoted["version"] == 2

        renamed = validate_success(
            api_client.patch_guest(
                guest["id"],
                {"display_name": "Mina O.",
                 "accommodation_profile": ["QUIET_ROUTE", "WHEELCHAIR"]},
                AGENT,
            )
        )
        assert renamed["display_name"] == "Mina O."
        assert renamed["accommodation_profile"] == ["QUIET_ROUTE", "WHEELCHAIR"]
        assert renamed["loyalty_tier"] == "PATRON"
        assert renamed["version"] == 3
        assert validate_success(
            api_client.get_guest(guest["id"], make_guest_headers(guest["id"]))
        ) == renamed

        frozen = validate_success(api_client.get_order(order["id"], AGENT))
        assert frozen["unit_price_cents"] == 41925
        assert frozen["per_guest_after_loyalty_cents"] == 41925
        assert frozen["net_amount_cents"] == 167700
        rows = assert_total_count(
            api_client.list_orders(AGENT, {"guest_account_id": guest["id"]}), 1
        )
        assert rows[0]["id"] == order["id"]

    def test_a_refused_patch_leaves_the_account_exactly_as_it_was(self):
        """An undeclared tier and an unknown id are both refused without a write.

        PRD: "an optional `loyalty_tier` of `VISITOR`, `MEMBER` or `PATRON`
        defaulting to `VISITOR`"
        PRD: "Every identifier in the request path resolves to a stored row,
        validated left to right."

        Design: Corner/endpoints/guest_account_crud_patches_only_the_fields_it_is_given
        """
        self._world()
        guest = fx.create_guest(email="mina@example.com",
                               display_name="Mina Ortega")
        promoted = validate_success(
            api_client.patch_guest(guest["id"], {"loyalty_tier": "PATRON"}, AGENT)
        )

        validate_error(
            api_client.patch_guest(guest["id"], {"loyalty_tier": "GOLD"}, AGENT),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )
        assert_row_inert(promoted, fx.read_guest(guest["id"]))

        validate_error(
            api_client.patch_guest(
                UNKNOWN_UUID, {"loyalty_tier": "MEMBER"}, AGENT
            ),
            ApiErrorId.ERR_GUEST_NOT_FOUND.value,
            404,
        )


class TestEveryBoundarySatisfiedAtOnce:
    """Every rung met at its exact edge, so a strict comparison shows up as a 4xx."""

    def test_a_request_sitting_on_every_edge_at_once_is_accepted(self):
        """The lease starts today, the window fills the run and the party fills the group.

        PRD: "activation is admissible only when the logical clock's calendar
        date is on or after `lease_start_date`, and an early attempt is refused
        with `ERR_LEASE_START_NOT_REACHED`."
        PRD: "`base_capacity` must be at least 1 and may not exceed the run's
        `effective_capacity`, nor a non-zero `effective_capacity_cap`; a
        violation is refused with `ERR_SLOT_CAPACITY_ABOVE_RUN`."

        Design: Corner/validations/a_request_sitting_on_every_boundary_at_once_is_accepted
        """
        bundle = fx.run_with_room()
        assert bundle["run"]["effective_capacity"] == 120

        leased = validate_success(
            api_client.activate_lease(bundle["venue"]["id"], VOM)
        )
        assert leased["status"] == "LEASE_ACTIVE"

        slot = validate_object(
            api_client.create_slot(
                f.slot_payload(
                    bundle["run"]["id"], "2026-10-31T23:00:00Z",
                    "2026-10-31T23:45:00Z", base_capacity=120,
                    wheelchair_positions=4,
                ),
                PRODUCER,
            ),
            201,
        )
        assert slot["base_capacity"] == 120

        released = validate_success(api_client.release_slot(slot["id"], PRODUCER))
        assert_slot_ledger(released, 120, 0, 0, 120)

        guest = validate_object(
            api_client.create_guest(
                f.guest_payload(email="a@b.c", display_name="A",
                                loyalty_tier="PATRON"),
                AGENT,
            ),
            201,
        )
        assert guest["email"] == "a@b.c"
        assert guest["display_name"] == "A"

        order = validate_object(
            api_client.create_order(
                f.order_payload(
                    slot["id"], guest["id"], party_size=12, order_type="GROUP",
                    wheelchair_party_count=4, merch_amount_cents=500000,
                ),
                AGENT,
            ),
            201,
        )
        assert order["party_size"] == 12
        assert order["wheelchair_party_count"] == 4
        assert order["merch_amount_cents"] == 500000
        assert_slot_ledger(fx.read_slot(slot["id"]), 120, 12, 0, 108)
