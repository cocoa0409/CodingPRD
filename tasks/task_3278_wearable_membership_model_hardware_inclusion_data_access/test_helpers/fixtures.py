"""Composite setup helpers.

Every fixture builds its preconditions from scratch via the PRD-declared
endpoints (the harness restarts the server before every test). Fixtures use
get_success_data() internally so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_ingest_payload,
    create_member_payload,
    create_pause_payload,
    create_payment_payload,
    create_device_payload,
    create_release_payload,
    create_replacement_request_payload,
    create_decision_payload,
    create_study_payload,
    create_team_payload,
    create_term_payload,
)
from .test_users import (
    make_anonymous_headers,
    make_coach_headers,
    make_member_headers,
    make_platform_admin_headers,
    make_support_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: basic creation / state progression
# ---------------------------------------------------------------------------

def create_member(email=None, full_name="Test Member") -> dict:
    """Register a member. Returns the created Member dict."""
    payload = create_member_payload()
    if email is not None:
        payload["email"] = email
    payload["full_name"] = full_name
    resp = api_client.create_member(payload, make_anonymous_headers())
    return get_success_data(resp)


def create_term_for_member(member_id: str, **term_overrides) -> dict:
    """Create an ACTIVE term for a member. Returns the term dict."""
    resp = api_client.create_term(
        member_id, create_term_payload(**term_overrides), make_member_headers(member_id)
    )
    return get_success_data(resp)


def create_member_with_term(email=None, **term_overrides):
    """Create member + ACTIVE term. Returns (member, term)."""
    member = create_member(email=email)
    term = create_term_for_member(member["id"], **term_overrides)
    return member, term


def provision_device_for(member_id: str, term_id: str, serial_number=None, **overrides) -> dict:
    """PlatformAdmin provisions a device. Returns the PROVISIONED device."""
    payload = create_device_payload(member_id, term_id, **overrides)
    if serial_number is not None:
        payload["serial_number"] = serial_number
    resp = api_client.provision_device(payload, make_platform_admin_headers())
    return get_success_data(resp)


def create_and_activate_device(member_id: str, term_id: str, serial_number=None, **overrides) -> dict:
    """Provision + activate a device. Returns the ACTIVE device."""
    device = provision_device_for(member_id, term_id, serial_number=serial_number, **overrides)
    resp = api_client.activate_device(device["id"], make_member_headers(member_id))
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock(to_iso8601, make_platform_admin_headers())
    return get_success_data(resp)


def record_payment(term_id: str, outcome: str) -> dict:
    resp = api_client.record_payment(
        term_id, create_payment_payload(outcome), make_support_headers()
    )
    return get_success_data(resp)


def pause_term(term_id: str, member_id: str, start_on: str, days: int) -> dict:
    resp = api_client.pause_term(
        term_id, create_pause_payload(start_on=start_on, days=days),
        make_member_headers(member_id),
    )
    return get_success_data(resp)


def resume_term(term_id: str, member_id: str) -> dict:
    resp = api_client.resume_term(term_id, make_member_headers(member_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_member_with_active_device(email=None, **term_overrides):
    """Member + ACTIVE term + ACTIVE device. Returns (member, term, device)."""
    member, term = create_member_with_term(email=email, **term_overrides)
    device = create_and_activate_device(member["id"], term["id"])
    return member, term, device


def setup_member_with_metric_set(email=None, day_on="2026-09-01", **ingest_overrides):
    """Member + term + ACTIVE device + one ingested metric set.

    Returns (member, term, device, metric_set).
    """
    member, term, device = setup_member_with_active_device(email=email)
    payload = create_ingest_payload(day_on=day_on, **ingest_overrides)
    resp = api_client.ingest_metrics(device["id"], payload, make_member_headers(member["id"]))
    metric_set = get_success_data(resp)
    return member, term, device, metric_set


def setup_team_with_membership(member_id: str, coach_user_id: str, **team_overrides):
    """Create team (owned by coach_user_id) + ACTIVE membership for member.

    Returns (team, membership).
    """
    coach_headers = make_coach_headers(coach_user_id)
    resp = api_client.create_team(
        create_team_payload(coach_user_id, **team_overrides), coach_headers
    )
    team = get_success_data(resp)
    resp = api_client.add_team_membership(
        team["id"], {"member_id": member_id}, coach_headers
    )
    membership = get_success_data(resp)
    return team, membership


def grant_consent(membership: dict, member_id: str, scope: str, expires_on=None) -> dict:
    """Grant a consent scope with the membership's current version."""
    payload = {
        "scope": scope,
        "action": "GRANT",
        "expected_team_membership_version": membership["version"],
    }
    if expires_on is not None:
        payload["expires_on"] = expires_on
    resp = api_client.grant_or_revoke_consent(
        membership["id"], payload, make_member_headers(member_id)
    )
    return get_success_data(resp)


def setup_team_membership_with_consent(
    member_id: str, coach_user_id: str, scope: str, expires_on=None, **team_overrides
):
    """Team + membership + one GRANTED consent. Returns (team, membership_after_grant)."""
    team, membership = setup_team_with_membership(member_id, coach_user_id, **team_overrides)
    updated = grant_consent(membership, member_id, scope, expires_on=expires_on)
    return team, updated


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_open_replacement_request(email=None, reason="HARDWARE_FAILURE"):
    """Member + term + ACTIVE device + OPEN replacement request.

    Returns (member, term, device, request).
    """
    member, term, device = setup_member_with_active_device(email=email)
    resp = api_client.open_replacement_request(
        device["id"], create_replacement_request_payload(reason),
        make_member_headers(member["id"]),
    )
    request = get_success_data(resp)
    return member, term, device, request


def setup_approved_replacement(email=None, reason="HARDWARE_FAILURE"):
    """Full path through decide=APPROVE: faulty device RMA_INBOUND, replacement
    PROVISIONED. Returns (member, term, faulty_device, request, replacement_id)."""
    member, term, device, request = setup_open_replacement_request(email=email, reason=reason)
    resp = api_client.decide_replacement_request(
        request["id"], create_decision_payload("APPROVE"), make_support_headers()
    )
    decided = get_success_data(resp)
    return member, term, device, decided, decided["replacement_device_id"]


def setup_funded_wallet(email=None, monthly_fee_cents=30000, pause_days_per_term=90,
                        pause_days=90, term_overrides=None):
    """Member + ACTIVE term funded by a same-day pause + resume.

    Unused days == pause_days (today == start), so credit ==
    round_half_up(monthly_fee_cents * pause_days / 30).
    Returns (member, term).
    """
    overrides = dict(term_overrides or {})
    overrides.setdefault("monthly_fee_cents", monthly_fee_cents)
    overrides.setdefault("pause_days_per_term", pause_days_per_term)
    member, term = create_member_with_term(email=email, **overrides)
    pause_term(term["id"], member["id"], start_on="2026-09-01", days=pause_days)
    resume_term(term["id"], member["id"])
    return member, term


def setup_suppressed_member(email=None, day_on="2026-09-01", ingest_overrides=None):
    """Member with ACTIVE term + device + metric set, then a published v2
    release (requires_member_ack=true) whose recompute changes recovery ->
    member ends SUPPRESSED. Returns (member, term, device, metric_set, release).
    """
    overrides = {"avg_hr": 140, "hrv_ms": 80, "resting_hr": 50, "sleep_minutes": 360}
    overrides.update(ingest_overrides or {})
    member, term, device, metric_set = setup_member_with_metric_set(
        email=email, day_on=day_on, **overrides
    )
    resp = api_client.create_algorithm_release(
        create_release_payload(version=2, requires_member_ack=True),
        make_platform_admin_headers(),
    )
    release = get_success_data(resp)
    resp = api_client.publish_algorithm_release(release["id"], make_platform_admin_headers())
    get_success_data(resp)
    return member, term, device, metric_set, release
