"""The acceptance gate: how the content and feature bars are reshaped by relief,
cure state and stability surplus, where GOLD refuses every concession, and how the
gate outranks the cure window."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_BUILD_GATE_NOT_MET,
    ERR_CURE_WINDOW_EXPIRED,
)
from test_helpers.assertions import assert_fields_equal, assert_pct_equals
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_2,
    DEFAULT_CRITERIA_3,
    activate,
    add_milestone,
    draft_agreement,
    record_conditional_review,
    setup_registry,
    setup_single_alpha,
    submit_build,
)
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

BETA_FIRST_BUILD = {
    "feature_completeness_pct": 95.00,
    "crash_free_sessions_pct": 98.00,
    "content_completeness_pct": 85.00,
    "known_blocker_count": 2,
}
BETA_CURE_BUILD = {
    "feature_completeness_pct": 88.00,
    "crash_free_sessions_pct": 98.50,
    "content_completeness_pct": 75.00,
    "known_blocker_count": 5,
}
ALPHA_PASSING = {
    "feature_completeness_pct": 75.00,
    "crash_free_sessions_pct": 96.00,
    "content_completeness_pct": 60.00,
    "known_blocker_count": 5,
}


def _nova_tide(api):
    """Two sibling BETA milestones; only the first is driven into a cure round and
    given content-threshold relief."""
    reg = setup_registry(api)
    agreement = draft_agreement(reg, "Nova Tide", 6000000, 2500, "2027-06-30")
    m1 = add_milestone(reg, agreement["id"], 1, "Content Complete", "BETA",
                       5400000, 0, DEFAULT_CRITERIA_3)
    m2 = add_milestone(reg, agreement["id"], 2, "Localization Pass", "BETA",
                       600000, 0, DEFAULT_CRITERIA_2)
    activate(reg, agreement["id"])

    build1 = submit_build(reg, m1["id"], 1, BETA_FIRST_BUILD)
    record_conditional_review(reg, build1["id"], [0, 2], 14)

    version = validate_success(api.get_agreement(agreement["id"], reg.finance))["version"]
    order = validate_success(
        api.create_change_order(
            f.change_order_payload(
                agreement["id"], m1["id"], "FEATURE_CUT", version,
                "Cutting the third biome to protect the date",
                requested_amount_cents=400000, ship_date_delta_days=0,
                content_threshold_relief_pct=10.00,
            ),
            reg.finance,
        ),
        201,
    )
    decided = validate_success(
        api.decide_change_order(order["id"], f.approve_payload("Scope trimmed"), reg.finance)
    )
    assert decided["state"] == "APPROVED_CUT"
    return reg, agreement["id"], m1, m2, build1


def test_relief_and_cure_uplift_and_stability_surplus_reshape_both_bars(api):
    """PRD §3.4: "start from the profile's content figure, subtract the milestone's
    accumulated `content_threshold_relief_pct` ... then, and only when the
    milestone's `status` is `CURE_PENDING`, add back 5.00 percentage points"; and
    "When the milestone's `gate_profile` is not `GOLD` and the build's
    `crash_free_sessions_pct` is at least half a percentage point above the
    profile's crash-free figure, the effective feature bar is the profile's feature
    figure less 2.00 percentage points".

    Design: Difficulty/combinatorial_formula/gate_threshold_shape_selected_by_profile_status_relief_and_stability_combination
    """
    reg, _agreement_id, m1, _m2, build1 = _nova_tide(api)

    build2 = validate_success(
        api.create_build(
            f.build_payload_from_metrics(m1["id"], 2, BETA_CURE_BUILD, [0, 2]), reg.dev
        ),
        201,
    )
    assert build2["gate_state"] == "PASSED"
    assert_pct_equals(build2["readiness_score"], 89.08, "readiness_score")

    milestone = validate_success(api.get_milestone(m1["id"], reg.dev))
    assert_fields_equal(
        milestone,
        {
            "status": "UNDER_REVIEW",
            "latest_build_number": 2,
            "open_condition_indexes": [],
            "cure_deadline_at": None,
            "uplift_cents": -400000,
        },
        "milestone",
    )
    assert_pct_equals(milestone["content_threshold_relief_pct"], 10.00, "relief")
    assert validate_success(api.get_build(build1["id"], reg.dev))["gate_state"] == "SUPERSEDED"


def test_the_same_metrics_miss_the_unrelieved_bar_on_the_sibling_milestone(api):
    """PRD §3.4: "If any of the four fails, the submission is rejected with
    `ERR_BUILD_GATE_NOT_MET` and no build row is persisted at all." A sibling
    milestone that bought no relief and is not in a cure round faces the raw 80.00
    content bar of its `BETA` profile.

    Design: Difficulty/combinatorial_formula/gate_threshold_shape_selected_by_profile_status_relief_and_stability_combination
    """
    reg, _agreement_id, _m1, m2, _build1 = _nova_tide(api)

    rejected = api.create_build(
        f.build_payload_from_metrics(m2["id"], 1, BETA_CURE_BUILD), reg.dev
    )
    validate_error(rejected, ERR_BUILD_GATE_NOT_MET, 422)

    milestone = validate_success(api.get_milestone(m2["id"], reg.dev))
    assert_fields_equal(
        milestone, {"status": "IN_DEVELOPMENT", "latest_build_number": 0}, "milestone"
    )
    rows, meta = validate_paginated(api.list_milestone_builds(m2["id"], reg.dev))
    assert rows == [] and meta["total_count"] == 0


def _lodestar(api):
    reg = setup_registry(api, with_reviewer=False)
    agreement = draft_agreement(reg, "Lodestar", 3000000, 2500, "2027-03-31")
    m1 = add_milestone(reg, agreement["id"], 1, "Ship Candidate", "GOLD",
                       3000000, 0, DEFAULT_CRITERIA_2)
    activate(reg, agreement["id"])
    return reg, agreement["id"], m1


def test_gold_stability_bar_rejects_a_hundredth_of_a_point_short(api):
    """PRD §3.4: "A `GOLD` milestone is the ship candidate and admits no slack
    whatsoever: 100.00 percent features, 99.50 percent crash-free sessions, 100.00
    percent content, and zero known blockers." PRD §2.5 adds that these figures are
    "compared exactly, with no tolerance or epsilon."

    Design: Difficulty/boundary_precision_check/gold_crash_free_threshold_at_99_49_versus_exactly_99_50
    """
    reg, _agreement_id, m1 = _lodestar(api)

    response = api.create_build(
        f.build_payload(m1["id"], 1, 100.00, 99.49, 100.00, 0), reg.dev
    )
    validate_error(response, ERR_BUILD_GATE_NOT_MET, 422)

    milestone = validate_success(api.get_milestone(m1["id"], reg.finance))
    assert_fields_equal(
        milestone, {"status": "IN_DEVELOPMENT", "latest_build_number": 0}, "milestone"
    )
    rows, meta = validate_paginated(api.list_milestone_builds(m1["id"], reg.finance))
    assert rows == [] and meta["total_count"] == 0


def test_gold_stability_bar_admits_exactly_the_threshold(api):
    """PRD §3.4: "The build then passes only if all four conditions hold
    simultaneously, and every comparison is inclusive: ... `crash_free_sessions_pct`
    is at least the profile's crash-free figure — the raw one, never adjusted".

    Design: Difficulty/boundary_precision_check/gold_crash_free_threshold_at_99_49_versus_exactly_99_50
    """
    reg, _agreement_id, m1 = _lodestar(api)

    build = validate_success(
        api.create_build(f.build_payload(m1["id"], 1, 100.00, 99.50, 100.00, 0), reg.dev),
        201,
    )
    assert build["gate_state"] == "PASSED"
    assert build["build_number"] == 1
    assert_pct_equals(build["readiness_score"], 99.83, "readiness_score")

    milestone = validate_success(api.get_milestone(m1["id"], reg.finance))
    assert_fields_equal(
        milestone, {"status": "UNDER_REVIEW", "latest_build_number": 1}, "milestone"
    )


def _emberfall_in_expired_cure(api):
    """One ALPHA milestone parked in a cure round whose deadline the clock has passed."""
    scenario = setup_single_alpha(
        api, title="Emberfall II", advance_total_cents=3400000,
        contractor_budget_cents=0, acceptance_criteria=DEFAULT_CRITERIA_3,
    )
    reg = scenario.reg
    build1 = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING)
    review = record_conditional_review(reg, build1["id"], [0], 14)
    assert review["cure_deadline_at"] == "2026-08-15T00:00:00.000Z"
    validate_success(api.set_clock("2026-08-20T00:00:00.000Z", reg.admin))
    return scenario, build1


def test_gate_failure_is_reported_ahead_of_the_expired_cure_window(api):
    """PRD §2.10 rule 46: "The build clears its acceptance gate, on build submission
    — `ERR_BUILD_GATE_NOT_MET`. This outranks the cure-window check at 51, so a
    build that both misses its gate and arrives after the cure deadline reports the
    gate failure."

    Design: Difficulty/priority_pair_validation_conflict/cp2_build_gate_not_met_outranks_cure_window_expired
    """
    scenario, build1 = _emberfall_in_expired_cure(api)
    reg = scenario.reg

    response = api.create_build(
        f.build_payload(scenario.m1["id"], 2, 40.00, 96.00, 55.00, 5, [0]), reg.dev
    )
    validate_error(response, ERR_BUILD_GATE_NOT_MET, 422)

    milestone = validate_success(api.get_milestone(scenario.m1["id"], reg.dev))
    assert_fields_equal(
        milestone,
        {
            "status": "CURE_PENDING",
            "latest_build_number": 1,
            "cure_deadline_at": "2026-08-15T00:00:00.000Z",
            "open_condition_indexes": [0],
        },
        "milestone",
    )
    rows, meta = validate_paginated(api.list_milestone_builds(scenario.m1["id"], reg.dev))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == build1["id"] and rows[0]["gate_state"] == "PASSED"


def test_a_gate_clearing_build_after_the_deadline_reports_the_expiry(api):
    """PRD §3.4: "Finally the cure window itself must still be open: if the
    milestone is `CURE_PENDING` and the logical clock has moved strictly past its
    `cure_deadline_at`, the submission is `ERR_CURE_WINDOW_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/cp2_build_gate_not_met_outranks_cure_window_expired
    """
    scenario, build1 = _emberfall_in_expired_cure(api)
    reg = scenario.reg

    response = api.create_build(
        f.build_payload(scenario.m1["id"], 2, 75.00, 96.00, 55.00, 5, [0]), reg.dev
    )
    validate_error(response, ERR_CURE_WINDOW_EXPIRED, 409)

    milestone = validate_success(api.get_milestone(scenario.m1["id"], reg.dev))
    assert_fields_equal(
        milestone,
        {"status": "CURE_PENDING", "latest_build_number": 1,
         "open_condition_indexes": [0]},
        "milestone",
    )
    rows, meta = validate_paginated(api.list_milestone_builds(scenario.m1["id"], reg.dev))
    assert meta["total_count"] == 1 and rows[0]["id"] == build1["id"]
