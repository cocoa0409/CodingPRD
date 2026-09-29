"""The four endpoint shapes that are not plain CRUD writes.

A bulk sweep with per-row skip semantics, two computed reads that must answer
either variant without saving anything, a conditional action that touches one
dimension of a three-dimensional row, and an action endpoint whose single call
has to fan out to a dispute, a segment, the ledger and a settlement cycle.
"""

from test_helpers import (
    ApiClient,
    admin_headers,
    assert_instant_equals,
    assert_money,
    bad_order_on_bn_world,
    closed_segment_world,
    computed_cycle,
    exchanged_cycle,
    exposure,
    file_dispute,
    ledger_entries,
    open_movement_of,
    read_cycle,
    read_movement,
    register_car,
    set_clock,
    standard_world,
    validate_success,
)
import test_helpers.factories as f

FILE_A_AT = "2026-08-26T00:00:00Z"
FILE_B_AT = "2026-08-27T00:00:00Z"
DEADLINE_A = "2026-08-29T00:00:00Z"
DEADLINE_B = "2026-08-30T00:00:00Z"
SWEEP_ONE_AT = "2026-08-29T00:00:01Z"
SWEEP_TWO_AT = "2026-08-30T00:00:01Z"


def _two_filed_corrections(api):
    """Two FILED timestamp amendments a day apart, so their deadlines differ."""
    world = standard_world(api)
    car_a = world.car
    car_b = register_car(api, "CX 100002", world.xm, world.cx, world=world)

    set_clock(api, "2026-08-24T00:00:00Z", world)
    event_a = validate_success(api.create_interchange_event(
        f.delivery_event_payload(car_a, world.jct, world.cx, world.bn,
                                 "2026-08-24T00:00:00Z", 1000, "LOADED"),
        world.clerk(world.cx)), 201)
    set_clock(api, "2026-08-25T00:00:00Z", world)
    event_b = validate_success(api.create_interchange_event(
        f.delivery_event_payload(car_b, world.jct, world.cx, world.bn,
                                 "2026-08-25T00:00:00Z", 2000, "LOADED"),
        world.clerk(world.cx)), 201)

    set_clock(api, FILE_A_AT, world)
    corr_a = validate_success(api.create_correction_request(
        f.timestamp_amend_payload(car_a, world.jct, world.bn, event_a["id"],
                                  "2026-08-24T06:00:00Z"),
        world.clerk(world.cx)), 201)
    set_clock(api, FILE_B_AT, world)
    corr_b = validate_success(api.create_correction_request(
        f.timestamp_amend_payload(car_b, world.jct, world.bn, event_b["id"],
                                  "2026-08-25T06:00:00Z"),
        world.clerk(world.cx)), 201)
    return world, corr_a, corr_b


class TestCorrectionExpireDueSweep:
    """The one bulk endpoint expires row by row and never errors on an empty batch."""

    def test_the_sweep_names_only_the_request_whose_window_has_lapsed(self, api: ApiClient):
        """One of two FILED requests expires, and evaluated_at is the logical clock.

        PRD: "The sweep returns `expired_count`, the list `expired_correction_request_ids` and the `evaluated_at` instant it used."

        Design: Corner/endpoints/correction_request_expire_due_sweep_is_idempotent
        """
        world, corr_a, corr_b = _two_filed_corrections(api)
        assert_instant_equals(corr_a["confirm_deadline_at"], DEADLINE_A, "deadline A")
        assert_instant_equals(corr_b["confirm_deadline_at"], DEADLINE_B, "deadline B")
        assert corr_a["status"] == "FILED"
        assert corr_b["status"] == "FILED"

        set_clock(api, SWEEP_ONE_AT, world)
        swept = validate_success(api.expire_due_correction_requests({}, admin_headers()))

        assert swept["expired_count"] == 1
        assert swept["expired_correction_request_ids"] == [corr_a["id"]]
        assert_instant_equals(swept["evaluated_at"], SWEEP_ONE_AT, "evaluated_at")

        expired = validate_success(api.get_correction_request(corr_a["id"],
                                                             world.clerk(world.cx)))
        assert expired["status"] == "EXPIRED"
        assert_instant_equals(expired["expired_at"], SWEEP_ONE_AT, "expired_at")

        untouched = validate_success(api.get_correction_request(corr_b["id"],
                                                               world.clerk(world.cx)))
        assert untouched["status"] == "FILED"
        assert untouched["expired_at"] is None

    def test_an_immediate_second_sweep_expires_nothing_and_still_returns_200(self, api: ApiClient):
        """The second call reports 0 with an empty list, then 1 once B's own deadline lapses.

        PRD: "A `ClearinghouseAdmin` may also run a sweep that expires every `FILED` request whose window has elapsed, processing them in `created_at` ascending order, taking each `FILED → EXPIRED` and stamping `expired_at`; requests already `CONFIRMED`, `APPLIED`, `REJECTED` or `EXPIRED` are untouched, so a second call with nothing newly due expires 0."

        Design: Corner/endpoints/correction_request_expire_due_sweep_is_idempotent
        """
        world, corr_a, corr_b = _two_filed_corrections(api)
        set_clock(api, SWEEP_ONE_AT, world)
        validate_success(api.expire_due_correction_requests({}, admin_headers()))

        second = api.expire_due_correction_requests({}, admin_headers())
        assert second.status_code == 200
        again = validate_success(second)
        assert again["expired_count"] == 0
        assert again["expired_correction_request_ids"] == []

        still_a = validate_success(api.get_correction_request(corr_a["id"],
                                                             world.clerk(world.cx)))
        assert still_a["status"] == "EXPIRED"
        assert_instant_equals(still_a["expired_at"], SWEEP_ONE_AT,
                             "expired_at after the second sweep")

        set_clock(api, SWEEP_TWO_AT, world)
        third = validate_success(api.expire_due_correction_requests({}, admin_headers()))
        assert third["expired_count"] == 1
        assert third["expired_correction_request_ids"] == [corr_b["id"]]
        assert_instant_equals(third["evaluated_at"], SWEEP_TWO_AT, "evaluated_at")

        now_b = validate_success(api.get_correction_request(corr_b["id"],
                                                           world.clerk(world.cx)))
        assert now_b["status"] == "EXPIRED"


class TestSettlementStatementComputedRead:
    """The statement is assembled on demand and stores nothing it derives."""

    def test_the_default_read_mirrors_the_stored_cycle_line_for_line(self, api: ApiClient):
        """Omitting variant gives AS_REPORTED: 1 line, 11464, 57, 11407 and the id lists.

        PRD: "Under `AS_REPORTED` — the default, and the only variant in play while no dispute on the cycle has been accepted — a segment contributes its `net_hire_cents`, the figure as originally reported by the handling road, ignoring every dispute outcome."

        Design: Corner/endpoints/settlement_statement_computed_read_reflects_the_cycle_without_mutating_it
        """
        world, movement = closed_segment_world(api)
        cycle, computed = computed_cycle(api, world)

        statement = validate_success(api.get_settlement_statement(
            cycle["id"], world.accountant(world.cx)))

        assert statement["settlement_cycle_id"] == cycle["id"]
        assert statement["variant_applied"] == "AS_REPORTED"
        assert statement["payer_road_id"] == world.bn
        assert statement["payee_road_id"] == world.cx
        assert statement["period_month"] == "2026-08"
        assert statement["movement_line_count"] == 1
        assert_money(statement["gross_hire_cents"], 11464, "gross_hire_cents")
        assert_money(statement["reclaim_credit_cents"], 0, "reclaim_credit_cents")
        assert_money(statement["penalty_cents"], 0, "penalty_cents")
        assert_money(statement["repair_charge_cents"], 0, "repair_charge_cents")
        assert_money(statement["dispute_adjustment_cents"], 0, "dispute_adjustment_cents")
        assert_money(statement["pre_fee_net_cents"], 11464, "pre_fee_net_cents")
        assert_money(statement["clearinghouse_fee_cents"], 57, "clearinghouse_fee_cents")
        assert_money(statement["net_settlement_cents"], 11407, "net_settlement_cents")
        assert statement["included_movement_ids"] == [movement["id"]]
        assert statement["included_repair_bill_ids"] == []

        assert_money(computed["pre_fee_net_cents"], 11464, "stored pre_fee_net_cents")
        assert_money(computed["net_settlement_cents"], 11407, "stored net_settlement_cents")

    def test_asking_for_the_other_variant_mutates_nothing(self, api: ApiClient):
        """A RECONCILED read returns 11407 too and leaves version and variant_applied alone.

        PRD: "Separately, a computed read returns the statement without mutating anything, so the two variants can be compared side by side: it accepts a `variant` selecting `AS_REPORTED` by default or `RECONCILED`, and returns `settlement_cycle_id`, `variant_applied`, `payer_road_id`, `payee_road_id`, `period_month`, `movement_line_count`, `gross_hire_cents`, `reclaim_credit_cents`, `penalty_cents`, `repair_charge_cents`, `dispute_adjustment_cents`, `pre_fee_net_cents`, `clearinghouse_fee_cents`, `net_settlement_cents`, and the membership lists `included_movement_ids` and `included_repair_bill_ids`."

        Design: Corner/endpoints/settlement_statement_computed_read_reflects_the_cycle_without_mutating_it
        """
        world, movement = closed_segment_world(api)
        cycle, computed = computed_cycle(api, world)
        version_before = computed["version"]
        assert computed["variant_applied"] == "AS_REPORTED"

        reconciled = validate_success(api.get_settlement_statement(
            cycle["id"], admin_headers(), params={"variant": "RECONCILED"}))
        assert reconciled["variant_applied"] == "RECONCILED"
        assert_money(reconciled["net_settlement_cents"], 11407,
                     "reconciled net_settlement_cents")
        assert_money(reconciled["pre_fee_net_cents"], 11464,
                     "reconciled pre_fee_net_cents")

        stored = read_cycle(api, world, cycle["id"])
        assert stored["version"] == version_before
        assert stored["variant_applied"] == "AS_REPORTED"
        assert stored["status"] == "COMPUTED"
        assert_money(stored["net_settlement_cents"], 11407, "stored net_settlement_cents")

        line = read_movement(api, world, movement["id"])
        assert_money(line["net_hire_cents"], 11464, "net_hire_cents")
        assert_money(line["adjusted_net_hire_cents"], 11464, "adjusted_net_hire_cents")


PROJECTION_START = "2026-08-30T00:00:00Z"
BAD_ORDER_AT = "2026-08-31T00:00:00Z"
PROJECTION_CLOCK = "2026-09-02T00:00:00Z"
DEFAULT_LIMIT_CENTS = 100000000


def _fleet_world(api):
    """CX owns three cars: one is out on BN, one is bad-ordered at home, one idle."""
    world = standard_world(api)
    register_car(api, "CX 100002", world.xm, world.cx, world=world)
    car2 = register_car(api, "CX 100003", world.xm, world.cx, world=world)

    set_clock(api, PROJECTION_START, world)
    validate_success(api.create_interchange_event(
        f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                 PROJECTION_START, 1000, "LOADED"),
        world.clerk(world.cx)), 201)

    set_clock(api, BAD_ORDER_AT, world)
    validate_success(api.report_bad_order(
        car2, f.bad_order_payload(BAD_ORDER_AT), world.clerk(world.cx)))

    set_clock(api, PROJECTION_CLOCK, world)
    return world, car2


class TestRailroadExposureComputedRead:
    """One read answers both what a road owes and how its own fleet is doing."""

    def test_the_handling_road_reads_its_money_block_in_both_variants(self, api: ApiClient):
        """BN's snapshot is 7800 with 99992200 of headroom and its projection is 17100.

        PRD: "One open segment starting at `2026-08-30T00:00:00Z` on an `XM`-rated car with the clock at `2026-09-02T00:00:00Z` gives a snapshot of 7800 — 72.00 elapsed, 68.00 chargeable, three days — and a projection of 17100, accruing to `2026-09-05T00:00:00Z` for 144.00 elapsed, 140.00 chargeable and six days priced as two days at 2350 plus four at 3100; the projection is more than double the snapshot because the escalated second-tier rate dominates the extra three days."

        Design: Corner/endpoints/railroad_exposure_computed_read_returns_the_utilization_block
        """
        world, car2 = _fleet_world(api)

        snapshot = exposure(api, world, world.bn, headers=world.accountant(world.bn))
        assert snapshot["railroad_id"] == world.bn
        assert snapshot["variant_applied"] == "SNAPSHOT"
        assert_money(snapshot["exposure_cents"], 7800, "exposure_cents")
        assert snapshot["open_movement_count"] == 1
        assert_money(snapshot["closed_unsettled_cents"], 0, "closed_unsettled_cents")
        assert_money(snapshot["settled_paid_cents"], 0, "settled_paid_cents")
        assert_money(snapshot["credit_limit_cents"], DEFAULT_LIMIT_CENTS,
                     "credit_limit_cents")
        assert_money(snapshot["credit_headroom_cents"], 99992200,
                     "credit_headroom_cents")
        assert snapshot["foreign_car_balance"] == 1

        projected = exposure(api, world, world.bn, variant="PROJECTED",
                             headers=world.accountant(world.bn))
        assert projected["variant_applied"] == "PROJECTED"
        assert_money(projected["exposure_cents"], 17100, "projected exposure_cents")
        assert projected["exposure_cents"] - snapshot["exposure_cents"] == 9300

    def test_the_two_roads_read_opposite_utilization_blocks(self, api: ApiClient):
        """CX owes nothing on its own cars yet reports 3 owned and 33.33 percent utilization.

        PRD: "`utilization_pct` is 100 times `serviceable_foreign_count` divided by `owned_car_count`, rounded half up to exactly two decimal places — 7 owned cars of which 3 are serviceable on a foreign road gives 42.86 — and is 0.00 when the fleet is empty, never an error and never null."

        Design: Corner/endpoints/railroad_exposure_computed_read_returns_the_utilization_block
        """
        world, car2 = _fleet_world(api)

        bn = exposure(api, world, world.bn, headers=world.accountant(world.bn))
        assert bn["owned_car_count"] == 0
        assert bn["on_foreign_count"] == 0
        assert bn["bad_order_count"] == 0
        assert bn["serviceable_foreign_count"] == 0
        assert bn["utilization_pct"] == 0.00

        cx = exposure(api, world, world.cx, headers=world.owner(world.cx))
        assert_money(cx["exposure_cents"], 0, "cx exposure_cents")
        assert cx["owned_car_count"] == 3
        assert cx["on_foreign_count"] == 1
        assert cx["bad_order_count"] == 1
        assert cx["serviceable_foreign_count"] == 1
        assert cx["utilization_pct"] == 33.33

        bad_ordered = validate_success(api.get_car(car2, world.owner(world.cx)))
        assert bad_ordered["mechanical_status"] == "BAD_ORDER"
        assert bad_ordered["custody_status"] == "ON_HOME_ROAD"


DISPUTED_CENTS = 5000
STANDING_COUNTER_CENTS = 3000
RESOLVED_AT = "2026-09-01T00:00:00Z"


def _countered_dispute(api):
    """The 11464 line disputed at 5000 and countered down to a standing 3000."""
    world, movement = closed_segment_world(api)
    cycle, computed, exchanged = exchanged_cycle(api, world)
    dispute = file_dispute(api, world, exchanged, "HIRE_RATE_MISAPPLIED",
                          DISPUTED_CENTS, movement_id=movement["id"])
    countered = validate_success(api.counter_dispute(
        dispute["id"], {"counter_amount_cents": STANDING_COUNTER_CENTS},
        world.accountant(world.cx)))
    return world, movement, cycle, dispute, countered


class TestDisputeAcceptFansOut:
    """One accept writes the dispute, the segment, the ledger and the cycle."""

    def test_accepting_from_countered_settles_at_the_standing_counter(self, api: ApiClient):
        """The filer's accept resolves at 3000, not 5000, and adjusts the line to 8464.

        PRD: "Either way `resolution_amount_cents` becomes the standing `counter_amount_cents` when a counter stands and `disputed_amount_cents` when none does, `resolved_at` is stamped, and the money moves: the subject segment's `adjusted_net_hire_cents` becomes its `net_hire_cents` minus `resolution_amount_cents`, a `DISPUTE_ADJUSTMENT` ledger entry for the negative of the resolution is minted, and the cycle is recomputed under `RECONCILED`."

        Design: Corner/endpoints/dispute_accept_action_endpoint_applies_every_declared_side_effect
        """
        world, movement, cycle, dispute, countered = _countered_dispute(api)
        assert_money(dispute["subject_net_at_filing_cents"], 11464,
                     "subject_net_at_filing_cents")
        assert countered["status"] == "COUNTERED"
        assert countered["round_number"] == 1
        assert_money(countered["counter_amount_cents"], STANDING_COUNTER_CENTS,
                     "counter_amount_cents")

        accepted = validate_success(api.accept_dispute(dispute["id"], {},
                                                      world.accountant(world.bn)))
        assert accepted["status"] == "ACCEPTED"
        assert_money(accepted["resolution_amount_cents"], STANDING_COUNTER_CENTS,
                     "resolution_amount_cents")
        assert accepted["resolution_amount_cents"] != DISPUTED_CENTS
        assert_instant_equals(accepted["resolved_at"], RESOLVED_AT, "resolved_at")

        line = read_movement(api, world, movement["id"])
        assert_money(line["net_hire_cents"], 11464, "net_hire_cents")
        assert_money(line["adjusted_net_hire_cents"], 8464, "adjusted_net_hire_cents")

        rows = ledger_entries(api, world.accountant(world.bn),
                             dispute_id=dispute["id"],
                             entry_type="DISPUTE_ADJUSTMENT")
        assert len(rows) == 1
        assert_money(rows[0]["amount_cents"], -STANDING_COUNTER_CENTS,
                     "DISPUTE_ADJUSTMENT amount_cents")

    def test_the_adjustment_entry_and_the_recomputed_cycle_follow_the_payer(self, api: ApiClient):
        """The entry debits payer BN and credits payee CX while the fee falls from 57 to 42.

        PRD: "Its `amount_cents` is signed from the payer road's perspective — positive increases what the payer owes the payee, negative decreases it — with `debit_road_id` being the road charged, which is the cycle's payer, and `credit_road_id` the road credited, which is the cycle's payee."

        Design: Corner/endpoints/dispute_accept_action_endpoint_applies_every_declared_side_effect
        """
        world, movement, cycle, dispute, countered = _countered_dispute(api)
        before = read_cycle(api, world, cycle["id"])
        assert_money(before["clearinghouse_fee_cents"], 57, "fee before the accept")

        validate_success(api.accept_dispute(dispute["id"], {},
                                           world.accountant(world.bn)))

        rows = ledger_entries(api, world.accountant(world.bn),
                             dispute_id=dispute["id"],
                             entry_type="DISPUTE_ADJUSTMENT")
        assert len(rows) == 1
        entry = rows[0]
        assert entry["debit_road_id"] == world.bn
        assert entry["credit_road_id"] == world.cx
        assert entry["movement_id"] == movement["id"]
        assert entry["settlement_cycle_id"] == cycle["id"]
        assert_money(entry["amount_cents"], -STANDING_COUNTER_CENTS, "amount_cents")

        after = read_cycle(api, world, cycle["id"])
        assert after["variant_applied"] == "RECONCILED"
        assert_money(after["dispute_adjustment_cents"], -STANDING_COUNTER_CENTS,
                     "dispute_adjustment_cents")
        assert_money(after["pre_fee_net_cents"], 8464, "pre_fee_net_cents")
        assert_money(after["clearinghouse_fee_cents"], 42, "clearinghouse_fee_cents")
        assert after["clearinghouse_fee_cents"] != 57
        assert_money(after["net_settlement_cents"], 8422, "net_settlement_cents")


ISSUED_AT = "2026-08-26T00:00:00Z"
DUE_AT = "2026-08-28T00:00:00Z"


def _obligation_ready_world(api):
    """A bad-ordered CX car in BN's custody, with the clock inside the window."""
    world, car = bad_order_on_bn_world(api)
    set_clock(api, ISSUED_AT, world)
    return world, car


class TestEmptyRoutingObligationAction:
    """The owner writes the routing column and nothing else."""

    def test_issuing_moves_the_routing_dimension_and_echoes_the_window(self, api: ApiClient):
        """The car goes to OBLIGATION_ACTIVE at JCT-CHI with one version bump.

        PRD: "Issuing takes the routing dimension `NO_OBLIGATION → OBLIGATION_ACTIVE`, or `OBLIGATION_MET → OBLIGATION_ACTIVE` when the car has already satisfied a previous obligation — a car can be re-obligated after a compliant return, and the new obligation supersedes the satisfied one."

        Design: Corner/endpoints/empty_routing_obligation_is_a_conditional_action_on_one_dimension_only
        """
        world, car = _obligation_ready_world(api)
        assert car["routing_status"] == "NO_OBLIGATION"
        version_before = car["version"]

        obligated = validate_success(api.issue_empty_routing_obligation(
            car["id"], f.routing_obligation_payload(world.jct, ISSUED_AT, DUE_AT),
            world.owner(world.cx)))

        assert obligated["routing_status"] == "OBLIGATION_ACTIVE"
        assert obligated["prescribed_return_junction_id"] == world.jct
        assert_instant_equals(obligated["obligation_issued_at"], ISSUED_AT,
                              "obligation_issued_at")
        assert_instant_equals(obligated["obligation_due_at"], DUE_AT,
                              "obligation_due_at")
        assert obligated["version"] == version_before + 1

    def test_the_custody_and_mechanical_dimensions_are_left_alone(self, api: ApiClient):
        """The same response still reads ON_FOREIGN_ROAD and BAD_ORDER, and mints no money.

        PRD: "The custody and mechanical dimensions are neither read nor written by this action."

        Design: Corner/endpoints/empty_routing_obligation_is_a_conditional_action_on_one_dimension_only
        """
        world, car = _obligation_ready_world(api)
        assert car["custody_status"] == "ON_FOREIGN_ROAD"
        assert car["mechanical_status"] == "BAD_ORDER"
        segment = open_movement_of(api, car["id"], world.bn,
                                  world.accountant(world.bn))

        obligated = validate_success(api.issue_empty_routing_obligation(
            car["id"], f.routing_obligation_payload(world.jct, ISSUED_AT, DUE_AT),
            world.owner(world.cx)))

        assert obligated["custody_status"] == "ON_FOREIGN_ROAD"
        assert obligated["mechanical_status"] == "BAD_ORDER"
        assert obligated["current_handling_road_id"] == world.bn
        assert_instant_equals(obligated["bad_order_since"], "2026-08-25T00:00:00Z",
                              "bad_order_since")

        after = open_movement_of(api, car["id"], world.bn,
                                world.accountant(world.bn))
        assert after["id"] == segment["id"]
        assert after["status"] == "OPEN"
        assert after["version"] == segment["version"]
        assert ledger_entries(api, world.accountant(world.bn),
                             movement_id=segment["id"]) == []
