"""A valid payload refused only because a neighbouring entity sits in the wrong state."""
from test_helpers import (
    CLINIC_LIMITED,
    PRESCRIPTION_DRAFT,
    QUEUE_KIND_APPOINTMENT,
    QUEUE_SCHEDULED,
    VISIT_CLOSED,
    VISIT_TREATED,
    ApiErrorId,
    add_appointment,
    checkout,
    create_insured_patient,
    create_patient,
    prescription_payload,
    read_clinic,
    read_patient,
    read_prescription,
    read_visit,
    staffed_clinic,
    treated_visit,
    validate_error,
    validate_success,
    verify_active_coverage,
    walk_in_payload,
)


def _limited_clinic_with_two_patients(api):
    """One clinician on duty at a site whose floor is two, so the posture is LIMITED."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         clinic={"min_clinicians_required": 2})
    env["walk_in_patient"] = create_patient(api, env["front_desk"],
                                            full_name="Wanda Walkin",
                                            date_of_birth="1982-02-02")
    env["appointment_patient"] = create_patient(api, env["front_desk"],
                                                full_name="Percy Booked",
                                                date_of_birth="1981-01-21")
    return env


def test_one_clinician_below_the_floor_puts_the_clinic_in_limited(api):
    """An on-duty count of 1 against a floor of 2 is the partial posture.

    PRD: "Hop two re-derives `open_status` from the new count, moving `OPEN → LIMITED`
    when the count is above 0 but below `min_clinicians_required`, and `OPEN → CLOSED`
    or `LIMITED → CLOSED` when it reaches 0."

    Design: Difficulty/cross_entity_state_dependency/walk_in_blocked_while_clinic_limited_but_appointment_admitted
    """
    env = _limited_clinic_with_two_patients(api)

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["on_duty_clinician_count"] == 1
    assert clinic["open_status"] == CLINIC_LIMITED


def test_a_limited_clinic_suspends_walk_in_intake(api):
    """The walk-in payload is impeccable; the clinic's posture is what refuses it.

    PRD: "The clinic must be fully `OPEN`: a `LIMITED` clinic — one that has some
    clinician on duty but fewer than its floor — refuses walk-ins with
    `ERR_WALK_IN_SUSPENDED`, and a `CLOSED` clinic refuses them with
    `ERR_CLINIC_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/walk_in_blocked_while_clinic_limited_but_appointment_admitted
    """
    env = _limited_clinic_with_two_patients(api)
    payload = walk_in_payload(env["clinic_id"], env["walk_in_patient"]["id"])

    response = api.create_queue_entry(payload, env["front_desk"])

    validate_error(response, ApiErrorId.ERR_WALK_IN_SUSPENDED, 409)
    assert read_clinic(api, env["clinic_id"])["waiting_count"] == 0


def test_the_same_limited_clinic_still_books_an_appointment(api):
    """The suspension is deliberately partial: booking is untouched by LIMITED.

    PRD: "An appointment is booked rather than admitted; it is created in `SCHEDULED`
    status and waits for the patient to show up."

    Design: Difficulty/cross_entity_state_dependency/walk_in_blocked_while_clinic_limited_but_appointment_admitted
    """
    env = _limited_clinic_with_two_patients(api)

    entry = add_appointment(api, env, env["appointment_patient"]["id"],
                            "2026-08-01T09:00:00Z")

    assert entry["status"] == QUEUE_SCHEDULED
    assert entry["kind"] == QUEUE_KIND_APPOINTMENT
    assert read_clinic(api, env["clinic_id"])["waiting_count"] == 0


def _closed_visit_holding_a_draft_prescription(api):
    """A DRAFT script written while the visit was TREATED, then checkout closed it."""
    env = staffed_clinic(api, protocol={"requires_cosign": False})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Rose Routed", date_of_birth="1975-07-07",
        payer_name="BlueCo", member_id="M-7007", pcp_consent_on_file=False)
    env["patient"] = patient
    bundle = treated_visit(api, env, patient["id"],
                           vitals={"temp_c": 37.6, "heart_rate_bpm": 88,
                                   "spo2_pct": 97})
    treated = read_visit(api, bundle["visit_id"], env["clinician_headers"])
    assert treated["clinical_status"] == VISIT_TREATED
    env["prescription"] = validate_success(api.create_prescription(
        prescription_payload(bundle["visit_id"], treated["version"]),
        env["clinician_headers"]), 201)
    verify_active_coverage(api, env, bundle["visit_id"], copay_cents=2500,
                           coinsurance_pct=12.5)
    checkout(api, env, bundle["visit_id"], services_rendered=[])
    env["bundle"] = bundle
    return env


def test_routing_reads_the_visit_state_and_a_closed_visit_is_not_treatable(api):
    """The script is still a valid DRAFT, but its visit has moved past TREATED.

    PRD: "The visit must be in `clinical_status` of `TREATED`; a visit that has moved
    on to `CLOSED`, or that never reached `TREATED` at all, is refused with
    `ERR_VISIT_NOT_TREATABLE`."

    Design: Difficulty/cross_entity_state_dependency/prescription_route_blocked_once_its_visit_is_closed
    """
    env = _closed_visit_holding_a_draft_prescription(api)

    response = api.route_prescription(env["prescription"]["id"],
                                      env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_VISIT_NOT_TREATABLE, 409)
    assert read_visit(api, env["bundle"]["visit_id"])["clinical_status"] == VISIT_CLOSED


def test_the_refused_route_leaves_the_prescription_a_draft_with_no_route_stamp(api):
    """Nothing on the prescription moved, so `routed_at` is still null.

    PRD: "A fresh draft has `status` of `DRAFT` and a null `routed_at`."

    Design: Difficulty/cross_entity_state_dependency/prescription_route_blocked_once_its_visit_is_closed
    """
    env = _closed_visit_holding_a_draft_prescription(api)

    api.route_prescription(env["prescription"]["id"], env["clinician_headers"])

    prescription = read_prescription(api, env["prescription"]["id"])
    assert prescription["status"] == PRESCRIPTION_DRAFT
    assert prescription["routed_at"] is None


def test_the_refused_route_takes_no_therapy_lock_for_the_patient(api):
    """The lock is only taken on a successful route, so the set stays empty.

    PRD: "On success the prescription advances `DRAFT → ROUTED`, its `routed_at` is
    stamped with the logical clock, and the patient's `active_therapy_classes` gains
    this `therapy_class` with `active_therapy_class_count` recomputed as the length of
    that set."

    Design: Difficulty/cross_entity_state_dependency/prescription_route_blocked_once_its_visit_is_closed
    """
    env = _closed_visit_holding_a_draft_prescription(api)

    api.route_prescription(env["prescription"]["id"], env["clinician_headers"])

    patient = read_patient(api, env["patient"]["id"])
    assert patient["active_therapy_classes"] == []
    assert patient["active_therapy_class_count"] == 0
