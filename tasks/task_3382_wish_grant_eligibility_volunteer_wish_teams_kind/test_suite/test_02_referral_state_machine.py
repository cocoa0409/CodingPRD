"""Referral lifecycle: state guards, auto-denial, the determination age
re-check, duplicate detection with normalization, and the SELF minimum age.
"""
from test_helpers import (
    ApiErrorId,
    AUTO_DENIAL_REASON,
    TEST_USERS,
    api_client,
    assert_referral,
    certify_referral,
    create_certify_payload,
    create_chapter,
    create_determine_payload,
    create_referral,
    create_referral_payload,
    determine_referral,
    get_referral,
    set_clock,
    validate_error,
    validate_success,
)

REFERRAL_SOURCE = TEST_USERS["referral_source_headers"]
MEDICAL_PROVIDER = TEST_USERS["medical_provider_headers"]
ELIGIBILITY_REVIEWER = TEST_USERS["eligibility_reviewer_headers"]


def _chapter_and_referral(**referral_overrides):
    set_clock()
    create_chapter(territory_zip_prefixes=["900"])
    return create_referral(**referral_overrides)


def test_referral_state_guards_and_terminal_lockdown():
    """PRD section 3.3: "Acting on a referral in `PENDING_CERTIFICATION` — any
    other state yields `ERR_INVALID_REFERRAL_STATE` (HTTP 409)"
    PRD section 3.3: "Determination belongs to the `EligibilityReviewer`,
    acting on a `CERTIFIED` referral — again `ERR_INVALID_REFERRAL_STATE`
    guards the from-state"

    Design: Corner/state_machines/referral_state_guards_and_terminal_lockdown
    """
    referral = _chapter_and_referral()

    early = api_client.determine_referral(
        referral["id"], create_determine_payload("APPROVED"), ELIGIBILITY_REVIEWER)
    validate_error(early, ApiErrorId.ERR_INVALID_REFERRAL_STATE)

    certify_referral(referral["id"], "ONCOLOGY")
    twice = api_client.certify_referral(
        referral["id"], create_certify_payload("CARDIAC"), MEDICAL_PROVIDER)
    validate_error(twice, ApiErrorId.ERR_INVALID_REFERRAL_STATE)

    determined = determine_referral(referral["id"], "APPROVED")
    assert determined["wish_id"], "APPROVED determination must create the wish"
    wish_resp = api_client.get_wish(determined["wish_id"],
                                    TEST_USERS["wish_coordinator_headers"])
    assert validate_success(wish_resp)["status"] == "CREATED"

    terminal = api_client.determine_referral(
        referral["id"], create_determine_payload("DENIED", denial_reason="late"),
        ELIGIBILITY_REVIEWER)
    validate_error(terminal, ApiErrorId.ERR_INVALID_REFERRAL_STATE)


def test_certify_non_qualifying_auto_denies_referral():
    """PRD section 3.3: "Declaring `NON_QUALIFYING` auto-denies the referral in
    the same breath: the referral moves straight to `DENIED`, both
    `certified_at` and `determined_at` are stamped, and `denial_reason` is set
    by the system to `CONDITION_NOT_QUALIFYING`."

    Design: Corner/state_machines/certify_non_qualifying_auto_denies_referral
    """
    referral = _chapter_and_referral()
    certify_referral(referral["id"], "NON_QUALIFYING",
                     certification_note="not life-threatening")
    fetched = get_referral(referral["id"])
    assert_referral(fetched)
    assert fetched["status"] == "DENIED"
    assert fetched["denial_reason"] == AUTO_DENIAL_REASON
    assert fetched["wish_id"] is None
    assert fetched["determined_at"] is not None
    assert fetched["certified_at"] is not None


def test_referral_age_trap_at_determination():
    """PRD section 3.3: "Approval, by contrast, re-checks the child's age at
    the determination date using the same complete-calendar-months measure as
    intake, and if the child has reached 216 months — the eighteenth birthday —
    approval is rejected with `ERR_CHILD_AGE_OUT_OF_RANGE`, even though intake
    accepted the case months earlier."
    PRD section 3.3: "Denial is never age-blocked: a reviewer may always deny,
    whatever the child's age."

    Design: Corner/calculations/referral_age_trap_at_determination
    """
    referral = _chapter_and_referral(
        child_full_name="Borderline Teen", child_date_of_birth="2008-09-20",
        parent_email="teen@example.org", diagnosis_summary="neuroblastoma")
    assert referral["age_months_at_intake"] == 215, (
        f"dob 2008-09-20 at the 2026-09-01 clock is 215 months, got "
        f"{referral['age_months_at_intake']}"
    )
    certify_referral(referral["id"], "NEUROLOGIC")
    set_clock("2026-10-01T00:00:00Z")

    blocked = api_client.determine_referral(
        referral["id"], create_determine_payload("APPROVED"), ELIGIBILITY_REVIEWER)
    validate_error(blocked, ApiErrorId.ERR_CHILD_AGE_OUT_OF_RANGE)

    denied = determine_referral(referral["id"], "DENIED", denial_reason="aged out")
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "aged out"
    assert denied["wish_id"] is None


def test_duplicate_referral_normalized_match_and_re_referral():
    """PRD section 3.2: "A duplicate exists when some earlier referral names a
    child with the same normalized name and the same `date_of_birth` and that
    earlier referral is still alive, meaning `PENDING_CERTIFICATION` or
    `CERTIFIED`; the intake is then rejected with `ERR_DUPLICATE_REFERRAL`
    (HTTP 409)."
    PRD section 3.2: "A prior referral that already reached `DENIED` or
    `APPROVED` does not block a new one: the existing child record, matched by
    the same normalized name and birth date, is reused and linked to the new
    referral."

    Design: Corner/calculations/duplicate_referral_normalized_match_and_re_referral
    """
    first = _chapter_and_referral()

    dup_resp = api_client.create_referral(
        {
            "child_full_name": " LILA  monroe ",
            "child_date_of_birth": "2016-03-10",
            "child_zip_code": "90012",
            "parent_email": "other@example.org",
            "diagnosis_summary": "leukemia",
            "source_type": "MEDICAL_PROFESSIONAL",
            "prognosis_months": 12,
        },
        REFERRAL_SOURCE,
    )
    validate_error(dup_resp, ApiErrorId.ERR_DUPLICATE_REFERRAL)

    certify_referral(first["id"], "NON_QUALIFYING")  # auto-denies r1
    second = create_referral(diagnosis_summary="leukemia - relapsed",
                             prognosis_months=6)
    assert second["status"] == "PENDING_CERTIFICATION"
    assert second["child_id"] == first["child_id"], (
        "re-referral after a terminal referral must reuse the existing child "
        f"record: {second['child_id']} != {first['child_id']}"
    )


def test_age_check_priority_beats_duplicate_detection():
    """PRD section 3.2: "Duplicate detection runs after the age checks and
    before territory selection."

    Design: Corner/calculations/age_check_priority_beats_duplicate_detection
    """
    _chapter_and_referral(
        child_full_name="Borderline Teen", child_date_of_birth="2008-09-20",
        parent_email="teen@example.org", diagnosis_summary="neuroblastoma")
    set_clock("2026-10-01T00:00:00Z")  # the child is now exactly 216 months
    dup_resp = api_client.create_referral(
        {
            "child_full_name": "Borderline Teen",
            "child_date_of_birth": "2008-09-20",
            "child_zip_code": "90012",
            "parent_email": "teen2@example.org",
            "diagnosis_summary": "neuroblastoma",
            "source_type": "FAMILY",
            "prognosis_months": 12,
        },
        REFERRAL_SOURCE,
    )
    # Both the age bound (216 months) and duplicate detection fail; the age
    # check runs first.
    validate_error(dup_resp, ApiErrorId.ERR_CHILD_AGE_OUT_OF_RANGE)


def test_self_referral_minimum_age():
    """PRD section 3.2: "A `SELF` referral carries an additional floor: the
    child must be at least 156 months old — thirteen years — at intake, or the
    request fails with `ERR_SELF_REFERRAL_TOO_YOUNG` (HTTP 422)."

    Design: Corner/validations/self_referral_minimum_age
    """
    set_clock()
    create_chapter(territory_zip_prefixes=["900"])

    too_young = api_client.create_referral(
        create_referral_payload(
            child_full_name="Young Teen", child_date_of_birth="2014-03-01",
            parent_email="yt@example.org", diagnosis_summary="cardiac",
            source_type="SELF"),
        REFERRAL_SOURCE,
    )
    validate_error(too_young, ApiErrorId.ERR_SELF_REFERRAL_TOO_YOUNG)

    family = create_referral(
        child_full_name="Young Teen", child_date_of_birth="2014-03-01",
        parent_email="yt@example.org", diagnosis_summary="cardiac",
        source_type="FAMILY")
    assert family["status"] == "PENDING_CERTIFICATION", (
        "the rejected SELF attempt persisted nothing, so the FAMILY intake of "
        "the same 150-month child must succeed"
    )

    older = create_referral(
        child_full_name="Older Teen", child_date_of_birth="2013-09-01",
        parent_email="ot@example.org", diagnosis_summary="cardiac",
        source_type="SELF")
    assert older["age_months_at_intake"] == 156, (
        f"dob 2013-09-01 at the 2026-09-01 clock is exactly 156 months, got "
        f"{older['age_months_at_intake']}"
    )
