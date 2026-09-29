"""Reserve arithmetic, the evergreen rollover and the compliance calendar.

Every test builds its own world from scratch against the deterministic logical
clock, because the harness empties the database before each one.
"""

from test_helpers import (
    ADMIN,
    BOARD,
    COMPLIANCE,
    api_client,
    assert_equity_plan,
    assert_grant,
    assert_instant_equals,
    assert_reserve_conservation,
    assert_reserve_posture,
    assert_three_fractional_digits,
    assert_transaction_report,
    assert_vesting_event,
    assert_vesting_tranche,
    canonical_instant,
    get_success_data,
    make_participant_headers,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local composite setup helpers. They live here rather than in the shared
# helpers because each one encodes a preamble only this module needs.
# ---------------------------------------------------------------------------
PLAN_BASE = {
    "total_authorized_shares": 1_000_000,
    "common_shares_outstanding": 1_000_000,
    "fiscal_year_start_date": "2026-01-01",
}


def _set_clock(instant, headers=ADMIN):
    return get_success_data(api_client.set_clock(instant, headers))


def _register_plan(**overrides):
    payload = dict(PLAN_BASE)
    payload.setdefault("name", "Reserve Arithmetic Plan")
    payload.update(overrides)
    return get_success_data(api_client.create_equity_plan(payload, ADMIN))


def _enrol_participant(employee_number, **overrides):
    payload = {
        "full_name": "Reserve Recipient",
        "employee_number": employee_number,
        "home_country_code": "US",
        "home_state_code": "CA",
        "hire_date": "2020-01-06",
        "birth_date": "1985-01-01",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_participant(payload, ADMIN))


def _open_window(plan_id, quarter_label, open_at, close_at, **overrides):
    payload = {
        "plan_id": plan_id,
        "quarter_label": quarter_label,
        "open_at": open_at,
        "close_at": close_at,
    }
    payload.update(overrides)
    window = get_success_data(api_client.create_trading_window(payload, COMPLIANCE))
    return get_success_data(
        api_client.set_trading_window_status(window["id"], {"action": "OPEN"}, COMPLIANCE)
    )


def _draft_with_tranches(plan_id, participant_id, award_type, target_shares,
                         tranches, exercise_price_cents=None):
    """Draft a grant and append every tranche while it is still DRAFT."""
    payload = {
        "plan_id": plan_id,
        "participant_id": participant_id,
        "award_type": award_type,
        "target_shares": target_shares,
    }
    if exercise_price_cents is not None:
        payload["exercise_price_cents"] = exercise_price_cents
    grant = get_success_data(api_client.create_grant(payload, ADMIN))
    rows = [
        get_success_data(
            api_client.create_vesting_tranche(grant["id"], spec, ADMIN)
        )
        for spec in tranches
    ]
    return grant, rows


def _submit(grant_id):
    return get_success_data(api_client.submit_grant(grant_id, ADMIN))


def _approve_by_board(grant_id):
    return get_success_data(
        api_client.approve_grant(grant_id, {"approval_path": "BOARD"}, BOARD)
    )


def _issue(grant_id):
    return get_success_data(api_client.issue_grant(grant_id, ADMIN))


def _read_plan(plan_id):
    return get_success_data(api_client.get_equity_plan(plan_id, ADMIN))


def _read_grant(grant_id):
    return get_success_data(api_client.get_grant(grant_id, ADMIN))


def _read_tranche(tranche_id):
    return get_success_data(api_client.get_vesting_tranche(tranche_id, ADMIN))


def _reclassify(participant_id, insider_status):
    return get_success_data(
        api_client.set_insider_status(
            participant_id, {"insider_status": insider_status}, COMPLIANCE
        )
    )


def _executed_insider_trade(plan_name, employee_number, insider_status,
                            requested_shares, execution_instant):
    """Carry one insider through preclearance to an executed trade, which is what
    mints the Section 16 report. Returns (participant, request, report)."""
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan(name=plan_name)
    participant = _enrol_participant(
        employee_number, home_state_code="NY", hire_date="2019-01-07",
        birth_date="1979-01-07",
    )
    _reclassify(participant["id"], insider_status)
    window = _open_window(
        plan["id"], "FY2026-Q1", "2026-01-05T00:00:00Z", "2026-03-31T00:00:00Z"
    )
    participant_headers = make_participant_headers(participant["id"])
    request = get_success_data(
        api_client.create_preclearance_request(
            {
                "participant_id": participant["id"],
                "window_id": window["id"],
                "transaction_type": "SELL",
                "requested_shares": requested_shares,
                "intended_trade_date": "2026-01-09",
            },
            participant_headers,
        )
    )
    request = get_success_data(
        api_client.decide_preclearance_request(
            request["id"], {"decision": "APPROVE"}, COMPLIANCE
        )
    )
    _set_clock(execution_instant)
    request = get_success_data(
        api_client.execute_preclearance_request(
            request["id"],
            {"executed_shares": requested_shares, "price_per_share_cents": 3000},
            participant_headers,
        )
    )
    reports, _meta = validate_paginated(
        api_client.list_participant_transaction_reports(
            participant["id"], COMPLIANCE
        )
    )
    assert len(reports) == 1, (
        f"an executed insider trade mints exactly one report, got {len(reports)}"
    )
    return participant, request, reports[0]


# ---------------------------------------------------------------------------
# The fungible share ratio and what a grant costs the reserve
# ---------------------------------------------------------------------------
def test_fungible_ratio_charges_full_value_awards_only_not_option_awards():
    """PRD §3.4: "Second, that committed count is weighted by instrument family: for the full-value types `RSU` and `PSU`, the count is multiplied by the plan's `fungible_ratio_full_value_bps` and divided by 10000, then rounded half up to whole shares; for the option types `ISO` and `NSO`, the count is charged one share for one share with no weighting at all."

    Design: Corner/calculations/fungible_weighting_applies_to_full_value_awards_only
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan(
        name="Corner Plan Uniform", fungible_ratio_full_value_bps=15000
    )
    participant = _enrol_participant("E-C-160", full_name="Fay Fungible")

    tranche_spec = [{
        "tranche_index": 1,
        "vest_type": "TIME",
        "scheduled_vest_date": "2027-01-05",
        "target_shares": 1000,
    }]
    rsu_grant, _rsu_tranches = _draft_with_tranches(
        plan["id"], participant["id"], "RSU", 1000, tranche_spec
    )
    nso_grant, _nso_tranches = _draft_with_tranches(
        plan["id"], participant["id"], "NSO", 1000, tranche_spec,
        exercise_price_cents=2500,
    )
    _submit(rsu_grant["id"])
    _submit(nso_grant["id"])

    rsu_response = api_client.approve_grant(
        rsu_grant["id"], {"approval_path": "BOARD"}, BOARD
    )
    rsu_approved = validate_success(rsu_response)
    nso_response = api_client.approve_grant(
        nso_grant["id"], {"approval_path": "BOARD"}, BOARD
    )
    nso_approved = validate_success(nso_response)

    assert_grant(rsu_approved)
    assert_grant(nso_approved)
    assert rsu_approved["weighted_reserve_shares"] == 1500, (
        "1000 RSU shares at a 15000 bps fungible ratio cost 1500 weighted shares, "
        f"got {rsu_approved['weighted_reserve_shares']}"
    )
    assert nso_approved["weighted_reserve_shares"] == 1000, (
        "an NSO award is charged one share per share with no weighting, got "
        f"{nso_approved['weighted_reserve_shares']}"
    )

    refreshed = _read_plan(plan["id"])
    assert_equity_plan(refreshed)
    assert refreshed["shares_committed_cumulative"] == 2500, (
        "the plan commits 1500 weighted RSU shares plus 1000 NSO shares, got "
        f"{refreshed['shares_committed_cumulative']}"
    )
    assert refreshed["available_reserve_shares"] == 997500, (
        f"available_reserve_shares expected 997500, got {refreshed['available_reserve_shares']}"
    )
    assert refreshed["fiscal_year_gross_granted_shares"] == 2500, (
        "the fiscal-year accumulator advances by the weighted figure, got "
        f"{refreshed['fiscal_year_gross_granted_shares']}"
    )
    assert refreshed["gross_burn_rate_bps"] == 25, (
        f"gross_burn_rate_bps expected 25, got {refreshed['gross_burn_rate_bps']}"
    )
    assert refreshed["net_burn_rate_bps"] == 25, (
        f"net_burn_rate_bps expected 25, got {refreshed['net_burn_rate_bps']}"
    )
    assert_reserve_conservation(refreshed)


# ---------------------------------------------------------------------------
# Retirement eligibility and the 365-day acceleration window
# ---------------------------------------------------------------------------
def test_retirement_acceleration_at_the_rule_of_65_and_the_365_day_edge():
    """PRD §3.3: "From those two integers, `retirement_eligible` is true when `age_years` is at least 55 **and** the sum of `age_years` and `service_years` is at least 65."

    PRD §3.8: "Otherwise, if the reason is `RETIREMENT`, the participant is retirement eligible, and the tranche's `scheduled_vest_date` falls at or before the termination date advanced by 365 days, the tranche moves to `VESTED` with `acceleration_reason` set to `RETIREMENT_ELIGIBILITY`; the window comparison is inclusive, so a tranche scheduled exactly 365 days out accelerates while one scheduled on day 366 forfeits."

    PRD §3.8: "It also writes `ptep_expiry_date`, the date on which the post-termination exercise period ends: the `termination_date` advanced by 0 days for `FOR_CAUSE`, 90 days for `VOLUNTARY`, 180 days for `INVOLUNTARY`, 1095 days for `RETIREMENT`, and 365 days for `DEATH`."

    Design: Corner/calculations/retirement_eligibility_rule_of_65_boundary
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan(name="Corner Plan Victor")
    participant = _enrol_participant(
        "E-C-170", full_name="Ray Tire", hire_date="2016-03-01",
        birth_date="1971-03-01",
    )
    _open_window(
        plan["id"], "FY2026-H1", "2026-01-05T00:00:00Z", "2026-06-30T00:00:00Z"
    )

    grant, tranches = _draft_with_tranches(
        plan["id"], participant["id"], "RSU", 2000,
        [
            {
                "tranche_index": 1,
                "vest_type": "TIME",
                "scheduled_vest_date": "2027-03-01",
                "target_shares": 1000,
            },
            {
                "tranche_index": 2,
                "vest_type": "TIME",
                "scheduled_vest_date": "2027-03-02",
                "target_shares": 1000,
            },
        ],
    )
    _submit(grant["id"])
    _approve_by_board(grant["id"])
    _issue(grant["id"])
    _set_clock("2026-03-01T10:00:00Z")

    response = api_client.terminate_participant(
        participant["id"],
        {
            "termination_date": "2026-03-01",
            "termination_reason": "RETIREMENT",
            "acceleration_fmv_per_share_cents": 4000,
        },
        ADMIN,
    )
    terminated = validate_success(response)

    assert terminated["age_years"] == 55, (
        f"age_years expected 55 at the termination date, got {terminated['age_years']}"
    )
    assert terminated["service_years"] == 10, (
        f"service_years expected 10, got {terminated['service_years']}"
    )
    assert terminated["retirement_eligible"] is True, (
        "55 years of age with 65 combined points sits exactly on both constants"
    )
    assert terminated["ptep_expiry_date"] == "2029-02-28", (
        "a RETIREMENT termination advances the exercise period by 1095 days, got "
        f"{terminated['ptep_expiry_date']}"
    )

    accelerated = _read_tranche(tranches[0]["id"])
    forfeited = _read_tranche(tranches[1]["id"])
    assert_vesting_tranche(accelerated)
    assert_vesting_tranche(forfeited)
    assert accelerated["status"] == "VESTED", (
        "a tranche scheduled exactly 365 days out accelerates, got "
        f"{accelerated['status']}"
    )
    assert accelerated["acceleration_reason"] == "RETIREMENT_ELIGIBILITY", (
        f"acceleration_reason expected RETIREMENT_ELIGIBILITY, got {accelerated['acceleration_reason']}"
    )
    assert forfeited["status"] == "FORFEITED", (
        f"a tranche scheduled on day 366 forfeits, got {forfeited['status']}"
    )
    assert forfeited["acceleration_reason"] is None, (
        f"a forfeited tranche carries no acceleration_reason, got {forfeited['acceleration_reason']}"
    )

    events, _meta = validate_paginated(
        api_client.list_vesting_events(ADMIN, params={"tranche_id": tranches[0]["id"]})
    )
    assert len(events) == 1, (
        f"the accelerated tranche gets exactly one settlement, got {len(events)}"
    )
    event = events[0]
    assert_vesting_event(event)
    assert event["gross_shares"] == 1000, (
        f"gross_shares snapshots the tranche's shares, got {event['gross_shares']}"
    )
    assert event["fmv_per_share_cents"] == 4000, (
        "the acceleration price comes from the termination request, got "
        f"{event['fmv_per_share_cents']}"
    )
    assert event["taxable_income_cents"] == 4000000, (
        f"taxable_income_cents expected 4000000, got {event['taxable_income_cents']}"
    )
    assert event["tax_status"] == "PENDING_ALLOCATION", (
        f"tax_status expected PENDING_ALLOCATION, got {event['tax_status']}"
    )
    assert event["settlement_status"] == "PENDING_TAX", (
        f"settlement_status expected PENDING_TAX, got {event['settlement_status']}"
    )

    resolved_grant = _read_grant(grant["id"])
    assert resolved_grant["status"] == "PARTIALLY_FORFEITED", (
        f"one surviving tranche leaves the grant PARTIALLY_FORFEITED, got {resolved_grant['status']}"
    )
    assert resolved_grant["weighted_reserve_shares"] == 1000, (
        "the forfeited tranche no longer contributes to the reserve charge, got "
        f"{resolved_grant['weighted_reserve_shares']}"
    )

    refreshed = _read_plan(plan["id"])
    assert refreshed["shares_committed_cumulative"] == 2000, (
        f"commitments are monotonic, got {refreshed['shares_committed_cumulative']}"
    )
    assert refreshed["shares_returned_cumulative"] == 1000, (
        f"the weight decrease is credited back, got {refreshed['shares_returned_cumulative']}"
    )
    assert refreshed["available_reserve_shares"] == 999000, (
        f"available_reserve_shares expected 999000, got {refreshed['available_reserve_shares']}"
    )
    assert refreshed["gross_burn_rate_bps"] == 20, (
        f"the gross variant is never unwound, got {refreshed['gross_burn_rate_bps']}"
    )
    assert refreshed["net_burn_rate_bps"] == 10, (
        f"the net variant falls as shares come back, got {refreshed['net_burn_rate_bps']}"
    )
    assert_reserve_conservation(refreshed)


# ---------------------------------------------------------------------------
# The reserve posture threshold is an exact integer cross-multiplication
# ---------------------------------------------------------------------------
def test_reserve_posture_is_open_exactly_on_the_threshold_and_flips_one_share_below():
    """PRD §3.1: "From the same three integers the system derives `reserve_posture`, which is `OPEN` when the available reserve multiplied by 10000 is greater than or equal to `low_reserve_threshold_bps` multiplied by `total_authorized_shares`, and `RESTRICTED` otherwise. That comparison is an exact integer cross-multiplication, so a reserve sitting precisely on the threshold is `OPEN`."

    PRD §3.1: "The adjustment adds `delta_shares` to `total_authorized_shares`, reruns the reserve ledger so that `available_reserve_shares` and `reserve_posture` are rewritten, and increments the plan's `version` by 1."

    PRD §3.1: "A conservation identity must hold after every request and after every individual cascade hop: the available reserve, plus cumulative commitments, minus cumulative returns, always equals the authorised total."

    Design: Corner/calculations/share_reserve_posture_exactly_at_threshold_is_open
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan(
        name="Corner Plan Whiskey",
        common_shares_outstanding=10_000_000,
        low_reserve_threshold_bps=5000,
    )
    participant = _enrol_participant(
        "E-C-180", full_name="Thea Thresh", birth_date="1984-02-02"
    )
    grant, _rows = _draft_with_tranches(
        plan["id"], participant["id"], "NSO", 500000,
        [{
            "tranche_index": 1,
            "vest_type": "TIME",
            "scheduled_vest_date": "2027-01-05",
            "target_shares": 500000,
        }],
        exercise_price_cents=2500,
    )
    _submit(grant["id"])
    _approve_by_board(grant["id"])

    on_threshold = _read_plan(plan["id"])
    assert_equity_plan(on_threshold)
    assert on_threshold["available_reserve_shares"] == 500000, (
        "committing 500000 shares of a 1000000-share pool leaves exactly 500000 "
        f"available, got {on_threshold['available_reserve_shares']}"
    )
    assert on_threshold["reserve_posture"] == "OPEN", (
        "500000 * 10000 == 5000 * 1000000, so the posture sits precisely on the "
        f"threshold and stays OPEN, got {on_threshold['reserve_posture']}"
    )
    assert_reserve_posture(on_threshold)
    assert on_threshold["gross_burn_rate_bps"] == 500, (
        f"gross_burn_rate_bps expected 500, got {on_threshold['gross_burn_rate_bps']}"
    )
    assert on_threshold["version"] == 2, (
        f"the approval bumped the plan to version 2, got {on_threshold['version']}"
    )

    response = api_client.adjust_share_reserve(
        plan["id"],
        {
            "delta_shares": -1,
            "expected_plan_version": on_threshold["version"],
            "adjustment_reason": "share retirement of one share",
        },
        ADMIN,
    )
    adjusted = validate_success(response)

    assert_equity_plan(adjusted)
    assert adjusted["total_authorized_shares"] == 999999, (
        f"total_authorized_shares expected 999999, got {adjusted['total_authorized_shares']}"
    )
    assert adjusted["available_reserve_shares"] == 499999, (
        f"available_reserve_shares expected 499999, got {adjusted['available_reserve_shares']}"
    )
    assert adjusted["reserve_posture"] == "RESTRICTED", (
        "499999 * 10000 is strictly below 5000 * 999999, so the posture flips, got "
        f"{adjusted['reserve_posture']}"
    )
    assert_reserve_posture(adjusted)
    assert adjusted["shares_committed_cumulative"] == 500000, (
        "the accumulator is monotonic and untouched by a pool adjustment, got "
        f"{adjusted['shares_committed_cumulative']}"
    )
    assert adjusted["version"] == 3, (
        f"the adjustment increments the version by 1, got {adjusted['version']}"
    )
    assert (
        adjusted["available_reserve_shares"]
        + adjusted["shares_committed_cumulative"]
        - adjusted["shares_returned_cumulative"]
    ) == 999999, "499999 + 500000 - 0 must equal the authorised total 999999"
    assert_reserve_conservation(adjusted)

    persisted = _read_plan(plan["id"])
    assert persisted["reserve_posture"] == "RESTRICTED", (
        f"the flipped posture is persisted, got {persisted['reserve_posture']}"
    )
    assert persisted["total_authorized_shares"] == 999999, (
        f"the reduced pool is persisted, got {persisted['total_authorized_shares']}"
    )


# ---------------------------------------------------------------------------
# The Section 16 filing deadline
# ---------------------------------------------------------------------------
def test_report_due_at_steps_over_the_weekend_and_filing_on_the_dot_is_timely():
    """PRD §3.10: "`due_at` is the end of the second business day after `transaction_at`. Take the calendar date of `transaction_at`; if that date is itself a Saturday or Sunday, begin from the next business day; then advance forward two business days, counting Monday through Friday only with no holiday calendar; `due_at` is that resulting date at `23:59:59.999Z`. A Wednesday transaction is therefore due at the end of Friday, and a Thursday transaction is due at the end of the following Monday."

    PRD §3.10: "A preclearance execution creates a report with `source_type` `PRECLEARANCE_EXECUTION` and `source_id` equal to the request's id, `transaction_at` equal to `executed_at`, and `shares` equal to `executed_shares`."

    PRD §3.10: "Filing stamps `filed_at` from the logical clock and then branches on a single millisecond-precision comparison from the same trigger: at or before `due_at` the report becomes `FILED`, and strictly after `due_at` it becomes `LATE_FILED`."

    Design: Corner/calculations/insider_report_due_at_skips_the_weekend
    """
    _participant, request, report = _executed_insider_trade(
        "Corner Plan Xray", "E-C-190", "SECTION_16_OFFICER", 500,
        "2026-01-08T14:00:00Z",
    )

    assert_transaction_report(report)
    assert report["source_type"] == "PRECLEARANCE_EXECUTION", (
        f"source_type expected PRECLEARANCE_EXECUTION, got {report['source_type']}"
    )
    assert report["source_id"] == request["id"], (
        f"source_id must name the executed request, got {report['source_id']}"
    )
    assert report["shares"] == 500, (
        f"shares must equal executed_shares, got {report['shares']}"
    )
    assert report["form_type"] == "FORM_4", (
        f"a SECTION_16_OFFICER files FORM_4, got {report['form_type']}"
    )
    assert report["status"] == "PENDING", (
        f"a freshly minted report is PENDING, got {report['status']}"
    )
    assert report["filed_at"] is None, (
        f"filed_at is null until the report is filed, got {report['filed_at']}"
    )
    assert_instant_equals(
        report["transaction_at"], "2026-01-08T14:00:00.000Z", "transaction_at"
    )
    assert_instant_equals(
        report["due_at"], "2026-01-12T23:59:59.999Z", "due_at"
    )
    assert_three_fractional_digits(report["due_at"], "due_at")

    _set_clock("2026-01-12T23:59:59.999Z")
    filed = validate_success(api_client.file_transaction_report(report["id"], COMPLIANCE))

    assert_transaction_report(filed)
    assert filed["status"] == "FILED", (
        "filing at exactly the deadline millisecond is timely, got "
        f"{filed['status']}"
    )
    assert_instant_equals(filed["filed_at"], "2026-01-12T23:59:59.999Z", "filed_at")
    assert_instant_equals(filed["filed_at"], filed["due_at"], "filed_at vs due_at")
    assert filed["version"] == report["version"] + 1, (
        f"filing advances the version by 1, got {filed['version']}"
    )

    persisted = validate_success(
        api_client.get_transaction_report(report["id"], COMPLIANCE)
    )
    assert persisted["status"] == "FILED", (
        f"the FILED status is persisted, got {persisted['status']}"
    )


def test_report_filed_one_millisecond_after_due_at_is_late_filed():
    """PRD §3.10: "Filing stamps `filed_at` from the logical clock and then branches on a single millisecond-precision comparison from the same trigger: at or before `due_at` the report becomes `FILED`, and strictly after `due_at` it becomes `LATE_FILED`. Filing at exactly `23:59:59.999Z` on the due date is timely; one millisecond later is late. Nothing rejects a late filing — lateness is recorded, not prevented, because the regulatory record must show it."

    PRD §3.10: "In both cases `form_type` is `FORM_4` for a `SECTION_16_OFFICER` and `FORM_5` for a `DESIGNATED_INSIDER`, `status` is `PENDING`, `filed_at` is null, and `participant_id` names the reporting insider."

    Design: Corner/calculations/insider_report_filed_one_millisecond_late_is_late_filed
    """
    participant, _request, report = _executed_insider_trade(
        "Corner Plan Yankee", "E-C-200", "DESIGNATED_INSIDER", 400,
        "2026-01-08T14:00:00Z",
    )

    assert_transaction_report(report)
    assert report["form_type"] == "FORM_5", (
        f"a DESIGNATED_INSIDER files FORM_5, got {report['form_type']}"
    )
    assert report["participant_id"] == participant["id"], (
        f"participant_id names the reporting insider, got {report['participant_id']}"
    )
    assert report["shares"] == 400, (
        f"shares must equal executed_shares, got {report['shares']}"
    )
    assert_instant_equals(report["due_at"], "2026-01-12T23:59:59.999Z", "due_at")

    _set_clock("2026-01-13T00:00:00Z")
    filed = validate_success(api_client.file_transaction_report(report["id"], COMPLIANCE))

    assert_transaction_report(filed)
    assert filed["status"] == "LATE_FILED", (
        "one millisecond past the deadline is late, got " f"{filed['status']}"
    )
    assert_instant_equals(filed["filed_at"], "2026-01-13T00:00:00.000Z", "filed_at")
    assert filed["version"] == report["version"] + 1, (
        f"filing advances the version by 1, got {filed['version']}"
    )

    persisted = validate_success(
        api_client.get_transaction_report(report["id"], COMPLIANCE)
    )
    assert persisted["status"] == "LATE_FILED", (
        f"the LATE_FILED status is persisted, got {persisted['status']}"
    )
    assert_instant_equals(
        persisted["due_at"], "2026-01-12T23:59:59.999Z", "persisted due_at"
    )


# ---------------------------------------------------------------------------
# Closing the fiscal year
# ---------------------------------------------------------------------------
def test_evergreen_topup_is_capped_and_the_rollover_expires_the_stale_delegation():
    """PRD §3.1: "The rollover first computes the evergreen top-up: the `common_shares_outstanding` multiplied by `evergreen_pct_bps`, divided by 10000 and rounded half up to whole shares, and then the smaller of that figure and `evergreen_cap_shares` is taken. Rounding happens before the cap is applied. When the cap is the binding term the top-up equals the cap exactly, and when the cap happens to equal the uncapped amount the top-up equals that amount — the comparison is a genuine minimum with no off-by-one. The resulting top-up is added to `total_authorized_shares` and recorded in `evergreen_topup_last_shares`. The rollover then overwrites `current_fiscal_year_label` with the supplied label, advances `fiscal_year_start_date` by exactly one calendar year from its prior value, and zeroes all four fiscal-year figures — `fiscal_year_gross_granted_shares`, `fiscal_year_returned_shares`, `gross_burn_rate_bps`, and `net_burn_rate_bps`. The reserve ledger is then rerun so that `available_reserve_shares` and `reserve_posture` reflect the larger pool. Finally, every delegation of the plan that is still `ACTIVE` and whose `effective_to` falls before the new fiscal-year start date moves to `EXPIRED`. Grants are untouched by a rollover; only the plan row and its delegations change."

    Design: Corner/calculations/evergreen_topup_capped_at_evergreen_cap_shares
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan(
        name="Corner Plan Zulu",
        total_authorized_shares=10_000_000,
        common_shares_outstanding=200_000_000,
        current_fiscal_year_label="FY2026",
        evergreen_pct_bps=100,
        evergreen_cap_shares=500_000,
    )
    authority_base = {
        "plan_id": plan["id"],
        "authority_type": "DELEGATED_OFFICER",
        "delegate_user_id": "officer-1",
        "per_grant_share_cap": 100000,
        "aggregate_share_cap": 100000,
        "effective_from": "2026-01-01",
    }
    stale = get_success_data(
        api_client.create_approval_authority(
            dict(authority_base, effective_to="2026-12-31"), BOARD
        )
    )
    surviving = get_success_data(
        api_client.create_approval_authority(
            dict(authority_base, effective_to="2027-12-31"), BOARD
        )
    )
    participant = _enrol_participant(
        "E-C-210", full_name="Evan Green", birth_date="1983-03-03"
    )
    grant, _rows = _draft_with_tranches(
        plan["id"], participant["id"], "NSO", 40000,
        [{
            "tranche_index": 1,
            "vest_type": "TIME",
            "scheduled_vest_date": "2027-01-05",
            "target_shares": 40000,
        }],
        exercise_price_cents=2500,
    )
    _submit(grant["id"])
    _approve_by_board(grant["id"])

    before = _read_plan(plan["id"])
    assert before["fiscal_year_gross_granted_shares"] == 40000, (
        "the approval charged 40000 option shares one for one, got "
        f"{before['fiscal_year_gross_granted_shares']}"
    )
    assert before["gross_burn_rate_bps"] == 2, (
        f"gross_burn_rate_bps expected 2, got {before['gross_burn_rate_bps']}"
    )
    assert before["available_reserve_shares"] == 9960000, (
        f"available_reserve_shares expected 9960000, got {before['available_reserve_shares']}"
    )

    _set_clock("2027-01-02T09:00:00Z")
    rolled = validate_success(
        api_client.run_annual_rollover(
            plan["id"], {"fiscal_year_label": "FY2027"}, ADMIN
        )
    )

    assert_equity_plan(rolled)
    assert rolled["evergreen_topup_last_shares"] == 500000, (
        "the uncapped 2000000-share amount is capped at evergreen_cap_shares, got "
        f"{rolled['evergreen_topup_last_shares']}"
    )
    assert rolled["total_authorized_shares"] == 10500000, (
        f"total_authorized_shares expected 10500000, got {rolled['total_authorized_shares']}"
    )
    assert rolled["available_reserve_shares"] == 10460000, (
        f"available_reserve_shares expected 10460000, got {rolled['available_reserve_shares']}"
    )
    assert rolled["shares_committed_cumulative"] == 40000, (
        "the rollover leaves the cumulative commitment untouched, got "
        f"{rolled['shares_committed_cumulative']}"
    )
    assert rolled["fiscal_year_gross_granted_shares"] == 0, (
        f"fiscal_year_gross_granted_shares must be zeroed, got {rolled['fiscal_year_gross_granted_shares']}"
    )
    assert rolled["fiscal_year_returned_shares"] == 0, (
        f"fiscal_year_returned_shares must be zeroed, got {rolled['fiscal_year_returned_shares']}"
    )
    assert rolled["gross_burn_rate_bps"] == 0, (
        f"gross_burn_rate_bps must be zeroed, got {rolled['gross_burn_rate_bps']}"
    )
    assert rolled["net_burn_rate_bps"] == 0, (
        f"net_burn_rate_bps must be zeroed, got {rolled['net_burn_rate_bps']}"
    )
    assert rolled["fiscal_year_start_date"] == "2027-01-01", (
        "the fiscal-year start advances exactly one calendar year, got "
        f"{rolled['fiscal_year_start_date']}"
    )
    assert rolled["current_fiscal_year_label"] == "FY2027", (
        f"current_fiscal_year_label expected FY2027, got {rolled['current_fiscal_year_label']}"
    )
    assert_reserve_conservation(rolled)

    expired = get_success_data(
        api_client.get_approval_authority(stale["id"], BOARD)
    )
    kept = get_success_data(
        api_client.get_approval_authority(surviving["id"], BOARD)
    )
    assert expired["status"] == "EXPIRED", (
        "a delegation whose effective_to precedes 2027-01-01 expires, got "
        f"{expired['status']}"
    )
    assert kept["status"] == "ACTIVE", (
        "a delegation running to 2027-12-31 survives the rollover, got "
        f"{kept['status']}"
    )
    assert kept["remaining_shares"] == 100000, (
        f"the surviving delegation is unconsumed, got {kept['remaining_shares']}"
    )

    untouched_grant = _read_grant(grant["id"])
    assert untouched_grant["status"] == "APPROVED", (
        f"grants are untouched by a rollover, got {untouched_grant['status']}"
    )


# ---------------------------------------------------------------------------
# A clearance never outlives its window
# ---------------------------------------------------------------------------
def test_preclearance_valid_until_is_capped_by_the_window_close_at():
    """PRD §3.9: "On approval, `valid_until` is the earlier of the `decided_at` instant advanced by 5 days and the window's own `close_at` — a clearance is good for five days or until the window closes, whichever comes first. The arithmetic is exact instant arithmetic."

    PRD §3.9: "On success the request becomes `APPROVED`, `decided_by_user_id`, `decided_at`, and `decision_note` are stored, `valid_until` is computed as described below, the window's `approved_shares_cumulative` is increased by `requested_shares`, and both the request's `version` and the window's `version` advance by 1."

    Design: Corner/calculations/preclearance_validity_capped_by_window_close_at
    """
    _set_clock("2026-03-28T10:00:00Z")
    plan = _register_plan(name="Corner Plan Alfa Two")
    participant = _enrol_participant(
        "E-C-220", full_name="Cara Cap", home_state_code="NY",
        hire_date="2019-01-07", birth_date="1981-04-04",
    )
    _reclassify(participant["id"], "DESIGNATED_INSIDER")
    window = _open_window(
        plan["id"], "FY2026-Q1", "2026-01-05T00:00:00Z", "2026-03-31T00:00:00Z"
    )
    assert window["aggregate_share_cap"] is None, (
        "this window carries no aggregate cap, got "
        f"{window['aggregate_share_cap']}"
    )
    request = get_success_data(
        api_client.create_preclearance_request(
            {
                "participant_id": participant["id"],
                "window_id": window["id"],
                "transaction_type": "SELL",
                "requested_shares": 250,
                "intended_trade_date": "2026-03-30",
            },
            make_participant_headers(participant["id"]),
        )
    )

    decided = validate_success(
        api_client.decide_preclearance_request(
            request["id"],
            {"decision": "APPROVE", "decision_note": "cleared to the window edge"},
            COMPLIANCE,
        )
    )

    assert decided["status"] == "APPROVED", (
        f"the clearance is approved, got {decided['status']}"
    )
    assert_instant_equals(
        decided["decided_at"], "2026-03-28T10:00:00.000Z", "decided_at"
    )
    assert decided["decided_by_user_id"] == "compliance-1", (
        f"decided_by_user_id expected compliance-1, got {decided['decided_by_user_id']}"
    )
    assert_instant_equals(
        decided["valid_until"], "2026-03-31T00:00:00.000Z", "valid_until"
    )
    assert canonical_instant(decided["valid_until"]) != canonical_instant(
        "2026-04-02T10:00:00.000Z"
    ), "the additive five-day term must lose to the window close_at"

    refreshed_window = get_success_data(
        api_client.get_trading_window(window["id"], COMPLIANCE)
    )
    assert refreshed_window["approved_shares_cumulative"] == 250, (
        "the approval reserves the requested shares against the window, got "
        f"{refreshed_window['approved_shares_cumulative']}"
    )
    assert refreshed_window["version"] == window["version"] + 1, (
        f"the window version advances by 1, got {refreshed_window['version']}"
    )
