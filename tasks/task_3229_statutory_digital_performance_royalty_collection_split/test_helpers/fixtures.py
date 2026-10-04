"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and uses the lenient get_success_data()
validator so a setup failure surfaces as "Setup failed", not an assertion deep
inside a test. Ownership-gated calls always use make_licensee_headers with the
real Licensee id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PAST_SCHEDULED_FOR
from .factories import (
    create_artist_payload,
    create_audit_case_payload,
    create_licensee_payload,
    create_ownership_claim_payload,
    create_play_line_payload,
    create_rate_proceeding_payload,
    create_rate_schedule_payload,
    create_recording_payload,
    create_rights_owner_payload,
    create_unclaimed_pool_payload,
    create_usage_report_payload,
)
from .test_users import (
    make_admin_headers,
    make_licensee_headers,
    make_matching_agent_headers,
    make_payee_admin_headers,
    make_royalty_auditor_headers,
    make_royalty_ops_headers,
    make_statutory_board_headers,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
PAYEE = make_payee_admin_headers()
BOARD = make_statutory_board_headers()
MATCHER = make_matching_agent_headers()


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation / state progression
# ---------------------------------------------------------------------------

def create_effective_schedule(**overrides):
    """Create a rate schedule and activate it. Returns the EFFECTIVE schedule."""
    resp = api_client.create_rate_schedule(create_rate_schedule_payload(**overrides),
                                           ADMIN)
    sched = get_success_data(resp)
    resp = api_client.activate_rate_schedule(sched["id"], ADMIN)
    return get_success_data(resp)


def create_licensee(**overrides):
    """Create a licensee in DRAFT status."""
    resp = api_client.create_licensee(create_licensee_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_active_licensee(**overrides):
    """Create a licensee and activate it. Returns the ACTIVE licensee."""
    lic = create_licensee(**overrides)
    resp = api_client.activate_licensee(lic["id"], ADMIN)
    return get_success_data(resp)


def create_verified_rights_owner(**overrides):
    """Create a rights owner and verify it. Returns the VERIFIED rights owner."""
    resp = api_client.create_rights_owner(create_rights_owner_payload(**overrides),
                                          PAYEE)
    ro = get_success_data(resp)
    resp = api_client.verify_rights_owner(ro["id"], PAYEE)
    return get_success_data(resp)


def create_verified_artist(**overrides):
    """Create an artist and verify it. Returns the VERIFIED artist."""
    resp = api_client.create_artist(create_artist_payload(**overrides), PAYEE)
    artist = get_success_data(resp)
    resp = api_client.verify_artist(artist["id"], PAYEE)
    return get_success_data(resp)


def create_recording(rights_owner_id, featured_artist_id, **overrides):
    """Register a catalog recording. Returns the ACTIVE recording."""
    resp = api_client.create_recording(
        create_recording_payload(rights_owner_id, featured_artist_id, **overrides),
        ADMIN,
    )
    return get_success_data(resp)


def create_pool(**overrides):
    """Create an unclaimed accrual pool. Returns the ACCRUING pool."""
    resp = api_client.create_unclaimed_pool(create_unclaimed_pool_payload(**overrides),
                                            ADMIN)
    return get_success_data(resp)


def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.5). Returns the response data."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: report lifecycle pipeline
# ---------------------------------------------------------------------------

def create_report_with_lines(licensee_id, lines, period_start, period_end):
    """Create a DRAFT report and add the given play lines to it.

    `lines` is a list of dicts of play-line input fields. Returns
    (report, created_line_dicts).
    """
    lh = make_licensee_headers(licensee_id)
    resp = api_client.create_usage_report(
        create_usage_report_payload(licensee_id, period_start=period_start,
                                    period_end=period_end),
        lh,
    )
    report = get_success_data(resp)
    created = []
    for line in lines:
        resp = api_client.add_play_line(report["id"], create_play_line_payload(**line), lh)
        created.append(get_success_data(resp))
    return report, created


def submit_and_accept_report(report_id, licensee_id):
    """Submit a DRAFT report and accept it. Returns the ACCEPTED report."""
    lh = make_licensee_headers(licensee_id)
    resp = api_client.submit_usage_report(report_id, lh)
    submitted = get_success_data(resp)
    resp = api_client.accept_usage_report(report_id, OPS)
    accepted = get_success_data(resp)
    return accepted


def setup_accepted_report_with_liability(
    licensee_id, lines, period_start, period_end,
):
    """DRAFT report + lines -> submit -> accept -> compute liability.

    Returns (report_after_compute, liability). The report dict carries the
    version bumped by the successful compute (PRD §2.9).
    """
    report, created = create_report_with_lines(licensee_id, lines,
                                               period_start, period_end)
    accepted = submit_and_accept_report(report["id"], licensee_id)
    resp = api_client.compute_liability(
        report["id"],
        {"expected_usage_report_version": accepted["version"]},
        OPS,
    )
    liability = get_success_data(resp)
    report_after = get_success_data(api_client.get_usage_report(report["id"], OPS))
    return report_after, liability


def pay_liability(liability_id):
    """Bill a COMPUTED liability and record full payment. Returns the PAID liability."""
    resp = api_client.bill_liability(liability_id, OPS)
    get_success_data(resp)
    resp = api_client.record_liability_payment(liability_id, OPS)
    return get_success_data(resp)


def setup_paid_pipeline(
    licensee_id, lines, period_start, period_end,
):
    """Full royalty pipeline: report -> accept -> compute -> bill -> pay.

    Returns (report_after_compute, paid_liability).
    """
    report, liability = setup_accepted_report_with_liability(
        licensee_id, lines, period_start, period_end,
    )
    paid = pay_liability(liability["id"])
    return report, paid


def setup_executed_batch(report, liability, licensee_id=None):
    """Create a 2026 unclaimed pool, plan a batch, advance the clock past its
    scheduled_for, and execute it.

    Returns (executed_batch, pool).
    """
    pool = create_pool()
    resp = api_client.create_distribution_batch(
        report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
    )
    batch = get_success_data(resp)
    # Advance the logical clock to exactly scheduled_for so the due gate
    # (`scheduled_for` at or before the logical clock) is satisfied.
    set_clock("2026-10-01T00:00:00Z")
    resp = api_client.execute_distribution_batch(
        batch["id"],
        {"expected_distribution_batch_version": batch["version"]},
        OPS,
    )
    executed = get_success_data(resp)
    pool = get_success_data(api_client.get_unclaimed_pool(pool["id"], OPS))
    return executed, pool


def setup_standard_paid_scenario(
    legal_name="ScenarioCo",
    lines=None,
    period_start="2026-01-01T00:00:00Z",
    period_end="2026-01-31T00:00:00Z",
):
    """Schedule NS-1 EFFECTIVE + ACTIVE licensee + paid liability for one report.

    Returns dict with keys: schedule, licensee, report, liability.
    """
    schedule = create_effective_schedule()
    licensee = create_active_licensee(legal_name=legal_name)
    if lines is None:
        lines = [{"isrc": "NM-STD", "track_title": "std", "artist_name": "std",
                  "performance_count": 10000}]
    report, liability = setup_paid_pipeline(
        licensee["id"], lines, period_start, period_end,
    )
    return {
        "schedule": schedule,
        "licensee": licensee,
        "report": report,
        "liability": liability,
    }


# ---------------------------------------------------------------------------
# Tier 3: audit lifecycle
# ---------------------------------------------------------------------------

def open_audit_case(licensee_id, auditor_user_id="auditor-one", **overrides):
    """Open an audit case against a licensee. Returns the OPENED audit case."""
    headers = make_royalty_auditor_headers(auditor_user_id)
    resp = api_client.create_audit_case(
        licensee_id, create_audit_case_payload(**overrides), headers,
    )
    return get_success_data(resp)


def issue_audit_findings(audit_id, declared_true_performances,
                         auditor_user_id="auditor-two"):
    """Issue findings from a different operator than the opener (segregation of
    duties). Returns the FINDINGS_ISSUED audit case."""
    headers = make_royalty_auditor_headers(auditor_user_id)
    resp = api_client.issue_audit_findings(
        audit_id, {"declared_true_performances": declared_true_performances}, headers,
    )
    return get_success_data(resp)


def setup_march_audit_scenario(
    legal_name="AuditCo",
    declared_true_performances=50000000,
    reported_performances=40000000,
):
    """Schedule NS-1 + ACTIVE licensee + a March report (reported_performances,
    gross 104000 > min fee at 40M perfs) billed and paid, plus an OPENED audit
    over March with findings already issued by a different auditor.

    Returns dict with keys: schedule, licensee, report, liability, audit.
    """
    schedule = create_effective_schedule()
    licensee = create_active_licensee(legal_name=legal_name)
    report, liability = setup_paid_pipeline(
        licensee["id"],
        [{"isrc": "NM-AUD", "track_title": "a", "artist_name": "a",
          "performance_count": reported_performances}],
        "2026-03-01T00:00:00Z",
        "2026-03-31T00:00:00Z",
    )
    audit = open_audit_case(
        licensee["id"],
        period_start="2026-03-01T00:00:00Z",
        period_end="2026-03-31T00:00:00Z",
    )
    audit = issue_audit_findings(audit["id"], declared_true_performances)
    return {
        "schedule": schedule,
        "licensee": licensee,
        "report": report,
        "liability": liability,
        "audit": audit,
    }


# ---------------------------------------------------------------------------
# Tier 4: ownership-claim composites
# ---------------------------------------------------------------------------

def setup_recording_with_claimants(isrc="ISRC-CLAIM", claimant_verified=True):
    """Two rights owners (RO1 = owner, RO2 = claimant) + one verified artist +
    one ACTIVE recording owned by RO1. Returns dict of the created entities.

    When claimant_verified is False, RO2 is left PENDING_VERIFICATION.
    """
    ro1 = create_verified_rights_owner(legal_name="Claim Label One",
                                       contact_email="c1@example.com")
    if claimant_verified:
        ro2 = create_verified_rights_owner(legal_name="Claim Label Two",
                                           contact_email="c2@example.com")
    else:
        resp = api_client.create_rights_owner(
            create_rights_owner_payload(legal_name="Claim Label Two",
                                        contact_email="c2@example.com"),
            PAYEE,
        )
        ro2 = get_success_data(resp)
    artist = create_verified_artist(stage_name="Claim Artist",
                                    contact_email="ca@example.com")
    rec = create_recording(ro1["id"], artist["id"], isrc=isrc)
    return {"ro1": ro1, "ro2": ro2, "artist": artist, "recording": rec}
