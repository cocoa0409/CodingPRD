"""The derived numbers: adjudication scores, coverage merges, postures and clocks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accrue_months,
    activate_tuition_agreement,
    add_verified_employment_history,
    assert_tuition_cents_identity,
    book_road_test,
    complete_negative_drug_test,
    create_applicant,
    create_carrier,
    create_application,
    create_tuition_agreement,
    fetch_applicant,
    fetch_carrier,
    fetch_dq_file,
    file_dq_document,
    make_safety_director_headers,
    order_screening_check,
    record_employment_segment,
    request_and_verify_segment,
    set_clock,
    setup_hired_applicant,
    setup_submitted_application,
    submit_application,
    terminate_hire,
    validate_error,
    validate_success,
)

RECRUITER = TEST_USERS["recruiter_headers"]
DER = TEST_USERS["der_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
SCHOOL = TEST_USERS["school_coordinator_headers"]


def test_mvr_expiry_follows_the_carriers_validity_window(api):
    """PRD §3.4: "For a motor vehicle record the service also computes `expires_on` as
    `issued_on` advanced by the carrier's `mvr_validity_days`; for a Pre-Employment Screening
    Program report and for a criminal check `expires_on` stays null."
    PRD §3.4: "For an `MVR` the raw sum is first reduced by an experience credit, then
    scaled. The credit is 1.5 for each full year of the applicant's `experience_months`,
    taking the whole number of years by discarding any remaining months, and it is capped at
    6.0 however long the driver has been on the road; the credit is not rounded before it is
    subtracted. The net is the raw sum minus that credit, floored at zero so a very
    experienced clean driver never scores below nothing."

    Design: Corner/calculations/mvr_expiry_uses_carrier_mvr_validity_days
    """
    ctx = setup_submitted_application(
        carrier_overrides={
            "legal_name": "Short Window Lines",
            "dot_number": "DOT-CORNER-1",
            "mvr_validity_days": 180,
        }
    )
    check = order_screening_check(ctx["application_id"], "MVR")

    recorded = validate_success(
        api.record_screening_result(
            check["id"],
            {
                "issued_on": "2026-07-01",
                "violation_points": 2,
                "serious_violation_count": 0,
                "crash_preventable_count": 0,
            },
            RECRUITER,
        )
    )

    assert recorded["expires_on"] == "2026-12-28"
    assert float(recorded["adjudication_score"]) == 0.00, (
        "raw 2.0 less the 3.0 experience credit is floored at zero"
    )


def test_adjacent_verified_segments_merge_into_one_run(api):
    """PRD §3.3: "They are then merged left to right: the next segment joins the run in
    progress when its lower bound is less than or equal to the run's current upper bound, so
    that two segments which merely touch at a shared date *do* merge, while a one-day hole
    between them does *not*."
    PRD §3.3: "The `verified_coverage_days` figure is the total number of days spanned by the
    merged runs, and `gap_days_unexplained` is 1,095 minus that figure."
    PRD §3.3: "That read answers with the `variant` it applied, the resulting
    `verified_coverage_days` and `gap_days_unexplained`, and a `merged_segment_count` giving
    the number of runs left after merging."

    Design: Corner/calculations/employment_coverage_merges_adjacent_and_keeps_gap
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    add_verified_employment_history(ctx["application_id"])

    payload = validate_success(
        api.get_employment_coverage(
            ctx["application_id"], AUDITOR, params={"variant": "strict_verified"}
        )
    )

    assert payload["verified_coverage_days"] == 1095
    assert payload["gap_days_unexplained"] == 0
    assert payload["merged_segment_count"] == 1

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["verified_coverage_days"] == 1095
    assert application["gap_days_unexplained"] == 0


def test_unanswered_and_unsent_segments_never_count_as_coverage(api):
    """PRD §3.3: "Segments in `PENDING`, `REQUESTED`, `NO_RESPONSE` or `RESPONDED_DISPUTED`
    are excluded by both accountings."
    PRD §3.3: "The strict accounting, named `strict_verified`, admits only segments in
    `RESPONDED_VERIFIED`; it is the default, it is the one persisted into the application's
    `verified_coverage_days` and `gap_days_unexplained`, and it is the one the hiring gate
    enforces."
    PRD §3.3: "The projected accounting, named `good_faith_projected`, admits segments in
    `RESPONDED_VERIFIED` and `GOOD_FAITH_DOCUMENTED` alike, so an employer that never answered
    three documented requests still counts as covered; identical rows therefore yield a larger
    coverage and a smaller gap under the projected accounting than under the strict one."

    Design: Corner/calculations/employment_coverage_excludes_pending_and_requested_rows
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    never_asked = record_employment_segment(
        ctx["application_id"], "Never Asked Co", "2023-01-01", "2026-08-01"
    )
    awaiting = record_employment_segment(
        ctx["application_id"], "Awaiting Reply Co", "2022-01-01", "2024-09-01"
    )
    validate_success(api.send_verification_request(awaiting["id"], RECRUITER))
    verified = record_employment_segment(
        ctx["application_id"], "Northgate Haul", "2024-09-01", "2026-08-01"
    )
    request_and_verify_segment(verified["id"])

    assert validate_success(
        api.get_employment_verification(never_asked["id"], RECRUITER)
    )["status"] == "PENDING"
    assert validate_success(
        api.get_employment_verification(awaiting["id"], RECRUITER)
    )["status"] == "REQUESTED"

    strict = validate_success(
        api.get_employment_coverage(
            ctx["application_id"], AUDITOR, params={"variant": "strict_verified"}
        )
    )
    assert strict["verified_coverage_days"] == 699
    assert strict["gap_days_unexplained"] == 396
    assert strict["merged_segment_count"] == 1

    projected = validate_success(
        api.get_employment_coverage(
            ctx["application_id"], AUDITOR, params={"variant": "good_faith_projected"}
        )
    )
    assert projected["verified_coverage_days"] == 699, (
        "neither excluded row reached GOOD_FAITH_DOCUMENTED"
    )


def test_only_an_unsatisfactory_rating_freezes_the_office(api):
    """PRD §3.1: "From those two numbers the office's `posture` follows, and the branches are
    evaluated in a fixed order with the first match winning: the posture is `FROZEN` when the
    carrier's `safety_rating` is `UNSATISFACTORY`; otherwise it is `RESTRICTED` when the
    deficiency ratio is greater than or equal to 0.2500 — a ratio of exactly one quarter
    already restricts the office; otherwise it is `OPEN`."
    PRD §3.1: "Reconfiguration adjusts `open_requisitions` and `safety_rating` under the
    concurrency rule of §2.7, taking `expected_carrier_version` alongside whichever of the two
    knobs the caller wishes to change; both are optional, the version is not."
    PRD §2.4: "It increments by exactly one on every mutation of the row it belongs to, and
    `updated_at` is refreshed to the logical-clock instant at which the mutation was applied."

    Design: Corner/calculations/carrier_posture_frozen_only_on_unsatisfactory_rating
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")
    base_version = carrier["version"]

    conditional = validate_success(
        api.update_carrier(
            carrier["id"],
            {"safety_rating": "CONDITIONAL", "expected_carrier_version": base_version},
            SAFETY_DIRECTOR,
        )
    )
    assert conditional["posture"] == "OPEN"
    assert conditional["version"] == base_version + 1
    assert conditional["filled_requisitions"] == 0
    assert float(conditional["deficiency_ratio"]) == 0.0

    unsatisfactory = validate_success(
        api.update_carrier(
            carrier["id"],
            {
                "safety_rating": "UNSATISFACTORY",
                "expected_carrier_version": conditional["version"],
            },
            SAFETY_DIRECTOR,
        )
    )
    assert unsatisfactory["posture"] == "FROZEN"
    assert unsatisfactory["version"] == base_version + 2
    assert unsatisfactory["filled_requisitions"] == 0
    assert float(unsatisfactory["deficiency_ratio"]) == 0.0


def test_a_lapsed_certificate_makes_the_file_deficient_and_restricts_the_office(api):
    """PRD §3.7: "It then selects the satisfied rows: a row is satisfied when its `status`
    belongs to the accounting's satisfying set *and* it is not lapsed, where lapsed means the
    row carries a non-null `expires_on` strictly earlier than the current logical-clock
    calendar date."
    PRD §3.7: "A file in `COMPLETE` falls back to `DEFICIENT` the moment its provisional
    percentage drops below 100.00 — most often because a document lapsed when the logical clock
    moved past its `expires_on` — and that move likewise recomputes the carrier's ratio and
    posture; the `COMPLETE → DEFICIENT → COMPLETE` cycle is how the system tracks expiry and
    remediation over a driver's tenure."
    PRD §3.1: "The `deficiency_ratio` is the number of qualification files in `DEFICIENT`
    status that belong to an application reachable from one of those active hires, divided by
    `filled_requisitions`, rounded half up to four decimal places; when `filled_requisitions`
    is zero the ratio is 0.0 rather than undefined."
    PRD §3.7: "`EXPIRED_GRACE` when the expiry has passed but the number of days since it
    passed is at most the carrier's `medical_cert_grace_days`"

    Design: Corner/calculations/dq_file_expiry_flips_complete_to_deficient_and_restricts_carrier
    """
    ctx = setup_hired_applicant(carrier_overrides={"dot_number": "DOT-CORNER-1"})

    set_clock("2026-10-02T00:00:00Z")

    payload = validate_success(
        api.get_dq_file_completeness(
            ctx["dq_file_id"], AUDITOR, params={"variant": "pre_hire_provisional"}
        )
    )
    assert float(payload["completeness_pct"]) == 85.71
    assert payload["satisfied_weight"] == 24
    assert payload["denominator_weight"] == 28
    assert payload["deficiency_count"] == 1

    assert fetch_dq_file(ctx["dq_file_id"])["status"] == "DEFICIENT"

    carrier = fetch_carrier(ctx["carrier_id"])
    assert carrier["filled_requisitions"] == 1
    assert float(carrier["deficiency_ratio"]) == 1.0
    assert carrier["posture"] == "RESTRICTED"

    assert fetch_applicant(ctx["applicant_id"])["cdl_downgrade_risk"] == "EXPIRED_GRACE"


def test_a_composite_of_exactly_eighty_passes_the_road_test(api):
    """PRD §3.6: "Each section is weighted and rounded on its own first: the pre-trip
    inspection section is `score_pretrip` multiplied by 0.25 and rounded half up to two decimal
    places, the basic control skills section is `score_skills` multiplied by 0.35 and rounded
    half up to two decimal places, and the on-road section is `score_road` multiplied by 0.40
    and rounded half up to two decimal places."
    PRD §3.6: "A pass requires two thresholds to hold together: the `composite_score` must be
    at least 80.0, and the raw `score_road` must be at least 70 on its own, so a candidate
    cannot compensate for weak on-road driving with a flawless pre-trip."
    PRD §3.6: "On success the test moves `SCHEDULED → PASSED`, which is its terminal state;
    the application's `qualification_status` advances `IN_PROGRESS → ROAD_TEST_PASSED`; the
    `ROAD_TEST_CERT` document of the application's qualification file becomes `PRESENT` with
    `effective_on` at the current logical-clock date; and the file's `completeness_pct`,
    `deficiency_count` and status are recomputed with its `version` incremented by one."

    Design: Corner/calculations/road_test_composite_exactly_at_pass_threshold_passes
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    complete_negative_drug_test(ctx["application_id"])
    road_test = book_road_test(ctx["application_id"])

    result = validate_success(
        api.record_road_test_result(
            road_test["id"],
            {"outcome": "PASSED", "score_pretrip": 80, "score_skills": 80, "score_road": 80},
            make_safety_director_headers("exam-501"),
        )
    )

    assert float(result["composite_score"]) == 80.0
    assert result["status"] == "PASSED"
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "ROAD_TEST_PASSED"


def test_a_weak_on_road_score_blocks_a_pass_despite_a_high_composite(api):
    """PRD §3.6: "A pass requires two thresholds to hold together: the `composite_score` must
    be at least 80.0, and the raw `score_road` must be at least 70 on its own, so a candidate
    cannot compensate for weak on-road driving with a flawless pre-trip. An outcome of
    `PASSED` whose figures fail either threshold is not a declared transition and is refused
    with `ERR_INVALID_STATE`."

    Design: Corner/calculations/road_test_road_floor_blocks_pass_despite_high_composite
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    complete_negative_drug_test(ctx["application_id"])
    road_test = book_road_test(ctx["application_id"])

    response = api.record_road_test_result(
        road_test["id"],
        {"outcome": "PASSED", "score_pretrip": 88, "score_skills": 90, "score_road": 68},
        make_safety_director_headers("exam-501"),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    row = validate_success(api.get_road_test(road_test["id"], RECRUITER))
    assert row["status"] == "SCHEDULED"
    assert row["composite_score"] is None
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "IN_PROGRESS"


def test_monthly_accruals_retire_the_principal_and_fulfil_the_agreement(api):
    """PRD §3.9: "Step one divides `tuition_total_cents` by `commitment_months` and takes the
    floor, giving `base_monthly_cents`, the principal retired per served month."
    PRD §3.9: "Step two keys a retention tier off that base figure and off nothing else: a
    base of at least 20,000 cents — two hundred dollars a month — earns a bonus rate of zero
    percent, a base of at least 10,000 cents but below that earns five percent, and anything
    below 10,000 cents earns ten percent."
    PRD §3.9: "On acceptance `months_served` increments by one; `reimbursed_cents` becomes
    `months_served` multiplied by `base_monthly_cents`, the principal retired so far;
    `bonus_paid_cents` becomes `months_served` multiplied by the difference between
    `monthly_reimbursement_cents` and `base_monthly_cents`, the retention incentive paid on
    top; and `outstanding_cents` becomes `tuition_total_cents` less `forgiven_cents`, less
    `reimbursed_cents`, less `clawback_cents`."
    PRD §3.9: "When `months_served` reaches `commitment_months` the agreement moves `ACTIVE →
    FULFILLED` with `outstanding_cents` left at zero."
    PRD §3.9: "One identity holds after every one of those three operations without exception:
    `tuition_total_cents` always equals `reimbursed_cents` plus `clawback_cents` plus
    `outstanding_cents` plus `forgiven_cents`."

    Design: Corner/calculations/tuition_accrual_updates_ledger_and_reaches_fulfilled
    """
    ctx = setup_hired_applicant(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    agreement = create_tuition_agreement(
        ctx["applicant_id"], tuition_total_cents=50001, commitment_months=2
    )

    activated = validate_success(api.activate_tuition_agreement(agreement["id"], SCHOOL))
    assert activated["base_monthly_cents"] == 25000
    assert activated["monthly_reimbursement_cents"] == 25000
    assert activated["forgiven_cents"] == 1
    assert activated["outstanding_cents"] == 50000
    assert_tuition_cents_identity(activated)

    first = validate_success(
        api.accrue_month(agreement["id"], {"service_month": "2026-09"}, SCHOOL)
    )
    assert first["months_served"] == 1
    assert first["reimbursed_cents"] == 25000
    assert first["bonus_paid_cents"] == 0
    assert first["outstanding_cents"] == 25000
    assert first["status"] == "ACTIVE"
    assert_tuition_cents_identity(first)

    second = validate_success(
        api.accrue_month(agreement["id"], {"service_month": "2026-10"}, SCHOOL)
    )
    assert second["months_served"] == 2
    assert second["reimbursed_cents"] == 50000
    assert second["outstanding_cents"] == 0
    assert second["status"] == "FULFILLED"
    assert_tuition_cents_identity(second)


def test_the_rehire_cooldown_expires_on_the_boundary_day(api):
    """PRD §3.8: "`COOLDOWN` when the current logical-clock date is strictly earlier than the
    latest `terminated_on` advanced by the carrier's `rehire_cooldown_days`, so the cooldown
    expires on the very day that sum is reached; and `ELIGIBLE` otherwise."
    PRD §3.8: "The first hop moves the record `ACTIVE → TERMINATED` and writes
    `terminated_on`, `termination_type`, `rehire_flag` and `tenure_days`, the last being the
    whole number of days from `hired_on` to `terminated_on`."
    PRD §3.8: "The applicant's `outstanding_clawback_cents` is the sum of `clawback_cents`
    across that applicant's tuition agreements in `TERMINATED_CLAWBACK`."

    Design: Corner/calculations/rehire_cooldown_expires_exactly_on_the_boundary_day
    """
    ctx = setup_hired_applicant(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    set_clock("2026-08-20T00:00:00Z")
    hire = terminate_hire(
        ctx["hire_id"],
        terminated_on="2026-08-20",
        termination_type="VOLUNTARY",
        rehire_flag="ELIGIBLE",
    )
    assert hire["status"] == "TERMINATED"
    assert hire["tenure_days"] == 7

    # terminated_on 2026-08-20 advanced by the carrier's 180 cooldown days is 2027-02-16.
    set_clock("2027-02-15T00:00:00Z")
    day_before = fetch_applicant(ctx["applicant_id"])
    assert day_before["rehire_eligibility"] == "COOLDOWN"
    assert day_before["outstanding_clawback_cents"] == 0

    set_clock("2027-02-16T00:00:00Z")
    boundary_day = fetch_applicant(ctx["applicant_id"])
    assert boundary_day["rehire_eligibility"] == "ELIGIBLE"
    assert boundary_day["outstanding_clawback_cents"] == 0


def test_the_review_window_stays_due_through_the_last_grace_day(api):
    """PRD §3.7: "From that baseline, `next_review_due_on` is the baseline advanced by the
    carrier's `annual_review_interval_days`, and the end of grace is `next_review_due_on`
    advanced by the carrier's `annual_review_grace_days`."
    PRD §3.7: "The `review_state` reads `NOT_DUE` while the current logical-clock date is
    strictly earlier than `next_review_due_on`; it reads `DUE` from `next_review_due_on`
    through the end of grace inclusive — a file whose grace end equals the clock date is still
    `DUE` — and it reads `OVERDUE` from the day after that."

    Design: Corner/calculations/dq_review_due_band_is_closed_at_the_grace_end
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})

    set_clock("2027-07-31T00:00:00Z")
    before_due = validate_success(api.get_dq_file(ctx["dq_file_id"], AUDITOR))
    assert before_due["review_state"] == "NOT_DUE"
    assert before_due["next_review_due_on"] == "2027-08-01"

    set_clock("2027-08-31T00:00:00Z")
    at_grace_end = validate_success(api.get_dq_file(ctx["dq_file_id"], AUDITOR))
    assert at_grace_end["review_state"] == "DUE"
    assert at_grace_end["next_review_due_on"] == "2027-08-01"

    set_clock("2027-09-01T00:00:00Z")
    past_grace = validate_success(api.get_dq_file(ctx["dq_file_id"], AUDITOR))
    assert past_grace["review_state"] == "OVERDUE"
    assert past_grace["next_review_due_on"] == "2027-08-01"


def test_the_downgrade_bands_step_down_as_the_certificate_ages(api):
    """PRD §3.7: "Let the countdown be the number of whole days from the current
    logical-clock calendar date to that expiry. The band reads `NONE` when the countdown is
    greater than 60 days; `WATCH` when it is greater than 15 days and at most 60 days;
    `IMMINENT` when it is between 0 and 15 days inclusive, meaning the expiry has not yet
    passed; `EXPIRED_GRACE` when the expiry has passed but the number of days since it passed
    is at most the carrier's `medical_cert_grace_days`; and `DOWNGRADED` in every remaining
    case."
    PRD §3.7: "Otherwise the governing certificate is the candidate with the greatest
    `expires_on`, ties broken by the greatest `created_at` and never by identifier; its
    `expires_on` is copied into `governing_medical_cert_expires_on`."

    Design: Corner/calculations/cdl_downgrade_risk_watch_band_upper_boundary
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    file_dq_document(
        ctx["dq_file_id"],
        "MEDICAL_CERT",
        status="PRESENT",
        effective_on="2026-07-15",
        expires_on="2026-10-01",
        source_ref="NRCME-889201",
    )

    at_start = fetch_applicant(ctx["applicant_id"])
    assert at_start["cdl_downgrade_risk"] == "NONE", "61 days out is beyond the watch window"
    assert at_start["governing_medical_cert_expires_on"] == "2026-10-01"

    set_clock("2026-08-02T00:00:00Z")
    at_watch_edge = fetch_applicant(ctx["applicant_id"])
    assert at_watch_edge["cdl_downgrade_risk"] == "WATCH", "exactly 60 days out is WATCH"
    assert at_watch_edge["governing_medical_cert_expires_on"] == "2026-10-01"

    set_clock("2026-09-16T00:00:00Z")
    at_imminent_edge = fetch_applicant(ctx["applicant_id"])
    assert at_imminent_edge["cdl_downgrade_risk"] == "IMMINENT", "exactly 15 days out is IMMINENT"
    assert at_imminent_edge["governing_medical_cert_expires_on"] == "2026-10-01"
