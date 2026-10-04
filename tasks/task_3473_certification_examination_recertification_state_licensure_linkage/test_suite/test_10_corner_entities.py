"""Queue B — entities: creation, system fields, defaults, required fields, and
simple computed fields on the registry's resources.
"""
from datetime import datetime, timezone

from test_helpers import (
    ADMIN,
    ANONYMOUS_HEADERS,
    ApiErrorId,
    CLOCK_DEFAULT_ISO,
    NON_EXISTENT_UUID,
    api_client,
    assert_candidate,
    assert_level_definition,
    assert_state_adoption_policy,
    assert_state_exam_passed_computed,
    ce_entry_payload,
    create_candidate,
    create_exam_application,
    create_level,
    create_level_payload,
    create_state_exam_record,
    is_valid_uuid,
    make_candidate_headers,
    setup_candidate_with_verified_completion,
    setup_recert_draft_with_entries,
    validate_error,
    validate_success,
)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_level_definition_create_persists_fields(api):
    """PRD §3.1: "Each **certification level** is defined with a unique `code` —
    one of `EMR`, `EMT`, `AEMT`, or `PARAMEDIC` — plus a human-readable
    `display_name` and a `scope_summary` describing the level's distinct scope
    of practice."
    PRD §2.5: "Before any call, the logical clock stands at exactly
    2026-09-01T00:00:00Z, and it must never fall back to wall-clock time."
    PRD §2.4: "`id` — a server-minted UUID with no type prefix."
    PRD §2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional
    digits, recording when the resource was created."

    Design: Corner/entities/level_definition_create_persists_fields
    """
    resp = api_client.create_level_definition(create_level_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert_level_definition(data)
    assert data["code"] == "EMT"
    assert data["cognitive_cut_score"] == 0.66
    assert data["ce_national_min_hours"] == 20
    assert data["refresher_hours_required"] == 24
    assert is_valid_uuid(data["id"])
    assert _ts(data["created_at"]) == _ts(CLOCK_DEFAULT_ISO), (
        f"created_at reads the logical clock default, got {data['created_at']}"
    )


def test_level_definition_duplicate_code_conflict(api):
    """PRD §3.1: "Defining a level whose `code` already exists is rejected with
    `ERR_DUPLICATE_LEVEL_CODE`."

    Design: Corner/entities/level_definition_duplicate_code_conflict
    """
    create_level()
    resp = api_client.create_level_definition(
        create_level_payload(display_name="Duplicate", scope_summary="dup",
                             cognitive_cut_score=0.5),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LEVEL_CODE)


def test_state_policy_defaults_applied(api):
    """PRD §3.1: "states whether a `jurisprudence_exam_required` attestation is
    demanded, defaulting to false; and sets the fee schedule:
    `base_license_fee_cents`, an optional `national_verification_surcharge_cents`
    applied on the national-certification path (default zero), an optional
    `state_exam_fee_cents` applied on the state-exam path (default zero), and
    the registry's `registry_share_bps` revenue share in basis points,
    defaulting to 1500 — that is, fifteen percent."

    Design: Corner/entities/state_policy_defaults_applied
    """
    # Only the required keys plus accepted_level_codes are sent, so the
    # server-side defaults apply to every omitted optional field.
    resp = api_client.create_state_adoption_policy(
        {"state_code": "WA", "adoption_mode": "NREMT_ACCEPTED",
         "accepted_level_codes": ["EMT"], "base_license_fee_cents": 9990},
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_state_adoption_policy(data)
    assert data["jurisprudence_exam_required"] is False
    assert data["registry_share_bps"] == 1500
    assert data["national_verification_surcharge_cents"] == 0
    assert data["state_exam_fee_cents"] == 0


def test_candidate_registration_mints_system_fields(api):
    """PRD §3.2: "Anyone may self-register as a **candidate** with a `full_name`
    and an `email`; the record starts in `REGISTERED` status, and its `id`
    becomes the caller's identity for everything that follows. The record also
    exposes `disciplinary_hold`, a live-computed flag that is false at
    registration and true whenever any disciplinary case against the candidate
    that has not yet reached `FINAL` carries the interim action
    `HOLD_NEW_APPLICATIONS`."
    PRD §2.5: "Before any call, the logical clock stands at exactly
    2026-09-01T00:00:00Z, and it must never fall back to wall-clock time."

    Design: Corner/entities/candidate_registration_mints_system_fields
    """
    resp = api_client.register_candidate(
        {"full_name": "Nina New", "email": "nina@example.com"}, ANONYMOUS_HEADERS,
    )
    data = validate_success(resp, 201)
    assert_candidate(data)
    assert is_valid_uuid(data["id"])
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] == "REGISTERED"
    assert data["disciplinary_hold"] is False
    assert _ts(data["created_at"]) == _ts(CLOCK_DEFAULT_ISO)


def test_get_unknown_candidate_returns_404(api):
    """PRD §2.8: "4. **Existence.** Path identifiers must exist, validated left
    to right so that the first missing identifier in the path is the one
    reported, and every record referenced in the body must exist
    (`ERR_NOT_FOUND`)."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/get_unknown_candidate_returns_404
    """
    resp = api_client.get_candidate(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "message" in body["data"]


def test_candidate_missing_email_fails(api):
    """PRD §3.2: "Anyone may self-register as a **candidate** with a `full_name`
    and an `email`".
    PRD §2.8: "3. **Request shape.** Required fields are present, types match,
    enum values are valid, station lists are non-empty, a scheduling window's
    end is strictly after its start, examination dates are not in the future,
    hour quantities are positive, and a response-delivery payload carries no
    more than twelve item responses (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/candidate_missing_email_fails
    """
    resp = api_client.register_candidate({"full_name": "No Email"}, ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_level_code_outside_enum_fails(api):
    """PRD §3.1: "Each **certification level** is defined with a unique `code` —
    one of `EMR`, `EMT`, `AEMT`, or `PARAMEDIC`".
    PRD §2.8: "3. **Request shape.** Required fields are present, types match,
    enum values are valid, station lists are non-empty, a scheduling window's
    end is strictly after its start, examination dates are not in the future,
    hour quantities are positive, and a response-delivery payload carries no
    more than twelve item responses (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/level_code_outside_enum_fails
    """
    resp = api_client.create_level_definition(
        create_level_payload(code="SUPEREMT"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_ce_entry_half_hour_increment_enforced(api):
    """PRD §3.6: "the `hours` earned, a positive multiple of one half hour
    (`ERR_CE_HOURS_INCREMENT`)".
    PRD §2.8: "On the continuing-education entry endpoint specifically, one
    further shape check sits between this tier and existence: hours must be a
    positive multiple of one half hour (`ERR_CE_HOURS_INCREMENT`)."

    1.3 hours is rejected; 1.5 hours is accepted and recorded.

    Design: Corner/entities/ce_entry_half_hour_increment_enforced
    """
    ctx = setup_recert_draft_with_entries(entry_specs=[])
    owner = make_candidate_headers(ctx["candidate"]["id"])
    bad = api_client.add_ce_entry(
        ctx["recert_application"]["id"],
        ce_entry_payload("NATIONAL", 1.3, "IN_PERSON", "2027-10-01", "AlphaCE"),
        owner,
    )
    validate_error(bad, ApiErrorId.ERR_CE_HOURS_INCREMENT)
    good = api_client.add_ce_entry(
        ctx["recert_application"]["id"],
        ce_entry_payload("NATIONAL", 1.5, "IN_PERSON", "2027-10-01", "AlphaCE"),
        owner,
    )
    data = validate_success(good, 201)
    assert data["status"] == "RECORDED"


def test_state_exam_record_passed_boundary(api):
    """PRD §3.8: "A `StateOfficial` may register a state's **own examination**
    result — `candidate_id`, `state_code`, `level_id`, the `exam_date` (not in
    the future), the reported `score`, and the state's `passing_score` — and
    the record computes `passed` as the score meeting or exceeding the passing
    threshold."

    70 against a 70 threshold passes (inclusive); 69.5 fails.

    Design: Corner/entities/state_exam_record_passed_boundary
    """
    level = create_level()
    candidate = create_candidate()
    at_boundary = create_state_exam_record(
        candidate["id"], "TX", level["id"],
        exam_date="2026-09-01", score=70, passing_score=70,
    )
    assert at_boundary["passed"] is True
    assert_state_exam_passed_computed(at_boundary)
    below = create_state_exam_record(
        candidate["id"], "TX", level["id"],
        exam_date="2026-09-01", score=69.5, passing_score=70,
    )
    assert below["passed"] is False
    assert_state_exam_passed_computed(below)


def test_exam_application_fee_snapshot(api):
    """PRD §3.4: "The application is born `SUBMITTED`, its
    `application_fee_cents` snapshotting the level's
    `initial_application_fee_cents` at creation and its `candidate_id` fixed
    from the caller's identity."

    Design: Corner/entities/exam_application_fee_snapshot
    """
    ctx = setup_candidate_with_verified_completion()
    application = create_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    assert application["status"] == "SUBMITTED"
    assert application["application_fee_cents"] == 9800, (
        f"fee snapshots the level's initial_application_fee_cents, "
        f"got {application['application_fee_cents']}"
    )
    assert application["candidate_id"] == ctx["candidate"]["id"]
