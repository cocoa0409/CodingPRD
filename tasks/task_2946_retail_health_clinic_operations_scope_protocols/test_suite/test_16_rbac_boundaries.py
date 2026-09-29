"""Authority is partitioned: each rung of the identity ladder answers for itself."""
from test_helpers import (
    ASSESSMENT_COSIGNED,
    ASSESSMENT_DRAFT,
    ASSESSMENT_TREATMENT_AUTHORIZED,
    BILLING_COVERAGE_VERIFIED,
    CREDENTIAL_PA,
    NON_EXISTENT_UUID,
    OUTCOME_WITHIN_SCOPE,
    PRESCRIPTION_DRAFT,
    PRESCRIPTION_ROUTED,
    QUEUE_WAITING,
    REVIEW_ATTESTED,
    REVIEW_CHANGES_REQUESTED,
    REVIEW_PENDING,
    ROLE_CLINICIAN,
    ROLE_KIND_FLOAT,
    SUMMARY_QUEUED,
    VISIT_SCREENING,
    ApiErrorId,
    active_coverage_payload,
    add_walk_in,
    call_next,
    closed_insured_visit,
    create_clinician,
    create_insured_patient,
    create_physician,
    error_id,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_clinician_headers,
    make_headers,
    make_patient_headers,
    make_physician_headers,
    prescription_payload,
    read_assessment,
    read_chart_review,
    read_clinician,
    read_patient,
    read_prescription,
    read_queue_entry,
    read_visit,
    run_sampling,
    staffed_clinic,
    staffing_assignment_payload,
    start_assessment,
    submit_assessment,
    treated_visit,
    validate_error,
    validate_paginated,
    validate_success,
    visit_payload,
)

UNDECLARED_ROLE = "RegionalDirector"


def _called_walk_in_awaiting_its_visit(api):
    """Hal Header has been called from the queue; only his visit is left to open."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         physician={"full_name": "Dr Maple"},
                         clinician={"full_name": "NP Maple"})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Hal Header", date_of_birth="1984-08-08",
        payer_name="BlueCo", member_id="M-7272")
    env["patient"] = patient
    env["entry"] = add_walk_in(api, env, patient["id"])
    call_next(api, env)
    return env


def test_a_blank_identity_header_is_unauthenticated_before_anything_else_is_read(api):
    """The body carries an unknown field and an unknown id, yet rung one answers.

    PRD: "If either header is absent, or present but empty, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/corner_header_authentication_outranks_role_path_and_body_checks
    """
    env = _called_walk_in_awaiting_its_visit(api)
    payload = visit_payload(NON_EXISTENT_UUID, bogus_field="x")

    empty_role = api.create_visit(payload, headers_with_empty_role(env["clinician_id"]))
    empty_user = api.create_visit(payload, headers_with_empty_user_id(ROLE_CLINICIAN))
    absent_role = api.create_visit(payload, headers_without_role(env["clinician_id"]))
    absent_user = api.create_visit(payload, headers_without_user_id(ROLE_CLINICIAN))

    for response in (empty_role, empty_user, absent_role, absent_user):
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_an_undeclared_role_string_is_unauthenticated_and_not_forbidden(api):
    """A role outside the recognized five fails authentication, not authorization.

    PRD: "The same rejection applies when `X-User-Role` is not one of the five roles
    the system recognizes: `ClinicAdmin`, `Clinician`, `CollaboratingPhysician`,
    `FrontDeskAgent`, and `Patient`."

    Design: Corner/rbac/corner_header_authentication_outranks_role_path_and_body_checks
    """
    env = _called_walk_in_awaiting_its_visit(api)

    response = api.create_visit(visit_payload(env["entry"]["id"]),
                                make_headers(env["clinician_id"], UNDECLARED_ROLE))

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert error_id(response) != "ERR_FORBIDDEN_ROLE"


def test_a_wrong_role_and_an_unresolvable_clinician_both_answer_with_forbidden_role(api):
    """Rungs three and four share one error id, and neither of them is a 404.

    PRD: "For all three, an identifier that does not resolve to a row of its backing
    entity is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403) — the caller has claimed a
    clinical or personal identity the system cannot corroborate."

    Design: Corner/rbac/corner_header_authentication_outranks_role_path_and_body_checks
    """
    env = _called_walk_in_awaiting_its_visit(api)
    payload = visit_payload(env["entry"]["id"])

    wrong_role = api.create_visit(payload, env["front_desk"])
    unresolvable = api.create_visit(payload, make_clinician_headers(NON_EXISTENT_UUID))

    validate_error(wrong_role, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    validate_error(unresolvable, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert unresolvable.status_code != 404


def test_the_four_refused_calls_leave_the_treating_clinicians_visit_the_only_one(api):
    """Four rejected attempts persist nothing; the fifth opens the encounter.

    PRD: "A patient who clears the gate gets a visit created with `clinical_status` of
    `SCREENING` and `billing_status` of `UNBILLED`, its priced amounts —
    `quoted_price_cents`, `final_price_cents`, `patient_responsibility_cents`,
    `payer_responsibility_cents`, `copay_cents` and `coinsurance_pct` — all still null,
    its `coverage_status` at `UNVERIFIED`, its `self_pay` flag false, its
    `referral_required` flag false, and its `services_rendered` empty."

    Design: Corner/rbac/corner_header_authentication_outranks_role_path_and_body_checks
    """
    env = _called_walk_in_awaiting_its_visit(api)
    entry_id = env["entry"]["id"]
    api.create_visit(visit_payload(NON_EXISTENT_UUID, bogus_field="x"),
                     headers_with_empty_role(env["clinician_id"]))
    api.create_visit(visit_payload(entry_id),
                     make_headers(env["clinician_id"], UNDECLARED_ROLE))
    api.create_visit(visit_payload(entry_id), env["front_desk"])
    api.create_visit(visit_payload(entry_id), make_clinician_headers(NON_EXISTENT_UUID))

    visit = validate_success(
        api.create_visit(visit_payload(entry_id), env["clinician_headers"]), 201)

    assert visit["clinical_status"] == VISIT_SCREENING
    rows, meta = validate_paginated(
        api.list_visits(env["admin"], {"queue_entry_id": entry_id}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == visit["id"]


def _submitted_assessment_awaiting_its_cosignature(api):
    """Rose Roles is treated under a protocol that demands a countersignature."""
    env = staffed_clinic(api, protocol={"requires_cosign": True},
                         physician={"full_name": "Dr Nutmeg"},
                         clinician={"full_name": "NP Nutmeg"})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Rose Roles", date_of_birth="1988-02-02",
        payer_name="BlueCo", member_id="M-7373")
    env["patient"] = patient
    env["bundle"] = treated_visit(
        api, env, patient["id"],
        vitals={"temp_c": 37.1, "heart_rate_bpm": 78, "spo2_pct": 98})
    env["visit_id"] = env["bundle"]["visit_id"]
    env["assessment_id"] = env["bundle"]["assessment_id"]
    return env


def test_cosigning_is_closed_to_the_administrator_and_to_the_treating_clinician(api):
    """The countersignature belongs to one role, and neither of these two is it.

    PRD: "When the headers are well-formed but the declared role does not appear in the
    authorized-role list of the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/corner_each_roles_exclusive_operation_is_closed_to_the_other_four
    """
    env = _submitted_assessment_awaiting_its_cosignature(api)

    by_admin = api.cosign_assessment(env["assessment_id"], env["admin"])
    by_clinician = api.cosign_assessment(env["assessment_id"], env["clinician_headers"])

    validate_error(by_admin, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    validate_error(by_clinician, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert read_assessment(api, env["assessment_id"])["status"] == (
        ASSESSMENT_TREATMENT_AUTHORIZED)


def test_the_clinician_and_the_front_desk_may_not_borrow_each_others_work(api):
    """Eligibility is the desk's alone, and calling a patient is the clinician's alone.

    PRD: "A `FrontDeskAgent` registers patients, books and checks in queue entries, and
    runs insurance eligibility."

    Design: Corner/rbac/corner_each_roles_exclusive_operation_is_closed_to_the_other_four
    """
    env = _submitted_assessment_awaiting_its_cosignature(api)

    eligibility = api.eligibility_check(env["visit_id"], active_coverage_payload(),
                                       env["clinician_headers"])
    call = api.call_next(env["clinic_id"], env["front_desk"])

    validate_error(eligibility, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    validate_error(call, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert read_visit(api, env["visit_id"])["billing_status"] != BILLING_COVERAGE_VERIFIED


def test_staffing_creation_is_closed_to_the_collaborating_physician(api):
    """Supervising clinicians is not the same authority as rostering them.

    PRD: "A `ClinicAdmin` is a regional operations administrator: they own reference
    data, staffing, float coverage, sampling runs, reviewer reassignment, summary
    transmission, charge voids, and the logical clock, and they hold no clinical
    authority whatsoever."

    Design: Corner/rbac/corner_each_roles_exclusive_operation_is_closed_to_the_other_four
    """
    env = _submitted_assessment_awaiting_its_cosignature(api)

    response = api.create_staffing_assignment(
        staffing_assignment_payload(
            env["clinic_id"], env["clinician_id"], role_kind=ROLE_KIND_FLOAT,
            starts_at="2026-08-02T00:00:00Z", ends_at="2026-08-02T08:00:00Z",
            pinned_supervising_physician_id=env["physician_id"]),
        env["physician_headers"])

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    _rows, meta = validate_paginated(
        api.list_staffing_assignments(env["admin"], {"clinic_id": env["clinic_id"]}))
    assert meta["total_count"] == 1


def test_each_exclusive_operation_succeeds_for_the_one_role_that_owns_it(api):
    """The physician's countersignature and the desk's eligibility check both land.

    PRD: "A successful cosignature moves the assessment to `COSIGNED`, records the
    acting physician in `cosigned_by_physician_id` and stamps `cosigned_at` with the
    logical clock."

    Design: Corner/rbac/corner_each_roles_exclusive_operation_is_closed_to_the_other_four
    """
    env = _submitted_assessment_awaiting_its_cosignature(api)

    cosigned = validate_success(
        api.cosign_assessment(env["assessment_id"], env["physician_headers"]))
    verified = validate_success(
        api.eligibility_check(env["visit_id"], active_coverage_payload(),
                              env["front_desk"]))

    assert cosigned["status"] == ASSESSMENT_COSIGNED
    assert cosigned["cosigned_by_physician_id"] == env["physician_id"]
    assert verified["billing_status"] == BILLING_COVERAGE_VERIFIED


def _two_patients_one_of_whom_has_a_closed_visit(api):
    """Owen Owner's encounter is closed and summarised; Stan Stranger is a bystander."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         physician={"full_name": "Dr Olive"},
                         clinician={"full_name": "NP Olive"})
    owner = create_insured_patient(
        api, env["front_desk"], full_name="Owen Owner", date_of_birth="1977-07-17",
        payer_name="BlueCo", member_id="M-7474", pcp_name="Dr Primary",
        pcp_direct_address="owen.pcp@direct.example.org", pcp_consent_on_file=True)
    stranger = create_insured_patient(
        api, env["front_desk"], full_name="Stan Stranger", date_of_birth="1978-08-18",
        payer_name="BlueCo", member_id="M-7475")
    env["owner"] = owner
    env["stranger"] = stranger
    env["owner_headers"] = make_patient_headers(owner["id"])
    env["stranger_headers"] = make_patient_headers(stranger["id"])
    env["bundle"] = closed_insured_visit(
        api, env, owner["id"], services_rendered=[], copay_cents=2000,
        coinsurance_pct=10.0)
    env["visit_id"] = env["bundle"]["visit_id"]
    rows, _meta = validate_paginated(
        api.list_visit_summaries(env["admin"], {"visit_id": env["visit_id"]}))
    env["summary"] = rows[0]
    return env


def test_a_patient_may_not_read_another_patients_visit_or_patient_row(api):
    """The role clears the endpoint's list, then ownership refuses the specific row.

    PRD: "A caller acting as `Patient` may only read rows that belong to them: the
    patient reference on the target visit, patient record or visit summary must equal
    `X-User-ID`, else `ERR_FORBIDDEN_OWNERSHIP` (403)."

    Design: Corner/rbac/corner_patient_ownership_is_checked_after_the_role_list
    """
    env = _two_patients_one_of_whom_has_a_closed_visit(api)

    foreign_visit = api.get_visit(env["visit_id"], env["stranger_headers"])
    foreign_patient = api.get_patient(env["owner"]["id"], env["stranger_headers"])

    validate_error(foreign_visit, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
    validate_error(foreign_patient, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)


def test_a_patient_may_not_read_another_patients_visit_summary(api):
    """The summary is the third row the self-service rung guards.

    PRD: "Reading a single visit, a single patient row or a single visit summary as a
    `Patient` requires that the row's patient reference equal `X-User-ID`; anything else
    is `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/corner_patient_ownership_is_checked_after_the_role_list
    """
    env = _two_patients_one_of_whom_has_a_closed_visit(api)

    response = api.get_visit_summary(env["summary"]["id"], env["stranger_headers"])

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
    assert error_id(response) != "ERR_FORBIDDEN_ROLE"


def test_the_visit_collection_is_closed_to_a_patient_even_filtered_to_themselves(api):
    """A self-restricting filter cannot buy a role its way onto a collection.

    PRD: "When the headers are well-formed but the declared role does not appear in the
    authorized-role list of the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/corner_patient_ownership_is_checked_after_the_role_list
    """
    env = _two_patients_one_of_whom_has_a_closed_visit(api)

    response = api.list_visits(env["owner_headers"],
                               {"patient_id": env["owner"]["id"]})

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert error_id(response) != "ERR_FORBIDDEN_OWNERSHIP"


def test_the_owning_patient_reads_her_own_visit_and_her_own_summary(api):
    """The very reads refused to the stranger are granted to the owner.

    PRD: "And when — and only when — the patient's `pcp_consent_on_file` is true, a
    visit summary is created in `QUEUED` status for delivery to their primary care
    provider, with `includes_referral` set true if the visit closed from `REFERRED` and
    false if it closed from `TREATED`."

    Design: Corner/rbac/corner_patient_ownership_is_checked_after_the_role_list
    """
    env = _two_patients_one_of_whom_has_a_closed_visit(api)

    visit = validate_success(api.get_visit(env["visit_id"], env["owner_headers"]))
    summary = validate_success(
        api.get_visit_summary(env["summary"]["id"], env["owner_headers"]))

    assert visit["patient_id"] == env["owner"]["id"]
    assert summary["status"] == SUMMARY_QUEUED
    assert summary["includes_referral"] is False


def _an_on_duty_clinician_and_an_unstaffed_colleague(api):
    """NP Poplar A is on duty; NP Poplar B is registered but rostered nowhere."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         physician={"full_name": "Dr Poplar"},
                         clinician={"full_name": "NP Poplar A"})
    other = create_clinician(api, env["clinic_id"], env["physician_id"], env["admin"],
                             full_name="NP Poplar B", credential=CREDENTIAL_PA)
    env["other"] = other
    env["other_headers"] = make_clinician_headers(other["id"])
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Pia Proxy", date_of_birth="1976-06-16",
        payer_name="BlueCo", member_id="M-7575")
    env["patient"] = patient
    env["entry"] = add_walk_in(api, env, patient["id"])
    return env


def _an_authorized_treatment_written_by_the_on_duty_clinician(api):
    """The on-duty clinician calls Pia, opens her visit and authorizes treatment."""
    env = _an_on_duty_clinician_and_an_unstaffed_colleague(api)
    call_next(api, env)
    visit = validate_success(
        api.create_visit(visit_payload(env["entry"]["id"]), env["clinician_headers"]), 201)
    env["visit_id"] = visit["id"]
    env["assessment"] = start_assessment(api, env, visit["id"], temp_c=37.3,
                                         heart_rate_bpm=82, spo2_pct=98)
    return env


def _a_draft_prescription_on_that_treatment(api):
    """The authorized visit carries one DRAFT prescription awaiting the pharmacy."""
    env = _an_authorized_treatment_written_by_the_on_duty_clinician(api)
    submit_assessment(api, env, env["assessment"]["id"])
    treated = read_visit(api, env["visit_id"])
    env["prescription"] = validate_success(
        api.create_prescription(prescription_payload(env["visit_id"], treated["version"]),
                                env["clinician_headers"]), 201)
    return env


def test_a_clinician_not_on_duty_may_not_call_the_next_patient(api):
    """Being a Clinician is not enough; the roster decides who may call.

    PRD: "The caller must actually be working there: the acting clinician must hold a
    staffing assignment at that clinic in `ACTIVE` status, and a clinician calling into a
    clinic where they are not on duty is refused with `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/corner_only_the_treating_clinician_may_call_next_submit_and_route
    """
    env = _an_on_duty_clinician_and_an_unstaffed_colleague(api)

    refused = api.call_next(env["clinic_id"], env["other_headers"])

    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
    assert read_queue_entry(api, env["entry"]["id"])["status"] == QUEUE_WAITING
    called = validate_success(api.call_next(env["clinic_id"], env["clinician_headers"]))
    assert called["id"] == env["entry"]["id"]


def test_only_the_visits_own_clinician_may_submit_its_assessment(api):
    """A colleague may not finish another clinician's assessment for them.

    PRD: "The acting user must own the row they are transitioning: only the visit's own
    clinician may submit its assessment or route its prescription, and only the review's
    current reviewer may request changes or attest."

    Design: Corner/rbac/corner_only_the_treating_clinician_may_call_next_submit_and_route
    """
    env = _an_authorized_treatment_written_by_the_on_duty_clinician(api)

    refused = api.submit_assessment(env["assessment"]["id"], env["other_headers"])

    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
    assert read_assessment(api, env["assessment"]["id"])["status"] == ASSESSMENT_DRAFT
    submitted = validate_success(
        api.submit_assessment(env["assessment"]["id"], env["clinician_headers"]))
    assert submitted["status"] == ASSESSMENT_TREATMENT_AUTHORIZED


def test_only_the_visits_own_clinician_may_route_its_prescription(api):
    """The pharmacy handoff stays with the prescriber, and the draft stands unrouted.

    PRD: "Only the visit's own clinician may route, else `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/corner_only_the_treating_clinician_may_call_next_submit_and_route
    """
    env = _a_draft_prescription_on_that_treatment(api)

    refused = api.route_prescription(env["prescription"]["id"], env["other_headers"])

    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
    assert read_prescription(api, env["prescription"]["id"])["status"] == PRESCRIPTION_DRAFT
    assert read_patient(api, env["patient"]["id"])["active_therapy_class_count"] == 0


def test_the_treating_clinician_routes_and_takes_the_therapy_lock(api):
    """The owner's route lands, records her as prescriber and locks one class.

    PRD: "On success the prescription advances `DRAFT → ROUTED`, its `routed_at` is
    stamped with the logical clock, and the patient's `active_therapy_classes` gains this
    `therapy_class` with `active_therapy_class_count` recomputed as the length of that
    set."

    Design: Corner/rbac/corner_only_the_treating_clinician_may_call_next_submit_and_route
    """
    env = _a_draft_prescription_on_that_treatment(api)

    routed = validate_success(
        api.route_prescription(env["prescription"]["id"], env["clinician_headers"]))

    assert routed["status"] == PRESCRIPTION_ROUTED
    assert routed["prescriber_clinician_id"] == env["clinician_id"]
    assert read_patient(api, env["patient"]["id"])["active_therapy_class_count"] == 1


def _pending_review_owned_by_the_first_physician(api):
    """One closed chart is sampled, and Dr Quince One inherits it as reviewer."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         physician={"full_name": "Dr Quince One"},
                         clinician={"full_name": "NP Quince"})
    second = create_physician(api, env["admin"], full_name="Dr Quince Two")
    env["second_physician"] = second
    env["second_headers"] = make_physician_headers(second["id"])
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Quin Quiet", date_of_birth="1974-04-14",
        payer_name="BlueCo", member_id="M-7676", pcp_consent_on_file=False)
    env["patient"] = patient
    env["bundle"] = closed_insured_visit(
        api, env, patient["id"], services_rendered=[], copay_cents=2000,
        coinsurance_pct=10.0)
    run = run_sampling(api, env["clinic_id"], "2026-08-01T00:00:00Z",
                       "2026-08-02T00:00:00Z", headers=env["admin"])
    env["review_id"] = run["chart_review_ids"][0]
    return env


def _resubmitted_review_ready_for_reassignment(api):
    """The chart has been round-tripped once and sits PENDING with one cycle spent."""
    env = _pending_review_owned_by_the_first_physician(api)
    validate_success(api.request_chart_review_changes(
        env["review_id"], "Document the throat exam", env["physician_headers"]))
    validate_success(api.resubmit_chart_review(
        env["review_id"], "Exam findings added", env["clinician_headers"]))
    return env


def test_only_the_named_reviewer_may_send_the_chart_back_for_changes(api):
    """A second collaborating physician has the role but not this review.

    PRD: "The reviewing physician — and only the physician currently named in
    `reviewer_physician_id`, else `ERR_FORBIDDEN_OWNERSHIP` — may send a chart back with a
    `change_note`, moving it `PENDING → CHANGES_REQUESTED` and raising
    `changes_requested_count` by 1."

    Design: Corner/rbac/corner_review_ownership_follows_the_reassignment
    """
    env = _pending_review_owned_by_the_first_physician(api)
    assert read_chart_review(api, env["review_id"])["reviewer_physician_id"] == (
        env["physician_id"])

    refused = api.request_chart_review_changes(
        env["review_id"], "Not my chart", env["second_headers"])
    owned = validate_success(api.request_chart_review_changes(
        env["review_id"], "Document the throat exam", env["physician_headers"]))

    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
    assert owned["status"] == REVIEW_CHANGES_REQUESTED
    assert owned["changes_requested_count"] == 1


def test_the_treating_clinician_and_not_the_reviewer_answers_the_change_request(api):
    """The amended chart comes back from the floor, and the counter holds at one.

    PRD: "The treating clinician — the clinician recorded on the reviewed visit, else
    `ERR_FORBIDDEN_OWNERSHIP` — answers by returning the amended chart with an
    `amendment_note`, which moves it `CHANGES_REQUESTED → PENDING` and closes one cycle
    without resetting the counter."

    Design: Corner/rbac/corner_review_ownership_follows_the_reassignment
    """
    env = _pending_review_owned_by_the_first_physician(api)
    validate_success(api.request_chart_review_changes(
        env["review_id"], "Document the throat exam", env["physician_headers"]))

    by_physician = api.resubmit_chart_review(
        env["review_id"], "Signed off myself", env["physician_headers"])
    by_clinician = validate_success(api.resubmit_chart_review(
        env["review_id"], "Exam findings added", env["clinician_headers"]))

    validate_error(by_physician, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert by_clinician["status"] == REVIEW_PENDING
    assert by_clinician["changes_requested_count"] == 1


def test_reassignment_hands_the_review_to_the_other_physician_while_it_stays_pending(api):
    """The administrator changes the owner without changing the state or the counter.

    PRD: "On success `reviewer_physician_id` is replaced, the status stays `PENDING`, and
    `due_at` is deliberately left unchanged — reassignment does not buy the clinic more
    time."

    Design: Corner/rbac/corner_review_ownership_follows_the_reassignment
    """
    env = _resubmitted_review_ready_for_reassignment(api)

    reassigned = validate_success(
        api.reassign_chart_review(env["review_id"], env["admin"]))

    assert reassigned["reviewer_physician_id"] == env["second_physician"]["id"]
    assert reassigned["status"] == REVIEW_PENDING
    assert reassigned["changes_requested_count"] == 1


def test_attestation_follows_the_reassignment_to_the_new_reviewer(api):
    """The displaced physician is refused and the new owner closes the chart.

    PRD: "Both outcomes require that the review be `PENDING` and that the attester be its
    current reviewer."

    Design: Corner/rbac/corner_review_ownership_follows_the_reassignment
    """
    env = _resubmitted_review_ready_for_reassignment(api)
    validate_success(api.reassign_chart_review(env["review_id"], env["admin"]))

    refused = api.attest_chart_review(env["review_id"], OUTCOME_WITHIN_SCOPE,
                                      env["physician_headers"])
    attested = validate_success(api.attest_chart_review(
        env["review_id"], OUTCOME_WITHIN_SCOPE, env["second_headers"],
        attestation_note="Care within scope"))

    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
    assert attested["status"] == REVIEW_ATTESTED
    assert attested["outcome"] == OUTCOME_WITHIN_SCOPE
    assert read_clinician(api, env["clinician_id"])["scope_hold"] is False
