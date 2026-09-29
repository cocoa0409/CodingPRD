"""Four requests that each break two rules at once, checked against the fixed
band order of the rejection ladder: state over accreditation, authorization over
existence, clinical safety over slot capacity, and state over the
superseded-notice constraint.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ApiErrors,
    UNKNOWN_UUID_ALT,
    add_patient,
    assert_error,
    build_practice,
    error_id_of,
    encounter_version,
    insurance_coordinator_headers,
    read_encounter,
    read_fitter,
    read_shelf,
    set_clock,
    shelf_version,
)
from test_helpers import factories as f


def _lapsing_clinic_documented_encounter(api):
    """A documented encounter at a clinic whose accreditation lapses on the fifth
    of the month, with the clock then standing past that date."""
    practice = build_practice(
        api, clinic={"accreditation_expires_on": "2026-08-05"}, with_shelf=False
    )
    encounter_id = practice.documented_encounter()
    first = read_encounter(api, encounter_id)
    assert first["clinical_status"] == "DOCUMENTED"
    set_clock(api, "2026-08-10T00:00:00Z")
    return practice, encounter_id, first


def test_wrong_clinical_state_outranks_the_lapsed_accreditation(api):
    """A second medical-necessity note on an already documented encounter at a
    clinic whose accreditation has lapsed is answered from the state band, not
    from the later safety band.

    PRD: "When a request violates more than one rule, exactly one error is
    returned, and which one is fully determined: the rules are evaluated in a fixed
    ascending priority order and the **first** violated rule produces the response."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_accreditation_on_second_medical_necessity_note_rejected
    """
    practice, encounter_id, _first = _lapsing_clinic_documented_encounter(api)

    response = api.sign_medical_necessity_note(
        encounter_id,
        f.medical_necessity_note_payload(
            mn_diagnosis_code="M54.51",
            mn_functional_deficit="revised deficit narrative",
            mn_expected_duration_months=9,
        ),
        practice.ordering_physician_headers,
    )

    assert_error(response, ApiErrors.INVALID_CLINICAL_STATE, 409)
    assert error_id_of(response) != ApiErrors.CLINIC_ACCREDITATION_EXPIRED


def test_the_rejected_second_note_leaves_the_first_narrative_in_place(api):
    """The refused request is a no-op: the diagnosis, the expected duration and the
    signing stamp are all still the ones the first note wrote.

    PRD: "Signing stores those three values on the encounter, stamps
    `mn_physician_id` with the acting physician's identity and `mn_signed_at` with
    the logical clock instant, and advances the clinical dimension
    `DRAFT → DOCUMENTED` while leaving `financial_status` exactly where it was."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_accreditation_on_second_medical_necessity_note_rejected
    """
    practice, encounter_id, first = _lapsing_clinic_documented_encounter(api)

    api.sign_medical_necessity_note(
        encounter_id,
        f.medical_necessity_note_payload(
            mn_diagnosis_code="M54.51",
            mn_functional_deficit="revised deficit narrative",
            mn_expected_duration_months=9,
        ),
        practice.ordering_physician_headers,
    )

    after = read_encounter(api, encounter_id)
    assert after["mn_diagnosis_code"] == "M54.50"
    assert after["mn_expected_duration_months"] == 6
    assert after["mn_signed_at"] == first["mn_signed_at"]
    assert after["version"] == first["version"]


def test_authorization_is_decided_before_the_encounter_is_looked_up(api):
    """A role that holds no reservation privilege is turned away with the
    authorization error even though the encounter id in the path names nothing,
    so the caller learns nothing about which ids exist.

    PRD: "The first band is authentication and authorization:
    `ERR_MISSING_AUTH_HEADERS`, then `ERR_UNKNOWN_ROLE`, then `ERR_UNAUTHORIZED`,
    then `ERR_ACTOR_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_beats_encounter_not_found_on_reservation_rejected
    """
    practice = build_practice(api)
    version = shelf_version(api, practice.par_level_id)

    response = api.create_reservation(
        UNKNOWN_UUID_ALT, f.reservation_payload(version), insurance_coordinator_headers()
    )

    assert_error(response, ApiErrors.UNAUTHORIZED, 403)
    assert error_id_of(response) != ApiErrors.ENCOUNTER_NOT_FOUND
    shelf = read_shelf(api, practice.par_level_id)
    assert shelf["reserved_qty"] == 0
    assert shelf["version"] == version


def test_the_same_unknown_encounter_is_reported_missing_to_a_permitted_role(api):
    """The id really does resolve to nothing: a fitter, who does hold the
    privilege, gets the existence error from the third band for the very same
    request that the unprivileged role never reached.

    PRD: "The third band is existence, and within it the order is
    `ERR_CLINIC_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_FITTER_NOT_FOUND`,
    `ERR_PAR_LEVEL_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`,
    `ERR_PRIOR_AUTH_NOT_FOUND`, `ERR_ABN_NOTICE_NOT_FOUND`,
    `ERR_FAB_ORDER_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`,
    `ERR_FITTING_RECORD_NOT_FOUND`, and then the cross-entity scoping check
    `ERR_CLINIC_SCOPE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_beats_encounter_not_found_on_reservation_rejected
    """
    practice = build_practice(api)
    version = shelf_version(api, practice.par_level_id)

    response = api.create_reservation(
        UNKNOWN_UUID_ALT, f.reservation_payload(version), practice.fitter_headers
    )

    assert_error(response, ApiErrors.ENCOUNTER_NOT_FOUND, 404)
    assert read_shelf(api, practice.par_level_id)["reserved_qty"] == 0


def _lapsed_fitter_with_a_booked_chair(api):
    """A fitter whose credential lapsed on the fifth, already holding one
    half-hour session, with a second reserved encounter waiting and the clock
    standing past the credential date."""
    practice = build_practice(api, fitter={"credential_expires_on": "2026-08-05"})
    first_encounter = practice.fitted_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )
    records = validate_success(
        api.list_fitting_records(practice.fitter_headers, {"encounter_id": first_encounter}), 200
    )
    assert len(records) == 1
    assert records[0]["fitting_minutes"] == 30

    patient_two = add_patient(practice, full_name="Joel Pike")
    second_encounter = practice.reserved_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5},
        patient_id=patient_two["id"],
    )
    set_clock(api, "2026-08-10T00:00:00Z")
    return practice, second_encounter, records[0]["id"]


def test_lapsed_fitter_credential_outranks_the_overlapping_chair(api):
    """A session that both overlaps the fitter's existing booking and is attempted
    on a lapsed credential is answered from the clinical-safety band, not from the
    capacity band far below it.

    PRD: "The fifth band is regulatory and clinical safety, in this order:
    `ERR_CLINIC_ACCREDITATION_EXPIRED`, `ERR_SUPPLIER_STANDARDS_NOT_ATTESTED`,
    `ERR_SUPPLIER_QUALITY_HOLD`, `ERR_COMPLIANCE_HOLD_ACTIVE`,
    `ERR_IOAS_SUPERVISION_MISSING`, `ERR_SEGREGATION_OF_DUTIES`,
    `ERR_STARK_DISCLOSURE_MISSING`, `ERR_MEDICAL_NECESSITY_MISSING`,
    `ERR_FITTER_CREDENTIAL_EXPIRED`, `ERR_FITTER_PRIVILEGE_SCOPE`,
    `ERR_REFIT_SAME_FITTER`, `ERR_DELIVERY_SIGNATURE_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/fitter_credential_beats_slot_conflict_on_fitting_record_rejected
    """
    practice, second_encounter, _first_record_id = _lapsed_fitter_with_a_booked_chair(api)

    response = api.create_fitting_record(
        second_encounter,
        f.fitting_record_payload(
            "2026-08-01T09:15:00Z",
            "2026-08-01T09:45:00Z",
            measurement_set={"waist_cm": 102, "height_cm": 180},
        ),
        practice.fitter_headers,
    )

    assert_error(response, ApiErrors.FITTER_CREDENTIAL_EXPIRED, 422)
    assert error_id_of(response) != ApiErrors.FITTING_SLOT_CONFLICT


def test_the_refused_session_books_no_minutes_and_writes_no_record(api):
    """Nothing survives the refusal: the waiting encounter is still reserved with
    no fitter stamped on it, the chair still shows only the first half hour, and no
    second record was created.

    PRD: "In all three branches the record is created, the acting fitter's
    `fitting_minutes_booked` increases by this record's `fitting_minutes` and the
    fitter's `version` advances by 1, and the encounter's `version` advances by 1."

    Design: Difficulty/priority_pair_validation_conflict/fitter_credential_beats_slot_conflict_on_fitting_record_rejected
    """
    practice, second_encounter, first_record_id = _lapsed_fitter_with_a_booked_chair(api)

    api.create_fitting_record(
        second_encounter,
        f.fitting_record_payload(
            "2026-08-01T09:15:00Z",
            "2026-08-01T09:45:00Z",
            measurement_set={"waist_cm": 102, "height_cm": 180},
        ),
        practice.fitter_headers,
    )

    encounter = read_encounter(api, second_encounter)
    assert encounter["clinical_status"] == "RESERVED"
    assert encounter["fitter_id"] is None
    assert read_fitter(api, practice.fitter_id)["fitting_minutes_booked"] == 30
    records = validate_success(
        api.list_fitting_records(practice.fitter_headers, {"encounter_id": second_encounter}), 200
    )
    assert records == []
    assert first_record_id is not None


def _superseded_notice(api):
    """A non-covered encounter whose first beneficiary notice was voided by a
    corrected re-issue."""
    practice = build_practice(api, with_shelf=False)
    encounter_id = practice.verified_encounter(coverage={"covered": False})
    first = practice.issue_abn(encounter_id, reason_non_covered="NOT_MEDICALLY_NECESSARY")
    assert first["notice_seq"] == 1
    assert first["status"] == "ISSUED"
    second = practice.issue_abn(encounter_id, reason_non_covered="NON_COVERED_ITEM")
    assert second["notice_seq"] == 2
    return practice, encounter_id, first, second


def test_the_voided_notices_own_state_outranks_the_superseded_constraint(api):
    """Signing the notice that a later issuance voided breaks both the notice's
    state rule and the greatest-sequence constraint, and the state band answers.

    PRD: "The fourth band is state, in the order `ERR_INVALID_CLINICAL_STATE`,
    `ERR_INVALID_FINANCIAL_STATE`, `ERR_INVALID_PRIOR_AUTH_STATE`,
    `ERR_INVALID_ABN_STATE`, `ERR_INVALID_FAB_ORDER_STATE`,
    `ERR_INVALID_RETURN_STATE` — so an encounter in the wrong clinical state is
    always diagnosed as such even when its financial state is also wrong."

    Design: Difficulty/priority_pair_validation_conflict/abn_state_beats_superseded_on_signing_voided_notice_rejected
    """
    _practice, _encounter_id, first, _second = _superseded_notice(api)

    response = api.sign_abn_notice(
        first["id"], f.abn_signature_payload(), insurance_coordinator_headers()
    )

    assert_error(response, ApiErrors.INVALID_ABN_STATE, 409)
    assert error_id_of(response) != ApiErrors.ABN_SUPERSEDED


def test_the_refused_signature_leaves_both_notices_and_the_encounter_as_they_were(api):
    """After the refusal the first notice is still void with no option recorded,
    the corrected notice still holds its quote, and the encounter's financial
    dimension has not advanced to self-pay.

    PRD: "A signature is only accepted while the notice's `status` is `ISSUED`;
    against a notice already `SIGNED`, `DECLINED` or `VOIDED` it is refused with
    `ERR_INVALID_ABN_STATE` and HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/abn_state_beats_superseded_on_signing_voided_notice_rejected
    """
    _practice, encounter_id, first, second = _superseded_notice(api)

    api.sign_abn_notice(first["id"], f.abn_signature_payload(), insurance_coordinator_headers())

    notices = validate_success(
        api.list_abn_notices(encounter_id, insurance_coordinator_headers()), 200
    )
    by_id = {notice["id"]: notice for notice in notices}
    assert by_id[first["id"]]["status"] == "VOIDED"
    assert by_id[first["id"]]["option_selected"] is None
    assert by_id[second["id"]]["status"] == "ISSUED"
    assert by_id[second["id"]]["estimated_cost_cents"] == 14265
    assert read_encounter(api, encounter_id)["financial_status"] == "ABN_ISSUED"
    assert encounter_version(api, encounter_id) >= 1
