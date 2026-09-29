"""The core of the rejection catalogue: entity 404s, natural-key uniqueness, the
supervision identifiers, the vial-volume floor, the void window, the adjustment
ceiling and the appliance-coverage gate."""

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


def test_unknown_payer_policy_and_patient_paths_report_their_own_identifiers(api):
    """PRD 2.8: "Every identifier in the path resolves to a stored row, resolved
    left to right."

    Design: Corner/errors/entity_not_found_returns_404_for_every_path_parameter
    """
    # The registry is empty, so a well-formed identifier resolves to nothing.
    validate_error(
        api.get_payer_policy(NON_EXISTENT_UUID, USERS.ADMIN_1),
        ApiErrorId.PAYER_POLICY_NOT_FOUND.value,
    )

    # The patient collection answers with its own identifier, not the plan's.
    validate_error(
        api.get_patient(NON_EXISTENT_UUID, USERS.ADMIN_1),
        ApiErrorId.PATIENT_NOT_FOUND.value,
    )


def test_unknown_allergy_order_reaction_vial_and_dose_paths_report_their_own_identifiers(api):
    """PRD 2.4: "In this service almost every path carries a single identifier —
    `policyId`, `patientId`, `orderId`, `eventId`, `vialId`, `doseId`, `caseId`,
    `studyId`, `dispenseId`, `scopeId`, `lotId`, `blockId` or `bookingId` — and
    each resolves against its own collection, producing the entity-specific 404
    named in §5."

    Design: Corner/errors/entity_not_found_returns_404_for_every_path_parameter
    """
    # The four allergy-clinic collections each own a distinct identifier.
    validate_error(
        api.get_allergy_test_order(NON_EXISTENT_UUID, USERS.NURSE_1),
        ApiErrorId.ALLERGY_TEST_ORDER_NOT_FOUND.value,
    )
    validate_error(
        api.get_reaction_event(NON_EXISTENT_UUID, USERS.NURSE_1),
        ApiErrorId.REACTION_EVENT_NOT_FOUND.value,
    )
    validate_error(
        api.get_immunotherapy_vial(NON_EXISTENT_UUID, USERS.NURSE_1),
        ApiErrorId.IMMUNOTHERAPY_VIAL_NOT_FOUND.value,
    )
    validate_error(
        api.get_immunotherapy_dose(NON_EXISTENT_UUID, USERS.NURSE_1),
        ApiErrorId.IMMUNOTHERAPY_DOSE_NOT_FOUND.value,
    )


def test_unknown_case_study_and_dispense_paths_report_their_own_identifiers(api):
    """PRD 2.4: "In this service almost every path carries a single identifier —
    `policyId`, `patientId`, `orderId`, `eventId`, `vialId`, `doseId`, `caseId`,
    `studyId`, `dispenseId`, `scopeId`, `lotId`, `blockId` or `bookingId` — and
    each resolves against its own collection, producing the entity-specific 404
    named in §5."

    Design: Corner/errors/entity_not_found_returns_404_for_every_path_parameter
    """
    # The sinuplasty, audiology and device collections answer separately.
    validate_error(
        api.get_sinuplasty_case(NON_EXISTENT_UUID, USERS.ENT_1),
        ApiErrorId.SINUPLASTY_CASE_NOT_FOUND.value,
    )
    validate_error(
        api.get_diagnostic_study(NON_EXISTENT_UUID, USERS.AUD_1),
        ApiErrorId.DIAGNOSTIC_STUDY_NOT_FOUND.value,
    )
    validate_error(
        api.get_device_dispense(NON_EXISTENT_UUID, USERS.AUD_1),
        ApiErrorId.DEVICE_DISPENSE_NOT_FOUND.value,
    )


def test_unknown_scope_lot_block_and_booking_paths_report_their_own_identifiers(api):
    """PRD 2.8: "Every identifier in the path resolves to a stored row, resolved
    left to right."

    Design: Corner/errors/entity_not_found_returns_404_for_every_path_parameter
    """
    # The asset, inventory and schedule collections close the catalogue.
    validate_error(
        api.get_endoscope(NON_EXISTENT_UUID, USERS.TECH_1),
        ApiErrorId.ENDOSCOPE_ASSET_NOT_FOUND.value,
    )
    validate_error(
        api.get_supply_lot(NON_EXISTENT_UUID, USERS.ADMIN_1),
        ApiErrorId.SUPPLY_LOT_NOT_FOUND.value,
    )
    validate_error(
        api.get_surgery_center_block(NON_EXISTENT_UUID, USERS.ADMIN_1),
        ApiErrorId.SURGERY_CENTER_BLOCK_NOT_FOUND.value,
    )
    validate_error(
        api.get_procedure_booking(NON_EXISTENT_UUID, USERS.ADMIN_1),
        ApiErrorId.PROCEDURE_BOOKING_NOT_FOUND.value,
    )


def test_unknown_plan_named_in_a_patient_body_reports_the_plan_identifier(api):
    """PRD 2.8: "The error is drawn from the same 404 catalogue as rung 4,
    selected by whichever referenced entity failed to resolve."

    Design: Corner/errors/entity_not_found_returns_404_for_every_path_parameter
    """
    # A registration names a governing plan that was never registered.
    payload = F.patient_payload(
        NON_EXISTENT_UUID,
        mrn=C.mrn(10234),
        full_name="Marisol Quintero-Fane",
        date_of_birth="1970-01-01",
    )
    validate_error(
        api.create_patient(payload, USERS.ADMIN_1),
        ApiErrorId.PAYER_POLICY_NOT_FOUND.value,
    )

    # The chart was never opened, so the registry is still empty.
    rows, meta = validate_paginated(api.list_patients(USERS.ADMIN_1))
    assert rows == []
    assert meta["total_count"] == 0


def test_second_plan_reusing_a_registered_plan_code_is_refused(api):
    """PRD 3.1: "A `plan_code` that already exists on another plan is refused with
    `ERR_DUPLICATE_PLAN_CODE`."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_across_five_entities
    """
    # One plan owns the code.
    incumbent = SETUP.create_policy(
        api, plan_code="ERRA-2999", payer_name="Northshore Health Plan"
    )
    assert incumbent["version"] == 1

    # A different payer claims the very same code.
    payload = F.payer_policy_payload(plan_code="ERRA-2999", payer_name="Lakeside Mutual")
    validate_error(
        api.create_payer_policy(payload, USERS.ADMIN_1),
        ApiErrorId.DUPLICATE_PLAN_CODE.value,
    )

    # The incumbent plan is untouched by the refused registration.
    stored = SETUP.read_policy(api, incumbent["id"])
    assert stored["payer_name"] == "Northshore Health Plan"
    assert stored["version"] == 1


def test_second_patient_reusing_a_registered_mrn_is_refused(api):
    """PRD 3.1: "A duplicate `mrn` is refused with `ERR_DUPLICATE_MRN`."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_across_five_entities
    """
    # One chart holds the record number.
    base = SETUP.policy_with_patient(
        api, plan_code="ERRB-2999", patient_mrn=C.mrn(10235)
    )

    # A second person is registered under the same plan with the same number.
    payload = F.patient_payload(
        base["policy"]["id"],
        mrn=C.mrn(10235),
        full_name="Imogen Thackeray-Voss",
        date_of_birth="1984-11-02",
    )
    validate_error(
        api.create_patient(payload, USERS.ADMIN_1),
        ApiErrorId.DUPLICATE_MRN.value,
    )

    # The plan still governs exactly one chart.
    rows, meta = validate_paginated(
        api.list_patients(
            USERS.ADMIN_1, params={"payer_policy_id": base["policy"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == base["patient"]["id"]


def test_second_endoscope_reusing_a_registered_serial_number_is_refused(api):
    """PRD 3.8: "A `PracticeAdmin` registers a flexible endoscope by supplying its
    `serial_number` — an `SC-` prefix followed by exactly four digits, unique
    across every scope ever registered, duplicates refused with
    `ERR_DUPLICATE_SCOPE_SERIAL` — and its `model`, free text of 1 to 60
    characters."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_across_five_entities
    """
    # One scope owns the serial.
    incumbent = SETUP.register_scope(api, serial=C.scope_serial(8), model="Olympus ENF-VH")

    # A different model is offered the same serial.
    payload = F.endoscope_payload(
        serial_number=C.scope_serial(8), model="Pentax EE-1580K"
    )
    validate_error(
        api.create_endoscope(payload, USERS.ADMIN_1),
        ApiErrorId.DUPLICATE_SCOPE_SERIAL.value,
    )

    # The register still lists the one scope, with its original model.
    rows, meta = validate_paginated(api.list_endoscopes(USERS.TECH_1))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == incumbent["id"]
    assert rows[0]["model"] == "Olympus ENF-VH"


def test_second_lot_reusing_a_registered_lot_number_is_refused(api):
    """PRD 3.8: "A `PracticeAdmin` books in a supply or implant lot by supplying
    its `item_type` — one of `BALLOON_DEVICE`, `TYMPANOSTOMY_TUBE`,
    `ALLERGEN_CONCENTRATE`, `HEARING_AID` or `ORAL_APPLIANCE`, which fixes for
    ever which workflow may draw from it — its `lot_number` as a `LOT-` prefix
    followed by exactly four digits and unique across all lots, duplicates
    refused with `ERR_DUPLICATE_LOT_NUMBER`, its `quantity_received` between 1
    and 1000 inclusive, and its expiry instant `expires_at`."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_across_five_entities
    """
    # A hearing-aid lot books in under the number.
    incumbent = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1020),
        quantity_received=5,
    )

    # A balloon-device delivery reaches for the same number.
    payload = F.supply_lot_payload(
        SETUP.LOT_EXPIRY_DEFAULT,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_number=C.lot_number(1020),
        quantity_received=40,
    )
    validate_error(
        api.create_supply_lot(payload, USERS.ADMIN_1),
        ApiErrorId.DUPLICATE_LOT_NUMBER.value,
    )

    # The incumbent lot keeps its item type and its opening buckets.
    stored = SETUP.read_lot(api, incumbent["id"])
    assert stored["item_type"] == C.ITEM_TYPE_HEARING_AID
    assert stored["quantity_received"] == 5
    assert stored["quantity_on_hand"] == 5
    assert stored["quantity_consumed"] == 0
    check.assert_lot_quantity_ledger(stored)


def test_second_dispense_reusing_the_serial_of_a_returned_unit_is_refused(api):
    """PRD 3.7: "The `device_serial` must be exactly two uppercase letters followed
    by six digits and must not already exist on any other dispense row —
    including on a `RETURNED` one — or the dispense is refused with
    `ERR_DUPLICATE_DEVICE_SERIAL`."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_across_five_entities
    """
    # A hearing aid is fitted and then handed back.
    base = SETUP.fitted_hearing_aid(
        api, plan_code="ERRE-2999", patient_mrn=C.mrn(10238), quantity_received=4
    )
    returned = SETUP.return_dispense(
        api, base["dispense"]["id"], C.RETURN_REASON_POOR_FIT
    )
    assert returned["fit_status"] == C.FIT_RETURNED

    # The returned unit still owns its serial, so the other ear cannot reuse it.
    payload = F.device_dispense_payload(
        base["study"]["id"],
        base["lot"]["id"],
        SETUP.study_version(api, base["study"]["id"]),
        device_serial=C.device_serial("HA", 100001),
        ear=C.EAR_RIGHT,
    )
    validate_error(
        api.create_device_dispense(payload, USERS.AUD_1),
        ApiErrorId.DUPLICATE_DEVICE_SERIAL.value,
    )

    # The study carries exactly the one dispense row.
    rows, meta = validate_paginated(
        api.list_device_dispenses(
            USERS.AUD_1, params={"diagnostic_study_id": base["study"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == base["dispense"]["id"]


def test_supervised_vial_refuses_a_draw_with_no_supervising_identifier(api):
    """PRD 3.5: "If the vial's `requires_supervised_administration` is true,
    `supervising_user_id` must be supplied, or it is refused with
    `ERR_SUPERVISION_REQUIRED`; when that flag is false the field may be omitted
    and defaults to null."

    Design: Corner/errors/dose_and_booking_start_require_the_supervision_identifiers
    """
    # A patient carrying three prior systemic reactions starts immunotherapy.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="ERRC-2999",
        patient_mrn=C.mrn(10241),
        patient_overrides={
            "epinephrine_on_file": True,
            "prior_systemic_reaction_count": 3,
        },
    )
    first = SETUP.administer_dose(api, base["vial"]["id"])
    check.assert_volume_ml(first["volume_ml"], 0.05)

    # A grade-3 reaction on that draw puts the vial under supervision.
    SETUP.record_reaction(api, 3, 10, dose_id=first["id"])
    vial = SETUP.read_vial(api, base["vial"]["id"])
    assert vial["status"] == C.VIAL_IN_USE
    assert vial["requires_supervised_administration"] is True

    # The nurse offers the next draw with no supervising otolaryngologist named.
    payload = F.immunotherapy_dose_payload(base["vial"]["id"])
    validate_error(
        api.create_immunotherapy_dose(payload, USERS.NURSE_1),
        ApiErrorId.SUPERVISION_REQUIRED.value,
    )

    # No volume moved and the vial still carries only the first draw.
    after = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_volume_ml(after["volume_ml_remaining"], 4.95)
    check.assert_volume_ml(after["volume_ml_dispensed_total"], 0.05)
    check.assert_vial_volume_ledger(after)
    rows, meta = validate_paginated(
        api.list_immunotherapy_doses(
            USERS.NURSE_1, params={"immunotherapy_vial_id": base["vial"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_supervised_draw_with_a_named_supervisor_takes_the_ninety_minute_window(api):
    """PRD 3.2: "If the patient's `supervision_tier` is `PHYSICIAN_PRESENT`, raise
    the candidate to at least 90 minutes."

    Design: Corner/errors/dose_and_booking_start_require_the_supervision_identifiers
    """
    # The same patient, the same grade-3 reaction, the same supervised vial.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="ERRC-2999",
        patient_mrn=C.mrn(10241),
        patient_overrides={
            "epinephrine_on_file": True,
            "prior_systemic_reaction_count": 3,
        },
    )
    first = SETUP.administer_dose(api, base["vial"]["id"])
    SETUP.record_reaction(api, 3, 10, dose_id=first["id"])
    patient = SETUP.read_patient(api, base["patient"]["id"])
    assert patient["supervision_tier"] == C.SUPERVISION_TIER_PHYSICIAN_PRESENT
    assert patient["immunotherapy_status"] == C.IMMUNO_STATUS_HELD

    # The nurse draws again, this time naming a supervising otolaryngologist.
    payload = F.immunotherapy_dose_payload(
        base["vial"]["id"], supervising_user_id=C.USER_ENT_1
    )
    dose = validate_success(
        api.create_immunotherapy_dose(payload, USERS.NURSE_1), 201
    )
    assert dose["status"] == C.DOSE_ADMINISTERED
    assert dose["supervising_user_id"] == C.USER_ENT_1
    assert dose["administered_by_user_id"] == C.USER_NURSE_1
    assert dose["escalation_step_at_dose"] == 1
    assert dose["gap_days_at_dose"] == 0
    check.assert_volume_ml(dose["volume_ml"], 0.05)
    assert dose["observation_required_minutes"] == 90

    # Two draws have now left the vial.
    after = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_volume_ml(after["volume_ml_remaining"], 4.90)
    check.assert_volume_ml(after["volume_ml_dispensed_total"], 0.10)
    check.assert_vial_volume_ledger(after)


def test_physician_present_booking_start_demands_a_second_physician(api):
    """PRD 3.9: "When `requires_physician_presence` is true,
    `attending_physician_user_id` must be present, or the start is refused with
    `ERR_ATTENDING_PHYSICIAN_REQUIRED`; when it is false the field may be
    supplied and is simply recorded."

    Design: Corner/errors/dose_and_booking_start_require_the_supervision_identifiers
    """
    # A patient with three prior reactions reads a twelve-antigen mould panel.
    base = SETUP.policy_with_patient(
        api,
        plan_code="ERRD-2999",
        patient_mrn=C.mrn(10242),
        patient_overrides={
            "epinephrine_on_file": True,
            "prior_systemic_reaction_count": 3,
        },
    )
    order = SETUP.administered_order(
        api,
        base["patient"]["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
    )
    SETUP.set_clock(api, "2026-08-01T01:00:00Z")
    SETUP.record_reading(api, order["id"], 10)

    # Ten sensitizations carry the chart to the physician-present tier.
    patient = SETUP.read_patient(api, base["patient"]["id"])
    assert patient["sensitized_antigen_count"] == 10
    assert patient["risk_score"] == 60
    assert patient["supervision_tier"] == C.SUPERVISION_TIER_PHYSICIAN_PRESENT

    # A tonsillectomy booked for that patient inherits the presence requirement.
    booking = SETUP.create_booking(
        api,
        base["patient"]["id"],
        "2026-08-04T09:00:00Z",
        "2026-08-04T10:00:00Z",
        physician_user_id=C.USER_ENT_1,
        procedure_type=C.PROCEDURE_TONSILLECTOMY,
        venue=C.VENUE_IN_OFFICE_SUITE,
    )
    assert booking["requires_physician_presence"] is True
    assert booking["attending_physician_user_id"] is None

    # The physician of record tries to start the case alone.
    validate_error(
        api.start_procedure_booking(
            booking["id"], USERS.ENT_1, F.booking_start_payload()
        ),
        ApiErrorId.ATTENDING_PHYSICIAN_REQUIRED.value,
    )
    assert SETUP.read_booking(api, booking["id"])["status"] == C.BOOKING_SCHEDULED

    # Naming a second, distinct otolaryngologist as attending starts the case.
    started = SETUP.start_booking(
        api,
        booking["id"],
        attending_physician_user_id=C.USER_ENT_2,
        headers=USERS.ENT_1,
    )
    assert started["status"] == C.BOOKING_IN_PROGRESS
    assert started["attending_physician_user_id"] == C.USER_ENT_2
    assert started["physician_user_id"] == C.USER_ENT_1


def test_four_cleared_doses_leave_thirty_five_hundredths_in_the_vial(api):
    """PRD 2.10: "After every mutation, `volume_ml_initial` must equal the sum of
    `volume_ml_remaining`, `volume_ml_dispensed_total` and `volume_ml_wasted`."

    Design: Corner/errors/insufficient_vial_volume_at_the_fifth_dose
    """
    # A one-millilitre extract vial is compounded and verified.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="ERRF-2999",
        patient_mrn=C.mrn(10243),
        patient_overrides={"epinephrine_on_file": True},
        volume_ml_initial=1.00,
    )
    check.assert_volume_ml(base["vial"]["volume_ml_initial"], 1.00)
    check.assert_volume_ml(base["vial"]["volume_ml_remaining"], 1.00)

    # Four escalation steps are given and cleared, half an hour apart.
    schedule = [
        (1, 0.05, "2026-08-01T00:30:00Z"),
        (2, 0.10, "2026-08-01T01:00:00Z"),
        (3, 0.20, "2026-08-01T01:30:00Z"),
        (4, 0.30, "2026-08-01T02:00:00Z"),
    ]
    for step, expected_volume, clearance_instant in schedule:
        dose = SETUP.administer_dose(api, base["vial"]["id"])
        assert dose["escalation_step_at_dose"] == step
        assert dose["gap_days_at_dose"] == 0
        assert dose["observation_required_minutes"] == 30
        check.assert_volume_ml(dose["volume_ml"], expected_volume)
        SETUP.set_clock(api, clearance_instant)
        assert SETUP.clear_dose(api, dose["id"])["status"] == C.DOSE_CLEARED

    # The vial has funded 0.65 mL and still holds 0.35 mL.
    vial = SETUP.read_vial(api, base["vial"]["id"])
    assert vial["status"] == C.VIAL_IN_USE
    check.assert_volume_ml(vial["volume_ml_dispensed_total"], 0.65)
    check.assert_volume_ml(vial["volume_ml_remaining"], 0.35)
    check.assert_volume_ml(vial["volume_ml_wasted"], 0.00)
    check.assert_vial_volume_ledger(vial)

    # The chart stands at step 5, still building up.
    patient = SETUP.read_patient(api, base["patient"]["id"])
    assert patient["immunotherapy_escalation_step"] == 5
    assert patient["immunotherapy_status"] == C.IMMUNO_STATUS_BUILD_UP


def test_fifth_step_draw_is_refused_when_the_vial_cannot_fund_it(api):
    """PRD 3.5: "Last of all, the vial's `volume_ml_remaining` must be at least the
    computed `volume_ml`, or the draw is refused with
    `ERR_INSUFFICIENT_VIAL_VOLUME` before any volume moves."

    Design: Corner/errors/insufficient_vial_volume_at_the_fifth_dose
    """
    # The same one-millilitre vial is worked down through four cleared steps.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="ERRF-2999",
        patient_mrn=C.mrn(10243),
        patient_overrides={"epinephrine_on_file": True},
        volume_ml_initial=1.00,
    )
    for clearance_instant in [
        "2026-08-01T00:30:00Z",
        "2026-08-01T01:00:00Z",
        "2026-08-01T01:30:00Z",
        "2026-08-01T02:00:00Z",
    ]:
        dose = SETUP.administer_dose(api, base["vial"]["id"])
        SETUP.set_clock(api, clearance_instant)
        SETUP.clear_dose(api, dose["id"])

    # The fifth step wants 0.40 mL and only 0.35 mL is left.
    payload = F.immunotherapy_dose_payload(base["vial"]["id"])
    validate_error(
        api.create_immunotherapy_dose(payload, USERS.NURSE_1),
        ApiErrorId.INSUFFICIENT_VIAL_VOLUME.value,
    )

    # Nothing moved: the vial keeps its 0.35 mL and the chart its step.
    vial = SETUP.read_vial(api, base["vial"]["id"])
    assert vial["status"] == C.VIAL_IN_USE
    check.assert_volume_ml(vial["volume_ml_remaining"], 0.35)
    check.assert_volume_ml(vial["volume_ml_dispensed_total"], 0.65)
    check.assert_vial_volume_ledger(vial)
    patient = SETUP.read_patient(api, base["patient"]["id"])
    assert patient["immunotherapy_escalation_step"] == 5
    rows, meta = validate_paginated(
        api.list_immunotherapy_doses(
            USERS.NURSE_1, params={"immunotherapy_vial_id": base["vial"]["id"]}
        )
    )
    assert meta["total_count"] == 4
    assert len(rows) == 4


def test_void_at_exactly_fifteen_minutes_restores_the_vial_ledger(api):
    """PRD 3.5: "The void moves the dose `ADMINISTERED → VOIDED`, returns its
    `volume_ml` to the vial's `volume_ml_remaining` and subtracts the same figure
    from the vial's `volume_ml_dispensed_total`, so the ledger closes with no
    residue at all."

    Design: Corner/errors/void_window_closes_after_fifteen_minutes
    """
    # A low-risk adult takes the first 0.05 mL step.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="ERRG-2999",
        patient_mrn=C.mrn(10244),
        patient_overrides={"epinephrine_on_file": True},
    )
    dose = SETUP.administer_dose(api, base["vial"]["id"])
    check.assert_instant_equals(dose["administered_at"], C.CLOCK_DEFAULT)
    check.assert_volume_ml(dose["volume_ml"], 0.05)

    # The clock advances to exactly the fifteenth minute and the draw is voided.
    SETUP.set_clock(api, "2026-08-01T00:15:00Z")
    voided = SETUP.void_dose(api, dose["id"], C.VOID_REASON_WRONG_VIAL)
    assert voided["status"] == C.DOSE_VOIDED

    # The vial is whole again with no residue anywhere in the ledger.
    vial = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_volume_ml(vial["volume_ml_remaining"], 5.00)
    check.assert_volume_ml(vial["volume_ml_dispensed_total"], 0.00)
    check.assert_volume_ml(vial["volume_ml_wasted"], 0.00)
    check.assert_vial_volume_ledger(vial)

    # The chart no longer remembers a dose instant.
    patient = SETUP.read_patient(api, base["patient"]["id"])
    assert patient["last_dose_administered_at"] is None


def test_voided_draw_leaves_the_schedule_and_the_gap_clock_untouched(api):
    """PRD 3.5: "The patient's `immunotherapy_escalation_step` is deliberately
    **left untouched** — a void neither advances the schedule nor rolls it back,
    and because a `VOIDED` dose never contributes to `last_dose_administered_at`,
    it also does not reset the gap clock."

    Design: Corner/errors/void_window_closes_after_fifteen_minutes
    """
    # A first step is drawn and then voided inside the window.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="ERRG-2999",
        patient_mrn=C.mrn(10244),
        patient_overrides={"epinephrine_on_file": True},
    )
    first = SETUP.administer_dose(api, base["vial"]["id"])
    SETUP.set_clock(api, "2026-08-01T00:15:00Z")
    SETUP.void_dose(api, first["id"], C.VOID_REASON_PATIENT_DEFERRED)
    patient = SETUP.read_patient(api, base["patient"]["id"])
    assert patient["immunotherapy_escalation_step"] == 1
    assert patient["immunotherapy_status"] == C.IMMUNO_STATUS_BUILD_UP

    # The replacement draw is another step-one dose with no gap behind it.
    second = SETUP.administer_dose(api, base["vial"]["id"])
    assert second["escalation_step_at_dose"] == 1
    assert second["gap_days_at_dose"] == 0
    check.assert_volume_ml(second["volume_ml"], 0.05)
    assert second["status"] == C.DOSE_ADMINISTERED

    # Only the replacement draw is charged against the vial.
    vial = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_volume_ml(vial["volume_ml_remaining"], 4.95)
    check.assert_volume_ml(vial["volume_ml_dispensed_total"], 0.05)
    check.assert_vial_volume_ledger(vial)


def test_void_one_minute_past_the_window_is_refused(api):
    """PRD 3.5: "The dose must still be `ADMINISTERED` with `observation_cleared_at`
    null, and no more than fifteen minutes may have elapsed since
    `administered_at`, or the void is refused with `ERR_VOID_WINDOW_CLOSED`."

    Design: Corner/errors/void_window_closes_after_fifteen_minutes
    """
    # The same first step is drawn at the top of the hour.
    base = SETUP.immunotherapy_ready_patient(
        api,
        plan_code="ERRG-2999",
        patient_mrn=C.mrn(10244),
        patient_overrides={"epinephrine_on_file": True},
    )
    dose = SETUP.administer_dose(api, base["vial"]["id"])

    # Sixteen whole minutes later the window has closed.
    SETUP.set_clock(api, "2026-08-01T00:16:00Z")
    validate_error(
        api.void_immunotherapy_dose(
            dose["id"],
            F.dose_void_payload(void_reason=C.VOID_REASON_DRAWN_IN_ERROR),
            USERS.NURSE_1,
        ),
        ApiErrorId.VOID_WINDOW_CLOSED.value,
    )

    # The dose stands as administered and the volume stays spent.
    stored = SETUP.read_dose(api, dose["id"])
    assert stored["status"] == C.DOSE_ADMINISTERED
    assert stored["observation_cleared_at"] is None
    vial = SETUP.read_vial(api, base["vial"]["id"])
    check.assert_volume_ml(vial["volume_ml_remaining"], 4.95)
    check.assert_volume_ml(vial["volume_ml_dispensed_total"], 0.05)
    check.assert_vial_volume_ledger(vial)


def test_three_fitting_adjustments_are_accepted_and_leave_the_billing_alone(api):
    """PRD 3.7: "On success the dispense moves to `ADJUSTED` — `FITTED → ADJUSTED`
    on the first adjustment, and `ADJUSTED → ADJUSTED` on the second and third,
    so `ADJUSTED` carries a self-loop — and `adjustment_count` increments by
    one."

    Design: Corner/errors/adjustment_limit_reached_on_the_fourth_adjustment
    """
    # A hearing aid is fitted against an interpreted audiometry.
    base = SETUP.fitted_hearing_aid(
        api,
        plan_code="ERRH-2999",
        patient_mrn=C.mrn(10245),
        price_cents=265000,
        quantity_received=3,
        pta_db_hl=65.0,
    )
    assert base["dispense"]["fit_status"] == C.FIT_FITTED
    assert base["dispense"]["billing_status"] == C.BILLING_INVOICED
    assert base["dispense"]["adjustment_count"] == 0

    # The three permitted adjustments are recorded.
    for expected_count in (1, 2, 3):
        adjusted = SETUP.adjust_dispense(
            api, base["dispense"]["id"], adjustment_note="Vent bore widened"
        )
        assert adjusted["adjustment_count"] == expected_count
        assert adjusted["fit_status"] == C.FIT_ADJUSTED
        assert adjusted["billing_status"] == C.BILLING_INVOICED

    # Fitting work never touches the inventory the unit came out of.
    lot = SETUP.read_lot(api, base["lot"]["id"])
    assert lot["quantity_received"] == 3
    assert lot["quantity_consumed"] == 1
    assert lot["quantity_on_hand"] == 2
    check.assert_lot_quantity_ledger(lot)


def test_fourth_fitting_adjustment_is_refused(api):
    """PRD 3.7: "The `adjustment_count` must be strictly below three, or the
    adjustment is refused with `ERR_ADJUSTMENT_LIMIT_REACHED`."

    Design: Corner/errors/adjustment_limit_reached_on_the_fourth_adjustment
    """
    # The same fitted aid takes its three adjustments.
    base = SETUP.fitted_hearing_aid(
        api,
        plan_code="ERRH-2999",
        patient_mrn=C.mrn(10245),
        price_cents=265000,
        quantity_received=3,
        pta_db_hl=65.0,
    )
    for _ in range(C.MAX_ADJUSTMENTS):
        SETUP.adjust_dispense(api, base["dispense"]["id"])

    # A fourth visit asks for one more.
    validate_error(
        api.adjust_device_dispense(
            base["dispense"]["id"],
            USERS.AUD_1,
            F.adjustment_payload(adjustment_note="Fourth request from the patient"),
        ),
        ApiErrorId.ADJUSTMENT_LIMIT_REACHED.value,
    )

    # The counter stopped at three and both dimensions held still.
    stored = SETUP.read_dispense(api, base["dispense"]["id"])
    assert stored["adjustment_count"] == 3
    assert stored["fit_status"] == C.FIT_ADJUSTED
    assert stored["billing_status"] == C.BILLING_INVOICED
    lot = SETUP.read_lot(api, base["lot"]["id"])
    assert lot["quantity_consumed"] == 1
    check.assert_lot_quantity_ledger(lot)


def test_oral_appliance_dispense_is_refused_when_the_plan_excludes_appliances(api):
    """PRD 3.7: "An `ORAL_APPLIANCE` dispense additionally requires the patient's
    plan to have `appliance_covered` true, or it is refused with
    `ERR_APPLIANCE_NOT_COVERED`."

    Design: Corner/errors/appliance_not_covered_when_the_plan_excludes_it
    """
    # The governing plan excludes oral appliances outright.
    base = SETUP.policy_with_patient(
        api,
        plan_code="ERRI-2999",
        patient_mrn=C.mrn(10246),
        policy_overrides={"appliance_covered": False},
    )
    assert base["policy"]["appliance_covered"] is False
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_ORAL_APPLIANCE,
        lot_no=C.lot_number(1030),
        quantity_received=3,
    )

    # A home sleep test recommends exactly the device the plan will not fund.
    study = SETUP.interpreted_sleep_study(api, base["patient"]["id"], 20.0)
    assert study["recommendation"] == C.RECOMMENDATION_ORAL_APPLIANCE

    # The audiologist tries to dispense the appliance anyway.
    payload = F.device_dispense_payload(
        study["id"],
        lot["id"],
        SETUP.study_version(api, study["id"]),
        device_type=C.DEVICE_TYPE_ORAL_APPLIANCE,
        device_serial=C.device_serial("OA", 400001),
        ear=C.EAR_NA,
        price_cents=145000,
    )
    validate_error(
        api.create_device_dispense(payload, USERS.AUD_1),
        ApiErrorId.APPLIANCE_NOT_COVERED.value,
    )

    # No unit left the lot.
    stored_lot = SETUP.read_lot(api, lot["id"])
    assert stored_lot["quantity_consumed"] == 0
    assert stored_lot["quantity_on_hand"] == 3
    check.assert_lot_quantity_ledger(stored_lot)


def test_amending_the_plan_lets_the_same_appliance_dispense_through(api):
    """PRD 3.1: "A `PracticeAdmin` may amend any of the thirteen optional terms —
    `plan_code` and `payer_name` are not amendable and are not accepted on an
    amendment — and every amendment increments the plan's `version` by one."

    Design: Corner/errors/appliance_not_covered_when_the_plan_excludes_it
    """
    # The same excluding plan, the same recommended appliance.
    base = SETUP.policy_with_patient(
        api,
        plan_code="ERRI-2999",
        patient_mrn=C.mrn(10246),
        policy_overrides={"appliance_covered": False},
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_ORAL_APPLIANCE,
        lot_no=C.lot_number(1030),
        quantity_received=3,
    )
    study = SETUP.interpreted_sleep_study(api, base["patient"]["id"], 20.0)
    pinned_version = SETUP.study_version(api, study["id"])

    # The plan is amended to cover appliances, which moves only the plan.
    amended = SETUP.patch_policy(api, base["policy"]["id"], appliance_covered=True)
    assert amended["appliance_covered"] is True
    assert amended["version"] == 2

    # The identical dispense, pinned to the same study version, now lands.
    payload = F.device_dispense_payload(
        study["id"],
        lot["id"],
        pinned_version,
        device_type=C.DEVICE_TYPE_ORAL_APPLIANCE,
        device_serial=C.device_serial("OA", 400001),
        ear=C.EAR_NA,
        price_cents=145000,
    )
    dispense = validate_success(api.create_device_dispense(payload, USERS.AUD_1), 201)
    assert dispense["device_type"] == C.DEVICE_TYPE_ORAL_APPLIANCE
    assert dispense["ear"] == C.EAR_NA
    assert dispense["fit_status"] == C.FIT_FITTED
    assert dispense["billing_status"] == C.BILLING_INVOICED
    assert dispense["price_cents"] == 145000
    assert dispense["refund_cents"] == 0
    assert dispense["adjustment_count"] == 0
    assert dispense["dispensed_by_user_id"] == C.USER_AUD_1

    # The appliance left the lot.
    stored_lot = SETUP.read_lot(api, lot["id"])
    assert stored_lot["quantity_consumed"] == 1
    assert stored_lot["quantity_on_hand"] == 2
    check.assert_lot_quantity_ledger(stored_lot)
