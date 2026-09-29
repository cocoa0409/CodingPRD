"""The scheduling and compounding half of the PRD 5 error catalogue: overnight
capability, authorized device counts, lazy authorization expiry, case-to-patient
coherence, vial label and beyond-use gates, and per-entity state gates."""

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


def test_a_pediatric_tonsillectomy_is_refused_by_a_block_without_overnight_capability(api):
    """PRD 3.9: "Next, at the safety rung, a booking whose `overnight_observation_required`
    is true and which names a block whose `overnight_capable` is false is refused with
    `ERR_OVERNIGHT_CAPABILITY_REQUIRED`."

    Design: Corner/errors/overnight_capability_required_for_a_pediatric_tonsillectomy
    """
    # A child born 2024-06-01 reads twenty-six whole months at the default clock.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRG-2999",
        patient_mrn=C.mrn(10241),
        policy_overrides={"payer_name": "Overnight Health"},
        patient_overrides={
            "full_name": "Tobias Marchetti",
            "date_of_birth": "2024-06-01",
        },
    )
    patient = registered["patient"]
    check.assert_patient(patient, age_months=26)

    # The day-surgery centre staffs two rooms for four hours but cannot keep a child overnight.
    day_block = SETUP.publish_block(
        api,
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        max_concurrent_cases=2,
        overnight_capable=False,
        center_name="Day Surgery North",
    )
    check.assert_surgery_center_block(
        day_block, capacity_minutes=480, overnight_capable=False, status=C.BLOCK_OPEN
    )

    # The tonsillectomy is booked into that block.
    response = api.create_procedure_booking(
        SETUP.booking_payload(
            patient["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T10:00:00Z",
            physician_user_id=C.USER_ENT_1,
            procedure_type=C.PROCEDURE_TONSILLECTOMY,
            venue=C.VENUE_SURGERY_CENTER,
            surgery_center_block_id=day_block["id"],
        ),
        USERS.ADMIN_1,
    )
    validate_error(response, ApiErrorId.OVERNIGHT_CAPABILITY_REQUIRED.value)

    # The refusal reserved nothing: the block's aggregates never moved.
    check.assert_surgery_center_block(
        SETUP.read_block(api, day_block["id"]),
        booked_case_count=0,
        booked_minutes=0,
        utilization_bps=0,
        capacity_minutes=480,
        status=C.BLOCK_OPEN,
    )


def test_an_overnight_capable_block_accepts_the_same_pediatric_tonsillectomy(api):
    """PRD 3.9: "Two flags are derived at creation: `overnight_observation_required` is true
    exactly when `procedure_type` is `TONSILLECTOMY` and the patient's `age_months` is below
    36, and `requires_physician_presence` is true when the patient's `supervision_tier` is
    already `PHYSICIAN_PRESENT` — and is also set true later, on an existing `SCHEDULED`
    booking, by the reaction cascade of §3.4 whenever that tier is raised."

    Design: Corner/errors/overnight_capability_required_for_a_pediatric_tonsillectomy
    """
    # The same twenty-six-month-old child, on the same plan.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRG-2999",
        patient_mrn=C.mrn(10241),
        policy_overrides={"payer_name": "Overnight Health"},
        patient_overrides={
            "full_name": "Tobias Marchetti",
            "date_of_birth": "2024-06-01",
        },
    )
    patient = registered["patient"]
    check.assert_patient(patient, age_months=26)

    # The children's centre publishes an identical block that differs only in that boolean.
    children_block = SETUP.publish_block(
        api,
        "2026-08-06T08:00:00Z",
        "2026-08-06T12:00:00Z",
        max_concurrent_cases=2,
        overnight_capable=True,
        center_name="Children's Surgery South",
    )
    check.assert_surgery_center_block(
        children_block, capacity_minutes=480, overnight_capable=True
    )

    # The identical booking payload is accepted there.
    response = api.create_procedure_booking(
        SETUP.booking_payload(
            patient["id"],
            "2026-08-06T09:00:00Z",
            "2026-08-06T10:00:00Z",
            physician_user_id=C.USER_ENT_1,
            procedure_type=C.PROCEDURE_TONSILLECTOMY,
            venue=C.VENUE_SURGERY_CENTER,
            surgery_center_block_id=children_block["id"],
        ),
        USERS.ADMIN_1,
    )
    booking = validate_success(response, 201)
    check.assert_procedure_booking(
        booking,
        procedure_type=C.PROCEDURE_TONSILLECTOMY,
        venue=C.VENUE_SURGERY_CENTER,
        surgery_center_block_id=children_block["id"],
        overnight_observation_required=True,
        requires_physician_presence=False,
        duration_minutes=60,
        planned_device_count=0,
        status=C.BOOKING_SCHEDULED,
    )

    # Sixty of the block's four hundred and eighty capacity minutes are now booked.
    check.assert_surgery_center_block(
        SETUP.read_block(api, children_block["id"]),
        booked_case_count=1,
        booked_minutes=60,
        capacity_minutes=480,
        utilization_bps=1250,
        status=C.BLOCK_OPEN,
    )


def test_a_booking_planning_more_devices_than_the_payer_authorized_is_refused(api):
    """PRD 3.9: "A `BALLOON_SINUPLASTY` booking's `planned_device_count` may not exceed the
    case's `authorized_device_count`, or it is refused with
    `ERR_DEVICE_COUNT_EXCEEDS_AUTHORIZATION` — which is how a plan's `max_balloon_devices`
    ceiling, applied at approval, reaches forward into the schedule."

    Design: Corner/errors/device_count_exceeding_authorization_is_rejected
    """
    # A plan that requires prior authorization and caps balloon devices at two.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRH-2999",
        patient_mrn=C.mrn(10242),
        policy_overrides={"payer_name": "Auth Count Health"},
        patient_overrides={
            "full_name": "Ingrid Solberg",
            "date_of_birth": "1967-09-09",
        },
    )
    patient = registered["patient"]
    check.assert_payer_policy(
        registered["policy"],
        requires_prior_auth=True,
        max_balloon_devices=2,
        auth_validity_days=90,
    )

    # A bilateral case over two sinuses plans four devices; the payer approves only two.
    case = SETUP.authorized_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_BILATERAL,
        sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
        payer_reference="PA-77201",
    )
    check.assert_sinuplasty_case(
        case,
        planned_device_count=4,
        contiguous_management_days=28,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
        authorized_device_count=2,
        status=C.CASE_AUTHORIZED,
    )

    # Supply can never be the binding constraint: six balloon devices are on hand.
    scope = SETUP.register_scope(api, serial=C.scope_serial(9), model="ENT-Flex 9")
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_no=C.lot_number(1026),
        quantity_received=6,
        expires_at="2028-01-01T00:00:00Z",
    )

    # The surgeon tries to schedule three devices against an authorization for two.
    response = api.create_procedure_booking(
        SETUP.booking_payload(
            patient["id"],
            "2026-08-04T09:00:00Z",
            "2026-08-04T10:00:00Z",
            physician_user_id=C.USER_ENT_1,
            procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
            venue=C.VENUE_IN_OFFICE_SUITE,
            sinuplasty_case_id=case["id"],
            endoscope_asset_id=scope["id"],
            supply_lot_id=lot["id"],
            planned_device_count=3,
        ),
        USERS.ENT_1,
    )
    validate_error(response, ApiErrorId.DEVICE_COUNT_EXCEEDS_AUTHORIZATION.value)

    # Neither the case nor the lot moved.
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case["id"]),
        status=C.CASE_AUTHORIZED,
        authorized_device_count=2,
    )
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]),
        quantity_reserved=0,
        quantity_on_hand=6,
        available_quantity=6,
    )


def test_a_booking_at_the_authorized_device_ceiling_schedules_the_case(api):
    """PRD 3.6: "`APPROVED` moves the case `AUTH_SUBMITTED → AUTHORIZED`, sets
    `authorized_device_count` to whichever is smaller of the case's `planned_device_count` and
    the plan's `max_balloon_devices`, and sets `auth_expires_at` to the current logical-clock
    instant advanced by the plan's `auth_validity_days` whole days."

    Design: Corner/errors/device_count_exceeding_authorization_is_rejected
    """
    # The same plan, patient and bilateral two-sinus case.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRH-2999",
        patient_mrn=C.mrn(10242),
        policy_overrides={"payer_name": "Auth Count Health"},
        patient_overrides={
            "full_name": "Ingrid Solberg",
            "date_of_birth": "1967-09-09",
        },
    )
    patient = registered["patient"]
    case = SETUP.authorized_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_BILATERAL,
        sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
        payer_reference="PA-77201",
    )
    check.assert_sinuplasty_case(
        case, planned_device_count=4, authorized_device_count=2, status=C.CASE_AUTHORIZED
    )
    check.assert_instant_equals(case["auth_expires_at"], "2026-10-30T00:00:00Z")

    scope = SETUP.register_scope(api, serial=C.scope_serial(9), model="ENT-Flex 9")
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_no=C.lot_number(1026),
        quantity_received=6,
        expires_at="2028-01-01T00:00:00Z",
    )

    # Two devices is exactly what the payer allowed, so the booking stands.
    response = api.create_procedure_booking(
        SETUP.booking_payload(
            patient["id"],
            "2026-08-04T09:00:00Z",
            "2026-08-04T10:00:00Z",
            physician_user_id=C.USER_ENT_1,
            procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
            venue=C.VENUE_IN_OFFICE_SUITE,
            sinuplasty_case_id=case["id"],
            endoscope_asset_id=scope["id"],
            supply_lot_id=lot["id"],
            planned_device_count=2,
        ),
        USERS.ENT_1,
    )
    booking = validate_success(response, 201)
    check.assert_procedure_booking(
        booking,
        sinuplasty_case_id=case["id"],
        planned_device_count=2,
        devices_used_count=0,
        status=C.BOOKING_SCHEDULED,
    )

    # The case follows the booking and the lot reserves the two units.
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case["id"]),
        status=C.CASE_SCHEDULED,
        authorized_device_count=2,
    )
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]),
        quantity_reserved=2,
        quantity_on_hand=6,
        quantity_consumed=0,
        available_quantity=4,
    )


def test_a_booking_on_the_expiry_instant_persists_the_case_as_auth_expired(api):
    """PRD 3.9: "When a `BALLOON_SINUPLASTY` booking is created against an `AUTHORIZED` case
    whose `auth_expires_at` the logical clock has reached, the case is **first persisted** as
    `AUTH_EXPIRED` and only then is the request rejected with `ERR_AUTHORIZATION_EXPIRED`."

    Design: Corner/errors/authorization_expired_persists_the_case_as_auth_expired
    """
    # A plan whose authorizations are good for ninety whole days.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRI-2999",
        patient_mrn=C.mrn(10243),
        policy_overrides={"payer_name": "Expiry Health"},
        patient_overrides={
            "full_name": "Amos Lindqvist",
            "date_of_birth": "1961-10-10",
        },
    )
    patient = registered["patient"]
    check.assert_payer_policy(registered["policy"], auth_validity_days=90)

    # Approved at the default clock, so the authorization runs out on 2026-10-30.
    case = SETUP.authorized_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_RIGHT,
        sinuses=[C.SINUS_MAXILLARY],
        payer_reference="PA-77202",
    )
    check.assert_sinuplasty_case(
        case,
        planned_device_count=1,
        authorized_device_count=1,
        revision_round=0,
        status=C.CASE_AUTHORIZED,
    )
    check.assert_instant_equals(case["auth_expires_at"], "2026-10-30T00:00:00Z")

    # Nothing else can block the booking: a ready scope and four balloon devices.
    scope = SETUP.register_scope(api, serial=C.scope_serial(10), model="ENT-Flex 9")
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_no=C.lot_number(1027),
        quantity_received=4,
        expires_at="2028-01-01T00:00:00Z",
    )

    # The practice administrator parks the clock exactly on the expiry instant.
    SETUP.set_clock(api, "2026-10-30T00:00:00Z")

    # The scheduling attempt observes the lapsed authorization.
    response = api.create_procedure_booking(
        SETUP.booking_payload(
            patient["id"],
            "2026-11-02T09:00:00Z",
            "2026-11-02T10:00:00Z",
            physician_user_id=C.USER_ENT_1,
            procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
            venue=C.VENUE_IN_OFFICE_SUITE,
            sinuplasty_case_id=case["id"],
            endoscope_asset_id=scope["id"],
            supply_lot_id=lot["id"],
            planned_device_count=1,
        ),
        USERS.ENT_1,
    )
    validate_error(response, ApiErrorId.AUTHORIZATION_EXPIRED.value)

    # The rejection left a durable trace: only the status moved.
    expired = SETUP.read_case(api, case["id"], USERS.LIAISON_1)
    check.assert_sinuplasty_case(
        expired,
        status=C.CASE_AUTH_EXPIRED,
        authorized_device_count=1,
        revision_round=0,
        payer_reference="PA-77202",
    )
    check.assert_instant_equals(expired["auth_expires_at"], "2026-10-30T00:00:00Z")

    # No booking row was written and no device was reserved.
    rows, _meta = validate_paginated(
        api.list_procedure_bookings(USERS.ADMIN_1, {"sinuplasty_case_id": case["id"]})
    )
    assert rows == [], "a rejected booking must leave no row behind, got {0!r}".format(rows)
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]), quantity_reserved=0, available_quantity=4
    )


def test_an_expired_authorization_re_enters_the_payer_loop_with_a_fresh_budget(api):
    """PRD 3.6: "From `AUTH_EXPIRED`, the submission resets `revision_round` to 0,
    `authorized_device_count` to 0 and `auth_expires_at` to null, giving an expired
    authorization a fresh revision budget as it re-enters the loop."

    Design: Corner/errors/authorization_expired_persists_the_case_as_auth_expired
    """
    # The same plan, patient and single-sinus case, authorized at the default clock.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRI-2999",
        patient_mrn=C.mrn(10243),
        policy_overrides={"payer_name": "Expiry Health"},
        patient_overrides={
            "full_name": "Amos Lindqvist",
            "date_of_birth": "1961-10-10",
        },
    )
    patient = registered["patient"]
    case = SETUP.authorized_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_RIGHT,
        sinuses=[C.SINUS_MAXILLARY],
        payer_reference="PA-77202",
    )
    scope = SETUP.register_scope(api, serial=C.scope_serial(10), model="ENT-Flex 9")
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_no=C.lot_number(1027),
        quantity_received=4,
        expires_at="2028-01-01T00:00:00Z",
    )

    # The clock reaches the expiry instant and a booking attempt observes it.
    SETUP.set_clock(api, "2026-10-30T00:00:00Z")
    rejected = api.create_procedure_booking(
        SETUP.booking_payload(
            patient["id"],
            "2026-11-02T09:00:00Z",
            "2026-11-02T10:00:00Z",
            physician_user_id=C.USER_ENT_1,
            procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
            venue=C.VENUE_IN_OFFICE_SUITE,
            sinuplasty_case_id=case["id"],
            endoscope_asset_id=scope["id"],
            supply_lot_id=lot["id"],
            planned_device_count=1,
        ),
        USERS.ENT_1,
    )
    validate_error(rejected, ApiErrorId.AUTHORIZATION_EXPIRED.value)
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case["id"]), status=C.CASE_AUTH_EXPIRED
    )

    # The payer liaison files a fresh submission from the expired posture.
    resubmitted = check.validate_unpaginated(
        api.submit_authorization(case["id"], USERS.LIAISON_1)
    )
    check.assert_sinuplasty_case(
        resubmitted,
        status=C.CASE_AUTH_SUBMITTED,
        revision_round=0,
        authorized_device_count=0,
        auth_expires_at=None,
        pinned_policy_version=1,
        submitted_by_user_id=C.USER_LIAISON_1,
    )


def test_a_booking_wired_to_another_patients_case_is_refused_as_a_mismatch(api):
    """PRD 3.9: "Then the referential rung: the lot's `item_type` must match the
    `procedure_type` — a `BALLOON_SINUPLASTY` draws `BALLOON_DEVICE` and a
    `TYMPANOSTOMY_TUBES` draws `TYMPANOSTOMY_TUBE` — or the booking is refused with
    `ERR_LOT_ITEM_TYPE_MISMATCH`; and the referenced case's `patient_id` must equal the
    booking's own `patient_id`, or it is refused with `ERR_CASE_PATIENT_MISMATCH`."

    Design: Corner/errors/case_patient_mismatch_on_booking_create
    """
    # Two adults share one plan; only the first of them owns a sinuplasty case.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRJ-2999",
        patient_mrn=C.mrn(10244),
        policy_overrides={"payer_name": "Mismatch Health"},
        patient_overrides={
            "full_name": "Case Owner A",
            "date_of_birth": "1959-11-11",
        },
    )
    owner = registered["patient"]
    other = SETUP.create_patient(
        api,
        registered["policy"]["id"],
        patient_mrn=C.mrn(10245),
        full_name="Other Patient B",
        date_of_birth="1962-12-12",
    )
    case = SETUP.authorized_case(
        api,
        owner["id"],
        laterality=C.LATERALITY_RIGHT,
        sinuses=[C.SINUS_SPHENOID],
        payer_reference="PA-77203",
    )
    check.assert_sinuplasty_case(
        case,
        patient_id=owner["id"],
        authorized_device_count=1,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
        status=C.CASE_AUTHORIZED,
    )

    scope = SETUP.register_scope(api, serial=C.scope_serial(11), model="ENT-Flex 9")
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_no=C.lot_number(1028),
        quantity_received=4,
        expires_at="2028-01-01T00:00:00Z",
    )

    # The booking names the second patient but the first patient's case; both ids exist.
    response = api.create_procedure_booking(
        SETUP.booking_payload(
            other["id"],
            "2026-08-04T09:00:00Z",
            "2026-08-04T10:00:00Z",
            physician_user_id=C.USER_ENT_1,
            procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
            venue=C.VENUE_IN_OFFICE_SUITE,
            sinuplasty_case_id=case["id"],
            endoscope_asset_id=scope["id"],
            supply_lot_id=lot["id"],
            planned_device_count=1,
        ),
        USERS.ENT_1,
    )
    validate_error(response, ApiErrorId.CASE_PATIENT_MISMATCH.value)

    # The cross-wired attempt moved neither the case nor the lot.
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case["id"]), status=C.CASE_AUTHORIZED
    )
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]), quantity_reserved=0, available_quantity=4
    )


def test_the_same_booking_for_the_cases_own_patient_schedules_the_case(api):
    """PRD 3.9: "A `BALLOON_SINUPLASTY` booking moves its case `AUTHORIZED → SCHEDULED`, or
    `DOCUMENTED → SCHEDULED` on the self-pay path."

    Design: Corner/errors/case_patient_mismatch_on_booking_create
    """
    # The same plan, the same two adults, the same authorized case belonging to the first.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRJ-2999",
        patient_mrn=C.mrn(10244),
        policy_overrides={"payer_name": "Mismatch Health"},
        patient_overrides={
            "full_name": "Case Owner A",
            "date_of_birth": "1959-11-11",
        },
    )
    owner = registered["patient"]
    SETUP.create_patient(
        api,
        registered["policy"]["id"],
        patient_mrn=C.mrn(10245),
        full_name="Other Patient B",
        date_of_birth="1962-12-12",
    )
    case = SETUP.authorized_case(
        api,
        owner["id"],
        laterality=C.LATERALITY_RIGHT,
        sinuses=[C.SINUS_SPHENOID],
        payer_reference="PA-77203",
    )
    scope = SETUP.register_scope(api, serial=C.scope_serial(11), model="ENT-Flex 9")
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_no=C.lot_number(1028),
        quantity_received=4,
        expires_at="2028-01-01T00:00:00Z",
    )

    # This time the booking's patient is the case's own patient.
    response = api.create_procedure_booking(
        SETUP.booking_payload(
            owner["id"],
            "2026-08-04T09:00:00Z",
            "2026-08-04T10:00:00Z",
            physician_user_id=C.USER_ENT_1,
            procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
            venue=C.VENUE_IN_OFFICE_SUITE,
            sinuplasty_case_id=case["id"],
            endoscope_asset_id=scope["id"],
            supply_lot_id=lot["id"],
            planned_device_count=1,
        ),
        USERS.ENT_1,
    )
    booking = validate_success(response, 201)
    check.assert_procedure_booking(
        booking,
        patient_id=owner["id"],
        sinuplasty_case_id=case["id"],
        endoscope_asset_id=scope["id"],
        planned_device_count=1,
        status=C.BOOKING_SCHEDULED,
    )

    # The case is scheduled, one device is reserved, and the scope waits until the start.
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case["id"]), status=C.CASE_SCHEDULED
    )
    check.assert_supply_lot(
        SETUP.read_lot(api, lot["id"]), quantity_reserved=1, available_quantity=3
    )
    check.assert_endoscope(SETUP.read_scope(api, scope["id"]), status=C.SCOPE_READY)


def test_a_retyped_label_that_differs_by_one_character_is_refused(api):
    """PRD 3.5: "The retyped `label_text_confirmation` must equal the stored `label_text`
    character for character, or the verification is refused with `ERR_VIAL_LABEL_MISMATCH`."

    Design: Corner/errors/vial_label_mismatch_then_expiry_blocks_verification
    """
    # One adult chart and one concentrate lot to compound from.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRK-2999",
        patient_mrn=C.mrn(10246),
        policy_overrides={"payer_name": "Label Health"},
        patient_overrides={
            "full_name": "Ludvig Aaltonen",
            "date_of_birth": "1957-01-15",
        },
    )
    patient = registered["patient"]
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_ALLERGEN_CONCENTRATE,
        lot_no=C.lot_number(1029),
        quantity_received=4,
        expires_at="2027-06-01T00:00:00Z",
    )

    # The first nurse compounds a blue vial that goes beyond use on 2026-08-15.
    vial = SETUP.mix_vial(
        api,
        patient,
        lot["id"],
        dilution_code=C.DILUTION_BLUE,
        expires_at="2026-08-15T00:00:00Z",
        headers=USERS.NURSE_1,
    )
    check.assert_immunotherapy_vial(
        vial,
        label_text=C.make_label_text(C.mrn(10246), C.DILUTION_BLUE, "2026-08-15T00:00:00Z"),
        mixed_by_user_id=C.USER_NURSE_1,
        verified_by_user_id=None,
        status=C.VIAL_MIXED,
    )

    # The second nurse retypes the label but names the neighbouring chart number.
    mistyped = C.make_label_text(C.mrn(10247), C.DILUTION_BLUE, "2026-08-15T00:00:00Z")
    response = api.verify_immunotherapy_vial_label(
        vial["id"], F.label_verification_payload(mistyped), USERS.NURSE_2
    )
    validate_error(response, ApiErrorId.VIAL_LABEL_MISMATCH.value)

    # The vial never left MIXED and no verifier was stamped.
    check.assert_immunotherapy_vial(
        SETUP.read_vial(api, vial["id"]),
        status=C.VIAL_MIXED,
        verified_by_user_id=None,
    )
    check.assert_patient(
        SETUP.read_patient(api, patient["id"]),
        immunotherapy_status=C.IMMUNO_STATUS_NONE,
    )


def test_a_character_perfect_label_is_still_refused_on_the_beyond_use_instant(api):
    """PRD 3.5: "And the logical clock must still be strictly before `expires_at`, or the
    verification is refused with `ERR_VIAL_EXPIRED`."

    Design: Corner/errors/vial_label_mismatch_then_expiry_blocks_verification
    """
    # The same chart, lot and blue vial expiring on 2026-08-15.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRK-2999",
        patient_mrn=C.mrn(10246),
        policy_overrides={"payer_name": "Label Health"},
        patient_overrides={
            "full_name": "Ludvig Aaltonen",
            "date_of_birth": "1957-01-15",
        },
    )
    patient = registered["patient"]
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_ALLERGEN_CONCENTRATE,
        lot_no=C.lot_number(1029),
        quantity_received=4,
        expires_at="2027-06-01T00:00:00Z",
    )
    vial = SETUP.mix_vial(
        api,
        patient,
        lot["id"],
        dilution_code=C.DILUTION_BLUE,
        expires_at="2026-08-15T00:00:00Z",
        headers=USERS.NURSE_1,
    )

    # The clock is parked exactly on the beyond-use instant.
    SETUP.set_clock(api, "2026-08-15T00:00:00Z")

    # The retyped label is now perfect, and the vial is out of time anyway.
    exact = C.make_label_text(C.mrn(10246), C.DILUTION_BLUE, "2026-08-15T00:00:00Z")
    assert exact == vial["label_text"], (
        "the confirmation must be character-perfect, got {0!r} against {1!r}".format(
            exact, vial["label_text"]
        )
    )
    response = api.verify_immunotherapy_vial_label(
        vial["id"], F.label_verification_payload(exact), USERS.NURSE_2
    )
    validate_error(response, ApiErrorId.VIAL_EXPIRED.value)

    # The build-up side effect belongs to a successful verification only.
    check.assert_immunotherapy_vial(
        SETUP.read_vial(api, vial["id"]),
        status=C.VIAL_MIXED,
        verified_by_user_id=None,
    )
    check.assert_patient(
        SETUP.read_patient(api, patient["id"]),
        immunotherapy_status=C.IMMUNO_STATUS_NONE,
    )


def test_the_beyond_use_discard_writes_the_whole_remaining_volume_off_to_waste(api):
    """PRD 3.5: "The discard moves the whole of `volume_ml_remaining` into `volume_ml_wasted`
    and sets `volume_ml_remaining` to 0.00, so a vial of 5.00 mL that had dispensed 4.70 mL
    before a contamination discard ends with 0.30 mL wasted, 0.00 remaining, and the identity
    still closing."

    Design: Corner/errors/vial_label_mismatch_then_expiry_blocks_verification
    """
    # The same never-verified vial, still holding its whole five millilitres.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRK-2999",
        patient_mrn=C.mrn(10246),
        policy_overrides={"payer_name": "Label Health"},
        patient_overrides={
            "full_name": "Ludvig Aaltonen",
            "date_of_birth": "1957-01-15",
        },
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_ALLERGEN_CONCENTRATE,
        lot_no=C.lot_number(1029),
        quantity_received=4,
        expires_at="2027-06-01T00:00:00Z",
    )
    vial = SETUP.mix_vial(
        api,
        registered["patient"],
        lot["id"],
        dilution_code=C.DILUTION_BLUE,
        expires_at="2026-08-15T00:00:00Z",
        headers=USERS.NURSE_1,
    )
    check.assert_volume_ml(vial["volume_ml_remaining"], 5.00)

    # Once the clock reaches the beyond-use instant the only move left is the discard.
    SETUP.set_clock(api, "2026-08-15T00:00:00Z")
    discarded = check.validate_unpaginated(
        api.discard_immunotherapy_vial(
            vial["id"],
            F.vial_discard_payload(discard_reason=C.DISCARD_REASON_BEYOND_USE_DATE),
            USERS.NURSE_2,
        )
    )
    check.assert_immunotherapy_vial(
        discarded,
        status=C.VIAL_DISCARDED,
        discard_reason=C.DISCARD_REASON_BEYOND_USE_DATE,
    )
    check.assert_volume_ml(discarded["volume_ml_wasted"], 5.00)
    check.assert_volume_ml(discarded["volume_ml_remaining"], 0.00)
    check.assert_volume_ml(discarded["volume_ml_dispensed_total"], 0.00)


def test_a_second_discard_on_an_already_discarded_vial_is_refused(api):
    """PRD 3.5: "A vial already `EXHAUSTED` or `DISCARDED` is refused with
    `ERR_VIAL_STATE_INVALID`."

    Design: Corner/errors/state_gates_reject_repeat_actions_on_vial_booking_and_block
    """
    # One adult chart, one concentrate lot and one freshly compounded vial.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRL-2999",
        patient_mrn=C.mrn(10247),
        policy_overrides={"payer_name": "Repeat Health"},
        patient_overrides={
            "full_name": "Nadia Bertrand",
            "date_of_birth": "1965-02-16",
        },
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_ALLERGEN_CONCENTRATE,
        lot_no=C.lot_number(1030),
        quantity_received=4,
        expires_at="2027-06-01T00:00:00Z",
    )
    vial = SETUP.mix_vial(
        api,
        registered["patient"],
        lot["id"],
        dilution_code=C.DILUTION_BLUE,
        expires_at="2026-12-01T00:00:00Z",
        headers=USERS.NURSE_1,
    )

    # The nurse discards it for contamination, writing all five millilitres off.
    discarded = SETUP.discard_vial(
        api, vial["id"], C.DISCARD_REASON_CONTAMINATION, USERS.NURSE_1
    )
    check.assert_immunotherapy_vial(
        discarded,
        status=C.VIAL_DISCARDED,
        discard_reason=C.DISCARD_REASON_CONTAMINATION,
    )
    check.assert_volume_ml(discarded["volume_ml_wasted"], 5.00)

    # The same discard is replayed against the terminal vial.
    response = api.discard_immunotherapy_vial(
        vial["id"],
        F.vial_discard_payload(discard_reason=C.DISCARD_REASON_CONTAMINATION),
        USERS.NURSE_1,
    )
    validate_error(response, ApiErrorId.VIAL_STATE_INVALID.value)

    # The waste was not written off twice.
    settled = SETUP.read_vial(api, vial["id"])
    check.assert_immunotherapy_vial(
        settled,
        status=C.VIAL_DISCARDED,
        discard_reason=C.DISCARD_REASON_CONTAMINATION,
    )
    check.assert_volume_ml(settled["volume_ml_wasted"], 5.00)
    check.assert_volume_ml(settled["volume_ml_remaining"], 0.00)
    check.assert_volume_ml(settled["volume_ml_dispensed_total"], 0.00)


def test_a_second_cancellation_on_an_already_cancelled_booking_is_refused(api):
    """PRD 3.9: "The booking must be `SCHEDULED`, or the cancellation is refused with
    `ERR_BOOKING_STATE_INVALID` — an `IN_PROGRESS` procedure cannot be cancelled, only
    completed."

    Design: Corner/errors/state_gates_reject_repeat_actions_on_vial_booking_and_block
    """
    # One adult chart with one office tonsillectomy on the books.
    registered = SETUP.policy_with_patient(
        api,
        plan_code="ERRL-2999",
        patient_mrn=C.mrn(10247),
        policy_overrides={"payer_name": "Repeat Health"},
        patient_overrides={
            "full_name": "Nadia Bertrand",
            "date_of_birth": "1965-02-16",
        },
    )
    booking = SETUP.create_booking(
        api,
        registered["patient"]["id"],
        "2026-08-04T09:00:00Z",
        "2026-08-04T10:00:00Z",
        physician_user_id=C.USER_ENT_1,
        procedure_type=C.PROCEDURE_TONSILLECTOMY,
        venue=C.VENUE_IN_OFFICE_SUITE,
    )
    check.assert_procedure_booking(
        booking,
        status=C.BOOKING_SCHEDULED,
        overnight_observation_required=False,
        cancel_reason=None,
    )

    # The practice administrator cancels it at the patient's request.
    cancelled = SETUP.cancel_booking(
        api, booking["id"], C.CANCEL_REASON_PATIENT_REQUEST, USERS.ADMIN_1
    )
    check.assert_procedure_booking(
        cancelled,
        status=C.BOOKING_CANCELLED,
        cancel_reason=C.CANCEL_REASON_PATIENT_REQUEST,
    )

    # The same cancellation is replayed against the terminal booking.
    response = api.cancel_procedure_booking(
        booking["id"],
        F.booking_cancel_payload(cancel_reason=C.CANCEL_REASON_PATIENT_REQUEST),
        USERS.ADMIN_1,
    )
    validate_error(response, ApiErrorId.BOOKING_STATE_INVALID.value)

    # The stored reason is exactly the one the first cancellation wrote.
    check.assert_procedure_booking(
        SETUP.read_booking(api, booking["id"]),
        status=C.BOOKING_CANCELLED,
        cancel_reason=C.CANCEL_REASON_PATIENT_REQUEST,
    )


def test_a_second_close_on_an_already_closed_block_is_refused(api):
    """PRD 3.9: "The block must be `OPEN` or `FULL` — the two arcs `OPEN → CLOSED` and
    `FULL → CLOSED` have identical effects — or the close is refused with
    `ERR_BLOCK_STATE_INVALID`."

    Design: Corner/errors/state_gates_reject_repeat_actions_on_vial_booking_and_block
    """
    # A four-hour block is published and nothing is ever booked into it.
    block = SETUP.publish_block(
        api,
        "2026-08-07T08:00:00Z",
        "2026-08-07T12:00:00Z",
        center_name="Day Surgery East",
    )
    check.assert_surgery_center_block(
        block,
        max_concurrent_cases=2,
        capacity_minutes=480,
        booked_case_count=0,
        booked_minutes=0,
        utilization_bps=0,
        status=C.BLOCK_OPEN,
    )

    # The practice administrator closes it to further bookings.
    closed = SETUP.close_block(api, block["id"], USERS.ADMIN_1)
    check.assert_surgery_center_block(closed, status=C.BLOCK_CLOSED)

    # The close is replayed against the terminal block.
    response = api.close_surgery_center_block(block["id"], USERS.ADMIN_1)
    validate_error(response, ApiErrorId.BLOCK_STATE_INVALID.value)

    # Closing an empty block leaves its aggregates at zero.
    check.assert_surgery_center_block(
        SETUP.read_block(api, block["id"]),
        status=C.BLOCK_CLOSED,
        booked_case_count=0,
        booked_minutes=0,
        utilization_bps=0,
        capacity_minutes=480,
    )
