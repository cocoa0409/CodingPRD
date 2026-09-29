"""Rejection precedence: which rung of the validation ladder answers first when a
single request violates authentication, role, shape, reference and contract rules.
"""

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


def test_a_blank_identity_header_is_rejected_before_the_body_is_read(api):
    """PRD 2.1: "If either header is missing, supplied as an empty string, or supplied
    as whitespace only, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_is_rejected_before_role_and_shape
    """
    # One plan so that payer_policy_id resolves and no 404 can mask the header rules.
    policy = SETUP.create_policy(api, plan_code="VALA-2999", payer_name="Header Health")

    # A well-formed body sent with an empty acting identifier is refused outright.
    validate_error(
        api.create_patient(
            F.patient_payload(
                policy["id"],
                mrn=C.mrn(10221),
                full_name="Empty Header",
                date_of_birth="1970-01-01",
            ),
            USERS.headers_with_blank_user_id(C.ROLE_PRACTICE_ADMIN),
        ),
        ApiErrorId.UNAUTHENTICATED.value,
    )

    # A body that is malformed as well still answers on the authentication rung.
    validate_error(
        api.create_patient(
            F.patient_payload(
                policy["id"],
                mrn="not-an-mrn",
                full_name="Both Wrong",
                date_of_birth="1970-01-01",
            ),
            USERS.headers_with_blank_user_id(C.ROLE_PRACTICE_ADMIN),
        ),
        ApiErrorId.UNAUTHENTICATED.value,
    )

    # Neither rejected call left a chart behind.
    rows, meta = validate_paginated(
        api.list_patients(USERS.ADMIN_1, params={"payer_policy_id": policy["id"]})
    )
    assert rows == [], "a rejected registration must not create a patient row"
    check.assert_pagination_meta(
        meta, limit=C.DEFAULT_LIMIT, offset=0, total_count=0, has_more=False
    )


def test_the_role_rung_answers_before_the_request_shape_rung(api):
    """PRD 2.1: "A header present and non-blank but naming something that is not one of
    the six declared roles, or naming a role that the target endpoint does not list,
    is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/validations/unauthenticated_request_is_rejected_before_role_and_shape
    """
    # One plan, so every rejection below is about the caller or the body, not a 404.
    policy = SETUP.create_policy(api, plan_code="VALA-2999", payer_name="Header Health")

    # A nurse is authenticated but is not among the roles registering charts.
    validate_error(
        api.create_patient(
            F.patient_payload(
                policy["id"],
                mrn=C.mrn(10221),
                full_name="Wrong Role",
                date_of_birth="1970-01-01",
            ),
            USERS.NURSE_1,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
    )

    # Only an authenticated, permitted caller ever reaches the shape rung.
    validate_error(
        api.create_patient(
            F.patient_payload(
                policy["id"],
                mrn="not-an-mrn",
                full_name="Bad Shape",
                date_of_birth="1970-01-01",
            ),
            USERS.ADMIN_1,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    # No chart was registered by either attempt.
    rows, meta = validate_paginated(
        api.list_patients(USERS.ADMIN_1, params={"payer_policy_id": policy["id"]})
    )
    assert rows == [], "a rejected registration must not create a patient row"
    check.assert_pagination_meta(
        meta, limit=C.DEFAULT_LIMIT, offset=0, total_count=0, has_more=False
    )


def test_body_references_resolve_in_the_order_the_endpoint_declares_them(api):
    """PRD 2.4: "Identifiers supplied inside a request body are resolved after every
    path identifier has resolved, and in the order the endpoint's own input list
    declares them, so a body naming two unknown parents reports the one declared
    first."

    Design: Corner/validations/body_foreign_keys_validated_in_declared_input_order
    """
    # An interpreted audiometry and a hearing-aid lot give the happy path its parents.
    policy = SETUP.create_policy(api, plan_code="VALB-2999", payer_name="Order Health")
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10222),
        full_name="Jo Lindqvist",
        date_of_birth="1962-02-02",
        epinephrine_on_file=True,
    )
    study = SETUP.create_study(api, patient["id"], study_type=C.STUDY_AUDIOMETRY)
    SETUP.record_audiometry_results(api, study["id"], 55.0, 66.0)
    interpreted = SETUP.interpret_study(api, study["id"])
    check.assert_diagnostic_study(
        interpreted,
        status=C.STUDY_INTERPRETED,
        recommendation=C.RECOMMENDATION_HEARING_AID,
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_HEARING_AID,
        lot_no=C.lot_number(1016),
        quantity_received=4,
        expires_at="2028-01-01T00:00:00Z",
    )
    study_v = interpreted["version"]

    # Both references dangle: the dispense reports the one declared first.
    validate_error(
        api.create_device_dispense(
            F.device_dispense_payload(
                NON_EXISTENT_UUID,
                NON_EXISTENT_UUID,
                study_v,
                device_type=C.DEVICE_TYPE_HEARING_AID,
                device_serial=C.device_serial("HA", 400002),
                ear=C.EAR_RIGHT,
                price_cents=180000,
            ),
            USERS.AUD_1,
        ),
        ApiErrorId.DIAGNOSTIC_STUDY_NOT_FOUND.value,
    )

    # Repairing only the study surfaces the second reference.
    validate_error(
        api.create_device_dispense(
            F.device_dispense_payload(
                study["id"],
                NON_EXISTENT_UUID,
                study_v,
                device_type=C.DEVICE_TYPE_HEARING_AID,
                device_serial=C.device_serial("HA", 400002),
                ear=C.EAR_RIGHT,
                price_cents=180000,
            ),
            USERS.AUD_1,
        ),
        ApiErrorId.SUPPLY_LOT_NOT_FOUND.value,
    )

    # With both parents resolved the unit is dispensed and the serial was still free.
    dispensed = validate_success(
        api.create_device_dispense(
            F.device_dispense_payload(
                study["id"],
                lot["id"],
                study_v,
                device_type=C.DEVICE_TYPE_HEARING_AID,
                device_serial=C.device_serial("HA", 400002),
                ear=C.EAR_RIGHT,
                price_cents=180000,
            ),
            USERS.AUD_1,
        ),
        201,
    )
    check.assert_device_dispense(
        dispensed,
        device_serial=C.device_serial("HA", 400002),
        price_cents=180000,
        ear=C.EAR_RIGHT,
        fit_status=C.FIT_FITTED,
        billing_status=C.BILLING_INVOICED,
    )

    # The two rejected calls moved nothing in the lot ledger.
    settled_lot = SETUP.read_lot(api, lot["id"])
    check.assert_supply_lot(settled_lot, quantity_received=4, quantity_wasted=0)


def test_a_plan_amended_after_authorization_blocks_the_balloon_start(api):
    """PRD 3.9: "Finally, a `BALLOON_SINUPLASTY` booking may only start while its case's
    `pinned_policy_version` still equals the plan's current `version`; if the plan was
    amended after authorization the two have diverged and the start is refused with
    `ERR_POLICY_VERSION_DRIFT`."

    Design: Corner/validations/policy_version_drift_blocks_booking_start
    """
    # A strict plan, one chart, a balloon lot and one scope per booking.
    policy = SETUP.create_policy(
        api,
        plan_code="VALC-2999",
        payer_name="Drift Health",
        requires_prior_auth=True,
        min_documented_criteria=3,
        min_medical_management_days=28,
        max_balloon_devices=2,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10223),
        full_name="Marisol Cadwallader",
        date_of_birth="1975-03-03",
        epinephrine_on_file=True,
    )
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_no=C.lot_number(1015),
        quantity_received=5,
        expires_at="2027-12-31T00:00:00Z",
    )
    scope_one = SETUP.register_scope(api, serial=C.scope_serial(1))
    scope_two = SETUP.register_scope(api, serial=C.scope_serial(2))

    # Both cases carry the same twenty-eight day course and reach ELIGIBLE.
    therapies = [F.therapy_course(C.THERAPY_INCS, "2026-06-01", "2026-06-28")]
    criteria = [
        C.CRITERION_CT_OPACIFICATION,
        C.CRITERION_FAILED_INCS,
        C.CRITERION_SNOT22_GE_20,
    ]
    case_ids = []
    for reference in ("PA-77101", "PA-77102"):
        case = SETUP.create_case(
            api,
            patient["id"],
            laterality=C.LATERALITY_LEFT,
            sinuses=[C.SINUS_MAXILLARY],
        )
        documented = SETUP.document_case(
            api,
            case["id"],
            therapies=therapies,
            criteria=criteria,
            ct_study_date="2026-05-15",
        )
        check.assert_sinuplasty_case(
            documented,
            status=C.CASE_DOCUMENTED,
            criteria_met_count=3,
            contiguous_management_days=28,
            candidacy_status=C.CANDIDACY_ELIGIBLE,
        )
        submitted = SETUP.submit_case(api, case["id"], headers=USERS.LIAISON_1)
        check.assert_sinuplasty_case(
            submitted, status=C.CASE_AUTH_SUBMITTED, pinned_policy_version=1
        )
        authorized = SETUP.decide_case(
            api,
            case["id"],
            C.DECISION_APPROVED,
            reference,
            headers=USERS.LIAISON_2,
        )
        check.assert_sinuplasty_case(
            authorized,
            status=C.CASE_AUTHORIZED,
            payer_reference=reference,
            pinned_policy_version=1,
        )
        case_ids.append(case["id"])

    # Two balloon bookings the same morning, each holding its own scope and one device.
    booking_one = SETUP.create_booking(
        api,
        patient["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        physician_user_id=C.USER_ENT_1,
        procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
        venue=C.VENUE_IN_OFFICE_SUITE,
        sinuplasty_case_id=case_ids[0],
        endoscope_asset_id=scope_one["id"],
        supply_lot_id=lot["id"],
        planned_device_count=1,
    )
    booking_two = SETUP.create_booking(
        api,
        patient["id"],
        "2026-08-05T11:00:00Z",
        "2026-08-05T12:00:00Z",
        physician_user_id=C.USER_ENT_1,
        procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
        venue=C.VENUE_IN_OFFICE_SUITE,
        sinuplasty_case_id=case_ids[1],
        endoscope_asset_id=scope_two["id"],
        supply_lot_id=lot["id"],
        planned_device_count=1,
    )
    check.assert_supply_lot(SETUP.read_lot(api, lot["id"]), quantity_reserved=2)

    # The first booking starts while the pinned version still matches the plan.
    # PRD 3.9: when `requires_physician_presence` is false the optional
    # `attending_physician_user_id` "may be supplied and is simply recorded", so
    # the start supplies it explicitly rather than expecting the server to infer
    # it from the acting identifier.
    started = SETUP.start_booking(
        api,
        booking_one["id"],
        attending_physician_user_id=C.USER_ENT_1,
        headers=USERS.ENT_1,
    )
    check.assert_procedure_booking(
        started,
        status=C.BOOKING_IN_PROGRESS,
        attending_physician_user_id=C.USER_ENT_1,
    )

    # The plan is then amended, which moves the plan's version away from both pins.
    amended = SETUP.patch_policy(api, policy["id"], covered_pct_bps=7000)
    check.assert_payer_policy(amended, covered_pct_bps=7000, version=2)

    # The second booking can no longer start: its case is pinned to the old version.
    validate_error(
        api.start_procedure_booking(
            booking_two["id"], USERS.ENT_1, F.booking_start_payload()
        ),
        ApiErrorId.POLICY_VERSION_DRIFT.value,
    )

    # Nothing moved: the booking still waits, the pin still reads one, units still held.
    check.assert_procedure_booking(
        SETUP.read_booking(api, booking_two["id"]),
        status=C.BOOKING_SCHEDULED,
        attending_physician_user_id=None,
    )
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case_ids[1]), pinned_policy_version=1
    )
    check.assert_supply_lot(SETUP.read_lot(api, lot["id"]), quantity_reserved=2)


def test_a_serum_conversion_needs_the_plan_to_cover_serum_testing(api):
    """PRD 3.2: "The governing plan must have `allergy_serum_covered` true, or the
    conversion is refused with `ERR_SERUM_NOT_COVERED`."

    Design: Corner/validations/serum_conversion_requires_plan_coverage
    """
    # Two plans differing only in whether serum testing is a covered benefit.
    uncovered_plan = SETUP.create_policy(
        api,
        plan_code="VALD-2999",
        payer_name="Skin Only Health",
        allergy_serum_covered=False,
    )
    covered_plan = SETUP.create_policy(
        api,
        plan_code="VALE-2999",
        payer_name="Full Panel Health",
        allergy_serum_covered=True,
    )
    uncovered_patient = SETUP.create_patient(
        api,
        uncovered_plan["id"],
        patient_mrn=C.mrn(10224),
        full_name="Teodora Vasquez-Bramwell",
        date_of_birth="1988-04-04",
        epinephrine_on_file=True,
    )
    covered_patient = SETUP.create_patient(
        api,
        covered_plan["id"],
        patient_mrn=C.mrn(10225),
        full_name="Anselm Okonkwo-Reith",
        date_of_birth="1988-04-04",
        epinephrine_on_file=True,
    )

    # The uncovered chart's panel cannot move to the serum arm at all.
    uncovered_order = SETUP.create_order(
        api,
        uncovered_patient["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
    )
    validate_error(
        api.convert_allergy_test_order_to_serum(uncovered_order["id"], USERS.NURSE_1),
        ApiErrorId.SERUM_NOT_COVERED.value,
    )

    # The refused order is untouched: still a skin panel awaiting administration.
    check.assert_allergy_test_order(
        SETUP.read_order(api, uncovered_order["id"]),
        status=C.ORDER_ORDERED,
        method=C.METHOD_SKIN_PRICK,
        billed_units=0,
        observation_required_minutes=C.OBSERVATION_BASE_SKIN_PRICK,
        practice_charge_cents=0,
        patient_responsibility_cents=0,
    )

    # The covered chart's identical panel converts and its observation wait vanishes.
    covered_order = SETUP.create_order(
        api,
        covered_patient["id"],
        panel_code=C.PANEL_MOLD_12,
        method=C.METHOD_SKIN_PRICK,
    )
    converted = SETUP.convert_order_to_serum(api, covered_order["id"])
    check.assert_allergy_test_order(
        converted,
        status=C.ORDER_SERUM_PENDING,
        method=C.METHOD_SERUM_IGE,
        billed_units=3,
        observation_required_minutes=C.OBSERVATION_MINUTES_SERUM,
        administered_at=None,
        administered_by_user_id=None,
    )

    # Neither chart's own risk figures moved: no reading has been recorded yet.
    for patient_id in (uncovered_patient["id"], covered_patient["id"]):
        check.assert_patient(
            SETUP.read_patient(api, patient_id),
            sensitized_antigen_count=0,
            risk_score=5,
            risk_score_variant=C.RISK_VARIANT_PROVISIONAL,
            supervision_tier=C.SUPERVISION_TIER_STANDARD,
        )


def test_a_draft_case_has_no_payer_pathway_yet(api):
    """PRD 3.6: "A submission from any other status is refused with
    `ERR_CASE_STATE_INVALID`."

    Design: Corner/validations/draft_case_submission_then_ineligible_candidacy
    """
    # A strict plan and one freshly opened case, still carrying no evidence.
    policy = SETUP.create_policy(
        api,
        plan_code="VALF-2999",
        payer_name="Cascade Health",
        requires_prior_auth=True,
        min_documented_criteria=3,
        min_medical_management_days=28,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10226),
        full_name="Ingrid Solvang-Marchetti",
        date_of_birth="1969-06-06",
        epinephrine_on_file=True,
    )
    case = SETUP.create_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_LEFT,
        sinuses=[C.SINUS_MAXILLARY],
    )
    check.assert_sinuplasty_case(
        case,
        status=C.CASE_DRAFT,
        candidacy_status=C.CANDIDACY_UNDETERMINED,
        evaluation_variant=C.EVAL_VARIANT_POLICY_STRICT,
        revision_round=0,
        submitted_by_user_id=None,
    )

    # Filing an authorization from DRAFT is not one of the three legal origins.
    validate_error(
        api.submit_authorization(case["id"], USERS.LIAISON_1),
        ApiErrorId.CASE_STATE_INVALID.value,
    )

    # The case is still a draft and no liaison is recorded against it.
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case["id"]),
        status=C.CASE_DRAFT,
        candidacy_status=C.CANDIDACY_UNDETERMINED,
        submitted_by_user_id=None,
        pinned_policy_version=None,
    )


def test_a_documented_case_that_falls_short_of_the_management_days_cannot_be_filed(api):
    """PRD 3.6: "From `DOCUMENTED`, the plan must require prior authorization — a case
    whose plan has `requires_prior_auth` false has no payer pathway at all and its
    submission is refused with `ERR_CASE_STATE_INVALID` — and the case's
    `candidacy_status` must be `ELIGIBLE`, or the submission is refused with
    `ERR_CANDIDACY_NOT_ELIGIBLE`."

    Design: Corner/validations/draft_case_submission_then_ineligible_candidacy
    """
    # The same strict plan, demanding twenty-eight management days and three criteria.
    policy = SETUP.create_policy(
        api,
        plan_code="VALF-2999",
        payer_name="Cascade Health",
        requires_prior_auth=True,
        min_documented_criteria=3,
        min_medical_management_days=28,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10226),
        full_name="Ingrid Solvang-Marchetti",
        date_of_birth="1969-06-06",
        epinephrine_on_file=True,
    )
    case = SETUP.create_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_LEFT,
        sinuses=[C.SINUS_MAXILLARY],
    )

    # Three admissible criteria, but only a fortnight of documented management.
    documented = SETUP.document_case(
        api,
        case["id"],
        therapies=[F.therapy_course(C.THERAPY_INCS, "2026-06-01", "2026-06-14")],
        criteria=[
            C.CRITERION_CT_OPACIFICATION,
            C.CRITERION_FAILED_INCS,
            C.CRITERION_ENDOSCOPY_FINDING,
        ],
        ct_study_date="2026-05-20",
    )
    check.assert_sinuplasty_case(
        documented,
        status=C.CASE_DOCUMENTED,
        criteria_met_count=3,
        contiguous_management_days=14,
        cumulative_management_days=14,
        candidacy_status=C.CANDIDACY_INELIGIBLE,
    )

    # An ineligible case has nothing to file with the payer.
    validate_error(
        api.submit_authorization(case["id"], USERS.LIAISON_1),
        ApiErrorId.CANDIDACY_NOT_ELIGIBLE.value,
    )

    # Nor can the physician re-document it: documentation is a one-shot from DRAFT.
    validate_error(
        api.document_sinuplasty_case(
            case["id"],
            F.documentation_payload(
                documented_therapies=[
                    F.therapy_course(C.THERAPY_INCS, "2026-06-01", "2026-06-28")
                ],
                documented_criteria_codes=[
                    C.CRITERION_CT_OPACIFICATION,
                    C.CRITERION_FAILED_INCS,
                    C.CRITERION_ENDOSCOPY_FINDING,
                ],
                ct_study_date="2026-05-20",
            ),
            USERS.ENT_1,
        ),
        ApiErrorId.CASE_STATE_INVALID.value,
    )

    # The case still stands exactly where the first documentation left it.
    check.assert_sinuplasty_case(
        SETUP.read_case(api, case["id"]),
        status=C.CASE_DOCUMENTED,
        candidacy_status=C.CANDIDACY_INELIGIBLE,
        contiguous_management_days=14,
        revision_round=0,
        submitted_by_user_id=None,
        pinned_policy_version=None,
    )
