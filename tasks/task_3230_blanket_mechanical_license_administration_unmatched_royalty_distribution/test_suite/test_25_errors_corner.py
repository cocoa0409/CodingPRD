"""Queue B (corner) — error catalogue behaviors."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    make_member_headers, make_dsp_headers,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    create_work, create_share, setup_work_with_share,
    create_report_with_lines, submit_report, accept_report, get_line_accrual,
    create_schedule_pending, create_dsp, activate_dsp,
    pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def test_missing_auth_header(api):
    """PRD §2.1: "A request missing either header, or presenting a malformed
    header, is rejected with `ERR_MISSING_AUTH` (HTTP 401)."

    Design: Corner/errors/error_missing_auth_header
    """
    resp = api_client._request("GET", "/mlc/members", headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH, expected_status=401)


def test_stale_rate_schedule_on_submit(api):
    """PRD §2.8: "The submission payload must carry
    `accepted_rate_schedule_version` equal to the DSP's current
    `accepted_rate_schedule_version`. The DSP's value advances whenever a new
    rate schedule activates, so a client that priced its lines against an
    earlier schedule holds a stale acknowledgement. If the payload value does
    not match the DSP's current value, the submission is rejected with
    `ERR_STALE_RATE_SCHEDULE` (HTTP 412); the client must re-read the DSP and
    re-acknowledge before resubmitting."

    Design: Corner/errors/error_stale_rate_schedule_on_submit
    """
    set_clock("2026-09-10T00:00:00Z")
    rs1 = create_schedule_pending(
        under=120, over=240,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z")
    rs2 = create_schedule_pending(effective_from="2026-06-01T00:00:00Z")
    validate_success(api_client.activate_rate_schedule(rs1["id"], ADMIN))
    dsp, dsp_headers, ack_v1 = activate_dsp(create_dsp())
    validate_success(api_client.activate_rate_schedule(rs2["id"], ADMIN))
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-08", [
        {"track_title": "Sora", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900051"},
    ])
    validate_error(
        api_client.submit_usage_report(dsp["id"], report["id"], ack_v1, dsp_headers),
        ApiErrorId.ERR_STALE_RATE_SCHEDULE)


def test_accrual_not_held_on_double_claim_validation(api):
    """PRD §3.6: "The target accrual must be `HELD` (`ERR_ACCRUAL_NOT_HELD`,
    HTTP 409)."

    Design: Corner/errors/error_accrual_not_held_on_double_claim_validation
    """
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member(legal_name="Alder Publishing", ipi_number="00000000101")
    m_b = create_member(legal_name="Birch Songs", ipi_number="00000000202")
    work = create_work(title="Gale (claimed)")
    create_share(work["id"], m_a["id"], share_percent=50)
    create_share(work["id"], m_b["id"], share_percent=50)
    # The line's track_title differs from the work's title so the line goes
    # UNMATCHED at acceptance and spawns the HELD accrual under test; the pad
    # line (shareless work) keeps unmatched at or under 60% of the total.
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Gale", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900032"},
    ])
    pad_report_for_match_floor(dsp, dsp_headers, report,
                               lines[0]["royalties_cents"])
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    accrual = get_line_accrual(lines[0]["id"])
    cl1 = validate_success(api_client.create_claim({
        "accrual_id": accrual["id"], "claimant_member_id": m_a["id"],
        "claimed_work_id": work["id"], "share_percent_claimed": 50,
    }, make_member_headers(m_a["id"])), expected_status=201)
    validate_success(api_client.validate_claim(cl1["id"], ADMIN))
    cl2 = validate_success(api_client.create_claim({
        "accrual_id": accrual["id"], "claimant_member_id": m_b["id"],
        "claimed_work_id": work["id"], "share_percent_claimed": 50,
    }, make_member_headers(m_b["id"])), expected_status=201)
    validate_error(api_client.validate_claim(cl2["id"], ADMIN),
                   ApiErrorId.ERR_ACCRUAL_NOT_HELD)
    cl2_after = validate_success(api_client.get_claim(cl2["id"], ADMIN))
    assert cl2_after["status"] == "PENDING"


def test_audit_credits_exhausted(api):
    """PRD §3.8: "Opening consumes one of the provider's `audit_credits` — a
    provider with zero credits cannot be audited, and the attempt is rejected
    with `ERR_AUDIT_CREDITS_EXHAUSTED` (HTTP 422) — and every scoped report in
    `ACCEPTED` moves to `UNDER_AUDIT`."

    Design: Corner/errors/error_audit_credits_exhausted

    A provider with zero credits has never had a report accepted, so the scope
    can never name a covered month: PRD names no ordering between the
    scope-coverage rule (no error id named in PRD; ERR_INVALID_REQUEST is the
    generic malformed-request id) and the zero-credit rule, so either error is
    a PRD-faithful observation of this doubly-invalid request.
    """
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, _dsp_headers, _ack = setup_active_dsp()
    m_a = create_member()
    validate_error_is_one_of(
        api_client.create_audit(dsp["id"], m_a["id"], ["2026-06"],
                                make_member_headers(m_a["id"])),
        [ApiErrorId.ERR_AUDIT_CREDITS_EXHAUSTED, ApiErrorId.ERR_INVALID_REQUEST])


def test_cycle_out_of_order(api):
    """PRD §3.8: "Closing requires that no run with an earlier `cycle_month` is
    still `OPEN` (`ERR_CYCLE_OUT_OF_ORDER`, HTTP 409), and then performs the
    sweep, the waterfall, and the epoch snapshot in one motion."

    Design: Corner/errors/error_cycle_out_of_order
    """
    c_sep = validate_success(api_client.create_cycle_run({
        "cycle_month": "2026-09", "pool_from_month": "2026-01",
        "pool_to_month": "2026-06", "methodology": "MARKET_SHARE_USAGE"}, ADMIN),
        expected_status=201)
    c_oct = validate_success(api_client.create_cycle_run({
        "cycle_month": "2026-10", "pool_from_month": "2026-01",
        "pool_to_month": "2026-06", "methodology": "MARKET_SHARE_USAGE"}, ADMIN),
        expected_status=201)
    validate_error(api_client.close_cycle_run(c_oct["id"], ADMIN),
                   ApiErrorId.ERR_CYCLE_OUT_OF_ORDER)
    after = validate_success(api_client.get_cycle_run(c_oct["id"], ADMIN))
    assert after["status"] == "OPEN"


def test_last_payee_termination(api):
    """PRD §3.7: "Payees are born `ACTIVE` and may be suspended and reinstated
    freely, but termination is guarded: the member must retain at least one
    other payee in `ACTIVE` or `SUSPENDED` status, so terminating the member's
    last remaining payee is rejected with `ERR_LAST_PAYEE_TERMINATION`
    (HTTP 409)."

    Design: Corner/errors/error_last_payee_termination
    """
    from test_helpers import setup_member_with_payee
    member, payee = setup_member_with_payee()
    validate_error(
        api_client.terminate_payee(member["id"], payee["id"], ADMIN),
        ApiErrorId.ERR_LAST_PAYEE_TERMINATION)
    after = validate_success(api_client.get_payee(member["id"], payee["id"], ADMIN))
    assert after["status"] == "ACTIVE"
