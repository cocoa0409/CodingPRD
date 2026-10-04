"""Corner tests (endpoints): disclosure publish gating — negotiation cap, timing,
and blackout window."""
from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    make_researcher_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    create_validated_report,
    register_researcher,
    resolve_report,
    set_clock,
    setup_active_program,
)


def _setup_agreed_disclosure_with_blackout():
    """Report RESOLVED at 2026-09-01 (disclosure window 30d -> earliest
    2026-10-01); blackout [2026-11-01, 2026-11-05]; disclosure request AGREED at
    2026-10-01 after 3 COUNTER rounds."""
    set_clock("2026-09-01T00:00:00Z")
    program, asset = setup_active_program(disclosure_window_days=30)
    patched = get_success_data(api_patch_program_with_blackout(program))
    researcher = register_researcher()
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    resolve_report(report["id"])
    dr = get_success_data(api_client.create_disclosure_request(
        {"report_id": report["id"], "proposed_publish_at": "2026-10-01T00:00:00Z"},
        make_researcher_headers(researcher["id"])))
    researcher_headers = make_researcher_headers(researcher["id"])
    get_success_data(api_client.respond_disclosure_request(
        dr["id"], {"decision": "COUNTER", "note": "need more time"}, PROGRAM_ADMIN))
    get_success_data(api_client.respond_disclosure_request(
        dr["id"], {"decision": "COUNTER", "note": "round 2"}, researcher_headers))
    get_success_data(api_client.respond_disclosure_request(
        dr["id"], {"decision": "COUNTER", "note": "round 3"}, PROGRAM_ADMIN))
    return program, researcher, report, dr


def api_patch_program_with_blackout(program):
    return api_client.patch_program(program["id"], {
        "expected_program_version": program["version"],
        "blackout_windows": [
            {"starts_at": "2026-11-01T00:00:00Z", "ends_at": "2026-11-05T00:00:00Z"},
        ],
    }, PROGRAM_ADMIN)


def test_disclosure_negotiation_rounds_cap_at_three(api):
    """PRD §3.10: "Either the owning researcher or a `ProgramAdmin` may counter,
    moving a `REQUESTED` or `UNDER_NEGOTIATION` request to `UNDER_NEGOTIATION`
    and incrementing `negotiation_round` by one; countering is refused once the
    round has reached 3, surfacing `ERR_NEGOTIATION_EXHAUSTED`."

    Design: Corner/endpoints/disclosure_publish_gating_window_blackout_and_negotiation
    """
    program, researcher, report, dr = _setup_agreed_disclosure_with_blackout()
    fourth = api.respond_disclosure_request(
        dr["id"], {"decision": "COUNTER", "note": "round 4"}, PROGRAM_ADMIN)
    validate_error(fourth, ApiErrorId.ERR_NEGOTIATION_EXHAUSTED)


def test_disclosure_publish_timing_then_blackout_then_success(api):
    """PRD §3.10: "Publication is a `ProgramAdmin` decision on an `AGREED`
    request, and it is gated three ways, evaluated in order. The report must be
    `RESOLVED`, else `ERR_REPORT_NOT_RESOLVED`. The logical now must be at or
    after `agreed_publish_at` and at or after `resolved_at` plus the program's
    `disclosure_window_days`; publishing earlier is rejected with
    `ERR_DISCLOSURE_TOO_EARLY`, and this timing check is evaluated before the
    blackout check so an early publication surfaces the timing error even when a
    blackout is also active. Finally, no blackout window on the program may
    contain the current instant — blackout intervals are closed, so a now exactly
    equal to a window's `starts_at` or `ends_at` falls inside it — else
    `ERR_BLACKOUT_ACTIVE`."

    Design: Corner/endpoints/disclosure_publish_gating_window_blackout_and_negotiation
    """
    program, researcher, report, dr = _setup_agreed_disclosure_with_blackout()
    # 4th COUNTER refused
    validate_error(
        api.respond_disclosure_request(
            dr["id"], {"decision": "COUNTER", "note": "round 4"}, PROGRAM_ADMIN),
        ApiErrorId.ERR_NEGOTIATION_EXHAUSTED)
    agreed = get_success_data(api.respond_disclosure_request(
        dr["id"], {"decision": "AGREE", "agreed_publish_at": "2026-10-01T00:00:00Z"},
        make_researcher_headers(researcher["id"])))
    assert agreed["status"] == "AGREED"
    assert agreed["agreed_publish_at"] == "2026-10-01T00:00:00Z"
    # Clock still at 2026-09-01: timing gate fires first
    too_early = api.respond_disclosure_request(
        dr["id"], {"decision": "PUBLISH"}, PROGRAM_ADMIN)
    validate_error(too_early, ApiErrorId.ERR_DISCLOSURE_TOO_EARLY)
    # Inside the closed blackout window
    set_clock("2026-11-02T00:00:00Z")
    blacked = api.respond_disclosure_request(
        dr["id"], {"decision": "PUBLISH"}, PROGRAM_ADMIN)
    validate_error(blacked, ApiErrorId.ERR_BLACKOUT_ACTIVE)
    # After the blackout, publication succeeds
    set_clock("2026-11-06T00:00:00Z")
    published = get_success_data(api.respond_disclosure_request(
        dr["id"], {"decision": "PUBLISH"}, PROGRAM_ADMIN))
    assert published["status"] == "PUBLISHED"
