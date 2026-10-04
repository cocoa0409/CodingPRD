"""Entity shape, computed defaults, and response envelope tests (PRD §2.2, §2.4, §3.1, §3.4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_institution,
    assert_match_fragment,
    create_active_integration,
    create_institution,
    create_institution_payload,
    create_instructor,
    create_source,
    create_student_payload,
    inject_fragment,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_instructor_headers,
    make_student_headers,
    setup_basic_scenario,
    submit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_institution_created_with_defaults(api):
    """PRD §3.1: "At creation the operator may also set the repository posture:
    `repository_participation` (defaulting to `INSTITUTION_ONLY` when omitted),
    `cross_institution_comparison_enabled` (default false), the
    `ai_detection_enabled` policy flag (default true), and
    `data_residency_locked` (default false). An institution starts with
    `comparable_submission_count` at zero"

    Design: Corner/entities/institution_created_with_defaults
    """
    created = validate_success(
        api.create_institution(create_institution_payload(name="Def U", residency_region="EU"), ADMIN),
        expected_status=201,
    )
    fetched = validate_success(api.get_institution(created["id"], ADMIN))
    assert_institution(fetched)
    assert fetched["repository_participation"] == "INSTITUTION_ONLY"
    assert fetched["cross_institution_comparison_enabled"] is False
    assert fetched["ai_detection_enabled"] is True
    assert fetched["data_residency_locked"] is False
    assert fetched["comparable_submission_count"] == 0
    assert fetched["version"] == 1
    assert is_valid_uuid(fetched["id"])


def test_match_fragment_carries_no_version_or_updated_at(api):
    """PRD §2.4: "The sole exception is `MatchFragment`, which carries only `id`
    and `created_at` — `updated_at` and `version` are absent from it entirely."
    PRD §3.5: "On success the fragment's `weighted_words` is computed immediately
    as the half-up-rounded product of `matched_word_count` and its category
    multiplier"

    Design: Corner/entities/match_fragment_immutable_no_version_field
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], "immutable fragment body")
    src = create_source(inst["id"], uri="https://src.example/imm")
    fragment = validate_success(
        api.inject_match(
            {
                "submission_id": sub["id"],
                "source_document_id": src["id"],
                "matched_word_count": 5,
                "match_category": "DIRECT_QUOTE",
                "offset_start": 0,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert_match_fragment(fragment)
    assert "version" not in fragment, "MatchFragment must not carry version"
    assert "updated_at" not in fragment, "MatchFragment must not carry updated_at"
    assert is_iso8601_timestamp(fragment["created_at"])
    # DIRECT_QUOTE multiplier 1.0 -> weighted_words == matched_word_count
    assert fragment["weighted_words"] == 5


def test_submission_word_count_computed_from_tokenization(api):
    """PRD §3.4: "its `word_count` is computed as the count of
    whitespace-separated tokens in `content_text`"

    Design: Corner/entities/submission_word_count_computed_not_input
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = validate_success(
        api.create_submission(
            asg["id"],
            {"student_id": student["id"], "content_text": "one two  three\nfour"},
            make_student_headers(student["id"]),
        ),
        expected_status=201,
    )
    assert sub["word_count"] == 4, (
        f"runs of spaces and newlines collapse to whitespace-separated tokens; got {sub['word_count']}"
    )


def test_list_response_envelope_and_pagination_meta(api):
    """PRD §2.3: "Every list response populates `limit`, `offset`,
    `total_count`, and `has_more` inside `meta`, where `total_count` is the full
    unpaginated count and `has_more` reports whether further results exist past
    the returned window." PRD §2.3: "`limit` defaults to 10"

    Design: Corner/endpoints/response_envelope_shape
    """
    inst = create_institution(name="Env U", residency_region="US")
    for i in range(2):
        validate_success(
            api.create_student(inst["id"], create_student_payload(external_lms_id=f"e{i}"), ADMIN),
            expected_status=201,
        )
    resp = api.list_students(inst["id"], ADMIN)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert resp.json()["meta"]["api_request_id"].startswith("req_")
    assert meta["total_count"] == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(data) == 2


def test_logical_clock_default_is_fixed_epoch(api):
    """PRD §2.4: "At server startup the logical clock reads
    `2026-09-01T00:00:00Z`." PRD §3.9: "it starts `ACTIVE` and transitions to
    `EXPIRED` lazily, on read or at purge time, once the logical clock reaches
    `retention_end`"

    Design: Corner/endpoints/clock_default_is_fixed_epoch
    """
    inst = create_institution(name="Clock U", residency_region="US")
    policy = validate_success(
        api.create_retention_policy(
            inst["id"],
            {
                "region": "US",
                "applies_to": "SUBMISSIONS",
                "retention_start": "2027-01-01T00:00:00Z",
                "retention_end": "2027-06-01T00:00:00Z",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert policy["policy_state"] == "ACTIVE"
    data, meta = validate_paginated(api.list_retention_policies(inst["id"], ADMIN))
    assert data[0]["policy_state"] == "ACTIVE", (
        "default logical clock 2026-09-01 precedes retention_end 2027-06-01, "
        "so no lazy expiry may fire regardless of the wall-clock date"
    )


def test_manual_student_repository_source_rejected(api):
    """PRD §3.5: "Manually creating a source of type `STUDENT_REPOSITORY` is
    forbidden — such rows are auto-created by the processing pipeline, one per
    deposit — and an attempt to do so is rejected with `ERR_VALIDATION`
    (HTTP 400)."

    Design: Corner/validations/manual_student_repository_source_rejected
    """
    inst = create_institution(name="Man U", residency_region="US")
    resp = api.create_source_document(
        inst["id"],
        {"source_type": "STUDENT_REPOSITORY", "uri": "repo://x", "region": "US"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_missing_required_field_rejected(api):
    """PRD §2.5: "Required-field presence, enum membership, and basic type
    well-formedness of the request body are then checked with `ERR_VALIDATION`
    (HTTP 400) before any state- or business-level rule runs."

    Design: Corner/validations/missing_required_field_rejected
    """
    inst = create_institution(name="Req U", residency_region="US")
    integ = create_active_integration(inst["id"], external_key="c20")
    instr = create_instructor(inst["id"])
    resp = api.create_assignment(
        integ["id"],
        {"instructor_id": instr["id"], "due_at": "2027-01-01T00:00:00Z"},
        make_instructor_headers(instr["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_not_found_on_unknown_institution_id(api):
    """PRD §2.5: "The first identifier that fails to resolve yields
    `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/validations/not_found_on_unknown_ids
    """
    create_institution(name="NF U", residency_region="US")
    resp = api.get_institution(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
