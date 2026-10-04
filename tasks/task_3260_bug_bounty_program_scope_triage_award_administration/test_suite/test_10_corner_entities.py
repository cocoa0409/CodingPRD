"""Corner tests (entities): creation defaults, required fields, system fields,
404s, listing/pagination, and cross-program references."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    get_success_data,
    make_researcher_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_program_payload, create_report_payload
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    create_asset,
    create_program,
    create_scope_version,
    get_program,
    register_researcher,
    setup_active_program,
    submit_report,
)


def test_program_create_defaults_applied(api):
    """PRD §3.1: "Optional knobs come with defaults: `visibility` defaults to
    `PUBLIC` and may instead be `PRIVATE` ... `first_report_bonus_pct` defaults
    to 0.10 ... `retest_award_cents` defaults to 50000 as the flat retest award;
    `bonus_cap_cents` defaults to 100000 as the ceiling on discretionary bonus
    awards; `exposure_modifier` defaults to 1.0 as a program-wide environmental
    severity multiplier; and `blackout_windows` defaults to an empty list. A new
    program starts in `DRAFT` posture with all ledger counters at zero."

    Design: Corner/entities/program_create_defaults_applied
    """
    program = create_program()
    assert program["status"] == "DRAFT"
    assert program["visibility"] == "PUBLIC"
    assert program["version"] == 1
    assert program["bounty_reserved_cents"] == 0
    assert program["bounty_paid_cents"] == 0
    assert program["total_withheld_cents"] == 0
    assert program["available_pool_cents"] == 5_000_000


def test_researcher_missing_required_country_returns_invalid_request(api):
    """PRD §3.3: "Anyone may self-register as a researcher by providing a unique
    `handle`, a contact `email`, and a `country_code` giving their ISO 3166-1
    alpha-2 residence country."
    PRD §2.5: "any request payload that is missing a required field, carries a
    malformed value, names an unknown or read-only field, or supplies an invalid
    enum member is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/researcher_missing_required_country_returns_invalid_request
    """
    resp = api.create_researcher(
        {"handle": "rx", "email": "rx@x.com"}, TEST_USERS["anonymous_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_read_only_field_in_report_payload_returns_invalid_request(api):
    """PRD §2.5: "any request payload that is missing a required field, carries a
    malformed value, names an unknown or read-only field, or supplies an invalid
    enum member is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.5: "A researcher submits a report as themselves — the submitting
    `researcher_id` is taken from the caller's `X-User-ID`, not from the payload —
    by naming the `program_id`, the target `asset_id`, a `title`, a `description`
    covering reproduction steps and impact, and a `vulnerability_class` of `XSS`,
    `SQLI`, `CSRF`, `SSRF`, `AUTHZ`, `RCE`, or `OTHER`."

    Design: Corner/entities/read_only_field_in_report_payload_returns_invalid_request
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    payload = create_report_payload(program["id"], asset["id"])
    payload["severity_final"] = "CRITICAL"
    resp = api.create_report(payload, make_researcher_headers(researcher["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_program_not_found_returns_404(api):
    """PRD §2.5: "4. **Path existence** — every resource identifier appearing in
    the URL path must exist, validated strictly left to right; the first missing
    identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_program_not_found_returns_404
    """
    resp = api.get_program(NON_EXISTENT_UUID, PLATFORM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_reports_list_pagination_and_filter(api):
    """PRD §2.3: "List endpoints paginate via the `limit` and `offset` query
    parameters. `limit` caps the number of returned items, defaults to 10 when
    omitted, and must lie between 1 and 100 inclusive. `offset` skips a number of
    items and defaults to 0. Every list response is sorted by the resources'
    `created_at` timestamp in ascending order unless stated otherwise, and every
    list response's `meta` object carries `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/reports_list_pagination_and_filter
    """
    program, asset = setup_active_program()
    researcher = register_researcher()
    submit_report(program, asset, researcher, title="one")
    submit_report(program, asset, researcher, title="two", vulnerability_class="SQLI")
    page1_resp = api.list_reports(TRIAGER, params={"status": "NEW", "limit": 1})
    page1, meta1 = validate_paginated(page1_resp)
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert len(page1) == 1
    page2_resp = api.list_reports(TRIAGER, params={"status": "NEW", "limit": 1, "offset": 1})
    page2, meta2 = validate_paginated(page2_resp)
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert len(page2) == 1
    assert page2[0]["id"] != page1[0]["id"]


def test_cross_program_asset_reference_out_of_scope(api):
    """PRD §2.5: "10. **Scope conformance** — the asset referenced by a new
    report must belong to the program, be `ACTIVE`, and appear in the scope
    version effective at submission time, else `ERR_OUT_OF_SCOPE` (HTTP 422)."

    Design: Corner/entities/cross_program_asset_reference_out_of_scope
    """
    program1, asset1 = setup_active_program()
    program2, asset2 = setup_active_program(criticality="HIGH")
    researcher = register_researcher()
    resp = api.create_report(
        create_report_payload(program1["id"], asset2["id"]),
        make_researcher_headers(researcher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUT_OF_SCOPE)
