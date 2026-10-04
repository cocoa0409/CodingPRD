"""Composite setup helpers for multi-step PRD workflows.

Every fixture builds preconditions from scratch using only PRD-declared endpoints,
because the server is restarted before every test with an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_editor_payload,
    create_page_payload,
    create_revision_payload,
    create_dispute_payload,
    create_protection_request_payload,
    create_flag_payload,
    create_campaign_payload,
    create_banner_payload,
    create_impression_payload,
    create_donation_payload,
    create_grant_program_payload,
    create_grant_application_payload,
    create_score_payload,
    create_legal_request_payload,
    create_transparency_report_payload,
    resolve_dispute_payload,
)
from .test_users import TEST_USERS, make_volunteer_editor_headers

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Advance the logical clock."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, TEST_USERS["platform_admin_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def create_editor(**overrides):
    """Create a VolunteerEditor. Returns (editor, headers) where headers carry the
    editor's real id for ownership-gated calls."""
    resp = api_client.create_editor(create_editor_payload(**overrides), TEST_USERS["anonymous_headers"])
    editor = get_success_data(resp)
    return editor, make_volunteer_editor_headers(editor["id"])


def create_page(editor_headers, **overrides):
    resp = api_client.create_page(create_page_payload(**overrides), editor_headers)
    return get_success_data(resp)


def create_revision(page_id, editor_headers, **overrides):
    resp = api_client.create_revision(page_id, create_revision_payload(**overrides), editor_headers)
    return get_success_data(resp)


def create_campaign(**overrides):
    resp = api_client.create_campaign(create_campaign_payload(**overrides), TEST_USERS["fundraising_manager_headers"])
    return get_success_data(resp)


def create_banner(campaign_id, **overrides):
    resp = api_client.create_banner(campaign_id, create_banner_payload(**overrides), TEST_USERS["fundraising_manager_headers"])
    return get_success_data(resp)


def create_donation(campaign_id, banner_id, **overrides):
    payload = create_donation_payload(**overrides)
    payload["banner_id"] = banner_id
    resp = api_client.create_donation(campaign_id, payload, TEST_USERS["anonymous_headers"])
    return get_success_data(resp)


def create_grant_program(**overrides):
    resp = api_client.create_grant_program(create_grant_program_payload(**overrides), TEST_USERS["grant_administrator_headers"])
    return get_success_data(resp)


def create_grant_application(program_id, applicant_headers, **overrides):
    resp = api_client.create_grant_application(program_id, create_grant_application_payload(**overrides), applicant_headers)
    return get_success_data(resp)


def create_legal_request(**overrides):
    resp = api_client.create_legal_request(create_legal_request_payload(**overrides), TEST_USERS["legal_counsel_headers"])
    return get_success_data(resp)


def create_transparency_report(**overrides):
    resp = api_client.create_transparency_report(create_transparency_report_payload(**overrides), TEST_USERS["legal_counsel_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: state progression
# ---------------------------------------------------------------------------

def create_active_campaign_with_banner(campaign_overrides=None, banner_overrides=None):
    """Create campaign + one banner, activate campaign. Returns (campaign, banner).
    Campaign is ACTIVE; banner is ACTIVE. Campaign version after activation is
    version_at_create + 1."""
    campaign = create_campaign(**(campaign_overrides or {}))
    banner = create_banner(campaign["id"], **(banner_overrides or {}))
    resp = api_client.activate_campaign(
        campaign["id"], {"expected_campaign_version": campaign["version"]},
        TEST_USERS["fundraising_manager_headers"],
    )
    campaign = get_success_data(resp)
    return campaign, banner


def create_pledged_donation(campaign, banner, **overrides):
    """Create a PLEDGED donation against an ACTIVE campaign/banner."""
    return create_donation(campaign["id"], banner["id"], **overrides)


def create_completed_donation(campaign, banner, **overrides):
    """Create + process a donation. Returns the COMPLETED donation."""
    donation = create_pledged_donation(campaign, banner, **overrides)
    resp = api_client.process_donation(donation["id"], TEST_USERS["payment_processor_headers"])
    return get_success_data(resp)


def create_accepted_revision(page, editor_headers, **overrides):
    """Create a revision on the page and accept it as Administrator.
    Returns (revision, refreshed_page)."""
    revision = create_revision(page["id"], editor_headers, **overrides)
    resp = api_client.accept_revision(
        revision["id"], {"expected_page_version": page["version"]},
        TEST_USERS["administrator_headers"],
    )
    revision = get_success_data(resp)
    page = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
    return revision, page


def create_open_dispute(page, initiator_headers, respondent_id, subject_revision_id, **overrides):
    """Open a TALK-level dispute on a page. Returns the DisputeCase (OPEN, TALK)."""
    payload = create_dispute_payload(**overrides)
    payload["respondent_id"] = respondent_id
    payload["subject_revision_id"] = subject_revision_id
    resp = api_client.create_dispute(page["id"], payload, initiator_headers)
    return get_success_data(resp)


def escalate_dispute_after(dispute, actor_headers, new_clock):
    """Advance clock, then escalate. Returns refreshed dispute."""
    set_clock(new_clock)
    resp = api_client.escalate_dispute(
        dispute["id"], {"expected_dispute_version": dispute["version"]}, actor_headers,
    )
    return get_success_data(resp)


def create_notice_level_dispute(page, initiator_headers, respondent_id, subject_revision_id,
                                first_clock="2026-09-05T00:00:00Z", **overrides):
    """Open a TALK dispute then escalate to NOTICE after 72h. Returns refreshed dispute."""
    dispute = create_open_dispute(page, initiator_headers, respondent_id, subject_revision_id, **overrides)
    return escalate_dispute_after(dispute, initiator_headers, first_clock)


def create_arbitration_level_dispute(page, initiator_headers, respondent_id, subject_revision_id,
                                     first_clock="2026-09-05T00:00:00Z",
                                     second_clock="2026-09-09T00:00:00Z", **overrides):
    """Open a TALK dispute, escalate to NOTICE after 72h, then to ARBITRATION after
    another 72h. Returns refreshed dispute."""
    dispute = create_notice_level_dispute(page, initiator_headers, respondent_id,
                                          subject_revision_id, first_clock, **overrides)
    return escalate_dispute_after(dispute, initiator_headers, second_clock)


def flag_and_confirm_revision(revision_id, reporter_headers, report_type="VANDALISM"):
    """Flag a revision then confirm the report as Administrator.
    Returns (flagged_revision_report, confirmed_report)."""
    resp = api_client.flag_revision(revision_id, create_flag_payload(report_type=report_type), reporter_headers)
    report = get_success_data(resp)
    resp = api_client.confirm_vandalism_report(report["id"], TEST_USERS["administrator_headers"])
    return get_success_data(resp)


def setup_scored_application_under_review(program, applicant_headers, scores=None, **overrides):
    """Create application, start review, score it. Returns refreshed application
    (UNDER_REVIEW with review_score set)."""
    application = create_grant_application(program["id"], applicant_headers, **overrides)
    resp = api_client.start_review_grant_application(application["id"], TEST_USERS["grant_reviewer_headers"])
    application = get_success_data(resp)
    resp = api_client.score_grant_application(
        application["id"], create_score_payload(**(scores or {})),
        TEST_USERS["grant_reviewer_headers"],
    )
    return get_success_data(resp)


def setup_approved_application(program, applicant_headers, awarded_cents, scores=None, **overrides):
    """Create application, review, score, approve. Returns refreshed application (APPROVED)."""
    application = setup_scored_application_under_review(program, applicant_headers, scores=scores, **overrides)
    resp = api_client.approve_grant_application(
        application["id"],
        {"awarded_cents": awarded_cents, "expected_application_version": application["version"]},
        TEST_USERS["grant_reviewer_headers"],
    )
    return get_success_data(resp)
