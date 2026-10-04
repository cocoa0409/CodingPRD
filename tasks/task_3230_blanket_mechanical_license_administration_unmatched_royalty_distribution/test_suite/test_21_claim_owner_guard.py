"""Queue B (corner) — claim owner guard."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    make_member_headers, set_clock, create_active_schedule,
    setup_active_dsp, create_member, setup_work_with_share,
    create_report_with_lines, submit_report, accept_report, get_line_accrual,
    pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_pending_claim():
    """HELD accrual from an accepted 2026-06 report (unmatched 'Gale' line)
    and a PENDING claim by member A. The claimed work's title differs from the
    line's track_title so the line goes UNMATCHED at acceptance (PRD §3.6
    requires no title equality between line and claimed work); the report is
    padded with a matched line so the acceptance circuit breaker passes."""
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member(legal_name="Alder Publishing", ipi_number="00000000101")
    m_b = create_member(legal_name="Birch Songs", ipi_number="00000000202")
    work, _ = setup_work_with_share("Gale (claimed)", m_a)
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Gale", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900032"},
    ])
    pad_report_for_match_floor(dsp, dsp_headers, report,
                               lines[0]["royalties_cents"])
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    accrual = get_line_accrual(lines[0]["id"])
    claim = validate_success(api_client.create_claim({
        "accrual_id": accrual["id"], "claimant_member_id": m_a["id"],
        "claimed_work_id": work["id"], "share_percent_claimed": 100,
    }, make_member_headers(m_a["id"])), expected_status=201)
    return m_a, m_b, claim


def test_claim_withdraw_by_non_owner_rejected(api):
    """PRD §3.6: "A `PENDING` claim may also be rejected outright by an
    administrator, moving it to `REJECTED`; or withdrawn by its own claimant —
    the acting member must be the claim's `claimant_member_id`, else
    `ERR_NOT_CLAIM_OWNER` (HTTP 403) — moving it to `WITHDRAWN`."

    Design: Corner/state_machines/claim_withdraw_only_by_owner
    """
    _m_a, m_b, claim = _setup_pending_claim()
    validate_error(
        api_client.withdraw_claim(claim["id"], make_member_headers(m_b["id"])),
        ApiErrorId.ERR_NOT_CLAIM_OWNER)
    after = validate_success(api_client.get_claim(claim["id"], ADMIN))
    assert after["status"] == "PENDING"


def test_claim_withdraw_by_owner_succeeds(api):
    """PRD §3.6: "A `PENDING` claim may also be rejected outright by an
    administrator, moving it to `REJECTED`; or withdrawn by its own claimant —
    the acting member must be the claim's `claimant_member_id`, else
    `ERR_NOT_CLAIM_OWNER` (HTTP 403) — moving it to `WITHDRAWN`."

    Design: Corner/state_machines/claim_withdraw_only_by_owner
    """
    m_a, _m_b, claim = _setup_pending_claim()
    withdrawn = validate_success(
        api_client.withdraw_claim(claim["id"], make_member_headers(m_a["id"])))
    assert withdrawn["status"] == "WITHDRAWN"
