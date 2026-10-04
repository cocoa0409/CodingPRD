"""Coverage proration, reliability scoring (incremental vs snapshot), part
return windows, campaign overdue boundary, campaign close gate, and
reliability report snapshots."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_coverage_contract_payload,
    create_truck_payload,
    make_uptime_coordinator_headers,
    setup_campaign_with_completion,
    setup_clock,
    setup_fleet_with_truck,
    setup_full_environment,
    setup_approved_base_warranty_claim,
    setup_case_in_state,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCoverageProration:
    def test_coverage_proration_time_vs_mileage_divergence(self, api):
        """PRD §3.10: "The `prorated_credit_cents` is the smaller of the two
        credits, rounded half-up to integer cents, with the division carried in
        rationals and rounded once at the end."

        Design: Difficulty/dual_variant_calc/coverage_proration_time_vs_mileage_divergence
        """
        # Contract: 2026-01-01 -> 2027-01-01 (365 days), max_miles 200000,
        # premium 1,000,000 cents. Truck starts at 100000 miles (contract
        # start), odometer moved to 170000 (used 70000 miles).
        # mileage_credit = 1000000 * (200000 - 70000) / 200000 = 650000
        # clock at 2026-04-01: elapsed 90 days
        # time_credit = 1000000 * (365 - 90) / 365 = 753425 (round-half-up)
        # min(650000, 753425) = 650000 -> mileage branch wins.
        setup_clock("2026-01-01T00:00:00Z")
        fleet, truck, fm = setup_fleet_with_truck(
            fleet_name="Mileage Heavy Freight",
            home_region="MW",
            truck_overrides={
                "in_service_on": "2025-12-15T00:00:00Z",
                "odometer_miles": 100000,
            },
        )
        fid, tid = fleet["id"], truck["id"]
        contract = validate_success(
            api.create_coverage_contract(
                fid, tid, create_coverage_contract_payload(), fm
            ),
            expected_status=201,
        )
        validate_success(
            api.update_truck(fid, tid, {"odometer_miles": 170000}, fm)
        )
        setup_clock("2026-04-01T00:00:00Z")
        cancelled = validate_success(api.cancel_coverage_contract(fid, tid, contract["id"], fm))
        assert cancelled["contract_status"] == "CANCELLED"
        assert cancelled["prorated_credit_cents"] == 650000, (
            f"mileage branch (650000) is the smaller credit and must win, "
            f"got {cancelled['prorated_credit_cents']}"
        )
        assert cancelled["prorated_credit_cents"] != 753425, (
            "time branch must NOT be selected when mileage is smaller"
        )
        assert cancelled["prorated_credit_cents"] != 1000000, (
            "full refund must not be given for partial consumption"
        )

    def test_coverage_proration_full_refund_at_start_boundary(self, api):
        """PRD §3.10: "Two boundaries anchor the formula: cancelling at the
        exact `starts_on` instant yields the full `premium_cents` back; a truck
        that has reached `max_miles` yields zero."

        Design: Difficulty/dual_variant_calc/coverage_proration_time_vs_mileage_divergence
        """
        setup_clock("2026-01-01T00:00:00Z")
        fleet, truck, fm = setup_fleet_with_truck(
            fleet_name="Boundary Fleet",
            home_region="MW",
            truck_overrides={
                "in_service_on": "2025-12-15T00:00:00Z",
                "odometer_miles": 100000,
            },
        )
        fid, tid = fleet["id"], truck["id"]
        contract = validate_success(
            api.create_coverage_contract(
                fid, tid, create_coverage_contract_payload(), fm
            ),
            expected_status=201,
        )
        # cancel at the exact starts_on instant, odometer unchanged
        cancelled = validate_success(api.cancel_coverage_contract(fid, tid, contract["id"], fm))
        assert cancelled["contract_status"] == "CANCELLED"
        assert cancelled["prorated_credit_cents"] == 1000000, (
            f"cancel at starts_on yields the full premium, got {cancelled['prorated_credit_cents']}"
        )


class TestReliabilityScoreVariants:
    def test_reliability_score_incremental_vs_snapshot_divergence(self, api):
        """PRD §3.9: "The fleet's `reliability_score` starts at 1000 and is
        decremented by four kinds of events: a case closing with
        `downtime_hours` strictly greater than 24.0 subtracts 10"
        PRD §3.9: "Penalties apply exactly once per triggering event; the ops
        run's snapshot variant recomputes the score from the full event history
        as an audit cross-check."

        Design: Difficulty/dual_variant_calc/reliability_score_incremental_vs_snapshot_divergence
        """
        # Case opened 2026-09-01T00:00:00Z, closed 2026-09-03T10:00:00Z -> 58h
        # downtime (> 24h -> -10 penalty). To pin 49h the recipe opens at
        # 09:00; the opened_at is the server clock at create time, so we open
        # at 2026-09-01T09:00 and close at 2026-09-03T10:00 -> 49.00 hours.
        setup_clock("2026-09-01T09:00:00Z")
        env = setup_full_environment(fleet_name="Delta Haulers")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        case = validate_success(
            api.create_case(fid, tid, {"fault_code": "SPN3216_FMI4"}, env["uc"]),
            expected_status=201,
        )
        validate_success(api.triage_case(fid, tid, case["id"], env["uc"]))
        truck_now = validate_success(api.get_truck(fid, tid, env["fm"]))
        validate_success(
            api.schedule_case(
                fid, tid, case["id"],
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
                {"diagnostic_minutes_authorized": 60}, env["uc"],
            )
        )
        validate_success(api.start_service(fid, tid, case["id"], env["da"]))
        validate_success(
            api.complete_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"labor_minutes_actual": 180, "repair_outcome": "FIXED"}, env["da"],
            )
        )
        validate_success(api.request_close(fid, tid, case["id"], env["da"]))
        setup_clock("2026-09-03T10:00:00Z")
        closed = validate_success(api.close_case(fid, tid, case["id"], env["uc"]))
        assert closed["downtime_hours"] == pytest.approx(49.00, abs=0.001)

        # incremental variant after close
        fleet_mid = validate_success(api.get_fleet(fid, env["fm"]))
        assert fleet_mid["reliability_score"] == 990, (
            f"incremental: 1000 - 10 downtime penalty = 990, got {fleet_mid['reliability_score']}"
        )

        # snapshot variant via ops run must agree (no double count)
        validate_success(api.ops_run(env["uc"]))
        fleet_after = validate_success(api.get_fleet(fid, env["fm"]))
        assert fleet_after["reliability_score"] == 990, (
            f"snapshot must agree with incremental, got {fleet_after['reliability_score']}"
        )
        reports = validate_paginated(api.list_reliability_reports(fid, env["fm"]))[0]
        assert len(reports) == 1
        assert reports[0]["reliability_score"] == 990

    def test_snapshot_recomputes_same_score_after_ops_run(self, api):
        """PRD §3.9: "The fleet's `reliability_score` starts at 1000 and is
        decremented by four kinds of events: a case closing with
        `downtime_hours` strictly greater than 24.0 subtracts 10"
        PRD §3.9: "Penalties apply exactly once per triggering event; the ops
        run's snapshot variant recomputes the score from the full event history
        as an audit cross-check."

        Design: Difficulty/dual_variant_calc/reliability_score_incremental_vs_snapshot_divergence
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Delta Haulers 2")
        ctx = setup_case_in_state(env, "CLOSED")
        case = ctx["case"]
        assert case["downtime_hours"] == pytest.approx(0.00, abs=0.001), (
            "same-clock close -> 0 downtime -> no penalty"
        )
        validate_success(api.ops_run(env["uc"]))
        fleet = validate_success(api.get_fleet(env["fleet"]["id"], env["fm"]))
        assert fleet["reliability_score"] == 1000
        reports = validate_paginated(
            api.list_reliability_reports(env["fleet"]["id"], env["fm"])
        )[0]
        assert reports[0]["reliability_score"] == 1000


class TestPartReturnWindow:
    def test_part_return_ship_after_window_lapsed_rejected(self, api):
        """PRD §3.7: "The ship is only allowed while the current clock is no
        later than the return's `created_at` plus its `return_window_days`; a
        late ship attempt is rejected with `ERR_RETURN_WINDOW_LAPSED`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_part_return_vs_claim_open
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Prio2 Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        claim, part_return = setup_approved_base_warranty_claim(
            env, case["id"],
            claim_type="BASE_WARRANTY",
            labor_minutes_claimed=100,
            parts_claimed_cents=100000,
        )
        assert part_return is not None
        assert part_return["return_window_days"] == 30

        # advance 44 days — well past the 30-day window
        setup_clock("2026-10-15T00:00:00Z")
        resp = api.ship_part_return(fid, tid, case["id"], claim["id"], part_return["id"], env["da"])
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_LAPSED.value, expected_status=422)

        prs = validate_paginated(
            api.list_part_returns(fid, tid, case["id"], claim["id"], env["sm"])
        )[0]
        assert prs[0]["part_return_status"] == "REQUESTED", (
            "rejected ship must leave the return in REQUESTED"
        )

    def test_part_return_ship_within_window_succeeds(self, api):
        """PRD §3.7: "The ship is only allowed while the current clock is no
        later than the return's `created_at` plus its `return_window_days`; a
        late ship attempt is rejected with `ERR_RETURN_WINDOW_LAPSED`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_part_return_vs_claim_open
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Prio2b Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        claim, part_return = setup_approved_base_warranty_claim(
            env, case["id"],
            claim_type="BASE_WARRANTY",
            labor_minutes_claimed=100,
            parts_claimed_cents=100000,
        )
        # Ship on the same clock day — well within the window.
        shipped = validate_success(
            api.ship_part_return(fid, tid, case["id"], claim["id"], part_return["id"], env["da"])
        )
        assert shipped["part_return_status"] == "IN_TRANSIT"
        assert shipped["shipped_at"] is not None


class TestCampaignOverdueBoundary:
    def test_campaign_completion_window_day_granularity(self, api):
        """PRD §2.5: "for each `OPEN` `CampaignCompletion` row whose parent
        campaign's `closes_on` is strictly earlier than the current clock — a
        row whose `closes_on` equals the current clock is *not* overdue — the
        owning fleet's `reliability_score` is decremented by 5, the parent
        campaign's `overdue_count` is recomputed as the count of `OPEN` rows
        past `closes_on`"

        Design: Difficulty/resource_temporal_overlap/campaign_completion_window_day_granularity
        """
        setup_clock("2026-08-01T00:00:00Z")
        env = setup_full_environment(fleet_name="CmpWin Fleet")
        campaign, completion = setup_campaign_with_completion(
            env,
            campaign_overrides={
                "opens_on": "2026-08-01T00:00:00Z",
                "closes_on": "2026-09-01T00:00:00Z",
            },
        )
        assert completion["completion_status"] == "OPEN"

        # At exactly closes_on the row is NOT overdue.
        setup_clock("2026-09-01T00:00:00Z")
        validate_success(api.ops_run(env["uc"]))
        camp = validate_success(api.get_campaign(campaign["id"], env["uc"]))
        assert camp["overdue_count"] == 0, (
            f"closes_on == now is NOT overdue (> not >=), got {camp['overdue_count']}"
        )

        # One second past closes_on it IS overdue.
        setup_clock("2026-09-01T00:00:01Z")
        validate_success(api.ops_run(env["uc"]))
        camp = validate_success(api.get_campaign(campaign["id"], env["uc"]))
        assert camp["overdue_count"] == 1, (
            f"now > closes_on must count the row overdue, got {camp['overdue_count']}"
        )
        fleet = validate_success(api.get_fleet(env["fleet"]["id"], env["fm"]))
        assert fleet["reliability_score"] == 995, (
            f"exactly one -5 overdue penalty across both ops runs, got {fleet['reliability_score']}"
        )
        cc = validate_success(
            api.get_campaign_completion_by_id(completion["id"], env["uc"])
        )
        assert cc["completion_status"] == "OPEN", (
            "the sweep counts overdue rows but does not change completion_status"
        )

    def test_overdue_sweep_penalizes_once_per_ops_run(self, api):
        """PRD §3.9: "each `OPEN` `CampaignCompletion` row found past its
        campaign's `closes_on` at an ops run subtracts 5 per row per run."

        Design: Difficulty/resource_temporal_overlap/campaign_completion_window_day_granularity
        """
        setup_clock("2026-08-01T00:00:00Z")
        env = setup_full_environment(fleet_name="CmpWin2 Fleet")
        campaign, completion = setup_campaign_with_completion(
            env,
            campaign_overrides={
                "opens_on": "2026-08-01T00:00:00Z",
                "closes_on": "2026-08-15T00:00:00Z",
            },
        )
        setup_clock("2026-09-01T00:00:00Z")
        validate_success(api.ops_run(env["uc"]))
        fleet = validate_success(api.get_fleet(env["fleet"]["id"], env["fm"]))
        assert fleet["reliability_score"] == 995
        # second ops run while still overdue: -5 again (per row per run)
        validate_success(api.ops_run(env["uc"]))
        fleet = validate_success(api.get_fleet(env["fleet"]["id"], env["fm"]))
        assert fleet["reliability_score"] == 990


class TestCampaignCloseGate:
    def test_campaign_close_empty_completion_set_returns_zero_pct(self, api):
        """PRD §3.11: "A campaign whose entire scope is exempted therefore
        reports 0.00, never 100.00."
        PRD §3.11: "Closure is permitted once `completion_pct` reaches at least
        95.00, or once the current clock is strictly later than `closes_on`
        plus 90 days; an attempt before either condition holds is rejected with
        `ERR_CAMPAIGN_NOT_CLOSABLE` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/campaign_close_empty_completion_set_returns_zero_pct
        """
        setup_clock()
        env = setup_full_environment(fleet_name="EmptyCmp Fleet")
        campaign, completion = setup_campaign_with_completion(env)
        validate_success(
            api.exempt_completion(
                campaign["id"], completion["id"],
                {"exemption_reason": "FLEET_SOLD"}, env["uc"],
            )
        )
        camp = validate_success(api.get_campaign(campaign["id"], env["uc"]))
        assert camp["completion_pct"] == pytest.approx(0.00, abs=0.001), (
            f"all-exempt scope must report 0.00, got {camp['completion_pct']}"
        )
        resp = api.close_campaign(
            campaign["id"],
            {"expected_campaign_version": camp["version"]},
            env["uc"],
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_CLOSABLE.value, expected_status=409)
        camp_after = validate_success(api.get_campaign(campaign["id"], env["uc"]))
        assert camp_after["campaign_status"] == "OPEN"

    def test_campaign_close_succeeds_after_grace_window(self, api):
        """PRD §3.11: "Closure is permitted once `completion_pct` reaches at
        least 95.00, or once the current clock is strictly later than
        `closes_on` plus 90 days; an attempt before either condition holds is
        rejected with `ERR_CAMPAIGN_NOT_CLOSABLE` (HTTP 409). Successful
        closure moves the campaign to `CLOSED`."

        Design: Difficulty/boundary_precision_check/campaign_close_empty_completion_set_returns_zero_pct
        """
        setup_clock()
        env = setup_full_environment(fleet_name="EmptyCmp2 Fleet")
        campaign, completion = setup_campaign_with_completion(env)
        validate_success(
            api.exempt_completion(
                campaign["id"], completion["id"],
                {"exemption_reason": "FLEET_SOLD"}, env["uc"],
            )
        )
        # closes_on is 2027-08-01; grace window ends 90 days later.
        setup_clock("2027-12-01T00:00:00Z")
        camp = validate_success(api.get_campaign(campaign["id"], env["uc"]))
        closed = validate_success(
            api.close_campaign(
                campaign["id"],
                {"expected_campaign_version": camp["version"]},
                env["uc"],
            )
        )
        assert closed["campaign_status"] == "CLOSED"


class TestReliabilityReports:
    def test_reliability_reports_computed_read(self, api):
        """PRD §2.5: "a `ReliabilityReport` snapshot row is written per fleet
        carrying `ops_run_index`, `computed_at`, `trucks_in_service`,
        `trucks_down`, `total_downtime_hours`, `repeat_repair_truck_count`,
        `campaign_completion_pct`, and `reliability_score`."

        Design: Corner/endpoints/reliability_reports_computed_read
        """
        setup_clock()
        fleet, truck_1, fm = setup_fleet_with_truck(
            fleet_name="RR Fleet",
            truck_overrides={"odometer_miles": 0},
        )
        validate_success(
            api.create_truck(
                fleet["id"], create_truck_payload(odometer_miles=0), fm
            ),
            expected_status=201,
        )
        validate_success(api.ops_run(make_uptime_coordinator_headers()))
        reports = validate_paginated(api.list_reliability_reports(fleet["id"], fm))[0]
        assert len(reports) == 1
        report = reports[0]
        assert report["trucks_in_service"] == 2
        assert report["trucks_down"] == 0
        assert report["reliability_score"] == 1000
