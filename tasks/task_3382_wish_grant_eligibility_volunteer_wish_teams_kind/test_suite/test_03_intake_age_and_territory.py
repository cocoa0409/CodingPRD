"""Intake boundaries: the 30/216-month age bounds, the territory selector's
empty-pool fallback, and read-after-write visibility of a fresh referral.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_referral,
    create_chapter,
    create_referral,
    create_referral_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

REFERRAL_SOURCE = TEST_USERS["referral_source_headers"]
WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]


def _chapter():
    set_clock()
    return create_chapter(territory_zip_prefixes=["900"])


def test_intake_age_30_months_lower_boundary():
    """PRD section 3.2: "A child is eligible for intake when this measure is
    at least 30 months — two and a half years — and strictly below 216 months,
    the eighteenth birthday. Anything outside that range is rejected with
    `ERR_CHILD_AGE_OUT_OF_RANGE` (HTTP 422)."

    Design: Corner/calculations/intake_age_30_months_lower_boundary
    """
    _chapter()
    accepted = create_referral(
        child_full_name="Tiny Okay", child_date_of_birth="2024-03-01",
        parent_email="a@example.org", diagnosis_summary="cardiac")
    assert accepted["age_months_at_intake"] == 30, (
        f"dob 2024-03-01 at the 2026-09-01 clock is exactly 30 months, got "
        f"{accepted['age_months_at_intake']}"
    )

    too_young = api_client.create_referral(
        create_referral_payload(
            child_full_name="Tiny Young", child_date_of_birth="2024-03-02",
            parent_email="b@example.org", diagnosis_summary="cardiac"),
        REFERRAL_SOURCE,
    )
    validate_error(too_young, ApiErrorId.ERR_CHILD_AGE_OUT_OF_RANGE)


def test_territory_empty_candidate_set_returns_error():
    """PRD section 3.2: "When no chapter matches at all, the entire intake
    fails with `ERR_NO_TERRITORY_CHAPTER` (HTTP 422) and nothing is persisted."

    Design: Corner/calculations/territory_empty_candidate_set_returns_error
    """
    chapter = _chapter()
    resp = api_client.create_referral(
        create_referral_payload(
            child_full_name="Far Away", child_zip_code="55555",
            parent_email="far@example.org", diagnosis_summary="x"),
        REFERRAL_SOURCE,
    )
    validate_error(resp, ApiErrorId.ERR_NO_TERRITORY_CHAPTER)
    list_resp = api_client.list_children(
        WISH_COORDINATOR, params={"chapter_id": chapter["id"]})
    _, meta = validate_paginated(list_resp)
    assert meta["total_count"] == 0, (
        "the failed intake must persist nothing, including the child record; "
        f"chapter has {meta['total_count']} children"
    )


def test_immediate_read_after_write_referral():
    """PRD section 2.2: "Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in the
    data field."
    PRD section 3.2: "The payload atomically creates — or, on re-referral after
    a terminal referral, reuses — the child record, and produces a referral in
    `PENDING_CERTIFICATION` status with `age_months_at_intake` computed from
    the logical clock and `child_id` linking the two records."

    Design: Corner/consistency_model/immediate_read_after_write_referral
    """
    chapter = _chapter()
    create_resp = api_client.create_referral(create_referral_payload(),
                                             REFERRAL_SOURCE)
    data = validate_success(create_resp, 201)
    assert_referral(data)
    assert data["status"] == "PENDING_CERTIFICATION"
    assert data["age_months_at_intake"] == 125
    assert data["source_type"] == "FAMILY"
    assert data["prognosis_months"] == 12

    read_resp = api_client.get_referral(data["id"], REFERRAL_SOURCE)
    reread = validate_success(read_resp)
    assert reread["id"] == data["id"]
    assert reread["age_months_at_intake"] == 125

    children_resp = api_client.list_children(
        WISH_COORDINATOR, params={"chapter_id": chapter["id"]})
    _, meta = validate_paginated(children_resp)
    assert meta["total_count"] == 1, (
        "the atomically created child must be visible immediately after intake"
    )


def test_referral_intake_age_216_months_rejected():
    """PRD section 3.2: "A child is eligible for intake when this measure is
    at least 30 months — two and a half years — and strictly below 216 months,
    the eighteenth birthday. Anything outside that range is rejected with
    `ERR_CHILD_AGE_OUT_OF_RANGE` (HTTP 422)."
    dob 2008-09-01 at the 2026-09-01 logical clock is exactly 216 complete
    months — the bound is exclusive, so the intake is rejected.

    Design: Difficulty/boundary_precision_check/referral_intake_age_216_months_boundary
    """
    _chapter()
    resp = api_client.create_referral(
        create_referral_payload(
            child_full_name="Aged Out", child_date_of_birth="2008-09-01",
            parent_email="a@example.org", diagnosis_summary="oncy"),
        REFERRAL_SOURCE,
    )
    validate_error(resp, ApiErrorId.ERR_CHILD_AGE_OUT_OF_RANGE)


def test_referral_intake_age_215_months_accepted():
    """PRD section 3.2: "A child is eligible for intake when this measure is
    at least 30 months — two and a half years — and strictly below 216 months,
    the eighteenth birthday."
    dob 2008-09-02 at the 2026-09-01 logical clock is 215 complete months —
    one below the exclusive bound — so the referral is created.

    Design: Difficulty/boundary_precision_check/referral_intake_age_216_months_boundary
    """
    _chapter()
    created = create_referral(
        child_full_name="Still Young", child_date_of_birth="2008-09-02",
        parent_email="b@example.org", diagnosis_summary="oncy")
    assert created["age_months_at_intake"] == 215, (
        f"expected 215 complete months, got {created['age_months_at_intake']}"
    )
    assert created["status"] == "PENDING_CERTIFICATION"
