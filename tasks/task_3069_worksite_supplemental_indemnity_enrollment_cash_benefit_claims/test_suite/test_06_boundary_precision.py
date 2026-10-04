"""Boundary precision: the exact window-end instant for lock, and zero remaining
occurrences for auto-deny."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    make_carrier_admin_headers,
    make_claims_adjuster_headers,
    make_counselor_headers,
)


def _open_campaign_ending_0915(client):
    base = fixtures.setup_open_campaign(
        client,
        campaign_overrides={
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-15T00:00:00Z",
        },
    )
    return base


def test_lock_one_second_before_window_end_is_rejected(client):
    """Locking before the window has run its course fails with ERR_WINDOW_NOT_CLOSED.

    "When the window has run its course, the counselor locks it (`OPEN` →
    `LOCKED`), which requires the current clock time to be at or after
    `window_end` — locking early fails with `ERR_WINDOW_NOT_CLOSED`."

    Design: Difficulty/boundary_precision_check/campaign_lock_at_exact_window_end_succeeds
    """
    base = _open_campaign_ending_0915(client)
    fixtures.set_clock(client, "2026-09-14T23:59:59Z")

    response = client.lock_enrollment_campaign(
        base.campaign["id"], make_counselor_headers(base.counselor["id"])
    )

    validate_error(response, api_errors.ERR_WINDOW_NOT_CLOSED, 422)
    campaign = validate_success(
        client.get_enrollment_campaign(base.campaign["id"],
                                       make_carrier_admin_headers()),
        200,
    )
    assert campaign["status"] == "OPEN"


def test_lock_at_exactly_window_end_succeeds(client):
    """The lock boundary is inclusive: at window_end exactly, the lock goes through.

    "When the window has run its course, the counselor locks it (`OPEN` →
    `LOCKED`), which requires the current clock time to be at or after
    `window_end` — locking early fails with `ERR_WINDOW_NOT_CLOSED`."

    Design: Difficulty/boundary_precision_check/campaign_lock_at_exact_window_end_succeeds
    """
    base = _open_campaign_ending_0915(client)
    fixtures.set_clock(client, "2026-09-14T23:59:59Z")
    validate_error(
        client.lock_enrollment_campaign(
            base.campaign["id"], make_counselor_headers(base.counselor["id"])
        ),
        api_errors.ERR_WINDOW_NOT_CLOSED,
        422,
    )

    fixtures.set_clock(client, "2026-09-15T00:00:00Z")
    locked = validate_success(
        client.lock_enrollment_campaign(
            base.campaign["id"], make_counselor_headers(base.counselor["id"])
        ),
        200,
    )
    assert locked["status"] == "LOCKED"


def _cap_consumed_policy(client):
    """A policy whose single yearly occurrence for LACERATION is already paid, plus
    a second documented claim under review."""
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="LACERATION",
                benefit_amount_cents=5000,
                max_occurrences_per_year=1,
                lifetime_max_cents=500000,
            )
        ],
    )
    first = fixtures.submit_claim(
        client, base.policy["id"], "LACERATION",
        service_date="2026-09-02T00:00:00Z", diagnosis_code="S61.401A",
        claimed_occurrences=1,
    )
    fixtures.pay_claim_full_cycle(client, first["id"])

    second = fixtures.submit_claim(
        client, base.policy["id"], "LACERATION",
        service_date="2026-09-16T00:00:00Z", diagnosis_code="S61.401A",
        claimed_occurrences=1,
    )
    fixtures.review_claim(client, second["id"])
    document = fixtures.attach_document(client, second["id"], doc_type="DIAGNOSIS_PROOF")
    fixtures.accept_document(client, document["id"])
    return base, second


def test_zero_remaining_occurrences_auto_denies_with_cap_exhausted(client):
    """A fully consumed yearly cap turns an APPROVE decision into an auto-denial.

    "Fourth, the fiscal caps: if the prior paid occurrences of this event code in
    the service date's calendar year already equal or exceed the benefit item's
    `max_occurrences_per_year` — zero remaining occurrences — or if the policy's
    `lifetime_paid_cents` already equals or exceeds the item's
    `lifetime_max_cents`, the claim is auto-denied with `denial_reason`
    `CAP_EXHAUSTED` (surfaced as `ERR_CAP_EXHAUSTED`)."

    Design: Difficulty/boundary_precision_check/claim_with_zero_remaining_occurrences_auto_denied
    """
    base, claim = _cap_consumed_policy(client)

    response = client.adjudicate_claim(
        claim["id"], {"decision": "APPROVE"}, make_claims_adjuster_headers()
    )

    validate_error(response, api_errors.ERR_CAP_EXHAUSTED, 422)
    reloaded = fixtures.read_claim(client, claim["id"])
    assert reloaded["status"] == "DENIED"
    assert reloaded["denial_reason"] == "CAP_EXHAUSTED"


def test_an_auto_denied_claim_posts_nothing_to_the_ledger(client):
    """The cap auto-deny is not a zero-cent approval; the ledger is untouched.

    "Fourth, the fiscal caps: if the prior paid occurrences of this event code in
    the service date's calendar year already equal or exceed the benefit item's
    `max_occurrences_per_year` — zero remaining occurrences — or if the policy's
    `lifetime_paid_cents` already equals or exceeds the item's
    `lifetime_max_cents`, the claim is auto-denied with `denial_reason`
    `CAP_EXHAUSTED` (surfaced as `ERR_CAP_EXHAUSTED`)."

    Design: Difficulty/boundary_precision_check/claim_with_zero_remaining_occurrences_auto_denied
    """
    base, claim = _cap_consumed_policy(client)

    client.adjudicate_claim(
        claim["id"], {"decision": "APPROVE"}, make_claims_adjuster_headers()
    )

    policy = fixtures.read_policy(client, base.policy["id"])
    assert policy["lifetime_paid_cents"] == 5000, (
        "only the first claim's 5000 stands; got %r" % policy.get("lifetime_paid_cents")
    )
    assert policy["paid_occurrences_by_year"]["2026"]["LACERATION"] == 1
