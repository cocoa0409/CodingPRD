"""Outcome tracking: the persistence ladder checkpoints and the dual-variant
persistence rates on the cycle's computed summary."""
from test_helpers import (
    TEST_USERS,
    advance_cycle_to_phase,
    assert_outcome_summary,
    checkpoint_outcome_record,
    expect_success,
    setup_enrolled_matches,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def _setup_four_records_checkpoints_applied():
    """Four enrolled matches; record 0 walks the full ladder to GRADUATED,
    record 1 persists to Y2, record 2 persists to Y3, record 3 stops out."""
    ctx = setup_enrolled_matches(4)
    cycle = advance_cycle_to_phase(ctx["cycle"]["id"], "OUTCOME_TRACKING")
    ctx["cycle"] = cycle
    records = ctx["outcome_records"]
    college_id = ctx["college"]["id"]
    checkpoint_outcome_record(records[0]["id"], "PERSISTED_Y2", college_id)
    checkpoint_outcome_record(records[0]["id"], "PERSISTED_Y3", college_id)
    checkpoint_outcome_record(records[0]["id"], "GRADUATED", college_id)
    checkpoint_outcome_record(records[1]["id"], "PERSISTED_Y2", college_id)
    checkpoint_outcome_record(records[2]["id"], "PERSISTED_Y2", college_id)
    checkpoint_outcome_record(records[2]["id"], "PERSISTED_Y3", college_id)
    checkpoint_outcome_record(records[3]["id"], "STOPPED_OUT", college_id)
    return ctx


def test_on_track_rate_counts_persisted_and_graduated(api):
    """PRD §3.9: "The denominator for both rates is the count of all outcome
    records of the cycle regardless of status. The on-track numerator counts
    records in `PERSISTED_Y2`, `PERSISTED_Y3`, or `GRADUATED` — a
    continued-enrollment measure — while the cohort-150 numerator counts
    `GRADUATED` alone, a completion measure, so the two diverge whenever any
    enrollee persists without graduating. Each rate is expressed in basis
    points: the numerator multiplied by 10,000, divided by the denominator,
    and rounded half-up to a whole basis point."
    PRD §3.9: "The legal moves trace a persistence ladder with a re-entry
    ramp: `ENROLLED_Y1` → `PERSISTED_Y2`, then `PERSISTED_Y2` →
    `PERSISTED_Y3`, then `PERSISTED_Y3` → `GRADUATED` for students who
    finish; ..."

    Design: Difficulty/dual_variant_calc/persistence_on_track_vs_cohort150
    """
    ctx = _setup_four_records_checkpoints_applied()
    resp = api.get_outcome_summary(ctx["cycle"]["id"], _ADMIN)
    summary = expect_success(resp, 200)
    assert_outcome_summary(summary)
    assert summary["enrolled_count"] == 4
    assert summary["on_track_denominator"] == 4
    assert summary["on_track_numerator"] == 3, (
        "PERSISTED_Y2 + PERSISTED_Y3 + GRADUATED; STOPPED_OUT does not count"
    )
    assert summary["on_track_rate_bp"] == 7500, "3 * 10,000 / 4 == 7,500 bp"


def test_cohort150_rate_counts_graduated_only(api):
    """PRD §3.9: "The on-track numerator counts records in `PERSISTED_Y2`,
    `PERSISTED_Y3`, or `GRADUATED` — a continued-enrollment measure — while
    the cohort-150 numerator counts `GRADUATED` alone, a completion measure,
    so the two diverge whenever any enrollee persists without graduating. Each
    rate is expressed in basis points: the numerator multiplied by 10,000,
    divided by the denominator, and rounded half-up to a whole basis point."
    PRD §3.9: "The cycle's outcome summary is a computed read, open to every
    authenticated role, that reports `enrolled_count`, `on_track_numerator`,
    `on_track_denominator`, `on_track_rate_bp`, `cohort150_numerator`,
    `cohort150_denominator`, and `cohort150_rate_bp`."

    Design: Difficulty/dual_variant_calc/persistence_on_track_vs_cohort150
    """
    ctx = _setup_four_records_checkpoints_applied()
    resp = api.get_outcome_summary(ctx["cycle"]["id"], _ADMIN)
    summary = expect_success(resp, 200)
    assert summary["cohort150_denominator"] == 4
    assert summary["cohort150_numerator"] == 1, "only the GRADUATED record"
    assert summary["cohort150_rate_bp"] == 2500, "1 * 10,000 / 4 == 2,500 bp"
    assert summary["on_track_rate_bp"] != summary["cohort150_rate_bp"], (
        "the two variants diverge on the same records: 7,500 != 2,500"
    )
