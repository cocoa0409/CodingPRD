"""Payload factories: one per creatable resource, input fields only.

A factory never sets a system-managed field (status, balances, versions,
timestamps); the server owns those.  Every factory accepts ``**overrides``
so a test can control exactly the knobs its claim cares about.
"""

import itertools

from .constants import (
    BUSINESS_RATE_FLOOR_CENTS,
    ADVERTISING_RATE_FLOOR_CENTS,
    PERSONAL_RATE_MIN_CENTS,
    CLOCK_INITIAL_INSTANT,
)

_counter = itertools.count(1)


def _unique(tag):
    return "{0}-{1}".format(tag, next(_counter))


# ─── Talents ──────────────────────────────────────────────────────────────


def talent_payload(**overrides):
    n = next(_counter)
    payload = {
        "stage_name": "Stage Star {0}".format(n),
        "legal_name": "Stage Star {0} Legal".format(n),
        "email": "talent{0}@example.com".format(n),
        "identity_document_ref": "doc-ref-{0}".format(n),
    }
    payload.update(overrides)
    return payload


def rates_payload(
    personal_rate_cents=10000,
    business_rate_cents=40000,
    advertising_rate_cents=80000,
    turnaround_hours=72,
    expected_talent_version=None,
    **overrides
):
    payload = {
        "personal_rate_cents": personal_rate_cents,
        "business_rate_cents": business_rate_cents,
        "advertising_rate_cents": advertising_rate_cents,
        "turnaround_hours": turnaround_hours,
    }
    if expected_talent_version is not None:
        payload["expected_talent_version"] = expected_talent_version
    payload.update(overrides)
    return payload


def tax_document_payload(doc_type="W9", tax_id_last4=None, **overrides):
    if tax_id_last4 is None:
        tax_id_last4 = "{0:04d}".format(next(_counter) % 10000)
    payload = {"doc_type": doc_type, "tax_id_last4": tax_id_last4}
    payload.update(overrides)
    return payload


# ─── Buyers ───────────────────────────────────────────────────────────────


def buyer_payload(is_business_account=False, **overrides):
    n = next(_counter)
    payload = {
        "email": "buyer{0}@example.com".format(n),
        "display_name": "Buyer {0}".format(n),
        "is_business_account": is_business_account,
    }
    payload.update(overrides)
    return payload


# ─── Orders ───────────────────────────────────────────────────────────────


def order_payload(talent_id, buyer_id, use_type="PERSONAL", **overrides):
    n = next(_counter)
    payload = {
        "talent_id": talent_id,
        "buyer_id": buyer_id,
        "use_type": use_type,
        "occasion": "occasion {0}".format(n),
        "script_instructions": "please record a friendly message {0}".format(n),
        "recipient_name": "Recipient {0}".format(n),
    }
    payload.update(overrides)
    return payload


def flagged_order_payload(talent_id, buyer_id, use_type="PERSONAL", **overrides):
    overrides.setdefault(
        "script_instructions",
        "FLAGGED_POLICY_VIOLATION this request trips the screening rule",
    )
    return order_payload(talent_id, buyer_id, use_type=use_type, **overrides)


# ─── Videos ───────────────────────────────────────────────────────────────


def video_payload(content_url=None, duration_seconds=30, **overrides):
    if content_url is None:
        content_url = "https://cdn.example.com/{0}.mp4".format(_unique("video"))
    payload = {"content_url": content_url, "duration_seconds": duration_seconds}
    payload.update(overrides)
    return payload


# ─── License grants ───────────────────────────────────────────────────────


def license_grant_payload(
    license_type="BUSINESS",
    territory="DOMESTIC",
    channels=None,
    starts_at="2026-09-01T00:00:00Z",
    ends_at="2026-10-01T00:00:00Z",
    **overrides
):
    if channels is None:
        channels = ["SOCIAL"]
    payload = {
        "license_type": license_type,
        "territory": territory,
        "channels": list(channels),
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


# ─── Sweeps ───────────────────────────────────────────────────────────────


def payout_sweep_payload(
    period_start=CLOCK_INITIAL_INSTANT,
    period_end="2026-09-08T00:00:00Z",
    **overrides
):
    payload = {"period_start": period_start, "period_end": period_end}
    payload.update(overrides)
    return payload
