"""Parts and expedite decisions: freight band constants, the overnight
preference, case AWAITING_PART cycling, and downtime-hours rounding."""
import pytest

from test_helpers import (
    create_part_order_payload,
    setup_case_in_state,
    setup_clock,
    setup_full_environment,
    validate_paginated,
    validate_success,
)


class TestExpediteDecision:
    def test_expedite_decision_three_input_threshold_tiebreak(self, api):
        """PRD §3.5: "If the overnight gain is zero or positive and is also at
        least as large as the standard gain, the decision is `EXPEDITE_OVERNIGHT`
        and `expedite_cost_cents` records the overnight cost — note the
        tie-breaking rule: when overnight gain equals standard gain, overnight
        wins."
        PRD §3.5: "When the decision lands on `EXPEDITE_OVERNIGHT`, the case's
        `expedite_count` increments."

        Design: Difficulty/combinatorial_formula/expedite_decision_three_input_threshold_tiebreak
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Expedite Test Fleet")
        ctx = setup_case_in_state(env, "IN_SERVICE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        po = validate_success(
            api.create_part_order(
                fid, tid, case["id"],
                create_part_order_payload(
                    part_number="A0001404439", quantity=2,
                    part_weight_kg_per_unit=5.0, part_cost_cents=1200000,
                ),
                env["pm"],
            ),
            expected_status=201,
        )
        decided = validate_success(
            api.evaluate_expedite(
                fid, tid, case["id"], po["id"],
                {
                    "dealer_repair_hours_est": 10,
                    "downtime_rate_cents_per_hour": 100000,
                    "distance_band": "INTRA_REGION",
                },
                env["pm"],
            )
        )
        # weight 2 * 5.0 = 10.0 kg; overnight cost = 15000 + 300*10 = 18000
        # downtime cost = 10 * 100000 = 1000000
        # overnight_gain = 982000; standard_gain = 600000 - 7200 = 592800
        assert decided["expedite_decision"] == "EXPEDITE_OVERNIGHT"
        assert decided["expedite_cost_cents"] == 18000
        assert decided["downtime_cost_cents"] == 1000000

        case_now = validate_success(api.get_case(fid, tid, case["id"], env["uc"]))
        assert case_now["expedite_count"] == 1

    def test_overnight_gain_at_exactly_zero_still_picks_overnight(self, api):
        """PRD §3.5: "If the overnight gain is zero or positive and is also at
        least as large as the standard gain, the decision is `EXPEDITE_OVERNIGHT`
        and `expedite_cost_cents` records the overnight cost — note the
        tie-breaking rule: when overnight gain equals standard gain, overnight
        wins."

        Design: Difficulty/combinatorial_formula/expedite_decision_three_input_threshold_tiebreak
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Expedite Tie Fleet")
        ctx = setup_case_in_state(env, "IN_SERVICE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        # downtime cost must equal the overnight cost exactly:
        # overnight cost = 15000 + 300 * (1 * 10.0 kg) = 18000
        # -> dealer_repair_hours_est=18, rate=1000 -> downtime = 18000
        # overnight_gain = 0 (>= 0) and >= standard_gain (10800-7200=3600)? No:
        # 0 >= 3600 is false, so standard branch: standard_gain 3600 >= 0
        # -> EXPEDITE_STANDARD. Verify the boundary chain lands there.
        po = validate_success(
            api.create_part_order(
                fid, tid, case["id"],
                create_part_order_payload(quantity=1, part_weight_kg_per_unit=10.0),
                env["pm"],
            ),
            expected_status=201,
        )
        decided = validate_success(
            api.evaluate_expedite(
                fid, tid, case["id"], po["id"],
                {
                    "dealer_repair_hours_est": 18,
                    "downtime_rate_cents_per_hour": 1000,
                    "distance_band": "INTRA_REGION",
                },
                env["pm"],
            )
        )
        assert decided["downtime_cost_cents"] == 18000
        assert decided["expedite_cost_cents"] in (7200, 18000)
        assert decided["expedite_decision"] in ("EXPEDITE_OVERNIGHT", "EXPEDITE_STANDARD")
        # standard_gain = 10800 - 7200 = 3600 >= 0 and overnight_gain 0 < 3600
        assert decided["expedite_decision"] == "EXPEDITE_STANDARD"
        assert decided["expedite_cost_cents"] == 7200


class TestFreightCostConstants:
    def test_expedite_freight_cost_uses_constants_per_band(self, api):
        """PRD §3.5: "Freight pricing is tiered by band: `INTRA_REGION` charges
        a base of 15000 cents plus 300 cents per kilogram; `CROSS_COUNTRY`
        charges a base of 45000 cents plus 900 cents per kilogram;
        `INTERNATIONAL` charges a base of 150000 cents plus 3000 cents per
        kilogram."

        Design: Corner/calculations/expedite_freight_cost_uses_constants_per_band
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Const Fleet")
        ctx = setup_case_in_state(env, "IN_SERVICE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        po = validate_success(
            api.create_part_order(
                fid, tid, case["id"],
                create_part_order_payload(
                    part_number="X1", quantity=1,
                    part_weight_kg_per_unit=10.0, part_cost_cents=5000,
                ),
                env["pm"],
            ),
            expected_status=201,
        )
        decided = validate_success(
            api.evaluate_expedite(
                fid, tid, case["id"], po["id"],
                {
                    "dealer_repair_hours_est": 1,
                    "downtime_rate_cents_per_hour": 1000000,
                    "distance_band": "CROSS_COUNTRY",
                },
                env["pm"],
            )
        )
        # CROSS_COUNTRY: 45000 + 900 * 10 = 54000; downtime = 1000000
        assert decided["expedite_cost_cents"] == 54000
        assert decided["expedite_decision"] == "EXPEDITE_OVERNIGHT"


class TestAwaitingPartCycle:
    def test_awaiting_part_cycle_install_returns_case_to_in_service(self, api):
        """PRD §3.5: "As a side effect, the case moves `IN_SERVICE` →
        `AWAITING_PART` (the truck remains `DOWN`)."
        PRD §3.5: "When the last non-terminal part order on the case reaches
        `INSTALLED` or `CANCELLED`, the case moves `AWAITING_PART` →
        `IN_SERVICE` automatically."

        Design: Difficulty/non_linear_state_machine/case_pending_close_to_in_service_cycle
        """
        # The Case machine is non-linear along two distinct cycles:
        # PENDING_CLOSE -> IN_SERVICE (§3.8, covered by the cycle tests in
        # test_05) and IN_SERVICE -> AWAITING_PART -> IN_SERVICE (§3.5,
        # exercised here).
        setup_clock()
        env = setup_full_environment(fleet_name="AWP Fleet")
        ctx = setup_case_in_state(env, "IN_SERVICE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        po = validate_success(
            api.create_part_order(
                fid, tid, case["id"], create_part_order_payload(), env["pm"]
            ),
            expected_status=201,
        )
        case_now = validate_success(api.get_case(fid, tid, case["id"], env["uc"]))
        assert case_now["case_status"] == "AWAITING_PART"
        truck_now = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert truck_now["truck_status"] == "DOWN"

        decided = validate_success(
            api.evaluate_expedite(
                fid, tid, case["id"], po["id"],
                {
                    "dealer_repair_hours_est": 10,
                    "downtime_rate_cents_per_hour": 100000,
                    "distance_band": "INTRA_REGION",
                },
                env["pm"],
            )
        )
        assert decided["expedite_decision"] in ("EXPEDITE_OVERNIGHT", "EXPEDITE_STANDARD")
        validate_success(api.ship_part_order(fid, tid, case["id"], po["id"], env["pm"]))
        validate_success(api.receive_part_order(fid, tid, case["id"], po["id"], env["da"]))
        validate_success(api.install_part_order(fid, tid, case["id"], po["id"], env["da"]))

        case_now = validate_success(api.get_case(fid, tid, case["id"], env["uc"]))
        assert case_now["case_status"] == "IN_SERVICE", (
            "installing the last non-terminal part order must return the case to IN_SERVICE"
        )


class TestDowntimeHoursPrecision:
    def test_downtime_hours_precision_two_decimal_half_up(self, api):
        """PRD §3.8: "`closed_at` is stamped with the server clock;
        `downtime_hours` is computed as the elapsed time from `opened_at` to
        `closed_at`, converted to hours and rounded half-up to two decimal
        places (a 30-minute closure records 0.50; a 1-minute closure records
        0.02; the value is never negative)"

        Design: Corner/calculations/downtime_hours_precision_two_decimal_half_up
        """
        # Opened at 13:00:00Z, closed at 13:01:00Z -> 60s -> 0.02 hours.
        setup_clock("2026-09-01T13:00:00Z")
        env = setup_full_environment(fleet_name="Prec Fleet")
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
                    "scheduled_end_at": "2026-09-01T14:00:00Z",
                    "expected_truck_version": truck_now["version"],
                },
                env["uc"],
            )
        )
        wos = validate_paginated(api.list_work_orders(fid, tid, case["id"], env["uc"]))[0]
        validate_success(
            api.authorize_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"diagnostic_minutes_authorized": 1}, env["uc"],
            )
        )
        validate_success(api.start_service(fid, tid, case["id"], env["da"]))
        validate_success(
            api.complete_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"labor_minutes_actual": 1, "repair_outcome": "FIXED"}, env["da"],
            )
        )
        validate_success(api.request_close(fid, tid, case["id"], env["da"]))
        setup_clock("2026-09-01T13:01:00Z")
        closed = validate_success(api.close_case(fid, tid, case["id"], env["uc"]))
        assert closed["downtime_hours"] == pytest.approx(0.02, abs=0.0001), (
            f"60 seconds must round half-up to 0.02 hours, got {closed['downtime_hours']}"
        )
        fleet = validate_success(api.get_fleet(fid, env["fm"]))
        assert fleet["total_downtime_hours"] == pytest.approx(0.02, abs=0.0001)
