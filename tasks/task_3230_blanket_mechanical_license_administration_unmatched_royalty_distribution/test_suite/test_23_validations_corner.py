"""Queue B (corner) — validations: match-rate floor, in-order acceptance,
supersede integrity, ABA checksum, dispute aging."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    ApiErrorId, make_member_headers,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    create_payee, create_work, create_share, setup_work_with_share,
    create_report_with_lines, submit_report, accept_report,
    get_line_accrual, setup_validated_claim, setup_pending_claim,
)
from test_helpers.api_client import api_client
from test_helpers.constants import ROUTING_VALID, ROUTING_INVALID

ADMIN = TEST_USERS["admin_headers"]


def test_acceptance_match_rate_floor_breach(api):
    """PRD §3.3: "if the resulting `unmatched_usage_cents` strictly exceeds 60
    percent of `total_usage_cents` — compared as `unmatched_usage_cents`
    multiplied by 100 being greater than 60 times `total_usage_cents`, so that
    exactly 60 percent passes — the acceptance is rejected with
    `ERR_MATCH_RATE_FLOOR_BREACH` (HTTP 422)."

    Design: Corner/validations/acceptance_match_rate_floor_breach
    """
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member()
    setup_work_with_share("Kestrel", m_a)
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Kestrel", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900001"},
        {"track_title": "Petrel", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900003"},
        {"track_title": "Gale", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900032"},
    ])
    submit_report(dsp, dsp_headers, ack, report)
    validate_error(
        api_client.accept_usage_report(dsp["id"], report["id"], ack, ADMIN),
        ApiErrorId.ERR_MATCH_RATE_FLOOR_BREACH)
    after = validate_success(api_client.get_usage_report(dsp["id"], report["id"], ADMIN))
    assert after["status"] == "SUBMITTED", (
        f"accept failed; no sweep side effects; got {after['status']}")


def test_out_of_order_acceptance_rejected(api):
    """PRD §3.3: "and no other report of the same provider with an earlier
    `reporting_month` may still be `SUBMITTED` — acceptance is strictly in
    chronological order, and an out-of-order attempt is rejected with
    `ERR_OUT_OF_ORDER_ACCEPTANCE` (HTTP 409)."

    Design: Corner/validations/out_of_order_acceptance_rejected
    """
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member()
    setup_work_with_share("Sora", m_a)
    setup_work_with_share("Ruff", m_a)
    r_jun, _ = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Sora", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900051"},
    ])
    submit_report(dsp, dsp_headers, ack, r_jun)
    r_jul, _ = create_report_with_lines(dsp, dsp_headers, "2026-07", [
        {"track_title": "Ruff", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900052"},
    ])
    submit_report(dsp, dsp_headers, ack, r_jul)
    validate_error(
        api_client.accept_usage_report(dsp["id"], r_jul["id"], ack, ADMIN),
        ApiErrorId.ERR_OUT_OF_ORDER_ACCEPTANCE)
    after = validate_success(api_client.get_usage_report(dsp["id"], r_jul["id"], ADMIN))
    assert after["status"] == "SUBMITTED"


def test_superseding_share_withdraws_prior(api):
    """PRD §3.2: "Fourth, supersede integrity: a `supersedes_share_id`, when
    present, must name an `ACTIVE` or `WITHDRAWN` share of the same work, else
    `ERR_SUPERSEDES_NOT_FOUND` (HTTP 422). On success the new share is
    `ACTIVE`, the work's `total_share_percent` is recomputed as the sum over
    its `ACTIVE` shares, the work's `version` increments by one, and a
    superseded share, when one was named, moves to `WITHDRAWN`."

    Design: Corner/validations/superseding_share_withdraws_prior
    """
    set_clock("2026-09-01T00:00:00Z")
    m_a = create_member()
    work = create_work(title="Kestrel")
    s1 = create_share(work["id"], m_a["id"], share_percent=50)
    work_now = validate_success(api_client.get_work(work["id"], ADMIN))
    # The ceiling check (PRD §3.2, second check) sums ACTIVE shares plus the
    # new share, so the superseding share must fit under 100 alongside the
    # still-ACTIVE prior share: 50 + 50 <= 100.
    s2 = validate_success(api_client.create_share(work["id"], {
        "claimant_member_id": m_a["id"], "share_percent": 50,
        "effective_from": "2026-06-01T00:00:00Z",
        "supersedes_share_id": s1["id"],
        "expected_work_version": work_now["version"],
    }, ADMIN), expected_status=201)
    assert s2["status"] == "ACTIVE"
    s1_after = validate_success(api_client.get_share(work["id"], s1["id"], ADMIN))
    assert s1_after["status"] == "WITHDRAWN"
    work_after = validate_success(api_client.get_work(work["id"], ADMIN))
    assert work_after["total_share_percent"] == 50


def test_payee_aba_checksum_enforced(api):
    """PRD §3.7: "A `routing_number`, when present, must be exactly nine digits
    and satisfy the ABA checksum: three times the sum of the first, fourth, and
    seventh digits, plus seven times the sum of the second, fifth, and eighth
    digits, plus the sum of the third, sixth, and ninth digits, must be
    divisible by ten. A violation — a failed checksum, a routing number present
    on a `CHECK` payee, or one absent on an `ACH` or `WIRE` payee — is rejected
    with `ERR_PAYEE_ROUTING_INVALID` (HTTP 422)."

    Design: Corner/validations/payee_aba_checksum_enforced
    """
    m_a = create_member()
    validate_error(api_client.create_payee(m_a["id"], {
        "payee_legal_name": "Alder Publishing LLC", "payment_method": "ACH",
        "routing_number": ROUTING_INVALID, "account_number": "123456789",
        "tax_id": "123456789",
    }, ADMIN), ApiErrorId.ERR_PAYEE_ROUTING_INVALID)
    ok = validate_success(api_client.create_payee(m_a["id"], {
        "payee_legal_name": "Alder Publishing LLC", "payment_method": "ACH",
        "routing_number": ROUTING_VALID, "account_number": "123456789",
        "tax_id": "123456789",
    }, ADMIN), expected_status=201)
    assert ok["status"] == "ACTIVE"


def test_dispute_escalation_90_day_boundary(api):
    """PRD §2.5: "A dispute becomes eligible for escalation only after it has
    been `OPEN` for at least 90 logical days; exactly 90 days passes, fewer is
    rejected with `ERR_DISPUTE_TOO_FRESH` (HTTP 422)."
    PRD §3.6: "Escalation is the alternative exit for stalemate: a dispute that
    has been `OPEN` for at least 90 logical days may be escalated (fewer than
    90 days draws `ERR_DISPUTE_TOO_FRESH`), moving it to `ESCALATED` while
    every folded claim remains `DISPUTED` and the accrual stays in its current
    hold posture — no funds move on escalation."

    Design: Corner/validations/dispute_escalation_90_day_boundary
    """
    dsp, report, line, accrual, member, work, claim = setup_pending_claim(
        title="Gale", clock="2026-09-01T00:00:00Z")
    dispute = validate_success(api_client.create_dispute({
        "work_id": work["id"], "share_context": "Alder Publishing 100%",
        "initiating_claim_id": claim["id"],
    }, ADMIN), expected_status=201)
    set_clock("2026-11-29T00:00:00Z")  # 89 days after 2026-09-01
    validate_error(api_client.escalate_dispute(dispute["id"], ADMIN),
                   ApiErrorId.ERR_DISPUTE_TOO_FRESH)
    set_clock("2026-11-30T00:00:00Z")  # exactly 90 days
    escalated = validate_success(api_client.escalate_dispute(dispute["id"], ADMIN))
    assert escalated["status"] == "ESCALATED"
