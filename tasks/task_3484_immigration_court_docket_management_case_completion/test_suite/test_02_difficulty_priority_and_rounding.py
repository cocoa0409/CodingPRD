"""Difficulty probes: combinatorial formulas with interacting inputs.

The priority score combines a custody step, a capped age term, and a capped
continuance drag; hearing durations are rounded per-hearing to 15-minute
blocks before any aggregation, and the judge's daily cap sums those rounded
blocks.
"""

from test_helpers import (
    ApiErrorId,
    advance_case_to_merits,
    case_version,
    create_case,
    create_court,
    create_judge,
    make_hearing_payload,
    read_case,
    schedule_hearing,
    set_clock,
    setup_docketed_case,
    same_instant,
    validate_error,
)


def test_priority_score_detained_step_plus_capped_age_term():
    """PRD §3.2: "The score starts from a base of 1000 points for a `DETAINED` case and 0 otherwise; it adds 2 points per calendar day of age as measured by `days_pending_calendar`, with the age term capped at 720 days; and it subtracts a drag of 25 points per granted continuance as measured by `continuance_count`, with the drag capped at 4 continuances — so a case with five granted continuances sheds the same 100 points as one with four."

    Design: Difficulty/combinatorial_formula/priority_score_three_input_interaction
    """
    court = create_court()
    detained = create_case(court["id"], custody_status="DETAINED")
    plain = create_case(court["id"], custody_status="NON_DETAINED")
    set_clock("2026-09-11T00:00:00Z")
    detained = read_case(detained["id"])
    plain = read_case(plain["id"])
    # Both cases were filed at the 2026-09-01T00:00:00Z clock anchor, so at
    # 2026-09-11 both show calendar age 10 with zero granted continuances.
    assert detained["days_pending_calendar"] == 10
    assert plain["days_pending_calendar"] == 10
    # 1000 + 2*min(10, 720) - 25*min(0, 4) = 1020.
    assert detained["priority_score"] == 1020
    # 0 + 2*10 - 0 = 20.
    assert plain["priority_score"] == 20
    # At identical age and continuance history the custody branch contributes
    # exactly the 1000-point step and nothing else.
    assert detained["priority_score"] - plain["priority_score"] == 1000


def test_priority_score_past_goal_reads_calendar_age_per_custody():
    """PRD §3.2: "The calendar variant alone drives the case's past-goal posture: `is_past_goal` is true only when `days_pending_calendar` strictly exceeds the custody-specific target."
    PRD §3.2: "The `continuance_count` itself counts only the case's `ContinuanceRequest` records in `GRANTED` status."

    Design: Difficulty/combinatorial_formula/priority_score_three_input_interaction
    """
    court = create_court()
    detained = create_case(court["id"], custody_status="DETAINED")
    plain = create_case(court["id"], custody_status="NON_DETAINED")
    set_clock("2026-09-11T00:00:00Z")
    detained = read_case(detained["id"])
    plain = read_case(plain["id"])
    # Age 10 is below both custody targets (60 detained / 365 non-detained).
    assert detained["is_past_goal"] is False
    assert plain["is_past_goal"] is False
    # No continuance requests exist, so the drag input is zero for both.
    assert detained["continuance_count"] == 0
    assert plain["continuance_count"] == 0


def _two_represented_cases_in_merits():
    """One court, one judge, two COUNSEL_RETAINED non-detained cases, each
    docketed and advanced through a completed master hearing into MERITS."""
    court = create_court()
    judge = create_judge(court["id"])
    first = setup_docketed_case(
        court=court, judge=judge, representation_status="COUNSEL_RETAINED"
    )
    advance_case_to_merits(first["case"], judge_id=judge["id"])
    second = setup_docketed_case(
        court=court, judge=judge, representation_status="COUNSEL_RETAINED",
        initial_clock=False,
    )
    advance_case_to_merits(
        second["case"], judge_id=judge["id"],
        master_start="2026-09-03T11:00:00Z", master_clock="2026-09-03T11:30:00Z",
    )
    return court, judge, first, second


def test_merits_hearing_duration_rounded_up_before_storage():
    """PRD §3.3: "An individual-merits hearing's raw length is 120 minutes, reduced by a factor of 0.75 when the case is `DETAINED` and by a factor of 0.8 when the respondent is represented — that is, whenever `representation_status` is anything other than `PRO_SE` — with both factors applying to a detained, represented case. The raw length is then rounded up to the next multiple of 15 minutes to produce the stored `duration_minutes`."
    PRD §3.3: "two represented, non-detained merits hearings run 96 raw minutes each yet contribute 105 minutes apiece after rounding, 210 toward the daily total, not the 195 that a single rounding of 192 would yield."

    Design: Difficulty/combinatorial_formula/hearing_block_rounding_then_sum_order
    """
    _, judge, first, _ = _two_represented_cases_in_merits()
    hearing = schedule_hearing(
        read_case(first["case"]["id"]), "INDIVIDUAL_MERITS", "2026-09-04T10:00:00Z"
    )
    # Raw 120 * 0.8 = 96 minutes is ceiled to the 105-minute block BEFORE the
    # value is stored on the hearing.
    assert hearing["duration_minutes"] == 105
    # scheduled_end is scheduled_start + the stored (rounded) duration:
    # 10:00 + 105 minutes = 11:45, not the 11:36 the raw minutes would give.
    assert same_instant(hearing["scheduled_end"], "2026-09-04T11:45:00Z")
    assert hearing["status"] == "SCHEDULED"
    assert hearing["auto_created"] is False
    assert hearing["judge_id"] == judge["id"]


def test_judge_daily_load_sums_rounded_blocks(api, admin_headers):
    """PRD §3.3: "The system totals the already-rounded `duration_minutes` of the judge's `SCHEDULED` hearings falling on the new hearing's UTC calendar date, adds the new hearing's rounded duration, and requires the sum to be at most 120 minutes; a sum of exactly 120 is allowed, and anything above it rejects the hearing with `ERR_JUDGE_DAILY_MINUTES_EXCEEDED`."
    PRD §3.3: "Rounding each hearing first and then summing is a different algorithm from summing raw minutes and rounding once, and it is the pinned one — two represented, non-detained merits hearings run 96 raw minutes each yet contribute 105 minutes apiece after rounding, 210 toward the daily total, not the 195 that a single rounding of 192 would yield."

    Design: Difficulty/combinatorial_formula/hearing_block_rounding_then_sum_order
    """
    _, _, first, second = _two_represented_cases_in_merits()
    hearing = schedule_hearing(
        read_case(first["case"]["id"]), "INDIVIDUAL_MERITS", "2026-09-04T10:00:00Z"
    )
    assert hearing["duration_minutes"] == 105
    # The second case's merits starts exactly when the first ends (adjacency
    # is not an overlap), so the judge's daily-minute cap is the only failing
    # check: 105 + 105 = 210 > 120 under the pinned round-then-sum order.
    payload = make_hearing_payload(
        second["case"]["id"], "INDIVIDUAL_MERITS", "2026-09-04T11:45:00Z",
        case_version(second["case"]["id"]),
    )
    resp = api.create_hearing(payload, headers=admin_headers)
    validate_error(resp, ApiErrorId.ERR_JUDGE_DAILY_MINUTES_EXCEEDED)
