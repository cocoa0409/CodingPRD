"""Entity probes: single-resource reads, list pagination, and the immutable
ledger records.

Unknown ids on the case and interpreter single-GETs return their pinned 404s;
the judges list paginates with total_count spanning the whole result set and
has_more marking the final page; and the two ledger resources — DocketReview
and CaseReassignment — carry only id and created_at, with the docket-review
run_index monotonic per court.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_case_reassignment,
    assert_docket_review,
    create_court,
    create_judge,
    reassign_case,
    run_docket_review,
    same_instant,
    setup_backlog_critical_source,
    validate_error,
    validate_paginated,
    CLOCK_DEFAULT_ISO,
)


def test_case_get_with_unknown_id_returns_case_not_found(api, admin_headers):
    """PRD §2.6: "3. **Existence (HTTP 404).** Path identifiers and body foreign-key identifiers must resolve to existing resources, validated left-to-right: path parameters first, in the order they appear in the path, then body identifiers in the endpoint's declared input order. The first unresolvable identifier produces its resource-specific error — `ERR_COURT_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`, `ERR_INTERPRETER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_CONTINUANCE_NOT_FOUND`, `ERR_VENUE_MOTION_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, or `ERR_MOTION_NOT_FOUND`."

    Design: Corner/entities/case_get_with_unknown_id_returns_case_not_found
    """
    resp = api.get_case(NON_EXISTENT_UUID, headers=admin_headers)
    err = validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)
    assert resp.status_code == 404
    assert err["error_id"] == "ERR_CASE_NOT_FOUND"
    assert err["message"].strip(), "the error payload carries a human-readable message"


def test_interpreter_get_unknown_returns_not_found(api, admin_headers):
    """PRD §2.6: "3. **Existence (HTTP 404).** Path identifiers and body foreign-key identifiers must resolve to existing resources, validated left-to-right: path parameters first, in the order they appear in the path, then body identifiers in the endpoint's declared input order. The first unresolvable identifier produces its resource-specific error — `ERR_COURT_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`, `ERR_INTERPRETER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_CONTINUANCE_NOT_FOUND`, `ERR_VENUE_MOTION_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, or `ERR_MOTION_NOT_FOUND`."

    Design: Corner/entities/interpreter_get_unknown_returns_not_found
    """
    resp = api.get_interpreter(NON_EXISTENT_UUID, headers=admin_headers)
    err = validate_error(resp, ApiErrorId.ERR_INTERPRETER_NOT_FOUND)
    assert resp.status_code == 404
    assert err["error_id"] == "ERR_INTERPRETER_NOT_FOUND"


def test_judges_list_paginates_with_total_count_and_has_more(api, admin_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
    PRD §2.3: "List responses carry the following pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/entities/judges_list_paginates_with_total_count_and_has_more
    """
    court = create_court()
    judges = [create_judge(court["id"]) for _ in range(3)]
    expected_ids = {j["id"] for j in judges}

    rows1, meta1 = validate_paginated(
        api.list_judges(
            headers=admin_headers,
            params={"court_id": court["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(rows1) == 2
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 3, (
        "total_count spans the whole result set, not just the page"
    )
    assert meta1["has_more"] is True

    rows2, meta2 = validate_paginated(
        api.list_judges(
            headers=admin_headers,
            params={"court_id": court["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(rows2) == 1
    assert meta2["offset"] == 2
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False, "the final page reports no further rows"

    # The pages partition the full set; row order within the set is not pinned
    # here because all three rows share one created_at instant.
    page1_ids = {r["id"] for r in rows1}
    page2_ids = {r["id"] for r in rows2}
    assert page1_ids.isdisjoint(page2_ids)
    assert page1_ids | page2_ids == expected_ids

    rows_all, meta_all = validate_paginated(api.list_judges(headers=admin_headers))
    assert len(rows_all) == 3, "the default limit 10 / offset 0 returns all three"
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0
    assert meta_all["total_count"] == 3
    assert meta_all["has_more"] is False


def test_reassignment_and_docket_review_are_immutable_records(api, admin_headers):
    """PRD §2.5: "Two resources are immutable, ledger-style records and carry only `id` and `created_at`: `CaseReassignment` and `DocketReview`. Both `updated_at` and `version` are absent from their representations, and neither resource can be modified after creation."
    PRD §3.8: "Each run freezes an immutable `DocketReview` snapshot carrying the `court_id` under review, a per-court `run_index` that starts at 1 on the court's first run and increments by 1 with every subsequent run for that court, and `computed_at` set to the clock at run time."
    PRD §3.8: "Onto that snapshot the run freezes the court's live `pending_case_count`, `completions_ytd`, and `is_backlog_critical` exactly as they stand at run time, plus three derived measures."
    PRD §3.8: "`representation_rate_pct` is the share of the court's pending cases whose `representation_status` is anything other than `PRO_SE`, expressed as a percentage to 1 decimal place with round-half-up — and defined as 0.0 when the court has no pending cases at all."
    PRD §3.8: "The official pace test reads only the calendar variant: `is_on_pace` is true exactly when `pace_ratio_calendar` is at least 1.0."
    PRD §3.7: "Execution writes an immutable `CaseReassignment` record: its `from_court_id` is the source court, its `to_court_id` the selected destination, its `reason` is always `BACKLOG_REBALANCE`, and its `executed_at` is the clock."

    Design: Corner/entities/reassignment_and_docket_review_are_immutable_records
    """
    # The CaseReassignment half runs first: the reassignment selector ranks
    # every other court by load ratio with a created_at tie-break, and under
    # the frozen clock all courts share one created_at — so the destination
    # must be the ONLY eligible court in the universe for the assertion on
    # to_court_id to be uniquely determined by PRD §3.7.  Building the
    # docket-review court afterwards keeps it out of the candidate pool.
    ctx = setup_backlog_critical_source(initial_clock=False)
    record = reassign_case(ctx["case"])
    assert_case_reassignment(record)  # forbids updated_at/version outright
    assert record["from_court_id"] == ctx["source_court"]["id"]
    assert record["to_court_id"] == ctx["dest_court"]["id"]
    assert same_instant(record["executed_at"], CLOCK_DEFAULT_ISO)

    court = create_court()
    rev1 = run_docket_review(court["id"])
    rev2 = run_docket_review(court["id"])
    assert_docket_review(rev1)  # ledger shape: id + created_at, no version/updated_at
    assert_docket_review(rev2)
    assert rev1["id"] != rev2["id"], "two runs are two snapshots, not one mutated row"
    assert rev1["run_index"] == 1
    assert rev2["run_index"] == 2, "run_index is per-court monotonic"
    for rev in (rev1, rev2):
        assert same_instant(rev["computed_at"], CLOCK_DEFAULT_ISO)
        assert rev["pending_case_count"] == 0
        assert rev["completions_ytd"] == 0
        assert rev["is_backlog_critical"] is False
        assert rev["representation_rate_pct"] == 0.0
        assert rev["pace_ratio_calendar"] == 0.0
        assert rev["pace_ratio_hearing_day"] == 0.0
        assert rev["cases_finalized_by_lapse"] == 0
        assert rev["is_on_pace"] is False

    rows, _meta = validate_paginated(
        api.list_docket_reviews(
            headers=admin_headers, params={"court_id": court["id"], "limit": 100}
        )
    )
    assert len(rows) == 2, "each run appended a snapshot; none was overwritten"
