"""Inter-club settlement: dual-variant line amounts, sweep window boundaries,
per-line rounding order, the completion-to-assessment cascade, period and line
lifecycle errors (PRD §3.7-3.8)."""
from test_helpers import (
    ApiErrorId,
    complete_foreign_tow_call,
    create_and_complete_call,
    create_settlement_period,
    create_service_call,
    get_success_data,
    make_federation_finance_headers,
    make_settlement_clerk_headers,
    set_clock,
    setup_foreign_call_scenario,
    setup_swept_period,
    validate_error,
    validate_paginated,
    validate_success,
)

CLERK_1_HEADERS = make_settlement_clerk_headers("clerk-1")
FIN_9_HEADERS = make_federation_finance_headers("fin-9")


class TestScheduleVersusActualBasis:
    def test_schedule_policy_bills_flat_schedule_amount(self, api, settlement_clerk_headers):
        """PRD §3.8: "Under the default `SCHEDULE` basis, the gross is a flat
        federation schedule indexed by the call's pinned `benefit_tier_code` and
        `service_type`, independent of actual miles and parts" — the CLASSIC TOW
        row bills 8900.

        Design: Difficulty/dual_variant_calc/interclub_settlement_schedule_vs_actual_basis
        """
        scenario = setup_foreign_call_scenario(servicing_billing_policy="SCHEDULE")
        done = complete_foreign_tow_call(scenario, actual_tow_miles=10)
        line = done["line"]
        assert line["gross_amount_cents"] == 8900
        assert line["status"] == "PENDING"
        assert line["excluded"] is False

    def test_actual_policy_bills_provider_cost_basis(self, api, settlement_clerk_headers):
        """PRD §3.8: "Under the `ACTUAL` basis, the gross mirrors the provider's
        cost: a hook fee of 5500 cents, plus 240 cents per actual effective tow
        mile (the `actual_tow_miles` minus the 3-mile courtesy bonus, floored at
        zero — zero for non-tow calls), plus the completion's
        `parts_charge_cents`."

        Design: Difficulty/dual_variant_calc/interclub_settlement_schedule_vs_actual_basis
        """
        scenario = setup_foreign_call_scenario(servicing_billing_policy="ACTUAL")
        done = complete_foreign_tow_call(scenario, actual_tow_miles=10)
        line = done["line"]
        # 5500 + max(0, 10 - 3) x 240 + 0 parts
        assert line["gross_amount_cents"] == 7180
        assert line["status"] == "PENDING"
        assert line["excluded"] is False


class TestAssessmentRoundingOrder:
    def _setup_three_call_period(self, api):
        scenario = setup_foreign_call_scenario(
            servicing_billing_policy="SCHEDULE",
            tier_overrides={"annual_call_cap": 6},
            provider_overrides={"capabilities": ["TOW", "BATTERY", "FUEL"], "max_concurrent_dispatches": 3},
        )
        m_id = scenario["membership"]["id"]
        p_id = scenario["primary"]["id"]
        # TOW (8900), BATTERY (6200), FUEL (4100) — all CLASSIC schedule amounts
        create_and_complete_call(m_id, p_id, complete_payload={"actual_tow_miles": 10},
                                 breakdown_location_state="CS", requested_tow_miles=10)
        create_and_complete_call(m_id, p_id, complete_payload={},
                                 service_type="BATTERY", breakdown_location_state="CS")
        create_and_complete_call(m_id, p_id, complete_payload={},
                                 service_type="FUEL", breakdown_location_state="CS")
        period = create_settlement_period(scenario["servicing_club"]["id"])
        set_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_settlement_period(period["id"], CLERK_1_HEADERS))
        return scenario, period

    def test_per_line_fees_rounded_before_sum(self, api, federation_finance_headers):
        """PRD §2.6: "each line's fee is rounded half-up first, and only then
        are the rounded per-line fees and nets summed; summing gross amounts
        first and rounding once at the end is forbidden." PRD §3.8: "computes
        `assessed_fee_cents` as the line's `gross_amount_cents` times the
        federation assessment rate of 4.5 percent, rounded half-up per line
        first".

        Design: Difficulty/combinatorial_formula/settlement_assessment_per_line_rounding_beats_sum_first
        """
        scenario, period = self._setup_three_call_period(api)
        validate_success(api.assess_settlement_period(period["id"], FIN_9_HEADERS))
        lines, _meta = validate_paginated(
            api.list_settlement_lines_for_period(period["id"], federation_finance_headers)
        )
        assert len(lines) == 3
        fees_by_gross = {l["gross_amount_cents"]: l["assessed_fee_cents"] for l in lines}
        # round_half_up per line: 8900->401, 6200->279, 4100->185
        assert fees_by_gross == {8900: 401, 6200: 279, 4100: 185}
        total_fee = sum(l["assessed_fee_cents"] for l in lines)
        assert total_fee == 865, "per-line rounding yields 865; sum-first would give 864"
        for line in lines:
            assert line["status"] == "ASSESSED"
            assert line["assessed_net_cents"] == line["gross_amount_cents"] - line["assessed_fee_cents"]

    def test_period_totals_sum_swept_gross(self, api, federation_finance_headers):
        """PRD §3.8: "The period records `total_foreign_call_count` as the swept
        count and `total_gross_cents` as the sum of swept `gross_amount_cents`".

        Design: Difficulty/combinatorial_formula/settlement_assessment_per_line_rounding_beats_sum_first
        """
        scenario, period = self._setup_three_call_period(api)
        closed = get_success_data(api.get_settlement_period(period["id"], federation_finance_headers))
        assert closed["total_gross_cents"] == 19200
        assert closed["total_foreign_call_count"] == 3
        assessed = validate_success(api.assess_settlement_period(period["id"], FIN_9_HEADERS))
        assert assessed["status"] == "ASSESSED"


class TestForeignCompletionCascade:
    def test_completion_births_pending_settlement_line(self, api, settlement_clerk_headers):
        """PRD §3.7: "When the membership's `home_club_id` differs from the
        call's `servicing_club_id` — a foreign call — completion also writes a
        `SettlementLine`, whose `status` begins at `PENDING` unless excluded. If
        the call was benefit-eligible, the line is born with `excluded` false
        and a `gross_amount_cents` computed per §3.8."

        Design: Difficulty/transitive_cascade/foreign_completion_cascades_to_settlement
        """
        scenario = setup_foreign_call_scenario(servicing_billing_policy="SCHEDULE")
        done = complete_foreign_tow_call(scenario, actual_tow_miles=10)
        line = done["line"]
        assert line["status"] == "PENDING"
        assert line["gross_amount_cents"] == 8900
        assert line["servicing_club_id"] == scenario["servicing_club"]["id"]
        assert line["home_club_id"] == scenario["home_club"]["id"]
        assert line["excluded"] is False

    def test_close_sweeps_and_assess_assesses_line(self, api, federation_finance_headers):
        """PRD §3.8: "then assign them to the period in exactly that order,
        stamping each line's `settlement_period_id` and moving it from `PENDING`
        to `SWEPT`" and at assess "Each swept line moves from `SWEPT` to
        terminal `ASSESSED`, and the period itself becomes `ASSESSED`,
        terminal."

        Design: Difficulty/transitive_cascade/foreign_completion_cascades_to_settlement
        """
        scenario = setup_swept_period(servicing_billing_policy="SCHEDULE")
        period = scenario["period"]
        assert period["status"] == "CLOSED"
        assert period["total_foreign_call_count"] == 1
        assert period["total_gross_cents"] == 8900
        validate_success(api.assess_settlement_period(period["id"], FIN_9_HEADERS))
        line = get_success_data(api.get_settlement_line(scenario["line"]["id"], federation_finance_headers))
        assert line["status"] == "ASSESSED"
        assert line["assessed_fee_cents"] == 401
        assert line["assessed_net_cents"] == 8499
        final = get_success_data(api.get_settlement_period(period["id"], federation_finance_headers))
        assert final["status"] == "ASSESSED"


class TestSettlementWindowHalfOpen:
    def test_completion_at_exactly_period_end_excluded(self, api, settlement_clerk_headers):
        """PRD §3.8: "then keep only lines whose service call's `completed_at`
        falls within the half-open window from `period_start_date` up to but not
        including `period_end_date`".

        Design: Difficulty/boundary_precision_check/settlement_window_half_open_boundary
        """
        scenario = setup_foreign_call_scenario(
            servicing_billing_policy="SCHEDULE",
            tier_overrides={"annual_call_cap": 6},
            provider_overrides={"max_concurrent_dispatches": 3},
        )
        m_id = scenario["membership"]["id"]
        p_id = scenario["primary"]["id"]
        set_clock("2026-09-30T23:00:00Z")
        pair1 = create_and_complete_call_helper(api, m_id, p_id, at="2026-09-30T23:59:59Z")
        line_in = _line_for_call(api, pair1["call"]["id"], settlement_clerk_headers)
        pair2 = create_and_complete_call_helper(api, m_id, p_id, at="2026-10-01T00:00:00Z")
        line_out = _line_for_call(api, pair2["call"]["id"], settlement_clerk_headers)
        period = create_settlement_period(scenario["servicing_club"]["id"])
        closed = validate_success(api.close_settlement_period(period["id"], CLERK_1_HEADERS))
        assert closed["total_foreign_call_count"] == 1
        assert closed["total_gross_cents"] == 8900
        in_after = get_success_data(api.get_settlement_line(line_in["id"], settlement_clerk_headers))
        assert in_after["status"] == "SWEPT"
        assert in_after["settlement_period_id"] == period["id"]
        out_after = get_success_data(api.get_settlement_line(line_out["id"], settlement_clerk_headers))
        assert out_after["status"] == "PENDING"
        assert out_after["settlement_period_id"] is None

    def test_empty_period_closes_cleanly_with_zero_totals(self, api, settlement_clerk_headers):
        """PRD §3.8: "The period records `total_foreign_call_count` as the swept
        count and `total_gross_cents` as the sum of swept `gross_amount_cents`"
        — a sweep with no surviving lines records zero and zero.

        Design: Difficulty/boundary_precision_check/settlement_window_half_open_boundary
        """
        scenario = setup_foreign_call_scenario(servicing_billing_policy="SCHEDULE")
        # Complete a foreign call exactly at the exclusive end so it is NOT swept.
        set_clock("2026-10-01T00:00:00Z")
        complete_foreign_tow_call(scenario, actual_tow_miles=5, requested_tow_miles=5)
        period = create_settlement_period(scenario["servicing_club"]["id"])
        closed = validate_success(api.close_settlement_period(period["id"], CLERK_1_HEADERS))
        assert closed["status"] == "CLOSED"
        assert closed["total_foreign_call_count"] == 0
        assert closed["total_gross_cents"] == 0


class TestSettlementLifecycleErrors:
    def test_assess_open_period_rejected(self, api, federation_finance_headers):
        """PRD §3.8: "assessing an `OPEN` period is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/settlement_assess_from_open_rejected
        """
        scenario = setup_foreign_call_scenario()
        period = create_settlement_period(scenario["servicing_club"]["id"])
        set_clock("2026-10-01T00:00:00Z")
        resp = api.assess_settlement_period(period["id"], federation_finance_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_close_before_period_end_rejected(self, api, settlement_clerk_headers):
        """PRD §3.8: "Closing is allowed only once the logical now has reached
        `period_end_date` — an early close is rejected with
        `ERR_PERIOD_NOT_CLOSABLE`."

        Design: Corner/state_machines/settlement_close_before_window_end_rejected
        """
        scenario = setup_foreign_call_scenario()
        period = create_settlement_period(scenario["servicing_club"]["id"])
        set_clock("2026-09-30T23:59:59Z")
        resp = api.close_settlement_period(period["id"], settlement_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSABLE, expected_status=422)
        after = get_success_data(api.get_settlement_period(period["id"], settlement_clerk_headers))
        assert after["status"] == "OPEN"

    def test_reverse_swept_line_rejected(self, api, federation_finance_headers, settlement_clerk_headers):
        """PRD §3.8: "Reversal is legal only while the line is `PENDING`; a
        `SWEPT` or `ASSESSED` line cannot be reversed and the attempt returns
        `ERR_LINE_ALREADY_SWEPT`."

        Design: Corner/state_machines/settlement_line_reverse_after_sweep_rejected
        """
        scenario = setup_swept_period(servicing_billing_policy="SCHEDULE")
        resp = api.reverse_settlement_line(scenario["line"]["id"], federation_finance_headers)
        validate_error(resp, ApiErrorId.ERR_LINE_ALREADY_SWEPT, expected_status=422)
        after = get_success_data(api.get_settlement_line(scenario["line"]["id"], settlement_clerk_headers))
        assert after["status"] == "SWEPT"


# --- local helpers ---

def create_and_complete_call_helper(api, membership_id, primary_id, at):
    """Complete a foreign TOW call so that completion lands exactly at `at`."""
    call = create_service_call(
        membership_id, primary_id, breakdown_location_state="CS", requested_tow_miles=5,
    )
    from test_helpers import dispatch_call, accept_dispatch, arrive_dispatch, complete_dispatch, set_clock as _set_clock
    dispatch = dispatch_call(call["id"], call["version"])
    accept_dispatch(dispatch["id"], en_route=True)
    arrive_dispatch(dispatch["id"])
    _set_clock(at)
    done = complete_dispatch(dispatch["id"], actual_tow_miles=5)
    return {"call": call, "dispatch": done}


def _line_for_call(api, call_id, headers):
    lines, _meta = validate_paginated(api.list_settlement_lines(headers, params={"service_call_id": call_id}))
    assert len(lines) == 1, f"expected exactly one settlement line for call {call_id}"
    return lines[0]
