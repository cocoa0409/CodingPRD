"""Corner queue — entity creation defaults, computed fields, catalogue admin.

PRD §3.1 candidate record, §3.2 syllabus/exam curation, §3.5 module defaults,
§3.8 transfer-credit mutual recognition, §2.3 pagination.
"""
from test_helpers import (
    ANONYMOUS,
    ApiErrorId,
    REGISTRAR,
    TRANSFER_CAS_CLAIM,
    TRANSFER_CAS_GRANTED,
    TRANSFER_CIA_CLAIM,
    TRANSFER_CIA_GRANTED,
    TRANSFER_IFOA_CLAIM,
    TRANSFER_IFOA_GRANTED,
    TRANSFER_IAA_CLAIM,
    TRANSFER_IAA_GRANTED,
    TRANSFER_OTHER_CLAIM,
    TRANSFER_OTHER_GRANTED,
    TRANSFER_TOTAL_ALL_TIERS,
    activate_syllabus,
    assert_candidate,
    assert_candidate_credit_totals,
    create_candidate_payload,
    get_candidate,
    get_success_data,
    is_valid_uuid,
    make_candidate,
    make_syllabus,
    make_transfer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_candidate_creation_defaults(api):
    """PRD §3.1: "A freshly created record starts with `status` of `ACTIVE`
    and `membership_tier` of `CANDIDATE`; the standing fields
    `suspended_until`, `associate_admitted_at`, `fellow_admitted_at`, and
    `last_evaluated_at` all begin null."

    Design: Corner/entities/candidate_creation_defaults
    """
    resp = api.create_candidate(
        create_candidate_payload(email="fresh@example.com", full_name="Fresh Candidate"),
        ANONYMOUS)
    candidate = validate_success(resp, 201)
    assert_candidate(candidate)
    assert candidate["status"] == "ACTIVE"
    assert candidate["membership_tier"] == "CANDIDATE"
    assert candidate["suspended_until"] is None
    assert candidate["associate_admitted_at"] is None
    assert candidate["fellow_admitted_at"] is None
    assert candidate["last_evaluated_at"] is None
    assert is_valid_uuid(candidate["id"])
    assert candidate["earned_exam_credit_hours"] == 0
    assert candidate["transfer_credit_hours"] == 0
    assert candidate["total_credit_hours"] == 0


def test_candidate_system_fields_input_ignored(api):
    """PRD §2.8: "Unknown body fields are ignored rather than rejected,
    including attempts to set system-managed or computed fields."

    Design: Corner/entities/candidate_system_fields_input_ignored
    """
    payload = create_candidate_payload(email="sneaky@example.com", full_name="Sneaky")
    payload.update({"status": "EXPELLED", "membership_tier": "FELLOW",
                    "version": 99, "transfer_credit_hours": 1000})
    candidate = validate_success(api.create_candidate(payload, ANONYMOUS), 201)
    assert candidate["status"] == "ACTIVE"
    assert candidate["membership_tier"] == "CANDIDATE"
    assert candidate["version"] != 99
    assert candidate["transfer_credit_hours"] == 0
    assert candidate["total_credit_hours"] == 0


def test_candidate_email_uniqueness(api):
    """PRD §3.1: "The `email` must be a non-empty, well-formed address and is
    unique across all candidates — a duplicate is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/candidate_email_uniqueness
    """
    first = validate_success(api.create_candidate(
        create_candidate_payload(email="dup@example.com", full_name="First"), ANONYMOUS), 201)
    assert first["email"] == "dup@example.com"
    resp_dup = api.create_candidate(
        create_candidate_payload(email="dup@example.com", full_name="Second"), ANONYMOUS)
    validate_error(resp_dup, ApiErrorId.ERR_INVALID_REQUEST)
    third = validate_success(api.create_candidate(
        create_candidate_payload(email="other@example.com", full_name="Third"), ANONYMOUS), 201)
    assert third["id"] != first["id"]


def test_syllabus_credit_map_default_empty(api):
    """PRD §3.2: "Creating a syllabus version requires a unique `version_code`
    ... and accepts an optional `credit_map` describing how credits on outgoing
    exams carry forward; when omitted, the map defaults to empty. The new
    version is born `DRAFT`, and its `activated_at` remains null until
    activation."

    Design: Corner/entities/syllabus_credit_map_default_empty
    """
    syllabus = make_syllabus(api, version_code="2026-A")
    assert syllabus["credit_map"] == {}
    assert syllabus["status"] == "DRAFT"
    assert syllabus["activated_at"] is None


def test_module_cooldown_default_echoed(api):
    """PRD §3.5: "A module takes a unique `module_code`, the `track_code` it
    belongs to, a `sequence_index` of at least 1 that is unique within its
    track and fixes the attempt order, a `title`, an optional `is_capstone`
    flag defaulting to false, a `passing_score` between 1 and 100 inclusive,
    and an optional `cooldown_days` of at least 0 that defaults to 14 days
    when omitted."

    Design: Corner/entities/module_cooldown_default_echoed
    """
    payload = {"module_code": "QFI-M1", "track_code": "QFI", "sequence_index": 1,
               "title": "QF Module 1", "passing_score": 70}
    module = validate_success(api.create_module(payload, REGISTRAR), 201)
    assert module["cooldown_days"] == 14
    assert module["is_capstone"] is False


def test_transfer_equivalency_mutual_recognition_tiers(api):
    """PRD §3.8: "a bilateral request grants the smaller of the claimed hours
    and thirty; a non-bilateral request grants the smaller of half the claimed
    hours — rounded half-up to a whole hour — and fifteen; an unrecognized
    request grants zero. The `status` is `GRANTED` for the two recognized
    classes and `DENIED` for an unrecognized body."
    PRD §3.1: "`transfer_credit_hours` sums `granted_hours` over the
    candidate's transfer-credit requests whose status is `GRANTED`."

    Design: Corner/entities/transfer_equivalency_mutual_recognition_tiers
    """
    candidate = make_candidate(api)
    r1 = make_transfer(api, candidate, "IFOA", TRANSFER_IFOA_CLAIM)
    assert r1["status"] == "GRANTED"
    assert r1["agreement_class"] == "BILATERAL"
    assert r1["granted_hours"] == TRANSFER_IFOA_GRANTED
    r2 = make_transfer(api, candidate, "CIA", TRANSFER_CIA_CLAIM)
    assert r2["granted_hours"] == TRANSFER_CIA_GRANTED
    r3 = make_transfer(api, candidate, "CAS", TRANSFER_CAS_CLAIM)
    assert r3["agreement_class"] == "NON_BILATERAL"
    assert r3["granted_hours"] == TRANSFER_CAS_GRANTED
    r4 = make_transfer(api, candidate, "IAA", TRANSFER_IAA_CLAIM)
    assert r4["granted_hours"] == TRANSFER_IAA_GRANTED
    r5 = make_transfer(api, candidate, "OTHER", TRANSFER_OTHER_CLAIM)
    assert r5["status"] == "DENIED"
    assert r5["granted_hours"] == TRANSFER_OTHER_GRANTED

    refreshed = get_candidate(api, candidate["id"])
    assert refreshed["transfer_credit_hours"] == TRANSFER_TOTAL_ALL_TIERS
    assert refreshed["earned_exam_credit_hours"] == 0
    assert_candidate_credit_totals(refreshed)


def test_listing_pagination_and_status_filter(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; when omitted it defaults to 10, and it is bounded below by 1
    and above by 100."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns
    resources sorted by their creation timestamp in ascending order."

    Design: Corner/entities/listing_pagination_and_status_filter
    """
    syllabus = make_syllabus(api, version_code="2026-A")
    for i in range(1, 13):
        validate_success(api.create_exam(
            {"exam_code": f"E{i:02d}", "title": f"Exam {i:02d}", "credit_hours": 1,
             "syllabus_version_id": syllabus["id"]}, REGISTRAR), 201)

    data, meta = validate_paginated(api.list_exams(REGISTRAR, params={"limit": 5}))
    assert len(data) == 5
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert data[0]["exam_code"] == "E01"

    data_active, meta_active = validate_paginated(
        api.list_exams(REGISTRAR, params={"status": "ACTIVE"}))
    assert data_active == []
    assert meta_active["total_count"] == 0

    data_default, meta_default = validate_paginated(api.list_exams(REGISTRAR))
    assert len(data_default) == 10
    assert meta_default["total_count"] == 12
    assert meta_default["has_more"] is True


def test_syllabus_double_activation_rejected(api):
    """PRD §3.2: "Activation is the pivotal act of syllabus governance,
    performed by a `Registrar` on a version still `DRAFT` — activating a
    version in any other state is rejected with
    `ERR_SYLLABUS_ACTIVATION_INVALID`."

    Design: Corner/errors/syllabus_double_activation_rejected
    """
    syllabus = make_syllabus(api, version_code="2026-A")
    activated = activate_syllabus(api, syllabus["id"])
    assert activated["status"] == "ACTIVE"
    resp = api.activate_syllabus_version(syllabus["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_SYLLABUS_ACTIVATION_INVALID)
