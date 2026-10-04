"""State machine tests: cyclic and branching machines, terminal lockdown,
clock-driven expiry, and outage preconditions."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_municipality,
    make_boiler,
    make_active_agreement,
    make_delivery,
    make_received_delivery,
    make_accepted_delivery,
    make_outage_with_approved_plan,
    start_outage,
    create_metals_recovery_contract_payload,
    create_metals_recovery_batch_payload,
    create_daily_throughput_report_payload,
    create_outage_window_payload,
    create_diversion_plan_payload,
    create_diversion_leg_payload,
    set_clock,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CM = TEST_USERS["contracts_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


class TestMetalsBatchDisputeResolveCycle:
    def _setup_batch(self):
        contract = get_success_data(
            api_client.create_metals_recovery_contract(create_metals_recovery_contract_payload(), CM)
        )
        batch = get_success_data(
            api_client.create_metals_recovery_batch(
                create_metals_recovery_batch_payload(contract_id=contract["id"]), PO
            )
        )
        return batch

    def test_dispute_blocks_settle_until_resolve_returns_batch_to_recorded(self):
        """PRD §3.8: "Settling moves a `RECORDED` batch to the terminal `SETTLED` status, but only while its contract is `ACTIVE`. Disputing moves a `RECORDED` batch to `DISPUTED`, and resolving moves a `DISPUTED` batch back to `RECORDED`, recomputing every settlement field from the contract's current rates at resolution time."

        Design: Difficulty/non_linear_state_machine/metals_batch_dispute_resolve_cycle_recomputes
        """
        batch = self._setup_batch()
        assert batch["status"] == "RECORDED"

        get_success_data(api_client.dispute_metals_recovery_batch(batch["id"], CM))

        resp = api_client.settle_metals_recovery_batch(batch["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api_client.resolve_metals_recovery_batch(batch["id"], CM))
        settled = get_success_data(api_client.settle_metals_recovery_batch(batch["id"], CM))
        assert settled["status"] == "SETTLED"

    def test_full_cycle_recomputes_settlement_and_tracks_version(self):
        """PRD §3.8: "resolving moves a `DISPUTED` batch back to `RECORDED`, recomputing every settlement field from the contract's current rates at resolution time. Each transition increments the batch's `version`."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on related resources."

        Design: Difficulty/non_linear_state_machine/metals_batch_dispute_resolve_cycle_recomputes
        """
        batch = self._setup_batch()
        assert batch["version"] == 1

        get_success_data(api_client.dispute_metals_recovery_batch(batch["id"], CM))
        resp = api_client.settle_metals_recovery_batch(batch["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        get_success_data(api_client.resolve_metals_recovery_batch(batch["id"], CM))
        settled = get_success_data(api_client.settle_metals_recovery_batch(batch["id"], CM))

        # Rates unchanged, so the recomputed settlement matches the original.
        assert settled["net_settlement_cents"] == 290000
        # create + dispute + resolve + settle = 4 mutations (the rejected settle
        # is not a mutation).
        assert settled["version"] == 4


class TestBoilerDerateRestoreBranching:
    def test_derate_restore_then_decommission_walks_the_branching_machine(self):
        """PRD §3.4: "Restoring moves the boiler from `DERATED` back to `ONLINE` and clears `derated_capacity_mw` to null. Decommissioning is permanent: a boiler in `ONLINE` may be moved to the terminal `OFFLINE` status only when no outage window for that boiler is `SCHEDULED` or `ACTIVE`; attempting it otherwise is rejected with `ERR_OUTAGE_IN_PROGRESS`."
        PRD §2.6: "Target state — the target resource must be in a state from which the requested transition is declared, else `ERR_INVALID_STATE`"

        Design: Difficulty/non_linear_state_machine/boiler_derate_restore_branching_vs_outage_path
        """
        boiler = make_boiler()

        derated = get_success_data(api_client.derate_boiler(boiler["id"], {"derated_capacity_mw": 30}, PO))
        assert derated["status"] == "DERATED"
        restored = get_success_data(api_client.restore_boiler(boiler["id"], PO))
        assert restored["status"] == "ONLINE"
        assert restored["derated_capacity_mw"] is None

        derated = get_success_data(api_client.derate_boiler(boiler["id"], {"derated_capacity_mw": 25}, PO))
        assert derated["derated_capacity_mw"] == pytest.approx(25)

        # Decommission is only declared from ONLINE; DERATED must be rejected.
        resp = api_client.decommission_boiler(boiler["id"], PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api_client.restore_boiler(boiler["id"], PO))
        offline = get_success_data(api_client.decommission_boiler(boiler["id"], PO))
        assert offline["status"] == "OFFLINE"
        assert offline["derated_capacity_mw"] is None

    def test_offline_is_terminal_and_version_tracks_each_mutation(self):
        """PRD §3.4: "Decommissioning is permanent: a boiler in `ONLINE` may be moved to the terminal `OFFLINE` status only when no outage window for that boiler is `SCHEDULED` or `ACTIVE`"
        PRD §3.4: "Each of these transitions increments the boiler's `version`"

        Design: Difficulty/non_linear_state_machine/boiler_derate_restore_branching_vs_outage_path
        """
        boiler = make_boiler()
        get_success_data(api_client.derate_boiler(boiler["id"], {"derated_capacity_mw": 30}, PO))
        get_success_data(api_client.restore_boiler(boiler["id"], PO))
        get_success_data(api_client.derate_boiler(boiler["id"], {"derated_capacity_mw": 25}, PO))
        resp = api_client.decommission_boiler(boiler["id"], PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        get_success_data(api_client.restore_boiler(boiler["id"], PO))
        offline = get_success_data(api_client.decommission_boiler(boiler["id"], PO))

        # OFFLINE is terminal: derate from it must be rejected.
        resp = api_client.derate_boiler(boiler["id"], {"derated_capacity_mw": 10}, PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # create + derate + restore + derate + restore + decommission = 6.
        assert offline["version"] == 6


class TestWsaInitialState:
    def test_new_agreement_is_draft_and_delivery_against_it_is_rejected(self):
        """PRD §3.2: "A new agreement begins life in `DRAFT` state."
        PRD §3.3: "The delivery's agreement must also be `ACTIVE` for the receive to proceed."

        Design: Corner/state_machines/wsa_initial_state_is_draft_and_deliveries_rejected_until_active
        """
        m1 = make_municipality()
        from test_helpers import create_waste_supply_agreement_payload

        agreement = get_success_data(
            api_client.create_waste_supply_agreement(
                create_waste_supply_agreement_payload(municipality_id=m1["id"]), CM
            )
        )
        assert agreement["state"] == "DRAFT"

        # Scheduling is not state-gated, but receiving against a DRAFT agreement is.
        delivery = get_success_data(
            api_client.create_waste_delivery(
                {
                    "agreement_id": agreement["id"],
                    "manifest_ref": "MAN-1",
                    "tonnes": 10,
                    "heating_value_mj_per_kg": 10,
                    "delivered_at": "2026-09-02T08:00:00Z",
                },
                PO
            )
        )
        resp = api_client.receive_waste_delivery(delivery["id"], PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDeliveryTerminalStateLockdown:
    def test_accepted_delivery_rejects_all_further_transitions(self):
        """PRD §3.3: "`ACCEPTED`, `REJECTED`, and `DIVERTED` are the delivery's terminal states."
        PRD §2.6: "Target state — the target resource must be in a state from which the requested transition is declared, else `ERR_INVALID_STATE`"
        PRD §3.3: "both the delivery's and the agreement's `version` increment by one."

        Design: Corner/state_machines/delivery_terminal_states_reject_further_transitions
        """
        m1 = make_municipality()
        make_boiler()
        agreement = make_active_agreement(municipality_id=m1["id"])
        delivery, _ = make_accepted_delivery(agreement, manifest_ref="MAN-1")

        resp = api_client.receive_waste_delivery(delivery["id"], PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api_client.reject_waste_delivery(delivery["id"], {"reject_reason": "x"}, PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        fresh = validate_success(api_client.get_waste_delivery(delivery["id"], CM))
        assert fresh["status"] == "ACCEPTED"
        # create + receive + accept = 3.
        assert fresh["version"] == 3


class TestOutageStartRequiresApprovedPlan:
    def test_start_without_approved_plan_is_rejected(self):
        """PRD §3.4: "The operator may start an outage only when an approved diversion plan exists for it (see §3.5) — starting without one is rejected with `ERR_DIVERSION_PLAN_REQUIRED`"

        Design: Corner/state_machines/outage_start_requires_approved_plan
        """
        boiler = make_boiler()
        outage = get_success_data(
            api_client.create_outage_window(create_outage_window_payload(boiler_id=boiler["id"]), PO)
        )
        plan = get_success_data(
            api_client.create_diversion_plan(create_diversion_plan_payload(outage_id=outage["id"]), PO)
        )
        get_success_data(
            api_client.create_diversion_leg(plan["id"], create_diversion_leg_payload(planned_tonnes=400), PO)
        )
        # Plan has a leg but was never approved.
        resp = api_client.start_outage_window(
            outage["id"], {"expected_boiler_version": boiler["version"]}, PO
        )
        validate_error(resp, ApiErrorId.ERR_DIVERSION_PLAN_REQUIRED)

        fresh_outage = validate_success(api_client.get_outage_window(outage["id"], PO))
        fresh_boiler = validate_success(api_client.get_boiler(boiler["id"], PO))
        assert fresh_outage["status"] == "SCHEDULED"
        assert fresh_boiler["status"] == "ONLINE"


class TestFinalizedReportImmutable:
    def test_put_on_finalized_report_rejected_and_fields_frozen(self):
        """PRD §3.6: "Finalizing a report moves it from `DRAFT` to the terminal `FINALIZED` status and is permitted only when the report's `capacity_check` is `OK`"
        PRD §3.6: "While the report is `DRAFT` the operator may edit any of `waste_processed_tonnes`, `avg_heating_value_mj_per_kg`, and `operating_hours`; every create and every such edit recomputes all computed fields and each edit increments the report's `version`."

        Design: Corner/state_machines/report_finalized_is_immutable
        """
        make_boiler(max_thermal_capacity_mw=150, max_steam_tph=500)
        # 540 * 10.0 * 1000 / 3600 / 10 = 150.000 MW == 150 MW capacity.
        report = get_success_data(
            api_client.create_daily_throughput_report(
                create_daily_throughput_report_payload(
                    report_date="2026-09-11",
                    waste_processed_tonnes=540,
                    avg_heating_value_mj_per_kg=10.0,
                    operating_hours=10,
                ),
                PO,
            )
        )
        get_success_data(api_client.finalize_daily_throughput_report(report["id"], PO))

        resp = api_client.update_daily_throughput_report(
            report["id"], {"waste_processed_tonnes": 100}, PO
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        frozen = validate_success(api_client.get_daily_throughput_report(report["id"], PO))
        assert frozen["thermal_input_mw"] == pytest.approx(150.0, abs=1e-9)
        assert frozen["status"] == "FINALIZED"


class TestWsaClockExpiry:
    def test_clock_past_term_end_expires_agreement_and_blocks_terminate(self):
        """PRD §2.4: "Advancing the clock fires any system transitions whose preconditions depend on the time — in particular, an `ACTIVE` waste supply agreement whose `term_end` has been reached transitions to `EXPIRED`, and an `ACTIVE` power purchase agreement whose `term_end` has been reached transitions to `EXPIRED`."
        PRD §3.2: "Agreements expire automatically: when the logical clock reaches or passes an `ACTIVE` agreement's `term_end`, the agreement's state becomes `EXPIRED` and its `version` increments."
        PRD §3.2: "`TERMINATED` is the only terminal state reachable by direct action; agreements in `EXPIRED` or `TERMINATED` state take no further transitions."

        Design: Corner/state_machines/wsa_clock_expiry_auto_transition
        """
        m1 = make_municipality()
        agreement = make_active_agreement(
            municipality_id=m1["id"],
            term_start="2026-01-01T00:00:00Z",
            term_end="2026-09-10T00:00:00Z",
            guaranteed_annual_tonnage=100,
        )

        set_clock("2026-09-10T00:00:00Z")

        fresh = validate_success(api_client.get_waste_supply_agreement(agreement["id"], CM))
        assert fresh["state"] == "EXPIRED"

        resp = api_client.terminate_waste_supply_agreement(agreement["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
