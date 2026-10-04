"""Application creation and submission gates: fee exactness, required studies,
duplicate-open constraint, product-state gate, ownership, and the absolute rate
cap (PRD §2.1, §2.8, §3.2).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    add_days,
    assert_application,
    assert_iso_instant_equal,
    create_active_ingredient,
    create_application,
    create_product,
    create_registered_product,
    create_required_studies,
    create_study,
    list_product_use_sites,
    make_application_payload,
    make_non_food_use_site_object,
    make_submit_payload,
    setup_application_in_review,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    DEFAULT_CLOCK_ISO,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REGISTRANT_B = TEST_USERS["registrant_bob_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]


def _get_application(application_id):
    """Read one application through the PRD §4 GET endpoint."""
    return validate_success(api_client.get_application(application_id, ADMIN))


def _draft_application_with_studies(use_pattern="NON_FOOD_USE"):
    """Product + DRAFT application + one study per required type (unsubmitted)."""
    ai = create_active_ingredient()
    product = create_product(REGISTRANT, ai["id"])
    application = create_application(product["id"], REGISTRANT, use_pattern)
    studies = create_required_studies(application["id"], use_pattern, REGISTRANT)
    return product, application, studies


def test_application_double_submit_returns_not_submittable(api):
    """PRD §3.2: "The application must actually be in `DRAFT` — a submit against
    any other status fails `ERR_APPLICATION_NOT_SUBMITTABLE` (HTTP 409)."
    PRD §3.2: "Resubmission refreshes `submitted_at` but never recomputes
    `review_due_at`: the statutory clock runs from the first submission only."

    Design: Corner/state_machines/application_double_submit_returns_not_submittable
    """
    ctx = setup_application_in_review()  # NON_FOOD_USE, submitted once
    app_id = ctx["application"]["id"]
    resp = api_client.submit_application(
        app_id, REGISTRANT, payload=make_submit_payload("NON_FOOD_USE"))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTABLE)

    application = _get_application(app_id)
    assert application["status"] == "IN_REVIEW"
    # First submit at the default instant + 270 days (NON_FOOD_USE timeline).
    expected_due = add_days(DEFAULT_CLOCK_ISO, 270)
    assert application["review_due_at"] is not None
    assert_iso_instant_equal(application["review_due_at"], expected_due,
                             "review_due_at")


def test_submit_food_use_without_residue_study_returns_missing_studies(api):
    """PRD §3.2: "The dossier must already contain at least one study submission —
    of any status, decided or not — for every study type the use pattern requires,
    failing `ERR_MISSING_REQUIRED_STUDIES` (HTTP 422) otherwise: `FOOD_USE` and
    `MIXED_USE` each require `EFFICACY`, `TOXICOLOGY`, `ENVIRONMENTAL_FATE`, and
    `RESIDUE_CHEMISTRY`, while `NON_FOOD_USE` requires `EFFICACY`, `TOXICOLOGY`,
    and `ENVIRONMENTAL_FATE`."

    Design: Corner/validations/submit_food_use_without_residue_study_returns_missing_studies
    """
    ai = create_active_ingredient()
    product = create_product(REGISTRANT, ai["id"], product_name="Nominex 15G")
    application = create_application(product["id"], REGISTRANT, "FOOD_USE")
    for study_type in ("EFFICACY", "TOXICOLOGY", "ENVIRONMENTAL_FATE"):
        create_study(application_id=application["id"], study_type=study_type,
                     registrant_headers=REGISTRANT)

    resp = api_client.submit_application(
        application["id"], REGISTRANT, payload=make_submit_payload("FOOD_USE"))
    validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_STUDIES)

    application = _get_application(application["id"])
    assert application["status"] == "DRAFT"
    assert application["payment_cents"] is None, (
        "no fee is captured on a rejected submit")


def test_submit_with_wrong_fee_returns_incorrect_fee(api):
    """PRD §3.2: "the `payment_cents` in the request must equal the filing fee for
    the use pattern exactly — 500,000 cents for `FOOD_USE`, 150,000 cents for
    `NON_FOOD_USE`, and 500,000 cents for `MIXED_USE` — with any mismatch failing
    `ERR_INCORRECT_FEE_PAYMENT` (HTTP 402)."

    Design: Corner/validations/submit_with_wrong_fee_returns_incorrect_fee
    """
    _, application, _ = _draft_application_with_studies("NON_FOOD_USE")
    resp = api_client.submit_application(
        application["id"], REGISTRANT, payload={"payment_cents": 149999})
    validate_error(resp, ApiErrorId.ERR_INCORRECT_FEE_PAYMENT)
    assert _get_application(application["id"])["status"] == "DRAFT"


def test_submit_second_registration_after_approval_returns_not_unregistered(api):
    """PRD §3.2: "The product must still be `UNREGISTERED`, failing
    `ERR_PRODUCT_NOT_UNREGISTERED` otherwise."

    Design: Corner/validations/submit_second_registration_after_approval_returns_not_unregistered
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    app_b = create_application(product_id, REGISTRANT, "NON_FOOD_USE",
                               proposed_use_sites=[make_non_food_use_site_object(
                                   max_application_rate_lbs_acre=0.5,
                                   max_applications_per_season=1,
                                   restricted_entry_interval_hours=12)])
    resp = api_client.submit_application(
        app_b["id"], REGISTRANT, payload=make_submit_payload("NON_FOOD_USE"))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_UNREGISTERED)
    assert _get_application(app_b["id"])["status"] == "DRAFT"


def test_registrant_cannot_submit_another_registrants_application(api):
    """PRD §2.1: "Ownership checks on registrant-scoped mutations — submitting or
    withdrawing an application, filing or withdrawing a label amendment, proposing
    a tolerance, submitting a study, responding to a data call-in, and applying
    for or renewing a state registration — compare the owning product's
    `registrant_ref` to `X-User-ID`, rejecting a mismatch with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/registrant_cannot_submit_another_registrants_application
    """
    _, application, _ = _draft_application_with_studies("NON_FOOD_USE")
    resp = api_client.submit_application(
        application["id"], REGISTRANT_B, payload=make_submit_payload("NON_FOOD_USE"))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert _get_application(application["id"])["status"] == "DRAFT"


def test_submit_duplicate_open_beats_fee_error(api):
    """PRD §2.8: "The stages are evaluated in the order below, and a failure at
    any stage short-circuits all later stages"
    PRD §3.2: "No other application of the same product may sit in `DRAFT`,
    `IN_REVIEW`, or `DATA_DEFICIENCY`, or the submit collides with
    `ERR_DUPLICATE_OPEN_APPLICATION`."
    PRD §3.2: "the `payment_cents` in the request must equal the filing fee for
    the use pattern exactly"

    Design: Difficulty/priority_pair_validation_conflict/submit_duplicate_open_beats_fee_error
    """
    product, app_a, _ = _draft_application_with_studies("NON_FOOD_USE")
    submit_application(app_a["id"], REGISTRANT, "NON_FOOD_USE")  # IN_REVIEW

    app_b = create_application(product["id"], REGISTRANT, "NON_FOOD_USE",
                               proposed_use_sites=[make_non_food_use_site_object(
                                   max_application_rate_lbs_acre=0.5,
                                   max_applications_per_season=1,
                                   restricted_entry_interval_hours=12)])
    create_required_studies(app_b["id"], "NON_FOOD_USE", REGISTRANT)

    resp = api_client.submit_application(
        app_b["id"], REGISTRANT, payload={"payment_cents": 1})
    # The 409 uniqueness check (stage 9) fires ahead of the 402 fiscal check
    # (stage 12) even though the 1-cent payment is also wrong.
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_APPLICATION)
    assert _get_application(app_b["id"])["status"] == "DRAFT"


def test_application_create_with_over_cap_rate_returns_safety_error(api):
    """PRD §3.2: "Every application rate proposed anywhere in the system is
    bounded by an absolute safety cap: `max_application_rate_lbs_acre` must be
    greater than zero and no more than 8.0 pounds per acre, and a rate above the
    cap is rejected with `ERR_RATE_EXCEEDS_SAFETY_CAP` (HTTP 422)"

    Design: Corner/validations/application_create_with_over_cap_rate_returns_safety_error
    """
    ai = create_active_ingredient()
    product = create_product(REGISTRANT, ai["id"])
    resp = api_client.create_application(
        make_application_payload(
            product["id"], "NON_FOOD_USE",
            proposed_use_sites=[make_non_food_use_site_object(
                max_application_rate_lbs_acre=8.5)]),
        REGISTRANT,
    )
    validate_error(resp, ApiErrorId.ERR_RATE_EXCEEDS_SAFETY_CAP)
    rows = list_product_use_sites(product["id"])
    assert rows == [], "no use-site rows may persist from a rejected create"
