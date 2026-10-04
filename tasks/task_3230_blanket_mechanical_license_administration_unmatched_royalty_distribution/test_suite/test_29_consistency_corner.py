"""Queue B (corner) — immediate consistency of acceptance effects."""
from test_helpers import (
    TEST_USERS, validate_success,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    setup_work_with_share, create_report_with_lines, submit_report,
    get_line_accrual,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def test_acceptance_effects_visible_immediately(api):
    """PRD §3.4: "The acceptance then freezes `matched_usage_cents` as the sum
    of `royalties_cents` over the lines the sweep moved to `MATCHED` and
    `unmatched_usage_cents` as the sum over those moved to `UNMATCHED`, and the
    invariant that their sum equals `total_usage_cents` must hold."
    PRD §3.4: "At report acceptance, every `PENDING_MATCH` line of the report
    is evaluated: a line that matches moves to `MATCHED`, its
    `matched_work_id` is set, and matched-earnings postings are queued per
    §3.7; a line that does not match moves to `UNMATCHED` and spawns a held
    accrual per §3.5."

    Design: Corner/consistency/acceptance_effects_visible_immediately
    """
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member()
    work, _ = setup_work_with_share("Kestrel", m_a)
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Kestrel", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900001"},
        {"track_title": "Petrel", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900003"},
    ])
    submit_report(dsp, dsp_headers, ack, report)
    accepted = validate_success(
        api_client.accept_usage_report(dsp["id"], report["id"], ack, ADMIN))
    reread = validate_success(
        api_client.get_usage_report(dsp["id"], report["id"], ADMIN))
    assert accepted["status"] == "ACCEPTED" == reread["status"]
    assert accepted["matched_usage_cents"] == 1310 == reread["matched_usage_cents"]
    assert accepted["unmatched_usage_cents"] == 1310 == reread["unmatched_usage_cents"]
    accrual = get_line_accrual(lines[1]["id"])
    assert accrual["status"] == "HELD", (
        f"the spawned accrual is queryable in the same instant; got {accrual['status']}")
    line_k = validate_success(api_client.get_usage_line(lines[0]["id"], ADMIN))
    assert line_k["status"] == "MATCHED"
    assert line_k["matched_work_id"] == work["id"]
