"""Container lifecycle: gate-out guards, holds, return-location selection and status."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_active_contract,
    create_terminal,
    create_terminal_with_labor_day,
    create_return_location,
    create_available_container,
    gate_out,
    return_empty,
    set_clock,
    set_hold_payload,
    validate_error,
    validate_success,
)

CM = {"X-User-ID": "cm-1", "X-User-Role": "ContractManager"}
TO = {"X-User-ID": "to-1", "X-User-Role": "TerminalOperator"}
EC = {"X-User-ID": "ec-1", "X-User-Role": "EquipmentController"}
BA = {"X-User-ID": "ba-1", "X-User-Role": "BillingAgent"}


def _stack(account_code, contract_ref, with_holiday=False, **contract_kw):
    account = create_account(account_code=account_code, legal_name=f"{account_code} Co")
    defaults = dict(demurrage_free_days=2, detention_free_days=5, saturday_counts_as_free_day=False)
    defaults.update(contract_kw)
    contract = create_active_contract(account["id"], contract_ref=contract_ref, **defaults)
    if with_holiday:
        terminal = create_terminal_with_labor_day(terminal_code="OAK")
    else:
        terminal = create_terminal(terminal_code="OAK")
    return account, contract, terminal


class TestContainerInitialState:
    def test_new_container_is_discharged(self):
        """PRD §3.3: "The container is born `DISCHARGED`."

        Design: Corner/state_machines/container_initial_state_is_discharged
        """
        account, contract, terminal = _stack("ACCT-IS", "CTR-IS")
        resp = api_client.create_container(
            {
                "container_number": "MATU0001027",
                "equipment_type": "DRY40",
                "customer_account_id": account["id"],
                "service_contract_id": contract["id"],
                "terminal_id": terminal["id"],
                "discharge_ts": "2026-09-01T12:00:00Z",
                "available_ts": "2026-09-02T12:00:00Z",
            },
            TO,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DISCHARGED"


class TestGateOutHeldContainer:
    def test_gate_out_needs_available_state_before_hold_check(self):
        """PRD §2.10: "Fifth, the target resource must be in a state from which
        the requested transition exists, otherwise `ERR_INVALID_STATE`. Sixth
        come container-hold safety checks (`ERR_CONTAINER_HELD`)."
        PRD §3.4: "A gate-out performed by a `TerminalOperator` moves the
        container from `AVAILABLE` to `GATE_OUT`".

        Design: Difficulty/priority_pair_validation_conflict/gate_out_held_container_vs_closed_account_state_vs_safety
        """
        account, contract, terminal = _stack("ACCT-I2", "CTR-I2")
        create_return_location(terminal["id"], location_code="LOC-1")
        container = validate_success(api_client.create_container(
            {
                "container_number": "MATU0000200",
                "equipment_type": "DRY40",
                "customer_account_id": account["id"],
                "service_contract_id": contract["id"],
                "terminal_id": terminal["id"],
                "discharge_ts": "2026-09-08T12:00:00Z",
                "available_ts": "2026-09-09T12:00:00Z",
            },
            TO,
        ), 201)
        # No hold at all: gate-out from DISCHARGED still fails on state
        resp = api_client.gate_out_container(
            container["id"],
            {"slot_override": True, "slot_override_reason": "waived"},
            TO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_error_precedes_hold_error_and_hold_blocks_after_available(self):
        """PRD §2.10: "Fifth, the target resource must be in a state from which
        the requested transition exists, otherwise `ERR_INVALID_STATE`. Sixth
        come container-hold safety checks (`ERR_CONTAINER_HELD`)."
        PRD §2.10: "A request that fails several checks reports the earliest
        failure in this order, never a later one."

        Design: Difficulty/priority_pair_validation_conflict/gate_out_held_container_vs_closed_account_state_vs_safety
        """
        account, contract, terminal = _stack("ACCT-I", "CTR-I")
        create_return_location(terminal["id"], location_code="LOC-1")
        container = validate_success(api_client.create_container(
            {
                "container_number": "MATU0000102",
                "equipment_type": "DRY40",
                "customer_account_id": account["id"],
                "service_contract_id": contract["id"],
                "terminal_id": terminal["id"],
                "discharge_ts": "2026-09-08T12:00:00Z",
                "available_ts": "2026-09-09T12:00:00Z",
            },
            TO,
        ), 201)
        # Place a hold while the container is still DISCHARGED
        validate_success(
            api_client.set_container_hold(container["id"], set_hold_payload("CUSTOMS_HOLD", "PLACE"), TO)
        )
        # Gate-out from DISCHARGED: state error wins over the hold safety check
        first = api_client.gate_out_container(
            container["id"],
            {"slot_override": True, "slot_override_reason": "waived"},
            TO,
        )
        validate_error(first, ApiErrorId.ERR_INVALID_STATE)

        validate_success(api_client.mark_container_available(container["id"], TO))
        second = api_client.gate_out_container(
            container["id"],
            {"slot_override": True, "slot_override_reason": "waived"},
            TO,
        )
        validate_error(second, ApiErrorId.ERR_CONTAINER_HELD)

        final = validate_success(api_client.get_container(container["id"], TO))
        assert final["status"] == "AVAILABLE"

    def test_gate_out_blocked_only_while_hold_active(self):
        """PRD §3.4: "First, no active `CUSTOMS_HOLD` or `USDA_HOLD` may remain
        in `hold_flags`; an attempt to gate out a held container is rejected
        with `ERR_CONTAINER_HELD`."
        PRD §3.3: "A hold whose `released_ts` is null is active."

        Design: Difficulty/cross_entity_state_dependency/gate_out_blocked_by_container_hold_overlay
        """
        account, contract, terminal = _stack("ACCT-M", "CTR-M")
        create_return_location(terminal["id"], location_code="LOC-1")
        held = create_available_container(
            account, contract, terminal,
            container_number="MATU0000151",
            discharge_ts="2026-09-08T12:00:00Z",
            available_ts="2026-09-09T12:00:00Z",
        )
        validate_success(api_client.set_container_hold(
            held["id"], set_hold_payload("CUSTOMS_HOLD", "PLACE"), TO
        ))
        released = create_available_container(
            account, contract, terminal,
            container_number="MATU0000169",
            discharge_ts="2026-09-08T12:00:00Z",
            available_ts="2026-09-09T12:00:00Z",
        )
        validate_success(api_client.set_container_hold(
            released["id"], set_hold_payload("CUSTOMS_HOLD", "PLACE"), TO
        ))
        validate_success(api_client.set_container_hold(
            released["id"], set_hold_payload("CUSTOMS_HOLD", "RELEASE"), TO
        ))
        set_clock("2026-09-10T12:00:00Z", TO)

        blocked = api_client.gate_out_container(
            held["id"], {"slot_override": True, "slot_override_reason": "waived"}, TO
        )
        validate_error(blocked, ApiErrorId.ERR_CONTAINER_HELD)

        ok = api_client.gate_out_container(
            released["id"], {"slot_override": True, "slot_override_reason": "waived"}, TO
        )
        assert validate_success(ok)["status"] == "GATE_OUT"

        held_now = validate_success(api_client.get_container(held["id"], TO))
        assert held_now["status"] == "AVAILABLE"


    def test_usda_hold_also_blocks_gate_out(self):
        """PRD §3.4: "First, no active `CUSTOMS_HOLD` or `USDA_HOLD` may remain
        in `hold_flags`; an attempt to gate out a held container is rejected
        with `ERR_CONTAINER_HELD`."

        Design: Difficulty/cross_entity_state_dependency/gate_out_blocked_by_container_hold_overlay
        """
        account, contract, terminal = _stack("ACCT-M2", "CTR-M2")
        create_return_location(terminal["id"], location_code="LOC-1")
        container = create_available_container(
            account, contract, terminal,
            container_number="MATU0000210",
            discharge_ts="2026-09-08T12:00:00Z",
            available_ts="2026-09-09T12:00:00Z",
        )
        validate_success(api_client.set_container_hold(
            container["id"], set_hold_payload("USDA_HOLD", "PLACE"), TO
        ))
        set_clock("2026-09-10T12:00:00Z", TO)
        resp = api_client.gate_out_container(
            container["id"], {"slot_override": True, "slot_override_reason": "waived"}, TO
        )
        validate_error(resp, ApiErrorId.ERR_CONTAINER_HELD)
        still = validate_success(api_client.get_container(container["id"], TO))
        assert still["status"] == "AVAILABLE"


class TestReturnLocationSelection:
    def test_selector_picks_highest_capacity_eligible_location(self):
        """PRD §3.4: "among `EquipmentReturnLocation` records whose
        `terminal_id` matches the container's terminal, whose
        `accepts_equipment_types` array contains the container's
        `equipment_type`, and whose status is `OPEN` or `RESTRICTED`, it picks
        the location with the highest `daily_empty_capacity`, breaking ties by
        ascending `location_code`, and records the choice in
        `assigned_return_location_id`".

        Design: Corner/endpoints/gate_out_selector_picks_highest_capacity_location
        """
        account, contract, terminal = _stack("ACCT-SEL", "CTR-SEL")
        create_return_location(
            terminal["id"], location_code="LOC-A", daily_empty_capacity=5
        )
        best = create_return_location(
            terminal["id"], location_code="LOC-B", daily_empty_capacity=20
        )
        create_return_location(
            terminal["id"], location_code="LOC-C",
            accepts_equipment_types=["REEFER40"], daily_empty_capacity=99,
        )
        container = create_available_container(
            account, contract, terminal,
            container_number="MATU0001142",
            discharge_ts="2026-09-08T12:00:00Z",
            available_ts="2026-09-09T12:00:00Z",
        )
        gated = gate_out(container["id"], clock_ts="2026-09-10T12:00:00Z")
        assert gated["assigned_return_location_id"] == best["id"]

    def test_selector_empty_pool_rejects_gate_out(self):
        """PRD §3.4: "if the eligible pool is empty the gate-out fails with
        `ERR_NO_RETURN_LOCATION`."

        Design: Corner/endpoints/gate_out_selector_empty_pool_rejected
        """
        account, contract, terminal = _stack("ACCT-NP", "CTR-NP")
        create_return_location(
            terminal["id"], location_code="LOC-R",
            accepts_equipment_types=["REEFER40"], daily_empty_capacity=99,
        )
        container = create_available_container(
            account, contract, terminal,
            container_number="MATU0001159",
            discharge_ts="2026-09-08T12:00:00Z",
            available_ts="2026-09-09T12:00:00Z",
        )
        set_clock("2026-09-10T12:00:00Z", TO)
        resp = api_client.gate_out_container(
            container["id"], {"slot_override": True, "slot_override_reason": "waived"}, TO
        )
        validate_error(resp, ApiErrorId.ERR_NO_RETURN_LOCATION)
        still = validate_success(api_client.get_container(container["id"], TO))
        assert still["status"] == "AVAILABLE"


class TestReturnEmptyBlockedByLocationStatus:
    def test_closed_location_blocks_return_until_reassignment(self):
        """PRD §3.4: "the assignment must exist; the location must not be
        `CLOSED`, else `ERR_RETURN_LOCATION_CLOSED`".
        PRD §3.4: "While the container is in `GATE_OUT`, an
        `EquipmentController` may reassign the return depot by supplying a new
        `assigned_return_location_id`."

        Design: Difficulty/cross_entity_state_dependency/return_empty_blocked_by_return_location_status
        """
        account, contract, terminal = _stack("ACCT-N", "CTR-N")
        loc1 = create_return_location(
            terminal["id"], location_code="LOC-1", daily_empty_capacity=10
        )
        loc2 = create_return_location(
            terminal["id"], location_code="LOC-2", daily_empty_capacity=5
        )
        container = create_available_container(
            account, contract, terminal,
            container_number="MATU0000177",
            discharge_ts="2026-09-08T12:00:00Z",
            available_ts="2026-09-09T12:00:00Z",
        )
        gated = gate_out(container["id"], clock_ts="2026-09-10T12:00:00Z")
        assert gated["assigned_return_location_id"] == loc1["id"]

        validate_success(api_client.set_return_location_status(loc1["id"], {"status": "CLOSED"}, EC))
        blocked = api_client.return_empty_container(container["id"], EC)
        validate_error(blocked, ApiErrorId.ERR_RETURN_LOCATION_CLOSED)

        validate_success(api_client.reassign_return_location(
            container["id"], {"assigned_return_location_id": loc2["id"]}, EC
        ))
        returned = validate_success(api_client.return_empty_container(container["id"], EC))
        assert returned["status"] == "EMPTY_RETURNED"

    def test_reassigned_location_serving_terminal_allows_return(self):
        """PRD §3.4: "Returning the empty — again an `EquipmentController`
        action — moves the container from `GATE_OUT` to `EMPTY_RETURNED` and is
        checked against the assigned depot".

        Design: Difficulty/cross_entity_state_dependency/return_empty_blocked_by_return_location_status
        """
        account, contract, terminal = _stack("ACCT-N2", "CTR-N2")
        loc1 = create_return_location(
            terminal["id"], location_code="LOC-1", daily_empty_capacity=10
        )
        loc2 = create_return_location(
            terminal["id"], location_code="LOC-2", daily_empty_capacity=5
        )
        container = create_available_container(
            account, contract, terminal,
            container_number="MATU0000301",
            discharge_ts="2026-09-08T12:00:00Z",
            available_ts="2026-09-09T12:00:00Z",
        )
        gated = gate_out(container["id"], clock_ts="2026-09-10T12:00:00Z")
        validate_success(api_client.reassign_return_location(
            container["id"], {"assigned_return_location_id": loc2["id"]}, EC
        ))
        returned = validate_success(api_client.return_empty_container(container["id"], EC))
        assert returned["status"] == "EMPTY_RETURNED"
        assert returned["assigned_return_location_id"] == loc2["id"]
