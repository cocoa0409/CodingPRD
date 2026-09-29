"""Version pinning, cascade bookkeeping and selector policy, layered on one another."""
from test_helpers import (
    ASSIGNMENT_ACTIVE,
    ASSIGNMENT_CANCELLED,
    BILLING_COVERAGE_VERIFIED,
    CLINIC_CLOSED,
    CLINIC_OPEN,
    CLOCK_START,
    CREDENTIAL_PA,
    PRESCRIPTION_DRAFT,
    ROLE_KIND_FLOAT,
    SAMPLED_RANDOM_SAMPLE,
    THERAPY_ANTIBIOTIC_MACROLIDE,
    ApiErrorId,
    add_walk_in,
    assert_instant_equal,
    closed_insured_visit,
    create_assignment,
    create_clinician,
    create_insured_patient,
    error_id,
    float_coverage_payload,
    prescription_payload,
    read_chart_review,
    read_clinic,
    read_clinician,
    read_physician,
    read_visit,
    run_sampling,
    set_clock,
    staffed_clinic,
    treated_visit,
    validate_error,
    validate_paginated,
    validate_success,
    verify_active_coverage,
    walk_in_payload,
)

SHIFT_END = "2026-08-01T23:00:00Z"


def _treated_visit_whose_version_has_been_read(api):
    """Vera Version is treated, and the client holds her visit's current version."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         physician={"full_name": "Dr Rowan"},
                         clinician={"full_name": "NP Rowan"})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Vera Version", date_of_birth="1973-03-23",
        payer_name="BlueCo", member_id="M-7777")
    env["patient"] = patient
    env["bundle"] = treated_visit(
        api, env, patient["id"],
        vitals={"temp_c": 37.2, "heart_rate_bpm": 76, "spo2_pct": 98})
    env["visit_id"] = env["bundle"]["visit_id"]
    env["version_1"] = read_visit(api, env["visit_id"])["version"]
    return env


def test_a_visit_version_one_behind_is_already_stale_for_a_prescription_draft(api):
    """Off by exactly one is refused; the freshly read number is accepted.

    PRD: "If that number does not equal the visit's current `version`, the creation is
    refused with `ERR_STALE_VISIT_VERSION` (HTTP 412) and the client must re-read the
    visit before retrying."

    Design: Corner/complexity_layers/corner_stale_expected_visit_version_refuses_the_prescription_draft
    """
    env = _treated_visit_whose_version_has_been_read(api)

    stale = api.create_prescription(
        prescription_payload(env["visit_id"], env["version_1"] - 1),
        env["clinician_headers"])
    fresh = validate_success(api.create_prescription(
        prescription_payload(env["visit_id"], env["version_1"]),
        env["clinician_headers"]), 201)

    validate_error(stale, ApiErrorId.ERR_STALE_VISIT_VERSION, 412)
    assert fresh["status"] == PRESCRIPTION_DRAFT


def test_the_eligibility_check_is_a_visit_write_that_stales_the_pinned_version(api):
    """A version that worked moments ago is refused once the desk touches the visit.

    PRD: "`version` is an integer that begins at 1 when the row is created and increases
    by exactly 1 on every mutation of that row, including mutations the server performs on
    its own initiative as part of a cascade rather than in response to a client request
    naming that row."

    Design: Corner/complexity_layers/corner_stale_expected_visit_version_refuses_the_prescription_draft
    """
    env = _treated_visit_whose_version_has_been_read(api)
    validate_success(api.create_prescription(
        prescription_payload(env["visit_id"], env["version_1"]),
        env["clinician_headers"]), 201)

    verified = verify_active_coverage(api, env, env["visit_id"], copay_cents=2000,
                                      coinsurance_pct=10.0)
    replayed = api.create_prescription(
        prescription_payload(env["visit_id"], env["version_1"],
                             drug_name="Azithromycin 250mg",
                             therapy_class=THERAPY_ANTIBIOTIC_MACROLIDE, days_supply=5),
        env["clinician_headers"])

    assert verified["billing_status"] == BILLING_COVERAGE_VERIFIED
    assert verified["version"] != env["version_1"]
    validate_error(replayed, ApiErrorId.ERR_STALE_VISIT_VERSION, 412)


def test_re_reading_the_visit_lets_the_second_draft_through_and_the_refusals_left_nothing(api):
    """Two 412s persisted no rows, so the visit ends with exactly two prescriptions.

    PRD: "Prescription creation requires `expected_visit_version`, carrying the client's
    last observed `version` of the visit named by `visit_id`."

    Design: Corner/complexity_layers/corner_stale_expected_visit_version_refuses_the_prescription_draft
    """
    env = _treated_visit_whose_version_has_been_read(api)
    api.create_prescription(prescription_payload(env["visit_id"], env["version_1"] - 1),
                            env["clinician_headers"])
    validate_success(api.create_prescription(
        prescription_payload(env["visit_id"], env["version_1"]),
        env["clinician_headers"]), 201)
    verify_active_coverage(api, env, env["visit_id"], copay_cents=2000,
                           coinsurance_pct=10.0)
    api.create_prescription(
        prescription_payload(env["visit_id"], env["version_1"],
                             drug_name="Azithromycin 250mg",
                             therapy_class=THERAPY_ANTIBIOTIC_MACROLIDE, days_supply=5),
        env["clinician_headers"])

    version_2 = read_visit(api, env["visit_id"])["version"]
    second = validate_success(api.create_prescription(
        prescription_payload(env["visit_id"], version_2,
                             drug_name="Azithromycin 250mg",
                             therapy_class=THERAPY_ANTIBIOTIC_MACROLIDE, days_supply=5),
        env["clinician_headers"]), 201)

    assert second["status"] == PRESCRIPTION_DRAFT
    _rows, meta = validate_paginated(
        api.list_prescriptions(env["admin"], {"visit_id": env["visit_id"]}))
    assert meta["total_count"] == 2


def _clinic_whose_only_shift_is_about_to_be_cancelled(api):
    """CA Store 78 is OPEN on one primary shift, with a float candidate in reserve."""
    env = staffed_clinic(api, with_protocol=False,
                         physician={"full_name": "Dr Sorrel"},
                         clinician={"full_name": "NP Sorrel Primary"})
    env["float_clinician"] = create_clinician(
        api, env["clinic_id"], env["physician_id"], env["admin"],
        full_name="NP Sorrel Float", float_eligible=True)
    clinic = read_clinic(api, env["clinic_id"])
    env["version_before"] = clinic["version"]
    env["posture_before"] = clinic["open_status"]
    return env


def _cancelled_shift_awaiting_its_cover(api):
    """The shift is gone, the site is dark, and the operator's clinic view is stale."""
    env = _clinic_whose_only_shift_is_about_to_be_cancelled(api)
    env["cancelled"] = validate_success(api.cancel_staffing_assignment(
        env["assignment_id"], env["admin"], cancel_reason="Ill"))
    clinic = read_clinic(api, env["clinic_id"])
    env["version_after_cancel"] = clinic["version"]
    env["posture_after_cancel"] = clinic["open_status"]
    return env


def test_the_clinic_version_read_before_the_cancellation_is_stale_for_coverage(api):
    """The four-hop closure cascade moved the very number the operator was holding.

    PRD: "If that number does not equal the clinic's current `version`, the creation is
    refused with `ERR_STALE_CLINIC_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/corner_the_cancel_cascade_makes_the_clinic_version_stale_before_the_coverage_guard
    """
    env = _cancelled_shift_awaiting_its_cover(api)
    assert env["posture_before"] == CLINIC_OPEN
    assert env["cancelled"]["status"] == ASSIGNMENT_CANCELLED

    response = api.create_float_coverage(
        env["clinic_id"],
        float_coverage_payload(env["assignment_id"], env["version_before"],
                               pinned_supervising_physician_id=env["physician_id"]),
        env["admin"])

    validate_error(response, ApiErrorId.ERR_STALE_CLINIC_VERSION, 412)
    assert env["version_after_cancel"] != env["version_before"]
    assert env["posture_after_cancel"] == CLINIC_CLOSED


def test_a_clinic_version_one_behind_the_cascaded_value_is_refused_too(api):
    """Only the exact post-cascade version buys the coverage through.

    PRD: "Float-coverage creation requires `expected_clinic_version`, carrying the
    client's last observed `version` of the clinic in the request path."

    Design: Corner/complexity_layers/corner_the_cancel_cascade_makes_the_clinic_version_stale_before_the_coverage_guard
    """
    env = _cancelled_shift_awaiting_its_cover(api)

    off_by_one = api.create_float_coverage(
        env["clinic_id"],
        float_coverage_payload(env["assignment_id"], env["version_after_cancel"] - 1,
                               pinned_supervising_physician_id=env["physician_id"]),
        env["admin"])
    covered = validate_success(api.create_float_coverage(
        env["clinic_id"],
        float_coverage_payload(env["assignment_id"], env["version_after_cancel"],
                               pinned_supervising_physician_id=env["physician_id"]),
        env["admin"]), 201)

    validate_error(off_by_one, ApiErrorId.ERR_STALE_CLINIC_VERSION, 412)
    assert covered["clinician_id"] == env["float_clinician"]["id"]
    assert covered["role_kind"] == ROLE_KIND_FLOAT


def test_replaying_the_accepted_clinic_version_answers_with_the_earlier_rung(api):
    """Version pinning is checked before coverage uniqueness, so 412 masks 409.

    PRD: "The ladder is evaluated top to bottom, and evaluation stops at the first
    failure."

    Design: Corner/complexity_layers/corner_the_cancel_cascade_makes_the_clinic_version_stale_before_the_coverage_guard
    """
    env = _cancelled_shift_awaiting_its_cover(api)
    validate_success(api.create_float_coverage(
        env["clinic_id"],
        float_coverage_payload(env["assignment_id"], env["version_after_cancel"],
                               pinned_supervising_physician_id=env["physician_id"]),
        env["admin"]), 201)

    replay = api.create_float_coverage(
        env["clinic_id"],
        float_coverage_payload(env["assignment_id"], env["version_after_cancel"],
                               pinned_supervising_physician_id=env["physician_id"]),
        env["admin"])

    validate_error(replay, ApiErrorId.ERR_STALE_CLINIC_VERSION, 412)
    assert error_id(replay) != "ERR_COVERAGE_ALREADY_EXISTS"


def test_the_coverage_reopens_the_site_and_bumps_the_clinic_version_again(api):
    """The FLOAT row activates inside the interval and the posture recovers to OPEN.

    PRD: "That new row is subject to the same double-booking, licensure and
    supervision-capacity rules as a hand-scheduled one, and it activates immediately when
    the logical clock already sits inside the interval — raising `on_duty_clinician_count`,
    possibly moving the posture `LIMITED → OPEN` or `CLOSED → LIMITED` or
    `CLOSED → OPEN`, and recomputing both the physician's `current_supervised_count` and
    the clinician's `active_assignment_count`."

    Design: Corner/complexity_layers/corner_the_cancel_cascade_makes_the_clinic_version_stale_before_the_coverage_guard
    """
    env = _cancelled_shift_awaiting_its_cover(api)

    validate_success(api.create_float_coverage(
        env["clinic_id"],
        float_coverage_payload(env["assignment_id"], env["version_after_cancel"],
                               pinned_supervising_physician_id=env["physician_id"]),
        env["admin"]), 201)

    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["version"] != env["version_after_cancel"]
    assert clinic["open_status"] == CLINIC_OPEN
    assert clinic["on_duty_clinician_count"] == 1
    _rows, meta = validate_paginated(api.list_staffing_assignments(
        env["admin"], {"clinic_id": env["clinic_id"], "role_kind": ROLE_KIND_FLOAT}))
    assert meta["total_count"] == 1


def _unstaffed_clinic_with_room_for_one_walk_in(api):
    """CA Store 79 has nobody on duty yet and a walk-in capacity of exactly one."""
    env = staffed_clinic(api, staff=False, protocol={"requires_cosign": False},
                         clinic={"walk_in_queue_capacity": 1},
                         physician={"full_name": "Dr Thistle"},
                         clinician={"full_name": "NP Thistle"})
    env["ida"] = create_insured_patient(
        api, env["front_desk"], full_name="Ida Idle", date_of_birth="1972-02-22",
        payer_name="BlueCo", member_id="M-7979")
    env["ody"] = create_insured_patient(
        api, env["front_desk"], full_name="Ody Overflow", date_of_birth="1971-01-21",
        payer_name="BlueCo", member_id="M-7980")
    env["version_create"] = read_clinic(api, env["clinic_id"])["version"]
    return env


def _clinic_open_on_one_activated_shift(api):
    """The shift is filed inside the current interval, so the site opens at once."""
    env = _unstaffed_clinic_with_room_for_one_walk_in(api)
    env["assignment"] = create_assignment(
        api, env["clinic_id"], env["clinician_id"], env["admin"],
        starts_at=CLOCK_START, ends_at=SHIFT_END,
        pinned_supervising_physician_id=env["physician_id"])
    env["version_staffed"] = read_clinic(api, env["clinic_id"])["version"]
    return env


def _clinic_with_its_single_walk_in_waiting(api):
    """Ida is in the waiting room, which fills the site's capacity of one."""
    env = _clinic_open_on_one_activated_shift(api)
    env["entry"] = add_walk_in(api, env, env["ida"]["id"])
    clinic = read_clinic(api, env["clinic_id"])
    env["version_queued"] = clinic["version"]
    env["posted_queued"] = clinic["posted_wait_minutes"]
    return env


def test_two_consecutive_clinic_reads_do_not_move_the_version_but_a_shift_does(api):
    """Reading is not mutating; activating the first shift is.

    PRD: "`version` is an integer that begins at 1 when the row is created and increases
    by exactly 1 on every mutation of that row, including mutations the server performs on
    its own initiative as part of a cascade rather than in response to a client request
    naming that row."

    Design: Corner/complexity_layers/corner_clinic_version_advances_on_every_derived_write_and_never_on_a_read
    """
    env = _unstaffed_clinic_with_room_for_one_walk_in(api)

    first_read = read_clinic(api, env["clinic_id"])
    second_read = read_clinic(api, env["clinic_id"])
    assignment = create_assignment(
        api, env["clinic_id"], env["clinician_id"], env["admin"],
        starts_at=CLOCK_START, ends_at=SHIFT_END,
        pinned_supervising_physician_id=env["physician_id"])

    assert first_read["version"] == env["version_create"]
    assert second_read["version"] == first_read["version"]
    assert assignment["status"] == ASSIGNMENT_ACTIVE
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["version"] > env["version_create"]
    assert clinic["on_duty_clinician_count"] == 1
    assert clinic["open_status"] == CLINIC_OPEN


def test_an_admitted_walk_in_bumps_the_version_and_posts_twenty_minutes(api):
    """One patient over one clinician projects a single twenty-minute visit.

    PRD: "The posted wait takes the clinic's current `waiting_count`, divides it by the
    number of clinicians on duty — using 1 as the divisor whenever
    `on_duty_clinician_count` is 0, so the arithmetic never breaks — and rounds that
    quotient **up** to a whole number of patients per clinician. That rounded-up figure is
    multiplied by 20 minutes, the average visit length."

    Design: Corner/complexity_layers/corner_clinic_version_advances_on_every_derived_write_and_never_on_a_read
    """
    env = _clinic_with_its_single_walk_in_waiting(api)

    assert env["version_queued"] > env["version_staffed"]
    assert env["posted_queued"] == 20


def test_a_walk_in_refused_for_capacity_leaves_the_clinic_version_untouched(api):
    """A rejected write is not a write, so the derived readings must not move.

    PRD: "And the site must have room: the number of that clinic's entries whose `kind` is
    `WALK_IN` and whose status is `WAITING` must be strictly below
    `walk_in_queue_capacity`, else the intake is refused with
    `ERR_QUEUE_CAPACITY_REACHED`."

    Design: Corner/complexity_layers/corner_clinic_version_advances_on_every_derived_write_and_never_on_a_read
    """
    env = _clinic_with_its_single_walk_in_waiting(api)

    response = api.create_queue_entry(
        walk_in_payload(env["clinic_id"], env["ody"]["id"]), env["front_desk"])

    validate_error(response, ApiErrorId.ERR_QUEUE_CAPACITY_REACHED, 409)
    assert read_clinic(api, env["clinic_id"])["version"] == env["version_queued"]


def test_calling_the_waiting_patient_bumps_the_version_and_records_the_realized_wait(api):
    """The call empties the waiting room and measures a wait of zero whole minutes.

    PRD: "The clinic's `last_realized_wait_minutes` is then set to the value just
    measured, its `waiting_count` falls by 1, and `posted_wait_minutes` is recomputed."

    Design: Corner/complexity_layers/corner_clinic_version_advances_on_every_derived_write_and_never_on_a_read
    """
    env = _clinic_with_its_single_walk_in_waiting(api)

    called = validate_success(api.call_next(env["clinic_id"], env["clinician_headers"]))

    assert called["id"] == env["entry"]["id"]
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["version"] > env["version_queued"]
    assert clinic["waiting_count"] == 0
    assert clinic["last_realized_wait_minutes"] == 0


def _two_tied_float_candidates_at_a_dark_clinic(api):
    """Both floats are homed here with no shifts, so only created_at separates them."""
    env = staffed_clinic(api, with_protocol=False,
                         state={"max_supervised_clinicians_per_physician": 4},
                         physician={"full_name": "Dr Umber",
                                    "max_supervised_clinicians": 4},
                         clinician={"full_name": "NP Umber Primary"})
    env["early"] = create_clinician(
        api, env["clinic_id"], env["physician_id"], env["admin"],
        full_name="NP Umber Float Early", float_eligible=True)
    env["late"] = create_clinician(
        api, env["clinic_id"], env["physician_id"], env["admin"],
        full_name="NP Umber Float Late", credential=CREDENTIAL_PA, float_eligible=True)
    validate_success(api.cancel_staffing_assignment(
        env["assignment_id"], env["admin"], cancel_reason="Jury duty"))
    env["clinic_version"] = read_clinic(api, env["clinic_id"])["version"]
    return env


def _coverage_awarded_between_the_tied_candidates(api):
    """The server picks the cover itself; nobody nominated a substitute."""
    env = _two_tied_float_candidates_at_a_dark_clinic(api)
    env["coverage"] = validate_success(api.create_float_coverage(
        env["clinic_id"],
        float_coverage_payload(env["assignment_id"], env["clinic_version"],
                               pinned_supervising_physician_id=env["physician_id"]),
        env["admin"]), 201)
    return env


def test_the_earlier_registered_float_candidate_wins_the_tie(api):
    """Home site and assignment count tie, so the older row takes the shift.

    PRD: "Surviving candidates are ranked with the clinician's home site first — those
    whose `home_clinic_id` equals the clinic being covered rank ahead of everyone else —
    then by ascending `active_assignment_count`, then by ascending `created_at`; the first
    candidate after that ranking wins, and the clinician's `id` never participates in the
    ordering."

    Design: Corner/complexity_layers/corner_float_selector_breaks_the_tie_on_created_at_and_never_on_id
    """
    env = _coverage_awarded_between_the_tied_candidates(api)

    assert env["coverage"]["clinician_id"] == env["early"]["id"]
    assert read_clinician(api, env["early"]["id"])["active_assignment_count"] == 1
    assert read_clinician(api, env["late"]["id"])["active_assignment_count"] == 0


def test_the_float_row_spans_the_covered_shift_exactly_and_activates(api):
    """The covering assignment inherits the interval it is covering, to the second.

    PRD: "The winner receives a new assignment with `role_kind` of `FLOAT` spanning
    exactly the covered shift's interval, pointing back at the covered row through
    `covers_assignment_id`."

    Design: Corner/complexity_layers/corner_float_selector_breaks_the_tie_on_created_at_and_never_on_id
    """
    env = _coverage_awarded_between_the_tied_candidates(api)

    coverage = env["coverage"]

    assert coverage["role_kind"] == ROLE_KIND_FLOAT
    assert coverage["covers_assignment_id"] == env["assignment_id"]
    assert_instant_equal(coverage["starts_at"], CLOCK_START)
    assert_instant_equal(coverage["ends_at"], SHIFT_END)
    assert coverage["status"] == ASSIGNMENT_ACTIVE


def test_the_cover_reopens_the_site_and_carries_the_supervision_load(api):
    """The cancelled primary stops counting and the float takes its place.

    PRD: "A physician's `current_supervised_count` is the number of **distinct**
    clinicians appearing on assignments that name that physician as pinned supervisor and
    sit in `SCHEDULED` or `ACTIVE` status; two shifts for the same clinician under the same
    physician count once, and `CANCELLED` or `COMPLETED` assignments are excluded
    entirely."

    Design: Corner/complexity_layers/corner_float_selector_breaks_the_tie_on_created_at_and_never_on_id
    """
    env = _coverage_awarded_between_the_tied_candidates(api)

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["open_status"] == CLINIC_OPEN
    assert clinic["on_duty_clinician_count"] == 1
    assert read_physician(api, env["physician_id"])["current_supervised_count"] == 1


WINDOW_00 = "2026-08-01T00:00:00Z"
WINDOW_01 = "2026-08-01T01:00:00Z"
WINDOW_02 = "2026-08-01T02:00:00Z"


def _two_closed_charts_created_an_hour_apart(api):
    """Ava's chart is closed at 00:00 and Bo's at 01:00, on the same shift."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         physician={"full_name": "Dr Verbena"},
                         clinician={"full_name": "NP Verbena"})
    ava = create_insured_patient(
        api, env["front_desk"], full_name="Ava Adjacent", date_of_birth="1975-05-15",
        payer_name="BlueCo", member_id="M-8181")
    bo = create_insured_patient(
        api, env["front_desk"], full_name="Bo Border", date_of_birth="1974-04-14",
        payer_name="BlueCo", member_id="M-8182")
    env["visit_a"] = closed_insured_visit(
        api, env, ava["id"], services_rendered=[], copay_cents=2000,
        coinsurance_pct=10.0)["visit_id"]
    set_clock(api, WINDOW_01, env["admin"])
    env["visit_b"] = closed_insured_visit(
        api, env, bo["id"], services_rendered=[], copay_cents=2000,
        coinsurance_pct=10.0)["visit_id"]
    return env


def test_each_adjacent_window_samples_exactly_the_chart_created_inside_it(api):
    """A visit created at 01:00 belongs to the later window, never to the earlier one.

    PRD: "The run supplies `window_start` and `window_end`, and the period is half-open: a
    visit qualifies when its `created_at` is at or after `window_start` and strictly before
    `window_end`."

    Design: Corner/complexity_layers/corner_two_adjacent_sampling_runs_partition_the_visits_without_overlap
    """
    env = _two_closed_charts_created_an_hour_apart(api)

    run_a = run_sampling(api, env["clinic_id"], WINDOW_00, WINDOW_01,
                         headers=env["admin"])
    run_b = run_sampling(api, env["clinic_id"], WINDOW_01, WINDOW_02,
                         headers=env["admin"])

    assert run_a["sampled_count"] == 1
    assert run_b["sampled_count"] == 1
    assert read_chart_review(api, run_a["chart_review_ids"][0])["visit_id"] == (
        env["visit_a"])
    assert read_chart_review(api, run_b["chart_review_ids"][0])["visit_id"] == (
        env["visit_b"])


def test_a_run_spanning_both_windows_samples_nothing_at_all(api):
    """Already-reviewed charts drop out of the eligible population for good.

    PRD: "Visits sitting in `SCREENING`, `IN_ASSESSMENT`, `TREATED`, `REFERRED` or
    `CANCELLED_CLOSURE` are all excluded, and because already-reviewed visits are excluded,
    re-running the sampler over an overlapping window never re-samples the same chart."

    Design: Corner/complexity_layers/corner_two_adjacent_sampling_runs_partition_the_visits_without_overlap
    """
    env = _two_closed_charts_created_an_hour_apart(api)
    run_a = run_sampling(api, env["clinic_id"], WINDOW_00, WINDOW_01,
                         headers=env["admin"])
    run_b = run_sampling(api, env["clinic_id"], WINDOW_01, WINDOW_02,
                         headers=env["admin"])

    run_c = run_sampling(api, env["clinic_id"], WINDOW_00, WINDOW_02,
                         headers=env["admin"])

    assert run_c["sampled_count"] == 0
    assert run_c["chart_review_ids"] == []
    assert run_a["chart_review_ids"][0] != run_b["chart_review_ids"][0]
    _rows, meta = validate_paginated(api.list_chart_reviews(env["admin"]))
    assert meta["total_count"] == 2


def test_both_reviews_are_due_seventy_two_hours_after_the_run_instant(api):
    """The deadline is anchored on the clock at sampling, not on each visit's creation.

    PRD: "Every chart the run selects becomes a review in `PENDING` status recording the
    `visit_id` sampled, the `assessment_id` under review, a `reviewer_physician_id` taken
    from the treating clinician's `supervising_physician_id`, the `sampled_reason`
    established above, and a `due_at` computed as the logical clock at the moment of
    sampling plus the state rule's `review_deadline_hours`."

    Design: Corner/complexity_layers/corner_two_adjacent_sampling_runs_partition_the_visits_without_overlap
    """
    env = _two_closed_charts_created_an_hour_apart(api)

    run_a = run_sampling(api, env["clinic_id"], WINDOW_00, WINDOW_01,
                         headers=env["admin"])
    run_b = run_sampling(api, env["clinic_id"], WINDOW_01, WINDOW_02,
                         headers=env["admin"])

    review_a = read_chart_review(api, run_a["chart_review_ids"][0])
    review_b = read_chart_review(api, run_b["chart_review_ids"][0])
    assert_instant_equal(review_a["due_at"], "2026-08-04T01:00:00Z")
    assert_instant_equal(review_b["due_at"], "2026-08-04T01:00:00Z")
    assert review_a["sampled_reason"] == SAMPLED_RANDOM_SAMPLE
