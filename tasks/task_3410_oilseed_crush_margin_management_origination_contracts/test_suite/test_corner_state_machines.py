"""Corner queue — state_machines section: terminal lockdowns, valid and
invalid transitions, exact-fill auto-advance, sweep-driven forced pricing and
defaults, and precondition enforcement (PRD §3.1/§3.3/§3.4/§3.6/§3.7/§3.8/§3.9).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_crush_run,
    assert_delivery_ticket,
    create_and_apply_ticket,
    create_cash_contract,
    create_crush_plant,
    create_crush_run,
    create_draft_schedule,
    create_deferred_contract,
    create_active_program,
    create_ticket,
    elect_price,
    enter_board_position,
    post_bean_quote,
    post_crush_quote_set,
    read_contract,
    read_crush_run,
    read_sales_contract,
    read_buyer,
    record_delivery,
    schedule_run,
    set_clock,
    setup_origination_site,
    setup_sales_scenario,
    transition_run,
    validate_error,
    validate_paginated,
    validate_success,
)
from conftest import parse_iso

ADMIN = TEST_USERS["platform_admin_headers"]
MERCH = TEST_USERS["origination_merchandiser_headers"]
AUDITOR = TEST_USERS["sustainability_auditor_headers"]
SCHEDULER = TEST_USERS["plant_scheduler_headers"]
TRADER = TEST_USERS["crush_trader_headers"]


class TestTerminalLockdowns:
    def test_schedule_publish_then_terminal_lockdown(self, api):
        """PRD §3.1: "Publishing is a one-way door: a `PlatformAdmin` publishes a `DRAFT` schedule, moving it to `PUBLISHED`, which is terminal, increments the schedule's `version`, and makes it pinnable to elevators." PRD §2.9
        rule 6: an entity not "in a state that permits the transition" fails
        with ERR_INVALID_STATE.

        Design: Corner/state_machines/schedule_publish_then_terminal_lockdown
        """
        schedule = create_draft_schedule()
        published = validate_success(
            api_client.publish_quality_discount_schedule(schedule["id"], ADMIN)
        )
        assert published["status"] == "PUBLISHED"
        assert published["version"] == 2
        resp = api_client.publish_quality_discount_schedule(schedule["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_program_close_then_terminal_lockdown(self, api):
        """PRD §3.1: "a `SustainabilityAuditor` may close one, moving it to `CLOSED` — terminal and version-incrementing". PRD §2.9 rule 6: the
        state precondition failure is ERR_INVALID_STATE.

        Design: Corner/state_machines/program_close_then_terminal_lockdown
        """
        program = create_active_program()
        closed = validate_success(
            api_client.close_sustainability_program(program["id"], AUDITOR)
        )
        assert closed["status"] == "CLOSED"
        resp = api_client.close_sustainability_program(program["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCrushRunTransitions:
    def test_crush_run_revert_cycle_scheduled_to_planned(self, api):
        """PRD §3.6: "A revert — requested through the run's transition capability with `to_status` set to `PLANNED` — moves the run back to `PLANNED`, frees the day's aggregate capacity, and increments the version." After run A (40000 bu) reverts from a 50000-cap day, run B
        (40000 bu) schedules onto the freed date.

        Design: Corner/state_machines/crush_run_revert_cycle_scheduled_to_planned
        """
        plant = create_crush_plant()
        post_crush_quote_set("2026-11")
        run_a = create_crush_run(plant["id"], run_date="2026-09-10T00:00:00Z",
                                 planned_bushels=40000, futures_month="2026-11")
        schedule_run(run_a["id"], expected_run_version=run_a["version"])
        run_b = create_crush_run(plant["id"], run_date="2026-09-10T00:00:00Z",
                                 planned_bushels=40000, futures_month="2026-11")
        reverted = transition_run(run_a["id"], "PLANNED")
        assert reverted["status"] == "PLANNED"
        scheduled_b = schedule_run(run_b["id"])
        assert_crush_run(scheduled_b)
        assert scheduled_b["status"] == "SCHEDULED"
        assert read_crush_run(run_a["id"])["status"] == "PLANNED"

    def test_crush_run_cancelled_terminal_rejects_start(self, api):
        """PRD §3.6: "Cancellation (`to_status` `CANCELLED`) is legal from `PLANNED` or `SCHEDULED` and, like `COMPLETE`, is terminal" and "a `to_status` that names a state the run's current state cannot reach is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/crush_run_cancelled_terminal_rejects_start
        """
        plant = create_crush_plant()
        post_crush_quote_set("2026-11")
        run = create_crush_run(plant["id"], run_date="2026-09-10T00:00:00Z",
                               planned_bushels=1000, futures_month="2026-11")
        cancelled = transition_run(run["id"], "CANCELLED")
        assert cancelled["status"] == "CANCELLED"
        resp = api_client.transition_crush_run(
            run["id"], {"to_status": "RUNNING"}, SCHEDULER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert read_crush_run(run["id"])["status"] == "CANCELLED"


class TestTicketApplyBranches:
    def test_ticket_apply_above_reject_moisture_returns_rejected_outcome(self, api):
        """PRD §3.3: "When `moisture_pct` is strictly greater than the pinned schedule's `reject_moisture_pct`, the load is refused: the ticket moves to `REJECTED`, the grading fields are still computed for the record, and the apply returns 200 with the rejected ticket — a business outcome, not a request error — while no contract, position, or elevator state changes."

        Design: Corner/state_machines/ticket_apply_above_reject_moisture_returns_rejected_outcome
        """
        site = setup_origination_site()
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=100
        )
        ticket = create_ticket(contract["id"], gross_bushels=100,
                               moisture_pct=18.5)
        resp = api_client.apply_delivery_ticket(ticket["id"], MERCH)
        rejected = validate_success(resp, 200)
        assert_delivery_ticket(rejected)
        assert rejected["status"] == "REJECTED"
        assert rejected["shrink_bushels"] is not None, (
            "grading fields are computed for the record on the REJECTED branch"
        )
        contract_after = read_contract(contract["id"])
        assert float(contract_after["delivered_bushels"]) == pytest.approx(0)
        assert contract_after["fulfillment_status"] == "OPEN"
        positions, meta = validate_paginated(
            api_client.list_storage_positions(
                MERCH, params={"elevator_id": site["elevator"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        elevator = validate_success(
            api_client.get_elevator(site["elevator"]["id"], MERCH)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(0)

    def test_ticket_apply_twice_returns_invalid_state(self, api):
        """PRD §3.3: "it is legal only while the ticket is `RECEIVED` and the contract's fulfillment is still `OPEN` or `DELIVERING`; anything else is `ERR_INVALID_STATE`." APPLIED is terminal, so the second apply fails 409
        and the first apply's side effects are not duplicated.

        Design: Corner/state_machines/ticket_apply_twice_returns_invalid_state
        """
        site = setup_origination_site()
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=100
        )
        create_and_apply_ticket(contract["id"], gross_bushels=50)
        ticket_id = api_client.list_delivery_tickets(
            MERCH, params={"contract_id": contract["id"]}
        ).json()["data"][0]["id"]
        resp = api_client.apply_delivery_ticket(ticket_id, MERCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        contract_after = read_contract(contract["id"])
        assert float(contract_after["delivered_bushels"]) == pytest.approx(50)
        elevator = validate_success(
            api_client.get_elevator(site["elevator"]["id"], MERCH)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(50)


class TestExactFillAutoAdvance:
    def test_contract_exact_fill_transitions_open_to_delivered(self, api):
        """PRD §3.3: "an apply that exactly fills the contract moves `OPEN` or `DELIVERING` straight to `DELIVERED". One clean 100-bu ticket fills a
        100-bu contract in a single hop.

        Design: Corner/state_machines/contract_exact_fill_transitions_open_to_delivered
        """
        site = setup_origination_site()
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=100
        )
        create_and_apply_ticket(contract["id"], gross_bushels=100)
        refreshed = read_contract(contract["id"])
        assert refreshed["fulfillment_status"] == "DELIVERED"
        assert float(refreshed["delivered_bushels"]) == pytest.approx(100)

    def test_sales_delivery_exact_fill_fulfills_from_open(self, api):
        """PRD §3.8: "a delivery that exactly fills the contract moves `OPEN` or `DELIVERING` straight to `FULFILLED` — terminal", and "A clean delivery appends the entry with its `delivery_date`, `quantity_lbs`, `actual_protein_pct`, `actual_ffa_pct`, and a `recorded_at` stamp, grows `delivered_lbs` by the delivered quantity".

        Design: Corner/state_machines/sales_delivery_exact_fill_fulfills_from_open
        """
        base = setup_sales_scenario(
            product="SOY_MEAL", quantity_lbs=2000, price_cents_per_lb=15,
            delivery_window_start="2026-09-10T00:00:00Z",
            delivery_window_end="2026-09-20T00:00:00Z", min_protein_pct=46.0,
        )
        set_clock("2026-09-12T00:00:00Z")
        updated = record_delivery(
            base["contract"]["id"], "2026-09-12T00:00:00Z", 2000,
            product="SOY_MEAL", actual_protein_pct=47.5,
        )
        assert updated["status"] == "FULFILLED"
        assert updated["delivered_lbs"] == 2000
        assert len(updated["deliveries"]) == 1
        assert float(updated["deliveries"][0]["actual_protein_pct"]) == pytest.approx(47.5)


class TestSweepDrivenTransitions:
    def test_sales_contract_defaulted_by_sweep_accrues_claim(self, api):
        """PRD §3.9: "Every sales contract in `OPEN` or `DELIVERING` whose
        `delivery_window_end` has fallen behind the new clock, with
        `delivered_lbs` still short of `quantity_lbs`, moves to `DEFAULTED`."
        and "Each default sets `claim_cents` to the undelivered pounds
        multiplied by `price_cents_per_lb` multiplied by ten percent, rounded
        half up to whole cents; increments the buyer's `open_claims_count` by
        one; and suspends the buyer — `ACTIVE` to `SUSPENDED`, terminal — the
        moment the count reaches three open claims."
        One default: claim 2000, count 1, buyer still ACTIVE.

        Design: Corner/state_machines/sales_contract_defaulted_by_sweep_accrues_claim
        """
        base = setup_sales_scenario(
            product="SOY_OIL", quantity_lbs=1000, price_cents_per_lb=20,
            delivery_window_start="2026-09-15T00:00:00Z",
            delivery_window_end="2026-09-30T00:00:00Z", max_ffa_pct=0.5,
        )
        set_clock("2026-10-01T00:00:00Z")
        contract = read_sales_contract(base["contract"]["id"])
        assert contract["status"] == "DEFAULTED"
        assert contract["claim_cents"] == 2000
        buyer = read_buyer(base["buyer"]["id"])
        assert buyer["open_claims_count"] == 1
        assert buyer["status"] == "ACTIVE"

    def test_forced_pricing_fires_when_clock_passes_deadline(self, api):
        """PRD §3.9: "Every `DEFERRED` contract whose `pricing_deadline` has fallen behind the new clock and whose pricing is not yet `PRICED` is priced in full: the forced election covers all remaining unpriced bushels at the bean futures quote as-of the deadline date itself, is appended to `elections` with an `origin` of `FORCED` and an `elected_at` of the `pricing_deadline`, and runs the final accrual leg from `last_accrual_date` through the deadline before the pool empties".
        Deadline 2026-09-10, quote 1100 as-of 09-01, pool of 100 from 09-01:
        accrual 9 days x 100 bu x 1 cent = 900.

        Design: Corner/state_machines/forced_pricing_fires_when_clock_passes_deadline
        """
        site = setup_origination_site()
        post_bean_quote("2026-12", 1100, "2026-09-01T00:00:00Z")
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=100, futures_month="2026-12",
            pricing_deadline="2026-09-10T00:00:00Z",
            storage_rate_cents_per_bushel_day=1,
        )
        create_and_apply_ticket(contract["id"], gross_bushels=100)
        set_clock("2026-09-11T00:00:00Z")
        refreshed = read_contract(contract["id"])
        assert refreshed["pricing_status"] == "PRICED"
        assert float(refreshed["priced_bushels"]) == pytest.approx(100)
        assert refreshed["priced_value_cents"] == 110000
        assert refreshed["accrued_storage_cents"] == 900
        forced = refreshed["elections"][-1]
        assert forced["origin"] == "FORCED"
        assert forced["unit_price_cents"] == 1100
        assert parse_iso(forced["elected_at"]) == parse_iso(
            "2026-09-10T00:00:00Z"
        ), "the forced election is stamped at the deadline, not the sweep time"


class TestPreconditionEnforcement:
    def test_hedge_offset_from_entered_returns_not_confirmed(self, api):
        """PRD §3.7: "A `CrushTrader` offsets a `CONFIRMED` position — any other state is `ERR_POSITION_NOT_CONFIRMED". Offsetting an ENTERED position
        fails 409; the position stays ENTERED with realized_pnl_cents null.

        Design: Corner/state_machines/hedge_offset_from_entered_returns_not_confirmed
        """
        post_crush_quote_set("2026-11")
        position = enter_board_position()
        resp = api_client.offset_board_crush_position(position["id"], TRADER)
        validate_error(resp, ApiErrorId.ERR_POSITION_NOT_CONFIRMED)
        after = api_client.get_board_crush_position(position["id"], TRADER)
        data = validate_success(after)
        assert data["status"] == "ENTERED"
        assert data["realized_pnl_cents"] is None

    def test_pricing_election_at_exact_deadline_allowed(self, api):
        """PRD §3.4: "For a `DEFERRED` contract the election must arrive while the logical clock is still on or before the `pricing_deadline"; PRD
        §3.9 fires only on contracts "whose `pricing_deadline` has fallen behind the new clock". With the clock exactly at the deadline the sweep has
        not fired and the client election succeeds with origin CLIENT.

        Design: Corner/state_machines/pricing_election_at_exact_deadline_allowed
        """
        site = setup_origination_site()
        post_bean_quote("2026-12", 1100, "2026-09-01T00:00:00Z")
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=100, futures_month="2026-12",
            pricing_deadline="2026-09-10T00:00:00Z",
            storage_rate_cents_per_bushel_day=1,
        )
        set_clock("2026-09-10T00:00:00Z")
        updated = elect_price(contract["id"], 100)
        assert updated["pricing_status"] == "PRICED"
        assert updated["elections"][-1]["origin"] == "CLIENT"
