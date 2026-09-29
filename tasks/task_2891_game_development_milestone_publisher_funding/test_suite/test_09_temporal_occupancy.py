"""Two occupancy calendars: the reviewer's half-open review windows and the vendor's
buffered engagement intervals."""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_REVIEWER_WINDOW_CONFLICT, ERR_VENDOR_COOLDOWN_CONFLICT
from test_helpers.assertions import assert_budget_summary, assert_fields_equal
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    DEFAULT_CRITERIA_2,
    activate,
    add_milestone,
    create_engagement,
    draft_agreement,
    read_milestone,
    record_accepted_review,
    setup_registry,
    submit_build,
)
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

ALPHA_PASSING = {
    "feature_completeness_pct": 75.00,
    "crash_free_sessions_pct": 96.00,
    "content_completeness_pct": 60.00,
    "known_blocker_count": 5,
}


def _two_marrow_builds_one_reviewer_busy(api):
    """Two independent agreements; the shared reviewer already occupies 09:00-13:00."""
    reg = setup_registry(api, studio_name="Marrowlight Games",
                        studio_email="dev@marrowlight.example", studio_country="DE")
    agreement_a = draft_agreement(reg, "Marrow A", 3600000, 2500, "2027-03-31",
                                  live_ops_quarterly_funding_cents=100000)
    milestone_a = add_milestone(reg, agreement_a["id"], 1, "Alpha A", "ALPHA",
                                3600000, 0, DEFAULT_CRITERIA_2)
    activate(reg, agreement_a["id"])
    build_a = submit_build(reg, milestone_a["id"], 1, ALPHA_PASSING)

    agreement_b = draft_agreement(reg, "Marrow B", 1000000, 2500, "2027-09-30",
                                  live_ops_quarterly_funding_cents=100000)
    milestone_b = add_milestone(reg, agreement_b["id"], 1, "Alpha B", "ALPHA",
                                1000000, 0, DEFAULT_CRITERIA_1)
    activate(reg, agreement_b["id"])
    build_b = submit_build(reg, milestone_b["id"], 1, ALPHA_PASSING)

    review_a = record_accepted_review(reg, build_a["id"], start_hour=9, end_hour=13)
    assert review_a["review_window_end_at"] == "2026-08-01T13:00:00.000Z"
    return reg, milestone_a, milestone_b, build_b, review_a


def _rejected_window(build_id, start_hour, end_hour):
    return f.review_payload(
        build_id, "REJECTED",
        f.utc_instant("2026-08-01", start_hour), f.utc_instant("2026-08-01", end_hour),
        notes="Slot under test",
    )


def test_a_window_overlapping_the_reviewers_existing_slot_is_refused(api):
    """PRD §3.5: "Two windows conflict when the new window's start falls strictly
    before the existing window's `review_window_end_at` and the existing window's
    `review_window_start_at` falls strictly before the new window's end; a conflict is
    `ERR_REVIEWER_WINDOW_CONFLICT`." The check spans "every agreement that reviewer
    works on".

    Design: Difficulty/resource_temporal_overlap/reviewer_window_half_open_overlap_blocks_but_adjacency_is_legal
    """
    reg, _milestone_a, milestone_b, build_b, _review_a = _two_marrow_builds_one_reviewer_busy(api)

    response = api.create_review(_rejected_window(build_b["id"], 12, 14), reg.reviewer)
    validate_error(response, ERR_REVIEWER_WINDOW_CONFLICT, 409)

    assert read_milestone(reg, milestone_b["id"])["status"] == "UNDER_REVIEW"
    rows, meta = validate_paginated(api.list_reviews(reg.reviewer, {"build_id": build_b["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_a_window_beginning_at_the_previous_windows_end_is_admitted(api):
    """PRD §3.5: "Because both comparisons are strict, back-to-back windows are legal —
    a new window may begin at the exact instant an existing one ends, or end at the
    exact instant an existing one begins."

    Design: Difficulty/resource_temporal_overlap/reviewer_window_half_open_overlap_blocks_but_adjacency_is_legal
    """
    reg, milestone_a, milestone_b, build_b, review_a = _two_marrow_builds_one_reviewer_busy(api)

    review_b = validate_success(
        api.create_review(_rejected_window(build_b["id"], 13, 17), reg.reviewer), 201
    )
    assert review_b["verdict"] == "REJECTED"
    assert review_b["review_window_start_at"] == review_a["review_window_end_at"]

    assert read_milestone(reg, milestone_b["id"])["status"] == "IN_DEVELOPMENT"
    assert validate_success(api.get_build(build_b["id"], reg.dev))["gate_state"] == "SUPERSEDED"
    assert read_milestone(reg, milestone_a["id"])["status"] == "ACCEPTED"

    _rows, meta = validate_paginated(
        api.list_reviews(reg.reviewer, {"reviewer_user_id": reg.reviewer_id})
    )
    assert meta["total_count"] == 2


def _duskharbor_with_one_vendor_block(api):
    """One ONE-VOICE engagement across the closed interval 2026-08-05..2026-08-20."""
    reg = setup_registry(api, studio_name="Duskharbor Studio",
                        studio_email="dev@duskharbor.example", studio_country="BR",
                        with_reviewer=False)
    agreement = draft_agreement(reg, "Duskharbor", 1000000, 2500, "2027-03-31",
                                live_ops_quarterly_funding_cents=100000)
    milestone = add_milestone(reg, agreement["id"], 1, "Alpha", "ALPHA",
                              1000000, 500000, DEFAULT_CRITERIA_2)
    activate(reg, agreement["id"])
    first = create_engagement(
        reg, milestone["id"], "ONE-VOICE", 300000, "2026-08-05", "2026-08-20",
        "Voice recording block 1",
    )
    assert first["status"] == "ACTIVE"
    return reg, milestone, first


def _second_block(milestone_id, start_date):
    return f.engagement_payload(
        milestone_id, "ONE-VOICE", 200000, start_date, "2026-09-10",
        "Voice recording block 2",
    )


def test_the_third_day_after_the_previous_engagement_is_still_blocked(api):
    """PRD §3.8: "Each candidate is treated as a closed date interval and padded
    symmetrically by a three-day buffer on both sides ... adjacency is illegal rather
    than legal here — three days after a prior engagement's `end_date` is still
    blocked, and the fourth day after it is the earliest lawful `start_date`."

    Design: Difficulty/resource_temporal_overlap/vendor_cooldown_buffer_blocks_day_three_and_clears_on_day_four
    """
    reg, milestone, first = _duskharbor_with_one_vendor_block(api)

    response = api.create_engagement(_second_block(milestone["id"], "2026-08-23"), reg.dev)
    validate_error(response, ERR_VENDOR_COOLDOWN_CONFLICT, 409)

    rows, meta = validate_paginated(
        api.list_engagements(reg.dev, {"milestone_id": milestone["id"]})
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == first["id"]
    assert_budget_summary(
        validate_success(api.get_budget_summary(milestone["id"], reg.dev)),
        milestone_id=milestone["id"], budget=500000, committed_basis=300000,
        incurred_basis=0, available_committed=200000, overrun=0,
    )


def test_the_fourth_day_after_the_previous_engagement_clears_the_cooldown(api):
    """PRD §3.8: "a conflict exists when the new engagement's `start_date` falls on or
    before the candidate's `end_date` plus three days **and** the candidate's
    `start_date` falls on or before the new engagement's `end_date` plus three days."
    A start on the fourth day fails the first half of that conjunction.

    Design: Difficulty/resource_temporal_overlap/vendor_cooldown_buffer_blocks_day_three_and_clears_on_day_four
    """
    reg, milestone, first = _duskharbor_with_one_vendor_block(api)

    second = validate_success(
        api.create_engagement(_second_block(milestone["id"], "2026-08-24"), reg.dev), 201
    )
    assert_fields_equal(
        second, {"status": "ACTIVE", "start_date": "2026-08-24"}, "engagement"
    )
    assert validate_success(api.get_engagement(first["id"], reg.dev))["status"] == "ACTIVE"

    assert_budget_summary(
        validate_success(api.get_budget_summary(milestone["id"], reg.dev)),
        milestone_id=milestone["id"], budget=500000, committed_basis=500000,
        incurred_basis=0, available_committed=0, overrun=0,
    )
