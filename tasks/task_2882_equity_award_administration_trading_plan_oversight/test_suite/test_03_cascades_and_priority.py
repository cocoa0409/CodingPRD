"""Multi-hop cascades and the rejection ladder's precedence pairs.

Two write endpoints each drive a chain in which every link is caused by the
previous one: terminating a participant forfeits a tranche, which rewrites its
grant, which credits the plan ledger, which flips the reserve posture; certifying
a performance cycle rewrites tranche share counts, which lifts the owning grant's
weight, which debits the plan ledger. Two further scenarios pin the rejection
ladder: a request that trips both a state check and a later business check must
report the state error.
"""

from test_helpers import (
    ADMIN,
    BOARD,
    COMPLIANCE,
    OFFICER,
    ApiErrorId,
    api_client,
    assert_approval_authority,
    assert_grant,
    assert_iso_date,
    assert_participant,
    assert_performance_cycle,
    assert_reserve_conservation,
    assert_reserve_posture,
    assert_retirement_eligibility,
    assert_trading_window,
    assert_vesting_tranche,
    create_authority,
    create_cycle,
    create_draft_grant,
    create_granted_grant,
    create_open_window,
    create_participant,
    create_plan,
    create_preclearance_request_payload,
    approve_grant_by_board,
    certify_payload,
    drive_window,
    make_participant_headers,
    read_authority,
    read_event,
    read_grant,
    read_participant,
    read_plan,
    read_tranche,
    read_window,
    set_clock,
    submit_grant,
    terminate_participant_payload,
    validate_error,
    validate_paginated,
    validate_success,
    vest_tranche,
)

_WINDOW_OPEN_AT = "2026-01-05T00:00:00Z"
_WINDOW_CLOSE_AT = "2026-03-31T00:00:00Z"


def _termination_cascade_scenario():
    """A RESTRICTED plan with 100000 authorized shares carrying one GRANTED RSU
    award of 40000 shares: tranche 1 of 15000 already VESTED and awaiting tax
    treatment, tranche 2 of 25000 still UNVESTED. The clock stands on the
    termination date.
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Plan G Reserve",
        total_authorized_shares=100_000,
        common_shares_outstanding=200_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=5000,
    )
    participant = create_participant(
        full_name="Gwen Leaver",
        employee_number="E-2882-07",
        home_country_code="US",
        home_state_code="IL",
        hire_date="2019-01-07",
        birth_date="1985-06-15",
    )
    create_open_window(
        plan["id"], quarter_label="FY2026-Q1",
        open_at=_WINDOW_OPEN_AT, close_at=_WINDOW_CLOSE_AT,
    )
    grant, tranches = create_granted_grant(
        plan["id"], participant["id"],
        award_type="RSU", target_shares=40000,
        tranches=[
            {"tranche_index": 1, "vest_type": "TIME",
             "scheduled_vest_date": "2026-07-01", "target_shares": 15000},
            {"tranche_index": 2, "vest_type": "TIME",
             "scheduled_vest_date": "2027-07-01", "target_shares": 25000},
        ],
    )
    plan_before = read_plan(plan["id"])
    assert plan_before["available_reserve_shares"] == 40000, (
        "60000 weighted shares against 100000 authorized"
    )
    assert plan_before["reserve_posture"] == "RESTRICTED", (
        "40000 available sits below the 50000-share threshold"
    )

    set_clock("2026-07-01T12:00:00Z")
    event = vest_tranche(tranches[0]["id"], fmv_per_share_cents=5000)
    set_clock("2026-08-03T09:00:00Z")
    return {"plan": plan, "plan_before": plan_before, "participant": participant,
            "grant": grant, "tranches": tranches, "event": event}


def _terminate_voluntarily(participant_id):
    return validate_success(
        api_client.terminate_participant(
            participant_id,
            terminate_participant_payload("2026-08-03", "VOLUNTARY"),
            ADMIN,
        ),
        200,
    )


class TestTerminationForfeitureCascade:
    """POST /participants/{id}/terminate and the four hops it sets off."""

    def test_termination_forfeits_the_unvested_tranche_and_rewrites_its_grant(self):
        """PRD §3.8: "For each `UNVESTED` tranche, the reference date is the `termination_date` and eligibility is `retirement_eligible` as evaluated at that date." "In every other case the tranche moves to `FORFEITED`."

        PRD §3.8: "For each tranche already `VESTED`, the reason decides: under `FOR_CAUSE` the tranche is clawed back to `FORFEITED`, and under every other reason it is left alone."

        PRD §3.8: "A grant whose recomputed `outstanding_shares` is greater than zero moves to `PARTIALLY_FORFEITED`; a grant whose `outstanding_shares` recomputes to exactly 0 and none of whose tranches is `SETTLED` moves to `FORFEITED` with both `outstanding_shares` and `weighted_reserve_shares` set to 0."

        Design: Difficulty/transitive_cascade/termination_forfeiture_cascade_depth_four
        """
        scenario = _termination_cascade_scenario()
        _terminate_voluntarily(scenario["participant"]["id"])

        vested = read_tranche(scenario["tranches"][0]["id"])
        assert vested["status"] == "VESTED", (
            "a VOLUNTARY termination never claws back a vested tranche"
        )
        forfeited = read_tranche(scenario["tranches"][1]["id"])
        assert forfeited["status"] == "FORFEITED", (
            "the UNVESTED tranche of a non-accelerating termination forfeits"
        )
        assert forfeited["acceleration_reason"] is None
        assert_vesting_tranche(forfeited)

        grant = read_grant(scenario["grant"]["id"])
        assert grant["status"] == "PARTIALLY_FORFEITED", (
            "outstanding_shares recomputes above zero, so the grant is only "
            "partially forfeited"
        )
        assert grant["outstanding_shares"] == 15000, (
            "the surviving VESTED tranche stays in the outstanding pool"
        )
        assert grant["weighted_reserve_shares"] == 22500, (
            "15000 full-value shares weighted at 15000 bps"
        )
        assert_grant(grant)

        event = read_event(scenario["event"]["id"])
        assert event["settlement_status"] == "PENDING_TAX", (
            "a VOLUNTARY termination leaves an unsettled settlement alone"
        )
        assert event["tax_status"] == "PENDING_ALLOCATION"

    def test_the_returned_weight_reaches_the_plan_ledger_and_flips_the_posture(self):
        """PRD §3.8: "Each grant's weight decrease from hop 2 is added to the plan's `shares_returned_cumulative` and to its `fiscal_year_returned_shares`. A fully forfeited grant returns its entire prior `weighted_reserve_shares`. The reserve ledger is then rerun, rewriting `available_reserve_shares`, and the net burn rate is recomputed. The gross burn rate is not unwound."

        PRD §3.8: "The increase in `available_reserve_shares` from hop 3 is fed back through the posture rule, which can flip `reserve_posture` from `RESTRICTED` to `OPEN` and thereby restore headroom that a later delegated approval depends on."

        Design: Difficulty/transitive_cascade/termination_forfeiture_cascade_depth_four
        """
        scenario = _termination_cascade_scenario()
        assert scenario["plan_before"]["gross_burn_rate_bps"] == 3
        assert scenario["plan_before"]["net_burn_rate_bps"] == 3

        _terminate_voluntarily(scenario["participant"]["id"])

        plan = read_plan(scenario["plan"]["id"])
        assert plan["shares_committed_cumulative"] == 60000, (
            "the commitment side of the ledger is never rewound"
        )
        assert plan["shares_returned_cumulative"] == 37500, (
            "60000 weighted shares fall to 22500, so 37500 come back"
        )
        assert plan["fiscal_year_returned_shares"] == 37500
        assert plan["available_reserve_shares"] == 77500
        assert plan["gross_burn_rate_bps"] == 3, (
            "the gross burn rate is not unwound"
        )
        assert plan["net_burn_rate_bps"] == 1, (
            "the net burn rate is recomputed over 22500 surviving shares"
        )
        assert plan["reserve_posture"] == "OPEN", (
            "77500 available now clears the 50000-share threshold"
        )
        assert_reserve_posture(plan)
        assert_reserve_conservation(plan)

    def test_termination_freezes_the_participant_and_dates_the_exercise_period(self):
        """PRD §3.8: "It also writes `ptep_expiry_date`, the date on which the post-termination exercise period ends: the `termination_date` advanced by 0 days for `FOR_CAUSE`, 90 days for `VOLUNTARY`, 180 days for `INVOLUNTARY`, 1095 days for `RETIREMENT`, and 365 days for `DEATH`."

        Design: Difficulty/transitive_cascade/termination_forfeiture_cascade_depth_four
        """
        scenario = _termination_cascade_scenario()
        terminated = _terminate_voluntarily(scenario["participant"]["id"])

        assert terminated["employment_status"] == "TERMINATED"
        assert terminated["termination_reason"] == "VOLUNTARY"
        assert terminated["termination_date"] == "2026-08-03"
        assert terminated["retirement_eligible"] is False, (
            "a participant born 1985-06-15 is far from the age floor"
        )
        assert_retirement_eligibility(terminated)
        assert_iso_date(terminated["ptep_expiry_date"], "ptep_expiry_date")
        assert terminated["ptep_expiry_date"] == "2026-11-01", (
            "2026-08-03 advanced by the 90 days a VOLUNTARY termination earns"
        )
        assert_participant(terminated)

        stored = read_participant(scenario["participant"]["id"])
        assert stored["ptep_expiry_date"] == "2026-11-01"
        assert stored["employment_status"] == "TERMINATED"


def _performance_cascade_scenario():
    """An OPEN cycle with target 100 and one GRANTED PSU award of 20000 shares
    whose single PERFORMANCE tranche is bound to that cycle, so the tranche still
    carries 0 shares and the grant has committed nothing.
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Plan H Performance",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=200_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=1000,
    )
    participant = create_participant(
        full_name="Hal Metric",
        employee_number="E-2882-08",
        home_country_code="US",
        home_state_code="TX",
        hire_date="2016-08-15",
        birth_date="1983-03-21",
    )
    create_open_window(
        plan["id"], quarter_label="FY2026-Q1",
        open_at=_WINDOW_OPEN_AT, close_at=_WINDOW_CLOSE_AT,
    )
    cycle = create_cycle(
        plan["id"], metric_code="REV2026", target_value=100,
        certification_due_date="2026-03-31",
    )
    grant, tranches = create_granted_grant(
        plan["id"], participant["id"],
        award_type="PSU", target_shares=20000,
        tranches=[
            {"tranche_index": 1, "vest_type": "PERFORMANCE",
             "scheduled_vest_date": "2027-03-31", "target_shares": 20000,
             "performance_cycle_id": cycle["id"]},
        ],
    )
    assert grant["weighted_reserve_shares"] == 0, (
        "an uncertified performance tranche commits nothing against the reserve"
    )
    return {"plan": plan, "participant": participant, "cycle": cycle,
            "grant": grant, "tranches": tranches}


class TestPerformanceCertificationCascade:
    """POST /performance-cycles/{id}/certify and the three hops it sets off."""

    def test_certification_rewrites_tranche_shares_and_lifts_the_grant_weight(self):
        """PRD §3.6: "That ratio is then looked up against a tier schedule whose boundaries are inclusive on the lower edge: a ratio below 0.800000 pays 0 basis points; a ratio from 0.800000 up to but not including 0.900000 pays 5000; from 0.900000 up to but not including 1.000000 pays 7500; from 1.000000 up to but not including 1.100000 pays 10000; from 1.100000 up to but not including 1.200000 pays 15000; and a ratio of 1.200000 or more pays the maximum of 20000."

        PRD §3.6: "In the first, every tranche bound to the cycle whose status is `UNVESTED` has its `shares` rewritten as its own `target_shares` multiplied by `payout_multiplier_bps`, divided by 10000, rounded half up to whole shares; a tranche already `VESTED`, `SETTLED`, or `FORFEITED` keeps whatever share count it had."

        Design: Difficulty/transitive_cascade/performance_certification_cascade_depth_three
        """
        scenario = _performance_cascade_scenario()
        certified = validate_success(
            api_client.certify_performance_cycle(
                scenario["cycle"]["id"], certify_payload(115), BOARD
            ),
            200,
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["actual_value"] == 115
        assert certified["payout_multiplier_bps"] == 15000, (
            "a ratio of 1.150000 sits in the 1.100000 tier"
        )
        assert certified["certified_by_user_id"] == "board-1", (
            "the certifier is a different identity from the cycle's creator"
        )
        assert_performance_cycle(certified)

        tranche = read_tranche(scenario["tranches"][0]["id"])
        assert tranche["shares"] == 30000, (
            "20000 target shares at 15000 basis points"
        )
        assert tranche["target_shares"] == 20000, (
            "target_shares is immutable once the grant exists"
        )
        assert tranche["status"] == "UNVESTED", (
            "certification revises the share count without vesting anything"
        )
        assert_vesting_tranche(tranche)

        grant = read_grant(scenario["grant"]["id"])
        assert grant["weighted_reserve_shares"] == 45000, (
            "30000 full-value shares weighted at 15000 bps"
        )
        assert grant["outstanding_shares"] == 30000
        assert grant["status"] == "GRANTED"
        assert_grant(grant)

    def test_the_positive_weight_delta_debits_the_plan_ledger(self):
        """PRD §3.6: "In the second, every grant owning a tranche the first hop touched recomputes `weighted_reserve_shares` and `outstanding_shares` by the rule of §3.4. In the third, each grant's signed weight delta is applied to the plan: a positive delta is added to `shares_committed_cumulative` and also to `fiscal_year_gross_granted_shares`, while a negative delta is added to `shares_returned_cumulative` and also to `fiscal_year_returned_shares`. The reserve ledger, `reserve_posture`, `gross_burn_rate_bps`, and `net_burn_rate_bps` are then all recomputed."

        Design: Difficulty/transitive_cascade/performance_certification_cascade_depth_three
        """
        scenario = _performance_cascade_scenario()
        plan_before = read_plan(scenario["plan"]["id"])
        assert plan_before["shares_committed_cumulative"] == 0
        assert plan_before["available_reserve_shares"] == 1_000_000

        validate_success(
            api_client.certify_performance_cycle(
                scenario["cycle"]["id"], certify_payload(115), BOARD
            ),
            200,
        )

        plan = read_plan(scenario["plan"]["id"])
        assert plan["shares_committed_cumulative"] == 45000, (
            "the positive weight delta lands on the commitment accumulator"
        )
        assert plan["fiscal_year_gross_granted_shares"] == 45000
        assert plan["shares_returned_cumulative"] == 0, (
            "an upward revision returns nothing"
        )
        assert plan["fiscal_year_returned_shares"] == 0
        assert plan["available_reserve_shares"] == 955000
        assert plan["gross_burn_rate_bps"] == 2
        assert plan["net_burn_rate_bps"] == 2, (
            "with nothing returned the two variants agree"
        )
        assert plan["reserve_posture"] == "OPEN"
        assert_reserve_posture(plan)
        assert_reserve_conservation(plan)


def _approved_grant_and_undersized_authority():
    """An APPROVED RSU grant carrying 15000 weighted shares alongside an ACTIVE
    delegation whose aggregate cap of 1000 shares cannot cover it.
    """
    set_clock("2026-02-09T11:00:00Z")
    plan = create_plan(
        name="Plan I Priority",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=200_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=0,
    )
    authority = create_authority(
        plan["id"],
        authority_type="DELEGATED_OFFICER",
        delegate_user_id="officer-1",
        per_grant_share_cap=100000,
        aggregate_share_cap=1000,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    participant = create_participant(
        full_name="Ivy Cap",
        employee_number="E-2882-09",
        home_country_code="US",
        home_state_code="CO",
        hire_date="2020-11-02",
        birth_date="1991-05-05",
    )
    grant, tranches = create_draft_grant(
        plan["id"], participant["id"],
        award_type="RSU", target_shares=10000,
        tranches=[
            {"tranche_index": 1, "vest_type": "TIME",
             "scheduled_vest_date": "2027-02-09", "target_shares": 10000},
        ],
    )
    submit_grant(grant["id"])
    grant = approve_grant_by_board(grant["id"])
    assert grant["status"] == "APPROVED"
    assert grant["weighted_reserve_shares"] == 15000
    return {"plan": plan, "authority": authority, "participant": participant,
            "grant": grant, "tranches": tranches}


class TestGrantStateBeatsAuthorityCap:
    """A replayed approval trips the state gate before the delegation's cap."""

    def test_reapproving_an_approved_grant_reports_the_state_error(self):
        """PRD §2.6: "When a single request violates more than one rule, exactly one error is returned, and which one is fully determined by a fixed ladder. Checks are evaluated in this order, and the first violation short-circuits the request so that nothing is written:"

        PRD §2.6: "The state gate — the addressed row must be in a state from which the requested transition exists — yielding the entity-specific invalid-state error described in §2.7. Replaying a transition that already succeeded lands here, which is how the system refuses idempotent repeats."

        PRD §2.6: "Business-safety, temporal, and fiscal rules, in the order set out where each workflow is described in §3."

        Design: Difficulty/priority_pair_validation_conflict/grant_state_beats_authority_fiscal_cap
        """
        scenario = _approved_grant_and_undersized_authority()
        validate_error(
            api_client.approve_grant(
                scenario["grant"]["id"],
                {"approval_path": "DELEGATED",
                 "authority_id": scenario["authority"]["id"]},
                OFFICER,
            ),
            ApiErrorId.ERR_GRANT_INVALID_STATE,
        )

    def test_the_refused_reapproval_consumes_none_of_the_delegation(self):
        """PRD §2.6: "Checks are evaluated in this order, and the first violation short-circuits the request so that nothing is written:"

        Design: Difficulty/priority_pair_validation_conflict/grant_state_beats_authority_fiscal_cap
        """
        scenario = _approved_grant_and_undersized_authority()
        validate_error(
            api_client.approve_grant(
                scenario["grant"]["id"],
                {"approval_path": "DELEGATED",
                 "authority_id": scenario["authority"]["id"]},
                OFFICER,
            ),
            ApiErrorId.ERR_GRANT_INVALID_STATE,
        )

        grant = read_grant(scenario["grant"]["id"])
        assert grant["status"] == "APPROVED", (
            "the refused replay leaves the grant exactly as the first approval "
            "left it"
        )
        assert grant["approval_path"] == "BOARD"
        assert grant["approved_by_user_id"] == "board-1"
        assert grant["approved_under_authority_id"] is None, (
            "the delegated path never took effect"
        )
        assert grant["weighted_reserve_shares"] == 15000

        authority = read_authority(scenario["authority"]["id"])
        assert authority["consumed_shares"] == 0, (
            "a short-circuited request writes nothing to the delegation"
        )
        assert authority["remaining_shares"] == 1000
        assert authority["status"] == "ACTIVE"
        assert_approval_authority(authority)

        plan = read_plan(scenario["plan"]["id"])
        assert plan["shares_committed_cumulative"] == 15000, (
            "the ledger is not double-charged"
        )
        assert_reserve_conservation(plan)


def _suspended_window_scenario():
    """A window opened and then suspended, with a designated insider standing by
    and no preclearance request on file.
    """
    set_clock("2026-01-06T10:00:00Z")
    plan = create_plan(
        name="Plan J Window",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=200_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=0,
    )
    participant = create_participant(
        full_name="Jon Blackout",
        employee_number="E-2882-10",
        home_country_code="US",
        home_state_code="NJ",
        hire_date="2015-02-16",
        birth_date="1977-09-08",
        insider_status="DESIGNATED_INSIDER",
    )
    window = create_open_window(
        plan["id"], quarter_label="FY2026-Q1",
        open_at=_WINDOW_OPEN_AT, close_at=_WINDOW_CLOSE_AT,
    )
    window = drive_window(
        window["id"], "SUSPEND", suspension_reason="MATERIAL_NEWS_PENDING"
    )
    assert window["status"] == "SUSPENDED"
    return {"plan": plan, "participant": participant, "window": window}


def _file_request_outside_the_span(scenario):
    payload = create_preclearance_request_payload(
        scenario["participant"]["id"], scenario["window"]["id"],
        transaction_type="SELL", requested_shares=250,
        intended_trade_date="2026-05-15",
    )
    return api_client.create_preclearance_request(
        payload, make_participant_headers(scenario["participant"]["id"])
    )


class TestWindowSafetyBeatsTradeDate:
    """A suspended window outranks an out-of-span intended trade date."""

    def test_suspended_window_reports_the_window_error_not_the_trade_date_error(self):
        """PRD §3.9: "The named window must be genuinely tradeable in the sense above — a `SUSPENDED` window, a `SCHEDULED` window whose `open_at` is still in the future, and an `OPEN` window whose `close_at` has already passed on the logical clock all yield `ERR_TRADING_WINDOW_CLOSED`."

        PRD §3.9: "The window-status rule sits above the trade-date rule, so a request that violates both reports `ERR_TRADING_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/window_safety_beats_trade_date_temporal
        """
        scenario = _suspended_window_scenario()
        validate_error(
            _file_request_outside_the_span(scenario),
            ApiErrorId.ERR_TRADING_WINDOW_CLOSED,
        )

    def test_the_refused_filing_leaves_no_request_and_no_reservation(self):
        """PRD §3.9: "The `intended_trade_date` must fall inside the window's date span, from the calendar date of `open_at` through the calendar date of `close_at` inclusive, and must not be earlier than the logical clock date; a violation is `ERR_TRADE_DATE_OUTSIDE_WINDOW`. And when the window carries a non-null `aggregate_share_cap`, its `approved_shares_cumulative` plus the `requested_shares` may not exceed that cap, otherwise `ERR_WINDOW_SHARE_CAP_EXCEEDED`. That last rule is an aggregate check across sibling requests: each individual request may be modest while the collective busts the ceiling. Only requests in `APPROVED` and `EXECUTED` status count toward `approved_shares_cumulative`; a `DENIED`, `EXPIRED`, or `VOID` request releases its reservation. The window-status rule sits above the trade-date rule, so a request that violates both reports `ERR_TRADING_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/window_safety_beats_trade_date_temporal
        """
        scenario = _suspended_window_scenario()
        validate_error(
            _file_request_outside_the_span(scenario),
            ApiErrorId.ERR_TRADING_WINDOW_CLOSED,
        )

        window = read_window(scenario["window"]["id"])
        assert window["status"] == "SUSPENDED"
        assert window["suspension_reason"] == "MATERIAL_NEWS_PENDING"
        assert window["approved_shares_cumulative"] == 0, (
            "a refused filing reserves nothing"
        )
        assert_trading_window(window)

        rows, meta = validate_paginated(
            api_client.list_preclearance_requests(
                COMPLIANCE, params={"window_id": scenario["window"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "the short-circuited request was never written"
        )
        assert rows == []
