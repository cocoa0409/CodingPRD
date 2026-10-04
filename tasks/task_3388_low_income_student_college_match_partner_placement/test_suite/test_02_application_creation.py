"""Application creation: required fields, server-side defaults, computed
fields, the one-live-application constraint, and validation priority between
a bad referral reference and that constraint."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    assert_application,
    create_student,
    expect_created,
    expect_error,
    make_student_headers,
    setup_application_open,
    setup_submitted_application,
    submit_application,
    validate_paginated,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_application_create_missing_required_field_returns_invalid_request(api):
    """PRD §2.10: "1. Request well-formedness — required fields present,
    correct types, enum fields carrying a declared member —
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.3: "The payload names the target `cycle_id`, an optional
    `referral_id` that stays null for self-originated applications,
    `household_income_cents` as the self-reported annual household income in
    cents, a `household_size` of at least one, an optional
    `self_reported_assets_cents` defaulting to zero, `gpa_scaled` carrying the
    GPA multiplied by 100 (so 375 encodes a 3.75), an optional `test_score`
    holding the SAT composite with null allowed, and an optional `essay_text`
    defaulting to an empty string." (household_income_cents is not optional.)

    Design: Corner/entities/application_create_missing_required_field_returns_invalid_request
    """
    ctx = setup_application_open()
    student = create_student()
    payload = {
        "cycle_id": ctx["cycle"]["id"],
        "household_size": 4,
        "gpa_scaled": 390,
        "test_score": 1450,
    }
    resp = api.create_application(payload, make_student_headers(student["id"]))
    expect_error(resp, ApiErrorId.ERR_INVALID_REQUEST, payload)
    data, meta = validate_paginated(
        api.list_applications(_ADMIN, params={"student_id": student["id"]})
    )
    assert data == [] and meta["total_count"] == 0, (
        "a rejected create must leave no Application row behind"
    )


def test_application_create_defaults_assets_to_zero(api):
    """PRD §3.3: "The payload names the target `cycle_id`, an optional
    `referral_id` that stays null for self-originated applications,
    `household_income_cents` as the self-reported annual household income in
    cents, a `household_size` of at least one, an optional
    `self_reported_assets_cents` defaulting to zero, ..."
    PRD §3.3: "The new application starts in `DRAFT` with `verification_flag`
    `NONE`, `matched_college_id` null, and `submitted_at` null."

    Design: Corner/entities/application_create_defaults_assets_to_zero
    """
    ctx = setup_application_open()
    student = create_student()
    payload = {
        "cycle_id": ctx["cycle"]["id"],
        "household_income_cents": 6_500_000,
        "household_size": 4,
        "gpa_scaled": 390,
        "test_score": 1450,
    }
    resp = api.create_application(payload, make_student_headers(student["id"]))
    data = expect_created(resp, payload)
    assert_application(data)
    assert data["self_reported_assets_cents"] == 0, (
        f"omitted assets must default to 0, got {data['self_reported_assets_cents']!r}"
    )
    assert data["status"] == "DRAFT"
    assert data["referral_id"] is None
    assert data["verification_flag"] == "NONE"
    assert data["matched_college_id"] is None
    assert data["submitted_at"] is None


def test_application_create_with_computed_field_input_ignored(api):
    """PRD §3.3: "Three snapshots are computed and stored on the application
    at submit time."
    PRD §3.3: "`academic_index` combines twice the `gpa_scaled` with a test
    component — zero when `test_score` is null, otherwise the test score
    divided by 4 with the quotient rounded down to a whole number — and the
    sum is capped at 2,000, so the stored index is the lesser of 2,000 and the
    raw sum."
    PRD §3.3: "`need_tier` compares income against half the household cap: the
    cap from the income screen is halved and that half is rounded half-up to a
    whole cent; income at or below the half yields `HIGH`, and anything above
    it yields `STANDARD`."

    Design: Corner/entities/application_create_with_computed_field_input_ignored
    """
    ctx = setup_application_open()
    student = create_student()
    payload = {
        "cycle_id": ctx["cycle"]["id"],
        "household_income_cents": 6_500_000,
        "household_size": 4,
        "gpa_scaled": 390,
        "test_score": 1450,
        "academic_index": 9999,  # computed field — the server must ignore it
    }
    resp = api.create_application(payload, make_student_headers(student["id"]))
    data = expect_created(resp, payload)
    assert data.get("academic_index") != 9999, (
        "a client-supplied academic_index must never be stored on the draft"
    )
    submitted = submit_application(data["id"], student["id"])
    assert_application(submitted)
    assert submitted["academic_index"] == 1142, (
        f"academic_index must be computed at submit as 390*2 + floor(1450/4) "
        f"== 1142, got {submitted['academic_index']!r}"
    )
    assert submitted["need_tier"] == "STANDARD", (
        "income 6,500,000 is above half the size-4 cap (3,250,000)"
    )


def test_duplicate_application_returns_duplicate_error(api):
    """PRD §3.3: "Creation is permitted only while the target cycle is
    `APPLICATION_OPEN`; at most one non-`WITHDRAWN` application may exist per
    student per cycle, a second attempt failing with
    `ERR_DUPLICATE_APPLICATION`; ..."

    Design: Corner/validations/duplicate_application_returns_duplicate_error
    """
    ctx = setup_submitted_application()
    payload = {
        "cycle_id": ctx["cycle"]["id"],
        "household_income_cents": 6_500_000,
        "household_size": 4,
        "gpa_scaled": 390,
        "test_score": 1450,
    }
    resp = api.create_application(
        payload, make_student_headers(ctx["student"]["id"])
    )
    expect_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION, payload)


def test_referential_failure_beats_duplicate_constraint_on_create(api):
    """PRD §2.10: "When a single request could fail several checks at once,
    the earliest failure in a fixed global order wins and later checks are
    never evaluated." — and the order places "8. Referential integrity of
    body-supplied references — `ERR_REFERRAL_NOT_FOUND` (HTTP 422) for an
    unusable `referral_id` on an application, `ERR_UNKNOWN_COLLEGE` (HTTP 422)
    for a college in a ranking list that does not exist, and `ERR_NOT_FOUND`
    (HTTP 404) when a new referral, income verification, or prep enrollment
    names a student, cycle, or application that does not exist." ahead of
    "9. Uniqueness and list-shape constraints — `ERR_EMAIL_TAKEN` (HTTP 409)
    on student registration, `ERR_DUPLICATE_APPLICATION` (HTTP 409) on a
    second live application, and `ERR_RANK_ORDER_INVALID` (HTTP 422),
    `ERR_TOO_MANY_RANKS` (HTTP 422), and `ERR_COLLEGE_INACTIVE` (HTTP 409) on
    ranking submissions.".
    PRD §3.3: "a cited referral must exist, still be `NOMINATED`, and belong
    to the same student and the same cycle — failing any of which the create
    is rejected with `ERR_REFERRAL_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_application_create
    """
    ctx = setup_submitted_application()
    payload = {
        "cycle_id": ctx["cycle"]["id"],
        "referral_id": UNKNOWN_UUID,
        "household_income_cents": 6_500_000,
        "household_size": 4,
        "gpa_scaled": 390,
        "test_score": 1450,
    }
    resp = api.create_application(
        payload, make_student_headers(ctx["student"]["id"])
    )
    expect_error(resp, ApiErrorId.ERR_REFERRAL_NOT_FOUND, payload)


def test_referential_failure_leaves_existing_application_untouched(api):
    """PRD §2.10: "When a single request could fail several checks at once,
    the earliest failure in a fixed global order wins and later checks are
    never evaluated." — the request dies at the referential check, so the
    student's single pre-existing (non-WITHDRAWN) application remains the only
    one in the cycle.
    PRD §3.3: "Applications can be listed filtered by `student_id`,
    `cycle_id`, `referral_id`, `matched_college_id`, or `status`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_application_create
    """
    ctx = setup_submitted_application()
    payload = {
        "cycle_id": ctx["cycle"]["id"],
        "referral_id": UNKNOWN_UUID,
        "household_income_cents": 6_500_000,
        "household_size": 4,
        "gpa_scaled": 390,
        "test_score": 1450,
    }
    resp = api.create_application(
        payload, make_student_headers(ctx["student"]["id"])
    )
    expect_error(resp, ApiErrorId.ERR_REFERRAL_NOT_FOUND, payload)
    data, meta = validate_paginated(
        api.list_applications(
            _ADMIN,
            params={
                "student_id": ctx["student"]["id"],
                "cycle_id": ctx["cycle"]["id"],
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"the rejected create must not add a row, got {meta['total_count']}"
    )
    assert data[0]["id"] == ctx["application"]["id"]
    assert data[0]["status"] == "UNDER_REVIEW"
