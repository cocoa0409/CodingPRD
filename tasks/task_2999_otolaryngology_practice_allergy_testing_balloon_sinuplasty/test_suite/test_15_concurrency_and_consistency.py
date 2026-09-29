"""Optimistic concurrency on compounding and dispensing, and eager consistency."""

from prd_bench_local_runner.testing import (
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


def _compounding_chart(api):
    """A chart at version 1 and a concentrate lot, for the vial version gate."""
    policy = SETUP.create_policy(api, plan_code="XCUA-2999", payer_name="OCC Health")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10251),
        full_name="Emil Draganov",
        date_of_birth="1971-06-06",
        epinephrine_on_file=True,
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_ALLERGEN_CONCENTRATE,
        lot_no=C.lot_number(1033),
        quantity_received=6,
    )
    return patient, lot


def test_a_vial_pinned_to_a_superseded_patient_version_is_refused(api):
    """PRD 2.7: "If `expected_patient_version` does not equal that patient's
    current `version`, the request is rejected with `ERR_STALE_PATIENT_VERSION`
    (HTTP 412) and no vial is created."

    Design: Corner/cross_cutting_complexity_layers/vial_create_rejects_stale_patient_version
    """
    patient, lot = _compounding_chart(api)
    stale_read = patient["version"]
    assert stale_read == 1, "a freshly created chart opens at version 1"

    # An intake revision moves the chart, ageing the version the nurse holds.
    amended = SETUP.patch_patient(api, patient["id"], prior_systemic_reaction_count=1)
    check.assert_patient(amended, version=2, prior_systemic_reaction_count=1)

    # Compounding against the version read before the revision is refused.
    validate_error(
        api.create_immunotherapy_vial(
            F.immunotherapy_vial_payload(
                patient["id"],
                lot["id"],
                C.mrn(10251),
                stale_read,
                "2026-12-01T00:00:00Z",
                dilution_code=C.DILUTION_BLUE,
            ),
            USERS.NURSE_1,
        ),
        ApiErrorId.STALE_PATIENT_VERSION.value,
    )

    # No vial exists for that patient, and the concentrate lot is untouched.
    rows, meta = validate_paginated(
        api.list_immunotherapy_vials(USERS.NURSE_1, params={"patient_id": patient["id"]})
    )
    assert rows == [], "a refused compounding must leave no vial behind"
    assert meta["total_count"] == 0
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]),
        quantity_received=6,
        quantity_on_hand=6,
        quantity_reserved=0,
        quantity_consumed=0,
        quantity_wasted=0,
        available_quantity=6,
        status=C.LOT_ACTIVE,
    )


def test_a_vial_pinned_to_the_current_patient_version_is_compounded_and_verified(api):
    """PRD 3.5: "On success the vial moves `MIXED → LABEL_VERIFIED`,
    `verified_by_user_id` is stamped, and the patient's `immunotherapy_status`
    leaves `NONE` for the first time: it becomes `BUILD_UP` when the patient's
    `immunotherapy_escalation_step` is 6 or lower, and `MAINTENANCE` when that
    step is 7 or higher."

    Design: Corner/cross_cutting_complexity_layers/vial_create_rejects_stale_patient_version
    """
    patient, lot = _compounding_chart(api)
    SETUP.patch_patient(api, patient["id"], prior_systemic_reaction_count=1)

    # The nurse re-reads the chart and pins what she just saw.
    current = SETUP.patient_version(api, patient["id"])
    assert current == 2, "one intake revision moves the chart from 1 to 2"
    label = C.make_label_text(C.mrn(10251), C.DILUTION_BLUE, "2026-12-01T00:00:00Z")
    vial = validate_success(
        api.create_immunotherapy_vial(
            F.immunotherapy_vial_payload(
                patient["id"],
                lot["id"],
                C.mrn(10251),
                current,
                "2026-12-01T00:00:00Z",
                dilution_code=C.DILUTION_BLUE,
            ),
            USERS.NURSE_1,
        ),
        201,
    )
    check.assert_immunotherapy_vial(
        vial,
        patient_id=patient["id"],
        supply_lot_id=lot["id"],
        dilution_code=C.DILUTION_BLUE,
        label_text=label,
        status=C.VIAL_MIXED,
        mixed_by_user_id=C.USER_NURSE_1,
        verified_by_user_id=None,
    )
    check.assert_volume_ml(vial["volume_ml_initial"], 5.00)
    check.assert_volume_ml(vial["volume_ml_remaining"], 5.00)
    check.assert_vial_volume_ledger(vial)

    # A second nurse verifies the label and the schedule opens.
    verified = check.validate_unpaginated(
        api.verify_immunotherapy_vial_label(
            vial["id"], F.label_verification_payload(label), USERS.NURSE_2
        )
    )
    check.assert_immunotherapy_vial(
        verified,
        status=C.VIAL_LABEL_VERIFIED,
        mixed_by_user_id=C.USER_NURSE_1,
        verified_by_user_id=C.USER_NURSE_2,
    )
    check.assert_patient(
        SETUP.read_patient(api, patient["id"]),
        immunotherapy_status=C.IMMUNO_STATUS_BUILD_UP,
    )


def test_compounding_again_supersedes_the_first_vial_and_moves_the_observation_point(api):
    """PRD 3.5: "Finally the patient's own `version` increments by one, which is
    the observation point the next compounder's `expected_patient_version` will
    be measured against."

    Design: Corner/cross_cutting_complexity_layers/vial_create_rejects_stale_patient_version
    """
    patient, lot = _compounding_chart(api)

    # One verified vial is already in the patient's hands.
    first = SETUP.mix_vial(
        api,
        patient,
        lot["id"],
        dilution_code=C.DILUTION_BLUE,
        expires_at="2026-12-01T00:00:00Z",
        headers=USERS.NURSE_1,
    )
    SETUP.verify_vial(api, first, headers=USERS.NURSE_2)

    # The next compounder re-reads the chart, so her pin is the current one.
    before = SETUP.patient_version(api, patient["id"])
    second = validate_success(
        api.create_immunotherapy_vial(
            F.immunotherapy_vial_payload(
                patient["id"],
                lot["id"],
                C.mrn(10251),
                before,
                "2026-12-15T00:00:00Z",
                dilution_code=C.DILUTION_BLUE,
            ),
            USERS.NURSE_1,
        ),
        201,
    )
    check.assert_immunotherapy_vial(
        second,
        status=C.VIAL_MIXED,
        label_text=C.make_label_text(C.mrn(10251), C.DILUTION_BLUE, "2026-12-15T00:00:00Z"),
        mixed_by_user_id=C.USER_NURSE_1,
    )

    # The older vial is discarded as superseded and its volume is wasted.
    superseded = SETUP.read_vial(api, first["id"])
    check.assert_immunotherapy_vial(
        superseded,
        status=C.VIAL_DISCARDED,
        discard_reason=C.DISCARD_REASON_SUPERSEDED,
    )
    check.assert_volume_ml(superseded["volume_ml_wasted"], 5.00)
    check.assert_volume_ml(superseded["volume_ml_remaining"], 0.00)
    check.assert_vial_volume_ledger(superseded)

    # Both vials remain on the chart, and the observation point has moved again.
    rows, meta = validate_paginated(
        api.list_immunotherapy_vials(USERS.NURSE_1, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 2
    assert set(row["id"] for row in rows) == {first["id"], second["id"]}
    assert SETUP.patient_version(api, patient["id"]) > before


def _dispensing_study(api):
    """A performed audiometry at version 2 and a hearing-aid lot of three."""
    policy = SETUP.create_policy(api, plan_code="XCUB-2999", payer_name="Study OCC Health")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10252),
        full_name="Petra Ivanauskas",
        date_of_birth="1954-07-07",
        epinephrine_on_file=True,
    )
    study = SETUP.create_study(api, patient["id"], headers=USERS.ENT_1)
    SETUP.record_audiometry_results(api, study["id"], 61.0, 54.0, headers=USERS.AUD_1)
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1034),
        quantity_received=3,
        expires_at="2028-01-01T00:00:00Z",
    )
    return study, lot


def test_a_dispense_pinned_to_the_pre_interpretation_study_version_is_refused(api):
    """PRD 2.7: "If `expected_study_version` does not equal that study's current
    `version`, the request is rejected with `ERR_STALE_STUDY_VERSION` (HTTP 412)
    and no dispense is created."

    Design: Corner/cross_cutting_complexity_layers/dispense_create_rejects_stale_study_version
    """
    study, lot = _dispensing_study(api)
    performed_read = SETUP.study_version(api, study["id"])
    assert performed_read == 2, "creation then results carry the study to version 2"

    # Interpretation moves the study, ageing the version the audiologist holds.
    interpreted = SETUP.interpret_study(api, study["id"], headers=USERS.AUD_2)
    check.assert_diagnostic_study(
        interpreted,
        status=C.STUDY_INTERPRETED,
        recommendation=C.RECOMMENDATION_HEARING_AID,
        version=3,
        superseded_dispense_count=0,
    )

    # Dispensing against the pre-interpretation read is refused.
    validate_error(
        api.create_device_dispense(
            F.device_dispense_payload(
                study["id"],
                lot["id"],
                performed_read,
                device_serial=C.device_serial("HA", 400008),
                ear=C.EAR_LEFT,
                price_cents=195000,
            ),
            USERS.AUD_1,
        ),
        ApiErrorId.STALE_STUDY_VERSION.value,
    )

    # Nothing was dispensed and no unit left the lot.
    rows, meta = validate_paginated(
        api.list_device_dispenses(
            USERS.AUD_1, params={"diagnostic_study_id": study["id"]}
        )
    )
    assert rows == [], "a refused dispense must leave no row behind"
    assert meta["total_count"] == 0
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]),
        quantity_received=3,
        quantity_on_hand=3,
        quantity_reserved=0,
        quantity_consumed=0,
        quantity_wasted=0,
        available_quantity=3,
        status=C.LOT_ACTIVE,
    )


def test_a_dispense_pinned_to_the_interpreted_study_version_is_fitted(api):
    """PRD 3.7: "Either way the study's `version` increments by one, which is what
    makes a second concurrent dispense holding the older version fail the
    stale-version check."

    Design: Corner/cross_cutting_complexity_layers/dispense_create_rejects_stale_study_version
    """
    study, lot = _dispensing_study(api)
    SETUP.interpret_study(api, study["id"], headers=USERS.AUD_2)

    # The audiologist re-reads the interpreted study and pins that version.
    interpreted_read = SETUP.study_version(api, study["id"])
    assert interpreted_read == 3
    dispense = validate_success(
        api.create_device_dispense(
            F.device_dispense_payload(
                study["id"],
                lot["id"],
                interpreted_read,
                device_serial=C.device_serial("HA", 400008),
                ear=C.EAR_LEFT,
                price_cents=195000,
            ),
            USERS.AUD_1,
        ),
        201,
    )
    check.assert_device_dispense(
        dispense,
        diagnostic_study_id=study["id"],
        supply_lot_id=lot["id"],
        device_serial=C.device_serial("HA", 400008),
        ear=C.EAR_LEFT,
        price_cents=195000,
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
        dispensed_by_user_id=C.USER_AUD_1,
    )

    # The first unit out of an interpreted study supersedes nothing.
    check.assert_diagnostic_study(
        SETUP.read_study(api, study["id"]), superseded_dispense_count=0
    )
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]),
        quantity_received=3,
        quantity_on_hand=2,
        quantity_reserved=0,
        quantity_consumed=1,
        quantity_wasted=0,
        available_quantity=2,
        status=C.LOT_ACTIVE,
    )


def test_the_second_dispense_must_pin_the_version_the_first_one_bumped(api):
    """PRD 2.7: "A second dispense against the same interpreted study is a
    legitimate operation — it supersedes the earlier unit and increments the
    study's `superseded_dispense_count` — so state cannot be the gate here
    either."

    Design: Corner/cross_cutting_complexity_layers/dispense_create_rejects_stale_study_version
    """
    study, lot = _dispensing_study(api)
    SETUP.interpret_study(api, study["id"], headers=USERS.AUD_2)
    interpreted_read = SETUP.study_version(api, study["id"])

    # The first unit goes out against that read, which itself bumps the study.
    first = SETUP.create_dispense(
        api,
        study["id"],
        lot["id"],
        serial=C.device_serial("HA", 400008),
        price_cents=195000,
        ear=C.EAR_LEFT,
        headers=USERS.AUD_1,
        expected_version=interpreted_read,
    )

    # A colleague still holding the pre-dispense read is refused.
    validate_error(
        api.create_device_dispense(
            F.device_dispense_payload(
                study["id"],
                lot["id"],
                interpreted_read,
                device_serial=C.device_serial("HA", 400009),
                ear=C.EAR_RIGHT,
                price_cents=195000,
            ),
            USERS.AUD_1,
        ),
        ApiErrorId.STALE_STUDY_VERSION.value,
    )

    # Re-reading the study yields the version the first dispense wrote.
    fresh_read = SETUP.study_version(api, study["id"])
    assert fresh_read > interpreted_read
    second = validate_success(
        api.create_device_dispense(
            F.device_dispense_payload(
                study["id"],
                lot["id"],
                fresh_read,
                device_serial=C.device_serial("HA", 400009),
                ear=C.EAR_RIGHT,
                price_cents=195000,
            ),
            USERS.AUD_1,
        ),
        201,
    )
    check.assert_device_dispense(
        second,
        device_serial=C.device_serial("HA", 400009),
        ear=C.EAR_RIGHT,
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
    )
    check.assert_diagnostic_study(
        SETUP.read_study(api, study["id"]), superseded_dispense_count=1
    )

    # Two units left the lot — one per accepted dispense, none per refusal.
    rows, meta = validate_paginated(
        api.list_device_dispenses(
            USERS.AUD_1, params={"diagnostic_study_id": study["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert set(row["id"] for row in rows) == {first["id"], second["id"]}
    lot_after = SETUP.read_lot(api, lot["id"])
    check.assert_supply_lot(
        lot_after,
        quantity_received=3,
        quantity_on_hand=1,
        quantity_reserved=0,
        quantity_consumed=2,
        quantity_wasted=0,
        available_quantity=1,
        status=C.LOT_ACTIVE,
    )
    check.assert_lot_quantity_ledger(lot_after)


def _cancellation_scenario(api):
    """An authorized case booked into a surgery-center block, holding one device,
    one scope interval and one block slot."""
    policy = SETUP.create_policy(
        api,
        plan_code="CONA-2999",
        payer_name="Immediate Health",
        requires_prior_auth=True,
        max_balloon_devices=2,
        min_documented_criteria=2,
        min_medical_management_days=28,
        requires_ct_within_months=12,
        auth_validity_days=90,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10253),
        full_name="Odile Ferreira",
        date_of_birth="1962-09-09",
        epinephrine_on_file=True,
    )
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
    SETUP.submit_case(api, case["id"], headers=USERS.LIAISON_1)
    SETUP.decide_case(
        api, case["id"], C.DECISION_APPROVED, "PA-77401", headers=USERS.LIAISON_2
    )
    scope = SETUP.register_scope(api, serial=C.scope_serial(13), model="ENT-Flex 9")
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_no=C.lot_number(1035),
        quantity_received=4,
        expires_at="2028-01-01T00:00:00Z",
    )
    block = SETUP.publish_block(
        api,
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        max_concurrent_cases=2,
        center_name="Day Surgery West",
    )
    booking = SETUP.create_booking(
        api,
        patient["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        physician_user_id=C.USER_ENT_1,
        procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
        venue=C.VENUE_SURGERY_CENTER,
        headers=USERS.ENT_1,
        sinuplasty_case_id=case["id"],
        endoscope_asset_id=scope["id"],
        supply_lot_id=lot["id"],
        surgery_center_block_id=block["id"],
        planned_device_count=1,
    )
    return {"case": case, "scope": scope, "lot": lot, "block": block, "booking": booking}


def _cancel(api, booking_id):
    """Cancel a scheduled booking at the patient's request."""
    return check.validate_unpaginated(
        api.cancel_procedure_booking(
            booking_id,
            F.booking_cancel_payload(cancel_reason=C.CANCEL_REASON_PATIENT_REQUEST),
            USERS.ADMIN_1,
        )
    )


def test_a_cancellation_is_already_in_the_blocks_utilization_when_it_is_next_read(api):
    """PRD 3.9: "The block's `booked_case_count` falls by one, its `booked_minutes`
    falls by the booking's `duration_minutes`, `utilization_bps` is recomputed,
    and the block flips `FULL → OPEN` if the result falls below 10000 basis
    points."

    Design: Corner/consistency_model/booking_cancel_is_immediately_visible_in_every_derived_read
    """
    world = _cancellation_scenario(api)

    # One booked hour out of a four-hour block over two concurrent slots.
    before = SETUP.read_block(api, world["block"]["id"])
    check.assert_surgery_center_block(
        before,
        capacity_minutes=480,
        booked_case_count=1,
        booked_minutes=60,
        utilization_bps=1250,
        status=C.BLOCK_OPEN,
    )
    check.assert_block_utilization(before)

    # The cancellation answers with the terminal status itself.
    cancelled = _cancel(api, world["booking"]["id"])
    check.assert_procedure_booking(cancelled, status=C.BOOKING_CANCELLED)

    # The very next read of the block already shows the released slot.
    after = SETUP.read_block(api, world["block"]["id"])
    check.assert_surgery_center_block(
        after,
        capacity_minutes=480,
        booked_case_count=0,
        booked_minutes=0,
        utilization_bps=0,
        status=C.BLOCK_OPEN,
    )
    check.assert_block_utilization(after)


def test_a_cancellation_is_already_in_the_lot_ledger_when_it_is_next_read(api):
    """PRD 3.9: "The lot's reservation of `planned_device_count` units is released,
    so `available_quantity` rises while all four buckets stay exactly where they
    were and the conserved identity is untouched; if that lifts
    `available_quantity` above zero the lot flips `EXHAUSTED → ACTIVE` and the
    `supply_shortfall_flag` is cleared on the lot's `SCHEDULED` bookings."

    Design: Corner/consistency_model/booking_cancel_is_immediately_visible_in_every_derived_read
    """
    world = _cancellation_scenario(api)

    # One balloon device is held against the scheduled procedure.
    before = SETUP.read_lot(api, world["lot"]["id"])
    check.assert_supply_lot(
        before,
        quantity_received=4,
        quantity_on_hand=4,
        quantity_reserved=1,
        quantity_consumed=0,
        quantity_wasted=0,
        available_quantity=3,
        status=C.LOT_ACTIVE,
    )
    check.assert_lot_quantity_ledger(before)

    _cancel(api, world["booking"]["id"])

    # The next read shows the reservation gone and the four buckets unmoved.
    after = SETUP.read_lot(api, world["lot"]["id"])
    check.assert_supply_lot(
        after,
        quantity_received=4,
        quantity_on_hand=4,
        quantity_reserved=0,
        quantity_consumed=0,
        quantity_wasted=0,
        available_quantity=4,
        status=C.LOT_ACTIVE,
    )
    check.assert_lot_quantity_ledger(after)

    # A booking that never started never claimed the scope's own status.
    check.assert_endoscope(
        SETUP.read_scope(api, world["scope"]["id"]),
        status=C.SCOPE_READY,
        cycle_count=0,
    )


def test_a_cancellation_returns_the_case_to_authorized_in_every_following_read(api):
    """PRD 3.9: "And the compensation reaches the case: a `BALLOON_SINUPLASTY`
    booking's case returns `SCHEDULED → AUTHORIZED`, or `SCHEDULED → DOCUMENTED`
    on the self-pay path, with its `authorized_device_count`, `auth_expires_at`,
    `pinned_policy_version` and `revision_round` all left exactly as they were,
    so a case can be rescheduled without any fresh trip to the payer — provided
    its authorization has not expired in the meantime."

    Design: Corner/consistency_model/booking_cancel_is_immediately_visible_in_every_derived_read
    """
    world = _cancellation_scenario(api)

    # Scheduling moved the authorized case onto the calendar.
    before = SETUP.read_case(api, world["case"]["id"])
    check.assert_sinuplasty_case(
        before,
        status=C.CASE_SCHEDULED,
        authorized_device_count=1,
        pinned_policy_version=1,
        payer_reference="PA-77401",
    )
    check.assert_instant_equals(before["auth_expires_at"], "2026-10-30T00:00:00Z")

    _cancel(api, world["booking"]["id"])

    # The next read of the case already carries the compensation, with the
    # authorization it won from the payer left exactly as it was.
    after = SETUP.read_case(api, world["case"]["id"])
    check.assert_sinuplasty_case(
        after,
        status=C.CASE_AUTHORIZED,
        authorized_device_count=1,
        pinned_policy_version=1,
        payer_reference="PA-77401",
    )
    check.assert_instant_equals(after["auth_expires_at"], "2026-10-30T00:00:00Z")

    # The booking itself is terminal and carries the reason it was cancelled.
    booking_after = SETUP.read_booking(api, world["booking"]["id"])
    check.assert_procedure_booking(
        booking_after,
        status=C.BOOKING_CANCELLED,
        cancel_reason=C.CANCEL_REASON_PATIENT_REQUEST,
        duration_minutes=60,
        planned_device_count=1,
    )

    # Reading each derived row a second time returns the same values, because
    # the cancellation was written once and not recomputed per read.
    assert SETUP.read_case(api, world["case"]["id"]) == after
    assert SETUP.read_booking(api, world["booking"]["id"]) == booking_after
