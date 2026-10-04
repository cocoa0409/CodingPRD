"""Queue B (corner) — endpoints: statement computed read, clock endpoint."""
from test_helpers import (
    TEST_USERS, validate_success, validate_paginated, get_success_data,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    create_payee, setup_work_with_share, create_report_with_lines,
    submit_report, accept_report,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def test_statement_finalize_computed_read(api):
    """PRD §3.7: "A statement's `gross_cents` is the sum of `allocated_cents`
    over its lines, its `adjustments_cents` is the signed sum over adjustment
    lines, and its `net_cents` is `gross_cents` plus `adjustments_cents` — all
    recomputed by the server at finalization from the current lines."

    Design: Corner/endpoints/statement_finalize_computed_read
    """
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member()
    setup_work_with_share("Sora", m_a)
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Sora", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900051"},
    ])
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    create_payee(m_a["id"])
    st = validate_success(api_client.create_statement(m_a["id"], "2026-06", ADMIN),
                          expected_status=201)
    finalized = validate_success(
        api_client.finalize_statement(m_a["id"], st["id"], ADMIN))
    assert finalized["status"] == "FINALIZED"
    assert finalized["gross_cents"] == 1310, (
        f"matched earnings of 10 * 131 flow into gross; got {finalized['gross_cents']}")
    assert finalized["net_cents"] == 1310, (
        f"no adjustments: net == gross; got {finalized['net_cents']}")


def test_clock_set_echoes_new_time(api):
    """PRD §2.5: "At startup the logical clock reads exactly
    `2026-09-01T00:00:00Z`, and it holds that value until an `MLCAdministrator`
    advances it through the clock-setting capability, which accepts a
    `to_iso8601` instant and returns the new `current_utc`."

    Design: Corner/endpoints/clock_default_and_set_action_endpoint
    """
    data = validate_success(api_client.set_clock("2026-10-01T00:00:00Z", ADMIN))
    assert data["current_utc"] == "2026-10-01T00:00:00Z"
