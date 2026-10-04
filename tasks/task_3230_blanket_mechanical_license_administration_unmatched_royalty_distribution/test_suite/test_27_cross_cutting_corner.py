"""Queue B (corner) — cross-cutting: derived field reconciliation and OCC."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, create_member, create_work, create_share,
    create_active_schedule, setup_active_dsp, create_report_with_lines,
    submit_report, accept_report, pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def test_total_share_percent_tracks_share_mutations(api):
    """PRD §3.2: "On success the new share is `ACTIVE`, the work's
    `total_share_percent` is recomputed as the sum over its `ACTIVE` shares,
    the work's `version` increments by one, and a superseded share, when one
    was named, moves to `WITHDRAWN`."
    PRD §3.2: "Withdrawal moves the share to `WITHDRAWN`, recomputes the work's
    `total_share_percent`, and increments the work's `version` by one."

    Design: Corner/cross_cutting/derived_field_reconciliation_total_share_percent
    """
    set_clock("2026-09-01T00:00:00Z")
    m_a = create_member(legal_name="Alder Publishing", ipi_number="00000000101")
    m_b = create_member(legal_name="Birch Songs", ipi_number="00000000202")
    work = create_work(title="Kestrel")
    assert work["total_share_percent"] == 0
    s1 = create_share(work["id"], m_a["id"], share_percent=50)
    work_v = validate_success(api_client.get_work(work["id"], ADMIN))
    assert work_v["total_share_percent"] == 50
    create_share(work["id"], m_b["id"], share_percent=40)
    work_v = validate_success(api_client.get_work(work["id"], ADMIN))
    assert work_v["total_share_percent"] == 90
    validate_success(api_client.withdraw_share(work["id"], s1["id"], ADMIN))
    work_v = validate_success(api_client.get_work(work["id"], ADMIN))
    assert work_v["total_share_percent"] == 40, (
        f"only member B's share remains ACTIVE; got {work_v['total_share_percent']}")


def test_occ_stale_work_version_conflict(api):
    """PRD §2.8: "Registering a share requires `expected_work_version` equal to
    the work's current `version`. Every share mutation on a work — creation or
    withdrawal — increments the work's `version` by one, so a client whose
    arithmetic was computed against an older share set is detected: the create
    is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the 100-percent
    ownership invariant from a share set the client never observed."

    Design: Corner/cross_cutting/occ_stale_work_version_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    m_a = create_member(legal_name="Alder Publishing", ipi_number="00000000101")
    m_b = create_member(legal_name="Birch Songs", ipi_number="00000000202")
    work = create_work(title="Kestrel")
    stale_version = work["version"]
    create_share(work["id"], m_a["id"], share_percent=50)
    fresh_version = validate_success(api_client.get_work(work["id"], ADMIN))["version"]
    validate_error(api_client.create_share(work["id"], {
        "claimant_member_id": m_b["id"], "share_percent": 40,
        "effective_from": "2026-01-01T00:00:00Z",
        "expected_work_version": stale_version,
    }, ADMIN), ApiErrorId.ERR_STALE_VERSION)
    s2 = validate_success(api_client.create_share(work["id"], {
        "claimant_member_id": m_b["id"], "share_percent": 40,
        "effective_from": "2026-01-01T00:00:00Z",
        "expected_work_version": fresh_version,
    }, ADMIN), expected_status=201)
    assert s2["status"] == "ACTIVE"
    work_after = validate_success(api_client.get_work(work["id"], ADMIN))
    assert work_after["total_share_percent"] == 90


def test_report_version_increments_on_submit_and_accept(api):
    """PRD §3.3: "On submission the report moves to `SUBMITTED`, its
    `total_usage_cents` is recomputed as the sum of `royalties_cents` over
    *all* of its lines regardless of line status, and the provider's `version`
    increments by one."
    PRD §3.3: "A successful acceptance stamps `payment_due_at` as the 15th day
    of the month following the reporting month at 00:00:00Z (a report accepted
    after that deadline is immediately late at the next posting run), stores a
    snapshot of the provider's `accepted_rate_schedule_version` on the report
    itself, grants the provider one audit credit (`audit_credits` increases by
    one), and increments the provider's `version` by one."

    Design: Corner/cross_cutting/report_version_increments_on_submit_and_accept
    """
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    v0 = validate_success(api_client.get_service_provider(dsp["id"], ADMIN))["version"]
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-08", [
        {"track_title": "Sora", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900051"},
    ])
    # Pad with a matched line (shareless pad work) so acceptance's circuit
    # breaker passes with the unmatched Sora line (PRD §3.3).
    pad_report_for_match_floor(dsp, dsp_headers, report,
                               lines[0]["royalties_cents"])
    submit_report(dsp, dsp_headers, ack, report)
    v1 = validate_success(api_client.get_service_provider(dsp["id"], ADMIN))["version"]
    assert v1 == v0 + 1, f"submit bumps the DSP version by 1; got {v0} -> {v1}"
    accept_report(dsp, ack, report)
    v2 = validate_success(api_client.get_service_provider(dsp["id"], ADMIN))["version"]
    assert v2 == v0 + 2, f"accept bumps the DSP version by 1; got {v0} -> {v2}"
