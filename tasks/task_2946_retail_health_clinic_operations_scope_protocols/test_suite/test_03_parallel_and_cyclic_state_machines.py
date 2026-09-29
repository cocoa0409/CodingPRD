"""One visit row advancing two dimensions, and one review row going round twice."""
from test_helpers import (
    ASSESSMENT_DRAFT,
    BILLING_COVERAGE_VERIFIED,
    REVIEW_CHANGES_REQUESTED,
    REVIEW_PENDING,
    SAMPLED_RANDOM_SAMPLE,
    VISIT_IN_ASSESSMENT,
    VISIT_SCREENING,
    checkout,
    create_insured_patient,
    read_chart_review,
    read_visit,
    run_sampling,
    screening_visit,
    staffed_clinic,
    start_assessment,
    treated_visit,
    validate_paginated,
    validate_success,
    verify_active_coverage,
)

WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-02T00:00:00Z"


def _screening_insured_visit(api):
    """An insured patient whose visit is SCREENING and whose billing is UNBILLED."""
    env = staffed_clinic(api, protocol={"requires_cosign": True})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Pia Parallel",
        date_of_birth="1992-02-02", payer_name="Aetna", member_id="M-3003",
        pcp_consent_on_file=False)
    env["patient"] = patient
    env["bundle"] = screening_visit(api, env, patient["id"])
    return env


def test_the_eligibility_check_leaves_the_clinical_dimension_in_screening(api):
    """Billing reaches COVERAGE_VERIFIED while the care dimension has not moved.

    PRD: "The two evolve on their own schedules and meet only at checkout, which
    refuses to proceed until the money dimension has settled."

    Design: Difficulty/non_linear_state_machine/visit_billing_and_clinical_dimensions_advance_independently
    """
    env = _screening_insured_visit(api)

    visit = verify_active_coverage(api, env, env["bundle"]["visit_id"],
                                   copay_cents=2500, coinsurance_pct=12.5)

    assert visit["billing_status"] == BILLING_COVERAGE_VERIFIED
    assert visit["clinical_status"] == VISIT_SCREENING
    assert visit["quoted_price_cents"] == 3425


def test_opening_the_assessment_leaves_the_billing_dimension_verified(api):
    """The care dimension advances to IN_ASSESSMENT and the money stays verified.

    PRD: "The new assessment is created in `DRAFT` status with its `protocol_id`
    copied from the visit, so protocol edits made afterwards cannot change how this
    assessment is evaluated, and the visit advances `SCREENING → IN_ASSESSMENT` with
    its `version` incremented."

    Design: Difficulty/non_linear_state_machine/visit_billing_and_clinical_dimensions_advance_independently
    """
    env = _screening_insured_visit(api)
    verify_active_coverage(api, env, env["bundle"]["visit_id"], copay_cents=2500,
                           coinsurance_pct=12.5)

    assessment = start_assessment(api, env, env["bundle"]["visit_id"], temp_c=37.0,
                                  heart_rate_bpm=70, spo2_pct=99)

    assert assessment["status"] == ASSESSMENT_DRAFT
    visit = read_visit(api, env["bundle"]["visit_id"])
    assert visit["clinical_status"] == VISIT_IN_ASSESSMENT
    assert visit["billing_status"] == BILLING_COVERAGE_VERIFIED


def test_both_dimensions_hold_their_own_value_on_the_same_visit_row(api):
    """One row reports IN_ASSESSMENT care against COVERAGE_VERIFIED money.

    PRD: "`clinical_status` tracks the care — screening, assessment, treatment or
    referral, closure — and `billing_status` tracks the money."

    Design: Difficulty/non_linear_state_machine/visit_billing_and_clinical_dimensions_advance_independently
    """
    env = _screening_insured_visit(api)
    verify_active_coverage(api, env, env["bundle"]["visit_id"], copay_cents=2500,
                           coinsurance_pct=12.5)
    start_assessment(api, env, env["bundle"]["visit_id"], temp_c=37.0,
                     heart_rate_bpm=70, spo2_pct=99)

    visit = read_visit(api, env["bundle"]["visit_id"])

    assert visit["clinical_status"] == VISIT_IN_ASSESSMENT
    assert visit["billing_status"] == BILLING_COVERAGE_VERIFIED
    assert visit["quoted_price_cents"] == 3425
    assert visit["self_pay"] is False


def _sampled_chart_review(api):
    """One closed insured chart, sampled into a PENDING review."""
    env = staffed_clinic(api, protocol={"requires_cosign": False})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Rita Review",
        date_of_birth="1970-07-07", payer_name="Aetna", member_id="M-4004",
        pcp_consent_on_file=False)
    env["patient"] = patient
    bundle = treated_visit(api, env, patient["id"],
                           vitals={"temp_c": 37.3, "heart_rate_bpm": 80,
                                   "spo2_pct": 98})
    verify_active_coverage(api, env, bundle["visit_id"], copay_cents=2500,
                           coinsurance_pct=12.5)
    checkout(api, env, bundle["visit_id"], services_rendered=[])
    env["bundle"] = bundle
    env["run"] = run_sampling(api, env["clinic_id"], WINDOW_START, WINDOW_END,
                              headers=env["physician_headers"])
    rows, _ = validate_paginated(
        api.list_chart_reviews(env["admin"], params={"visit_id": bundle["visit_id"]}))
    env["review"] = rows[0]
    env["review_id"] = rows[0]["id"]
    return env


def test_the_sampling_run_mints_one_pending_review_for_the_closed_chart(api):
    """One eligible chart at a 40 percent rate is sampled as a random draw.

    PRD: "Every chart the run selects becomes a review in `PENDING` status recording
    the `visit_id` sampled, the `assessment_id` under review, a
    `reviewer_physician_id` taken from the treating clinician's
    `supervising_physician_id`, the `sampled_reason` established above, and a
    `due_at` computed as the logical clock at the moment of sampling plus the state
    rule's `review_deadline_hours`."

    Design: Difficulty/non_linear_state_machine/chart_review_cycles_back_to_pending_twice
    """
    env = _sampled_chart_review(api)

    assert env["run"]["sampled_count"] == 1
    review = env["review"]
    assert review["status"] == REVIEW_PENDING
    assert review["sampled_reason"] == SAMPLED_RANDOM_SAMPLE
    assert review["reviewer_physician_id"] == env["physician_id"]
    assert review["changes_requested_count"] == 0


def test_a_resubmission_returns_the_review_to_pending(api):
    """The first round moves PENDING out and back again.

    PRD: "The treating clinician — the clinician recorded on the reviewed visit, else
    `ERR_FORBIDDEN_OWNERSHIP` — answers by returning the amended chart with an
    `amendment_note`, which moves it `CHANGES_REQUESTED → PENDING` and closes one
    cycle without resetting the counter."

    Design: Difficulty/non_linear_state_machine/chart_review_cycles_back_to_pending_twice
    """
    env = _sampled_chart_review(api)

    sent_back = validate_success(api.request_chart_review_changes(
        env["review_id"], "Document the negative strep result explicitly.",
        env["physician_headers"]))
    returned = validate_success(api.resubmit_chart_review(
        env["review_id"], "Strep result added.", env["clinician_headers"]))

    assert sent_back["status"] == REVIEW_CHANGES_REQUESTED
    assert sent_back["changes_requested_count"] == 1
    assert returned["status"] == REVIEW_PENDING
    assert returned["changes_requested_count"] == 1


def test_two_completed_cycles_leave_the_counter_at_two_and_the_status_pending(api):
    """The counter accumulates across both rounds while the status comes home.

    PRD: "The reviewing physician — and only the physician currently named in
    `reviewer_physician_id`, else `ERR_FORBIDDEN_OWNERSHIP` — may send a chart back
    with a `change_note`, moving it `PENDING → CHANGES_REQUESTED` and raising
    `changes_requested_count` by 1."

    Design: Difficulty/non_linear_state_machine/chart_review_cycles_back_to_pending_twice
    """
    env = _sampled_chart_review(api)

    for note, amendment in (
            ("Document the negative strep result explicitly.", "Strep result added."),
            ("Also record the throat exam findings.", "Exam findings added.")):
        validate_success(api.request_chart_review_changes(
            env["review_id"], note, env["physician_headers"]))
        validate_success(api.resubmit_chart_review(
            env["review_id"], amendment, env["clinician_headers"]))

    review = read_chart_review(api, env["review_id"])
    assert review["status"] == REVIEW_PENDING
    assert review["changes_requested_count"] == 2
    assert review["sampled_reason"] == SAMPLED_RANDOM_SAMPLE
