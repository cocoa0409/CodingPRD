"""Disclosure intake: event-notice timeliness, annual coverage overlap,
portal review terminal states, suspension gating, and visibility scoping
(PRD sections 2.7, 3.4, 3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_disclosure,
    create_issuer_org,
    make_issuer_rep_headers,
    review_submission,
    set_clock,
    suspend_organization,
    validate_error,
    validate_paginated,
    validate_success,
)

PUBLIC = TEST_USERS["public_reader_headers"]
PORTAL_OPERATOR = TEST_USERS["portal_operator_headers"]


def _event_notice_payload(org_id, doc_uri, category):
    return {
        "issuer_org_id": org_id,
        "submission_type": "EVENT_NOTICE",
        "event_category": category,
        "event_occurred_at": "2026-09-01T00:00:00Z",
        "document_uri": doc_uri,
        "cusip": "123456789",
    }


def test_event_notice_day_ten_timely_day_eleven_late(api):
    """PRD section 3.4: "it counts the whole calendar days between the UTC
    calendar date of `event_occurred_at` and the UTC calendar date the
    filing was received, and classifies the notice `TIMELY` when that count
    is at most ten — filing on exactly the tenth day is timely — and `LATE`
    otherwise."

    Design: Corner/calculations/event_notice_day10_timely_day11_late
    """
    org = create_issuer_org(api, org_code="IS-2001", name="Issuer Event")
    headers = make_issuer_rep_headers(org["id"])

    set_clock(api, "2026-09-11T00:00:00Z")  # the tenth calendar day after 2026-09-01
    day10 = validate_success(
        api.create_disclosure_submission(
            _event_notice_payload(org["id"], "doc://ev10", "PAYMENT_DEFAULT"), headers
        ),
        201,
    )
    assert day10["timeliness"] == "TIMELY", (
        f"filing on exactly day 10 must be TIMELY, got {day10['timeliness']!r}"
    )

    set_clock(api, "2026-09-12T00:00:00Z")  # the eleventh calendar day
    day11 = validate_success(
        api.create_disclosure_submission(
            _event_notice_payload(org["id"], "doc://ev11", "RATING_CHANGE"), headers
        ),
        201,
    )
    assert day11["timeliness"] == "LATE", (
        f"filing on day 11 must be LATE, got {day11['timeliness']!r}"
    )


def test_annual_coverage_shared_single_day_overlaps_but_adjacency_passes(api):
    """PRD section 3.4: "a new `ANNUAL_FINANCIAL` submission whose closed
    coverage interval intersects any sibling `ANNUAL_FINANCIAL` submission
    of the same issuer in `RECEIVED` or `PUBLISHED` status is rejected with
    `ERR_COVERAGE_PERIOD_OVERLAP` (HTTP 409). The comparison is
    closed-interval: two periods that share even a single calendar day
    overlap, while perfect adjacency — the new period starting the day
    after the existing period ends — is permitted."

    Design: Difficulty/resource_temporal_overlap/annual_coverage_closed_interval_overlap
    """
    org = create_issuer_org(api, org_code="IS-900", name="Issuer Nine")
    headers = make_issuer_rep_headers(org["id"])
    create_disclosure(
        api, org["id"], submission_type="ANNUAL_FINANCIAL",
        period_start="2025-01-01T00:00:00Z", period_end="2025-12-31T00:00:00Z",
        document_uri="doc://fy2025", cusip="123456789",
    )

    overlapping = api.create_disclosure_submission(
        {
            "issuer_org_id": org["id"],
            "submission_type": "ANNUAL_FINANCIAL",
            "period_start": "2025-12-31T00:00:00Z",  # shares the single day 2025-12-31
            "period_end": "2026-12-30T00:00:00Z",
            "document_uri": "doc://fy2025b",
            "cusip": "123456789",
        },
        headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP)

    adjacent = api.create_disclosure_submission(
        {
            "issuer_org_id": org["id"],
            "submission_type": "ANNUAL_FINANCIAL",
            "period_start": "2026-01-01T00:00:00Z",  # the day after the existing period ends
            "period_end": "2026-12-31T00:00:00Z",
            "document_uri": "doc://fy2026",
            "cusip": "123456789",
        },
        headers,
    )
    data = validate_success(adjacent, 201)
    assert data["status"] == "RECEIVED"


def test_annual_coverage_ignores_deficient_sibling(api):
    """PRD section 3.4: the overlap rule rejects intersection only with "any
    sibling `ANNUAL_FINANCIAL` submission of the same issuer in `RECEIVED`
    or `PUBLISHED` status" — a sibling marked `DEFICIENT` is outside that
    set, so re-filing the same coverage period after a deficiency
    determination is accepted.

    Design: Difficulty/resource_temporal_overlap/annual_coverage_closed_interval_overlap
    """
    org = create_issuer_org(api, org_code="IS-901", name="Issuer Cure")
    headers = make_issuer_rep_headers(org["id"])
    first = create_disclosure(
        api, org["id"], submission_type="ANNUAL_FINANCIAL",
        period_start="2025-01-01T00:00:00Z", period_end="2025-12-31T00:00:00Z",
        document_uri="doc://fy2025", cusip="123456789",
    )
    review_submission(api, first["id"], "DEFICIENT", deficiency_reason="missing exhibits")

    refiled = api.create_disclosure_submission(
        {
            "issuer_org_id": org["id"],
            "submission_type": "ANNUAL_FINANCIAL",
            "period_start": "2025-01-01T00:00:00Z",
            "period_end": "2025-12-31T00:00:00Z",
            "document_uri": "doc://fy2025-fixed",
            "cusip": "123456789",
        },
        headers,
    )
    data = validate_success(refiled, 201)
    assert data["status"] == "RECEIVED"


def test_deficient_submission_is_terminal(api):
    """PRD section 3.4: "`PUBLISHED` and `DEFICIENT` are both terminal;
    reviewing an already-terminal submission is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/deficient_submission_is_terminal
    """
    org = create_issuer_org(api, org_code="IS-1006", name="Issuer Six")
    submission = create_disclosure(
        api, org["id"], submission_type="VOLUNTARY", document_uri="doc://v1", cusip="123456789"
    )
    review_submission(api, submission["id"], "DEFICIENT", deficiency_reason="missing exhibits")

    resp = api.review_submission(submission["id"], {"outcome": "PUBLISH"}, PORTAL_OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_suspended_issuer_cannot_file_disclosure(api):
    """PRD section 3.4: the filing organization "must currently be
    `ACTIVE`, otherwise `ERR_ORG_SUSPENDED` (HTTP 409)".

    Design: Corner/validations/suspended_issuer_cannot_file_disclosure
    """
    org = create_issuer_org(api, org_code="IS-3008", name="Issuer Suspended")
    suspend_organization(api, org["id"], reason="failure to file")

    resp = api.create_disclosure_submission(
        {
            "issuer_org_id": org["id"],
            "submission_type": "VOLUNTARY",
            "document_uri": "doc://late",
            "cusip": "123456789",
        },
        make_issuer_rep_headers(org["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORG_SUSPENDED)


def test_event_notice_without_category_returns_event_category_required(api):
    """PRD section 3.4: "When `submission_type` is `EVENT_NOTICE`, the
    filing must include an `event_category`" and "a missing category is
    rejected with `ERR_EVENT_CATEGORY_REQUIRED` (HTTP 422)".

    Design: Corner/errors/event_notice_without_category_returns_event_category_required
    """
    org = create_issuer_org(api, org_code="IS-5007", name="Issuer Category")
    resp = api.create_disclosure_submission(
        {
            "issuer_org_id": org["id"],
            "submission_type": "EVENT_NOTICE",
            "event_occurred_at": "2026-08-30T00:00:00Z",
            "document_uri": "doc://evx",
            "cusip": "123456789",
        },
        make_issuer_rep_headers(org["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_CATEGORY_REQUIRED)


def test_public_reader_sees_only_published_disclosures(api):
    """PRD section 2.7: "a `PublicReader` sees only `PUBLISHED` disclosure
    submissions and `DISSEMINATED` trade reports" and "A single-resource
    read that exists but falls outside the caller's scope is reported as
    not-found — `ERR_SUBMISSION_NOT_FOUND` or `ERR_TRADE_NOT_FOUND` —
    never as a permission error". "`PortalOperator` and `ComplianceOfficer`
    see all submissions and trades."

    Design: Corner/endpoints/public_reader_sees_only_published_disclosures
    """
    org = create_issuer_org(api, org_code="IS-4002", name="Issuer Public")
    published = create_disclosure(
        api, org["id"], submission_type="OFFICIAL_STATEMENT",
        document_uri="doc://os1", cusip="123456789",
    )
    pending = create_disclosure(
        api, org["id"], submission_type="VOLUNTARY",
        document_uri="doc://vol1", cusip="123456789",
    )
    review_submission(api, published["id"], "PUBLISH")

    public_list, _ = validate_paginated(api.list_disclosure_submissions(PUBLIC))
    assert len(public_list) == 1, (
        f"PublicReader must see exactly the published filing, got {len(public_list)} rows"
    )
    assert public_list[0]["status"] == "PUBLISHED"

    hidden = api.get_disclosure_submission(pending["id"], PUBLIC)
    validate_error(hidden, ApiErrorId.ERR_SUBMISSION_NOT_FOUND)

    operator_list, _ = validate_paginated(api.list_disclosure_submissions(PORTAL_OPERATOR))
    assert len(operator_list) == 2, (
        f"PortalOperator must see both filings, got {len(operator_list)} rows"
    )


def test_issuer_rep_is_scoped_to_own_org_submissions(api):
    """PRD section 2.7: "An `IssuerRep` sees only its own organization's
    disclosure submissions" and scoped single reads report not-found,
    "never as a permission error, so that scoped callers cannot probe for
    the existence of other organizations' filings."

    Design: Corner/endpoints/issuer_rep_scoped_to_own_org_submissions
    """
    org_a = create_issuer_org(api, org_code="IS-4004A", name="Issuer A")
    org_b = create_issuer_org(api, org_code="IS-4004B", name="Issuer B")
    create_disclosure(api, org_a["id"], submission_type="VOLUNTARY",
                      document_uri="doc://a1", cusip="123456789")
    foreign = create_disclosure(api, org_b["id"], submission_type="VOLUNTARY",
                                document_uri="doc://b1", cusip="123456789")

    own_list, _ = validate_paginated(
        api.list_disclosure_submissions(make_issuer_rep_headers(org_a["id"]))
    )
    assert len(own_list) == 1, (
        f"IssuerRep of org A must see only org A filings, got {len(own_list)} rows"
    )
    assert own_list[0]["issuer_org_id"] == org_a["id"]

    hidden = api.get_disclosure_submission(foreign["id"], make_issuer_rep_headers(org_a["id"]))
    validate_error(hidden, ApiErrorId.ERR_SUBMISSION_NOT_FOUND)
