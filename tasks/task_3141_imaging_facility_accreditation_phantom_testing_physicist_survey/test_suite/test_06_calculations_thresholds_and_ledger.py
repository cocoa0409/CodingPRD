"""Deadline classification, phantom attempt counts, and the credit ledger."""
from test_helpers import (
    TEST_USERS,
    api_client,
    read_facility,
    read_plan,
    read_record,
    read_unit,
    set_clock,
    setup_credit_at_threshold,
    setup_imaging_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["accreditation_body_headers"]
READER = TEST_USERS["any_headers"]


def _file(scenario, required=10, accepted=8):
    return validate_success(
        api_client.create_clinical_image_submission(
            {
                "unit_id": scenario.unit_id,
                "image_type": "CLINICAL",
                "submitted_at": "2026-09-12T00:00:00Z",
                "reviewer_note_code": "NOTE-1",
                "required_view_count": required,
                "accepted_view_count": accepted,
                "expected_unit_version": read_unit(scenario.unit_id)["version"],
            },
            scenario.admin,
        ),
        201,
    )


def _corrective_plan(scenario, category="POSITIONING"):
    submission = _file(scenario)
    reviewed = validate_success(
        api_client.review_clinical_image_submission(
            submission["id"],
            {"review_outcome": "ACCEPT_WITH_DEFICIENCY", "reviewer_deficiency_category": category},
            REVIEWER,
        ),
        200,
    )
    return reviewed, read_plan(reviewed["corrective_action_plan_id"])


# ══════════════════════════════════════════════════════════════════════════
# Corrective action deadline: the ten-day DUE_SOON window
# ══════════════════════════════════════════════════════════════════════════

def test_a_plan_with_ten_whole_days_remaining_is_due_soon(api):
    """PRD §3.7: "It computes the days remaining as the number of whole days
    between the plan's `due_at` and the current logical clock — the elapsed
    seconds divided by the `86400` seconds in a day, truncated down to a whole
    number. It then classifies: fewer than zero whole days remaining is
    `OVERDUE`; zero through `10` whole days remaining inclusive is `DUE_SOON`;
    more than `10` whole days remaining is `ON_TRACK`."
    PRD §3.7: "The classification is produced by the corrective action
    deadline rule in §3.4 and is re-derived on every re-read of a plan, not
    only at creation."

    Design: Corner/calculations/corrective_action_deadline_due_soon_boundary_at_exactly_ten_days
    """
    scenario = setup_imaging_facility()
    _, plan = _corrective_plan(scenario)
    assert plan["due_at"] == "2026-10-27T00:00:00Z"
    assert plan["deadline_status"] == "ON_TRACK"

    set_clock("2026-10-17T00:00:00Z")
    exactly_ten = read_plan(plan["id"])
    assert exactly_ten["deadline_status"] == "DUE_SOON"
    assert exactly_ten["due_at"] == "2026-10-27T00:00:00Z"
    assert exactly_ten["plan_status"] == "OPEN"
    assert read_unit(scenario.unit_id)["deficiency_open_count"] == 1


def test_the_whole_day_truncation_keeps_a_plan_due_soon_until_its_due_instant(api):
    """PRD §3.7: "Because truncation is toward zero on a whole-day count, a
    plan due in exactly ten days and twenty-three hours still classifies as
    `DUE_SOON` — that is the whole-day variant."
    PRD §3.7: "If the current logical clock passes the plan's `due_at`, a
    system transition moves an `OPEN` plan to `EXPIRED`."

    Design: Corner/calculations/corrective_action_deadline_due_soon_boundary_at_exactly_ten_days
    """
    scenario = setup_imaging_facility()
    _, plan = _corrective_plan(scenario)
    due_at = plan["due_at"]

    set_clock("2026-10-27T23:59:59Z")
    still_due_soon = read_plan(plan["id"])
    assert still_due_soon["deadline_status"] == "DUE_SOON"

    # One second past the due instant the whole-day count falls below zero.
    set_clock("2026-10-28T00:00:00Z")
    overdue = read_plan(plan["id"])
    assert overdue["deadline_status"] == "OVERDUE"
    assert overdue["due_at"] == due_at


# ══════════════════════════════════════════════════════════════════════════
# Phantom attempt counting: only scored acquisitions count
# ══════════════════════════════════════════════════════════════════════════

def test_a_voided_acquisition_is_excluded_from_the_attempt_counters(api):
    """PRD §3.4: "Voiding recomputes the unit's `phantom_attempt_count` so
    that the voided test drops out of consideration."
    PRD §3.4: "`phantom_attempt_count` counts only tests that actually
    produced a score — a test still in `ACQUIRED` is not counted."
    PRD §3.4: "Not every acquisition is scored. The accrediting body can void
    an acquisition outright, which is permitted only while `result_status` is
    `ACQUIRED` and transitions the test to the terminal `VOIDED`, leaving
    `phantom_total_score` null."

    Design: Corner/calculations/phantom_composite_score_input_filtering_on_attempt_counts
    """
    scenario = setup_imaging_facility()
    phantom = validate_success(
        api_client.create_phantom_test(
            {
                "unit_id": scenario.unit_id,
                "phantom_serial_code": "PH-CT-9",
                "acquired_at": "2026-09-13T00:00:00Z",
                "duration_minutes": 30,
            },
            scenario.admin,
        ),
        201,
    )
    voided = validate_success(api_client.void_phantom_test(phantom["id"], {}, scenario.admin), 200)
    assert voided["result_status"] == "VOIDED"
    assert voided["phantom_total_score"] is None

    unit = read_unit(scenario.unit_id)
    assert unit["phantom_attempt_count"] == 0
    assert unit["phantom_failure_count"] == 0
    assert unit["last_phantom_score"] is None


def test_a_scored_acquisition_does_count_toward_the_attempt_counters(api):
    """PRD §3.4: "recomputes the owning unit's `phantom_attempt_count` as the
    number of that unit's tests in `SCORED`, `PASS` or `FAIL` status, and
    recomputes `phantom_failure_count` as the number in `FAIL`."

    Design: Corner/calculations/phantom_composite_score_input_filtering_on_attempt_counts
    """
    scenario = setup_imaging_facility()
    phantom = validate_success(
        api_client.create_phantom_test(
            {
                "unit_id": scenario.unit_id,
                "phantom_serial_code": "PH-CT-9",
                "acquired_at": "2026-09-13T00:00:00Z",
                "duration_minutes": 30,
            },
            scenario.admin,
        ),
        201,
    )
    scored = validate_success(
        api_client.score_phantom_test(
            phantom["id"],
            {
                "spatial_resolution_score": 3,
                "contrast_score": 4,
                "artifact_score": 5,
                "scored_at": "2026-09-13T01:00:00Z",
            },
            scenario.admin,
        ),
        200,
    )
    assert scored["result_status"] == "FAIL"

    unit = read_unit(scenario.unit_id)
    assert unit["phantom_attempt_count"] == 1
    assert unit["phantom_failure_count"] == 1
    assert unit["last_phantom_score"] == 4.0


# ══════════════════════════════════════════════════════════════════════════
# Deviation bands, second observation of the same survey metric
# ══════════════════════════════════════════════════════════════════════════

def test_a_post_repair_survey_reports_the_same_deviation_as_its_predecessor(api):
    """PRD §3.5: "The dose deviation rule runs when a survey leaves
    `SCHEDULED`, and again when a corrective-required survey is resubmitted.
    It computes the deviation as the measured entrance dose minus the
    reference entrance dose, divided by the reference entrance dose,
    multiplied by one hundred — a signed percentage."
    PRD §3.5: "A survey that survives the lapse check moves to `SUBMITTED`"

    Design: Difficulty/dual_variant_calc/survey_dose_deviation_banded_weight_vs_mean_of_bands
    """
    scenario = setup_imaging_facility()
    second = validate_success(
        api_client.create_physicist_survey(
            {
                "facility_id": scenario.facility_id,
                "physicist_qualification_id": scenario.physicist_qualification_id,
                "survey_type": "POST_REPAIR",
                "scheduled_at": "2026-09-20T00:00:00Z",
                "reference_entrance_dose_mgy": 2.0,
                "unit_id": scenario.unit_id,
            },
            scenario.physicist,
        ),
        201,
    )
    submitted = validate_success(
        api_client.submit_physicist_survey(
            second["id"],
            {
                "performed_at": "2026-09-20T00:00:00Z",
                "measured_entrance_dose_mgy": 2.15,
                "shielding_verdict": "PASS",
            },
            scenario.physicist,
        ),
        200,
    )
    # Both the baseline and this survey carry the identical deviation of 7.5 %.
    assert submitted["dose_deviation_pct"] == 7.5
    assert available_survey_count(scenario) == 2


# ══════════════════════════════════════════════════════════════════════════
# The registry credit ledger
# ══════════════════════════════════════════════════════════════════════════

def test_submitting_and_rejecting_a_record_conserves_the_registry_balance(api):
    """PRD §3.6: "A successful submission stamps `submitted_at` from the
    current logical clock, sets `registry_fee_cents` to `2500`, debits `2500`
    from the facility's `registry_credit_cents`, and moves the record to
    `SUBMITTED`."
    PRD §3.6: "The effect is to set `registry_fee_cents` back to `0`, clear
    `submitted_at` to null, return `benchmark_status` to `NOT_EVALUATED`, and
    credit `2500` back to the facility's `registry_credit_cents`, restoring
    the balance the submission had consumed."

    Design: Difficulty/compensating_invariant/registry_credit_cents_conserved_across_record_submit_and_reject
    """
    scenario = setup_imaging_facility()
    balance_before = read_facility(scenario.facility_id)["registry_credit_cents"]

    record = validate_success(
        api_client.create_dose_registry_record(
            {
                "unit_id": scenario.unit_id,
                "exam_category_code": "CT_HEAD",
                "exam_month": "2026-07-01T00:00:00Z",
                "dose_index_value": 2.3,
            },
            scenario.admin,
        ),
        201,
    )
    submitted = validate_success(
        api_client.submit_dose_registry_record(record["id"], {}, scenario.admin), 200
    )
    assert submitted["submission_status"] == "SUBMITTED"
    assert submitted["registry_fee_cents"] == 2500
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == balance_before - 2500

    rejected = validate_success(
        api_client.reject_dose_registry_record(record["id"], {}, REVIEWER), 200
    )
    assert rejected["submission_status"] == "REJECTED"
    assert rejected["registry_fee_cents"] == 0
    assert rejected["benchmark_status"] == "NOT_EVALUATED"
    assert rejected["submitted_at"] is None
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == balance_before


def test_rejecting_a_record_restores_the_balance_read_back_through_the_entity(api):
    """PRD §3.6: "Rejection is terminal."
    PRD §2.7: "`registry_credit_cents` is a prepaid balance, denominated in
    whole cents, that a facility spends to interact with the national dose
    registry and to open renewal windows. It can never be negative."

    Design: Difficulty/compensating_invariant/registry_credit_cents_conserved_across_record_submit_and_reject
    """
    scenario = setup_imaging_facility()
    balance_before = read_facility(scenario.facility_id)["registry_credit_cents"]
    record = validate_success(
        api_client.create_dose_registry_record(
            {
                "unit_id": scenario.unit_id,
                "exam_category_code": "CT_HEAD",
                "exam_month": "2026-07-01T00:00:00Z",
                "dose_index_value": 2.3,
            },
            scenario.admin,
        ),
        201,
    )
    api_client.submit_dose_registry_record(record["id"], {}, scenario.admin)
    api_client.reject_dose_registry_record(record["id"], {}, REVIEWER)

    assert read_record(record["id"])["submission_status"] == "REJECTED"
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == balance_before


def test_a_balance_of_exactly_the_fee_admits_one_more_submission(api):
    """PRD §2.7: "Every operation that spends from the balance is refused with
    `ERR_INSUFFICIENT_REGISTRY_CREDIT` at HTTP 402 when the stored balance
    does not cover the debit in question"
    PRD §3.6: "the facility's `registry_credit_cents` must hold at least
    `2500`, failing which the submission is refused with
    `ERR_INSUFFICIENT_REGISTRY_CREDIT`."

    Design: Corner/complexity_layers/registry_credit_threshold_at_exactly_2500_still_admits_one_submission
    """
    scenario = setup_credit_at_threshold(2500)
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == 2500

    first = validate_success(
        api_client.create_dose_registry_record(
            {
                "unit_id": scenario.unit_id,
                "exam_category_code": "CT_HEAD",
                "exam_month": "2026-07-01T00:00:00Z",
                "dose_index_value": 2.3,
            },
            scenario.admin,
        ),
        201,
    )
    second = validate_success(
        api_client.create_dose_registry_record(
            {
                "unit_id": scenario.unit_id,
                "exam_category_code": "CT_HEAD",
                "exam_month": "2026-08-01T00:00:00Z",
                "dose_index_value": 2.4,
            },
            scenario.admin,
        ),
        201,
    )

    accepted = validate_success(
        api_client.submit_dose_registry_record(first["id"], {}, scenario.admin), 200
    )
    assert accepted["submitted_at"] == "2026-09-05T00:00:00Z"
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == 0

    res = api_client.submit_dose_registry_record(second["id"], {}, scenario.admin)
    assert res.status_code == 402, f"Expected 402, got {res.status_code}: {res.text}"
    validate_error(res, "ERR_INSUFFICIENT_REGISTRY_CREDIT")

    assert read_record(second["id"])["submission_status"] == "STAGED"
    assert read_record(second["id"])["registry_fee_cents"] == 0


def test_a_staged_record_is_not_counted_in_the_listing_by_submission_status(api):
    """PRD §3.6: "A record begins in `STAGED` status with `benchmark_status`
    `NOT_EVALUATED`, `registry_fee_cents` at `0`, and its `submitted_at`,
    `benchmark_comparison_value` and `dose_benchmark_average` null."

    Design: Corner/complexity_layers/registry_credit_threshold_at_exactly_2500_still_admits_one_submission
    """
    scenario = setup_credit_at_threshold(2500)
    staged = validate_success(
        api_client.create_dose_registry_record(
            {
                "unit_id": scenario.unit_id,
                "exam_category_code": "CT_HEAD",
                "exam_month": "2026-07-01T00:00:00Z",
                "dose_index_value": 2.3,
            },
            scenario.admin,
        ),
        201,
    )
    assert staged["submission_status"] == "STAGED"
    assert staged["benchmark_status"] == "NOT_EVALUATED"
    assert staged["registry_fee_cents"] == 0
    assert staged["submitted_at"] is None
    assert staged["dose_benchmark_average"] is None


def available_survey_count(scenario):
    data, meta = validate_paginated(
        api_client.list_physicist_surveys(READER, {"facility_id": scenario.facility_id})
    )
    return meta["total_count"]