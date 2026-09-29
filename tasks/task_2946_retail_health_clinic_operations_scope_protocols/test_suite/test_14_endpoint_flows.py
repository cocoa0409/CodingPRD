"""Action endpoints whose single call moves several rows at once.

Arrival converts a booking into queue presence; float coverage drafts a
substitute only against a cancelled, uncovered shift; and a second sampling run
over the same window finds nothing left to draw.
"""
from test_helpers import (
    ASSIGNMENT_ACTIVE,
    ASSIGNMENT_CANCELLED,
    CLINIC_CLOSED,
    CLINIC_OPEN,
    CREDENTIAL_PA,
    QUEUE_SCHEDULED,
    QUEUE_WAITING,
    ROLE_KIND_FLOAT,
    ApiErrorId,
    add_appointment,
    arrive,
    assert_instant_equal,
    closed_insured_visit,
    create_clinician,
    create_insured_patient,
    create_patient,
    float_coverage_payload,
    read_clinic,
    read_clinician,
    read_queue_entry,
    run_sampling,
    staffed_clinic,
    validate_error,
    validate_paginated,
    validate_success,
    validate_unpaginated,
)

APPOINTMENT_SLOT = "2026-08-01T00:10:00Z"
SAMPLING_WINDOW_START = "2026-08-01T00:00:00Z"
SAMPLING_WINDOW_END = "2026-08-02T00:00:00Z"


# ---------------------------------------------------------------------------
# Appointment arrival: the on-time bonus and the posted wait
# ---------------------------------------------------------------------------

def _a_booking_ten_minutes_out_at_an_open_site(api):
    """One tier-2 appointment booked for 00:10 while the clock still reads 00:00."""
    env = staffed_clinic(api)
    patient = create_patient(api, env["front_desk"], full_name="Ann Arrival",
                             date_of_birth="1989-09-09")
    env["patient"] = patient
    env["entry"] = add_appointment(api, env, patient["id"], APPOINTMENT_SLOT)
    env["clinic_before"] = read_clinic(api, env["clinic_id"])
    return env


def test_a_booking_that_has_not_arrived_scores_its_acuity_alone(api):
    """Tier 2 earns 200 and nothing else, because arrived_at is still null.

    PRD: "**Punctuality** contributes a flat 250 points when the entry's `kind` is
    `APPOINTMENT`, its `arrived_at` is set, and that arrival instant is no later than
    its `scheduled_at` plus 10 minutes of grace; a walk-in, an un-arrived appointment,
    or an appointment that arrived more than 10 minutes late contributes 0 from this
    component."

    Design: Corner/endpoints/corner_appointment_arrival_awards_the_on_time_bonus_and_lifts_the_wait
    """
    env = _a_booking_ten_minutes_out_at_an_open_site(api)

    entry = env["entry"]

    assert entry["status"] == QUEUE_SCHEDULED
    assert entry["arrived_at"] is None
    assert entry["acuity_tier"] == 2
    assert entry["priority_score"] == 200
    assert env["clinic_before"]["waiting_count"] == 0


def test_arrival_stamps_the_logical_clock_and_awards_the_on_time_bonus(api):
    """Arriving at 00:00 against a 00:10 slot lifts the score from 200 to 450.

    PRD: "On success `arrived_at` is stamped with the logical clock, `priority_score`
    is computed with the on-time bonus available, `waiting_count` rises by 1, and
    `posted_wait_minutes` is recomputed."

    Design: Corner/endpoints/corner_appointment_arrival_awards_the_on_time_bonus_and_lifts_the_wait
    """
    env = _a_booking_ten_minutes_out_at_an_open_site(api)

    arrived = arrive(api, env["entry"]["id"], env["front_desk"])

    assert arrived["status"] == QUEUE_WAITING
    assert_instant_equal(arrived["arrived_at"], "2026-08-01T00:00:00Z")
    assert arrived["priority_score"] == 450
    assert read_queue_entry(api, env["entry"]["id"])["priority_score"] == 450


def test_the_arrived_entry_leaves_the_blend_term_and_joins_the_waiting_depth(api):
    """One patient waiting against one clinician posts a flat 20 minutes.

    PRD: "That rounded-up figure is multiplied by 20 minutes, the average visit
    length."

    Design: Corner/endpoints/corner_appointment_arrival_awards_the_on_time_bonus_and_lifts_the_wait
    """
    env = _a_booking_ten_minutes_out_at_an_open_site(api)

    arrive(api, env["entry"]["id"], env["front_desk"])

    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["waiting_count"] == 1
    assert clinic["on_duty_clinician_count"] == 1
    assert clinic["open_status"] == CLINIC_OPEN
    assert clinic["posted_wait_minutes"] == 20


def test_arrival_is_not_a_call_so_no_realized_wait_is_reported(api):
    """The site has admitted a patient but nobody has been called, so the field is null.

    PRD: "Until the first patient at a site is ever called, both the entry-level
    `realized_wait_minutes` and the clinic-level `last_realized_wait_minutes` remain
    null."

    Design: Corner/endpoints/corner_appointment_arrival_awards_the_on_time_bonus_and_lifts_the_wait
    """
    env = _a_booking_ten_minutes_out_at_an_open_site(api)

    arrive(api, env["entry"]["id"], env["front_desk"])

    assert read_clinic(api, env["clinic_id"])["last_realized_wait_minutes"] is None
    assert read_queue_entry(api, env["entry"]["id"])["realized_wait_minutes"] is None


# ---------------------------------------------------------------------------
# Float coverage: both halves of the cancelled-and-uncovered guard
# ---------------------------------------------------------------------------

def _an_active_shift_with_one_float_candidate_on_site(api):
    """NP Primary Ash works [00:00, 23:00); NP Float Ash is idle and float-eligible."""
    env = staffed_clinic(api, with_protocol=False,
                         clinic={"name": "CA Store 58"},
                         physician={"full_name": "Dr Ash"},
                         clinician={"full_name": "NP Primary Ash"})
    env["float_clinician"] = create_clinician(
        api, env["clinic_id"], env["physician_id"], env["admin"],
        full_name="NP Float Ash", float_eligible=True)
    return env


def _cover(api, env, expected_version):
    """Ask the server to draft a substitute for the cancelled primary shift."""
    payload = float_coverage_payload(
        env["assignment_id"], expected_version,
        pinned_supervising_physician_id=env["physician_id"])
    return api.create_float_coverage(env["clinic_id"], payload, env["admin"])


def test_covering_a_shift_that_is_still_active_is_refused(api):
    """The substitute request is well formed; the covered shift has not been cancelled.

    PRD: "Float coverage may only be created against a cancelled assignment that no
    other float assignment already covers, else `ERR_COVERAGE_ALREADY_EXISTS` (409)."

    Design: Corner/endpoints/corner_float_coverage_requires_a_cancelled_uncovered_assignment
    """
    env = _an_active_shift_with_one_float_candidate_on_site(api)
    assert env["assignment"]["status"] == ASSIGNMENT_ACTIVE

    response = _cover(api, env, read_clinic(api, env["clinic_id"])["version"])

    validate_error(response, ApiErrorId.ERR_COVERAGE_ALREADY_EXISTS, 409)
    rows, meta = validate_paginated(api.list_staffing_assignments(
        env["admin"], params={"clinic_id": env["clinic_id"],
                              "role_kind": ROLE_KIND_FLOAT}))
    assert meta["total_count"] == 0
    assert rows == []


def test_the_first_cover_after_cancellation_drafts_the_float_eligible_clinician(api):
    """The server picks NP Float Ash itself and files the row as FLOAT.

    PRD: "The winner receives a new assignment with `role_kind` of `FLOAT` spanning
    exactly the covered shift's interval, pointing back at the covered row through
    `covers_assignment_id`."

    Design: Corner/endpoints/corner_float_coverage_requires_a_cancelled_uncovered_assignment
    """
    env = _an_active_shift_with_one_float_candidate_on_site(api)
    cancelled = validate_success(api.cancel_staffing_assignment(
        env["assignment_id"], env["admin"], cancel_reason="Family emergency"))
    assert cancelled["status"] == ASSIGNMENT_CANCELLED

    covered = validate_success(
        _cover(api, env, read_clinic(api, env["clinic_id"])["version"]), 201)

    assert covered["clinician_id"] == env["float_clinician"]["id"]
    assert covered["role_kind"] == ROLE_KIND_FLOAT
    assert covered["covers_assignment_id"] == env["assignment_id"]


def test_the_covering_shift_brings_the_site_back_on_duty(api):
    """The FLOAT row activates at once because the clock already sits inside it.

    PRD: "That new row is subject to the same double-booking, licensure and
    supervision-capacity rules as a hand-scheduled one, and it activates immediately
    when the logical clock already sits inside the interval — raising
    `on_duty_clinician_count`, possibly moving the posture `LIMITED → OPEN` or
    `CLOSED → LIMITED` or `CLOSED → OPEN`, and recomputing both the physician's
    `current_supervised_count` and the clinician's `active_assignment_count`."

    Design: Corner/endpoints/corner_float_coverage_requires_a_cancelled_uncovered_assignment
    """
    env = _an_active_shift_with_one_float_candidate_on_site(api)
    validate_success(api.cancel_staffing_assignment(
        env["assignment_id"], env["admin"], cancel_reason="Family emergency"))

    covered = validate_success(
        _cover(api, env, read_clinic(api, env["clinic_id"])["version"]), 201)

    assert covered["status"] == ASSIGNMENT_ACTIVE
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["on_duty_clinician_count"] == 1
    assert clinic["open_status"] == CLINIC_OPEN


def test_a_second_cover_of_the_same_cancelled_shift_never_stacks_a_float_row(api):
    """Coverage is not idempotent: the repeat is refused and only one FLOAT row exists.

    PRD: "The coverage request names `covers_assignment_id` — which must point at an
    assignment in `CANCELLED` status that no other `FLOAT` assignment already covers,
    else `ERR_COVERAGE_ALREADY_EXISTS` — together with `expected_clinic_version` as
    described in §2.6, and optionally a `pinned_supervising_physician_id` for the
    covering shift."

    Design: Corner/endpoints/corner_float_coverage_requires_a_cancelled_uncovered_assignment
    """
    env = _an_active_shift_with_one_float_candidate_on_site(api)
    validate_success(api.cancel_staffing_assignment(
        env["assignment_id"], env["admin"], cancel_reason="Family emergency"))
    validate_success(_cover(api, env, read_clinic(api, env["clinic_id"])["version"]), 201)

    response = _cover(api, env, read_clinic(api, env["clinic_id"])["version"])

    validate_error(response, ApiErrorId.ERR_COVERAGE_ALREADY_EXISTS, 409)
    _, meta = validate_paginated(api.list_staffing_assignments(
        env["admin"], params={"clinic_id": env["clinic_id"],
                              "role_kind": ROLE_KIND_FLOAT}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Float coverage with an empty candidate set
# ---------------------------------------------------------------------------

def _a_closed_site_whose_only_spare_clinician_is_not_float_eligible(api):
    """The primary shift is cancelled and the one other clinician was never flagged."""
    env = staffed_clinic(api, with_protocol=False,
                         clinic={"name": "CA Store 59"},
                         physician={"full_name": "Dr Birch"},
                         clinician={"full_name": "NP Primary Birch"})
    env["other_clinician"] = create_clinician(
        api, env["clinic_id"], env["physician_id"], env["admin"],
        full_name="NP Not Float Birch", credential=CREDENTIAL_PA)
    env["cancelled"] = validate_success(api.cancel_staffing_assignment(
        env["assignment_id"], env["admin"], cancel_reason="Storm closure"))
    env["clinic_after_cancel"] = read_clinic(api, env["clinic_id"])
    return env


def test_the_spare_clinician_carries_the_default_float_flag(api):
    """Registering without the flag leaves float_eligible false, never coerced true.

    PRD: "The optional `float_eligible` flag defaults to false; when true, the
    clinician becomes a candidate for covering shifts at other sites in the same
    state."

    Design: Corner/endpoints/corner_float_coverage_with_no_eligible_clinician_returns_no_coverage_available
    """
    env = _a_closed_site_whose_only_spare_clinician_is_not_float_eligible(api)

    other = read_clinician(api, env["other_clinician"]["id"])

    assert other["float_eligible"] is False
    assert other["scope_hold"] is False
    assert env["clinic_after_cancel"]["open_status"] == CLINIC_CLOSED
    assert env["clinic_after_cancel"]["on_duty_clinician_count"] == 0


def test_coverage_with_no_surviving_candidate_is_refused(api):
    """No clinician is float-eligible, so the candidate set is empty before ranking.

    PRD: "When no candidate survives the filters, the request is refused with
    `ERR_NO_FLOAT_COVERAGE_AVAILABLE`."

    Design: Corner/endpoints/corner_float_coverage_with_no_eligible_clinician_returns_no_coverage_available
    """
    env = _a_closed_site_whose_only_spare_clinician_is_not_float_eligible(api)

    response = _cover(api, env, env["clinic_after_cancel"]["version"])

    validate_error(response, ApiErrorId.ERR_NO_FLOAT_COVERAGE_AVAILABLE, 409)


def test_the_refused_coverage_drafts_nobody_and_leaves_the_site_closed(api):
    """An ineligible clinician is never silently drafted onto the empty floor.

    PRD: "When the on-duty count is 0 the posture is `CLOSED`."

    Design: Corner/endpoints/corner_float_coverage_with_no_eligible_clinician_returns_no_coverage_available
    """
    env = _a_closed_site_whose_only_spare_clinician_is_not_float_eligible(api)

    _cover(api, env, env["clinic_after_cancel"]["version"])

    _, meta = validate_paginated(api.list_staffing_assignments(
        env["admin"], params={"clinic_id": env["clinic_id"],
                              "role_kind": ROLE_KIND_FLOAT}))
    assert meta["total_count"] == 0
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["open_status"] == CLINIC_CLOSED
    assert clinic["on_duty_clinician_count"] == 0
    assert read_clinician(api, env["other_clinician"]["id"])[
        "active_assignment_count"] == 0


# ---------------------------------------------------------------------------
# A second sampling run over an already-sampled window
# ---------------------------------------------------------------------------

def _one_closed_chart_inside_the_day_window(api):
    """Exactly one insured visit is CLOSED and assessed inside [00:00, next 00:00)."""
    env = staffed_clinic(api, clinic={"name": "CA Store 60"},
                         protocol={"requires_cosign": False},
                         physician={"full_name": "Dr Cedarwood"},
                         clinician={"full_name": "NP Cedarwood"})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Sol Single", date_of_birth="1982-12-02",
        payer_name="BlueCo", member_id="M-3333", pcp_consent_on_file=False)
    env["patient"] = patient
    env["bundle"] = closed_insured_visit(
        api, env, patient["id"], services_rendered=[],
        vitals={"temp_c": 37.0, "heart_rate_bpm": 76, "spo2_pct": 99})
    env["visit_id"] = env["bundle"]["visit_id"]
    return env


def test_the_first_run_over_the_day_draws_the_single_eligible_chart(api):
    """One eligible visit at a 40 percent rate rounds up to a target of one.

    PRD: "The size of the run comes from the state rule: multiply the number of
    eligible visits by `chart_review_sample_pct`, divide by 100, and round the result
    **up** to a whole number to obtain the target total."

    Design: Corner/endpoints/corner_second_sampling_run_over_the_same_window_samples_nothing
    """
    env = _one_closed_chart_inside_the_day_window(api)

    run = run_sampling(api, env["clinic_id"], SAMPLING_WINDOW_START,
                       SAMPLING_WINDOW_END, headers=env["physician_headers"])

    assert run["sampled_count"] == 1
    assert run["mandatory_count"] == 0
    assert run["random_count"] == 1
    assert len(run["chart_review_ids"]) == 1


def test_the_second_run_over_the_identical_window_samples_nothing(api):
    """Zero eligible charts answer with three zeros and an empty list, not an error.

    PRD: "Visits sitting in `SCREENING`, `IN_ASSESSMENT`, `TREATED`, `REFERRED` or
    `CANCELLED_CLOSURE` are all excluded, and because already-reviewed visits are
    excluded, re-running the sampler over an overlapping window never re-samples the
    same chart."

    Design: Corner/endpoints/corner_second_sampling_run_over_the_same_window_samples_nothing
    """
    env = _one_closed_chart_inside_the_day_window(api)
    run_sampling(api, env["clinic_id"], SAMPLING_WINDOW_START, SAMPLING_WINDOW_END,
                 headers=env["physician_headers"])

    response = api.run_chart_review_sampling(
        env["clinic_id"], SAMPLING_WINDOW_START, SAMPLING_WINDOW_END,
        env["physician_headers"])

    assert response.status_code == 200
    second = validate_unpaginated(response)
    assert second["sampled_count"] == 0
    assert second["mandatory_count"] == 0
    assert second["random_count"] == 0
    assert second["chart_review_ids"] == []


def test_the_repeated_run_leaves_exactly_one_review_on_the_visit(api):
    """The eligible set excluded the visit, so no duplicate review was minted.

    PRD: "The eligible population is narrow by design — visits at that clinic whose
    `clinical_status` is `CLOSED`, created inside the window, that have an assessment,
    and that no chart review already covers."

    Design: Corner/endpoints/corner_second_sampling_run_over_the_same_window_samples_nothing
    """
    env = _one_closed_chart_inside_the_day_window(api)
    first = run_sampling(api, env["clinic_id"], SAMPLING_WINDOW_START,
                         SAMPLING_WINDOW_END, headers=env["physician_headers"])
    run_sampling(api, env["clinic_id"], SAMPLING_WINDOW_START, SAMPLING_WINDOW_END,
                 headers=env["physician_headers"])

    rows, meta = validate_paginated(api.list_chart_reviews(
        env["admin"], params={"visit_id": env["visit_id"]}))

    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == first["chart_review_ids"]
