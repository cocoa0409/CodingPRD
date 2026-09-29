"""Hearing-aid dispensing: the two trial-return refund variants, the two independent dispense dimensions, and the study gates a dispense must clear."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def _hearing_aid_dispensed_at_the_default_clock(
    api, patient_mrn, device_serial, ear, word_recognition_pct
):
    """Fit one hearing aid at the default clock under a thirty-day trial plan.

    The plan charges a fifteen-percent restocking fee with a floor of one hundred
    and twenty-five dollars, and the audiometry reads a pure-tone average of 55
    decibels, so the interpretation recommends a hearing aid.
    """
    policy = SETUP.create_policy(
        api,
        plan_code="AUD-2999",
        payer_name="Audio Mutual",
        requires_prior_auth=True,
        device_trial_days=30,
        restock_fee_bps=1500,
        restock_fee_floor_cents=12500,
        appliance_covered=True,
        covered_pct_bps=8000,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=patient_mrn,
        full_name="Trial Patient",
        date_of_birth="1988-06-20",
        epinephrine_on_file=True,
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1001),
        quantity_received=5,
        expires_at="2027-06-30T00:00:00Z",
    )
    study = SETUP.interpreted_audiometry(
        api,
        patient["id"],
        pta_db_hl=55.0,
        word_recognition_pct=word_recognition_pct,
    )
    check.assert_diagnostic_study(
        study, status=C.STUDY_INTERPRETED, recommendation=C.RECOMMENDATION_HEARING_AID
    )
    return SETUP.create_dispense(
        api,
        study["id"],
        lot["id"],
        device_type=C.DEVICE_TYPE_HEARING_AID,
        serial=device_serial,
        price_cents=289000,
        ear=ear,
    )


def test_in_trial_return_refunds_the_price_less_restocking_and_wear(api):
    """PRD 3.7: "The `refund_cents` is `price_cents` less `restock_fee_cents` less
    the wear charge, floored at zero so a refund is never negative, and
    `billing_status` becomes `REFUND_PENDING`."

    Design: Difficulty/dual_variant_calc/refund_variant_divergence_on_device_dispense
    """
    dispense = _hearing_aid_dispensed_at_the_default_clock(
        api, C.mrn(10011), C.device_serial("HA", 100001), C.EAR_RIGHT, 72.0
    )
    check.assert_device_dispense(
        dispense,
        price_cents=289000,
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
        refund_variant=None,
        restock_fee_cents=0,
        refund_cents=0,
    )
    check.assert_instant_equals(dispense["trial_end_at"], "2026-08-31T00:00:00Z")

    # The patient brings the aid back on the twelfth day, inside the window.
    SETUP.set_clock(api, "2026-08-12T00:00:00Z")
    returned = SETUP.return_dispense(
        api, dispense["id"], C.RETURN_REASON_DISSATISFIED
    )

    # Fifteen percent of 289000 clears the floor, and wear runs to twelve days.
    check.assert_device_dispense(
        returned,
        price_cents=289000,
        fit_status=C.FIT_RETURNED,
        billing_status=C.BILLING_REFUND_PENDING,
        refund_variant=C.REFUND_VARIANT_IN_TRIAL,
        days_used=12,
        restock_fee_cents=43350,
        refund_cents=241450,
    )
    check.assert_instant_equals(returned["trial_end_at"], "2026-08-31T00:00:00Z")


def test_post_trial_return_retains_the_whole_price(api):
    """PRD 3.7: "Under `POST_TRIAL` the practice keeps the money:
    `restock_fee_cents` is 0, `refund_cents` is 0, and `billing_status` becomes
    `RETAINED`, which is financially terminal and needs no settlement."

    Design: Difficulty/dual_variant_calc/refund_variant_divergence_on_device_dispense
    """
    dispense = _hearing_aid_dispensed_at_the_default_clock(
        api, C.mrn(10011), C.device_serial("HA", 100002), C.EAR_LEFT, 70.0
    )
    check.assert_device_dispense(dispense, price_cents=289000)
    check.assert_instant_equals(dispense["trial_end_at"], "2026-08-31T00:00:00Z")

    # This patient keeps the aid five days past the end of the trial window.
    SETUP.set_clock(api, "2026-09-05T00:00:00Z")
    returned = SETUP.return_dispense(
        api, dispense["id"], C.RETURN_REASON_DISSATISFIED
    )

    # The same price and the same window, and yet no money moves.
    check.assert_device_dispense(
        returned,
        price_cents=289000,
        fit_status=C.FIT_RETURNED,
        billing_status=C.BILLING_RETAINED,
        refund_variant=C.REFUND_VARIANT_POST_TRIAL,
        days_used=36,
        restock_fee_cents=0,
        refund_cents=0,
    )
    check.assert_instant_equals(returned["trial_end_at"], "2026-08-31T00:00:00Z")


def _fitted_aid_and_its_lot_under_a_parallel_plan(api):
    """Fit one 1500-dollar hearing aid and hand back the lot it came out of."""
    policy = SETUP.create_policy(
        api,
        plan_code="PAR-2999",
        payer_name="Parallel Mutual",
        requires_prior_auth=True,
        device_trial_days=30,
        restock_fee_bps=1500,
        restock_fee_floor_cents=12500,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10061),
        full_name="Parallel Patient",
        date_of_birth="1988-06-20",
        epinephrine_on_file=True,
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1003),
        quantity_received=5,
        expires_at="2027-06-30T00:00:00Z",
    )
    study = SETUP.interpreted_audiometry(
        api, patient["id"], pta_db_hl=55.0, word_recognition_pct=68.0
    )
    dispense = SETUP.create_dispense(
        api,
        study["id"],
        lot["id"],
        device_type=C.DEVICE_TYPE_HEARING_AID,
        serial=C.device_serial("HA", 200001),
        price_cents=150000,
        ear=C.EAR_BOTH,
    )
    check.assert_device_dispense(
        dispense,
        price_cents=150000,
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
        adjustment_count=0,
        dispensed_by_user_id=C.USER_AUD_1,
    )
    check.assert_instant_equals(dispense["trial_end_at"], "2026-08-31T00:00:00Z")
    return dispense, lot


def test_adjustments_move_only_the_fitting_dimension(api):
    """PRD 3.7: "Most transitions move exactly one of the two, and understanding
    which is which is the whole point of the design: the refund settlement moves
    only the financial dimension, leaving `fit_status` at `RETURNED`, while an
    adjustment moves only the fitting dimension and leaves `billing_status`
    untouched at `INVOICED`."

    Design: Difficulty/non_linear_state_machine/device_dispense_parallel_dimensions
    """
    dispense, _lot = _fitted_aid_and_its_lot_under_a_parallel_plan(api)

    # Day two of the trial: the vent bore is opened up.
    SETUP.set_clock(api, "2026-08-02T00:00:00Z")
    first = SETUP.adjust_dispense(
        api, dispense["id"], adjustment_note="Vent bore opened"
    )
    check.assert_device_dispense(
        first,
        fit_status=C.FIT_ADJUSTED,
        billing_status=C.BILLING_INVOICED,
        adjustment_count=1,
        refund_variant=None,
        refund_cents=0,
    )

    # Day three: the gain is trimmed, and ADJUSTED loops back onto itself.
    SETUP.set_clock(api, "2026-08-03T00:00:00Z")
    second = SETUP.adjust_dispense(
        api, dispense["id"], adjustment_note="Gain trimmed 4 dB"
    )
    check.assert_device_dispense(
        second,
        fit_status=C.FIT_ADJUSTED,
        billing_status=C.BILLING_INVOICED,
        adjustment_count=2,
        refund_variant=None,
        refund_cents=0,
    )


def test_refund_settlement_moves_only_the_financial_dimension(api):
    """PRD 3.7: "On success `billing_status` moves `REFUND_PENDING → REFUNDED` and
    `settled_by_user_id` is stamped, while the fitting dimension self-loops
    `RETURNED → RETURNED` and stays exactly where it was — this transition is
    purely financial, which is what proves the two dimensions independent."

    Design: Difficulty/non_linear_state_machine/device_dispense_parallel_dimensions
    """
    dispense, lot = _fitted_aid_and_its_lot_under_a_parallel_plan(api)

    # Two adjustments on the fitting axis before the aid comes back.
    SETUP.set_clock(api, "2026-08-02T00:00:00Z")
    SETUP.adjust_dispense(api, dispense["id"], adjustment_note="Vent bore opened")
    SETUP.set_clock(api, "2026-08-03T00:00:00Z")
    SETUP.adjust_dispense(api, dispense["id"], adjustment_note="Gain trimmed 4 dB")

    # The return moves the fitting axis to RETURNED and opens a pending refund.
    SETUP.set_clock(api, "2026-08-12T00:00:00Z")
    returned = SETUP.return_dispense(api, dispense["id"], C.RETURN_REASON_POOR_FIT)
    check.assert_device_dispense(
        returned,
        fit_status=C.FIT_RETURNED,
        billing_status=C.BILLING_REFUND_PENDING,
        refund_variant=C.REFUND_VARIANT_IN_TRIAL,
        days_used=12,
        restock_fee_cents=22500,
        refund_cents=123300,
        adjustment_count=2,
        settled_by_user_id=None,
    )

    # A second administrator settles the money and touches nothing else.
    settled = check.validate_unpaginated(
        api.settle_device_refund(dispense["id"], USERS.ADMIN_2)
    )
    check.assert_device_dispense(
        settled,
        fit_status=C.FIT_RETURNED,
        billing_status=C.BILLING_REFUNDED,
        refund_variant=C.REFUND_VARIANT_IN_TRIAL,
        days_used=12,
        restock_fee_cents=22500,
        refund_cents=123300,
        adjustment_count=2,
        dispensed_by_user_id=C.USER_AUD_1,
        settled_by_user_id=C.USER_ADMIN_2,
    )

    # The returned unit is written off rather than restocked.
    lot_after = SETUP.read_lot(api, lot["id"])
    check.assert_supply_lot(
        lot_after,
        quantity_received=5,
        quantity_on_hand=4,
        quantity_reserved=0,
        quantity_consumed=0,
        quantity_wasted=1,
        available_quantity=4,
        status=C.LOT_ACTIVE,
    )


def _audiology_patient_and_stocked_lot(api):
    """Register a plan, an adult patient and a lot of five hearing aids.

    Five units means inventory never binds, so the gates a dispense fails are
    only ever the study's own.
    """
    policy = SETUP.create_policy(
        api,
        plan_code="AUDX-2999",
        payer_name="Audio Mutual",
        requires_prior_auth=True,
        device_trial_days=30,
        restock_fee_bps=1500,
        restock_fee_floor_cents=12500,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10141),
        full_name="Hearing Patient",
        date_of_birth="1959-04-22",
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1007),
        quantity_received=5,
        expires_at="2028-06-30T00:00:00Z",
    )
    return patient, lot


def _hearing_aid_dispense_body(study_id, lot_id, expected_study_version):
    """One hearing-aid dispense body, identical at every attempt but the version."""
    return F.device_dispense_payload(
        study_id,
        lot_id,
        expected_study_version,
        device_type=C.DEVICE_TYPE_HEARING_AID,
        device_serial=C.device_serial("HA", 300001),
        ear=C.EAR_LEFT,
        price_cents=289000,
    )


def test_dispense_against_an_ordered_study_reports_the_study_state(api):
    """PRD 3.7: "The study must be `INTERPRETED`, or the dispense is refused with
    `ERR_STUDY_STATE_INVALID`; a `QUARANTINED` lot is refused with
    `ERR_LOT_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/dispense_gated_by_study_state_then_recommendation
    """
    patient, lot = _audiology_patient_and_stocked_lot(api)

    # A study that has only been ordered carries no measurements at all.
    study = SETUP.create_study(api, patient["id"], study_type=C.STUDY_AUDIOMETRY)
    check.assert_diagnostic_study(
        study,
        status=C.STUDY_ORDERED,
        version=1,
        pta_db_hl=None,
        recommendation=None,
        superseded_dispense_count=0,
    )

    # The version is pinned freshly, so only the lifecycle rule can bite.
    body = _hearing_aid_dispense_body(
        study["id"], lot["id"], SETUP.study_version(api, study["id"])
    )
    validate_error(
        api.create_device_dispense(body, USERS.AUD_1),
        ApiErrorId.STUDY_STATE_INVALID.value,
    )

    # Neither the study nor the inventory moved.
    check.assert_diagnostic_study(
        SETUP.read_study(api, study["id"]), status=C.STUDY_ORDERED, version=1
    )
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]),
        quantity_received=5,
        quantity_on_hand=5,
        quantity_consumed=0,
        quantity_wasted=0,
        available_quantity=5,
        status=C.LOT_ACTIVE,
    )


def test_hearing_aid_is_refused_against_an_observation_recommendation(api):
    """PRD 3.7: "A `CPAP` recommendation and an `OBSERVATION` recommendation admit
    no device at all, so any dispense attempted against them is refused with
    `ERR_DEVICE_TYPE_NOT_RECOMMENDED`."

    Design: Difficulty/cross_entity_state_dependency/dispense_gated_by_study_state_then_recommendation
    """
    patient, lot = _audiology_patient_and_stocked_lot(api)

    # A pure-tone average of 30 decibels does not reach the hearing-aid line.
    study = SETUP.interpreted_audiometry(
        api, patient["id"], pta_db_hl=30.0, word_recognition_pct=88.0
    )
    check.assert_diagnostic_study(
        study,
        status=C.STUDY_INTERPRETED,
        version=3,
        recommendation=C.RECOMMENDATION_OBSERVATION,
        performed_by_user_id=C.USER_AUD_1,
        interpreted_by_user_id=C.USER_AUD_2,
    )

    # The state gate is satisfied now, so the content gate is what refuses.
    body = _hearing_aid_dispense_body(
        study["id"], lot["id"], SETUP.study_version(api, study["id"])
    )
    validate_error(
        api.create_device_dispense(body, USERS.AUD_1),
        ApiErrorId.DEVICE_TYPE_NOT_RECOMMENDED.value,
    )

    # A refused dispense leaves the interpreted study and the lot alone.
    check.assert_diagnostic_study(
        SETUP.read_study(api, study["id"]),
        status=C.STUDY_INTERPRETED,
        version=3,
        superseded_dispense_count=0,
    )
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]),
        quantity_on_hand=5,
        quantity_consumed=0,
        available_quantity=5,
        status=C.LOT_ACTIVE,
    )


def test_hearing_aid_dispense_succeeds_against_a_recommending_study(api):
    """PRD 3.7: "On success the dispense is created with `fit_status` `FITTED`,
    `billing_status` `INVOICED`, `adjustment_count` 0, `days_used` 0,
    `restock_fee_cents` 0, `refund_cents` 0, `refund_variant` null,
    `settled_by_user_id` null, `dispensed_by_user_id` stamped from the acting
    identifier, `dispensed_at` stamped from the logical clock, and `trial_end_at`
    set to `dispensed_at` advanced by the plan's `device_trial_days` whole days."

    Design: Difficulty/cross_entity_state_dependency/dispense_gated_by_study_state_then_recommendation
    """
    patient, lot = _audiology_patient_and_stocked_lot(api)

    # This audiometry reads 55 decibels, which crosses the hearing-aid line.
    study = SETUP.interpreted_audiometry(
        api, patient["id"], pta_db_hl=55.0, word_recognition_pct=62.0
    )
    check.assert_diagnostic_study(
        study,
        status=C.STUDY_INTERPRETED,
        version=3,
        recommendation=C.RECOMMENDATION_HEARING_AID,
    )

    # The identical body now clears every gate on the ladder.
    body = _hearing_aid_dispense_body(
        study["id"], lot["id"], SETUP.study_version(api, study["id"])
    )
    dispense = validate_success(api.create_device_dispense(body, USERS.AUD_1), 201)
    check.assert_device_dispense(
        dispense,
        device_type=C.DEVICE_TYPE_HEARING_AID,
        device_serial=C.device_serial("HA", 300001),
        ear=C.EAR_LEFT,
        price_cents=289000,
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
        adjustment_count=0,
        days_used=0,
        restock_fee_cents=0,
        refund_cents=0,
        refund_variant=None,
        settled_by_user_id=None,
        dispensed_by_user_id=C.USER_AUD_1,
    )
    check.assert_instant_equals(dispense["dispensed_at"], "2026-08-01T00:00:00Z")
    check.assert_instant_equals(dispense["trial_end_at"], "2026-08-31T00:00:00Z")

    # One unit left the lot, and the study version moved on with it.
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]),
        quantity_received=5,
        quantity_on_hand=4,
        quantity_reserved=0,
        quantity_consumed=1,
        quantity_wasted=0,
        available_quantity=4,
        status=C.LOT_ACTIVE,
    )
    check.assert_diagnostic_study(
        SETUP.read_study(api, study["id"]),
        status=C.STUDY_INTERPRETED,
        version=4,
        superseded_dispense_count=0,
    )
