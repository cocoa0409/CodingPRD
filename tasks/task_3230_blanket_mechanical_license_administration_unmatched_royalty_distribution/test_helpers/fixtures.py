"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a fresh server
(the harness restarts the server before each test) using only PRD-declared
endpoints. Setup calls use get_success_data() so a failure surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.

Identity threading rule: ownership-gated calls for entity-backed roles use
make_dsp_headers(dsp["id"]) / make_member_headers(member["id"]) — never the
shared TEST_USERS constants.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO
from .factories import (
    create_service_provider_payload, create_member_payload,
    create_payee_payload, create_work_payload, create_share_payload,
    create_rate_schedule_payload, create_usage_line_payload,
)
from .test_users import TEST_USERS, make_dsp_headers, make_member_headers

ADMIN = TEST_USERS["admin_headers"]


def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_active_schedule(under=131, over=252,
                           effective_from="2026-01-01T00:00:00Z",
                           effective_to=None, headers=None):
    """Create + activate a rate schedule. Returns the ACTIVE schedule dict."""
    headers = headers or ADMIN
    payload = create_rate_schedule_payload(
        effective_from=effective_from,
        rate_cents_under_5min=under,
        rate_cents_per_minute_over_5min=over,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    rs = get_success_data(api_client.create_rate_schedule(payload, headers))
    return get_success_data(api_client.activate_rate_schedule(rs["id"], headers))


def create_schedule_pending(under=131, over=252,
                            effective_from="2026-01-01T00:00:00Z",
                            effective_to=None, headers=None):
    """Create a PENDING rate schedule (not activated)."""
    headers = headers or ADMIN
    payload = create_rate_schedule_payload(
        effective_from=effective_from,
        rate_cents_under_5min=under,
        rate_cents_per_minute_over_5min=over,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return get_success_data(api_client.create_rate_schedule(payload, headers))


def create_dsp(headers=None):
    """Register a PENDING service provider."""
    headers = headers or ADMIN
    return get_success_data(
        api_client.create_service_provider(create_service_provider_payload(), headers))


def activate_dsp(dsp, headers=None):
    """Activate a DSP; returns (dsp_dict_after_activate, dsp_user_headers, ack_version)."""
    headers = headers or ADMIN
    dsp = get_success_data(api_client.activate_service_provider(dsp["id"], headers))
    return dsp, make_dsp_headers(dsp["id"]), dsp["accepted_rate_schedule_version"]


def setup_active_dsp(legal_name=None, headers=None):
    """PENDING -> ACTIVE DSP. Returns (dsp, dsp_headers, ack_version)."""
    headers = headers or ADMIN
    payload = create_service_provider_payload()
    if legal_name:
        payload["legal_name"] = legal_name
    dsp = get_success_data(api_client.create_service_provider(payload, headers))
    return activate_dsp(dsp, headers)


def create_member(headers=None, **overrides):
    """Register a member (born ACTIVE)."""
    headers = headers or ADMIN
    return get_success_data(
        api_client.create_member(create_member_payload(**overrides), headers))


def create_payee(member_id, headers=None, **overrides):
    """Set up an ACH payee for a member (born ACTIVE)."""
    headers = headers or ADMIN
    return get_success_data(
        api_client.create_payee(member_id, create_payee_payload(**overrides), headers))


def setup_member_with_payee(headers=None, **member_overrides):
    """Member + one ACTIVE ACH payee. Returns (member, payee)."""
    member = create_member(headers=headers, **member_overrides)
    payee = create_payee(member["id"], headers=headers)
    return member, payee


def create_work(headers=None, **overrides):
    headers = headers or ADMIN
    return get_success_data(
        api_client.create_work(create_work_payload(**overrides), headers))


def create_share(work_id, claimant_member_id, share_percent=100,
                 effective_from="2026-01-01T00:00:00Z", effective_to=None,
                 supersedes_share_id=None, expected_work_version=None,
                 headers=None):
    """Create a share with OCC. When expected_work_version is None the current
    work version is re-read first. Returns the new share dict."""
    headers = headers or ADMIN
    if expected_work_version is None:
        work = get_success_data(api_client.get_work(work_id, headers))
        expected_work_version = work["version"]
    payload = create_share_payload(
        claimant_member_id=claimant_member_id,
        share_percent=share_percent,
        effective_from=effective_from,
        expected_work_version=expected_work_version,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    if supersedes_share_id is not None:
        payload["supersedes_share_id"] = supersedes_share_id
    return get_success_data(api_client.create_share(work_id, payload, headers))


def setup_work_with_share(title, member, share_percent=100,
                          effective_from="2026-01-01T00:00:00Z",
                          headers=None, **work_overrides):
    """Work + one ACTIVE share for the member. Returns (work, share)."""
    headers = headers or ADMIN
    work = create_work(headers=headers, title=title, **work_overrides)
    share = create_share(work["id"], member["id"], share_percent=share_percent,
                         effective_from=effective_from, headers=headers)
    work = get_success_data(api_client.get_work(work["id"], headers))
    return work, share


def create_report_with_lines(dsp, dsp_headers, month, lines):
    """DRAFT report with the given lines added. lines is a list of dicts with
    keys track_title/plays_count/duration_seconds (+ optional isrc).
    Returns (report, [line dicts])."""
    report = get_success_data(api_client.create_usage_report(
        dsp["id"], {"reporting_month": month}, dsp_headers))
    created = []
    for spec in lines:
        payload = create_usage_line_payload(
            track_title=spec["track_title"],
            plays_count=spec["plays_count"],
            duration_seconds=spec["duration_seconds"],
        )
        if "isrc" in spec:
            payload["isrc"] = spec["isrc"]
        created.append(get_success_data(api_client.create_usage_line(
            dsp["id"], report["id"], payload, dsp_headers)))
    return report, created


def submit_report(dsp, dsp_headers, ack_version, report):
    return get_success_data(api_client.submit_usage_report(
        dsp["id"], report["id"], ack_version, dsp_headers))


def accept_report(dsp, ack_version, report, headers=None):
    headers = headers or ADMIN
    return get_success_data(api_client.accept_usage_report(
        dsp["id"], report["id"], ack_version, headers))


def setup_report_in_state(month="2026-06", lines=None, target="ACCEPTED"):
    """Full chain: ACTIVE schedule + ACTIVE DSP + report with lines walked to
    the target state ("SUBMITTED" or "ACCEPTED").
    Returns (dsp, dsp_headers, ack, report, lines)."""
    lines = lines if lines is not None else [
        {"track_title": "NoSuchWorkTitleXYZ", "plays_count": 10, "duration_seconds": 100}
    ]
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    report, created = create_report_with_lines(dsp, dsp_headers, month, lines)
    if target in ("SUBMITTED", "ACCEPTED"):
        report = submit_report(dsp, dsp_headers, ack, report)
    if target == "ACCEPTED":
        report = accept_report(dsp, ack, report)
    return dsp, dsp_headers, ack, report, created


_pad_counter = itertools.count(1)


def pad_report_for_match_floor(dsp, dsp_headers, report, unmatched_cents,
                               rate=131):
    """Pad a DRAFT report with a matched line so acceptance's data-quality
    circuit breaker passes (PRD §3.3: rejected when unmatched*100 > 60*total).

    Registers a fresh shareless work titled uniquely and adds one line naming
    it, so the line matches at acceptance without creating accruals, postings
    (no shares), or member-weight side effects. Returns the pad line dict.
    """
    n = next(_pad_counter)
    title = f"PadAnchor{n}"
    create_work(title=title)
    # Need 100*U <= 60*(U + rate*plays)  =>  plays >= 2U / (3*rate)
    plays = -(-2 * unmatched_cents // (3 * rate))  # ceil
    if plays < 1:
        plays = 1
    return get_success_data(api_client.create_usage_line(
        dsp["id"], report["id"],
        create_usage_line_payload(
            track_title=title, plays_count=plays, duration_seconds=100),
        dsp_headers))


def get_line_accrual(line_id, headers=None):
    """Return the (single) accrual of an unmatched line."""
    headers = headers or ADMIN
    data, _meta = _list_accruals_of_line(line_id, headers)
    assert len(data) >= 1, f"Setup failed: no accrual found for line {line_id}"
    return data[0]


def _list_accruals_of_line(line_id, headers):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_line_accruals(line_id, headers)
    return validate_paginated(resp)


def setup_accepted_report_with_unmatched_line(
        title="NoSuchWorkTitleXYZ", plays=100, duration=100, month="2026-06",
        clock=CLOCK_DEFAULT_ISO):
    """Accepted report whose named line matched nothing: one HELD accrual.

    The report is padded with a matched line (shareless pad work) so the
    acceptance circuit breaker passes: the named line's cents must not
    strictly exceed 60% of the report total (PRD §3.3).
    Returns (dsp, dsp_headers, ack, report, line, accrual)."""
    set_clock(clock)
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    report, lines = create_report_with_lines(
        dsp, dsp_headers, month,
        [{"track_title": title, "plays_count": plays, "duration_seconds": duration}])
    # Pad so the unmatched line's share of the total stays at or under 60%.
    unmatched_cents = lines[0]["royalties_cents"]
    pad_report_for_match_floor(dsp, dsp_headers, report, unmatched_cents)
    report = submit_report(dsp, dsp_headers, ack, report)
    report = accept_report(dsp, ack, report)
    accrual = get_line_accrual(lines[0]["id"])
    return dsp, dsp_headers, ack, report, lines[0], accrual


def setup_pending_claim(title="Gale", plays=100, duration=100, month="2026-06",
                        clock=CLOCK_DEFAULT_ISO, share_percent=100):
    """Same chain as setup_validated_claim but stops before validation: the
    claim is PENDING. Disputes seed from a PENDING claim (PRD §3.6's contested
    branch routes the claim being validated into the dispute).
    Returns (dsp, report, line, accrual, member, work, claim)."""
    set_clock(clock)
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    member = create_member()
    work, _share = setup_work_with_share(title + " (claimed work)", member,
                                         share_percent=share_percent)
    report, lines = create_report_with_lines(
        dsp, dsp_headers, month,
        [{"track_title": title, "plays_count": plays, "duration_seconds": duration}])
    pad_report_for_match_floor(dsp, dsp_headers, report,
                               lines[0]["royalties_cents"])
    report = submit_report(dsp, dsp_headers, ack, report)
    report = accept_report(dsp, ack, report)
    line = get_success_data(api_client.get_usage_line(lines[0]["id"], ADMIN))
    assert line["status"] == "UNMATCHED", (
        f"Setup failed: expected line UNMATCHED, got {line['status']} "
        "(the pre-registered work matched the line at acceptance)"
    )
    accrual = get_line_accrual(line["id"])
    member_headers = make_member_headers(member["id"])
    claim = get_success_data(api_client.create_claim({
        "accrual_id": accrual["id"],
        "claimant_member_id": member["id"],
        "claimed_work_id": work["id"],
        "share_percent_claimed": share_percent,
    }, member_headers))
    return dsp, report, line, accrual, member, work, claim


def setup_validated_claim(title="Gale", plays=100, duration=100, month="2026-06",
                          clock=CLOCK_DEFAULT_ISO, share_percent=100):
    """Full chain: HELD accrual + member with a covering share on a work +
    claim by that member + admin validation.

    The work's title deliberately differs from the line's track_title so the
    line goes UNMATCHED at acceptance (a claim names the work the claimant
    says the usage embodies; no title equality is required by PRD §3.6). The
    report is padded with a matched line so the acceptance circuit breaker
    passes (PRD §3.3).
    Returns (dsp, report, line, accrual, member, work, claim)."""
    set_clock(clock)
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    member = create_member()
    work, _share = setup_work_with_share(title + " (claimed work)", member,
                                         share_percent=share_percent)
    report, lines = create_report_with_lines(
        dsp, dsp_headers, month,
        [{"track_title": title, "plays_count": plays, "duration_seconds": duration}])
    pad_report_for_match_floor(dsp, dsp_headers, report,
                               lines[0]["royalties_cents"])
    report = submit_report(dsp, dsp_headers, ack, report)
    report = accept_report(dsp, ack, report)
    line = get_success_data(api_client.get_usage_line(lines[0]["id"], ADMIN))
    assert line["status"] == "UNMATCHED", (
        f"Setup failed: expected line UNMATCHED, got {line['status']} "
        "(the pre-registered work matched the line at acceptance)"
    )
    accrual = get_line_accrual(line["id"])
    member_headers = make_member_headers(member["id"])
    claim = get_success_data(api_client.create_claim({
        "accrual_id": accrual["id"],
        "claimant_member_id": member["id"],
        "claimed_work_id": work["id"],
        "share_percent_claimed": share_percent,
    }, member_headers))
    claim = get_success_data(api_client.validate_claim(claim["id"], ADMIN))
    return dsp, report, line, accrual, member, work, claim


def hold_expiry_for_month(reporting_month: str) -> str:
    """hold_expires_at: 36 months after the first day of the month following
    the reporting month."""
    year, month = int(reporting_month[:4]), int(reporting_month[5:7])
    month += 1
    if month > 12:
        month = 1
        year += 1
    year += 3  # +36 months
    return f"{year:04d}-{month:02d}-01T00:00:00Z"


def setup_open_dispute(clock=CLOCK_DEFAULT_ISO):
    """Pending claim + a dispute opened over the claimed share.
    Returns (dsp, report, line, accrual, member, work, claim, dispute)."""
    dsp, report, line, accrual, member, work, claim = setup_pending_claim(
        title="Gale", clock=clock)
    dispute = get_success_data(api_client.create_dispute({
        "work_id": work["id"],
        "share_context": "Alder Publishing 100%",
        "initiating_claim_id": claim["id"],
    }, make_member_headers(member["id"])))
    return dsp, report, line, accrual, member, work, claim, dispute
