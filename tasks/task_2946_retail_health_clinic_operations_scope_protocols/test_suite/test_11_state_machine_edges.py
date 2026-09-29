"""State-machine edges: birth states, refused transitions, terminal lockdowns and the clock.

Every test here drives one declared transition to its boundary — the state a row is
born in, the transition that is simply not declared from where the row sits, the
status that nothing follows, and the two transitions only the logical clock can fire.
"""
from test_helpers import (
    ASSESSMENT_DRAFT,
    ASSESSMENT_TREATMENT_AUTHORIZED,
    ASSIGNMENT_ACTIVE,
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_SCHEDULED,
    BILLING_COVERAGE_VERIFIED,
    BILLING_INVOICED,
    CLINIC_CLOSED,
    CLINIC_OPEN,
    CLOCK_START,
    COMPLAINT_EAR_PAIN,
    COVERAGE_ACTIVE,
    DESTINATION_DIRECT_MESSAGE,
    PRESCRIPTION_CANCELLED,
    QUEUE_ABANDONED,
    QUEUE_SCHEDULED,
    QUEUE_WAITING,
    REVIEW_PENDING,
    SAMPLED_RANDOM_SAMPLE,
    SUMMARY_FAILED,
    SUMMARY_QUEUED,
    SUMMARY_UNDELIVERABLE,
    THERAPY_ANTIBIOTIC_MACROLIDE,
    TRANSPORT_FAILED,
    VISIT_CLOSED,
    VISIT_IN_ASSESSMENT,
    VISIT_TREATED,
    ApiErrorId,
    add_appointment,
    add_walk_in,
    assert_instant_equal,
    checkout,
    create_insured_patient,
    create_patient,
    create_physician,
    error_id,
    insured_patient_share,
    prescription_payload,
    read_assessment,
    read_assignment,
    read_chart_review,
    read_clinic,
    read_patient,
    read_prescription,
    read_queue_entry,
    read_visit,
    run_sampling,
    screening_visit,
    set_clock,
    staffed_clinic,
    start_assessment,
    treated_visit,
    validate_error,
    validate_paginated,
    validate_success,
    verify_active_coverage,
)


# ---------------------------------------------------------------------------
# A queue entry's birth state is decided by its kind
# ---------------------------------------------------------------------------

def _one_walk_in_and_one_appointment(api):
    """Two adults join the same OPEN clinic at the 00:00 startup clock, one of each kind."""
    env = staffed_clinic(api, clinic={"name": "CA Store 30"})
    walk_in_patient = create_patient(api, env["front_desk"], full_name="Walk Wanda",
                                    date_of_birth="1987-07-07")
    appointment_patient = create_patient(api, env["front_desk"], full_name="Appt Alan",
                                         date_of_birth="1986-06-16")
    env["walk_in_entry"] = add_walk_in(api, env, walk_in_patient["id"])
    env["appointment_entry"] = add_appointment(api, env, appointment_patient["id"],
                                               "2026-08-01T09:00:00Z")
    return env


def test_a_walk_in_is_advanced_to_waiting_inside_its_own_intake_request(api):
    """The walk-in never rests in SCHEDULED: it is already WAITING with arrived_at stamped.

    PRD: "A walk-in is admitted straight into the waiting room. Inside the same request
    the entry advances `SCHEDULED → WAITING`, its `arrived_at` is stamped with the logical
    clock, its `priority_score` is computed, the clinic's `waiting_count` rises by 1 and
    `posted_wait_minutes` is recomputed from the new depth."

    Design: Corner/state_machines/corner_queue_entry_initial_state_depends_on_kind
    """
    env = _one_walk_in_and_one_appointment(api)

    entry = env["walk_in_entry"]

    assert entry["status"] == QUEUE_WAITING
    assert_instant_equal(entry["arrived_at"], CLOCK_START)


def test_an_appointment_stays_scheduled_with_no_arrival_stamp(api):
    """Booking is not admission, so the appointment sits in SCHEDULED with arrived_at null.

    PRD: "An appointment is booked rather than admitted; it is created in `SCHEDULED`
    status and waits for the patient to show up."

    Design: Corner/state_machines/corner_queue_entry_initial_state_depends_on_kind
    """
    env = _one_walk_in_and_one_appointment(api)

    entry = read_queue_entry(api, env["appointment_entry"]["id"])

    assert entry["status"] == QUEUE_SCHEDULED
    assert entry["arrived_at"] is None


def test_an_unarrived_appointment_earns_acuity_points_but_no_punctuality_bonus(api):
    """Only the tier-2 acuity contributes, so the score is 200 rather than 450.

    PRD: "**Punctuality** contributes a flat 250 points when the entry's `kind` is
    `APPOINTMENT`, its `arrived_at` is set, and that arrival instant is no later than its
    `scheduled_at` plus 10 minutes of grace; a walk-in, an un-arrived appointment, or an
    appointment that arrived more than 10 minutes late contributes 0 from this component."

    Design: Corner/state_machines/corner_queue_entry_initial_state_depends_on_kind
    """
    env = _one_walk_in_and_one_appointment(api)

    entry = read_queue_entry(api, env["appointment_entry"]["id"])

    assert entry["acuity_tier"] == 2
    assert entry["priority_score"] == 200


def test_the_scheduled_appointment_is_not_counted_as_waiting(api):
    """Waiting depth is 1, not 2: a booked appointment is nobody in the waiting room yet.

    PRD: "Inside the same request the entry advances `SCHEDULED → WAITING`, its
    `arrived_at` is stamped with the logical clock, its `priority_score` is computed, the
    clinic's `waiting_count` rises by 1 and `posted_wait_minutes` is recomputed from the
    new depth."

    Design: Corner/state_machines/corner_queue_entry_initial_state_depends_on_kind
    """
    env = _one_walk_in_and_one_appointment(api)

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["waiting_count"] == 1
    assert clinic["open_status"] == CLINIC_OPEN


# ---------------------------------------------------------------------------
# Cosign is not declared from DRAFT
# ---------------------------------------------------------------------------

def _draft_assessment_awaiting_submission(api):
    """A cosign-demanding protocol, a visit in IN_ASSESSMENT and an unsubmitted DRAFT."""
    env = staffed_clinic(api, clinic={"name": "CA Store 31"},
                         protocol={"requires_cosign": True})
    patient = create_patient(api, env["front_desk"], full_name="Draft Dora",
                            date_of_birth="1984-04-24")
    started = screening_visit(api, env, patient["id"])
    env["visit_id"] = started["visit_id"]
    env["assessment_id"] = start_assessment(api, env, started["visit_id"], temp_c=37.1,
                                            heart_rate_bpm=80, spo2_pct=98)["id"]
    return env


def test_cosigning_an_unsubmitted_draft_assessment_is_refused_as_an_invalid_state(api):
    """No cosign transition leaves DRAFT, so the 409 names the assessment's state.

    PRD: "The target row must currently sit in a state from which the requested transition
    exists. The refusal names the resource: `ERR_STAFFING_ASSIGNMENT_INVALID_STATE`,
    `ERR_QUEUE_ENTRY_INVALID_STATE`, `ERR_VISIT_INVALID_STATE`,
    `ERR_ASSESSMENT_INVALID_STATE`, `ERR_PRESCRIPTION_INVALID_STATE`,
    `ERR_CHART_REVIEW_INVALID_STATE` or `ERR_SUMMARY_INVALID_STATE`, each HTTP 409."

    Design: Corner/state_machines/corner_cosign_before_submit_returns_assessment_invalid_state
    """
    env = _draft_assessment_awaiting_submission(api)

    response = api.cosign_assessment(env["assessment_id"], env["physician_headers"])

    validate_error(response, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE, 409)
    assert error_id(response) == "ERR_ASSESSMENT_INVALID_STATE"


def test_the_refused_early_cosignature_leaves_the_draft_unsigned(api):
    """Cosignature is declared from the two submitted states only, and nothing was written.

    PRD: "A `CollaboratingPhysician` may cosign an assessment that sits in
    `TREATMENT_AUTHORIZED` or in `REFERRAL_REQUIRED` — both branches are cosignable, and
    cosigning a referral is expected practice, since the referral record itself is what the
    physician is signing."

    Design: Corner/state_machines/corner_cosign_before_submit_returns_assessment_invalid_state
    """
    env = _draft_assessment_awaiting_submission(api)
    api.cosign_assessment(env["assessment_id"], env["physician_headers"])

    assessment = read_assessment(api, env["assessment_id"])

    assert assessment["status"] == ASSESSMENT_DRAFT
    assert assessment["cosigned_by_physician_id"] is None
    assert assessment["cosigned_at"] is None
    assert read_visit(api, env["visit_id"])["clinical_status"] == VISIT_IN_ASSESSMENT


# ---------------------------------------------------------------------------
# Cosign carries a protocol precondition of its own
# ---------------------------------------------------------------------------

def _treated_visit_on_a_protocol_that_needs_no_cosignature(api):
    """An EAR_PAIN protocol with requires_cosign false, assessed with normal vitals."""
    env = staffed_clinic(api, clinic={"name": "CA Store 32"},
                         protocol={"complaint_code": COMPLAINT_EAR_PAIN,
                                   "base_price_cents": 8500, "acuity_tier": 1,
                                   "max_heart_rate_bpm": 150, "requires_cosign": False})
    patient = create_patient(api, env["front_desk"], full_name="Ned NoCosign",
                            date_of_birth="1983-03-13")
    env["bundle"] = treated_visit(api, env, patient["id"],
                                  complaint_code=COMPLAINT_EAR_PAIN,
                                  vitals={"temp_c": 37.0, "heart_rate_bpm": 78,
                                          "spo2_pct": 99})
    return env


def test_normal_vitals_authorize_treatment_without_any_countersignature(api):
    """The submission forks to the treatment branch and the visit becomes TREATED.

    PRD: "On the treatment branch, the linked visit advances `IN_ASSESSMENT → TREATED`, its
    `referral_required` flag is set false, no prescription cascade fires at all, and
    prescribing becomes legal for the first time."

    Design: Corner/state_machines/corner_cosign_on_non_cosign_protocol_returns_cosign_not_required
    """
    env = _treated_visit_on_a_protocol_that_needs_no_cosignature(api)

    assert env["bundle"]["assessment"]["status"] == ASSESSMENT_TREATMENT_AUTHORIZED
    assert read_visit(api, env["bundle"]["visit_id"])["clinical_status"] == VISIT_TREATED


def test_cosigning_where_the_protocol_does_not_demand_it_is_refused(api):
    """A perfectly cosignable state still refuses, because the protocol asks for no signature.

    PRD: "The protocol's `requires_cosign` must be true; cosigning an assessment governed by
    a protocol that does not demand it is refused with `ERR_COSIGN_NOT_REQUIRED`."

    Design: Corner/state_machines/corner_cosign_on_non_cosign_protocol_returns_cosign_not_required
    """
    env = _treated_visit_on_a_protocol_that_needs_no_cosignature(api)
    assessment_id = env["bundle"]["assessment_id"]

    response = api.cosign_assessment(assessment_id, env["physician_headers"])

    validate_error(response, ApiErrorId.ERR_COSIGN_NOT_REQUIRED, 422)
    assert error_id(response) == "ERR_COSIGN_NOT_REQUIRED"
    assert read_assessment(api, assessment_id)["status"] == ASSESSMENT_TREATMENT_AUTHORIZED
    assert read_visit(api, env["bundle"]["visit_id"])["clinical_status"] == VISIT_TREATED


# ---------------------------------------------------------------------------
# The mirror-image rule: checkout demands the signature the protocol asked for
# ---------------------------------------------------------------------------

def _insured_treated_visit_awaiting_its_countersignature(api):
    """A requires_cosign protocol, a TREATED visit and coverage already verified."""
    env = staffed_clinic(api, clinic={"name": "CA Store 33"},
                         protocol={"requires_cosign": True})
    patient = create_insured_patient(api, env["front_desk"],
                                    full_name="Cora NeedsCosign",
                                    date_of_birth="1976-06-26", payer_name="BlueCo",
                                    member_id="M-3003", pcp_consent_on_file=False)
    env["patient_id"] = patient["id"]
    bundle = treated_visit(api, env, patient["id"],
                           vitals={"temp_c": 37.3, "heart_rate_bpm": 86, "spo2_pct": 97})
    env["visit_id"] = bundle["visit_id"]
    env["verified"] = verify_active_coverage(api, env, bundle["visit_id"])
    return env


def test_checkout_of_a_treated_visit_without_the_cosignature_is_refused(api):
    """TREATMENT_AUTHORIZED is not enough when the governing protocol demands a signature.

    PRD: "When the governing protocol's `requires_cosign` is true and the visit is
    `TREATED`, its assessment must already be `COSIGNED` rather than merely
    `TREATMENT_AUTHORIZED`, else `ERR_COSIGN_REQUIRED`."

    Design: Corner/state_machines/corner_checkout_without_cosign_returns_cosign_required
    """
    env = _insured_treated_visit_awaiting_its_countersignature(api)

    response = api.checkout(env["visit_id"], env["clinician_headers"],
                            services_rendered=[])

    validate_error(response, ApiErrorId.ERR_COSIGN_REQUIRED, 422)
    assert error_id(response) == "ERR_COSIGN_REQUIRED"


def test_the_refused_checkout_leaves_the_visit_verified_but_unpriced(api):
    """The billing dimension stays where the eligibility check put it, with no money written.

    PRD: "Active coverage moves the visit `UNBILLED → COVERAGE_VERIFIED`. Its
    `coverage_status` becomes `ACTIVE`, its `self_pay` flag is set false, the reported
    `copay_cents` and `coinsurance_pct` are stored on the visit, and `quoted_price_cents`
    is written with an **insured estimate**."

    Design: Corner/state_machines/corner_checkout_without_cosign_returns_cosign_required
    """
    env = _insured_treated_visit_awaiting_its_countersignature(api)
    assert env["verified"]["billing_status"] == BILLING_COVERAGE_VERIFIED
    api.checkout(env["visit_id"], env["clinician_headers"], services_rendered=[])

    visit = read_visit(api, env["visit_id"])

    assert visit["clinical_status"] == VISIT_TREATED
    assert visit["billing_status"] == BILLING_COVERAGE_VERIFIED
    assert visit["coverage_status"] == COVERAGE_ACTIVE
    assert visit["final_price_cents"] is None
    assert visit["patient_responsibility_cents"] is None


def test_the_refused_checkout_puts_nothing_on_the_patient_balance(api):
    """No invoice was raised, so the patient still owes nothing at all.

    PRD: "A patient's `outstanding_balance_cents` is the sum of
    `patient_responsibility_cents` across that patient's visits whose `billing_status` is
    `INVOICED`, and it is recomputed from scratch on every billing transition that touches
    the patient."

    Design: Corner/state_machines/corner_checkout_without_cosign_returns_cosign_required
    """
    env = _insured_treated_visit_awaiting_its_countersignature(api)
    api.checkout(env["visit_id"], env["clinician_headers"], services_rendered=[])

    assert read_patient(api, env["patient_id"])["outstanding_balance_cents"] == 0


# ---------------------------------------------------------------------------
# CANCELLED is terminal for a prescription
# ---------------------------------------------------------------------------

def _draft_prescription_on_a_treated_visit(api):
    """One DRAFT macrolide prescription written against the visit's current version."""
    env = staffed_clinic(api, clinic={"name": "CA Store 34"})
    patient = create_patient(api, env["front_desk"], full_name="Cal Cancel",
                            date_of_birth="1979-09-19")
    env["patient_id"] = patient["id"]
    bundle = treated_visit(api, env, patient["id"],
                           vitals={"temp_c": 37.4, "heart_rate_bpm": 84, "spo2_pct": 98})
    env["visit_id"] = bundle["visit_id"]
    payload = prescription_payload(bundle["visit_id"],
                                   read_visit(api, bundle["visit_id"])["version"],
                                   drug_name="Azithromycin 250mg",
                                   therapy_class=THERAPY_ANTIBIOTIC_MACROLIDE,
                                   days_supply=5)
    env["prescription_id"] = validate_success(
        api.create_prescription(payload, env["clinician_headers"]), 201)["id"]
    return env


def test_cancelling_a_draft_prescription_releases_no_therapy_lock(api):
    """The draft never held a lock, so CANCELLED leaves the patient's therapy set empty.

    PRD: "A `DRAFT → CANCELLED` cancellation changes nothing about the patient's therapy
    set, because a draft never held a lock."

    Design: Corner/state_machines/corner_prescription_cancel_from_cancelled_is_locked_out
    """
    env = _draft_prescription_on_a_treated_visit(api)

    cancelled = validate_success(api.cancel_prescription(
        env["prescription_id"], env["clinician_headers"],
        cancel_reason="Patient declined"))

    assert cancelled["status"] == PRESCRIPTION_CANCELLED
    assert cancelled["routed_at"] is None
    assert read_patient(api, env["patient_id"])["active_therapy_classes"] == []


def test_a_second_cancel_of_the_same_prescription_is_refused(api):
    """Cancellation is not idempotent-by-retry once the row is already CANCELLED.

    PRD: "Cancelling an already-`CANCELLED` prescription is refused with
    `ERR_PRESCRIPTION_INVALID_STATE`."

    Design: Corner/state_machines/corner_prescription_cancel_from_cancelled_is_locked_out
    """
    env = _draft_prescription_on_a_treated_visit(api)
    validate_success(api.cancel_prescription(env["prescription_id"],
                                             env["clinician_headers"],
                                             cancel_reason="Patient declined"))

    response = api.cancel_prescription(env["prescription_id"], env["clinician_headers"],
                                       cancel_reason="Duplicate cancel")

    validate_error(response, ApiErrorId.ERR_PRESCRIPTION_INVALID_STATE, 409)
    assert error_id(response) == "ERR_PRESCRIPTION_INVALID_STATE"


def test_routing_a_cancelled_prescription_does_not_revive_it(api):
    """Routing is declared from DRAFT alone, so the dead row stays dead.

    PRD: "The prescription must be in `DRAFT`, else `ERR_PRESCRIPTION_INVALID_STATE`."

    Design: Corner/state_machines/corner_prescription_cancel_from_cancelled_is_locked_out
    """
    env = _draft_prescription_on_a_treated_visit(api)
    validate_success(api.cancel_prescription(env["prescription_id"],
                                             env["clinician_headers"],
                                             cancel_reason="Patient declined"))

    response = api.route_prescription(env["prescription_id"], env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_PRESCRIPTION_INVALID_STATE, 409)
    prescription = read_prescription(api, env["prescription_id"])
    assert prescription["status"] == PRESCRIPTION_CANCELLED
    assert prescription["routed_at"] is None


# ---------------------------------------------------------------------------
# Checkout happens once
# ---------------------------------------------------------------------------

def _invoiced_insured_visit(api):
    """An insured base-line-only encounter carried through to INVOICED and CLOSED."""
    env = staffed_clinic(api, clinic={"name": "CA Store 35"})
    patient = create_insured_patient(api, env["front_desk"], full_name="Ida Once",
                                    date_of_birth="1981-11-21", payer_name="Aetna",
                                    member_id="M-4004", pcp_consent_on_file=False)
    env["patient_id"] = patient["id"]
    bundle = treated_visit(api, env, patient["id"],
                           vitals={"temp_c": 37.2, "heart_rate_bpm": 82, "spo2_pct": 98})
    env["visit_id"] = bundle["visit_id"]
    verify_active_coverage(api, env, bundle["visit_id"])
    env["invoiced"] = checkout(api, env, bundle["visit_id"], services_rendered=[])
    return env


def test_the_first_checkout_prices_the_base_line_and_splits_it(api):
    """9900 allowed, 1238 of coinsurance on the single line plus the 2500 copay.

    PRD: "For an insured visit, the patient's share is built **line by line**:
    `coinsurance_pct` is applied to each line price, each line's result is rounded to whole
    cents half up on its own, those rounded shares are added together, `copay_cents` is
    added on top, and the outcome is finally capped so that it never exceeds the total
    allowed amount."

    Design: Corner/state_machines/corner_second_checkout_on_invoiced_visit_returns_visit_invalid_state
    """
    env = _invoiced_insured_visit(api)

    invoiced = env["invoiced"]

    assert invoiced["final_price_cents"] == 9900
    assert invoiced["patient_responsibility_cents"] == 3738
    assert invoiced["patient_responsibility_cents"] == insured_patient_share(
        [9900], 2500, 12.5, 9900)
    assert invoiced["payer_responsibility_cents"] == 6162


def test_a_second_checkout_of_an_invoiced_visit_is_refused(api):
    """The visit is CLOSED on the clinical side, and no checkout transition leaves CLOSED.

    PRD: "The visit's `clinical_status` must be `TREATED` or `REFERRED`; anything else,
    including a visit already `CLOSED`, is refused with `ERR_VISIT_INVALID_STATE`."

    Design: Corner/state_machines/corner_second_checkout_on_invoiced_visit_returns_visit_invalid_state
    """
    env = _invoiced_insured_visit(api)
    assert env["invoiced"]["clinical_status"] == VISIT_CLOSED

    response = api.checkout(env["visit_id"], env["clinician_headers"],
                            services_rendered=[])

    validate_error(response, ApiErrorId.ERR_VISIT_INVALID_STATE, 409)
    assert error_id(response) == "ERR_VISIT_INVALID_STATE"


def test_the_refused_retry_does_not_double_the_patient_balance(api):
    """The balance is a recomputed sum over invoiced visits, so 3738 never becomes 7476.

    PRD: "Patient balances are never patched incrementally. A patient's
    `outstanding_balance_cents` is the sum of `patient_responsibility_cents` across that
    patient's visits whose `billing_status` is `INVOICED`, and it is recomputed from scratch
    on every billing transition that touches the patient."

    Design: Corner/state_machines/corner_second_checkout_on_invoiced_visit_returns_visit_invalid_state
    """
    env = _invoiced_insured_visit(api)
    api.checkout(env["visit_id"], env["clinician_headers"], services_rendered=[])

    visit = read_visit(api, env["visit_id"])

    assert visit["billing_status"] == BILLING_INVOICED
    assert visit["patient_responsibility_cents"] == 3738
    assert read_patient(api, env["patient_id"])["outstanding_balance_cents"] == 3738


# ---------------------------------------------------------------------------
# The summary retry loop and its cap
# ---------------------------------------------------------------------------

def _queued_summary_for_a_consenting_patient(api):
    """Checkout mints one QUEUED summary, discovered through the filtered list read."""
    env = staffed_clinic(api, clinic={"name": "CA Store 36"})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Ruth Retry", date_of_birth="1975-05-15",
        payer_name="BlueCo", member_id="M-5005", pcp_name="Dr PCP",
        pcp_direct_address="pcp@direct.example", pcp_accepts_electronic_summary=True,
        pcp_consent_on_file=True)
    bundle = treated_visit(api, env, patient["id"],
                           vitals={"temp_c": 37.2, "heart_rate_bpm": 80, "spo2_pct": 98})
    verify_active_coverage(api, env, bundle["visit_id"])
    checkout(api, env, bundle["visit_id"], services_rendered=[])
    rows, _meta = validate_paginated(api.list_visit_summaries(
        env["admin"], params={"visit_id": bundle["visit_id"]}))
    env["summary"] = rows[0]
    env["summary_id"] = rows[0]["id"]
    return env


def _fail_transmission(api, env, failure_code):
    return validate_success(api.transmit_visit_summary(
        env["summary_id"], TRANSPORT_FAILED, env["admin"], failure_code=failure_code))


def test_checkout_queues_a_direct_message_summary_for_a_consenting_patient(api):
    """The address is on file and accepts electronic delivery, so the first branch wins.

    PRD: "When the patient has a `pcp_direct_address` on file and their
    `pcp_accepts_electronic_summary` is true, `destination_kind` is `DIRECT_MESSAGE` and
    `destination_address` is that address."

    Design: Corner/state_machines/corner_summary_retry_cycle_reaches_undeliverable_on_third_failure
    """
    env = _queued_summary_for_a_consenting_patient(api)

    summary = env["summary"]

    assert summary["status"] == SUMMARY_QUEUED
    assert summary["destination_kind"] == DESTINATION_DIRECT_MESSAGE
    assert summary["destination_address"] == "pcp@direct.example"


def test_a_retry_after_the_first_failure_requeues_without_resetting_the_counter(api):
    """Failure one lands in FAILED at attempt 1, and the requeue keeps that 1.

    PRD: "A `FAILED` summary may be requeued for another try, moving `FAILED → QUEUED`
    while retaining `last_error_code` until the next attempt overwrites it and never
    resetting `attempt_count`."

    Design: Corner/state_machines/corner_summary_retry_cycle_reaches_undeliverable_on_third_failure
    """
    env = _queued_summary_for_a_consenting_patient(api)

    first_failure = _fail_transmission(api, env, "TIMEOUT")
    requeued = validate_success(api.retry_visit_summary(env["summary_id"], env["admin"]))

    assert first_failure["status"] == SUMMARY_FAILED
    assert first_failure["attempt_count"] == 1
    assert requeued["status"] == SUMMARY_QUEUED
    assert requeued["attempt_count"] == 1


def test_the_third_failure_lands_in_the_terminal_undeliverable_state(api):
    """Two failures hold at FAILED with 1 then 2; the third crosses the cap of three.

    PRD: "Concretely, the first two failures land in `FAILED` with `attempt_count` at 1 and
    then 2, and the third failure lands in `UNDELIVERABLE` with `attempt_count` at 3."

    Design: Corner/state_machines/corner_summary_retry_cycle_reaches_undeliverable_on_third_failure
    """
    env = _queued_summary_for_a_consenting_patient(api)
    _fail_transmission(api, env, "TIMEOUT")
    validate_success(api.retry_visit_summary(env["summary_id"], env["admin"]))

    second_failure = _fail_transmission(api, env, "BUSY")
    validate_success(api.retry_visit_summary(env["summary_id"], env["admin"]))
    third_failure = _fail_transmission(api, env, "REJECTED")

    assert second_failure["status"] == SUMMARY_FAILED
    assert second_failure["attempt_count"] == 2
    assert third_failure["status"] == SUMMARY_UNDELIVERABLE
    assert third_failure["attempt_count"] == 3
    assert third_failure["last_error_code"] == "REJECTED"
    assert third_failure["sent_at"] is None


def test_requeueing_an_undeliverable_summary_is_refused(api):
    """UNDELIVERABLE is the end of the line, so the fourth try never happens.

    PRD: "Requeueing anything that is not `FAILED` — including the terminal
    `UNDELIVERABLE` — is refused with `ERR_SUMMARY_INVALID_STATE`, as is a retry of a
    summary already `SENT`."

    Design: Corner/state_machines/corner_summary_retry_cycle_reaches_undeliverable_on_third_failure
    """
    env = _queued_summary_for_a_consenting_patient(api)
    for failure_code in ("TIMEOUT", "BUSY"):
        _fail_transmission(api, env, failure_code)
        validate_success(api.retry_visit_summary(env["summary_id"], env["admin"]))
    _fail_transmission(api, env, "REJECTED")

    response = api.retry_visit_summary(env["summary_id"], env["admin"])

    validate_error(response, ApiErrorId.ERR_SUMMARY_INVALID_STATE, 409)
    assert error_id(response) == "ERR_SUMMARY_INVALID_STATE"
    assert validate_success(api.get_visit_summary(
        env["summary_id"], env["admin"]))["status"] == SUMMARY_UNDELIVERABLE


# ---------------------------------------------------------------------------
# Only the clock activates and completes a shift
# ---------------------------------------------------------------------------

def _future_shift_at_a_closed_clinic(api):
    """A PRIMARY shift booked for [09:00, 12:00) while the clock still reads 00:00."""
    env = staffed_clinic(api, with_protocol=False, clinic={"name": "CA Store 37"},
                         physician={"full_name": "Dr Elm"},
                         clinician={"full_name": "NP Elm"},
                         assignment={"starts_at": "2026-08-01T09:00:00Z",
                                     "ends_at": "2026-08-01T12:00:00Z"})
    env["clinic_before"] = read_clinic(api, env["clinic_id"])
    return env


def test_a_shift_whose_window_has_not_been_reached_is_merely_scheduled(api):
    """The clock is outside [09:00, 12:00), so nobody is on duty and the site is CLOSED.

    PRD: "An assignment is born `SCHEDULED`. It advances `SCHEDULED → ACTIVE` the moment
    the logical clock sits inside its interval — either because the clock was already there
    when the assignment was created, in which case the activation happens inside the same
    request, or because a later clock move crossed `starts_at`."

    Design: Corner/state_machines/corner_clock_advance_activates_then_completes_the_assignment
    """
    env = _future_shift_at_a_closed_clinic(api)

    assert env["assignment"]["status"] == ASSIGNMENT_SCHEDULED
    assert env["clinic_before"]["open_status"] == CLINIC_CLOSED
    assert env["clinic_before"]["on_duty_clinician_count"] == 0


def test_the_clock_reaching_the_start_instant_activates_the_shift_and_opens_the_clinic(api):
    """09:00 is inclusive: the advance reports the activation and the site comes to life.

    PRD: "The response to a clock move reports what it did, listing `current_utc` alongside
    `activated_assignment_ids`, `completed_assignment_ids`, `abandoned_queue_entry_ids` and
    `affected_clinic_ids`."

    Design: Corner/state_machines/corner_clock_advance_activates_then_completes_the_assignment
    """
    env = _future_shift_at_a_closed_clinic(api)

    advance = set_clock(api, "2026-08-01T09:00:00Z", env["admin"])

    assert env["assignment_id"] in advance["activated_assignment_ids"]
    assert env["clinic_id"] in advance["affected_clinic_ids"]
    assert read_assignment(api, env["assignment_id"])["status"] == ASSIGNMENT_ACTIVE
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["open_status"] == CLINIC_OPEN
    assert clinic["on_duty_clinician_count"] == 1


def test_the_clock_reaching_the_end_instant_completes_the_shift_and_closes_the_clinic(api):
    """The interval's end is exclusive, so at 12:00 the shift is over and the floor empties.

    PRD: "When the clock later passes `ends_at`, the assignment advances
    `ACTIVE → COMPLETED`, lowering `on_duty_clinician_count` by 1 and re-deriving posture in
    the other direction — `OPEN → LIMITED`, `OPEN → CLOSED` or `LIMITED → CLOSED`, with the
    queue and visit cascades of §2.8 — and both counters are recomputed again."

    Design: Corner/state_machines/corner_clock_advance_activates_then_completes_the_assignment
    """
    env = _future_shift_at_a_closed_clinic(api)
    set_clock(api, "2026-08-01T09:00:00Z", env["admin"])

    advance = set_clock(api, "2026-08-01T12:00:00Z", env["admin"])

    assert env["assignment_id"] in advance["completed_assignment_ids"]
    assert read_assignment(api, env["assignment_id"])["status"] == ASSIGNMENT_COMPLETED
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["open_status"] == CLINIC_CLOSED
    assert clinic["on_duty_clinician_count"] == 0
    assert clinic["posted_wait_minutes"] == 0


# ---------------------------------------------------------------------------
# Abandonment is inclusive at two hours
# ---------------------------------------------------------------------------

def _one_uncalled_walk_in(api):
    """A walk-in arrives at the 00:00 clock into a site staffed until 23:00, and is left."""
    env = staffed_clinic(api, clinic={"name": "CA Store 38"},
                         physician={"full_name": "Dr Fern"},
                         clinician={"full_name": "NP Fern"})
    patient = create_patient(api, env["front_desk"], full_name="Abe Abandon",
                            date_of_birth="1972-02-12")
    env["entry_id"] = add_walk_in(api, env, patient["id"])["id"]
    env["clinic_before"] = read_clinic(api, env["clinic_id"])
    return env


def test_one_waiting_patient_against_one_clinician_posts_a_twenty_minute_wait(api):
    """One block of one patient per clinician, so the public projection is 20 minutes.

    PRD: "The posted wait takes the clinic's current `waiting_count`, divides it by the
    number of clinicians on duty — using 1 as the divisor whenever `on_duty_clinician_count`
    is 0, so the arithmetic never breaks — and rounds that quotient **up** to a whole number
    of patients per clinician. That rounded-up figure is multiplied by 20 minutes, the
    average visit length."

    Design: Corner/state_machines/corner_clock_abandons_waiting_entry_at_exactly_one_hundred_twenty_minutes
    """
    env = _one_uncalled_walk_in(api)

    clinic = env["clinic_before"]

    assert clinic["waiting_count"] == 1
    assert clinic["on_duty_clinician_count"] == 1
    assert clinic["posted_wait_minutes"] == 20


def test_a_clock_advance_to_exactly_two_hours_abandons_the_waiting_entry(api):
    """The guard is inclusive: 120 minutes on the nose is already too long to wait.

    PRD: "When the logical clock advances to 120 minutes or more past an entry's
    `arrived_at` while that entry is still `WAITING` and no one has called it, the entry
    moves `WAITING → ABANDONED`, the clinic's `waiting_count` falls by 1, and
    `posted_wait_minutes` is recomputed."

    Design: Corner/state_machines/corner_clock_abandons_waiting_entry_at_exactly_one_hundred_twenty_minutes
    """
    env = _one_uncalled_walk_in(api)

    advance = set_clock(api, "2026-08-01T02:00:00Z", env["admin"])

    assert env["entry_id"] in advance["abandoned_queue_entry_ids"]
    assert read_queue_entry(api, env["entry_id"])["status"] == QUEUE_ABANDONED


def test_the_abandonment_empties_the_waiting_room_and_zeroes_the_posted_wait(api):
    """Losing the only waiting entry takes the projection from 20 straight back to 0.

    PRD: "This projection is recomputed on every mutation of `waiting_count` or
    `on_duty_clinician_count`, and it never looks at when anybody was actually called."

    Design: Corner/state_machines/corner_clock_abandons_waiting_entry_at_exactly_one_hundred_twenty_minutes
    """
    env = _one_uncalled_walk_in(api)
    set_clock(api, "2026-08-01T02:00:00Z", env["admin"])

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["waiting_count"] == 0
    assert clinic["posted_wait_minutes"] == 0
    assert clinic["open_status"] == CLINIC_OPEN
    assert read_assignment(api, env["assignment_id"])["status"] == ASSIGNMENT_ACTIVE


def test_an_entry_that_was_never_called_records_no_realized_wait(api):
    """Abandonment is not a measurement, so both realized readings stay null.

    PRD: "Until the first patient at a site is ever called, both the entry-level
    `realized_wait_minutes` and the clinic-level `last_realized_wait_minutes` remain null."

    Design: Corner/state_machines/corner_clock_abandons_waiting_entry_at_exactly_one_hundred_twenty_minutes
    """
    env = _one_uncalled_walk_in(api)
    set_clock(api, "2026-08-01T02:00:00Z", env["admin"])

    assert read_queue_entry(api, env["entry_id"])["realized_wait_minutes"] is None
    assert read_clinic(api, env["clinic_id"])["last_realized_wait_minutes"] is None


# ---------------------------------------------------------------------------
# Reassignment is a PENDING to PENDING self-transition
# ---------------------------------------------------------------------------

def _pending_chart_review_with_an_idle_second_physician(api):
    """One closed insured chart sampled to its supervisor, with an unloaded rival on file."""
    env = staffed_clinic(api, clinic={"name": "CA Store 39"},
                         physician={"full_name": "Dr Supervisor"},
                         clinician={"full_name": "NP Gale"})
    env["idle_physician_id"] = create_physician(api, env["admin"],
                                                full_name="Dr Idle")["id"]
    patient = create_insured_patient(api, env["front_desk"], full_name="Rita Review",
                                    date_of_birth="1974-04-14", payer_name="BlueCo",
                                    member_id="M-6006", pcp_consent_on_file=False)
    bundle = treated_visit(api, env, patient["id"],
                           vitals={"temp_c": 37.1, "heart_rate_bpm": 79, "spo2_pct": 98})
    verify_active_coverage(api, env, bundle["visit_id"])
    checkout(api, env, bundle["visit_id"], services_rendered=[])
    env["run"] = run_sampling(api, env["clinic_id"], CLOCK_START,
                              "2026-08-02T00:00:00Z")
    env["review_id"] = env["run"]["chart_review_ids"][0]
    env["review_before"] = read_chart_review(api, env["review_id"])
    return env


def test_a_forty_percent_sample_of_one_eligible_chart_rounds_up_to_one(api):
    """Two fifths of a single chart rounds up to one, and it is drawn by chance.

    PRD: "The size of the run comes from the state rule: multiply the number of eligible
    visits by `chart_review_sample_pct`, divide by 100, and round the result **up** to a
    whole number to obtain the target total."

    Design: Corner/state_machines/corner_chart_review_reassign_switches_reviewer_and_stays_pending
    """
    env = _pending_chart_review_with_an_idle_second_physician(api)

    run = env["run"]

    assert run["sampled_count"] == 1
    assert run["mandatory_count"] == 0
    assert run["random_count"] == 1
    assert env["review_before"]["sampled_reason"] == SAMPLED_RANDOM_SAMPLE


def test_the_new_review_is_pending_to_the_supervisor_with_a_seventy_two_hour_deadline(api):
    """The reviewer is inherited from the treating clinician and the deadline is 2026-08-04.

    PRD: "Every chart the run selects becomes a review in `PENDING` status recording the
    `visit_id` sampled, the `assessment_id` under review, a `reviewer_physician_id` taken
    from the treating clinician's `supervising_physician_id`, the `sampled_reason`
    established above, and a `due_at` computed as the logical clock at the moment of sampling
    plus the state rule's `review_deadline_hours`."

    Design: Corner/state_machines/corner_chart_review_reassign_switches_reviewer_and_stays_pending
    """
    env = _pending_chart_review_with_an_idle_second_physician(api)

    review = env["review_before"]

    assert review["status"] == REVIEW_PENDING
    assert review["reviewer_physician_id"] == env["physician_id"]
    assert_instant_equal(review["due_at"], "2026-08-04T00:00:00Z")
    assert review["changes_requested_count"] == 0


def test_reassignment_hands_the_chart_to_the_unloaded_second_physician(api):
    """The incumbent is excluded by name, so Dr Idle is the only surviving candidate.

    PRD: "Candidates are physicians whose `status` is `ACTIVE`, whose `licensed_state_codes`
    contains the clinic's `state_code`, who are neither the incumbent
    `reviewer_physician_id` nor the assessment's `cosigned_by_physician_id`, and whose
    `current_supervised_count` is strictly below their effective cap — the smaller of their
    own `max_supervised_clinicians` and the state rule's
    `max_supervised_clinicians_per_physician`."

    Design: Corner/state_machines/corner_chart_review_reassign_switches_reviewer_and_stays_pending
    """
    env = _pending_chart_review_with_an_idle_second_physician(api)

    reassigned = validate_success(
        api.reassign_chart_review(env["review_id"], env["admin"]))

    assert reassigned["reviewer_physician_id"] == env["idle_physician_id"]
    assert reassigned["reviewer_physician_id"] != env["physician_id"]


def test_reassignment_leaves_the_review_pending_on_its_original_deadline(api):
    """Handing the chart over buys no extra time and does not move the review's status.

    PRD: "On success `reviewer_physician_id` is replaced, the status stays `PENDING`, and
    `due_at` is deliberately left unchanged — reassignment does not buy the clinic more
    time."

    Design: Corner/state_machines/corner_chart_review_reassign_switches_reviewer_and_stays_pending
    """
    env = _pending_chart_review_with_an_idle_second_physician(api)

    reassigned = validate_success(
        api.reassign_chart_review(env["review_id"], env["admin"]))

    assert reassigned["status"] == REVIEW_PENDING
    assert_instant_equal(reassigned["due_at"], env["review_before"]["due_at"])
    assert_instant_equal(reassigned["due_at"], "2026-08-04T00:00:00Z")
    assert reassigned["changes_requested_count"] == 0
