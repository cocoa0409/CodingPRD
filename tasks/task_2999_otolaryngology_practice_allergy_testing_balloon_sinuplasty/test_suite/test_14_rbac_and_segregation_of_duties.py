"""Role-based access control and the segregation-of-duties identity rules."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def test_creation_endpoints_refuse_every_role_outside_their_declared_list(api):
    """PRD 2.1: "A header present and non-blank but naming something that is not
    one of the six declared roles, or naming a role that the target endpoint does
    not list, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_returns_403_for_other_roles
    """
    # Registering a plan, a chart, a lot and a block belongs to the practice
    # administrator alone, so the physician, the nurse and the technician are all
    # refused on the endpoints that neighbour their own work.
    validate_error(
        api.create_payer_policy(
            F.payer_policy_payload(payer_name="Nope Health", plan_code="RBAX-2999"),
            USERS.ENT_1,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.create_patient(
            F.patient_payload(
                NON_EXISTENT_UUID,
                mrn=C.mrn(19999),
                full_name="Role Probe",
                date_of_birth="1980-01-01",
            ),
            USERS.NURSE_1,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.create_supply_lot(
            F.supply_lot_payload(
                "2028-01-01T00:00:00Z",
                item_type=C.ITEM_TYPE_BALLOON_DEVICE,
                lot_number=C.lot_number(1999),
                quantity_received=1,
            ),
            USERS.TECH_1,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.create_surgery_center_block(
            F.surgery_center_block_payload(
                "2026-08-05T08:00:00Z",
                "2026-08-05T12:00:00Z",
                center_name="Nope Center",
            ),
            USERS.ENT_1,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.set_clock("2026-08-02T00:00:00Z", USERS.LIAISON_1),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    # The clinical creations are each owned by one clinical role, and the
    # neighbouring clinician does not inherit them.
    validate_error(
        api.create_sinuplasty_case(
            F.sinuplasty_case_payload(
                NON_EXISTENT_UUID,
                laterality=C.LATERALITY_LEFT,
                sinuses=[C.SINUS_MAXILLARY],
            ),
            USERS.LIAISON_1,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.create_diagnostic_study(
            F.diagnostic_study_payload(NON_EXISTENT_UUID, study_type=C.STUDY_AUDIOMETRY),
            USERS.AUD_1,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.create_allergy_test_order(
            F.allergy_test_order_payload(
                NON_EXISTENT_UUID,
                panel_code=C.PANEL_MOLD_12,
                method=C.METHOD_SKIN_PRICK,
            ),
            USERS.AUD_1,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    # Not one of the refused creations left a row behind.
    rows, meta = validate_paginated(api.list_patients(USERS.ADMIN_1))
    assert rows == [], "a refused creation must leave no patient row behind"
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_the_role_gate_answers_before_the_path_identifier_is_resolved(api):
    """PRD 2.8: "**The first rung that finds a violation produces the response;
    every higher-numbered rung is armed but never reached.**"

    Design: Corner/rbac/exclusive_operations_returns_403_for_other_roles
    """
    # Every identifier below belongs to no row at all, yet the answer is the
    # role refusal of rung 2 rather than the 404 of rung 4.
    validate_error(
        api.void_immunotherapy_dose(
            NON_EXISTENT_UUID, F.dose_void_payload(), USERS.AUD_1
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.record_payer_decision(
            NON_EXISTENT_UUID, F.payer_decision_payload("PA-79999"), USERS.ENT_1
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.start_reprocessing(NON_EXISTENT_UUID, USERS.NURSE_1),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.settle_device_refund(NON_EXISTENT_UUID, USERS.AUD_1),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    # The administrator creates and cancels bookings, and is still refused the
    # start, which belongs to the operating physician alone.
    validate_error(
        api.start_procedure_booking(NON_EXISTENT_UUID, USERS.ADMIN_1),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )


def test_the_candidacy_projection_is_the_one_read_closed_to_three_roles(api):
    """PRD 3.6: "A `PracticeAdmin`, an `Otolaryngologist` or a `PayerLiaison` may
    recompute and read the determination without mutating anything."

    Design: Corner/rbac/exclusive_operations_returns_403_for_other_roles
    """
    # The three roles the projection does not list are refused before the case
    # identifier is even resolved.
    for headers in (USERS.NURSE_1, USERS.AUD_1, USERS.TECH_1):
        validate_error(
            api.get_candidacy_evaluation(NON_EXISTENT_UUID, headers),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
        )

    # Every other read in the service stays open to those same roles.
    for headers in (USERS.NURSE_1, USERS.AUD_1, USERS.TECH_1):
        rows, meta = validate_paginated(api.list_patients(headers))
        assert rows == []
        assert meta["total_count"] == 0


def test_an_undeclared_role_is_refused_while_a_blank_role_is_unauthenticated(api):
    """PRD 2.1: "If either header is missing, supplied as an empty string, or
    supplied as whitespace only, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/exclusive_operations_returns_403_for_other_roles
    """
    # A role naming nothing in the declared set of six is a role refusal, not a
    # shape complaint.
    validate_error(
        api.list_patients(USERS.headers_for("u_front_1", C.UNDECLARED_ROLE)),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    # An empty role header is answered one rung earlier, by the identity gate.
    validate_error(
        api.list_patients(USERS.headers_with_blank_role(C.USER_ADMIN_1)),
        ApiErrorId.UNAUTHENTICATED.value,
    )

    # Neither refusal wrote anything.
    rows, meta = validate_paginated(api.list_patients(USERS.ADMIN_1))
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


SHARED_PLAN_TERMS = {
    "payer_name": "Shared Health",
    "requires_prior_auth": True,
    "min_documented_criteria": 2,
    "min_medical_management_days": 28,
    "requires_ct_within_months": 12,
}


def _shared_access_patient(api):
    """A strict plan and one adult chart under it, for the shared endpoints."""
    policy = SETUP.create_policy(api, plan_code="RBAA-2999", **SHARED_PLAN_TERMS)
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10249),
        full_name="Shared Access",
        date_of_birth="1960-03-03",
        epinephrine_on_file=True,
    )
    return policy, patient


def test_an_allergy_panel_is_ordered_by_the_physician_and_by_the_nurse_alike(api):
    """PRD 3.2: "An `Otolaryngologist` or an `AllergyNurse` opens a panel by naming
    the `patient_id`, choosing a `panel_code` from `ENV_36`, `FOOD_24`, `MOLD_12`
    and `VENOM_5`, and choosing a `method` from `SKIN_PRICK`, `INTRADERMAL` and
    `SERUM_IGE`."

    Design: Corner/rbac/shared_operations_permitted_for_both_declared_roles
    """
    _policy, patient = _shared_access_patient(api)

    # The physician opens the first panel.
    first = validate_success(
        api.create_allergy_test_order(
            F.allergy_test_order_payload(
                patient["id"],
                panel_code=C.PANEL_MOLD_12,
                method=C.METHOD_SKIN_PRICK,
            ),
            USERS.ENT_1,
        ),
        201,
    )
    check.assert_allergy_test_order(
        first,
        status=C.ORDER_ORDERED,
        method=C.METHOD_SKIN_PRICK,
        panel_code=C.PANEL_MOLD_12,
        ordered_by_user_id=C.USER_ENT_1,
    )

    # The nurse opens the second, and the initial state is identical.
    second = validate_success(
        api.create_allergy_test_order(
            F.allergy_test_order_payload(
                patient["id"],
                panel_code=C.PANEL_VENOM_5,
                method=C.METHOD_INTRADERMAL,
            ),
            USERS.NURSE_1,
        ),
        201,
    )
    check.assert_allergy_test_order(
        second,
        status=C.ORDER_ORDERED,
        method=C.METHOD_INTRADERMAL,
        panel_code=C.PANEL_VENOM_5,
        ordered_by_user_id=C.USER_NURSE_1,
    )


def test_the_patient_chart_is_revised_by_the_admin_and_by_the_nurse_on_one_row(api):
    """PRD 3.1: "A `PracticeAdmin` or an `AllergyNurse` may revise the three
    patient-reported intake facts — `antihistamine_last_dose_at`,
    `epinephrine_on_file` and `prior_systemic_reaction_count` — at any time."

    Design: Corner/rbac/shared_operations_permitted_for_both_declared_roles
    """
    _policy, patient = _shared_access_patient(api)
    assert patient["version"] == 1

    # The administrator corrects the reaction history.
    after_admin = check.validate_unpaginated(
        api.patch_patient(
            patient["id"],
            F.patient_patch_payload(prior_systemic_reaction_count=1),
            USERS.ADMIN_1,
        )
    )
    check.assert_patient(after_admin, version=2, prior_systemic_reaction_count=1)

    # The nurse writes to the very same row, and the counter simply climbs.
    after_nurse = check.validate_unpaginated(
        api.patch_patient(
            patient["id"],
            F.patient_patch_payload(epinephrine_on_file=True),
            USERS.NURSE_1,
        )
    )
    check.assert_patient(after_nurse, version=3, epinephrine_on_file=True)


def test_a_procedure_is_scheduled_by_the_admin_and_by_the_physician_alike(api):
    """PRD 3.9: "A `PracticeAdmin` or an `Otolaryngologist` schedules a procedure
    by supplying the `patient_id`, the `procedure_type` (`BALLOON_SINUPLASTY`,
    `DIAGNOSTIC_ENDOSCOPY`, `TYMPANOSTOMY_TUBES` or `TONSILLECTOMY`), the `venue`
    (`IN_OFFICE_SUITE` or `SURGERY_CENTER`), the `start_at` and `end_at` instants
    with `end_at` strictly after `start_at`, and the `physician_user_id` of the
    otolaryngologist of record."

    Design: Corner/rbac/shared_operations_permitted_for_both_declared_roles
    """
    _policy, patient = _shared_access_patient(api)

    # The administrator books the morning slot.
    admin_booking = validate_success(
        api.create_procedure_booking(
            SETUP.booking_payload(
                patient["id"],
                "2026-08-04T09:00:00Z",
                "2026-08-04T10:00:00Z",
                physician_user_id=C.USER_ENT_1,
                procedure_type=C.PROCEDURE_TONSILLECTOMY,
                venue=C.VENUE_IN_OFFICE_SUITE,
            ),
            USERS.ADMIN_1,
        ),
        201,
    )
    check.assert_procedure_booking(
        admin_booking,
        status=C.BOOKING_SCHEDULED,
        duration_minutes=60,
        physician_user_id=C.USER_ENT_1,
    )

    # The physician books the late-morning slot on the same shared endpoint.
    physician_booking = validate_success(
        api.create_procedure_booking(
            SETUP.booking_payload(
                patient["id"],
                "2026-08-04T11:00:00Z",
                "2026-08-04T12:00:00Z",
                physician_user_id=C.USER_ENT_1,
                procedure_type=C.PROCEDURE_TONSILLECTOMY,
                venue=C.VENUE_IN_OFFICE_SUITE,
            ),
            USERS.ENT_1,
        ),
        201,
    )
    check.assert_procedure_booking(
        physician_booking,
        status=C.BOOKING_SCHEDULED,
        duration_minutes=60,
        physician_user_id=C.USER_ENT_1,
    )


def test_a_study_is_interpreted_by_an_audiologist_and_by_a_physician_alike(api):
    """PRD 3.7: "Either an `Otolaryngologist` or an `Audiologist` interprets a
    `PERFORMED` study, with no request body."

    Design: Corner/rbac/shared_operations_permitted_for_both_declared_roles
    """
    _policy, patient = _shared_access_patient(api)

    # Two audiometries measured by the same audiologist.
    first = SETUP.create_study(api, patient["id"], headers=USERS.ENT_1)
    SETUP.record_audiometry_results(api, first["id"], 58.0, 60.0, headers=USERS.AUD_1)
    second = SETUP.create_study(api, patient["id"], headers=USERS.ENT_1)
    SETUP.record_audiometry_results(api, second["id"], 58.0, 60.0, headers=USERS.AUD_1)

    # The second audiologist reads the first study.
    by_audiologist = check.validate_unpaginated(
        api.interpret_diagnostic_study(first["id"], USERS.AUD_2)
    )
    check.assert_diagnostic_study(
        by_audiologist,
        status=C.STUDY_INTERPRETED,
        recommendation=C.RECOMMENDATION_HEARING_AID,
        interpreted_by_user_id=C.USER_AUD_2,
    )

    # A physician reads the second one, to the same effect.
    by_physician = check.validate_unpaginated(
        api.interpret_diagnostic_study(second["id"], USERS.ENT_2)
    )
    check.assert_diagnostic_study(
        by_physician,
        status=C.STUDY_INTERPRETED,
        recommendation=C.RECOMMENDATION_HEARING_AID,
        interpreted_by_user_id=C.USER_ENT_2,
    )


def test_the_candidacy_projection_reads_alike_for_each_of_its_three_roles(api):
    """PRD 3.6: "It performs no state transition and increments no `version`."

    Design: Corner/rbac/shared_operations_permitted_for_both_declared_roles
    """
    _policy, patient = _shared_access_patient(api)

    # One documented case with twenty-eight contiguous management days and the
    # two criteria the strict plan demands.
    case = SETUP.create_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_LEFT,
        sinuses=[C.SINUS_FRONTAL],
        headers=USERS.ENT_1,
    )
    documented = SETUP.document_case(
        api,
        case["id"],
        therapies=list(SETUP.ADJACENT_TWENTY_EIGHT_DAY_COURSES),
        criteria=[C.CRITERION_CT_OPACIFICATION, C.CRITERION_FAILED_INCS],
        ct_study_date="2026-05-01",
        headers=USERS.ENT_1,
    )
    version_before = documented["version"]

    # All three declared roles recompute the determination and see one answer.
    readings = []
    for headers in (USERS.ADMIN_1, USERS.ENT_1, USERS.LIAISON_1):
        reading = check.validate_unpaginated(
            api.get_candidacy_evaluation(case["id"], headers)
        )
        check.assert_candidacy_evaluation(
            reading,
            evaluation_variant=C.EVAL_VARIANT_POLICY_STRICT,
            criteria_met_count=2,
            contiguous_management_days=28,
            cumulative_management_days=28,
            candidacy_status=C.CANDIDACY_ELIGIBLE,
            min_documented_criteria_required=2,
            min_medical_management_days_required=28,
        )
        readings.append(reading)
    assert readings[0] == readings[1] == readings[2], (
        "the projection must read identically for each of its declared roles"
    )

    # Three reads mutated nothing.
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case["id"]),
        version=version_before,
        status=C.CASE_DOCUMENTED,
    )


DUTY_PLAN_TERMS = {
    "payer_name": "Duty Health",
    "requires_prior_auth": True,
    "min_documented_criteria": 2,
    "min_medical_management_days": 28,
    "requires_ct_within_months": 12,
    "device_trial_days": 30,
    "restock_fee_bps": 1500,
    "restock_fee_floor_cents": 12500,
}


def _duty_patient(api):
    """A strict plan and one adult chart, for the five identity rules."""
    policy = SETUP.create_policy(api, plan_code="RBAB-2999", **DUTY_PLAN_TERMS)
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10250),
        full_name="Silje Haugen",
        date_of_birth="1956-04-18",
        epinephrine_on_file=True,
    )
    return policy, patient


def test_a_vial_label_may_not_be_verified_by_the_nurse_who_compounded_it(api):
    """PRD 2.9: "The staff member who verifies a vial's label must differ from the
    `mixed_by_user_id` recorded when the vial was compounded, or the verification
    is refused with `ERR_SELF_VERIFICATION_FORBIDDEN`."

    Design: Corner/rbac/segregation_of_duties_across_five_actor_identity_rules
    """
    _policy, patient = _duty_patient(api)
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_ALLERGEN_CONCENTRATE,
        lot_no=C.lot_number(1031),
        quantity_received=4,
    )

    # The first nurse compounds the vial, and her identity is recorded on it.
    vial = SETUP.mix_vial(
        api,
        patient,
        lot["id"],
        dilution_code=C.DILUTION_BLUE,
        expires_at="2026-12-01T00:00:00Z",
        headers=USERS.NURSE_1,
    )
    check.assert_immunotherapy_vial(
        vial,
        status=C.VIAL_MIXED,
        mixed_by_user_id=C.USER_NURSE_1,
        verified_by_user_id=None,
        label_text=C.make_label_text(C.mrn(10250), C.DILUTION_BLUE, "2026-12-01T00:00:00Z"),
    )

    # She may not then verify her own work.
    validate_error(
        api.verify_immunotherapy_vial_label(
            vial["id"],
            F.label_verification_payload(vial["label_text"]),
            USERS.NURSE_1,
        ),
        ApiErrorId.SELF_VERIFICATION_FORBIDDEN.value,
    )

    # A second nurse retypes the same label and the vial activates.
    verified = check.validate_unpaginated(
        api.verify_immunotherapy_vial_label(
            vial["id"],
            F.label_verification_payload(vial["label_text"]),
            USERS.NURSE_2,
        )
    )
    check.assert_immunotherapy_vial(
        verified,
        status=C.VIAL_LABEL_VERIFIED,
        mixed_by_user_id=C.USER_NURSE_1,
        verified_by_user_id=C.USER_NURSE_2,
    )


def test_a_payer_decision_may_not_be_recorded_by_the_liaison_who_submitted_it(api):
    """PRD 2.9: "The staff member who records a payer decision must differ from the
    `submitted_by_user_id` recorded on the case's current submission, or the
    decision is refused with `ERR_SELF_DECISION_FORBIDDEN`."

    Design: Corner/rbac/segregation_of_duties_across_five_actor_identity_rules
    """
    _policy, patient = _duty_patient(api)

    # An eligible case, filed with the payer by the first liaison.
    case = SETUP.create_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_LEFT,
        sinuses=[C.SINUS_MAXILLARY],
        headers=USERS.ENT_1,
    )
    SETUP.document_case(
        api,
        case["id"],
        therapies=list(SETUP.ADJACENT_TWENTY_EIGHT_DAY_COURSES),
        criteria=[C.CRITERION_CT_OPACIFICATION, C.CRITERION_FAILED_INCS],
        ct_study_date="2026-05-01",
        headers=USERS.ENT_1,
    )
    submitted = SETUP.submit_case(api, case["id"], headers=USERS.LIAISON_1)
    check.assert_sinuplasty_case(
        submitted,
        status=C.CASE_AUTH_SUBMITTED,
        submitted_by_user_id=C.USER_LIAISON_1,
    )

    # The person who filed the submission may not record what the payer said.
    validate_error(
        api.record_payer_decision(
            case["id"],
            F.payer_decision_payload("PA-77301", decision=C.DECISION_APPROVED),
            USERS.LIAISON_1,
        ),
        ApiErrorId.SELF_DECISION_FORBIDDEN.value,
    )

    # The second liaison records the approval.
    decided = check.validate_unpaginated(
        api.record_payer_decision(
            case["id"],
            F.payer_decision_payload("PA-77301", decision=C.DECISION_APPROVED),
            USERS.LIAISON_2,
        )
    )
    check.assert_sinuplasty_case(
        decided,
        status=C.CASE_AUTHORIZED,
        authorized_device_count=1,
        payer_reference="PA-77301",
    )


def test_a_study_may_not_be_interpreted_by_the_audiologist_who_measured_it(api):
    """PRD 2.9: "The staff member who interprets a study must differ from the
    `performed_by_user_id` recorded when the results were entered, or the
    interpretation is refused with `ERR_SELF_INTERPRETATION_FORBIDDEN`."

    Design: Corner/rbac/segregation_of_duties_across_five_actor_identity_rules
    """
    _policy, patient = _duty_patient(api)

    # One audiometry measured by the first audiologist.
    study = SETUP.create_study(api, patient["id"], headers=USERS.ENT_1)
    performed = SETUP.record_audiometry_results(
        api, study["id"], 60.0, 56.0, headers=USERS.AUD_1
    )
    check.assert_diagnostic_study(
        performed, status=C.STUDY_PERFORMED, performed_by_user_id=C.USER_AUD_1
    )

    # The clinician who measured may not also be the clinician who reads.
    validate_error(
        api.interpret_diagnostic_study(study["id"], USERS.AUD_1),
        ApiErrorId.SELF_INTERPRETATION_FORBIDDEN.value,
    )

    # The second audiologist interprets it.
    interpreted = check.validate_unpaginated(
        api.interpret_diagnostic_study(study["id"], USERS.AUD_2)
    )
    check.assert_diagnostic_study(
        interpreted,
        status=C.STUDY_INTERPRETED,
        recommendation=C.RECOMMENDATION_HEARING_AID,
        interpreted_by_user_id=C.USER_AUD_2,
    )


def test_a_refund_may_not_be_settled_by_the_audiologist_who_dispensed_the_device(api):
    """PRD 2.9: "The staff member who settles a refund must differ from the
    `dispensed_by_user_id` recorded when the device went out, or the settlement
    is refused with `ERR_SELF_SETTLEMENT_FORBIDDEN`."

    Design: Corner/rbac/segregation_of_duties_across_five_actor_identity_rules
    """
    _policy, patient = _duty_patient(api)
    study = SETUP.create_study(api, patient["id"], headers=USERS.ENT_1)
    SETUP.record_audiometry_results(api, study["id"], 60.0, 56.0, headers=USERS.AUD_1)
    SETUP.interpret_study(api, study["id"], headers=USERS.AUD_2)
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1032),
        quantity_received=3,
        expires_at="2028-01-01T00:00:00Z",
    )

    # The first audiologist fits the aid, so the sale carries her identity.
    dispense = SETUP.create_dispense(
        api,
        study["id"],
        lot["id"],
        serial=C.device_serial("HA", 400007),
        price_cents=210000,
        ear=C.EAR_BOTH,
        headers=USERS.AUD_1,
    )
    check.assert_device_dispense(
        dispense,
        device_serial=C.device_serial("HA", 400007),
        ear=C.EAR_BOTH,
        price_cents=210000,
        dispensed_by_user_id=C.USER_AUD_1,
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
    )

    # The patient brings it back inside the trial window.
    returned = SETUP.return_dispense(
        api, dispense["id"], C.RETURN_REASON_POOR_FIT, headers=USERS.AUD_1
    )
    check.assert_device_dispense(
        returned,
        fit_status=C.FIT_RETURNED,
        billing_status=C.BILLING_REFUND_PENDING,
        restock_fee_cents=31500,
        refund_cents=178150,
    )

    # The same identity carried under an administrator's capacity is still the
    # person who dispensed, so the money may not close in her hands.
    validate_error(
        api.settle_device_refund(
            dispense["id"], USERS.headers_for(C.USER_AUD_1, C.ROLE_PRACTICE_ADMIN)
        ),
        ApiErrorId.SELF_SETTLEMENT_FORBIDDEN.value,
    )

    # An administrator who never touched the device settles it.
    settled = check.validate_unpaginated(
        api.settle_device_refund(dispense["id"], USERS.ADMIN_1)
    )
    check.assert_device_dispense(
        settled,
        billing_status=C.BILLING_REFUNDED,
        settled_by_user_id=C.USER_ADMIN_1,
        fit_status=C.FIT_RETURNED,
        restock_fee_cents=31500,
        refund_cents=178150,
    )


def test_a_disinfection_run_is_closed_only_by_the_technician_who_opened_it(api):
    """PRD 2.9: "A disinfection run must be closed by the same technician who
    opened it: the identifier on the completion must **equal** the scope's
    `reprocessing_started_by_user_id`, and a mismatch is refused with
    `ERR_REPROCESSING_TECH_MISMATCH`."

    Design: Corner/rbac/segregation_of_duties_across_five_actor_identity_rules
    """
    _policy, patient = _duty_patient(api)
    scope = SETUP.register_scope(api, serial=C.scope_serial(12), model="ENT-Flex 9")

    # One diagnostic endoscopy leaves the scope soiled.
    soiled = SETUP.soil_scope(
        api,
        scope["id"],
        patient["id"],
        start_at="2026-08-01T09:00:00Z",
        end_at="2026-08-01T10:00:00Z",
        physician_headers=USERS.ENT_1,
        physician_user_id=C.USER_ENT_1,
    )
    check.assert_endoscope(soiled, status=C.SCOPE_SOILED, cycle_count=0)

    # The first technician opens the run and owns it.
    opened = SETUP.start_reprocessing(api, scope["id"], headers=USERS.TECH_1)
    check.assert_endoscope(
        opened,
        status=C.SCOPE_REPROCESSING,
        cycle_count=0,
        reprocessing_started_by_user_id=C.USER_TECH_1,
    )

    # A colleague of the same role cannot sign off someone else's cycle.
    validate_error(
        api.complete_reprocessing(
            scope["id"], F.reprocessing_completion_payload(True), USERS.TECH_2
        ),
        ApiErrorId.REPROCESSING_TECH_MISMATCH.value,
    )
    check.assert_endoscope(
        SETUP.read_scope(api, scope["id"]),
        status=C.SCOPE_REPROCESSING,
        cycle_count=0,
        reprocessing_started_by_user_id=C.USER_TECH_1,
    )

    # The technician who opened it closes it, and the shelf life opens.
    completed = check.validate_unpaginated(
        api.complete_reprocessing(
            scope["id"], F.reprocessing_completion_payload(True), USERS.TECH_1
        )
    )
    check.assert_endoscope(
        completed,
        status=C.SCOPE_READY,
        cycle_count=1,
        consecutive_mec_failures=0,
        reprocessing_started_by_user_id=None,
    )
    check.assert_instant_equals(completed["last_reprocessed_at"], "2026-08-01T00:00:00Z")
    check.assert_instant_equals(completed["hld_expires_at"], "2026-08-08T00:00:00Z")
    check.assert_hld_window(completed)
