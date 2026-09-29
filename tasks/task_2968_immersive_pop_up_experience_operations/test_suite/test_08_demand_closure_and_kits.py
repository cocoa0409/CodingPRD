"""Demand buys the last days, and the close strikes the kit that tours on."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_extension_days_conserved,
    assert_kit,
    assert_order,
    assert_row_inert,
    assert_run,
    assert_slot,
    assert_slot_ledger,
    assert_staff_member,
    assert_total_count,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_object,
    validate_success,
)

PRODUCER = fx.PRODUCER
PRODUCER_OTHER = fx.PRODUCER_OTHER
AGENT = fx.AGENT
VOM = fx.VOM


class TestTheExtensionFloorTurnsOnOneSeat:
    """Twenty-seven seats of forty miss the floor; the twenty-eighth lands on it."""

    @staticmethod
    def _world():
        """An open run with forty released seats, twenty-seven of them sold.

        Twenty-seven of forty is 67.50 per cent and no order has been refunded,
        so the index is 67.50 - half of nothing.  A fourth party of one is left
        `PENDING` on the window, holding a seat that utilisation does not see.
        """
        bundle = fx.run_at_demand(utilisation_seats=40, sold_seats=27, option_days=30)
        bundle["pending"] = fx.place_order(
            bundle["slot"]["id"], bundle["guest"]["id"],
            order_type="SINGLE", party_size=1,
        )
        bundle["slot"] = fx.read_slot(bundle["slot"]["id"])
        return bundle

    def test_a_held_seat_does_not_buy_a_day(self):
        """67.50 is under the floor, and the held seat cannot lift it.

        PRD: "Utilisation is 100 multiplied by the sum of `sold_capacity` over
        those windows divided by the sum of `released_capacity` over them,
        rounded half up to two decimals, and is 0.00 when nothing has been
        released at all rather than an error."
        PRD: "The gate is inclusive: an index of at least 70.00 permits an
        extension and exactly 70.00 passes, while anything lower is refused with
        `ERR_DEMAND_BELOW_THRESHOLD`."
        PRD: "Note that `demand_index` is written only on a successful
        extension; the read-only telemetry view computes the same figure and
        stores nothing."

        Design: Difficulty/boundary_precision_check/demand_index_extension_floor_at_exactly_seventy
        """
        world = self._world()
        run_id = world["run"]["id"]
        assert_slot_ledger(world["slot"], 40, 1, 27, 12)
        assert world["slot"]["status"] == "OPEN"

        before_run = fx.read_run(run_id)
        before_venue = fx.read_venue(world["venue"]["id"])
        validate_error(
            api_client.grant_extension(
                run_id, f.extension_payload(14), PRODUCER_OTHER
            ),
            ApiErrorId.ERR_DEMAND_BELOW_THRESHOLD.value,
            409,
        )

        run = fx.read_run(run_id)
        assert_run(run)
        assert run["run_status"] == "OPEN"
        assert run["clearance_status"] == "CLEARED"
        assert run["extension_days_granted"] == 0
        assert run["scheduled_close_date"] == "2026-10-31"
        assert run["demand_index"] == 0.00
        assert run["demand_index_at_extension"] is None
        assert_row_inert(before_run, run)

        venue = fx.read_venue(world["venue"]["id"])
        assert venue["lease_extension_days_consumed"] == 0
        assert venue["lease_extension_option_days"] == 30
        assert_row_inert(before_venue, venue)
        assert_extension_days_conserved(venue, [run])

    def test_the_seat_that_moves_from_held_to_sold_buys_the_days(self):
        """Confirming the fourth party puts the index on 70.00 exactly, and it passes.

        PRD: "On success the order moves `PENDING → CONFIRMED`,
        `net_collected_cents` becomes `net_amount_cents`, the seats move from
        `held_capacity` into `sold_capacity`, `wheelchair_sold` rises by
        `wheelchair_party_count`, `available_capacity` is recomputed as
        `released_capacity` less `held_capacity` less `sold_capacity`, and the
        slot moves to `SOLD_OUT` when that leaves nothing available."
        PRD: "The gate is inclusive: an index of at least 70.00 permits an
        extension and exactly 70.00 passes, while anything lower is refused with
        `ERR_DEMAND_BELOW_THRESHOLD`."
        PRD: "On success the freshly computed figure is stored as `demand_index`
        and also copied into `demand_index_at_extension`, `scheduled_close_date`
        advances by that many calendar days, `extension_days_granted` rises by
        the same number, the venue's `lease_extension_days_consumed` rises too —
        taking a version increment on the venue — and the run moves
        `OPEN → EXTENDED`, or `EXTENDED → EXTENDED` on each further round."
        PRD: "On a venue, `lease_extension_days_consumed` always equals the sum
        of `extension_days_granted` across every run at that venue."

        Design: Difficulty/boundary_precision_check/demand_index_extension_floor_at_exactly_seventy
        """
        world = self._world()
        run_id = world["run"]["id"]
        venue_id = world["venue"]["id"]
        run_version_before = fx.read_run(run_id)["version"]
        venue_version_before = fx.read_venue(venue_id)["version"]

        validate_success(api_client.confirm_order(world["pending"]["id"], AGENT))
        slot = fx.read_slot(world["slot"]["id"])
        assert_slot(slot)
        assert_slot_ledger(slot, 40, 0, 28, 12)
        assert slot["status"] == "OPEN"

        run = validate_success(
            api_client.grant_extension(
                run_id, f.extension_payload(14), PRODUCER_OTHER
            )
        )
        assert_run(run)
        assert run["run_status"] == "EXTENDED"
        assert run["demand_index"] == 70.00
        assert run["demand_index_at_extension"] == 70.00
        assert run["extension_days_granted"] == 14
        assert run["scheduled_close_date"] == "2026-11-14"
        assert run["scheduled_open_date"] == "2026-08-10"
        assert run["version"] > run_version_before

        venue = fx.read_venue(venue_id)
        assert venue["lease_extension_days_consumed"] == 14
        assert venue["version"] > venue_version_before
        assert_extension_days_conserved(venue, [fx.read_run(run_id)])


class TestSegregationOfDutiesOutranksTheDemandFloor:
    """One body, two live objections, and identity is the one that answers."""

    @staticmethod
    def _world():
        """An open run with forty seats released and not one of them sold.

        Nothing has sold, so utilisation is 0.00 and no order is counted, which
        puts the index on 0.00 - seventy points under the floor.  The extension
        is therefore refusable on demand grounds as well as on identity grounds,
        and the run was created by the first producer.
        """
        bundle = fx.open_run(
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 0},
            venue_overrides={"lease_extension_option_days": 30},
        )
        assert bundle["run"]["created_by_user_id"] == "producer-1"
        return bundle

    def test_the_creator_is_told_about_himself_not_about_demand(self):
        """The producer who created the run is refused on identity, not on demand.

        PRD: "A request that violates both a segregation-of-duties rule and a
        lease-budget rule reports the segregation-of-duties error, because
        identity sits above money on the ladder."
        PRD: "On success `created_by_user_id` is copied from the creating
        `X-User-ID` — the identity that segregation of duties will later bar from
        granting this run's extension — and the deployed kit moves
        `READY → DEPLOYED`, taking its own version increment."
        PRD: "The producer granting it must not be the producer who created the
        run: when the granting `X-User-ID` equals the run's `created_by_user_id`
        the request is refused with `ERR_SOD_EXTENSION_SAME_USER`."

        Design: Difficulty/priority_pair_validation_conflict/extension_segregation_of_duties_masks_the_demand_floor
        """
        world = self._world()
        run_id = world["run"]["id"]
        assert_slot_ledger(world["slot"], 40, 0, 0, 40)

        before_run = fx.read_run(run_id)
        before_venue = fx.read_venue(world["venue"]["id"])
        validate_error(
            api_client.grant_extension(run_id, f.extension_payload(14), PRODUCER),
            ApiErrorId.ERR_SOD_EXTENSION_SAME_USER.value,
            403,
        )

        run = fx.read_run(run_id)
        assert_run(run)
        assert run["run_status"] == "OPEN"
        assert run["extension_days_granted"] == 0
        assert run["scheduled_close_date"] == "2026-10-31"
        assert run["demand_index"] == 0.00
        assert run["demand_index_at_extension"] is None
        assert_row_inert(before_run, run)
        assert_row_inert(before_venue, fx.read_venue(world["venue"]["id"]))

    def test_the_same_body_from_the_other_producer_falls_through_to_demand(self):
        """Past the identity rung the weak index is what the caller finally hears.

        PRD: "so that an under-performing run that also lacks lease days reports
        the demand failure"
        PRD: "Utilisation is 100 multiplied by the sum of `sold_capacity` over
        those windows divided by the sum of `released_capacity` over them,
        rounded half up to two decimals, and is 0.00 when nothing has been
        released at all rather than an error."
        PRD: "The gate is inclusive: an index of at least 70.00 permits an
        extension and exactly 70.00 passes, while anything lower is refused with
        `ERR_DEMAND_BELOW_THRESHOLD`."

        Design: Difficulty/priority_pair_validation_conflict/extension_segregation_of_duties_masks_the_demand_floor
        """
        world = self._world()
        run_id = world["run"]["id"]
        venue_id = world["venue"]["id"]
        payload = f.extension_payload(14)

        validate_error(
            api_client.grant_extension(run_id, payload, PRODUCER),
            ApiErrorId.ERR_SOD_EXTENSION_SAME_USER.value,
            403,
        )
        validate_error(
            api_client.grant_extension(run_id, payload, PRODUCER_OTHER),
            ApiErrorId.ERR_DEMAND_BELOW_THRESHOLD.value,
            409,
        )

        run = fx.read_run(run_id)
        assert_run(run)
        assert run["run_status"] == "OPEN"
        assert run["clearance_status"] == "CLEARED"
        assert run["demand_index"] == 0.00
        assert run["extension_days_granted"] == 0
        assert run["scheduled_close_date"] == "2026-10-31"

        venue = fx.read_venue(venue_id)
        assert venue["lease_extension_days_consumed"] == 0
        assert venue["lease_extension_option_days"] == 30
        assert_extension_days_conserved(venue, [run])


class TestTheCloseStrikesTheKitAndSendsItOnTour:
    """One decision decays a kit, retires it from the run and re-prices its next city."""

    @staticmethod
    def _world():
        """An open run whose kit is forty modules starting at 64.00 points.

        Forty modules cost 4.00 plus twelve points of module wear, so the strike
        takes the kit sixteen points down to 48.00 and routes it to the
        refurbishment branch.  The clock is parked on the run's last scheduled
        day so the closure stamps are known instants.
        """
        bundle = fx.open_run(
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 0},
            kit_overrides={"module_count": 40, "initial_condition_score": 64.00},
        )
        assert bundle["kit"]["status"] == "DEPLOYED"
        assert bundle["kit"]["condition_score"] == 64.00
        assert bundle["kit"]["last_city_code"] is None
        fx.set_clock("2026-10-31T18:00:00Z")
        return bundle

    def test_the_close_strikes_the_kit_and_stands_the_roster_down(self):
        """Four hops on the kit and one independent sweep over the people.

        PRD: "A `decision` of `CLOSE` then moves `CLOSING → CLOSED`, and it is
        admissible only when the books are clean: no order of the run may still
        be `CONFIRMED` or `REFUND_DUE`, and no shift of the run may still be
        `SCHEDULED`."
        PRD: "Hop 1 stamps `closed_at` and sets `run_status` to `CLOSED`."
        PRD: "Hop 2, caused by hop 1, strikes the kit: its `condition_score` is
        decayed, its `reuse_cycle_count` rises by 1, and its `last_city_code` is
        set to the closing venue's `city_code`."
        PRD: "The wear is 4.00 as a base charge for the close, plus 0.30 for each
        of the kit's `module_count` modules, plus a further 9.00 when the kit has
        moved city — that is, when `last_city_code` was already set and differs
        from this venue's `city_code`."
        PRD: "The first closure of a brand-new kit never pays the city-move
        charge, because `last_city_code` is still null."
        PRD: "below 60.00 it moves `DEPLOYED → REFURB_REQUIRED`, and at 60.00 or
        above it moves `DEPLOYED → IN_TRANSIT`"
        PRD: "Hop 4 fires only on the refurbishment branch: a kit that needs
        rebuilding also needs re-localising, so its `localization_status` is reset
        to `PENDING` and its `localization_cost_cents` is reset to 0."
        PRD: "Independently of those hops, every staff member of the run in
        `CANDIDATE`, `TRAINING`, `CLEARED` or `SUSPENDED` is moved to `RELEASED`."

        Design: Difficulty/transitive_cascade/close_decision_cascades_into_kit_decay_refurb_and_relocalisation
        """
        world = self._world()
        run_id = world["run"]["id"]

        closing = validate_success(
            api_client.decide_closure(
                run_id, f.closure_decision_payload("START_CLOSING"), PRODUCER
            )
        )
        assert_run(closing)
        assert closing["run_status"] == "CLOSING"
        assert_instant_equals(closing["closing_started_at"], "2026-10-31T18:00:00Z")
        assert closing["closed_at"] is None
        assert fx.read_slot(world["slot"]["id"])["status"] == "CLOSED_OUT"

        run = validate_success(
            api_client.decide_closure(
                run_id, f.closure_decision_payload("CLOSE"), PRODUCER
            )
        )
        assert_run(run)
        assert run["run_status"] == "CLOSED"
        assert_instant_equals(run["closed_at"], "2026-10-31T18:00:00Z")

        kit = fx.read_kit(world["kit"]["id"])
        assert_kit(kit)
        assert kit["condition_score"] == 48.00
        assert kit["reuse_cycle_count"] == 1
        assert kit["refurb_count"] == 0
        assert kit["last_city_code"] == "NYC"
        assert kit["status"] == "REFURB_REQUIRED"
        assert kit["localization_status"] == "PENDING"
        assert kit["localization_cost_cents"] == 0
        assert kit["localization_language"] == "en-US"

        for key in ("performer", "ambassador", "technician"):
            member = fx.read_staff_member(world["roster"][key]["id"])
            assert_staff_member(member)
            assert member["status"] == "RELEASED", key

    def test_the_rebuild_comes_before_the_next_city_and_earns_it_a_discount(self):
        """A struck kit cannot be localised until the rebuild has moved it into transit.

        PRD: "The resource named in the path is in a state from which the
        requested transition is declared."
        PRD: "It takes a replacement `localization_language`, requires the kit to
        be `IN_TRANSIT` with `localization_status` of `PENDING` and a
        `condition_score` of at least 60.00, and moves the kit
        `IN_TRANSIT → READY` with `localization_status` set to `LOCALIZED`."
        PRD: "On a kit in `REFURB_REQUIRED` whose `refurb_count` is still below
        2, refurbishing adds 30.00 to `condition_score` capped at 100.00, raises
        `refurb_count` by 1, and moves the kit `REFURB_REQUIRED → IN_TRANSIT`"
        PRD: "The cost booked into `localization_cost_cents` is a base of 400000
        cents plus 3300 cents for each module, less a reuse discount: the kit's
        `reuse_cycle_count` is first capped at 5 cycles"
        PRD: "The per-module component is never discounted, and the cycle cap is
        applied before the multiplication, so a kit on its ninth tour pays exactly
        what a kit on its fifth pays."

        Design: Difficulty/transitive_cascade/close_decision_cascades_into_kit_decay_refurb_and_relocalisation
        """
        world = fx.closed_run(self._world())
        kit_id = world["kit"]["id"]
        struck = fx.read_kit(kit_id)
        assert struck["status"] == "REFURB_REQUIRED"
        assert struck["condition_score"] == 48.00

        validate_error(
            api_client.localize_kit(kit_id, f.localize_payload("fr-FR"), VOM),
            ApiErrorId.ERR_KIT_INVALID_STATE.value,
            409,
        )
        assert_row_inert(struck, fx.read_kit(kit_id))

        rebuilt = validate_success(api_client.refurbish_kit(kit_id, VOM))
        assert_kit(rebuilt)
        assert rebuilt["status"] == "IN_TRANSIT"
        assert rebuilt["condition_score"] == 78.00
        assert rebuilt["refurb_count"] == 1
        assert rebuilt["reuse_cycle_count"] == 1
        assert rebuilt["localization_status"] == "PENDING"
        assert rebuilt["localization_cost_cents"] == 0

        localised = validate_success(
            api_client.localize_kit(kit_id, f.localize_payload("fr-FR"), VOM)
        )
        assert_kit(localised)
        assert localised["status"] == "READY"
        assert localised["localization_status"] == "LOCALIZED"
        assert localised["localization_language"] == "fr-FR"
        assert localised["localization_cost_cents"] == 521200
        assert localised["condition_score"] == 78.00
        assert localised["reuse_cycle_count"] == 1
        assert localised["refurb_count"] == 1
        assert localised["last_city_code"] == "NYC"


class TestTheDemandIndexReadsFilteredSets:
    """Four windows and four orders, and only some of each belong in the figure."""

    @staticmethod
    def _world():
        """Two windows that count, one withdrawn, one never released, four orders.

        The counting window holds a confirmed party of twelve, a pending party of
        three and a cancelled party of two; a second counting window was sold to
        a party of eight that has since been refunded and then closed out.  So
        the denominator is forty seats, the numerator twelve, and of the two
        orders that count one is refunded.
        """
        bundle = fx.selling_world(
            slot_overrides={"base_capacity": 20, "wheelchair_positions": 0},
            venue_overrides={"lease_extension_option_days": 30},
        )
        run_id = bundle["run"]["id"]
        guest_id = bundle["guest"]["id"]
        bundle["slot_b"] = fx.open_slot(
            run_id, slot_start_utc="2026-09-06T14:00:00Z",
            slot_end_utc="2026-09-06T14:45:00Z", base_capacity=30,
            wheelchair_positions=0,
        )
        bundle["slot_d"] = fx.open_slot(
            run_id, slot_start_utc="2026-09-07T14:00:00Z",
            slot_end_utc="2026-09-07T14:45:00Z", base_capacity=20,
            wheelchair_positions=0,
        )
        bundle["slot_c"] = fx.draft_slot(
            run_id, slot_start_utc="2026-09-08T14:00:00Z",
            slot_end_utc="2026-09-08T14:45:00Z", base_capacity=25,
            wheelchair_positions=0,
        )
        bundle["order_confirmed"] = fx.confirmed_order(
            bundle["slot"]["id"], guest_id, order_type="GROUP", party_size=12
        )
        bundle["order_pending"] = fx.place_order(
            bundle["slot"]["id"], guest_id, order_type="SINGLE", party_size=3
        )
        doomed = fx.place_order(
            bundle["slot"]["id"], guest_id, order_type="SINGLE", party_size=2
        )
        validate_success(
            api_client.cancel_order(
                doomed["id"], f.cancel_payload("changed plans"), AGENT
            )
        )
        bundle["order_cancelled"] = fx.read_order(doomed["id"])
        bundle["order_refund_due"] = fx.refund_due_order(
            bundle["slot_d"]["id"], guest_id, order_type="GROUP", party_size=8
        )
        validate_success(
            api_client.decide_slot_status(
                bundle["slot_b"]["id"],
                f.slot_status_decision_payload(
                    "CANCEL", note="room rebuild, window withdrawn"
                ),
                PRODUCER,
            )
        )
        validate_success(
            api_client.decide_slot_status(
                bundle["slot_d"]["id"],
                f.slot_status_decision_payload("CLOSE_OUT", note="window finished"),
                PRODUCER,
            )
        )
        return bundle

    def test_the_figure_ignores_the_windows_and_orders_the_prd_excludes(self):
        """Thirty per cent utilisation less half a fifty per cent refund share is 5.00.

        PRD: "Released windows are those slots of the run whose status is `OPEN`,
        `SOLD_OUT`, `SUSPENDED` or `CLOSED_OUT` — that is, every window that was
        ever released; `DRAFT` and `CANCELLED` slots are excluded."
        PRD: "The refund share counts orders, not money: the counted orders are
        those of the run with status `CONFIRMED`, `CHECKED_IN`, `NO_SHOW`,
        `REFUND_DUE` or `REFUNDED`, and the refunded ones are those with status
        `REFUND_DUE` or `REFUNDED`; the share is 100 multiplied by the refunded
        count divided by the counted count, rounded half up to two decimals, and
        is 0.00 when no order is counted."
        PRD: "`PENDING` and `CANCELLED` orders enter neither term. The
        `demand_index` is then the utilisation percentage minus half the
        refund-share percentage, rounded half up to two decimals — both component
        percentages are rounded before the subtraction."
        PRD: "Alongside these actions the system exposes a read-only demand
        telemetry view of a run: it returns the demand figure the extension
        calculation would produce at this instant together with every input
        feeding it."
        PRD: "That view persists nothing, writes no field and never advances the
        run's `version`."
        PRD: "`CANCEL` moves a `DRAFT` or `OPEN` slot to the terminal
        `CANCELLED`, zeroing `released_capacity` and `available_capacity`, and is
        refused with `ERR_SLOT_HAS_SALES` when either `sold_capacity` or
        `held_capacity` is above 0 — a window carrying money cannot simply be
        deleted."

        Design: Corner/calculations/demand_index_counts_only_released_slots_and_settled_orders
        """
        world = self._world()
        run_id = world["run"]["id"]
        assert world["order_confirmed"]["status"] == "CONFIRMED"
        assert world["order_pending"]["status"] == "PENDING"
        assert world["order_cancelled"]["status"] == "CANCELLED"
        assert world["order_refund_due"]["status"] == "REFUND_DUE"
        assert world["order_refund_due"]["refund_pct"] == 1.00

        before = fx.read_run(run_id)
        telemetry = validate_object(api_client.get_demand_index(run_id, PRODUCER))
        assert telemetry["demand_index"] == 5.00
        after = fx.read_run(run_id)
        assert after["demand_index"] == 0.00
        assert after["demand_index_at_extension"] is None
        assert_row_inert(before, after)

        slot_a = fx.read_slot(world["slot"]["id"])
        assert_slot_ledger(slot_a, 20, 3, 12, 5)
        assert slot_a["status"] == "OPEN"
        slot_c = fx.read_slot(world["slot_c"]["id"])
        assert slot_c["status"] == "DRAFT"
        assert slot_c["released_capacity"] == 0
        slot_d = fx.read_slot(world["slot_d"]["id"])
        assert slot_d["status"] == "CLOSED_OUT"
        assert slot_d["sold_capacity"] == 0
        assert slot_d["available_capacity"] == 0

        withdrawn = assert_total_count(
            api_client.list_slots(
                PRODUCER, {"run_id": run_id, "status": "CANCELLED"}
            ),
            1,
        )
        assert withdrawn[0]["id"] == world["slot_b"]["id"]
        assert withdrawn[0]["released_capacity"] == 0
        assert withdrawn[0]["available_capacity"] == 0

        validate_error(
            api_client.grant_extension(run_id, f.extension_payload(7), PRODUCER_OTHER),
            ApiErrorId.ERR_DEMAND_BELOW_THRESHOLD.value,
            409,
        )
        assert fx.read_run(run_id)["demand_index"] == 0.00


class TestTheLeaseBudgetSitsBelowTheDemandGate:
    """The deepest refusal in the API, and the one refusal that still outranks it."""

    @staticmethod
    def _world():
        """A sold-out four-seat window on a venue whose option grants seven days.

        Four seats released and four sold puts utilisation on 100.00 with nothing
        refunded, so demand never stands in the way and every refusal that comes
        back must be the lease budget's.  The clock stays on the epoch, twenty-four
        days before the window, so the order can still be cancelled later.
        """
        bundle = fx.selling_world(
            venue_overrides={"lease_extension_option_days": 7},
            slot_overrides={
                "slot_start_utc": "2026-08-25T14:00:00Z",
                "slot_end_utc": "2026-08-25T14:45:00Z",
                "base_capacity": 4,
                "wheelchair_positions": 1,
            },
        )
        bundle["order"] = fx.confirmed_order(
            bundle["slot"]["id"], bundle["guest"]["id"],
            order_type="SINGLE", party_size=4,
        )
        bundle["slot"] = fx.read_slot(bundle["slot"]["id"])
        assert bundle["slot"]["status"] == "SOLD_OUT"
        return bundle

    def test_exactly_the_whole_option_is_granted_and_one_day_more_is_not(self):
        """Ten days is refused, seven is granted, and then one more is refused again.

        PRD: "Alongside these actions the system exposes a read-only demand
        telemetry view of a run: it returns the demand figure the extension
        calculation would produce at this instant together with every input
        feeding it."
        PRD: "Only then is the budget checked: the venue's
        `lease_extension_days_consumed` plus the `requested_extension_days` may
        not exceed its `lease_extension_option_days`, or the request is refused
        with `ERR_LEASE_EXTENSION_EXHAUSTED`."
        PRD: "On success the freshly computed figure is stored as `demand_index`
        and also copied into `demand_index_at_extension`, `scheduled_close_date`
        advances by that many calendar days, `extension_days_granted` rises by
        the same number, the venue's `lease_extension_days_consumed` rises too —
        taking a version increment on the venue — and the run moves
        `OPEN → EXTENDED`, or `EXTENDED → EXTENDED` on each further round."
        PRD: "The self-loop is unbounded except by the venue's remaining lease
        flexibility, which is what eventually terminates it."

        Design: Corner/errors/lease_extension_budget_error_is_reachable_past_the_demand_gate
        """
        world = self._world()
        run_id = world["run"]["id"]
        venue_id = world["venue"]["id"]

        telemetry = validate_object(api_client.get_demand_index(run_id, PRODUCER_OTHER))
        assert telemetry["demand_index"] == 100.00
        assert fx.read_run(run_id)["demand_index"] == 0.00

        before_run = fx.read_run(run_id)
        before_venue = fx.read_venue(venue_id)
        validate_error(
            api_client.grant_extension(
                run_id, f.extension_payload(10, memo="ten more days please"),
                PRODUCER_OTHER,
            ),
            ApiErrorId.ERR_LEASE_EXTENSION_EXHAUSTED.value,
            409,
        )
        assert_row_inert(before_run, fx.read_run(run_id))
        assert_row_inert(before_venue, fx.read_venue(venue_id))

        run = validate_success(
            api_client.grant_extension(
                run_id, f.extension_payload(7, memo="take the whole option"),
                PRODUCER_OTHER,
            )
        )
        assert_run(run)
        assert run["run_status"] == "EXTENDED"
        assert run["extension_days_granted"] == 7
        assert run["scheduled_close_date"] == "2026-11-07"
        assert run["demand_index"] == 100.00
        assert run["demand_index_at_extension"] == 100.00
        venue = fx.read_venue(venue_id)
        assert venue["lease_extension_days_consumed"] == 7
        assert_extension_days_conserved(venue, [run])

        validate_error(
            api_client.grant_extension(
                run_id, f.extension_payload(1, memo="one more day"), PRODUCER_OTHER
            ),
            ApiErrorId.ERR_LEASE_EXTENSION_EXHAUSTED.value,
            409,
        )
        after = fx.read_run(run_id)
        assert after["run_status"] == "EXTENDED"
        assert after["extension_days_granted"] == 7
        assert after["scheduled_close_date"] == "2026-11-07"
        assert fx.read_venue(venue_id)["lease_extension_days_consumed"] == 7

    def test_a_collapsed_index_answers_before_the_exhausted_budget_does(self):
        """With both gates armed the demand floor is the one that speaks.

        PRD: "The seats come back: `sold_capacity` falls by `party_size`,
        `wheelchair_sold` falls by `wheelchair_party_count`, `available_capacity`
        is recomputed, and a `SOLD_OUT` slot returns to `OPEN`."
        PRD: "`PENDING` and `CANCELLED` orders enter neither term. The
        `demand_index` is then the utilisation percentage minus half the
        refund-share percentage, rounded half up to two decimals — both component
        percentages are rounded before the subtraction."
        PRD: "so a run with weak demand and no remaining lease flexibility
        reports the demand failure"
        PRD: "Note that `demand_index` is written only on a successful extension;
        the read-only telemetry view computes the same figure and stores nothing."

        Design: Corner/errors/lease_extension_budget_error_is_reachable_past_the_demand_gate
        """
        world = self._world()
        run_id = world["run"]["id"]
        venue_id = world["venue"]["id"]
        validate_success(
            api_client.grant_extension(
                run_id, f.extension_payload(7, memo="take the whole option"),
                PRODUCER_OTHER,
            )
        )

        order = validate_success(
            api_client.cancel_order(
                world["order"]["id"], f.cancel_payload("guest rebooked"), AGENT
            )
        )
        assert_order(order)
        assert order["status"] == "REFUND_DUE"
        assert order["refund_pct"] == 1.00
        slot = fx.read_slot(world["slot"]["id"])
        assert slot["status"] == "OPEN"
        assert_slot_ledger(slot, 4, 0, 0, 4)

        telemetry = validate_object(api_client.get_demand_index(run_id, PRODUCER_OTHER))
        assert telemetry["demand_index"] == -50.00

        validate_error(
            api_client.grant_extension(
                run_id,
                f.extension_payload(1, memo="one more day, demand now gone"),
                PRODUCER_OTHER,
            ),
            ApiErrorId.ERR_DEMAND_BELOW_THRESHOLD.value,
            409,
        )

        run = fx.read_run(run_id)
        assert_run(run)
        assert run["run_status"] == "EXTENDED"
        assert run["extension_days_granted"] == 7
        assert run["scheduled_close_date"] == "2026-11-07"
        assert run["demand_index"] == 100.00
        assert run["demand_index_at_extension"] == 100.00
        venue = fx.read_venue(venue_id)
        assert venue["lease_extension_days_consumed"] == 7
        assert venue["lease_extension_option_days"] == 7
        assert_extension_days_conserved(venue, [run])
