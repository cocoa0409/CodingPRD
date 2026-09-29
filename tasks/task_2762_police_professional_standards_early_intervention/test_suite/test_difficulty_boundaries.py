"""Exact boundaries: the rounded preponderance, the small cell and the notice hour."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_instant,
    assert_one_dp,
    assert_report_group,
    assert_two_dp,
)
from test_helpers import factories, fixtures


def case_at_marginal_findings(api, weight_for, weight_against):
    """One Class C allegation carried to findings on the weights supplied."""
    world = fixtures.world_assigned_investigation(api, offense_class="C")
    session = fixtures.schedule_session(api, world, world["i1_id"])
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.hold_session(api, world, session["id"])
    filed = fixtures.submit_findings(
        api,
        world,
        world["i1_id"],
        [factories.finding_entry(world["a1_id"], weight_for, weight_against)],
    )
    world.update({"s1_id": session["id"], "filed": filed})
    return world


def test_a_raw_ratio_above_fifty_percent_still_fails_once_rounded(api):
    """Five thousand and one against five thousand rounds down to an exact tie.

    PRD: Note carefully that the comparison is made on the **rounded** `support_pct` and not on the raw ratio — weights of 5001 for and 5000 against give a raw ratio of 50.005 percent, which exceeds the threshold, yet rounds to `support_pct` 50.00 and therefore leaves `preponderance_met` false.
    Design: Difficulty/boundary_precision_check/preponderance_decided_on_the_rounded_support_pct_not_the_raw_ratio
    """
    world = case_at_marginal_findings(api, 5001, 5000)
    assert world["filed"]["status"] == "PENDING_REVIEW"

    allegation = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert_two_dp(allegation["support_pct"], 50.00, label="support_pct")
    assert allegation["preponderance_met"] is False

    refused = api.dispose_allegation(
        world["a1_id"],
        factories.disposition_payload("SUSTAINED", rationale="Attempt on the rounded tie."),
        world["cmdr_headers"],
    )

    validate_error(refused, "ERR_PREPONDERANCE_NOT_MET", 422)
    unchanged = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert unchanged["disposition"] == "PENDING"
    assert unchanged["disposed_at"] is None
    disciplines, _ = fixtures.rows(
        api.list_disciplines(world["cmdr_headers"], {"allegation_id": world["a1_id"]})
    )
    assert disciplines == []
    complaint = fixtures.read_complaint(api, world["c_id"], world["cmdr_headers"])
    assert complaint["sustained_allegation_count"] == 0


def test_one_more_unit_of_weight_rounds_up_and_carries_the_burden(api):
    """Five thousand and two against five thousand rounds to 50.01 and succeeds.

    PRD: Otherwise `support_pct` is one hundred times `evidence_weight_for` divided by the total, rounded half up to two decimal places.
    PRD: `preponderance_met` is then true only when `support_pct` is **strictly greater than** 50.00.
    Design: Difficulty/boundary_precision_check/preponderance_decided_on_the_rounded_support_pct_not_the_raw_ratio
    """
    world = case_at_marginal_findings(api, 5001, 5000)

    get_success_data(
        api.toll_investigation(
            world["i1_id"],
            factories.tolling_payload("RESUME", tolling_reason="Reopened to weigh one further exhibit."),
            world["cmdr_headers"],
        )
    )
    revised = fixtures.submit_findings(
        api, world, world["i1_id"], [factories.finding_entry(world["a1_id"], 5002, 5000)]
    )
    assert revised["status"] == "PENDING_REVIEW"

    allegation = fixtures.read_allegation(api, world["a1_id"], world["cmdr_headers"])
    assert_two_dp(allegation["support_pct"], 50.01, label="support_pct")
    assert allegation["preponderance_met"] is True

    disposed = fixtures.dispose_allegation(api, world, world["a1_id"], "SUSTAINED")

    assert disposed["disposition"] == "SUSTAINED"
    disciplines, _ = fixtures.rows(
        api.list_disciplines(world["cmdr_headers"], {"allegation_id": world["a1_id"]})
    )
    assert len(disciplines) == 1
    assert disciplines[0]["status"] == "PROPOSED"
    assert disciplines[0]["presumptive_days"] == 3
    complaint = fixtures.read_complaint(api, world["c_id"], world["cmdr_headers"])
    assert complaint["sustained_allegation_count"] == 1


PERIOD = ("2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")


def five_closed_files_across_two_demographics(api, world):
    """Three DG_A withdrawals, one DG_B withdrawal and one DG_B sustained close."""
    withdrawn = []
    for index, demographic in enumerate(("DG_A", "DG_A", "DG_A", "DG_B"), start=1):
        complaint = fixtures.file_supervisor_complaint(
            api,
            world,
            narrative=f"Rude tone at a traffic stop, number {index}.",
            incident_datetime=f"2026-07-0{index + 1}T10:00:00Z",
            reported_allegation_types=["DISCOURTESY"],
            complainant_demographic_code=demographic,
        )
        withdrawn.append(complaint)

    sustained = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Neglect of duty on the late shift.",
        incident_datetime="2026-07-15T20:00:00Z",
        reported_allegation_types=["NEGLECT_OF_DUTY"],
        complainant_demographic_code="DG_B",
    )
    allegation = fixtures.attach_allegation(
        api, world, sustained["id"], allegation_type="NEGLECT_OF_DUTY", offense_class="C"
    )
    investigation = fixtures.open_investigation(api, world, sustained["id"])
    fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], world["inv_a_id"]
    )
    session = fixtures.schedule_session(
        api,
        world,
        investigation["id"],
        scheduled_start="2026-08-10T09:00:00Z",
        scheduled_end="2026-08-10T10:30:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
    )

    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    for complaint in withdrawn:
        fixtures.withdraw_complaint(
            api,
            world,
            complaint["id"],
            intake_reference_code=complaint["intake_reference_code"],
            withdrawal_reason="Resolved informally.",
        )

    fixtures.set_clock(api, "2026-08-10T09:00:00Z")
    fixtures.hold_session(api, world, session["id"])
    fixtures.submit_findings(
        api, world, investigation["id"], [factories.finding_entry(allegation["id"], 60, 40)]
    )
    fixtures.dispose_allegation(api, world, allegation["id"], "SUSTAINED")
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    fixtures.close_investigation(api, world, investigation["id"])

    return {
        "withdrawn_ids": [row["id"] for row in withdrawn],
        "c5_id": sustained["id"],
        "a5_id": allegation["id"],
        "i5_id": investigation["id"],
    }


def read_report(api, world, breakdown=None):
    """Read the outcome report over the whole of August."""
    return get_success_data(
        api.get_complaint_outcome_report(
            world["custodian_headers"],
            factories.outcome_report_params(PERIOD[0], PERIOD[1], breakdown=breakdown),
        )
    )


def test_a_cell_of_three_is_disclosed_while_a_cell_of_two_rolls_up(api, world):
    """DG_A stands at exactly the threshold; DG_B falls below it and empties into SUPPRESSED.

    PRD: Any group whose `total_complaints` is **strictly less than** 3 is suppressed: its `total_complaints`, `sustained_complaints` and `sustain_rate_pct` are all reported as null and its `suppressed` flag is true, and its counts are rolled into a single trailing group whose `group_key` is the literal `SUPPRESSED`.
    PRD: A group of exactly 3 is disclosed in full, since the comparison is strict.
    Design: Difficulty/boundary_precision_check/small_cell_suppression_discloses_exactly_three_and_hides_two
    """
    five_closed_files_across_two_demographics(api, world)

    report = read_report(api, world, breakdown="DEMOGRAPHIC")

    assert report["suppression_min_cell"] == 3
    assert report["total_complaints"] == 5
    assert report["sustained_complaints"] == 1
    assert_one_dp(report["sustain_rate_pct"], 20.0, label="sustain_rate_pct")

    groups = report["groups"]
    assert [row["group_key"] for row in groups] == ["DG_A", "DG_B", "SUPPRESSED"]
    assert_report_group(groups[0], "DG_A", 3, 0, 0.0, False)
    assert_report_group(groups[1], "DG_B", None, None, None, True)
    assert_report_group(groups[2], "SUPPRESSED", 2, 1, 50.0, False)


def test_the_same_five_files_are_fully_disclosed_without_a_demographic_breakdown(api, world):
    """Suppression is decided per group, so one group of five hides nothing.

    PRD: Grouping follows the `breakdown`: `DEMOGRAPHIC` groups by `complainant_demographic_code`, with `UNKNOWN` forming a group of its own; `CHANNEL` groups by `intake_channel`; and when `breakdown` is omitted the whole population forms a single group whose `group_key` is the literal `ALL`.
    PRD: The report's top-level `period_start`, `period_end`, `breakdown`, `total_complaints`, `sustained_complaints` and `sustain_rate_pct` describe the whole population and are never suppressed.
    Design: Difficulty/boundary_precision_check/small_cell_suppression_discloses_exactly_three_and_hides_two
    """
    five_closed_files_across_two_demographics(api, world)

    ungrouped = read_report(api, world)

    assert ungrouped["breakdown"] == "ALL"
    assert ungrouped["total_complaints"] == 5
    assert ungrouped["sustained_complaints"] == 1
    assert_one_dp(ungrouped["sustain_rate_pct"], 20.0, label="sustain_rate_pct")
    assert len(ungrouped["groups"]) == 1
    assert_report_group(ungrouped["groups"][0], "ALL", 5, 1, 20.0, False)

    by_channel = read_report(api, world, breakdown="CHANNEL")

    assert by_channel["breakdown"] == "CHANNEL"
    assert by_channel["total_complaints"] == 5
    assert by_channel["sustained_complaints"] == 1
    assert_one_dp(by_channel["sustain_rate_pct"], 20.0, label="sustain_rate_pct")
    assert [row["group_key"] for row in by_channel["groups"]] == ["SUPERVISOR"]
    assert_report_group(by_channel["groups"][0], "SUPERVISOR", 5, 1, 20.0, False)


def session_payload(world, notice_served_at, start="2026-08-10T09:00:00Z", end="2026-08-10T10:30:00Z"):
    """A booking whose only variable is the instant written notice was served."""
    return factories.interview_session_payload(
        world["subj_id"],
        world["room1_id"],
        scheduled_start=start,
        scheduled_end=end,
        notice_served_at=notice_served_at,
        representation_status="REP_PRESENT",
    )


def test_notice_of_exactly_forty_eight_hours_is_accepted_and_one_minute_less_is_not(api):
    """Forty-seven hours fifty-nine minutes floors to 47 and fails; the exact 48 passes.

    PRD: The officer bill-of-rights test is non-strict: `notice_hours` must be at least 48, which is two full days of written notice.
    PRD: Notice served one minute later than that — say at one minute past nine on the eighth of a month for a session starting at nine on the tenth — yields an elapsed span of forty-seven hours and fifty-nine minutes, which floors to 47 and fails with `ERR_INSUFFICIENT_NOTICE`.
    Design: Difficulty/boundary_precision_check/interview_notice_accepted_at_exactly_forty_eight_hours_and_rejected_at_forty_seven
    """
    world = fixtures.world_assigned_investigation(api, offense_class="C")
    assert world["investigation"]["status"] == "ASSIGNED"

    refused = api.schedule_interview_session(
        world["i1_id"], session_payload(world, "2026-08-08T09:01:00Z"), world["inv_a_headers"]
    )
    validate_error(refused, "ERR_INSUFFICIENT_NOTICE", 422)
    sessions, _ = fixtures.rows(
        api.list_interview_sessions(world["inv_a_headers"], {"investigation_id": world["i1_id"]})
    )
    assert sessions == []
    assert fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])["status"] == "ASSIGNED"

    accepted = get_success_data(
        api.schedule_interview_session(
            world["i1_id"], session_payload(world, "2026-08-08T09:00:00Z"), world["inv_a_headers"]
        )
    )

    assert accepted["status"] == "SCHEDULED"
    assert_two_dp(accepted["notice_hours"], 48, label="notice_hours")
    assert accepted["duration_minutes"] == 90
    assert accepted["postpone_count"] == 0
    assert accepted["held_at"] is None
    assert fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])["status"] == "IN_PROGRESS"


def test_a_postponement_re_tests_the_same_boundary_against_the_new_notice(api):
    """The original notice buys nothing: the new pair of instants is measured on its own.

    PRD: And `notice_hours` is recomputed from `new_notice_served_at` to `new_scheduled_start` and re-tested against the same non-strict 48-hour minimum: **the original notice does not carry over to the new date**, so a postponement to a date less than forty-eight hours after the newly served notice fails with `ERR_INSUFFICIENT_NOTICE`.
    PRD: An accepted postponement raises `postpone_count` by 1 and rewrites `scheduled_start`, `scheduled_end`, `notice_served_at`, `notice_hours` and `duration_minutes`.
    Design: Difficulty/boundary_precision_check/interview_notice_accepted_at_exactly_forty_eight_hours_and_rejected_at_forty_seven
    """
    world = fixtures.world_assigned_investigation(api, offense_class="C")
    booked = get_success_data(
        api.schedule_interview_session(
            world["i1_id"], session_payload(world, "2026-08-08T09:00:00Z"), world["inv_a_headers"]
        )
    )

    refused = api.postpone_interview_session(
        booked["id"],
        factories.postpone_payload(
            "2026-08-15T09:00:00Z", "2026-08-15T11:00:00Z", "2026-08-13T09:01:00Z"
        ),
        world["inv_a_headers"],
    )

    validate_error(refused, "ERR_INSUFFICIENT_NOTICE", 422)
    held_over = fixtures.read_session(api, booked["id"], world["inv_a_headers"])
    assert held_over["postpone_count"] == 0
    assert held_over["status"] == "SCHEDULED"
    assert_instant(held_over["scheduled_start"], "2026-08-10T09:00:00Z")
    assert_two_dp(held_over["notice_hours"], 48, label="notice_hours")
    assert held_over["duration_minutes"] == 90

    moved = get_success_data(
        api.postpone_interview_session(
            booked["id"],
            factories.postpone_payload(
                "2026-08-15T09:00:00Z", "2026-08-15T11:00:00Z", "2026-08-13T09:00:00Z"
            ),
            world["inv_a_headers"],
        )
    )

    assert moved["status"] == "SCHEDULED"
    assert moved["postpone_count"] == 1
    assert_instant(moved["scheduled_start"], "2026-08-15T09:00:00Z")
    assert_instant(moved["scheduled_end"], "2026-08-15T11:00:00Z")
    assert_instant(moved["notice_served_at"], "2026-08-13T09:00:00Z")
    assert_two_dp(moved["notice_hours"], 48, label="notice_hours")
    assert moved["duration_minutes"] == 120
