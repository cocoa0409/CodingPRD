"""
Validation breadth: the declared failure precedence, the typed 404 families, the
state gates on every lifecycle, the unique keys and the eligibility rules that
guard booking, billing, assistance and recall work.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    UNKNOWN_ROLE_NAME,
    UNRESOLVABLE_IDENTITY,
    assert_instant_equals,
    assert_vial_counters,
    headers_omitting,
    validate_list,
    with_role,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    COMPLIANCE_USER_ID,
    COMPLIANCE_USER_ID_2,
    COMPLIANCE_USER_ID_3,
    compliance_headers,
    patient_headers,
    specialist_headers,
    tech_headers,
)

# Syntactically valid UUIDs that resolve to no row in any collection.
PROBE_IDS = {
    "payer": "aaaaaaaa-0000-4000-8000-000000000001",
    "drug": "aaaaaaaa-0000-4000-8000-000000000002",
    "policy": "aaaaaaaa-0000-4000-8000-000000000003",
    "patient": "aaaaaaaa-0000-4000-8000-000000000004",
    "clinician": "aaaaaaaa-0000-4000-8000-000000000005",
    "imaging": "aaaaaaaa-0000-4000-8000-000000000006",
    "plan": "aaaaaaaa-0000-4000-8000-000000000007",
    "lot": "aaaaaaaa-0000-4000-8000-000000000008",
    "vial": "aaaaaaaa-0000-4000-8000-000000000009",
    "authorization": "aaaaaaaa-0000-4000-8000-00000000000a",
    "encounter": "aaaaaaaa-0000-4000-8000-00000000000b",
    "claim": "aaaaaaaa-0000-4000-8000-00000000000c",
    "enrollment": "aaaaaaaa-0000-4000-8000-00000000000d",
    "adverse_event": "aaaaaaaa-0000-4000-8000-00000000000e",
    "recall": "aaaaaaaa-0000-4000-8000-00000000000f",
    "notification": "aaaaaaaa-0000-4000-8000-000000000010",
}

UNKNOWN_FK_PATIENT = "bbbbbbbb-0000-4000-8000-000000000001"
UNKNOWN_FK_DRUG = "bbbbbbbb-0000-4000-8000-000000000002"
UNKNOWN_FK_PAYER = "bbbbbbbb-0000-4000-8000-000000000003"
UNKNOWN_FK_ENCOUNTER = "bbbbbbbb-0000-4000-8000-000000000004"


def test_the_four_auth_checks_fire_in_their_declared_order(breadth, admin, tech):
    """
    Absent headers outrank a malformed body, an unlisted role outranks the
    endpoint's own permission list, a listed-but-unpermitted role outranks identity
    resolution, and an unresolvable specialist is the last of the four to speak.

    The PRD numbers them: "1. Both authentication headers present and non-empty —
    otherwise `ERR_MISSING_AUTH_HEADERS` (401). Applies to every endpoint.  2.
    `X-User-Role` is one of the six declared roles — otherwise `ERR_UNKNOWN_ROLE`
    (401). Applies to every endpoint.  3. The role is authorised for this endpoint —
    otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint.  4. For the
    entity-backed roles, `X-User-ID` resolves to an existing row (`RetinaSpecialist`
    to a `Clinician`, `Patient` to a `Patient`) — otherwise
    `ERR_ACTING_IDENTITY_NOT_FOUND` (403)."  The first request also fails the payload
    gate, and the PRD says which wins: "Because role authorisation (step 3) precedes
    payload validation (step 5), a wrong-role request with a malformed body reports
    the role failure."  Nothing is written on the way out, because "When a single
    request violates more than one rule, the response must carry the error of the
    *first* violated rule in the order below, and evaluation stops there."

    Design: Corner/validations/corner_auth_layer_rejects_missing_headers_unknown_roles_and_wrong_roles_in_priority_order
    """
    patient = breadth.pt_np
    breadth.cl1

    validate_error(
        breadth.api.create_payer(
            {"name": "", "payer_type": "NOT_A_TYPE", "coinsurance_rate": 9.5},
            headers_omitting(admin, "X-User-Role", "X-User-ID"),
        ),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS,
        401,
    )
    validate_error(
        breadth.api.create_payer(
            f.payer_payload(
                name="Anywhere Health", payer_type="COMMERCIAL", coinsurance_rate=0.2
            ),
            with_role(admin, UNKNOWN_ROLE_NAME),
        ),
        ApiErrorId.ERR_UNKNOWN_ROLE,
        401,
    )
    validate_error(
        breadth.api.create_payer(
            f.payer_payload(
                name="Anywhere Health", payer_type="COMMERCIAL", coinsurance_rate=0.2
            ),
            tech,
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        breadth.api.create_imaging_study(
            f.imaging_payload(
                patient_id=patient["id"],
                eye="OD",
                study_datetime=breadth.CLOCK,
                central_subfield_thickness_um=400,
                intraretinal_fluid=True,
                va_letter_score=60,
            ),
            specialist_headers(UNRESOLVABLE_IDENTITY),
        ),
        ApiErrorId.ERR_ACTING_IDENTITY_NOT_FOUND,
        403,
    )

    _, payer_meta = validate_list(
        breadth.api.list_payers(admin, f.page_params(name="Anywhere Health"))
    )
    assert payer_meta["total_count"] == 0

    _, study_meta = validate_list(
        breadth.api.list_imaging_studies(admin, f.page_params(patient_id=patient["id"]))
    )
    assert study_meta["total_count"] == 0


def test_each_of_the_sixteen_path_id_families_answers_with_its_own_404(breadth, admin):
    """
    Sixteen single-resource reads against an empty database return sixteen distinct
    `error_id` values rather than one shared not-found code.

    The PRD enumerates the catalogue behind step 6: "Every identifier in the URL path
    resolves to an existing row, validated left to right — otherwise the 404 belonging
    to the entity that failed to resolve, drawn from `ERR_PAYER_NOT_FOUND`,
    `ERR_DRUG_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`,
    `ERR_CLINICIAN_NOT_FOUND`, `ERR_IMAGING_STUDY_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_VIAL_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`,
    `ERR_ENCOUNTER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_ADVERSE_EVENT_NOT_FOUND`, `ERR_RECALL_NOT_FOUND` and
    `ERR_NOTIFICATION_NOT_FOUND`. Applies to every endpoint that has a path
    identifier."  Each identifier is "a server-minted UUID with no type prefix", so a
    well-formed UUID that names nothing is a resolution failure rather than a payload
    failure.

    Design: Corner/validations/corner_every_path_id_family_returns_its_own_not_found
    """
    api = breadth.api

    probes = [
        (api.get_payer(PROBE_IDS["payer"], admin), ApiErrorId.ERR_PAYER_NOT_FOUND),
        (api.get_drug(PROBE_IDS["drug"], admin), ApiErrorId.ERR_DRUG_NOT_FOUND),
        (
            api.get_payer_drug_policy(PROBE_IDS["policy"], admin),
            ApiErrorId.ERR_POLICY_NOT_FOUND,
        ),
        (api.get_patient(PROBE_IDS["patient"], admin), ApiErrorId.ERR_PATIENT_NOT_FOUND),
        (
            api.get_clinician(PROBE_IDS["clinician"], admin),
            ApiErrorId.ERR_CLINICIAN_NOT_FOUND,
        ),
        (
            api.get_imaging_study(PROBE_IDS["imaging"], admin),
            ApiErrorId.ERR_IMAGING_STUDY_NOT_FOUND,
        ),
        (api.get_treatment_plan(PROBE_IDS["plan"], admin), ApiErrorId.ERR_PLAN_NOT_FOUND),
        (api.get_drug_lot(PROBE_IDS["lot"], admin), ApiErrorId.ERR_LOT_NOT_FOUND),
        (api.get_vial(PROBE_IDS["vial"], admin), ApiErrorId.ERR_VIAL_NOT_FOUND),
        (
            api.get_prior_authorization(PROBE_IDS["authorization"], admin),
            ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND,
        ),
        (
            api.get_injection_encounter(PROBE_IDS["encounter"], admin),
            ApiErrorId.ERR_ENCOUNTER_NOT_FOUND,
        ),
        (api.get_claim(PROBE_IDS["claim"], admin), ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (
            api.get_assistance_enrollment(PROBE_IDS["enrollment"], admin),
            ApiErrorId.ERR_ENROLLMENT_NOT_FOUND,
        ),
        (
            api.get_adverse_event(PROBE_IDS["adverse_event"], admin),
            ApiErrorId.ERR_ADVERSE_EVENT_NOT_FOUND,
        ),
        (api.get_lot_recall(PROBE_IDS["recall"], admin), ApiErrorId.ERR_RECALL_NOT_FOUND),
        (
            api.get_recall_notification(PROBE_IDS["notification"], compliance_headers()),
            ApiErrorId.ERR_NOTIFICATION_NOT_FOUND,
        ),
    ]

    for response, expected in probes:
        validate_error(response, expected, 404)

    assert len({expected.value for _, expected in probes}) == 16


def test_body_foreign_keys_are_resolved_in_the_order_the_endpoint_declares_them(
    breadth, admin, billing
):
    """
    A plan naming two unknown parents reports the patient's 404 because `patient_id`
    is declared first, and repairing only the patient surfaces the drug's 404.

    The PRD fixes both the position and the order of the check: "Every foreign key
    supplied in the request body resolves to an existing row, validated in the order
    the fields are listed for that endpoint in §4's companion narrative — otherwise
    the same catalogue of 404s. Applies to every endpoint whose input carries a
    foreign key."  The plan's own narrative lists them in that order — a specialist
    "opens a plan for one patient and one eye, naming the `patient_id`, the `drug_id`
    of the planned product before any biosimilar substitution, and the `eye`" — while a
    policy is the row for "the claim's payer paired with the encounter's effective
    drug" and a claim carries the "`injection_encounter_id`".  Evaluation "stops
    there", so no row is written.

    Design: Corner/validations/corner_body_foreign_keys_are_checked_in_declaration_order_not_found
    """
    breadth.pol_np_ref
    patient = breadth.pt_np
    clinician = breadth.cl1
    injector = specialist_headers(clinician["id"])

    validate_error(
        breadth.api.create_treatment_plan(
            f.plan_payload(
                patient_id=UNKNOWN_FK_PATIENT,
                drug_id=UNKNOWN_FK_DRUG,
                eye="OD",
                loading_doses_required=3,
            ),
            injector,
        ),
        ApiErrorId.ERR_PATIENT_NOT_FOUND,
        404,
    )
    validate_error(
        breadth.api.create_treatment_plan(
            f.plan_payload(
                patient_id=patient["id"],
                drug_id=UNKNOWN_FK_DRUG,
                eye="OD",
                loading_doses_required=3,
            ),
            injector,
        ),
        ApiErrorId.ERR_DRUG_NOT_FOUND,
        404,
    )
    validate_error(
        breadth.api.create_payer_drug_policy(
            f.policy_payload(
                payer_id=UNKNOWN_FK_PAYER,
                drug_id=breadth.drug_ref["id"],
                coverage_tier="PREFERRED",
                drug_allowed_cents_per_billing_unit=14000,
                admin_allowed_cents=10000,
            ),
            admin,
        ),
        ApiErrorId.ERR_PAYER_NOT_FOUND,
        404,
    )
    validate_error(
        breadth.api.create_claim(
            f.claim_payload(injection_encounter_id=UNKNOWN_FK_ENCOUNTER), billing
        ),
        ApiErrorId.ERR_ENCOUNTER_NOT_FOUND,
        404,
    )

    _, plan_meta = validate_list(breadth.api.list_treatment_plans(admin, f.page_params()))
    assert plan_meta["total_count"] == 0

    _, policy_meta = validate_list(
        breadth.api.list_payer_drug_policies(admin, f.page_params())
    )
    assert policy_meta["total_count"] == 1

    _, claim_meta = validate_list(breadth.api.list_claims(admin, f.page_params()))
    assert claim_meta["total_count"] == 0


def test_a_draft_plan_refuses_resumption_suspension_and_treatment_but_accepts_activation(
    breadth,
):
    """
    Resume and suspend are both illegal edges out of `DRAFT`, booking against a draft
    plan is refused by the treatability gate without touching inventory, and only the
    first activation is accepted.

    The PRD groups the refusals under one code: "any transition attempted on a
    discontinued plan is `ERR_PLAN_STATE_INVALID` (HTTP 409), as is activation of a
    plan that is not in `DRAFT`, suspension of a plan that is in `DRAFT` or already
    terminal, and resumption of a plan that is not `SUSPENDED`."  Booking is guarded
    separately: "The plan must be treatable, meaning its status is `LOADING`,
    `MAINTENANCE` or `INTENSIFIED`. A plan in `DRAFT`, `SUSPENDED` or `DISCONTINUED`
    cannot receive an injection, and the rejection carries its own dedicated code:
    `ERR_PLAN_NOT_TREATABLE` (HTTP 409)", and
    "no vial is ever reserved by a request that goes on to fail."  The one accepted
    edge is the activation itself: it "moves the plan `DRAFT → LOADING`" and "advances
    the plan's `version` by 1", which is why the surviving row sits at version 2.

    Design: Corner/validations/corner_plan_state_gates_reject_resume_and_treatment_on_a_draft_plan
    """
    breadth.pol_np_ref
    lot = breadth.lot_ref
    study = breadth.img_np
    plan = breadth.plan_np
    injector = specialist_headers(breadth.cl1["id"])

    assert plan["status"] == "DRAFT"

    validate_error(
        breadth.api.resume_treatment_plan(plan["id"], {}, injector),
        ApiErrorId.ERR_PLAN_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.suspend_treatment_plan(
            plan["id"], f.plan_suspend_payload(suspension_reason="CLINICIAN_HOLD"), injector
        ),
        ApiErrorId.ERR_PLAN_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=study["id"],
                encounter_datetime=breadth.ENCOUNTER_AT,
                expected_treatment_plan_version=plan["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_PLAN_NOT_TREATABLE,
        409,
    )
    assert_vial_counters(breadth.read_lot(lot["id"]), vials_on_hand=5, vials_reserved=0)

    activated = validate_success(
        breadth.api.activate_treatment_plan(
            plan["id"],
            f.plan_activate_payload(baseline_imaging_study_id=study["id"]),
            injector,
        ),
        200,
    )
    assert activated["status"] == "LOADING"

    validate_error(
        breadth.api.activate_treatment_plan(
            plan["id"],
            f.plan_activate_payload(baseline_imaging_study_id=study["id"]),
            injector,
        ),
        ApiErrorId.ERR_PLAN_STATE_INVALID,
        409,
    )

    settled = breadth.read_plan(plan["id"])
    assert settled["status"] == "LOADING"
    assert settled["version"] == 2


def test_a_decision_before_submission_a_cap_breach_and_a_late_appeal_are_all_refused(
    breadth, billing, admin
):
    """
    Three independent authorization guards refuse three requests on one row: a
    decision on an unsubmitted draft, an approval above the policy cap, and an appeal
    filed one day past the payer's window.

    The PRD gates the decision on the state: "The payer's answer arrives as a
    decision, which is accepted only while the authorization sits in `SUBMITTED` or
    `APPEALED`."  The cap is the policy's: "`approved_injections` may not exceed the
    governing policy's `pa_max_injections`; exceeding it is
    `ERR_APPROVED_INJECTIONS_EXCEED_POLICY` (HTTP 422)", and that ceiling is the
    declared default because the policy did not state one — "`pa_max_injections`
    defaults to 3, must be at least 1, and caps how many injections one authorization
    may cover."  The denial itself needs a member of the closed list: "A decision of
    `DENIED` requires a `denial_reason` drawn from `STEP_THERAPY`,
    `NOT_MEDICALLY_NECESSARY`, `NON_FORMULARY` and `INCOMPLETE_DOCUMENTATION`; it
    stores that reason and deliberately leaves `approved_injections` null."  The appeal
    clock runs from the denial: "the logical clock must be at or before the
    authorization's `updated_at` advanced by the payer's `appeal_window_days` in whole
    days, and a late filing is `ERR_APPEAL_WINDOW_CLOSED` (HTTP 409)", and this payer's
    window is 45 days, so it closed on 2026-09-15.

    Design: Corner/validations/corner_authorization_gates_reject_out_of_order_decisions_and_late_appeals
    """
    breadth.pol_np_ref
    plan = breadth.plan_np_active
    authorization = breadth.authorization(
        treatment_plan_id=plan["id"], expected_treatment_plan_version=plan["version"]
    )
    assert authorization["status"] == "DRAFT"

    validate_error(
        breadth.api.decide_prior_authorization(
            authorization["id"],
            f.approval_decision_payload(
                auth_number="AUTH-0001",
                approved_injections=3,
                effective_date="2026-08-01T00:00:00Z",
            ),
            billing,
        ),
        ApiErrorId.ERR_AUTHORIZATION_STATE_INVALID,
        409,
    )

    submitted = breadth.submit_authorization(
        authorization["id"], clinical_justification="Active exudative disease on OCT"
    )
    assert submitted["status"] == "SUBMITTED"

    validate_error(
        breadth.api.decide_prior_authorization(
            authorization["id"],
            f.approval_decision_payload(
                auth_number="AUTH-0002",
                approved_injections=5,
                effective_date="2026-08-01T00:00:00Z",
            ),
            billing,
        ),
        ApiErrorId.ERR_APPROVED_INJECTIONS_EXCEED_POLICY,
        422,
    )
    assert breadth.read_authorization(authorization["id"])["status"] == "SUBMITTED"

    denied = validate_success(
        breadth.api.decide_prior_authorization(
            authorization["id"],
            f.denial_decision_payload(denial_reason="STEP_THERAPY"),
            billing,
        ),
        200,
    )
    assert denied["status"] == "DENIED"
    assert denied["approved_injections"] is None

    breadth.set_clock("2026-09-16T00:00:00Z")

    validate_error(
        breadth.api.appeal_prior_authorization(
            authorization["id"],
            f.authorization_appeal_payload(appeal_basis="Prior failure records attached"),
            billing,
        ),
        ApiErrorId.ERR_APPEAL_WINDOW_CLOSED,
        409,
    )

    settled = breadth.read_authorization(authorization["id"])
    assert settled["status"] == "DENIED"
    assert settled["appeal_basis"] is None


def test_the_claim_line_gates_refuse_early_money_a_second_submit_and_a_second_claim(
    breadth, billing, admin
):
    """
    Remittance and appeal are both refused while the two axes are still pending,
    submitting twice is refused, and the encounter cannot carry a second claim.

    The PRD guards each move by the line status: "Submitting a claim whose lines have
    already left `PENDING` is `ERR_CLAIM_LINE_STATE_INVALID` (HTTP 409)", "Remitting a
    line that is still `PENDING` is `ERR_CLAIM_LINE_STATE_INVALID` (HTTP 409)" and
    "Appealing a drug line that is not `DENIED` is `ERR_CLAIM_LINE_STATE_INVALID`
    (HTTP 409)."  Creation left both axes at the bottom — "Both status axes are born
    `PENDING`" — and the one accepted call moves them together: "Submitting the claim
    moves *both* axes `PENDING → SUBMITTED` in a single call; the administration line
    has no independent side effect of its own, and the two dimensions leave `PENDING`
    together."  The encounter's claim is unique: "At most one claim may exist per
    encounter; a second attempt is `ERR_DUPLICATE_CLAIM` (HTTP 409)."  Creating the
    first claim also moved the encounter on — "`ATTESTED → BILLED` happens when a
    claim is created for the encounter" — so the second attempt breaks the state gate
    of §2.8 step 13 and the uniqueness rule of step 37 at the same time, and either
    409 answer is faithful.

    Design: Corner/validations/corner_claim_line_gates_reject_double_submission_early_remittance_and_a_second_claim
    """
    encounter = breadth.enc_np_attested
    claim = breadth.claim_np
    assert claim["drug_line_status"] == "PENDING"
    assert claim["admin_line_status"] == "PENDING"

    validate_error(
        breadth.api.post_remittance(
            claim["id"],
            f.drug_line_paid_payload(
                drug_allowed_cents=28000,
                drug_paid_cents=24200,
                wastage_allowed_cents=0,
                wastage_paid_cents=0,
            ),
            billing,
        ),
        ApiErrorId.ERR_CLAIM_LINE_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.appeal_drug_line(
            claim["id"],
            f.claim_appeal_payload(appeal_basis="Wastage documentation attached"),
            billing,
        ),
        ApiErrorId.ERR_CLAIM_LINE_STATE_INVALID,
        409,
    )

    submitted = validate_success(breadth.api.submit_claim(claim["id"], {}, billing), 200)
    assert submitted["drug_line_status"] == "SUBMITTED"
    assert submitted["admin_line_status"] == "SUBMITTED"

    validate_error(
        breadth.api.submit_claim(claim["id"], {}, billing),
        ApiErrorId.ERR_CLAIM_LINE_STATE_INVALID,
        409,
    )
    second_claim = breadth.api.create_claim(
        f.claim_payload(injection_encounter_id=encounter["id"]), billing
    )
    assert second_claim.status_code == 409
    validate_error_is_one_of(
        second_claim,
        [ApiErrorId.ERR_DUPLICATE_CLAIM, ApiErrorId.ERR_ENCOUNTER_STATE_INVALID],
    )

    _, meta = validate_list(
        breadth.api.list_claims(
            admin, f.page_params(injection_encounter_id=encounter["id"])
        )
    )
    assert meta["total_count"] == 1


def test_the_authorization_gate_opens_for_exactly_the_approved_injection_count(
    breadth, admin
):
    """
    On a payer whose policy demands authorization, the first booking is refused for
    want of one, an approval for a single injection lets exactly one encounter
    through, and the next booking is refused as exhausted while the window is still
    open.

    The PRD makes the gate conditional on the policy: "When that policy's `pa_required`
    is true, the plan must hold at least one authorization whose status is `APPROVED`
    or `EXHAUSTED`; holding none is `ERR_AUTHORIZATION_MISSING` (HTTP 409)", and "no
    vial is ever reserved by a request that goes on to fail."  Approval prices the
    window: it "computes `expiration_date` as `effective_date` advanced by
    `pa_validity_days` whole days", the policy's declared 180.  Consumption is counted
    and then capped: "On success the authorization's identifier is written to
    `prior_authorization_id`, its `injections_used` is bumped, and it flips `APPROVED →
    EXHAUSTED` when that bump reaches `approved_injections`", after which "its
    `injections_used` must be strictly below its `approved_injections`, a full
    authorization being `ERR_AUTHORIZATION_EXHAUSTED` (HTTP 409)."

    Design: Corner/validations/corner_authorization_is_required_then_exhausted_by_the_approved_injection_count
    """
    breadth.pol_comm_ref
    lot = breadth.lot_ref
    patient = breadth.pt_comm
    injector = specialist_headers(breadth.cl1["id"])

    study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=patient["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=425,
        intraretinal_fluid=True,
        va_letter_score=57,
    )
    plan = breadth.plan(
        clinician_id=breadth.cl1["id"],
        patient_id=patient["id"],
        drug_id=breadth.drug_ref["id"],
        eye="OD",
    )
    activated = breadth.activate_plan(
        plan["id"], clinician_id=breadth.cl1["id"], baseline_imaging_study_id=study["id"]
    )

    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=study["id"],
                encounter_datetime="2026-08-01T09:00:00Z",
                expected_treatment_plan_version=activated["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_AUTHORIZATION_MISSING,
        409,
    )
    assert breadth.read_lot(lot["id"])["vials_reserved"] == 0

    approved = breadth.approved_authorization(
        treatment_plan_id=plan["id"],
        expected_treatment_plan_version=activated["version"],
        auth_number="AUTH-1001",
        approved_injections=1,
        effective_date="2026-08-01T00:00:00Z",
    )
    assert approved["status"] == "APPROVED"
    assert_instant_equals(
        approved["expiration_date"], "2027-01-28T00:00:00Z", "expiration_date"
    )

    guarded = breadth.read_plan(plan["id"])
    first = breadth.encounter(
        clinician_id=breadth.cl1["id"],
        treatment_plan_id=plan["id"],
        imaging_study_id=study["id"],
        encounter_datetime="2026-08-01T09:00:00Z",
        expected_treatment_plan_version=guarded["version"],
    )
    assert first["prior_authorization_id"] == approved["id"]

    consumed = breadth.read_authorization(approved["id"])
    assert consumed["injections_used"] == 1
    assert consumed["status"] == "EXHAUSTED"

    breadth.document(
        first["id"],
        clinician_id=breadth.cl1["id"],
        administered_dose_ml=0.06,
        post_injection_iop_mmhg=16,
    )

    later_study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=patient["id"],
        eye="OD",
        study_datetime="2026-08-29T08:00:00Z",
        central_subfield_thickness_um=415,
        intraretinal_fluid=True,
        va_letter_score=58,
    )
    reread = breadth.read_plan(plan["id"])

    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=later_study["id"],
                encounter_datetime="2026-08-29T09:00:00Z",
                expected_treatment_plan_version=reread["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_AUTHORIZATION_EXHAUSTED,
        409,
    )

    assert_vial_counters(
        breadth.read_lot(lot["id"]), vials_administered=1, vials_reserved=0
    )


def test_a_mandatory_biosimilar_swap_invalidates_the_reference_drug_authorization(
    breadth, admin
):
    """
    A Medicare plan written for the reference product is substituted to the preferred
    biosimilar at booking, and the authorization approved for the reference product no
    longer matches the product going into the eye.

    The substitution is the payer's rule: "Otherwise, when the payer's
    `biosimilar_preference` is `MANDATORY`, the chosen candidate becomes
    `effective_drug_id` and the displaced plan product is recorded in
    `substituted_from_drug_id`."  The authorization, by contrast, was frozen at
    creation: "`drug_id` is copied from the plan's planned product and is never
    re-derived afterwards."  The gate then compares the two: "its `drug_id` must equal
    the encounter's `effective_drug_id` — a mandatory biosimilar substitution routinely
    invalidates an authorization written for the reference product, and the mismatch is
    `ERR_AUTHORIZATION_DRUG_MISMATCH` (HTTP 409)."  The refusal costs nothing, since
    the vial is picked "Last of all, and only once every preceding gate has passed" and
    "no vial is ever reserved by a request that goes on to fail."

    Design: Corner/validations/corner_a_biosimilar_substitution_invalidates_the_reference_drug_authorization
    """
    reference = breadth.drug_ref
    biosimilar = breadth.drug_bio_a
    reference_lot = breadth.lot_ref
    biosimilar_lot = breadth.lot_bio_a
    patient = breadth.pt_mcr
    injector = specialist_headers(breadth.cl1["id"])

    breadth.policy(
        payer_id=breadth.pay_mcr["id"],
        drug_id=reference["id"],
        coverage_tier="NON_PREFERRED",
        drug_allowed_cents_per_billing_unit=14000,
        admin_allowed_cents=10000,
        wastage_reimbursed=True,
        pa_required=True,
        pa_validity_days=180,
        pa_max_injections=3,
    )
    breadth.policy(
        payer_id=breadth.pay_mcr["id"],
        drug_id=biosimilar["id"],
        coverage_tier="PREFERRED",
        drug_allowed_cents_per_billing_unit=11000,
        admin_allowed_cents=10000,
        wastage_reimbursed=True,
        pa_required=True,
        pa_validity_days=180,
        pa_max_injections=3,
    )

    study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=patient["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=460,
        intraretinal_fluid=True,
        subretinal_fluid=True,
        va_letter_score=48,
    )
    plan = breadth.plan(
        clinician_id=breadth.cl1["id"],
        patient_id=patient["id"],
        drug_id=reference["id"],
        eye="OD",
    )
    activated = breadth.activate_plan(
        plan["id"], clinician_id=breadth.cl1["id"], baseline_imaging_study_id=study["id"]
    )

    approved = breadth.approved_authorization(
        treatment_plan_id=plan["id"],
        expected_treatment_plan_version=activated["version"],
        auth_number="AUTH-2001",
        approved_injections=3,
        effective_date="2026-08-01T00:00:00Z",
    )
    assert approved["drug_id"] == reference["id"]
    assert approved["status"] == "APPROVED"

    guarded = breadth.read_plan(plan["id"])
    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=study["id"],
                encounter_datetime="2026-08-01T09:00:00Z",
                expected_treatment_plan_version=guarded["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_AUTHORIZATION_DRUG_MISMATCH,
        409,
    )

    assert breadth.read_lot(biosimilar_lot["id"])["vials_reserved"] == 0
    assert breadth.read_lot(reference_lot["id"])["vials_reserved"] == 0

    settled = breadth.read_authorization(approved["id"])
    assert settled["injections_used"] == 0
    assert settled["status"] == "APPROVED"


def test_an_authorization_past_its_window_is_persisted_as_expired_by_the_rejection(
    breadth, admin
):
    """
    Booking against an authorization whose window closed four days earlier is refused,
    and the refusal itself is what writes `EXPIRED` onto the row.

    The PRD makes the flip a side effect of the rejection and pins the order: "`EXPIRED`
    is the authorization's terminal status and is reached lazily. When an encounter
    creation selects an authorization whose `expiration_date` is strictly before the
    logical clock, the authorization is flipped to `EXPIRED` from either `APPROVED` or
    `EXHAUSTED`, that flip is persisted, and only then is the triggering encounter
    creation rejected with `ERR_AUTHORIZATION_EXPIRED` (HTTP 409). The ordering matters:
    a client that retries after such a rejection will find the authorization already
    recorded as `EXPIRED`."  Selection reaches it because no window covers the clock:
    "If no authorization's window contains the clock, the server instead takes the one
    with the greatest `expiration_date`, with `created_at` descending breaking a tie,
    flips that authorization to `EXPIRED`, persists the flip, and rejects the encounter
    with `ERR_AUTHORIZATION_EXPIRED` (HTTP 409)."  The window itself was computed at
    approval as `effective_date` "advanced by `pa_validity_days` whole days".

    Design: Corner/validations/corner_authorization_outside_its_window_is_flipped_to_expired_and_rejected
    """
    breadth.pol_comm_ref
    lot = breadth.lot_ref
    patient = breadth.pt_comm
    injector = specialist_headers(breadth.cl1["id"])

    study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=patient["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=425,
        intraretinal_fluid=True,
        va_letter_score=57,
    )
    plan = breadth.plan(
        clinician_id=breadth.cl1["id"],
        patient_id=patient["id"],
        drug_id=breadth.drug_ref["id"],
        eye="OD",
    )
    activated = breadth.activate_plan(
        plan["id"], clinician_id=breadth.cl1["id"], baseline_imaging_study_id=study["id"]
    )
    approved = breadth.approved_authorization(
        treatment_plan_id=plan["id"],
        expected_treatment_plan_version=activated["version"],
        auth_number="AUTH-3001",
        approved_injections=1,
        effective_date="2026-08-01T00:00:00Z",
    )
    assert_instant_equals(
        approved["expiration_date"], "2027-01-28T00:00:00Z", "expiration_date"
    )

    breadth.set_clock("2027-02-01T00:00:00Z")
    late_study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=patient["id"],
        eye="OD",
        study_datetime="2027-02-01T08:00:00Z",
        central_subfield_thickness_um=445,
        intraretinal_fluid=True,
        va_letter_score=51,
    )
    guarded = breadth.read_plan(plan["id"])

    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=late_study["id"],
                encounter_datetime="2027-02-01T09:00:00Z",
                expected_treatment_plan_version=guarded["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_AUTHORIZATION_EXPIRED,
        409,
    )

    settled = breadth.read_authorization(approved["id"])
    assert settled["status"] == "EXPIRED"
    assert settled["injections_used"] == 0

    _, meta = validate_list(breadth.api.list_injection_encounters(admin, f.page_params()))
    assert meta["total_count"] == 0
    assert breadth.read_lot(lot["id"])["vials_reserved"] == 0


def test_the_imaging_validity_window_is_the_closed_zero_to_fourteen_day_interval(breadth):
    """
    A fifteen-day-old study and a study dated after the injection are both refused by
    the same code, while a gap of exactly fourteen days books successfully.

    The PRD states both bounds in one sentence: "It must also be fresh relative to the
    injection: the difference between `encounter_datetime` and the study's
    `study_datetime` must be at least zero and no more than fourteen days, so an
    encounter dated *before* its own imaging study is just as invalid as one dated more
    than two weeks after it. Either failure is `ERR_IMAGING_STUDY_STALE` (HTTP 422)."
    Only the accepted booking touches the plan, because "The plan's `version` advances
    by 1" is a consequence of creation, and a rejected creation leaves the row alone:
    "no vial is ever reserved by a request that goes on to fail."

    Design: Corner/validations/corner_imaging_validity_window_rejects_a_stale_or_future_study
    """
    breadth.pol_np_ref
    breadth.lot_ref
    baseline = breadth.img_np
    plan = breadth.plan_np_active
    injector = specialist_headers(breadth.cl1["id"])

    future_study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=breadth.pt_np["id"],
        eye="OD",
        study_datetime="2026-08-20T00:00:00Z",
        central_subfield_thickness_um=410,
        intraretinal_fluid=True,
        va_letter_score=57,
    )

    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=baseline["id"],
                encounter_datetime="2026-08-16T00:00:00Z",
                expected_treatment_plan_version=plan["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_IMAGING_STUDY_STALE,
        422,
    )
    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=future_study["id"],
                encounter_datetime="2026-08-15T00:00:00Z",
                expected_treatment_plan_version=plan["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_IMAGING_STUDY_STALE,
        422,
    )
    assert breadth.read_plan(plan["id"])["version"] == plan["version"]

    booked = validate_success(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=baseline["id"],
                encounter_datetime="2026-08-15T00:00:00Z",
                expected_treatment_plan_version=plan["version"],
            ),
            injector,
        ),
        201,
    )
    assert booked["status"] == "DRAFT"
    assert breadth.read_plan(plan["id"])["version"] == plan["version"] + 1


def test_the_documentation_and_attestation_gates_fire_in_their_declared_order(breadth):
    """
    An over-fill dose and a zero dose share one code, an unconfirmed prep has its own,
    and on attestation the segregation rule speaks before the wastage comparison even
    though the injector also brought the wrong volume.

    The dose bound is two-sided: "the dose must be physically possible: strictly greater
    than zero and no greater than the effective drug's `vial_fill_ml`, either violation
    being `ERR_DOSE_EXCEEDS_VIAL_FILL` (HTTP 422)", and the prep flag "must be true or
    the request is `ERR_PREP_ATTESTATION_REQUIRED` (HTTP 422)".  Attestation is guarded
    twice over: "The attester must be a different clinician from the injector: an acting
    `X-User-ID` equal to the encounter's `clinician_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)", and "the witnessed figure must agree with
    the computed one: `attested_wasted_ml` must equal the encounter's `wasted_ml` to
    three decimal places, a disagreement being `ERR_ATTESTED_WASTAGE_MISMATCH` (HTTP
    422)."  The precedence between them is declared: step "9. The wastage attester is not
    the injecting clinician — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)" runs long
    before step "30." reaches the volume.  The computed figure is 0.21 ml, since
    "`wasted_ml` is the effective drug's `vial_fill_ml` less `administered_dose_ml`,
    rounded half up to three decimal places".

    Design: Corner/validations/corner_documentation_gates_reject_dose_prep_and_wastage_errors_in_priority_order
    """
    encounter = breadth.enc_np
    injector = specialist_headers(breadth.cl1["id"])
    witness = specialist_headers(breadth.cl2["id"])

    validate_error(
        breadth.api.document_injection_encounter(
            encounter["id"],
            f.document_payload(administered_dose_ml=0.3, post_injection_iop_mmhg=17),
            injector,
        ),
        ApiErrorId.ERR_DOSE_EXCEEDS_VIAL_FILL,
        422,
    )
    validate_error(
        breadth.api.document_injection_encounter(
            encounter["id"],
            f.document_payload(administered_dose_ml=0, post_injection_iop_mmhg=17),
            injector,
        ),
        ApiErrorId.ERR_DOSE_EXCEEDS_VIAL_FILL,
        422,
    )
    validate_error(
        breadth.api.document_injection_encounter(
            encounter["id"],
            f.document_payload(
                administered_dose_ml=0.06,
                injection_site_prep_confirmed=False,
                post_injection_iop_mmhg=17,
            ),
            injector,
        ),
        ApiErrorId.ERR_PREP_ATTESTATION_REQUIRED,
        422,
    )

    documented = validate_success(
        breadth.api.document_injection_encounter(
            encounter["id"],
            f.document_payload(administered_dose_ml=0.06, post_injection_iop_mmhg=17),
            injector,
        ),
        200,
    )
    assert documented["status"] == "DOCUMENTED"
    assert round(documented["wasted_ml"], 3) == 0.21
    assert breadth.read_vial(encounter["vial_id"])["status"] == "ADMINISTERED"
    assert_vial_counters(
        breadth.read_lot(breadth.lot_ref["id"]), vials_administered=1, vials_on_hand=4
    )

    validate_error(
        breadth.api.attest_wastage(
            encounter["id"], f.attest_payload(attested_wasted_ml=0.2), injector
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        breadth.api.attest_wastage(
            encounter["id"], f.attest_payload(attested_wasted_ml=0.2), witness
        ),
        ApiErrorId.ERR_ATTESTED_WASTAGE_MISMATCH,
        422,
    )

    attested = validate_success(
        breadth.api.attest_wastage(
            encounter["id"], f.attest_payload(attested_wasted_ml=0.21), witness
        ),
        200,
    )
    assert attested["status"] == "ATTESTED"
    assert attested["attested_by_clinician_id"] == breadth.cl2["id"]


def test_a_missing_policy_and_an_excluded_policy_are_two_different_answers(breadth):
    """
    A payer with no policy for the product refuses the booking with a 409, a payer
    whose policy exists but excludes the product refuses it with a 422, and neither
    refusal touches the stock that was available to both.

    The PRD separates silence from refusal, in that order: "the coverage policy for
    the patient's payer paired with that product must exist — its absence is
    `ERR_PAYER_POLICY_MISSING` (HTTP 409) — and its `coverage_tier` must not be
    `EXCLUDED`, an exclusion being `ERR_DRUG_EXCLUDED_BY_PAYER` (HTTP 422)."  The
    exclusion is a legitimate tier, since a policy names "a `coverage_tier` of
    `PREFERRED`, `NON_PREFERRED` or `EXCLUDED`".  Both refusals precede the vial step,
    which happens "Last of all, and only once every preceding gate has passed", and
    "no vial is ever reserved by a request that goes on to fail."

    Design: Corner/validations/corner_coverage_gates_separate_a_missing_policy_from_an_excluded_drug
    """
    drug = breadth.drug_ref
    lot = breadth.lot_ref
    injector = specialist_headers(breadth.cl1["id"])

    uncovered_payer = breadth.payer(
        name="Ridgeline Regional",
        payer_type="COMMERCIAL",
        coinsurance_rate=0.2,
        pa_required=False,
        biosimilar_preference="NONE",
        appeal_window_days=60,
    )
    uncovered_patient = breadth.patient(
        mrn="MRN-2031",
        full_name="Rita Duval",
        payer_id=uncovered_payer["id"],
        member_id="RID-31",
        notification_channel="EMAIL",
        contact_point="rita.duval@example.test",
    )
    uncovered_study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=uncovered_patient["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=405,
        intraretinal_fluid=True,
        va_letter_score=60,
    )
    uncovered_plan = breadth.plan(
        clinician_id=breadth.cl1["id"],
        patient_id=uncovered_patient["id"],
        drug_id=drug["id"],
        eye="OD",
    )
    uncovered_active = breadth.activate_plan(
        uncovered_plan["id"],
        clinician_id=breadth.cl1["id"],
        baseline_imaging_study_id=uncovered_study["id"],
    )

    excluding_payer = breadth.payer(
        name="Basin Exclusive Health",
        payer_type="COMMERCIAL",
        coinsurance_rate=0.2,
        pa_required=False,
        biosimilar_preference="NONE",
        appeal_window_days=60,
    )
    breadth.policy(
        payer_id=excluding_payer["id"],
        drug_id=drug["id"],
        coverage_tier="EXCLUDED",
        drug_allowed_cents_per_billing_unit=0,
        admin_allowed_cents=0,
        wastage_reimbursed=False,
        pa_required=False,
    )
    excluded_patient = breadth.patient(
        mrn="MRN-2032",
        full_name="Eli Okafor",
        payer_id=excluding_payer["id"],
        member_id="BAS-32",
        notification_channel="SMS",
        contact_point="+15550112032",
    )
    excluded_study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=excluded_patient["id"],
        eye="OS",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=390,
        subretinal_fluid=True,
        va_letter_score=62,
    )
    excluded_plan = breadth.plan(
        clinician_id=breadth.cl1["id"],
        patient_id=excluded_patient["id"],
        drug_id=drug["id"],
        eye="OS",
    )
    excluded_active = breadth.activate_plan(
        excluded_plan["id"],
        clinician_id=breadth.cl1["id"],
        baseline_imaging_study_id=excluded_study["id"],
    )

    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=uncovered_plan["id"],
                imaging_study_id=uncovered_study["id"],
                encounter_datetime="2026-08-01T09:00:00Z",
                expected_treatment_plan_version=uncovered_active["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_PAYER_POLICY_MISSING,
        409,
    )
    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=excluded_plan["id"],
                imaging_study_id=excluded_study["id"],
                encounter_datetime="2026-08-01T09:30:00Z",
                expected_treatment_plan_version=excluded_active["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_DRUG_EXCLUDED_BY_PAYER,
        422,
    )

    assert_vial_counters(breadth.read_lot(lot["id"]), vials_on_hand=5, vials_reserved=0)

    for plan, activated in (
        (uncovered_plan, uncovered_active),
        (excluded_plan, excluded_active),
    ):
        settled = breadth.read_plan(plan["id"])
        assert settled["status"] == "LOADING"
        assert settled["version"] == activated["version"]


def test_the_lot_number_key_is_scoped_to_its_drug_and_the_lot_state_gate_pre_empts_the_recall_guard(
    breadth, tech, admin
):
    """
    The same lot number is a duplicate under one drug and a fresh lot under another,
    quarantine and release each refuse the wrong starting state, and once the lot is
    recalled the state gate answers before the open-recall guard.

    The key is scoped: a tech supplies "the manufacturer's `lot_number` (3 to 24
    characters, unique within that drug — a repeat is `ERR_DUPLICATE_LOT_NUMBER`, HTTP
    409)".  Both inventory holds are two-way gated — "Quarantining a lot that is not
    `AVAILABLE` is `ERR_LOT_STATE_INVALID` (HTTP 409)", while release demands the
    opposite: "The lot must be `QUARANTINED`, no recall on that lot may exist in any
    status other than `CLOSED` — an open recall makes release impossible and is rejected
    with `ERR_RECALL_ALREADY_OPEN` (HTTP 409) — and the lot's `expiration_date` must be
    strictly after the logical clock".  A release restores the shelf: "every vial of the
    lot that is `QUARANTINED` **and** whose `reserved_for_encounter_id` is null returns
    to `IN_STOCK`".  A recall is singular — "At most one non-`CLOSED` recall may exist
    per lot; a second is `ERR_RECALL_ALREADY_OPEN` (HTTP 409)" — and it makes the lot
    terminal: "the lot moves to `RECALLED`, which is terminal".  The last two calls each
    break both rules at once, and the declared order decides which one speaks: step "13.
    The target resource is in a state the requested transition allows" runs well ahead of
    step "40. The lot has no recall in any status other than `CLOSED`", so a `RECALLED`
    lot answers with its state error on both the second recall and the release.

    Design: Corner/validations/corner_lot_uniqueness_and_lot_state_gates_including_a_pre_empted_recall_guard
    """
    drug = breadth.drug_ref
    other_drug = breadth.drug_bio_a
    lot = breadth.lot_ref

    validate_error(
        breadth.api.create_drug_lot(
            f.lot_payload(
                drug_id=drug["id"],
                lot_number="RX-9001",
                expiration_date="2027-09-30T00:00:00Z",
                received_date="2026-07-15T00:00:00Z",
                unit_acquisition_cost_cents=132000,
                vials_received=2,
            ),
            tech,
        ),
        ApiErrorId.ERR_DUPLICATE_LOT_NUMBER,
        409,
    )

    cross_drug = validate_success(
        breadth.api.create_drug_lot(
            f.lot_payload(
                drug_id=other_drug["id"],
                lot_number="RX-9001",
                expiration_date="2027-09-30T00:00:00Z",
                received_date="2026-07-15T00:00:00Z",
                unit_acquisition_cost_cents=96000,
                vials_received=2,
            ),
            tech,
        ),
        201,
    )
    assert cross_drug["status"] == "AVAILABLE"
    assert cross_drug["lot_number"] == "RX-9001"
    assert cross_drug["drug_id"] == other_drug["id"]

    validate_error(
        breadth.api.release_drug_lot(lot["id"], {}, compliance_headers()),
        ApiErrorId.ERR_LOT_STATE_INVALID,
        409,
    )

    quarantined = validate_success(
        breadth.api.quarantine_drug_lot(
            lot["id"],
            f.quarantine_payload(quarantine_reason="Visible particulate reported by pharmacy"),
            tech,
        ),
        200,
    )
    assert quarantined["status"] == "QUARANTINED"

    validate_error(
        breadth.api.quarantine_drug_lot(
            lot["id"], f.quarantine_payload(quarantine_reason="Duplicate quarantine attempt"), tech
        ),
        ApiErrorId.ERR_LOT_STATE_INVALID,
        409,
    )

    released = validate_success(
        breadth.api.release_drug_lot(lot["id"], {}, compliance_headers()),
        200,
    )
    assert released["status"] == "AVAILABLE"
    assert released["quarantine_reason"] is None
    assert_vial_counters(released, vials_on_hand=5, vials_quarantined=0)

    vials, vial_meta = validate_list(
        breadth.api.list_vials(tech, f.page_params(drug_lot_id=lot["id"], limit=100))
    )
    assert vial_meta["total_count"] == 5
    assert {row["status"] for row in vials} == {"IN_STOCK"}

    recall = validate_success(
        breadth.api.create_lot_recall(
            f.recall_payload(
                drug_lot_id=lot["id"],
                recall_class="CLASS_III",
                reason="Manufacturer label defect",
            ),
            compliance_headers(),
        ),
        201,
    )
    assert recall["status"] == "INITIATED"

    validate_error(
        breadth.api.create_lot_recall(
            f.recall_payload(
                drug_lot_id=lot["id"],
                recall_class="CLASS_II",
                reason="Second recall on the same lot",
            ),
            compliance_headers(),
        ),
        ApiErrorId.ERR_LOT_STATE_INVALID,
        409,
    )

    validate_error(
        breadth.api.release_drug_lot(lot["id"], {}, compliance_headers()),
        ApiErrorId.ERR_LOT_STATE_INVALID,
        409,
    )
    assert breadth.read_lot(lot["id"])["status"] == "RECALLED"


def test_a_quarantine_between_reservation_and_documentation_splits_into_two_errors(
    breadth, tech
):
    """
    The vial already reserved cannot be injected because its lot is no longer
    available, while a brand-new booking cannot find a vial at all.

    A plain quarantine spares reservations: "every one of its vials that was `IN_STOCK`
    moves to `QUARANTINED` in the same operation ... Vials already `RESERVED` are left
    alone by a plain quarantine — only a recall reaches into reservations."  That leaves
    the two rejections keyed on different things.  Documentation checks the parent lot:
    "The reserved vial's lot must still be `AVAILABLE` at this moment — a lot
    quarantined or recalled in the window between reservation and documentation blocks
    the injection with `ERR_LOT_NOT_AVAILABLE` (HTTP 409)."  A fresh booking instead
    finds an empty pool, since eligibility requires "every vial whose own status is
    `IN_STOCK`, whose lot's status is `AVAILABLE`" and "An empty pool is
    `ERR_NO_ELIGIBLE_VIAL` (HTTP 409)".  The second booking is placed a full cadence
    later so that every earlier gate is satisfied and selection is genuinely the first
    failure: the gap "must be at least the effective drug's `min_interval_days`, with the
    boundary inclusive so a gap exactly equal to the minimum is allowed", and the study
    is "at least zero and no more than fourteen days" old.

    Design: Corner/validations/corner_quarantining_a_lot_blocks_documentation_and_new_selection_by_two_different_errors
    """
    encounter = breadth.enc_np
    lot = breadth.lot_ref
    injector = specialist_headers(breadth.cl1["id"])

    held = validate_success(
        breadth.api.quarantine_drug_lot(
            lot["id"],
            f.quarantine_payload(quarantine_reason="Cold-chain excursion during transit"),
            tech,
        ),
        200,
    )
    assert held["status"] == "QUARANTINED"
    assert_vial_counters(held, vials_quarantined=4, vials_reserved=1, vials_on_hand=0)

    validate_error(
        breadth.api.document_injection_encounter(
            encounter["id"],
            f.document_payload(administered_dose_ml=0.06, post_injection_iop_mmhg=15),
            injector,
        ),
        ApiErrorId.ERR_LOT_NOT_AVAILABLE,
        409,
    )
    assert breadth.read_encounter(encounter["id"])["status"] == "DRAFT"

    reserved, reserved_meta = validate_list(
        breadth.api.list_vials(tech, f.page_params(drug_lot_id=lot["id"], status="RESERVED"))
    )
    assert reserved_meta["total_count"] == 1
    assert reserved[0]["status"] == "RESERVED"
    assert reserved[0]["reserved_for_encounter_id"] == encounter["id"]

    fresh_study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=breadth.pt_np["id"],
        eye="OD",
        study_datetime="2026-08-29T08:00:00Z",
        central_subfield_thickness_um=415,
        intraretinal_fluid=True,
        va_letter_score=56,
    )
    guarded = breadth.read_plan(breadth.plan_np["id"])

    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=guarded["id"],
                imaging_study_id=fresh_study["id"],
                encounter_datetime="2026-08-29T09:00:00Z",
                expected_treatment_plan_version=guarded["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_VIAL,
        409,
    )
    assert_vial_counters(
        breadth.read_lot(lot["id"]), vials_quarantined=4, vials_reserved=1, vials_on_hand=0
    )


def test_the_five_unique_keys_the_active_plan_key_and_biosimilar_lineage_are_separate_rules(
    breadth, admin
):
    """
    Five different duplicates all answer with one error id, the fellow eye is a
    different plan key, and biosimilar lineage is refused in both broken shapes.

    The PRD gathers the keys under one code: "exactly one such policy may exist for a
    given pairing — a second attempt at the same `payer_id` and `drug_id` combination is
    rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409), the same error that guards a
    duplicate payer `name`, a duplicate `hcpcs_code`, a duplicate patient `mrn` and a
    duplicate clinician `npi`."  The plan key is narrower: "at most one plan per patient
    and eye may be open at a time: if that patient already has a plan for the same `eye`
    whose status is `DRAFT`, `LOADING`, `MAINTENANCE`, `INTENSIFIED` or `SUSPENDED`,
    creation is rejected with `ERR_DUPLICATE_ACTIVE_PLAN` (HTTP 409)."  Lineage is
    checked both ways: "a supplied `reference_drug_id` must resolve to a drug whose own
    `is_biosimilar` is false, and a drug declaring `is_biosimilar` true must supply a
    non-null `reference_drug_id`. Either violation is rejected with
    `ERR_INVALID_REFERENCE_DRUG` (HTTP 422)".

    Design: Corner/validations/corner_unique_keys_and_reference_drug_integrity_are_enforced_per_key
    """
    breadth.pol_np_ref
    breadth.lot_ref
    breadth.plan_np_active
    biosimilar = breadth.drug_bio_a
    injector = specialist_headers(breadth.cl1["id"])

    duplicates = [
        breadth.api.create_payer(
            f.payer_payload(
                name="Foothill Open Access", payer_type="MEDICARE_ADVANTAGE", coinsurance_rate=0.15
            ),
            admin,
        ),
        breadth.api.create_drug(
            f.drug_payload(
                brand_name="Ranovex Copy",
                hcpcs_code="J2778",
                vial_fill_ml=0.27,
                label_dose_ml=0.06,
                mg_per_ml=40,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=15000,
                min_interval_days=28,
                max_interval_days=112,
            ),
            admin,
        ),
        breadth.api.create_patient(
            f.patient_payload(
                mrn="MRN-2003",
                full_name="Nina Prakash Duplicate",
                payer_id=breadth.pay_np["id"],
                member_id="FOO-99",
                contact_point="dup@example.test",
            ),
            admin,
        ),
        breadth.api.create_clinician(
            f.clinician_payload(full_name="Dr Alina Reyes Duplicate", npi="2000000001"),
            admin,
        ),
        breadth.api.create_payer_drug_policy(
            f.policy_payload(
                payer_id=breadth.pay_np["id"],
                drug_id=breadth.drug_ref["id"],
                coverage_tier="NON_PREFERRED",
                drug_allowed_cents_per_billing_unit=13000,
                admin_allowed_cents=9000,
            ),
            admin,
        ),
    ]
    for response in duplicates:
        validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE, 409)

    validate_error(
        breadth.api.create_treatment_plan(
            f.plan_payload(
                patient_id=breadth.pt_np["id"],
                drug_id=breadth.drug_ref["id"],
                eye="OD",
                loading_doses_required=3,
            ),
            injector,
        ),
        ApiErrorId.ERR_DUPLICATE_ACTIVE_PLAN,
        409,
    )

    fellow = validate_success(
        breadth.api.create_treatment_plan(
            f.plan_payload(
                patient_id=breadth.pt_np["id"],
                drug_id=breadth.drug_ref["id"],
                eye="OS",
                loading_doses_required=3,
            ),
            injector,
        ),
        201,
    )
    assert fellow["status"] == "DRAFT"
    assert fellow["eye"] == "OS"

    validate_error(
        breadth.api.create_drug(
            f.drug_payload(
                brand_name="Orphan Biosimilar",
                hcpcs_code="Q5301",
                vial_fill_ml=0.27,
                label_dose_ml=0.06,
                mg_per_ml=40,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=9000,
                min_interval_days=28,
                max_interval_days=112,
                is_biosimilar=True,
            ),
            admin,
        ),
        ApiErrorId.ERR_INVALID_REFERENCE_DRUG,
        422,
    )
    validate_error(
        breadth.api.create_drug(
            f.biosimilar_payload(
                reference_drug_id=biosimilar["id"],
                brand_name="Biosimilar Of A Biosimilar",
                hcpcs_code="Q5302",
                vial_fill_ml=0.27,
                label_dose_ml=0.06,
                mg_per_ml=40,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=8500,
                min_interval_days=28,
                max_interval_days=112,
            ),
            admin,
        ),
        ApiErrorId.ERR_INVALID_REFERENCE_DRUG,
        422,
    )


def test_step_therapy_is_judged_at_submission_and_not_at_planning(breadth, admin, billing):
    """
    A treatment-naive patient may be planned and authorised on a step-therapy product
    right up to the submission, which is the only call that fails.

    The gate lives on the submit endpoint: step "31. Counted prerequisite-drug failures
    reach the policy's required number — otherwise `ERR_STEP_THERAPY_NOT_SATISFIED`
    (422). Applies to prior-authorization submission."  The count is taken there and
    nowhere else: "The count is taken fresh at every submission ... The gate then
    requires the count to be at least the policy's `required_prior_failures`; a
    shortfall is rejected with `ERR_STEP_THERAPY_NOT_SATISFIED` (HTTP 422)."  Because
    the request never lands, the authorization keeps its birth figures — "The new
    authorization begins in `DRAFT` with `injections_used` at 0, `submission_count` at
    0, `step_therapy_failures_documented` at 0" — where a successful first submission
    would have "increases `submission_count` by 1".

    Design: Corner/validations/corner_step_therapy_blocks_submission_when_no_prerequisite_failure_is_documented
    """
    reference = breadth.drug_ref
    step_payer = breadth.payer(
        name="Summit Step Health",
        payer_type="COMMERCIAL",
        coinsurance_rate=0.2,
        pa_required=True,
        biosimilar_preference="NONE",
        appeal_window_days=60,
    )
    target = validate_success(
        breadth.api.create_drug(
            f.drug_payload(
                brand_name="Zaltruvex",
                hcpcs_code="J2779",
                vial_fill_ml=0.5,
                label_dose_ml=0.05,
                mg_per_ml=100,
                billing_unit_mg=1,
                asp_cents_per_billing_unit=20000,
                min_interval_days=28,
                max_interval_days=112,
                is_biosimilar=False,
            ),
            admin,
        ),
        201,
    )
    breadth.policy(
        payer_id=step_payer["id"],
        drug_id=reference["id"],
        coverage_tier="PREFERRED",
        drug_allowed_cents_per_billing_unit=14000,
        admin_allowed_cents=10000,
        wastage_reimbursed=True,
        pa_required=False,
        pa_validity_days=180,
        pa_max_injections=3,
    )
    breadth.policy(
        payer_id=step_payer["id"],
        drug_id=target["id"],
        coverage_tier="PREFERRED",
        drug_allowed_cents_per_billing_unit=20000,
        admin_allowed_cents=10000,
        wastage_reimbursed=True,
        pa_required=True,
        pa_validity_days=180,
        pa_max_injections=3,
        step_therapy_prerequisite_drug_id=reference["id"],
        required_prior_failures=1,
    )

    naive_patient = breadth.patient(
        mrn="MRN-2041",
        full_name="Hana Iversen",
        payer_id=step_payer["id"],
        member_id="SUM-41",
        contact_point="hana.iversen@example.test",
        notification_channel="EMAIL",
    )
    study = breadth.imaging(
        clinician_id=breadth.cl1["id"],
        patient_id=naive_patient["id"],
        eye="OD",
        study_datetime=breadth.CLOCK,
        central_subfield_thickness_um=480,
        intraretinal_fluid=True,
        subretinal_fluid=True,
        va_letter_score=48,
    )
    plan = breadth.plan(
        clinician_id=breadth.cl1["id"],
        patient_id=naive_patient["id"],
        drug_id=target["id"],
        eye="OD",
        loading_doses_required=3,
    )
    activated = breadth.activate_plan(
        plan["id"], clinician_id=breadth.cl1["id"], baseline_imaging_study_id=study["id"]
    )
    assert activated["status"] == "LOADING"

    authorization = breadth.authorization(
        treatment_plan_id=plan["id"],
        expected_treatment_plan_version=activated["version"],
    )
    assert authorization["status"] == "DRAFT"

    validate_error(
        breadth.api.submit_prior_authorization(
            authorization["id"],
            f.authorization_submit_payload(
                clinical_justification="First-line request for the step-therapy drug"
            ),
            billing,
        ),
        ApiErrorId.ERR_STEP_THERAPY_NOT_SATISFIED,
        422,
    )

    settled = breadth.read_authorization(authorization["id"])
    assert settled["status"] == "DRAFT"
    assert settled["submission_count"] == 0
    assert settled["step_therapy_failures_documented"] == 0


def test_the_assistance_gates_sit_on_different_calls_of_the_enrollment_lifecycle(
    breadth, billing
):
    """
    A copay card is refused at creation for the federally covered patient but accepted
    for the commercial one, while the one-active-programme rule bites only at approval.

    The PRD puts each gate on its own call: an enrollment "is born `PENDING` with
    `benefit_used_cents` of 0 and `termination_reason` null. A `program_type` of
    `MANUFACTURER_COPAY_CARD` is refused outright for a patient whose payer carries
    `federal_program` true, with `ERR_COPAY_CARD_FEDERAL_INELIGIBLE` (HTTP 422).
    Approval moves `PENDING → ACTIVE` and changes nothing else, but requires that the
    patient have no other enrollment already in `ACTIVE`; a second one is
    `ERR_DUPLICATE_ACTIVE_ENROLLMENT` (HTTP 409). Termination is available from
    `PENDING`, `ACTIVE` or `EXHAUSTED`, stores `termination_reason`, and is terminal ...
    Approving anything that is not `PENDING`, or terminating something already
    `TERMINATED` or `EXPIRED`, is `ERR_ENROLLMENT_STATE_INVALID` (HTTP 409)."  Which
    patient is federal is not declared but derived: `federal_program` "is true when
    `payer_type` is `MEDICARE_PART_B`, `MEDICARE_ADVANTAGE` or `MEDICAID`, and false
    when `payer_type` is `COMMERCIAL`".

    Design: Corner/validations/corner_assistance_enrollment_gates_cover_federal_eligibility_and_one_active_program
    """
    federal_patient = breadth.pt_mcr
    commercial_patient = breadth.pt_np

    validate_error(
        breadth.api.create_assistance_enrollment(
            f.enrollment_payload(
                patient_id=federal_patient["id"],
                program_type="MANUFACTURER_COPAY_CARD",
                annual_benefit_cents=1000000,
                per_encounter_cap_cents=200000,
                effective_date="2026-08-01T00:00:00Z",
                expiration_date="2027-07-31T00:00:00Z",
            ),
            billing,
        ),
        ApiErrorId.ERR_COPAY_CARD_FEDERAL_INELIGIBLE,
        422,
    )

    foundation = validate_success(
        breadth.api.create_assistance_enrollment(
            f.enrollment_payload(
                patient_id=federal_patient["id"],
                program_type="INDEPENDENT_FOUNDATION",
                annual_benefit_cents=1000000,
                per_encounter_cap_cents=200000,
                effective_date="2026-08-01T00:00:00Z",
                expiration_date="2027-07-31T00:00:00Z",
            ),
            billing,
        ),
        201,
    )
    assert foundation["status"] == "PENDING"
    assert foundation["benefit_used_cents"] == 0
    assert foundation["termination_reason"] is None

    activated = validate_success(
        breadth.api.approve_assistance_enrollment(foundation["id"], {}, billing), 200
    )
    assert activated["status"] == "ACTIVE"

    validate_error(
        breadth.api.approve_assistance_enrollment(foundation["id"], {}, billing),
        ApiErrorId.ERR_ENROLLMENT_STATE_INVALID,
        409,
    )

    second = validate_success(
        breadth.api.create_assistance_enrollment(
            f.enrollment_payload(
                patient_id=federal_patient["id"],
                program_type="FREE_DRUG_PAP",
                annual_benefit_cents=500000,
                per_encounter_cap_cents=100000,
                effective_date="2026-08-01T00:00:00Z",
                expiration_date="2027-07-31T00:00:00Z",
            ),
            billing,
        ),
        201,
    )
    assert second["status"] == "PENDING"

    validate_error(
        breadth.api.approve_assistance_enrollment(second["id"], {}, billing),
        ApiErrorId.ERR_DUPLICATE_ACTIVE_ENROLLMENT,
        409,
    )
    assert breadth.read_enrollment(second["id"])["status"] == "PENDING"

    terminated = validate_success(
        breadth.api.terminate_assistance_enrollment(
            second["id"],
            f.enrollment_terminate_payload(
                termination_reason="Filed in error while the foundation grant is active"
            ),
            billing,
        ),
        200,
    )
    assert terminated["status"] == "TERMINATED"

    validate_error(
        breadth.api.terminate_assistance_enrollment(
            second["id"], f.enrollment_terminate_payload(termination_reason="Second attempt"), billing
        ),
        ApiErrorId.ERR_ENROLLMENT_STATE_INVALID,
        409,
    )

    commercial_card = validate_success(
        breadth.api.create_assistance_enrollment(
            f.enrollment_payload(
                patient_id=commercial_patient["id"],
                program_type="MANUFACTURER_COPAY_CARD",
                annual_benefit_cents=1000000,
                per_encounter_cap_cents=200000,
                effective_date="2026-08-01T00:00:00Z",
                expiration_date="2027-07-31T00:00:00Z",
            ),
            billing,
        ),
        201,
    )
    assert commercial_card["status"] == "PENDING"


def test_three_independent_guards_surround_one_endophthalmitis_report(breadth):
    """
    Review out of turn is a state error, the injecting clinician may not clear their own
    event, resumption is blocked until the event is terminal, and the unrelated verdict
    fires no cascade of its own.

    Filing writes the derived gap: "`days_post_injection` is written as the whole days
    from the encounter's `encounter_datetime` to `onset_datetime`, truncated downward.
    The event is born `REPORTED`".  Review has its own order: "A `ComplianceOfficer`
    opens the investigation, moving `REPORTED → UNDER_INVESTIGATION` ... Adjudication is
    then a `RetinaSpecialist` action carrying `outcome` and `adjudication_note`,
    permitted only from `UNDER_INVESTIGATION`; anything else is
    `ERR_ADVERSE_EVENT_STATE_INVALID` (HTTP 409). The adjudicator may not be the
    clinician who gave the injection: an acting `X-User-ID` equal to the source
    encounter's `clinician_id` is refused with `ERR_ADJUDICATOR_IS_INJECTOR` (HTTP
    403)."  The plan is held shut meanwhile: resumption "is blocked while any adverse
    event linked to one of the plan's encounters is still `REPORTED` or
    `UNDER_INVESTIGATION` — that rejection is `ERR_OPEN_ADVERSE_EVENT` (HTTP 409)", and
    on success it "moves the plan `SUSPENDED → MAINTENANCE`".  The verdict taken here is
    the inert one: "An `outcome` of `UNRELATED` moves the event to
    `ADJUDICATED_UNRELATED` and fires **nothing else**: the treatment plan is left
    exactly as it was".

    Design: Corner/validations/corner_adverse_event_gates_block_out_of_order_review_self_adjudication_and_resumption
    """
    encounter = breadth.enc_np_attested
    injector = specialist_headers(breadth.cl1["id"])
    reviewer = specialist_headers(breadth.cl2["id"])
    plan_id = breadth.plan_np["id"]

    event = validate_success(
        breadth.api.create_adverse_event(
            f.adverse_event_payload(
                injection_encounter_id=encounter["id"],
                event_type="ENDOPHTHALMITIS",
                onset_datetime="2026-08-06T09:00:00Z",
                severity="SEVERE",
                culture_result="POSITIVE",
            ),
            injector,
        ),
        201,
    )
    assert event["status"] == "REPORTED"
    assert event["reported_by_clinician_id"] == breadth.cl1["id"]
    assert event["days_post_injection"] == 5

    suspended = validate_success(
        breadth.api.suspend_treatment_plan(
            plan_id, f.plan_suspend_payload(suspension_reason="CLINICIAN_HOLD"), injector
        ),
        200,
    )
    assert suspended["status"] == "SUSPENDED"

    validate_error(
        breadth.api.adjudicate_adverse_event(
            event["id"],
            f.adjudication_payload(
                outcome="UNRELATED", adjudication_note="Premature adjudication attempt"
            ),
            reviewer,
        ),
        ApiErrorId.ERR_ADVERSE_EVENT_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.resume_treatment_plan(plan_id, {}, injector),
        ApiErrorId.ERR_OPEN_ADVERSE_EVENT,
        409,
    )

    investigating = validate_success(
        breadth.api.start_adverse_event_investigation(
            event["id"], {}, compliance_headers(COMPLIANCE_USER_ID)
        ),
        200,
    )
    assert investigating["status"] == "UNDER_INVESTIGATION"

    validate_error(
        breadth.api.start_adverse_event_investigation(
            event["id"], {}, compliance_headers(COMPLIANCE_USER_ID)
        ),
        ApiErrorId.ERR_ADVERSE_EVENT_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.resume_treatment_plan(plan_id, {}, injector),
        ApiErrorId.ERR_OPEN_ADVERSE_EVENT,
        409,
    )
    validate_error(
        breadth.api.adjudicate_adverse_event(
            event["id"],
            f.adjudication_payload(
                outcome="UNRELATED", adjudication_note="Self-adjudication attempt by the injector"
            ),
            injector,
        ),
        ApiErrorId.ERR_ADJUDICATOR_IS_INJECTOR,
        403,
    )

    adjudicated = validate_success(
        breadth.api.adjudicate_adverse_event(
            event["id"],
            f.adjudication_payload(
                outcome="UNRELATED",
                adjudication_note=(
                    "Culture consistent with pre-existing blepharitis, unrelated to the injection"
                ),
            ),
            reviewer,
        ),
        200,
    )
    assert adjudicated["status"] == "ADJUDICATED_UNRELATED"
    assert adjudicated["adjudicated_by_clinician_id"] == breadth.cl2["id"]
    assert breadth.read_plan(plan_id)["status"] == "SUSPENDED"

    resumed = validate_success(breadth.api.resume_treatment_plan(plan_id, {}, injector), 200)
    assert resumed["status"] == "MAINTENANCE"
    assert resumed["suspension_reason"] is None


def test_the_recall_ladder_trips_six_different_guards_on_the_way_to_closed(
    breadth, admin, tech, billing
):
    """
    One recall walked end to end refuses an early shipment, an unsent acknowledgement, a
    stranger's acknowledgement, an over-credit, a closure with the patient still silent,
    a second notification outcome and a closure by its own initiator.

    Each rung is separately guarded.  The tech's step needs the officer's first: "The
    `ComplianceOfficer` sends notifications, moving the recall `INITIATED →
    PATIENTS_NOTIFIED` ... The `PharmacyTech` then ships the return with a
    `carrier_reference`, moving the recall `PATIENTS_NOTIFIED → RETURN_SHIPPED`", and the
    shipment "**freezes** `credit_expected_cents` at `vials_returned_count` multiplied by
    the lot's `unit_acquisition_cost_cents`", after which "the figure may not exceed
    `credit_expected_cents`, and a larger one is `ERR_CREDIT_EXCEEDS_EXPECTED` (HTTP
    422)".  Notifications resolve only from one state and only for their owner: "A
    notification has exactly two terminal outcomes, both reachable only from `SENT` ...
    Only the owning patient may do it — an acting `Patient` whose `X-User-ID` differs
    from the notification's `patient_id` is refused with `ERR_NOT_NOTIFICATION_OWNER`
    (HTTP 403) ... Acknowledging a notification that is still `PENDING`, or acting on one
    that has already reached `ACKNOWLEDGED` or `UNREACHABLE`, is
    `ERR_NOTIFICATION_STATE_INVALID` (HTTP 409)."  Closure carries two more: "Every
    notification must be resolved: `notifications_acknowledged` plus
    `notifications_unreachable` must equal `notifications_required` exactly, and any
    shortfall is `ERR_PATIENT_NOTIFICATIONS_INCOMPLETE` (HTTP 409) ... And the closer
    must not be the initiator: an acting `X-User-ID` equal to `initiated_by_user_id` is
    refused with `ERR_RECALL_CLOSER_CONFLICT` (HTTP 403)."  Steps out of turn are
    `ERR_RECALL_STATE_INVALID`, since "any attempt to take one out of turn is
    `ERR_RECALL_STATE_INVALID` (HTTP 409)".

    Design: Corner/validations/corner_recall_closure_walk_enforces_step_order_credit_ceiling_ownership_and_segregation
    """
    breadth.enc_np_documented
    lot = breadth.lot_ref
    exposed_patient = breadth.pt_np

    stranger = breadth.patient(
        mrn="MRN-2051",
        full_name="Tobias Reff",
        payer_id=breadth.pay_np["id"],
        member_id="FOO-51",
        contact_point="+15550112051",
        notification_channel="SMS",
    )

    recall = validate_success(
        breadth.api.create_lot_recall(
            f.recall_payload(
                drug_lot_id=lot["id"],
                recall_class="CLASS_II",
                reason="Manufacturer sterility investigation",
            ),
            compliance_headers(COMPLIANCE_USER_ID),
        ),
        201,
    )
    assert recall["status"] == "INITIATED"
    assert recall["notifications_required"] == 1
    assert recall["initiated_by_user_id"] == COMPLIANCE_USER_ID
    assert_vial_counters(
        breadth.read_lot(lot["id"]), vials_quarantined=4, vials_administered=1, vials_on_hand=0
    )

    notices, notice_meta = validate_list(
        breadth.api.list_recall_notifications(
            compliance_headers(COMPLIANCE_USER_ID), f.page_params(lot_recall_id=recall["id"])
        )
    )
    assert notice_meta["total_count"] == 1
    notice = notices[0]
    assert notice["status"] == "PENDING"
    assert notice["patient_id"] == exposed_patient["id"]

    validate_error(
        breadth.api.ship_recall_return(
            recall["id"], f.ship_return_payload(carrier_reference="PREMATURE-1"), tech
        ),
        ApiErrorId.ERR_RECALL_STATE_INVALID,
        409,
    )
    validate_error(
        breadth.api.acknowledge_recall_notification(
            notice["id"], {}, patient_headers(exposed_patient["id"])
        ),
        ApiErrorId.ERR_NOTIFICATION_STATE_INVALID,
        409,
    )

    notified = validate_success(
        breadth.api.send_recall_notifications(
            recall["id"], {}, compliance_headers(COMPLIANCE_USER_ID)
        ),
        200,
    )
    assert notified["status"] == "PATIENTS_NOTIFIED"

    validate_error(
        breadth.api.acknowledge_recall_notification(
            notice["id"], {}, patient_headers(stranger["id"])
        ),
        ApiErrorId.ERR_NOT_NOTIFICATION_OWNER,
        403,
    )

    shipped = validate_success(
        breadth.api.ship_recall_return(
            recall["id"], f.ship_return_payload(carrier_reference="RET-778213"), tech
        ),
        200,
    )
    assert shipped["status"] == "RETURN_SHIPPED"
    assert shipped["vials_returned_count"] == 4
    assert shipped["credit_expected_cents"] == 528000

    validate_error(
        breadth.api.reconcile_recall_credit(
            recall["id"], f.reconcile_credit_payload(credit_received_cents=600000), billing
        ),
        ApiErrorId.ERR_CREDIT_EXCEEDS_EXPECTED,
        422,
    )

    reconciled = validate_success(
        breadth.api.reconcile_recall_credit(
            recall["id"], f.reconcile_credit_payload(credit_received_cents=528000), billing
        ),
        200,
    )
    assert reconciled["status"] == "CREDIT_RECONCILED"
    assert reconciled["credit_received_cents"] == 528000

    validate_error(
        breadth.api.close_lot_recall(
            recall["id"],
            f.recall_close_payload(closure_note="Closing before the patient replies"),
            compliance_headers(COMPLIANCE_USER_ID_2),
        ),
        ApiErrorId.ERR_PATIENT_NOTIFICATIONS_INCOMPLETE,
        409,
    )

    acknowledged = validate_success(
        breadth.api.acknowledge_recall_notification(
            notice["id"], {}, patient_headers(exposed_patient["id"])
        ),
        200,
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert_instant_equals(acknowledged["acknowledged_at"], breadth.CLOCK, "acknowledged_at")

    validate_error(
        breadth.api.mark_recall_notification_unreachable(
            notice["id"],
            f.mark_unreachable_payload(
                attempt_note="Late unreachable attempt on an acknowledged notification"
            ),
            compliance_headers(COMPLIANCE_USER_ID),
        ),
        ApiErrorId.ERR_NOTIFICATION_STATE_INVALID,
        409,
    )

    validate_error(
        breadth.api.close_lot_recall(
            recall["id"],
            f.recall_close_payload(closure_note="Closed by the initiating officer"),
            compliance_headers(COMPLIANCE_USER_ID),
        ),
        ApiErrorId.ERR_RECALL_CLOSER_CONFLICT,
        403,
    )

    closed = validate_success(
        breadth.api.close_lot_recall(
            recall["id"],
            f.recall_close_payload(
                closure_note="Return credited in full, patient acknowledged, lot destroyed"
            ),
            compliance_headers(COMPLIANCE_USER_ID_2),
        ),
        200,
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == COMPLIANCE_USER_ID_2


def test_a_recall_on_a_fully_injected_lot_is_stranded_with_nothing_to_send_back(
    breadth, tech
):
    """
    When the single vial of the recalled lot has already been injected there is nothing
    quarantined to ship, so the return step is refused and the recall stops at
    `PATIENTS_NOTIFIED` with no credit ever frozen.

    The shipment carries its own precondition: "the lot must have at least one
    `QUARANTINED` vial or the step is refused with `ERR_NO_QUARANTINED_VIALS` (HTTP
    409)", and only that step freezes money, "**freezes** `credit_expected_cents` at
    `vials_returned_count` multiplied by the lot's `unit_acquisition_cost_cents`".  The
    recall itself opened normally — "the lot moves to `RECALLED`, which is terminal; both
    its `IN_STOCK` and its `RESERVED` vials move to `QUARANTINED`", of which this lot has
    neither — and its deadline follows the class table: "`notification_deadline_date` is
    computed as the logical clock plus the class notice period: three days for `CLASS_I`,
    ten for `CLASS_II`, thirty for `CLASS_III`".  The opening figures are declared:
    "`notifications_acknowledged`, `notifications_unreachable` and `vials_returned_count`
    all start at 0, `credit_expected_cents` starts at 0".

    Design: Corner/validations/corner_a_fully_dispensed_lot_recall_cannot_ship_a_return
    """
    breadth.pol_np_ref
    solo_lot = breadth.lot(
        drug_id=breadth.drug_ref["id"],
        lot_number="RX-9020",
        expiration_date="2027-03-31T00:00:00Z",
        received_date="2026-07-20T00:00:00Z",
        unit_acquisition_cost_cents=131000,
        vials_received=1,
    )
    plan = breadth.plan_np_active
    encounter = breadth.encounter(
        clinician_id=breadth.cl1["id"],
        treatment_plan_id=plan["id"],
        imaging_study_id=breadth.img_np["id"],
        encounter_datetime=breadth.ENCOUNTER_AT,
        expected_treatment_plan_version=plan["version"],
    )
    breadth.document(
        encounter["id"],
        clinician_id=breadth.cl1["id"],
        administered_dose_ml=0.06,
        post_injection_iop_mmhg=17,
    )
    assert_vial_counters(
        breadth.read_lot(solo_lot["id"]), vials_administered=1, vials_on_hand=0, vials_reserved=0
    )

    recall = validate_success(
        breadth.api.create_lot_recall(
            f.recall_payload(
                drug_lot_id=solo_lot["id"],
                recall_class="CLASS_I",
                reason="Confirmed sterility failure at the fill site",
            ),
            compliance_headers(COMPLIANCE_USER_ID_3),
        ),
        201,
    )
    assert recall["notifications_required"] == 1
    assert_instant_equals(
        recall["notification_deadline_date"],
        "2026-08-04T00:00:00Z",
        "notification_deadline_date",
    )

    notified = validate_success(
        breadth.api.send_recall_notifications(
            recall["id"], {}, compliance_headers(COMPLIANCE_USER_ID_3)
        ),
        200,
    )
    assert notified["status"] == "PATIENTS_NOTIFIED"

    validate_error(
        breadth.api.ship_recall_return(
            recall["id"], f.ship_return_payload(carrier_reference="RET-000000"), tech
        ),
        ApiErrorId.ERR_NO_QUARANTINED_VIALS,
        409,
    )

    stranded = breadth.read_recall(recall["id"])
    assert stranded["status"] == "PATIENTS_NOTIFIED"
    assert stranded["vials_returned_count"] == 0
    assert stranded["credit_expected_cents"] == 0

    settled_lot = breadth.read_lot(solo_lot["id"])
    assert settled_lot["status"] == "RECALLED"
    assert_vial_counters(settled_lot, vials_administered=1, vials_quarantined=0, vials_returned=0)
