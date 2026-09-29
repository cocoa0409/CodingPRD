"""Two accruals over one population, the true-up, and the ladder guarding the create."""

from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    api_client,
    assert_ids,
    assert_instant_equals,
    assert_row_inert,
    assert_statement,
    assert_total_count,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

PRODUCER = fx.PRODUCER
LM = fx.LM
AGENT = fx.AGENT


class TestTheTwoAccrualVariantsOnIdenticalOrders:
    """Four order rows, one population, and two figures that differ by 21670 cents."""

    @staticmethod
    def _world():
        """Four identical orders left in four different statuses.

        Each party of four is bought 11 days out, so the lead multiplier is 1.00
        and every order carries `net_amount_cents` 143332 with 25020 cents of
        merchandise beside it.  The first is checked in, the second stays
        confirmed, the third is never paid for and the fourth is refunded in
        full, which zeroes the money the operator actually holds on it.
        """
        bundle = fx.selling_world(
            slot_overrides={"base_capacity": 40, "wheelchair_positions": 4}
        )
        fx.set_clock("2026-08-25T00:00:00Z")
        orders = [
            fx.place_order(
                bundle["slot"]["id"], bundle["guest"]["id"],
                order_type="SINGLE", party_size=4, wheelchair_party_count=0,
                sensory_accommodations=[], merch_amount_cents=25020,
            )
            for _ in range(4)
        ]
        for index in (0, 1, 3):
            validate_success(api_client.confirm_order(orders[index]["id"], AGENT))
        fx.set_clock("2026-08-26T00:00:00Z")
        validate_success(
            api_client.cancel_order(
                orders[3]["id"], f.cancel_payload("schedule change"), AGENT
            )
        )
        validate_success(api_client.settle_refund(orders[3]["id"], AGENT))
        fx.set_clock("2026-09-05T14:30:00Z")
        validate_success(
            api_client.record_attendance(
                orders[0]["id"], f.attendance_payload("CHECK_IN"), AGENT
            )
        )
        bundle["orders"] = [fx.read_order(order["id"]) for order in orders]
        assert [order["status"] for order in bundle["orders"]] == [
            "CHECKED_IN", "CONFIRMED", "PENDING", "REFUNDED"
        ]
        for order in bundle["orders"]:
            assert order["net_amount_cents"] == 143332
            assert order["merch_amount_cents"] == 25020
        return bundle

    def test_the_provisional_variant_counts_the_money_the_operator_expects(self):
        """Three orders at face value, both legs rounded apart, and nothing else written.

        PRD: "It runs at creation and on every recompute, writing
        `ticket_base_cents`, `merch_base_cents` and `provisional_royalty_cents`."
        PRD: "its ticket base is the sum of `net_amount_cents` and its
        merchandise base the sum of `merch_amount_cents` over the orders with
        status `PENDING`, `CONFIRMED`, `CHECKED_IN` or `NO_SHOW` — unpaid pending
        orders included at face value."
        PRD: "the ticket leg is the ticket base multiplied by the agreement's
        `royalty_rate_bps` and divided by 10000, and the merchandise leg is the
        merchandise base multiplied by `merch_royalty_rate_bps` and divided by
        10000."
        PRD: "A new statement lands in `DRAFT` with
        `provisional_royalty_cents_prev`, `truedown_cents`, `final_royalty_cents`,
        `mg_prorated_cents`, `minimum_guarantee_shortfall_cents` and
        `amount_due_cents` all at 0 and `superseded_by_statement_id` null."
        PRD: "The statement's `license_agreement_id` is copied from the run rather
        than named by the client, so a statement can never be pointed at an
        agreement the run does not stage."

        Design: Difficulty/dual_variant_calc/royalty_provisional_versus_final_on_identical_orders
        """
        world = self._world()
        statement = fx.draft_statement(
            world["run"]["id"],
            period_start_date="2026-09-01", period_end_date="2026-09-30",
        )
        assert_statement(statement)
        assert statement["status"] == "DRAFT"
        assert statement["run_id"] == world["run"]["id"]
        assert statement["license_agreement_id"] == world["agreement"]["id"]
        assert statement["ticket_base_cents"] == 429996
        assert statement["merch_base_cents"] == 75060
        assert statement["provisional_royalty_cents"] == 59380
        assert statement["provisional_royalty_cents_prev"] == 0
        assert statement["truedown_cents"] == 0
        assert statement["final_royalty_cents"] == 0
        assert statement["mg_prorated_cents"] == 0
        assert statement["minimum_guarantee_shortfall_cents"] == 0
        assert statement["amount_due_cents"] == 0
        assert statement["superseded_by_statement_id"] is None
        assert statement["issued_at"] is None
        assert statement["settled_at"] is None

    def test_the_final_variant_counts_only_the_money_actually_held(self):
        """The same rows earn 37710, and the guarantee tops the difference back up.

        PRD: "its ticket base is the sum of `net_collected_cents` over the orders
        with status `CONFIRMED`, `CHECKED_IN`, `NO_SHOW`, `REFUND_DUE` or
        `REFUNDED` — a refunded order contributes nothing because its
        `net_collected_cents` was zeroed when the refund was computed — and its
        merchandise base is the sum of `merch_amount_cents` over the orders with
        status `CHECKED_IN`"
        PRD: "Finalisation refreshes `ticket_base_cents` and `merch_base_cents`
        from the final variant's population"
        PRD: "Second the minimum guarantee is prorated: the licence term length in
        days is `term_end_date` minus `term_start_date` plus one, the period length
        is `period_end_date` minus `period_start_date` plus one — both inclusive
        counts — and `mg_prorated_cents` is the agreement's
        `minimum_guarantee_cents` multiplied by the period days, divided by the
        term days, and rounded half up to whole cents."
        PRD: "Third `minimum_guarantee_shortfall_cents` is `mg_prorated_cents`
        less `final_royalty_cents`, floored at 0 — there is no shortfall when the
        earned royalty already clears the guarantee."
        PRD: "Fourth `amount_due_cents` is `final_royalty_cents` plus
        `minimum_guarantee_shortfall_cents`."
        PRD: "The statement then moves `DRAFT → ISSUED` or `UNDER_TRUEUP → ISSUED`
        and `issued_at` is stamped from the clock; a statement issued out of
        true-up keeps its `truedown_cents` as the record of the provisional
        reduction."

        Design: Difficulty/dual_variant_calc/royalty_provisional_versus_final_on_identical_orders
        """
        world = self._world()
        statement = fx.draft_statement(
            world["run"]["id"],
            period_start_date="2026-09-01", period_end_date="2026-09-30",
        )
        provisional = statement["provisional_royalty_cents"]

        fx.set_clock("2026-10-01T00:00:00Z")
        issued = validate_success(
            api_client.finalize_statement(statement["id"], LM)
        )
        assert_statement(issued)
        assert issued["status"] == "ISSUED"
        assert issued["ticket_base_cents"] == 286664
        assert issued["merch_base_cents"] == 25020
        assert issued["final_royalty_cents"] == 37710
        assert provisional - issued["final_royalty_cents"] == 21670
        assert issued["provisional_royalty_cents"] == 59380
        assert issued["mg_prorated_cents"] == 37802
        assert issued["minimum_guarantee_shortfall_cents"] == 92
        assert issued["amount_due_cents"] == 37802
        assert issued["truedown_cents"] == 0
        assert_instant_equals(issued["issued_at"], "2026-10-01T00:00:00Z")
        assert issued["settled_at"] is None

        refunded = fx.read_order(world["orders"][3]["id"])
        assert refunded["status"] == "REFUNDED"
        assert refunded["net_collected_cents"] == 0
        assert refunded["merch_amount_cents"] == 25020


class TestRecomputeTruesDownThenLocksOut:
    """One trigger, two destinations, and no way back out of the second one."""

    @staticmethod
    def _world():
        """A draft statement over a period holding one unpaid order.

        The window sits on 2026-08-25 inside the August period, and the order is
        placed 24 days ahead so the lead multiplier is 1.00 and the two guests
        accrue 71666 cents of ticket base beside 4000 cents of merchandise.
        """
        bundle = fx.selling_world(
            slot_overrides={
                "slot_start_utc": "2026-08-25T14:00:00Z",
                "slot_end_utc": "2026-08-25T14:45:00Z",
                "base_capacity": 20,
                "wheelchair_positions": 2,
            }
        )
        bundle["order_pending"] = fx.place_order(
            bundle["slot"]["id"], bundle["guest"]["id"],
            order_type="SINGLE", party_size=2, merch_amount_cents=4000,
        )
        assert bundle["order_pending"]["net_amount_cents"] == 71666
        bundle["statement"] = fx.draft_statement(
            bundle["run"]["id"],
            period_start_date="2026-08-01", period_end_date="2026-08-31",
        )
        return bundle

    @classmethod
    def _drive_to_true_up(cls, world):
        """Grow the accrual once, then shrink it, which lands the row in true-up."""
        world["order_confirmed"] = fx.confirmed_order(
            world["slot"]["id"], world["guest"]["id"],
            order_type="SINGLE", party_size=2,
        )
        validate_success(
            api_client.recompute_provisional(world["statement"]["id"], LM)
        )
        validate_success(
            api_client.cancel_order(
                world["order_pending"]["id"], f.cancel_payload("guest withdrew"), AGENT
            )
        )
        return validate_success(
            api_client.recompute_provisional(world["statement"]["id"], LM)
        )

    def test_a_rise_resets_the_truedown_and_a_fall_records_it(self):
        """The same call keeps the row in DRAFT once and moves it to true-up once.

        PRD: "The recompute first copies the stored `provisional_royalty_cents`
        into `provisional_royalty_cents_prev`, then rewrites `ticket_base_cents`,
        `merch_base_cents` and `provisional_royalty_cents` from the provisional
        variant."
        PRD: "When the new figure is greater than or equal to the previous one the
        statement stays in `DRAFT` and `truedown_cents` is 0 — the period held or
        grew."
        PRD: "When the new figure is strictly lower, cancellations have eaten into
        the accrual: the statement moves `DRAFT → UNDER_TRUEUP` and
        `truedown_cents` records exactly how much was lost, being the previous
        figure less the new one."
        PRD: "Orders are replayed in ascending `created_at` order, and `CANCELLED`
        orders and `SUPERSEDED` statements never enter either computation."

        Design: Corner/calculations/statement_recompute_trues_down_then_locks_out_further_recomputes
        """
        world = self._world()
        opening = world["statement"]
        assert_statement(opening)
        assert opening["status"] == "DRAFT"
        assert opening["ticket_base_cents"] == 71666
        assert opening["merch_base_cents"] == 4000
        assert opening["provisional_royalty_cents"] == 9258
        assert opening["provisional_royalty_cents_prev"] == 0
        assert opening["truedown_cents"] == 0
        assert opening["version"] == 1

        world["order_confirmed"] = fx.confirmed_order(
            world["slot"]["id"], world["guest"]["id"],
            order_type="SINGLE", party_size=2,
        )
        grown = validate_success(
            api_client.recompute_provisional(opening["id"], LM)
        )
        assert_statement(grown)
        assert grown["status"] == "DRAFT"
        assert grown["ticket_base_cents"] == 143332
        assert grown["merch_base_cents"] == 4000
        assert grown["provisional_royalty_cents"] == 18217
        assert grown["provisional_royalty_cents_prev"] == 9258
        assert grown["truedown_cents"] == 0
        assert grown["version"] == 2

        validate_success(
            api_client.cancel_order(
                world["order_pending"]["id"], f.cancel_payload("guest withdrew"), AGENT
            )
        )
        shrunk = validate_success(
            api_client.recompute_provisional(opening["id"], LM)
        )
        assert_statement(shrunk)
        assert shrunk["status"] == "UNDER_TRUEUP"
        assert shrunk["ticket_base_cents"] == 71666
        assert shrunk["merch_base_cents"] == 0
        assert shrunk["provisional_royalty_cents"] == 8958
        assert shrunk["provisional_royalty_cents_prev"] == 18217
        assert shrunk["truedown_cents"] == 9259
        assert shrunk["version"] == 3

    def test_true_up_refuses_a_third_recompute_and_still_issues(self):
        """No recompute leaves true-up, but finalisation does — carrying the audit trail.

        PRD: "The resource named in the path is in a state from which the
        requested transition is declared."
        PRD: "Finalising issues the statement, and it may only happen once the
        period is genuinely over"
        PRD: "its ticket base is the sum of `net_collected_cents` over the orders
        with status `CONFIRMED`, `CHECKED_IN`, `NO_SHOW`, `REFUND_DUE` or
        `REFUNDED` — a refunded order contributes nothing because its
        `net_collected_cents` was zeroed when the refund was computed — and its
        merchandise base is the sum of `merch_amount_cents` over the orders with
        status `CHECKED_IN`"
        PRD: "The statement then moves `DRAFT → ISSUED` or `UNDER_TRUEUP → ISSUED`
        and `issued_at` is stamped from the clock; a statement issued out of
        true-up keeps its `truedown_cents` as the record of the provisional
        reduction."

        Design: Corner/calculations/statement_recompute_trues_down_then_locks_out_further_recomputes
        """
        world = self._world()
        trued = self._drive_to_true_up(world)
        statement_id = trued["id"]
        assert trued["status"] == "UNDER_TRUEUP"

        validate_error(
            api_client.recompute_provisional(statement_id, LM),
            ApiErrorId.ERR_STATEMENT_INVALID_STATE.value,
            409,
        )
        after = fx.read_statement(statement_id)
        assert_row_inert(trued, after)
        assert after["version"] == 3
        assert after["truedown_cents"] == 9259

        fx.set_clock("2026-09-01T00:00:00Z")
        issued = validate_success(api_client.finalize_statement(statement_id, LM))
        assert_statement(issued)
        assert issued["status"] == "ISSUED"
        assert issued["ticket_base_cents"] == 71666
        assert issued["merch_base_cents"] == 0
        assert issued["final_royalty_cents"] == 8958
        # 192790 * 31 / 153 = 39062.0261..., which rounds half up to 39062.
        assert issued["mg_prorated_cents"] == 39062
        assert issued["minimum_guarantee_shortfall_cents"] == 30104
        assert issued["amount_due_cents"] == 39062
        assert issued["truedown_cents"] == 9259
        assert issued["provisional_royalty_cents"] == 8958
        assert issued["version"] == 4
        assert_instant_equals(issued["issued_at"], "2026-09-01T00:00:00Z")
        assert issued["settled_at"] is None


class TestTheRunCounterTracksStatementsAcrossASupersede:
    """A supersede retires a row without deleting it, so the counter still climbs."""

    def test_the_counter_counts_the_retired_row_as_well_as_the_new_one(self):
        """Three accepted creates, three rows, three counter steps and three versions.

        PRD: "When a statement already exists for the same combination of `run_id`,
        `period_start_date` and `period_end_date` and its status is `DRAFT` or
        `UNDER_TRUEUP`, the new create moves that older row to the terminal
        `SUPERSEDED` and sets its `superseded_by_statement_id` to the new row's
        `id`, preserving its `truedown_cents` as the audit trail."
        PRD: "Every accepted create raises the run's `royalty_statement_count` by
        1 and therefore advances the run's `version`, which is exactly why the
        create carries a stale-version guard: two managers cutting statements for
        the same run must serialise, and the loser must re-read the run."
        PRD: "Note that every accepted statement create itself advances the run's
        `version` (by incrementing `royalty_statement_count`), so a caller
        intending to supersede must re-read the run first."
        PRD: "List royalty statements; the reverse-reachability channel for the
        run, agreement and supersede links."

        Design: Corner/state_machines/statement_count_on_the_run_tracks_the_statement_rows_across_a_supersede
        """
        world = fx.run_with_room()
        run_id = world["run"]["id"]
        opening_version = fx.run_version(run_id)
        assert world["run"]["royalty_statement_count"] == 0

        first = fx.draft_statement(
            run_id, period_start_date="2026-08-01", period_end_date="2026-08-31"
        )
        assert fx.read_run(run_id)["royalty_statement_count"] == 1

        second = fx.draft_statement(
            run_id, period_start_date="2026-08-01", period_end_date="2026-08-31"
        )
        assert second["id"] != first["id"]
        assert second["status"] == "DRAFT"
        assert second["superseded_by_statement_id"] is None
        retired = fx.read_statement(first["id"])
        assert_statement(retired)
        assert retired["status"] == "SUPERSEDED"
        assert retired["superseded_by_statement_id"] == second["id"]
        assert retired["version"] == 2
        assert retired["truedown_cents"] == 0
        assert fx.read_run(run_id)["royalty_statement_count"] == 2

        third = fx.draft_statement(
            run_id, period_start_date="2026-09-01", period_end_date="2026-09-30"
        )
        run = fx.read_run(run_id)
        assert run["royalty_statement_count"] == 3
        assert run["version"] == opening_version + 3

        rows = assert_total_count(
            api_client.list_statements(LM, {"run_id": run_id}), 3
        )
        by_id = {row["id"]: row for row in rows}
        assert set(by_id) == {first["id"], second["id"], third["id"]}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[second["id"]]["status"] == "DRAFT"
        assert by_id[third["id"]]["status"] == "DRAFT"

        reverse = assert_total_count(
            api_client.list_statements(
                LM, {"superseded_by_statement_id": second["id"]}
            ),
            1,
        )
        assert_ids(reverse, [first["id"]])


class TestStatementCreateRejectsInStrictPriorityOrder:
    """One endpoint, five rungs, five different status lines in the declared order."""

    def test_each_rung_answers_before_the_next_one_is_reached(self):
        """Shape, then the body key, then the version, then the calendar, then the period.

        PRD: "Most requests that fail could plausibly fail for several reasons at
        once, and the service must be predictable about which one it reports."
        PRD: "Every required input field is present; every type matches; every
        enum value is a member of its declared set; every numeric value lies inside
        its declared range; dates are ten-character ISO calendar dates; instants are
        ISO 8601 UTC instants; array-valued inputs contain no duplicates and only
        declared members."
        PRD: "This rung guards the creation of experience runs, themed rooms,
        timed-entry slots, ticket orders, creative submissions, staff members,
        staff shifts, safety inspections, build kits and royalty statements."
        PRD: "If `expected_run_version` does not equal the run's current `version`,
        the create is rejected with `ERR_RUN_VERSION_CONFLICT` and HTTP 412."
        PRD: "A statement period not wholly inside its agreement's term earns
        `ERR_PERIOD_OUTSIDE_TERM` (422)."
        PRD: "But once a statement for that period has been issued the numbers have
        left the building: if the existing row is `ISSUED`, `SETTLED` or already
        `SUPERSEDED`, the create is refused with `ERR_STATEMENT_PERIOD_ISSUED`."

        Design: Corner/validations/statement_create_rejects_in_strict_priority_order
        """
        world = fx.run_with_room()
        run_id = world["run"]["id"]
        stale = fx.run_version(run_id)
        issued = fx.issued_statement(
            run_id, period_start_date="2026-08-01", period_end_date="2026-08-31",
            finalize_at="2026-09-01T00:00:00Z",
        )
        assert issued["status"] == "ISSUED"
        fresh = fx.run_version(run_id)
        assert fresh != stale
        before_issued = fx.read_statement(issued["id"])

        validate_error(
            api_client.create_statement(
                {
                    "run_id": UNKNOWN_UUID,
                    "period_start_date": "2026-07-01",
                    "expected_run_version": stale,
                },
                LM,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )
        validate_error(
            api_client.create_statement(
                f.statement_payload(
                    UNKNOWN_UUID, stale,
                    period_start_date="2026-07-01", period_end_date="2026-07-31",
                ),
                LM,
            ),
            ApiErrorId.ERR_RUN_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_statement(
                f.statement_payload(
                    run_id, stale,
                    period_start_date="2026-07-01", period_end_date="2026-07-31",
                ),
                LM,
            ),
            ApiErrorId.ERR_RUN_VERSION_CONFLICT.value,
            412,
        )
        validate_error(
            api_client.create_statement(
                f.statement_payload(
                    run_id, fresh,
                    period_start_date="2026-07-01", period_end_date="2026-07-31",
                ),
                LM,
            ),
            ApiErrorId.ERR_PERIOD_OUTSIDE_TERM.value,
            422,
        )
        validate_error(
            api_client.create_statement(
                f.statement_payload(
                    run_id, stale,
                    period_start_date="2026-08-01", period_end_date="2026-08-31",
                ),
                LM,
            ),
            ApiErrorId.ERR_RUN_VERSION_CONFLICT.value,
            412,
        )
        validate_error(
            api_client.create_statement(
                f.statement_payload(
                    run_id, fresh,
                    period_start_date="2026-08-01", period_end_date="2026-08-31",
                ),
                LM,
            ),
            ApiErrorId.ERR_STATEMENT_PERIOD_ISSUED.value,
            409,
        )

        clean = validate_success(
            api_client.create_statement(
                f.statement_payload(
                    run_id, fresh,
                    period_start_date="2026-09-01", period_end_date="2026-09-30",
                ),
                LM,
            ),
            201,
        )
        assert_statement(clean)
        assert clean["status"] == "DRAFT"
        run = fx.read_run(run_id)
        assert run["royalty_statement_count"] == 2
        assert run["version"] == fresh + 1
        assert_row_inert(before_issued, fx.read_statement(issued["id"]))
