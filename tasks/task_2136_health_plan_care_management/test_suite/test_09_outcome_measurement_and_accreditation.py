"""Outcome measurement, the two ROI methods and the accreditation file."""
import pytest

from test_helpers import (
    ApiErrorId, PROGRAM_ADMIN, UTILIZATION_ANALYST, activate,
    assert_compliance_rate, assert_roi_measurement, assert_roi_ratio,
    complete_intervention, create_member, enroll, enrollment_version,
    plan_intervention, read_enrollment, set_clock, setup_active_care_plan,
    setup_program_and_managers, stratify, validate_error, validate_paginated,
    validate_success,
)

ROI_EVENTS = [
    {"event_type": "INPATIENT_ADMISSION", "occurred_at": "2025-09-15T00:00:00Z",
     "facility_name": "Bay General", "episode_cost_cents": 1800000,
     "adjudication_status": "CLOSED"},
    {"event_type": "ED_VISIT", "occurred_at": "2026-01-20T00:00:00Z",
     "facility_name": "Bay General", "episode_cost_cents": 240006,
     "adjudication_status": "CLOSED"},
    {"event_type": "ED_VISIT", "occurred_at": "2026-03-05T00:00:00Z",
     "facility_name": "Bay General", "episode_cost_cents": 180000,
     "adjudication_status": "OPEN"},
    {"event_type": "ED_VISIT", "occurred_at": "2026-06-10T00:00:00Z",
     "facility_name": "Bay General", "episode_cost_cents": 220000,
     "adjudication_status": "CLOSED"},
]


def _roi_scenario(external_member_id, chronic_condition_count, events,
                  min_risk_tier, program_name):
    """Activate on 2026-05-01, deliver three 20-minute interventions, then move
    the clock to 2026-08-01 so exactly three whole months have elapsed."""
    set_clock("2026-05-01T00:00:00Z")
    scenario = setup_active_care_plan(
        program_overrides={"name": program_name, "min_risk_tier": min_risk_tier,
                           "stratification_variant": "CONCURRENT",
                           "required_credential_levels": ["RN"],
                           "staff_minute_budget": 100000,
                           "hourly_cost_cents": 9050,
                           "cohort_benchmark_pmpm_cents": 120000,
                           "care_plan_review_interval_days": 90,
                           "toc_outreach_hours": 48, "referral_loop_days": 30},
        member_overrides={"external_member_id": external_member_id,
                          "full_name": "Luis Ortega", "birth_date": "1952-02-09",
                          "chronic_condition_count": chronic_condition_count},
        events=events,
        goal_specs=[{"domain": "CLINICAL",
                     "description": "Stabilize heart failure",
                     "target_date": "2026-11-01"}],
        plan_title="Complex care plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    scenario["interventions"] = [
        plan_intervention(scenario["goal"]["id"], care_manager_id,
                          modality=modality, staff_minutes=20)
        for modality in ("PHONE", "EDUCATION", "MEDICATION_REVIEW")
    ]
    for intervention in scenario["interventions"]:
        complete_intervention(intervention["id"], care_manager_id)
    set_clock("2026-08-01T00:00:00Z")
    return scenario


def test_pre_post_method_trends_the_members_own_baseline(api):
    """PRD §3.9: "Under `PRE_POST`, the baseline window is the 12 whole calendar
    months immediately preceding the month in which `activated_at` falls, ending
    where that month begins. Sum `episode_cost_cents` over the member's `CLOSED`
    utilization events inside that baseline window, divide by 12, and round half
    up to whole cents: that is `baseline_pmpm_cents`. Multiply that figure by a
    trend factor of 1.03 and round half up to whole cents to obtain
    `monthly_projected_cost_cents`."
    PRD §3.9: "`gross_savings_cents` is the sum, taken month by month across those
    same months, of `monthly_projected_cost_cents` less that month's actual cost —
    a figure that may legitimately be negative when the member cost more during
    the program than the projection expected."

    Design: Difficulty/dual_variant_calc/roi_method_divergence_on_enrollment_savings
    """
    scenario = _roi_scenario("MBR-2001", 10, ROI_EVENTS, "MODERATE",
                             "Complex Care ROI")
    assert scenario["enrollment"]["risk_tier_at_enrollment"] == "RISING"
    enrollment_id = scenario["enrollment"]["id"]

    data = validate_success(
        api.create_roi_measurement(
            enrollment_id,
            {"method": "PRE_POST",
             "expected_enrollment_version": enrollment_version(enrollment_id)},
            UTILIZATION_ANALYST,
        ),
        201,
    )
    assert_roi_measurement(data)
    assert data["baseline_pmpm_cents"] == 170001
    assert data["monthly_projected_cost_cents"] == 175101
    assert data["intervention_month_count"] == 3
    assert data["projected_cost_cents"] == 525303
    assert data["actual_cost_cents"] == 220000
    assert data["gross_savings_cents"] == 305303
    assert data["program_cost_cents"] == 9051
    assert data["net_savings_cents"] == 296252
    assert_roi_ratio(data["roi_ratio"], 32.73)


def test_matched_cohort_method_scales_the_program_benchmark_by_tier(api):
    """PRD §3.9: "Under `MATCHED_COHORT`, the member's own history is ignored
    entirely: `baseline_pmpm_cents` is recorded as 0, and
    `monthly_projected_cost_cents` is the program's `cohort_benchmark_pmpm_cents`
    multiplied by a risk factor keyed to the enrollment's
    `risk_tier_at_enrollment` — 0.6 for `LOW`, 1.0 for `MODERATE`, 1.4 for
    `RISING` and 2.1 for `HIGH` — rounded half up to whole cents."
    PRD §3.9: "For identical inputs the two methods report different
    `gross_savings_cents`, different `net_savings_cents` and a different
    `roi_ratio`, which is the point of offering both."

    Design: Difficulty/dual_variant_calc/roi_method_divergence_on_enrollment_savings
    """
    scenario = _roi_scenario("MBR-2002", 10, ROI_EVENTS, "MODERATE",
                             "Complex Care ROI")
    enrollment_id = scenario["enrollment"]["id"]

    pre_post = validate_success(
        api.create_roi_measurement(
            enrollment_id,
            {"method": "PRE_POST",
             "expected_enrollment_version": enrollment_version(enrollment_id)},
            UTILIZATION_ANALYST,
        ),
        201,
    )
    cohort = validate_success(
        api.create_roi_measurement(
            enrollment_id,
            {"method": "MATCHED_COHORT",
             "expected_enrollment_version": enrollment_version(enrollment_id)},
            UTILIZATION_ANALYST,
        ),
        201,
    )
    assert cohort["baseline_pmpm_cents"] == 0
    assert cohort["monthly_projected_cost_cents"] == 168000
    assert cohort["intervention_month_count"] == 3
    assert cohort["projected_cost_cents"] == 504000
    assert cohort["gross_savings_cents"] == 284000
    assert cohort["program_cost_cents"] == 9051
    assert cohort["net_savings_cents"] == 274949
    assert_roi_ratio(cohort["roi_ratio"], 30.38)
    assert cohort["gross_savings_cents"] != pre_post["gross_savings_cents"]


def test_intervention_cost_is_rounded_once_per_intervention(api):
    """PRD §2.7: "**rounding happens at the smallest declared unit and the rounded
    values are then summed — never the reverse.** An intervention's cost is
    rounded once when the intervention is created and that stored figure is what
    later aggregations add up; a projected member-month cost is rounded once per
    member-month and the monthly figures are then combined."
    PRD §3.9: "`program_cost_cents` is the sum of the stored `cost_cents` values
    of every intervention in `COMPLETED` status that hangs beneath one of this
    enrollment's care plans, added exactly as each was stored at creation time."

    Design: Difficulty/combinatorial_formula/roi_rounding_order_per_month_and_per_intervention
    """
    scenario = _roi_scenario("MBR-3001", 0, [], "LOW", "Rounding Probe Program")
    assert scenario["interventions"][0]["cost_cents"] == 3017, (
        "20 minutes at 9050 cents an hour rounds half up to 3017 cents"
    )
    enrollment_id = scenario["enrollment"]["id"]

    data = validate_success(
        api.create_roi_measurement(
            enrollment_id,
            {"method": "MATCHED_COHORT",
             "expected_enrollment_version": enrollment_version(enrollment_id)},
            UTILIZATION_ANALYST,
        ),
        201,
    )
    assert data["program_cost_cents"] == 9051, (
        "three interventions rounded individually sum to 9051"
    )
    assert data["program_cost_cents"] != 9050, (
        "summing the 60 raw minutes first and rounding once would give 9050"
    )


def test_monthly_projection_is_rounded_once_per_member_month(api):
    """PRD §3.9: "`monthly_projected_cost_cents` is rounded once, per the
    paragraph above, and that single rounded figure is what every subsequent
    multiplication and subtraction uses. `projected_cost_cents` is
    `monthly_projected_cost_cents` multiplied by `intervention_month_count`."
    PRD §3.9: "Finally `roi_ratio` is `net_savings_cents` divided by
    `program_cost_cents`, rounded half up to two decimal places — and is recorded
    as null when `program_cost_cents` is 0, rather than as an infinity or an
    error."

    Design: Difficulty/combinatorial_formula/roi_rounding_order_per_month_and_per_intervention
    """
    scenario = _roi_scenario("MBR-3002", 0, [], "LOW", "Rounding Probe Program")
    assert scenario["enrollment"]["risk_tier_at_enrollment"] == "LOW"
    enrollment_id = scenario["enrollment"]["id"]

    data = validate_success(
        api.create_roi_measurement(
            enrollment_id,
            {"method": "MATCHED_COHORT",
             "expected_enrollment_version": enrollment_version(enrollment_id)},
            UTILIZATION_ANALYST,
        ),
        201,
    )
    assert data["monthly_projected_cost_cents"] == 72000
    assert data["intervention_month_count"] == 3
    assert data["projected_cost_cents"] == 216000
    assert data["actual_cost_cents"] == 0
    assert data["gross_savings_cents"] == 216000
    assert data["net_savings_cents"] == 206949
    assert_roi_ratio(data["roi_ratio"], 22.86)


def _empty_window_scenario():
    set_clock("2026-08-05T00:00:00Z")
    setting = setup_program_and_managers(
        program_overrides={"name": "Empty Window Program"}, with_reviewer=False
    )
    member = create_member(external_member_id="MBR-1601", full_name="Vic Sole",
                           birth_date="1975-04-18", chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")
    enrollment = enroll(member["id"], setting["program"]["id"],
                        setting["care_manager"]["id"])
    enrollment = activate(enrollment["id"])
    assert enrollment["activated_at"] == "2026-08-05T00:00:00.000Z"
    set_clock("2026-08-25T00:00:00Z")
    return enrollment


def test_measurement_window_with_no_whole_month_is_rejected(api):
    """PRD §3.9: "Only *whole calendar months entirely inside that period* count:
    a month qualifies when its first instant is at or after the period's start and
    its last instant is at or before the period's end, so a partial month at either
    edge is dropped entirely."
    PRD §3.9: "If that count is zero — the enrollment was activated too recently
    for a single whole month to have elapsed — nothing is recorded and the request
    is refused with `ERR_MEASUREMENT_PERIOD_EMPTY`."

    Design: Difficulty/boundary_precision_check/roi_with_zero_whole_months_rejects_empty_measurement_period
    """
    enrollment = _empty_window_scenario()

    response = api.create_roi_measurement(
        enrollment["id"],
        {"method": "PRE_POST",
         "expected_enrollment_version": enrollment["version"]},
        UTILIZATION_ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_MEASUREMENT_PERIOD_EMPTY.value)
    assert response.status_code == 422

    _, meta = validate_paginated(
        api.list_roi_measurements(enrollment["id"], UTILIZATION_ANALYST)
    )
    assert meta["total_count"] == 0


def test_rejected_measurement_leaves_the_enrollment_version_untouched(api):
    """PRD §3.9: "Recording a measurement increases the enrollment's `version` by
    one."
    PRD §2.4: "`version`, an integer that starts at 1 on creation and increases by
    exactly one on every mutation of that record."

    Design: Difficulty/boundary_precision_check/roi_with_zero_whole_months_rejects_empty_measurement_period
    """
    enrollment = _empty_window_scenario()
    version_before = enrollment["version"]

    response = api.create_roi_measurement(
        enrollment["id"],
        {"method": "PRE_POST", "expected_enrollment_version": version_before},
        UTILIZATION_ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_MEASUREMENT_PERIOD_EMPTY.value)

    assert read_enrollment(enrollment["id"])["version"] == version_before, (
        "a rejected measurement records nothing and so mutates nothing"
    )


def test_accreditation_file_samples_only_active_enrollments(api):
    """PRD §3.9: "It evaluates one program's *active* enrollments — those whose
    `enrollment_status` is `ACTIVE` — and nothing else; `PENDING`, `GRADUATED` and
    `DISENROLLED` enrollments are outside the audit sample entirely."
    PRD §3.9: "`TOUCH_OVERDUE` is raised when the enrollment's
    `next_touch_due_at` is not null and is earlier than that instant."
    PRD §3.9: "`compliance_rate_pct` is the share of the sample that is entirely
    clean: subtract `enrollments_with_deficiency_count` from
    `active_enrollment_count`, multiply by 100, divide by `active_enrollment_count`,
    and round half up to one decimal place."

    Design: Corner/calculations/accreditation_file_samples_only_active_enrollments_and_counts_overdue_touches
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Accreditation Program",
                           "care_plan_review_interval_days": 90,
                           "referral_loop_days": 30},
        member_overrides={"external_member_id": "MBR-5601", "full_name": "Aud Ann",
                          "birth_date": "1968-08-28", "chronic_condition_count": 0},
        goal_specs=[{"domain": "CLINICAL", "description": "Audit goal"}],
        plan_title="Audit plan",
    )
    audited = scenario["enrollment"]
    assert audited["next_touch_due_at"] == "2026-08-31T00:00:00.000Z"
    assert scenario["plan"]["next_review_due_at"] == "2026-10-30T00:00:00.000Z"

    pending_member = create_member(external_member_id="MBR-5602",
                                   full_name="Pen Ding", birth_date="1969-09-29",
                                   chronic_condition_count=0)
    stratify(pending_member["id"], "CONCURRENT")
    pending = enroll(pending_member["id"], scenario["program"]["id"],
                     scenario["care_manager"]["id"])

    set_clock("2026-09-30T00:00:00Z")
    data = validate_success(
        api.get_accreditation_file(scenario["program"]["id"], UTILIZATION_ANALYST)
    )

    assert data["program_id"] == scenario["program"]["id"]
    assert data["evaluated_at"] == "2026-09-30T00:00:00.000Z"
    assert data["active_enrollment_count"] == 1
    assert data["enrollments_with_deficiency_count"] == 1
    assert_compliance_rate(data["compliance_rate_pct"], 0.0)
    assert data["deficiency_counts"]["TOUCH_OVERDUE"] == 1
    assert data["deficiency_counts"]["CARE_PLAN_MISSING"] == 0
    assert data["deficiency_counts"]["CARE_PLAN_STALE"] == 0
    assert audited["id"] in data["deficient_enrollment_ids"]
    assert pending["id"] not in data["deficient_enrollment_ids"]


def _measurement_ready_enrollment(external_member_id, with_second_manager=False):
    set_clock("2026-05-01T00:00:00Z")
    setting = setup_program_and_managers(
        program_overrides={"name": "ROI OCC Program"},
        with_reviewer=with_second_manager,
    )
    member = create_member(external_member_id=external_member_id,
                           full_name="Roi Rue", birth_date="1970-01-01",
                           chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")
    enrollment = enroll(member["id"], setting["program"]["id"],
                        setting["care_manager"]["id"])
    enrollment = activate(enrollment["id"])
    setting["enrollment"] = enrollment
    return setting


def test_stale_expected_version_blocks_an_roi_measurement(api):
    """PRD §2.8: "Here too, a `expected_enrollment_version` that does not equal the
    enrollment's current `version` is rejected with `ERR_STALE_ENROLLMENT_VERSION`
    (HTTP 412), and no measurement row is appended."
    PRD §3.9: "Finally `roi_ratio` is `net_savings_cents` divided by
    `program_cost_cents`, rounded half up to two decimal places — and is recorded
    as null when `program_cost_cents` is 0, rather than as an infinity or an
    error."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_roi_measurement_returns_stale_enrollment_version
    """
    setting = _measurement_ready_enrollment("MBR-9701", with_second_manager=True)
    enrollment = setting["enrollment"]
    stale_version = enrollment["version"]

    transferred = validate_success(
        api.transfer_enrollment(
            enrollment["id"],
            {"to_care_manager_id": setting["reviewer"]["id"],
             "expected_enrollment_version": stale_version},
            PROGRAM_ADMIN,
        )
    )
    fresh_version = transferred["version"]
    set_clock("2026-08-01T00:00:00Z")

    stale = api.create_roi_measurement(
        enrollment["id"],
        {"method": "PRE_POST", "expected_enrollment_version": stale_version},
        UTILIZATION_ANALYST,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ENROLLMENT_VERSION.value)
    assert stale.status_code == 412

    data = validate_success(
        api.create_roi_measurement(
            enrollment["id"],
            {"method": "PRE_POST", "expected_enrollment_version": fresh_version},
            UTILIZATION_ANALYST,
        ),
        201,
    )
    assert data["intervention_month_count"] == 3
    assert data["baseline_pmpm_cents"] == 0
    assert data["gross_savings_cents"] == 0
    assert data["program_cost_cents"] == 0
    assert_roi_ratio(data.get("roi_ratio"), None)

    _, meta = validate_paginated(
        api.list_roi_measurements(enrollment["id"], UTILIZATION_ANALYST)
    )
    assert meta["total_count"] == 1


def test_new_measurement_supersedes_the_prior_one_of_the_same_method(api):
    """PRD §3.9: "Recording a new measurement marks every prior measurement for
    the same `enrollment_id` and the same `method` with `superseded` set to true;
    a freshly written measurement always reads `superseded` false. A `PRE_POST`
    measurement never supersedes a `MATCHED_COHORT` one or vice versa."
    PRD §3.9: "Measurements may be listed for an enrollment newest first,
    optionally narrowed by `method`."

    Design: Corner/cross_cutting_complexity_layers/roi_measurement_supersedes_prior_measurement_of_same_method
    """
    setting = _measurement_ready_enrollment("MBR-9801")
    enrollment_id = setting["enrollment"]["id"]
    set_clock("2026-08-01T00:00:00Z")

    first = validate_success(
        api.create_roi_measurement(
            enrollment_id,
            {"method": "PRE_POST",
             "expected_enrollment_version": enrollment_version(enrollment_id)},
            UTILIZATION_ANALYST,
        ),
        201,
    )
    assert first["superseded"] is False

    other_method = validate_success(
        api.create_roi_measurement(
            enrollment_id,
            {"method": "MATCHED_COHORT",
             "expected_enrollment_version": enrollment_version(enrollment_id)},
            UTILIZATION_ANALYST,
        ),
        201,
    )

    second = validate_success(
        api.create_roi_measurement(
            enrollment_id,
            {"method": "PRE_POST",
             "expected_enrollment_version": enrollment_version(enrollment_id)},
            UTILIZATION_ANALYST,
        ),
        201,
    )
    assert second["superseded"] is False

    pre_post_rows, pre_post_meta = validate_paginated(
        api.list_roi_measurements(enrollment_id, UTILIZATION_ANALYST,
                                  params={"method": "PRE_POST"})
    )
    assert pre_post_meta["total_count"] == 2
    by_id = {row["id"]: row for row in pre_post_rows}
    assert by_id[first["id"]]["superseded"] is True
    assert by_id[second["id"]]["superseded"] is False

    cohort_rows, _ = validate_paginated(
        api.list_roi_measurements(enrollment_id, UTILIZATION_ANALYST,
                                  params={"method": "MATCHED_COHORT"})
    )
    assert {row["id"]: row for row in cohort_rows}[
        other_method["id"]
    ]["superseded"] is False
