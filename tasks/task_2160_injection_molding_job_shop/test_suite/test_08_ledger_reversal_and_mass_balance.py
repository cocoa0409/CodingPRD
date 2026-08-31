"""Reversing a report, the conserved resin balance and the shot-metered gates."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_production_report_payload,
    create_released_lot,
    job_version,
    post_report,
    read_job,
    read_lot,
    read_mold,
    read_report,
    reverse_report,
    setup_running_job,
    setup_scheduled_job,
    validate_error,
    validate_paginated,
    validate_success,
)

PE = TEST_USERS["process_engineer_headers"]
QE = TEST_USERS["quality_engineer_headers"]

STANDARD_LINE = dict(
    shots=1000,
    short_shot_shots=25,
    good_parts=3800,
    scrap_parts=200,
    virgin_grams=36000,
    regrind_grams=4000,
    run_minutes=700,
)


def test_reversal_returns_the_resin_balance_and_shot_counters_with_zero_drift(api):
    """PRD §2.10: "Because every quantity involved is an integer, the recomputation
    restores the exact prior values with zero drift; there is no compensating-entry
    arithmetic and no residue."
    PRD §3.5: "At every point in time, `qty_grams_remaining` equals the received
    kilograms multiplied by 1,000, minus the sum of `virgin_grams` over every
    non-reversed shift report whose `resin_lot_id` points at that lot."
    PRD §3.7: "The lot's `qty_grams_remaining`, the tool's `total_shot_count` and
    `shots_since_pm`, and every one of the job's part, minute, ratio and cost
    counters return to precisely their pre-report values."

    Design: Difficulty/compensating_invariant/report_reversal_conserves_resin_mass_and_shot_counters
    """
    shop = setup_running_job()
    report = post_report(shop["job"]["id"], **STANDARD_LINE)
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 464000
    assert read_mold(shop["mold"]["id"])["total_shot_count"] == 1000

    reversed_report = validate_success(
        api.reverse_production_report(
            report["id"], {"reason": "shift report keyed against the wrong job"}, QE
        )
    )

    assert reversed_report["is_reversed"] is True
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 500000
    mold = read_mold(shop["mold"]["id"])
    assert mold["total_shot_count"] == 0
    assert mold["shots_since_pm"] == 0


def test_reversal_returns_every_job_counter_and_cost_to_its_pre_report_value(api):
    """PRD §2.10: "Every accumulator in the system is defined as a function of the
    *non-reversed* reports that feed it, so a reversal is applied simply by
    recomputing those accumulators from the remaining reports."
    PRD §3.7: "`first_pass_yield_bp` is `good_parts_total` multiplied by 10,000 and
    divided by `parts_molded_total`, rounded **down**, and stands at 10,000 basis
    points whenever `parts_molded_total` is zero. `actual_cycle_time_sec` is
    `total_run_minutes` multiplied by the 60 seconds in a minute and divided by
    `total_shots`, rounded half up, and is unset whenever `total_shots` is zero."

    Design: Difficulty/compensating_invariant/report_reversal_conserves_resin_mass_and_shot_counters
    """
    shop = setup_running_job()
    report = post_report(shop["job"]["id"], **STANDARD_LINE)

    reverse_report(report["id"])

    job = read_job(shop["job"]["id"])
    assert job["total_shots"] == 0
    assert job["parts_molded_total"] == 0
    assert job["good_parts_total"] == 0
    assert job["scrap_parts_total"] == 0
    assert job["total_run_minutes"] == 0
    assert job["job_direct_cost_cents"] == 0
    assert job["job_overhead_cents"] == 0
    assert job["job_total_cost_cents"] == 0
    assert job["first_pass_yield_bp"] == 10000
    assert job.get("actual_cycle_time_sec") is None
    assert job["run_status"] == "RUNNING", "reversal never moves the run axis"
    assert read_lot(shop["lot"]["id"])["status"] == "RELEASED"


def test_a_reversed_report_drops_out_of_every_rollup_the_survivor_still_feeds(api):
    """PRD §2.10: "Every accumulator in the system is defined as a function of the
    *non-reversed* reports that feed it, so a reversal is applied simply by
    recomputing those accumulators from the remaining reports."
    PRD §3.7: "**Yield accounting** rebuilds the job's counters from scratch:
    `total_shots` is the summed `shots`; `parts_molded_total` is the summed product
    of each report's `shots` and the tool's `cavity_count`; `good_parts_total`,
    `scrap_parts_total`, `short_shot_shots_total` and `total_run_minutes` are the
    summed `good_parts`, `scrap_parts`, `short_shot_shots` and `run_minutes`
    respectively."
    PRD §2.3: "Shift reports may be filtered by `job_id`, `resin_lot_id` and
    `is_reversed`."

    Design: Corner/calculations/reversed_reports_are_excluded_from_every_job_rollup
    """
    shop = setup_running_job()
    first = post_report(
        shop["job"]["id"],
        shots=1000,
        short_shot_shots=5,
        good_parts=3960,
        scrap_parts=40,
        virgin_grams=36000,
        regrind_grams=4000,
        run_minutes=600,
    )
    post_report(
        shop["job"]["id"],
        shots=500,
        short_shot_shots=0,
        good_parts=1980,
        scrap_parts=20,
        virgin_grams=18000,
        regrind_grams=2000,
        run_minutes=300,
    )

    reverse_report(first["id"], reason="operator logged the wrong shift")

    job = read_job(shop["job"]["id"])
    assert job["total_shots"] == 500
    assert job["parts_molded_total"] == 2000
    assert job["good_parts_total"] == 1980
    assert job["scrap_parts_total"] == 20
    assert job["first_pass_yield_bp"] == 9900
    assert job["actual_cycle_time_sec"] == 36
    assert job["job_direct_cost_cents"] == 40200
    assert job["job_overhead_cents"] == 14070
    assert job["job_total_cost_cents"] == 54270
    assert job["cumulative_regrind_bp"] == 1000
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 482000
    mold = read_mold(shop["mold"]["id"])
    assert mold["total_shot_count"] == 500
    assert mold["shots_since_pm"] == 500

    _, meta = validate_paginated(
        api.list_production_reports(
            QE, params={"job_id": shop["job"]["id"], "is_reversed": False}
        )
    )
    assert meta["total_count"] == 1


def test_a_lot_consumed_to_exactly_zero_grams_becomes_depleted(api):
    """PRD §3.5: "When a report drives the balance of a `RELEASED` lot to exactly 0,
    that lot moves `RELEASED → DEPLETED` and may no longer be staged by another
    job."
    PRD §3.7: "On acceptance the report snapshots the job's `staged_resin_lot_id`
    into its own `resin_lot_id`, so the material traceability of the report survives
    any later de-staging, and the job's `version` is incremented by 1."

    Design: Corner/calculations/resin_lot_reaching_zero_grams_becomes_depleted
    """
    shop = setup_running_job(
        lot_overrides={"supplier_lot_code": "L-SMALL", "qty_kg_received": 36}
    )

    report = validate_success(
        api.create_production_report(
            create_production_report_payload(
                shop["job"]["id"],
                job_version(shop["job"]["id"]),
                shots=1000,
                short_shot_shots=5,
                good_parts=3960,
                scrap_parts=40,
                virgin_grams=36000,
                regrind_grams=4000,
                run_minutes=600,
            ),
            PE,
        ),
        201,
    )

    lot = read_lot(shop["lot"]["id"])
    assert lot["qty_grams_remaining"] == 0
    assert lot["status"] == "DEPLETED"
    assert report["resin_lot_id"] == shop["lot"]["id"]


def test_a_report_drawing_more_virgin_than_the_lot_holds_is_rejected(api):
    """PRD §3.7: "`virgin_grams` may not exceed the staged lot's
    `qty_grams_remaining`, otherwise `ERR_RESIN_LOT_INSUFFICIENT`."
    PRD §3.5: "At every point in time, `qty_grams_remaining` equals the received
    kilograms multiplied by 1,000, minus the sum of `virgin_grams` over every
    non-reversed shift report whose `resin_lot_id` points at that lot."

    Design: Corner/calculations/resin_lot_insufficient_grams_rejects_the_report
    """
    shop = setup_running_job(
        lot_overrides={"supplier_lot_code": "L-SMALL", "qty_kg_received": 36}
    )
    version_before = job_version(shop["job"]["id"])

    response = api.create_production_report(
        create_production_report_payload(
            shop["job"]["id"],
            version_before,
            shots=1000,
            short_shot_shots=5,
            good_parts=3960,
            scrap_parts=40,
            virgin_grams=36001,
            regrind_grams=4000,
            run_minutes=600,
        ),
        PE,
    )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_RESIN_LOT_INSUFFICIENT.value)
    lot = read_lot(shop["lot"]["id"])
    assert lot["qty_grams_remaining"] == 36000
    assert lot["status"] == "RELEASED"
    job = read_job(shop["job"]["id"])
    assert job["total_shots"] == 0
    assert job["version"] == version_before


def test_a_report_cannot_be_reversed_twice(api):
    """PRD §2.10: "A report that has already been reversed cannot be reversed again,
    and a second attempt is rejected with `ERR_REPORT_ALREADY_REVERSED`."
    PRD §2.10: "Because every quantity involved is an integer, the recomputation
    restores the exact prior values with zero drift; there is no compensating-entry
    arithmetic and no residue."

    Design: Corner/state_machines/report_reverse_twice_returns_report_already_reversed
    """
    shop = setup_running_job()
    report = post_report(
        shop["job"]["id"],
        shots=1000,
        short_shot_shots=5,
        good_parts=3960,
        scrap_parts=40,
        virgin_grams=36000,
        regrind_grams=4000,
        run_minutes=600,
    )
    reverse_report(report["id"])

    response = api.reverse_production_report(report["id"], {"reason": "double entry"}, QE)

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_REPORT_ALREADY_REVERSED.value)
    assert read_report(report["id"])["is_reversed"] is True
    assert read_lot(shop["lot"]["id"])["qty_grams_remaining"] == 500000, (
        "the ledger is not credited twice"
    )
    assert read_mold(shop["mold"]["id"])["total_shot_count"] == 0


def test_an_interim_approval_expires_the_tool_on_the_shot_that_reaches_its_ceiling(api):
    """PRD §3.4: "The tool moves `SAMPLING → INTERIM_APPROVED`, its
    `approved_max_regrind_bp` is set to the package's `max_regrind_bp`, its own
    `interim_expiry_shots` is set to the tool's current `total_shot_count` plus the
    supplied allowance — so the ceiling is expressed as an absolute lifetime shot
    count, not a remaining balance — and its `version` is incremented by 1."
    PRD §3.8: "**The interim-approval gate is evaluated second**: if the tool's
    `interim_expiry_shots` is set, `total_shot_count` has reached or passed it, and
    the tool's lifecycle status is `INTERIM_APPROVED`, the tool moves
    `INTERIM_APPROVED → QUARANTINED`, which is likewise a cascade origin, blocking
    that tool's scheduled jobs with `block_reason` `INTERIM_PPAP_EXPIRED`."
    PRD §3.8: "Two threshold gates are then evaluated in a fixed order, and both use
    an inclusive comparison, so the shot that lands exactly on the threshold trips
    it."

    Design: Corner/calculations/interim_ppap_shot_ceiling_quarantines_the_mold
    """
    shop = setup_running_job(decision="INTERIM_APPROVE", interim_expiry_shots=500)
    before = read_mold(shop["mold"]["id"])
    assert before["status"] == "INTERIM_APPROVED"
    assert before["interim_expiry_shots"] == 500

    validate_success(
        api.create_production_report(
            create_production_report_payload(
                shop["job"]["id"],
                job_version(shop["job"]["id"]),
                shots=500,
                short_shot_shots=0,
                good_parts=1980,
                scrap_parts=20,
                virgin_grams=18000,
                regrind_grams=2000,
                run_minutes=300,
            ),
            PE,
        ),
        201,
    )

    mold = read_mold(shop["mold"]["id"])
    assert mold["total_shot_count"] == 500
    assert mold["shots_since_pm"] == 500
    assert mold["status"] == "QUARANTINED"
    assert mold["service_state"] == "SERVICEABLE", (
        "500 shots is far below the 5000-shot preventive-maintenance interval"
    )
    assert read_job(shop["job"]["id"])["run_status"] == "RUNNING"


def test_staging_a_lot_of_the_wrong_grade_is_rejected(api):
    """PRD §3.5: "Staging requires the job's `run_status` to be `SCHEDULED`,
    otherwise `ERR_JOB_NOT_SCHEDULED`; requires the lot's `status` to be `RELEASED`,
    otherwise `ERR_RESIN_LOT_NOT_RELEASED`; requires the lot's `resin_grade` to
    equal the `resin_grade` on the job's quote, otherwise `ERR_RESIN_GRADE_MISMATCH`;
    and requires the lot to have at least 1 gram remaining. On success the lot's id
    is written to the job's `staged_resin_lot_id`."

    Design: Corner/validations/stage_material_with_mismatched_resin_grade_is_rejected
    """
    shop = setup_scheduled_job()
    wrong_grade = create_released_lot(resin_grade="ABS", supplier_lot_code="L-ABS")

    rejected = api.stage_material(
        shop["job"]["id"], {"resin_lot_id": wrong_grade["id"]}, PE
    )
    assert rejected.status_code == 422, f"Expected 422, got {rejected.status_code}"
    validate_error(rejected, ApiErrorId.ERR_RESIN_GRADE_MISMATCH.value)
    job = read_job(shop["job"]["id"])
    assert job["material_status"] == "UNSTAGED"
    assert job.get("staged_resin_lot_id") is None

    staged = validate_success(
        api.stage_material(shop["job"]["id"], {"resin_lot_id": shop["lot"]["id"]}, PE)
    )
    assert staged["material_status"] == "STAGED"
    assert staged["staged_resin_lot_id"] == shop["lot"]["id"]
