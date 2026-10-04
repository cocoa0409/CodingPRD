"""Composite setup helpers for the accreditation / scoring domain.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test). Setup calls use
the lenient get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_publication_payload, create_critic_payload, create_title_payload,
    create_release_payload, create_review_payload,
    create_audience_member_payload, create_ticket_verification_payload,
    create_audience_rating_payload, create_accreditation_review_payload,
)
from .test_users import (
    TEST_USERS, make_critic_headers, make_audience_member_headers,
)
from .constants import TEST_DEFAULTS

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]
STUDIO = TEST_USERS["studio_rep_headers"]

_outlet_seq = [0]


def _unique_outlet() -> str:
    _outlet_seq[0] += 1
    return f"Outlet {_outlet_seq[0]:06d}"


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=TEST_DEFAULTS["CLOCK_START"]):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed (set_clock): {resp.text}"
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation + state progression
# ---------------------------------------------------------------------------

def create_publication(outlet_name=None, **overrides):
    payload = create_publication_payload(
        outlet_name=outlet_name or _unique_outlet())
    payload.update(overrides)
    return get_success_data(api_client.create_publication(payload, ADMIN))


def accredit_publication(publication_id):
    return get_success_data(api_client.transition_publication(
        publication_id, {"action": "ACCREDIT"}, BOARD))


def create_critic(publication_id, is_top_critic=False, full_name=None):
    payload = create_critic_payload(publication_id, is_top_critic=is_top_critic)
    if full_name:
        payload["full_name"] = full_name
    return get_success_data(api_client.create_critic(payload, ADMIN))


def accredit_critic(critic_id):
    return get_success_data(api_client.transition_critic(
        critic_id, {"action": "ACCREDIT"}, BOARD))


def create_title(**overrides):
    return get_success_data(
        api_client.create_title(create_title_payload(**overrides), ADMIN))


def open_title(title_id):
    return get_success_data(
        api_client.update_title(title_id, {"posture": "OPEN"}, ADMIN))


def create_release(title_id, **overrides):
    return get_success_data(api_client.create_release(
        title_id, create_release_payload(**overrides), ADMIN))


def open_release(release_id):
    return get_success_data(api_client.transition_release(
        release_id, {"action": "OPEN"}, ADMIN))


def create_audience_member(**overrides):
    return get_success_data(api_client.create_audience_member(
        create_audience_member_payload(**overrides), ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy composites
# ---------------------------------------------------------------------------

def setup_accredited_publication(outlet_name=None):
    """Create a publication and accredit it. Returns the publication."""
    pub = create_publication(outlet_name=outlet_name)
    return accredit_publication(pub["id"])


def setup_accredited_critic(publication_id, is_top_critic=False,
                            full_name=None):
    """Create a critic under a publication and accredit them."""
    critic = create_critic(publication_id, is_top_critic=is_top_critic,
                           full_name=full_name)
    return accredit_critic(critic["id"])


def setup_open_release(title=None, embargo_until=None, **overrides):
    """Open title + open release under it. Returns (title, release)."""
    if title is None:
        title = open_title(create_title()["id"])
    rel_overrides = dict(overrides)
    if embargo_until is not None:
        rel_overrides["embargo_until"] = embargo_until
    release = create_release(title["id"], **rel_overrides)
    return title, open_release(release["id"])


# ---------------------------------------------------------------------------
# Tier 3: review lifecycle shortcuts
# ---------------------------------------------------------------------------

def ingest_review(release_id, critic_id, designation="FRESH",
                  body_text=None):
    payload = create_review_payload(critic_id, self_designation=designation)
    if body_text:
        payload["body_text"] = body_text
    return get_success_data(api_client.create_review(
        release_id, payload, make_critic_headers(critic_id)))


def publish_review(review_id, critic_id):
    return get_success_data(api_client.transition_review(
        review_id, {"action": "PUBLISH"}, make_critic_headers(critic_id)))


def publish_review_for(release_id, critic_id, designation="FRESH"):
    """Ingest + publish a review by an accredited critic. Returns the review."""
    review = ingest_review(release_id, critic_id, designation=designation)
    return publish_review(review["id"], critic_id)


def revoke_critic_via_review(critic_id, period_start=None, period_end=None):
    """File + begin + RULE_REVOKE an accreditation review against a critic."""
    payload = create_accreditation_review_payload(
        subject_critic_id=critic_id)
    if period_start:
        payload["period_start"] = period_start
    if period_end:
        payload["period_end"] = period_end
    review = get_success_data(
        api_client.create_accreditation_review(payload, BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "BEGIN_REVIEW"}, BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "RULE_REVOKE"}, BOARD))
    return review


# ---------------------------------------------------------------------------
# Tier 4: verified-rating chain
# ---------------------------------------------------------------------------

def setup_verified_ticket(release_id, member_id,
                          showtime_at="2026-09-02T00:00:00Z",
                          exhibitor_code="AMC"):
    """Submit + VERIFY a ticket verification. Returns the verification."""
    tv = get_success_data(api_client.create_ticket_verification(
        release_id,
        create_ticket_verification_payload(
            member_id, showtime_at=showtime_at, exhibitor_code=exhibitor_code),
        make_audience_member_headers(member_id)))
    return get_success_data(api_client.transition_ticket_verification(
        tv["id"], {"action": "VERIFY"}, ADMIN))


def create_rating(release_id, member_id, stars, ticket_verification_id=None):
    payload = create_audience_rating_payload(member_id, stars=stars)
    if ticket_verification_id is not None:
        payload["ticket_verification_id"] = ticket_verification_id
    return get_success_data(api_client.create_audience_rating(
        release_id, payload, make_audience_member_headers(member_id)))


def setup_verified_rating(release_id, member_id, stars,
                          showtime_at="2026-09-02T00:00:00Z"):
    """Member + verified ticket + rating VERIFY-transitioned.

    Returns (ticket_verification, rating). Caller supplies the member id.
    """
    tv = setup_verified_ticket(release_id, member_id, showtime_at=showtime_at)
    rating = create_rating(release_id, member_id, stars)
    rating = get_success_data(api_client.transition_audience_rating(
        rating["id"],
        {"action": "VERIFY", "ticket_verification_id": tv["id"]},
        make_audience_member_headers(member_id)))
    return tv, rating


# ---------------------------------------------------------------------------
# Dispute helpers
# ---------------------------------------------------------------------------

def file_classification_dispute(review_id, filer_critic_id,
                                requested_classification):
    return get_success_data(api_client.create_dispute(
        {"dispute_kind": "CLASSIFICATION",
         "subject_review_id": review_id,
         "filed_by_critic_id": filer_critic_id,
         "requested_classification": requested_classification},
        make_critic_headers(filer_critic_id)))


def file_score_display_dispute(release_id, studio_name="Harbor Pictures"):
    return get_success_data(api_client.create_dispute(
        {"dispute_kind": "SCORE_DISPLAY",
         "subject_release_id": release_id,
         "filed_by_studio": studio_name},
        STUDIO))


def triage_dispute(dispute_id):
    return get_success_data(api_client.transition_dispute(
        dispute_id, {"action": "TRIAGE"}, BOARD))


def rule_dispute(dispute_id, action):
    """RULE_UPHOLD / RULE_REJECT carrying the current dispute version (OCC)."""
    dispute = get_success_data(api_client.get_dispute(dispute_id, BOARD))
    return get_success_data(api_client.transition_dispute(
        dispute_id,
        {"action": action, "expected_dispute_version": dispute["version"]},
        BOARD))
