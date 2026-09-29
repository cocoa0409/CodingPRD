"""Declared transitions, their preconditions and their side effects.

Cycles, repair bills, the mechanical dimension and reclaim decisions each move
only along their declared edges: the initial state, the gate that guards an
edge, the cascade an edge fires, and the refusal that a terminal or wrong-state
row returns.
"""

from test_helpers import (
    AUGUST_END,
    DELIVERY_OUT_AT,
    ERR_COUNTER_BILL_ROUNDS_EXHAUSTED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PERIOD_NOT_ENDED,
    ERR_RECLAIM_DECISION_NOT_OWNER_ROAD,
    ApiClient,
    admin_headers,
    assert_error_envelope,
    assert_hours,
    assert_instant_equals,
    assert_money,
    bad_order_band_world,
    bad_order_on_bn_world,
    closed_segment_world,
    deliver_out,
    draft_repair_bill,
    exposure,
    file_reclaim,
    ledger_entries,
    open_cycle,
    open_movement_of,
    read_cycle,
    read_movement,
    set_clock,
    settled_cycle,
    standard_world,
    submitted_repair_bill,
    validate_success,
)
import test_helpers.factories as f

AUGUST_START = "2026-08-01T00:00:00Z"
ONE_SECOND_SHORT = "2026-08-31T23:59:59Z"
OCTOBER_FIRST = "2026-10-01T00:00:00Z"
PAST_THE_REOPEN_WINDOW = "2026-10-02T00:00:00Z"
REPORTED_AT = "2026-08-25T00:00:00Z"
SUBMIT_CLOCK = "2026-08-26T00:00:00Z"
SETTLE_CLOCK = "2026-08-27T00:00:00Z"


class TestSettlementCycleLifecycle:
    """A cycle opens empty, computes only after the month, and ends archived."""

    def test_a_new_cycle_is_open_with_every_money_field_at_zero(self, api: ApiClient):
        """Creation yields OPEN, the derived period bounds and version 1.

        PRD: "The cycle is created at `OPEN` with every money field 0 and `version` 1, and is addressed thereafter by `settlement_cycle_id`."

        Design: Corner/state_machines/settlement_cycle_starts_in_open
        """
        world = standard_world(api, register_first_car=False)
        cycle = open_cycle(api, world)

        assert cycle["status"] == "OPEN"
        assert cycle["period_month"] == "2026-08"
        assert_instant_equals(cycle["period_start_at"], AUGUST_START, "period_start_at")
        assert_instant_equals(cycle["period_end_at"], AUGUST_END, "period_end_at")

        for field in ("gross_hire_cents", "reclaim_credit_cents", "penalty_cents",
                      "repair_charge_cents", "dispute_adjustment_cents",
                      "pre_fee_net_cents", "clearinghouse_fee_cents",
                      "net_settlement_cents"):
            assert_money(cycle[field], 0, field)

        assert cycle["variant_applied"] is None
        assert cycle["computed_at"] is None
        assert cycle["exchanged_at"] is None
        assert cycle["reopen_count"] == 0
        assert cycle["movement_line_count"] == 0
        assert cycle["version"] == 1

    def test_computing_one_second_before_the_period_ends_is_refused(self, api: ApiClient):
        """23:59:59 on 31 August is ERR_PERIOD_NOT_ENDED; one second later computes.

        PRD: "Only the payee road computes, and only once the month is over: the logical clock must be at or after `period_end_at`, otherwise `ERR_PERIOD_NOT_ENDED`."

        Design: Corner/state_machines/cycle_compute_before_period_end_rejected
        """
        world = standard_world(api, register_first_car=False)
        cycle = open_cycle(api, world, clock=ONE_SECOND_SHORT)

        refused = api.compute_settlement_cycle(cycle["id"], {},
                                              world.accountant(world.cx))
        assert_error_envelope(refused, ERR_PERIOD_NOT_ENDED, 422)
        still_open = read_cycle(api, world, cycle["id"])
        assert still_open["status"] == "OPEN"
        assert still_open["version"] == 1
        assert still_open["computed_at"] is None

        set_clock(api, AUGUST_END, world)
        computed = validate_success(api.compute_settlement_cycle(
            cycle["id"], {}, world.accountant(world.cx)))
        assert computed["status"] == "COMPUTED"
        assert_instant_equals(computed["computed_at"], AUGUST_END, "computed_at")
        assert computed["movement_line_count"] == 0
        assert_money(computed["gross_hire_cents"], 0, "gross_hire_cents")
        assert_money(computed["pre_fee_net_cents"], 0, "pre_fee_net_cents")
        assert_money(computed["clearinghouse_fee_cents"], 0, "clearinghouse_fee_cents")
        assert_money(computed["net_settlement_cents"], 0, "net_settlement_cents")

    def test_exchange_opens_the_dispute_window_without_moving_the_money(self, api: ApiClient):
        """EXCHANGED stamps a deadline exactly 30 days out and keeps 11407.

        PRD: "The payee road exchanges the computed statement, moving `COMPUTED → EXCHANGED`, stamping `exchanged_at` and setting `dispute_deadline_at` to 30 days after it; exchange is what makes the cycle a legal dispute container."

        Design: Corner/state_machines/settlement_exchange_stamps_dispute_deadline_at
        """
        world, movement = closed_segment_world(api)
        cycle = open_cycle(api, world)
        computed = validate_success(api.compute_settlement_cycle(
            cycle["id"], {}, world.accountant(world.cx)))
        assert computed["movement_line_count"] == 1
        assert_money(computed["gross_hire_cents"], 11464, "gross_hire_cents")
        assert_money(computed["clearinghouse_fee_cents"], 57, "clearinghouse_fee_cents")
        assert_money(computed["net_settlement_cents"], 11407, "net_settlement_cents")

        exchanged = validate_success(api.exchange_settlement_cycle(
            cycle["id"], {}, world.accountant(world.cx)))
        assert exchanged["status"] == "EXCHANGED"
        assert_instant_equals(exchanged["exchanged_at"], AUGUST_END, "exchanged_at")
        assert_instant_equals(exchanged["dispute_deadline_at"], OCTOBER_FIRST,
                              "dispute_deadline_at")
        assert exchanged["version"] > computed["version"]
        assert_money(exchanged["net_settlement_cents"], 11407, "net_settlement_cents")

    def test_settling_mints_one_payment_entry_and_drops_the_payer_exposure(self, api: ApiClient):
        """The payer remits 11407, leaving a -11407 entry and 57 of exposure.

        PRD: "Settling stamps `settled_at`, sets `reopen_deadline_at` to 30 days after it, mints a `SETTLEMENT_PAYMENT` ledger entry for the negative of `net_settlement_cents`, and reduces the payer road's `per_diem_exposure_cents` by `net_settlement_cents`."

        Design: Corner/state_machines/settle_mints_settlement_payment_and_reduces_payer_exposure
        """
        world, movement = closed_segment_world(api)
        set_clock(api, AUGUST_END, world)
        before = exposure(api, world, world.bn)
        assert_money(before["exposure_cents"], 11464, "exposure before settling")

        cycle, computed, exchanged, settled = settled_cycle(api, world)
        assert settled["status"] == "SETTLED"
        assert_instant_equals(settled["settled_at"], AUGUST_END, "settled_at")
        assert_instant_equals(settled["reopen_deadline_at"], OCTOBER_FIRST,
                              "reopen_deadline_at")

        payments = ledger_entries(api, settlement_cycle_id=cycle["id"],
                                  entry_type="SETTLEMENT_PAYMENT")
        assert len(payments) == 1
        assert_money(payments[0]["amount_cents"], -11407, "amount_cents")
        assert payments[0]["debit_road_id"] == world.bn
        assert payments[0]["credit_road_id"] == world.cx
        assert_instant_equals(payments[0]["effective_at"], AUGUST_END, "effective_at")

        after = exposure(api, world, world.bn)
        assert_money(after["exposure_cents"], 57, "exposure after settling")
        road = validate_success(api.get_railroad(world.bn, world.accountant(world.bn)))
        assert_money(road["per_diem_exposure_cents"], 57, "per_diem_exposure_cents")

    def test_settling_an_open_cycle_reports_the_state_gate(self, api: ApiClient):
        """The payer firing settle on an OPEN cycle gets 409 and writes no ledger row.

        PRD: "The target row's current status is a legal from-state for the requested transition — otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/settlement_settle_from_open_returns_invalid_state
        """
        world = standard_world(api, register_first_car=False)
        cycle = open_cycle(api, world)

        refused = api.settle_settlement_cycle(cycle["id"], {},
                                             world.accountant(world.bn))
        assert_error_envelope(refused, ERR_INVALID_STATE_TRANSITION, 409)

        after = read_cycle(api, world, cycle["id"])
        assert after["status"] == "OPEN"
        assert after["settled_at"] is None
        assert after["reopen_deadline_at"] is None
        assert ledger_entries(api, settlement_cycle_id=cycle["id"]) == []

    def test_an_archived_cycle_refuses_reopen_compute_and_archive_alike(self, api: ApiClient):
        """Every edge off ARCHIVED is 409 ERR_INVALID_STATE_TRANSITION, never the window error.

        PRD: "Re-issuing a transition that already ran, or driving a terminal row, fails here."

        Design: Corner/state_machines/archived_cycle_reopen_rejected
        """
        world = standard_world(api, register_first_car=False)
        cycle, computed, exchanged, settled = settled_cycle(api, world)

        set_clock(api, PAST_THE_REOPEN_WINDOW, world)
        archived = validate_success(api.archive_settlement_cycle(
            cycle["id"], {}, admin_headers()))
        assert archived["status"] == "ARCHIVED"
        assert_instant_equals(archived["archived_at"], PAST_THE_REOPEN_WINDOW,
                              "archived_at")

        reopen = api.reopen_settlement_cycle(
            cycle["id"], {"reopen_reason": "late reclaim discovered"}, admin_headers())
        assert_error_envelope(reopen, ERR_INVALID_STATE_TRANSITION, 409)
        recompute = api.compute_settlement_cycle(cycle["id"], {},
                                               world.accountant(world.cx))
        assert_error_envelope(recompute, ERR_INVALID_STATE_TRANSITION, 409)
        rearchive = api.archive_settlement_cycle(cycle["id"], {}, admin_headers())
        assert_error_envelope(rearchive, ERR_INVALID_STATE_TRANSITION, 409)

        after = read_cycle(api, world, cycle["id"])
        assert after["status"] == "ARCHIVED"
        assert after["reopen_count"] == 0
        assert after["reopened_at"] is None


class TestRepairBillLifecycle:
    """A bill is drafted, priced at submission, negotiated twice, then settled."""

    def test_submission_is_where_the_bill_is_priced_and_responsibility_decided(self, api: ApiClient):
        """DRAFT holds no figures; SUBMITTED stamps 48644 against the owner road.

        PRD: "The billing road submits, taking the bill `DRAFT → SUBMITTED` and stamping `submitted_at` from the logical clock while `counter_bill_round` stays 0."

        Design: Corner/state_machines/repair_bill_submit_moves_draft_to_submitted
        """
        world, car = bad_order_on_bn_world(api, report_at=REPORTED_AT)
        set_clock(api, SUBMIT_CLOCK, world)

        draft = draft_repair_bill(api, world, world.car, world.bn, "NORMAL_WEAR",
                                  REPORTED_AT, 3.5, 12000)
        assert draft["status"] == "DRAFT"
        assert draft["counter_bill_round"] == 0
        assert draft["submitted_at"] is None
        assert draft["accepted_at"] is None
        assert draft["settled_at"] is None

        submitted = validate_success(api.submit_repair_bill(
            draft["id"], {}, world.repair(world.bn)))
        assert submitted["status"] == "SUBMITTED"
        assert_instant_equals(submitted["submitted_at"], SUBMIT_CLOCK, "submitted_at")
        assert submitted["counter_bill_round"] == 0
        assert submitted["responsibility_rule_applied"] == "OWNER_RESPONSIBILITY_RULE"
        assert submitted["responsible_road_id"] == world.cx
        assert_money(submitted["labor_cents"], 33250, "labor_cents")
        assert_money(submitted["subtotal_cents"], 45250, "subtotal_cents")
        assert_money(submitted["handling_fee_cents"], 3394, "handling_fee_cents")
        assert_money(submitted["total_cents"], 48644, "total_cents")

        car_row = validate_success(api.get_car(world.car, world.owner(world.cx)))
        assert car_row["mechanical_status"] == "UNDER_REPAIR"
        assert car_row["custody_status"] == "ON_FOREIGN_ROAD"

    def test_submitting_the_same_bill_twice_changes_nothing(self, api: ApiClient):
        """The second submit is 409 and the first stamp and total survive intact.

        PRD: "The target row's current status is a legal from-state for the requested transition — otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/repair_bill_submit_twice_rejected
        """
        world, car = bad_order_on_bn_world(api, report_at=REPORTED_AT)
        set_clock(api, SUBMIT_CLOCK, world)
        draft, submitted = submitted_repair_bill(api, world, world.car, world.bn,
                                                "NORMAL_WEAR", REPORTED_AT, 3.5, 12000)

        set_clock(api, SETTLE_CLOCK, world)
        again = api.submit_repair_bill(draft["id"], {}, world.repair(world.bn))
        assert_error_envelope(again, ERR_INVALID_STATE_TRANSITION, 409)

        after = validate_success(api.get_repair_bill(draft["id"],
                                                   world.repair(world.bn)))
        assert after["status"] == "SUBMITTED"
        assert_instant_equals(after["submitted_at"], SUBMIT_CLOCK, "submitted_at")
        assert_money(after["total_cents"], 48644, "total_cents")
        car_row = validate_success(api.get_car(world.car, world.owner(world.cx)))
        assert car_row["mechanical_status"] == "UNDER_REPAIR"

    def test_a_third_counter_offer_is_refused_with_the_rounds_error(self, api: ApiClient):
        """Two counters stand at 35000 and the third is ERR_COUNTER_BILL_ROUNDS_EXHAUSTED.

        PRD: "The counter must satisfy `0 < counter_total_cents < total_cents` as the bill currently stands — an absent, zero, negative, or at-or-above-standing-total figure is not a counter-offer at all and is `ERR_REPAIR_AMOUNT_INVALID` — and `counter_bill_round` must be strictly less than 2, so the second counter is the last one accepted and a third attempt is `ERR_COUNTER_BILL_ROUNDS_EXHAUSTED`."

        Design: Corner/state_machines/repair_counter_bill_third_round_rejected
        """
        world, car = bad_order_on_bn_world(api, report_at=REPORTED_AT)
        set_clock(api, SUBMIT_CLOCK, world)
        draft, submitted = submitted_repair_bill(api, world, world.car, world.bn,
                                                "NORMAL_WEAR", REPORTED_AT, 3.5, 12000)

        first = validate_success(api.counter_repair_bill(
            draft["id"], {"counter_total_cents": 40000}, world.repair(world.cx)))
        assert first["status"] == "SUBMITTED"
        assert first["counter_bill_round"] == 1
        assert_money(first["total_cents"], 40000, "total_cents")
        assert_instant_equals(first["last_counter_at"], SUBMIT_CLOCK, "last_counter_at")

        second = validate_success(api.counter_repair_bill(
            draft["id"], {"counter_total_cents": 35000}, world.repair(world.cx)))
        assert second["counter_bill_round"] == 2
        assert_money(second["total_cents"], 35000, "total_cents")

        third = api.counter_repair_bill(draft["id"], {"counter_total_cents": 30000},
                                       world.repair(world.cx))
        assert_error_envelope(third, ERR_COUNTER_BILL_ROUNDS_EXHAUSTED, 409)

        after = validate_success(api.get_repair_bill(draft["id"],
                                                   world.repair(world.bn)))
        assert after["counter_bill_round"] == 2
        assert_money(after["total_cents"], 35000, "total_cents")
        assert_money(after["subtotal_cents"], 45250, "subtotal_cents")
        assert_money(after["handling_fee_cents"], 3394, "handling_fee_cents")

    def test_settling_the_bill_puts_the_car_back_in_service(self, api: ApiClient):
        """Acceptance charges 48644 and settlement clears the bad order at 08-27.

        PRD: "Settlement is also how a repaired car re-enters service: the mechanical dimension moves `UNDER_REPAIR → SERVICEABLE`, `bad_order_since` is cleared to null, `bad_order_cleared_at` is stamped at the logical clock, and the open bad-order stamp on the car's current segment is closed."

        Design: Corner/state_machines/repair_bill_settle_returns_car_to_serviceable
        """
        world, car = bad_order_on_bn_world(api, report_at=REPORTED_AT)
        set_clock(api, SUBMIT_CLOCK, world)
        draft, submitted = submitted_repair_bill(api, world, world.car, world.bn,
                                                "NORMAL_WEAR", REPORTED_AT, 3.5, 12000)

        accepted = validate_success(api.accept_repair_bill(draft["id"], {},
                                                          world.repair(world.cx)))
        assert accepted["status"] == "ACCEPTED"
        assert_instant_equals(accepted["accepted_at"], SUBMIT_CLOCK, "accepted_at")
        charges = ledger_entries(api, repair_bill_id=draft["id"])
        assert len(charges) == 1
        assert charges[0]["entry_type"] == "REPAIR_CHARGE"
        assert_money(charges[0]["amount_cents"], 48644, "amount_cents")
        assert charges[0]["debit_road_id"] == world.cx
        assert charges[0]["credit_road_id"] == world.bn

        set_clock(api, SETTLE_CLOCK, world)
        settled = validate_success(api.settle_repair_bill(draft["id"], {},
                                                         admin_headers()))
        assert settled["status"] == "SETTLED"
        assert_instant_equals(settled["settled_at"], SETTLE_CLOCK, "settled_at")

        car_row = validate_success(api.get_car(world.car, world.owner(world.cx)))
        assert car_row["mechanical_status"] == "SERVICEABLE"
        assert car_row["bad_order_since"] is None
        assert_instant_equals(car_row["bad_order_cleared_at"], SETTLE_CLOCK,
                              "bad_order_cleared_at")

        segment = open_movement_of(api, world.car, world.bn,
                                  world.accountant(world.bn))
        assert_instant_equals(segment["bad_order_from"], REPORTED_AT, "bad_order_from")
        assert_instant_equals(segment["bad_order_to"], SETTLE_CLOCK, "bad_order_to")
        assert len(ledger_entries(api, repair_bill_id=draft["id"])) == 1


class TestMechanicalDimensionStampsTheSegment:
    """A bad order opens a band on the current segment and a release closes it."""

    def test_release_closes_the_band_without_closing_the_segment(self, api: ApiClient):
        """The 08-25 to 08-26 band is stamped while the segment stays OPEN and unpriced.

        PRD: "The car's `bad_order_since` is cleared to null and `bad_order_cleared_at` becomes `released_at`, and the segment whose `bad_order_from` is non-null while its `bad_order_to` is still null has that `bad_order_to` stamped at `released_at`."

        Design: Corner/state_machines/release_to_service_closes_the_bad_order_stamp_on_the_movement
        """
        world = standard_world(api)
        deliver_out(api, world, world.car, DELIVERY_OUT_AT, 1000)
        before = open_movement_of(api, world.car, world.bn,
                                 world.accountant(world.bn))
        assert before["bad_order_from"] is None
        assert before["bad_order_to"] is None

        set_clock(api, REPORTED_AT, world)
        reported = validate_success(api.report_bad_order(
            world.car, f.bad_order_payload(REPORTED_AT), world.clerk(world.bn)))
        assert reported["mechanical_status"] == "BAD_ORDER"
        assert_instant_equals(reported["bad_order_since"], REPORTED_AT,
                              "bad_order_since")
        opened = open_movement_of(api, world.car, world.bn,
                                 world.accountant(world.bn))
        assert_instant_equals(opened["bad_order_from"], REPORTED_AT, "bad_order_from")
        assert opened["bad_order_to"] is None
        assert opened["version"] > before["version"]

        set_clock(api, SUBMIT_CLOCK, world)
        released = validate_success(api.release_to_service(
            world.car, f.release_payload(SUBMIT_CLOCK), world.clerk(world.bn)))
        assert released["mechanical_status"] == "SERVICEABLE"
        assert released["bad_order_since"] is None
        assert_instant_equals(released["bad_order_cleared_at"], SUBMIT_CLOCK,
                              "bad_order_cleared_at")
        assert released["custody_status"] == "ON_FOREIGN_ROAD"
        assert released["routing_status"] == "NO_OBLIGATION"

        closed_band = open_movement_of(api, world.car, world.bn,
                                      world.accountant(world.bn))
        assert closed_band["status"] == "OPEN"
        assert_instant_equals(closed_band["bad_order_from"], REPORTED_AT,
                              "bad_order_from")
        assert_instant_equals(closed_band["bad_order_to"], SUBMIT_CLOCK,
                              "bad_order_to")
        assert closed_band["end_at"] is None
        assert closed_band["gross_hire_cents"] in (0, None)
        assert closed_band["net_hire_cents"] in (0, None)


class TestReclaimDecisionOwnership:
    """Only the road named in against_road_id may allow a claim."""

    def test_the_filing_road_cannot_allow_its_own_claim(self, api: ApiClient):
        """BN allowing its own claim is 403; CX allowing it grants 2843.

        PRD: "Only the owner road named in `against_road_id` may allow or disallow, and only the filing road may withdraw; the filer deciding its own claim is `ERR_RECLAIM_DECISION_NOT_OWNER_ROAD`."

        Design: Corner/state_machines/reclaim_allow_by_the_filing_road_rejected
        """
        world, movement = bad_order_band_world(api, report_at=REPORTED_AT,
                                              release_at=SUBMIT_CLOCK)
        claim = file_reclaim(api, world, movement, "BAD_ORDER", REPORTED_AT,
                            SUBMIT_CLOCK)
        assert claim["status"] == "FILED"
        assert_hours(claim["claimed_hours"], 24.00, "claimed_hours")
        assert claim["filed_by_road_id"] == world.bn
        assert claim["against_road_id"] == world.cx
        assert_money(claim["credit_cents"], 0, "credit_cents")

        refused = api.allow_reclaim_claim(claim["id"], {},
                                        world.accountant(world.bn))
        assert_error_envelope(refused, ERR_RECLAIM_DECISION_NOT_OWNER_ROAD, 403)
        unchanged = validate_success(api.get_reclaim_claim(
            claim["id"], world.accountant(world.bn)))
        assert unchanged["status"] == "FILED"
        assert_money(unchanged["credit_cents"], 0, "credit_cents")

        allowed = validate_success(api.allow_reclaim_claim(
            claim["id"], {}, world.accountant(world.cx)))
        assert allowed["status"] == "ALLOWED"
        assert_hours(allowed["allowed_hours"], 24.00, "allowed_hours")
        assert_money(allowed["credit_cents"], 2843, "credit_cents")

        priced = read_movement(api, world, movement["id"])
        assert_money(priced["reclaim_credit_cents"], 2843, "reclaim_credit_cents")
        assert_money(priced["net_hire_cents"], 8621, "net_hire_cents")
