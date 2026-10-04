"""Cascading side effects and derived-field reconciliation: case close fans
out to truck, fleet, bay, and campaign; open_case_count stays consistent."""
import pytest

from test_helpers import (
    setup_case_in_state,
    setup_campaign_with_completion,
    setup_clock,
    setup_full_environment,
    validate_paginated,
    validate_success,
    create_case_payload,
)


class TestCaseCloseCascade:
    def test_case_close_cascades_truck_fleet_bay_campaign(self, api):
        """PRD §3.8: "the fleet's `total_downtime_hours` is incremented by that
        amount; the bay returns to `AVAILABLE` if it was still `IN_USE` for
        this case; the truck's and fleet's `open_case_count` are each
        decremented; and if the truck has no remaining open cases, its
        `truck_status` returns to `IN_SERVICE`. If the case's downtime exceeded
        24.0 hours — strictly greater than, not equal to — the fleet's
        `reliability_score` drops by 10. Closing also completes campaign work:
        any linked `CampaignCompletion` in `SCHEDULED` moves to `COMPLETED` and
        the campaign's `completion_pct` is recomputed."

        Design: Difficulty/transitive_cascade/case_close_cascades_truck_fleet_bay_campaign
        """
        # Case opened at 2026-09-01T13:00:00Z, closed at 2026-09-02T14:30:00Z
        # (25.5 hours of downtime).
        setup_clock("2026-09-01T13:00:00Z")
        env = setup_full_environment(fleet_name="Cascade Close Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        campaign, completion = setup_campaign_with_completion(env)
        case = validate_success(
            api.create_case(fid, tid, create_case_payload(fault_code="SPN3216_FMI4"), env["uc"]),
            expected_status=201,
        )
        validate_success(api.triage_case(fid, tid, case["id"], env["uc"]))
        validate_success(
            api.schedule_completion(
                campaign["id"], completion["id"], {"case_id": case["id"]}, env["uc"]
            )
        )
        truck_now = validate_success(api.get_truck(fid, tid, env["fm"]))
        validate_success(
            api.schedule_case(
                fid,
                tid,
                case["id"],
                {
                    "dealer_id": env["dealer"]["id"],
                    "bay_id": env["bay"]["id"],
                    "scheduled_start_at": "2026-09-01T13:00:00Z",
                    "scheduled_end_at": "2026-09-01T17:00:00Z",
                    "expected_truck_version": truck_now["version"],
                },
                env["uc"],
            )
        )
        wos = validate_paginated(api.list_work_orders(fid, tid, case["id"], env["uc"]))[0]
        validate_success(
            api.authorize_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"diagnostic_minutes_authorized": 30}, env["uc"],
            )
        )
        validate_success(api.start_service(fid, tid, case["id"], env["da"]))
        validate_success(
            api.complete_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"labor_minutes_actual": 200, "repair_outcome": "FIXED"}, env["da"],
            )
        )
        validate_success(api.request_close(fid, tid, case["id"], env["da"]))
        setup_clock("2026-09-02T14:30:00Z")

        closed = validate_success(api.close_case(fid, tid, case["id"], env["uc"]))
        assert closed["case_status"] == "CLOSED"
        assert closed["downtime_hours"] == pytest.approx(25.50, abs=0.001)

        truck = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert truck["truck_status"] == "IN_SERVICE"
        assert truck["open_case_count"] == 0

        fleet = validate_success(api.get_fleet(fid, env["fm"]))
        assert fleet["open_case_count"] == 0
        assert fleet["total_downtime_hours"] == pytest.approx(25.50, abs=0.001)
        assert fleet["reliability_score"] == 990, (
            f"25.50 > 24.0 hours must apply the -10 downtime penalty, got {fleet['reliability_score']}"
        )

        bay = validate_success(api.get_bay_by_id(env["bay"]["id"], env["uc"]))
        assert bay["bay_status"] == "AVAILABLE"

        cc = validate_success(
            api.get_campaign_completion_by_id(completion["id"], env["uc"])
        )
        assert cc["completion_status"] == "COMPLETED"
        camp = validate_success(api.get_campaign(campaign["id"], env["uc"]))
        assert camp["completion_pct"] == pytest.approx(100.00, abs=0.001)

    def test_case_close_without_campaign_still_cascades_truck_fleet_bay(self, api):
        """PRD §3.8: "the fleet's `total_downtime_hours` is incremented by that
        amount; the bay returns to `AVAILABLE` if it was still `IN_USE` for
        this case; the truck's and fleet's `open_case_count` are each
        decremented; and if the truck has no remaining open cases, its
        `truck_status` returns to `IN_SERVICE`."

        Design: Difficulty/transitive_cascade/case_close_cascades_truck_fleet_bay_campaign
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Cascade2 Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        closed = validate_success(
            api.close_case(env["fleet"]["id"], env["truck"]["id"], case["id"], env["uc"])
        )
        assert closed["case_status"] == "CLOSED"
        truck = validate_success(
            api.get_truck(env["fleet"]["id"], env["truck"]["id"], env["fm"])
        )
        assert truck["truck_status"] == "IN_SERVICE"
        assert truck["open_case_count"] == 0
        fleet = validate_success(api.get_fleet(env["fleet"]["id"], env["fm"]))
        assert fleet["open_case_count"] == 0
        assert fleet["total_downtime_hours"] == pytest.approx(
            closed["downtime_hours"], abs=0.001
        )
        bay = validate_success(api.get_bay_by_id(env["bay"]["id"], env["uc"]))
        assert bay["bay_status"] == "AVAILABLE"


class TestTruckDecommissionCascade:
    def test_truck_decommission_cascades_coverage_and_campaign(self, api):
        """PRD §3.1: "Decommissioning flips `truck_status` to `DECOMMISSIONED`
        and fans out two cascades: every `ACTIVE` `CoverageContract` on the
        truck transitions to `CANCELLED`, the coverage proration calculation
        runs, and the resulting `prorated_credit_cents` is credited to the
        fleet's ledger; and every `OPEN` `CampaignCompletion` row pointing at
        that truck transitions to `EXEMPTED` with its `exemption_reason` set to
        the literal string `TRUCK_DECOMMISSIONED`."

        Design: Difficulty/transitive_cascade/truck_decommission_cascades_coverage_and_campaign
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Cascade Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        contract = validate_success(
            api.create_coverage_contract(
                fid,
                tid,
                {
                    "contract_type": "EXTENDED_FULL",
                    "starts_on": "2026-01-01T00:00:00Z",
                    "ends_on": "2027-01-01T00:00:00Z",
                    "max_miles": 100000,
                    "premium_cents": 500000,
                },
                env["fm"],
            ),
            expected_status=201,
        )
        campaign, completion = setup_campaign_with_completion(env)

        validate_success(api.decommission_truck(fid, tid, env["fm"]))

        truck = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert truck["truck_status"] == "DECOMMISSIONED"

        contracts = validate_paginated(
            api.list_coverage_contracts(fid, tid, env["fm"])
        )[0]
        assert contracts[0]["id"] == contract["id"]
        assert contracts[0]["contract_status"] == "CANCELLED"
        assert isinstance(contracts[0]["prorated_credit_cents"], int)
        assert contracts[0]["prorated_credit_cents"] > 0

        cc = validate_success(
            api.get_campaign_completion_by_id(completion["id"], env["uc"])
        )
        assert cc["completion_status"] == "EXEMPTED"
        assert cc["exemption_reason"] == "TRUCK_DECOMMISSIONED"

        camp = validate_success(api.get_campaign(campaign["id"], env["uc"]))
        assert camp["completion_pct"] == pytest.approx(0.00, abs=0.001)

    def test_decommission_without_campaign_still_cancels_coverage(self, api):
        """PRD §3.1: "Decommissioning flips `truck_status` to `DECOMMISSIONED`
        and fans out two cascades: every `ACTIVE` `CoverageContract` on the
        truck transitions to `CANCELLED`, the coverage proration calculation
        runs, and the resulting `prorated_credit_cents` is credited to the
        fleet's ledger"

        Design: Difficulty/transitive_cascade/truck_decommission_cascades_coverage_and_campaign
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Cascade2b Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        validate_success(
            api.create_coverage_contract(
                fid,
                tid,
                {
                    "contract_type": "EXTENDED_POWERTRAIN",
                    "starts_on": "2026-01-01T00:00:00Z",
                    "ends_on": "2027-01-01T00:00:00Z",
                    "max_miles": 200000,
                    "premium_cents": 1000000,
                },
                env["fm"],
            ),
            expected_status=201,
        )
        validate_success(api.decommission_truck(fid, tid, env["fm"]))
        contracts = validate_paginated(
            api.list_coverage_contracts(fid, tid, env["fm"])
        )[0]
        assert contracts[0]["contract_status"] == "CANCELLED"
        assert contracts[0]["prorated_credit_cents"] >= 0


class TestImmediateConsistency:
    def test_immediate_consistency_case_close_reflects_all_updates(self, api):
        """PRD §3.8: "the bay returns to `AVAILABLE` if it was still `IN_USE`
        for this case; the truck's and fleet's `open_case_count` are each
        decremented; and if the truck has no remaining open cases, its
        `truck_status` returns to `IN_SERVICE`."
        PRD §3.8: "Closing also completes campaign work: any linked
        `CampaignCompletion` in `SCHEDULED` moves to `COMPLETED` and the
        campaign's `completion_pct` is recomputed."

        Design: Corner/consistency model/immediate_consistency_case_close_reflects_all_updates
        """
        setup_clock()
        env = setup_full_environment(fleet_name="IC Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        campaign, completion = setup_campaign_with_completion(env)
        case = validate_success(
            api.create_case(fid, tid, create_case_payload(fault_code="SPN3216_FMI4"), env["uc"]),
            expected_status=201,
        )
        validate_success(api.triage_case(fid, tid, case["id"], env["uc"]))
        validate_success(
            api.schedule_completion(
                campaign["id"], completion["id"], {"case_id": case["id"]}, env["uc"]
            )
        )
        truck_now = validate_success(api.get_truck(fid, tid, env["fm"]))
        validate_success(
            api.schedule_case(
                fid,
                tid,
                case["id"],
                {
                    "dealer_id": env["dealer"]["id"],
                    "bay_id": env["bay"]["id"],
                    "scheduled_start_at": "2026-09-01T14:00:00Z",
                    "scheduled_end_at": "2026-09-01T17:00:00Z",
                    "expected_truck_version": truck_now["version"],
                },
                env["uc"],
            )
        )
        wos = validate_paginated(api.list_work_orders(fid, tid, case["id"], env["uc"]))[0]
        validate_success(
            api.authorize_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"diagnostic_minutes_authorized": 30}, env["uc"],
            )
        )
        validate_success(api.start_service(fid, tid, case["id"], env["da"]))
        validate_success(
            api.complete_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"labor_minutes_actual": 100, "repair_outcome": "FIXED"}, env["da"],
            )
        )
        validate_success(api.request_close(fid, tid, case["id"], env["da"]))
        resp = api.close_case(fid, tid, case["id"], env["uc"])
        assert resp.status_code == 200, f"close failed: {resp.text}"

        # Immediately after close, every read reflects the post-close state.
        case_now = validate_success(api.get_case(fid, tid, case["id"], env["uc"]))
        assert case_now["case_status"] == "CLOSED"
        truck_now = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert truck_now["truck_status"] == "IN_SERVICE"
        bays = validate_paginated(api.list_bays(env["dealer"]["id"], env["da"]))[0]
        assert bays[0]["bay_status"] == "AVAILABLE"
        ccs = validate_paginated(
            api.list_campaign_completions(campaign["id"], env["uc"], params={"truck_id": tid})
        )[0]
        assert ccs[0]["completion_status"] == "COMPLETED"


class TestDerivedFieldReconciliation:
    def test_derived_field_reconciliation_fleet_open_case_count(self, api):
        """PRD §3.2: "A fleet's `open_case_count` and a truck's
        `open_case_count` count cases in any of `OPEN`, `TRIAGE`, `SCHEDULED`,
        `IN_SERVICE`, `AWAITING_PART`, or `PENDING_CLOSE` — both are read-only
        and recomputed synchronously as cases open and resolve."

        Design: Corner/cross-cutting complexity layers/derived_field_reconciliation_fleet_open_case_count
        """
        setup_clock()
        env = setup_full_environment(fleet_name="DF Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        case_1 = validate_success(
            api.create_case(fid, tid, create_case_payload(fault_code="SPN3216_FMI4"), env["uc"]),
            expected_status=201,
        )
        validate_success(
            api.create_case(fid, tid, create_case_payload(fault_code="SPN3226_FMI4"), env["uc"]),
            expected_status=201,
        )
        validate_success(api.cancel_case(fid, tid, case_1["id"], env["uc"]))

        fleet = validate_success(api.get_fleet(fid, env["fm"]))
        truck = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert fleet["open_case_count"] == 1, (
            "case_2 still OPEN, case_1 CANCELLED — count must be 1"
        )
        assert truck["open_case_count"] == 1

    def test_open_case_count_returns_to_zero_after_full_open_close_cycle(self, api):
        """PRD §3.8: "the truck's and fleet's `open_case_count` are each
        decremented" and PRD §3.2: "The truck's `open_case_count` and the
        fleet's `open_case_count` are each incremented."

        Design: Difficulty/compensating_invariant/case_open_close_conserves_open_case_count
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Inv1 Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        case = validate_success(
            api.create_case(fid, tid, create_case_payload(), env["uc"]),
            expected_status=201,
        )
        validate_success(api.triage_case(fid, tid, case["id"], env["uc"]))
        truck_mid = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert truck_mid["open_case_count"] == 1
        validate_success(
            api.schedule_case(
                fid,
                tid,
                case["id"],
                {
                    "dealer_id": env["dealer"]["id"],
                    "bay_id": env["bay"]["id"],
                    "scheduled_start_at": "2026-09-01T13:00:00Z",
                    "scheduled_end_at": "2026-09-01T17:00:00Z",
                    "expected_truck_version": truck_mid["version"],
                },
                env["uc"],
            )
        )
        wos = validate_paginated(api.list_work_orders(fid, tid, case["id"], env["uc"]))[0]
        validate_success(
            api.authorize_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"diagnostic_minutes_authorized": 30}, env["uc"],
            )
        )
        validate_success(api.start_service(fid, tid, case["id"], env["da"]))
        validate_success(
            api.complete_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"labor_minutes_actual": 100, "repair_outcome": "FIXED"}, env["da"],
            )
        )
        validate_success(api.request_close(fid, tid, case["id"], env["da"]))
        closed = validate_success(api.close_case(fid, tid, case["id"], env["uc"]))
        assert closed["case_status"] == "CLOSED"

        fleet = validate_success(api.get_fleet(fid, env["fm"]))
        truck = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert fleet["open_case_count"] == 0, (
            f"open_case_count must return to 0 after close, got {fleet['open_case_count']}"
        )
        assert truck["open_case_count"] == 0

    def test_open_case_count_returns_to_zero_after_cancel(self, api):
        """PRD §3.8: "Cancellation moves the case to `CANCELLED`, releases any
        `RESERVED` bay back to `AVAILABLE`, moves every `DRAFT` work order on
        the case to `CANCELLED`, moves every `PENDING` part order on the case
        to `CANCELLED`, and decrements both the truck's and the fleet's
        `open_case_count`."

        Design: Difficulty/compensating_invariant/case_open_close_conserves_open_case_count
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Inv1b Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        case = validate_success(
            api.create_case(fid, tid, create_case_payload(), env["uc"]),
            expected_status=201,
        )
        cancelled = validate_success(api.cancel_case(fid, tid, case["id"], env["uc"]))
        assert cancelled["case_status"] == "CANCELLED"
        fleet = validate_success(api.get_fleet(fid, env["fm"]))
        truck = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert fleet["open_case_count"] == 0
        assert truck["open_case_count"] == 0


class TestScheduleCascadesToBay:
    def test_cascading_side_effects_case_to_bay_to_truck(self, api):
        """PRD §3.3: "On success the case moves `TRIAGE` → `SCHEDULED`:
        `Case.dealer_id` is set, a `DRAFT` `WorkOrder` is created linking the
        case to the dealer and the bay (with `case_id`, `dealer_id`, `bay_id`,
        `scheduled_start_at`, and `scheduled_end_at` recorded), the bay's
        `bay_status` flips to `RESERVED`, and both the truck's `version` and
        the case's `version` increment"

        Design: Corner/cross-cutting complexity layers/cascading_side_effects_case_to_bay_to_truck
        """
        setup_clock()
        env = setup_full_environment(fleet_name="CSE Fleet")
        ctx = setup_case_in_state(env, "TRIAGE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        truck_now = validate_success(api.get_truck(fid, tid, env["fm"]))
        scheduled = validate_success(
            api.schedule_case(
                fid,
                tid,
                case["id"],
                {
                    "dealer_id": env["dealer"]["id"],
                    "bay_id": env["bay"]["id"],
                    "scheduled_start_at": "2026-09-01T14:00:00Z",
                    "scheduled_end_at": "2026-09-01T17:00:00Z",
                    "expected_truck_version": truck_now["version"],
                },
                env["uc"],
            )
        )
        assert scheduled["case_status"] == "SCHEDULED"
        bays = validate_paginated(api.list_bays(env["dealer"]["id"], env["da"]))[0]
        assert bays[0]["bay_status"] == "RESERVED", (
            "bay cascade must be applied atomically with the case transition"
        )
