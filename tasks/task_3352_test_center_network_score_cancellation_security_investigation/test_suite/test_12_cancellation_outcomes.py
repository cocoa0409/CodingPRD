"""CANCELLED adjudication: report recall cascade and the examinee-ban branch."""
from test_helpers import (
    ADMIN_2_ID,
    ApiErrorId,
    adjudicate_case,
    create_score_report_payload,
    fresh_case_version,
    get_examinee,
    get_only_review_case,
    get_registration,
    get_score_record,
    list_reports,
    notify_case,
    send_report,
    setup_exposure_case,
    setup_open_gain_case,
    set_clock,
    CLOCK_PAST_RESPONSE_DEADLINE,
    validate_error,
)


def _adjudicate_exposure_cancelled(name, institution_codes=("MIT2026",)):
    """Exposure case (flagged_by admin-1), examinee responded; admin-2
    adjudicates CANCELLED. Returns the context dict."""
    ctx = setup_exposure_case(
        name=name, institution_codes=institution_codes, respond=True
    )
    version = fresh_case_version(ctx["registration"]["id"])
    adjudicate_case(
        ctx["case"]["id"], "CANCELLED",
        "Exposure corroborated by device photo metadata", version,
        admin_id=ADMIN_2_ID,
    )
    return ctx


def test_cancellation_recalls_reports(api):
    """PRD §3.6: "A `CANCELLED` adjudication detonates the record. The score
    moves to `CANCELLED` — this holds whether it sat `UNDER_REVIEW` or had
    been `RELEASED` before a content-exposure case dragged it back under
    review — and a cascade runs in hops. First, every score report of the
    record in `HELD` or `RELEASED` status is recalled to `RECALLED` with
    `recalled_at` set to the clock. Second, the ledger resyncs: the record's
    `released_report_count` is recomputed and becomes 0."

    Design: Difficulty/transitive_cascade/cancellation_recalls_reports_and_bans_examinee
    """
    ctx = _adjudicate_exposure_cancelled("Center CB")
    case = get_only_review_case(ctx["registration"]["id"])
    assert case["status"] == "ADJUDICATED_CANCELLED"
    score = get_score_record(ctx["score_record"]["id"])
    assert score["status"] == "CANCELLED", "hop 1: caused by the adjudication"
    assert score["released_report_count"] == 0, "ledger resync"
    reports = list_reports(ctx["score_record"]["id"])
    assert len(reports) == 1
    assert reports[0]["status"] == "RECALLED", "hop 2: caused by the cancellation"
    assert reports[0]["recalled_at"] is not None


def test_cancellation_bans_examinee_on_content_exposure(api):
    """PRD §3.6: "Third, when the case's `trigger_reason` is
    `CONTENT_EXPOSURE`, the owning examinee transitions from `ACTIVE` to
    `BANNED`; existing registrations are left untouched as historical record,
    but every future registration attempt by that examinee is rejected with
    `ERR_EXAMINEE_BANNED`."

    Design: Difficulty/transitive_cascade/cancellation_recalls_reports_and_bans_examinee
    """
    ctx = _adjudicate_exposure_cancelled("Center CB2")
    case = get_only_review_case(ctx["registration"]["id"])
    assert case["trigger_reason"] == "CONTENT_EXPOSURE"
    examinee = get_examinee(ctx["examinee"]["id"])
    assert examinee["status"] == "BANNED", (
        "branch hop, only because trigger_reason == CONTENT_EXPOSURE"
    )
    # The historical registration is untouched.
    assert get_registration(ctx["registration"]["id"])["booking_status"] == "CONFIRMED"


def test_report_send_cancelled_score_rejected(api, score_analyst_headers):
    """PRD §3.7: "A score still in `PENDING_ANALYSIS` rejects the send with
    `ERR_SCORE_NOT_RELEASED`, and a `CANCELLED` score rejects it with
    `ERR_SCORE_CANCELLED`."
    PRD §3.6: "Third, when the case's `trigger_reason` is `CONTENT_EXPOSURE`,
    the owning examinee transitions from `ACTIVE` to `BANNED`"

    Design: Corner/validations/report_send_cancelled_score_rejected
    """
    ctx = setup_open_gain_case(name="Center CX")
    notify_id = ctx["case"]["id"]
    notify_case(notify_id)
    set_clock(CLOCK_PAST_RESPONSE_DEADLINE)
    version = fresh_case_version(ctx["registration"]["id"])
    adjudicate_case(
        notify_id, "CANCELLED", "Unexplained gain sustained", version,
        admin_id=ADMIN_2_ID,
    )
    score = get_score_record(ctx["score_record"]["id"])
    assert score["status"] == "CANCELLED"
    resp = api.create_score_report(
        score["id"], create_score_report_payload("MIT2026"), score_analyst_headers
    )
    validate_error(resp, ApiErrorId.ERR_SCORE_CANCELLED)
    # ANOMALOUS_GAIN cancellation does not ban the examinee.
    assert get_examinee(ctx["examinee"]["id"])["status"] == "ACTIVE"
