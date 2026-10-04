"""Queue B (corner) — providers, members, works: defaults, validation, listing."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_service_provider_payload, create_member_payload, create_work_payload,
    create_member, create_active_schedule, setup_active_dsp, set_clock,
    create_report_with_lines,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
PUBLIC = TEST_USERS["public_headers"]


def test_create_service_provider_defaults(api):
    """PRD §3.1: "The new provider begins in `PENDING` participation status with
    `audit_credits` at zero, and it cannot file usage until activated."
    PRD §2.4: "`version`, an integer that starts low and increments by one on
    every mutation of that resource."

    Design: Corner/entities/create_service_provider_required_fields_and_defaults
    """
    dsp = validate_success(
        api_client.create_service_provider(
            create_service_provider_payload(), ADMIN),
        expected_status=201)
    assert dsp["participation_status"] == "PENDING"
    assert dsp["audit_credits"] == 0
    assert dsp["version"] == 1


def test_create_service_provider_missing_legal_name(api):
    """PRD §2.7: "a malformed body or a missing required field is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400) — and then state and business rules, in
    that order."

    Design: Corner/entities/create_service_provider_missing_legal_name_returns_invalid_request
    """
    validate_error(api_client.create_service_provider({}, ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST)


def test_get_member_not_found(api):
    """PRD §2.7: "The not-found errors are resource-specific:
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_PAYEE_NOT_FOUND`, `ERR_WORK_NOT_FOUND`, `ERR_SHARE_NOT_FOUND`,
    `ERR_RATE_SCHEDULE_NOT_FOUND`, `ERR_USAGE_REPORT_NOT_FOUND`,
    `ERR_USAGE_LINE_NOT_FOUND`, `ERR_ACCRUAL_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_DISPUTE_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
    and `ERR_CYCLE_RUN_NOT_FOUND`."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    validate_error(api_client.get_member(NON_EXISTENT_UUID, ADMIN),
                   ApiErrorId.ERR_MEMBER_NOT_FOUND)


def test_list_members_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10 when omitted, accepts a minimum of 1, and is
    capped at a maximum of 100. The `offset` parameter sets how many items to
    skip and defaults to 0."

    Design: Corner/entities/list_members_pagination_envelope
    """
    create_member(legal_name="Alder Publishing", ipi_number="00000000101")
    create_member(legal_name="Birch Songs", ipi_number="00000000202",
                  member_type="SELF_PUBLISHED_SONGWRITER")
    resp = api_client.list_members(PUBLIC)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_member_ipi_uniqueness_enforced(api):
    """PRD §3.9: "an optional `ipi_number` (unique across members that carry
    one, null permitted for members without one)"

    Design: Corner/entities/member_ipi_uniqueness_enforced
    """
    create_member(legal_name="Alder Publishing", ipi_number="00000000101")
    validate_error(
        api_client.create_member(
            create_member_payload(legal_name="Alder Copycat"), ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST)


def test_work_iswc_uniqueness_enforced(api):
    """PRD §3.2: "A work is registered with a `title` and an optional `iswc`;
    the ISWC, when present, must be unique among works that carry one, while
    works without an ISWC are permitted freely."

    Design: Corner/entities/work_iswc_uniqueness_enforced
    """
    validate_success(api_client.create_work(
        create_work_payload(title="Kestrel", iswc="T0000000001"), ADMIN),
        expected_status=201)
    validate_error(
        api_client.create_work(
            create_work_payload(title="Kestrel (alt)", iswc="T0000000001"), ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST)


def test_usage_line_rejects_zero_plays(api):
    """PRD §3.3: "each carrying the `isrc` of the sound recording (exactly 12
    characters: two letters, three alphanumeric characters, then seven digits),
    the `track_title` as the provider reported it, a `plays_count` greater than
    zero, and a `duration_seconds` greater than zero."

    Design: Corner/entities/usage_line_rejects_zero_plays
    """
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, _ack = setup_active_dsp()
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-08", [])
    validate_error(
        api_client.create_usage_line(dsp["id"], report["id"], {
            "isrc": "USAA19900051", "track_title": "Sora",
            "plays_count": 0, "duration_seconds": 100,
        }, dsp_headers),
        ApiErrorId.ERR_INVALID_REQUEST)


def test_delivered_statement_cannot_be_reopened(api):
    """PRD §3.7: "Delivery moves a `FINALIZED` statement to `DELIVERED`, at
    which point the statement and its lines become immutable — no update
    endpoint exists."
    PRD §3.7: "A `FINALIZED` statement may be reopened to `DRAFT` for revision"

    Design: Corner/entities/statement_line_immutability
    """
    from test_helpers import setup_member_with_payee
    member, _payee = setup_member_with_payee()
    st = validate_success(api_client.create_statement(member["id"], "2026-06", ADMIN),
                          expected_status=201)
    validate_success(api_client.finalize_statement(member["id"], st["id"], ADMIN))
    validate_success(api_client.deliver_statement(member["id"], st["id"], ADMIN))
    validate_error(api_client.reopen_statement(member["id"], st["id"], ADMIN),
                   ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_statement(member["id"], st["id"], ADMIN))
    assert after["status"] == "DELIVERED"
