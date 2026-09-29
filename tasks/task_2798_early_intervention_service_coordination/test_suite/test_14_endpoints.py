"""
Endpoint surfaces that only a multi-row scenario reaches: the computed caseload
read at a posture boundary, the two branches of the notify-LEA action, and the
assessment create/read/list round trip with its filters and pagination.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ALL_DOMAINS,
    EVALUATOR_HEADERS,
    INTAKE_CLOCK,
    POST_EVALUATION_CLOCK,
    ApiErrorId,
    assert_caseload_summary,
    assert_utilization_ratio,
    assign_coordinator,
    build_assigned,
    build_transition_planning_case,
    complete_assessment,
    create_child,
    create_coordinator,
    create_referral,
    determine_eligibility,
    factories,
    read_caseload_summary,
    read_coordinator,
    read_service_line,
    schedule_assessment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COUNTY = "CNT_B"
CEILING_POINTS = 3.20
DETERMINATION_DATE = "2026-03-20"
SECOND_CHILD = {
    "first_name": "Leo",
    "last_name": "Vance",
    "date_of_birth": "2024-08-01",
}
SECOND_REFERRAL = {
    "primary_referral_source": "PARENT",
    "presenting_concern": (
        "Parent reports no two-word combinations and limited joint attention"
    ),
}


def _two_pre_plan_cases_on_one_coordinator(api):
    """
    Two assigned pre-plan cases at 1.50 points each against a 3.20 ceiling, with
    the first case's assessments completed but no determination recorded.
    """
    set_clock(api, INTAKE_CLOCK)
    coordinator_id = create_coordinator(
        api,
        full_name="Priya Raman",
        county_code=COUNTY,
        max_weighted_caseload_points=CEILING_POINTS,
    )
    first_child = create_child(api, county_code=COUNTY)
    first_referral = create_referral(api, first_child, county_code=COUNTY)
    assign_coordinator(api, first_referral, coordinator_id)

    second_child = create_child(api, county_code=COUNTY, **SECOND_CHILD)
    second_referral = create_referral(
        api, second_child, county_code=COUNTY, **SECOND_REFERRAL
    )
    assign_coordinator(api, second_referral, coordinator_id)

    evaluation_id = schedule_assessment(api, first_referral)
    family_id = schedule_assessment(
        api,
        first_referral,
        assessment_type="FAMILY_ASSESSMENT",
        scheduled_date="2026-03-19",
    )
    set_clock(api, POST_EVALUATION_CLOCK)
    complete_assessment(
        api, evaluation_id, "2026-03-18", eligibility_recommendation="NOT_ELIGIBLE"
    )
    complete_assessment(
        api, family_id, "2026-03-19", eligibility_recommendation="NOT_ELIGIBLE"
    )
    return coordinator_id, first_referral


class TestCaseloadSummaryComputedRead:

    def test_posture_moves_from_near_cap_to_open_on_a_not_eligible_drop(self, api):
        """
        Two pre-plan cases at 3.00 of a 3.20 ceiling report NEAR_CAP without ever
        reaching AT_CAP, and determining one case ineligible drops it from both the
        count and the weighted total in the same request.

        PRD 3.2: "A case in `NOT_ELIGIBLE` or `EXITED` weighs exactly 0.00 and
        drops out of every caseload total."
        PRD 3.2: "A coordinator's `active_case_count` is the number of referrals
        assigned to them whose status is neither `NOT_ELIGIBLE` nor `EXITED`, and
        their `weighted_caseload_points` is the sum of `case_weight_points` over
        exactly that same set of referrals, held to two decimal places rounded
        half up."
        PRD 3.2: "A computed caseload read exposes those numbers together with the
        coordinator's own identifier as `coordinator_id`, the ceiling as
        `max_weighted_caseload_points`, a `headroom_points` figure giving the
        ceiling minus the current weighted points to two decimal places, and a
        `caseload_posture` verdict."
        PRD 3.2: "The posture is `OVER` when weighted points exceed the ceiling,
        `AT_CAP` when they equal it exactly, `NEAR_CAP` when neither of those
        holds but the utilization ratio is at least 0.9000, and `OPEN` otherwise —
        the tests are applied in that order, so an over-cap coordinator never
        reports `NEAR_CAP`."

        Design: Corner/endpoints/caseload_summary_computed_read_tracks_posture_across_a_not_eligible_drop
        """
        coordinator_id, first_referral = _two_pre_plan_cases_on_one_coordinator(api)

        near_cap = read_caseload_summary(api, coordinator_id)
        assert_caseload_summary(
            near_cap,
            coordinator_id=coordinator_id,
            active_case_count=2,
            weighted_caseload_points=3.00,
            max_weighted_caseload_points=CEILING_POINTS,
            utilization_ratio=0.9375,
            caseload_posture="NEAR_CAP",
            headroom_points=0.20,
        )

        determined = determine_eligibility(
            api,
            first_referral,
            is_eligible=False,
            determination_date=DETERMINATION_DATE,
        )
        assert determined["status"] == "NOT_ELIGIBLE"
        assert float(determined["case_weight_points"]) == 0.00

        reopened = read_caseload_summary(api, coordinator_id)
        assert_caseload_summary(
            reopened,
            active_case_count=1,
            weighted_caseload_points=1.50,
            utilization_ratio=0.4688,
            caseload_posture="OPEN",
            headroom_points=1.70,
        )

        coordinator = read_coordinator(api, coordinator_id)
        assert float(coordinator["weighted_caseload_points"]) == 1.50
        assert coordinator["active_case_count"] == 1
        assert_utilization_ratio(coordinator["utilization_ratio"], 0.4688)


# ─── The notify-LEA action, both branches ─────────────────────────────

NOTIFICATION_DATE = "2026-04-20"
LEAD_DAYS = 265
FIRST_LEA_CODE = "LEA_014"
SECOND_LEA_CODE = "LEA_099"
OPT_OUT_SIGNED_DATE = "2026-04-18"
EXIT_DATE = "2026-04-20"
EXIT_RATINGS = {
    "exit_rating_social": 4,
    "exit_rating_knowledge": 5,
    "exit_rating_needs": 6,
}
PROGRESS_CATEGORY_FIELDS = (
    "progress_category_social",
    "progress_category_knowledge",
    "progress_category_needs",
)


class TestNotifyLeaNotifiedBranch:

    def test_a_265_day_lead_is_timely_and_the_action_is_single_shot(self, api):
        """
        A 265-day lead sits inside the timely band rather than the early one, and a
        second notification on the now-notified plan is refused without re-grading.

        PRD 3.9: "When `family_opt_out` is false the plan moves `DRAFT →
        NOTIFIED`."
        PRD 3.9: "It also requires `lea_code` to be present and
        `opt_out_signed_date` to be absent. On success `lea_code`,
        `notification_date`, `notification_lead_days` and
        `notification_compliance` are all stored."
        PRD 3.9: "`notification_lead_days` is the whole number of days from
        `notification_date` to the child's `third_birthday_date`."
        PRD 3.9: "Given a non-negative lead, the verdict follows in this order: an
        opted-out plan is `WAIVED_OPT_OUT`; otherwise a lead of more than 270 days
        is `EARLY`; otherwise a lead of at least 90 days is `TIMELY`; otherwise the
        notification is `LATE`."
        PRD 3.9: "The transition plan must be in `DRAFT`, or the request is refused
        with `ERR_TRANSITION_PLAN_STATE_INVALID`."

        Design: Corner/endpoints/notify_lea_action_grades_a_265_day_lead_as_timely_and_is_not_repeatable
        """
        case = build_transition_planning_case(api)

        notified = validate_success(
            api.notify_lea(
                case.transition_plan_id,
                factories.notify_lea_payload(
                    NOTIFICATION_DATE, lea_code=FIRST_LEA_CODE
                ),
                case.coordinator_headers,
            ),
            200,
        )
        assert notified["status"] == "NOTIFIED"
        assert notified["lea_code"] == FIRST_LEA_CODE
        assert notified["notification_date"] == NOTIFICATION_DATE
        assert notified["family_opt_out"] is False
        assert notified["opt_out_signed_date"] is None
        assert notified["notification_lead_days"] == LEAD_DAYS
        assert notified["notification_compliance"] == "TIMELY"

        repeat = api.notify_lea(
            case.transition_plan_id,
            factories.notify_lea_payload(NOTIFICATION_DATE, lea_code=SECOND_LEA_CODE),
            case.coordinator_headers,
        )
        validate_error(
            repeat, ApiErrorId.TRANSITION_PLAN_STATE_INVALID.value, 409
        )

        unchanged = validate_success(
            api.get_transition_plan(case.transition_plan_id, ADMIN_HEADERS), 200
        )
        assert unchanged["status"] == "NOTIFIED"
        assert unchanged["lea_code"] == FIRST_LEA_CODE
        assert unchanged["notification_date"] == NOTIFICATION_DATE
        assert unchanged["notification_lead_days"] == LEAD_DAYS


class TestNotifyLeaOptOutBranch:

    def test_the_opt_out_branch_waives_the_verdict_and_unlocks_the_exit(self, api):
        """
        Opting out stores the signed date instead of a district code, keeps the
        computed lead, and satisfies the age-three exit gate.

        PRD 3.9: "When `family_opt_out` is true the plan moves `DRAFT → OPT_OUT`
        instead. That branch requires `opt_out_signed_date` to be present and
        `lea_code` to be absent — a family that declined notification cannot also
        have a district recorded as notified. `notification_compliance` is set to
        `WAIVED_OPT_OUT`, and `notification_lead_days` is still computed and stored
        so that the audit record shows how close to the deadline the family's
        decision landed."
        PRD 3.9: "All three exit ratings are required and each must be an integer
        from 1 through 7, and when the `exit_reason` is `REACHED_AGE_THREE` the
        case must additionally carry a transition plan on its `ACTIVE` plan whose
        status is `NOTIFIED` or `OPT_OUT` — a child cannot age out of the program
        without the district having been notified or the family having formally
        declined."
        PRD 3.9: "If a case received services for fewer than 180 days, no
        meaningful comparison is possible and all three of
        `progress_category_social`, `progress_category_knowledge` and
        `progress_category_needs` are recorded as `NOT_COMPARABLE`, whatever the
        ratings say."
        PRD 3.9: "And finally the case's own derived state is cleared:
        `case_weight_points` is set to 0, the coordinator's
        `weighted_caseload_points`, `active_case_count` and `utilization_ratio` are
        recomputed without it, `service_gap_flag` is set to false, and
        `monthly_contact_status` returns to `NOT_APPLICABLE`."

        Design: Corner/endpoints/notify_lea_opt_out_waives_the_deadline_and_unlocks_the_age_three_exit
        """
        case = build_transition_planning_case(api)

        opted_out = validate_success(
            api.notify_lea(
                case.transition_plan_id,
                factories.notify_lea_payload(
                    NOTIFICATION_DATE,
                    family_opt_out=True,
                    opt_out_signed_date=OPT_OUT_SIGNED_DATE,
                ),
                case.coordinator_headers,
            ),
            200,
        )
        assert opted_out["status"] == "OPT_OUT"
        assert opted_out["family_opt_out"] is True
        assert opted_out["opt_out_signed_date"] == OPT_OUT_SIGNED_DATE
        assert opted_out["lea_code"] is None
        assert opted_out["notification_lead_days"] == LEAD_DAYS
        assert opted_out["notification_compliance"] == "WAIVED_OPT_OUT"

        exited = validate_success(
            api.exit_referral(
                case.referral_id,
                factories.exit_payload(
                    EXIT_DATE, exit_reason="REACHED_AGE_THREE", **EXIT_RATINGS
                ),
                case.coordinator_headers,
            ),
            200,
        )
        assert exited["status"] == "EXITED"
        assert exited["exit_reason"] == "REACHED_AGE_THREE"
        assert exited["service_duration_days"] == 31
        for field in PROGRESS_CATEGORY_FIELDS:
            assert exited[field] == "NOT_COMPARABLE"

        assert read_service_line(api, case.line_id)["status"] == "DISCONTINUED"
        coordinator = read_coordinator(api, case.coordinator_id)
        assert float(coordinator["weighted_caseload_points"]) == 0.00


# ─── Assessment create, read and filtered list ────────────────────────

EVALUATION_DATE = "2026-03-10"
FAMILY_DATE = "2026-03-19"


class TestAssessmentRoundTrip:

    def test_create_read_and_filtered_list_round_trip(self, api):
        """
        Two assessments of different types on one case round-trip through the read
        endpoint and are then separated by the type filter and paged by limit.

        PRD 3.3: "A new record is created with `status` `SCHEDULED`, and the acting
        evaluator's identifier is captured as `evaluator_user_id`."
        PRD 2.4: "`version` is an integer that starts at 1 when the row is created
        and increments by exactly 1 on every mutation of that row — including
        mutations that arrive as the secondary effect of a write aimed at a
        different resource."
        PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` is true
        when rows remain beyond the current page."
        PRD 2.3: "Assessment listing filters on `referral_id`, `assessment_type`
        and `status`."

        Design: Corner/endpoints/assessment_crud_create_read_and_filtered_list_round_trip
        """
        case = build_assigned(api)

        evaluation = validate_success(
            api.create_assessment(
                factories.assessment_payload(
                    case.referral_id,
                    scheduled_date=EVALUATION_DATE,
                    domains_assessed=list(ALL_DOMAINS),
                ),
                EVALUATOR_HEADERS,
            ),
            201,
        )
        family = validate_success(
            api.create_assessment(
                factories.assessment_payload(
                    case.referral_id,
                    assessment_type="FAMILY_ASSESSMENT",
                    scheduled_date=FAMILY_DATE,
                ),
                EVALUATOR_HEADERS,
            ),
            201,
        )
        for created in (evaluation, family):
            assert created["status"] == "SCHEDULED"
            assert created["completion_date"] is None
            assert created["eligibility_recommendation"] is None
            assert created["version"] == 1

        read_evaluation = validate_success(
            api.get_assessment(evaluation["id"], EVALUATOR_HEADERS), 200
        )
        assert read_evaluation["referral_id"] == case.referral_id
        assert read_evaluation["assessment_type"] == "INITIAL_EVALUATION"
        assert read_evaluation["scheduled_date"] == EVALUATION_DATE
        assert read_evaluation["setting_code"] == "HOME"
        assert read_evaluation["domains_assessed"] == list(ALL_DOMAINS)

        read_family = validate_success(
            api.get_assessment(family["id"], EVALUATOR_HEADERS), 200
        )
        assert read_family["assessment_type"] == "FAMILY_ASSESSMENT"
        assert read_family["domains_assessed"] is None

        rows, meta = validate_paginated(
            api.list_assessments(
                EVALUATOR_HEADERS, {"referral_id": case.referral_id}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {evaluation["id"], family["id"]}

        filtered_rows, filtered_meta = validate_paginated(
            api.list_assessments(
                EVALUATOR_HEADERS,
                {
                    "referral_id": case.referral_id,
                    "assessment_type": "FAMILY_ASSESSMENT",
                },
            )
        )
        assert filtered_meta["total_count"] == 1
        assert filtered_rows[0]["id"] == family["id"]

        paged_rows, paged_meta = validate_paginated(
            api.list_assessments(
                EVALUATOR_HEADERS,
                {"referral_id": case.referral_id, "limit": 1, "offset": 0},
            )
        )
        assert len(paged_rows) == 1
        assert paged_meta["total_count"] == 2
        assert paged_meta["has_more"] is True
