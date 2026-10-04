"""RMA logistics: ship-by SLA formula, branch fork, and branch violations."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_ts_equal,
    make_coverage,
    make_device,
    make_service_contract,
    set_clock,
    setup_covered_device,
    setup_open_rma,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LOGISTICS = TEST_USERS["logistics_agent_headers"]


class TestRmaShipBySla:
    def test_advance_4h_ship_by_opened_plus_four_hours(self, api):
        """PRD §3.7: "For `ADVANCE_4H` the replacement must ship within 14400
        seconds — four hours — of `opened_at`".

        Design: Difficulty/combinatorial_formula/rma_sla_branch_conditional_formula
        """
        account, va, device, contract, coverage = setup_covered_device(
            service_level="ADVANCE_4H")
        set_clock("2026-09-10T00:00:00Z")
        rma = validate_success(api.create_rma_case(
            {"contract_coverage_id": coverage["id"], "failure_description": "psu dead"}, ADMIN),
            expected_status=201)
        assert_ts_equal(rma["opened_at"], "2026-09-10T00:00:00Z")
        assert_ts_equal(rma["ship_by"], "2026-09-10T04:00:00Z",
            "ADVANCE_4H ship_by must be opened_at + 4h")
        assert rma["sla_breached"] is False

    def test_advance_nbd_ship_by_opened_plus_24_hours(self, api):
        """PRD §3.7: "for `ADVANCE_NBD` the deadline is 86400 seconds —
        twenty-four hours, the next business day — after `opened_at`; both
        deadlines are recorded in `ship_by`."

        Design: Difficulty/combinatorial_formula/rma_sla_branch_conditional_formula
        """
        account, va, device, contract, coverage = setup_covered_device(
            service_level="ADVANCE_NBD")
        set_clock("2026-09-10T00:00:00Z")
        rma = validate_success(api.create_rma_case(
            {"contract_coverage_id": coverage["id"], "failure_description": "fan dead"}, ADMIN),
            expected_status=201)
        assert_ts_equal(rma["ship_by"], "2026-09-11T00:00:00Z",
            "ADVANCE_NBD ship_by must be opened_at + 24h")
        assert rma["sla_breached"] is False


class TestRmaBranchFork:
    def test_advance_branch_ships_first(self, api):
        """PRD §3.7: "On the advance branches (`ADVANCE_NBD`, `ADVANCE_4H`),
        a `LogisticsAgent` or the `PlatformAdmin` ships the replacement first,
        moving the case from `OPENED` to `REPLACEMENT_SHIPPED`".

        Design: Difficulty/non_linear_state_machine/rma_branching_fork_by_service_level
        """
        account, va, device, contract, coverage, rma = setup_open_rma(
            service_level="ADVANCE_NBD")
        shipped = validate_success(api.ship_replacement(rma["id"], LOGISTICS))
        assert shipped["status"] == "REPLACEMENT_SHIPPED"
        assert_ts_equal(shipped["ship_by"], "2026-09-02T00:00:00Z",
            "opened at the default clock + 86400s")

    def test_depot_branch_receives_first_and_has_no_ship_by(self, api):
        """PRD §3.7: "On the depot branch (`DEPOT_RETURN`), the sequence
        reverses: the defective unit is received first (`OPENED` to
        `DEFECTIVE_RETURNED`), and only then may the replacement ship
        (`DEFECTIVE_RETURNED` to `REPLACEMENT_SHIPPED`)". PRD §3.7: "For
        `DEPOT_RETURN` there is no advance ship commitment and `ship_by` is
        null."

        Design: Difficulty/non_linear_state_machine/rma_branching_fork_by_service_level
        """
        account, va, device, contract, coverage, rma = setup_open_rma(
            service_level="DEPOT_RETURN")
        assert rma["ship_by"] is None, "depot branch carries no advance ship SLA"
        received = validate_success(api.receive_defective(rma["id"], LOGISTICS))
        assert received["status"] == "DEFECTIVE_RETURNED"
        shipped = validate_success(api.ship_replacement(rma["id"], LOGISTICS))
        assert shipped["status"] == "REPLACEMENT_SHIPPED"


class TestRmaBranchViolation:
    def test_depot_ship_from_opened_rejected(self, api):
        """PRD §3.7: "A ship attempt from `OPENED` on a depot contract, or a
        receive-defective attempt from `OPENED` on an advance contract,
        violates the branch and is rejected with `ERR_RMA_BRANCH_VIOLATION`
        (HTTP 409)."

        Design: Corner/state_machines/rma_depot_ship_before_receive_branch_violation
        """
        account, va, device, contract, coverage, rma = setup_open_rma(
            service_level="DEPOT_RETURN")
        resp = api.ship_replacement(rma["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_RMA_BRANCH_VIOLATION)

    def test_cancelled_rma_is_terminal(self, api):
        """PRD §3.7: "A case still `OPENED` may instead be cancelled by an
        `AccountAdmin` of the owning account, a delegated `PartnerManager`, or
        the `PlatformAdmin`, moving it to the terminal `CANCELLED`."

        Design: Corner/state_machines/rma_terminal_lockdown_cancelled
        """
        account, va, device, contract, coverage, rma = setup_open_rma(
            service_level="DEPOT_RETURN")
        cancelled = validate_success(api.cancel_rma_case(rma["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED"
        resp = api.receive_defective(rma["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
