"""Corner queue, entities section: creation shape, defaults, scoped
uniqueness, not-found, pagination, strict request schemas."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    CLOCK_START,
    NON_EXISTENT_UUID,
    add_candidate_contest,
    add_filing,
    assert_instant_equals,
    create_volunteer,
    fresh_league,
    get_success_data,
    is_valid_uuid,
    make_contest_payload,
    make_cycle_payload,
    make_filing_payload,
    make_jurisdiction_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_cycle_create_returns_declared_fields_and_starts_draft(api, admin_headers):
    """PRD §3.1: "the cycle is born `DRAFT`" and "A cycle also tracks
    `distributed_edition_count`, the number of its guide editions currently
    in `DISTRIBUTED` status".
    PRD §2.5: "`id`, a server-minted UUID with no type prefix; `created_at`,
    an ISO 8601 UTC timestamp with three fractional digits recording the
    logical creation time".
    PRD §2.4: "Before any administrator action the clock reads exactly
    2026-09-01T00:00:00Z, the server startup default."

    Design: Corner/entities/cycle_create_returns_declared_fields_and_starts_draft
    """
    resp = api.create_cycle(make_cycle_payload(), admin_headers)
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"])
    assert data["status"] == "DRAFT"
    assert data["distributed_edition_count"] == 0
    assert data["cycle_name"] == "2026 General"
    assert data["election_date"] == "2026-11-03"
    assert_instant_equals(data["created_at"], CLOCK_START, "created_at")
    assert isinstance(data["version"], int)


def test_jurisdiction_duplicate_fips_in_same_cycle_rejected(api, admin_headers):
    """PRD §3.1: "an official `fips_code` that must be unique within the
    parent cycle (a repeat is rejected with `ERR_DUPLICATE_FIPS`)"."

    Design: Corner/entities/jurisdiction_duplicate_fips_in_same_cycle_rejected
    """
    cycle_a = get_success_data(
        api.create_cycle(make_cycle_payload(cycle_name="Cycle A"), admin_headers)
    )
    cycle_b = get_success_data(
        api.create_cycle(make_cycle_payload(cycle_name="Cycle B"), admin_headers)
    )
    get_success_data(
        api.create_jurisdiction(cycle_a["id"], make_jurisdiction_payload(),
                                admin_headers),
        expected_status=201,
    )
    dup = api.create_jurisdiction(
        cycle_a["id"],
        make_jurisdiction_payload(jurisdiction_name="Springfield Heights",
                                  reading_level_metric="SMOG"),
        admin_headers,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_FIPS)
    assert dup.status_code == 409

    other_cycle = api.create_jurisdiction(
        cycle_b["id"],
        make_jurisdiction_payload(jurisdiction_name="Other Springfield",
                                  reading_level_metric="SMOG"),
        admin_headers,
    )
    data = validate_success(other_cycle, expected_status=201)
    assert data["fips_code"] == "06001"


def test_filing_reference_reuse_rejected_in_same_contest_only(api):
    """PRD §3.2: "a `filing_reference` that must be unique within the
    contest (`ERR_DUPLICATE_FILING_REFERENCE`)"."

    Design: Corner/entities/filing_reference_reuse_rejected_in_same_contest_only
    """
    ctx = fresh_league(api)
    ct1 = add_candidate_contest(api, ctx, office_name="Mayor")
    ct2 = add_candidate_contest(api, ctx, office_name="Clerk")
    add_filing(api, ctx, ct1["id"], verify=False)

    dup = api.create_filing(
        ct1["id"],
        make_filing_payload(candidate_name="Copy Cat", filing_reference="F-1"),
        ctx["coordinator_h"],
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_FILING_REFERENCE)
    assert dup.status_code == 409

    sibling = api.create_filing(
        ct2["id"],
        make_filing_payload(candidate_name="Other Person", filing_reference="F-1"),
        ctx["coordinator_h"],
    )
    data = validate_success(sibling, expected_status=201)
    assert data["filing_reference"] == "F-1"


def test_contest_get_with_random_uuid_returns_not_found(api):
    """PRD §2.7: "Only then are path identifiers resolved, strictly left to
    right, with the first unresolvable id producing `ERR_NOT_FOUND`"."

    Design: Corner/entities/contest_get_with_random_uuid_returns_not_found
    """
    ctx = fresh_league(api)
    resp = api.get_contest(NON_EXISTENT_UUID, ctx["coordinator_h"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_filings_list_paginates_with_limit_offset_and_envelope_fields(api):
    """PRD §2.3: "List endpoints accept `limit` and `offset` query
    parameters." and "List responses carry `limit`, `offset`, `total_count`,
    and `has_more` in `meta`."

    Design: Corner/entities/filings_list_paginates_with_limit_offset_and_envelope_fields
    """
    ctx = fresh_league(api)
    contest = add_candidate_contest(api, ctx)
    for i, name in enumerate(("Ana One", "Bob Two", "Cid Three"), start=1):
        add_filing(api, ctx, contest["id"], candidate_name=name,
                   filing_reference=f"F-{i}", verify=False)

    page1, meta1 = validate_paginated(
        api.list_filings(contest["id"], ctx["coordinator_h"],
                         params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_filings(contest["id"], ctx["coordinator_h"],
                         params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_contest_create_with_undeclared_or_computed_field_rejected(api):
    """PRD §2.7: "then request-body well-formedness (`ERR_INVALID_REQUEST` —
    covering missing or undeclared fields, bad types or enum members, the
    `office_name` kind rule, duplicate question positions, incomplete answer
    coverage, out-of-range channel tiers, and missing `minutes_text` or
    `corrective_action` where those are required)".

    Design: Corner/entities/contest_create_with_undeclared_or_computed_field_rejected
    """
    ctx = fresh_league(api)
    payload = make_contest_payload()
    payload["completion_index"] = 99.9  # computed field is never client-settable
    resp = api.create_contest(ctx["jurisdiction"]["id"], payload,
                              ctx["coordinator_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400


def test_volunteer_created_with_current_attestation_and_ninety_day_expiry(api):
    """PRD §3.1: "A new volunteer is `ACTIVE` with a `CURRENT` attestation
    whose `attestation_expires_at` is set to ninety days after creation."
    and "an optional `advocacy_flag` that defaults to false".

    Design: Corner/entities/volunteer_created_with_current_attestation_and_ninety_day_expiry
    """
    set_clock(api, CLOCK_START)
    resp = api.create_volunteer(
        {
            "volunteer_name": "Vic Volunteer",
            "chapter_code": "CH9",
            "roles": ["EDITOR", "REVIEWER"],
        },
        TEST_USERS["admin_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["advocacy_flag"] is False
    assert data["status"] == "ACTIVE"
    assert data["attestation_status"] == "CURRENT"
    # 2026-09-01T00:00:00Z + 90 days == 2026-11-30T00:00:00Z
    assert_instant_equals(data["attestation_expires_at"], "2026-11-30T00:00:00Z",
                          "attestation_expires_at")
    assert_instant_equals(data["created_at"], CLOCK_START, "created_at")
    assert data["substantiated_incident_count"] == 0


def test_measure_contest_with_office_name_rejected(api):
    """PRD §3.2: "An `office_name` is required when and only when the kind
    is `CANDIDATE_RACE`, and must be omitted for a ballot measure; violating
    either direction is a malformed request (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/measure_contest_with_office_name_rejected
    """
    ctx = fresh_league(api)
    with_office = api.create_contest(
        ctx["jurisdiction"]["id"],
        {"kind": "BALLOT_MEASURE", "office_name": "Measure Office",
         "filing_deadline": "2026-09-15T17:00:00Z"},
        ctx["coordinator_h"],
    )
    validate_error(with_office, ApiErrorId.ERR_INVALID_REQUEST)
    assert with_office.status_code == 400

    without_office = api.create_contest(
        ctx["jurisdiction"]["id"],
        {"kind": "CANDIDATE_RACE", "filing_deadline": "2026-09-15T17:00:00Z"},
        ctx["coordinator_h"],
    )
    validate_error(without_office, ApiErrorId.ERR_INVALID_REQUEST)
    assert without_office.status_code == 400
