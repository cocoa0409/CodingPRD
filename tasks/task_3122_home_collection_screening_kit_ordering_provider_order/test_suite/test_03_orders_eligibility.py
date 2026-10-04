"""Order capture and eligibility determination: initial state, safety gates,
age-band boundaries, rejection terminal state, and validation ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_order,
    create_patient,
    create_program,
    create_provider,
    enroll_cohort,
    get_order,
    make_provider_headers,
    setup_pending_order,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]


def test_order_initial_state_pending_eligibility(api):
    """PRD §3.3: "On success the order starts in `PENDING_ELIGIBILITY` status,
    and its `order_channel` is copied from the ordering provider's `channel`
    at that moment, freezing the channel attribution even if the provider's
    channel later changes. The order's `recollection_round` starts at 0, its
    `quality_outcome` starts at `UNRESOLVED`, and `eligible_at`, `shipped_at`,
    `returned_at`, `abandonment_due_at`, and `active_kit_id` all begin unset."

    Design: Corner/state_machines/order_initial_state_pending_eligibility
    """
    ctx = setup_pending_order()
    order = ctx["order"]
    assert order["status"] == "PENDING_ELIGIBILITY"
    assert order["quality_outcome"] == "UNRESOLVED"
    assert order["recollection_round"] == 0
    assert order["version"] == 1
    assert order["order_channel"] == "ORDERING"
    assert order.get("eligible_at") is None
    assert order.get("active_kit_id") is None


def test_high_risk_category_rejected_at_eligibility(api):
    """PRD §3.3: "the patient's `risk_category` must not be `HIGH` —
    high-risk patients require a different test modality and fail with
    `ERR_RISK_CATEGORY_EXCLUDED`".

    Design: Corner/validations/high_risk_category_rejected_at_eligibility
    """
    ctx = setup_pending_order(patient_overrides={"risk_category": "HIGH"})
    resp = api.confirm_eligibility(ctx["order"]["id"], PA)
    validate_error(resp, ApiErrorId.ERR_RISK_CATEGORY_EXCLUDED)
    assert get_order(ctx["order"]["id"])["status"] == "PENDING_ELIGIBILITY"


def test_contraindication_rejected_at_eligibility(api):
    """PRD §3.3: "the patient's `contraindication_flags` must be empty,
    failing with `ERR_CONTRAINDICATION_PRESENT` when any code is present."

    Design: Corner/validations/contraindication_rejected_at_eligibility
    """
    ctx = setup_pending_order(
        patient_overrides={"contraindication_flags": ["PRIOR_COLECTOMY"]}
    )
    resp = api.confirm_eligibility(ctx["order"]["id"], PA)
    validate_error(resp, ApiErrorId.ERR_CONTRAINDICATION_PRESENT)


def test_inactive_provider_rejected_at_order_capture(api):
    """PRD §3.3: "First, the referenced provider must be active; an order
    against a provider whose `is_active` is false is rejected with
    `ERR_PROVIDER_INACTIVE` (HTTP 422)."

    Design: Corner/validations/inactive_provider_rejected_at_order_capture
    """
    patient = create_patient()
    provider = create_provider(channel="TELEHEALTH", is_active=False)
    resp = api.create_order(
        {"patient_id": patient["id"], "provider_id": provider["id"]},
        make_provider_headers(provider["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROVIDER_INACTIVE)


def test_cohort_program_mismatch_rejected(api):
    """PRD §3.3: "Second, `program_id` and `cohort_id` must be consistent:
    either both are supplied or neither is, and when both are supplied the
    cohort must belong to the named program — any other combination is
    `ERR_COHORT_PROGRAM_MISMATCH` (HTTP 422)."

    Design: Corner/validations/cohort_program_mismatch_rejected
    """
    g1 = create_program(program_code="G-M1")
    g2 = create_program(program_code="G-M2")
    patient = create_patient()
    cohort = enroll_cohort(g2, patient)
    provider = create_provider()
    resp = api.create_order(
        {
            "patient_id": patient["id"],
            "provider_id": provider["id"],
            "program_id": g1["id"],
            "cohort_id": cohort["id"],
        },
        make_provider_headers(provider["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COHORT_PROGRAM_MISMATCH)


def _order_for_dob(dob):
    patient = create_patient(date_of_birth=dob)
    provider = create_provider()
    return create_order(patient, provider)


def test_age_boundaries_45_and_75_inclusive_pass(api):
    """PRD §3.3: "the patient's age at the order's creation date must fall
    within 45 to 75 years inclusive on both ends, failing with
    `ERR_AGE_OUT_OF_RANGE` otherwise".

    Design: Difficulty/boundary_precision_check/age_boundary_45_and_75_inclusive
    """
    # Logical clock defaults to 2026-09-01T00:00:00Z at server start.
    o45 = _order_for_dob("1981-09-01")  # turns 45 exactly on the order date
    o75 = _order_for_dob("1951-09-01")  # turns 75 exactly on the order date

    data45 = validate_success(api.confirm_eligibility(o45["id"], PA))
    data75 = validate_success(api.confirm_eligibility(o75["id"], PA))
    assert data45["status"] == "ELIGIBLE"
    assert data75["status"] == "ELIGIBLE"


def test_age_outside_45_to_75_rejected(api):
    """PRD §3.3: "the patient's age at the order's creation date must fall
    within 45 to 75 years inclusive on both ends, failing with
    `ERR_AGE_OUT_OF_RANGE` otherwise".

    Design: Difficulty/boundary_precision_check/age_boundary_45_and_75_inclusive
    """
    # 1982-09-02 has not yet turned 45 on 2026-09-01; 1950-08-31 is 76.
    o_under = _order_for_dob("1982-09-02")
    o_over = _order_for_dob("1950-08-31")

    validate_error(api.confirm_eligibility(o_under["id"], PA), ApiErrorId.ERR_AGE_OUT_OF_RANGE)
    validate_error(api.confirm_eligibility(o_over["id"], PA), ApiErrorId.ERR_AGE_OUT_OF_RANGE)
    assert get_order(o_under["id"])["status"] == "PENDING_ELIGIBILITY"
    assert get_order(o_over["id"])["status"] == "PENDING_ELIGIBILITY"


def test_eligibility_reject_terminal_state(api):
    """PRD §3.3: "Rejection is simpler: from `PENDING_ELIGIBILITY` (again
    enforced with `ERR_ORDER_INVALID_STATE`), the order transitions to
    `REJECTED_INELIGIBLE` and its `version` increments."

    Design: Corner/state_machines/eligibility_reject_terminal_state
    """
    ctx = setup_pending_order(patient_overrides={"date_of_birth": "1940-01-01"})
    rejected = validate_success(api.reject_eligibility(ctx["order"]["id"], PA))
    assert rejected["status"] == "REJECTED_INELIGIBLE"

    resp = api.confirm_eligibility(ctx["order"]["id"], PA)
    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)


def test_state_error_wins_over_patient_not_active(api):
    """PRD §3.3: "Confirmation is guarded by five checks, evaluated in this
    order: the order must still be in `PENDING_ELIGIBILITY` (otherwise
    `ERR_ORDER_INVALID_STATE`); the patient must be `ACTIVE` — a patient who
    is `DECEASED` or `OPTED_OUT` fails with `ERR_PATIENT_NOT_ACTIVE`".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_eligibility_confirm
    """
    ctx = setup_pending_order()
    validate_success(api.confirm_eligibility(ctx["order"]["id"], PA))
    validate_success(api.opt_out_patient(ctx["patient"]["id"], PA))

    resp = api.confirm_eligibility(ctx["order"]["id"], PA)
    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)


def test_state_precedence_leaves_order_unchanged(api):
    """PRD §3.3: "Confirmation is guarded by five checks, evaluated in this
    order: the order must still be in `PENDING_ELIGIBILITY` (otherwise
    `ERR_ORDER_INVALID_STATE`); the patient must be `ACTIVE` — a patient who
    is `DECEASED` or `OPTED_OUT` fails with `ERR_PATIENT_NOT_ACTIVE`".
    PRD §2.4: "The `version` is an integer that increments by exactly 1 on
    every mutation of that resource."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_eligibility_confirm
    """
    ctx = setup_pending_order()
    confirmed = validate_success(api.confirm_eligibility(ctx["order"]["id"], PA))
    validate_success(api.opt_out_patient(ctx["patient"]["id"], PA))

    resp = api.confirm_eligibility(ctx["order"]["id"], PA)
    assert resp.status_code == 409
    after = get_order(ctx["order"]["id"])
    assert after["status"] == "ELIGIBLE"
    assert after["version"] == confirmed["version"]


def test_state_precondition_beats_age_safety_check(api):
    """PRD §3.3: "Confirmation is guarded by five checks, evaluated in this
    order: the order must still be in `PENDING_ELIGIBILITY` (otherwise
    `ERR_ORDER_INVALID_STATE`); the patient must be `ACTIVE` — a patient who
    is `DECEASED` or `OPTED_OUT` fails with `ERR_PATIENT_NOT_ACTIVE`; the
    patient's age at the order's creation date must fall within 45 to 75
    years inclusive on both ends, failing with `ERR_AGE_OUT_OF_RANGE`
    otherwise".

    Design: Corner/validations/state_precondition_beats_safety_priority
    """
    # Age-ineligible patient (40 on the order date); order already rejected.
    ctx = setup_pending_order(patient_overrides={"date_of_birth": "1986-06-01"})
    validate_success(api.reject_eligibility(ctx["order"]["id"], PA))

    resp = api.confirm_eligibility(ctx["order"]["id"], PA)
    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
