"""Derived-figure semantics: observation sizing, panel billing, the anaphylaxis
risk score, candidacy management-day merging, block utilization and trial refunds.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def test_serum_conversion_zeroes_the_observation_window(api):
    """PRD 3.2: "If the context is `SERUM_IGE`, the answer is exactly 0 and nothing
    further applies — in particular, the plan's `observation_floor_minutes` is
    **bypassed entirely** on that path, which is the one hard exception to the
    floor in this whole specification."

    Design: Corner/calculations/serum_ige_conversion_bypasses_observation_floor
    """
    # A plan with a two-hour observation floor that nevertheless covers serum assays.
    policy = SETUP.create_policy(
        api,
        plan_code="CALA-2999",
        payer_name="Serum Health",
        observation_floor_minutes=120,
        covered_pct_bps=5000,
        allergy_serum_covered=True,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10211),
        full_name="Ada Kwan",
        date_of_birth="1979-11-02",
        epinephrine_on_file=True,
    )
    check.assert_patient(patient, risk_score=5, sensitized_antigen_count=0)

    # A twenty-four antigen food panel is ordered on the skin arm and never administered.
    order = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_FOOD_24, method=C.METHOD_SKIN_PRICK
    )
    check.assert_allergy_test_order(
        order, status=C.ORDER_ORDERED, antigen_count=24, method=C.METHOD_SKIN_PRICK
    )

    # The nurse moves the order onto the serum arm.
    converted = check.validate_unpaginated(
        api.convert_allergy_test_order_to_serum(order["id"], USERS.NURSE_1)
    )
    check.assert_allergy_test_order(
        converted,
        status=C.ORDER_SERUM_PENDING,
        method=C.METHOD_SERUM_IGE,
        antigen_count=24,
        billed_units=6,
        observation_required_minutes=0,
        administered_at=None,
        administered_by_user_id=None,
        practice_charge_cents=0,
        patient_responsibility_cents=0,
    )

    # The reading is accepted with no waiting period at all: the clock never moved.
    read = check.validate_unpaginated(
        api.record_allergy_test_reading(
            order["id"], F.allergy_reading_payload(6), USERS.NURSE_1
        )
    )
    check.assert_allergy_test_order(
        read,
        status=C.ORDER_READ,
        method=C.METHOD_SERUM_IGE,
        antigen_count=24,
        billed_units=6,
        positive_antigen_count=6,
        practice_charge_cents=18372,
        patient_responsibility_cents=9186,
        abort_reason=None,
    )

    # The chart picks up the six positives and nothing else.
    refreshed = SETUP.read_patient(api, patient["id"])
    check.assert_patient(
        refreshed,
        sensitized_antigen_count=6,
        risk_score=11,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )


def test_sensitized_count_ignores_orders_that_have_not_been_read(api):
    """PRD 3.3: "The chart's `sensitized_antigen_count` is recomputed as the sum of
    `positive_antigen_count` across all of that patient's orders in status `READ`,
    capped at 20; the `risk_score` is recomputed under the patient's current
    `risk_score_variant`; and `supervision_tier` is re-derived from the new score."

    Design: Corner/calculations/sensitized_antigen_count_only_counts_read_orders
    """
    # A default plan: eighty percent coverage and a twenty-minute observation floor.
    policy = SETUP.create_policy(api, plan_code="CALB-2999", payer_name="Filter Health")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10212),
        full_name="Bo Ferrer",
        date_of_birth="1981-07-19",
        epinephrine_on_file=True,
    )

    # Three panels are ordered; only the first is administered at the opening clock.
    order_a = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_MOLD_12, method=C.METHOD_SKIN_PRICK
    )
    order_b = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_VENOM_5, method=C.METHOD_SKIN_PRICK
    )
    order_c = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_ENV_36, method=C.METHOD_SERUM_IGE
    )
    SETUP.administer_order(api, order_a["id"])

    # Half an hour later the first panel is read and the second is administered.
    SETUP.set_clock(api, "2026-08-01T00:30:00Z")
    read_a = SETUP.record_reading(api, order_a["id"], 4)
    check.assert_allergy_test_order(
        read_a,
        status=C.ORDER_READ,
        billed_units=12,
        practice_charge_cents=21300,
        patient_responsibility_cents=4260,
    )
    SETUP.administer_order(api, order_b["id"])

    # Only the READ order feeds the chart: the ADMINISTERED and ORDERED ones do not.
    midway = SETUP.read_patient(api, patient["id"])
    check.assert_patient(midway, sensitized_antigen_count=4, risk_score=9)

    # A further half hour lets the second panel be read as well.
    SETUP.set_clock(api, "2026-08-01T01:00:00Z")
    read_b = SETUP.record_reading(api, order_b["id"], 3)
    check.assert_allergy_test_order(
        read_b,
        status=C.ORDER_READ,
        billed_units=5,
        practice_charge_cents=8875,
        patient_responsibility_cents=1775,
    )

    # The chart now sums both READ orders and still ignores the untouched one.
    final = SETUP.read_patient(api, patient["id"])
    check.assert_patient(
        final,
        sensitized_antigen_count=7,
        risk_score=12,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )
    untouched = SETUP.read_order(api, order_c["id"])
    check.assert_allergy_test_order(
        untouched,
        status=C.ORDER_ORDERED,
        positive_antigen_count=0,
        practice_charge_cents=0,
        patient_responsibility_cents=0,
    )


def test_a_fresh_grade_two_reaction_lifts_supervision_to_physician_present(api):
    """PRD 3.1: "A patient's `supervision_tier` is `STANDARD` while `risk_score` is 59
    or lower, and becomes `PHYSICIAN_PRESENT` as soon as `risk_score` reaches 60 or
    more."

    Design: Corner/calculations/risk_decay_factor_at_sixty_one_days_with_fresh_event
    """
    # One prior systemic reaction on file puts the base at 5 + 15 == 20.
    policy = SETUP.create_policy(api, plan_code="CALC-2999", payer_name="Decay Health")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10213),
        full_name="Cyd Halim",
        date_of_birth="1980-02-02",
        epinephrine_on_file=True,
        prior_systemic_reaction_count=1,
    )
    check.assert_patient(
        patient,
        risk_score=20,
        sensitized_antigen_count=0,
        risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )

    # A panel is administered at the opening clock and a grade-2 reaction follows.
    order_a = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_MOLD_12, method=C.METHOD_SKIN_PRICK
    )
    SETUP.administer_order(api, order_a["id"])
    event_one = SETUP.record_reaction(
        api, 2, 12, order_id=order_a["id"], local_wheal_mm=22.0, epinephrine_given=True
    )
    check.assert_reaction_event(event_one, systemic_grade=2, onset_minutes=12)
    check.assert_instant_equals(event_one["occurred_at"], "2026-08-01T00:00:00Z")

    # The panel is aborted unbilled and the chart flips to the post-reaction variant.
    aborted = SETUP.read_order(api, order_a["id"])
    check.assert_allergy_test_order(
        aborted,
        status=C.ORDER_ABORTED,
        abort_reason=C.ABORT_REASON_SYSTEMIC_REACTION,
        worst_systemic_grade=2,
        practice_charge_cents=0,
        patient_responsibility_cents=0,
    )

    # Base 20 plus a fresh grade-2 term of forty points reaches exactly the tier line.
    escalated = SETUP.read_patient(api, patient["id"])
    check.assert_patient(
        escalated,
        risk_score=60,
        risk_score_variant=C.RISK_VARIANT_POST_REACTION,
        supervision_tier=C.SUPERVISION_TIER_PHYSICIAN_PRESENT,
    )


def test_a_sixty_one_day_old_reaction_decays_to_six_tenths_of_its_weight(api):
    """PRD 3.1: "The decay factor is read from the whole number of days between the
    event's `occurred_at` and the current clock instant, taken downward: 1.00 when
    that age is 30 days or fewer; 0.60 when it is 31 through 90 days inclusive; 0.30
    when it is 91 through 180 days inclusive; and 0.00 beyond 180 days, at which
    point the event stops contributing entirely."

    Design: Corner/calculations/risk_decay_factor_at_sixty_one_days_with_fresh_event
    """
    # The same chart: base 20, and a grade-2 reaction recorded at the opening clock.
    policy = SETUP.create_policy(api, plan_code="CALC-2999", payer_name="Decay Health")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10213),
        full_name="Cyd Halim",
        date_of_birth="1980-02-02",
        epinephrine_on_file=True,
        prior_systemic_reaction_count=1,
    )
    order_a = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_MOLD_12, method=C.METHOD_SKIN_PRICK
    )
    SETUP.administer_order(api, order_a["id"])
    SETUP.record_reaction(
        api, 2, 12, order_id=order_a["id"], local_wheal_mm=22.0, epinephrine_given=True
    )

    # Sixty-one days later a second panel is administered and reacts at grade one.
    SETUP.set_clock(api, "2026-10-01T00:00:00Z")
    order_b = SETUP.create_order(
        api, patient["id"], panel_code=C.PANEL_VENOM_5, method=C.METHOD_SKIN_PRICK
    )
    SETUP.administer_order(api, order_b["id"])
    event_two = SETUP.record_reaction(
        api, 1, 20, order_id=order_b["id"], local_wheal_mm=9.0, epinephrine_given=False
    )
    check.assert_instant_equals(event_two["occurred_at"], "2026-10-01T00:00:00Z")

    # A grade-one event documents itself without aborting its parent panel.
    still_running = SETUP.read_order(api, order_b["id"])
    check.assert_allergy_test_order(
        still_running, status=C.ORDER_ADMINISTERED, worst_systemic_grade=1, abort_reason=None
    )

    # A chart revision recomputes the score under the current post-reaction variant.
    revised = SETUP.patch_patient(
        api, patient["id"], antihistamine_last_dose_at="2026-09-01T00:00:00Z"
    )
    check.assert_patient(
        revised,
        risk_score=64,
        risk_score_variant=C.RISK_VARIANT_POST_REACTION,
        supervision_tier=C.SUPERVISION_TIER_PHYSICIAN_PRESENT,
    )


def test_adjacent_therapy_courses_merge_while_a_six_day_gap_does_not(api):
    """PRD 3.6: "Adjacency counts as contiguous — a course ending on the 14th and a
    course starting on the 15th leave a gap of zero days and merge into one span."

    Design: Corner/calculations/candidacy_merges_adjacent_and_preserves_disjoint_courses
    """
    # A strict plan demanding twenty-eight management days and three criteria.
    policy = SETUP.create_policy(
        api,
        plan_code="CALD-2999",
        payer_name="Merge Health",
        requires_prior_auth=True,
        min_medical_management_days=28,
        min_documented_criteria=3,
        requires_ct_within_months=12,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10214),
        full_name="Dee Marchetti",
        date_of_birth="1975-04-09",
        epinephrine_on_file=True,
    )

    # Two single-sinus cases on the same chart, so each plans exactly one device.
    case_a = SETUP.create_case(
        api, patient["id"], laterality=C.LATERALITY_LEFT, sinuses=[C.SINUS_MAXILLARY]
    )
    case_b = SETUP.create_case(
        api, patient["id"], laterality=C.LATERALITY_LEFT, sinuses=[C.SINUS_MAXILLARY]
    )
    check.assert_sinuplasty_case(case_a, planned_device_count=1, status=C.CASE_DRAFT)
    check.assert_sinuplasty_case(case_b, planned_device_count=1, status=C.CASE_DRAFT)

    # The first case documents two fourteen-day courses that touch end to start.
    asserted_criteria = [
        C.CRITERION_CT_OPACIFICATION,
        C.CRITERION_FAILED_INCS,
        C.CRITERION_FAILED_ABX,
    ]
    documented_a = SETUP.document_case(
        api,
        case_a["id"],
        therapies=[
            F.therapy_course(C.THERAPY_INCS, "2026-06-01", "2026-06-14"),
            F.therapy_course(C.THERAPY_ABX, "2026-06-15", "2026-06-28"),
        ],
        criteria=asserted_criteria,
        ct_study_date="2026-05-01",
    )
    check.assert_sinuplasty_case(
        documented_a,
        status=C.CASE_DOCUMENTED,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
        contiguous_management_days=28,
        cumulative_management_days=28,
        criteria_met_count=3,
        evaluation_variant=C.EVAL_VARIANT_POLICY_STRICT,
    )

    # The second case documents the same two spans six days apart.
    documented_b = SETUP.document_case(
        api,
        case_b["id"],
        therapies=[
            F.therapy_course(C.THERAPY_INCS, "2026-06-01", "2026-06-14"),
            F.therapy_course(C.THERAPY_ABX, "2026-06-21", "2026-07-04"),
        ],
        criteria=asserted_criteria,
        ct_study_date="2026-05-01",
    )
    check.assert_sinuplasty_case(
        documented_b,
        status=C.CASE_DOCUMENTED,
        candidacy_status=C.CANDIDACY_INELIGIBLE,
        contiguous_management_days=14,
        cumulative_management_days=28,
        criteria_met_count=3,
        evaluation_variant=C.EVAL_VARIANT_POLICY_STRICT,
    )

    # The merged case clears the threshold on its single twenty-eight-day span.
    evaluation_a = check.validate_unpaginated(
        api.get_candidacy_evaluation(case_a["id"], USERS.LIAISON_1)
    )
    check.assert_candidacy_evaluation(
        evaluation_a,
        evaluation_variant=C.EVAL_VARIANT_POLICY_STRICT,
        criteria_met_count=3,
        contiguous_management_days=28,
        cumulative_management_days=28,
        management_days_metric=28,
        min_documented_criteria_required=3,
        min_medical_management_days_required=28,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
    )
    assert sorted(evaluation_a["admissible_criteria_codes"]) == sorted(asserted_criteria)

    # The gapped case carries an identical cumulative total and still falls short.
    evaluation_b = check.validate_unpaginated(
        api.get_candidacy_evaluation(case_b["id"], USERS.LIAISON_1)
    )
    check.assert_candidacy_evaluation(
        evaluation_b,
        evaluation_variant=C.EVAL_VARIANT_POLICY_STRICT,
        criteria_met_count=3,
        contiguous_management_days=14,
        cumulative_management_days=28,
        management_days_metric=14,
        min_documented_criteria_required=3,
        min_medical_management_days_required=28,
        candidacy_status=C.CANDIDACY_INELIGIBLE,
    )
    assert sorted(evaluation_b["admissible_criteria_codes"]) == sorted(asserted_criteria)


def test_panel_pricing_tier_moves_only_with_the_antigen_count(api):
    """PRD 3.3: "Third select the volume tier factor from the antigen count: a factor
    of exactly 1.0000 when the antigen count is 12 or fewer, exactly 0.9250 when it
    is 13 through 30 inclusive, and exactly 0.8500 when it is 31 or more."

    Design: Corner/calculations/allergy_billing_tier_boundaries_across_four_panels
    """
    # A default plan: eighty percent coverage against a twenty-minute floor.
    policy = SETUP.create_policy(api, plan_code="CALE-2999", payer_name="Tier Health")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10215),
        full_name="Eli Vasquez",
        date_of_birth="1969-12-01",
        epinephrine_on_file=True,
    )

    # Four skin-prick panels, one per panel code, all administered at the same instant.
    orders = {}
    for panel in (C.PANEL_VENOM_5, C.PANEL_MOLD_12, C.PANEL_FOOD_24, C.PANEL_ENV_36):
        order = SETUP.create_order(
            api, patient["id"], panel_code=panel, method=C.METHOD_SKIN_PRICK
        )
        administered = SETUP.administer_order(api, order["id"])
        check.assert_allergy_test_order(
            administered,
            status=C.ORDER_ADMINISTERED,
            observation_required_minutes=C.OBSERVATION_BASE_SKIN_PRICK,
        )
        orders[panel] = order

    # Thirty minutes later every window has elapsed and all four may be read.
    SETUP.set_clock(api, "2026-08-01T00:30:00Z")

    # Five antigens: the small tier applies its factor of one and nothing rounds.
    venom = SETUP.record_reading(api, orders[C.PANEL_VENOM_5]["id"], 2)
    check.assert_allergy_test_order(
        venom,
        status=C.ORDER_READ,
        antigen_count=5,
        billed_units=5,
        practice_charge_cents=8875,
        patient_responsibility_cents=1775,
    )

    # Twelve antigens sit at the inclusive top of the same tier.
    mold = SETUP.record_reading(api, orders[C.PANEL_MOLD_12]["id"], 3)
    check.assert_allergy_test_order(
        mold,
        status=C.ORDER_READ,
        antigen_count=12,
        billed_units=12,
        practice_charge_cents=21300,
        patient_responsibility_cents=4260,
    )

    # Twenty-four antigens take the middle tier at a per-unit gross of 1642 cents.
    food = SETUP.record_reading(api, orders[C.PANEL_FOOD_24]["id"], 4)
    check.assert_allergy_test_order(
        food,
        status=C.ORDER_READ,
        antigen_count=24,
        billed_units=24,
        practice_charge_cents=39408,
        patient_responsibility_cents=7872,
    )

    # Thirty-six antigens take the large tier at a per-unit gross of 1509 cents.
    env = SETUP.record_reading(api, orders[C.PANEL_ENV_36]["id"], 5)
    check.assert_allergy_test_order(
        env,
        status=C.ORDER_READ,
        antigen_count=36,
        billed_units=36,
        practice_charge_cents=54324,
        patient_responsibility_cents=10872,
    )

    # Fourteen positives across the four panels leave the chart short of escalation.
    refreshed = SETUP.read_patient(api, patient["id"])
    check.assert_patient(
        refreshed,
        sensitized_antigen_count=14,
        risk_score=19,
        supervision_tier=C.SUPERVISION_TIER_STANDARD,
    )


def test_cancelling_a_booking_returns_a_full_block_to_open(api):
    """PRD 3.9: "The posture follows the number: a block flips `OPEN → FULL` the moment
    `utilization_bps` reaches 10000 or more, and flips `FULL → OPEN` again the moment
    a cancellation brings it back below 10000."

    Design: Corner/calculations/block_utilization_returns_to_open_on_cancel
    """
    # Three adult charts, so no pediatric venue or overnight rule participates.
    policy = SETUP.create_policy(api, plan_code="CALF-2999", payer_name="Aggregate Health")
    patient_one = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10216),
        full_name="Fay Osei",
        date_of_birth="1991-01-15",
        epinephrine_on_file=True,
    )
    patient_two = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10217),
        full_name="Gil Osei",
        date_of_birth="1992-02-16",
        epinephrine_on_file=True,
    )
    patient_three = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10218),
        full_name="Hana Osei",
        date_of_birth="1993-03-17",
        epinephrine_on_file=True,
    )

    # A four-hour block with two rooms opens empty at 480 capacity minutes.
    block = SETUP.publish_block(
        api,
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        max_concurrent_cases=2,
        center_name="Eastside Surgery Center",
    )
    check.assert_surgery_center_block(
        block,
        capacity_minutes=480,
        booked_minutes=0,
        utilization_bps=0,
        booked_case_count=0,
        status=C.BLOCK_OPEN,
    )

    # Two whole-window tube cases fill the block to exactly the ceiling.
    first = SETUP.create_booking(
        api,
        patient_one["id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        physician_user_id=C.USER_ENT_1,
        procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
        venue=C.VENUE_SURGERY_CENTER,
        surgery_center_block_id=block["id"],
    )
    second = SETUP.create_booking(
        api,
        patient_two["id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        physician_user_id=C.USER_ENT_1,
        procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
        venue=C.VENUE_SURGERY_CENTER,
        surgery_center_block_id=block["id"],
    )
    check.assert_procedure_booking(first, duration_minutes=240, status=C.BOOKING_SCHEDULED)
    check.assert_procedure_booking(second, duration_minutes=240, status=C.BOOKING_SCHEDULED)
    filled = SETUP.read_block(api, block["id"])
    check.assert_surgery_center_block(
        filled,
        booked_minutes=480,
        utilization_bps=10000,
        booked_case_count=2,
        status=C.BLOCK_FULL,
    )

    # Cancelling one case takes it out of the aggregate entirely.
    cancelled = SETUP.cancel_booking(
        api, second["id"], C.CANCEL_REASON_PATIENT_REQUEST
    )
    check.assert_procedure_booking(
        cancelled,
        status=C.BOOKING_CANCELLED,
        cancel_reason=C.CANCEL_REASON_PATIENT_REQUEST,
    )
    reopened = SETUP.read_block(api, block["id"])
    check.assert_surgery_center_block(
        reopened,
        booked_minutes=240,
        utilization_bps=5000,
        booked_case_count=1,
        status=C.BLOCK_OPEN,
    )

    # The reopened block accepts a fresh two-hour case.
    third = validate_success(
        api.create_procedure_booking(
            SETUP.booking_payload(
                patient_three["id"],
                "2026-08-10T08:00:00Z",
                "2026-08-10T10:00:00Z",
                physician_user_id=C.USER_ENT_1,
                procedure_type=C.PROCEDURE_TYMPANOSTOMY_TUBES,
                venue=C.VENUE_SURGERY_CENTER,
                surgery_center_block_id=block["id"],
            ),
            USERS.ADMIN_1,
        ),
        201,
    )
    check.assert_procedure_booking(third, duration_minutes=120, status=C.BOOKING_SCHEDULED)
    topped_up = SETUP.read_block(api, block["id"])
    check.assert_surgery_center_block(
        topped_up,
        booked_minutes=360,
        utilization_bps=7500,
        booked_case_count=2,
        status=C.BLOCK_OPEN,
    )


def test_restock_floor_overrides_the_smaller_computed_percentage(api):
    """PRD 3.7: "The `restock_fee_cents` is the larger of the plan's
    `restock_fee_floor_cents` and the `price_cents` multiplied by the plan's
    `restock_fee_bps` divided by ten thousand, that quotient rounded half up to a
    whole number of cents."

    Design: Corner/calculations/refund_restock_floor_dominates_computed_percentage
    """
    # A sixty-day trial with a fifteen-percent restock fee floored at 12500 cents.
    policy = SETUP.create_policy(
        api,
        plan_code="CALG-2999",
        payer_name="Floor Health",
        device_trial_days=60,
        restock_fee_bps=1500,
        restock_fee_floor_cents=12500,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10219),
        full_name="Ida Brandt",
        date_of_birth="1958-06-06",
        epinephrine_on_file=True,
    )

    # An audiometry at 45 dB HL is interpreted as calling for a hearing aid.
    study = SETUP.create_study(api, patient["id"], study_type=C.STUDY_AUDIOMETRY)
    SETUP.record_audiometry_results(api, study["id"], 45.0, 72.0)
    interpreted = SETUP.interpret_study(api, study["id"])
    check.assert_diagnostic_study(
        interpreted,
        status=C.STUDY_INTERPRETED,
        recommendation=C.RECOMMENDATION_HEARING_AID,
    )

    # A 60000-cent unit is dispensed from a hearing-aid lot at the opening clock.
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1014),
        quantity_received=5,
        expires_at="2028-01-01T00:00:00Z",
    )
    dispense = SETUP.create_dispense(
        api,
        study["id"],
        lot["id"],
        device_type=C.DEVICE_TYPE_HEARING_AID,
        serial=C.device_serial("HA", 400001),
        price_cents=60000,
        ear=C.EAR_LEFT,
    )
    check.assert_device_dispense(
        dispense, fit_status=C.FIT_FITTED, billing_status=C.BILLING_INVOICED
    )
    check.assert_instant_equals(dispense["trial_end_at"], "2026-09-30T00:00:00Z")

    # Thirty-nine whole days later the patient hands the unit back, still in trial.
    SETUP.set_clock(api, "2026-09-09T00:00:00Z")
    returned = check.validate_unpaginated(
        api.return_device_dispense(
            dispense["id"],
            F.trial_return_payload(return_reason=C.RETURN_REASON_DISSATISFIED),
            USERS.AUD_1,
        )
    )
    check.assert_device_dispense(
        returned,
        refund_variant=C.REFUND_VARIANT_IN_TRIAL,
        days_used=40,
        restock_fee_cents=12500,
        refund_cents=33500,
        fit_status=C.FIT_RETURNED,
        billing_status=C.BILLING_REFUND_PENDING,
    )
