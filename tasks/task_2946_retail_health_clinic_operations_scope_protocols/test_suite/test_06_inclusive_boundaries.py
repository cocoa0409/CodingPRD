"""Inclusive thresholds: an age exactly at the floor, and a half-open empty window."""
from test_helpers import (
    COMPLAINT_EAR_PAIN,
    QUEUE_CALLED,
    QUEUE_SERVED,
    REVIEW_PENDING,
    VISIT_SCREENING,
    ApiErrorId,
    add_walk_in,
    call_next,
    checkout,
    create_insured_patient,
    create_patient,
    read_chart_review,
    read_queue_entry,
    run_sampling,
    staffed_clinic,
    start_visit,
    treated_visit,
    validate_error,
    verify_active_coverage,
    visit_payload,
)

EAR_PAIN_PROTOCOL = {
    "complaint_code": COMPLAINT_EAR_PAIN,
    "min_age_months": 12,
    "base_price_cents": 8500,
    "acuity_tier": 1,
    "red_flag_codes": ["MASTOID_SWELLING"],
    "max_heart_rate_bpm": 150,
    "requires_cosign": False,
}


def _two_called_toddlers(api):
    """One toddler exactly 24 months old and one a month younger, both CALLED."""
    env = staffed_clinic(api, protocol=EAR_PAIN_PROTOCOL)
    env["called"] = {}
    for key, name, birth in (("exact", "Exact Toddler", "2024-08-01"),
                             ("under", "Under Toddler", "2024-09-01")):
        patient = create_patient(api, env["front_desk"], full_name=name,
                                 date_of_birth=birth)
        entry = add_walk_in(api, env, patient["id"],
                            complaint_code=COMPLAINT_EAR_PAIN)
        call_next(api, env)
        env["called"][key] = {"patient": patient, "entry": entry}
    return env


def test_a_patient_exactly_at_the_effective_age_floor_is_seen(api):
    """24 whole months against a floor of max(12, 24) is admitted, not refused.

    PRD: "Both bounds are inclusive: an age exactly equal to the effective floor is
    eligible, and so is an age exactly equal to the ceiling."

    Design: Difficulty/boundary_precision_check/visit_age_lower_bound_inclusive_at_exactly_24_months
    """
    env = _two_called_toddlers(api)

    visit = start_visit(api, env, env["called"]["exact"]["entry"]["id"])

    assert visit["patient_age_months_at_visit"] == 24
    assert visit["clinical_status"] == VISIT_SCREENING


def test_the_admitted_visit_consumes_its_called_entry(api):
    """The entry the visit was opened against advances to SERVED.

    PRD: "The visit copies its `clinic_id`, its `patient_id` and its `complaint_code`
    from the entry it consumes, and the consumed entry advances `CALLED → SERVED` in
    the same request."

    Design: Difficulty/boundary_precision_check/visit_age_lower_bound_inclusive_at_exactly_24_months
    """
    env = _two_called_toddlers(api)

    start_visit(api, env, env["called"]["exact"]["entry"]["id"])

    entry = read_queue_entry(api, env["called"]["exact"]["entry"]["id"])
    assert entry["status"] == QUEUE_SERVED


def test_a_patient_one_month_short_of_the_floor_is_out_of_scope(api):
    """23 months is below the floor, so no visit opens and the entry stays CALLED.

    PRD: "An age below the floor or above the ceiling is out of scope for retail care
    and the visit is refused with `ERR_OUT_OF_PROTOCOL_SCOPE`."

    Design: Difficulty/boundary_precision_check/visit_age_lower_bound_inclusive_at_exactly_24_months
    """
    env = _two_called_toddlers(api)
    entry_id = env["called"]["under"]["entry"]["id"]

    response = api.create_visit(visit_payload(entry_id), env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_OUT_OF_PROTOCOL_SCOPE, 422)
    assert read_queue_entry(api, entry_id)["status"] == QUEUE_CALLED


def _one_closed_chart_at_the_startup_instant(api):
    """A single CLOSED, assessed visit created while the clock reads the default."""
    env = staffed_clinic(api, protocol={"requires_cosign": False})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Zoe Zero", date_of_birth="1977-03-03",
        payer_name="Aetna", member_id="M-6006", pcp_consent_on_file=False)
    bundle = treated_visit(api, env, patient["id"],
                           vitals={"temp_c": 37.4, "heart_rate_bpm": 82,
                                   "spo2_pct": 97})
    verify_active_coverage(api, env, bundle["visit_id"], copay_cents=2500,
                           coinsurance_pct=12.5)
    checkout(api, env, bundle["visit_id"], services_rendered=[])
    env["patient"] = patient
    env["bundle"] = bundle
    return env


def test_a_window_ending_at_the_visit_instant_samples_nothing_and_errors_not(api):
    """The half-open end excludes the chart, giving three zeros and an empty list.

    PRD: "The run supplies `window_start` and `window_end`, and the period is
    half-open: a visit qualifies when its `created_at` is at or after `window_start`
    and strictly before `window_end`."

    Design: Difficulty/boundary_precision_check/chart_review_sampling_empty_window_returns_zero_counts
    """
    env = _one_closed_chart_at_the_startup_instant(api)

    run = run_sampling(api, env["clinic_id"], "2026-07-01T00:00:00Z",
                       "2026-08-01T00:00:00Z", headers=env["physician_headers"])

    assert run["sampled_count"] == 0
    assert run["mandatory_count"] == 0
    assert run["random_count"] == 0
    assert run["chart_review_ids"] == []


def test_widening_the_window_by_a_day_samples_the_single_chart(api):
    """The same chart falls inside the widened window and one review is drawn.

    PRD: "Three boundaries make the arithmetic concrete: five eligible visits at a 40
    percent sample rate give a target of 2; three eligible visits at a 0 percent rate
    with one mandatory chart produce that one mandatory chart and no random ones; and
    zero eligible visits produce a sample of zero with an empty result list and no
    error at all."

    Design: Difficulty/boundary_precision_check/chart_review_sampling_empty_window_returns_zero_counts
    """
    env = _one_closed_chart_at_the_startup_instant(api)
    run_sampling(api, env["clinic_id"], "2026-07-01T00:00:00Z",
                 "2026-08-01T00:00:00Z", headers=env["physician_headers"])

    wide = run_sampling(api, env["clinic_id"], "2026-07-01T00:00:00Z",
                        "2026-08-02T00:00:00Z", headers=env["physician_headers"])

    assert wide["sampled_count"] == 1
    assert len(wide["chart_review_ids"]) == 1


def test_the_sampled_identifier_resolves_to_a_pending_review_of_that_visit(api):
    """The one identifier the widened run reports is a real PENDING review row.

    PRD: "The run itself answers with a summary of what it did: `sampled_count`,
    `mandatory_count`, `random_count`, and `chart_review_ids` listing the reviews
    created."

    Design: Difficulty/boundary_precision_check/chart_review_sampling_empty_window_returns_zero_counts
    """
    env = _one_closed_chart_at_the_startup_instant(api)

    wide = run_sampling(api, env["clinic_id"], "2026-07-01T00:00:00Z",
                        "2026-08-02T00:00:00Z", headers=env["physician_headers"])

    review = read_chart_review(api, wide["chart_review_ids"][0])
    assert review["visit_id"] == env["bundle"]["visit_id"]
    assert review["status"] == REVIEW_PENDING
