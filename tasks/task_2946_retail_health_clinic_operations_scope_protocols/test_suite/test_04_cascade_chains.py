"""Multi-hop cascades: a cancelled shift closing a site, and a referral clearing scripts."""
from test_helpers import (
    ASSESSMENT_REFERRAL_REQUIRED,
    ASSIGNMENT_CANCELLED,
    CLINIC_CLOSED,
    CLINIC_OPEN,
    PRESCRIPTION_CANCELLED,
    QUEUE_DEFERRED_CLOSURE,
    REASON_HYPOXIA,
    REFERRAL_EMERGENCY_DEPARTMENT,
    VISIT_CANCELLED_CLOSURE,
    VISIT_REFERRED,
    add_walk_in,
    create_insured_patient,
    create_patient,
    prescription_payload,
    read_assignment,
    read_clinic,
    read_clinician,
    read_patient,
    read_physician,
    read_prescription,
    read_queue_entry,
    read_visit,
    screening_visit,
    staffed_clinic,
    start_assessment,
    submit_assessment,
    validate_success,
)


def _open_clinic_with_one_called_and_two_waiting(api):
    """One ACTIVE shift, a SCREENING visit, and two walk-ins still WAITING."""
    env = staffed_clinic(api, protocol={"requires_cosign": True})
    called_patient = create_patient(api, env["front_desk"], full_name="Ann Called",
                                    date_of_birth="1983-04-04")
    env["called_bundle"] = screening_visit(api, env, called_patient["id"])
    env["waiting"] = []
    for name, birth in (("Bob Waiting", "1984-05-05"), ("Cid Waiting", "1986-06-06")):
        patient = create_patient(api, env["front_desk"], full_name=name,
                                 date_of_birth=birth)
        env["waiting"].append(add_walk_in(api, env, patient["id"]))
    return env


def _cancel_the_shift(api, env):
    return validate_success(api.cancel_staffing_assignment(
        env["assignment_id"], env["admin"], cancel_reason="Clinician called away"))


def test_cancelling_the_only_active_shift_empties_the_floor_and_closes_the_site(api):
    """The clinic posts 40 minutes while OPEN, then reaches CLOSED at zero on duty.

    PRD: "Hop one lowers the clinic's `on_duty_clinician_count` by 1. Hop two
    re-derives `open_status` from the new count, moving `OPEN → LIMITED` when the
    count is above 0 but below `min_clinicians_required`, and `OPEN → CLOSED` or
    `LIMITED → CLOSED` when it reaches 0."

    Design: Difficulty/transitive_cascade/staffing_cancel_closes_clinic_defers_queue_and_zeroes_wait
    """
    env = _open_clinic_with_one_called_and_two_waiting(api)
    before = read_clinic(api, env["clinic_id"])
    assert before["open_status"] == CLINIC_OPEN
    assert before["posted_wait_minutes"] == 40

    _cancel_the_shift(api, env)

    assert read_assignment(api, env["assignment_id"])["status"] == ASSIGNMENT_CANCELLED
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["on_duty_clinician_count"] == 0
    assert clinic["open_status"] == CLINIC_CLOSED


def test_the_closure_defers_both_waiting_entries_and_cancels_the_screening_visit(api):
    """Every waiting entry is deferred and the un-assessed visit is cancelled.

    PRD: "When a clinic reaches `CLOSED` from either `OPEN` or `LIMITED`, every queue
    entry at that clinic in `SCHEDULED` or `WAITING` status moves to
    `DEFERRED_CLOSURE` regardless of kind, and in addition every visit at that clinic
    still in `SCREENING` moves to `CANCELLED_CLOSURE` — those are patients who were
    called but never assessed."

    Design: Difficulty/transitive_cascade/staffing_cancel_closes_clinic_defers_queue_and_zeroes_wait
    """
    env = _open_clinic_with_one_called_and_two_waiting(api)

    _cancel_the_shift(api, env)

    for entry in env["waiting"]:
        assert read_queue_entry(api, entry["id"])["status"] == QUEUE_DEFERRED_CLOSURE
    visit = read_visit(api, env["called_bundle"]["visit_id"])
    assert visit["clinical_status"] == VISIT_CANCELLED_CLOSURE


def test_the_deferred_entries_are_what_zero_the_depth_and_the_posted_wait(api):
    """The counters follow the queue transitions, not the cancel call itself.

    PRD: "Only after those child transitions have happened is the clinic's
    `waiting_count` recomputed, and only from that new `waiting_count` is
    `posted_wait_minutes` re-derived."

    Design: Difficulty/transitive_cascade/staffing_cancel_closes_clinic_defers_queue_and_zeroes_wait
    """
    env = _open_clinic_with_one_called_and_two_waiting(api)

    _cancel_the_shift(api, env)

    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["waiting_count"] == 0
    assert clinic["posted_wait_minutes"] == 0


def test_the_cancelled_shift_stops_counting_towards_either_staffing_counter(api):
    """Supervision load and the clinician's shift count both fall back to zero.

    PRD: "A physician's `current_supervised_count` is the number of **distinct**
    clinicians appearing on assignments that name that physician as pinned supervisor
    and sit in `SCHEDULED` or `ACTIVE` status; two shifts for the same clinician under
    the same physician count once, and `CANCELLED` or `COMPLETED` assignments are
    excluded entirely."

    Design: Difficulty/transitive_cascade/staffing_cancel_closes_clinic_defers_queue_and_zeroes_wait
    """
    env = _open_clinic_with_one_called_and_two_waiting(api)

    _cancel_the_shift(api, env)

    assert read_physician(api, env["physician_id"])["current_supervised_count"] == 0
    assert read_clinician(api, env["clinician_id"])["active_assignment_count"] == 0


def _hypoxic_visit_with_a_draft_prescription(api):
    """An IN_ASSESSMENT visit recording spo2 88 with one DRAFT script hanging off it."""
    env = staffed_clinic(api, protocol={"requires_cosign": True})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Hank Hypoxic",
        date_of_birth="1968-08-08", payer_name="Aetna", member_id="M-5005",
        pcp_consent_on_file=False)
    env["patient"] = patient
    bundle = screening_visit(api, env, patient["id"])
    env["assessment"] = start_assessment(api, env, bundle["visit_id"], temp_c=38.1,
                                         heart_rate_bpm=96, spo2_pct=88)
    visit = read_visit(api, bundle["visit_id"], env["clinician_headers"])
    payload = prescription_payload(bundle["visit_id"], visit["version"])
    env["prescription"] = validate_success(
        api.create_prescription(payload, env["clinician_headers"]), 201)
    env["bundle"] = bundle
    return env


def test_an_oxygen_saturation_below_the_protocol_floor_forks_to_referral(api):
    """88 against a floor of 92 refers the patient to an emergency department.

    PRD: "**Hypoxia** fires when `spo2_pct` is strictly below the protocol's
    `min_spo2_pct`, and it also directs to an emergency department."

    Design: Difficulty/transitive_cascade/referral_submit_cancels_draft_prescription_and_clears_therapy_lock
    """
    env = _hypoxic_visit_with_a_draft_prescription(api)

    assessment = submit_assessment(api, env, env["assessment"]["id"])

    assert assessment["status"] == ASSESSMENT_REFERRAL_REQUIRED
    assert assessment["referral_reason_code"] == REASON_HYPOXIA
    assert assessment["referral_destination"] == REFERRAL_EMERGENCY_DEPARTMENT


def test_the_referred_assessment_carries_its_visit_to_referred(api):
    """The visit follows the assessment's fork and raises its referral flag.

    PRD: "On the referral branch, the linked visit advances `IN_ASSESSMENT →
    REFERRED` and its `referral_required` flag is set true; then every prescription on
    that visit whose status is `DRAFT` or `ROUTED` is cancelled; then, for each
    prescription that was cancelled, the patient's `active_therapy_classes` and
    `active_therapy_class_count` are recomputed."

    Design: Difficulty/transitive_cascade/referral_submit_cancels_draft_prescription_and_clears_therapy_lock
    """
    env = _hypoxic_visit_with_a_draft_prescription(api)

    submit_assessment(api, env, env["assessment"]["id"])

    visit = read_visit(api, env["bundle"]["visit_id"])
    assert visit["clinical_status"] == VISIT_REFERRED
    assert visit["referral_required"] is True


def test_the_referral_cancels_the_draft_script_and_leaves_no_therapy_lock(api):
    """The script is cancelled and the patient holds no therapy class at all.

    PRD: "then, for each prescription that was cancelled, the patient's
    `active_therapy_classes` and `active_therapy_class_count` are recomputed."

    Design: Difficulty/transitive_cascade/referral_submit_cancels_draft_prescription_and_clears_therapy_lock
    """
    env = _hypoxic_visit_with_a_draft_prescription(api)

    submit_assessment(api, env, env["assessment"]["id"])

    assert read_prescription(api,
                            env["prescription"]["id"])["status"] == PRESCRIPTION_CANCELLED
    patient = read_patient(api, env["patient"]["id"])
    assert patient["active_therapy_classes"] == []
    assert patient["active_therapy_class_count"] == 0
