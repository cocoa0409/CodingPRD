"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the server is restarted before every test, so nothing carries
over). Setup calls use the lenient get_success_data() validator so failures
surface as clear "Setup failed" errors. All ownership-gated calls use
per-instance headers built from the actual Member.id.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, WRONG_CODE
from .factories import (
    assign_slot_payload,
    create_account_payload,
    create_device_payload,
    create_household_payload,
    grant_travel_pass_payload,
    issue_challenge_payload,
    initiate_transfer_payload,
    purchase_slot_payload,
    set_clock_payload,
    submit_challenge_payload,
)
from .test_users import TEST_USERS, make_owner_headers


def admin_headers():
    return TEST_USERS["admin_headers"]


def support_headers():
    return TEST_USERS["support_headers"]


def parse_instant(iso: str) -> datetime:
    """Parse an ISO 8601 instant (accepting a trailing Z) to an aware datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def instants_equal(a: str, b: str) -> bool:
    return parse_instant(a) == parse_instant(b)


# ---------------------------------------------------------------------------
# Tier 1: accounts
# ---------------------------------------------------------------------------

def create_account(email=None, region_code="NA", plan_tier="STANDARD", clock=None):
    """Create an account. Returns (account_dict, owner_headers)."""
    if clock is not None:
        set_clock(clock)
    payload = create_account_payload(region_code=region_code, plan_tier=plan_tier)
    if email is not None:
        payload["email"] = email
    account = get_success_data(api_client.create_account(payload, admin_headers()))
    return account, make_owner_headers(account["owner_member_id"])


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, admin_headers()))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), admin_headers()))


# ---------------------------------------------------------------------------
# Tier 2: account + household + device
# ---------------------------------------------------------------------------

def create_account_with_household(email=None, region_code="NA", plan_tier="STANDARD",
                                  network_fingerprint="fp-home-1", geo_cell="geo-home-1"):
    """Account + ESTABLISHED household. Returns (account, household, owner_headers)."""
    account, owner_h = create_account(email=email, region_code=region_code, plan_tier=plan_tier)
    household = get_success_data(
        api_client.create_household(
            account["id"],
            create_household_payload(
                network_fingerprint=network_fingerprint, geo_cell=geo_cell
            ),
            owner_h,
        )
    )
    return account, household, owner_h


def create_account_with_device(email=None, region_code="NA", plan_tier="STANDARD",
                               device_network="fp-home-1", device_geo="geo-home-1",
                               household_network="fp-home-1", household_geo="geo-home-1",
                               trust=False, device_type="TV"):
    """Account + household + one device (optionally trusted).
    Returns (account, household, device, owner_headers)."""
    account, household, owner_h = create_account_with_household(
        email=email, region_code=region_code, plan_tier=plan_tier,
        network_fingerprint=household_network, geo_cell=household_geo,
    )
    device = get_success_data(
        api_client.create_device(
            household["id"],
            create_device_payload(
                device_type=device_type,
                network_fingerprint=device_network,
                geo_cell=device_geo,
            ),
            owner_h,
        )
    )
    if trust:
        device = get_success_data(api_client.trust_device(device["id"], owner_h))
    return account, household, device, owner_h


# ---------------------------------------------------------------------------
# Tier 3: extra-member slots
# ---------------------------------------------------------------------------

def purchase_slot(account, owner_h):
    """Read the current account version and purchase one slot. Returns slot."""
    fresh = get_account(account["id"])
    return get_success_data(
        api_client.purchase_slot(
            account["id"],
            purchase_slot_payload(account["owner_member_id"], fresh["version"]),
            owner_h,
        )
    )


def create_account_with_slot(email=None, region_code="NA", plan_tier="STANDARD", clock=None):
    """Account + one purchased OFFERED slot. Returns (account, slot, owner_headers)."""
    account, owner_h = create_account(email=email, region_code=region_code,
                                      plan_tier=plan_tier, clock=clock)
    slot = purchase_slot(account, owner_h)
    return account, slot, owner_h


def create_account_with_assigned_slot(email=None, region_code="NA", plan_tier="STANDARD",
                                      extra_email=None, member_region=None, clock=None):
    """Account + one purchased + assigned (ACTIVE) slot.
    Returns (account, slot, extra_member_id, owner_headers)."""
    account, slot, owner_h = create_account_with_slot(
        email=email, region_code=region_code, plan_tier=plan_tier, clock=clock
    )
    payload = assign_slot_payload(member_region=member_region or region_code)
    if extra_email is not None:
        payload["email"] = extra_email
    assigned = get_success_data(api_client.assign_slot(slot["id"], payload, owner_h))
    return account, assigned, assigned["member_id"], owner_h


# ---------------------------------------------------------------------------
# Tier 4: verification challenges
# ---------------------------------------------------------------------------

def issue_challenge(account_id, channel="EMAIL", challenge_reason="NEW_DEVICE"):
    """Issue a challenge as PlatformAdmin. Returns challenge."""
    return get_success_data(
        api_client.issue_challenge(
            account_id,
            issue_challenge_payload(channel=channel, challenge_reason=challenge_reason),
            admin_headers(),
        )
    )


def lock_out_challenge(challenge_id, member_id, owner_h, attempts=3):
    """Drive a PENDING challenge to LOCKED_OUT with the reserved wrong code."""
    result = None
    for _ in range(attempts):
        result = api_client.submit_challenge(
            challenge_id, submit_challenge_payload(WRONG_CODE, member_id), owner_h
        )
    return result


def expire_challenge(challenge_id, advance_to):
    """Advance the clock past expires_at and read the challenge so the lazy
    EXPIRED transition materializes. Returns the read challenge."""
    set_clock(advance_to)
    return get_success_data(api_client.get_challenge(challenge_id, admin_headers()))


# ---------------------------------------------------------------------------
# Tier 5: profile transfers
# ---------------------------------------------------------------------------

def create_pending_transfer(account, member_id, owner_h, target_email=None):
    """Initiate a profile transfer. Returns transfer."""
    payload = initiate_transfer_payload(member_id)
    if target_email is not None:
        payload["target_email"] = target_email
    return get_success_data(
        api_client.initiate_transfer(account["id"], payload, owner_h)
    )


# ---------------------------------------------------------------------------
# Tier 6: travel passes
# ---------------------------------------------------------------------------

def grant_pass(device_id, owner_h, grant_type="TEMPORARY_14D", starts_at=DEFAULT_CLOCK):
    return get_success_data(
        api_client.grant_travel_pass(
            device_id,
            grant_travel_pass_payload(grant_type=grant_type, starts_at=starts_at),
            owner_h,
        )
    )
