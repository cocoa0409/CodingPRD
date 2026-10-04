"""Home lifecycle: parallel state dimensions, build advance, cycle time, sales."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_home_to,
    approve_contract,
    close_contract,
    create_contract_for_home,
    get_success_data,
    sell_and_close_home,
    set_clock,
    setup_ready_community,
    start_home,
    validate_error,
)
from test_helpers import TEST_USERS

_CM = TEST_USERS["community_manager_headers"]
_SA = TEST_USERS["sales_agent_headers"]


class TestParallelDimensions:
    def test_build_advance_survives_sales_cycle(self, api, community_manager_headers):
        """PRD §3.7: "A home carries two independent state dimensions on one row:
        `build_stage` tracks construction (`PERMITTED`, `FOUNDATION`, `FRAME`,
        `DRYWALL`, `COMPLETE`, `CLOSED`) and `sales_status` tracks the commercial
        side (`UNSOLD`, `RESERVED`, `SOLD`, `CLOSED_SALE`). They evolve
        independently — a home can be framed while unsold, or complete and merely
        reserved."

        Design: Difficulty/non_linear_state_machine/home_parallel_dimensions_with_cancel_cycle
        """
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        home = advance_home_to(api, home["id"], "FRAME")
        sc = create_contract_for_home(api, home["id"])
        get_success_data(api.terminate_sales_contract(sc["id"], _SA))
        home = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert home["build_stage"] == "FRAME"
        assert home["sales_status"] == "UNSOLD"

    def test_sales_cycle_does_not_touch_build_stage(self, api, community_manager_headers):
        """PRD §3.7: "They evolve independently — a home can be framed while
        unsold, or complete and merely reserved."

        Design: Difficulty/non_linear_state_machine/home_parallel_dimensions_with_cancel_cycle
        """
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        home = advance_home_to(api, home["id"], "FRAME")
        sc = create_contract_for_home(api, home["id"])
        mid = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert mid["sales_status"] == "RESERVED"
        assert mid["build_stage"] == "FRAME"
        get_success_data(api.terminate_sales_contract(sc["id"], _SA))
        end = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert end["sales_status"] == "UNSOLD"
        assert end["build_stage"] == "FRAME"


class TestRenegotiationCycle:
    def test_renegotiate_returns_to_pending_with_count(self, api, community_manager_headers):
        """PRD §3.9: "A `SALES_AGENT` can renegotiate, which moves the contract
        from `APPROVED` back to `PENDING`, increments `renegotiation_count` by 1,
        and flips the home from `SOLD` back to `RESERVED`".

        Design: Difficulty/non_linear_state_machine/sales_contract_renegotiation_cycle
        """
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        sc = create_contract_for_home(api, home["id"])
        approve_contract(api, sc["id"])
        reneg = get_success_data(api.renegotiate_sales_contract(
            sc["id"], {"contract_price_cents": 40_500_000}, _SA))
        assert reneg["state"] == "PENDING"
        assert reneg["renegotiation_count"] == 1
        assert reneg["contract_price_cents"] == 40_500_000

    def test_reapproval_after_renegotiate_returns_home_to_sold(
            self, api, community_manager_headers):
        """PRD §3.9: "The cycle `APPROVED` back to `PENDING` and forward to
        `APPROVED` may repeat, with `renegotiation_count` counting each return to
        `PENDING`; the renegotiate call carries a new `contract_price_cents`,
        which is then re-tested against the floor at the next approval."

        Design: Difficulty/non_linear_state_machine/sales_contract_renegotiation_cycle
        """
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        sc = create_contract_for_home(api, home["id"])
        approve_contract(api, sc["id"])
        get_success_data(api.renegotiate_sales_contract(
            sc["id"], {"contract_price_cents": 40_500_000}, _SA))
        reapproved = get_success_data(api.approve_sales_contract(sc["id"], _CM))
        assert reapproved["state"] == "APPROVED"
        home = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert home["sales_status"] == "SOLD"


class TestAdvanceStageTerminal:
    def test_advance_from_complete_rejected(self, api, community_manager_headers):
        """PRD §3.7: "Each advance requires the home to currently sit in the
        expected prior stage (otherwise `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/advance_stage_from_complete_returns_invalid_state
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        advance_home_to(api, home["id"], "COMPLETE")
        resp = api.advance_stage(home["id"], community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_complete_home_stays_complete_after_rejected_advance(
            self, api, community_manager_headers):
        """PRD §3.7: "Each advance requires the home to currently sit in the
        expected prior stage (otherwise `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/advance_stage_from_complete_returns_invalid_state
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        advance_home_to(api, home["id"], "COMPLETE")
        api.advance_stage(home["id"], community_manager_headers)
        home = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert home["build_stage"] == "COMPLETE"


class TestCycleTime:
    def test_cycle_time_days_floor_whole_days(self, api, community_manager_headers,
                                              division_president_headers):
        """PRD §3.7: "The advance into `COMPLETE` is special: it stamps
        `completed_at` with the clock, computes `cycle_time_days` as the whole
        days from the home's `created_at` to `completed_at` (fractional days
        discarded)".

        Design: Corner/calculations/cycle_time_days_from_permit_to_co
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        advance_home_to(api, home["id"], "DRYWALL")
        set_clock(api, "2026-09-21T00:00:00Z")
        home = get_success_data(api.advance_stage(home["id"], community_manager_headers))
        assert home["build_stage"] == "COMPLETE"
        assert home["cycle_time_days"] == 20

    def test_completed_at_stamped_with_clock(self, api, community_manager_headers,
                                             division_president_headers):
        """PRD §3.7: "The advance into `COMPLETE` is special: it stamps
        `completed_at` with the clock, computes `cycle_time_days` as the whole
        days from the home's `created_at` to `completed_at` (fractional days
        discarded)".

        Design: Corner/calculations/cycle_time_days_from_permit_to_co
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        advance_home_to(api, home["id"], "DRYWALL")
        set_clock(api, "2026-09-21T00:00:00Z")
        home = get_success_data(api.advance_stage(home["id"], community_manager_headers))
        assert home["completed_at"].startswith("2026-09-21T00:00:00")


class TestInitialStateAndLotConsumption:
    def test_home_born_permitted_unsold(self, api, community_manager_headers):
        """PRD §3.6: "A home that clears all six gates is created with
        `build_stage` `PERMITTED` and `sales_status` `UNSOLD`, and its arrival
        cascades: the lot flips from `BANKED` to `CONSUMED`".

        Design: Corner/state_machines/home_initial_state_and_lot_consumption
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        assert home["build_stage"] == "PERMITTED"
        assert home["sales_status"] == "UNSOLD"

    def test_lot_flips_banked_to_consumed(self, api, community_manager_headers):
        """PRD §3.6: "A home that clears all six gates is created with
        `build_stage` `PERMITTED` and `sales_status` `UNSOLD`, and its arrival
        cascades: the lot flips from `BANKED` to `CONSUMED`".

        Design: Corner/state_machines/home_initial_state_and_lot_consumption
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        lots_before = get_success_data(api.list_lots(env["community"]["id"],
                                                     community_manager_headers))
        assert all(lot["state"] == "BANKED" for lot in lots_before)
        start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        lots_after = get_success_data(api.list_lots(env["community"]["id"],
                                                    community_manager_headers))
        by_id = {lot["id"]: lot["state"] for lot in lots_after}
        assert by_id[env["lot_ids"][0]] == "CONSUMED"


class TestCloseRequiresCompleteHome:
    def test_close_on_frame_home_rejected(self, api, community_manager_headers):
        """PRD §3.9: "Closing is the terminal handshake, owned by the
        `COMMUNITY_MANAGER`. The contract must be `APPROVED` (else
        `ERR_INVALID_STATE`) and the home's `build_stage` must be `COMPLETE`
        (else `ERR_HOME_NOT_COMPLETE`) — a buyer cannot close on a home still
        standing at drywall."

        Design: Corner/state_machines/close_requires_home_complete
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        home = advance_home_to(api, home["id"], "FRAME")
        sc = create_contract_for_home(api, home["id"], contract_price_cents=40_400_000)
        approve_contract(api, sc["id"])
        resp = api.close_sales_contract(sc["id"], community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_HOME_NOT_COMPLETE, 409)

    def test_rejected_close_leaves_contract_approved(self, api, community_manager_headers):
        """PRD §3.9: "The contract must be `APPROVED` (else `ERR_INVALID_STATE`)
        and the home's `build_stage` must be `COMPLETE` (else
        `ERR_HOME_NOT_COMPLETE`)".

        Design: Corner/state_machines/close_requires_home_complete
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        home = advance_home_to(api, home["id"], "FRAME")
        sc = create_contract_for_home(api, home["id"], contract_price_cents=40_400_000)
        approve_contract(api, sc["id"])
        api.close_sales_contract(sc["id"], community_manager_headers)
        sc_after = get_success_data(api.get_sales_contract(sc["id"], community_manager_headers))
        assert sc_after["state"] == "APPROVED"


class TestContractOnReservedHome:
    def test_second_contract_on_reserved_home_rejected(self, api, sales_agent_headers):
        """PRD §3.9: "A `SALES_AGENT` writes a sales contract against a home by
        naming the `home_id`, the `buyer_name`, and the negotiated
        `contract_price_cents`. The home must be `UNSOLD`, else
        `ERR_HOME_NOT_UNSOLD`."

        Design: Corner/state_machines/sales_contract_create_on_sold_home_rejected
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        create_contract_for_home(api, home["id"])
        resp = api.create_sales_contract(
            {"home_id": home["id"], "buyer_name": "Buyer B",
             "contract_price_cents": 40_100_000}, sales_agent_headers)
        validate_error(resp, ApiErrorId.ERR_HOME_NOT_UNSOLD, 409)

    def test_home_remains_reserved_after_rejection(self, api, sales_agent_headers,
                                                   community_manager_headers):
        """PRD §3.9: "A `SALES_AGENT` writes a sales contract against a home by
        naming the `home_id`, the `buyer_name`, and the negotiated
        `contract_price_cents`. The home must be `UNSOLD`, else
        `ERR_HOME_NOT_UNSOLD`."

        Design: Corner/state_machines/sales_contract_create_on_sold_home_rejected
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        create_contract_for_home(api, home["id"])
        api.create_sales_contract(
            {"home_id": home["id"], "buyer_name": "Buyer B",
             "contract_price_cents": 40_100_000}, sales_agent_headers)
        home = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert home["sales_status"] == "RESERVED"


class TestTerminateClosedContract:
    def test_terminate_closed_returns_not_terminable(self, api, sales_agent_headers):
        """PRD §3.9: "A `CLOSED` or already-`TERMINATED` contract cannot be
        terminated; the attempt is rejected with
        `ERR_SALES_CONTRACT_NOT_TERMINABLE` (HTTP 409)."

        Design: Corner/state_machines/terminate_closed_contract_returns_not_terminable
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        advance_home_to(api, home["id"], "COMPLETE")
        sc = sell_and_close_home(api, home["id"], 41_200_000)
        resp = api.terminate_sales_contract(sc["id"], sales_agent_headers)
        validate_error(resp, ApiErrorId.ERR_SALES_CONTRACT_NOT_TERMINABLE, 409)

    def test_home_remains_closed_sale_after_rejected_terminate(
            self, api, sales_agent_headers, community_manager_headers):
        """PRD §3.9: "A `CLOSED` or already-`TERMINATED` contract cannot be
        terminated; the attempt is rejected with
        `ERR_SALES_CONTRACT_NOT_TERMINABLE` (HTTP 409)."

        Design: Corner/state_machines/terminate_closed_contract_returns_not_terminable
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        advance_home_to(api, home["id"], "COMPLETE")
        sc = sell_and_close_home(api, home["id"], 41_200_000)
        api.terminate_sales_contract(sc["id"], sales_agent_headers)
        home = get_success_data(api.get_home(home["id"], community_manager_headers))
        assert home["sales_status"] == "CLOSED_SALE"


class TestPriceFloorAtApproval:
    def test_approve_below_net_floor_rejected(self, api, community_manager_headers):
        """PRD §3.9: "the `contract_price_cents` must be at least the home's
        `net_effective_price_cents` at approval time — incentives included —
        else the approval is rejected with `ERR_PRICE_BELOW_NET_FLOOR`
        (HTTP 422)."

        Design: Corner/validations/approve_below_net_floor_rejected
        """
        from test_helpers import create_incentive
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        create_incentive(api, env["community"]["id"], value_cents=500_000)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        advance_home_to(api, home["id"], "FRAME")
        sc = create_contract_for_home(api, home["id"], contract_price_cents=39_000_000)
        resp = api.approve_sales_contract(sc["id"], community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PRICE_BELOW_NET_FLOOR, 422)


class TestFloorUsesCurrentStagePrice:
    def test_stale_price_rejected_after_stage_advance(self, api, community_manager_headers):
        """PRD §3.9: "Because the floor is evaluated at approval time, a
        mid-flight incentive activation or a build-stage advance between contract
        creation and approval changes what price will clear."

        Design: Corner/state_machines/contract_execution_price_floor_uses_current_stage_price
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        sc = create_contract_for_home(api, home["id"], contract_price_cents=40_000_000)
        advance_home_to(api, home["id"], "FRAME")  # net floor rises to 40,400,000
        resp = api.approve_sales_contract(sc["id"], community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PRICE_BELOW_NET_FLOOR, 422)


class TestHomeStatusPartitionConserved:
    def test_approve_terminate_pair_restores_standing_count(
            self, api, community_manager_headers):
        """PRD §3.9: "Termination is where the deepest cascade in the system
        lives, and every link matters: 1. The home returns to `UNSOLD` — from
        `RESERVED` when the terminated contract was `PENDING`, from `SOLD` when
        it was `APPROVED`. 2. The community's `standing_spec_count` increases by
        1 and its posture is recomputed."

        Design: Difficulty/compensating_invariant/home_status_partition_conserved_under_approve_terminate
        """
        env = setup_ready_community(api, lot_count=5, max_starts=20, committed_units=20)
        h1 = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        start_home(api, env["community"]["id"], env["lot_ids"][1], env["series"]["id"])
        sc = create_contract_for_home(api, h1["id"])
        approve_contract(api, sc["id"])
        get_success_data(api.terminate_sales_contract(sc["id"], _SA))
        community = get_success_data(api.get_community(env["community"]["id"],
                                                       community_manager_headers))
        assert community["standing_spec_count"] == 2

    def test_approve_terminate_pair_restores_home_to_unsold(
            self, api, community_manager_headers):
        """PRD §3.9: "1. The home returns to `UNSOLD` — from `RESERVED` when the
        terminated contract was `PENDING`, from `SOLD` when it was `APPROVED`."

        Design: Difficulty/compensating_invariant/home_status_partition_conserved_under_approve_terminate
        """
        env = setup_ready_community(api, lot_count=5, max_starts=20, committed_units=20)
        h1 = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        start_home(api, env["community"]["id"], env["lot_ids"][1], env["series"]["id"])
        sc = create_contract_for_home(api, h1["id"])
        approve_contract(api, sc["id"])
        get_success_data(api.terminate_sales_contract(sc["id"], _SA))
        homes = get_success_data(api.list_community_homes(env["community"]["id"],
                                                          community_manager_headers))
        statuses = sorted(h["sales_status"] for h in homes)
        assert statuses == ["UNSOLD", "UNSOLD"]
        h1_after = get_success_data(api.get_home(h1["id"], community_manager_headers))
        assert h1_after["sales_status"] == "UNSOLD"
