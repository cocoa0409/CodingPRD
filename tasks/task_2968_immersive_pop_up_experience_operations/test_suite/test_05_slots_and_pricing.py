"""Putting windows on sale: half-open geometry, the seat ledger and dynamic pricing."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_row_inert,
    assert_slot,
    assert_slot_ledger,
    assert_slot_ledger_conserved,
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
LM = fx.LM
PRODUCER = fx.PRODUCER
OFFICER = fx.OFFICER
AGENT = fx.AGENT


def _three_room_run():
    """A run whose slowest room pins effective_capacity at 56."""
    bundle = fx.run_with_room()
    run_id = bundle["run"]["id"]
    fx.add_room(
        run_id, 2, name="Signal Room", room_occupancy_cap=30,
        target_dwell_minutes=12, min_dwell_minutes=4, sensory_intensity_level=3,
    )
    fx.add_room(
        run_id, 3, name="Atrium Finale", room_occupancy_cap=25,
        target_dwell_minutes=20, min_dwell_minutes=8, sensory_intensity_level=5,
    )
    bundle["run"] = fx.read_run(run_id)
    return bundle


class TestAggregateAdmissionLoad:
    """Overlap is not the failure condition; the combined seat count is."""

    def test_two_overlapping_windows_are_legal_while_their_seats_fit(self):
        """Sixty seats over a 56-seat run is refused; exactly 56 is admitted.

        PRD: "strict on both sides, so adjacency does not overlap. The admission
        load is the new `base_capacity` plus the sum of `base_capacity` over
        every overlapping peer, and when that load exceeds the run's
        `effective_capacity` the request is refused with
        `ERR_SLOT_OVERLAP_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/slot_half_open_aggregate_admission_load_on_one_run
        """
        bundle = _three_room_run()
        run_id = bundle["run"]["id"]
        assert bundle["run"]["effective_capacity"] == 56
        rooms, _ = validate_paginated(
            api_client.list_rooms(PRODUCER, {"run_id": run_id})
        )
        assert [room["throughput_per_slot"] for room in rooms] == [120, 112, 56]

        first = fx.draft_slot(
            run_id, slot_start_utc="2026-09-05T12:00:00Z",
            slot_end_utc="2026-09-05T12:45:00Z", base_capacity=30,
        )
        assert first["status"] == "DRAFT"

        validate_error(
            api_client.create_slot(
                f.slot_payload(
                    run_id, "2026-09-05T12:30:00Z", "2026-09-05T13:15:00Z",
                    base_capacity=30,
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_SLOT_OVERLAP_CAPACITY.value,
            409,
        )
        second = validate_object(
            api_client.create_slot(
                f.slot_payload(
                    run_id, "2026-09-05T12:30:00Z", "2026-09-05T13:15:00Z",
                    base_capacity=26,
                ),
                PRODUCER,
            ),
            201,
        )
        assert_slot(second)
        assert second["status"] == "DRAFT"
        assert_slot_ledger(second, 0, 0, 0, 0)
        assert second["released_at"] is None
        assert_total_count(api_client.list_slots(PRODUCER, {"run_id": run_id}), 2)
        assert_row_inert(first, fx.read_slot(first["id"]))

    def test_adjacency_is_free_but_one_seat_over_the_sum_is_not(self):
        """A window starting at another's end instant carries its own load alone.

        PRD: "`slot_start_utc` is inclusive, `slot_end_utc` is exclusive, and a
        following window may legitimately start at exactly the instant an earlier
        one ends."
        PRD: "The peers considered are the other slots of the same run with
        status `DRAFT`, `OPEN`, `SOLD_OUT`, `HELD_FOR_BUYOUT` or `SUSPENDED`".

        Design: Difficulty/resource_temporal_overlap/slot_half_open_aggregate_admission_load_on_one_run
        """
        bundle = _three_room_run()
        run_id = bundle["run"]["id"]
        first = fx.draft_slot(
            run_id, slot_start_utc="2026-09-05T12:00:00Z",
            slot_end_utc="2026-09-05T12:45:00Z", base_capacity=30,
        )
        second = fx.draft_slot(
            run_id, slot_start_utc="2026-09-05T12:30:00Z",
            slot_end_utc="2026-09-05T13:15:00Z", base_capacity=26,
        )

        # 13:15 is the instant the second window ends, so nothing overlaps and
        # the whole 56-seat capacity is available to this window alone.
        third = validate_object(
            api_client.create_slot(
                f.slot_payload(
                    run_id, "2026-09-05T13:15:00Z", "2026-09-05T14:00:00Z",
                    base_capacity=56,
                ),
                PRODUCER,
            ),
            201,
        )
        assert third["status"] == "DRAFT"

        validate_error(
            api_client.create_slot(
                f.slot_payload(
                    run_id, "2026-09-05T13:20:00Z", "2026-09-05T14:05:00Z",
                    base_capacity=1, wheelchair_positions=0,
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_SLOT_OVERLAP_CAPACITY.value,
            409,
        )
        rows, meta = validate_paginated(
            api_client.list_slots(PRODUCER, {"run_id": run_id})
        )
        assert meta["total_count"] == 3
        assert {row["id"] for row in rows} == {
            first["id"], second["id"], third["id"]
        }
        assert all(row["released_at"] is None for row in rows)


class TestSlotCancelPriority:
    """The state rung answers first, and the sales ceiling waits its turn."""

    @staticmethod
    def _suspended_slot_with_a_hold():
        bundle = fx.run_with_room(lease_active=True)
        run_id = bundle["run"]["id"]
        slot = fx.open_slot(run_id, base_capacity=40, wheelchair_positions=4)
        guest = fx.create_guest(email="finn@example.com", display_name="Finn Ito")
        order = fx.place_order(slot["id"], guest["id"], party_size=4)
        bundle["slot"] = fx.read_slot(slot["id"])
        bundle["order"] = order
        bundle["guest"] = guest
        return bundle

    def test_the_state_gate_reports_before_the_sales_ceiling(self):
        """One body violates both rules, and the byte-identical retry exposes the second.

        PRD: "A request that violates both a segregation-of-duties rule and a
        lease-budget rule reports the segregation-of-duties error, because
        identity sits above money on the ladder."
        PRD: "The resource named in the path is in a state from which the
        requested transition is declared."
        PRD: "`CANCEL` moves a `DRAFT` or `OPEN` slot to the terminal
        `CANCELLED`, zeroing `released_capacity` and `available_capacity`, and is
        refused with `ERR_SLOT_HAS_SALES` when either `sold_capacity` or
        `held_capacity` is above 0".

        Design: Difficulty/priority_pair_validation_conflict/slot_cancel_state_gate_masks_the_slot_has_sales_ceiling
        """
        bundle = self._suspended_slot_with_a_hold()
        slot_id = bundle["slot"]["id"]
        assert_slot_ledger(bundle["slot"], 40, 4, 0, 36)

        suspended = validate_success(
            api_client.decide_slot_status(
                slot_id,
                f.slot_status_decision_payload("SUSPEND", note="signage rework"),
                PRODUCER,
            )
        )
        assert suspended["status"] == "SUSPENDED"
        assert_slot_ledger(suspended, 40, 4, 0, 36)

        cancel = f.slot_status_decision_payload("CANCEL", note="pull the window")
        validate_error(
            api_client.decide_slot_status(slot_id, cancel, PRODUCER),
            ApiErrorId.ERR_SLOT_INVALID_STATE.value,
            409,
        )
        assert_row_inert(suspended, fx.read_slot(slot_id))

        resumed = validate_success(
            api_client.decide_slot_status(
                slot_id,
                f.slot_status_decision_payload("RESUME", note="signage done"),
                PRODUCER,
            )
        )
        assert resumed["status"] == "OPEN"

        # The same body, and now the masked business rule answers.
        validate_error(
            api_client.decide_slot_status(slot_id, cancel, PRODUCER),
            ApiErrorId.ERR_SLOT_HAS_SALES.value,
            409,
        )
        still_open = fx.read_slot(slot_id)
        assert still_open["status"] == "OPEN"
        assert still_open["held_capacity"] == 4

    def test_releasing_the_hold_finally_lets_the_window_be_pulled(self):
        """Once the seats come back the cancel is accepted and zeroes the ledger.

        PRD: "`CANCEL` moves a `DRAFT` or `OPEN` slot to the terminal
        `CANCELLED`, zeroing `released_capacity` and `available_capacity`, and is
        refused with `ERR_SLOT_HAS_SALES` when either `sold_capacity` or
        `held_capacity` is above 0 — a window carrying money cannot simply be
        deleted."

        Design: Difficulty/priority_pair_validation_conflict/slot_cancel_state_gate_masks_the_slot_has_sales_ceiling
        """
        bundle = self._suspended_slot_with_a_hold()
        slot_id = bundle["slot"]["id"]
        cancel = f.slot_status_decision_payload("CANCEL", note="pull the window")

        validate_error(
            api_client.decide_slot_status(slot_id, cancel, PRODUCER),
            ApiErrorId.ERR_SLOT_HAS_SALES.value,
            409,
        )

        released = validate_success(
            api_client.cancel_order(
                bundle["order"]["id"], f.cancel_payload("window pulled"), AGENT
            )
        )
        assert released["status"] == "CANCELLED"
        freed = fx.read_slot(slot_id)
        assert_slot_ledger(freed, 40, 0, 0, 40)

        pulled = validate_success(
            api_client.decide_slot_status(slot_id, cancel, PRODUCER)
        )
        assert pulled["status"] == "CANCELLED"
        assert pulled["released_capacity"] == 0
        assert pulled["available_capacity"] == 0


class TestBuyoutLedgerConserved:
    """One order moves all 26 seats between the three buckets and back."""

    @staticmethod
    def _world():
        bundle = fx.open_run(
            slot_overrides={"base_capacity": 26, "wheelchair_positions": 2}
        )
        bundle["buyer"] = fx.create_guest(
            email="mira@example.com", display_name="Mira Adeyemi"
        )
        bundle["walk_up"] = fx.create_guest(
            email="noor@example.com", display_name="Noor Haddad"
        )
        return bundle

    def test_the_buyout_takes_the_whole_window_and_gives_it_back(self):
        """Four hops, and the seat identity holds at every one of them.

        PRD: "the slot moves `OPEN → HELD_FOR_BUYOUT`, its `held_capacity`
        becomes the whole `released_capacity`, its `available_capacity` becomes
        0, and `buyout_order_id` records the holding order."
        PRD: "Cancelling it instead moves the slot `HELD_FOR_BUYOUT → OPEN`,
        returns `held_capacity` to 0, restores `available_capacity` to
        `released_capacity` less `sold_capacity`, and clears `buyout_order_id`."

        Design: Difficulty/compensating_invariant/slot_capacity_ledger_conserved_across_a_buyout_hold_and_release
        """
        bundle = self._world()
        slot_id = bundle["slot"]["id"]
        assert_slot_ledger(bundle["slot"], 26, 0, 0, 26)
        assert bundle["slot"]["wheelchair_sold"] == 0

        order = validate_object(
            api_client.create_order(
                f.order_payload(
                    slot_id, bundle["buyer"]["id"], party_size=26,
                    order_type="PRIVATE_BUYOUT",
                ),
                AGENT,
            ),
            201,
        )
        assert order["per_guest_after_loyalty_cents"] == 32250
        # 32250 * 26 * 1.25 is exactly 1048125 cents, with no group discount.
        assert order["gross_amount_cents"] == 1048125
        assert order["group_discount_cents"] == 0
        assert order["companion_waiver_cents"] == 0
        assert order["net_amount_cents"] == 1048125

        held = fx.read_slot(slot_id)
        assert held["status"] == "HELD_FOR_BUYOUT"
        assert held["buyout_order_id"] == order["id"]
        assert_slot_ledger(held, 26, 26, 0, 0)

        validate_success(api_client.confirm_order(order["id"], AGENT))
        sold = fx.read_slot(slot_id)
        assert sold["status"] == "SOLD_OUT"
        assert_slot_ledger(sold, 26, 0, 26, 0)
        assert fx.read_order(order["id"])["net_collected_cents"] == 1048125

        fx.set_clock("2026-09-01T14:00:00Z")
        cancelled = validate_success(
            api_client.cancel_order(
                order["id"], f.cancel_payload("corporate client withdrew"), AGENT
            )
        )
        assert cancelled["status"] == "REFUND_DUE"
        assert cancelled["refund_pct"] == 1.00
        assert cancelled["refunded_cents"] == 1048125

        reopened = fx.read_slot(slot_id)
        assert reopened["status"] == "OPEN"
        assert reopened["buyout_order_id"] is None
        assert_slot_ledger(reopened, 26, 0, 0, 26)
        assert reopened["wheelchair_sold"] == 0

    def test_the_returned_seats_are_genuinely_resellable(self):
        """A later order prices on its own clock position and moves the same ledger.

        PRD: "After release the conserved slot identity of §2.5 holds:
        `released_capacity` always equals `held_capacity` plus `sold_capacity`
        plus `available_capacity`."
        PRD: "Because it is frozen at creation, moving the clock afterwards can
        never reprice an existing order."

        Design: Difficulty/compensating_invariant/slot_capacity_ledger_conserved_across_a_buyout_hold_and_release
        """
        bundle = self._world()
        slot_id = bundle["slot"]["id"]
        buyout = fx.place_order(
            slot_id, bundle["buyer"]["id"], party_size=26,
            order_type="PRIVATE_BUYOUT",
        )
        validate_success(api_client.confirm_order(buyout["id"], AGENT))
        fx.set_clock("2026-09-01T14:00:00Z")
        validate_success(
            api_client.cancel_order(
                buyout["id"], f.cancel_payload("corporate client withdrew"), AGENT
            )
        )
        assert_slot_ledger_conserved(fx.read_slot(slot_id))

        walk_up = validate_object(
            api_client.create_order(
                f.order_payload(slot_id, bundle["walk_up"]["id"], party_size=4),
                AGENT,
            ),
            201,
        )
        # Four days out, so the late multiplier prices this order, not the 0.90
        # band the buyout was frozen at.
        assert walk_up["unit_price_cents"] == 41208
        assert walk_up["net_amount_cents"] == 164832
        held = fx.read_slot(slot_id)
        assert_slot_ledger(held, 26, 4, 0, 22)

        validate_success(api_client.confirm_order(walk_up["id"], AGENT))
        settled = fx.read_slot(slot_id)
        assert settled["status"] == "OPEN"
        assert_slot_ledger(settled, 26, 0, 4, 22)
        assert settled["wheelchair_sold"] == 0
        assert fx.read_order(buyout["id"])["unit_price_cents"] == 32250


class TestReleaseWritesTheLedger:
    """Release is the only call that turns a design figure into a live ledger."""

    def test_release_writes_four_counters_and_the_release_instant(self):
        """The status flip is not the whole side effect.

        PRD: "Releasing a slot moves it `DRAFT → OPEN`, sets both
        `released_capacity` and `available_capacity` to `base_capacity` and
        stamps `released_at` from the clock."

        Design: Corner/state_machines/slot_release_writes_the_capacity_ledger_it_declares
        """
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        run_before = fx.read_run(run_id)
        slot = fx.draft_slot(
            run_id, pricing_tier="PEAK", base_capacity=26, wheelchair_positions=3
        )

        fx.set_clock("2026-08-04T11:30:00Z")
        released = validate_success(api_client.release_slot(slot["id"], PRODUCER))
        assert released["status"] == "OPEN"
        assert_slot_ledger(released, 26, 0, 0, 26)
        assert released["wheelchair_sold"] == 0
        assert_instant_equals(released["released_at"], "2026-08-04T11:30:00Z")
        assert released["base_capacity"] == 26
        assert released["wheelchair_positions"] == 3
        assert released["version"] == 2

        # A release has no upward side effect on the run that owns the window.
        assert_row_inert(run_before, fx.read_run(run_id))


class TestPriceMatrix:
    """Four tiers crossed with three lead bands, read without writing a row."""

    def test_the_twelve_cells_of_the_matrix_agree_with_the_declared_multipliers(self):
        """Every cell is one product rounded once, and the quote reports its lead days.

        PRD: "Booking 30 or more days ahead earns the early multiplier 0.90; from
        7 up to 29 days the multiplier is 1.00; closer in than 7 days the late
        multiplier is 1.15. The tier multiplier is 0.80 for `OFFPEAK`, 1.00 for
        `STANDARD`, 1.30 for `PEAK` and 1.60 for `PREMIUM`."
        PRD: "A read-only quote on a slot returns `slot_id`, the slot's
        `pricing_tier`, the computed `lead_days`, the `unit_price_cents`".

        Design: Corner/calculations/price_quote_walks_the_tier_matrix_across_the_three_lead_bands
        """
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        slots = {
            tier: fx.draft_slot(run_id, pricing_tier=tier, base_capacity=20)
            for tier in ("OFFPEAK", "STANDARD", "PEAK", "PREMIUM")
        }

        bands = [
            (None, 35, {"OFFPEAK": 25800, "STANDARD": 32250,
                        "PEAK": 41925, "PREMIUM": 51600}),
            ("2026-08-26T00:00:00Z", 10, {"OFFPEAK": 28666, "STANDARD": 35833,
                                          "PEAK": 46583, "PREMIUM": 57333}),
            ("2026-09-03T00:00:00Z", 2, {"OFFPEAK": 32966, "STANDARD": 41208,
                                         "PEAK": 53570, "PREMIUM": 65933}),
        ]
        for clock, lead_days, expected in bands:
            if clock is not None:
                fx.set_clock(clock)
            for tier, unit in expected.items():
                quote = validate_success(
                    api_client.get_price_quote(
                        slots[tier]["id"],
                        f.price_quote_params(party_size=1),
                        AGENT,
                    )
                )
                assert quote["slot_id"] == slots[tier]["id"]
                assert quote["pricing_tier"] == tier
                assert quote["lead_days"] == lead_days
                assert quote["unit_price_cents"] == unit
                assert quote["per_guest_after_loyalty_cents"] == unit
                assert quote["net_amount_cents"] == unit

        for tier, slot in slots.items():
            assert_row_inert(slot, fx.read_slot(slot["id"]))
        assert_total_count(api_client.list_orders(AGENT), 0)

    def test_the_two_band_edges_are_each_one_second_wide(self):
        """Thirty days still earns the early band; one second later it does not.

        PRD: "Lead time is measured from the current logical clock instant to
        `slot_start_utc` in seconds and floored to whole days."

        Design: Corner/calculations/lead_band_edges_land_at_exactly_thirty_and_seven_days
        """
        bundle = fx.run_with_room()
        slot = fx.draft_slot(bundle["run"]["id"], base_capacity=20)

        edges = [
            ("2026-08-06T14:00:00Z", 30, 32250),
            ("2026-08-06T14:00:01Z", 29, 35833),
            ("2026-08-29T14:00:00Z", 7, 35833),
            ("2026-08-29T14:00:01Z", 6, 41208),
            ("2026-09-05T14:00:00Z", 0, 41208),
        ]
        for clock, lead_days, unit in edges:
            fx.set_clock(clock)
            quote = validate_success(
                api_client.get_price_quote(
                    slot["id"], f.price_quote_params(party_size=1), PRODUCER
                )
            )
            assert quote["lead_days"] == lead_days
            assert quote["unit_price_cents"] == unit
        assert_row_inert(slot, fx.read_slot(slot["id"]))

    def test_the_product_rounds_once_and_the_clamps_bite_afterwards(self):
        """A one-cent fingerprint, and both ends of the declared price range.

        PRD: "the run's `base_ticket_price_cents` is multiplied by the tier
        multiplier and the lead multiplier in one single product, and that
        product is rounded half up to whole cents exactly"
        PRD: "The rounded figure is then clamped into the range 1000 to 100000
        cents inclusive, and becomes the order's `unit_price_cents`."

        Design: Corner/calculations/prices_round_once_and_clamp_at_the_declared_floor_and_ceiling
        """
        bundle = fx.run_with_room()
        venue_id = bundle["venue"]["id"]
        agreement_id = bundle["agreement"]["id"]
        ordinary = fx.draft_slot(
            bundle["run"]["id"], pricing_tier="OFFPEAK", base_capacity=20
        )

        cheap_run = validate_object(
            api_client.create_run(
                f.run_payload(
                    venue_id, agreement_id, fx.create_kit(module_count=12)["id"],
                    run_name="Neon Atrium Community Preview",
                    base_ticket_price_cents=900,
                ),
                PRODUCER,
            ),
            201,
        )
        fx.add_room(cheap_run["id"], 1, name="Preview Vestibule")
        cheap_slot = fx.draft_slot(
            cheap_run["id"], pricing_tier="OFFPEAK", base_capacity=20
        )

        dear_run = validate_object(
            api_client.create_run(
                f.run_payload(
                    venue_id, agreement_id, fx.create_kit(module_count=12)["id"],
                    run_name="Neon Atrium Patron Nights",
                    base_ticket_price_cents=88000,
                ),
                PRODUCER,
            ),
            201,
        )
        fx.add_room(dear_run["id"], 1, name="Patron Vestibule")
        dear_slot = fx.draft_slot(
            dear_run["id"], pricing_tier="PREMIUM", base_capacity=20
        )

        # 35833 * 0.8 * 0.9 is 25799.76; the forbidden intermediate round gives
        # 25799, one cent lower.
        single = validate_success(
            api_client.get_price_quote(
                ordinary["id"], f.price_quote_params(party_size=1), PRODUCER
            )
        )
        assert single["unit_price_cents"] == 25800

        floored = validate_success(
            api_client.get_price_quote(
                cheap_slot["id"], f.price_quote_params(party_size=1), PRODUCER
            )
        )
        assert floored["unit_price_cents"] == 1000
        assert floored["per_guest_after_loyalty_cents"] == 1000
        assert floored["net_amount_cents"] == 1000

        capped = validate_success(
            api_client.get_price_quote(
                dear_slot["id"],
                f.price_quote_params(loyalty_tier="PATRON", party_size=2),
                PRODUCER,
            )
        )
        assert capped["unit_price_cents"] == 100000
        assert capped["per_guest_after_loyalty_cents"] == 88000
        assert capped["net_amount_cents"] == 176000

    def test_the_quote_follows_the_clock_while_the_order_stays_frozen(self):
        """The same breakdown the order will store, and nothing is written.

        PRD: "The quote persists nothing and advances no version."
        PRD: "`companion_waiver_cents` is the per-guest figure multiplied by the
        smaller of `wheelchair_party_count` and 1, so exactly one companion
        travels free however many chairs are in the party."

        Design: Corner/endpoints/price_quote_previews_the_order_total_and_persists_nothing
        """
        bundle = fx.run_with_room()
        slot = fx.open_slot(
            bundle["run"]["id"], slot_start_utc="2026-09-15T14:00:00Z",
            slot_end_utc="2026-09-15T14:45:00Z", pricing_tier="PEAK",
            base_capacity=20, wheelchair_positions=2,
        )
        guest = fx.create_guest(
            email="mina@example.com", display_name="Mina Ortega",
            loyalty_tier="PATRON",
        )
        shape = f.price_quote_params(
            order_type="GROUP", loyalty_tier="PATRON", party_size=6,
            wheelchair_party_count=1,
        )
        expected = {
            "unit_price_cents": 41925,
            "per_guest_after_loyalty_cents": 36894,
            "gross_amount_cents": 221364,
            "group_discount_cents": 11068,
            "companion_waiver_cents": 36894,
            "discount_cents": 47962,
            "net_amount_cents": 173402,
        }

        quote = validate_success(
            api_client.get_price_quote(slot["id"], shape, AGENT)
        )
        assert quote["lead_days"] == 45
        for field, value in expected.items():
            assert quote[field] == value
        as_guest = validate_success(
            api_client.get_price_quote(
                slot["id"], shape, make_guest_headers(guest["id"])
            )
        )
        assert {k: as_guest[k] for k in expected} == expected

        order = validate_object(
            api_client.create_order(
                f.order_payload(
                    slot["id"], guest["id"], party_size=6, order_type="GROUP",
                    wheelchair_party_count=1,
                ),
                AGENT,
            ),
            201,
        )
        for field, value in expected.items():
            assert order[field] == value

        fx.set_clock("2026-09-10T00:00:00Z")
        later = validate_success(
            api_client.get_price_quote(slot["id"], shape, AGENT)
        )
        assert later["lead_days"] == 5
        assert later["unit_price_cents"] == 53570
        assert later["per_guest_after_loyalty_cents"] == 47142
        assert later["gross_amount_cents"] == 282852
        assert later["group_discount_cents"] == 14143
        assert later["companion_waiver_cents"] == 47142
        assert later["discount_cents"] == 61285
        assert later["net_amount_cents"] == 221567

        frozen = fx.read_order(order["id"])
        assert frozen["unit_price_cents"] == 41925
        assert frozen["net_amount_cents"] == 173402
        assert_total_count(api_client.list_orders(AGENT, {"slot_id": slot["id"]}), 1)

        after = fx.read_slot(slot["id"])
        assert_slot_ledger(after, 20, 6, 0, 14)
        assert after["wheelchair_sold"] == 0
        assert after["version"] == slot["version"] + 1


class TestIntervalAndCalendarBounds:
    """One rung, three error identifiers and three asymmetric containment bounds."""

    def test_inverted_intervals_and_out_of_span_windows_are_each_refused(self):
        """The closing day is sellable to 23:59:59.999 and the next day is not.

        PRD: "any empty or inverted interval earns `ERR_INVALID_WINDOW` (422). An
        admission window that does not lie wholly inside its run's admission
        span, or a run whose `scheduled_close_date` falls after its venue's
        `lease_end_date` at creation, earns `ERR_SLOT_OUTSIDE_RUN_WINDOW` (422)."
        PRD: "the whole window must lie inside the run's scheduled dates — on or
        after midnight at the start of `scheduled_open_date` and on or before
        23:59:59.999 of `scheduled_close_date`".

        Design: Corner/validations/interval_and_window_bounds_are_rejected_across_five_endpoints
        """
        bundle = fx.run_with_room()
        run_id = bundle["run"]["id"]
        venue_id = bundle["venue"]["id"]
        agreement_id = bundle["agreement"]["id"]

        validate_error(
            api_client.create_venue(
                f.venue_payload(
                    city_code="CHI", site_name="Fulton Annex",
                    lease_start_date="2026-09-01", lease_end_date="2026-09-01",
                    base_monthly_rent_cents=3000000,
                    buildout_allowance_cents=500000, buildout_cap_cents=900000,
                    requested_occupancy_load=120, egress_width_cm=300,
                ),
                VOM,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            422,
        )
        validate_error(
            api_client.create_agreement(
                f.agreement_payload(
                    ip_title="Neon Atrium II", term_start_date="2026-10-01",
                    term_end_date="2026-09-30",
                ),
                LM,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            422,
        )

        # Each probe needs its own READY kit, because a kit already deployed to
        # a run is refused on an earlier rung than the calendar checks.
        validate_error(
            api_client.create_run(
                f.run_payload(
                    venue_id, agreement_id, fx.create_kit()["id"],
                    run_name="Backwards window",
                    scheduled_open_date="2026-10-31",
                    scheduled_close_date="2026-08-10",
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            422,
        )
        validate_error(
            api_client.create_run(
                f.run_payload(
                    venue_id, agreement_id, fx.create_kit()["id"],
                    run_name="Past the lease",
                    scheduled_close_date="2027-02-01",
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_SLOT_OUTSIDE_RUN_WINDOW.value,
            422,
        )

        validate_error(
            api_client.create_slot(
                f.slot_payload(
                    run_id, "2026-08-11T14:45:00Z", "2026-08-11T14:00:00Z"
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            422,
        )
        validate_error(
            api_client.create_slot(
                f.slot_payload(
                    run_id, "2026-08-09T23:00:00Z", "2026-08-09T23:45:00Z"
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_SLOT_OUTSIDE_RUN_WINDOW.value,
            422,
        )
        last_evening = validate_object(
            api_client.create_slot(
                f.slot_payload(
                    run_id, "2026-10-31T23:00:00Z", "2026-10-31T23:45:00Z"
                ),
                PRODUCER,
            ),
            201,
        )
        assert last_evening["status"] == "DRAFT"
        validate_error(
            api_client.create_slot(
                f.slot_payload(
                    run_id, "2026-11-01T10:00:00Z", "2026-11-01T10:45:00Z"
                ),
                PRODUCER,
            ),
            ApiErrorId.ERR_SLOT_OUTSIDE_RUN_WINDOW.value,
            422,
        )

        run_version = fx.run_version(run_id)
        validate_error(
            api_client.create_statement(
                f.statement_payload(
                    run_id, run_version, period_start_date="2026-08-31",
                    period_end_date="2026-08-01",
                ),
                LM,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            422,
        )
        validate_error(
            api_client.create_statement(
                f.statement_payload(
                    run_id, run_version, period_start_date="2026-07-31",
                    period_end_date="2026-08-31",
                ),
                LM,
            ),
            ApiErrorId.ERR_PERIOD_OUTSIDE_TERM.value,
            422,
        )
        whole_term = validate_object(
            api_client.create_statement(
                f.statement_payload(
                    run_id, run_version, period_start_date="2026-08-01",
                    period_end_date="2026-12-31",
                ),
                LM,
            ),
            201,
        )
        assert whole_term["status"] == "DRAFT"
