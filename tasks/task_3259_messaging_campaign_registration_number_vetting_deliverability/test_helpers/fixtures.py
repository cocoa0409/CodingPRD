"""Composite setup builders and the pytest fixtures that expose them.

Every builder drives the public API only. Builders use ``get_success_data``
so a setup step that the PRD allows to answer 200 or 201 is not pinned to
one of the two at every call site, and a failed setup step reports
"Setup step failed" instead of a confusing assertion deep in a test.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_INITIAL_INSTANT
from . import factories as f
from .test_users import (
    ADMIN,
    ANALYST,
    BRAND_MANAGER,
    CAMPAIGN_MANAGER,
    CARRIER_REVIEWER,
    COMPLIANCE,
    PROVISIONER,
    SYSTEM_DRIVER,
)

# ─── pytest fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def client():
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def api(client):
    """Alias kept so a test can read either name."""
    return client


# ─── Building blocks ──────────────────────────────────────────────────────


def set_clock(client, to_iso8601=CLOCK_INITIAL_INSTANT):
    """Move the logical clock (PRD section 2.5)."""
    response = client.set_clock(to_iso8601, headers=ADMIN)
    return get_success_data(response)


def create_account(client, **overrides):
    """Create an account and return its data payload."""
    response = client.create_account(f.account_payload(**overrides), headers=ADMIN)
    return get_success_data(response)


def create_brand(client, account_id, profile="high95", **overrides):
    """Create a DRAFT brand from a named scoring profile."""
    response = client.create_brand(
        account_id, f.brand_payload(profile, **overrides), headers=BRAND_MANAGER
    )
    return get_success_data(response)


def submit_brand(client, account_id, brand_id):
    response = client.submit_brand(account_id, brand_id, headers=BRAND_MANAGER)
    return get_success_data(response)


def verify_brand(client, account_id, brand_id):
    response = client.verify_brand(account_id, brand_id, headers=CARRIER_REVIEWER)
    return get_success_data(response)


def fail_brand(client, account_id, brand_id):
    response = client.fail_brand(account_id, brand_id, headers=CARRIER_REVIEWER)
    return get_success_data(response)


def create_verified_brand(client, account_id, profile="high95", **overrides):
    """Create + submit + verify a brand. Returns the VERIFIED brand."""
    brand = create_brand(client, account_id, profile=profile, **overrides)
    submit_brand(client, account_id, brand["id"])
    return verify_brand(client, account_id, brand["id"])


def create_campaign(client, account_id, brand_id, path_kind="TEN_DLC", **overrides):
    """Create a DRAFT campaign."""
    response = client.create_campaign(
        account_id,
        f.campaign_payload(brand_id, path_kind=path_kind, **overrides),
        headers=CAMPAIGN_MANAGER,
    )
    return get_success_data(response)


def submit_campaign(client, account_id, campaign_id, expected_campaign_version=None):
    payload = {}
    if expected_campaign_version is not None:
        payload["expected_campaign_version"] = expected_campaign_version
    response = client.submit_campaign(
        account_id, campaign_id, payload=payload, headers=CAMPAIGN_MANAGER
    )
    return get_success_data(response)


def approve_campaign(client, account_id, campaign_id):
    response = client.approve_campaign(account_id, campaign_id, headers=CARRIER_REVIEWER)
    return get_success_data(response)


def reject_campaign(client, account_id, campaign_id, reason_code):
    response = client.reject_campaign(
        account_id,
        campaign_id,
        {"rejection_reason_code": reason_code},
        headers=CARRIER_REVIEWER,
    )
    return get_success_data(response)


def create_approved_campaign(client, account_id, brand_id, path_kind="TEN_DLC", **overrides):
    """Create + submit + approve a campaign. Returns the APPROVED campaign."""
    campaign = create_campaign(
        client, account_id, brand_id, path_kind=path_kind, **overrides
    )
    submit_campaign(client, account_id, campaign["id"])
    return approve_campaign(client, account_id, campaign["id"])


def campaign_version(client, account_id, campaign_id):
    """Read the campaign and return its current version."""
    data = get_success_data(
        client.get_campaign(account_id, campaign_id, headers=CAMPAIGN_MANAGER)
    )
    return data["version"]


def create_active_number(client, account_id, number_type="TEN_DLC", **overrides):
    """Provision a new-purchase number and activate it."""
    number = get_success_data(
        client.create_number(
            account_id,
            f.number_payload(number_type=number_type, **overrides),
            headers=PROVISIONER,
        )
    )
    return get_success_data(
        client.activate_number(account_id, number["id"], headers=PROVISIONER)
    )


def attach_number(client, account_id, number_id, campaign_id):
    """Attach a number to a campaign, reading the current OCC version first."""
    version = campaign_version(client, account_id, campaign_id)
    return get_success_data(
        client.attach_number(
            account_id,
            number_id,
            {
                "campaign_id": campaign_id,
                "expected_campaign_version": version,
            },
            headers=PROVISIONER,
        )
    )


def create_consent(client, account_id, brand_id, phone_number, **overrides):
    response = client.create_consent_record(
        account_id,
        f.consent_payload(brand_id, phone_number, **overrides),
        headers=BRAND_MANAGER,
    )
    return get_success_data(response)


def send_message(client, account_id, campaign_id, number_id, to_number, **overrides):
    response = client.send_message(
        account_id,
        f.message_payload(campaign_id, number_id, to_number, **overrides),
        headers=CAMPAIGN_MANAGER,
    )
    return get_success_data(response)


def run_ops(client, account_id):
    response = client.run_ops(account_id, headers=ADMIN)
    return get_success_data(response)


# ─── Composite stacks ─────────────────────────────────────────────────────


def approved_tendlc_stack(
    client,
    account_overrides=None,
    brand_profile="high95",
    number_phone="+15551234567",
    consent_numbers=(),
):
    """APPROVED TEN_DLC campaign with one attached ACTIVE number.

    Returns a dict with the account, brand, campaign (post-attach state),
    and number payloads, plus the ACTIVE consent records requested.
    """
    set_clock(client)
    account = create_account(client, **(account_overrides or {}))
    account_id = account["id"]
    brand = create_verified_brand(client, account_id, profile=brand_profile)
    campaign = create_approved_campaign(client, account_id, brand["id"])
    number = create_active_number(client, account_id, phone_number=number_phone)
    attach_number(client, account_id, number["id"], campaign["id"])
    consents = [
        create_consent(client, account_id, brand["id"], phone)
        for phone in consent_numbers
    ]
    campaign = get_success_data(
        client.get_campaign(account_id, campaign["id"], headers=CAMPAIGN_MANAGER)
    )
    return {
        "account": account,
        "brand": brand,
        "campaign": campaign,
        "number": number,
        "consents": consents,
    }


def queued_message_stack(client, to_number="+15550000900", **kwargs):
    """Approved stack plus one QUEUED message to ``to_number``."""
    stack = approved_tendlc_stack(client, consent_numbers=(to_number,), **kwargs)
    message = send_message(
        client,
        stack["account"]["id"],
        stack["campaign"]["id"],
        stack["number"]["id"],
        to_number,
    )
    stack["message"] = message
    return stack


def sent_message_stack(client, to_number="+15550000900", **kwargs):
    """Approved stack plus a message drained to SENT."""
    stack = queued_message_stack(client, to_number=to_number, **kwargs)
    run_ops(client, stack["account"]["id"])
    return stack


def failed_message_stack(client, to_number="+15550000900", error_code="E30034", **kwargs):
    """Approved stack plus a SENT message marked FAILED by the carrier."""
    stack = sent_message_stack(client, to_number=to_number, **kwargs)
    stack["message"] = get_success_data(
        client.report_delivery_outcome(
            stack["account"]["id"],
            stack["message"]["id"],
            {"outcome": "FAILED", "error_code": error_code},
            headers=SYSTEM_DRIVER,
        )
    )
    return stack


def charges(client, account_id, **params):
    """List charges for an account, returning the data list."""
    from prd_bench_local_runner.testing import validate_paginated

    response = client.list_charges(account_id, headers=ADMIN, params=params or None)
    data, _meta = validate_paginated(response)
    return data
