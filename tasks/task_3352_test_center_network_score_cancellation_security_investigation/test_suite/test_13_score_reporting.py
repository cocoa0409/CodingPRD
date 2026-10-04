"""Score reporting: RELEASED/HELD births, hold release, recall conservation."""
from test_helpers import (
    ADMIN_2_ID,
    ApiErrorId,
    CLEAN_SCORE_SPEC,
    EXPECTED_RESPONSE_DEADLINE_ISO,
    adjudicate_case,
    assert_iso_equal,
    create_score_report_payload,
    fresh_case_version,
    get_score_record,
    list_reports,
    notify_case,
    respond_to_case,
    send_report,
    setup_administered_session,
    setup_analyzed_session,
    setup_exposure_case,
    setup_open_gain_case,
    validate_error,
    is_iso8601_timestamp,
)


def test_released_report_count_rises_on_sends(api):
    """PRD §3.7: "For a score in `RELEASED`, the report is born `RELEASED`:
    its `released_at` is stamped with the clock, its `hold_until` stays null,
    and the record's `released_report_count` increases by 1."
    PRD §3.7: "The `released_report_count` is, at every moment, exactly the
    number of this record's reports currently in `RELEASED` status, recomputed
    on every report creation, release, and recall."

    Design: Difficulty/compensating_invariant/released_report_count_conservation_send_recall
    """
    ctx = setup_analyzed_session([dict(CLEAN_SCORE_SPEC)], name="Center RC")
    score_id = ctx["score_records"][0]["id"]
    rep1 = send_report(score_id, "MIT2026")
    rep2 = send_report(score_id, "YALE2026")
    assert rep1["status"] == "RELEASED"
    assert rep2["status"] == "RELEASED"
    assert rep1["hold_until"] is None
    assert is_iso8601_timestamp(rep1["released_at"])
    score = get_score_record(score_id)
    assert score["released_report_count"] == 2


def test_recall_returns_released_report_count_to_zero(api):
    """PRD §3.6: "First, every score report of the record in `HELD` or
    `RELEASED` status is recalled to `RECALLED` with `recalled_at` set to the
    clock. Second, the ledger resyncs: the record's `released_report_count` is
    recomputed and becomes 0."
    PRD §3.7: "The `released_report_count` is, at every moment, exactly the
    number of this record's reports currently in `RELEASED` status, recomputed
    on every report creation, release, and recall."

    Design: Difficulty/compensating_invariant/released_report_count_conservation_send_recall
    """
    ctx = setup_exposure_case(
        name="Center RC2", institution_codes=("MIT2026", "YALE2026"),
        expire_window=True,
    )
    score_id = ctx["score_record"]["id"]
    assert get_score_record(score_id)["released_report_count"] == 2
    version = fresh_case_version(ctx["registration"]["id"])
    adjudicate_case(
        ctx["case"]["id"], "CANCELLED", "Exposure proven", version,
        admin_id=ADMIN_2_ID,
    )
    score = get_score_record(score_id)
    assert score["released_report_count"] == 0, "back to the pre-send value"
    reports = list_reports(score_id)
    assert len(reports) == 2
    assert all(r["status"] == "RECALLED" for r in reports)
    assert all(r["recalled_at"] is not None for r in reports)


def test_report_held_during_investigation_released_on_uphold(api):
    """PRD §3.7: "For a score in `UNDER_REVIEW`, the report is instead born
    `HELD`, and its `hold_until` is set to the `response_deadline` of the
    review case currently open on that score's registration."
    PRD §3.6: "An `UPHELD` adjudication vindicates the score: the score record
    moves from `UNDER_REVIEW` to `VALIDATED` and then immediately on to
    `RELEASED`, and every institutional report of that record still `HELD` is
    released with it — `released_at` set to the clock, `hold_until` cleared to
    null, and the record's `released_report_count` increased by 1 for each
    such report."

    Design: Corner/state_machines/report_held_during_investigation_released_on_uphold
    """
    ctx = setup_open_gain_case(name="Center HF")
    notify_case(ctx["case"]["id"])
    score_id = ctx["score_record"]["id"]
    report = send_report(score_id, "MIT2026")
    assert report["status"] == "HELD"
    assert_iso_equal(report["hold_until"], EXPECTED_RESPONSE_DEADLINE_ISO)
    assert get_score_record(score_id)["released_report_count"] == 0, (
        "HELD reports do not count"
    )
    respond_to_case(ctx["case"]["id"], ctx["examinee"]["id"],
                    "Documented study program attached.")
    version = fresh_case_version(ctx["registration"]["id"])
    adjudicate_case(
        ctx["case"]["id"], "UPHELD", "Gain explained by documented study",
        version, admin_id=ADMIN_2_ID,
    )
    reports = list_reports(score_id)
    assert len(reports) == 1
    assert reports[0]["status"] == "RELEASED"
    assert reports[0]["hold_until"] is None
    assert reports[0]["released_at"] is not None
    score = get_score_record(score_id)
    assert score["status"] == "RELEASED"
    assert score["released_report_count"] == 1


def test_report_send_pending_analysis_rejected(api, score_analyst_headers):
    """PRD §3.7: "A score still in `PENDING_ANALYSIS` rejects the send with
    `ERR_SCORE_NOT_RELEASED`, and a `CANCELLED` score rejects it with
    `ERR_SCORE_CANCELLED`."

    Design: Corner/validations/report_send_pending_analysis_rejected
    """
    ctx = setup_administered_session(
        [dict(CLEAN_SCORE_SPEC)], name="Center RP", total_seats=5
    )
    score_id = ctx["score_records"][0]["id"]
    assert get_score_record(score_id)["status"] == "PENDING_ANALYSIS"
    resp = api.create_score_report(
        score_id, create_score_report_payload("MIT2026"), score_analyst_headers
    )
    validate_error(resp, ApiErrorId.ERR_SCORE_NOT_RELEASED)
    assert list_reports(score_id) == []
