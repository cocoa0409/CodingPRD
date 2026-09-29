"""Round trips over the registration aggregate, the contribution link, and a repeat filing."""
from test_helpers import (
    COMPLIANCE,
    COMPLIANCE_2,
    COMPLIANCE_USER_ID_2,
    DEFAULT_CLOCK_INSTANT,
    DEFAULT_CLOCK_STAMP,
    DIRECTOR,
    TRUSTEE,
    api_client,
    assert_bare_uuid,
    assert_instant_equals,
    assert_registration,
    create_contribution_payload,
    create_registration_payload,
    open_fund,
    read_candidate,
    read_notice,
    read_report,
    register_candidate,
    setup_certified_report,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_registration_round_trips_and_its_empty_subresource_lists_are_pages():
    """Create, read back unchanged, and two well-formed empty child pages.

    PRD 2.3: "Both appear in the `meta` object of the response envelope alongside
    `total_count` (the number of items that match the request before pagination is applied)
    and `has_more` (true when items remain beyond the returned page)."
    PRD 3.5: "A draft starts in `DRAFT` with `amendment_round` at 0, `filed_at` and
    `terminated_at` null, and both year-to-date accumulators at 0."

    Design: Corner/Endpoints/registration_create_read_and_subresource_lists_round_trip
    """
    payload = create_registration_payload()
    created = validate_success(
        api_client.create_lobbying_registration(payload, COMPLIANCE), 201
    )
    assert_bare_uuid(created["id"])
    assert_registration(created)
    for field, value in payload.items():
        assert created[field] == value
    assert created["status"] == "DRAFT"
    assert created["filed_at"] is None
    assert created["terminated_at"] is None
    assert created["amendment_round"] == 0
    assert created["ytd_reportable_cents"] == 0
    assert float(created["ytd_reportable_hours"]) == 0.000
    assert created["version"] == 1

    fetched = validate_success(
        api_client.get_lobbying_registration(created["id"], COMPLIANCE), 200
    )
    assert fetched == created

    activity_rows, activity_meta = validate_paginated(
        api_client.list_registration_activities(
            created["id"], DIRECTOR, params={"limit": 50, "offset": 0}
        )
    )
    assert activity_rows == []
    assert activity_meta["total_count"] == 0
    assert activity_meta["has_more"] is False

    report_rows, report_meta = validate_paginated(
        api_client.list_registration_expenditure_reports(
            created["id"], TRUSTEE, params={"limit": 50, "offset": 0}
        )
    )
    assert report_rows == []
    assert report_meta["total_count"] == 0
    assert report_meta["has_more"] is False


def test_a_candidates_contribution_list_spans_every_fund_that_supported_it():
    """The same rows are reachable from both ends of the link, and the filter narrows.

    PRD 2.3: "A `status` filter narrows a list to rows whose own status value matches —
    committee seats, positions, votes, activities, reports, alerts, prior approvals, and
    contributions all support it."
    PRD 3.9: "An accepted proposal is written in `PENDING_BOARD` status with
    `proposed_by_user_id` taken from `X-User-ID`, `board_approved_by_user_id`,
    `disbursed_at`, `voided_at` and `void_reason` all null, and it adds its `amount_cents`
    to the candidate's `pending_support_cents`."

    Design: Corner/Endpoints/candidate_pac_contributions_lists_rows_from_every_fund
    """
    fund_a = open_fund(name="NMA Political Action Fund A", min_reserve_cents=0)
    fund_b = open_fund(name="NMA Political Action Fund B", min_reserve_cents=0)
    candidate = register_candidate(voting_alignment_pct=90.00, committee_relevance_score=80)

    first = validate_success(
        api_client.create_pac_contribution(
            create_contribution_payload(
                fund_a["id"],
                candidate["id"],
                amount_cents=50_000,
                memo="Committee-aligned incumbent, fund A",
            ),
            DIRECTOR,
        ),
        201,
    )
    second = validate_success(
        api_client.create_pac_contribution(
            create_contribution_payload(
                fund_b["id"],
                candidate["id"],
                amount_cents=50_000,
                memo="Committee-aligned incumbent, fund B",
            ),
            DIRECTOR,
        ),
        201,
    )
    for row, memo in ((first, "fund A"), (second, "fund B")):
        assert float(row["support_score"]) == 80.50
        assert row["max_allowed_cents"] == 250_000
        assert row["status"] == "PENDING_BOARD"
        assert row["memo"].endswith(memo)

    rows, meta = validate_paginated(
        api_client.list_candidate_pac_contributions(
            candidate["id"], TRUSTEE, params={"limit": 50, "offset": 0}
        )
    )
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert meta["total_count"] == 2
    assert {row["fund_id"] for row in rows} == {fund_a["id"], fund_b["id"]}

    disbursed_rows, disbursed_meta = validate_paginated(
        api_client.list_candidate_pac_contributions(
            candidate["id"], TRUSTEE, params={"limit": 50, "offset": 0, "status": "DISBURSED"}
        )
    )
    assert disbursed_rows == []
    assert disbursed_meta["total_count"] == 0

    fund_rows, fund_meta = validate_paginated(
        api_client.list_fund_pac_contributions(
            fund_a["id"], COMPLIANCE, params={"limit": 50, "offset": 0}
        )
    )
    assert [row["id"] for row in fund_rows] == [first["id"]]
    assert fund_meta["total_count"] == 1

    stored = read_candidate(candidate["id"])
    assert stored["pending_support_cents"] == 100_000


def test_a_second_certification_is_a_state_error_and_counts_the_total_once():
    """The state gate answers ahead of the segregation-of-duties comparison.

    PRD 3.6: "Certification is the act of filing, and it moves the report `OPEN →
    CERTIFIED`."
    PRD 2.11: "This ordering is normative: a request that is both unauthenticated and
    malformed reports `ERR_UNAUTHENTICATED`, and a request whose committee roster is still
    forming and whose position is in the wrong state reports the state error first, because
    the state gate sits above the roster gate."

    Design: Corner/Errors/certifying_an_already_certified_report_rejected
    """
    state = setup_certified_report(
        [{"activity_date": "2026-02-15", "hours": 2.000, "expenditure_cents": 300_000}],
        period_code="2026Q1",
        certify_on=DEFAULT_CLOCK_INSTANT,
        certify_headers=COMPLIANCE_2,
    )
    report = state["report"]
    assert report["status"] == "CERTIFIED"
    assert report["certified_by_user_id"] == COMPLIANCE_USER_ID_2
    assert_instant_equals(report["certified_at"], DEFAULT_CLOCK_STAMP, "certified_at")
    assert report["late"] is True
    assert report["filed_total_cents"] == 300_000

    validate_error(
        api_client.certify_expenditure_report(report["id"], COMPLIANCE),
        "ERR_INVALID_REPORT_STATE",
        409,
    )

    stored = read_report(state["registration"]["id"], report["id"])
    assert stored["certified_by_user_id"] == COMPLIANCE_USER_ID_2
    assert_instant_equals(stored["certified_at"], DEFAULT_CLOCK_STAMP, "certified_at")

    notice = read_notice(state["members"][0]["id"])
    assert notice["lobbying_spend_cents"] == 300_000
