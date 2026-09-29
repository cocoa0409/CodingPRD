"""Boundary precision and cross-entity state gating.

Every scenario is built from scratch through the endpoints of the Equity Award
Administration API, because each test starts against an empty database and a
freshly booted logical clock.
"""

from test_helpers import (
    ADMIN,
    BOARD,
    COMPLIANCE,
    ApiErrorId,
    api_client,
    approve_grant_by_board,
    assert_allocations_sum_to_full_bps,
    assert_burn_rate_summary,
    assert_instant_equals,
    assert_reserve_conservation,
    assert_round_then_sum_total,
    certify_cycle,
    create_draft_grant,
    create_mobility_assignment,
    create_open_window,
    create_participant,
    create_plan,
    issue_grant,
    read_cycle,
    read_event,
    read_grant,
    read_plan,
    read_preclearance,
    read_tranche,
    read_window,
    set_clock,
    setup_performance_scenario,
    setup_preclearance_scenario,
    submit_grant,
    validate_error,
    validate_paginated,
    validate_success,
    vest_tranche,
)


# ---------------------------------------------------------------------------
# Fixtures for the burn-rate boundary: burn_rate_limit_bps 100 against
# 1000000 common shares outstanding puts the fiscal-year gross cap at exactly
# 10000 shares (PRD §3.4).
# ---------------------------------------------------------------------------
def _plan_at_burn_limit():
    """An ACTIVE plan whose gross burn cap is exactly 10000 shares, plus one
    ACTIVE recipient."""
    set_clock("2026-03-02T10:00:00Z")
    plan = create_plan(
        name="Plan K Boundary",
        total_authorized_shares=5000000,
        common_shares_outstanding=1000000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=100,
        fungible_ratio_full_value_bps=10000,
        low_reserve_threshold_bps=0,
    )
    participant = create_participant(
        full_name="Kay Edge",
        employee_number="E-2882-11",
        home_country_code="US",
        home_state_code="OR",
        hire_date="2021-04-19",
        birth_date="1994-10-23",
    )
    return plan, participant


def _pending_nso_grant(plan_id, participant_id, shares):
    """An NSO award of ``shares`` shares sitting at PENDING_APPROVAL. Option
    instruments are charged one share for one share, so weighted_reserve_shares
    will come out at exactly ``shares``."""
    grant, tranches = create_draft_grant(
        plan_id,
        participant_id,
        award_type="NSO",
        target_shares=shares,
        exercise_price_cents=4200,
        tranches=[{
            "tranche_index": 1,
            "vest_type": "TIME",
            "scheduled_vest_date": "2027-03-02",
            "target_shares": shares,
        }],
    )
    submit_grant(grant["id"])
    return read_grant(grant["id"]), tranches[0]


class TestBurnRateBoundaryAtLimit:
    """The projected gross burn rate is compared to burn_rate_limit_bps by exact
    integer cross-multiplication on grant approval."""

    def test_burn_rate_projection_one_share_below_limit_is_approved(self):
        """PRD §3.4: "Two plan-level fiscal gates then apply to **both** paths, in this order. First the burn-rate gate: the projected figure is `fiscal_year_gross_granted_shares` plus the `weighted_reserve_shares` just computed, and the approval is refused with `ERR_BURN_RATE_LIMIT_EXCEEDED` when that projection multiplied by 10000 is strictly greater than `burn_rate_limit_bps` multiplied by `common_shares_outstanding`. The comparison is exact integer cross-multiplication and never rounds, so a projection landing exactly on the limit is approved."

        PRD §3.1: "`headroom_shares` is the `burn_rate_limit_bps` multiplied by `common_shares_outstanding`, divided by 10000 and rounded **down** to a whole number of shares, minus `fiscal_year_gross_granted_shares`, and the result is floored at 0 so that an over-budget plan reports zero headroom rather than a negative one."

        Design: Difficulty/boundary_precision_check/burn_rate_exactly_at_limit_allowed
        """
        plan, participant = _plan_at_burn_limit()
        grant, _ = _pending_nso_grant(plan["id"], participant["id"], 9999)

        approved = validate_success(
            api_client.approve_grant(grant["id"], {"approval_path": "BOARD"}, BOARD)
        )

        assert approved["status"] == "APPROVED", (
            "a projection of 9999 shares sits one share below the 10000-share cap "
            f"and must be approved, got status {approved['status']}"
        )
        assert approved["weighted_reserve_shares"] == 9999, (
            "an NSO award is charged one share for one share, so "
            f"weighted_reserve_shares must be 9999, got {approved['weighted_reserve_shares']}"
        )

        summary = validate_success(api_client.get_burn_rate_summary(plan["id"], ADMIN))
        assert_burn_rate_summary(summary, plan=read_plan(plan["id"]))
        assert summary["fiscal_year_gross_granted_shares"] == 9999, (
            "the approval adds the weighted figure to the fiscal-year gross "
            f"accumulator, got {summary['fiscal_year_gross_granted_shares']}"
        )
        assert summary["headroom_shares"] == 1, (
            "the limit converts to 10000 whole shares, so 9999 granted shares leave "
            f"exactly 1 share of headroom, got {summary['headroom_shares']}"
        )

    def test_burn_rate_projection_exactly_at_limit_is_approved_and_next_share_is_refused(self):
        """PRD §3.4: "Two plan-level fiscal gates then apply to **both** paths, in this order. First the burn-rate gate: the projected figure is `fiscal_year_gross_granted_shares` plus the `weighted_reserve_shares` just computed, and the approval is refused with `ERR_BURN_RATE_LIMIT_EXCEEDED` when that projection multiplied by 10000 is strictly greater than `burn_rate_limit_bps` multiplied by `common_shares_outstanding`. The comparison is exact integer cross-multiplication and never rounds, so a projection landing exactly on the limit is approved."

        Design: Difficulty/boundary_precision_check/burn_rate_exactly_at_limit_allowed
        """
        plan, participant = _plan_at_burn_limit()
        grant_at_limit, _ = _pending_nso_grant(plan["id"], participant["id"], 10000)
        grant_one_over, _ = _pending_nso_grant(plan["id"], participant["id"], 1)

        approved = validate_success(
            api_client.approve_grant(
                grant_at_limit["id"], {"approval_path": "BOARD"}, BOARD
            )
        )
        assert approved["status"] == "APPROVED", (
            "a projection landing exactly on the limit is approved, got status "
            f"{approved['status']}"
        )
        assert approved["weighted_reserve_shares"] == 10000, (
            "the 10000-share NSO award must charge exactly 10000 weighted shares, got "
            f"{approved['weighted_reserve_shares']}"
        )

        summary = validate_success(api_client.get_burn_rate_summary(plan["id"], BOARD))
        assert summary["gross_burn_rate_bps"] == 100, (
            "10000 granted shares against 1000000 common shares is exactly 100 basis "
            f"points, got {summary['gross_burn_rate_bps']}"
        )
        assert summary["headroom_shares"] == 0, (
            "a plan sitting exactly on its limit reports zero headroom, got "
            f"{summary['headroom_shares']}"
        )

        validate_error(
            api_client.approve_grant(
                grant_one_over["id"], {"approval_path": "BOARD"}, BOARD
            ),
            ApiErrorId.ERR_BURN_RATE_LIMIT_EXCEEDED.value,
        )

        refused = read_grant(grant_one_over["id"])
        assert refused["status"] == "PENDING_APPROVAL", (
            "the refused approval writes nothing, so the grant stays at "
            f"PENDING_APPROVAL, got {refused['status']}"
        )
        assert refused["weighted_reserve_shares"] == 0, (
            "a grant refused on the burn-rate gate never has its reserve charge "
            f"written, got {refused['weighted_reserve_shares']}"
        )

        after = read_plan(plan["id"])
        assert after["fiscal_year_gross_granted_shares"] == 10000, (
            "the refused approval must not move the fiscal-year gross accumulator, got "
            f"{after['fiscal_year_gross_granted_shares']}"
        )
        assert after["shares_committed_cumulative"] == 10000, (
            "the refused approval must not commit a single further share, got "
            f"{after['shares_committed_cumulative']}"
        )
        assert after["gross_burn_rate_bps"] == 100, (
            f"gross_burn_rate_bps must stay at 100, got {after['gross_burn_rate_bps']}"
        )
        assert_reserve_conservation(after)

    def test_burn_rate_projection_one_share_above_limit_is_refused(self):
        """PRD §3.4: "Two plan-level fiscal gates then apply to **both** paths, in this order. First the burn-rate gate: the projected figure is `fiscal_year_gross_granted_shares` plus the `weighted_reserve_shares` just computed, and the approval is refused with `ERR_BURN_RATE_LIMIT_EXCEEDED` when that projection multiplied by 10000 is strictly greater than `burn_rate_limit_bps` multiplied by `common_shares_outstanding`. The comparison is exact integer cross-multiplication and never rounds, so a projection landing exactly on the limit is approved."

        Design: Difficulty/boundary_precision_check/burn_rate_exactly_at_limit_allowed
        """
        plan, participant = _plan_at_burn_limit()
        grant, _ = _pending_nso_grant(plan["id"], participant["id"], 10001)

        validate_error(
            api_client.approve_grant(grant["id"], {"approval_path": "BOARD"}, BOARD),
            ApiErrorId.ERR_BURN_RATE_LIMIT_EXCEEDED.value,
        )

        refused = read_grant(grant["id"])
        assert refused["status"] == "PENDING_APPROVAL", (
            "a single share over the limit leaves the grant at PENDING_APPROVAL, got "
            f"{refused['status']}"
        )
        assert refused["approved_at"] is None, (
            "a refused approval never stamps approved_at"
        )

        after = read_plan(plan["id"])
        assert after["fiscal_year_gross_granted_shares"] == 0, (
            "nothing is written when the burn-rate gate refuses, got "
            f"{after['fiscal_year_gross_granted_shares']}"
        )
        assert after["shares_committed_cumulative"] == 0, (
            f"no share may be committed, got {after['shares_committed_cumulative']}"
        )
        assert after["gross_burn_rate_bps"] == 0, (
            f"gross_burn_rate_bps must stay at 0, got {after['gross_burn_rate_bps']}"
        )
        assert after["available_reserve_shares"] == 5000000, (
            "the whole authorised pool is still available, got "
            f"{after['available_reserve_shares']}"
        )


# ---------------------------------------------------------------------------
# Fixtures for the workday-coverage boundary: one VESTED settlement whose
# sourcing period is [2026-01-05, 2026-07-01] and whose participant starts with
# no assignment record at all (PRD §3.7).
# ---------------------------------------------------------------------------
def _vested_event_without_workdays():
    """A settlement at PENDING_ALLOCATION for 1000 shares at 5000 cents, whose
    participant has no mobility assignment recorded."""
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Plan L Gap",
        total_authorized_shares=1000000,
        common_shares_outstanding=200000000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=0,
    )
    participant = create_participant(
        full_name="Lee Gap",
        employee_number="E-2882-12",
        home_country_code="US",
        home_state_code="CA",
        hire_date="2023-01-03",
        birth_date="1996-06-06",
    )
    create_open_window(
        plan["id"],
        quarter_label="FY2026-Q1",
        open_at="2026-01-05T00:00:00Z",
        close_at="2026-03-31T00:00:00Z",
    )
    grant, tranches = create_draft_grant(
        plan["id"],
        participant["id"],
        award_type="RSU",
        target_shares=1000,
        tranches=[{
            "tranche_index": 1,
            "vest_type": "TIME",
            "scheduled_vest_date": "2026-07-01",
            "target_shares": 1000,
        }],
    )
    submit_grant(grant["id"])
    approve_grant_by_board(grant["id"])
    issue_grant(grant["id"])
    set_clock("2026-07-01T12:00:00Z")
    event = vest_tranche(
        tranches[0]["id"],
        fmv_per_share_cents=5000,
        withholding_method="SHARE_WITHHOLD",
    )
    return {
        "plan": read_plan(plan["id"]),
        "participant": participant,
        "grant": read_grant(grant["id"]),
        "tranche": read_tranche(tranches[0]["id"]),
        "event": event,
    }


def _tax_rows_by_jurisdiction(event_id):
    rows, meta = validate_paginated(
        api_client.list_event_tax_allocations(event_id, ADMIN)
    )
    return {row["jurisdiction_code"]: row for row in rows}, meta


class TestTaxAllocationWorkdayCoverage:
    """The contained workday set must sum to a strictly positive figure before the
    per-jurisdiction tax rows may be materialised."""

    def test_allocation_with_no_contained_assignment_is_refused(self):
        """PRD §3.7: "If that total is zero — whether because no assignment is contained in the period at all or because every contained assignment records zero workdays — the request is refused with `ERR_WORKDAY_COVERAGE_GAP` and no row is written."

        Design: Difficulty/boundary_precision_check/tax_allocation_empty_workday_set_rejected
        """
        scenario = _vested_event_without_workdays()
        event_id = scenario["event"]["id"]

        assert scenario["event"]["taxable_income_cents"] == 5000000, (
            "1000 gross shares at 5000 cents is 5000000 cents of taxable income, got "
            f"{scenario['event']['taxable_income_cents']}"
        )
        assert scenario["event"]["sourcing_start_date"] == "2026-01-05", (
            "sourcing_start_date is copied from the grant's grant_date, got "
            f"{scenario['event']['sourcing_start_date']}"
        )
        assert scenario["event"]["vest_date"] == "2026-07-01", (
            f"vest_date is the logical clock's calendar date, got {scenario['event']['vest_date']}"
        )

        validate_error(
            api_client.allocate_taxes(event_id, ADMIN),
            ApiErrorId.ERR_WORKDAY_COVERAGE_GAP.value,
        )

        rows, meta = _tax_rows_by_jurisdiction(event_id)
        assert meta["total_count"] == 0, (
            f"no tax row may be written by a refused allocation, got {meta['total_count']}"
        )
        assert rows == {}, "a refused allocation materialises no per-jurisdiction row"

        refreshed = read_event(event_id)
        assert refreshed["tax_status"] == "PENDING_ALLOCATION", (
            "the refused allocation leaves tax_status at PENDING_ALLOCATION, got "
            f"{refreshed['tax_status']}"
        )
        assert refreshed["total_workdays"] == 0, (
            f"total_workdays must stay at 0, got {refreshed['total_workdays']}"
        )
        assert refreshed["total_tax_cents"] == 0, (
            f"total_tax_cents must stay at 0, got {refreshed['total_tax_cents']}"
        )

    def test_allocation_with_contained_zero_workday_assignment_is_refused(self):
        """PRD §3.7: "If that total is zero — whether because no assignment is contained in the period at all or because every contained assignment records zero workdays — the request is refused with `ERR_WORKDAY_COVERAGE_GAP` and no row is written."

        Design: Difficulty/boundary_precision_check/tax_allocation_empty_workday_set_rejected
        """
        scenario = _vested_event_without_workdays()
        event_id = scenario["event"]["id"]

        create_mobility_assignment(
            scenario["participant"]["id"],
            jurisdiction_code="US-CA",
            tax_rate_bps=4200,
            start_date="2026-01-06",
            end_date="2026-02-28",
            workdays=0,
        )

        validate_error(
            api_client.allocate_taxes(event_id, ADMIN),
            ApiErrorId.ERR_WORKDAY_COVERAGE_GAP.value,
        )

        rows, meta = _tax_rows_by_jurisdiction(event_id)
        assert meta["total_count"] == 0, (
            "a non-empty contained set that sums to zero workdays writes no tax row, got "
            f"{meta['total_count']}"
        )

        refreshed = read_event(event_id)
        assert refreshed["tax_status"] == "PENDING_ALLOCATION", (
            "the same rule refuses a contained set of zero workdays, so tax_status stays "
            f"at PENDING_ALLOCATION, got {refreshed['tax_status']}"
        )
        assert refreshed["total_workdays"] == 0, (
            f"total_workdays must stay at 0, got {refreshed['total_workdays']}"
        )

    def test_allocation_with_first_positive_workday_total_succeeds_and_keeps_zero_workday_row(self):
        """PRD §3.7: "A contained group whose own workdays sum to zero is still a contributing group when other groups carry workdays: it produces a tax row with an `allocation_bps` of 0 and a `tax_amount_cents` of 0."

        PRD §3.7: "Third, each group's `tax_amount_cents` is the settlement's `taxable_income_cents` multiplied by that group's `allocation_bps` multiplied by that group's rate, divided by 100000000, rounded half up to whole cents; the division is evaluated once over the exact product, with no intermediate rounding after the allocation step."

        Design: Difficulty/boundary_precision_check/tax_allocation_empty_workday_set_rejected
        """
        scenario = _vested_event_without_workdays()
        event_id = scenario["event"]["id"]

        create_mobility_assignment(
            scenario["participant"]["id"],
            jurisdiction_code="US-CA",
            tax_rate_bps=4200,
            start_date="2026-01-06",
            end_date="2026-02-28",
            workdays=0,
        )
        create_mobility_assignment(
            scenario["participant"]["id"],
            jurisdiction_code="US-NY",
            tax_rate_bps=4000,
            start_date="2026-03-01",
            end_date="2026-06-30",
            workdays=200,
        )

        allocated = validate_success(api_client.allocate_taxes(event_id, ADMIN))

        assert allocated["tax_status"] == "ALLOCATED", (
            "the first strictly positive workday total allows the run, got tax_status "
            f"{allocated['tax_status']}"
        )
        assert allocated["settlement_status"] == "PENDING_TAX", (
            "allocating taxes moves only the tax dimension, got settlement_status "
            f"{allocated['settlement_status']}"
        )
        assert allocated["total_workdays"] == 200, (
            f"total_workdays is the sum of the group figures, got {allocated['total_workdays']}"
        )
        assert allocated["total_tax_cents"] == 2000000, (
            f"total_tax_cents must be 2000000, got {allocated['total_tax_cents']}"
        )
        assert allocated["blended_rate_bps"] == 4000, (
            f"blended_rate_bps must be 4000, got {allocated['blended_rate_bps']}"
        )

        rows, meta = _tax_rows_by_jurisdiction(event_id)
        assert meta["total_count"] == 2, (
            "the zero-workday jurisdiction is still a contributing group, so two rows "
            f"exist, got {meta['total_count']}"
        )
        assert rows["US-CA"]["workdays_in_period"] == 0, (
            f"US-CA sourced 0 workdays, got {rows['US-CA']['workdays_in_period']}"
        )
        assert rows["US-CA"]["allocation_bps"] == 0, (
            f"US-CA must carry allocation_bps 0, got {rows['US-CA']['allocation_bps']}"
        )
        assert rows["US-CA"]["tax_amount_cents"] == 0, (
            f"US-CA must carry tax_amount_cents 0, got {rows['US-CA']['tax_amount_cents']}"
        )
        assert rows["US-NY"]["workdays_in_period"] == 200, (
            f"US-NY sourced 200 workdays, got {rows['US-NY']['workdays_in_period']}"
        )
        assert rows["US-NY"]["allocation_bps"] == 10000, (
            f"US-NY must take the whole allocation, got {rows['US-NY']['allocation_bps']}"
        )
        assert rows["US-NY"]["tax_amount_cents"] == 2000000, (
            f"US-NY must carry tax_amount_cents 2000000, got {rows['US-NY']['tax_amount_cents']}"
        )
        assert_allocations_sum_to_full_bps(list(rows.values()))
        assert_round_then_sum_total(allocated, list(rows.values()))


# ---------------------------------------------------------------------------
# Fixtures for the tranche/cycle dependency: a PSU award whose single
# PERFORMANCE tranche is bound to a still-OPEN cycle and whose
# scheduled_vest_date has already passed on the logical clock (PRD §3.6, §3.7).
# ---------------------------------------------------------------------------
_GATE_PLAN_OVERRIDES = {
    "name": "Plan M Gate",
    "total_authorized_shares": 1000000,
    "common_shares_outstanding": 200000000,
    "fiscal_year_start_date": "2026-01-01",
    "current_fiscal_year_label": "FY2026",
    "burn_rate_limit_bps": 500,
    "fungible_ratio_full_value_bps": 15000,
    "low_reserve_threshold_bps": 0,
}


def _performance_tranche_past_its_schedule():
    """A GRANTED PSU award with one PERFORMANCE tranche of 8000 target shares
    bound to an OPEN cycle whose target_value is 200; the clock is moved past the
    tranche's scheduled_vest_date so the cycle's state is the only blocker."""
    scenario = setup_performance_scenario(
        clock="2026-01-05T09:00:00Z",
        target_value=200,
        tranche_target_shares=8000,
        award_type="PSU",
        scheduled_vest_date="2026-07-01",
        plan_overrides=dict(_GATE_PLAN_OVERRIDES),
        participant_overrides={
            "full_name": "Moe Perf",
            "employee_number": "E-2882-13",
            "home_country_code": "US",
            "home_state_code": "CA",
            "hire_date": "2018-10-08",
            "birth_date": "1987-01-14",
        },
        window_overrides={
            "quarter_label": "FY2026-Q1",
            "open_at": "2026-01-05T00:00:00Z",
            "close_at": "2026-03-31T00:00:00Z",
        },
    )
    set_clock("2026-07-01T12:00:00Z")
    scenario["tranche"] = read_tranche(scenario["tranches"][0]["id"])
    return scenario


class TestPerformanceTrancheVestGate:
    """A PERFORMANCE tranche depends on its cycle: no certification, no vest."""

    def test_performance_tranche_cannot_vest_while_cycle_is_open(self):
        """PRD §3.7: "When the tranche's `vest_type` is `PERFORMANCE`, its bound cycle must be `CERTIFIED`; a cycle still `OPEN` or already `CANCELLED` yields `ERR_PERFORMANCE_NOT_CERTIFIED`, because a performance tranche's share count is provisional until the multiplier is fixed."

        Design: Difficulty/cross_entity_state_dependency/performance_tranche_vest_blocked_until_cycle_certified
        """
        scenario = _performance_tranche_past_its_schedule()
        tranche_id = scenario["tranches"][0]["id"]

        assert read_cycle(scenario["cycle"]["id"])["status"] == "OPEN", (
            "the cycle must still be OPEN for this scenario to isolate the gate"
        )
        assert scenario["tranche"]["shares"] == 0, (
            "an uncertified performance tranche carries 0 effective shares, got "
            f"{scenario['tranche']['shares']}"
        )

        validate_error(
            api_client.vest_tranche(
                tranche_id,
                {"fmv_per_share_cents": 4000, "withholding_method": "SHARE_WITHHOLD"},
                ADMIN,
            ),
            ApiErrorId.ERR_PERFORMANCE_NOT_CERTIFIED.value,
        )

        refused = read_tranche(tranche_id)
        assert refused["status"] == "UNVESTED", (
            "the refused vest leaves the tranche UNVESTED, got "
            f"{refused['status']}"
        )
        assert refused["shares"] == 0, (
            "the refused vest leaves the provisional share count at 0, got "
            f"{refused['shares']}"
        )
        assert refused["vested_at"] is None, (
            "a refused vest never stamps vested_at"
        )

        events, meta = validate_paginated(
            api_client.list_vesting_events(ADMIN, params={"tranche_id": tranche_id})
        )
        assert meta["total_count"] == 0, (
            "a refused vest creates no settlement record, got "
            f"{meta['total_count']}"
        )
        assert events == [], "a refused vest creates no settlement record"

    def test_performance_tranche_vests_after_cycle_certification_sizes_its_shares(self):
        """PRD §3.6: "In the first, every tranche bound to the cycle whose status is `UNVESTED` has its `shares` rewritten as its own `target_shares` multiplied by `payout_multiplier_bps`, divided by 10000, rounded half up to whole shares; a tranche already `VESTED`, `SETTLED`, or `FORFEITED` keeps whatever share count it had."

        PRD §3.7: "When the tranche's `vest_type` is `PERFORMANCE`, its bound cycle must be `CERTIFIED`; a cycle still `OPEN` or already `CANCELLED` yields `ERR_PERFORMANCE_NOT_CERTIFIED`, because a performance tranche's share count is provisional until the multiplier is fixed."

        Design: Difficulty/cross_entity_state_dependency/performance_tranche_vest_blocked_until_cycle_certified
        """
        scenario = _performance_tranche_past_its_schedule()
        tranche_id = scenario["tranches"][0]["id"]

        validate_error(
            api_client.vest_tranche(
                tranche_id,
                {"fmv_per_share_cents": 4000, "withholding_method": "SHARE_WITHHOLD"},
                ADMIN,
            ),
            ApiErrorId.ERR_PERFORMANCE_NOT_CERTIFIED.value,
        )

        certified = certify_cycle(scenario["cycle"]["id"], 210, headers=BOARD)
        assert certified["status"] == "CERTIFIED", (
            f"an achievement ratio of 1.05 certifies the cycle, got {certified['status']}"
        )
        assert certified["payout_multiplier_bps"] == 10000, (
            "a ratio of 1.05 falls in the tier paying 10000 basis points, got "
            f"{certified['payout_multiplier_bps']}"
        )

        resized = read_tranche(tranche_id)
        assert resized["shares"] == 8000, (
            "8000 target shares at 10000 basis points is 8000 effective shares, got "
            f"{resized['shares']}"
        )
        grant = read_grant(scenario["grant"]["id"])
        assert grant["weighted_reserve_shares"] == 12000, (
            "8000 shares weighted at 15000 basis points is 12000 weighted shares, got "
            f"{grant['weighted_reserve_shares']}"
        )
        plan = read_plan(scenario["plan"]["id"])
        assert plan["available_reserve_shares"] == 988000, (
            "the certification commits 12000 weighted shares against the 1000000-share "
            f"pool, got {plan['available_reserve_shares']}"
        )
        assert_reserve_conservation(plan)

        event = validate_success(
            api_client.vest_tranche(
                tranche_id,
                {"fmv_per_share_cents": 4000, "withholding_method": "SHARE_WITHHOLD"},
                ADMIN,
            ),
            201,
        )

        assert read_tranche(tranche_id)["status"] == "VESTED", (
            "the identical call succeeds once the cycle is CERTIFIED"
        )
        assert event["gross_shares"] == 8000, (
            "gross_shares snapshots the tranche's certified share count, got "
            f"{event['gross_shares']}"
        )
        assert event["vest_date"] == "2026-07-01", (
            f"vest_date is the logical clock's calendar date, got {event['vest_date']}"
        )
        assert event["sourcing_start_date"] == "2026-01-05", (
            "sourcing_start_date is copied from the grant's grant_date, got "
            f"{event['sourcing_start_date']}"
        )
        assert event["taxable_income_cents"] == 32000000, (
            "8000 shares at 4000 cents is 32000000 cents of taxable income, got "
            f"{event['taxable_income_cents']}"
        )
        assert event["tax_status"] == "PENDING_ALLOCATION", (
            f"a fresh settlement starts at PENDING_ALLOCATION, got {event['tax_status']}"
        )


# ---------------------------------------------------------------------------
# Fixtures for the preclearance/window dependency: an OPEN window over
# [2026-01-05T00:00:00Z, 2026-01-20T00:00:00Z) carrying one SUBMITTED request
# (PRD §3.9).
# ---------------------------------------------------------------------------
def _submitted_request_in_short_window():
    """One SUBMITTED preclearance request for 400 SELL shares inside an OPEN
    window whose close_at is 2026-01-20T00:00:00Z."""
    return setup_preclearance_scenario(
        clock="2026-01-06T10:00:00Z",
        insider_status="DESIGNATED_INSIDER",
        plan_overrides={
            "name": "Plan N Interval",
            "total_authorized_shares": 1000000,
            "common_shares_outstanding": 200000000,
            "fiscal_year_start_date": "2026-01-01",
            "current_fiscal_year_label": "FY2026",
            "burn_rate_limit_bps": 500,
            "fungible_ratio_full_value_bps": 15000,
            "low_reserve_threshold_bps": 0,
        },
        participant_overrides={
            "full_name": "Nia Clock",
            "employee_number": "E-2882-14",
            "home_country_code": "US",
            "home_state_code": "VA",
            "hire_date": "2014-07-07",
            "birth_date": "1981-08-28",
        },
        window_overrides={
            "quarter_label": "FY2026-Q1",
            "open_at": "2026-01-05T00:00:00Z",
            "close_at": "2026-01-20T00:00:00Z",
        },
        request_overrides={
            "transaction_type": "SELL",
            "requested_shares": 400,
            "intended_trade_date": "2026-01-15",
        },
    )


def _assert_request_untouched_by_refusal(request_id, window_id):
    refused = read_preclearance(request_id)
    assert refused["status"] == "SUBMITTED", (
        f"a refused approval leaves the request SUBMITTED, got {refused['status']}"
    )
    assert refused["valid_until"] is None, (
        "a refused approval computes no validity, so valid_until stays null, got "
        f"{refused['valid_until']}"
    )
    assert refused["decided_at"] is None, (
        "a refused approval stamps no decision instant"
    )
    window = read_window(window_id)
    assert window["approved_shares_cumulative"] == 0, (
        "a refused approval reserves no share against the window, got "
        f"{window['approved_shares_cumulative']}"
    )
    assert window["status"] == "OPEN", (
        "the window row still reads OPEN throughout - the refusal is driven by the "
        f"clock against close_at, got {window['status']}"
    )


class TestPreclearanceApprovalWindowInterval:
    """Approval depends on the window being genuinely tradeable, which is a
    half-open interval test against the logical clock rather than a status flag."""

    def test_approval_refused_one_second_after_window_close_at(self):
        """PRD §3.9: "Being `OPEN` is necessary but not sufficient for trading: a window is genuinely tradeable only when its status is `OPEN` **and** the logical clock lies at or after `open_at` and strictly before `close_at`."

        PRD §3.9: "The window must be genuinely tradeable, otherwise `ERR_TRADING_WINDOW_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/preclearance_approval_requires_open_window
        """
        scenario = _submitted_request_in_short_window()
        set_clock("2026-01-20T00:00:01Z")

        validate_error(
            api_client.decide_preclearance_request(
                scenario["request"]["id"],
                {"decision": "APPROVE", "decision_note": "Attempt past close_at."},
                COMPLIANCE,
            ),
            ApiErrorId.ERR_TRADING_WINDOW_CLOSED.value,
        )

        _assert_request_untouched_by_refusal(
            scenario["request"]["id"], scenario["window"]["id"]
        )

    def test_approval_refused_exactly_at_window_close_at(self):
        """PRD §3.9: "Being `OPEN` is necessary but not sufficient for trading: a window is genuinely tradeable only when its status is `OPEN` **and** the logical clock lies at or after `open_at` and strictly before `close_at`."

        Design: Difficulty/cross_entity_state_dependency/preclearance_approval_requires_open_window
        """
        scenario = _submitted_request_in_short_window()
        set_clock("2026-01-20T00:00:00Z")

        validate_error(
            api_client.decide_preclearance_request(
                scenario["request"]["id"],
                {"decision": "APPROVE", "decision_note": "Attempt on close_at."},
                COMPLIANCE,
            ),
            ApiErrorId.ERR_TRADING_WINDOW_CLOSED.value,
        )

        _assert_request_untouched_by_refusal(
            scenario["request"]["id"], scenario["window"]["id"]
        )

    def test_approval_inside_window_interval_stamps_validity_and_reserves_shares(self):
        """PRD §3.9: "On success the request becomes `APPROVED`, `decided_by_user_id`, `decided_at`, and `decision_note` are stored, `valid_until` is computed as described below, the window's `approved_shares_cumulative` is increased by `requested_shares`, and both the request's `version` and the window's `version` advance by 1."

        PRD §3.9: "On approval, `valid_until` is the earlier of the `decided_at` instant advanced by 5 days and the window's own `close_at` — a clearance is good for five days or until the window closes, whichever comes first."

        Design: Difficulty/cross_entity_state_dependency/preclearance_approval_requires_open_window
        """
        scenario = _submitted_request_in_short_window()
        set_clock("2026-01-20T00:00:01Z")

        validate_error(
            api_client.decide_preclearance_request(
                scenario["request"]["id"],
                {"decision": "APPROVE", "decision_note": "Attempt past close_at."},
                COMPLIANCE,
            ),
            ApiErrorId.ERR_TRADING_WINDOW_CLOSED.value,
        )

        set_clock("2026-01-10T10:00:00Z")
        approved = validate_success(
            api_client.decide_preclearance_request(
                scenario["request"]["id"],
                {"decision": "APPROVE", "decision_note": "Cleared inside the window."},
                COMPLIANCE,
            )
        )

        assert approved["status"] == "APPROVED", (
            "the identical call inside the half-open interval succeeds, got "
            f"{approved['status']}"
        )
        assert_instant_equals(
            approved["decided_at"], "2026-01-10T10:00:00.000Z", "decided_at"
        )
        assert_instant_equals(
            approved["valid_until"], "2026-01-15T10:00:00.000Z", "valid_until"
        )
        assert approved["decision_note"] == "Cleared inside the window.", (
            f"the decision note is stored, got {approved['decision_note']!r}"
        )

        window = read_window(scenario["window"]["id"])
        assert window["approved_shares_cumulative"] == 400, (
            "the approval reserves the requested 400 shares against the window, got "
            f"{window['approved_shares_cumulative']}"
        )
        assert window["status"] == "OPEN", (
            f"the window is still OPEN after the approval, got {window['status']}"
        )
