"""Temporal overlap on contended calendars, and the compensating actions that
must restore the invariants their forward actions moved.

Every scenario is built from scratch through the endpoints of the Equity Award
Administration API, because each test starts against an empty database and a
freshly booted logical clock.
"""

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    ApiErrorId,
    api_client,
    approve_grant_by_delegate,
    assert_approval_authority,
    assert_instant_equals,
    assert_mobility_assignment,
    assert_reserve_conservation,
    assert_share_split_identity,
    assert_trading_window,
    create_authority,
    create_draft_grant,
    create_participant,
    create_plan,
    create_window,
    read_authority,
    read_event,
    read_grant,
    read_plan,
    read_tranche,
    set_clock,
    setup_settled_event,
    submit_grant,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Fixtures for the workday calendar: one participant owning exactly one closed
# assignment period, US-CA 2026-01-06..2026-03-05 (PRD §3.3).
# ---------------------------------------------------------------------------
def _participant_with_one_assignment():
    set_clock("2026-01-05T09:00:00Z")
    participant = create_participant(
        full_name="Mia Move",
        employee_number="E-2882-15",
        home_country_code="US",
        home_state_code="CA",
        hire_date="2019-03-11",
        birth_date="1989-04-02",
    )
    existing = validate_success(
        api_client.create_mobility_assignment(
            {
                "participant_id": participant["id"],
                "jurisdiction_code": "US-CA",
                "tax_rate_bps": 4500,
                "start_date": "2026-01-06",
                "end_date": "2026-03-05",
                "workdays": 40,
            },
            ADMIN,
        ),
        201,
    )
    assert_mobility_assignment(existing)
    return participant, existing


def _assignments_of(participant_id, params=None):
    return validate_paginated(
        api_client.list_participant_mobility_assignments(
            participant_id, ADMIN, params=params
        )
    )


class TestMobilityAssignmentInclusiveOverlap:
    """A participant's assignment periods are closed intervals, so the endpoints
    themselves collide."""

    def test_new_period_starting_on_existing_end_date_is_refused(self):
        """PRD §3.3: "Assignment periods are closed intervals, inclusive at both ends, and no two periods of the same participant may intersect. The comparison is inclusive on both endpoints, which means a new period beginning on the exact `end_date` of an existing one overlaps and is refused with `ERR_ASSIGNMENT_PERIOD_OVERLAP`, while a period beginning one day later is accepted."

        Design: Difficulty/resource_temporal_overlap/mobility_assignment_inclusive_date_overlap
        """
        participant, existing = _participant_with_one_assignment()

        validate_error(
            api_client.create_mobility_assignment(
                {
                    "participant_id": participant["id"],
                    "jurisdiction_code": "US-NY",
                    "tax_rate_bps": 4484,
                    "start_date": "2026-03-05",
                    "end_date": "2026-04-30",
                    "workdays": 38,
                },
                ADMIN,
            ),
            ApiErrorId.ERR_ASSIGNMENT_PERIOD_OVERLAP.value,
        )

        rows, meta = _assignments_of(participant["id"])
        assert meta["total_count"] == 1, (
            "the refused period is never written, so the participant still owns one "
            f"assignment, got {meta['total_count']}"
        )
        assert rows[0]["end_date"] == "2026-03-05", (
            "the incumbent period is untouched by the refusal, got end_date "
            f"{rows[0]['end_date']}"
        )
        assert rows[0]["id"] == existing["id"], (
            "the surviving row is the incumbent US-CA period"
        )

    def test_new_period_contained_inside_existing_period_is_refused(self):
        """PRD §3.3: "Assignment periods are closed intervals, inclusive at both ends, and no two periods of the same participant may intersect. The comparison is inclusive on both endpoints, which means a new period beginning on the exact `end_date` of an existing one overlaps and is refused with `ERR_ASSIGNMENT_PERIOD_OVERLAP`, while a period beginning one day later is accepted."

        Design: Difficulty/resource_temporal_overlap/mobility_assignment_inclusive_date_overlap
        """
        participant, _ = _participant_with_one_assignment()

        validate_error(
            api_client.create_mobility_assignment(
                {
                    "participant_id": participant["id"],
                    "jurisdiction_code": "US-TX",
                    "tax_rate_bps": 0,
                    "start_date": "2026-02-01",
                    "end_date": "2026-02-10",
                    "workdays": 7,
                },
                ADMIN,
            ),
            ApiErrorId.ERR_ASSIGNMENT_PERIOD_OVERLAP.value,
        )

        _, meta = _assignments_of(participant["id"])
        assert meta["total_count"] == 1, (
            "a period wholly inside an incumbent one intersects it and is never "
            f"written, got {meta['total_count']}"
        )
        _, texas = _assignments_of(
            participant["id"], params={"jurisdiction_code": "US-TX"}
        )
        assert texas["total_count"] == 0, (
            "no US-TX assignment row may exist after the refusal, got "
            f"{texas['total_count']}"
        )

    def test_new_period_starting_one_day_after_existing_end_date_is_accepted(self):
        """PRD §3.3: "Assignment periods are closed intervals, inclusive at both ends, and no two periods of the same participant may intersect. The comparison is inclusive on both endpoints, which means a new period beginning on the exact `end_date` of an existing one overlaps and is refused with `ERR_ASSIGNMENT_PERIOD_OVERLAP`, while a period beginning one day later is accepted."

        PRD §3.3: "Assignment rows are immutable once written — there is no update endpoint, no `updated_at`, and no `version`."

        Design: Difficulty/resource_temporal_overlap/mobility_assignment_inclusive_date_overlap
        """
        participant, existing = _participant_with_one_assignment()

        validate_error(
            api_client.create_mobility_assignment(
                {
                    "participant_id": participant["id"],
                    "jurisdiction_code": "US-NY",
                    "tax_rate_bps": 4484,
                    "start_date": "2026-03-05",
                    "end_date": "2026-04-30",
                    "workdays": 38,
                },
                ADMIN,
            ),
            ApiErrorId.ERR_ASSIGNMENT_PERIOD_OVERLAP.value,
        )

        accepted = validate_success(
            api_client.create_mobility_assignment(
                {
                    "participant_id": participant["id"],
                    "jurisdiction_code": "US-NY",
                    "tax_rate_bps": 4484,
                    "start_date": "2026-03-06",
                    "end_date": "2026-04-30",
                    "workdays": 38,
                },
                ADMIN,
            ),
            201,
        )

        assert accepted["start_date"] == "2026-03-06", (
            "a period beginning one day after the incumbent's end_date is accepted, got "
            f"start_date {accepted['start_date']}"
        )
        assert_mobility_assignment(accepted)

        rows, meta = _assignments_of(participant["id"])
        assert meta["total_count"] == 2, (
            "the participant now owns two non-intersecting periods, got "
            f"{meta['total_count']}"
        )
        incumbent = next(row for row in rows if row["id"] == existing["id"])
        assert incumbent["end_date"] == "2026-03-05", (
            "the incumbent period is unchanged by the refusal and the acceptance, got "
            f"end_date {incumbent['end_date']}"
        )


# ---------------------------------------------------------------------------
# Fixtures for the plan's trading calendar: one SCHEDULED window over
# [2026-01-05T00:00:00Z, 2026-03-31T00:00:00Z) (PRD §3.9).
# ---------------------------------------------------------------------------
_CALENDAR_PLAN = {
    "name": "Plan O Calendar",
    "total_authorized_shares": 1000000,
    "common_shares_outstanding": 200000000,
    "fiscal_year_start_date": "2026-01-01",
    "current_fiscal_year_label": "FY2026",
    "burn_rate_limit_bps": 500,
    "fungible_ratio_full_value_bps": 15000,
    "low_reserve_threshold_bps": 0,
}


def _plan_with_one_scheduled_window():
    set_clock("2026-01-02T09:00:00Z")
    plan = create_plan(**_CALENDAR_PLAN)
    window = create_window(
        plan["id"],
        quarter_label="FY2026-Q1",
        open_at="2026-01-05T00:00:00Z",
        close_at="2026-03-31T00:00:00Z",
    )
    assert window["status"] == "SCHEDULED", (
        f"a freshly scheduled window is SCHEDULED, got {window['status']}"
    )
    assert_trading_window(window)
    return plan, window


def _schedule_window(plan_id, quarter_label, open_at, close_at):
    return api_client.create_trading_window(
        {
            "plan_id": plan_id,
            "quarter_label": quarter_label,
            "open_at": open_at,
            "close_at": close_at,
        },
        COMPLIANCE,
    )


def _windows_of(plan_id):
    return validate_paginated(api_client.list_plan_trading_windows(plan_id, COMPLIANCE))


class TestTradingWindowHalfOpenIntervalAndBuffer:
    """Window intervals are half-open, so the shared instant is not an overlap - it
    is a blackout-buffer violation."""

    def test_window_opening_exactly_at_incumbent_close_at_is_a_buffer_violation_not_an_overlap(self):
        """PRD §3.9: "First, the new interval may not overlap any window of the same plan that is not `CLOSED`. Window intervals are half-open — inclusive of `open_at`, exclusive of `close_at` — and are compared half-open, so a new window whose `open_at` equals an existing window's `close_at` does not overlap. An overlap is refused with `ERR_TRADING_WINDOW_OVERLAP`."

        PRD §3.9: "Second, even non-overlapping windows must be separated by a 48-hour blackout buffer measured from the preceding non-`CLOSED` window's `close_at` to the new window's `open_at`, so that the market can absorb the prior window's trades; a gap of exactly 48 hours is allowed, while 47 hours and 59 minutes is refused with `ERR_TRADING_WINDOW_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/trading_window_half_open_plus_buffer
        """
        plan, _ = _plan_with_one_scheduled_window()

        response = _schedule_window(
            plan["id"], "FY2026-Q2A", "2026-03-31T00:00:00Z", "2026-04-15T00:00:00Z"
        )
        reported = response.json().get("data", {}).get("error_id")
        assert reported != ApiErrorId.ERR_TRADING_WINDOW_OVERLAP.value, (
            "sharing the incumbent's close_at instant is not an overlap under half-open "
            f"semantics, yet the refusal reported {reported}"
        )
        validate_error(response, ApiErrorId.ERR_TRADING_WINDOW_BUFFER_VIOLATION.value)

        rows, meta = _windows_of(plan["id"])
        assert meta["total_count"] == 1, (
            f"the refused window is never written, got {meta['total_count']} windows"
        )
        assert [row["quarter_label"] for row in rows] == ["FY2026-Q1"], (
            "only the incumbent FY2026-Q1 window survives the refusal, got "
            f"{[row['quarter_label'] for row in rows]}"
        )

    def test_window_opening_inside_incumbent_interval_is_refused_as_an_overlap(self):
        """PRD §3.9: "Two calendar rules guard creation, and their order matters. First, the new interval may not overlap any window of the same plan that is not `CLOSED`."

        PRD §3.9: "Because the buffer is checked immediately after the overlap rule, a window that both overlaps and violates the buffer reports the overlap."

        Design: Difficulty/resource_temporal_overlap/trading_window_half_open_plus_buffer
        """
        plan, _ = _plan_with_one_scheduled_window()

        validate_error(
            _schedule_window(
                plan["id"], "FY2026-Q2B", "2026-03-30T00:00:00Z", "2026-04-20T00:00:00Z"
            ),
            ApiErrorId.ERR_TRADING_WINDOW_OVERLAP.value,
        )

        rows, meta = _windows_of(plan["id"])
        assert meta["total_count"] == 1, (
            f"the overlapping window is never written, got {meta['total_count']}"
        )
        assert "FY2026-Q2B" not in [row["quarter_label"] for row in rows], (
            "no window row may carry the refused quarter_label FY2026-Q2B"
        )

    def test_window_opening_forty_seven_hours_fifty_nine_minutes_after_close_is_refused(self):
        """PRD §3.9: "Second, even non-overlapping windows must be separated by a 48-hour blackout buffer measured from the preceding non-`CLOSED` window's `close_at` to the new window's `open_at`, so that the market can absorb the prior window's trades; a gap of exactly 48 hours is allowed, while 47 hours and 59 minutes is refused with `ERR_TRADING_WINDOW_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/trading_window_half_open_plus_buffer
        """
        plan, _ = _plan_with_one_scheduled_window()

        validate_error(
            _schedule_window(
                plan["id"], "FY2026-Q2C", "2026-04-01T23:59:00Z", "2026-04-20T00:00:00Z"
            ),
            ApiErrorId.ERR_TRADING_WINDOW_BUFFER_VIOLATION.value,
        )

        _, meta = _windows_of(plan["id"])
        assert meta["total_count"] == 1, (
            "a gap one minute short of the blackout buffer writes nothing, got "
            f"{meta['total_count']} windows"
        )

    def test_window_opening_exactly_forty_eight_hours_after_close_is_scheduled(self):
        """PRD §3.9: "Second, even non-overlapping windows must be separated by a 48-hour blackout buffer measured from the preceding non-`CLOSED` window's `close_at` to the new window's `open_at`, so that the market can absorb the prior window's trades; a gap of exactly 48 hours is allowed, while 47 hours and 59 minutes is refused with `ERR_TRADING_WINDOW_BUFFER_VIOLATION`."

        PRD §3.9: "A new window is `SCHEDULED` with `approved_shares_cumulative` at 0 and `suspension_reason` null."

        Design: Difficulty/resource_temporal_overlap/trading_window_half_open_plus_buffer
        """
        plan, incumbent = _plan_with_one_scheduled_window()

        validate_error(
            _schedule_window(
                plan["id"], "FY2026-Q2A", "2026-03-31T00:00:00Z", "2026-04-15T00:00:00Z"
            ),
            ApiErrorId.ERR_TRADING_WINDOW_BUFFER_VIOLATION.value,
        )
        validate_error(
            _schedule_window(
                plan["id"], "FY2026-Q2B", "2026-03-30T00:00:00Z", "2026-04-20T00:00:00Z"
            ),
            ApiErrorId.ERR_TRADING_WINDOW_OVERLAP.value,
        )

        accepted = validate_success(
            _schedule_window(
                plan["id"], "FY2026-Q2", "2026-04-02T00:00:00Z", "2026-04-30T00:00:00Z"
            ),
            201,
        )

        assert_instant_equals(
            accepted["open_at"], "2026-04-02T00:00:00.000Z", "TradingWindow.open_at"
        )
        assert accepted["status"] == "SCHEDULED", (
            f"a window accepted at exactly 48 hours is SCHEDULED, got {accepted['status']}"
        )
        assert accepted["approved_shares_cumulative"] == 0, (
            "a new window starts with approved_shares_cumulative 0, got "
            f"{accepted['approved_shares_cumulative']}"
        )
        assert accepted["suspension_reason"] is None, (
            f"a new window carries a null suspension_reason, got {accepted['suspension_reason']!r}"
        )
        assert_trading_window(accepted)

        rows, meta = _windows_of(plan["id"])
        assert meta["total_count"] == 2, (
            "only the incumbent and the accepted window exist, got "
            f"{meta['total_count']}"
        )
        labels = sorted(row["quarter_label"] for row in rows)
        assert labels == ["FY2026-Q1", "FY2026-Q2"], (
            "no row may survive for the refused labels FY2026-Q2A or FY2026-Q2B, got "
            f"{labels}"
        )
        assert incumbent["id"] in [row["id"] for row in rows], (
            "the incumbent window is untouched by the two refusals"
        )


# ---------------------------------------------------------------------------
# Fixtures for the compensating cancellation: an RSU grant approved on the
# delegated path whose weighted charge exhausts the delegation exactly
# (PRD §3.1, §3.4).
# ---------------------------------------------------------------------------
_CONSERVE_PLAN = {
    "name": "Plan P Conserve",
    "total_authorized_shares": 500000,
    "common_shares_outstanding": 200000000,
    "fiscal_year_start_date": "2026-01-01",
    "current_fiscal_year_label": "FY2026",
    "burn_rate_limit_bps": 500,
    "fungible_ratio_full_value_bps": 15000,
    "low_reserve_threshold_bps": 0,
}


def _grant_approved_under_exhausted_delegation():
    """Approve a 10000-share RSU grant, charging 15000 weighted shares, through a
    delegation whose per-grant and aggregate caps are both exactly 15000."""
    set_clock("2026-02-16T10:00:00Z")
    plan = create_plan(**_CONSERVE_PLAN)
    authority = create_authority(
        plan["id"],
        authority_type="DELEGATED_OFFICER",
        delegate_user_id="officer-1",
        per_grant_share_cap=15000,
        aggregate_share_cap=15000,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    participant = create_participant(
        full_name="Pat Pool",
        employee_number="E-2882-16",
        home_country_code="US",
        home_state_code="MN",
        hire_date="2020-06-01",
        birth_date="1993-02-12",
    )
    grant, tranches = create_draft_grant(
        plan["id"],
        participant["id"],
        award_type="RSU",
        target_shares=10000,
        tranches=[{
            "tranche_index": 1,
            "vest_type": "TIME",
            "scheduled_vest_date": "2027-02-16",
            "target_shares": 10000,
        }],
    )
    submit_grant(grant["id"])
    grant = approve_grant_by_delegate(grant["id"], authority["id"], "officer-1")

    plan_after_approve = read_plan(plan["id"])
    assert plan_after_approve["available_reserve_shares"] == 485000, (
        "the 15000 weighted shares are debited from the 500000-share pool, leaving "
        f"485000, got {plan_after_approve['available_reserve_shares']}"
    )
    authority_after_approve = read_authority(authority["id"])
    assert authority_after_approve["status"] == "EXHAUSTED", (
        "a delegation consumed to its aggregate cap is EXHAUSTED, got "
        f"{authority_after_approve['status']}"
    )
    assert authority_after_approve["remaining_shares"] == 0, (
        "the delegation has no capacity left before the cancellation, got "
        f"{authority_after_approve['remaining_shares']}"
    )
    return plan, authority, grant, tranches[0]


class TestGrantCancellationRestoresReserveIdentity:
    """Cancelling credits back exactly the figure the approval debited."""

    def test_cancellation_credits_back_the_exact_weighted_figure_without_unwinding_gross_burn(self):
        """PRD §3.1: "A conservation identity must hold after every request and after every individual cascade hop: the available reserve, plus cumulative commitments, minus cumulative returns, always equals the authorised total. A compensating action must therefore credit back exactly the amount the forward action debited — never a re-derived figure."

        PRD §3.4: "When the grant had a non-zero `weighted_reserve_shares`, that exact figure is added to the plan's `shares_returned_cumulative` and to its `fiscal_year_returned_shares`, after which the reserve ledger, `reserve_posture`, and the net burn rate are recomputed — the gross burn rate is deliberately **not** unwound."

        Design: Difficulty/compensating_invariant/grant_cancel_restores_plan_reserve_identity
        """
        plan, _, grant, _ = _grant_approved_under_exhausted_delegation()

        validate_success(
            api_client.cancel_grant(
                grant["id"], {"cancel_reason": "DUPLICATE_AWARD"}, ADMIN
            )
        )

        refreshed = read_plan(plan["id"])
        assert refreshed["shares_committed_cumulative"] == 15000, (
            "the commitment accumulator is monotonic and keeps the 15000 it recorded, got "
            f"{refreshed['shares_committed_cumulative']}"
        )
        assert refreshed["shares_returned_cumulative"] == 15000, (
            "the cancellation credits back exactly 15000 returned shares, got "
            f"{refreshed['shares_returned_cumulative']}"
        )
        assert refreshed["available_reserve_shares"] == 500000, (
            "the pool is whole again at 500000 available shares, got "
            f"{refreshed['available_reserve_shares']}"
        )
        assert_reserve_conservation(refreshed)
        assert (
            refreshed["available_reserve_shares"]
            + refreshed["shares_committed_cumulative"]
            - refreshed["shares_returned_cumulative"]
        ) == 500000, "the conservation identity must land back on the authorised total"
        assert refreshed["fiscal_year_gross_granted_shares"] == 15000, (
            "the fiscal-year gross accumulator never decreases, got "
            f"{refreshed['fiscal_year_gross_granted_shares']}"
        )
        assert refreshed["fiscal_year_returned_shares"] == 15000, (
            "the fiscal-year returned accumulator records the released 15000, got "
            f"{refreshed['fiscal_year_returned_shares']}"
        )
        assert refreshed["gross_burn_rate_bps"] == 1, (
            "the gross burn rate is deliberately not unwound and stays at 1 bp, got "
            f"{refreshed['gross_burn_rate_bps']}"
        )
        assert refreshed["net_burn_rate_bps"] == 0, (
            "the net burn rate falls back to 0 once the shares come back, got "
            f"{refreshed['net_burn_rate_bps']}"
        )

    def test_cancellation_returns_the_exhausted_delegation_to_active_with_full_capacity(self):
        """PRD §3.4: "When the grant had been approved under a delegation, that delegation's `consumed_shares` is reduced by the released figure, `remaining_shares` is recomputed, and an `EXHAUSTED` delegation returns to `ACTIVE` once `remaining_shares` is greater than 0."

        Design: Difficulty/compensating_invariant/grant_cancel_restores_plan_reserve_identity
        """
        _, authority, grant, _ = _grant_approved_under_exhausted_delegation()

        validate_success(
            api_client.cancel_grant(
                grant["id"], {"cancel_reason": "DUPLICATE_AWARD"}, ADMIN
            )
        )

        refreshed = read_authority(authority["id"])
        assert refreshed["consumed_shares"] == 0, (
            "the released 15000 shares are subtracted from consumed_shares, got "
            f"{refreshed['consumed_shares']}"
        )
        assert refreshed["remaining_shares"] == 15000, (
            "remaining_shares is recomputed to the whole 15000 aggregate cap, got "
            f"{refreshed['remaining_shares']}"
        )
        assert refreshed["status"] == "ACTIVE", (
            "an EXHAUSTED delegation returns to ACTIVE once capacity is restored, got "
            f"{refreshed['status']}"
        )
        assert_approval_authority(refreshed)

    def test_cancellation_zeroes_the_grant_charge_and_forfeits_its_tranche(self):
        """PRD §3.4: "Cancelling sets the status to `CANCELLED`, stores the reason, and moves every tranche of the grant whose status is `UNVESTED` or `VESTED` to `FORFEITED`, which for a `VESTED` tranche also reverses any settlement of that tranche still awaiting tax treatment (see §3.7)."

        PRD §3.4: "Finally the grant's own `weighted_reserve_shares` and `outstanding_shares` are set to 0."

        Design: Difficulty/compensating_invariant/grant_cancel_restores_plan_reserve_identity
        """
        _, _, grant, tranche = _grant_approved_under_exhausted_delegation()

        cancelled = validate_success(
            api_client.cancel_grant(
                grant["id"], {"cancel_reason": "DUPLICATE_AWARD"}, ADMIN
            )
        )

        assert cancelled["status"] == "CANCELLED", (
            f"the grant moves to CANCELLED, got {cancelled['status']}"
        )
        assert cancelled["cancel_reason"] == "DUPLICATE_AWARD", (
            f"the supplied reason is stored, got {cancelled['cancel_reason']!r}"
        )
        reread = read_grant(grant["id"])
        assert reread["weighted_reserve_shares"] == 0, (
            "the cancelled grant's own weighted charge is zeroed, got "
            f"{reread['weighted_reserve_shares']}"
        )
        assert reread["outstanding_shares"] == 0, (
            f"the cancelled grant carries no outstanding shares, got {reread['outstanding_shares']}"
        )
        refreshed_tranche = read_tranche(tranche["id"])
        assert refreshed_tranche["status"] == "FORFEITED", (
            "the UNVESTED tranche of a cancelled grant is FORFEITED, got "
            f"{refreshed_tranche['status']}"
        )


# ---------------------------------------------------------------------------
# Fixtures for the compensating reversal: one SHARE_WITHHOLD settlement carried
# all the way to SETTLED over a single US-CA sourcing period (PRD §3.7).
# ---------------------------------------------------------------------------
_REVERSE_PLAN = {
    "name": "Plan Q Reverse",
    "total_authorized_shares": 1000000,
    "common_shares_outstanding": 200000000,
    "fiscal_year_start_date": "2026-01-01",
    "current_fiscal_year_label": "FY2026",
    "burn_rate_limit_bps": 500,
    "fungible_ratio_full_value_bps": 15000,
    "low_reserve_threshold_bps": 0,
}

_REVERSE_PARTICIPANT = {
    "full_name": "Ray Undo",
    "employee_number": "E-2882-17",
    "home_country_code": "US",
    "home_state_code": "CA",
    "hire_date": "2021-02-01",
    "birth_date": "1990-09-09",
}


def _settled_share_withhold_scenario():
    """A 1000-share RSU tranche vested at 5000 cents and settled by SHARE_WITHHOLD,
    so 400 shares are withheld against 2000000 cents of US-CA tax."""
    scenario = setup_settled_event(
        clock="2026-01-05T09:00:00Z",
        vest_clock="2026-07-01T12:00:00Z",
        fmv_per_share_cents=5000,
        withholding_method="SHARE_WITHHOLD",
        target_shares=1000,
        scheduled_vest_date="2026-07-01",
        plan_overrides=_REVERSE_PLAN,
        participant_overrides=dict(_REVERSE_PARTICIPANT),
        window_overrides={
            "quarter_label": "FY2026-Q1",
            "open_at": "2026-01-05T00:00:00Z",
            "close_at": "2026-03-31T00:00:00Z",
        },
        grant_overrides={"award_type": "RSU"},
        jurisdictions=[{
            "jurisdiction_code": "US-CA",
            "tax_rate_bps": 4000,
            "start_date": "2026-01-06",
            "end_date": "2026-06-30",
            "workdays": 250,
        }],
    )
    event = scenario["event"]
    assert event["shares_withheld"] == 400, (
        "the SHARE_WITHHOLD settlement withholds 400 shares against 2000000 cents of "
        f"tax at 5000 cents a share, got {event['shares_withheld']}"
    )
    assert event["net_shares_delivered"] == 600, (
        f"600 of the 1000 gross shares are delivered, got {event['net_shares_delivered']}"
    )
    assert scenario["participant"]["insider_status"] == "NON_INSIDER", (
        "the recipient is a NON_INSIDER, so no Section 16 report is minted by the "
        f"settlement, got {scenario['participant']['insider_status']}"
    )
    return scenario


def _reverse(event_id):
    return validate_success(
        api_client.reverse_vesting_event(
            event_id, {"reversal_reason": "MISSTATED_FMV"}, ADMIN
        )
    )


class TestSettlementReversalRestoresShareSplitAndTaxLedger:
    """Reversing a settlement conserves the tranche's share count and the
    settlement's share-split identity."""

    def test_reversal_returns_the_withheld_shares_to_the_net_delivery(self):
        """PRD §3.7: "Reversal sets `settlement_status` to `REVERSED`, stores the reason, zeroes `shares_withheld`, `shares_sold`, `residual_cash_cents`, and `cash_due_cents`, and restores `net_shares_delivered` to `gross_shares`."

        PRD §3.7: "On every one of the three branches the same identity must hold: `gross_shares` equals `net_shares_delivered` plus `shares_withheld` plus `shares_sold`."

        Design: Difficulty/compensating_invariant/settlement_reverse_restores_share_split_and_tax_zero
        """
        scenario = _settled_share_withhold_scenario()

        reversed_event = _reverse(scenario["event"]["id"])

        assert reversed_event["settlement_status"] == "REVERSED", (
            f"the settlement moves to REVERSED, got {reversed_event['settlement_status']}"
        )
        assert reversed_event["reversal_reason"] == "MISSTATED_FMV", (
            f"the supplied reason is stored, got {reversed_event['reversal_reason']!r}"
        )
        assert reversed_event["shares_withheld"] == 0, (
            f"shares_withheld is zeroed, got {reversed_event['shares_withheld']}"
        )
        assert reversed_event["shares_sold"] == 0, (
            f"shares_sold is zeroed, got {reversed_event['shares_sold']}"
        )
        assert reversed_event["net_shares_delivered"] == 1000, (
            "net_shares_delivered is restored to the 1000 gross shares, got "
            f"{reversed_event['net_shares_delivered']}"
        )
        assert reversed_event["residual_cash_cents"] == 0, (
            f"residual_cash_cents is zeroed, got {reversed_event['residual_cash_cents']}"
        )
        assert reversed_event["cash_due_cents"] == 0, (
            f"cash_due_cents is zeroed, got {reversed_event['cash_due_cents']}"
        )
        assert reversed_event["gross_shares"] == 1000, (
            f"gross_shares is untouched at 1000, got {reversed_event['gross_shares']}"
        )
        assert_share_split_identity(reversed_event)
        assert_share_split_identity(read_event(scenario["event"]["id"]))

    def test_reversal_zeroes_the_tax_ledger_and_deletes_every_tax_row(self):
        """PRD §3.7: "It also drives `tax_status` back to `PENDING_ALLOCATION`, zeroes `total_tax_cents`, `total_workdays`, and `blended_rate_bps`, and deletes every tax row of the settlement, so the allocation can be redone from current workday records."

        Design: Difficulty/compensating_invariant/settlement_reverse_restores_share_split_and_tax_zero
        """
        scenario = _settled_share_withhold_scenario()
        assert scenario["event"]["total_tax_cents"] == 2000000, (
            "the US-CA allocation charged 2000000 cents before the reversal, got "
            f"{scenario['event']['total_tax_cents']}"
        )

        _reverse(scenario["event"]["id"])

        refreshed = read_event(scenario["event"]["id"])
        assert refreshed["tax_status"] == "PENDING_ALLOCATION", (
            "the settlement is ready to be allocated again, got "
            f"{refreshed['tax_status']}"
        )
        assert refreshed["total_tax_cents"] == 0, (
            f"total_tax_cents is zeroed, got {refreshed['total_tax_cents']}"
        )
        assert refreshed["total_workdays"] == 0, (
            f"total_workdays is zeroed, got {refreshed['total_workdays']}"
        )
        assert refreshed["blended_rate_bps"] == 0, (
            f"blended_rate_bps is zeroed, got {refreshed['blended_rate_bps']}"
        )
        _, meta = validate_paginated(
            api_client.list_event_tax_allocations(scenario["event"]["id"], ADMIN)
        )
        assert meta["total_count"] == 0, (
            "every tax row of the settlement is deleted, got "
            f"{meta['total_count']} rows"
        )

    def test_reversal_restores_the_tranche_and_grant_without_touching_the_reserve(self):
        """PRD §3.7: "The owning tranche moves from `SETTLED` back to `VESTED` with its `shares` untouched, and the grant's `outstanding_shares` returns to its pre-settlement value."

        PRD §3.7: "Settling records the `withholding_method` in force, writes the five derived figures, moves `settlement_status` to `SETTLED`, and moves the owning tranche from `VESTED` to `SETTLED`, which causes the grant's `outstanding_shares` to be recomputed — a `SETTLED` tranche leaves the outstanding pool while remaining committed against the reserve."

        PRD §3.9: "Reports are never created by a client. Two side effects create them, and both fire only when the participant's `insider_status` is `SECTION_16_OFFICER` or `DESIGNATED_INSIDER`."

        Design: Difficulty/compensating_invariant/settlement_reverse_restores_share_split_and_tax_zero
        """
        scenario = _settled_share_withhold_scenario()

        _reverse(scenario["event"]["id"])

        tranche = read_tranche(scenario["tranche"]["id"])
        assert tranche["status"] == "VESTED", (
            f"the owning tranche returns to VESTED, got {tranche['status']}"
        )
        assert tranche["shares"] == 1000, (
            f"the tranche's share count is untouched at 1000, got {tranche['shares']}"
        )

        grant = read_grant(scenario["grant"]["id"])
        assert grant["outstanding_shares"] == 1000, (
            "outstanding_shares returns to its pre-settlement 1000, got "
            f"{grant['outstanding_shares']}"
        )
        assert grant["weighted_reserve_shares"] == 1500, (
            "the reserve charge is untouched by the reversal and stays at 1500, got "
            f"{grant['weighted_reserve_shares']}"
        )

        plan = read_plan(scenario["plan"]["id"])
        assert plan["shares_committed_cumulative"] == 1500, (
            "the plan still carries the 1500-share commitment, got "
            f"{plan['shares_committed_cumulative']}"
        )
        assert plan["shares_returned_cumulative"] == 0, (
            "a settlement reversal returns no share to the pool, got "
            f"{plan['shares_returned_cumulative']}"
        )
        assert_reserve_conservation(plan)

        _, reports = validate_paginated(
            api_client.list_participant_transaction_reports(
                scenario["participant"]["id"], COMPLIANCE
            )
        )
        assert reports["total_count"] == 0, (
            "a NON_INSIDER recipient has no Section 16 report before or after the "
            f"reversal, got {reports['total_count']}"
        )
