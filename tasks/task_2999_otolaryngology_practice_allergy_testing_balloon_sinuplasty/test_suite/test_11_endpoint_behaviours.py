"""Endpoint behaviour: plan amendment, the candidacy projection, closing out a kept
device and the coherence limbs that link a dispense to its study and its lot.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS


def test_every_plan_amendment_increments_the_plan_version(api):
    """PRD 3.1: "A `PracticeAdmin` may amend any of the thirteen optional terms —
    `plan_code` and `payer_name` are not amendable and are not accepted on an
    amendment — and every amendment increments the plan's `version` by one."

    Design: Corner/endpoints/payer_policy_patch_updates_and_bumps_version
    """
    # A plan created with one non-default term, everything else left at its default.
    policy = SETUP.create_policy(
        api,
        plan_code="ENDA-2999",
        payer_name="CRUD Health",
        covered_pct_bps=9000,
    )
    check.assert_payer_policy(policy, covered_pct_bps=9000, version=1)
    created_at = policy["created_at"]

    # Two terms are amended in one call, which carries the plan to version two.
    amended = SETUP.patch_policy(
        api, policy["id"], min_documented_criteria=5, appliance_covered=False
    )
    check.assert_payer_policy(
        amended, min_documented_criteria=5, appliance_covered=False, version=2
    )

    # A read by a second administrator echoes the amendment and bumps nothing.
    echoed = check.validate_unpaginated(
        api.get_payer_policy(policy["id"], USERS.ADMIN_2)
    )
    check.assert_payer_policy(
        echoed,
        plan_code="ENDA-2999",
        payer_name="CRUD Health",
        min_documented_criteria=5,
        appliance_covered=False,
        covered_pct_bps=9000,
        requires_prior_auth=True,
        min_medical_management_days=28,
        requires_ct_within_months=12,
        max_balloon_devices=2,
        allergy_serum_covered=True,
        observation_floor_minutes=20,
        device_trial_days=30,
        restock_fee_bps=1500,
        restock_fee_floor_cents=12500,
        auth_validity_days=90,
        version=2,
    )

    # Resending the identical pair of values is still a write, so the version moves on.
    reamended = SETUP.patch_policy(
        api, policy["id"], min_documented_criteria=5, appliance_covered=False
    )
    check.assert_payer_policy(
        reamended, min_documented_criteria=5, appliance_covered=False, version=3
    )

    # The creation instant is the one stamp two amendments never touch.
    check.assert_instant_equals(
        SETUP.read_policy(api, policy["id"])["created_at"], created_at
    )


def test_the_candidacy_projection_is_read_by_three_roles_and_mutates_nothing(api):
    """PRD 3.6: "A `PracticeAdmin`, an `Otolaryngologist` or a `PayerLiaison` may
    recompute and read the determination without mutating anything."

    Design: Corner/endpoints/candidacy_evaluation_read_matches_stored_metrics
    """
    # A self-pay plan, so the case is evaluated under the broad variant.
    policy = SETUP.create_policy(
        api,
        plan_code="ENDB-2999",
        payer_name="Broad Read Health",
        requires_prior_auth=False,
        min_documented_criteria=2,
        min_medical_management_days=20,
        requires_ct_within_months=6,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10231),
        full_name="Otto Ferrand",
        date_of_birth="1964-03-03",
        epinephrine_on_file=True,
    )
    case = SETUP.create_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_RIGHT,
        sinuses=[C.SINUS_SPHENOID],
    )
    documented = SETUP.document_case(
        api,
        case["id"],
        therapies=[
            F.therapy_course(C.THERAPY_INCS, "2026-06-01", "2026-06-10"),
            F.therapy_course(C.THERAPY_SALINE, "2026-06-20", "2026-06-30"),
        ],
        criteria=[
            C.CRITERION_CT_OPACIFICATION,
            C.CRITERION_FAILED_ABX,
            C.CRITERION_FAILED_ABX,
        ],
        ct_study_date="2024-01-01",
    )
    documented_version = documented["version"]

    # All three listed roles see the same nine-field projection.
    for headers in (USERS.ADMIN_1, USERS.ENT_2, USERS.LIAISON_1):
        evaluation = check.validate_unpaginated(
            api.get_candidacy_evaluation(case["id"], headers)
        )
        check.assert_candidacy_evaluation(
            evaluation,
            evaluation_variant=C.EVAL_VARIANT_CLINICAL_BROAD,
            criteria_met_count=2,
            candidacy_status=C.CANDIDACY_ELIGIBLE,
        )

    # A role the endpoint does not list is turned away, unlike every other read.
    validate_error(
        api.get_candidacy_evaluation(case["id"], USERS.NURSE_1),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    # Three reads and one rejection later the case row stands exactly where it was.
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case["id"]),
        status=C.CASE_DOCUMENTED,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
        version=documented_version,
    )


def test_the_broad_variant_reads_the_cumulative_management_days(api):
    """PRD 3.6: "Under **`CLINICAL_BROAD`**, which governs whenever the plan's
    `requires_prior_auth` is false, the verdict consults `cumulative_management_days` —
    every documented course adds up regardless of the gaps between them."

    Design: Corner/endpoints/candidacy_evaluation_read_matches_stored_metrics
    """
    # The same self-pay plan and the same two courses nine days apart.
    policy = SETUP.create_policy(
        api,
        plan_code="ENDB-2999",
        payer_name="Broad Read Health",
        requires_prior_auth=False,
        min_documented_criteria=2,
        min_medical_management_days=20,
        requires_ct_within_months=6,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10231),
        full_name="Otto Ferrand",
        date_of_birth="1964-03-03",
        epinephrine_on_file=True,
    )
    case = SETUP.create_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_RIGHT,
        sinuses=[C.SINUS_SPHENOID],
    )
    documented = SETUP.document_case(
        api,
        case["id"],
        therapies=[
            F.therapy_course(C.THERAPY_INCS, "2026-06-01", "2026-06-10"),
            F.therapy_course(C.THERAPY_SALINE, "2026-06-20", "2026-06-30"),
        ],
        criteria=[
            C.CRITERION_CT_OPACIFICATION,
            C.CRITERION_FAILED_ABX,
            C.CRITERION_FAILED_ABX,
        ],
        ct_study_date="2024-01-01",
    )

    # The stored row keeps both figures: nothing merged, so the longest span is eleven.
    check.assert_sinuplasty_case(
        documented,
        status=C.CASE_DOCUMENTED,
        planned_device_count=1,
        evaluation_variant=C.EVAL_VARIANT_CLINICAL_BROAD,
        criteria_met_count=2,
        contiguous_management_days=11,
        cumulative_management_days=21,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
    )

    # The projection reconciles with the row and names the figure the variant consults.
    evaluation = check.validate_unpaginated(
        api.get_candidacy_evaluation(case["id"], USERS.LIAISON_1)
    )
    check.assert_candidacy_evaluation(
        evaluation,
        evaluation_variant=C.EVAL_VARIANT_CLINICAL_BROAD,
        criteria_met_count=2,
        contiguous_management_days=11,
        cumulative_management_days=21,
        management_days_metric=21,
        min_documented_criteria_required=2,
        min_medical_management_days_required=20,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
    )

    # The repeated criterion survives once, and the 2024 CT faces no recency test here.
    assert sorted(evaluation["admissible_criteria_codes"]) == sorted(
        [C.CRITERION_CT_OPACIFICATION, C.CRITERION_FAILED_ABX]
    ), "the broad variant admits both asserted codes and deduplicates the repeat"


def test_a_kept_device_cannot_be_closed_out_before_the_trial_ends(api):
    """PRD 3.8: "Here the boundary is inclusive: a finalization at exactly `trial_end_at`
    succeeds, which is the exact complement of the return boundary — at that one instant
    a return is `POST_TRIAL` and a finalization is permitted."

    Design: Corner/endpoints/finalize_before_trial_end_is_rejected
    """
    # A thirty-day trial plan, one interpreted audiometry and one fitted hearing aid.
    policy = SETUP.create_policy(
        api,
        plan_code="ENDC-2999",
        payer_name="Trial Health",
        device_trial_days=30,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10232),
        full_name="Pearl Nakamura",
        date_of_birth="1955-10-10",
        epinephrine_on_file=True,
    )
    study = SETUP.create_study(api, patient["id"], study_type=C.STUDY_AUDIOMETRY)
    SETUP.record_audiometry_results(api, study["id"], 60.0, 58.0)
    interpreted = SETUP.interpret_study(api, study["id"])
    check.assert_diagnostic_study(
        interpreted,
        status=C.STUDY_INTERPRETED,
        recommendation=C.RECOMMENDATION_HEARING_AID,
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1017),
        quantity_received=3,
        expires_at="2028-01-01T00:00:00Z",
    )
    dispense = SETUP.create_dispense(
        api,
        study["id"],
        lot["id"],
        device_type=C.DEVICE_TYPE_HEARING_AID,
        serial=C.device_serial("HA", 400003),
        price_cents=250000,
        ear=C.EAR_BOTH,
    )
    check.assert_device_dispense(
        dispense,
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
        price_cents=250000,
    )
    check.assert_instant_equals(dispense["trial_end_at"], "2026-08-31T00:00:00Z")

    # Halfway through the trial the patient has not yet finished deciding.
    SETUP.set_clock(api, "2026-08-15T00:00:00Z")
    validate_error(
        api.finalize_device_dispense(dispense["id"], USERS.AUD_1),
        ApiErrorId.TRIAL_NOT_COMPLETE.value,
    )
    check.assert_device_dispense(
        SETUP.read_dispense(api, dispense["id"]),
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
    )

    # At exactly the trial's end the close-out is permitted.
    SETUP.set_clock(api, "2026-08-31T00:00:00Z")
    finalized = check.validate_unpaginated(
        api.finalize_device_dispense(dispense["id"], USERS.AUD_1)
    )
    check.assert_device_dispense(
        finalized,
        fit_status=C.FIT_FINALIZED,
        billing_status=C.BILLING_RETAINED,
        restock_fee_cents=0,
        refund_cents=0,
    )

    # A second close-out is answered on the lifecycle rung, not the temporal one.
    validate_error(
        api.finalize_device_dispense(dispense["id"], USERS.AUD_1),
        ApiErrorId.DISPENSE_STATE_INVALID.value,
    )
    check.assert_device_dispense(
        SETUP.read_dispense(api, dispense["id"]),
        fit_status=C.FIT_FINALIZED,
        billing_status=C.BILLING_RETAINED,
        restock_fee_cents=0,
        refund_cents=0,
    )


def test_a_dispense_must_draw_from_a_lot_of_its_own_item_type(api):
    """PRD 3.7: "The `device_type` must be the one the study's `recommendation` admits,
    or the dispense is refused with `ERR_DEVICE_TYPE_NOT_RECOMMENDED`; the lot's
    `item_type` must equal the `device_type`, or it is refused with
    `ERR_LOT_ITEM_TYPE_MISMATCH`."

    Design: Corner/endpoints/dispense_lot_item_type_must_match_device_type
    """
    # A plan covering appliances, one sleep study recommending one, and two lots.
    policy = SETUP.create_policy(
        api,
        plan_code="ENDD-2999",
        payer_name="Link Health",
        appliance_covered=True,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10233),
        full_name="Quinn Adeyemi",
        date_of_birth="1974-07-07",
        epinephrine_on_file=True,
    )
    study = SETUP.create_study(api, patient["id"], study_type=C.STUDY_SLEEP_HSAT)
    SETUP.record_sleep_results(api, study["id"], 20.0)
    interpreted = SETUP.interpret_study(api, study["id"])
    check.assert_diagnostic_study(
        interpreted,
        status=C.STUDY_INTERPRETED,
        recommendation=C.RECOMMENDATION_ORAL_APPLIANCE,
        superseded_dispense_count=0,
    )
    study_v = interpreted["version"]
    hearing_lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1018),
        quantity_received=4,
        expires_at="2028-01-01T00:00:00Z",
    )
    appliance_lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_ORAL_APPLIANCE,
        lot_no=C.lot_number(1019),
        quantity_received=4,
        expires_at="2028-01-01T00:00:00Z",
    )

    # The recommended device drawn from the wrong lot violates only the lot limb.
    validate_error(
        api.create_device_dispense(
            F.device_dispense_payload(
                study["id"],
                hearing_lot["id"],
                study_v,
                device_type=C.DEVICE_TYPE_ORAL_APPLIANCE,
                device_serial=C.device_serial("OA", 500001),
                ear=C.EAR_NA,
                price_cents=140000,
            ),
            USERS.AUD_1,
        ),
        ApiErrorId.LOT_ITEM_TYPE_MISMATCH.value,
    )

    # A hearing aid out of a hearing-aid lot violates only the recommendation limb.
    validate_error(
        api.create_device_dispense(
            F.device_dispense_payload(
                study["id"],
                hearing_lot["id"],
                study_v,
                device_type=C.DEVICE_TYPE_HEARING_AID,
                device_serial=C.device_serial("HA", 400004),
                ear=C.EAR_LEFT,
                price_cents=140000,
            ),
            USERS.AUD_1,
        ),
        ApiErrorId.DEVICE_TYPE_NOT_RECOMMENDED.value,
    )

    # Only the matched triple creates the association.
    dispensed = validate_success(
        api.create_device_dispense(
            F.device_dispense_payload(
                study["id"],
                appliance_lot["id"],
                study_v,
                device_type=C.DEVICE_TYPE_ORAL_APPLIANCE,
                device_serial=C.device_serial("OA", 500001),
                ear=C.EAR_NA,
                price_cents=140000,
            ),
            USERS.AUD_1,
        ),
        201,
    )
    check.assert_device_dispense(
        dispensed,
        diagnostic_study_id=study["id"],
        supply_lot_id=appliance_lot["id"],
        device_type=C.DEVICE_TYPE_ORAL_APPLIANCE,
        device_serial=C.device_serial("OA", 500001),
        ear=C.EAR_NA,
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
        adjustment_count=0,
    )

    # The rejected calls moved no units, and only one dispense stands against the study.
    check.assert_supply_lot(
        SETUP.read_lot(api, hearing_lot["id"]),
        quantity_received=4,
        quantity_reserved=0,
        quantity_consumed=0,
    )
    check.assert_supply_lot(
        SETUP.read_lot(api, appliance_lot["id"]), quantity_received=4, quantity_wasted=0
    )
    check.assert_diagnostic_study(
        SETUP.read_study(api, study["id"]), superseded_dispense_count=0
    )
