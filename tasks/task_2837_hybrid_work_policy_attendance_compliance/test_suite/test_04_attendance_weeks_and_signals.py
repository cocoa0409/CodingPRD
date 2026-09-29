"""Opening attendance weeks, appending presence evidence and crediting office days."""
from test_helpers import (
    ApiErrorId,
    add_full_day_signals,
    add_signal,
    amend,
    api_client,
    assert_attendance_week,
    assert_compliance_signal,
    canonical_instant,
    cases_for,
    create_team,
    finalize,
    first_case_for,
    open_week,
    pin_clock,
    read_case,
    read_cycle,
    read_employee,
    read_team,
    read_week,
    register_employee,
    setup_cycle_team_employee,
    setup_open_week,
    signal_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, HRBP, MANAGER, SYSTEM


def _two_standards_scenario():
    """One cycle carrying a union team and a corroborating team, one employee each.

    Both employees are left unclassified, so each carries the `ONSITE_REQUIRED`
    policy default and each week demands five days. Both weeks receive the same
    five signals: badge and network on 2026-09-08, badge only on 2026-09-09,
    network only on 2026-09-10 and a short badge on 2026-09-11.
    """
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-H1", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T1-CORE",
            "expected_days_in_office_per_week": 5,
            "core_collaboration_days": ["MON", "TUE", "WED", "THU", "FRI"],
            "headcount_planned": 25,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-1001"},
    )
    corroborating_team = create_team(
        base["cycle"]["id"],
        team_code="T2-FIELD",
        expected_days_in_office_per_week=3,
        core_collaboration_days=["TUE", "WED", "THU"],
        headcount_planned=12,
        signal_corroboration_required=True,
    )
    corroborated_employee = register_employee(
        corroborating_team["id"], employee_number="E-2001",
        demographic_band="BAND_B",
    )
    weeks = {}
    for key, employee_id, site in (
        ("union", base["employee"]["id"], "NYC-01"),
        ("corroborated", corroborated_employee["id"], "CHI-02"),
    ):
        week = open_week(employee_id, "2026-W37")
        for source, observed, minutes in (
            ("BADGE", "2026-09-08", 480),
            ("NETWORK", "2026-09-08", 300),
            ("BADGE", "2026-09-09", 480),
            ("NETWORK", "2026-09-10", 480),
            ("BADGE", "2026-09-11", 120),
        ):
            validate_success(
                api_client.append_signal(
                    week["id"],
                    signal_payload(
                        observed, source, site_code=site, minutes_present=minutes,
                        dedupe_key=f"{source[0]}-{observed[5:].replace('-', '')}",
                    ),
                    SYSTEM,
                ),
                201,
            )
        weeks[key] = week
    return {
        "cycle": base["cycle"],
        "union_team": base["team"],
        "corroborating_team": corroborating_team,
        "union_employee": base["employee"],
        "corroborated_employee": corroborated_employee,
        "union_week": weeks["union"],
        "corroborated_week": weeks["corroborated"],
    }


def _amendment_loop_scenario():
    """An unclassified employee on a five-day team with two credited badge days."""
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-CYC", "days_in_office_floor": 2},
        team_overrides={
            "team_code": "T1-CORE",
            "expected_days_in_office_per_week": 5,
            "core_collaboration_days": ["MON", "TUE", "WED", "THU", "FRI"],
            "headcount_planned": 25,
            "signal_corroboration_required": False,
        },
        employee_overrides={"employee_number": "E-1001"},
    )
    base["week"] = open_week(base["employee"]["id"], "2026-W37")
    add_full_day_signals(base["week"]["id"], ["2026-09-08", "2026-09-09"])
    return base


def test_01_appended_evidence_is_immutable_and_carries_neither_version_nor_updated_at():
    """A compliance signal is the one resource that opts out of the common audit fields.

    PRD 2.4: "A compliance signal is an immutable observation: once appended it is
    never edited, so it carries only `id` and `created_at`."
    PRD 2.4: "It has no `updated_at` and no `version` field at all, and neither
    field appears in its response payload."
    PRD 3.4: "Appending a signal moves no derived field whatsoever: signals are
    pure evidence, and nothing is credited until the week is settled."

    Design: Corner/entities/compliance_signal_is_immutable_with_no_version_and_no_update_path
    """
    scenario = setup_open_week(
        cycle_overrides={"cycle_label": "FY27-EVIDENCE"},
        employee_overrides={"employee_number": "E-1001"},
    )
    week = scenario["week"]

    created = validate_success(
        api_client.append_signal(
            week["id"],
            signal_payload(
                "2026-09-08", "BADGE", site_code="NYC-01", minutes_present=480,
                dedupe_key="B-0908",
            ),
            SYSTEM,
        ),
        201,
    )
    assert_compliance_signal(created)
    assert created["attendance_week_id"] == week["id"]
    assert created["signal_source"] == "BADGE"
    assert created["site_code"] == "NYC-01"
    assert created["observed_date"] == "2026-09-08"
    assert created["minutes_present"] == 480
    assert created["dedupe_key"] == "B-0908"
    assert "version" not in created
    assert "updated_at" not in created
    assert canonical_instant(created["created_at"]) == "2026-09-01T09:00:00Z", (
        "the record time is the logical clock even though the evidence time is "
        "2026-09-08"
    )

    fetched = validate_success(api_client.get_compliance_signal(created["id"], AUDITOR))
    assert fetched == created, (
        "reading the signal back returns the same body it was created with"
    )

    rows, meta = validate_paginated(
        api_client.list_compliance_signals(
            AUDITOR, {"attendance_week_id": week["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == created["id"]
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]

    after_append = read_week(week["id"])
    assert after_append["status"] == "OPEN"
    assert after_append["credited_days"] == 0
    assert after_append["required_days"] == 0
    assert after_append["shortfall_days"] == 0
    assert after_append["relief_days_credited"] == 0
    assert after_append["variant_applied"] is None
    assert after_append["finalized_at"] is None
    assert read_employee(scenario["employee"]["id"])["non_compliance_pressure"] == 0.00


def test_02_the_week_listing_filters_before_it_paginates():
    """Three weeks for one employee page two at a time; a peer's week never appears.

    PRD 2.3: "Every list endpoint accepts two optional query parameters."
    PRD 2.3: "`limit` defaults to 10, must be at least 1 and at most 100; `offset`
    defaults to 0 and must be at least 0."
    PRD 2.3: "A value outside either range is a request-shape violation and is
    refused with `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters
    before the window is applied and `has_more` is true exactly when rows remain
    after the returned window."

    Design: Corner/entities/attendance_week_listing_paginates_with_total_count_and_has_more
    """
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-PAGES", "days_in_office_floor": 2},
        team_overrides={"team_code": "T-A", "expected_days_in_office_per_week": 3,
                        "headcount_planned": 12},
        employee_overrides={"employee_number": "E-1001"},
    )
    employee = base["employee"]
    peer = register_employee(
        base["team"]["id"], employee_number="E-1002", demographic_band="BAND_B"
    )
    own = {
        iso_week: open_week(employee["id"], iso_week)["id"]
        for iso_week in ("2026-W37", "2026-W38", "2026-W39")
    }
    peer_week = open_week(peer["id"], "2026-W37")

    first_page, first_meta = validate_paginated(
        api_client.list_attendance_weeks(
            AUDITOR, {"employee_id": employee["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3, (
        "the employee filter is applied before the window, so the peer's week is "
        "not counted"
    )
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_attendance_weeks(
            AUDITOR, {"employee_id": employee["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False, "no rows remain after the second window"

    paged_ids = [row["id"] for row in first_page + second_page]
    assert sorted(paged_ids) == sorted(own.values()), (
        "the two windows together return exactly the filtered population"
    )
    assert peer_week["id"] not in paged_ids
    for row in first_page + second_page:
        assert row["employee_id"] == employee["id"]
        assert_attendance_week(row)

    filtered, filtered_meta = validate_paginated(
        api_client.list_attendance_weeks(
            AUDITOR, {"employee_id": employee["id"], "iso_week": "2026-W38"}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert filtered[0]["iso_week"] == "2026-W38"
    assert filtered[0]["id"] == own["2026-W38"]

    validate_error(
        api_client.list_attendance_weeks(
            AUDITOR, {"employee_id": employee["id"], "limit": 0}
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )


def test_03_settlement_is_refused_twice_while_amendment_demands_a_settled_week():
    """The editable set is {OPEN, AMENDED}, so each refusal names the state it wanted.

    PRD 3.4: "Signals may only be appended while the week is still editable — that
    is, while its `status` is `OPEN` or `AMENDED`; an append onto a `FINALIZED` or
    `LOCKED` week is refused with `ERR_WEEK_NOT_OPEN` (409)."
    PRD 3.5: "The week must be editable — `OPEN` or `AMENDED` — or the call is
    refused with `ERR_WEEK_NOT_OPEN` (409), which is also what a second settlement
    of an already-`FINALIZED` week receives."
    PRD 3.5: "Only an `HRBusinessPartner` may reopen a week, moving it `FINALIZED →
    AMENDED` with a supplied `amendment_reason`; a week in any other status is
    refused with `ERR_WEEK_NOT_FINALIZED` (409), and the parent cycle must again be
    `OPEN` or `RECALIBRATING`."

    Design: Corner/state_machines/attendance_week_finalize_is_not_idempotent_and_amend_demands_a_settled_week
    """
    scenario = setup_open_week(
        cycle_overrides={"cycle_label": "FY27-EDITSET"},
        employee_overrides={"employee_number": "E-1001"},
    )
    week = scenario["week"]
    employee_id = scenario["employee"]["id"]

    validate_error(
        api_client.amend_week(
            week["id"], {"amendment_reason": "premature correction attempt"}, HRBP
        ),
        ApiErrorId.ERR_WEEK_NOT_FINALIZED.value,
        409,
    )
    assert read_week(week["id"])["status"] == "OPEN", "the refused amend wrote nothing"

    add_signal(week["id"], "2026-09-08", "BADGE", minutes_present=480,
               dedupe_key="B-0908")
    settled = finalize(week["id"])
    assert settled["status"] == "FINALIZED"
    assert settled["required_days"] == 5
    assert settled["variant_applied"] == "SIGNAL_UNION"
    assert settled["credited_days"] == 1
    assert settled["shortfall_days"] == 4
    assert canonical_instant(settled["finalized_at"]) == "2026-09-01T09:00:00Z"
    assert read_employee(employee_id)["non_compliance_pressure"] == 7.00, (
        "four shortfall days at the onsite multiplier plus a one-week streak"
    )

    validate_error(
        api_client.finalize_week(week["id"], SYSTEM),
        ApiErrorId.ERR_WEEK_NOT_OPEN.value,
        409,
    )
    unchanged = read_week(week["id"])
    assert unchanged["credited_days"] == 1
    assert unchanged["shortfall_days"] == 4
    assert unchanged["version"] == settled["version"], (
        "settlement is not idempotent, and the refused replay moved nothing"
    )

    validate_error(
        api_client.append_signal(
            week["id"],
            signal_payload("2026-09-09", "BADGE", site_code="NYC-01",
                           minutes_present=480, dedupe_key="B-0909"),
            SYSTEM,
        ),
        ApiErrorId.ERR_WEEK_NOT_OPEN.value,
        409,
    )
    _, signal_meta = validate_paginated(
        api_client.list_compliance_signals(AUDITOR, {"attendance_week_id": week["id"]})
    )
    assert signal_meta["total_count"] == 1, "a settled week accepts no further evidence"

    amended = amend(week["id"], "badge controller missed Wednesday")
    assert amended["status"] == "AMENDED"
    assert read_employee(employee_id)["non_compliance_pressure"] == 0.00, (
        "the week left the settled set, so it stops contributing"
    )

    accepted = validate_success(
        api_client.append_signal(
            week["id"],
            signal_payload("2026-09-09", "BADGE", site_code="NYC-01",
                           minutes_present=480, dedupe_key="B-0909"),
            SYSTEM,
        ),
        201,
    )
    assert accepted["observed_date"] == "2026-09-09", (
        "an amended week is editable again, and the key refused a moment ago lands"
    )

    resettled = finalize(week["id"])
    assert resettled["status"] == "FINALIZED"
    assert resettled["credited_days"] == 2
    assert resettled["shortfall_days"] == 3
    assert read_employee(employee_id)["non_compliance_pressure"] == 5.50


def test_04_one_signal_set_credits_three_days_under_union_and_one_under_corroboration():
    """The evidence standard is chosen by the team, not by anything on the week.

    PRD 3.4: "Which of the two evidence standards applies is taken from the team's
    `signal_corroboration_required` flag at settlement time and recorded on the week
    as `variant_applied`."
    PRD 3.4: "Under the `SIGNAL_UNION` standard, used when the team does not require
    corroboration, a date counts when **any** of badge, network or attestation
    evidence is satisfied, so a badge-only day counts."
    PRD 3.4: "Under the `SIGNAL_CORROBORATED` standard, used when the team does
    require it, a date counts only when badge **and** network evidence are **both**
    satisfied on that date, or an attestation exists for it."
    PRD 3.4: "For the same signal set, the corroborated standard therefore yields
    strictly fewer credited days than the union standard whenever any date carries
    exactly one automated source."

    Design: Difficulty/dual_variant_calc/credited_days_union_versus_corroborated
    """
    scenario = _two_standards_scenario()

    union = finalize(scenario["union_week"]["id"])
    corroborated = finalize(scenario["corroborated_week"]["id"])
    assert_attendance_week(union)
    assert_attendance_week(corroborated)

    assert union["variant_applied"] == "SIGNAL_UNION"
    assert corroborated["variant_applied"] == "SIGNAL_CORROBORATED"

    assert union["credited_days"] == 3, (
        "2026-09-08, 2026-09-09 and 2026-09-10 each carry one qualifying automated "
        "source, and 2026-09-11 falls under the 240-minute floor"
    )
    assert corroborated["credited_days"] == 1, (
        "only 2026-09-08 carries both badge and network above the floor"
    )
    assert union["credited_days"] - corroborated["credited_days"] == 2, (
        "the two variants diverge by two days on byte-identical evidence"
    )

    assert union["required_days"] == 5
    assert corroborated["required_days"] == 5, (
        "both employees are ONSITE_REQUIRED, so neither week inherits its team's "
        "expected days"
    )
    assert union["shortfall_days"] == 2
    assert corroborated["shortfall_days"] == 4

    _, union_meta = validate_paginated(
        api_client.list_compliance_signals(
            AUDITOR, {"attendance_week_id": scenario["union_week"]["id"]}
        )
    )
    assert union_meta["total_count"] == 5, "no evidence was consumed or discarded"
    _, corroborated_meta = validate_paginated(
        api_client.list_compliance_signals(
            AUDITOR, {"attendance_week_id": scenario["corroborated_week"]["id"]}
        )
    )
    assert corroborated_meta["total_count"] == 5


def test_05_the_stricter_standard_pushes_the_same_evidence_two_rungs_higher():
    """The credited-day divergence carries all the way into the escalation stage.

    PRD 3.5: "Take the raw shortfall — the same sum as `cumulative_shortfall_days` —
    and multiply it by the severity multiplier for the employee's current
    eligibility class: 0.0 for `FULLY_REMOTE`, 1.0 for `HYBRID`, and 1.5 for
    `ONSITE_REQUIRED`."
    PRD 3.5: "To that product add the breach streak multiplied by a consecutive-week
    weight of 1.0."
    PRD 3.5: "Thereafter, every cascade that touches the employee's pressure sets
    the open case's `stage` from the pressure directly, provided `discretionary_hold`
    is false: a pressure of 10.00 or more yields `REFERRED`, 7.00 or more yields
    `PERFORMANCE_PLAN`, 4.00 or more yields `WRITTEN_WARNING`, 2.00 or more yields
    `COACHING`, and anything below 2.00 yields `CURED`."
    PRD 3.5: "`formal_action_count` is the number holding a case in the narrower
    formal-action band of `WRITTEN_WARNING`, `PERFORMANCE_PLAN` or `REFERRED`."

    Design: Difficulty/dual_variant_calc/credited_days_union_versus_corroborated
    """
    scenario = _two_standards_scenario()
    finalize(scenario["union_week"]["id"])
    finalize(scenario["corroborated_week"]["id"])

    union_employee = read_employee(scenario["union_employee"]["id"])
    assert union_employee["cumulative_shortfall_days"] == 2
    assert union_employee["consecutive_breach_weeks"] == 1
    assert union_employee["non_compliance_pressure"] == 4.00, (
        "two shortfall days at 1.5 plus one streak week"
    )
    assert union_employee["compliance_state"] == "BREACH"
    assert union_employee["escalation_stage"] == "WRITTEN_WARNING"

    corroborated_employee = read_employee(scenario["corroborated_employee"]["id"])
    assert corroborated_employee["cumulative_shortfall_days"] == 4
    assert corroborated_employee["consecutive_breach_weeks"] == 1
    assert corroborated_employee["non_compliance_pressure"] == 7.00, (
        "four shortfall days at 1.5 plus one streak week"
    )
    assert corroborated_employee["compliance_state"] == "BREACH"
    assert corroborated_employee["escalation_stage"] == "PERFORMANCE_PLAN", (
        "the same evidence read strictly lands two rungs higher"
    )

    assert first_case_for(union_employee["id"])["stage"] == "WRITTEN_WARNING"
    assert first_case_for(corroborated_employee["id"])["stage"] == "PERFORMANCE_PLAN"
    assert read_team(scenario["union_team"]["id"])["formal_action_count"] == 1
    assert read_team(scenario["corroborating_team"]["id"])["formal_action_count"] == 1
    assert read_cycle(scenario["cycle"]["id"])["formal_action_total"] == 2, (
        "the cycle total is the sum across the two teams"
    )


def test_06_an_attestation_credits_without_minutes_and_the_count_stops_at_five():
    """A zero-minute attestation counts, a 239-minute badge does not, and six dates credit five.

    PRD 3.4: "**Credited days** are counted date by date across the week's seven
    dates, against a minute floor of four hours — a badge or network observation
    must record at least 240 minutes present to count, while a manual attestation
    counts on the strength of its existence alone and its `minutes_present` is
    ignored entirely."
    PRD 3.4: "For a given date, badge evidence is satisfied when at least one signal
    on that date has source `BADGE` and at least 240 minutes present; network
    evidence is satisfied the same way with source `NETWORK`; and attestation
    evidence is satisfied when at least one signal on that date has source
    `MANUAL_ATTEST`, whatever its minutes."
    PRD 3.4: "The count of qualifying dates is finally capped at 5, so a week with
    weekend presence never credits more than five days."

    Design: Corner/calculations/manual_attestation_ignores_the_minute_floor_and_credit_is_capped_at_five
    """
    scenario = setup_open_week(
        cycle_overrides={"cycle_label": "FY27-ATTEST"},
        employee_overrides={"employee_number": "E-1001"},
    )
    week_id = scenario["week"]["id"]
    employee_id = scenario["employee"]["id"]

    add_signal(week_id, "2026-09-07", "BADGE", minutes_present=239,
               dedupe_key="B-0907-SHORT")
    add_signal(week_id, "2026-09-08", "BADGE", minutes_present=240,
               dedupe_key="B-0908-EXACT")
    add_signal(week_id, "2026-09-09", "MANUAL_ATTEST", minutes_present=0,
               dedupe_key="M-0909", headers=MANAGER)
    add_signal(week_id, "2026-09-12", "MANUAL_ATTEST", minutes_present=15,
               dedupe_key="M-0912-SAT", headers=MANAGER)

    first_pass = finalize(week_id)
    assert first_pass["variant_applied"] == "SIGNAL_UNION"
    assert first_pass["credited_days"] == 3, (
        "the badge at exactly 240 credits, the zero-minute attestation credits, and "
        "the Saturday attestation credits, while the 239-minute badge does not"
    )
    assert first_pass["required_days"] == 5
    assert first_pass["shortfall_days"] == 2
    assert read_employee(employee_id)["non_compliance_pressure"] == 4.00
    opened_case = first_case_for(employee_id)
    assert opened_case["stage"] == "WRITTEN_WARNING"

    amend(week_id, "late attestations received for the rest of the week")
    for observed, key in (
        ("2026-09-10", "M-0910"),
        ("2026-09-11", "M-0911"),
        ("2026-09-13", "M-0913-SUN"),
    ):
        add_signal(week_id, observed, "MANUAL_ATTEST", minutes_present=0,
                   dedupe_key=key, headers=MANAGER)

    second_pass = finalize(week_id)
    assert second_pass["credited_days"] == 5, (
        "six distinct dates now carry evidence, but the count of qualifying dates "
        "is capped at five"
    )
    assert second_pass["shortfall_days"] == 0
    settled_employee = read_employee(employee_id)
    assert settled_employee["non_compliance_pressure"] == 0.00
    assert settled_employee["compliance_state"] == "COMPLIANT"
    assert read_case(opened_case["id"])["stage"] == "CURED"

    _, signal_meta = validate_paginated(
        api_client.list_compliance_signals(AUDITOR, {"attendance_week_id": week_id})
    )
    assert signal_meta["total_count"] == 7, (
        "the uncredited 239-minute badge row is still stored: evidence that fails "
        "the floor is not deleted"
    )


def test_07_the_settle_amend_settle_loop_recomputes_the_week_on_every_lap():
    """The same week reports two credited days, then none, then three.

    PRD 3.5: "The telemetry feed, an `HRBusinessPartner` or a `PeopleManager`
    settles a week, moving it `OPEN → FINALIZED` the first time and `AMENDED →
    FINALIZED` on any later pass."
    PRD 3.5: "**First**, the week's own accounting is written: `status` becomes
    `FINALIZED`, `finalized_at` is stamped at the current logical instant,
    `required_days` is snapshotted, `variant_applied` records `SIGNAL_CORROBORATED`
    when the team requires corroboration and `SIGNAL_UNION` otherwise,
    `credited_days` is counted under that standard, `relief_days_credited` is applied
    from approved exceptions, and `shortfall_days` becomes the required days minus
    the credited days minus the credited relief, floored at zero so it never goes
    negative."
    PRD 3.5: "Reopening zeroes the week's `credited_days`, `relief_days_credited` and
    `shortfall_days`, so the week stops contributing to the employee's totals while
    it sits amended."
    PRD 3.5: "Because `FINALIZED → AMENDED → FINALIZED` is a cycle, a week may be
    corrected and re-settled any number of times."
    PRD 3.5: "Re-settlement after an amendment replays this identical chain against
    whatever signals and approved exceptions exist at that later moment."

    Design: Difficulty/non_linear_state_machine/attendance_week_finalize_amend_refinalize_cycle
    """
    scenario = _amendment_loop_scenario()
    week_id = scenario["week"]["id"]
    employee_id = scenario["employee"]["id"]

    first_lap = finalize(week_id)
    assert first_lap["status"] == "FINALIZED"
    assert first_lap["required_days"] == 5
    assert first_lap["credited_days"] == 2
    assert first_lap["shortfall_days"] == 3
    assert canonical_instant(first_lap["finalized_at"]) == "2026-09-01T09:00:00Z"
    assert read_employee(employee_id)["non_compliance_pressure"] == 5.50

    reason = "badge reader outage on 2026-09-10 confirmed by facilities"
    reopened = amend(week_id, reason)
    assert reopened["status"] == "AMENDED"
    assert reopened["credited_days"] == 0
    assert reopened["relief_days_credited"] == 0
    assert reopened["shortfall_days"] == 0
    assert reopened["amendment_reason"] == reason
    amended_employee = read_employee(employee_id)
    assert amended_employee["cumulative_shortfall_days"] == 0, (
        "an amended week is absent from the settled set entirely"
    )
    assert amended_employee["consecutive_breach_weeks"] == 0
    assert amended_employee["non_compliance_pressure"] == 0.00
    assert amended_employee["escalation_stage"] == "NONE"

    add_signal(week_id, "2026-09-10", "BADGE", minutes_present=480,
               dedupe_key="B-0910")
    pin_clock("2026-09-15T09:00:00Z")
    second_lap = finalize(week_id)
    assert second_lap["status"] == "FINALIZED", (
        "the machine re-enters a state it has already visited"
    )
    assert second_lap["credited_days"] == 3, (
        "the replay counts the evidence present at this later moment"
    )
    assert second_lap["shortfall_days"] == 2
    assert second_lap["amendment_reason"] == reason
    assert canonical_instant(second_lap["finalized_at"]) == "2026-09-15T09:00:00Z", (
        "the second settlement re-stamps finalized_at at the current logical instant"
    )
    assert read_employee(employee_id)["non_compliance_pressure"] == 4.00


def test_08_the_second_lap_opens_a_second_case_threaded_to_the_cured_one():
    """Curing by amendment and breaching again leaves a navigable case chain.

    PRD 3.5: "The employee's `cumulative_shortfall_days`, `consecutive_breach_weeks`,
    `non_compliance_pressure` and `compliance_state` are then recomputed downward,
    and the employee's open case — provided `discretionary_hold` is false — has its
    `stage` reset from the new pressure; when that value is `CURED` the case becomes
    `CURED` and `escalated_headcount`, `formal_action_count` and
    `formal_action_total` all decrement accordingly."
    PRD 3.5: "When a cascade leaves an employee in `BREACH` and no case of theirs
    sits outside the two terminal stages, the server opens one at `COACHING`, records
    `opened_pressure` as the employee's pressure at that instant, sets
    `discretionary_hold` to false, and sets `prior_case_id` to the `id` of that
    employee's most recently created `CURED` case — ordered by `created_at`
    descending — or null when this is their first case."
    PRD 3.5: "A later breach opens a brand-new case whose `prior_case_id` points back
    at the cured one, which is how the self-referential case history is threaded."

    Design: Difficulty/non_linear_state_machine/attendance_week_finalize_amend_refinalize_cycle
    """
    scenario = _amendment_loop_scenario()
    week_id = scenario["week"]["id"]
    employee_id = scenario["employee"]["id"]

    finalize(week_id)
    original_case = first_case_for(employee_id)
    assert original_case["stage"] == "WRITTEN_WARNING"
    assert original_case["prior_case_id"] is None
    assert original_case["opened_pressure"] == 5.50
    assert read_team(scenario["team"]["id"])["formal_action_count"] == 1

    amend(week_id, "badge reader outage on 2026-09-10 confirmed by facilities")
    cured = read_case(original_case["id"])
    assert cured["stage"] == "CURED", (
        "the amendment drove the pressure below the breach floor"
    )
    cleared_team = read_team(scenario["team"]["id"])
    assert cleared_team["escalated_headcount"] == 0
    assert cleared_team["formal_action_count"] == 0
    assert read_cycle(scenario["cycle"]["id"])["formal_action_total"] == 0

    add_signal(week_id, "2026-09-10", "BADGE", minutes_present=480,
               dedupe_key="B-0910")
    finalize(week_id)

    chain = cases_for(employee_id)
    assert len(chain) == 2, "the cured case is kept and a brand-new case is opened"
    successor = [case for case in chain if case["id"] != original_case["id"]][0]
    assert successor["prior_case_id"] == original_case["id"]
    assert successor["opened_pressure"] == 4.00
    assert successor["stage"] == "WRITTEN_WARNING"
    assert successor["discretionary_hold"] is False
    assert read_case(original_case["id"])["stage"] == "CURED", (
        "the cured case is not reopened"
    )
    assert read_employee(employee_id)["escalation_stage"] == "WRITTEN_WARNING"
    reopened_team = read_team(scenario["team"]["id"])
    assert reopened_team["escalated_headcount"] == 1
    assert reopened_team["formal_action_count"] == 1
    assert read_cycle(scenario["cycle"]["id"])["formal_action_total"] == 1


def test_09_one_settlement_leaves_nothing_for_a_later_read_to_settle():
    """The finalize response and four immediate reads already agree on every field.

    PRD 3.5: "What follows is a chain of six links, each caused by the previous one
    rather than by the call itself, and an implementation that stops after the first
    link will look correct on the week and wrong everywhere else."
    PRD 3.5: "**Second**, because this week has entered the settled set, the
    employee's `cumulative_shortfall_days`, `consecutive_breach_weeks`,
    `non_compliance_pressure` and `compliance_state` are all recomputed."
    PRD 3.5: "**Third**, if that recomputation left the employee in `BREACH` and no
    escalation case for them is currently open, a case is opened."
    PRD 3.5: "**Fourth**, the open case's stage is driven from the recomputed
    pressure."
    PRD 3.5: "**Fifth**, a stage that has entered the formal-action band changes the
    team's `formal_action_count`."
    PRD 3.5: "**Sixth**, because the team counter changed, the cycle's
    `formal_action_total` and `aggregate_compliance_rate` are recomputed."
    PRD 3.2: "Registration also recomputes the parent cycle's
    `aggregate_compliance_rate`, which is the count of `ACTIVE` employees on teams of
    that cycle whose `compliance_state` is `COMPLIANT`, divided by the total count of
    `ACTIVE` employees on those teams, multiplied by 100 and rounded half up to two
    decimals; when no `ACTIVE` employee exists on the cycle's teams at all the rate
    is exactly 0.00 rather than an error."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response_and_the_next_read
    """
    scenario = setup_open_week(
        cycle_overrides={"cycle_label": "FY27-IMMEDIATE"},
        employee_overrides={"employee_number": "E-1001"},
    )
    week_id = scenario["week"]["id"]
    employee_id = scenario["employee"]["id"]
    add_full_day_signals(week_id, ["2026-09-08", "2026-09-09", "2026-09-10"])

    settled = validate_success(api_client.finalize_week(week_id, SYSTEM))
    assert settled["status"] == "FINALIZED"
    assert settled["required_days"] == 5
    assert settled["credited_days"] == 3
    assert settled["relief_days_credited"] == 0
    assert settled["shortfall_days"] == 2
    assert settled["variant_applied"] == "SIGNAL_UNION"
    assert canonical_instant(settled["finalized_at"]) == "2026-09-01T09:00:00Z", (
        "no follow-up read is needed to see the settled week"
    )

    employee = read_employee(employee_id)
    assert employee["cumulative_shortfall_days"] == 2
    assert employee["consecutive_breach_weeks"] == 1
    assert employee["non_compliance_pressure"] == 4.00
    assert employee["compliance_state"] == "BREACH"
    assert employee["escalation_stage"] == "WRITTEN_WARNING"

    team = read_team(scenario["team"]["id"])
    assert team["escalated_headcount"] == 1
    assert team["formal_action_count"] == 1

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["aggregate_compliance_rate"] == 0.00, (
        "the cycle's only ACTIVE employee is in BREACH"
    )
    assert cycle["formal_action_total"] == 1

    cases, case_meta = validate_paginated(
        api_client.list_escalation_cases(HRBP, {"employee_id": employee_id})
    )
    assert case_meta["total_count"] == 1
    assert cases[0]["stage"] == "WRITTEN_WARNING", (
        "the cascade opened the case and drove its stage in the same call"
    )
    assert cases[0]["opened_pressure"] == 4.00
    assert cases[0]["discretionary_hold"] is False
    assert cases[0]["prior_case_id"] is None

    finalized, finalized_meta = validate_paginated(
        api_client.list_attendance_weeks(
            HRBP, {"employee_id": employee_id, "status": "FINALIZED"}
        )
    )
    assert finalized_meta["total_count"] == 1
    assert finalized_meta["has_more"] is False
    assert finalized[0]["id"] == week_id

    assert read_employee(employee_id) == employee, (
        "nothing settles late, so a second read returns the same row"
    )
    assert read_team(scenario["team"]["id"]) == team
    assert read_cycle(scenario["cycle"]["id"]) == cycle
    repeat_cases, repeat_case_meta = validate_paginated(
        api_client.list_escalation_cases(HRBP, {"employee_id": employee_id})
    )
    assert repeat_cases == cases
    assert repeat_case_meta["total_count"] == case_meta["total_count"]
