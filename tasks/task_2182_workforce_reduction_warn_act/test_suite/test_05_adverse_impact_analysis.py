"""Adverse-impact testing: the pool, the focal class, the two statistics."""

from test_helpers import (
    ALICE,
    BEN,
    CARLA,
    HIRO,
    TEST_USERS,
    USER_IDS,
    ApiErrorId,
    assert_analysis,
    clear_analysis,
    create_locked_plan,
    decide,
    decide_many,
    make_counsel_headers,
    propose_batch,
    read_analysis,
    read_plan,
    read_selection,
    rescind,
    run_analysis,
    setup_eight_person_analysis_pool,
    setup_site_with_roster,
    validate_error,
    validate_paginated,
    validate_success,
)

LEAD = TEST_USERS["lead_headers"]
COUNSEL = TEST_USERS["counsel_headers"]


def test_impact_ratio_flags_the_pool_that_standard_deviation_clears(api):
    """PRD 3.5: "Under `IMPACT_RATIO`, the `impact_ratio` is the focal rate
    divided by the reference rate, rounded half up to four decimal places,
    `standard_deviations` is null, and the analysis is flagged when the impact
    ratio is strictly below the four-fifths threshold of 0.80 and small-sample
    suppression is not in force."
    PRD 3.5: "`standard_deviations` is 0 when the standard deviation is 0, and
    otherwise the expected focal selections less the actual focal selections,
    divided by the standard deviation, rounded half up to four decimal places.
    The analysis is flagged when `standard_deviations` is at least the threshold
    of 2.0 and small-sample suppression is not in force; that comparison is
    inclusive, so exactly 2.0000 is flagged."
    PRD 3.5: "The `focal_class_code` is the class with the smallest such rate,
    with ties broken by class code ascending so that `CLASS_A` precedes
    `CLASS_B` which precedes `CLASS_C`."

    Design: Corner/calculations/adverse_impact_ratio_flags_where_standard_deviation_does_not
    """
    scn = setup_eight_person_analysis_pool()

    ratio = run_analysis(scn["plan"]["id"], "IMPACT_RATIO")
    assert_analysis(ratio)
    assert ratio["focal_class_code"] == "CLASS_A"
    assert ratio["pool_count"] == 8
    assert ratio["selected_count"] == 4
    assert ratio["focal_pool_count"] == 3
    assert ratio["focal_selected_count"] == 1
    assert ratio["focal_rate"] == 0.3333
    assert ratio["reference_rate"] == 0.6000
    assert ratio["shortfall_count"] == 1
    assert ratio["small_sample_suppressed"] is False
    assert ratio["standard_deviations"] is None
    assert ratio["impact_ratio"] < 0.80, "the four-fifths rule is breached"
    assert ratio["status"] == "FLAGGED"

    deviations = run_analysis(scn["plan"]["id"], "STANDARD_DEVIATION")
    assert deviations["impact_ratio"] is None
    assert deviations["standard_deviations"] == 0.6831
    assert deviations["status"] == "COMPUTED", (
        "the same pool clears the two-standard-deviation threshold"
    )
    assert read_analysis(ratio["id"])["status"] == "SUPERSEDED"


def test_rescinded_selections_leave_the_analysis_pool_entirely(api):
    """PRD 3.5: "The pool is the plan's own selections in status `PROPOSED`,
    `SELECTED`, `EXEMPTED` or `SEPARATED`; rescinded selections are excluded, and
    an employee who holds no selection never enters the pool even when they sit
    in the same decisional unit."
    PRD 3.5: "The `focal_rate` is the focal selected count divided by the focal
    pooled count, rounded half up to four decimal places. The `reference_rate` is
    the pool's selected count less the focal selected count, divided by the pool
    count less the focal pooled count, again rounded half up to four decimal
    places."
    PRD 3.5: "The `small_sample_suppressed` flag is true when the focal pooled
    count is below 3 — a class of one or two people cannot carry a statistical
    finding, and the flag suppresses flagging no matter what the statistic says."

    Design: Corner/calculations/adverse_impact_pool_excludes_rescinded_selections
    """
    from test_helpers import DAN

    _site, employees = setup_site_with_roster((ALICE, BEN, CARLA, DAN), "TX")
    plan = create_locked_plan()
    batch = propose_batch(
        plan["id"],
        [
            employees[0]["id"],
            employees[2]["id"],
            employees[3]["id"],
            employees[1]["id"],
        ],
    )
    s_alice, s_carla, s_dan, s_ben = batch["selection_ids"]
    decide_many(plan["id"], [s_alice, s_carla, s_dan], "SELECT")
    decide(s_ben, "EXEMPT", "Retained for critical skills.")
    rescind(s_dan, "Redeployed to a retained requisition.")

    analysis = run_analysis(plan["id"], "IMPACT_RATIO")
    assert analysis["pool_count"] == 3
    assert analysis["selected_count"] == 2
    assert analysis["focal_class_code"] == "CLASS_A"
    assert analysis["focal_pool_count"] == 2
    assert analysis["focal_selected_count"] == 1
    assert analysis["reference_rate"] == 1.0000
    assert analysis["impact_ratio"] == 0.5000
    assert analysis["shortfall_count"] == 1
    assert analysis["small_sample_suppressed"] is True
    assert analysis["status"] == "COMPUTED"

    assert read_selection(s_dan)["status"] == "RESCINDED"
    assert read_plan(plan["id"])["pool_count"] == 3


def test_a_focal_class_of_one_suppresses_the_four_fifths_flag(api):
    """PRD 3.5: "The `small_sample_suppressed` flag is true when the focal pooled
    count is below 3 — a class of one or two people cannot carry a statistical
    finding, and the flag suppresses flagging no matter what the statistic says."
    PRD 3.5: "Under `IMPACT_RATIO`, the `impact_ratio` is the focal rate divided
    by the reference rate, rounded half up to four decimal places,
    `standard_deviations` is null, and the analysis is flagged when the impact
    ratio is strictly below the four-fifths threshold of 0.80 and small-sample
    suppression is not in force."

    Design: Corner/calculations/small_focal_class_suppresses_the_four_fifths_flag
    """
    _site, employees = setup_site_with_roster((ALICE, BEN, CARLA), "TX")
    plan = create_locked_plan()
    batch = propose_batch(plan["id"], [e["id"] for e in employees])
    decide(batch["selection_ids"][0], "SELECT")

    analysis = run_analysis(plan["id"], "IMPACT_RATIO")
    assert analysis["focal_class_code"] == "CLASS_B"
    assert analysis["focal_pool_count"] == 1
    assert analysis["focal_selected_count"] == 0
    assert analysis["reference_rate"] == 0.5000
    assert analysis["impact_ratio"] == 0.0000
    assert analysis["shortfall_count"] == 1
    assert analysis["small_sample_suppressed"] is True
    assert analysis["status"] == "COMPUTED", (
        "suppression holds the row at COMPUTED despite a ratio far below 0.80"
    )


def test_clearing_an_already_cleared_analysis_is_refused(api):
    """PRD 3.5: "Clearing an analysis (`COMPUTED → CLEARED` or `FLAGGED →
    CLEARED`) requires a `justification` that is supplied and non-empty, records
    that business-necessity narrative on the row along with `cleared_by_user_id`,
    and increments the analysis's `version` by 1. Attempting to clear a row that
    is already `CLEARED`, or one that has become `SUPERSEDED` or `STALE`, is
    refused with `ERR_INVALID_ANALYSIS_STATE`."

    Design: Corner/errors/error_clearing_an_already_cleared_analysis_is_rejected
    """
    _site, employees = setup_site_with_roster((ALICE, CARLA), "TX")
    plan = create_locked_plan()
    batch = propose_batch(plan["id"], [employees[0]["id"], employees[1]["id"]])
    decide(batch["selection_ids"][0], "SELECT")

    analysis = run_analysis(plan["id"], "IMPACT_RATIO")
    clear_analysis(analysis["id"], "Documented business necessity.")

    response = api.clear_analysis(
        analysis["id"],
        {"justification": "Second clearance attempt."},
        make_counsel_headers(USER_IDS["COUNSEL_2"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ANALYSIS_STATE.value)
    assert response.status_code == 409

    after = read_analysis(analysis["id"])
    assert after["status"] == "CLEARED"
    assert after["cleared_by_user_id"] == USER_IDS["COUNSEL"]
    assert after["justification"] == "Documented business necessity."


def test_a_second_analysis_on_a_stale_plan_version_is_rejected(api):
    """PRD 2.8: "Creating an adverse-impact analysis at
    `POST /adverse-impact-analyses` requires a non-optional
    `expected_plan_version` field in the request body, carrying the `version` of
    the `ReductionPlan` the client last observed. If that value does not equal
    the plan's current `version`, the request is rejected with
    `ERR_STALE_PLAN_VERSION` and HTTP status 412."
    PRD 3.5: "Creating a new analysis supersedes every earlier analysis of the
    same plan, moving each of them into `SUPERSEDED` from whichever of
    `COMPUTED`, `FLAGGED` or `CLEARED` it held, incrementing each superseded
    row's `version` by 1, and incrementing the plan's `version` by 1 as well."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_rejects_a_second_analysis
    """
    _site, employees = setup_site_with_roster((ALICE, CARLA), "TX")
    plan = create_locked_plan()
    batch = propose_batch(plan["id"], [e["id"] for e in employees])
    decide_many(plan["id"], batch["selection_ids"], "SELECT")

    plan_v1 = read_plan(plan["id"])["version"]
    first = validate_success(
        api.create_analysis(
            {
                "plan_id": plan["id"],
                "method": "IMPACT_RATIO",
                "expected_plan_version": plan_v1,
            },
            COUNSEL,
        ),
        201,
    )

    stale = api.create_analysis(
        {
            "plan_id": plan["id"],
            "method": "STANDARD_DEVIATION",
            "expected_plan_version": plan_v1,
        },
        COUNSEL,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PLAN_VERSION.value)
    assert stale.status_code == 412

    plan_v2 = read_plan(plan["id"])["version"]
    assert plan_v2 == plan_v1 + 1, "creating the first analysis bumped the plan"

    second = validate_success(
        api.create_analysis(
            {
                "plan_id": plan["id"],
                "method": "STANDARD_DEVIATION",
                "expected_plan_version": plan_v2,
            },
            COUNSEL,
        ),
        201,
    )
    assert read_analysis(first["id"])["status"] == "SUPERSEDED"
    assert read_analysis(second["id"])["status"] == "COMPUTED"

    rows, _meta = validate_paginated(
        api.list_analyses(COUNSEL, params={"plan_id": plan["id"]})
    )
    assert len(rows) == 2


class TestUnanalysablePools:
    """Zero-count edges are refused rather than divided through."""

    def test_a_pool_with_nobody_selected_is_refused(self, api):
        """PRD 3.5: "The analysis records `pool_count` as the size of that pool
        and `selected_count` as the number of pooled rows in `SELECTED` or
        `SEPARATED` status. If the pool is empty, or nobody in it is selected,
        the request is refused with `ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA`."

        Design: Difficulty/boundary_precision_check/impact_analysis_zero_selected_and_empty_reference_group_are_rejected
        """
        _site, employees = setup_site_with_roster((ALICE, BEN, HIRO), "TX")
        plan = create_locked_plan()
        propose_batch(plan["id"], [e["id"] for e in employees])

        plan_version = read_plan(plan["id"])["version"]
        response = api.create_analysis(
            {
                "plan_id": plan["id"],
                "method": "IMPACT_RATIO",
                "expected_plan_version": plan_version,
            },
            COUNSEL,
        )
        validate_error(response, ApiErrorId.ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA.value)
        assert response.status_code == 422

        rows, _meta = validate_paginated(
            api.list_analyses(COUNSEL, params={"plan_id": plan["id"]})
        )
        assert rows == []
        assert read_plan(plan["id"])["pool_count"] == 3

    def test_a_pool_whose_only_class_is_the_focal_class_is_refused(self, api):
        """PRD 3.5: "If removing the focal class leaves no reference group at all
        — that is, the pool count and the focal pooled count are equal — the
        request is refused with `ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA`."

        Design: Difficulty/boundary_precision_check/impact_analysis_zero_selected_and_empty_reference_group_are_rejected
        """
        _site, employees = setup_site_with_roster((ALICE, BEN, HIRO), "TX")
        plan = create_locked_plan()
        batch = propose_batch(plan["id"], [e["id"] for e in employees])
        decide(batch["selection_ids"][0], "SELECT")

        plan_version = read_plan(plan["id"])["version"]
        response = api.create_analysis(
            {
                "plan_id": plan["id"],
                "method": "STANDARD_DEVIATION",
                "expected_plan_version": plan_version,
            },
            COUNSEL,
        )
        validate_error(response, ApiErrorId.ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA.value)
        assert response.status_code == 422

        rows, _meta = validate_paginated(
            api.list_analyses(COUNSEL, params={"plan_id": plan["id"]})
        )
        assert rows == []
        plan = read_plan(plan["id"])
        assert plan["pool_count"] == 3
        assert plan["selected_count"] == 1
