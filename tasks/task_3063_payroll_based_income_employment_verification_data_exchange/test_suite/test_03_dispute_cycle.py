"""The RecordDispute cycle: reopen, closure, terminality and OCC on filing."""
from test_helpers import (
    setup_dispute_in_notice_sent,
    setup_dispute_acknowledged,
    setup_employer_worker_record,
    file_dispute,
    notice_dispute,
    respond_dispute,
    reopen_dispute,
    get_dispute,
    list_disputes,
    get_worker,
    get_employer,
    get_record,
    record_version_of,
    set_clock,
    make_employer_headers,
    make_worker_headers,
    api,
    validate_error,
    ApiErrorId,
)


def test_upheld_dispute_can_be_reopened_and_re_resolved(api):
    """PRD §3.6: "An upheld dispute is likewise not final: within 14 days of
    `resolved_at` the worker may reopen it, which returns the dispute to `NOTICE_SENT`
    and increments both open-dispute counters again."

    Design: Difficulty/non_linear_state_machine/record_dispute_round_trip_reopen_and_re_resolve
    """
    ctx = setup_dispute_in_notice_sent()
    employer_id = ctx["employer"]["id"]
    worker_id = ctx["worker"]["id"]
    dispute_id = ctx["dispute"]["id"]

    respond_dispute(employer_id, dispute_id, "UPHELD")
    reopen_dispute(worker_id, dispute_id, "REOPEN")
    final = respond_dispute(employer_id, dispute_id, "UPHELD")

    assert final["dispute_state"] == "RESOLVED_UPHELD", (
        f"the second traversal of the respond edge must land on RESOLVED_UPHELD, got {final['dispute_state']}"
    )


def test_reopened_dispute_counters_return_to_zero_after_the_second_resolution(api):
    """PRD §3.6: "both resolution forms decrement the worker's `open_dispute_count`
    and the employer's `dispute_open_count`."
    PRD §3.6: "within 14 days of `resolved_at` the worker may reopen it, which returns
    the dispute to `NOTICE_SENT` and increments both open-dispute counters again."

    Design: Difficulty/non_linear_state_machine/record_dispute_round_trip_reopen_and_re_resolve
    """
    ctx = setup_dispute_in_notice_sent()
    employer_id = ctx["employer"]["id"]
    worker_id = ctx["worker"]["id"]
    dispute_id = ctx["dispute"]["id"]

    respond_dispute(employer_id, dispute_id, "UPHELD")
    reopened = reopen_dispute(worker_id, dispute_id, "REOPEN")
    assert reopened["dispute_state"] == "NOTICE_SENT"
    assert get_worker(worker_id)["open_dispute_count"] == 1
    assert get_employer(employer_id)["dispute_open_count"] == 1

    respond_dispute(employer_id, dispute_id, "UPHELD")
    assert get_worker(worker_id)["open_dispute_count"] == 0
    assert get_employer(employer_id)["dispute_open_count"] == 0


def test_closed_dispute_rejects_a_further_response(api):
    """PRD §3.6: "After those 14 days elapse, a resolved dispute — corrected or upheld
    — is swept to `CLOSED`, which is terminal; reopening or responding to a closed
    dispute is refused with `ERR_DISPUTE_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/record_dispute_closed_is_terminal_for_respond
    """
    ctx = setup_dispute_in_notice_sent(
        clock="2026-06-01T00:00:00Z", pay_period_end_date="2026-05-31T00:00:00Z"
    )
    employer_id = ctx["employer"]["id"]
    dispute_id = ctx["dispute"]["id"]
    headers = make_employer_headers(employer_id)

    respond_dispute(employer_id, dispute_id, "UPHELD")
    set_clock("2026-07-20T00:00:00Z")
    closed = get_dispute(dispute_id, headers)
    assert closed["dispute_state"] == "CLOSED"

    response = api.respond_dispute(dispute_id, "UPHELD", headers)
    validate_error(response, ApiErrorId.ERR_DISPUTE_TERMINAL)


def test_closed_dispute_state_is_unchanged_by_the_rejected_response(api):
    """PRD §5: "`ERR_DISPUTE_TERMINAL` | 409".
    PRD §3.6: "reopening or responding to a closed dispute is refused".

    Design: Corner/state_machines/record_dispute_closed_is_terminal_for_respond
    """
    ctx = setup_dispute_in_notice_sent(
        clock="2026-06-01T00:00:00Z", pay_period_end_date="2026-05-31T00:00:00Z"
    )
    employer_id = ctx["employer"]["id"]
    dispute_id = ctx["dispute"]["id"]

    respond_dispute(employer_id, dispute_id, "UPHELD")
    set_clock("2026-07-20T00:00:00Z")
    after = get_dispute(dispute_id, make_employer_headers(employer_id))
    assert after["dispute_state"] == "CLOSED"


def test_stale_record_version_rejects_a_second_dispute_filing(api):
    """PRD §2.9: "filing a `RecordDispute` requires `expected_employment_record_version`
    matching the disputed `EmploymentRecord`'s current `version`."
    PRD §2.9: "a worker may legitimately file a fresh dispute over a span that was
    disputed and corrected before, and the only defect rejected is that the
    `claimed_field` values and the span's `currency_state` were read from a superseded
    view of the row."

    Design: Corner/cross_cutting_layers/occ_stale_employment_record_version_rejects_second_dispute
    """
    ctx = setup_employer_worker_record(pay_period_end_date="2026-08-31T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    worker_id = ctx["worker"]["id"]
    record_id = ctx["record"]["id"]

    stale_version = record_version_of(record_id)
    dispute = file_dispute(worker_id, record_id, claimed_field="PAY_RATE",
                           claimed_correct_value="480000", record_version=stale_version)
    notice_dispute(employer_id, dispute["id"])
    respond_dispute(employer_id, dispute["id"], "UPHELD")

    response = api.create_dispute(
        {
            "employment_record_id": record_id,
            "covered_worker_id": worker_id,
            "claimed_field": "EMPLOYMENT_STATUS",
            "claimed_correct_value": "TERMINATED",
            "expected_employment_record_version": stale_version,
        },
        make_worker_headers(worker_id),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert record_version_of(record_id) > stale_version


def test_fresh_version_after_the_first_round_permits_a_new_filing(api):
    """PRD §2.9: "The filing check is not a duplicate-dispute check: a worker may
    legitimately file a fresh dispute over a span that was disputed and corrected
    before".

    Design: Corner/cross_cutting_layers/occ_stale_employment_record_version_rejects_second_dispute
    """
    ctx = setup_employer_worker_record(pay_period_end_date="2026-08-31T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    worker_id = ctx["worker"]["id"]
    record_id = ctx["record"]["id"]

    dispute = file_dispute(worker_id, record_id, claimed_field="PAY_RATE",
                           claimed_correct_value="480000")
    notice_dispute(employer_id, dispute["id"])
    respond_dispute(employer_id, dispute["id"], "UPHELD")

    fresh = record_version_of(record_id)
    second = file_dispute(worker_id, record_id, claimed_field="EMPLOYMENT_STATUS",
                          claimed_correct_value="TERMINATED", record_version=fresh)
    assert second["dispute_state"] == "AWAITING_EMPLOYER"
    assert get_dispute(dispute["id"], make_employer_headers(employer_id))["dispute_state"] == "RESOLVED_UPHELD"


def test_escalation_stales_records_and_delays_the_employer_feed(api):
    """PRD §3.6: "Escalating a dispute drives the employer's `feed_status` to
    `DELAYED`, stales every one of the employer's records that was `CURRENT`".
    PRD §3.6: "an acknowledged dispute whose `response_due_date` passes without
    resolution is swept into `ESCALATED`".

    Design: Difficulty/transitive_cascade/dispute_escalation_cascade_delays_feed_stales_records
    """
    ctx = setup_dispute_acknowledged(
        clock="2026-06-01T00:00:00Z", pay_period_end_date="2026-05-31T00:00:00Z"
    )
    employer_id = ctx["employer"]["id"]
    worker_id = ctx["worker"]["id"]
    record_id = ctx["record"]["id"]
    dispute_id = ctx["dispute"]["id"]

    assert get_employer(employer_id)["feed_status"] == "CURRENT"
    # filed_at was 2026-06-01, so response_due_date is 45 days later; step past it.
    set_clock("2026-08-01T00:00:00Z")
    list_disputes(worker_id=worker_id)

    assert get_dispute(dispute_id, make_employer_headers(employer_id))["dispute_state"] == "ESCALATED"
    assert get_employer(employer_id)["feed_status"] == "DELAYED"
    assert get_record(record_id)["currency_state"] == "STALE"


def test_escalated_dispute_remains_open(api):
    """PRD §3.6: "that escalation is not a private matter between the employer and one
    worker."
    PRD §3.6: "a resolved dispute — corrected or upheld — is swept to `CLOSED`".

    Design: Difficulty/transitive_cascade/dispute_escalation_cascade_delays_feed_stales_records
    """
    ctx = setup_dispute_acknowledged(
        clock="2026-06-01T00:00:00Z", pay_period_end_date="2026-05-31T00:00:00Z"
    )
    employer_id = ctx["employer"]["id"]
    dispute_id = ctx["dispute"]["id"]

    set_clock("2026-08-01T00:00:00Z")
    assert get_dispute(dispute_id, make_employer_headers(employer_id))["dispute_state"] == "ESCALATED"
    assert get_employer(employer_id)["dispute_open_count"] == 1