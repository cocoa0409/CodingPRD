"""Queue B (corner) — RBAC denials and public read-only scope."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    make_member_headers, make_dsp_headers, make_public_headers,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    create_work, create_report_with_lines, submit_report,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def test_service_provider_user_cannot_accept_reports(api):
    """PRD §3.3: "Acceptance is the administrative gate, and its checks run in a
    fixed order."
    PRD §2.1: "When a request's role is not permitted for the endpoint it
    targets, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /mlc/service-providers/{id}/usage-reports/{reportId}/accept is
    authorized for MLCAdministrator only.

    Design: Corner/rbac/service_provider_user_cannot_accept_reports
    """
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    report, _ = create_report_with_lines(dsp, dsp_headers, "2026-08", [
        {"track_title": "Sora", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900051"},
    ])
    submit_report(dsp, dsp_headers, ack, report)
    validate_error(
        api_client.accept_usage_report(dsp["id"], report["id"], ack, dsp_headers),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = validate_success(api_client.get_usage_report(dsp["id"], report["id"], ADMIN))
    assert after["status"] == "SUBMITTED"


def test_member_user_cannot_open_match_runs(api):
    """PRD §3.4: "an administrator may launch a matching pass that re-evaluates
    every line in `PENDING_MATCH` or `UNMATCHED` across the system"
    PRD §2.1: "When a request's role is not permitted for the endpoint it
    targets, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /mlc/match-runs is authorized for MLCAdministrator only.

    Design: Corner/rbac/member_user_cannot_open_match_runs
    """
    m_a = create_member()
    validate_error(api_client.create_match_run(make_member_headers(m_a["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_public_searcher_read_only_scope(api):
    """PRD §2.1: "When `X-User-Role` is `PublicSearcher`, `X-User-ID` is
    likewise an opaque identifier not tied to any persisted entity; it grants
    read-only access to the public search surface and nothing else."
    PRD §3.5: "The `PublicSearcher` role exists precisely so that rights
    holders who are not yet members — or anyone performing diligence — can
    list and inspect held funds through the unmatched-royalty search surface"

    Design: Corner/rbac/public_searcher_read_only_scope
    """
    work = create_work(title="Kestrel")
    read = validate_success(api_client.get_work(work["id"], make_public_headers()))
    assert read["title"] == "Kestrel"
    validate_error(
        api_client.create_work({"title": "Intruder"}, make_public_headers()),
        ApiErrorId.ERR_UNAUTHORIZED_ROLE)
