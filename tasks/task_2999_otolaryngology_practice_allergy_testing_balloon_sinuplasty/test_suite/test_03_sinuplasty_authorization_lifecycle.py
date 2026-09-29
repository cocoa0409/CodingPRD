"""Balloon-sinuplasty candidacy evaluation, the payer revision loop, and the booking gate that reads a case's lifecycle state."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as check
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as SETUP
from test_helpers import test_users as USERS

# The documentation both variant tests file: an intranasal-corticosteroid course
# of fourteen days, a six-day gap, then an antibiotic course of fourteen days.
GAPPED_FOURTEEN_DAY_COURSES = [
    F.therapy_course(C.THERAPY_INCS, "2026-06-01", "2026-06-14"),
    F.therapy_course(C.THERAPY_ABX, "2026-06-20", "2026-07-03"),
]

# Three criteria that survive the strict admissibility cross-check against the
# two courses above, so the two variants can differ on the days figure alone.
GAPPED_CRITERIA_CODES = [
    C.CRITERION_CT_OPACIFICATION,
    C.CRITERION_FAILED_INCS,
    C.CRITERION_FAILED_ABX,
]


def test_policy_strict_candidacy_reads_only_the_longest_merged_span(api):
    """PRD 3.6: "Under **`POLICY_STRICT`**, which governs whenever the plan's
    `requires_prior_auth` is true, the verdict consults
    `contiguous_management_days` — the longest single merged span only, so
    separate courses do not add up."

    Design: Difficulty/dual_variant_calc/candidacy_variant_divergence_on_sinuplasty_case
    """
    # A plan that demands prior authorization, so its cases evaluate strictly.
    policy = SETUP.create_policy(
        api,
        plan_code="STRICT-2999",
        payer_name="Strict Mutual",
        requires_prior_auth=True,
        min_medical_management_days=28,
        requires_ct_within_months=12,
        min_documented_criteria=3,
        covered_pct_bps=8000,
        observation_floor_minutes=20,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10001),
        full_name="Strict Plan Patient",
        date_of_birth="1988-06-20",
        epinephrine_on_file=True,
        prior_systemic_reaction_count=0,
    )

    # A bilateral case documented with two courses that the six-day gap keeps apart.
    case = SETUP.create_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_BILATERAL,
        sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
    )
    documented = SETUP.document_case(
        api,
        case["id"],
        therapies=list(GAPPED_FOURTEEN_DAY_COURSES),
        criteria=list(GAPPED_CRITERIA_CODES),
        ct_study_date="2026-05-01",
    )
    check.assert_sinuplasty_case(
        documented,
        status=C.CASE_DOCUMENTED,
        evaluation_variant=C.EVAL_VARIANT_POLICY_STRICT,
        criteria_met_count=3,
        contiguous_management_days=14,
        cumulative_management_days=28,
        candidacy_status=C.CANDIDACY_INELIGIBLE,
    )

    # The projection recomputes the verdict for the payer liaison to read.
    evaluation = check.validate_unpaginated(
        api.get_candidacy_evaluation(case["id"], USERS.LIAISON_1)
    )
    check.assert_candidacy_evaluation(
        evaluation,
        evaluation_variant=C.EVAL_VARIANT_POLICY_STRICT,
        criteria_met_count=3,
        contiguous_management_days=14,
        cumulative_management_days=28,
        management_days_metric=14,
        min_documented_criteria_required=3,
        min_medical_management_days_required=28,
        candidacy_status=C.CANDIDACY_INELIGIBLE,
    )
    assert sorted(evaluation["admissible_criteria_codes"]) == sorted(
        GAPPED_CRITERIA_CODES
    ), "all three asserted criteria are admissible under the strict cross-check"

    # Reading the determination moved neither the status nor the version.
    after = SETUP.read_case(api, case["id"])
    check.assert_sinuplasty_case(
        after,
        status=C.CASE_DOCUMENTED,
        candidacy_status=C.CANDIDACY_INELIGIBLE,
        version=documented["version"],
    )


def test_clinical_broad_candidacy_sums_every_documented_course(api):
    """PRD 3.6: "Under **`CLINICAL_BROAD`**, which governs whenever the plan's
    `requires_prior_auth` is false, the verdict consults
    `cumulative_management_days` — every documented course adds up regardless of
    the gaps between them."

    Design: Difficulty/dual_variant_calc/candidacy_variant_divergence_on_sinuplasty_case
    """
    # A plan with no payer pathway at all, so its cases evaluate broadly.
    policy = SETUP.create_policy(
        api,
        plan_code="BROAD-2999",
        payer_name="Broad Mutual",
        requires_prior_auth=False,
        min_medical_management_days=28,
        requires_ct_within_months=12,
        min_documented_criteria=3,
        covered_pct_bps=8000,
        observation_floor_minutes=20,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10002),
        full_name="Broad Plan Patient",
        date_of_birth="1988-06-20",
        epinephrine_on_file=True,
        prior_systemic_reaction_count=0,
    )

    # Byte-identical documentation to the strict plan's case.
    case = SETUP.create_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_BILATERAL,
        sinuses=[C.SINUS_MAXILLARY, C.SINUS_FRONTAL],
    )
    documented = SETUP.document_case(
        api,
        case["id"],
        therapies=list(GAPPED_FOURTEEN_DAY_COURSES),
        criteria=list(GAPPED_CRITERIA_CODES),
        ct_study_date="2026-05-01",
    )
    check.assert_sinuplasty_case(
        documented,
        status=C.CASE_DOCUMENTED,
        evaluation_variant=C.EVAL_VARIANT_CLINICAL_BROAD,
        criteria_met_count=3,
        contiguous_management_days=14,
        cumulative_management_days=28,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
    )

    # The same nine-field projection, now consulting the cumulative figure.
    evaluation = check.validate_unpaginated(
        api.get_candidacy_evaluation(case["id"], USERS.LIAISON_1)
    )
    check.assert_candidacy_evaluation(
        evaluation,
        evaluation_variant=C.EVAL_VARIANT_CLINICAL_BROAD,
        criteria_met_count=3,
        contiguous_management_days=14,
        cumulative_management_days=28,
        management_days_metric=28,
        min_documented_criteria_required=3,
        min_medical_management_days_required=28,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
    )
    assert sorted(evaluation["admissible_criteria_codes"]) == sorted(
        GAPPED_CRITERIA_CODES
    ), "the broad variant admits every asserted code with no cross-check"

    # The read is a projection, so the case is untouched by it.
    after = SETUP.read_case(api, case["id"])
    check.assert_sinuplasty_case(
        after,
        status=C.CASE_DOCUMENTED,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
        version=documented["version"],
    )


def _documented_case_under_a_cycling_plan(api):
    """Open and document one case that a strict plan already finds ELIGIBLE.

    A single intranasal-corticosteroid course of twenty-eight contiguous days and
    three admissible criteria clear the plan's two thresholds, so the case is
    ready for the payer conversation without any further preparation.
    """
    policy = SETUP.create_policy(
        api,
        plan_code="CYC-2999",
        payer_name="Cycle Mutual",
        requires_prior_auth=True,
        min_medical_management_days=28,
        min_documented_criteria=3,
        requires_ct_within_months=12,
        max_balloon_devices=2,
        auth_validity_days=90,
    )
    patient = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10051),
        full_name="Revision Patient",
        date_of_birth="1988-06-20",
        epinephrine_on_file=True,
    )
    case = SETUP.create_case(
        api,
        patient["id"],
        laterality=C.LATERALITY_LEFT,
        sinuses=[C.SINUS_MAXILLARY],
    )
    documented = SETUP.document_case(
        api,
        case["id"],
        therapies=[F.therapy_course(C.THERAPY_INCS, "2026-06-01", "2026-06-28")],
        criteria=[
            C.CRITERION_CT_OPACIFICATION,
            C.CRITERION_SNOT22_GE_20,
            C.CRITERION_FAILED_INCS,
        ],
        ct_study_date="2026-07-15",
    )
    check.assert_sinuplasty_case(
        documented,
        status=C.CASE_DOCUMENTED,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
        criteria_met_count=3,
        contiguous_management_days=28,
        revision_round=0,
    )
    return documented


def test_information_requested_leaves_the_revision_round_for_the_next_submission(api):
    """PRD 3.6: "`INFO_REQUESTED` moves the case `AUTH_SUBMITTED → INFO_REQUESTED`
    and leaves `revision_round` alone, for the next submission to increment."

    Design: Difficulty/non_linear_state_machine/sinuplasty_case_revision_cycle
    """
    documented = _documented_case_under_a_cycling_plan(api)

    # The first submission comes from DOCUMENTED, so it increments nothing.
    submitted = SETUP.submit_case(api, documented["id"])
    check.assert_sinuplasty_case(
        submitted,
        status=C.CASE_AUTH_SUBMITTED,
        revision_round=0,
        submitted_by_user_id=C.USER_LIAISON_1,
    )

    # The payer asks for more information, which parks the case in the loop.
    decided = SETUP.decide_case(
        api, documented["id"], C.DECISION_INFO_REQUESTED, "PA-2999-0001"
    )
    check.assert_sinuplasty_case(
        decided,
        status=C.CASE_INFO_REQUESTED,
        revision_round=0,
        payer_reference="PA-2999-0001",
        authorized_device_count=0,
        auth_expires_at=None,
    )


def test_case_re_enters_authorization_submitted_from_information_requested(api):
    """PRD 3.6: "The short one runs `AUTH_SUBMITTED → INFO_REQUESTED →
    AUTH_SUBMITTED` and may be traversed at most twice before the revision cap
    bites."

    Design: Difficulty/non_linear_state_machine/sinuplasty_case_revision_cycle
    """
    documented = _documented_case_under_a_cycling_plan(api)

    # First trip through the payer: submission, then a request for information.
    first = SETUP.submit_case(api, documented["id"])
    check.assert_sinuplasty_case(first, status=C.CASE_AUTH_SUBMITTED, revision_round=0)
    SETUP.decide_case(api, documented["id"], C.DECISION_INFO_REQUESTED, "PA-2999-0001")

    # Second traversal: the same state is occupied again, one revision along.
    second = SETUP.submit_case(api, documented["id"])
    check.assert_sinuplasty_case(
        second,
        status=C.CASE_AUTH_SUBMITTED,
        revision_round=1,
        submitted_by_user_id=C.USER_LIAISON_1,
    )
    SETUP.decide_case(api, documented["id"], C.DECISION_INFO_REQUESTED, "PA-2999-0002")

    # Third traversal: the cap is now reached but this submission still stands.
    third = SETUP.submit_case(api, documented["id"])
    check.assert_sinuplasty_case(
        third,
        status=C.CASE_AUTH_SUBMITTED,
        revision_round=C.MAX_REVISION_ROUNDS,
        submitted_by_user_id=C.USER_LIAISON_1,
    )


def test_a_further_submission_is_refused_once_the_revision_round_reaches_two(api):
    """PRD 3.6: "From `INFO_REQUESTED`, the case's `revision_round` must be
    strictly below 2; the submission then increments `revision_round` by one, and
    a third attempt made when `revision_round` already stands at 2 is refused
    with `ERR_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/sinuplasty_case_revision_cycle
    """
    documented = _documented_case_under_a_cycling_plan(api)

    # Three submissions and three requests for information exhaust the budget.
    SETUP.submit_case(api, documented["id"])
    SETUP.decide_case(api, documented["id"], C.DECISION_INFO_REQUESTED, "PA-2999-0001")
    SETUP.submit_case(api, documented["id"])
    SETUP.decide_case(api, documented["id"], C.DECISION_INFO_REQUESTED, "PA-2999-0002")
    SETUP.submit_case(api, documented["id"])
    parked = SETUP.decide_case(
        api, documented["id"], C.DECISION_INFO_REQUESTED, "PA-2999-0003"
    )
    check.assert_sinuplasty_case(
        parked, status=C.CASE_INFO_REQUESTED, revision_round=C.MAX_REVISION_ROUNDS
    )

    # A fourth submission finds the loop closed.
    validate_error(
        api.submit_authorization(documented["id"], USERS.LIAISON_1),
        ApiErrorId.REVISION_LIMIT_REACHED.value,
    )

    # The refusal left the case exactly where the loop had parked it.
    after = SETUP.read_case(api, documented["id"])
    check.assert_sinuplasty_case(
        after,
        status=C.CASE_INFO_REQUESTED,
        revision_round=C.MAX_REVISION_ROUNDS,
        submitted_by_user_id=C.USER_LIAISON_1,
        payer_reference="PA-2999-0003",
    )


def _two_cases_over_one_exhausted_balloon_lot(api):
    """Build a denied case and an authorized case that draw on the same dry lot.

    The lot receives a single balloon device and writes it off immediately, so
    its ``available_quantity`` is 0 and its status is EXHAUSTED rather than
    QUARANTINED, leaving the fiscal rule as the only inventory rule in play. An
    endoscope is registered because a balloon-sinuplasty booking must name one.
    """
    policy = SETUP.create_policy(
        api,
        plan_code="CONF-2999",
        payer_name="Conflict Health",
        requires_prior_auth=True,
        min_medical_management_days=28,
        requires_ct_within_months=12,
        min_documented_criteria=3,
        max_balloon_devices=4,
        auth_validity_days=90,
    )
    patient_a = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10091),
        full_name="Denied Case Patient",
        date_of_birth="1979-03-04",
    )
    patient_b = SETUP.create_patient(
        api,
        policy["id"],
        patient_mrn=C.mrn(10092),
        full_name="Authorized Case Patient",
        date_of_birth="1981-11-19",
    )

    # One balloon device received and written off in the same breath.
    lot = SETUP.create_lot(
        api,
        item_type=C.ITEM_TYPE_BALLOON_DEVICE,
        lot_no=C.lot_number(1006),
        quantity_received=1,
        expires_at="2027-06-30T00:00:00Z",
    )
    written_off = SETUP.adjust_lot(
        api, lot["id"], C.ADJUSTMENT_REASON_WRITE_OFF, quantity=1
    )
    check.assert_supply_lot(
        written_off,
        quantity_received=1,
        quantity_on_hand=0,
        quantity_reserved=0,
        quantity_consumed=0,
        quantity_wasted=1,
        available_quantity=0,
        status=C.LOT_EXHAUSTED,
    )
    scope = SETUP.register_scope(api, serial=C.scope_serial(1))

    # Case A walks the payer conversation to a refusal.
    case_a = SETUP.eligible_documented_case(
        api, patient_a["id"], laterality=C.LATERALITY_LEFT, sinuses=[C.SINUS_MAXILLARY]
    )
    SETUP.submit_case(api, case_a["id"])
    denied = SETUP.decide_case(api, case_a["id"], C.DECISION_DENIED, "PA-2999-DENY")
    check.assert_sinuplasty_case(
        denied, status=C.CASE_DENIED, authorized_device_count=0
    )

    # Case B carries identical documentation and is approved.
    authorized = SETUP.authorized_case(
        api,
        patient_b["id"],
        laterality=C.LATERALITY_LEFT,
        sinuses=[C.SINUS_MAXILLARY],
        payer_reference="PA-2999-APPR",
    )
    check.assert_sinuplasty_case(
        authorized, status=C.CASE_AUTHORIZED, authorized_device_count=1
    )
    return {
        "patient_a": patient_a,
        "patient_b": patient_b,
        "case_a": denied,
        "case_b": authorized,
        "lot": lot,
        "scope": scope,
    }


def _balloon_booking_body(patient_id, case_id, scope_id, lot_id):
    """One balloon-sinuplasty booking body carrying all three live references."""
    return F.procedure_booking_payload(
        patient_id,
        "2026-08-20T09:00:00Z",
        "2026-08-20T10:00:00Z",
        C.USER_ENT_1,
        procedure_type=C.PROCEDURE_BALLOON_SINUPLASTY,
        venue=C.VENUE_IN_OFFICE_SUITE,
        sinuplasty_case_id=case_id,
        endoscope_asset_id=scope_id,
        supply_lot_id=lot_id,
        planned_device_count=1,
    )


def test_denied_case_outranks_the_exhausted_balloon_lot(api):
    """PRD 2.8: "**First**, on booking creation, a lifecycle failure beats a
    supply failure: if the referenced sinuplasty case is `DENIED` — not
    `AUTHORIZED` and not `DOCUMENTED` — while the referenced supply lot
    simultaneously has an `available_quantity` of 0, the response is
    `ERR_CASE_STATE_INVALID` from rung 7, not `ERR_SUPPLY_EXHAUSTED` from rung
    14."

    Design: Difficulty/priority_pair_validation_conflict/case_state_beats_supply_exhausted_on_booking_create
    """
    fixture = _two_cases_over_one_exhausted_balloon_lot(api)

    # Both failures are live in the one request: denied case, empty lot.
    body = _balloon_booking_body(
        fixture["patient_a"]["id"],
        fixture["case_a"]["id"],
        fixture["scope"]["id"],
        fixture["lot"]["id"],
    )
    validate_error(
        api.create_procedure_booking(body, USERS.ENT_1),
        ApiErrorId.CASE_STATE_INVALID.value,
    )

    # A denied case is not schedulable, so nothing was booked at all.
    rows, meta = validate_paginated(
        api.list_procedure_bookings(
            USERS.ADMIN_1, {"patient_id": fixture["patient_a"]["id"]}
        )
    )
    assert rows == [], "the rejected request must leave no booking row behind"
    assert meta["total_count"] == 0, "expected no bookings for the denied case"

    # Inventory was never consulted, so the lot reserved nothing.
    lot_after = SETUP.read_lot(api, fixture["lot"]["id"])
    check.assert_supply_lot(
        lot_after,
        quantity_received=1,
        quantity_on_hand=0,
        quantity_reserved=0,
        quantity_wasted=1,
        available_quantity=0,
        status=C.LOT_EXHAUSTED,
    )


def test_authorized_case_against_the_same_dry_lot_reports_supply_exhausted(api):
    """PRD 3.9: "The lot must have at least `planned_device_count` units
    available, or the booking is refused with `ERR_SUPPLY_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/case_state_beats_supply_exhausted_on_booking_create
    """
    fixture = _two_cases_over_one_exhausted_balloon_lot(api)

    # The same body against an authorized case reaches the fiscal rung.
    body = _balloon_booking_body(
        fixture["patient_b"]["id"],
        fixture["case_b"]["id"],
        fixture["scope"]["id"],
        fixture["lot"]["id"],
    )
    validate_error(
        api.create_procedure_booking(body, USERS.ENT_1),
        ApiErrorId.SUPPLY_EXHAUSTED.value,
    )

    # A rejected booking does not move the case toward the schedule.
    case_after = SETUP.read_case(api, fixture["case_b"]["id"])
    check.assert_sinuplasty_case(
        case_after,
        status=C.CASE_AUTHORIZED,
        authorized_device_count=1,
        candidacy_status=C.CANDIDACY_ELIGIBLE,
    )

    # And it reserved nothing on the way out.
    lot_after = SETUP.read_lot(api, fixture["lot"]["id"])
    check.assert_supply_lot(
        lot_after, quantity_reserved=0, available_quantity=0, status=C.LOT_EXHAUSTED
    )
